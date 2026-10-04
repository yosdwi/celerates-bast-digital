from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from digital_bast.application.bast_closing import BastClosingSettings
from digital_bast.application.bast_snapshot import BastClosingSnapshot, BastTalentSnapshot
from digital_bast.application.talent_reminders import (
    TalentReminderService,
    _talent_reminder_message,  # pyright: ignore[reportPrivateUsage]
)
from digital_bast.application.talentops import Blocker
from digital_bast.application.talentops_followups import FollowUpSendCommand, FollowUpSendView
from digital_bast.domain.completion import CheckState, DateRange

_NOW = datetime(2026, 8, 29, 2, 5, tzinfo=UTC)  # 09:05 Jakarta
_PERIOD = DateRange(date(2026, 8, 1), date(2026, 8, 31))


def _settings(*, initial_day: int = 29, hour: int = 9) -> BastClosingSettings:
    return BastClosingSettings(
        scope_key="default",
        enabled=True,
        initial_day=initial_day,
        followup_offsets=(),
        send_hour=hour,
        talent_reminder_enabled=True,
        pmo_summary_enabled=True,
    )


def _talent() -> BastTalentSnapshot:
    return BastTalentSnapshot(
        employee_id="employee-1",
        nrp="JIMT24002",
        name="Talent Test",
        actionable=(
            Blocker("attendance", CheckState.INCOMPLETE, ("27 Aug missing Clock Out",)),
            Blocker(
                "evidence",
                CheckState.INCOMPLETE,
                ("Task A missing evidence", "Task B missing evidence"),
            ),
        ),
        waiting_pmo=False,
        source_review=(),
    )


class Control:
    def __init__(self, settings: BastClosingSettings) -> None:
        self._settings = settings

    async def settings(self, scope_key: str = "default") -> BastClosingSettings:
        assert scope_key == "default"
        return self._settings


class Snapshot:
    def __init__(self, talents: tuple[BastTalentSnapshot, ...] = (_talent(),)) -> None:
        self.talents = talents
        self.calls = 0

    async def build(self, period: DateRange) -> BastClosingSnapshot:
        self.calls += 1
        assert period.start.isoformat() == "2026-08-01"
        assert period.end.isoformat() == "2026-08-31"
        need = sum(1 for item in self.talents if item.actionable)
        return BastClosingSnapshot(
            total_talents=len(self.talents),
            complete=0,
            need_talent_action=need,
            waiting_pmo=0,
            source_review=0,
            talents=self.talents,
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
    snapshot = Snapshot()
    followups = FollowUps()
    service = TalentReminderService("default", Control(_settings()), snapshot, followups)  # type: ignore[arg-type]

    first = await service.run(_NOW)
    second = await service.run(_NOW)

    assert first.eligible == 1
    assert first.sent == 1
    assert second.sent == 0
    assert second.skipped == 1
    assert len(followups.commands) == 2
    assert followups.commands[0].idempotency_key == "bast-reminder:default:2026-08-29:jimt24002"
    assert "*Attendance — 1*" in followups.commands[0].message
    assert "*Evidence — 2*" in followups.commands[0].message


@pytest.mark.asyncio
async def test_talent_reminder_skips_wrong_date_before_hour_and_no_attention() -> None:
    wrong_date_snapshot = Snapshot()
    wrong_date_followups = FollowUps()
    wrong_date = TalentReminderService(
        "default",
        Control(_settings(initial_day=28)),
        wrong_date_snapshot,  # type: ignore[arg-type]
        wrong_date_followups,  # type: ignore[arg-type]
    )
    before_snapshot = Snapshot()
    before_followups = FollowUps()
    before = TalentReminderService(
        "default",
        Control(_settings(hour=10)),
        before_snapshot,  # type: ignore[arg-type]
        before_followups,  # type: ignore[arg-type]
    )
    empty_followups = FollowUps()
    empty = TalentReminderService(
        "default",
        Control(_settings()),
        Snapshot(()),  # type: ignore[arg-type]
        empty_followups,  # type: ignore[arg-type]
    )

    wrong_date_result = await wrong_date.run(_NOW)
    before_result = await before.run(_NOW)
    empty_result = await empty.run(_NOW)

    assert wrong_date_result.eligible == 0
    assert before_result.eligible == 0
    assert empty_result.eligible == 0
    assert wrong_date_snapshot.calls == 0
    assert before_snapshot.calls == 0
    assert wrong_date_followups.commands == []
    assert before_followups.commands == []
    assert empty_followups.commands == []


@pytest.mark.asyncio
async def test_manual_send_on_scheduled_date_consumes_same_slot_as_scheduler() -> None:
    snapshot = Snapshot()
    followups = FollowUps()
    service = TalentReminderService("default", Control(_settings()), snapshot, followups)  # type: ignore[arg-type]

    manual = await service.send_manual(_PERIOD, "admin@example.com", _NOW)
    scheduled = await service.run(_NOW)

    assert manual.scheduled_slot_consumed is True
    assert manual.sent == 1
    assert scheduled.sent == 0
    assert scheduled.skipped == 1
    assert followups.commands[0].idempotency_key == followups.commands[1].idempotency_key
    assert followups.commands[0].idempotency_key == "bast-reminder:default:2026-08-29:jimt24002"


@pytest.mark.asyncio
async def test_manual_send_outside_scheduled_date_is_unique_ad_hoc_batch() -> None:
    snapshot = Snapshot()
    followups = FollowUps()
    service = TalentReminderService("default", Control(_settings()), snapshot, followups)  # type: ignore[arg-type]

    off_schedule = datetime(2026, 8, 20, 2, 0, tzinfo=UTC)
    first = await service.send_manual(_PERIOD, "admin@example.com", off_schedule)
    second = await service.send_manual(_PERIOD, "admin@example.com", off_schedule)

    assert first.scheduled_slot_consumed is False
    assert second.scheduled_slot_consumed is False
    assert first.sent == 1
    assert second.sent == 1
    assert followups.commands[0].idempotency_key != followups.commands[1].idempotency_key
    assert followups.commands[0].idempotency_key.startswith("bast-manual:default:")


def test_reminder_message_drops_timesheet_issues_derived_from_attendance() -> None:
    item = BastTalentSnapshot(
        employee_id="employee-1",
        nrp="JIMT24002",
        name="Talent Test",
        actionable=(
            Blocker("attendance", CheckState.INCOMPLETE, ("1 Sep missing Clock Out",)),
            Blocker(
                "timesheet",
                CheckState.INCOMPLETE,
                ("1 Sep — Timesheet belum dapat lengkap karena Log 1 PAMA belum valid.",),
            ),
            Blocker("task", CheckState.INCOMPLETE, ('Task "X" belum Closed.',)),
        ),
        waiting_pmo=False,
        source_review=(),
    )

    message = _talent_reminder_message(item, _PERIOD)

    assert "Timesheet" not in message
    assert "*2 hal*" in message
    assert "Attendance" in message
    assert "Task List" in message


def test_reminder_message_keeps_timesheet_issue_independent_of_attendance() -> None:
    item = BastTalentSnapshot(
        employee_id="employee-1",
        nrp="JIMT24002",
        name="Talent Test",
        actionable=(
            Blocker(
                "timesheet",
                CheckState.INCOMPLETE,
                (
                    "1 Sep — Timesheet belum dapat lengkap karena Log 1 PAMA belum valid.",
                    "2 Sep — Keterangan OFF pada Timesheet belum terisi.",
                ),
            ),
        ),
        waiting_pmo=False,
        source_review=(),
    )

    message = _talent_reminder_message(item, _PERIOD)

    assert "*Timesheet — 1*" in message
    assert "Keterangan OFF pada Timesheet belum terisi." in message
    assert "Log 1 PAMA belum valid" not in message
