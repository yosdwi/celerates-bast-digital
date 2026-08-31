from __future__ import annotations

from datetime import date

import pytest

from digital_bast.bot.llm import LlmInterpreter
from digital_bast.bot.talent_context import TalentConversationContext, TalentIntent
from digital_bast.bot.whatsapp import Intent
from digital_bast.domain.completion import DateRange


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
    client = _FakeChatClient("maaf, saya tidak mengerti")
    interpreter = LlmInterpreter(client)

    assert await interpreter.interpret("halo", date(2026, 8, 20)) is None


@pytest.mark.asyncio
async def test_interpret_returns_none_when_the_client_fails() -> None:
    client = _FakeChatClient(None)
    interpreter = LlmInterpreter(client)

    assert await interpreter.interpret("status", date(2026, 8, 20)) is None


@pytest.mark.asyncio
async def test_talent_interpretation_carries_explicit_historical_month() -> None:
    client = _FakeChatClient(
        '{"intent":"attendance","start_date":"2026-08-01","end_date":"2026-08-31"}'
    )
    interpreter = LlmInterpreter(client)

    result = await interpreter.interpret_talent(
        "attendance bulan agustus 2026", date(2026, 9, 1)
    )

    assert result is not None
    assert result.intent is TalentIntent.ATTENDANCE
    assert result.period == DateRange(date(2026, 8, 1), date(2026, 8, 31))
    assert "Previous context: none" in client.calls[0][1]


@pytest.mark.asyncio
async def test_talent_followup_reuses_previous_period_when_model_omits_dates() -> None:
    client = _FakeChatClient('{"intent":"requests","start_date":null,"end_date":null}')
    interpreter = LlmInterpreter(client)
    context = TalentConversationContext(
        TalentIntent.ATTENDANCE,
        DateRange(date(2026, 8, 1), date(2026, 8, 31)),
    )

    result = await interpreter.interpret_talent(
        "yang pending PMO mana?", date(2026, 9, 1), context
    )

    assert result is not None
    assert result.intent is TalentIntent.REQUESTS
    assert result.period == context.period
    assert "attendance 2026-08-01..2026-08-31" in client.calls[0][1]


@pytest.mark.asyncio
async def test_talent_statement_can_remain_unknown_instead_of_keyword_routing() -> None:
    client = _FakeChatClient('{"intent":"unknown","start_date":null,"end_date":null}')
    interpreter = LlmInterpreter(client)

    result = await interpreter.interpret_talent(
        "tasklist kemarin sebenarnya sudah aku isi", date(2026, 9, 1)
    )

    assert result is not None
    assert result.intent is TalentIntent.UNKNOWN
    system_prompt = client.calls[0][0]
    assert "seluruh kalimat" in system_prompt.casefold()
    assert "tasklist kemarin sebenarnya sudah aku isi" in system_prompt


@pytest.mark.asyncio
async def test_talent_interpretation_rejects_cross_month_mobile_period() -> None:
    client = _FakeChatClient(
        '{"intent":"attendance","start_date":"2026-08-20","end_date":"2026-09-01"}'
    )
    interpreter = LlmInterpreter(client)

    result = await interpreter.interpret_talent(
        "attendance 20 agustus sampai 1 september",
        date(2026, 9, 1),
    )

    assert result is None


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
