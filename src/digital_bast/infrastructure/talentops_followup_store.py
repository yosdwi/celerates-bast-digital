"""PostgreSQL adapters for TalentOps outbound follow-up workflow."""

from __future__ import annotations

from datetime import date, datetime
from typing import final
from uuid import uuid4

import psycopg
from anyio.to_thread import run_sync
from psycopg.rows import class_row

from digital_bast.application.talentops_followups import FollowUpRecord, FollowUpWrite
from digital_bast.infrastructure.errors import InfrastructureError


class _FollowUpRow:
    __slots__ = (
        "channel",
        "created_at",
        "created_by",
        "employee_id",
        "error_code",
        "id",
        "idempotency_key",
        "message",
        "period_end",
        "period_start",
        "provider_message_id",
        "sent_at",
        "source",
        "status",
    )

    def __init__(  # noqa: PLR0913, PLR0917 - mirrors database row
        self,
        id: str,  # noqa: A002 - database column name
        idempotency_key: str,
        employee_id: str,
        period_start: date,
        period_end: date,
        channel: str,
        message: str,
        source: str,
        status: str,
        provider_message_id: str | None,
        created_by: str,
        created_at: datetime,
        sent_at: datetime | None,
        error_code: str | None,
    ) -> None:
        self.id = id
        self.idempotency_key = idempotency_key
        self.employee_id = employee_id
        self.period_start = period_start
        self.period_end = period_end
        self.channel = channel
        self.message = message
        self.source = source
        self.status = status
        self.provider_message_id = provider_message_id
        self.created_by = created_by
        self.created_at = created_at
        self.sent_at = sent_at
        self.error_code = error_code


def _record(row: _FollowUpRow) -> FollowUpRecord:
    return FollowUpRecord(
        id=row.id,
        idempotency_key=row.idempotency_key,
        employee_id=row.employee_id,
        period_start=row.period_start.isoformat(),
        period_end=row.period_end.isoformat(),
        channel=row.channel,
        message=row.message,
        source=row.source,
        status=row.status,
        provider_message_id=row.provider_message_id,
        created_by=row.created_by,
        created_at=row.created_at,
        sent_at=row.sent_at,
        error_code=row.error_code,
    )


_SELECT = """
    SELECT id,
           idempotency_key,
           employee_id,
           period_start,
           period_end,
           channel,
           message,
           source,
           status,
           provider_message_id,
           created_by,
           created_at,
           sent_at,
           error_code
    FROM talentops_followups
"""


@final
class PostgresTalentOpsFollowUpRepository:
    def __init__(self, dsn: str, connect_timeout_seconds: int = 5) -> None:
        self._dsn = dsn
        self._connect_timeout_seconds = connect_timeout_seconds

    def _connect(self) -> psycopg.Connection[tuple[object, ...]]:
        return psycopg.connect(self._dsn, connect_timeout=self._connect_timeout_seconds)

    async def by_idempotency(self, idempotency_key: str) -> FollowUpRecord | None:
        return await run_sync(self._by_idempotency, idempotency_key)

    async def latest_for_employee(self, employee_id: str) -> FollowUpRecord | None:
        return await run_sync(self._latest_for_employee, employee_id)

    async def record(self, write: FollowUpWrite) -> FollowUpRecord:
        return await run_sync(self._record, write)

    def _by_idempotency(self, idempotency_key: str) -> FollowUpRecord | None:
        try:
            with (
                self._connect() as connection,
                connection.cursor(row_factory=class_row(_FollowUpRow)) as cursor,
            ):
                _ = cursor.execute(
                    _SELECT + " WHERE idempotency_key = %s",
                    (idempotency_key,),
                )
                row = cursor.fetchone()
        except psycopg.Error as error:
            raise InfrastructureError(
                service="postgres", operation="talentops_followup_by_idempotency"
            ) from error
        return None if row is None else _record(row)

    def _latest_for_employee(self, employee_id: str) -> FollowUpRecord | None:
        try:
            with (
                self._connect() as connection,
                connection.cursor(row_factory=class_row(_FollowUpRow)) as cursor,
            ):
                _ = cursor.execute(
                    _SELECT
                    + " WHERE employee_id = %s ORDER BY created_at DESC LIMIT 1",
                    (employee_id,),
                )
                row = cursor.fetchone()
        except psycopg.Error as error:
            raise InfrastructureError(
                service="postgres", operation="talentops_latest_followup"
            ) from error
        return None if row is None else _record(row)

    def _record(self, write: FollowUpWrite) -> FollowUpRecord:
        delivery_id = f"fu_{uuid4().hex}"
        try:
            with (
                self._connect() as connection,
                connection.cursor(row_factory=class_row(_FollowUpRow)) as cursor,
            ):
                try:
                    _ = cursor.execute(
                        """
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
                            provider_message_id,
                            created_by,
                            sent_at,
                            error_code
                        ) VALUES (%s,%s,%s,%s,%s,'whatsapp',%s,%s,%s,%s,%s,%s,%s)
                        RETURNING id,
                                  idempotency_key,
                                  employee_id,
                                  period_start,
                                  period_end,
                                  channel,
                                  message,
                                  source,
                                  status,
                                  provider_message_id,
                                  created_by,
                                  created_at,
                                  sent_at,
                                  error_code
                        """,
                        (
                            delivery_id,
                            write.idempotency_key,
                            write.employee_id,
                            write.period.start,
                            write.period.end,
                            write.message,
                            write.source,
                            write.status,
                            write.provider_message_id,
                            write.created_by,
                            write.sent_at,
                            write.error_code,
                        ),
                    )
                    row = cursor.fetchone()
                except psycopg.errors.UniqueViolation:
                    connection.rollback()
                    existing = self._by_idempotency(write.idempotency_key)
                    if existing is not None:
                        return existing
                    raise
        except psycopg.Error as error:
            raise InfrastructureError(
                service="postgres", operation="record_talentops_followup"
            ) from error
        if row is None:  # pragma: no cover - RETURNING invariant
            raise InfrastructureError(service="postgres", operation="reload_talentops_followup")
        return _record(row)


@final
class PostgresWhatsAppIdentityResolver:
    """Resolve Talent WhatsApp binding only; PMO identity is a separate table."""

    def __init__(self, dsn: str, connect_timeout_seconds: int = 5) -> None:
        self._dsn = dsn
        self._connect_timeout_seconds = connect_timeout_seconds

    async def jid_for_employee(self, employee_id: str) -> str | None:
        return await run_sync(self._jid_for_employee, employee_id)

    def _jid_for_employee(self, employee_id: str) -> str | None:
        try:
            with psycopg.connect(
                self._dsn, connect_timeout=self._connect_timeout_seconds
            ) as connection, connection.cursor() as cursor:
                _ = cursor.execute(
                    "SELECT wa_jid FROM wa_identity WHERE employee_id = %s",
                    (employee_id,),
                )
                row = cursor.fetchone()
        except psycopg.Error as error:
            raise InfrastructureError(
                service="postgres", operation="resolve_talent_whatsapp_identity"
            ) from error
        return None if row is None else str(row[0])
