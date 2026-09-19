from __future__ import annotations

import pytest

from digital_bast.application.payroll_closing_settings import PayrollClosingSettings


def test_payroll_closing_policy_is_safe_by_default() -> None:
    settings = PayrollClosingSettings()

    assert settings.enabled is False
    assert settings.dispatch_enabled is False
    assert settings.closing_day == 20
    assert settings.reminder_offsets == (5, 3, 1)
    assert settings.target_roles == ("Developer", "IoT Operations")
    assert settings.next_day_ready_hour == 6


def test_desired_update_normalizes_offsets_roles_and_increments_version() -> None:
    settings = PayrollClosingSettings(desired_version=3, applied_version=2)

    updated = settings.with_desired_update(
        enabled=True,
        paused=False,
        closing_day=20,
        reminder_hour=9,
        reminder_offsets=(1, 5, 3, 5),
        target_roles=("Developer", "IoT Operations", "Developer"),
        next_day_ready_hour=7,
        actor="admin@example.com",
    )

    assert updated.dispatch_enabled is True
    assert updated.reminder_offsets == (5, 3, 1)
    assert updated.target_roles == ("Developer", "IoT Operations")
    assert updated.desired_version == 4
    assert updated.applied_version == 2
    assert updated.updated_by == "admin@example.com"


def test_policy_rejects_unsupported_target_role() -> None:
    with pytest.raises(ValueError, match="unsupported role"):
        PayrollClosingSettings(target_roles=("Developer", "Unknown"))
