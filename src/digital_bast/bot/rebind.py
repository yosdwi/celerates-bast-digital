"""Talent WhatsApp-number replacement with PMO approval.

A new number can prove the employee identity with the normal NRP confirmation,
but it never takes over the old binding automatically. The request is durable
and the old binding remains authoritative until an authorized PMO approves it.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING, final
from uuid import UUID

import psycopg
from anyio.to_thread import run_sync
from psycopg.rows import class_row

from digital_bast.infrastructure.errors import InfrastructureError

if TYPE_CHECKING:
    from datetime import date


class RebindStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class RebindRequestOutcome(StrEnum):
    CREATED = "created"
    NO_EXISTING_BINDING = "no_existing_binding"
    SAME_NUMBER = "same_number"
    NEW_NUMBER_ALREADY_BOUND = "new_number_already_bound"
    ALREADY_PENDING = "already_pending"


class RebindDecisionOutcome(StrEnum):
    UPDATED = "updated"
    NOT_FOUND = "not_found"
    ALREADY_RESOLVED = "already_resolved"
    SOURCE_CHANGED = "source_changed"
    NEW_NUMBER_ALREADY_BOUND = "new_number_already_bound"
    REJECTION_REASON_REQUIRED = "rejection_reason_required"


@dataclass(frozen=True, slots=True)
class RebindRequest:
    id: UUID
    employee_id: str
    nrp: str
    full_name: str
    old_wa_jid: str
    new_wa_jid: str
    scope_key: str
    status: RebindStatus
    requested_at: datetime
    reviewed_by: str | None
    reviewed_at: datetime | None
    rejection_reason: str | None


@dataclass(frozen=True, slots=True)
class RebindRequestResult:
    outcome: RebindRequestOutcome
    request_id: UUID | None = None


@dataclass(frozen=True, slots=True)
class RebindDecisionResult:
    outcome: RebindDecisionOutcome
    status: RebindStatus | None = None


class _RebindRow:
    __slots__ = (
        "employee_id",
        "full_name",
        "new_wa_jid",
        "nrp",
        "old_wa_jid",
        "rejection_reason",
        "request_id",
        "requested_at",
        "reviewed_at",
        "reviewed_by",
        "scope_key",
        "status",
    )

    def __init__(  # noqa: PLR0913, PLR0917 - mirrors database row
        self,
        request_id: UUID,
        employee_id: str,
        nrp: str,
        full_name: str,
        old_wa_jid: str,
        new_wa_jid: str,
        scope_key: str,
        status: str,
        requested_at: datetime,
        reviewed_by: str | None,
        reviewed_at: datetime | None,
        rejection_reason: str | None,
    ) -> None:
        self.request_id = request_id
        self.employee_id = employee_id
        self.nrp = nrp
        self.full_name = full_name
        self.old_wa_jid = old_wa_jid
        self.new_wa_jid = new_wa_jid
        self.scope_key = scope_key
        self.status = status
        self.requested_at = requested_at
        self.reviewed_by = reviewed_by
        self.reviewed_at = reviewed_at
        self.rejection_reason = rejection_reason


def _to_request(row: _RebindRow) -> RebindRequest:
    return RebindRequest(
        id=row.request_id,
        employee_id=row.employee_id,
        nrp=row.nrp,
        full_name=row.full_name,
        old_wa_jid=row.old_wa_jid,
        new_wa_jid=row.new_wa_jid,
        scope_key=row.scope_key,
        status=RebindStatus(row.status),
        requested_at=row.requested_at,
        reviewed_by=row.reviewed_by,
        reviewed_at=row.reviewed_at,
        rejection_reason=row.rejection_reason,
    )


_REBIND_SELECT = """
    SELECT r.id AS request_id,
           r.employee_id,
           e.nrp,
           e.full_name,
           r.old_wa_jid,
           r.new_wa_jid,
           r.scope_key,
           r.status,
           r.requested_at,
           r.reviewed_by,
           r.reviewed_at,
           r.rejection_reason
    FROM identity_rebind_requests r
    JOIN employees e ON e.employee_id = r.employee_id
"""


@final
class IdentityRebindService:
    def __init__(self, dsn: str, connect_timeout_seconds: int = 5) -> None:
        self._dsn = dsn
        self._connect_timeout_seconds = connect_timeout_seconds

    def _connect(self) -> psycopg.Connection[tuple[object, ...]]:
        return psycopg.connect(self._dsn, connect_timeout=self._connect_timeout_seconds)

    async def stage(self, wa_jid: str, employee_id: str) -> None:
        await run_sync(self._stage, wa_jid, employee_id)

    async def staged(self, wa_jid: str) -> str | None:
        return await run_sync(self._staged, wa_jid)

    async def clear_stage(self, wa_jid: str) -> None:
        await run_sync(self._clear_stage, wa_jid)

    async def request(
        self, employee_id: str, new_wa_jid: str, scope_key: str = "default"
    ) -> RebindRequestResult:
        return await run_sync(self._request, employee_id, new_wa_jid, scope_key)

    async def pending(self, scope_key: str | None = None) -> tuple[RebindRequest, ...]:
        return await run_sync(self._pending, scope_key)

    async def decide(
        self,
        request_id: UUID,
        reviewer: str,
        *,
        approve: bool,
        rejection_reason: str | None = None,
    ) -> RebindDecisionResult:
        return await run_sync(self._decide, request_id, reviewer, approve, rejection_reason)

    def _stage(self, wa_jid: str, employee_id: str) -> None:
        try:
            with self._connect() as connection, connection.cursor() as cursor:
                _ = cursor.execute(
                    """
                    INSERT INTO bot_conversations (wa_jid, pending_rebind_employee_id, updated_at)
                    VALUES (%s,%s,now())
                    ON CONFLICT (wa_jid) DO UPDATE SET
                        pending_rebind_employee_id = EXCLUDED.pending_rebind_employee_id,
                        updated_at = now()
                    """,
                    (wa_jid, employee_id),
                )
        except psycopg.Error as error:
            raise InfrastructureError(service="postgres", operation="stage_identity_rebind") from error

    def _staged(self, wa_jid: str) -> str | None:
        try:
            with self._connect() as connection, connection.cursor() as cursor:
                _ = cursor.execute(
                    "SELECT pending_rebind_employee_id FROM bot_conversations WHERE wa_jid = %s",
                    (wa_jid,),
                )
                row = cursor.fetchone()
                return None if row is None or row[0] is None else str(row[0])
        except psycopg.Error as error:
            raise InfrastructureError(service="postgres", operation="load_staged_identity_rebind") from error

    def _clear_stage(self, wa_jid: str) -> None:
        try:
            with self._connect() as connection, connection.cursor() as cursor:
                _ = cursor.execute(
                    """
                    UPDATE bot_conversations
                    SET pending_rebind_employee_id = NULL, updated_at = now()
                    WHERE wa_jid = %s
                    """,
                    (wa_jid,),
                )
        except psycopg.Error as error:
            raise InfrastructureError(service="postgres", operation="clear_staged_identity_rebind") from error

    def _request(
        self, employee_id: str, new_wa_jid: str, scope_key: str
    ) -> RebindRequestResult:
        try:
            with self._connect() as connection, connection.cursor() as cursor:
                _ = cursor.execute(
                    "SELECT wa_jid FROM wa_identity WHERE employee_id = %s FOR UPDATE",
                    (employee_id,),
                )
                existing = cursor.fetchone()
                if existing is None:
                    return RebindRequestResult(RebindRequestOutcome.NO_EXISTING_BINDING)
                old_wa_jid = str(existing[0])
                if old_wa_jid == new_wa_jid:
                    return RebindRequestResult(RebindRequestOutcome.SAME_NUMBER)
                _ = cursor.execute("SELECT 1 FROM wa_identity WHERE wa_jid = %s", (new_wa_jid,))
                if cursor.fetchone() is not None:
                    return RebindRequestResult(RebindRequestOutcome.NEW_NUMBER_ALREADY_BOUND)
                _ = cursor.execute("SELECT 1 FROM wa_operator_identity WHERE wa_jid = %s", (new_wa_jid,))
                if cursor.fetchone() is not None:
                    return RebindRequestResult(RebindRequestOutcome.NEW_NUMBER_ALREADY_BOUND)
                try:
                    _ = cursor.execute(
                        """
                        INSERT INTO identity_rebind_requests (
                            employee_id, old_wa_jid, new_wa_jid, scope_key
                        ) VALUES (%s,%s,%s,%s)
                        RETURNING id
                        """,
                        (employee_id, old_wa_jid, new_wa_jid, scope_key),
                    )
                    created = cursor.fetchone()
                except psycopg.errors.UniqueViolation:
                    connection.rollback()
                    return RebindRequestResult(RebindRequestOutcome.ALREADY_PENDING)
                return RebindRequestResult(
                    RebindRequestOutcome.CREATED,
                    UUID(str(created[0])) if created is not None else None,
                )
        except psycopg.Error as error:
            raise InfrastructureError(service="postgres", operation="request_identity_rebind") from error

    def _pending(self, scope_key: str | None) -> tuple[RebindRequest, ...]:
        try:
            with (
                self._connect() as connection,
                connection.cursor(row_factory=class_row(_RebindRow)) as cursor,
            ):
                if scope_key is None:
                    _ = cursor.execute(
                        _REBIND_SELECT + " WHERE r.status = 'pending' ORDER BY r.requested_at"
                    )
                else:
                    _ = cursor.execute(
                        _REBIND_SELECT
                        + " WHERE r.status = 'pending' AND r.scope_key = %s ORDER BY r.requested_at",
                        (scope_key,),
                    )
                return tuple(_to_request(row) for row in cursor.fetchall())
        except psycopg.Error as error:
            raise InfrastructureError(service="postgres", operation="list_identity_rebind_queue") from error

    def _decide(  # noqa: PLR0911
        self,
        request_id: UUID,
        reviewer: str,
        approve: bool,
        rejection_reason: str | None,
    ) -> RebindDecisionResult:
        if not approve and not (rejection_reason or "").strip():
            return RebindDecisionResult(RebindDecisionOutcome.REJECTION_REASON_REQUIRED)
        try:
            with self._connect() as connection, connection.cursor() as cursor:
                _ = cursor.execute(
                    """
                    SELECT employee_id, old_wa_jid, new_wa_jid, status
                    FROM identity_rebind_requests
                    WHERE id = %s
                    FOR UPDATE
                    """,
                    (request_id,),
                )
                row = cursor.fetchone()
                if row is None:
                    return RebindDecisionResult(RebindDecisionOutcome.NOT_FOUND)
                current_status = RebindStatus(str(row[3]))
                if current_status is not RebindStatus.PENDING:
                    return RebindDecisionResult(
                        RebindDecisionOutcome.ALREADY_RESOLVED, current_status
                    )
                employee_id = str(row[0])
                old_wa_jid = str(row[1])
                new_wa_jid = str(row[2])
                new_status = RebindStatus.APPROVED if approve else RebindStatus.REJECTED
                if approve:
                    _ = cursor.execute(
                        "SELECT wa_jid FROM wa_identity WHERE employee_id = %s FOR UPDATE",
                        (employee_id,),
                    )
                    current = cursor.fetchone()
                    if current is None or str(current[0]) != old_wa_jid:
                        return RebindDecisionResult(RebindDecisionOutcome.SOURCE_CHANGED)
                    _ = cursor.execute(
                        "SELECT 1 FROM wa_identity WHERE wa_jid = %s AND employee_id <> %s",
                        (new_wa_jid, employee_id),
                    )
                    if cursor.fetchone() is not None:
                        return RebindDecisionResult(
                            RebindDecisionOutcome.NEW_NUMBER_ALREADY_BOUND
                        )
                    _ = cursor.execute(
                        "SELECT 1 FROM wa_operator_identity WHERE wa_jid = %s",
                        (new_wa_jid,),
                    )
                    if cursor.fetchone() is not None:
                        return RebindDecisionResult(
                            RebindDecisionOutcome.NEW_NUMBER_ALREADY_BOUND
                        )
                    _ = cursor.execute(
                        "UPDATE wa_identity SET wa_jid = %s WHERE employee_id = %s",
                        (new_wa_jid, employee_id),
                    )
                    _ = cursor.execute(
                        "DELETE FROM bot_conversations WHERE wa_jid IN (%s,%s)",
                        (old_wa_jid, new_wa_jid),
                    )
                _ = cursor.execute(
                    """
                    UPDATE identity_rebind_requests
                    SET status = %s,
                        reviewed_by = %s,
                        reviewed_at = now(),
                        rejection_reason = %s
                    WHERE id = %s
                    """,
                    (
                        new_status.value,
                        reviewer,
                        None if approve else (rejection_reason or "").strip(),
                        request_id,
                    ),
                )
                return RebindDecisionResult(RebindDecisionOutcome.UPDATED, new_status)
        except psycopg.Error as error:
            raise InfrastructureError(service="postgres", operation="decide_identity_rebind") from error
