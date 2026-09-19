from __future__ import annotations

from typing import Final, LiteralString, Protocol, final

import anyio.to_thread
import psycopg

from digital_bast.infrastructure.errors import InfrastructureError

LEGACY_PIC_UPDATE_SQL: Final[LiteralString] = (
    'INSERT INTO "pc38r6u1npuq0ul"."_nc_m2m_tasklist_develo_Employee Data" ('
    'tasklist_developer_copy_id, "Employee Data_id") '
    "SELECT DISTINCT a.id, b.id "
    'FROM "pc38r6u1npuq0ul"."Tasklist IoT Operations" AS a '
    "JOIN LATERAL ("
    "SELECT employee.id "
    'FROM "pc38r6u1npuq0ul"."Employee Data" AS employee '
    'WHERE employee."Employee_Name" % a."PIC_Selection" '
    'ORDER BY similarity(employee."Employee_Name", a."PIC_Selection") DESC, employee.id '
    "LIMIT 1"
    ") AS b ON TRUE "
    'LEFT JOIN "pc38r6u1npuq0ul"."_nc_m2m_tasklist_develo_Employee Data" AS c '
    "ON c.tasklist_developer_copy_id = a.id "
    "WHERE NULLIF(BTRIM(a.\"PIC_Selection\"), '') IS NOT NULL "
    "AND b.id IS NOT NULL "
    "AND c.tasklist_developer_copy_id IS NULL "
    "ON CONFLICT DO NOTHING"
)


class SyncExecutor(Protocol):
    def __call__(self, statement: LiteralString) -> int: ...


@final
class LegacyIoTPicUpdater:
    def __init__(self, dsn: str, *, executor: SyncExecutor | None = None) -> None:
        self._dsn = dsn
        self._executor: SyncExecutor = self._execute if executor is None else executor

    async def update(self) -> int:
        return await anyio.to_thread.run_sync(self._executor, LEGACY_PIC_UPDATE_SQL)

    def _execute(self, statement: LiteralString) -> int:
        try:
            with (
                psycopg.connect(self._dsn) as connection,
                connection.cursor() as cursor,
            ):
                _ = cursor.execute(statement)
                return cursor.rowcount
        except psycopg.Error as error:
            raise InfrastructureError(
                service="legacy-pic",
                operation="update",
            ) from error
