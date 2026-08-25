from __future__ import annotations

from typing import final

import psycopg
from anyio.to_thread import run_sync

from digital_bast.infrastructure.errors import InfrastructureError


@final
class PostgresWhatsAppIdentityResolver:
    def __init__(self, dsn: str, connect_timeout_seconds: int = 5) -> None:
        self._dsn = dsn
        self._connect_timeout_seconds = connect_timeout_seconds

    async def jid_for_employee(self, employee_id: str) -> str | None:
        return await run_sync(self._jid_for_employee, employee_id)

    def _jid_for_employee(self, employee_id: str) -> str | None:
        try:
            with psycopg.connect(
                self._dsn,
                connect_timeout=self._connect_timeout_seconds,
            ) as connection, connection.cursor() as cursor:
                _ = cursor.execute(
                    "SELECT wa_jid FROM wa_identity WHERE employee_id = %s",
                    (employee_id,),
                )
                row = cursor.fetchone()
        except psycopg.Error as error:
            raise InfrastructureError(
                service="postgres",
                operation="resolve_whatsapp_identity",
            ) from error
        return None if row is None else str(row[0])
