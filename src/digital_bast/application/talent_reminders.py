"""Scheduled, context-aware Talent WhatsApp reminders for BAST closing."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Protocol, final

from digital_bast.application.bast_closing import BastClosingSettings, closing_schedule
from digital_bast.application.talentops_followups import FollowUpSendCommand
from digital_bast.domain.completion import DateRange
from digital_bast.domain.time import JAKARTA, month_dates

if TYPE_CHECKING:
    from digital_bast.application.talentops import AttentionItem, TalentOpsService
    from digital_bast.application.talentops_followups import TalentOpsFollowUpService


@dataclass(frozen=True, slots=True)
class TalentReminderRunSummary:
    enabled: bool = False
    due: bool = False
    eligible: int = 0
    sent: int = 0
    skipped: int = 0
    failed: int = 0


class ReminderControlSource(Protocol):
    async def settings(self, scope_key: str = "default") -> BastClosingSettings: ...


def _period_for(local: datetime) -> DateRange:
    dates = month_dates(local.year, local.month)
    return DateRange(dates[0], dates[-1])


def _talent_reminder_message(item: AttentionItem, period: DateRange) -> str:
    labels = {
        "attendance": "Attendance",
        "timesheet": "Timesheet",
        "task": "Task List",
        "evidence": "Evidence",
    }
    blockers = [blocker for blocker in item.blockers if blocker.issues]
    total = sum(len(blocker.issues) for blocker in blockers)
    lines = [
        f"*Kelengkapan BAST — {period.label()}*",
        "",
        f"Halo {item.name}, masih ada *{total} hal* yang perlu diperhatikan:",
        "",
    ]
    options: list[str] = []
    for blocker in blockers:
        label = labels.get(blocker.domain, blocker.domain.title())
        lines.append(f"*{label} — {len(blocker.issues)}*")
        for issue in blocker.issues[:3]:
            lines.append(f"• {issue}")
        if len(blocker.issues) > 3:
            lines.append(f"• +{len(blocker.issues) - 3} lainnya")
        lines.append("")
        options.append(label)
    if options:
        lines.append("Kamu bisa langsung balas bagian yang ingin dicek:")
        lines.extend(f"{index}. {label}" for index, label in enumerate(options, start=1))
        lines.append("")
        lines.append("Atau tulis langsung kebutuhannya dengan bahasa biasa.")
    lines.append("Status Task List mengikuti source (Redmine) dan tidak diubah dari chatbot.")
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
        settings = await self._control.settings(self._scope_key)
        if not settings.enabled or not settings.talent_reminder_enabled:
            return TalentReminderRunSummary(enabled=settings.enabled)

        schedule = closing_schedule(local.year, local.month, settings)
        due = schedule.is_talent_reminder_date(local.date()) and local.hour >= settings.send_hour
        if not due:
            return TalentReminderRunSummary(enabled=True)

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
                        f"bast-reminder:{self._scope_key}:"
                        f"{local.date().isoformat()}:{item.nrp.casefold()}"
                    ),
                    created_by="system:bast-closing",
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
            enabled=True,
            due=True,
            eligible=len(view.attention),
            sent=sent,
            skipped=skipped,
            failed=failed,
        )