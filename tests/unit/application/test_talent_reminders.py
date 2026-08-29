from __future__ import annotations

from datetime import UTC, datetime

import pytest

from digital_bast.application.talent_reminders import TalentReminderService
from digital_bast.application.talentops import (
    AttentionItem,
    Blocker,
    CommandCenterSummary,
    CommandCenterView,
    DeliverySummary,
    PeriodView,
)
from digital_bast.application.talentops_followups import FollowUpSendCommand, FollowUpSendView
from digital_bast.application.workflow_control import NotificationSettings
from digital_bast.domain.completion import CheckState, DateRange
from digital_bast.domain.models import EmployeeRole

_NOW = datetime(2026, 8, 29, 2, 5, tzinfo=UTC)  # 09:05 Jakarta


def _settings(*, talent_days: tuple[int, ...] = (29,), hour: int = 9) -> NotificationSettings:
    return NotificationSettings(
        scope_key="default",
        attendance_immediate=False,
        rebind_immediate=False,
        reminder_hour=hour,
        talent_reminder_days=talent_days,
        pmo_reminder_days=(),
    )


def _attention() -> AttentionItem:
    return AttentionItem(
        employee_id="employee-1",
        nrp="JIMT24002",
        name="Talent Test",
        role=EmployeeRole.DEVELOPER,
        overall_state=CheckState.INCOMPLETE,
        blockers=(
            Blocker("attendance", CheckState.INCOMPLETE, ("27 Aug missing Clock Out",)),
            Blocker(
                "evidence",
                CheckState.INCOMPLETE,
                ("Task A missing evidence", "Task B missing evidence"),
            ),
        ),
    )


class Control:
    def __init__(self, settings: NotificationSettings) -> None:
        self.settings = settings

    async def notification_settings(self, scope_key: str = "default") -> NotificationSettings:
        assert scope_key == "default"
        return self.settings


class TalentOps:
    def __init__(self, attention: tuple[AttentionItem, ...] = (_attention(),)) -> None:
        self.attention = attention
        self.calls = 0

    async def command_center(self, period: DateRange) -> CommandCenterView:
        self.calls += 1
        assert period.start.isoformat() == "2026-08-01"
        assert period.end.isoformat() == "2026-08-31"
        return CommandCenterView(
            period=PeriodView(2026, 8, "2026-08-01", "2026-08-31", "1-31 Agustus 2026"),
            summary=CommandCenterSummary(1, 0, len(self.attention), 0, 0),
            attention=self.attention,
            readiness=(),
            teams=(),
            delivery=DeliverySummary(0, 0, 0, ()),
            sources=(),
        )


class FollowUps:
    def __init__(self) -> None:
        self.commands: list[FollowUpSendCommand] = []
        self.sent_keys: set[str] = set()

    async def send(self, command: FollowUpSendCommand) -> FollowUpSendView:
        self.commands.append(command)
        duplicate = command.idempotency_key in self.sent_keys
        self.sent_keys.add(command.idempotency_key)
        return FollowUpSendView(
            status="sent",
            delivery_id="delivery-1",
            provider_message_id="wa-1",
            sent_at=_NOW,
            error_code=None,
            duplicate=duplicate,
        )


@pytest.mark.asyncio
async def test_talent_reminder_sends_only_on_configured_calendar_date() -> None:
    talentops = TalentOps()
    followups = FollowUps()
    service = TalentReminderService("default", Control(_settings()), talentops, followups)  # type: ignore[arg-type]

    first = await service.run(_NOW)
    second = await service.run(_NOW)

    assert first.eligible == 1
    assert first.sent == 1
    assert second.sent == 0
    assert second.skipped == 1
    assert len(followups.commands) == 2
    assert followups.commands[0].idempotency_key == (
        "scheduled-reminder:default:2026-08-29:jimt24002"
    )
    assert "Attendance: 1 perlu tindakan" in followups.commands[0].message
    assert "Task Evidence: 2 perlu tindakan" in followups.commands[0].message


@pytest.mark.asyncio
async def test_talent_reminder_skips_wrong_date_before_hour_and_no_attention() -> None:
    wrong_date_talentops = TalentOps()
    wrong_date_followups = FollowUps()
    wrong_date = TalentReminderService(
        "default",
        Control(_settings(talent_days=(28,))),
        wrong_date_talentops,
        wrong_date_followups,
    )  # type: ignore[arg-type]
    before_talentops = TalentOps()
    before_followups = FollowUps()
    before = TalentReminderService(
        "default",
        Control(_settings(hour=10)),
        before_talentops,
        before_followups,
    )  # type: ignore[arg-type]
    empty_followups = FollowUps()
    empty = TalentReminderService(
        "default",
        Control(_settings()),
        TalentOps(()),
        empty_followups,
    )  # type: ignore[arg-type]

    wrong_date_result = await wrong_date.run(_NOW)
    before_result = await before.run(_NOW)
    empty_result = await empty.run(_NOW)

    assert wrong_date_result.eligible == 0
    assert before_result.eligible == 0
    assert empty_result.eligible == 0
    assert wrong_date_talentops.calls == 0
    assert before_talentops.calls == 0
    assert wrong_date_followups.commands == []
    assert before_followups.commands == []
    assert empty_followups.commands == []
