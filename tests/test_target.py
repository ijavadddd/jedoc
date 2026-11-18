import os
import subprocess
from pathlib import Path

import pytest

from backend.engine.git_target import GitError, bind_workspace, inspect_repo
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
