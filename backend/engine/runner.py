"""Drive a compiled flow until it finishes, pauses for approval, or opens a circuit breaker."""

from __future__ import annotations

import asyncio
import time
import traceback
import uuid
from pathlib import Path
from typing import Any

from langgraph.checkpoint.memory import MemorySaver

from backend.engine.graph_builder import compile_flow, validate_flow
from backend.engine.templates import FLOW_ID, default_flow
from backend.events import EventBus
from backend.marketplace.manager import SkillManager
from backend.providers.cursor_cli import kill_feature_cli_processes
from backend.storage.session_store import FeatureSessionStore

try:
    from langgraph.errors import GraphBubbleUp, GraphInterrupt
except ImportError:  # pragma: no cover - older langgraph packages
    class GraphInterrupt(Exception):
        pass

    GraphBubbleUp = GraphInterrupt


_CHECKPOINT_TIMEOUT_S = 45.0
_FAILURE_ERROR_LIMIT = 48_000


def _format_run_failure(exc: BaseException) -> str:
    """Keep the actionable message intact; never chop the head off a long traceback."""
    message = str(exc).strip() or type(exc).__name__
    tb = "".join(traceback.format_exception(exc))
    body = f"{type(exc).__name__}: {message}"
    if tb.strip() and message not in tb:
        body = f"{body}\n\n{tb}"
    elif tb.strip():
        body = tb
    if len(body) <= _FAILURE_ERROR_LIMIT:
        return body
    keep = _FAILURE_ERROR_LIMIT - len(message) - 64
    return f"{type(exc).__name__}: {message}\n\n…traceback truncated…\n{tb[-max(keep, 0):]}"


def _circuit_tripped(values: dict[str, Any], feature: dict[str, Any]) -> bool:
    if (values.get("route") or "") == "circuit_open":
        return True
    blob = f"{values.get('error') or ''} {feature.get('error') or ''}".lower()
    return "circuit breaker" in blob


def _is_interrupt(exc: BaseException | None) -> bool:
    """True when LangGraph stopped for interrupt_before / human gate (including chained lock errors)."""
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if isinstance(current, GraphBubbleUp):
            return True
        if isinstance(current, BaseExceptionGroup):
            if any(_is_interrupt(item) for item in current.exceptions):
                return True
        text = f"{type(current).__name__}: {current}"
        if "GraphInterrupt" in text:
            return True
        current = current.__cause__ or current.__context__
    return False


class PipelineRunner:
    def __init__(
        self,
        store: FeatureSessionStore,
        skills: SkillManager,
        bus: EventBus,
        checkpointer=None,
    ) -> None:
        self.store = store
        self.skills = skills
        self.bus = bus
        self.checkpointer = checkpointer if checkpointer is not None else MemorySaver()
        self.tasks: dict[str, asyncio.Task] = {}
        self._guards: dict[str, asyncio.Lock] = {}
        self._pause_requested: set[str] = set()
        self._restart_requested: set[str] = set()
        self._skip_requested: set[str] = set()

    def startup(self) -> None:
        self.store.init()
        self._ensure_builtin_flow()
        self.skills.seed_states()
        self.recover_orphaned_runs()

    def _ensure_builtin_flow(self) -> None:
        """Seed or upgrade the built-in template (review→architect escalation, higher retry budgets)."""
        template = default_flow()
        existing = self.store.get_flow(FLOW_ID)
        if existing is None:
            self.store.save_flow(template, is_template=True)
            return
        by_id = {node["id"]: node for node in existing.get("nodes") or []}
        changed = False
        for node in template["nodes"]:
            current = by_id.get(node["id"])
            if current is None:
                continue
            for key in ("max_retries", "system_prompt"):
                if current.get(key) != node.get(key) and key == "max_retries":
                    if int(current.get("max_retries") or 0) < int(node.get("max_retries") or 0):
                        current["max_retries"] = node["max_retries"]
                        changed = True
                elif key == "system_prompt" and node["id"] in {"prd_scale_architect", "adversarial_reviewer"}:
                    if current.get("system_prompt") != node.get("system_prompt"):
                        current["system_prompt"] = node["system_prompt"]
                        changed = True
        edges = list(existing.get("edges") or [])
        edge_ids = {edge.get("id") for edge in edges}
        for edge in template["edges"]:
            if edge["id"] not in edge_ids:
                edges.append(edge)
                changed = True
            else:
                # Keep fail/scale targets aligned with the built-in escalation design.
                for item in edges:
                    if item.get("id") == edge["id"] and (
                        item.get("target") != edge["target"] or item.get("condition") != edge["condition"]
                    ):
                        item["target"] = edge["target"]
                        item["condition"] = edge["condition"]
                        item["source_handle"] = edge.get("source_handle", item.get("source_handle"))
                        item["target_handle"] = edge.get("target_handle", item.get("target_handle"))
                        changed = True
        if changed:
            existing["edges"] = edges
            existing["nodes"] = list(by_id.values())
            # Preserve node order from template when possible.
            ordered = []
            seen = set()
            for node in template["nodes"]:
                if node["id"] in by_id:
                    ordered.append(by_id[node["id"]])
                    seen.add(node["id"])
            for node_id, node in by_id.items():
                if node_id not in seen:
                    ordered.append(node)
            existing["nodes"] = ordered
            self.store.save_flow(existing, is_template=True)

    def recover_orphaned_runs(self) -> int:
        """Mark DB 'running' rows as failed when no live task exists (API restart / hung worker)."""
        recovered = 0
        for feature in self.store.list_features():
            if feature.get("status") != "running":
                continue
            if self.is_executing(feature["id"]):
                continue
            self.store.update_feature(
                feature["id"],
                status="failed",
                error="Recovered after API restart or a stuck run. Use Resume to continue from the last passed agent.",
            )
            recovered += 1
        return recovered

    def is_executing(self, feature_id: str) -> bool:
        task = self.tasks.get(feature_id)
        return bool(task and not task.done())

    def launch(self, feature_id: str, *, resume: bool, note: str = "") -> None:
        existing = self.tasks.get(feature_id)
        if existing and not existing.done():
            raise RuntimeError("This feature is already executing")
        self.tasks[feature_id] = asyncio.create_task(
            self.execute(feature_id, resume=resume, note=note),
            name=f"jedoc-{feature_id}",
        )

    async def execute(self, feature_id: str, *, resume: bool, note: str = "") -> None:
        lock = self._guards.setdefault(feature_id, asyncio.Lock())
        async with lock:
            try:
                await self._execute(feature_id, resume=resume, note=note)
            except asyncio.CancelledError:
                if feature_id in self._skip_requested:
                    self._skip_requested.discard(feature_id)
                    return
                if feature_id in self._restart_requested:
                    self._restart_requested.discard(feature_id)
                    return
                if feature_id in self._pause_requested:
                    self._pause_requested.discard(feature_id)
                    await self._publish_user_paused(feature_id)
                    return
                raise
            except Exception as exc:
                # Killing the CLI on pause/restart/skip can surface as a CursorCLIError before CancelledError.
                if feature_id in self._skip_requested:
                    self._skip_requested.discard(feature_id)
                    return
                if feature_id in self._restart_requested:
                    self._restart_requested.discard(feature_id)
                    return
                if feature_id in self._pause_requested:
                    self._pause_requested.discard(feature_id)
                    await self._publish_user_paused(feature_id)
                    return
                if await self._recover_interrupt(feature_id, exc):
                    return
                detail = _format_run_failure(exc)
                self.store.update_feature(feature_id, status="failed", error=detail)
                await self.bus.publish(
                    feature_id,
                    {"type": "feature_status", "status": "failed", "error": detail},
                )
            finally:
                self._pause_requested.discard(feature_id)
                self._restart_requested.discard(feature_id)
                self._skip_requested.discard(feature_id)

    async def pause(self, feature_id: str) -> dict[str, Any]:
        """Stop a live run and leave the checkpoint resumable."""
        feature = self.store.get_feature(feature_id)
        if feature is None:
            raise RuntimeError("Feature not found")
        if feature["status"] != "running":
            raise RuntimeError(f"Cannot pause a feature that is {feature['status']}")
        self._pause_requested.add(feature_id)
        killed = await kill_feature_cli_processes(feature_id)
        task = self.tasks.get(feature_id)
        if task and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            except Exception:
                pass
        if killed:
            await self.bus.publish(
                feature_id,
                {
                    "type": "stream",
                    "kind": "system",
                    "text": f"Stopped {killed} Cursor agent process(es).",
                },
            )
        current = self.store.get_feature(feature_id)
        if current and current["status"] == "running":
            await self._publish_user_paused(feature_id)
            current = self.store.get_feature(feature_id)
        return current or feature

    async def skip_agent(self, feature_id: str, agent_id: str | None = None) -> dict[str, Any]:
        """Stop the current/queued agent, mark it PASS (skipped), and continue the pipeline."""
        feature = self.store.get_feature(feature_id)
        if feature is None:
            raise RuntimeError("Feature not found")
        if feature["status"] in {"archived", "draft", "completed"}:
            raise RuntimeError(f"Cannot skip an agent while the feature is {feature['status']}")
        flow = self.store.get_flow(feature["flow_id"])
        if flow is None:
            raise RuntimeError("Flow not found")
        flow = validate_flow(flow)
        known = {node["id"]: node for node in flow["nodes"]}

        self._pause_requested.discard(feature_id)
        self._restart_requested.discard(feature_id)
        self._skip_requested.add(feature_id)
        await kill_feature_cli_processes(feature_id)
        task = self.tasks.get(feature_id)
        if task and not task.done():
            task.cancel()
            try:
                await asyncio.wait_for(task, timeout=8)
            except (asyncio.CancelledError, TimeoutError, Exception):
                pass
        self._skip_requested.discard(feature_id)

        graph = compile_flow(flow, self.store, self.skills, self.bus, self.checkpointer)
        config = {"configurable": {"thread_id": feature["thread_id"]}}
        try:
            snapshot = await self._checkpoint(graph.aget_state(config), label="skip-read")
        except Exception as exc:
            raise RuntimeError(f"Could not read pipeline checkpoint to skip: {exc}") from exc
        values = dict(snapshot.values or {})
        nxt = list(snapshot.next or [])

        target = agent_id or (nxt[0] if nxt else "")
        if not target:
            # Mid-run cancel often leaves next empty; fall back to the last announced running node.
            target = self._latest_running_node(feature_id, known) or str(values.get("last_node") or "")
        if not target or target not in known:
            raise RuntimeError("Nothing to skip — no current or queued agent.")
        if known[target].get("role_type") == "terminal":
            raise RuntimeError("Cannot skip the terminal feature-complete node.")

        display = str(known[target].get("display_name") or target)
        artifacts = dict(values.get("artifacts") or {})
        for item in self.store.list_artifacts(feature_id):
            artifacts.setdefault(item["name"], item["content"])
        healed = {
            "feature_id": feature["id"],
            "flow_id": feature["flow_id"],
            "workspace": feature["workspace_path"],
            "prd": feature.get("prd") or values.get("prd") or "",
            "artifacts": artifacts,
            "retry_counts": dict(values.get("retry_counts") or {}),
            "route": "on_pass",
            "verdict": "PASS",
            "last_node": target,
            "last_output": values.get("last_output") or "",
            "error": "",
            "qa_report": dict(values.get("qa_report") or {}),
            "approval_packet": values.get("approval_packet") or "",
        }
        await self._checkpoint(
            graph.aupdate_state(config, healed, as_node=target),
            label="skip-advance",
        )
        await self.bus.publish(
            feature_id,
            {
                "type": "node_status",
                "node_id": target,
                "status": "PASSED",
                "chat_id": "",
                "action": "Skipped by user",
                "display_name": display,
            },
        )
        await self.bus.publish(
            feature_id,
            {
                "type": "stream",
                "kind": "system",
                "text": f"Skipped `{display}`. Continuing with the next agent…",
            },
        )
        self.store.update_feature(feature_id, error="")
        self.launch(feature_id, resume=True, note=f"Skipped {display} and continued.")
        current = self.store.get_feature(feature_id)
        return current or feature

    def _latest_running_node(self, feature_id: str, known: dict[str, Any]) -> str | None:
        for row in reversed(self.store.list_audit(feature_id, limit=200)):
            payload = row.get("payload") or {}
            if (row.get("event_type") or payload.get("type")) != "node_status":
                continue
            if (payload.get("status") or "") != "RUNNING":
                continue
            node_id = str(payload.get("node_id") or row.get("node_id") or "")
            if node_id in known:
                return node_id
        return None

    async def restart_from_start(self, feature_id: str) -> dict[str, Any]:
        """Wipe the pipeline checkpoint and agent chats, then run again from the entry (PRD) agent."""
        feature = self.store.get_feature(feature_id)
        if feature is None:
            raise RuntimeError("Feature not found")
        if feature["status"] == "archived":
            raise RuntimeError("Feature is archived. Start a new feature for a fresh context.")
        flow = self.store.get_flow(feature["flow_id"])
        if flow is None:
            raise RuntimeError("Flow not found")
        flow = validate_flow(flow)
        entry_id = str(flow.get("entry") or (flow["nodes"][0]["id"] if flow["nodes"] else "entry"))
        entry = next((node for node in flow["nodes"] if node["id"] == entry_id), {"display_name": entry_id})
        entry_name = str(entry.get("display_name") or entry_id)

        self._pause_requested.discard(feature_id)
        self._restart_requested.add(feature_id)
        # Kill the live Cursor CLI first — task.cancel alone often leaves the agent process running.
        killed = await kill_feature_cli_processes(feature_id)
        task = self.tasks.get(feature_id)
        if task and not task.done():
            task.cancel()
            try:
                await asyncio.wait_for(task, timeout=8)
            except (asyncio.CancelledError, TimeoutError, Exception):
                pass
            if not task.done():
                task.cancel()
                try:
                    await asyncio.wait_for(task, timeout=2)
                except (asyncio.CancelledError, TimeoutError, Exception):
                    pass
        self._restart_requested.discard(feature_id)

        archived = self.store.archive_active_sessions(feature_id)
        self.store.update_feature(feature_id, thread_id=new_thread_id(), error="")
        await self.bus.publish(
            feature_id,
            {
                "type": "stream",
                "kind": "system",
                "text": (
                    f"Starting over from `{entry_name}`. "
                    f"Stopped {killed} agent process(es); archived {len(archived)} chat(s); checkpoint reset."
                ),
            },
        )
        self.launch(feature_id, resume=False)
        current = self.store.get_feature(feature_id)
        return current or feature

    async def mark_done(self, feature_id: str) -> list[dict[str, Any]]:
        self._pause_requested.discard(feature_id)
        self._restart_requested.discard(feature_id)
        await kill_feature_cli_processes(feature_id)
        task = self.tasks.get(feature_id)
        if task and not task.done():
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass
        archived = self.store.archive_feature_sessions(feature_id)
        await self.bus.publish(
            feature_id,
            {
                "type": "feature_status",
                "status": "archived",
                "detail": "Chat sessions archived. They were not deleted.",
            },
        )
        return archived

    async def _execute(self, feature_id: str, *, resume: bool, note: str) -> None:
        feature = self.store.get_feature(feature_id)
        if feature is None:
            raise RuntimeError("Feature not found")
        if feature["status"] == "archived":
            raise RuntimeError("Feature is archived. Start a new feature for a fresh context.")
        flow = self.store.get_flow(feature["flow_id"])
        if flow is None:
            raise RuntimeError("Flow not found")
        flow = validate_flow(flow)
        workspace = Path(feature["workspace_path"])
        if note:
            note_path = workspace / ".jedoc" / "approval.md"
            note_path.parent.mkdir(parents=True, exist_ok=True)
            note_path.write_text(note.rstrip() + "\n", encoding="utf-8")
            self.store.save_artifact(feature_id, "APPROVAL.md", note)
        self.store.update_feature(feature_id, status="running", error="")
        await self.bus.publish(feature_id, {"type": "feature_status", "status": "running"})
        graph = compile_flow(flow, self.store, self.skills, self.bus, self.checkpointer)
        config = {"configurable": {"thread_id": feature["thread_id"]}}
        payload: Any
        if resume:
            payload = None
            await self._prepare_resume(graph, config, feature, flow, note=note)
        else:
            payload = {
                "feature_id": feature["id"],
                "flow_id": feature["flow_id"],
                "workspace": str(workspace),
                "prd": feature["prd"],
                "artifacts": {item["name"]: item["content"] for item in self.store.list_artifacts(feature_id)},
                "retry_counts": {},
                "route": "on_pass",
                "verdict": "",
                "last_node": "",
                "last_output": "",
                "error": "",
                "qa_report": {},
                "approval_packet": "",
            }
        snapshot = await self._drive(
            graph,
            config,
            payload,
            flow,
            feature_id=feature_id,
            skip_gate_once=bool(note) or resume,
        )
        waiting = self._human_gate(flow, snapshot)
        if waiting:
            await self._publish_paused(feature_id, waiting)
            return
        values = dict(snapshot.values or {})
        if values.get("error") or values.get("route") == "circuit_open":
            error = values.get("error") or "Circuit breaker opened"
            self.store.update_feature(feature_id, status="failed", error=error)
            await self.bus.publish(feature_id, {"type": "feature_status", "status": "failed", "error": error})
            return
        self.store.update_feature(feature_id, status="completed", error="")
        await self.bus.publish(feature_id, {"type": "feature_status", "status": "completed"})

    async def _drive(
        self,
        graph,
        config,
        payload,
        flow,
        *,
        feature_id: str,
        skip_gate_once: bool = False,
    ):
        await self._announce_next(
            graph,
            config,
            flow,
            feature_id,
            action="Starting…" if payload is not None else "Resuming…",
        )
        await self._invoke(graph, config, payload)
        skipped = skip_gate_once
        last_invoked: str | None = None
        same_node_streak = 0
        while True:
            if feature_id in self._pause_requested:
                snapshot = await graph.aget_state(config)
                await self._publish_user_paused(feature_id, list(snapshot.next or []))
                return snapshot
            snapshot = await graph.aget_state(config)
            if not snapshot.next:
                return snapshot
            waiting = self._human_gate(flow, snapshot)
            if waiting and skipped:
                # Approval / resume should run the gated node once, not pause again immediately.
                skipped = False
                await self._announce_nodes(flow, feature_id, list(snapshot.next), "RUNNING", "Resuming approved agent…")
                last_invoked = list(snapshot.next)[0] if snapshot.next else None
                await self._invoke(graph, config, None)
                continue
            if waiting:
                return snapshot
            nxt = list(snapshot.next)
            # Guard: if LangGraph keeps re-queueing the same agent (seen in live review loops),
            # stop instead of burning the Cursor session for tens of minutes.
            head = nxt[0] if nxt else None
            if head and head == last_invoked:
                same_node_streak += 1
            else:
                same_node_streak = 0
            if same_node_streak >= 2:
                detail = (
                    f"Pipeline stuck re-invoking `{head}` without progressing. "
                    "Paused — Approve & Resume after fixing blockers, or Resume to retry."
                )
                self.store.update_feature(feature_id, status="paused", error=detail)
                await self.bus.publish(
                    feature_id,
                    {"type": "feature_status", "status": "paused", "error": detail, "waiting": nxt},
                )
                await self._announce_nodes(flow, feature_id, nxt, "WAITING_APPROVAL", detail)
                return snapshot
            await self._announce_nodes(flow, feature_id, nxt, "RUNNING", "Next agent…")
            last_invoked = head
            await self._invoke(graph, config, None)

    async def _invoke(self, graph, config, payload) -> None:
        try:
            if payload is None:
                await graph.ainvoke(None, config)
            else:
                await graph.ainvoke(payload, config)
        except GraphBubbleUp:
            return
        except Exception as exc:
            # Interrupt + checkpointer race often chains GraphInterrupt → database is locked.
            if _is_interrupt(exc):
                return
            name = type(exc).__name__
            if name == "EmptyInputError" or "Received no input" in str(exc):
                raise RuntimeError(
                    "Nothing to resume: the pipeline checkpoint is empty. "
                    "Use Restart from start, or Resume again after Jedoc rebuilds from the last passed agent."
                ) from exc
            raise

    async def _checkpoint(self, awaitable, *, label: str):
        """Bound LangGraph checkpoint I/O so a locked SQLite never leaves the UI spinning forever."""
        try:
            return await asyncio.wait_for(awaitable, timeout=_CHECKPOINT_TIMEOUT_S)
        except asyncio.TimeoutError as exc:
            raise RuntimeError(
                f"Checkpoint {label} timed out after {_CHECKPOINT_TIMEOUT_S:.0f}s. "
                "Another Jedoc API process is likely locking data/checkpoints.sqlite — "
                "stop extra uvicorn workers and Resume again."
            ) from exc

    async def _prepare_resume(self, graph, config, feature: dict[str, Any], flow: dict[str, Any], *, note: str) -> None:
        """Ensure the checkpoint can continue; rebuild from audit if the interrupt flush was lost."""
        try:
            snapshot = await self._checkpoint(graph.aget_state(config), label="read")
        except RuntimeError:
            raise
        except Exception as exc:
            raise RuntimeError(f"Could not read pipeline checkpoint: {exc}") from exc
        values = dict(snapshot.values or {})
        nxt = list(snapshot.next or [])

        if _circuit_tripped(values, feature):
            await self._heal_circuit_checkpoint(graph, config, feature, flow, values)
            return

        if values.get("feature_id") and (nxt or values.get("last_node")):
            await self._announce_nodes(
                flow,
                feature["id"],
                nxt or ([values["last_node"]] if values.get("last_node") else []),
                "RUNNING",
                "Resuming from checkpoint…",
            )
            return

        last_passed = self._last_passed_node(feature["id"], flow)
        if not last_passed:
            raise RuntimeError(
                "Cannot resume: no checkpoint and no passed agents yet. Use Restart from start."
            )
        # Show progress immediately — aupdate_state can block for a long time if SQLite is contended.
        guessed = self._successors(flow, last_passed)
        await self.bus.publish(
            feature["id"],
            {
                "type": "stream",
                "kind": "system",
                "text": f"Rebuilding checkpoint after `{last_passed}`…",
            },
        )
        if guessed:
            await self._announce_nodes(
                flow,
                feature["id"],
                guessed,
                "RUNNING",
                "Rebuilding checkpoint…",
            )
        artifacts = {item["name"]: item["content"] for item in self.store.list_artifacts(feature["id"])}
        rebuilt = {
            "feature_id": feature["id"],
            "flow_id": feature["flow_id"],
            "workspace": feature["workspace_path"],
            "prd": feature["prd"],
            "artifacts": artifacts,
            "retry_counts": {},
            "route": "on_pass",
            "verdict": "PASS",
            "last_node": last_passed,
            "last_output": "",
            "error": "",
            "qa_report": {},
            "approval_packet": artifacts.get("APPROVAL_PACKET.md") or note or "",
        }
        await self._checkpoint(
            graph.aupdate_state(config, rebuilt, as_node=last_passed),
            label="rebuild",
        )
        snapshot = await self._checkpoint(graph.aget_state(config), label="read-after-rebuild")
        nxt = list(snapshot.next or [])
        await self.bus.publish(
            feature["id"],
            {
                "type": "stream",
                "kind": "system",
                "text": f"Rebuilt checkpoint after `{last_passed}`. Next: {', '.join(nxt) or 'done'}.",
            },
        )
        await self._announce_nodes(flow, feature["id"], nxt, "RUNNING", "Resuming from last passed agent…")

    async def _heal_circuit_checkpoint(
        self,
        graph,
        config,
        feature: dict[str, Any],
        flow: dict[str, Any],
        values: dict[str, Any],
    ) -> None:
        """Clear a tripped circuit and escalate to PRD/architecture so Resume can continue."""
        flow = validate_flow(flow)
        reviewers = [node["id"] for node in flow["nodes"] if node.get("role_type") in {"reviewer", "qa_auditor"}]
        source = str(values.get("last_node") or "")
        if source not in reviewers:
            source = reviewers[0] if reviewers else str(flow.get("entry") or "")
        if not source:
            raise RuntimeError("Cannot resume: circuit is open and no reviewer/entry node is available. Use Start over from PRD.")

        retries = dict(values.get("retry_counts") or {})
        retries[source] = 0
        has_scale = any(
            edge.get("source") == source and (edge.get("condition") or "") == "on_scale_issue"
            for edge in flow.get("edges") or []
        )
        route = "on_scale_issue" if has_scale else "on_fail"
        healed = {
            **values,
            "feature_id": feature["id"],
            "flow_id": feature["flow_id"],
            "workspace": feature["workspace_path"],
            "prd": feature.get("prd") or values.get("prd") or "",
            "retry_counts": retries,
            "route": route,
            "verdict": "SCALE_ISSUE" if route == "on_scale_issue" else "FAIL",
            "error": "",
            "last_node": source,
        }
        self.store.update_feature(feature["id"], error="")
        await self.bus.publish(
            feature["id"],
            {
                "type": "stream",
                "kind": "system",
                "text": (
                    f"Cleared circuit breaker on `{source}`. "
                    "Escalating to PRD Scale Architect with a fresh retry budget…"
                ),
            },
        )
        await self._checkpoint(
            graph.aupdate_state(config, healed, as_node=source),
            label="heal-circuit",
        )
        snapshot = await self._checkpoint(graph.aget_state(config), label="read-after-heal")
        nxt = list(snapshot.next or [])
        await self._announce_nodes(
            flow,
            feature["id"],
            nxt,
            "RUNNING",
            "Resuming after circuit heal…",
        )

    def _successors(self, flow: dict[str, Any], node_id: str) -> list[str]:
        return [
            str(edge["target"])
            for edge in flow.get("edges") or []
            if edge.get("source") == node_id and edge.get("target")
        ]

    def _last_passed_node(self, feature_id: str, flow: dict[str, Any]) -> str | None:
        known = {node["id"] for node in flow["nodes"]}
        for row in reversed(self.store.list_audit(feature_id, limit=800)):
            payload = row.get("payload") or {}
            event_type = row.get("event_type") or payload.get("type")
            if event_type != "node_status":
                continue
            if (payload.get("status") or "") != "PASSED":
                continue
            node_id = str(payload.get("node_id") or row.get("node_id") or "")
            if node_id in known:
                return node_id
        return None

    async def _announce_next(self, graph, config, flow: dict[str, Any], feature_id: str, *, action: str) -> None:
        try:
            snapshot = await graph.aget_state(config)
        except Exception:
            return
        nxt = list(snapshot.next or [])
        if nxt:
            await self._announce_nodes(flow, feature_id, nxt, "RUNNING", action)

    async def _announce_nodes(
        self,
        flow: dict[str, Any],
        feature_id: str,
        node_ids: list[str],
        status: str,
        action: str,
    ) -> None:
        specs = {node["id"]: node for node in flow["nodes"]}
        started = time.time()
        for node_id in node_ids:
            node = specs.get(node_id) or {"id": node_id, "display_name": node_id}
            await self.bus.publish(
                feature_id,
                {
                    "type": "node_status",
                    "node_id": node_id,
                    "status": status,
                    "chat_id": "",
                    "action": action,
                    "started_at": started,
                    "display_name": node.get("display_name") or node_id,
                },
            )

    async def _recover_interrupt(self, feature_id: str, exc: Exception) -> bool:
        """If the run stopped at a human gate (even via a chained checkpoint error), pause instead of fail."""
        if not _is_interrupt(exc):
            # Still try: a lock error after the gate may leave the checkpoint waiting.
            if "database is locked" not in str(exc).lower() and "GraphInterrupt" not in "".join(traceback.format_exception(exc)):
                return False
        feature = self.store.get_feature(feature_id)
        if feature is None:
            return False
        flow = self.store.get_flow(feature["flow_id"])
        if flow is None:
            return False
        flow = validate_flow(flow)
        graph = compile_flow(flow, self.store, self.skills, self.bus, self.checkpointer)
        config = {"configurable": {"thread_id": feature["thread_id"]}}
        try:
            snapshot = await graph.aget_state(config)
        except Exception:
            if _is_interrupt(exc):
                await self._publish_paused(feature_id, ["implementer"])
                return True
            return False
        waiting = self._human_gate(flow, snapshot) or list(snapshot.next or [])
        if not waiting and not _is_interrupt(exc):
            return False
        if not waiting:
            waiting = ["implementer"]
        await self._publish_paused(feature_id, waiting)
        return True

    async def _publish_paused(self, feature_id: str, waiting: list[str]) -> None:
        self.store.update_feature(feature_id, status="paused", error="")
        for node_id in waiting:
            await self.bus.publish(
                feature_id,
                {
                    "type": "node_status",
                    "node_id": node_id,
                    "status": "WAITING_APPROVAL",
                    "action": "Pre-implementation gate — review the spec and skills, then approve",
                    "chat_id": "",
                },
            )
        await self.bus.publish(
            feature_id,
            {"type": "feature_status", "status": "paused", "waiting": waiting},
        )

    async def _publish_user_paused(self, feature_id: str, waiting: list[str] | None = None) -> None:
        pending = list(waiting or [])
        detail = "Paused by user. Resume to continue from the checkpoint."
        self.store.update_feature(feature_id, status="paused", error=detail)
        for node_id in pending:
            await self.bus.publish(
                feature_id,
                {
                    "type": "node_status",
                    "node_id": node_id,
                    "status": "WAITING_APPROVAL",
                    "action": detail,
                    "chat_id": "",
                },
            )
        await self.bus.publish(
            feature_id,
            {
                "type": "stream",
                "kind": "system",
                "text": detail,
            },
        )
        await self.bus.publish(
            feature_id,
            {"type": "feature_status", "status": "paused", "error": detail, "waiting": pending},
        )

    def _human_gate(self, flow: dict, snapshot) -> list[str]:
        pending = [node_id for node_id in (snapshot.next or [])]
        if not pending:
            return []
        values = snapshot.values or {}
        retries = values.get("retry_counts") or {}
        specs = {node["id"]: node for node in flow["nodes"]}
        # First entry needs approval. After a rejection, auto-run implementer once; on the
        # second+ rejection pause so a FAIL loop cannot burn 40 minutes unattended.
        from_rejection = (values.get("route") or "") in {"on_fail", "on_scale_issue"}
        waiting = []
        for node_id in pending:
            spec = specs.get(node_id)
            if not spec or not spec.get("require_approval_before"):
                continue
            attempts = int(retries.get(node_id, 0))
            if spec.get("approve_every_entry") or attempts == 0:
                waiting.append(node_id)
            elif from_rejection and attempts > 1:
                waiting.append(node_id)
        return waiting


def new_thread_id() -> str:
    return uuid.uuid4().hex
