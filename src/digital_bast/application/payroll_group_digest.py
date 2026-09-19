"""Scheduled PMO group digest for Payroll closing milestones."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Protocol, final

from digital_bast.application.attendance_closing_policy import due_milestone, payroll_cycle_for
from digital_bast.application.payroll_reminder_delivery import (
    PayrollDeliveryState,
    payroll_bridge_request_id,
)
from digital_bast.domain.time import JAKARTA

if TYPE_CHECKING:
    from digital_bast.application.attendance_closing_policy import PayrollCycle
    from digital_bast.application.payroll_closing_settings import PayrollClosingSettingsStore
    from digital_bast.application.payroll_digest import PayrollClosingDigest, PayrollDigestService
    from digital_bast.application.talentops_followups import WhatsAppSendReceipt
    from digital_bast.infrastructure.whatsapp_directory import PayrollClosingGroupSetting


@dataclass(frozen=True, slots=True)
class PayrollGroupDigestDelivery:
    idempotency_key: str
    scope_key: str
    cycle_id: str
    milestone: str
    group_jid: str
    message: str
    state: PayrollDeliveryState
    attempt_count: int
    provider_message_id: str | None = None
    error_code: str | None = None


@dataclass(frozen=True, slots=True)
class PayrollGroupDigestReservation:
    record: PayrollGroupDigestDelivery
    created: bool


@dataclass(frozen=True, slots=True)
class PayrollGroupDigestRunSummary:
    enabled: bool
    paused: bool
    milestone: str | None
    outcome: str
    sent: int = 0


class PayrollClosingGroupSource(Protocol):
    async def closing_group(self, scope_key: str) -> PayrollClosingGroupSetting: ...


class PayrollGroupOutboundGateway(Protocol):
    async def send_group(
        self,
        group_jid: str,
        text: str,
        request_id: str,
    ) -> WhatsAppSendReceipt: ...


class PayrollGroupDigestDeliveryStore(Protocol):
    async def reserve(  # noqa: PLR0913 - logical delivery identity is explicit
        self,
        *,
        idempotency_key: str,
        scope_key: str,
        cycle_id: str,
        milestone: str,
        group_jid: str,
        message: str,
        created_by: str,
    ) -> PayrollGroupDigestReservation: ...

    async def refresh_retryable(
        self,
        idempotency_key: str,
        *,
        group_jid: str,
        message: str,
    ) -> PayrollGroupDigestDelivery | None: ...

    async def claim(self, idempotency_key: str) -> PayrollGroupDigestDelivery | None: ...

    async def finish(
        self,
        idempotency_key: str,
        state: PayrollDeliveryState,
        *,
        provider_message_id: str | None = None,
        error_code: str | None = None,
    ) -> PayrollGroupDigestDelivery | None: ...


def _due_digest_milestone(
    cycle: PayrollCycle,
    now: datetime,
    *,
    reminder_hour: int,
    offsets: tuple[int, ...],
) -> str | None:
    local = now.astimezone(JAKARTA)
    if local.hour < reminder_hour:
        return None
    if local.date() == cycle.period.end:
        return "FINAL"
    milestone = due_milestone(
        cycle,
        now,
        reminder_hour=reminder_hour,
        offsets=offsets,
    )
    return None if milestone is None else milestone.label


def compose_payroll_group_digest(digest: PayrollClosingDigest, milestone: str) -> str:
    summary = digest.summary
    delivery_problems = (
        summary.delivery_retryable_failed
        + summary.delivery_final_failed
        + summary.delivery_unknown
    )
    lines = [
        f"*{digest.cycle.label} · {milestone}*",
        f"Complete: {summary.complete}",
        f"Perlu Talent: {summary.needs_talent_action}",
        f"Menunggu review: {summary.waiting_submitted}",
        "",
        f"Reminder terkirim: {summary.successfully_reminded_talents} Talent",
        f"Belum merespons: {summary.unresponded_talents}",
        f"Belum pernah terkirim: {summary.actionable_not_reminded}",
    ]
    if summary.unverified:
        lines.append(f"Perlu cek data sumber: {summary.unverified}")
    if delivery_problems:
        lines.append(
            "Delivery bermasalah: "
            f"{delivery_problems} "
            f"(retry {summary.delivery_retryable_failed}, "
            f"final {summary.delivery_final_failed}, UNKNOWN {summary.delivery_unknown})"
        )
    lines.extend(("", "Detail dan follow-up tersedia di Payroll TalentOps."))
    return "\n".join(lines)


@final
class PayrollGroupDigestService:
    def __init__(  # noqa: PLR0913, PLR0917 - explicit delivery ports are intentional
        self,
        scope_key: str,
        settings: PayrollClosingSettingsStore,
        digest: PayrollDigestService,
        groups: PayrollClosingGroupSource,
        outbound: PayrollGroupOutboundGateway,
        deliveries: PayrollGroupDigestDeliveryStore,
    ) -> None:
        self._scope_key = scope_key
        self._settings = settings
        self._digest = digest
        self._groups = groups
        self._outbound = outbound
        self._deliveries = deliveries

    async def run(  # noqa: C901, PLR0911 - explicit delivery state machine
        self,
        *,
        now: datetime | None = None,
    ) -> PayrollGroupDigestRunSummary:
        instant = now or datetime.now(JAKARTA)
        policy = await self._settings.load(self._scope_key)
        if not policy.dispatch_enabled:
            return PayrollGroupDigestRunSummary(
                enabled=policy.enabled,
                paused=policy.paused,
                milestone=None,
                outcome="disabled" if not policy.enabled else "paused",
            )

        cycle = payroll_cycle_for(
            instant.astimezone(JAKARTA).date(),
            policy.closing_day,
        )
        milestone = _due_digest_milestone(
            cycle,
            instant,
            reminder_hour=policy.reminder_hour,
            offsets=policy.reminder_offsets,
        )
        if milestone is None:
            return PayrollGroupDigestRunSummary(
                enabled=True,
                paused=False,
                milestone=None,
                outcome="not_due",
            )

        destination = await self._groups.closing_group(self._scope_key)
        if destination.group_jid is None:
            return PayrollGroupDigestRunSummary(
                enabled=True,
                paused=False,
                milestone=milestone,
                outcome="group_not_configured",
            )

        digest = await self._digest.project(
            cycle,
            now=instant,
            next_day_ready_hour=policy.next_day_ready_hour,
            target_roles=policy.target_roles,
        )
        message = compose_payroll_group_digest(digest, milestone)
        idempotency_key = f"payroll-digest:{self._scope_key}:{cycle.cycle_id}:{milestone}"
        reservation = await self._deliveries.reserve(
            idempotency_key=idempotency_key,
            scope_key=self._scope_key,
            cycle_id=cycle.cycle_id,
            milestone=milestone,
            group_jid=destination.group_jid,
            message=message,
            created_by="payroll-scheduler",
        )
        record = reservation.record
        if record.state is PayrollDeliveryState.SENT:
            return PayrollGroupDigestRunSummary(
                enabled=True,
                paused=False,
                milestone=milestone,
                outcome="duplicate",
            )
        if record.state is PayrollDeliveryState.UNKNOWN:
            return PayrollGroupDigestRunSummary(
                enabled=True,
                paused=False,
                milestone=milestone,
                outcome="unknown",
            )
        if record.state is PayrollDeliveryState.FAILED_FINAL:
            return PayrollGroupDigestRunSummary(
                enabled=True,
                paused=False,
                milestone=milestone,
                outcome="failed_final",
            )
        if record.state is PayrollDeliveryState.SENDING:
            await self._deliveries.finish(
                idempotency_key,
                PayrollDeliveryState.UNKNOWN,
                error_code="interrupted_after_delivery_claim",
            )
            return PayrollGroupDigestRunSummary(
                enabled=True,
                paused=False,
                milestone=milestone,
                outcome="unknown",
            )

        refreshed = await self._deliveries.refresh_retryable(
            idempotency_key,
            group_jid=destination.group_jid,
            message=message,
        )
        if refreshed is None:
            return PayrollGroupDigestRunSummary(
                enabled=True,
                paused=False,
                milestone=milestone,
                outcome="unsafe_skipped",
            )
        claimed = await self._deliveries.claim(idempotency_key)
        if claimed is None:
            return PayrollGroupDigestRunSummary(
                enabled=True,
                paused=False,
                milestone=milestone,
                outcome="unsafe_skipped",
            )

        receipt = await self._outbound.send_group(
            destination.group_jid,
            message,
            payroll_bridge_request_id(idempotency_key),
        )
        if receipt.status == "sent":
            await self._deliveries.finish(
                idempotency_key,
                PayrollDeliveryState.SENT,
                provider_message_id=receipt.provider_message_id,
            )
            return PayrollGroupDigestRunSummary(
                enabled=True,
                paused=False,
                milestone=milestone,
                outcome="sent",
                sent=1,
            )
        if receipt.status == "bridge_unavailable":
            await self._deliveries.finish(
                idempotency_key,
                PayrollDeliveryState.FAILED_RETRYABLE,
                error_code=receipt.error_code,
            )
            return PayrollGroupDigestRunSummary(
                enabled=True,
                paused=False,
                milestone=milestone,
                outcome="failed_retryable",
            )

        await self._deliveries.finish(
            idempotency_key,
            PayrollDeliveryState.FAILED_FINAL,
            error_code=receipt.error_code,
        )
        return PayrollGroupDigestRunSummary(
            enabled=True,
            paused=False,
            milestone=milestone,
            outcome="failed_final",
        )
