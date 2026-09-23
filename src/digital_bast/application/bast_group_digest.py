"""Aggregate PMO WhatsApp digest for the independent BAST closing campaign."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import TYPE_CHECKING, Protocol, final
from urllib.parse import urlencode, urlsplit
from uuid import uuid4

from digital_bast.application.bast_closing import closing_schedule
from digital_bast.application.payroll_reminder_delivery import PayrollDeliveryState
from digital_bast.domain.completion import DateRange
from digital_bast.domain.time import JAKARTA, month_dates

if TYPE_CHECKING:
    from digital_bast.application.bast_closing import (
        BastClosingControlService,
        BastClosingSchedule,
    )
    from digital_bast.application.bast_snapshot import (
        BastClosingSnapshot,
        BastClosingSnapshotService,
    )
    from digital_bast.application.payroll_group_digest import (
        PayrollGroupDigestDeliveryStore,
    )
    from digital_bast.application.talentops_followups import WhatsAppSendReceipt
    from digital_bast.application.workflow_control import TalentMobileSettings

_GATEWAY_UNKNOWN_ERRORS = frozenset({"delivery_outcome_unknown", "receipt_store_unhealthy"})
_MAX_APPROVAL_PREVIEW = 5
_MONTH_LABELS = (
    "Jan",
    "Feb",
    "Mar",
    "Apr",
    "Mei",
    "Jun",
    "Jul",
    "Agu",
    "Sep",
    "Okt",
    "Nov",
    "Des",
)


class BastGroupOutboundGateway(Protocol):
    async def send_group(
        self,
        group_jid: str,
        text: str,
        request_id: str,
    ) -> WhatsAppSendReceipt: ...


class BastPublicUrlSource(Protocol):
    async def talent_mobile_settings(
        self,
        scope_key: str = "default",
    ) -> TalentMobileSettings: ...


@dataclass(frozen=True, slots=True)
class BastWebLinks:
    approval_url: str
    readiness_url: str


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
    pending_approvals: int = 0


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


def _milestone(schedule: BastClosingSchedule, day: date) -> str | None:
    if day == schedule.closing_date:
        return "FINAL"
    if day == schedule.initial_date:
        return "INITIAL"
    for followup in schedule.followup_dates:
        if day == followup:
            offset = (schedule.closing_date - followup).days
            return f"EOM-{offset}"
    return None


def _milestone_label(milestone: str) -> str:
    if milestone == "FINAL":
        return "Closing"
    if milestone == "INITIAL":
        return "Initial reminder"
    if milestone.startswith("EOM-"):
        return f"H-{milestone.removeprefix('EOM-')}"
    if milestone == "MANUAL":
        return "Manual"
    return milestone


def _short_date(value: date) -> str:
    return f"{value.day} {_MONTH_LABELS[value.month - 1]}"


def _admin_links(public_url: str | None, period: DateRange) -> BastWebLinks | None:
    if not public_url:
        return None
    parsed = urlsplit(public_url.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None
    origin = f"{parsed.scheme}://{parsed.netloc}"
    query = urlencode({"year": period.start.year, "month": period.start.month})
    return BastWebLinks(
        approval_url=(
            f"{origin}/admin/talentops/actions?{query}#approval-queue"
        ),
        readiness_url=f"{origin}/admin/talentops/bast-readiness?{query}",
    )


def _domain_metrics(snapshot: BastClosingSnapshot) -> dict[str, tuple[int, int]]:
    employees: dict[str, set[str]] = {}
    issues: dict[str, int] = {}
    for talent in snapshot.talents:
        for blocker in talent.actionable:
            employees.setdefault(blocker.domain, set()).add(talent.employee_id)
            issues[blocker.domain] = issues.get(blocker.domain, 0) + max(
                len(blocker.issues),
                1,
            )
    return {
        domain: (len(employee_ids), issues.get(domain, 0))
        for domain, employee_ids in employees.items()
    }


def _talent_action_lines(snapshot: BastClosingSnapshot) -> list[str]:
    if not snapshot.need_talent_action:
        return ["✅ *Tidak ada action Talent yang tertunda.*"]

    metrics = _domain_metrics(snapshot)
    lines = [f"🟠 *Masih menunggu Talent — {snapshot.need_talent_action} orang*"]
    talent_count, issue_count = metrics.get("task", (0, 0))
    if issue_count:
        lines.append(f"• {talent_count} Talent: {issue_count} Task Redmine belum Closed")
    talent_count, issue_count = metrics.get("attendance", (0, 0))
    if issue_count:
        lines.append(
            f"• {talent_count} Talent: {issue_count} tanggal attendance belum lengkap"
        )
    talent_count, issue_count = metrics.get("timesheet", (0, 0))
    if issue_count:
        lines.append(f"• {talent_count} Talent: {issue_count} masalah timesheet")
    talent_count, issue_count = metrics.get("evidence", (0, 0))
    if issue_count:
        lines.append(
            f"• {talent_count} Talent: {issue_count} evidence wajib belum dilengkapi"
        )
    lines.extend(("", "_Satu Talent bisa punya lebih dari satu jenis kendala._"))
    return lines


def _approval_lines(
    snapshot: BastClosingSnapshot,
    links: BastWebLinks | None,
) -> list[str]:
    approvals = snapshot.pending_approvals
    if not approvals:
        return ["✅ *Tidak ada approval PMO yang menunggu.*"]

    lines = [f"🔴 *Perlu tindakan PMO — {len(approvals)} approval*"]
    for index, item in enumerate(approvals[:_MAX_APPROVAL_PREVIEW], start=1):
        lines.append(
            f"{index}. {item.name} — {_short_date(item.work_date)} — {item.change}"
        )
    remaining = len(approvals) - _MAX_APPROVAL_PREVIEW
    if remaining > 0:
        lines.append(f"+{remaining} approval lainnya")
    lines.append("")
    if links is not None:
        lines.extend(("*Review approval →*", links.approval_url))
    else:
        lines.append("Review approval di TalentOps Web → Action Center.")
    return lines


def compose_bast_group_digest(
    snapshot: BastClosingSnapshot,
    period: DateRange,
    milestone: str,
    links: BastWebLinks | None = None,
) -> str:
    lines = [
        f"*BAST Closing — {period.label()}*",
        f"Closing {_short_date(period.end)} · {_milestone_label(milestone)}",
        "",
        *_approval_lines(snapshot, links),
        "",
        *_talent_action_lines(snapshot),
        "",
        "*Progress BAST*",
        f"✅ Complete: {snapshot.complete} / {snapshot.total_talents}",
        f"🟠 Perlu action Talent: {snapshot.need_talent_action}",
        f"🕒 Menunggu PMO: {snapshot.waiting_pmo} Talent",
    ]
    if snapshot.source_review:
        lines.append(f"🔎 Source perlu dicek: {snapshot.source_review} Talent")
    if links is not None:
        lines.extend(("", "*Lihat BAST lengkap →*", links.readiness_url))
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
        public_urls: BastPublicUrlSource | None = None,
    ) -> None:
        self._scope_key = scope_key
        self._control = control
        self._snapshot = snapshot
        self._outbound = outbound
        self._deliveries = deliveries
        self._public_urls = public_urls

    async def _links(self, period: DateRange) -> BastWebLinks | None:
        if self._public_urls is None:
            return None
        settings = await self._public_urls.talent_mobile_settings(self._scope_key)
        return _admin_links(settings.public_url, period)

    async def preview(
        self,
        period: DateRange,
        milestone: str = "MANUAL",
    ) -> BastGroupDigestPreview:
        settings = await self._control.settings(self._scope_key)
        snapshot = await self._snapshot.build(period)
        links = await self._links(period)
        return BastGroupDigestPreview(
            configured=bool(settings.pmo_group_jid),
            group_jid=settings.pmo_group_jid,
            message=compose_bast_group_digest(snapshot, period, milestone, links),
            total=snapshot.total_talents,
            complete=snapshot.complete,
            need_talent_action=snapshot.need_talent_action,
            waiting_pmo=snapshot.waiting_pmo,
            source_review=snapshot.source_review,
            pending_approvals=len(snapshot.pending_approvals),
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
            return BastGroupDigestRunSummary(
                enabled=True,
                due=False,
                milestone=None,
                outcome="not_due",
            )
        period = _period(local.year, local.month)
        return await self._deliver(
            period,
            display_milestone=milestone,
            delivery_milestone=milestone,
            group_jid=settings.pmo_group_jid,
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
        if scheduled is not None:
            display_milestone = scheduled
            delivery_milestone = scheduled
            key = (
                f"bast-digest:{self._scope_key}:"
                f"{period.start.year}-{period.start.month:02d}:{scheduled}"
            )
        else:
            batch = uuid4().hex
            display_milestone = "MANUAL"
            delivery_milestone = f"MANUAL:{batch}"
            key = f"bast-digest-manual:{self._scope_key}:{batch}"
        return await self._deliver(
            period,
            display_milestone=display_milestone,
            delivery_milestone=delivery_milestone,
            group_jid=settings.pmo_group_jid,
            created_by=actor,
            idempotency_key=key,
        )

    async def _deliver(  # noqa: C901, PLR0911, PLR0913
        self,
        period: DateRange,
        *,
        display_milestone: str,
        delivery_milestone: str,
        group_jid: str | None,
        created_by: str,
        idempotency_key: str,
    ) -> BastGroupDigestRunSummary:
        if not group_jid:
            return BastGroupDigestRunSummary(
                enabled=True,
                due=True,
                milestone=display_milestone,
                outcome="group_not_configured",
            )
        snapshot = await self._snapshot.build(period)
        links = await self._links(period)
        message = compose_bast_group_digest(snapshot, period, display_milestone, links)
        cycle_id = f"bast:{period.start.year}-{period.start.month:02d}"
        reservation = await self._deliveries.reserve(
            idempotency_key=idempotency_key,
            scope_key=self._scope_key,
            cycle_id=cycle_id,
            milestone=delivery_milestone,
            group_jid=group_jid,
            message=message,
            created_by=created_by,
        )
        record = reservation.record
        if record.state is PayrollDeliveryState.SENT:
            return BastGroupDigestRunSummary(
                enabled=True,
                due=True,
                milestone=display_milestone,
                outcome="duplicate",
            )
        if record.state is PayrollDeliveryState.UNKNOWN:
            return BastGroupDigestRunSummary(
                enabled=True,
                due=True,
                milestone=display_milestone,
                outcome="unknown",
            )
        if record.state is PayrollDeliveryState.FAILED_FINAL:
            return BastGroupDigestRunSummary(
                enabled=True,
                due=True,
                milestone=display_milestone,
                outcome="failed_final",
            )
        if record.state is PayrollDeliveryState.SENDING:
            _ = await self._deliveries.finish(
                idempotency_key,
                PayrollDeliveryState.UNKNOWN,
                error_code="interrupted_after_delivery_claim",
            )
            return BastGroupDigestRunSummary(
                enabled=True,
                due=True,
                milestone=display_milestone,
                outcome="unknown",
            )

        refreshed = await self._deliveries.refresh_retryable(
            idempotency_key,
            group_jid=group_jid,
            message=message,
        )
        if refreshed is None:
            return BastGroupDigestRunSummary(
                enabled=True,
                due=True,
                milestone=display_milestone,
                outcome="unsafe_skipped",
            )
        claimed = await self._deliveries.claim(idempotency_key)
        if claimed is None:
            return BastGroupDigestRunSummary(
                enabled=True,
                due=True,
                milestone=display_milestone,
                outcome="unsafe_skipped",
            )

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
            return BastGroupDigestRunSummary(
                enabled=True,
                due=True,
                milestone=display_milestone,
                outcome="sent",
                sent=1,
            )
        if receipt.error_code in _GATEWAY_UNKNOWN_ERRORS:
            _ = await self._deliveries.finish(
                idempotency_key,
                PayrollDeliveryState.UNKNOWN,
                error_code=receipt.error_code,
            )
            return BastGroupDigestRunSummary(
                enabled=True,
                due=True,
                milestone=display_milestone,
                outcome="unknown",
            )
        if receipt.status == "bridge_unavailable":
            _ = await self._deliveries.finish(
                idempotency_key,
                PayrollDeliveryState.FAILED_RETRYABLE,
                error_code=receipt.error_code,
            )
            return BastGroupDigestRunSummary(
                enabled=True,
                due=True,
                milestone=display_milestone,
                outcome="retryable_failed",
            )
        _ = await self._deliveries.finish(
            idempotency_key,
            PayrollDeliveryState.FAILED_FINAL,
            error_code=receipt.error_code or receipt.status,
        )
        return BastGroupDigestRunSummary(
            enabled=True,
            due=True,
            milestone=display_milestone,
            outcome="failed_final",
        )
