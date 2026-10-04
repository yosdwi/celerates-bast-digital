"""PostgreSQL delivery ledger for Payroll closing-group digests."""

from __future__ import annotations

from typing import final

import psycopg
from anyio.to_thread import run_sync
from psycopg.rows import class_row

from digital_bast.application.payroll_group_digest import (
    PayrollGroupDigestDelivery,
    PayrollGroupDigestReservation,
)
from digital_bast.application.payroll_reminder_delivery import PayrollDeliveryState
from digital_bast.infrastructure.errors import InfrastructureError


class _GroupDigestRow:
    __slots__ = (
        "attempt_count",
        "cycle_id",
        "delivery_state",
        "error_code",
        "group_jid",
        "idempotency_key",
        "message",
        "milestone",
        "provider_message_id",
        "scope_key",
    )

    def __init__(  # noqa: PLR0913, PLR0917 - mirrors selected database columns
        self,
        idempotency_key: str,
        scope_key: str,
        cycle_id: str,
        milestone: str,
        group_jid: str,
        message: str,
        delivery_state: str,
        attempt_count: int,
        provider_message_id: str | None,
        error_code: str | None,
    ) -> None:
        self.idempotency_key = idempotency_key
        self.scope_key = scope_key
        self.cycle_id = cycle_id
        self.milestone = milestone
        self.group_jid = group_jid
        self.message = message
        self.delivery_state = delivery_state
        self.attempt_count = attempt_count
        self.provider_message_id = provider_message_id
        self.error_code = error_code


def _record(row: _GroupDigestRow) -> PayrollGroupDigestDelivery:
    return PayrollGroupDigestDelivery(
        idempotency_key=row.idempotency_key,
        scope_key=row.scope_key,
        cycle_id=row.cycle_id,
        milestone=row.milestone,
        group_jid=row.group_jid,
        message=row.message,
        state=PayrollDeliveryState(row.delivery_state),
        attempt_count=row.attempt_count,
        provider_message_id=row.provider_message_id,
        error_code=row.error_code,
    )


_RESERVE_SQL = """
    INSERT INTO payroll_group_digest_deliveries (
        idempotency_key,
        scope_key,
        cycle_id,
        milestone,
        group_jid,
        message,
        created_by
    ) VALUES (%s,%s,%s,%s,%s,%s,%s)
    ON CONFLICT DO NOTHING
    RETURNING idempotency_key,
              scope_key,
              cycle_id,
              milestone,
              group_jid,
              message,
              delivery_state,
              attempt_count,
              provider_message_id,
              error_code
"""
_BY_KEY_SQL = """
    SELECT idempotency_key,
           scope_key,
           cycle_id,
           milestone,
           group_jid,
           message,
           delivery_state,
           attempt_count,
           provider_message_id,
           error_code
    FROM payroll_group_digest_deliveries
    WHERE idempotency_key = %s
"""
_REFRESH_SQL = """
    UPDATE payroll_group_digest_deliveries
    SET group_jid = %s,
        message = %s,
        delivery_state = 'RESERVED',
        provider_message_id = NULL,
        error_code = NULL,
        sending_at = NULL,
        reserved_at = now()
    WHERE idempotency_key = %s
      AND delivery_state IN ('RESERVED', 'FAILED_RETRYABLE')
    RETURNING idempotency_key,
              scope_key,
              cycle_id,
              milestone,
              group_jid,
              message,
              delivery_state,
              attempt_count,
              provider_message_id,
              error_code
"""
_CLAIM_SQL = """
    UPDATE payroll_group_digest_deliveries
    SET delivery_state = 'SENDING',
        sending_at = now(),
        attempt_count = attempt_count + 1
    WHERE idempotency_key = %s
      AND delivery_state = 'RESERVED'
    RETURNING idempotency_key,
              scope_key,
              cycle_id,
              milestone,
              group_jid,
              message,
              delivery_state,
              attempt_count,
              provider_message_id,
              error_code
"""
_FINISH_SQL = """
    UPDATE payroll_group_digest_deliveries
    SET delivery_state = %s,
        provider_message_id = %s,
        error_code = %s,
        sent_at = CASE WHEN %s = 'SENT' THEN now() ELSE sent_at END
    WHERE idempotency_key = %s
      AND delivery_state = 'SENDING'
    RETURNING idempotency_key,
              scope_key,
              cycle_id,
              milestone,
              group_jid,
              message,
              delivery_state,
              attempt_count,
              provider_message_id,
              error_code
"""


@final
class PostgresPayrollGroupDigestDeliveryStore:
    def __init__(self, dsn: str, connect_timeout_seconds: int = 5) -> None:
        self._dsn = dsn
        self._connect_timeout_seconds = connect_timeout_seconds

    def _connect(self) -> psycopg.Connection[tuple[object, ...]]:
        return psycopg.connect(self._dsn, connect_timeout=self._connect_timeout_seconds)

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
    ) -> PayrollGroupDigestReservation:
        return await run_sync(
            self._reserve,
            idempotency_key,
            scope_key,
            cycle_id,
            milestone,
            group_jid,
            message,
            created_by,
        )

    async def refresh_retryable(
        self,
        idempotency_key: str,
        *,
        group_jid: str,
        message: str,
    ) -> PayrollGroupDigestDelivery | None:
        return await run_sync(self._refresh_retryable, idempotency_key, group_jid, message)

    async def claim(self, idempotency_key: str) -> PayrollGroupDigestDelivery | None:
        return await run_sync(self._claim, idempotency_key)

    async def finish(
        self,
        idempotency_key: str,
        state: PayrollDeliveryState,
        *,
        provider_message_id: str | None = None,
        error_code: str | None = None,
    ) -> PayrollGroupDigestDelivery | None:
        return await run_sync(
            self._finish,
            idempotency_key,
            state,
            provider_message_id,
            error_code,
        )

    def _reserve(  # noqa: PLR0913, PLR0917 - mirrors reserve contract
        self,
        idempotency_key: str,
        scope_key: str,
        cycle_id: str,
        milestone: str,
        group_jid: str,
        message: str,
        created_by: str,
    ) -> PayrollGroupDigestReservation:
        try:
            with (
                self._connect() as connection,
                connection.cursor(row_factory=class_row(_GroupDigestRow)) as cursor,
            ):
                _ = cursor.execute(
                    _RESERVE_SQL,
                    (
                        idempotency_key,
                        scope_key,
                        cycle_id,
                        milestone,
                        group_jid,
                        message,
                        created_by,
                    ),
                )
                row = cursor.fetchone()
                if row is not None:
                    return PayrollGroupDigestReservation(record=_record(row), created=True)
                _ = cursor.execute(_BY_KEY_SQL, (idempotency_key,))
                existing = cursor.fetchone()
        except psycopg.Error as error:
            raise InfrastructureError(
                service="postgres",
                operation="reserve_payroll_group_digest",
            ) from error
        if existing is None:
            raise InfrastructureError(
                service="postgres",
                operation="reload_payroll_group_digest",
            )
        return PayrollGroupDigestReservation(record=_record(existing), created=False)

    def _refresh_retryable(
        self,
        idempotency_key: str,
        group_jid: str,
        message: str,
    ) -> PayrollGroupDigestDelivery | None:
        try:
            with (
                self._connect() as connection,
                connection.cursor(row_factory=class_row(_GroupDigestRow)) as cursor,
            ):
                _ = cursor.execute(_REFRESH_SQL, (group_jid, message, idempotency_key))
                row = cursor.fetchone()
        except psycopg.Error as error:
            raise InfrastructureError(
                service="postgres",
                operation="refresh_payroll_group_digest",
            ) from error
        return None if row is None else _record(row)

    def _claim(self, idempotency_key: str) -> PayrollGroupDigestDelivery | None:
        try:
            with (
                self._connect() as connection,
                connection.cursor(row_factory=class_row(_GroupDigestRow)) as cursor,
            ):
                _ = cursor.execute(_CLAIM_SQL, (idempotency_key,))
                row = cursor.fetchone()
        except psycopg.Error as error:
            raise InfrastructureError(
                service="postgres",
                operation="claim_payroll_group_digest",
            ) from error
        return None if row is None else _record(row)

    def _finish(
        self,
        idempotency_key: str,
        state: PayrollDeliveryState,
        provider_message_id: str | None,
        error_code: str | None,
    ) -> PayrollGroupDigestDelivery | None:
        if state in {PayrollDeliveryState.RESERVED, PayrollDeliveryState.SENDING}:
            message = "finish state must be terminal or retryable"
            raise ValueError(message)
        try:
            with (
                self._connect() as connection,
                connection.cursor(row_factory=class_row(_GroupDigestRow)) as cursor,
            ):
                _ = cursor.execute(
                    _FINISH_SQL,
                    (
                        state.value,
                        provider_message_id,
                        error_code,
                        state.value,
                        idempotency_key,
                    ),
                )
                row = cursor.fetchone()
        except psycopg.Error as error:
            raise InfrastructureError(
                service="postgres",
                operation="finish_payroll_group_digest",
            ) from error
        return None if row is None else _record(row)
