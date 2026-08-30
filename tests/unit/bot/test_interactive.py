from __future__ import annotations

import json

from digital_bast.bot.interactive import interactive


def _payload(value: str) -> dict[str, object]:
    parsed = json.loads(value)
    assert isinstance(parsed, dict)
    return parsed


def test_digit_shortcuts_defaults_to_true() -> None:
    payload = _payload(interactive("Halo", ("menu", "Menu")))
    assert payload["digitShortcuts"] is True


def test_digit_shortcuts_can_be_disabled_for_screens_with_their_own_numbered_list() -> None:
    # dm_workflow._attendance_status_reply sets this False whenever its own
    # text already asks for a bare-number reply to pick an evidence
    # candidate -- wa-session's digit-selects-a-button shortcut must not
    # shadow that more specific, pre-existing numbered flow.
    payload = _payload(
        interactive(
            "1. 21 Agustus\n\nBalas nomornya, lalu kirim foto evidence-nya.",
            ("tasklist", "Task & Evidence"),
            ("attendance", "Refresh"),
            ("menu", "Menu"),
            digit_shortcuts=False,
        )
    )
    assert payload["digitShortcuts"] is False
    assert [item["id"] for item in payload["actions"]] == ["tasklist", "attendance", "menu"]
