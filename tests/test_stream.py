import asyncio

from backend.providers.cursor_cli import CursorCLIChatModel


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
