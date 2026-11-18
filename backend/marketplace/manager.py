"""Local skill registry. Enable, disable, edit, and materialize files into a workspace.

Nothing is downloaded. Catalog content lives in bundled_skills/. Edits are stored as
overrides in SQLite and win over the bundled file at sync time.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

from backend.config import bundled_skills_dir
from backend.storage.session_store import FeatureSessionStore

MANAGED_NAME = ".cursor/jedoc-managed.json"


class SkillError(ValueError):
    pass


class SkillManager:
    def __init__(self, store: FeatureSessionStore, root: Path | None = None) -> None:
        self.store = store
        self.root = root or bundled_skills_dir()

    def catalog(self) -> list[dict[str, Any]]:
        manifests = []
        if not self.root.exists():
            return manifests
        for manifest_path in sorted(self.root.glob("*/manifest.json")):
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["_dir"] = manifest_path.parent
            manifests.append(manifest)
        return manifests

    def get_manifest(self, skill_id: str) -> dict[str, Any]:
        for manifest in self.catalog():
            if manifest["id"] == skill_id:
                return manifest
        raise SkillError(f"Unknown skill '{skill_id}'")

    def seed_states(self) -> None:
        existing = self.store.list_skill_states()
        for manifest in self.catalog():
            if manifest["id"] not in existing:
                self.store.upsert_skill_state(manifest["id"], enabled=True, overrides={})

    def list_skills(self, workspace: str | None = None) -> list[dict[str, Any]]:
        self.seed_states()
        states = self.store.list_skill_states()
        workspace_path = Path(workspace).resolve() if workspace else None
        items = []
        for manifest in self.catalog():
            state = states.get(manifest["id"], {"enabled": True, "overrides": {}})
            overrides = state.get("overrides") or {}
            files = []
            for entry in manifest.get("files", []):
                src = entry["src"]
                content = overrides.get(src)
                if content is None:
                    content = (manifest["_dir"] / src).read_text(encoding="utf-8")
                dest = entry["dest"]
                present = bool(workspace_path and (workspace_path / dest).exists())
                files.append(
                    {
                        "path": src,
                        "dest": dest,
                        "content": content,
                        "customized": src in overrides,
                        "present_in_workspace": present,
                    }
                )
            synced = bool(files) and all(f["present_in_workspace"] for f in files if not f["dest"].endswith("mcp.json"))
            items.append(
                {
                    "id": manifest["id"],
                    "name": manifest["name"],
                    "summary": manifest["summary"],
                    "version": manifest.get("version", "1.0.0"),
                    "enabled": bool(state.get("enabled", True)),
                    "synced": synced if workspace_path else False,
                    "files": files,
                }
            )
        return items

    def set_enabled(self, skill_id: str, enabled: bool) -> dict[str, Any]:
        self.get_manifest(skill_id)
        self.store.upsert_skill_state(skill_id, enabled=enabled)
        return next(item for item in self.list_skills() if item["id"] == skill_id)

    def set_content(self, skill_id: str, relative_path: str, content: str) -> dict[str, Any]:
        manifest = self.get_manifest(skill_id)
        known = {entry["src"] for entry in manifest.get("files", [])}
        if relative_path not in known:
            raise SkillError(f"{skill_id} has no editable file '{relative_path}'")
        state = self.store.get_skill_state(skill_id)
        overrides = dict(state.get("overrides") or {})
        overrides[relative_path] = content
        if skill_id not in self.store.list_skill_states():
            self.store.upsert_skill_state(skill_id, enabled=True, overrides=overrides)
        else:
            self.store.upsert_skill_state(skill_id, overrides=overrides)
        return next(item for item in self.list_skills() if item["id"] == skill_id)

    def effective_files(self, skill_id: str) -> list[tuple[str, str, str]]:
        """Return (src, dest, content) for a skill using overrides when present."""
        manifest = self.get_manifest(skill_id)
        state = self.store.get_skill_state(skill_id)
        overrides = state.get("overrides") or {}
        files = []
        for entry in manifest.get("files", []):
            src = entry["src"]
            content = overrides.get(src)
            if content is None:
                content = (manifest["_dir"] / src).read_text(encoding="utf-8")
            files.append((src, entry["dest"], content))
        return files

    def sync(self, workspace: str, skill_ids: list[str]) -> dict[str, Any]:
        """Materialize exactly skill_ids into the workspace and remove previously managed files."""
        workspace_path = Path(workspace).resolve()
        if not workspace_path.is_dir():
            raise SkillError(f"Workspace does not exist: {workspace_path}")
        unknown = [skill_id for skill_id in skill_ids if not self._exists(skill_id)]
        if unknown:
            raise SkillError(f"Unknown skills: {', '.join(unknown)}")

        managed_path = workspace_path / MANAGED_NAME
        previous = {"files": [], "mcpServers": []}
        if managed_path.exists():
            try:
                previous = json.loads(managed_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                previous = {"files": [], "mcpServers": []}

        for rel in previous.get("files") or []:
            target = workspace_path / rel
            if target.is_file() or target.is_symlink():
                target.unlink()
            self._prune_empty(target.parent, workspace_path)

        self._remove_mcp_servers(workspace_path, previous.get("mcpServers") or [])

        written: list[str] = []
        mcp_servers: list[str] = []
        for skill_id in skill_ids:
            manifest = self.get_manifest(skill_id)
            for _src, dest, content in self.effective_files(skill_id):
                target = workspace_path / dest
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(content, encoding="utf-8")
                if dest.endswith(".py"):
                    target.chmod(0o755)
                written.append(dest)
            mcp_name = self._write_mcp(workspace_path, manifest)
            if mcp_name:
                mcp_servers.append(mcp_name)

        managed_path.parent.mkdir(parents=True, exist_ok=True)
        managed_path.write_text(
            json.dumps({"files": written, "mcpServers": mcp_servers}, indent=2) + "\n",
            encoding="utf-8",
        )
        return {"workspace": str(workspace_path), "files": written, "mcp_servers": mcp_servers, "skills": skill_ids}

    def sync_global(self, workspace: str) -> dict[str, Any]:
        self.seed_states()
        states = self.store.list_skill_states()
        enabled = [manifest["id"] for manifest in self.catalog() if states.get(manifest["id"], {}).get("enabled", True)]
        return self.sync(workspace, enabled)

    def _exists(self, skill_id: str) -> bool:
        try:
            self.get_manifest(skill_id)
        except SkillError:
            return False
        return True

    def _write_mcp(self, workspace: Path, manifest: dict[str, Any]) -> str | None:
        mcp = manifest.get("mcp")
        if not mcp:
            return None
        path = workspace / ".cursor" / "mcp.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        document: dict[str, Any] = {"mcpServers": {}}
        if path.exists():
            try:
                document = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                document = {"mcpServers": {}}
        document.setdefault("mcpServers", {})
        args = list(mcp.get("args") or [])
        if mcp.get("absolute_args"):
            args = [str((workspace / arg).resolve()) if not os.path.isabs(arg) else arg for arg in args]
        command = mcp.get("command") or sys.executable
        if command in {"python", "python3"}:
            command = sys.executable
        env = {}
        for key, value in (mcp.get("env") or {}).items():
            env[key] = str((workspace / value).resolve()) if key.endswith("DB") and not os.path.isabs(value) else value
        document["mcpServers"][mcp["server_name"]] = {"command": command, "args": args, "env": env}
        path.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
        return mcp["server_name"]

    def _remove_mcp_servers(self, workspace: Path, names: list[str]) -> None:
        path = workspace / ".cursor" / "mcp.json"
        if not path.exists() or not names:
            return
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return
        servers = document.get("mcpServers") or {}
        for name in names:
            servers.pop(name, None)
        document["mcpServers"] = servers
        path.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")

    def _prune_empty(self, directory: Path, workspace: Path) -> None:
        cursor = (workspace / ".cursor").resolve()
        current = directory.resolve()
        while current != workspace.resolve() and cursor in current.parents or current == cursor:
            try:
                current.rmdir()
            except OSError:
                break
            current = current.parent
