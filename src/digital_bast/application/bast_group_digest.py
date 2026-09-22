"""Aggregate PMO WhatsApp digest for the independent BAST closing campaign."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Protocol, final
from uuid import uuid4

from digital_bast.application.bast_closing import closing_schedule
from digital_bast.application.payroll_reminder_delivery import PayrollDeliveryState
from digital_bast.domain.completion import DateRange
from digital_bast.domain.time import JAKARTA, month_dates

if TYPE_CHECKING:
    from digital_bast.application.bast_closing import BastClosingControlService, BastClosingSchedule
    from digital_bast.application.bast_snapshot import BastClosingSnapshot, BastClosingSnapshotService
    from digital_bast.application.payroll_group_digest import PayrollGroupDigestDeliveryStore
    from digital_bast.application.talentops_followups import WhatsAppSendReceipt

_GATEWAY_UNKNOWN_ERRORS = frozenset({"delivery_outcome_unknown", "receipt_store_unhealthy"})


class BastGroupOutboundGateway(Protocol):
    async def send_group(
        self,
        group_jid: str,
        text: str,
        request_id: str,
    ) -> WhatsAppSendReceipt: ...


@dataclass(frozen=True, slots=True)
class BastGroupDigestPreview:
    configured: bool
    group_jid: str | None
    message: str
    total: int
    complete: int
    need_talent_action: int
    waiting_pmo: int
    source_review: int


@dataclass(frozen=True, slots=True)
class BastGroupDigestRunSummary:
    enabled: bool
    due: bool
    milestone: str | None
    outcome: str
    sent: int = 0


def _period(year: int, month: int) -> DateRange:
    dates = month_dates(year, month)
    return DateRange(dates[0], dates[-1])


def _milestone(schedule: BastClosingSchedule, day: object) -> str | None:
    if day == schedule.closing_date:
        return "FINAL"
    if day == schedule.initial_date:
        return "INITIAL"
    for followup in schedule.followup_dates:
        if day == followup:
            offset = (schedule.closing_date - followup).days
            return f"EOM-{offset}"
    return None


def compose_bast_group_digest(snapshot: BastClosingSnapshot, period: DateRange, milestone: str) -> str:
    domain_counts = {"task": 0, "attendance": 0, "timesheet": 0, "evidence": 0}
    for talent in snapshot.talents:
        for blocker in talent.actionable:
            domain_counts[blocker.domain] = domain_counts.get(blocker.domain, 0) + max(
                len(blocker.issues),
                1,
            )
    lines = [
        f"*BAST Closing — {period.label()} · {milestone}*",
        "",
        f"Total Talent: {snapshot.total_talents}",
        f"Complete: {snapshot.complete}",
        f"Perlu action Talent: {snapshot.need_talent_action}",
        f"Menunggu PMO: {snapshot.waiting_pmo}",
    ]
    if snapshot.source_review:
        lines.append(f"Perlu cek source: {snapshot.source_review}")
    lines.extend(
        (
            "",
            "Outstanding factual:",
            f"• Task List: {domain_counts.get('task', 0)}",
            f"• Attendance: {domain_counts.get('attendance', 0)}",
            f"• Timesheet: {domain_counts.get('timesheet', 0)}",
            f"• Evidence wajib: {domain_counts.get('evidence', 0)}",
            "",
            "Detail dan review tersedia di TalentOps Web.",
        )
    )
    return "\n".join(lines)


@final
class BastGroupDigestService:
    def __init__(
        self,
        scope_key: str,
        control: BastClosingControlService,
        snapshot: BastClosingSnapshotService,
        outbound: BastGroupOutboundGateway,
        deliveries: PayrollGroupDigestDeliveryStore,
    ) -> None:
        self._scope_key = scope_key
        self._control = control
        self._snapshot = snapshot
        self._outbound = outbound
        self._deliveries = deliveries

    async def preview(self, period: DateRange, milestone: str = "MANUAL") -> BastGroupDigestPreview:
        settings = await self._control.settings(self._scope_key)
        snapshot = await self._snapshot.build(period)
        return BastGroupDigestPreview(
            configured=bool(settings.pmo_group_jid),
            group_jid=settings.pmo_group_jid,
            message=compose_bast_group_digest(snapshot, period, milestone),
            total=snapshot.total_talents,
            complete=snapshot.complete,
            need_talent_action=snapshot.need_talent_action,
            waiting_pmo=snapshot.waiting_pmo,
            source_review=snapshot.source_review,
        )

    async def run(self, now: datetime | None = None) -> BastGroupDigestRunSummary:
        instant = (now or datetime.now(UTC)).astimezone(UTC)
        local = instant.astimezone(JAKARTA)
        settings = await self._control.settings(self._scope_key)
        if not settings.enabled or not settings.pmo_summary_enabled:
            return BastGroupDigestRunSummary(
                enabled=settings.enabled,
                due=False,
                milestone=None,
                outcome="disabled",
            )
        schedule = closing_schedule(local.year, local.month, settings)
        milestone = _milestone(schedule, local.date())
        due = milestone is not None and local.hour >= settings.send_hour
        if not due or milestone is None:
            return BastGroupDigestRunSummary(True, False, None, "not_due")
        period = _period(local.year, local.month)
        return await self._deliver(
            period,
            milestone,
            settings.pmo_group_jid,
            created_by="system:bast-closing",
            idempotency_key=(
                f"bast-digest:{self._scope_key}:{local.year}-{local.month:02d}:{milestone}"
            ),
        )

    async def send_manual(
        self,
        period: DateRange,
        actor: str,
        now: datetime | None = None,
    ) -> BastGroupDigestRunSummary:
        instant = (now or datetime.now(UTC)).astimezone(UTC)
        local = instant.astimezone(JAKARTA)
        settings = await self._control.settings(self._scope_key)
        schedule = closing_schedule(period.start.year, period.start.month, settings)
        same_period = (local.year, local.month) == (period.start.year, period.start.month)
        scheduled = _milestone(schedule, local.date()) if same_period else None
        if scheduled is not None and local.hour >= settings.send_hour:
            milestone = scheduled
            key = (
                f"bast-digest:{self._scope_key}:"
                f"{period.start.year}-{period.start.month:02d}:{milestone}"
            )
        else:
            milestone = "MANUAL"
            key = f"bast-digest-manual:{self._scope_key}:{uuid4().hex}"
        return await self._deliver(
            period,
            milestone,
            settings.pmo_group_jid,
            created_by=actor,
            idempotency_key=key,
        )

    async def _deliver(  # noqa: C901, PLR0911
        self,
        period: DateRange,
        milestone: str,
        group_jid: str | None,
        *,
        created_by: str,
        idempotency_key: str,
    ) -> BastGroupDigestRunSummary:
        if not group_jid:
            return BastGroupDigestRunSummary(True, True, milestone, "group_not_configured")
        snapshot = await self._snapshot.build(period)
        message = compose_bast_group_digest(snapshot, period, milestone)
        cycle_id = f"bast:{period.start.year}-{period.start.month:02d}"
        reservation = await self._deliveries.reserve(
            idempotency_key=idempotency_key,
            scope_key=self._scope_key,
            cycle_id=cycle_id,
            milestone=milestone,
            group_jid=group_jid,
            message=message,
            created_by=created_by,
        )
        record = reservation.record
        if record.state is PayrollDeliveryState.SENT:
            return BastGroupDigestRunSummary(True, True, milestone, "duplicate")
        if record.state is PayrollDeliveryState.UNKNOWN:
            return BastGroupDigestRunSummary(True, True, milestone, "unknown")
        if record.state is PayrollDeliveryState.FAILED_FINAL:
            return BastGroupDigestRunSummary(True, True, milestone, "failed_final")
        if record.state is PayrollDeliveryState.SENDING:
            _ = await self._deliveries.finish(
                idempotency_key,
                PayrollDeliveryState.UNKNOWN,
                error_code="interrupted_after_delivery_claim",
            )
            return BastGroupDigestRunSummary(True, True, milestone, "unknown")

        refreshed = await self._deliveries.refresh_retryable(
            idempotency_key,
            group_jid=group_jid,
            message=message,
        )
        if refreshed is None:
            return BastGroupDigestRunSummary(True, True, milestone, "unsafe_skipped")
        claimed = await self._deliveries.claim(idempotency_key)
        if claimed is None:
            return BastGroupDigestRunSummary(True, True, milestone, "unsafe_skipped")

        receipt = await self._outbound.send_group(
            group_jid,
            message,
            f"bast-group:{idempotency_key}",
        )
        if receipt.status == "sent":
            _ = await self._deliveries.finish(
                idempotency_key,
                PayrollDeliveryState.SENT,
                provider_message_id=receipt.provider_message_id,
            )
            return BastGroupDigestRunSummary(True, True, milestone, "sent", sent=1)
        if receipt.error_code in _GATEWAY_UNKNOWN_ERRORS:
            _ = await self._deliveries.finish(
                idempotency_key,
                PayrollDeliveryState.UNKNOWN,
                error_code=receipt.error_code,
            )
            return BastGroupDigestRunSummary(True, True, milestone, "unknown")
        if receipt.status == "bridge_unavailable":
            _ = await self._deliveries.finish(
                idempotency_key,
                PayrollDeliveryState.FAILED_RETRYABLE,
                error_code=receipt.error_code,
            )
            return BastGroupDigestRunSummary(True, True, milestone, "retryable_failed")
        _ = await self._deliveries.finish(
            idempotency_key,
            PayrollDeliveryState.FAILED_FINAL,
            error_code=receipt.error_code or receipt.status,
        )
        return BastGroupDigestRunSummary(True, True, milestone, "failed_final")
