from __future__ import annotations

from datetime import datetime
from typing import final
from uuid import uuid4

import psycopg
from anyio.to_thread import run_sync

from digital_bast.application.talentops_followups import FollowUpRecord, FollowUpWrite
from digital_bast.infrastructure.errors import InfrastructureError

_SELECT_FIELDS = """
    id, idempotency_key, employee_id, period_start, period_end,
    channel, message, source, status, provider_message_id,
    created_by, created_at, sent_at, error_code,
    delivered_at, read_at, failed_at, delivery_error_code
"""


@final
class PostgresTalentOpsFollowUpRepository:
    def __init__(self, dsn: str, connect_timeout_seconds: int = 5) -> None:
        self._dsn = dsn
        self._connect_timeout_seconds = connect_timeout_seconds

    async def by_idempotency(self, idempotency_key: str) -> FollowUpRecord | None:
        return await run_sync(self._by_idempotency, idempotency_key)

    async def latest_for_employee(self, employee_id: str) -> FollowUpRecord | None:
        return await run_sync(self._latest_for_employee, employee_id)

    async def record(self, write: FollowUpWrite) -> FollowUpRecord:
        return await run_sync(self._record, write)

    def _connect(self) -> psycopg.Connection[tuple[object, ...]]:
        return psycopg.connect(self._dsn, connect_timeout=self._connect_timeout_seconds)

    @staticmethod
    def _as_datetime(value: object) -> datetime:
        return value if isinstance(value, datetime) else datetime.fromisoformat(str(value))

    @staticmethod
    def _row(row: tuple[object, ...] | None) -> FollowUpRecord | None:
        if row is None:
            return None
        return FollowUpRecord(
            id=str(row[0]),
            idempotency_key=str(row[1]),
            employee_id=str(row[2]),
            period_start=str(row[3]),
            period_end=str(row[4]),
            channel=str(row[5]),
            message=str(row[6]),
            source=str(row[7]),
            status=str(row[8]),
            provider_message_id=None if row[9] is None else str(row[9]),
            created_by=str(row[10]),
            created_at=PostgresTalentOpsFollowUpRepository._as_datetime(row[11]),
            sent_at=(
                None
                if row[12] is None
                else PostgresTalentOpsFollowUpRepository._as_datetime(row[12])
            ),
            error_code=None if row[13] is None else str(row[13]),
            delivered_at=(
                None
                if row[14] is None
                else PostgresTalentOpsFollowUpRepository._as_datetime(row[14])
            ),
            read_at=(
                None
                if row[15] is None
                else PostgresTalentOpsFollowUpRepository._as_datetime(row[15])
            ),
            failed_at=(
                None
                if row[16] is None
                else PostgresTalentOpsFollowUpRepository._as_datetime(row[16])
            ),
            delivery_error_code=None if row[17] is None else str(row[17]),
        )

    def _by_idempotency(self, idempotency_key: str) -> FollowUpRecord | None:
        try:
            with self._connect() as connection, connection.cursor() as cursor:
                _ = cursor.execute(
                    f"""
                    SELECT {_SELECT_FIELDS}
                    FROM talentops_followups
                    WHERE idempotency_key = %s
                    """,  # noqa: S608 - constant field list, values remain parameterized
                    (idempotency_key,),
                )
                row = cursor.fetchone()
        except psycopg.Error as error:
            raise InfrastructureError(
                service="postgres", operation="load_talentops_followup"
            ) from error
        return self._row(row)

    def _latest_for_employee(self, employee_id: str) -> FollowUpRecord | None:
        try:
            with self._connect() as connection, connection.cursor() as cursor:
                _ = cursor.execute(
                    f"""
                    SELECT {_SELECT_FIELDS}
                    FROM talentops_followups
                    WHERE employee_id = %s
                    ORDER BY created_at DESC
                    LIMIT 1
                    """,  # noqa: S608 - constant field list, values remain parameterized
                    (employee_id,),
                )
                row = cursor.fetchone()
        except psycopg.Error as error:
            raise InfrastructureError(
                service="postgres", operation="load_latest_talentops_followup"
            ) from error
        return self._row(row)

    def _record(self, write: FollowUpWrite) -> FollowUpRecord:
        record_id = str(uuid4())
        try:
            with self._connect() as connection, connection.cursor() as cursor:
                _ = cursor.execute(
                    """
                    INSERT INTO talentops_followups (
                        id, idempotency_key, employee_id, period_start, period_end,
                        channel, message, source, status, provider_message_id,
                        created_by, sent_at, error_code
                    ) VALUES (
                        %s, %s, %s, %s, %s,
                        'whatsapp', %s, %s, %s, %s,
                        %s, %s, %s
                    )
                    ON CONFLICT (idempotency_key) DO NOTHING
                    RETURNING id, idempotency_key, employee_id, period_start, period_end,
                              channel, message, source, status, provider_message_id,
                              created_by, created_at, sent_at, error_code,
                              delivered_at, read_at, failed_at, delivery_error_code
                    """,
                    (
                        record_id,
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
                if row is None:
                    _ = cursor.execute(
                        f"""
                        SELECT {_SELECT_FIELDS}
                        FROM talentops_followups
                        WHERE idempotency_key = %s
                        """,  # noqa: S608 - constant field list, values remain parameterized
                        (write.idempotency_key,),
                    )
                    row = cursor.fetchone()
        except psycopg.Error as error:
            raise InfrastructureError(
                service="postgres", operation="record_talentops_followup"
            ) from error
        result = self._row(row)
        if result is None:
            raise InfrastructureError(
                service="postgres", operation="record_talentops_followup_empty"
            )
        return result
