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


def test_cli_timeout_helpers_and_hard_floor():
    from backend.providers.cursor_cli import CursorCLIError, cli_hard_timeout_s, is_cli_timeout

    assert is_cli_timeout(CursorCLIError("No Cursor activity for 1800s (agent may be stuck — Resume to retry)"))
    assert is_cli_timeout(CursorCLIError("Cursor CLI timed out after 600s"))
    assert not is_cli_timeout(CursorCLIError("ActionRequiredError: buy credits"))
    assert cli_hard_timeout_s(1800) >= 7200


def test_reviewer_failures_escalate_to_prd_architect():
    from backend.engine.runtime import _route
    from backend.engine.templates import default_flow

    flow = default_flow()
    reviewer = next(node for node in flow["nodes"] if node["id"] == "adversarial_reviewer")
    state: dict = {"retry_counts": {}}
    route = "on_pass"
    # First max_retries FAILs bounce to the implementer.
    for _ in range(int(reviewer["max_retries"])):
        route, state["retry_counts"], error = _route(flow, reviewer, "FAIL", state)
        assert route == "on_fail"
        assert error == ""
    # One more FAIL escalates to the PRD Scale Architect instead of opening the circuit.
    route, state["retry_counts"], error = _route(flow, reviewer, "FAIL", state)
    assert route == "on_scale_issue"
    assert error == ""
    assert state["retry_counts"]["adversarial_reviewer"] == 0
    assert state["retry_counts"]["prd_scale_architect"] == 1


def test_reviewer_scale_issue_goes_to_architect():
    from backend.engine.runtime import _route
    from backend.engine.templates import default_flow

    flow = default_flow()
    reviewer = next(node for node in flow["nodes"] if node["id"] == "adversarial_reviewer")
    route, retries, error = _route(flow, reviewer, "SCALE_ISSUE", {"retry_counts": {}})
    assert route == "on_scale_issue"
    assert error == ""
    assert retries["adversarial_reviewer"] == 1


def test_skip_agent_advances_past_queued_node(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("JEDOC_EXECUTION_MODE", "simulate")
    monkeypatch.setenv("JEDOC_QA_DURATION_S", "0")

    store = FeatureSessionStore(str(tmp_path / "jedoc.sqlite"))
    skills = SkillManager(store)
    bus = EventBus(store)
    runner = PipelineRunner(store, skills, bus, checkpointer=MemorySaver())
    runner.startup()

    workspace = prepare_workspace(tmp_path / "workspace", "Skip me.")
    feature = store.create_feature(
        name="Skip",
        prd="Skip me.",
        workspace_path=str(workspace),
        flow_id="jedoc-million-user",
    )
    # Run until pre-impl gate pause (simulate hits interrupt before implementer).
    asyncio.run(runner.execute(feature["id"], resume=False, note=""))
    assert store.get_feature(feature["id"])["status"] == "paused"

    async def _skip():
        await runner.skip_agent(feature["id"], "implementer")
        for _ in range(150):
            await asyncio.sleep(0.02)
            status = store.get_feature(feature["id"])["status"]
            if status in {"paused", "completed", "failed"} and not runner.is_executing(feature["id"]):
                break
        return store.get_feature(feature["id"])

    updated = asyncio.run(_skip())
    assert updated is not None
    assert updated["status"] in {"running", "paused", "completed", "failed"}
    texts = [
        str((row.get("payload") or {}).get("text") or (row.get("payload") or {}).get("action") or "")
        for row in store.list_audit(feature["id"], limit=120)
    ]
    assert any("Skipped" in text for text in texts)
    assert any(
        (row.get("payload") or {}).get("node_id") == "implementer"
        and (row.get("payload") or {}).get("status") == "PASSED"
        for row in store.list_audit(feature["id"], limit=120)
    )


def test_circuit_tripped_detects_open_route_and_error_text():
    from backend.engine.runner import _circuit_tripped

    assert _circuit_tripped({"route": "circuit_open", "error": ""}, {"error": ""})
    assert _circuit_tripped(
        {"route": "on_fail", "error": ""},
        {"error": "Circuit breaker opened for adversarial_reviewer after 3 retries"},
    )
    assert not _circuit_tripped({"route": "on_pass", "error": ""}, {"error": ""})


def test_resume_heals_circuit_open_checkpoint(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("JEDOC_EXECUTION_MODE", "simulate")
    monkeypatch.setenv("JEDOC_QA_DURATION_S", "0")

    from backend.engine.graph_builder import compile_flow, validate_flow
    from backend.engine.templates import default_flow

    store = FeatureSessionStore(str(tmp_path / "jedoc.sqlite"))
    skills = SkillManager(store)
    bus = EventBus(store)
    runner = PipelineRunner(store, skills, bus, checkpointer=MemorySaver())
    runner.startup()

    workspace = prepare_workspace(tmp_path / "workspace", "Heal circuit.")
    feature = store.create_feature(
        name="Heal",
        prd="Heal circuit.",
        workspace_path=str(workspace),
        flow_id="jedoc-million-user",
    )
    store.update_feature(
        feature["id"],
        status="failed",
        error="Circuit breaker opened for adversarial_reviewer after 3 retries",
    )
    flow = validate_flow(store.get_flow("jedoc-million-user") or default_flow())
    graph = compile_flow(flow, store, skills, bus, runner.checkpointer)
    config = {"configurable": {"thread_id": feature["thread_id"]}}

    async def _seed_and_heal():
        await graph.aupdate_state(
            config,
            {
                "feature_id": feature["id"],
                "flow_id": feature["flow_id"],
                "workspace": str(workspace),
                "prd": "Heal circuit.",
                "artifacts": {},
                "retry_counts": {"adversarial_reviewer": 4},
                "route": "circuit_open",
                "verdict": "FAIL",
                "last_node": "adversarial_reviewer",
                "last_output": "",
                "error": "Circuit breaker opened for adversarial_reviewer after 3 retries",
                "qa_report": {},
                "approval_packet": "",
            },
            as_node="adversarial_reviewer",
        )
        await runner._heal_circuit_checkpoint(
            graph,
            config,
            store.get_feature(feature["id"]),
            flow,
            dict((await graph.aget_state(config)).values or {}),
        )
        snap = await graph.aget_state(config)
        return dict(snap.values or {}), list(snap.next or [])

    values, nxt = asyncio.run(_seed_and_heal())
    assert values.get("route") == "on_scale_issue"
    assert values.get("error") == ""
    assert values.get("retry_counts", {}).get("adversarial_reviewer") == 0
    assert "prd_scale_architect" in nxt
    assert store.get_feature(feature["id"])["error"] == ""


def test_architect_escalation_budget_eventually_opens_circuit():
    from backend.engine.runtime import _route
    from backend.engine.templates import default_flow

    flow = default_flow()
    reviewer = next(node for node in flow["nodes"] if node["id"] == "adversarial_reviewer")
    architect = next(node for node in flow["nodes"] if node["id"] == "prd_scale_architect")
    state: dict = {"retry_counts": {}}
    # Exhaust implementer bounce budget enough times to exceed architect escalations.
    for _ in range(int(architect["max_retries"]) + 1):
        state["retry_counts"][reviewer["id"]] = int(reviewer["max_retries"])
        route, state["retry_counts"], error = _route(flow, reviewer, "FAIL", state)
    assert route == "circuit_open"
    assert "prd_scale_architect" in error
    assert "architecture escalations" in error


def test_restart_from_start_resets_thread_and_sessions(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("JEDOC_EXECUTION_MODE", "simulate")
    monkeypatch.setenv("JEDOC_QA_DURATION_S", "0")

    store = FeatureSessionStore(str(tmp_path / "jedoc.sqlite"))
    skills = SkillManager(store)
    bus = EventBus(store)
    runner = PipelineRunner(store, skills, bus, checkpointer=MemorySaver())
    runner.startup()

    workspace = prepare_workspace(tmp_path / "workspace", "Restart me.")
    feature = store.create_feature(
        name="Restart",
        prd="Restart me.",
        workspace_path=str(workspace),
        flow_id="jedoc-million-user",
    )
    asyncio.run(runner.execute(feature["id"], resume=False, note=""))
    assert store.get_feature(feature["id"])["status"] == "paused"
    old_thread = store.get_feature(feature["id"])["thread_id"]
    assert store.get_active_session(feature["id"], "prd_scale_architect") is not None

    async def _restart():
        await runner.restart_from_start(feature["id"])
        for _ in range(100):
            await asyncio.sleep(0.02)
            status = store.get_feature(feature["id"])["status"]
            if status in {"paused", "completed", "failed"}:
                break
        return store.get_feature(feature["id"])

    restarted = asyncio.run(_restart())
    assert restarted is not None
    assert restarted["thread_id"] != old_thread
    # Prior architect chat archived; a new active session may already exist from the fresh run.
    sessions = store.list_sessions(feature["id"])
    assert any(row["agent_id"] == "prd_scale_architect" and row["status"] == "archived" for row in sessions)


def test_pause_stops_running_feature(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("JEDOC_EXECUTION_MODE", "simulate")
    monkeypatch.setenv("JEDOC_QA_DURATION_S", "0")

    store = FeatureSessionStore(str(tmp_path / "jedoc.sqlite"))
    skills = SkillManager(store)
    bus = EventBus(store)
    runner = PipelineRunner(store, skills, bus, checkpointer=MemorySaver())
    runner.startup()

    workspace = prepare_workspace(tmp_path / "workspace", "Pause me.")
    feature = store.create_feature(
        name="Pause",
        prd="Pause me.",
        workspace_path=str(workspace),
        flow_id="jedoc-million-user",
    )

    async def _run():
        runner.launch(feature["id"], resume=False)
        for _ in range(50):
            await asyncio.sleep(0.02)
            if store.get_feature(feature["id"])["status"] == "running":
                break
        paused = await runner.pause(feature["id"])
        assert paused["status"] == "paused"
        assert store.get_feature(feature["id"])["status"] == "paused"
        assert runner.is_executing(feature["id"]) is False

    asyncio.run(_run())


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
