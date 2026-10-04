"""Durable logical delivery contract for Payroll attendance reminders."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from hashlib import sha256
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from datetime import datetime
    from uuid import UUID

    from digital_bast.domain.completion import DateRange


class PayrollDeliveryState(StrEnum):
    RESERVED = "RESERVED"
    SENDING = "SENDING"
    SENT = "SENT"
    FAILED_RETRYABLE = "FAILED_RETRYABLE"
    FAILED_FINAL = "FAILED_FINAL"
    UNKNOWN = "UNKNOWN"


def payroll_bridge_request_id(idempotency_key: str) -> str:
    """Return a stable bridge request id safely below the transport length cap."""
    digest = sha256(idempotency_key.encode("utf-8")).hexdigest()
    return f"payroll:{digest}"


@dataclass(frozen=True, slots=True)
class PayrollDeliveryRecord:
    id: str
    idempotency_key: str
    employee_id: str
    message: str
    state: PayrollDeliveryState
    scope_key: str
    cycle_id: str
    milestone: str
    context_id: UUID
    attempt_count: int
    provider_message_id: str | None = None
    error_code: str | None = None
    reserved_at: datetime | None = None
    sent_at: datetime | None = None
    responded_at: datetime | None = None
    response_kind: str | None = None


@dataclass(frozen=True, slots=True)
class PayrollDeliveryReservation:
    record: PayrollDeliveryRecord
    created: bool


class PayrollReminderDeliveryStore(Protocol):
    async def reserve(  # noqa: PLR0913 - logical delivery identity is explicit
        self,
        *,
        idempotency_key: str,
        employee_id: str,
        period: DateRange,
        message: str,
        scope_key: str,
        cycle_id: str,
        milestone: str,
        context_id: UUID,
        created_by: str,
    ) -> PayrollDeliveryReservation: ...

    async def refresh_retryable(
        self,
        idempotency_key: str,
        *,
        message: str,
        context_id: UUID,
    ) -> PayrollDeliveryRecord | None: ...

    async def claim(self, idempotency_key: str) -> PayrollDeliveryRecord | None: ...

    async def finish(
        self,
        idempotency_key: str,
        state: PayrollDeliveryState,
        *,
        provider_message_id: str | None = None,
        error_code: str | None = None,
        sent_at: datetime | None = None,
    ) -> PayrollDeliveryRecord | None: ...

    async def mark_attendance_response(
        self,
        *,
        context_id: UUID,
        employee_id: str,
        responded_at: datetime,
    ) -> bool: ...

    async def list_cycle(
        self,
        *,
        scope_key: str,
        cycle_id: str,
    ) -> tuple[PayrollDeliveryRecord, ...]: ...
