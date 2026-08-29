"""Read-only helper used before legacy onboarding attempts a WhatsApp bind."""

from __future__ import annotations

from typing import final

import psycopg
from anyio.to_thread import run_sync

from digital_bast.infrastructure.errors import InfrastructureError


@final
class RebindOnboardingService:
    def __init__(self, dsn: str, connect_timeout_seconds: int = 5) -> None:
        self._dsn = dsn
        self._connect_timeout_seconds = connect_timeout_seconds

    async def existing_jid(self, employee_id: str) -> str | None:
        return await run_sync(self._existing_jid, employee_id)

    def _existing_jid(self, employee_id: str) -> str | None:
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
            raise InfrastructureError(service="postgres", operation="lookup_existing_wa_binding") from error
        return None if row is None else str(row[0])
