from datetime import UTC, date, datetime, timedelta

from digital_bast.application.talent_mobile_access import (
    issue_talent_mobile_token,
    talent_mobile_binding_matches,
    verify_talent_mobile_token,
)
from digital_bast.domain.completion import DateRange


def test_talent_mobile_token_round_trip_keeps_exact_period_and_hides_jid() -> None:
    now = datetime(2026, 8, 17, 12, 0, tzinfo=UTC)
    period = DateRange(date(2026, 8, 1), date(2026, 8, 17))
    token = issue_talent_mobile_token(
        "x" * 48,
        "employee-1",
        "628123@s.whatsapp.net",
        period,
        now=now,
    )

    claims = verify_talent_mobile_token("x" * 48, token, now=now + timedelta(minutes=5))

    assert claims is not None
    assert claims.employee_id == "employee-1"
    assert claims.period == period
    assert talent_mobile_binding_matches(
        "x" * 48,
        "628123@s.whatsapp.net",
        claims.binding_tag,
    )
    assert not talent_mobile_binding_matches(
        "x" * 48,
        "628999@s.whatsapp.net",
        claims.binding_tag,
    )
    assert "628123" not in token


def test_talent_mobile_token_rejects_tampering_and_expiry() -> None:
    now = datetime(2026, 8, 31, 12, 0, tzinfo=UTC)
    period = DateRange(date(2026, 8, 1), date(2026, 8, 31))
    token = issue_talent_mobile_token(
        "x" * 48,
        "employee-1",
        "628123@s.whatsapp.net",
        period,
        now=now,
        ttl_seconds=60,
    )

    encoded, signature = token.split(".", 1)
    assert verify_talent_mobile_token("x" * 48, f"{encoded}x.{signature}", now=now) is None
    assert verify_talent_mobile_token("x" * 48, token, now=now + timedelta(seconds=61)) is None


def test_talent_mobile_token_rejects_period_longer_than_one_month() -> None:
    now = datetime(2026, 8, 31, 12, 0, tzinfo=UTC)
    token = issue_talent_mobile_token(
        "x" * 48,
        "employee-1",
        "628123@s.whatsapp.net",
        DateRange(date(2026, 8, 1), date(2026, 9, 1)),
        now=now,
    )

    assert verify_talent_mobile_token("x" * 48, token, now=now) is None
