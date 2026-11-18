"""Feature workspace scaffolding and git scope fences."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path


GIT_ENV = {
    "GIT_AUTHOR_NAME": "Jedoc",
    "GIT_AUTHOR_EMAIL": "jedoc@local",
    "GIT_COMMITTER_NAME": "Jedoc",
    "GIT_COMMITTER_EMAIL": "jedoc@local",
}


def prepare_workspace(path: Path, prd: str) -> Path:
    path = path.expanduser().resolve()
    created = not path.exists()
    path.mkdir(parents=True, exist_ok=True)
    (path / "src").mkdir(exist_ok=True)
    (path / "tests").mkdir(exist_ok=True)
    (path / "PRD.md").write_text(prd.rstrip() + "\n", encoding="utf-8")
    gitignore = path / ".gitignore"
    if not gitignore.exists():
        gitignore.write_text("__pycache__/\n.pytest_cache/\n.venv/\nnode_modules/\n", encoding="utf-8")
    pytest_ini = path / "pytest.ini"
    if not pytest_ini.exists():
        pytest_ini.write_text("[pytest]\npythonpath = src\n", encoding="utf-8")
    readme = path / "README.md"
    if not readme.exists():
        readme.write_text("# Feature workspace\n\nOpened by Jedoc. The pipeline reads `PRD.md`.\n", encoding="utf-8")
    if created or not (path / ".git").exists():
        _git(path, ["init"])
        _git(path, ["add", "."])
        _git(path, ["commit", "-m", "Initial feature workspace"])
    return path


def git_snapshot(workspace: Path) -> set[str]:
    if not (workspace / ".git").exists():
        return set()
    result = _git(workspace, ["status", "--porcelain"], check=False)
    paths: set[str] = set()
    for line in (result.stdout or "").splitlines():
        if len(line) < 4:
            continue
        raw = line[3:].strip()
        if " -> " in raw:
            raw = raw.split(" -> ", 1)[1]
        paths.add(raw.strip('"'))
    return paths


def enforce_scope(workspace: Path, role: str, before: set[str]) -> list[str]:
    """Revert files a role is forbidden to touch when this node introduced the change."""
    if role == "tdd":
        forbidden_prefix = ("src/",)
    elif role == "implementer":
        forbidden_prefix = ("tests/",)
    else:
        return []
    if not (workspace / ".git").exists():
        return []
    after = git_snapshot(workspace)
    introduced = after - before
    illegal = [item for item in introduced if item.startswith(forbidden_prefix)]
    for relative in illegal:
        target = workspace / relative
        tracked = _git(workspace, ["ls-files", "--error-unmatch", relative], check=False)
        if tracked.returncode == 0:
            _git(workspace, ["checkout", "--", relative], check=False)
        elif target.exists() and target.is_file():
            target.unlink()
    return illegal


def file_stats(workspace: Path) -> dict[str, tuple[int, int]]:
    """Added and removed lines per path versus HEAD, with untracked files counted as additions."""
    if not (workspace / ".git").exists():
        return {}
    stats: dict[str, tuple[int, int]] = {}
    numstat = _git(workspace, ["diff", "--numstat", "HEAD"], check=False)
    for line in (numstat.stdout or "").splitlines():
        added_text, removed_text, path = (line.split("\t", 2) + ["", ""])[:3]
        if not path:
            continue
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        stats[path.strip('"')] = (
            int(added_text) if added_text.isdigit() else 0,
            int(removed_text) if removed_text.isdigit() else 0,
        )
    untracked = _git(workspace, ["ls-files", "--others", "--exclude-standard"], check=False)
    for raw in (untracked.stdout or "").splitlines():
        path = raw.strip()
        if not path or path in stats:
            continue
        target = workspace / path
        added = 0
        if target.is_file():
            try:
                added = sum(1 for _line in target.open("rb"))
            except OSError:
                added = 0
        stats[path] = (added, 0)
    return stats


def file_delta(before: dict[str, tuple[int, int]], after: dict[str, tuple[int, int]]) -> list[dict[str, int | str]]:
    """Files this turn changed, with the line counts added since the earlier snapshot."""
    changes: list[dict[str, int | str]] = []
    for path in sorted(set(before) | set(after)):
        old_added, old_removed = before.get(path, (0, 0))
        new_added, new_removed = after.get(path, (0, 0))
        added = max(0, new_added - old_added)
        removed = max(0, new_removed - old_removed)
        if added or removed:
            changes.append({"path": path, "added": added, "removed": removed})
    return changes


def relative_path(workspace: Path, path: str) -> str:
    candidate = Path(path)
    if not candidate.is_absolute():
        return path
    try:
        return str(candidate.resolve().relative_to(workspace.resolve()))
    except ValueError:
        return candidate.name or path


def diff_stat(workspace: Path) -> str:
    if not (workspace / ".git").exists():
        return "(workspace is not a git repository)"
    result = _git(workspace, ["diff", "--stat", "HEAD"], check=False)
    untracked = _git(workspace, ["ls-files", "--others", "--exclude-standard"], check=False)
    parts = [(result.stdout or "").strip(), (untracked.stdout or "").strip()]
    text = "\n".join(part for part in parts if part)
    return text[:12000] or "(clean working tree)"


def _git(workspace: Path, args: list[str], check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=workspace,
        text=True,
        capture_output=True,
        check=check,
        env={**os.environ, **GIT_ENV},
    )
