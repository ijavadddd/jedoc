import json
from pathlib import Path

from backend.engine.artifacts import extract_files, extract_verdict
from backend.marketplace.manager import SkillManager
from backend.providers.cursor_cli import describe_tool_call, extract_text
from backend.storage.session_store import FeatureSessionStore


def test_session_chat_id_survives_until_explicit_archive(tmp_path: Path):
    store = FeatureSessionStore(str(tmp_path / "jedoc.sqlite"))
    store.init()
    feature = store.create_feature(name="Drop", prd="prd", workspace_path=str(tmp_path), flow_id="flow")
    created = {"n": 0}

    def factory() -> str:
        created["n"] += 1
        return f"chat-{created['n']}"

    first = store.get_or_create_session(feature["id"], "implementer", factory)
    second = store.get_or_create_session(feature["id"], "implementer", factory)
    assert first["chat_id"] == "chat-1"
    assert second["chat_id"] == "chat-1"
    assert created["n"] == 1
    archived = store.archive_session(feature["id"], "implementer")
    assert archived is not None
    assert archived["status"] == "archived"
    third = store.get_or_create_session(feature["id"], "implementer", factory)
    assert third["chat_id"] == "chat-2"
    assert third["status"] == "active"
    rows = store.list_sessions(feature["id"])
    assert len(rows) == 2
    store.archive_feature_sessions(feature["id"])
    assert store.get_feature(feature["id"])["status"] == "archived"
    assert all(row["status"] == "archived" for row in store.list_sessions(feature["id"]))
    assert len(store.list_sessions(feature["id"])) == 2


def test_skill_toggle_materializes_and_removes_files(tmp_path: Path):
    store = FeatureSessionStore(str(tmp_path / "jedoc.sqlite"))
    store.init()
    skills = SkillManager(store)
    workspace = tmp_path / "repo"
    workspace.mkdir()
    synced = skills.sync(str(workspace), ["founder-skill", "awesome-design-md", "claude-mem-cursor"])
    assert (workspace / ".cursor/skills/founder-skill/SKILL.md").is_file()
    assert (workspace / ".cursor/rules/founder-skill.mdc").is_file()
    assert (workspace / "DESIGN.md").is_file()
    assert (workspace / ".cursor/skills/claude-mem-cursor/server.py").is_file()
    mcp = json.loads((workspace / ".cursor/mcp.json").read_text())
    assert "jedoc-claude-mem" in mcp["mcpServers"]
    assert Path(mcp["mcpServers"]["jedoc-claude-mem"]["args"][0]).is_file()
    skills.set_content("founder-skill", "SKILL.md", "# Custom founder\n")
    skills.sync(str(workspace), ["founder-skill"])
    assert (workspace / ".cursor/skills/founder-skill/SKILL.md").read_text().startswith("# Custom founder")
    assert not (workspace / "DESIGN.md").exists()
    assert not (workspace / ".cursor/skills/claude-mem-cursor/server.py").exists()
    assert "jedoc-claude-mem" not in json.loads((workspace / ".cursor/mcp.json").read_text())["mcpServers"]
    assert "founder-skill" in synced["skills"]


def test_file_markers_and_verdict():
    text = "<<<FILE:PRD_OPTIMIZED.md>>>\n# Title\n<<<END FILE>>>\nnotes\nVERDICT: FAIL\nVERDICT: PASS\n"
    files = extract_files(text)
    assert files["PRD_OPTIMIZED.md"].strip() == "# Title"
    assert extract_verdict(text) == "PASS"


def test_stream_event_normalization():
    text = extract_text({"type": "assistant", "message": {"content": [{"type": "text", "text": "hello"}]}})
    assert text == "hello"
    described = describe_tool_call(
        {
            "type": "tool_call",
            "subtype": "started",
            "tool_call": {"shellToolCall": {"args": {"command": "pytest -q"}}},
        }
    )
    assert described["kind"] == "shell"
    assert "pytest" in described["detail"]
    assert "path" not in described
    edited = describe_tool_call(
        {
            "type": "tool_call",
            "subtype": "completed",
            "tool_call": {
                "editToolCall": {
                    "args": {"path": "/repo/src/capacity/inventory.py"},
                    "result": {"success": {"linesAdded": 12, "linesRemoved": 3}},
                }
            },
        }
    )
    assert edited["path"].endswith("inventory.py")
    assert edited["added"] == 12
    assert edited["removed"] == 3


def _load(path: Path, name: str):
    import importlib.util

    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_graphify_and_memory(tmp_path: Path, monkeypatch):
    root_repo = Path(__file__).resolve().parents[1]
    graphify_cli = _load(root_repo / "bundled_skills" / "graphify" / "graphify_cli.py", "graphify_cli")
    memory = _load(root_repo / "bundled_skills" / "claude-mem-cursor" / "server.py", "jedoc_mem")

    root = tmp_path / "repo"
    root.mkdir()
    (root / "pkg").mkdir()
    (root / "pkg" / "models.py").write_text(
        "from sqlalchemy.orm import DeclarativeBase\n"
        "class Base(DeclarativeBase):\n    pass\n"
        "class Order(Base):\n    __tablename__ = 'orders'\n",
        encoding="utf-8",
    )
    assert graphify_cli.main([str(root), str(root)]) == 0
    report = (root / "graphify-out" / "GRAPH_REPORT.md").read_text()
    assert "orders" in report
    assert "pkg/models.py" in report

    monkeypatch.setenv("JEDOC_MEMORY_DB", str(tmp_path / "mem.sqlite"))
    stored = memory.tool_call(
        "memory_store",
        {"title": "No hot row", "kind": "constraint", "content": "Reservations use a conditional update.", "tags": "inventory"},
    )
    assert "Stored memory" in stored["content"][0]["text"]
    found = memory.tool_call("memory_search", {"query": "conditional"})
    assert "No hot row" in found["content"][0]["text"]
