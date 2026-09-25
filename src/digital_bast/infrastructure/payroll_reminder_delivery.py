"""PostgreSQL delivery ledger operations for scheduled Payroll reminders."""

from __future__ import annotations

from typing import TYPE_CHECKING, final
from uuid import uuid4

import psycopg
from anyio.to_thread import run_sync
from psycopg.rows import class_row

from digital_bast.application.payroll_reminder_delivery import (
    PayrollDeliveryRecord,
    PayrollDeliveryReservation,
    PayrollDeliveryState,
)
from digital_bast.infrastructure.errors import InfrastructureError

if TYPE_CHECKING:
    from datetime import datetime
    from uuid import UUID

    from digital_bast.domain.completion import DateRange


class _DeliveryRow:
    __slots__ = (
        "attempt_count",
        "context_id",
        "cycle_id",
        "delivery_state",
        "employee_id",
        "error_code",
        "id",
        "idempotency_key",
        "message",
        "milestone",
        "provider_message_id",
        "reserved_at",
        "responded_at",
        "response_kind",
        "scope_key",
        "sent_at",
    )

    def __init__(  # noqa: PLR0913, PLR0917 - mirrors selected ledger fields
        self,
        id: str,  # noqa: A002 - database column name
        idempotency_key: str,
        employee_id: str,
        message: str,
        delivery_state: str,
        scope_key: str,
        cycle_id: str,
        milestone: str,
        context_id: UUID,
        attempt_count: int,
        provider_message_id: str | None,
        error_code: str | None,
        reserved_at: datetime | None,
        sent_at: datetime | None,
        responded_at: datetime | None,
        response_kind: str | None,
    ) -> None:
        self.id = id
        self.idempotency_key = idempotency_key
        self.employee_id = employee_id
        self.message = message
        self.delivery_state = delivery_state
        self.scope_key = scope_key
        self.cycle_id = cycle_id
        self.milestone = milestone
        self.context_id = context_id
        self.attempt_count = attempt_count
        self.provider_message_id = provider_message_id
        self.error_code = error_code
        self.reserved_at = reserved_at
        self.sent_at = sent_at
        self.responded_at = responded_at
        self.response_kind = response_kind


def _record(row: _DeliveryRow) -> PayrollDeliveryRecord:
    return PayrollDeliveryRecord(
        id=row.id,
        idempotency_key=row.idempotency_key,
        employee_id=row.employee_id,
        message=row.message,
        state=PayrollDeliveryState(row.delivery_state),
        scope_key=row.scope_key,
        cycle_id=row.cycle_id,
        milestone=row.milestone,
        context_id=row.context_id,
        attempt_count=row.attempt_count,
        provider_message_id=row.provider_message_id,
        error_code=row.error_code,
        reserved_at=row.reserved_at,
        sent_at=row.sent_at,
        responded_at=row.responded_at,
        response_kind=row.response_kind,
    )


_RESERVE_SQL = """
    INSERT INTO talentops_followups (
        id,
        idempotency_key,
        employee_id,
        period_start,
        period_end,
        channel,
        message,
        source,
        status,
        created_by,
        delivery_state,
        scope_key,
        cycle_id,
        milestone,
        context_id,
        reserved_at
    ) VALUES (%s,%s,%s,%s,%s,'whatsapp',%s,'deterministic','reserved',%s,
              'RESERVED',%s,%s,%s,%s,now())
    ON CONFLICT (idempotency_key) DO NOTHING
    RETURNING id,
              idempotency_key,
              employee_id,
              message,
              delivery_state,
              scope_key,
              cycle_id,
              milestone,
              context_id,
              attempt_count,
              provider_message_id,
              error_code,
              reserved_at,
              sent_at,
              responded_at,
              response_kind
"""
_BY_KEY_SQL = """
    SELECT id,
           idempotency_key,
           employee_id,
           message,
           delivery_state,
           scope_key,
           cycle_id,
           milestone,
           context_id,
           attempt_count,
           provider_message_id,
           error_code,
           reserved_at,
           sent_at,
           responded_at,
           response_kind
    FROM talentops_followups
    WHERE idempotency_key = %s
      AND delivery_state IS NOT NULL
"""
_REFRESH_SQL = """
    UPDATE talentops_followups
    SET message = %s,
        context_id = %s,
        delivery_state = 'RESERVED',
        status = 'reserved',
        provider_message_id = NULL,
        error_code = NULL,
        sending_at = NULL,
        reserved_at = now()
    WHERE idempotency_key = %s
      AND delivery_state IN ('RESERVED', 'FAILED_RETRYABLE')
    RETURNING id,
              idempotency_key,
              employee_id,
              message,
              delivery_state,
              scope_key,
              cycle_id,
              milestone,
              context_id,
              attempt_count,
              provider_message_id,
              error_code,
              reserved_at,
              sent_at,
              responded_at,
              response_kind
"""
_CLAIM_SQL = """
    UPDATE talentops_followups
    SET delivery_state = 'SENDING',
        status = 'sending',
        sending_at = now(),
        attempt_count = attempt_count + 1
    WHERE idempotency_key = %s
      AND delivery_state = 'RESERVED'
    RETURNING id,
              idempotency_key,
              employee_id,
              message,
              delivery_state,
              scope_key,
              cycle_id,
              milestone,
              context_id,
              attempt_count,
              provider_message_id,
              error_code,
              reserved_at,
              sent_at,
              responded_at,
              response_kind
"""
_FINISH_SQL = """
    UPDATE talentops_followups
    SET delivery_state = %s,
        status = %s,
        provider_message_id = %s,
        error_code = %s,
        sent_at = %s
    WHERE idempotency_key = %s
      AND delivery_state = 'SENDING'
    RETURNING id,
              idempotency_key,
              employee_id,
              message,
              delivery_state,
              scope_key,
              cycle_id,
              milestone,
              context_id,
              attempt_count,
              provider_message_id,
              error_code,
              reserved_at,
              sent_at,
              responded_at,
              response_kind
"""
_RESPONSE_SQL = """
    UPDATE talentops_followups
    SET responded_at = %s,
        response_kind = 'attendance_action'
    WHERE context_id = %s
      AND employee_id = %s
      AND delivery_state = 'SENT'
      AND responded_at IS NULL
"""
_LIST_CYCLE_SQL = """
    SELECT id,
           idempotency_key,
           employee_id,
           message,
           delivery_state,
           scope_key,
           cycle_id,
           milestone,
           context_id,
           attempt_count,
           provider_message_id,
           error_code,
           reserved_at,
           sent_at,
           responded_at,
           response_kind
    FROM talentops_followups
    WHERE scope_key = %s
      AND cycle_id = %s
      AND delivery_state IS NOT NULL
    ORDER BY reserved_at, id
"""


@final
class PostgresPayrollReminderDeliveryStore:
    def __init__(self, dsn: str, connect_timeout_seconds: int = 5) -> None:
        self._dsn = dsn
        self._connect_timeout_seconds = connect_timeout_seconds

    def _connect(self) -> psycopg.Connection[tuple[object, ...]]:
        return psycopg.connect(self._dsn, connect_timeout=self._connect_timeout_seconds)

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
    ) -> PayrollDeliveryReservation:
        return await run_sync(
            self._reserve,
            idempotency_key,
            employee_id,
            period,
            message,
            scope_key,
            cycle_id,
            milestone,
            context_id,
            created_by,
        )

    async def refresh_retryable(
        self,
        idempotency_key: str,
        *,
        message: str,
        context_id: UUID,
    ) -> PayrollDeliveryRecord | None:
        return await run_sync(self._refresh_retryable, idempotency_key, message, context_id)

    async def claim(self, idempotency_key: str) -> PayrollDeliveryRecord | None:
        return await run_sync(self._claim, idempotency_key)

    async def finish(
        self,
        idempotency_key: str,
        state: PayrollDeliveryState,
        *,
        provider_message_id: str | None = None,
        error_code: str | None = None,
        sent_at: datetime | None = None,
    ) -> PayrollDeliveryRecord | None:
        return await run_sync(
            self._finish,
            idempotency_key,
            state,
            provider_message_id,
            error_code,
            sent_at,
        )

    async def mark_attendance_response(
        self,
        *,
        context_id: UUID,
        employee_id: str,
        responded_at: datetime,
    ) -> bool:
        return await run_sync(
            self._mark_attendance_response,
            context_id,
            employee_id,
            responded_at,
        )

    async def list_cycle(
        self,
        *,
        scope_key: str,
        cycle_id: str,
    ) -> tuple[PayrollDeliveryRecord, ...]:
        return await run_sync(self._list_cycle, scope_key, cycle_id)

    def _reserve(  # noqa: PLR0913, PLR0917 - mirrors reserve contract
        self,
        idempotency_key: str,
        employee_id: str,
        period: DateRange,
        message: str,
        scope_key: str,
        cycle_id: str,
        milestone: str,
        context_id: UUID,
        created_by: str,
    ) -> PayrollDeliveryReservation:
        delivery_id = f"fu_{uuid4().hex}"
        try:
            with (
                self._connect() as connection,
                connection.cursor(row_factory=class_row(_DeliveryRow)) as cursor,
            ):
                _ = cursor.execute(
                    _RESERVE_SQL,
                    (
                        delivery_id,
                        idempotency_key,
                        employee_id,
                        period.start,
                        period.end,
                        message,
                        created_by,
                        scope_key,
                        cycle_id,
                        milestone,
                        context_id,
                    ),
                )
                row = cursor.fetchone()
                if row is not None:
                    return PayrollDeliveryReservation(record=_record(row), created=True)
                _ = cursor.execute(_BY_KEY_SQL, (idempotency_key,))
                existing = cursor.fetchone()
        except psycopg.Error as error:
            raise InfrastructureError(
                service="postgres",
                operation="reserve_payroll_reminder",
            ) from error
        if existing is None:
            raise InfrastructureError(
                service="postgres",
                operation="reload_payroll_reminder",
            )
        return PayrollDeliveryReservation(record=_record(existing), created=False)

    def _refresh_retryable(
        self,
        idempotency_key: str,
        message: str,
        context_id: UUID,
    ) -> PayrollDeliveryRecord | None:
        try:
            with (
                self._connect() as connection,
                connection.cursor(row_factory=class_row(_DeliveryRow)) as cursor,
            ):
                _ = cursor.execute(_REFRESH_SQL, (message, context_id, idempotency_key))
                row = cursor.fetchone()
        except psycopg.Error as error:
            raise InfrastructureError(
                service="postgres",
                operation="refresh_payroll_reminder",
            ) from error
        return None if row is None else _record(row)

    def _claim(self, idempotency_key: str) -> PayrollDeliveryRecord | None:
        try:
            with (
                self._connect() as connection,
                connection.cursor(row_factory=class_row(_DeliveryRow)) as cursor,
            ):
                _ = cursor.execute(_CLAIM_SQL, (idempotency_key,))
                row = cursor.fetchone()
        except psycopg.Error as error:
            raise InfrastructureError(
                service="postgres",
                operation="claim_payroll_reminder",
            ) from error
        return None if row is None else _record(row)

    def _finish(
        self,
        idempotency_key: str,
        state: PayrollDeliveryState,
        provider_message_id: str | None,
        error_code: str | None,
        sent_at: datetime | None,
    ) -> PayrollDeliveryRecord | None:
        if state in {PayrollDeliveryState.RESERVED, PayrollDeliveryState.SENDING}:
            message = "finish state must be terminal or retryable"
            raise ValueError(message)
        try:
            with (
                self._connect() as connection,
                connection.cursor(row_factory=class_row(_DeliveryRow)) as cursor,
            ):
                _ = cursor.execute(
                    _FINISH_SQL,
                    (
                        state.value,
                        state.value.casefold(),
                        provider_message_id,
                        error_code,
                        sent_at,
                        idempotency_key,
                    ),
                )
                row = cursor.fetchone()
        except psycopg.Error as error:
            raise InfrastructureError(
                service="postgres",
                operation="finish_payroll_reminder",
            ) from error
        return None if row is None else _record(row)

    def _mark_attendance_response(
        self,
        context_id: UUID,
        employee_id: str,
        responded_at: datetime,
    ) -> bool:
        try:
            with self._connect() as connection, connection.cursor() as cursor:
                _ = cursor.execute(_RESPONSE_SQL, (responded_at, context_id, employee_id))
                return cursor.rowcount > 0
        except psycopg.Error as error:
            raise InfrastructureError(
                service="postgres",
                operation="mark_payroll_reminder_response",
            ) from error

    def _list_cycle(
        self,
        scope_key: str,
        cycle_id: str,
    ) -> tuple[PayrollDeliveryRecord, ...]:
        try:
            with (
                self._connect() as connection,
                connection.cursor(row_factory=class_row(_DeliveryRow)) as cursor,
            ):
                _ = cursor.execute(_LIST_CYCLE_SQL, (scope_key, cycle_id))
                return tuple(_record(row) for row in cursor.fetchall())
        except psycopg.Error as error:
            raise InfrastructureError(
                service="postgres",
                operation="list_payroll_reminder_deliveries",
            ) from error
