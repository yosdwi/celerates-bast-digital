from __future__ import annotations

from datetime import date

import pytest

from digital_bast.bot.llm import LlmInterpreter
from digital_bast.bot.whatsapp import Intent


class _FakeChatClient:
    def __init__(self, response: str | None) -> None:
        self.response = response
        self.calls: list[tuple[str, str]] = []

    async def complete(self, system_prompt: str, user_prompt: str) -> str | None:
        self.calls.append((system_prompt, user_prompt))
        return self.response


@pytest.mark.asyncio
async def test_interpret_parses_a_valid_command_from_the_injected_client() -> None:
    client = _FakeChatClient('{"intent": "system-status"}')
    interpreter = LlmInterpreter(client)

    command = await interpreter.interpret("status server gimana", date(2026, 8, 20))

    assert command is not None
    assert command.intent is Intent.SYSTEM_STATUS
    assert len(client.calls) == 1
    assert "2026-08-20" in client.calls[0][1]


@pytest.mark.asyncio
async def test_interpret_falls_back_to_none_on_non_json_content() -> None:
    # LlmInterpreter no longer asks the transport to force JSON output (that
    # was an Ollama-specific option) -- callers (cli._resolve_command) already
    # fall back to parse_command() on None, which is what must still happen
    # if Cloudflare's response isn't valid JSON for this schema.
    client = _FakeChatClient("maaf, saya tidak mengerti")
    interpreter = LlmInterpreter(client)

    assert await interpreter.interpret("halo", date(2026, 8, 20)) is None


@pytest.mark.asyncio
async def test_interpret_returns_none_when_the_client_fails() -> None:
    client = _FakeChatClient(None)
    interpreter = LlmInterpreter(client)

    assert await interpreter.interpret("status", date(2026, 8, 20)) is None


@pytest.mark.asyncio
async def test_choose_index_rejects_an_out_of_range_choice() -> None:
    client = _FakeChatClient('{"choice": 5}')
    interpreter = LlmInterpreter(client)

    assert await interpreter.choose_index(("A", "B"), "yang mana") is None


@pytest.mark.asyncio
async def test_choose_index_accepts_a_valid_choice() -> None:
    client = _FakeChatClient('{"choice": 2}')
    interpreter = LlmInterpreter(client)

    assert await interpreter.choose_index(("A", "B"), "yang kedua") == 2


@pytest.mark.asyncio
async def test_persona_reply_passes_through_the_client_response_directly() -> None:
    client = _FakeChatClient("Halo! Aku bot Digital BAST.")
    interpreter = LlmInterpreter(client)

    reply = await interpreter.persona_reply("kenalin dong")

    assert reply == "Halo! Aku bot Digital BAST."
    assert client.calls[0][1] == "kenalin dong"
