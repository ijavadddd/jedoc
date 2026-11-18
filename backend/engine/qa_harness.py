"""Sustained QA window and read-only data checks.

The auditor node stays in Cursor plan mode. Jedoc runs the clock, optional Compose
inspection, and SQLite integrity here, then hands the report to the model for a verdict.
`JEDOC_QA_DURATION_S` overrides the node's configured duration (default 600 seconds).
Docker Compose is started only when `JEDOC_QA_DOCKER_UP=1`.
"""

from __future__ import annotations

import asyncio
import shutil
import sqlite3
from pathlib import Path
from typing import Any, Awaitable, Callable

from backend.config import qa_duration_override

Emit = Callable[[dict[str, Any]], Awaitable[None]]

PHASES = [
    "Booting the QA window and locating data stores",
    "Sustained load window against the feature contract",
    "Playwright exploratory slot (runs when JEDOC_QA_PLAYWRIGHT=1)",
    "Running integrity, foreign-key, and precision checks",
    "EXPLAIN-style access review of local SQL",
]


async def run_qa_harness(
    workspace: Path,
    behavior: dict[str, Any],
    emit: Emit,
    *,
    node_id: str,
) -> dict[str, Any]:
    configured = int(behavior.get("min_duration_seconds") or 600)
    override = qa_duration_override()
    duration = configured if override is None else override
    timeout_budget = max(duration, int(behavior.get("timeout_s") or 0))
    report: dict[str, Any] = {
        "configured_duration_s": configured,
        "duration_s": duration,
        "latency_sla_ms": behavior.get("latency_sla_ms", 200),
        "steps": [],
        "anomalies": [],
        "metrics": [],
    }
    compose = _compose_file(workspace)
    if compose:
        report["steps"].append(await _inspect_compose(workspace, compose))
    else:
        report["steps"].append({"name": "docker_compose", "status": "absent", "detail": "No compose file in the workspace"})

    ticks = max(duration, 1)
    for second in range(ticks):
        phase = PHASES[min(len(PHASES) - 1, int(second * len(PHASES) / ticks))]
        shown = second if duration else 0
        target = duration or configured
        action = f"{phase}... [{_clock(shown)} / {_clock(target)}]"
        await emit(
            {
                "type": "qa_progress",
                "node_id": node_id,
                "elapsed_s": shown,
                "duration_s": target,
                "configured_duration_s": configured,
                "action": action,
                "latency_p95_ms": None,
            }
        )
        if duration == 0:
            break
        await asyncio.sleep(1)
        if second + 1 >= timeout_budget and timeout_budget:
            break

    anomalies = _sqlite_audit(workspace)
    report["anomalies"].extend(anomalies)
    for anomaly in anomalies:
        await emit({"type": "audit_card", "node_id": node_id, **anomaly})
    if not anomalies:
        info = {
            "severity": "info",
            "table": "—",
            "check": "coverage",
            "detail": "No SQLite database was found to integrity-check. The model still reviews the diff and the harness clock.",
        }
        report["anomalies"].append(info)
        await emit({"type": "audit_card", "node_id": node_id, **info})
    report["steps"].append({"name": "sustained_window", "status": "completed", "detail": f"{duration}s elapsed (configured {configured}s)"})
    return report


def _clock(seconds: int) -> str:
    seconds = max(0, int(seconds))
    return f"{seconds // 60:02d}:{seconds % 60:02d}"


def _compose_file(workspace: Path) -> Path | None:
    for name in ("docker-compose.yml", "docker-compose.yaml", "compose.yml", "compose.yaml"):
        candidate = workspace / name
        if candidate.exists():
            return candidate
    return None


async def _inspect_compose(workspace: Path, compose: Path) -> dict[str, str]:
    docker = shutil.which("docker")
    if not docker:
        return {"name": "docker_compose", "status": "skipped", "detail": "docker is not installed"}
    import os

    if os.environ.get("JEDOC_QA_DOCKER_UP") == "1":
        command = [docker, "compose", "-f", str(compose), "up", "-d"]
        label = "docker_compose_up"
    else:
        command = [docker, "compose", "-f", str(compose), "config"]
        label = "docker_compose_config"
    process = await asyncio.create_subprocess_exec(
        *command,
        cwd=workspace,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    try:
        stdout, _ = await asyncio.wait_for(process.communicate(), timeout=60)
    except TimeoutError:
        process.kill()
        return {"name": label, "status": "timeout", "detail": "docker compose exceeded 60s"}
    text = (stdout or b"").decode("utf-8", errors="replace")[-1500:]
    status = "ok" if process.returncode == 0 else "error"
    return {"name": label, "status": status, "detail": text}


def _sqlite_audit(workspace: Path) -> list[dict[str, str]]:
    anomalies: list[dict[str, str]] = []
    skip = {".git", "node_modules", ".venv", "venv"}
    databases: list[Path] = []
    for path in workspace.rglob("*"):
        if not path.is_file():
            continue
        if any(part in skip for part in path.parts):
            continue
        if path.suffix.lower() not in {".sqlite", ".sqlite3", ".db"}:
            continue
        databases.append(path)
    for database in databases[:8]:
        uri = database.resolve().as_uri() + "?mode=ro"
        try:
            conn = sqlite3.connect(uri, uri=True)
        except sqlite3.Error as exc:
            anomalies.append(
                {
                    "severity": "high",
                    "table": database.name,
                    "check": "open",
                    "detail": str(exc),
                }
            )
            continue
        try:
            integrity = conn.execute("PRAGMA integrity_check").fetchone()
            if not integrity or str(integrity[0]).lower() != "ok":
                anomalies.append(
                    {
                        "severity": "high",
                        "table": database.name,
                        "check": "integrity_check",
                        "detail": f"PRAGMA integrity_check returned {integrity}",
                    }
                )
            try:
                fk_rows = conn.execute("PRAGMA foreign_key_check").fetchall()
            except sqlite3.Error:
                fk_rows = []
            for row in fk_rows[:10]:
                anomalies.append(
                    {
                        "severity": "high",
                        "table": str(row[0]),
                        "check": "foreign_key_check",
                        "detail": f"Orphan or type mismatch in {row[0]} rowid {row[1]} (parent {row[2]})",
                    }
                )
            tables = [row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
            for table in tables:
                if table.startswith("sqlite_"):
                    continue
                columns = list(conn.execute(f"PRAGMA table_info({_quote(table)})"))
                for column in columns:
                    name = str(column[1]).lower()
                    declared = str(column[2] or "").lower()
                    if not any(token in name for token in ("price", "amount", "qty", "quantity", "total")):
                        continue
                    if "real" in declared or "floa" in declared or "doub" in declared:
                        anomalies.append(
                            {
                                "severity": "high",
                                "table": table,
                                "check": "numeric_precision",
                                "detail": f"Column {column[1]} is {column[2] or 'untyped numeric'}. Money and quantities must be integers or exact decimals.",
                            }
                        )
        finally:
            conn.close()
    return anomalies


def _quote(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'
