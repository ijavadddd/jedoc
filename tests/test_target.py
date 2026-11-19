import asyncio
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from backend.engine import git_target
from backend.engine.git_target import GitError, bind_workspace, inspect_repo, pick_project_folder
from backend.engine.workspace import file_delta, file_stats
from backend.providers.cursor_cli import parse_model_list


def _git(repo: Path, *args: str) -> None:
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "Jedoc",
        "GIT_AUTHOR_EMAIL": "jedoc@local",
        "GIT_COMMITTER_NAME": "Jedoc",
        "GIT_COMMITTER_EMAIL": "jedoc@local",
    }
    subprocess.run(["git", *args], cwd=repo, check=True, env=env, capture_output=True, text=True)


def _repo(path: Path) -> Path:
    path.mkdir()
    _git(path, "init", "-b", "main")
    (path / "README.md").write_text("hello\n", encoding="utf-8")
    _git(path, "add", ".")
    _git(path, "commit", "-m", "init")
    _git(path, "branch", "feature")
    return path


def test_worktree_binding_leaves_the_current_branch(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("JEDOC_DATA_DIR", str(tmp_path / "data"))
    repo = _repo(tmp_path / "repo")
    bound = bind_workspace(repo, "feature", True, "drop")
    workspace = Path(bound["workspace_path"])
    assert workspace != repo.resolve()
    assert (workspace / "README.md").is_file()
    info = inspect_repo(str(workspace))
    assert info["branch"] == "feature"
    assert inspect_repo(str(repo))["branch"] == "main"
    again = bind_workspace(repo, "feature", True, "drop")
    assert again["workspace_path"] == bound["workspace_path"]


def test_dirty_checkout_asks_for_a_worktree(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("JEDOC_DATA_DIR", str(tmp_path / "data"))
    repo = _repo(tmp_path / "repo")
    (repo / "README.md").write_text("dirty\n", encoding="utf-8")
    with pytest.raises(GitError, match="worktree"):
        bind_workspace(repo, "feature", False, "drop")


def test_file_delta_counts_only_this_turn(tmp_path: Path):
    repo = _repo(tmp_path / "repo")
    before = file_stats(repo)
    (repo / "src").mkdir()
    (repo / "src" / "inventory.py").write_text("line\n" * 4, encoding="utf-8")
    (repo / "README.md").write_text("hello\nchanged\n", encoding="utf-8")
    changes = {item["path"]: item for item in file_delta(before, file_stats(repo))}
    assert changes["src/inventory.py"]["added"] == 4
    assert changes["README.md"]["added"] == 1
    again = file_delta(file_stats(repo), file_stats(repo))
    assert again == []


def test_model_list_parses_text_and_json():
    assert parse_model_list('{"models":[{"id":"gpt-5"},{"name":"composer-1.5"}]}') == ["gpt-5", "composer-1.5"]
    assert parse_model_list("Error: Authentication required\n") == []
    assert "claude-sonnet-4-6" in parse_model_list("- claude-sonnet-4-6\n- gpt-5 thinking\n")


def test_pick_project_folder_uses_osascript_on_macos(monkeypatch):
    calls: list[tuple[str, ...]] = []

    class FakeProcess:
        returncode = 0

        async def communicate(self):
            return (b"/Users/jay/Projects/jedoc\n", b"")

        def kill(self):
            return None

    async def fake_exec(*args, **_kwargs):
        calls.append(args)
        return FakeProcess()

    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(git_target.shutil, "which", lambda name: "/usr/bin/osascript" if name == "osascript" else None)
    monkeypatch.setattr(git_target.asyncio, "create_subprocess_exec", fake_exec)

    chosen = asyncio.run(pick_project_folder())
    assert chosen == "/Users/jay/Projects/jedoc"
    assert calls and calls[0][0] == "osascript"


def test_pick_project_folder_errors_without_a_dialog_tool(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(git_target.shutil, "which", lambda _name: None)
    with pytest.raises(GitError, match="folder dialog"):
        asyncio.run(pick_project_folder())


def test_graphify_timeout_does_not_abort_the_pipeline(tmp_path: Path, monkeypatch):
    from backend.engine import runtime

    monkeypatch.setenv("JEDOC_BUNDLED_SKILLS", str(tmp_path))
    monkeypatch.setenv("JEDOC_GRAPHIFY_TIMEOUT_S", "1")
    (tmp_path / "graphify").mkdir()
    (tmp_path / "graphify" / "graphify_cli.py").write_text(
        "import time\ntime.sleep(30)\n",
        encoding="utf-8",
    )

    asyncio.run(runtime._run_graphify(tmp_path))
    report = tmp_path / "graphify-out" / "GRAPH_REPORT.md"
    assert report.is_file()
    assert "Timed out" in report.read_text(encoding="utf-8")


def test_live_action_labels_stream_kinds():
    from backend.engine.runtime import _live_action

    assert _live_action({"kind": "thinking", "text": "plan the hot path"}).startswith("Thinking")
    assert _live_action({"kind": "assistant", "text": "PRD_OPTIMIZED"}).startswith("Writing")
    assert _live_action({"kind": "shell", "text": "ls src"}).startswith("$")
    assert "Read" in _live_action({"kind": "tool_call", "name": "Read", "text": "Read started src/a.py"})


def test_interrupt_detection_covers_chained_lock_errors():
    from langgraph.errors import GraphInterrupt

    from backend.engine.runner import _is_interrupt

    locked = sqlite3.OperationalError("database is locked")
    locked.__context__ = GraphInterrupt()
    assert _is_interrupt(locked)
    assert _is_interrupt(GraphInterrupt())
    assert not _is_interrupt(RuntimeError("boom"))


def test_last_passed_node_reads_audit(tmp_path: Path):
    from backend.engine.runner import PipelineRunner
    from backend.events import EventBus
    from backend.marketplace.manager import SkillManager
    from backend.storage.session_store import FeatureSessionStore

    store = FeatureSessionStore(str(tmp_path / "jedoc.sqlite"))
    store.init()
    runner = PipelineRunner(store, SkillManager(store), EventBus(store))
    runner.startup()
    feature = store.create_feature(name="X", prd="p", workspace_path=str(tmp_path), flow_id="jedoc-million-user")
    store.add_audit(feature["id"], "node_status", {"type": "node_status", "node_id": "prd_scale_architect", "status": "PASSED"}, node_id="prd_scale_architect")
    store.add_audit(feature["id"], "node_status", {"type": "node_status", "node_id": "pre_impl_gate", "status": "PASSED"}, node_id="pre_impl_gate")
    flow = store.get_flow("jedoc-million-user")
    assert runner._last_passed_node(feature["id"], flow) == "pre_impl_gate"
