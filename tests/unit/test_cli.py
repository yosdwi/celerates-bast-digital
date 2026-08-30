from __future__ import annotations

import pytest

from digital_bast import cli
from digital_bast.cli import _NRP_ATTEMPT_MAX_ECHO, _NRP_HELP, _dm_onboarding, _nrp_not_found_reply

_JID = "628123@s.whatsapp.net"


def test_echoes_the_attempted_nrp_so_the_user_knows_what_was_read() -> None:
    reply = _nrp_not_found_reply("LJIMT24002")
    assert "LJIMT24002" in reply


def test_truncates_a_long_attempt_instead_of_echoing_it_verbatim() -> None:
    attempt = "x" * (_NRP_ATTEMPT_MAX_ECHO + 20)
    reply = _nrp_not_found_reply(attempt)
    assert attempt not in reply
    assert "x" * _NRP_ATTEMPT_MAX_ECHO in reply


class _FakeActivationService:
    async def pending_claim(self, wa_jid: str) -> None:
        assert wa_jid == _JID


@pytest.mark.asyncio
async def test_onboarding_greets_a_not_yet_bound_sender_instead_of_erroring(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # "halo" from someone we don't know yet used to fall straight into NRP
    # lookup and come back as "NRP 'halo' belum aku kenali" -- a genuine
    # greeting shouldn't read as a rejected ID. It gets the same friendly
    # nudge a blank message already got.
    monkeypatch.setattr(cli, "create_activation_service", _FakeActivationService)
    for greeting in ("halo", "Hai", "MENU", "  "):
        assert await _dm_onboarding(greeting, _JID) == _NRP_HELP


@pytest.mark.asyncio
async def test_onboarding_still_rejects_a_genuinely_unrecognized_nrp(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Regression guard: only greetings/blank get the friendly nudge --
    # a real, wrong-looking NRP attempt must still get the not-found error
    # (with the attempt echoed back) so the sender knows what was read.
    monkeypatch.setattr(cli, "create_activation_service", _FakeActivationService)

    async def empty_roster() -> tuple[object, ...]:
        return ()

    monkeypatch.setattr(cli, "load_roster", empty_roster)
    reply = await _dm_onboarding("LJIMT99999", _JID)
    assert "LJIMT99999" in reply
    assert reply != _NRP_HELP
