"""PMO closing digest projected from Payroll truth and reminder delivery facts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Protocol, final

from digital_bast.application.payroll_reminder_delivery import PayrollDeliveryState

if TYPE_CHECKING:
    from datetime import date

    from digital_bast.application.attendance_closing_policy import PayrollCycle
    from digital_bast.application.payroll_read import PayrollOverview, PayrollTalentView
    from digital_bast.application.payroll_reminder_delivery import PayrollDeliveryRecord


class PayrollFollowUpReason(StrEnum):
    DELIVERY_UNKNOWN = "DELIVERY_UNKNOWN"
    DELIVERY_RETRYABLE_FAILED = "DELIVERY_RETRYABLE_FAILED"
    DELIVERY_FINAL_FAILED = "DELIVERY_FINAL_FAILED"
    UNRESPONDED = "UNRESPONDED"
    NOT_REMINDED = "NOT_REMINDED"
    WAITING_REVIEW = "WAITING_REVIEW"
    SOURCE_UNVERIFIED = "SOURCE_UNVERIFIED"


@dataclass(frozen=True, slots=True)
class PayrollDigestSummary:
    total_talents: int
    complete: int
    waiting_submitted: int
    needs_talent_action: int
    unverified: int
    successful_reminder_deliveries: int
    successfully_reminded_talents: int
    unresponded_talents: int
    actionable_not_reminded: int
    delivery_retryable_failed: int
    delivery_final_failed: int
    delivery_unknown: int


@dataclass(frozen=True, slots=True)
class PayrollFollowUpItem:
    employee_id: str
    nrp: str
    name: str
    role: str
    status: str
    actionable_days: int
    waiting_days: int
    unverified_days: int
    reason: PayrollFollowUpReason
    latest_delivery_state: PayrollDeliveryState | None = None
    latest_milestone: str | None = None
    latest_sent_at: datetime | None = None
    responded_at: datetime | None = None
    error_code: str | None = None


@dataclass(frozen=True, slots=True)
class PayrollClosingDigest:
    cycle: PayrollCycle
    evaluated_through: date | None
    summary: PayrollDigestSummary
    items: tuple[PayrollFollowUpItem, ...]


class PayrollDigestOverviewReader(Protocol):
    async def overview(
        self,
        cycle: PayrollCycle,
        *,
        now: datetime,
        next_day_ready_hour: int = 6,
    ) -> PayrollOverview: ...


class PayrollDigestDeliveryReader(Protocol):
    async def list_cycle(
        self,
        *,
        scope_key: str,
        cycle_id: str,
    ) -> tuple[PayrollDeliveryRecord, ...]: ...


def _delivery_order(record: PayrollDeliveryRecord) -> tuple[datetime, datetime, str]:
    minimum = datetime.min.replace(tzinfo=UTC)
    return record.reserved_at or minimum, record.sent_at or minimum, record.id


def _latest_by_employee(
    deliveries: tuple[PayrollDeliveryRecord, ...],
) -> dict[str, PayrollDeliveryRecord]:
    result: dict[str, PayrollDeliveryRecord] = {}
    for delivery in deliveries:
        current = result.get(delivery.employee_id)
        if current is None or _delivery_order(delivery) > _delivery_order(current):
            result[delivery.employee_id] = delivery
    return result


def _latest_sent_by_employee(
    deliveries: tuple[PayrollDeliveryRecord, ...],
) -> dict[str, PayrollDeliveryRecord]:
    return _latest_by_employee(
        tuple(item for item in deliveries if item.state is PayrollDeliveryState.SENT)
    )


def _reason(  # noqa: PLR0911 - ordered operational priority is explicit
    talent: PayrollTalentView,
    latest: PayrollDeliveryRecord | None,
    latest_sent: PayrollDeliveryRecord | None,
) -> PayrollFollowUpReason | None:
    if talent.talent_action_required:
        if latest is not None and latest.state is PayrollDeliveryState.UNKNOWN:
            return PayrollFollowUpReason.DELIVERY_UNKNOWN
        if latest is not None and latest.state is PayrollDeliveryState.FAILED_RETRYABLE:
            return PayrollFollowUpReason.DELIVERY_RETRYABLE_FAILED
        if latest is not None and latest.state is PayrollDeliveryState.FAILED_FINAL:
            return PayrollFollowUpReason.DELIVERY_FINAL_FAILED
        if latest_sent is not None and latest_sent.responded_at is None:
            return PayrollFollowUpReason.UNRESPONDED
        if latest_sent is None:
            return PayrollFollowUpReason.NOT_REMINDED
    if talent.waiting_days > 0:
        return PayrollFollowUpReason.WAITING_REVIEW
    if talent.unverified_days > 0:
        return PayrollFollowUpReason.SOURCE_UNVERIFIED
    return None


def _follow_up_item(
    talent: PayrollTalentView,
    reason: PayrollFollowUpReason,
    latest: PayrollDeliveryRecord | None,
    latest_sent: PayrollDeliveryRecord | None,
) -> PayrollFollowUpItem:
    reference = latest if latest is not None else latest_sent
    return PayrollFollowUpItem(
        employee_id=talent.employee_id,
        nrp=talent.nrp,
        name=talent.name,
        role=talent.role,
        status=talent.status.value,
        actionable_days=talent.actionable_days,
        waiting_days=talent.waiting_days,
        unverified_days=talent.unverified_days,
        reason=reason,
        latest_delivery_state=None if reference is None else reference.state,
        latest_milestone=None if reference is None else reference.milestone,
        latest_sent_at=None if latest_sent is None else latest_sent.sent_at,
        responded_at=None if latest_sent is None else latest_sent.responded_at,
        error_code=None if reference is None else reference.error_code,
    )


def _is_unresponded(
    talent: PayrollTalentView,
    latest_sent: dict[str, PayrollDeliveryRecord],
) -> bool:
    if not talent.talent_action_required:
        return False
    sent = latest_sent.get(talent.employee_id)
    return sent is not None and sent.responded_at is None


_REASON_RANK = {
    PayrollFollowUpReason.DELIVERY_UNKNOWN: 0,
    PayrollFollowUpReason.DELIVERY_RETRYABLE_FAILED: 1,
    PayrollFollowUpReason.DELIVERY_FINAL_FAILED: 2,
    PayrollFollowUpReason.UNRESPONDED: 3,
    PayrollFollowUpReason.NOT_REMINDED: 4,
    PayrollFollowUpReason.WAITING_REVIEW: 5,
    PayrollFollowUpReason.SOURCE_UNVERIFIED: 6,
}


@final
class PayrollDigestService:
    def __init__(
        self,
        scope_key: str,
        payroll: PayrollDigestOverviewReader,
        deliveries: PayrollDigestDeliveryReader,
    ) -> None:
        self._scope_key = scope_key
        self._payroll = payroll
        self._deliveries = deliveries

    async def project(
        self,
        cycle: PayrollCycle,
        *,
        now: datetime,
        next_day_ready_hour: int = 6,
        target_roles: tuple[str, ...] | None = None,
    ) -> PayrollClosingDigest:
        overview = await self._payroll.overview(
            cycle,
            now=now,
            next_day_ready_hour=next_day_ready_hour,
        )
        audience = tuple(
            talent
            for talent in overview.talents
            if target_roles is None or talent.role in target_roles
        )
        deliveries = await self._deliveries.list_cycle(
            scope_key=self._scope_key,
            cycle_id=cycle.cycle_id,
        )
        audience_ids = {talent.employee_id for talent in audience}
        scoped_deliveries = tuple(
            delivery for delivery in deliveries if delivery.employee_id in audience_ids
        )
        latest = _latest_by_employee(scoped_deliveries)
        latest_sent = _latest_sent_by_employee(scoped_deliveries)

        items: list[PayrollFollowUpItem] = []
        for talent in audience:
            reason = _reason(
                talent,
                latest.get(talent.employee_id),
                latest_sent.get(talent.employee_id),
            )
            if reason is None:
                continue
            items.append(
                _follow_up_item(
                    talent,
                    reason,
                    latest.get(talent.employee_id),
                    latest_sent.get(talent.employee_id),
                )
            )

        successful = tuple(
            delivery
            for delivery in scoped_deliveries
            if delivery.state is PayrollDeliveryState.SENT
        )
        current_latest = tuple(latest.values())
        summary = PayrollDigestSummary(
            total_talents=len(audience),
            complete=sum(
                talent.actionable_days == 0
                and talent.waiting_days == 0
                and talent.unverified_days == 0
                for talent in audience
            ),
            waiting_submitted=sum(
                talent.actionable_days == 0
                and talent.waiting_days > 0
                and talent.unverified_days == 0
                for talent in audience
            ),
            needs_talent_action=sum(talent.actionable_days > 0 for talent in audience),
            unverified=sum(talent.unverified_days > 0 for talent in audience),
            successful_reminder_deliveries=len(successful),
            successfully_reminded_talents=len(latest_sent),
            unresponded_talents=sum(_is_unresponded(talent, latest_sent) for talent in audience),
            actionable_not_reminded=sum(
                talent.talent_action_required and talent.employee_id not in latest_sent
                for talent in audience
            ),
            delivery_retryable_failed=sum(
                item.state is PayrollDeliveryState.FAILED_RETRYABLE for item in current_latest
            ),
            delivery_final_failed=sum(
                item.state is PayrollDeliveryState.FAILED_FINAL for item in current_latest
            ),
            delivery_unknown=sum(
                item.state is PayrollDeliveryState.UNKNOWN for item in current_latest
            ),
        )
        ordered = tuple(
            sorted(
                items,
                key=lambda item: (
                    _REASON_RANK[item.reason],
                    item.name.casefold(),
                    item.employee_id,
                ),
            )
        )
        return PayrollClosingDigest(
            cycle=cycle,
            evaluated_through=overview.evaluated_through,
            summary=summary,
            items=ordered,
        )
