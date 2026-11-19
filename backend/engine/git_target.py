"""Resolve the git project, branch, and optional worktree a feature runs in."""

from __future__ import annotations

import asyncio
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

from backend.config import data_dir


class GitError(RuntimeError):
    pass


def projects_root() -> Path:
    raw = os.environ.get("JEDOC_PROJECTS_ROOT", "").strip()
    if raw:
        return Path(raw).expanduser().resolve()
    home = Path.home() / "Documents" / "Projects"
    if home.is_dir():
        return home.resolve()
    return Path.home().resolve()


def list_projects() -> dict:
    root = projects_root()
    projects: list[dict[str, str]] = []
    if root.is_dir():
        for child in sorted(root.iterdir(), key=lambda item: item.name.lower()):
            if child.name.startswith(".") or not child.is_dir():
                continue
            if not (child / ".git").exists():
                continue
            projects.append(_summary(child))
    return {"root": str(root), "projects": projects}


def inspect_repo(path: str) -> dict:
    repo = _require_repo(path)
    return {
        "path": str(repo),
        "name": repo.name,
        "branch": _current_branch(repo),
        "dirty": bool(_git(repo, ["status", "--porcelain"], check=False).stdout.strip()),
        "branches": _branches(repo),
        "worktrees": _worktrees(repo),
    }


async def pick_project_folder() -> str | None:
    """Open the desktop folder dialog and return the chosen path. Cancel returns None."""
    if sys.platform == "darwin" and shutil.which("osascript"):
        return await _pick_folder_osascript()
    if shutil.which("zenity"):
        return await _pick_folder_zenity()
    raise GitError(
        "No folder dialog tool is available. On macOS use osascript (built-in); on Linux install zenity."
    )


async def _pick_folder_osascript() -> str | None:
    script = 'POSIX path of (choose folder with prompt "Select a project folder")'
    process = await asyncio.create_subprocess_exec(
        "osascript",
        "-e",
        script,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, _stderr = await asyncio.wait_for(process.communicate(), timeout=180)
    except TimeoutError:
        process.kill()
        raise GitError("The folder dialog timed out.") from None
    if process.returncode != 0:
        return None
    chosen = stdout.decode("utf-8", errors="replace").strip().rstrip("/")
    return chosen or None


async def _pick_folder_zenity() -> str | None:
    env = os.environ.copy()
    if not env.get("DISPLAY"):
        for number in ("1", "0"):
            if Path(f"/tmp/.X11-unix/X{number}").exists():
                env["DISPLAY"] = f":{number}"
                break
    if not env.get("DISPLAY"):
        raise GitError("No desktop session is available for a folder dialog.")
    process = await asyncio.create_subprocess_exec(
        "zenity",
        "--file-selection",
        "--directory",
        "--title=Select a project folder",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=env,
    )
    try:
        stdout, _stderr = await asyncio.wait_for(process.communicate(), timeout=180)
    except TimeoutError:
        process.kill()
        raise GitError("The folder dialog timed out.") from None
    if process.returncode != 0:
        return None
    chosen = stdout.decode("utf-8", errors="replace").strip()
    return chosen or None


def bind_workspace(project: str | Path, branch: str, use_worktree: bool, slug: str) -> dict:
    repo = _require_repo(str(project))
    branch = (branch or "").strip()
    if not branch:
        raise GitError("Choose a branch")
    if branch not in _branches(repo):
        raise GitError(f"Branch '{branch}' is not in {repo.name}")
    workspace = _ensure_worktree(repo, branch, slug) if use_worktree else _checkout(repo, branch)
    return {
        "project_path": str(repo),
        "branch": branch,
        "use_worktree": bool(use_worktree),
        "workspace_path": str(workspace),
    }


def _summary(path: Path) -> dict[str, str]:
    repo = path.resolve()
    return {"path": str(repo), "name": repo.name, "branch": _current_branch(repo)}


def _require_repo(path: str) -> Path:
    repo = Path(path).expanduser().resolve()
    if not repo.is_dir() or not (repo / ".git").exists():
        raise GitError(f"{repo} is not a git repository")
    return repo


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-") or "feature"


def _branches(repo: Path) -> list[str]:
    result = _git(repo, ["for-each-ref", "--format=%(refname:short)", "refs/heads"])
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def _current_branch(repo: Path) -> str:
    result = _git(repo, ["rev-parse", "--abbrev-ref", "HEAD"], check=False)
    name = (result.stdout or "").strip()
    return name if result.returncode == 0 else ""


def _worktrees(repo: Path) -> list[dict[str, str]]:
    result = _git(repo, ["worktree", "list", "--porcelain"], check=False)
    items: list[dict[str, str]] = []
    current: dict[str, str] = {}
    for line in (result.stdout or "").splitlines():
        if line.startswith("worktree "):
            if current:
                items.append(current)
            current = {"path": line.split(" ", 1)[1], "branch": "", "head": ""}
        elif line.startswith("branch ") and current:
            current["branch"] = line.split(" ", 1)[1].removeprefix("refs/heads/")
        elif line.startswith("HEAD ") and current:
            current["head"] = line.split(" ", 1)[1]
        elif line == "detached" and current:
            current["branch"] = ""
    if current:
        items.append(current)
    return items


def _ensure_worktree(repo: Path, branch: str, slug: str) -> Path:
    dest = data_dir() / "worktrees" / f"{_slug(slug)}-{_slug(branch)}"
    for item in _worktrees(repo):
        if Path(item["path"]).resolve() == dest and item["branch"] == branch:
            return dest
    if dest.exists():
        raise GitError(f"{dest} already exists and is not a worktree of {branch}")
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        _git(repo, ["worktree", "add", str(dest), branch])
    except GitError as exc:
        message = str(exc).lower()
        if "already checked out" in message or "already used" in message:
            raise GitError(
                f"Branch '{branch}' is already checked out. Turn the worktree off to use that checkout, or pick another branch."
            ) from exc
        raise
    return dest


def _checkout(repo: Path, branch: str) -> Path:
    if _current_branch(repo) == branch:
        return repo
    dirty = _git(repo, ["status", "--porcelain"], check=False).stdout.strip()
    if dirty:
        raise GitError("The project has uncommitted changes. Use a worktree, or commit before switching branches.")
    _git(repo, ["checkout", branch])
    return repo


def _git(repo: Path, args: list[str], check: bool = True) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        ["git", *args],
        cwd=repo,
        text=True,
        capture_output=True,
        check=False,
    )
    if check and result.returncode != 0:
        detail = (result.stderr or result.stdout or "git failed").strip()
        raise GitError(detail)
    return result
