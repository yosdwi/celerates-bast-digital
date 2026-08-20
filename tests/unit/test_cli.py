from __future__ import annotations

from digital_bast.cli import _NRP_ATTEMPT_MAX_ECHO, _nrp_not_found_reply


def test_echoes_the_attempted_nrp_so_the_user_knows_what_was_read() -> None:
    reply = _nrp_not_found_reply("LJIMT24002")
    assert "LJIMT24002" in reply


def test_truncates_a_long_attempt_instead_of_echoing_it_verbatim() -> None:
    attempt = "x" * (_NRP_ATTEMPT_MAX_ECHO + 20)
    reply = _nrp_not_found_reply(attempt)
    assert attempt not in reply
    assert "x" * _NRP_ATTEMPT_MAX_ECHO in reply
