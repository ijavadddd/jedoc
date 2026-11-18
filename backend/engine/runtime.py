"""One LangGraph node execution: skill sync, persistent Cursor session, artifacts, routing."""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from langchain_core.messages import HumanMessage

from backend.config import bundled_skills_dir, default_model_override, resolved_execution_mode
from backend.engine.artifacts import extract_files, extract_verdict, write_workspace_files
from backend.engine.qa_harness import run_qa_harness
from backend.engine.templates import OUTPUT_CONTRACT
from backend.engine.workspace import diff_stat, enforce_scope, file_delta, file_stats, git_snapshot, relative_path
from backend.events import EventBus
from backend.marketplace.manager import SkillManager
from backend.providers.cursor_cli import CursorCLIChatModel, create_chat
from backend.storage.session_store import FeatureSessionStore

WRITE_ROLES = {"tdd", "implementer", "custom"}
MODEL_ROLES = {"architect", "tdd", "implementer", "reviewer", "qa_auditor", "custom"}


def make_executor(node_id: str, store: FeatureSessionStore, skills: SkillManager, bus: EventBus):
    async def execute(state: dict[str, Any]) -> dict[str, Any]:
        flow = store.get_flow(state["flow_id"])
        if flow is None:
            raise RuntimeError(f"Flow {state['flow_id']} disappeared")
        node = next((item for item in flow["nodes"] if item["id"] == node_id), None)
        if node is None:
            raise RuntimeError(f"Node {node_id} is no longer in the flow")
        feature_id = state["feature_id"]
        workspace = Path(state["workspace"])
        role = node.get("role_type") or "custom"
        started = time.time()
        if node.get("enabled", True) is False:
            await _status(bus, feature_id, node, "DISABLED", "", "Disabled — skipped", started)
            return {"last_node": node_id, "verdict": "PASS", "route": "on_pass"}
        await _status(bus, feature_id, node, "RUNNING", "", "Preparing workspace skills", started)

        if role != "terminal":
            skills.sync(str(workspace), list(node.get("enabled_skills") or []))
        stats_before = file_stats(workspace) if role in MODEL_ROLES else {}

        if role == "gate":
            return await _gate(state, flow, node, store, bus, started)
        if role == "terminal":
            await _status(bus, feature_id, node, "PASSED", "", "Feature passed the pipeline", started)
            return {"last_node": node_id, "verdict": "PASS", "route": "on_pass"}

        if "graphify" in (node.get("enabled_skills") or []) and role == "architect":
            await _status(bus, feature_id, node, "RUNNING", "", "Mapping the repository with graphify", started)
            _run_graphify(workspace)

        chat_id = ""
        if role in MODEL_ROLES:
            chat_id = await _ensure_chat(
                store,
                feature_id,
                node_id,
                str(workspace),
                store.provider_credentials(node.get("provider") or "cursor"),
            )
        await _status(bus, feature_id, node, "RUNNING", chat_id, _opening_action(node), started)

        qa_report = dict(state.get("qa_report") or {})
        if role == "qa_auditor":
            behavior = dict(node.get("behavior_data") or {})
            behavior["timeout_s"] = node.get("timeout_s") or 900
            qa_report = await run_qa_harness(
                workspace,
                behavior,
                lambda event: bus.publish(feature_id, event),
                node_id=node_id,
            )
            store.save_artifact(feature_id, "QA_HARNESS.json", json.dumps(qa_report, indent=2))

        before = git_snapshot(workspace)
        prompt = _prompt(state, flow, node, workspace, qa_report, chat_id, store)
        store.append_turn(feature_id, node_id, chat_id, "user", prompt)
        chat = {"id": chat_id}
        live_files: dict[str, dict[str, Any]] = {}

        async def sink(event: dict[str, Any]) -> None:
            await bus.publish(feature_id, event)
            if event.get("type") != "stream":
                return
            kind = event.get("kind")
            if kind == "session":
                text = event.get("text") if isinstance(event.get("text"), str) else ""
                if text and text != chat["id"]:
                    store.set_agent_chat_id(feature_id, node_id, text)
                    chat["id"] = text
                return
            if kind not in {"tool_call", "shell", "mcp"}:
                return
            if kind == "tool_call" and event.get("subtype") == "completed":
                noted = _note_file_edit(workspace, live_files, event)
                if noted is not None:
                    await bus.publish(
                        feature_id,
                        {"type": "file_changes", "node_id": node_id, "chat_id": chat["id"], "files": noted},
                    )
            await _status(
                bus,
                feature_id,
                node,
                "RUNNING",
                chat["id"],
                (event.get("text") or event.get("detail") or "Tool call")[:180],
                started,
            )

        model_name = default_model_override() or node.get("model") or ""
        cli_env = store.provider_credentials(node.get("provider") or "cursor")
        model = CursorCLIChatModel(
            model_name=model_name,
            mode=node.get("cursor_mode") or "agent",
            workspace=str(workspace),
            chat_id=chat["id"],
            feature_id=feature_id,
            agent_id=node_id,
            timeout_s=int(node.get("timeout_s") or 900),
            force=role in WRITE_ROLES,
            sink=sink,
            cli_env=cli_env,
        )
        result = await model.ainvoke([HumanMessage(content=prompt)])
        text = result.content if isinstance(result.content, str) else json.dumps(result.content)
        if model.chat_id and model.chat_id != chat["id"]:
            store.set_agent_chat_id(feature_id, node_id, model.chat_id)
            chat["id"] = model.chat_id
        store.append_turn(feature_id, node_id, chat["id"], "assistant", text)

        artifacts = dict(state.get("artifacts") or {})
        written = write_workspace_files(workspace, extract_files(text))
        for relative in written:
            content = (workspace / relative).read_text(encoding="utf-8")
            artifacts[relative] = content
            store.save_artifact(feature_id, relative, content)
            await bus.publish(
                feature_id,
                {"type": "artifact", "node_id": node_id, "name": relative, "content": content[:20000]},
            )

        illegal = enforce_scope(workspace, role, before) if role in {"tdd", "implementer"} else []
        if illegal:
            note = "Reverted out-of-scope writes:\n" + "\n".join(f"- {item}" for item in illegal) + "\n"
            artifacts["SCOPE_VIOLATIONS.md"] = note
            store.save_artifact(feature_id, "SCOPE_VIOLATIONS.md", note)

        if role == "implementer":
            pytest_output = _run_pytest(workspace)
            if pytest_output:
                artifacts["PYTEST.txt"] = pytest_output
                store.save_artifact(feature_id, "PYTEST.txt", pytest_output)
                await bus.publish(
                    feature_id,
                    {"type": "stream", "kind": "shell", "node_id": node_id, "text": pytest_output[-4000:], "name": "pytest"},
                )

        verdict = extract_verdict(text)
        if verdict is None:
            verdict = "FAIL" if role in {"reviewer", "qa_auditor"} else "PASS"
        if role == "qa_auditor" and any(item.get("severity") == "high" for item in qa_report.get("anomalies") or []):
            if verdict == "PASS":
                verdict = "FAIL"
                text += "\nVERDICT: FAIL\n(orchestrator override: high-severity data anomaly)\n"

        route, retries, error = _route(flow, node, verdict, state)
        status = "PASSED" if route == "on_pass" else "FAILED"
        if route == "circuit_open":
            status = "FAILED"
        elif route in {"on_fail", "on_scale_issue"}:
            status = "FAILED_RETRYING"
        changes = file_delta(stats_before, file_stats(workspace))
        if not changes and live_files:
            changes = list(live_files.values())
        stored = store.get_active_session(feature_id, node_id) or {}
        merged = _merge_files(list(stored.get("files") or []), changes)
        store.set_session_files(feature_id, node_id, merged)
        await bus.publish(
            feature_id,
            {"type": "file_changes", "node_id": node_id, "chat_id": chat["id"], "files": merged},
        )
        await _status(bus, feature_id, node, status, chat["id"], f"VERDICT: {verdict}", started)
        return {
            "artifacts": artifacts,
            "retry_counts": retries,
            "route": route,
            "verdict": verdict,
            "last_node": node_id,
            "last_output": text[-20000:],
            "error": error,
            "qa_report": qa_report,
        }

    return execute


async def _gate(state, flow, node, store, bus, started) -> dict[str, Any]:
    feature_id = state["feature_id"]
    names = sorted((state.get("artifacts") or {}).keys())
    lines = [
        "# Pre-implementation review",
        "",
        "The architect and TDD nodes have finished. Approve to enter the implementer.",
        "Skill files for this gate are synced into the workspace. Edits and toggles apply before resume.",
        "",
        "## Artifacts",
        *(f"- {name}" for name in names),
        "",
        "## Enabled on the next editing agent",
    ]
    target = _target(flow, node["id"], "always") or "implementer"
    target_node = next((item for item in flow["nodes"] if item["id"] == target), None)
    if target_node:
        lines.extend(f"- {skill}" for skill in target_node.get("enabled_skills") or [])
    packet = "\n".join(lines) + "\n"
    artifacts = dict(state.get("artifacts") or {})
    artifacts["PRE_IMPL_REVIEW.md"] = packet
    store.save_artifact(feature_id, "PRE_IMPL_REVIEW.md", packet)
    workspace = Path(state["workspace"])
    write_workspace_files(workspace, {"PRE_IMPL_REVIEW.md": packet})
    await bus.publish(feature_id, {"type": "artifact", "node_id": node["id"], "name": "PRE_IMPL_REVIEW.md", "content": packet})
    await _status(bus, feature_id, node, "PASSED", "", "Review packet ready — approval required before implementation", started)
    return {
        "artifacts": artifacts,
        "approval_packet": packet,
        "last_node": node["id"],
        "verdict": "PASS",
        "route": "on_pass",
        "error": "",
    }


def _route(flow: dict, node: dict, verdict: str, state: dict) -> tuple[str, dict, str]:
    role = node.get("role_type")
    if role == "reviewer":
        route = "on_pass" if verdict == "PASS" else "on_fail"
    elif role == "qa_auditor":
        route = {"PASS": "on_pass", "FAIL": "on_fail", "SCALE_ISSUE": "on_scale_issue"}.get(verdict, "on_fail")
    else:
        route = "on_pass"
    retries = dict(state.get("retry_counts") or {})
    error = ""
    if route in {"on_fail", "on_scale_issue"}:
        target = _target(flow, node["id"], route)
        if target:
            retries[target] = int(retries.get(target, 0)) + 1
            spec = next(item for item in flow["nodes"] if item["id"] == target)
            maximum = int(spec.get("max_retries", 3))
            if retries[target] > maximum:
                route = "circuit_open"
                error = f"Circuit breaker opened for {target} after {maximum} retries"
    return route, retries, error


def _target(flow: dict, source: str, condition: str) -> str | None:
    for edge in flow.get("edges") or []:
        if edge["source"] == source and (edge.get("condition") or "always") == condition:
            return edge["target"]
    return None


def _prompt(state, flow, node, workspace: Path, qa_report: dict, chat_id: str, store: FeatureSessionStore) -> str:
    retries = state.get("retry_counts") or {}
    counts = " ".join(f"{item['id']}={int(retries.get(item['id'], 0))}" for item in flow["nodes"])
    prior = [
        turn
        for turn in store.list_turns(state["feature_id"], node["id"])
        if turn["chat_id"] == chat_id and turn["role"] == "user"
    ]
    sections = []
    if prior:
        sections.append(
            f"You are still {node['display_name']} in the same Cursor chat. "
            "Do not discard earlier decisions in this session. Address the new evidence below."
        )
    else:
        sections.append(f"You are {node['display_name']} ({node.get('role_type')}) inside Jedoc.")
        sections.append(node.get("system_prompt") or "")
        sections.append("Behavior data:\n" + json.dumps(node.get("behavior_data") or {}, indent=2))
        skills = ", ".join(node.get("enabled_skills") or []) or "(none)"
        sections.append(
            "Enabled skills are synced under .cursor/ in this workspace: "
            f"{skills}. Follow them. System context is injected only on this first turn; "
            "later turns resume this chat id."
        )
    sections.append(OUTPUT_CONTRACT)
    sections.append("Feature PRD:\n" + (state.get("prd") or "")[:20000])
    sections.append("Retry counts: " + counts)
    if node.get("role_type") == "architect":
        report = workspace / "graphify-out" / "GRAPH_REPORT.md"
        if report.exists():
            sections.append("Graphify report:\n" + report.read_text(encoding="utf-8")[:20000])
    if node.get("role_type") in {"reviewer", "qa_auditor", "implementer"}:
        sections.append("Git diff stat:\n" + diff_stat(workspace))
    if qa_report:
        sections.append("QA harness report:\n" + json.dumps(qa_report, indent=2)[:20000])
    approval = workspace / ".jedoc" / "approval.md"
    if approval.exists():
        sections.append("Human approval note:\n" + approval.read_text(encoding="utf-8")[:8000])
    artifacts = state.get("artifacts") or {}
    if artifacts:
        chunks = []
        for name, content in artifacts.items():
            chunks.append(f"##### {name}\n{content[:8000]}")
        sections.append("Artifacts so far:\n" + "\n\n".join(chunks)[:50000])
    if state.get("last_output") and prior:
        sections.append("Previous agent output (tail):\n" + state["last_output"][-8000:])
    return "\n\n".join(section for section in sections if section)


async def _ensure_chat(
    store: FeatureSessionStore,
    feature_id: str,
    agent_id: str,
    workspace: str,
    cli_env: dict[str, str] | None = None,
) -> str:
    existing = store.get_active_session(feature_id, agent_id)
    live = resolved_execution_mode() != "simulate"
    if existing and not (live and str(existing["chat_id"]).startswith("sim_")):
        return existing["chat_id"]
    created = await create_chat(workspace, execution_mode="live" if live else None, cli_env=cli_env)
    if existing:
        store.set_agent_chat_id(feature_id, agent_id, created)
        return created
    row = store.get_or_create_session(feature_id, agent_id, lambda: created)
    return row["chat_id"]


def _merge_files(existing: list[dict[str, Any]], changes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged = {str(item.get("path")): {"path": item.get("path"), "added": int(item.get("added") or 0), "removed": int(item.get("removed") or 0)} for item in existing if item.get("path")}
    for item in changes:
        path = str(item.get("path") or "")
        if not path:
            continue
        current = merged.get(path, {"path": path, "added": 0, "removed": 0})
        current["added"] += int(item.get("added") or 0)
        current["removed"] += int(item.get("removed") or 0)
        merged[path] = current
    return [merged[path] for path in sorted(merged)]


def _note_file_edit(workspace: Path, files: dict[str, dict[str, Any]], event: dict[str, Any]) -> list[dict[str, Any]] | None:
    raw = event.get("path")
    if not isinstance(raw, str) or not raw:
        return None
    path = relative_path(workspace, raw)
    current = files.setdefault(path, {"path": path, "added": 0, "removed": 0})
    current["added"] += int(event.get("added") or 0)
    current["removed"] += int(event.get("removed") or 0)
    return list(files.values())


async def _status(bus, feature_id, node, status, chat_id, action, started) -> None:
    await bus.publish(
        feature_id,
        {
            "type": "node_status",
            "node_id": node["id"],
            "status": status,
            "chat_id": chat_id,
            "action": action,
            "started_at": started,
            "display_name": node.get("display_name") or node["id"],
            "enabled_skills": node.get("enabled_skills") or [],
            "cursor_mode": node.get("cursor_mode") or "",
        },
    )


def _opening_action(node: dict) -> str:
    role = node.get("role_type")
    if role == "qa_auditor":
        seconds = int((node.get("behavior_data") or {}).get("min_duration_seconds") or 600)
        return f"Starting sustained QA window [{_clock(0)} / {_clock(seconds)}]"
    if role == "architect":
        return "Reading the PRD and repository topology"
    if role == "tdd":
        return "Writing failing tests under tests/"
    if role == "implementer":
        return "Implementing against the frozen tests"
    if role == "reviewer":
        return "Auditing the diff against ARCHITECTURE_SPEC.md"
    return "Running agent"


def _clock(seconds: int) -> str:
    return f"{seconds // 60:02d}:{seconds % 60:02d}"


def _run_graphify(workspace: Path) -> None:
    synced = workspace / ".cursor" / "skills" / "graphify" / "graphify_cli.py"
    script = synced if synced.exists() else bundled_skills_dir() / "graphify" / "graphify_cli.py"
    if not script.exists():
        return
    subprocess.run(
        [sys.executable, str(script), str(workspace)],
        cwd=workspace,
        check=False,
        capture_output=True,
        text=True,
        timeout=60,
    )


def _run_pytest(workspace: Path) -> str:
    if not any((workspace / "tests").glob("test_*.py")):
        return ""
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pytest", "-q", "tests"],
            cwd=workspace,
            capture_output=True,
            text=True,
            timeout=180,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return f"pytest could not be completed: {exc}"
    return ((result.stdout or "") + "\n" + (result.stderr or "")).strip()[-8000:]
