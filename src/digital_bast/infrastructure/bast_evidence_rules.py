"""Read BAST evidence requirements by stable task category."""

from __future__ import annotations

from typing import final

import psycopg
from anyio.to_thread import run_sync

from digital_bast.infrastructure.errors import InfrastructureError


@final
class PostgresBastEvidenceRequirementReader:
    def __init__(
        self,
        dsn: str,
        scope_key: str = "default",
        connect_timeout_seconds: int = 5,
    ) -> None:
        self._dsn = dsn
        self._scope_key = scope_key
        self._connect_timeout_seconds = connect_timeout_seconds

    async def requirements(self) -> dict[str, bool]:
        return await run_sync(self._requirements)

    def _requirements(self) -> dict[str, bool]:
        try:
            with (
                psycopg.connect(
                    self._dsn,
                    connect_timeout=self._connect_timeout_seconds,
                ) as connection,
                connection.cursor() as cursor,
            ):
                _ = cursor.execute(
                    """
                    SELECT task_category, evidence_required
                    FROM bast_evidence_rules
                    WHERE scope_key = %s
                    """,
                    (self._scope_key,),
                )
                rows = cursor.fetchall()
        except psycopg.Error as error:
            raise InfrastructureError(
                service="postgres",
                operation="bast_evidence_requirements",
            ) from error
        return {str(category): bool(required) for category, required in rows}
