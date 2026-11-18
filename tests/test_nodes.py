import asyncio
from pathlib import Path

from backend.engine.graph_builder import interrupt_nodes, validate_flow
from backend.engine.runtime import make_executor
from backend.events import EventBus
from backend.marketplace.manager import SkillManager
from backend.storage.session_store import FeatureSessionStore


def test_disabled_agent_is_skipped_and_does_not_pause(tmp_path: Path):
    store = FeatureSessionStore(str(tmp_path / "jedoc.sqlite"))
    store.init()
    flow = validate_flow(
        {
            "id": "tiny",
            "name": "Tiny",
            "entry": "skip_me",
            "interrupt_before": ["skip_me"],
            "nodes": [
                {
                    "id": "skip_me",
                    "display_name": "Skip Me",
                    "role_type": "implementer",
                    "cursor_mode": "agent",
                    "enabled": False,
                    "require_approval_before": True,
                }
            ],
            "edges": [],
        }
    )
    assert interrupt_nodes(flow) == []
    store.save_flow(flow)
    feature = store.create_feature(name="Skip", prd="Nothing.", workspace_path=str(tmp_path), flow_id="tiny")
    result = asyncio.run(
        make_executor("skip_me", store, SkillManager(store), EventBus(store))(
            {"feature_id": feature["id"], "flow_id": "tiny", "workspace": str(tmp_path), "prd": "Nothing."}
        )
    )
    assert result["route"] == "on_pass"
    assert result["verdict"] == "PASS"
    assert store.list_sessions(feature["id"]) == []

    flow["nodes"][0]["enabled"] = True
    assert interrupt_nodes(validate_flow(flow)) == ["skip_me"]
