"""One LangGraph node execution: skill sync, persistent Cursor session, artifacts, routing."""

from __future__ import annotations

import json
import os
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
from backend.providers.cursor_cli import CursorCLIChatModel, CursorCLIError, create_chat, is_cli_timeout
from backend.storage.session_store import FeatureSessionStore

WRITE_ROLES = {"tdd", "implementer", "custom"}
MODEL_ROLES = {"architect", "tdd", "implementer", "reviewer", "qa_auditor", "custom"}
# Idle budgets below these floors kill long Cursor turns that are still streaming tools.
ROLE_TIMEOUT_FLOOR_S = {
    "architect": 900,
    "tdd": 900,
    "implementer": 1800,
    "reviewer": 1800,
    "qa_auditor": 1800,
    "custom": 900,
}


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
            await _run_graphify(workspace, bus=bus, feature_id=feature_id, node=node, started=started)

        chat_id = ""
        if role in MODEL_ROLES:
            await _status(bus, feature_id, node, "RUNNING", "", "Opening Cursor chat…", started)
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

        last_action_at = {"t": 0.0}

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
            action = _live_action(event)
            if not action:
                return
            if kind == "tool_call" and event.get("subtype") == "completed":
                noted = _note_file_edit(workspace, live_files, event)
                if noted is not None:
                    await bus.publish(
                        feature_id,
                        {"type": "file_changes", "node_id": node_id, "chat_id": chat["id"], "files": noted},
                    )
            now = time.time()
            # Tool/shell/mcp always refresh the node; token streams are throttled so the canvas stays readable.
            if kind in {"tool_call", "shell", "mcp", "system", "thinking"} or now - last_action_at["t"] >= 0.35:
                last_action_at["t"] = now
                await _status(bus, feature_id, node, "RUNNING", chat["id"], action[:180], started)

        model_name = default_model_override() or node.get("model") or ""
        cli_env = store.provider_credentials(node.get("provider") or "cursor")
        await _status(bus, feature_id, node, "RUNNING", chat["id"], "Launching Cursor agent…", started)
        timeout_s = max(
            int(node.get("timeout_s") or 900),
            ROLE_TIMEOUT_FLOOR_S.get(role, 900),
        )
        model = CursorCLIChatModel(
            model_name=model_name,
            mode=node.get("cursor_mode") or "agent",
            workspace=str(workspace),
            chat_id=chat["id"],
            feature_id=feature_id,
            agent_id=node_id,
            timeout_s=timeout_s,
            force=role in WRITE_ROLES,
            sink=sink,
            cli_env=cli_env,
        )
        try:
            result = await model.ainvoke([HumanMessage(content=prompt)])
            text = result.content if isinstance(result.content, str) else json.dumps(result.content)
        except CursorCLIError as exc:
            # Idle/hard timeouts become a FAIL verdict so max_retries can recover instead of killing the feature.
            if not is_cli_timeout(exc):
                raise
            text = (
                f"Cursor agent timed out on `{node_id}`.\n{exc}\n\n"
                "VERDICT: FAIL\n"
            )
            await bus.publish(
                feature_id,
                {"type": "stream", "kind": "system", "level": "error", "node_id": node_id, "text": str(exc)},
            )
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
    if role in {"reviewer", "qa_auditor"}:
        route = {"PASS": "on_pass", "FAIL": "on_fail", "SCALE_ISSUE": "on_scale_issue"}.get(verdict, "on_fail")
    else:
        route = "on_pass"
    retries = dict(state.get("retry_counts") or {})
    error = ""
    if route in {"on_fail", "on_scale_issue"}:
        # Count failures on the rejecting node so a stuck review↔fix loop cannot run forever
        # when the implementer step is skipped or the checkpoint does not advance.
        source_id = node["id"]
        retries[source_id] = int(retries.get(source_id, 0)) + 1
        source_max = int(node.get("max_retries", 3))
        if retries[source_id] > source_max:
            # Prefer reopening PRD/architecture over killing the feature.
            escalated = _escalate_to_architect(flow, node, retries)
            if escalated is not None:
                return escalated
            route = "circuit_open"
            error = f"Circuit breaker opened for {source_id} after {source_max} retries"
            return route, retries, error
        target = _target(flow, node["id"], route)
        if target:
            retries[target] = int(retries.get(target, 0)) + 1
            spec = next(item for item in flow["nodes"] if item["id"] == target)
            maximum = int(spec.get("max_retries", 3))
            if retries[target] > maximum:
                escalated = _escalate_to_architect(flow, node, retries)
                if escalated is not None:
                    return escalated
                route = "circuit_open"
                error = f"Circuit breaker opened for {target} after {maximum} retries"
    return route, retries, error


def _escalate_to_architect(flow: dict, node: dict, retries: dict) -> tuple[str, dict, str] | None:
    """Send the pipeline back to PRD/architecture when implementer loops are exhausted."""
    architect = _target(flow, node["id"], "on_scale_issue")
    if not architect:
        architect = str(flow.get("entry") or "") or None
    if not architect:
        return None
    # Fresh implementer/reviewer budget after the architect revises the spec.
    retries[node["id"]] = 0
    retries[architect] = int(retries.get(architect, 0)) + 1
    spec = next((item for item in flow["nodes"] if item["id"] == architect), None)
    maximum = int((spec or {}).get("max_retries", 5))
    if retries[architect] > maximum:
        return (
            "circuit_open",
            retries,
            f"Circuit breaker opened for {architect} after {maximum} architecture escalations",
        )
    # Prefer the explicit scale edge when present so LangGraph routing stays valid.
    if _target(flow, node["id"], "on_scale_issue"):
        return "on_scale_issue", retries, ""
    # Fall back: treat as fail routed to entry by rewriting route via a synthetic pass — callers
    # need an edge; without on_scale_issue, circuit is safer.
    return None


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


def _live_action(event: dict[str, Any]) -> str:
    """Human-readable activity line for the canvas while the Cursor stream is live."""
    kind = str(event.get("kind") or "")
    text = str(event.get("text") or event.get("detail") or "").strip()
    name = str(event.get("name") or "").strip()
    if kind == "thinking":
        return f"Thinking… {text}" if text else "Thinking…"
    if kind == "assistant":
        return f"Writing… {text}" if text else "Writing…"
    if kind == "shell":
        return f"$ {text or name or 'shell'}"
    if kind == "mcp":
        return f"MCP {name or 'tool'}: {text}".strip(": ")
    if kind == "tool_call":
        return text or (f"{name}…" if name else "Tool call")
    if kind == "system":
        return text or "Agent update"
    if kind == "session":
        return f"Session {text[:18]}" if text else ""
    return text


async def _run_graphify(
    workspace: Path,
    *,
    bus: EventBus | None = None,
    feature_id: str = "",
    node: dict[str, Any] | None = None,
    started: float = 0.0,
) -> None:
    """Map the repo for the architect. Timeouts and tool failures must not abort the feature."""
    synced = workspace / ".cursor" / "skills" / "graphify" / "graphify_cli.py"
    script = synced if synced.exists() else bundled_skills_dir() / "graphify" / "graphify_cli.py"
    if not script.exists():
        return
    raw = os.environ.get("JEDOC_GRAPHIFY_TIMEOUT_S", "300").strip()
    try:
        timeout = max(30, int(raw or "300"))
    except ValueError:
        timeout = 300
    import asyncio

    try:
        process = await asyncio.create_subprocess_exec(
            sys.executable,
            str(script),
            str(workspace),
            cwd=workspace,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except OSError as exc:
        _write_graphify_fallback(workspace, f"Graphify could not run: {exc}")
        return

    deadline = time.time() + timeout
    while True:
        remaining = deadline - time.time()
        if remaining <= 0:
            process.kill()
            await process.wait()
            _write_graphify_fallback(
                workspace,
                f"Timed out after {timeout}s while mapping `{workspace.name}`. "
                "Proceed from the PRD and the visible repository layout.",
            )
            return
        try:
            await asyncio.wait_for(process.wait(), timeout=min(5.0, remaining))
            break
        except TimeoutError:
            if bus is not None and node is not None and feature_id:
                elapsed = int(time.time() - (started or time.time()))
                await _status(
                    bus,
                    feature_id,
                    node,
                    "RUNNING",
                    "",
                    f"Mapping repository… {_clock(elapsed)} (still scanning {workspace.name})",
                    started,
                )
            continue
    if process.returncode not in (0, None) and not (workspace / "graphify-out" / "GRAPH_REPORT.md").exists():
        stderr = ""
        if process.stderr is not None:
            stderr = (await process.stderr.read()).decode("utf-8", errors="replace")[:1500]
        _write_graphify_fallback(workspace, stderr.strip() or f"Graphify exited {process.returncode}")


def _write_graphify_fallback(workspace: Path, detail: str) -> None:
    out = workspace / "graphify-out"
    out.mkdir(parents=True, exist_ok=True)
    report = out / "GRAPH_REPORT.md"
    if report.exists():
        return
    report.write_text(f"# Graphify report\n\n{detail}\n", encoding="utf-8")


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
