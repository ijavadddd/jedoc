"""Cursor CLI chat model.

Invokes `agent` in print mode and normalizes stream-json events into assistant text,
tool calls, shell output, and MCP activity. Agent mode is the CLI default: `--mode`
is passed only for `plan` and `ask`, because the installed CLI rejects `--mode agent`.
"""

from __future__ import annotations

import asyncio
import errno
import fcntl
import json
import os
import pty
import re
import shutil
import signal
import struct
import termios
import time
import uuid
from typing import Any, AsyncIterator, Callable

from langchain_core.callbacks import AsyncCallbackManagerForLLMRun, CallbackManagerForLLMRun
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult
from langchain_core.messages import AIMessageChunk
from pydantic import ConfigDict, Field

from backend.config import agent_bin, resolved_execution_mode

EventSink = Callable[[dict[str, Any]], Any]

CHAT_ID_RE = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")


class CursorCLIError(RuntimeError):
    pass


def message_text(message: BaseMessage) -> str:
    content = message.content
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict):
                parts.append(str(block.get("text") or block.get("content") or ""))
        return "\n".join(part for part in parts if part)
    return str(content)


def extract_text(payload: dict[str, Any]) -> str:
    message = payload.get("message") or {}
    content = message.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        chunks = []
        for block in content:
            if isinstance(block, str):
                chunks.append(block)
            elif isinstance(block, dict) and block.get("type") in {None, "text"}:
                chunks.append(str(block.get("text") or ""))
        return "".join(chunks)
    if isinstance(payload.get("text"), str):
        return payload["text"]
    if isinstance(payload.get("delta"), str):
        return payload["delta"]
    return ""


def describe_tool_call(payload: dict[str, Any]) -> dict[str, Any]:
    tool = payload.get("tool_call") or payload.get("tool") or {}
    name = "tool"
    detail = ""
    kind = "tool_call"
    if isinstance(tool, dict):
        for key, value in tool.items():
            if not isinstance(value, dict):
                continue
            name = key.replace("ToolCall", "").replace("toolCall", "") or key
            args = value.get("args") or value.get("arguments") or value
            if isinstance(args, dict):
                detail = str(
                    args.get("command")
                    or args.get("path")
                    or args.get("file_path")
                    or args.get("uri")
                    or args.get("query")
                    or args.get("description")
                    or ""
                )
                if "shell" in key.lower() or "command" in args:
                    kind = "shell"
                elif "mcp" in key.lower():
                    kind = "mcp"
                else:
                    kind = "tool_call"
            break
        if name == "tool" and tool.get("name"):
            name = str(tool["name"])
            detail = json.dumps(tool.get("arguments") or tool.get("args") or {})
            if "mcp" in name.lower():
                kind = "mcp"
            if "shell" in name.lower() or "bash" in name.lower():
                kind = "shell"
    subtype = str(payload.get("subtype") or "")
    result = payload.get("result")
    if isinstance(result, str) and result.strip():
        detail = (detail + "\n" + result).strip()
    described = {
        "kind": kind,
        "name": name,
        "subtype": subtype,
        "detail": detail,
        "text": f"{name} {subtype} {detail}".strip(),
    }
    edit = file_edit_from_tool(payload, name)
    if edit:
        described.update(edit)
    return described


def file_edit_from_tool(payload: dict[str, Any], name: str = "") -> dict[str, Any] | None:
    """Pull a Cursor edit's path and line counts out of a tool_call payload."""
    tool = payload.get("tool_call") or payload.get("tool") or {}
    if not isinstance(tool, dict):
        return None
    path, added, removed = _scan_file_edit(tool)
    label = (name or "").lower()
    editing = any(token in label for token in ("edit", "write", "strreplace", "str_replace", "delete", "patch"))
    if not path or (not editing and added is None and removed is None):
        return None
    return {"path": path, "added": int(added or 0), "removed": int(removed or 0)}


def _scan_file_edit(node: Any, depth: int = 0) -> tuple[str, int | None, int | None]:
    path = ""
    added: int | None = None
    removed: int | None = None

    def walk(current: Any, level: int) -> None:
        nonlocal path, added, removed
        if level > 6 or not isinstance(current, dict):
            return
        for key in ("path", "file_path", "filePath", "target_file", "relativeWorkspacePath"):
            value = current.get(key)
            if isinstance(value, str) and value and not value.startswith(("http://", "https://")):
                path = value
                break
        next_added = _line_count(current.get("linesAdded") if "linesAdded" in current else current.get("lines_added"))
        next_removed = _line_count(current.get("linesRemoved") if "linesRemoved" in current else current.get("lines_removed"))
        diff = current.get("diffString") or current.get("diff")
        if isinstance(diff, str) and diff and next_added is None and next_removed is None:
            next_added = sum(1 for line in diff.splitlines() if line.startswith("+") and not line.startswith("+++"))
            next_removed = sum(1 for line in diff.splitlines() if line.startswith("-") and not line.startswith("---"))
        if next_added is not None:
            added = next_added
        if next_removed is not None:
            removed = next_removed
        for value in current.values():
            if isinstance(value, dict):
                walk(value, level + 1)

    walk(node, depth)
    return path, added, removed


def _line_count(value: Any) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return None


class CursorCLIChatModel(BaseChatModel):
    """LangChain chat model backed by `agent -p --output-format stream-json`."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    model_name: str = ""
    mode: str = "agent"
    workspace: str = "."
    chat_id: str | None = None
    force: bool = True
    trust: bool = True
    feature_id: str = ""
    agent_id: str = ""
    timeout_s: int = 900
    execution_mode: str = ""
    sink: Any = Field(default=None, exclude=True)
    cli_env: dict[str, str] = Field(default_factory=dict)
    noted_session: str = Field(default="", exclude=True)

    @property
    def _llm_type(self) -> str:
        return "cursor-cli"

    @property
    def _identifying_params(self) -> dict[str, Any]:
        return {
            "model_name": self.model_name,
            "mode": self.mode,
            "workspace": self.workspace,
            "chat_id": self.chat_id,
        }

    def _mode(self) -> str:
        return (self.execution_mode or resolved_execution_mode()).lower()

    def bind_sink(self, sink: EventSink | None) -> CursorCLIChatModel:
        self.sink = sink
        return self

    async def _emit(self, event: dict[str, Any]) -> None:
        event.setdefault("feature_id", self.feature_id)
        event.setdefault("node_id", self.agent_id)
        event.setdefault("chat_id", self.chat_id)
        sink = self.sink
        if sink is None:
            return
        result = sink(event)
        if asyncio.iscoroutine(result):
            await result

    def _build_command(self, prompt: str) -> list[str]:
        binary = agent_bin()
        if shutil.which(binary) is None and not os.path.isabs(binary):
            raise CursorCLIError(f"Cursor CLI binary '{binary}' was not found on PATH")
        command = [
            binary,
            "-p",
            "--output-format",
            "stream-json",
            "--stream-partial-output",
            "--workspace",
            self.workspace,
            "--resume",
            self.chat_id or "",
        ]
        cursor_mode = (self.mode or "agent").lower()
        if cursor_mode in {"plan", "ask"}:
            command.extend(["--mode", cursor_mode])
        elif cursor_mode != "agent":
            raise CursorCLIError(f"Unsupported cursor mode '{self.mode}'")
        if self.model_name:
            command.extend(["--model", self.model_name])
        if self.force and cursor_mode == "agent":
            command.append("--force")
        if self.trust:
            command.append("--trust")
        if cursor_mode == "agent":
            # Ask and plan stay read-only and skip MCP startup, which otherwise holds the first token.
            command.append("--approve-mcps")
            command.extend(["--sandbox", "disabled"])
        command.append(prompt)
        return command

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        text = asyncio.run(self._collect(messages))
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content=text))])

    async def _agenerate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: AsyncCallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        text = await self._collect(messages, run_manager)
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content=text))])

    async def _astream(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: AsyncCallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[ChatGenerationChunk]:
        async for delta in self._iterate(messages):
            if run_manager is not None and delta:
                await run_manager.on_llm_new_token(delta)
            yield ChatGenerationChunk(message=AIMessageChunk(content=delta))

    async def _collect(
        self,
        messages: list[BaseMessage],
        run_manager: AsyncCallbackManagerForLLMRun | None = None,
    ) -> str:
        parts: list[str] = []
        async for delta in self._iterate(messages):
            if delta:
                parts.append(delta)
                if run_manager is not None:
                    await run_manager.on_llm_new_token(delta)
        return "".join(parts).strip()

    async def _iterate(self, messages: list[BaseMessage]) -> AsyncIterator[str]:
        prompt = "\n\n".join(message_text(message) for message in messages if message_text(message))
        if self._mode() == "simulate":
            async for delta in self._simulate(prompt):
                yield delta
            return
        async for delta in self._stream_cli(prompt):
            yield delta

    async def _stream_cli(self, prompt: str) -> AsyncIterator[str]:
        if not self.chat_id:
            raise CursorCLIError("chat_id is required. Create a session before invoking the model.")
        command = self._build_command(prompt)
        process, stdout, close_terminal = await _pty_subprocess(command, cwd=self.workspace, env=_subprocess_env(self.cli_env))
        assistant = ""
        final_result = ""
        stderr_task = asyncio.create_task(self._drain_stderr(process))
        exit_task = asyncio.create_task(process.wait())
        pending_read: dict[str, asyncio.Task[bytes] | None] = {"task": None}

        async def read_stdout() -> AsyncIterator[str]:
            nonlocal assistant, final_result
            seen_tool = False
            last_text_at = 0.0
            while True:
                # Stop soon after the last answer token. Cancelling readline deadlocks the subprocess pipes,
                # so a quiet turn is ended by letting the read finish after the process is stopped.
                timeout = None
                if last_text_at:
                    timeout = max(0.1, (8.0 if seen_tool else 0.25) - (time.monotonic() - last_text_at))
                read_task = asyncio.create_task(stdout.readline())
                timer = asyncio.create_task(asyncio.sleep(timeout)) if timeout is not None else None
                waiting = {read_task, exit_task}
                if timer is not None:
                    waiting.add(timer)
                done, _pending = await asyncio.wait(waiting, return_when=asyncio.FIRST_COMPLETED)
                if exit_task in done and read_task not in done:
                    # The CLI exited, and a child can keep the terminal open. Close it so this read finishes.
                    close_terminal()
                if timer is not None and read_task not in done:
                    # The answer is out. Keep this read alive in the background so the same
                    # CLI session can finish writing the turn. Killing it here starts a new session next time.
                    timer.cancel()
                    pending_read["task"] = read_task
                    return
                if timer is not None:
                    timer.cancel()
                try:
                    line = read_task.result()
                except OSError as exc:
                    # The terminal raises EIO when the CLI closes it. That is a normal end of stream.
                    if exc.errno == errno.EIO:
                        break
                    raise
                if not line:
                    break
                raw = line.decode("utf-8", errors="replace").strip()
                if not raw:
                    continue
                try:
                    payload = json.loads(raw)
                except json.JSONDecodeError:
                    await self._emit({"type": "stream", "kind": "system", "text": raw})
                    continue
                async for delta in self._consume_payload(payload, assistant):
                    event_type, assistant, piece, final_result = delta
                    if event_type == "assistant" and piece:
                        last_text_at = time.monotonic()
                        yield piece
                    elif event_type == "tool":
                        seen_tool = True
                    if event_type in {"thinking", "assistant"} and piece:
                        # Let the chat socket flush this token before the next CLI line is parsed.
                        await asyncio.sleep(0)
                    if event_type == "result":
                        if piece and not assistant:
                            yield piece
                        return

        got_text = False
        quiet_since = time.monotonic()

        async def heartbeat() -> None:
            while True:
                await asyncio.sleep(4)
                waited = int(time.monotonic() - quiet_since)
                if waited < 4:
                    continue
                await self._emit(
                    {
                        "type": "stream",
                        "kind": "system",
                        "text": f"Cursor is working… {waited}s (waiting for the next stream event)",
                    }
                )

        pulse = asyncio.create_task(heartbeat())
        try:
            async with asyncio.timeout(self.timeout_s):
                async for piece in read_stdout():
                    if not got_text:
                        quiet_since = time.monotonic()
                    got_text = True
                    quiet_since = time.monotonic()
                    yield piece
        except TimeoutError as exc:
            self._terminate(process)
            raise CursorCLIError(f"Cursor CLI timed out after {self.timeout_s}s") from exc
        finally:
            pulse.cancel()
            try:
                await pulse
            except asyncio.CancelledError:
                pass
        if got_text:
            # The answer is already on the socket. Let the same process save the session, then stop it.
            asyncio.create_task(
                _save_cli_session(
                    process,
                    stdout,
                    stderr_task,
                    exit_task,
                    self._terminate,
                    close_terminal,
                    pending_read.get("task"),
                    self._remember_session,
                )
            )
            return
        if process.returncode is None:
            self._terminate(process)
        try:
            await asyncio.wait_for(exit_task, timeout=2)
        except TimeoutError:
            self._terminate(process, signal.SIGKILL)
            await exit_task
        try:
            stderr = await asyncio.wait_for(stderr_task, timeout=2)
        except TimeoutError:
            stderr = ""
        code = process.returncode
        if code not in (0, None):
            detail = stderr.strip() or "Cursor CLI exited with a non-zero status"
            await self._emit({"type": "stream", "kind": "system", "text": detail, "level": "error"})
            raise CursorCLIError(detail)

    async def _remember_session(self, payload: dict[str, Any]) -> None:
        """The CLI session id is the chat. Later messages resume it instead of opening another."""
        sid = payload.get("session_id")
        if not isinstance(sid, str) or not sid or sid == self.noted_session:
            return
        self.noted_session = sid
        self.chat_id = sid
        await self._emit({"type": "stream", "kind": "session", "text": sid})

    async def _consume_payload(self, payload: dict[str, Any], assistant: str):
        """Yield tuples of (kind, new_assistant_buffer, text_delta, result_text)."""
        await self._remember_session(payload)
        kind = str(payload.get("type") or "")
        if kind == "thinking":
            text = extract_text(payload) if payload.get("subtype") == "delta" else ""
            if text:
                await self._emit({"type": "stream", "kind": "thinking", "text": text})
            yield ("thinking", assistant, text, "")
            return
        if kind == "assistant":
            text = extract_text(payload)
            if text.startswith(assistant) and assistant:
                delta = text[len(assistant) :]
                assistant = text
            elif text == assistant:
                delta = ""
            else:
                delta = text
                assistant += text
            if delta:
                await self._emit({"type": "stream", "kind": "assistant", "text": delta})
            yield ("assistant", assistant, delta, "")
            return
        if kind == "tool_call":
            described = describe_tool_call(payload)
            await self._emit({"type": "stream", **described})
            yield ("tool", assistant, "", "")
            return
        if kind == "result":
            result = payload.get("result")
            text = result if isinstance(result, str) else json.dumps(result) if result is not None else ""
            if text and not assistant:
                await self._emit({"type": "stream", "kind": "assistant", "text": text})
            yield ("result", assistant, text if not assistant else "", text)
            return
        if kind in {"system", "user"}:
            # `init` is a new process attaching to the same session, not a new chat.
            if str(payload.get("subtype") or "") == "init":
                yield ("system", assistant, "", "")
                return
            text = extract_text(payload) or str(payload.get("subtype") or kind)
            await self._emit({"type": "stream", "kind": "system", "text": text})
            yield ("system", assistant, "", "")
            return
        yield ("other", assistant, "", "")

    async def _drain_stderr(self, process: asyncio.subprocess.Process) -> str:
        if process.stderr is None:
            return ""
        data = await process.stderr.read()
        return data.decode("utf-8", errors="replace")

    def _terminate(self, process: asyncio.subprocess.Process, sig: int = signal.SIGTERM) -> None:
        if process.pid is None:
            return
        try:
            os.killpg(process.pid, sig)
        except ProcessLookupError:
            pass

    async def _simulate(self, prompt: str) -> AsyncIterator[str]:
        from backend.providers.simulator import scripted_response

        text = scripted_response(self.agent_id, prompt)
        await self._emit(
            {
                "type": "stream",
                "kind": "system",
                "text": f"Simulation mode for {self.agent_id} ({self.chat_id})",
            }
        )
        chunk = 180
        for index in range(0, len(text), chunk):
            piece = text[index : index + chunk]
            await self._emit({"type": "stream", "kind": "assistant", "text": piece})
            if self.agent_id in {"tdd_spec_writer", "implementer"} and index == 0:
                await self._emit(
                    {
                        "type": "stream",
                        "kind": "tool_call",
                        "name": "edit",
                        "subtype": "completed",
                        "detail": "Wrote scoped files from the scripted response",
                        "text": "edit completed",
                    }
                )
            yield piece
            await asyncio.sleep(0.01)
        if "VERDICT: FAIL" in text:
            await self._emit(
                {
                    "type": "stream",
                    "kind": "tool_call",
                    "name": "review",
                    "subtype": "completed",
                    "detail": "VERDICT: FAIL",
                    "text": "review VERDICT: FAIL",
                }
            )


async def create_chat(
    workspace: str,
    *,
    execution_mode: str | None = None,
    cli_env: dict[str, str] | None = None,
) -> str:
    """Create a Cursor chat id via `agent create-chat`, or a stable simulated id."""
    mode = (execution_mode or resolved_execution_mode()).lower()
    if mode == "simulate":
        return f"sim_{uuid.uuid4()}"
    binary = agent_bin()
    if shutil.which(binary) is None and os.path.isabs(binary) is False:
        raise CursorCLIError(f"Cursor CLI binary '{binary}' was not found on PATH")
    attempts = [
        [binary, "--workspace", workspace, "--trust", "create-chat"],
        [binary, "create-chat"],
    ]
    errors: list[str] = []
    for command in attempts:
        process = await asyncio.create_subprocess_exec(
            *command,
            cwd=workspace,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=_subprocess_env(cli_env),
        )
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=60)
        except TimeoutError:
            process.kill()
            errors.append("create-chat timed out")
            continue
        text = (stdout or b"").decode("utf-8", errors="replace").strip()
        err = (stderr or b"").decode("utf-8", errors="replace").strip()
        if process.returncode != 0:
            errors.append(err or text or f"exit {process.returncode}")
            continue
        match = CHAT_ID_RE.search(text)
        if match:
            return match.group(0)
        for line in reversed(text.splitlines()):
            token = line.strip().strip('"')
            if token and " " not in token and len(token) >= 8:
                return token
        errors.append(text or err or "create-chat returned no id")
    raise CursorCLIError("; ".join(errors) or "unable to create a Cursor chat")


def parse_model_list(text: str) -> list[str]:
    """Pull model ids out of `agent models` text or JSON."""
    raw = (text or "").strip()
    if not raw:
        return []
    payload: Any = None
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        payload = None
    names: list[str] = []
    if isinstance(payload, dict):
        values = payload.get("models") or payload.get("data") or []
        names.extend(_model_names(values))
    elif isinstance(payload, list):
        names.extend(_model_names(payload))
    else:
        for line in raw.splitlines():
            cleaned = line.strip().lstrip("-*").strip()
            if not cleaned:
                continue
            lowered = cleaned.lower()
            if lowered.startswith(("error", "usage", "available", "model", "authentication", "run ")):
                continue
            token = cleaned.split()[0].strip(",:\"'")
            if token and re.fullmatch(r"[A-Za-z0-9_.:\[\]=,-]+", token) and not token.startswith("http"):
                names.append(token)
    ordered: list[str] = []
    for name in names:
        if name not in ordered:
            ordered.append(name)
    return ordered


def _model_names(values: Any) -> list[str]:
    names: list[str] = []
    if not isinstance(values, list):
        return names
    for item in values:
        if isinstance(item, str) and item.strip():
            names.append(item.strip())
        elif isinstance(item, dict):
            name = item.get("id") or item.get("name") or item.get("model")
            if isinstance(name, str) and name.strip():
                names.append(name.strip())
    return names


async def _save_cli_session(
    process: asyncio.subprocess.Process,
    stdout: asyncio.StreamReader,
    stderr_task: asyncio.Task[str],
    exit_task: asyncio.Task[int],
    terminate,
    close_terminal,
    pending_read: asyncio.Task[bytes] | None,
    remember_session,
) -> None:
    """Keep reading until the CLI stores this turn on the current session, then stop the process."""
    try:
        read_task = pending_read
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            if read_task is None:
                if exit_task.done():
                    break
                read_task = asyncio.create_task(stdout.readline())
            done, _pending = await asyncio.wait(
                {read_task, exit_task},
                timeout=max(0.1, deadline - time.monotonic()),
                return_when=asyncio.FIRST_COMPLETED,
            )
            if not done:
                break
            if exit_task in done and read_task not in done:
                close_terminal()
            if read_task not in done:
                break
            try:
                line = read_task.result()
            except OSError:
                break
            read_task = None
            if not line:
                break
            raw = line.decode("utf-8", errors="replace").strip()
            if not raw:
                continue
            try:
                payload = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if isinstance(payload, dict):
                await remember_session(payload)
                if payload.get("type") == "result":
                    break
        try:
            await asyncio.wait_for(exit_task, timeout=3)
        except TimeoutError:
            terminate(process)
            try:
                await asyncio.wait_for(exit_task, timeout=2)
            except TimeoutError:
                terminate(process, signal.SIGKILL)
                await exit_task
        try:
            await asyncio.wait_for(stderr_task, timeout=1)
        except TimeoutError:
            stderr_task.cancel()
    except Exception:
        return


async def _pty_subprocess(command: list[str], *, cwd: str, env: dict[str, str]):
    """Run the CLI on a wide terminal so each stream-json line is flushed immediately.

    A pipe makes Node block-buffer stdout, so a whole answer arrives in one lump.
    The returned closer shuts the terminal if the CLI exits while a child still holds it.
    """
    master, slave = pty.openpty()
    winsize = struct.pack("HHHH", 200, 2000, 0, 0)
    fcntl.ioctl(slave, termios.TIOCSWINSZ, winsize)
    process = await asyncio.create_subprocess_exec(
        *command,
        cwd=cwd,
        stdout=slave,
        stderr=asyncio.subprocess.PIPE,
        stdin=asyncio.subprocess.DEVNULL,
        start_new_session=True,
        env=env,
    )
    os.close(slave)
    reader = asyncio.StreamReader()
    protocol = asyncio.StreamReaderProtocol(reader)
    transport, _ = await asyncio.get_running_loop().connect_read_pipe(lambda: protocol, os.fdopen(master, "rb", buffering=0))

    def close_terminal() -> None:
        try:
            transport.close()
        except Exception:
            return

    return process, reader, close_terminal


def _subprocess_env(cli_env: dict[str, str] | None) -> dict[str, str]:
    env = os.environ.copy()
    for key, value in (cli_env or {}).items():
        if value:
            env[key] = value
    return env


_login_process: asyncio.subprocess.Process | None = None


async def agent_status(cli_env: dict[str, str] | None = None) -> dict[str, Any]:
    binary = agent_bin()
    resolved = shutil.which(binary) if not os.path.isabs(binary) else binary
    info: dict[str, Any] = {
        "binary": binary,
        "path": resolved,
        "installed": bool(resolved),
        "execution_mode": resolved_execution_mode(),
        "authenticated": False,
        "detail": "",
        "user": "",
    }
    if not resolved:
        info["detail"] = "agent is not on PATH"
        return info
    process = await asyncio.create_subprocess_exec(
        binary,
        "status",
        "--format",
        "json",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=_subprocess_env(cli_env),
    )
    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=20)
    except TimeoutError:
        process.kill()
        info["detail"] = "agent status timed out"
        return info
    text = ((stdout or b"") + b"\n" + (stderr or b"")).decode("utf-8", errors="replace").strip()
    info["exit_code"] = process.returncode
    parsed: Any = None
    try:
        parsed = json.loads((stdout or b"").decode("utf-8", errors="replace").strip() or "null")
    except json.JSONDecodeError:
        parsed = None
    if isinstance(parsed, dict):
        info["authenticated"] = bool(parsed.get("isAuthenticated") or parsed.get("status") == "authenticated")
        info["user"] = str(parsed.get("email") or parsed.get("user") or "")
        info["detail"] = str(parsed.get("message") or parsed.get("status") or text)[:2000]
    else:
        lowered = text.lower()
        info["detail"] = text[:2000]
        info["authenticated"] = process.returncode == 0 and (
            "logged in" in lowered or "login successful" in lowered or "authenticated" in lowered
        )
    return info


async def list_cursor_models(cli_env: dict[str, str] | None = None) -> dict[str, Any]:
    binary = agent_bin()
    resolved = shutil.which(binary) if not os.path.isabs(binary) else binary
    if not resolved:
        return {"models": [], "error": "agent is not on PATH"}
    process = await asyncio.create_subprocess_exec(
        binary,
        "models",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=_subprocess_env(cli_env),
    )
    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=30)
    except TimeoutError:
        process.kill()
        return {"models": [], "error": "agent models timed out"}
    text = ((stdout or b"") + b"\n" + (stderr or b"")).decode("utf-8", errors="replace").strip()
    models = parse_model_list((stdout or b"").decode("utf-8", errors="replace"))
    error = ""
    if process.returncode != 0 or not models:
        error = text[:1500] or f"agent models exited {process.returncode}"
    return {"models": models, "error": error if not models else ""}


async def begin_cursor_login(cli_env: dict[str, str] | None = None) -> dict[str, Any]:
    """Start `agent login` and keep it alive so the browser handshake can finish."""
    global _login_process
    binary = agent_bin()
    resolved = shutil.which(binary) if not os.path.isabs(binary) else binary
    if not resolved:
        return {"started": False, "url": "", "detail": "agent is not on PATH", "exit_code": None}
    if _login_process is not None and _login_process.returncode is None:
        return {"started": True, "url": "", "detail": "A Cursor login is already waiting in the browser.", "exit_code": None}
    process = await asyncio.create_subprocess_exec(
        binary,
        "login",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        env=_subprocess_env(cli_env),
    )
    _login_process = process
    lines: list[str] = []
    url = ""
    assert process.stdout is not None
    try:
        while len(lines) < 40:
            line = await asyncio.wait_for(process.stdout.readline(), timeout=8)
            if not line:
                break
            text = line.decode("utf-8", errors="replace").rstrip()
            lines.append(text)
            match = re.search(r"https://\S+", text)
            if match:
                url = match.group(0).rstrip(").,")
                break
    except TimeoutError:
        pass
    return {
        "started": process.returncode is None,
        "url": url,
        "detail": "\n".join(lines)[:2000],
        "exit_code": process.returncode,
    }


async def cursor_logout(cli_env: dict[str, str] | None = None) -> dict[str, Any]:
    global _login_process
    if _login_process is not None and _login_process.returncode is None:
        _login_process.kill()
        _login_process = None
    binary = agent_bin()
    resolved = shutil.which(binary) if not os.path.isabs(binary) else binary
    if not resolved:
        return {"ok": False, "detail": "agent is not on PATH"}
    process = await asyncio.create_subprocess_exec(
        binary,
        "logout",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=_subprocess_env(cli_env),
    )
    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=20)
    except TimeoutError:
        process.kill()
        return {"ok": False, "detail": "agent logout timed out"}
    text = ((stdout or b"") + b"\n" + (stderr or b"")).decode("utf-8", errors="replace").strip()
    return {"ok": process.returncode == 0, "detail": text[:1500]}
