from __future__ import annotations

from datetime import date

from digital_bast.application.bast_closing import BastClosingSettings, closing_schedule


def test_default_campaign_is_disabled() -> None:
    settings = BastClosingSettings(scope_key="default")

    assert settings.enabled is False
    assert settings.initial_day == 25
    assert settings.followup_offsets == (3, 1)
    assert settings.send_hour == 9


def test_september_schedule_uses_day_25_and_end_of_month_offsets() -> None:
    schedule = closing_schedule(2026, 9, BastClosingSettings(scope_key="default"))

    assert schedule.initial_date == date(2026, 9, 25)
    assert schedule.followup_dates == (date(2026, 9, 27), date(2026, 9, 29))
    assert schedule.talent_reminder_dates == (
        date(2026, 9, 25),
        date(2026, 9, 27),
        date(2026, 9, 29),
    )
    assert schedule.closing_date == date(2026, 9, 30)


def test_october_schedule_tracks_31_day_month() -> None:
    schedule = closing_schedule(2026, 10, BastClosingSettings(scope_key="default"))

    assert schedule.talent_reminder_dates == (
        date(2026, 10, 25),
        date(2026, 10, 28),
        date(2026, 10, 30),
    )
    assert schedule.closing_date == date(2026, 10, 31)


def test_february_collision_is_deduplicated() -> None:
    schedule = closing_schedule(2026, 2, BastClosingSettings(scope_key="default"))

    assert schedule.initial_date == date(2026, 2, 25)
    assert schedule.followup_dates == (date(2026, 2, 27),)
    assert schedule.talent_reminder_dates == (date(2026, 2, 25), date(2026, 2, 27))
    assert schedule.closing_date == date(2026, 2, 28)
