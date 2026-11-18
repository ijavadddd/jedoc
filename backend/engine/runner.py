"""Drive a compiled flow until it finishes, pauses for approval, or opens a circuit breaker."""

from __future__ import annotations

import asyncio
import traceback
import uuid
from pathlib import Path
from typing import Any

from langgraph.checkpoint.memory import MemorySaver

from backend.engine.graph_builder import compile_flow, validate_flow
from backend.engine.templates import FLOW_ID, default_flow
from backend.events import EventBus
from backend.marketplace.manager import SkillManager
from backend.storage.session_store import FeatureSessionStore

try:
    from langgraph.errors import GraphInterrupt
except ImportError:  # pragma: no cover - older langgraph packages
    class GraphInterrupt(Exception):
        pass


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

    def startup(self) -> None:
        self.store.init()
        if self.store.get_flow(FLOW_ID) is None:
            self.store.save_flow(default_flow(), is_template=True)
        self.skills.seed_states()

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
                raise
            except Exception as exc:
                detail = "".join(traceback.format_exception(exc))[-4000:]
                self.store.update_feature(feature_id, status="failed", error=detail)
                await self.bus.publish(
                    feature_id,
                    {"type": "feature_status", "status": "failed", "error": detail},
                )

    async def mark_done(self, feature_id: str) -> list[dict[str, Any]]:
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
        snapshot = await self._drive(graph, config, payload, flow)
        waiting = self._human_gate(flow, snapshot)
        if waiting:
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
            return
        values = dict(snapshot.values or {})
        if values.get("error") or values.get("route") == "circuit_open":
            error = values.get("error") or "Circuit breaker opened"
            self.store.update_feature(feature_id, status="failed", error=error)
            await self.bus.publish(feature_id, {"type": "feature_status", "status": "failed", "error": error})
            return
        self.store.update_feature(feature_id, status="completed", error="")
        await self.bus.publish(feature_id, {"type": "feature_status", "status": "completed"})

    async def _drive(self, graph, config, payload, flow):
        await self._invoke(graph, config, payload)
        while True:
            snapshot = await graph.aget_state(config)
            if not snapshot.next:
                return snapshot
            if self._human_gate(flow, snapshot):
                return snapshot
            await self._invoke(graph, config, None)

    async def _invoke(self, graph, config, payload) -> None:
        try:
            if payload is None:
                await graph.ainvoke(None, config)
            else:
                await graph.ainvoke(payload, config)
        except GraphInterrupt:
            return

    def _human_gate(self, flow: dict, snapshot) -> list[str]:
        pending = [node_id for node_id in (snapshot.next or [])]
        if not pending:
            return []
        values = snapshot.values or {}
        retries = values.get("retry_counts") or {}
        specs = {node["id"]: node for node in flow["nodes"]}
        waiting = []
        for node_id in pending:
            spec = specs.get(node_id)
            if not spec or not spec.get("require_approval_before"):
                continue
            attempts = int(retries.get(node_id, 0))
            if spec.get("approve_every_entry") or attempts == 0:
                waiting.append(node_id)
        return waiting


def new_thread_id() -> str:
    return uuid.uuid4().hex
