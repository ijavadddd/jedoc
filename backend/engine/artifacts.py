"""Pull `<<<FILE:...>>>` documents out of model output and persist them."""

from __future__ import annotations

import re
from pathlib import Path

FILE_RE = re.compile(r"<<<FILE:(.+?)>>>\n(.*?)<<<END FILE>>>", re.S)
VERDICT_RE = re.compile(r"VERDICT:\s*(PASS|FAIL|SCALE_ISSUE)\b", re.I)


def extract_files(text: str) -> dict[str, str]:
    found: dict[str, str] = {}
    for name, body in FILE_RE.findall(text or ""):
        relative = name.strip().lstrip("/")
        if not relative or relative.startswith(".."):
            continue
        found[relative] = body.strip("\n") + "\n"
    return found


def extract_verdict(text: str) -> str | None:
    matches = VERDICT_RE.findall(text or "")
    if not matches:
        return None
    return matches[-1].upper()


def write_workspace_files(workspace: Path, files: dict[str, str]) -> list[str]:
    written: list[str] = []
    root = workspace.resolve()
    for relative, content in files.items():
        target = (root / relative).resolve()
        if root != target and root not in target.parents:
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        written.append(relative)
    return written
