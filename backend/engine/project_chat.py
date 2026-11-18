"""A provider chat bound to a project folder, outside the pipeline."""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from langchain_core.messages import HumanMessage

from backend.config import default_model_override
from backend.engine.workspace import file_delta, file_stats, relative_path
from backend.providers.cursor_cli import CursorCLIChatModel, agent_status, create_chat
from backend.storage.session_store import FeatureSessionStore

_CLI_MODE = {"ask": "ask", "plan": "plan", "agent": "agent", "debug": "agent", "multitask": "agent"}
_ready_until: dict[str, float] = {}


async def provider_ready(store: FeatureSessionStore, provider: str) -> bool:
    """An enabled, authorized Cursor account is enough. Pipeline simulate mode does not block this chat."""
    row = next((item for item in store.list_providers() if item["id"] == provider), None)
    if row is None or not row.get("enabled"):
        _ready_until.pop(provider, None)
        return False
    if _ready_until.get(provider, 0) > time.monotonic():
        return True
    if row.get("has_api_key"):
        _ready_until[provider] = time.monotonic() + 60
        return True
    status = await agent_status(store.provider_credentials(provider))
    ready = bool(status.get("installed") and status.get("authenticated"))
    if ready:
        _ready_until[provider] = time.monotonic() + 60
    return ready


async def iter_project_chat(
    store: FeatureSessionStore,
    *,
    workspace: str,
    message: str,
    mode: str,
    model: str,
    provider: str,
    thread_id: str = "",
) -> AsyncIterator[dict[str, Any]]:
    path = str(Path(workspace).expanduser().resolve())
    cli_mode = _CLI_MODE.get(mode)
    if cli_mode is None:
        raise ValueError("Mode must be agent, plan, debug, multitask, or ask")
    provider_id = provider or "cursor"
    if not await provider_ready(store, provider_id):
        yield {"type": "error", "detail": "No provider found"}
        return
    record = store.project_chat(path, thread_id or None)
    if not record:
        yield {"type": "error", "detail": "That chat is not in this project"}
        return
    thread_id = str(record["thread_id"])
    session_id = record["chat_id"]
    # One Jedoc thread is one Cursor CLI session. A new id is created only for the first message
    # of a thread. Opening a previous thread resumes that same session.
    fresh = not session_id or str(session_id).startswith("sim_")
    credentials = store.provider_credentials(provider_id)
    if fresh:
        session_id = await create_chat(path, execution_mode="live", cli_env=credentials)
        store.set_project_chat_id(path, session_id, thread_id)
    chat_id = session_id
    store.append_project_message(path, "user", message, mode, thread_id)
    yield {"type": "ack", "chat_id": chat_id, "thread_id": thread_id, "workspace": path}
    stats_before = file_stats(Path(path))
    live_files: dict[str, dict[str, Any]] = {}
    if fresh:
        stance = "Answer questions about the project. Do not edit files." if mode == "ask" else "Carry out the requested change inside this folder."
        prompt = f"You are the Jedoc project assistant, outside the pipeline. The project folder is {path}. {stance}\n\n{message}"
    else:
        prompt = message
    llm = CursorCLIChatModel(
        model_name=default_model_override() or model,
        mode=cli_mode,
        workspace=path,
        chat_id=chat_id,
        force=cli_mode == "agent",
        execution_mode="live",
        trust=True,
        feature_id="",
        agent_id="project_assistant",
        timeout_s=900,
        cli_env=credentials,
    )
    queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()

    async def on_cli(event: dict[str, Any]) -> None:
        if event.get("type") != "stream":
            return
        kind = str(event.get("kind") or "")
        text = event.get("text") if isinstance(event.get("text"), str) else ""
        if kind == "tool_call" and event.get("subtype") == "completed" and isinstance(event.get("path"), str):
            relative = relative_path(Path(path), event["path"])
            current = live_files.setdefault(relative, {"path": relative, "added": 0, "removed": 0})
            current["added"] += int(event.get("added") or 0)
            current["removed"] += int(event.get("removed") or 0)
            await queue.put({"type": "files", "files": list(live_files.values())})
        if not text:
            return
        if kind == "session" and text and text != chat_id:
            store.set_project_chat_id(path, text, thread_id)
        elif kind == "thinking":
            await queue.put({"type": "thinking", "text": text})
        elif kind == "assistant":
            await queue.put({"type": "delta", "text": text})
        elif kind == "system":
            await queue.put({"type": "thinking", "text": f"{text}\n"})
        elif kind in {"tool_call", "shell", "mcp"}:
            await queue.put({"type": "thinking", "text": f"\n{text}\n"})

    llm.bind_sink(on_cli)

    async def run() -> None:
        try:
            async for _chunk in llm.astream([HumanMessage(content=prompt)]):
                pass
        except Exception as exc:
            await queue.put({"type": "error", "detail": str(exc) or "The provider chat failed", "chat_id": chat_id})
        finally:
            await queue.put(None)

    task = asyncio.create_task(run())
    parts: list[str] = []
    failed = False
    try:
        while True:
            event = await queue.get()
            if event is None:
                break
            if event.get("type") == "delta" and isinstance(event.get("text"), str):
                parts.append(event["text"])
            if event.get("type") == "error":
                failed = True
                store.append_project_message(path, "assistant", str(event.get("detail") or "The provider chat failed"), mode, thread_id)
            yield event
    finally:
        task.cancel()
    if failed:
        return
    full = "".join(parts).strip() or "(The provider returned an empty reply.)"
    changes = file_delta(stats_before, file_stats(Path(path)))
    if not changes and live_files:
        changes = list(live_files.values())
    store.append_project_message(path, "assistant", full, mode, thread_id, changes)
    yield {"type": "done", "content": full, "chat_id": chat_id, "thread_id": thread_id, "workspace": path, "files": changes}
