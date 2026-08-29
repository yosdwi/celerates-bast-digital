"""Scheduled, context-aware Talent WhatsApp reminders.

Admin chooses explicit calendar dates in TalentOps. The 15-minute notification
worker evaluates those dates against Asia/Jakarta and only contacts Talent who
still have deterministic BAST blockers at send time.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Protocol, final

from digital_bast.application.talentops_followups import FollowUpSendCommand
from digital_bast.domain.completion import DateRange
from digital_bast.domain.time import JAKARTA, month_dates

if TYPE_CHECKING:
    from digital_bast.application.talentops import AttentionItem, TalentOpsService
    from digital_bast.application.talentops_followups import TalentOpsFollowUpService
    from digital_bast.application.workflow_control import NotificationSettings


@dataclass(frozen=True, slots=True)
class TalentReminderRunSummary:
    eligible: int = 0
    sent: int = 0
    skipped: int = 0
    failed: int = 0


class ReminderControlSource(Protocol):
    async def notification_settings(self, scope_key: str = "default") -> NotificationSettings: ...


def _period_for(local: datetime) -> DateRange:
    dates = month_dates(local.year, local.month)
    return DateRange(dates[0], dates[-1])


def _talent_reminder_message(item: AttentionItem, period: DateRange) -> str:
    labels = {
        "attendance": "Attendance",
        "timesheet": "Timesheet",
        "task": "Task List",
        "evidence": "Task Evidence",
    }
    lines = [
        f"*Pengingat BAST — {period.label()}*",
        "",
        f"Halo {item.name}, masih ada yang perlu kamu lengkapi:",
    ]
    for blocker in item.blockers:
        label = labels.get(blocker.domain, blocker.domain.title())
        count = max(len(blocker.issues), 1)
        lines.append(f"• {label}: {count} perlu tindakan")
    lines.extend(
        (
            "",
            "Kirim `menu` untuk buka Status Saya, Attendance, atau Task & Evidence.",
        )
    )
    return "\n".join(lines)


@final
class TalentReminderService:
    def __init__(
        self,
        scope_key: str,
        control: ReminderControlSource,
        talentops: TalentOpsService,
        followups: TalentOpsFollowUpService,
    ) -> None:
        self._scope_key = scope_key
        self._control = control
        self._talentops = talentops
        self._followups = followups

    async def run(self, now: datetime | None = None) -> TalentReminderRunSummary:
        current = (now or datetime.now(UTC)).astimezone(UTC)
        local = current.astimezone(JAKARTA)
        settings = await self._control.notification_settings(self._scope_key)
        if (
            local.day not in settings.talent_reminder_days
            or local.hour < settings.reminder_hour
        ):
            return TalentReminderRunSummary()

        period = _period_for(local)
        view = await self._talentops.command_center(period)
        sent = 0
        skipped = 0
        failed = 0
        for item in view.attention:
            result = await self._followups.send(
                FollowUpSendCommand(
                    period=period,
                    nrp=item.nrp,
                    message=_talent_reminder_message(item, period),
                    idempotency_key=(
                        f"scheduled-reminder:{self._scope_key}:"
                        f"{local.date().isoformat()}:{item.nrp.casefold()}"
                    ),
                    created_by="system:scheduled-reminder",
                    source="deterministic",
                )
            )
            if result is None or result.status in {"not_bound", "no_blockers"}:
                skipped += 1
            elif result.status == "sent":
                sent += int(not result.duplicate)
                skipped += int(result.duplicate)
            else:
                failed += 1
        return TalentReminderRunSummary(
            eligible=len(view.attention),
            sent=sent,
            skipped=skipped,
            failed=failed,
        )
