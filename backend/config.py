"""Runtime paths and execution settings. Values are read lazily so tests can override env."""

from __future__ import annotations

import os
import shutil
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def data_dir() -> Path:
    return Path(os.environ.get("JEDOC_DATA_DIR", REPO_ROOT / "data")).expanduser().resolve()


def bundled_skills_dir() -> Path:
    return Path(os.environ.get("JEDOC_BUNDLED_SKILLS", REPO_ROOT / "bundled_skills")).expanduser().resolve()


def db_path() -> Path:
    return data_dir() / "jedoc.sqlite"


def checkpoint_path() -> Path:
    return data_dir() / "checkpoints.sqlite"


def execution_mode() -> str:
    """live | simulate | auto.

    auto uses the Cursor CLI when the `agent` binary is on PATH, otherwise simulation.
    """
    mode = os.environ.get("JEDOC_EXECUTION_MODE", "auto").strip().lower()
    if mode not in {"live", "simulate", "auto"}:
        return "auto"
    return mode


def resolved_execution_mode() -> str:
    mode = execution_mode()
    if mode == "auto":
        return "live" if shutil.which(agent_bin()) else "simulate"
    return mode


def agent_bin() -> str:
    return os.environ.get("JEDOC_AGENT_BIN", "agent")


def qa_duration_override() -> int | None:
    raw = os.environ.get("JEDOC_QA_DURATION_S")
    if raw is None or raw == "":
        return None
    return max(0, int(raw))


def default_model_override() -> str:
    return os.environ.get("JEDOC_DEFAULT_MODEL", "").strip()


def cors_origins() -> list[str]:
    raw = os.environ.get("JEDOC_CORS_ORIGINS", "http://127.0.0.1:5173,http://localhost:5173")
    return [item.strip() for item in raw.split(",") if item.strip()]
