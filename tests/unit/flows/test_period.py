from __future__ import annotations

from datetime import date

import pytest

from digital_bast import flows


def test_period_exposes_calendar_bounds_when_input_is_valid() -> None:
    period = flows.Period.parse("2024-02")

    assert period.start == date(2024, 2, 1)
    assert period.end == date(2024, 2, 29)
    assert str(period) == "2024-02"


@pytest.mark.parametrize("value", ["2024-2", "2024-13", "24-02", "2024/02", ""])
def test_period_rejects_invalid_input(value: str) -> None:
    with pytest.raises(flows.InvalidPeriodError):
        flows.Period.parse(value)
