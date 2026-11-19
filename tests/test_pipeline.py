import asyncio
import os
from pathlib import Path

from langgraph.checkpoint.memory import MemorySaver

from backend.engine.runner import PipelineRunner
from backend.engine.workspace import prepare_workspace
from backend.events import EventBus
from backend.marketplace.manager import SkillManager
from backend.storage.session_store import FeatureSessionStore


def test_pipeline_pauses_then_keeps_chat_ids(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("JEDOC_EXECUTION_MODE", "simulate")
    monkeypatch.setenv("JEDOC_QA_DURATION_S", "0")
    monkeypatch.setenv("JEDOC_SIMULATE_REVIEW_FAILS", "1")
    os.environ["JEDOC_EXECUTION_MODE"] = "simulate"

    store = FeatureSessionStore(str(tmp_path / "jedoc.sqlite"))
    skills = SkillManager(store)
    bus = EventBus(store)
    runner = PipelineRunner(store, skills, bus, checkpointer=MemorySaver())
    runner.startup()

    workspace = prepare_workspace(tmp_path / "workspace", "Reserve inventory without a hot row.")
    feature = store.create_feature(
        name="Drop",
        prd="Reserve inventory without a hot row.",
        workspace_path=str(workspace),
        flow_id="jedoc-million-user",
    )

    asyncio.run(runner.execute(feature["id"], resume=False, note=""))
    paused = store.get_feature(feature["id"])
    assert paused is not None
    assert paused["status"] == "paused", paused["error"]
    architect = store.get_active_session(feature["id"], "prd_scale_architect")
    tdd = store.get_active_session(feature["id"], "tdd_spec_writer")
    assert architect and tdd
    assert architect["chat_id"] != tdd["chat_id"]
    assert (workspace / "PRD_OPTIMIZED.md").is_file()
    assert (workspace / "ARCHITECTURE_SPEC.md").is_file()
    assert (workspace / "tests" / "test_capacity.py").is_file()
    assert (workspace / "graphify-out" / "GRAPH_REPORT.md").is_file()

    asyncio.run(runner.execute(feature["id"], resume=True, note="Approved. Keep the conditional update."))
    finished = store.get_feature(feature["id"])
    assert finished is not None
    assert finished["status"] == "completed", finished["error"]
    implementer_rows = [row for row in store.list_sessions(feature["id"]) if row["agent_id"] == "implementer"]
    assert len(implementer_rows) == 1
    assert implementer_rows[0]["status"] == "active"
    turns = [turn for turn in store.list_turns(feature["id"], "implementer") if turn["role"] == "user"]
    assert len(turns) >= 2
    assert {turn["chat_id"] for turn in turns} == {implementer_rows[0]["chat_id"]}
    edited = {item["path"] for item in implementer_rows[0]["files"]}
    assert any(path.endswith("inventory.py") for path in edited)
    assert any(item["added"] > 0 for item in implementer_rows[0]["files"])
    assert "idempotency" in (workspace / "src" / "capacity" / "inventory.py").read_text()
    assert (workspace / "QA_REPORT.md").is_file()

    archived = asyncio.run(runner.mark_done(feature["id"]))
    assert archived
    assert store.get_feature(feature["id"])["status"] == "archived"
    assert store.get_active_session(feature["id"], "implementer") is None
    assert any(row["agent_id"] == "implementer" for row in store.list_sessions(feature["id"]))


def test_format_run_failure_keeps_message_not_mid_traceback_tail():
    from backend.engine.runner import _format_run_failure

    try:
        raise RuntimeError("ActionRequiredError: GPT-5.6 Sol is not included in your weekly usage")
    except RuntimeError as exc:
        detail = _format_run_failure(exc)
    assert "GPT-5.6 Sol is not included in your weekly usage" in detail
    assert detail.startswith("RuntimeError:") or detail.startswith("Traceback")
    assert not detail.startswith("nd/engine")


def test_recover_orphaned_running_and_empty_checkpoint_resume(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("JEDOC_EXECUTION_MODE", "simulate")
    monkeypatch.setenv("JEDOC_QA_DURATION_S", "0")

    store = FeatureSessionStore(str(tmp_path / "jedoc.sqlite"))
    skills = SkillManager(store)
    bus = EventBus(store)
    runner = PipelineRunner(store, skills, bus, checkpointer=MemorySaver())
    runner.startup()

    workspace = prepare_workspace(tmp_path / "workspace", "Orphan resume.")
    feature = store.create_feature(
        name="Orphan",
        prd="Orphan resume.",
        workspace_path=str(workspace),
        flow_id="jedoc-million-user",
    )
    store.update_feature(feature["id"], status="running", error="")
    assert runner.recover_orphaned_runs() == 1
    assert store.get_feature(feature["id"])["status"] == "failed"
    assert runner.is_executing(feature["id"]) is False

    # Simulate a lost interrupt flush: audit shows gate passed, checkpoint is empty.
    store.add_audit(
        feature["id"],
        "node_status",
        {
            "type": "node_status",
            "node_id": "pre_impl_gate",
            "status": "PASSED",
            "action": "Review packet ready",
        },
        node_id="pre_impl_gate",
    )
    flow = store.get_flow("jedoc-million-user")
    assert flow is not None
    from backend.engine.graph_builder import compile_flow

    graph = compile_flow(flow, store, skills, bus, runner.checkpointer)
    config = {"configurable": {"thread_id": feature["thread_id"]}}

    async def _prep():
        await runner._prepare_resume(graph, config, store.get_feature(feature["id"]), flow, note="go")

    asyncio.run(_prep())
    statuses = [
        row["payload"]
        for row in store.list_audit(feature["id"], limit=50)
        if row["event_type"] == "node_status" and row["payload"].get("node_id") == "implementer"
    ]
    assert statuses, "resume must announce the next agent before hanging on checkpoint I/O"
    assert statuses[-1]["status"] == "RUNNING"
    snap = asyncio.run(graph.aget_state(config))
    assert list(snap.next or []) == ["implementer"]
