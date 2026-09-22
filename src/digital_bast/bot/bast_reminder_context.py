"""Durable, bounded context for replies to a BAST closing reminder.

Only the ordered domains shown in the latest successful BAST reminder are
stored here. Current blockers are always re-read before a reply is rendered;
this context never becomes a second source of business truth.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import TYPE_CHECKING, final

import psycopg
from anyio.to_thread import run_sync
from psycopg.rows import class_row

from digital_bast.infrastructure.errors import InfrastructureError

if TYPE_CHECKING:
    from digital_bast.domain.completion import DateRange

_ALLOWED_DOMAINS = frozenset({"attendance", "timesheet", "task", "evidence"})


@dataclass(frozen=True, slots=True)
class BastReminderContext:
    employee_id: str
    period_start: date
    period_end: date
    domains: tuple[str, ...]
    expires_at: datetime

    def domain_at(self, position: int) -> str | None:
        if position < 1 or position > len(self.domains):
            return None
        return self.domains[position - 1]


class _ContextRow:
    __slots__ = ("domains", "employee_id", "expires_at", "period_end", "period_start")

    def __init__(
        self,
        employee_id: str,
        period_start: date,
        period_end: date,
        domains: list[str],
        expires_at: datetime,
    ) -> None:
        self.employee_id = employee_id
        self.period_start = period_start
        self.period_end = period_end
        self.domains = domains
        self.expires_at = expires_at


@final
class BastReminderContextService:
    def __init__(self, dsn: str, connect_timeout_seconds: int = 5) -> None:
        self._dsn = dsn
        self._connect_timeout_seconds = connect_timeout_seconds

    def _connect(self) -> psycopg.Connection[tuple[object, ...]]:
        return psycopg.connect(self._dsn, connect_timeout=self._connect_timeout_seconds)

    async def save_for_employee(
        self,
        employee_id: str,
        period: DateRange,
        domains: tuple[str, ...],
        expires_at: datetime,
    ) -> bool:
        normalized = tuple(domain for domain in domains if domain in _ALLOWED_DOMAINS)
        if not normalized:
            return False
        return await run_sync(
            self._save_for_employee,
            employee_id,
            period.start,
            period.end,
            normalized,
            expires_at,
        )

    async def load(
        self,
        wa_jid: str,
        *,
        now: datetime | None = None,
    ) -> BastReminderContext | None:
        return await run_sync(self._load, wa_jid, now)

    async def clear(self, wa_jid: str) -> None:
        await run_sync(self._clear, wa_jid)

    def _save_for_employee(
        self,
        employee_id: str,
        period_start: date,
        period_end: date,
        domains: tuple[str, ...],
        expires_at: datetime,
    ) -> bool:
        try:
            with self._connect() as connection, connection.cursor() as cursor:
                _ = cursor.execute(
                    """
                    INSERT INTO bast_reminder_contexts (
                        wa_jid, employee_id, period_start, period_end, domains, expires_at
                    )
                    SELECT wi.wa_jid, %s, %s, %s, %s, %s
                    FROM wa_identity wi
                    WHERE wi.employee_id = %s
                    ON CONFLICT (wa_jid) DO UPDATE SET
                        employee_id = EXCLUDED.employee_id,
                        period_start = EXCLUDED.period_start,
                        period_end = EXCLUDED.period_end,
                        domains = EXCLUDED.domains,
                        expires_at = EXCLUDED.expires_at,
                        updated_at = now()
                    """,
                    (
                        employee_id,
                        period_start,
                        period_end,
                        list(domains),
                        expires_at,
                        employee_id,
                    ),
                )
                return cursor.rowcount > 0
        except psycopg.Error as error:
            raise InfrastructureError(
                service="postgres",
                operation="save_bast_reminder_context",
            ) from error

    def _load(
        self,
        wa_jid: str,
        now: datetime | None = None,
    ) -> BastReminderContext | None:
        instant = now or datetime.now(UTC)
        try:
            with (
                self._connect() as connection,
                connection.cursor(row_factory=class_row(_ContextRow)) as cursor,
            ):
                _ = cursor.execute(
                    """
                    SELECT employee_id, period_start, period_end, domains, expires_at
                    FROM bast_reminder_contexts
                    WHERE wa_jid = %s
                    """,
                    (wa_jid,),
                )
                row = cursor.fetchone()
        except psycopg.Error as error:
            raise InfrastructureError(
                service="postgres",
                operation="load_bast_reminder_context",
            ) from error
        if row is None or row.expires_at <= instant:
            return None
        domains = tuple(domain for domain in row.domains if domain in _ALLOWED_DOMAINS)
        if not domains:
            return None
        return BastReminderContext(
            employee_id=row.employee_id,
            period_start=row.period_start,
            period_end=row.period_end,
            domains=domains,
            expires_at=row.expires_at,
        )

    def _clear(self, wa_jid: str) -> None:
        try:
            with self._connect() as connection, connection.cursor() as cursor:
                _ = cursor.execute(
                    "DELETE FROM bast_reminder_contexts WHERE wa_jid = %s",
                    (wa_jid,),
                )
        except psycopg.Error as error:
            raise InfrastructureError(
                service="postgres",
                operation="clear_bast_reminder_context",
            ) from error
