"""Scheduled and manual Talent WhatsApp reminders for BAST closing."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Protocol, final
from uuid import uuid4

from digital_bast.application.bast_closing import BastClosingSettings, closing_schedule
from digital_bast.application.talentops_followups import FollowUpSendCommand
from digital_bast.domain.completion import DateRange
from digital_bast.domain.time import JAKARTA, month_dates

if TYPE_CHECKING:
    from digital_bast.application.bast_snapshot import BastClosingSnapshotService, BastTalentSnapshot
    from digital_bast.application.talentops_followups import TalentOpsFollowUpService


@dataclass(frozen=True, slots=True)
class TalentReminderRunSummary:
    enabled: bool = False
    due: bool = False
    eligible: int = 0
    sent: int = 0
    skipped: int = 0
    failed: int = 0


@dataclass(frozen=True, slots=True)
class BastBlastPreviewRow:
    nrp: str
    name: str
    actionable_count: int
    status: str


@dataclass(frozen=True, slots=True)
class BastBlastPreview:
    total: int
    will_send: int
    waiting_pmo: int
    complete: int
    source_review: int
    rows: tuple[BastBlastPreviewRow, ...]


@dataclass(frozen=True, slots=True)
class BastManualBlastSummary:
    batch_id: str
    eligible: int
    sent: int
    skipped: int
    failed: int
    scheduled_slot_consumed: bool


class ReminderControlSource(Protocol):
    async def settings(self, scope_key: str = "default") -> BastClosingSettings: ...


def _period_for(local: datetime) -> DateRange:
    dates = month_dates(local.year, local.month)
    return DateRange(dates[0], dates[-1])


def _talent_reminder_message(item: BastTalentSnapshot, period: DateRange) -> str:
    labels = {
        "attendance": "Attendance",
        "timesheet": "Timesheet",
        "task": "Task List",
        "evidence": "Evidence",
    }
    lines = [
        f"*Kelengkapan BAST — {period.label()}*",
        "",
        f"Halo {item.name}, masih ada *{item.actionable_count} hal* yang perlu kamu selesaikan:",
        "",
    ]
    options: list[str] = []
    for blocker in item.actionable:
        label = labels.get(blocker.domain, blocker.domain.title())
        lines.append(f"*{label} — {max(len(blocker.issues), 1)}*")
        for issue in blocker.issues[:3]:
            lines.append(f"• {issue}")
        if len(blocker.issues) > 3:
            lines.append(f"• +{len(blocker.issues) - 3} lainnya")
        lines.append("")
        options.append(label)
    lines.append("Pilih bagian yang mau dicek:")
    lines.extend(f"{index}. {label}" for index, label in enumerate(options, start=1))
    lines.extend(("", "Atau langsung tulis kebutuhannya dengan bahasa biasa."))
    if any(blocker.domain == "task" for blocker in item.actionable):
        lines.append("Status Task List mengikuti Redmine/source dan tidak diubah dari chatbot.")
    return "\n".join(lines)


@final
class TalentReminderService:
    def __init__(
        self,
        scope_key: str,
        control: ReminderControlSource,
        snapshot: BastClosingSnapshotService,
        followups: TalentOpsFollowUpService,
    ) -> None:
        self._scope_key = scope_key
        self._control = control
        self._snapshot = snapshot
        self._followups = followups

    async def preview(self, period: DateRange) -> BastBlastPreview:
        snapshot = await self._snapshot.build(period)
        rows: list[BastBlastPreviewRow] = []
        for item in snapshot.talents:
            if item.actionable:
                status = "will_send"
            elif item.waiting_pmo:
                status = "waiting_pmo"
            else:
                status = "source_review"
            rows.append(
                BastBlastPreviewRow(
                    nrp=item.nrp,
                    name=item.name,
                    actionable_count=item.actionable_count,
                    status=status,
                )
            )
        return BastBlastPreview(
            total=snapshot.total_talents,
            will_send=snapshot.need_talent_action,
            waiting_pmo=snapshot.waiting_pmo,
            complete=snapshot.complete,
            source_review=snapshot.source_review,
            rows=tuple(rows),
        )

    async def send_manual(
        self,
        period: DateRange,
        actor: str,
        now: datetime | None = None,
    ) -> BastManualBlastSummary:
        current = (now or datetime.now(UTC)).astimezone(UTC)
        local = current.astimezone(JAKARTA)
        settings = await self._control.settings(self._scope_key)
        schedule = closing_schedule(period.start.year, period.start.month, settings)
        same_period = (local.year, local.month) == (period.start.year, period.start.month)
        consumes_slot = same_period and schedule.is_talent_reminder_date(local.date())
        batch_id = uuid4().hex
        snapshot = await self._snapshot.build(period)
        sent = skipped = failed = 0

        for item in snapshot.talents:
            if not item.actionable:
                continue
            key = (
                f"bast-reminder:{self._scope_key}:{local.date().isoformat()}:{item.nrp.casefold()}"
                if consumes_slot
                else f"bast-manual:{self._scope_key}:{batch_id}:{item.nrp.casefold()}"
            )
            result = await self._followups.send(
                FollowUpSendCommand(
                    period=period,
                    nrp=item.nrp,
                    message=_talent_reminder_message(item, period),
                    idempotency_key=key,
                    created_by=actor,
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

        return BastManualBlastSummary(
            batch_id=batch_id,
            eligible=snapshot.need_talent_action,
            sent=sent,
            skipped=skipped,
            failed=failed,
            scheduled_slot_consumed=consumes_slot,
        )

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
        snapshot = await self._snapshot.build(period)
        sent = skipped = failed = 0
        for item in snapshot.talents:
            if not item.actionable:
                continue
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
            eligible=snapshot.need_talent_action,
            sent=sent,
            skipped=skipped,
            failed=failed,
        )