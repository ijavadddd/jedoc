import asyncio
import signal

from backend.providers import cursor_cli as cursor_cli_mod
from backend.providers.cursor_cli import CursorCLIChatModel, kill_feature_cli_processes, track_cli_process


def test_thinking_delta_is_emitted_before_the_answer():
    model = CursorCLIChatModel(execution_mode="simulate")
    seen: list[dict] = []

    async def sink(event):
        seen.append(event)

    model.bind_sink(sink)

    async def run():
        async for _item in model._consume_payload({"type": "thinking", "subtype": "delta", "text": "The user"}, ""):
            pass
        async for _item in model._consume_payload(
            {"type": "assistant", "message": {"role": "assistant", "content": [{"type": "text", "text": "pong"}]}},
            "",
        ):
            pass

    asyncio.run(run())
    assert [item["kind"] for item in seen] == ["thinking", "assistant"]
    assert seen[0]["text"] == "The user"
    assert seen[1]["text"] == "pong"


def test_init_event_keeps_the_same_cli_session():
    model = CursorCLIChatModel(execution_mode="simulate", chat_id="chat-1")
    seen: list[dict] = []

    async def sink(event):
        seen.append(event)

    model.bind_sink(sink)

    async def run():
        async for _item in model._consume_payload({"type": "system", "subtype": "init", "session_id": "chat-1"}, ""):
            pass
        async for _item in model._consume_payload({"type": "system", "subtype": "init", "session_id": "chat-1"}, ""):
            pass

    asyncio.run(run())
    assert [item["kind"] for item in seen] == ["session"]
    assert seen[0]["text"] == "chat-1"
    assert model.chat_id == "chat-1"


def test_kill_feature_cli_processes_terminates_tracked_agents(monkeypatch):
    class FakeProc:
        def __init__(self, pid: int):
            self.pid = pid
            self.returncode = None

        async def wait(self):
            self.returncode = -9
            return self.returncode

        def send_signal(self, sig):
            self.returncode = -int(sig)

    killed: list[tuple[int, int]] = []

    def fake_killpg(pid, sig):
        killed.append((pid, int(sig)))

    monkeypatch.setattr(cursor_cli_mod.os, "killpg", fake_killpg)
    closed: list[int] = []
    track_cli_process("feat-kill", FakeProc(77), lambda: closed.append(1))
    assert asyncio.run(kill_feature_cli_processes("feat-kill")) == 1
    assert closed == [1]
    assert (77, int(signal.SIGTERM)) in killed
    assert asyncio.run(kill_feature_cli_processes("feat-kill")) == 0
