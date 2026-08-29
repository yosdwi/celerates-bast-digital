"""Small durable state for PMO WhatsApp actions that require a follow-up reason."""

from __future__ import annotations

from dataclasses import dataclass
from typing import final
from uuid import UUID

import psycopg
from anyio.to_thread import run_sync

from digital_bast.infrastructure.errors import InfrastructureError


@dataclass(frozen=True, slots=True)
class PmoPendingAction:
    action: str
    request_id: UUID


@final
class PmoDmStateService:
    def __init__(self, dsn: str, connect_timeout_seconds: int = 5) -> None:
        self._dsn = dsn
        self._connect_timeout_seconds = connect_timeout_seconds

    def _connect(self) -> psycopg.Connection[tuple[object, ...]]:
        return psycopg.connect(self._dsn, connect_timeout=self._connect_timeout_seconds)

    async def set(self, wa_jid: str, action: str, request_id: UUID) -> None:
        await run_sync(self._set, wa_jid, action, request_id)

    async def get(self, wa_jid: str) -> PmoPendingAction | None:
        return await run_sync(self._get, wa_jid)

    async def clear(self, wa_jid: str) -> None:
        await run_sync(self._clear, wa_jid)

    def _set(self, wa_jid: str, action: str, request_id: UUID) -> None:
        try:
            with self._connect() as connection, connection.cursor() as cursor:
                _ = cursor.execute(
                    """
                    INSERT INTO pmo_conversations (
                        wa_jid, pending_action, pending_request_id, updated_at
                    ) VALUES (%s,%s,%s,now())
                    ON CONFLICT (wa_jid) DO UPDATE SET
                        pending_action = EXCLUDED.pending_action,
                        pending_request_id = EXCLUDED.pending_request_id,
                        updated_at = now()
                    """,
                    (wa_jid, action, request_id),
                )
        except psycopg.Error as error:
            raise InfrastructureError(service="postgres", operation="set_pmo_dm_state") from error

    def _get(self, wa_jid: str) -> PmoPendingAction | None:
        try:
            with self._connect() as connection, connection.cursor() as cursor:
                _ = cursor.execute(
                    """
                    SELECT pending_action, pending_request_id
                    FROM pmo_conversations
                    WHERE wa_jid = %s
                      AND pending_action IS NOT NULL
                      AND pending_request_id IS NOT NULL
                    """,
                    (wa_jid,),
                )
                row = cursor.fetchone()
        except psycopg.Error as error:
            raise InfrastructureError(service="postgres", operation="get_pmo_dm_state") from error
        if row is None:
            return None
        return PmoPendingAction(str(row[0]), UUID(str(row[1])))

    def _clear(self, wa_jid: str) -> None:
        try:
            with self._connect() as connection, connection.cursor() as cursor:
                _ = cursor.execute("DELETE FROM pmo_conversations WHERE wa_jid = %s", (wa_jid,))
        except psycopg.Error as error:
            raise InfrastructureError(service="postgres", operation="clear_pmo_dm_state") from error
