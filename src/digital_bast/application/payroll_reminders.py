"""Scheduled and explicit Payroll attendance reminders over current closing truth."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Protocol, final
from uuid import NAMESPACE_URL, uuid5

from digital_bast.application.attendance_closing_policy import due_milestone, payroll_cycle_for
from digital_bast.application.payroll_reminder_delivery import (
    PayrollDeliveryState,
    payroll_bridge_request_id,
)
from digital_bast.bot.attendance_reminder import compose_attendance_reminder
from digital_bast.domain.time import JAKARTA

if TYPE_CHECKING:
    from uuid import UUID

    from digital_bast.application.attendance_closing_policy import PayrollCycle
    from digital_bast.application.payroll_closing_settings import (
        PayrollClosingSettings,
        PayrollClosingSettingsStore,
    )
    from digital_bast.application.payroll_read import PayrollOverview, PayrollTalentView
    from digital_bast.application.payroll_reminder_delivery import (
        PayrollDeliveryRecord,
        PayrollReminderDeliveryStore,
    )
    from digital_bast.application.talentops_followups import (
        WhatsAppIdentityResolver,
        WhatsAppOutboundGateway,
    )
    from digital_bast.bot.attendance_context import AttendanceReminderContext

_CONTEXT_TTL = timedelta(days=7)
_SCHEDULED_BY = "payroll-scheduler"
_MANUAL_BY = "payroll-manual"


class PayrollOverviewReader(Protocol):
    async def overview(
        self,
        cycle: PayrollCycle,
        *,
        now: datetime,
        next_day_ready_hour: int = 6,
    ) -> PayrollOverview: ...


class AttendanceContextWriter(Protocol):
    async def save(self, wa_jid: str, context: AttendanceReminderContext) -> None: ...


@dataclass(frozen=True, slots=True)
class PayrollReminderRunSummary:
    enabled: bool
    paused: bool
    due_milestone: str | None
    policy_version: int
    evaluated_talents: int = 0
    actionable_talents: int = 0
    sent: int = 0
    duplicate: int = 0
    unbound: int = 0
    retryable_failed: int = 0
    final_failed: int = 0
    unknown: int = 0
    unsafe_skipped: int = 0


@dataclass(frozen=True, slots=True)
class PayrollManualReminderPreview:
    employee_id: str
    eligible: bool
    outcome: str
    actionable_days: int = 0
    message: str | None = None


@dataclass(frozen=True, slots=True)
class PayrollManualReminderResult:
    employee_id: str
    outcome: str
    sent: bool


def _delivery_order(record: PayrollDeliveryRecord) -> tuple[datetime, datetime, str]:
    minimum = datetime.min.replace(tzinfo=UTC)
    return record.reserved_at or minimum, record.sent_at or minimum, record.id


@final
class PayrollTalentReminderService:
    def __init__(  # noqa: PLR0913, PLR0917 - explicit side-effect ports are intentional
        self,
        scope_key: str,
        settings: PayrollClosingSettingsStore,
        payroll: PayrollOverviewReader,
        identities: WhatsAppIdentityResolver,
        contexts: AttendanceContextWriter,
        outbound: WhatsAppOutboundGateway,
        deliveries: PayrollReminderDeliveryStore,
    ) -> None:
        self._scope_key = scope_key
        self._settings = settings
        self._payroll = payroll
        self._identities = identities
        self._contexts = contexts
        self._outbound = outbound
        self._deliveries = deliveries

    async def run(self, *, now: datetime | None = None) -> PayrollReminderRunSummary:
        instant = now or datetime.now(JAKARTA)
        policy = await self._settings.load(self._scope_key)
        if policy.applied_version < policy.desired_version:
            policy = await self._settings.mark_applied(
                policy.scope_key,
                policy.desired_version,
            )

        summary = PayrollReminderRunSummary(
            enabled=policy.enabled,
            paused=policy.paused,
            due_milestone=None,
            policy_version=policy.desired_version,
        )
        if not policy.dispatch_enabled:
            return summary

        cycle = payroll_cycle_for(
            instant.astimezone(JAKARTA).date(),
            policy.closing_day,
        )
        milestone = due_milestone(
            cycle,
            instant,
            reminder_hour=policy.reminder_hour,
            offsets=policy.reminder_offsets,
        )
        if milestone is None:
            return summary

        overview = await self._payroll.overview(
            cycle,
            now=instant,
            next_day_ready_hour=policy.next_day_ready_hour,
        )
        audience = tuple(
            talent for talent in overview.talents if talent.role in policy.target_roles
        )
        counts = {
            "sent": 0,
            "duplicate": 0,
            "unbound": 0,
            "retryable_failed": 0,
            "final_failed": 0,
            "unknown": 0,
            "unsafe_skipped": 0,
        }
        actionable = 0
        for talent in audience:
            if not talent.talent_action_required:
                continue
            actionable += 1
            outcome = await self._send_one(
                talent=talent,
                cycle=cycle,
                milestone=milestone.label,
                now=instant,
                idempotency_key=(
                    f"payroll-reminder:{self._scope_key}:{cycle.cycle_id}:"
                    f"{milestone.label}:{talent.employee_id}"
                ),
                created_by=_SCHEDULED_BY,
            )
            counts[outcome] += 1

        return PayrollReminderRunSummary(
            enabled=True,
            paused=False,
            due_milestone=milestone.label,
            policy_version=policy.desired_version,
            evaluated_talents=len(audience),
            actionable_talents=actionable,
            **counts,
        )

    async def preview_manual(
        self,
        employee_id: str,
        cycle: PayrollCycle,
        *,
        now: datetime,
    ) -> PayrollManualReminderPreview:
        policy, talent, outcome = await self._current_talent(employee_id, cycle, now)
        if talent is None:
            return PayrollManualReminderPreview(employee_id, False, outcome)
        context_id = uuid5(
            NAMESPACE_URL,
            f"payroll-preview:{self._scope_key}:{cycle.cycle_id}:{employee_id}",
        )
        draft = compose_attendance_reminder(
            talent,
            cycle,
            expires_at=now + _CONTEXT_TTL,
            context_id=context_id,
        )
        if draft is None:
            return PayrollManualReminderPreview(
                employee_id,
                False,
                "unsafe_skipped",
                actionable_days=talent.actionable_days,
            )
        _ = policy
        return PayrollManualReminderPreview(
            employee_id,
            True,
            "ready",
            actionable_days=talent.actionable_days,
            message=draft.as_plain_text(),
        )

    async def send_manual(
        self,
        employee_id: str,
        cycle: PayrollCycle,
        request_id: UUID,
        *,
        now: datetime,
    ) -> PayrollManualReminderResult:
        _, talent, outcome = await self._current_talent(employee_id, cycle, now)
        if talent is None:
            return PayrollManualReminderResult(employee_id, outcome, False)

        latest = await self._latest_delivery(employee_id, cycle)
        if latest is not None and latest.state in {
            PayrollDeliveryState.UNKNOWN,
            PayrollDeliveryState.RESERVED,
            PayrollDeliveryState.SENDING,
            PayrollDeliveryState.FAILED_RETRYABLE,
        }:
            blocked = {
                PayrollDeliveryState.UNKNOWN: "unknown_blocked",
                PayrollDeliveryState.RESERVED: "delivery_in_progress",
                PayrollDeliveryState.SENDING: "delivery_in_progress",
                PayrollDeliveryState.FAILED_RETRYABLE: "retry_pending",
            }[latest.state]
            return PayrollManualReminderResult(employee_id, blocked, False)

        idempotency_key = (
            f"payroll-manual:{self._scope_key}:{cycle.cycle_id}:"
            f"{request_id}:{employee_id}"
        )
        result = await self._send_one(
            talent=talent,
            cycle=cycle,
            milestone="MANUAL",
            now=now,
            idempotency_key=idempotency_key,
            created_by=_MANUAL_BY,
        )
        return PayrollManualReminderResult(employee_id, result, result == "sent")

    async def _current_talent(
        self,
        employee_id: str,
        cycle: PayrollCycle,
        now: datetime,
    ) -> tuple[PayrollClosingSettings, PayrollTalentView | None, str]:
        policy = await self._settings.load(self._scope_key)
        overview = await self._payroll.overview(
            cycle,
            now=now,
            next_day_ready_hour=policy.next_day_ready_hour,
        )
        talent = next(
            (item for item in overview.talents if item.employee_id == employee_id),
            None,
        )
        if talent is None:
            return policy, None, "talent_not_found"
        if talent.role not in policy.target_roles:
            return policy, None, "not_in_audience"
        if not talent.talent_action_required:
            return policy, None, "not_actionable"
        return policy, talent, "ready"

    async def _latest_delivery(
        self,
        employee_id: str,
        cycle: PayrollCycle,
    ) -> PayrollDeliveryRecord | None:
        records = tuple(
            record
            for record in await self._deliveries.list_cycle(
                scope_key=self._scope_key,
                cycle_id=cycle.cycle_id,
            )
            if record.employee_id == employee_id
        )
        return None if not records else max(records, key=_delivery_order)

    async def _send_one(  # noqa: C901, PLR0911, PLR0913 - explicit delivery state machine
        self,
        *,
        talent: PayrollTalentView,
        cycle: PayrollCycle,
        milestone: str,
        now: datetime,
        idempotency_key: str,
        created_by: str,
    ) -> str:
        context_id = uuid5(NAMESPACE_URL, idempotency_key)
        draft = compose_attendance_reminder(
            talent,
            cycle,
            expires_at=now + _CONTEXT_TTL,
            context_id=context_id,
        )
        if draft is None:
            return "unsafe_skipped"
        message = draft.as_plain_text()
        reservation = await self._deliveries.reserve(
            idempotency_key=idempotency_key,
            employee_id=talent.employee_id,
            period=cycle.period,
            message=message,
            scope_key=self._scope_key,
            cycle_id=cycle.cycle_id,
            milestone=milestone,
            context_id=context_id,
            created_by=created_by,
        )
        record = reservation.record
        if record.state is PayrollDeliveryState.SENT:
            return "duplicate"
        if record.state is PayrollDeliveryState.UNKNOWN:
            return "unknown"
        if record.state is PayrollDeliveryState.FAILED_FINAL:
            return "final_failed"
        if record.state is PayrollDeliveryState.SENDING:
            await self._deliveries.finish(
                idempotency_key,
                PayrollDeliveryState.UNKNOWN,
                error_code="interrupted_after_delivery_claim",
            )
            return "unknown"

        refreshed = await self._deliveries.refresh_retryable(
            idempotency_key,
            message=message,
            context_id=context_id,
        )
        if refreshed is None:
            return "unsafe_skipped"

        jid = await self._identities.jid_for_employee(talent.employee_id)
        if jid is None:
            claimed = await self._deliveries.claim(idempotency_key)
            if claimed is None:
                return "unsafe_skipped"
            await self._deliveries.finish(
                idempotency_key,
                PayrollDeliveryState.FAILED_FINAL,
                error_code="whatsapp_identity_not_bound",
            )
            return "unbound"

        # The exact ordered attendance snapshot is durable before outbound.
        await self._contexts.save(jid, draft.context)
        claimed = await self._deliveries.claim(idempotency_key)
        if claimed is None:
            return "unsafe_skipped"

        receipt = await self._outbound.send(
            jid,
            message,
            payroll_bridge_request_id(idempotency_key),
        )
        if receipt.status == "sent":
            await self._deliveries.finish(
                idempotency_key,
                PayrollDeliveryState.SENT,
                provider_message_id=receipt.provider_message_id,
                sent_at=now,
            )
            return "sent"
        if receipt.status == "bridge_unavailable":
            await self._deliveries.finish(
                idempotency_key,
                PayrollDeliveryState.FAILED_RETRYABLE,
                error_code=receipt.error_code,
            )
            return "retryable_failed"

        await self._deliveries.finish(
            idempotency_key,
            PayrollDeliveryState.FAILED_FINAL,
            error_code=receipt.error_code,
        )
        return "final_failed"
