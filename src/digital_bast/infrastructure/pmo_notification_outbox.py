from __future__ import annotations

from typing import TYPE_CHECKING, cast, final

import psycopg
from anyio.to_thread import run_sync
from psycopg.rows import class_row

from digital_bast.application.pmo_notifications import (
    NotificationEnqueueCommand,
    NotificationOutboxItem,
)
from digital_bast.infrastructure.errors import InfrastructureError

if TYPE_CHECKING:
    from datetime import datetime
    from uuid import UUID

    from digital_bast.application.pmo_notifications import NotificationKind, NotificationStatus


class _OutboxRow:
    __slots__ = (
        "attempts",
        "dedupe_key",
        "kind",
        "message",
        "next_attempt_at",
        "operator_email",
        "outbox_id",
        "scope_key",
        "status",
    )

    def __init__(  # noqa: PLR0913, PLR0917 - mirrors selected database columns
        self,
        outbox_id: UUID,
        operator_email: str,
        scope_key: str,
        kind: str,
        dedupe_key: str,
        message: str,
        status: str,
        attempts: int,
        next_attempt_at: datetime,
    ) -> None:
        self.outbox_id = outbox_id
        self.operator_email = operator_email
        self.scope_key = scope_key
        self.kind = kind
        self.dedupe_key = dedupe_key
        self.message = message
        self.status = status
        self.attempts = attempts
        self.next_attempt_at = next_attempt_at


def _item(row: _OutboxRow) -> NotificationOutboxItem:
    return NotificationOutboxItem(
        id=row.outbox_id,
        operator_email=row.operator_email,
        scope_key=row.scope_key,
        kind=cast("NotificationKind", row.kind),
        dedupe_key=row.dedupe_key,
        message=row.message,
        status=cast("NotificationStatus", row.status),
        attempts=row.attempts,
        next_attempt_at=row.next_attempt_at,
    )


@final
class PostgresPmoNotificationOutbox:
    def __init__(
        self,
        dsn: str,
        scope_key: str = "default",
        connect_timeout_seconds: int = 5,
    ) -> None:
        self._dsn = dsn
        self._scope_key = scope_key
        self._connect_timeout_seconds = connect_timeout_seconds

    def _connect(self) -> psycopg.Connection[tuple[object, ...]]:
        return psycopg.connect(self._dsn, connect_timeout=self._connect_timeout_seconds)

    async def enqueue(self, command: NotificationEnqueueCommand) -> bool:
        return await run_sync(self._enqueue, command)

    async def due(self, now: datetime, limit: int = 100) -> tuple[NotificationOutboxItem, ...]:
        return await run_sync(self._due, now, limit)

    async def mark_sent(self, item_id: UUID, provider_message_id: str | None) -> None:
        await run_sync(self._mark_sent, item_id, provider_message_id)

    async def mark_failed(
        self,
        item_id: UUID,
        *,
        error_code: str,
        next_attempt_at: datetime,
        terminal: bool,
    ) -> None:
        await run_sync(self._mark_failed, item_id, error_code, next_attempt_at, terminal)

    def _enqueue(self, command: NotificationEnqueueCommand) -> bool:
        try:
            with self._connect() as connection, connection.cursor() as cursor:
                _ = cursor.execute(
                    """
                    INSERT INTO workflow_notification_outbox (
                        operator_email, scope_key, kind, dedupe_key, message, next_attempt_at
                    ) VALUES (%s,%s,%s,%s,%s,%s)
                    ON CONFLICT (operator_email, dedupe_key) DO NOTHING
                    """,
                    (
                        command.operator_email,
                        command.scope_key,
                        command.kind,
                        command.dedupe_key,
                        command.message,
                        command.available_at,
                    ),
                )
                return cursor.rowcount > 0
        except psycopg.Error as error:
            raise InfrastructureError(
                service="postgres",
                operation="enqueue_pmo_notification",
            ) from error

    def _due(self, now: datetime, limit: int) -> tuple[NotificationOutboxItem, ...]:
        try:
            with (
                self._connect() as connection,
                connection.cursor(row_factory=class_row(_OutboxRow)) as cursor,
            ):
                _ = cursor.execute(
                    """
                    SELECT id AS outbox_id,
                           operator_email,
                           scope_key,
                           kind,
                           dedupe_key,
                           message,
                           status,
                           attempts,
                           next_attempt_at
                    FROM workflow_notification_outbox
                    WHERE scope_key = %s
                      AND status = 'pending'
                      AND next_attempt_at <= %s
                    ORDER BY next_attempt_at, created_at, id
                    LIMIT %s
                    """,
                    (self._scope_key, now, limit),
                )
                return tuple(_item(row) for row in cursor.fetchall())
        except psycopg.Error as error:
            raise InfrastructureError(
                service="postgres",
                operation="list_due_pmo_notifications",
            ) from error

    def _mark_sent(self, item_id: UUID, provider_message_id: str | None) -> None:
        try:
            with self._connect() as connection, connection.cursor() as cursor:
                _ = cursor.execute(
                    """
                    UPDATE workflow_notification_outbox
                    SET status = 'sent',
                        attempts = attempts + 1,
                        provider_message_id = %s,
                        last_error = NULL,
                        sent_at = now()
                    WHERE id = %s AND status = 'pending'
                    """,
                    (provider_message_id, item_id),
                )
        except psycopg.Error as error:
            raise InfrastructureError(
                service="postgres",
                operation="mark_pmo_notification_sent",
            ) from error

    def _mark_failed(
        self,
        item_id: UUID,
        error_code: str,
        next_attempt_at: datetime,
        terminal: bool,
    ) -> None:
        try:
            with self._connect() as connection, connection.cursor() as cursor:
                _ = cursor.execute(
                    """
                    UPDATE workflow_notification_outbox
                    SET status = CASE WHEN %s THEN 'dead' ELSE 'pending' END,
                        attempts = attempts + 1,
                        next_attempt_at = %s,
                        last_error = %s
                    WHERE id = %s AND status = 'pending'
                    """,
                    (terminal, next_attempt_at, error_code, item_id),
                )
        except psycopg.Error as error:
            raise InfrastructureError(
                service="postgres",
                operation="mark_pmo_notification_failed",
            ) from error
