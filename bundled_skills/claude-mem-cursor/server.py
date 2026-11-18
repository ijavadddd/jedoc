#!/usr/bin/env python3
"""Minimal stdio MCP server: local SQLite engineering memory for Cursor CLI.

Protocol: Content-Length framed JSON-RPC, MCP methods initialize / tools/list / tools/call.
Database: JEDOC_MEMORY_DB, or .cursor/claude-mem.sqlite under the process working directory.
"""

from __future__ import annotations

import json
import os
import sqlite3
import sys
from pathlib import Path


def db_path() -> Path:
    raw = os.environ.get("JEDOC_MEMORY_DB", ".cursor/claude-mem.sqlite")
    path = Path(raw)
    if not path.is_absolute():
        path = Path.cwd() / path
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(db_path())
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS memories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            kind TEXT NOT NULL,
            content TEXT NOT NULL,
            tags TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
        """
    )
    conn.commit()
    return conn


TOOLS = [
    {
        "name": "memory_store",
        "description": "Store a compressed engineering decision, fact, constraint, or bug post-mortem.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "kind": {"type": "string", "enum": ["decision", "fact", "postmortem", "constraint"]},
                "content": {"type": "string"},
                "tags": {"type": "string", "description": "Space-separated tags"},
            },
            "required": ["title", "kind", "content"],
        },
    },
    {
        "name": "memory_search",
        "description": "Keyword search across memory title, content, and tags.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "limit": {"type": "integer", "default": 8},
            },
            "required": ["query"],
        },
    },
    {
        "name": "memory_list",
        "description": "List the newest memories.",
        "inputSchema": {
            "type": "object",
            "properties": {"limit": {"type": "integer", "default": 20}},
        },
    },
]


def tool_call(name: str, arguments: dict) -> dict:
    conn = connect()
    try:
        if name == "memory_store":
            title = str(arguments.get("title") or "").strip()
            kind = str(arguments.get("kind") or "fact").strip()
            content = str(arguments.get("content") or "").strip()
            tags = str(arguments.get("tags") or "").strip()
            if not title or not content:
                raise ValueError("title and content are required")
            if kind not in {"decision", "fact", "postmortem", "constraint"}:
                kind = "fact"
            cur = conn.execute(
                "INSERT INTO memories (title, kind, content, tags) VALUES (?, ?, ?, ?)",
                (title, kind, content, tags),
            )
            conn.commit()
            text = f"Stored memory {cur.lastrowid}: {title}"
        elif name == "memory_search":
            query = str(arguments.get("query") or "").strip()
            limit = max(1, min(50, int(arguments.get("limit") or 8)))
            like = f"%{query}%"
            rows = conn.execute(
                """
                SELECT id, title, kind, content, tags, created_at
                FROM memories
                WHERE title LIKE ? OR content LIKE ? OR tags LIKE ?
                ORDER BY id DESC
                LIMIT ?
                """,
                (like, like, like, limit),
            ).fetchall()
            if not rows:
                text = "No memories matched."
            else:
                chunks = [
                    f"[{row['id']}] {row['kind']}: {row['title']}\n{row['content']}\ntags: {row['tags']}"
                    for row in rows
                ]
                text = "\n\n".join(chunks)
        elif name == "memory_list":
            limit = max(1, min(100, int(arguments.get("limit") or 20)))
            rows = conn.execute(
                "SELECT id, title, kind, content, tags, created_at FROM memories ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
            if not rows:
                text = "Memory store is empty."
            else:
                text = "\n".join(f"[{row['id']}] {row['created_at']} {row['kind']}: {row['title']}" for row in rows)
        else:
            raise ValueError(f"unknown tool {name}")
    finally:
        conn.close()
    return {"content": [{"type": "text", "text": text}]}


def handle(message: dict) -> dict | None:
    method = message.get("method")
    msg_id = message.get("id")
    if method == "notifications/initialized" or method is None and "id" not in message:
        return None
    if method and method.startswith("notifications/"):
        return None
    try:
        if method == "initialize":
            result = {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": "jedoc-claude-mem", "version": "1.0.0"},
            }
        elif method == "ping":
            result = {}
        elif method == "tools/list":
            result = {"tools": TOOLS}
        elif method == "tools/call":
            params = message.get("params") or {}
            result = tool_call(str(params.get("name")), params.get("arguments") or {})
        else:
            if msg_id is None:
                return None
            return {
                "jsonrpc": "2.0",
                "id": msg_id,
                "error": {"code": -32601, "message": f"Method not found: {method}"},
            }
    except Exception as exc:  # noqa: BLE001 — MCP tools must return errors, not crash the stdio loop
        if msg_id is None:
            return None
        return {"jsonrpc": "2.0", "id": msg_id, "error": {"code": -32000, "message": str(exc)}}
    if msg_id is None:
        return None
    return {"jsonrpc": "2.0", "id": msg_id, "result": result}


def read_message() -> dict | None:
    headers: dict[str, str] = {}
    while True:
        line = sys.stdin.buffer.readline()
        if not line:
            return None
        if line in (b"\r\n", b"\n"):
            break
        decoded = line.decode("utf-8", errors="replace").strip()
        if ":" in decoded:
            key, value = decoded.split(":", 1)
            headers[key.strip().lower()] = value.strip()
    length = int(headers.get("content-length", "0"))
    if length <= 0:
        return None
    body = sys.stdin.buffer.read(length)
    if not body:
        return None
    return json.loads(body.decode("utf-8"))


def write_message(payload: dict) -> None:
    raw = json.dumps(payload).encode("utf-8")
    sys.stdout.buffer.write(f"Content-Length: {len(raw)}\r\n\r\n".encode("ascii") + raw)
    sys.stdout.buffer.flush()


def main() -> int:
    while True:
        message = read_message()
        if message is None:
            return 0
        response = handle(message)
        if response is not None:
            write_message(response)


if __name__ == "__main__":
    raise SystemExit(main())
