"""Roster from the `employees` table.

Replaces the three rosters that used to coexist -- employee_data.json,
NocoDB "Employee Data", and the DISTINCT-over-durable_records query in
postgres_sql.EMPLOYEES -- with the single table both the pipeline and NocoDB
read and write.

Only `status = 'Active'` rows are returned, matching what the NocoDB employee
source filtered on.
"""

from __future__ import annotations

from typing import final

import psycopg
from anyio.to_thread import run_sync
from psycopg.rows import class_row

from digital_bast.domain.models import Employee, EmployeeId, EmployeeRole
from digital_bast.infrastructure.errors import InfrastructureError


class _EmployeeRow:
    __slots__ = ("employee_id", "full_name", "nrp", "role")

    def __init__(self, employee_id: str, nrp: str, full_name: str, role: str) -> None:
        self.employee_id = employee_id
        self.nrp = nrp
        self.full_name = full_name
        self.role = role


@final
class PostgresEmployeeSource:
    def __init__(self, dsn: str, connect_timeout_seconds: int = 5) -> None:
        self._dsn = dsn
        self._connect_timeout_seconds = connect_timeout_seconds

    async def load(self) -> tuple[Employee, ...]:
        return await run_sync(self._load)

    def _load(self) -> tuple[Employee, ...]:
        try:
            with (
                psycopg.connect(
                    self._dsn, connect_timeout=self._connect_timeout_seconds
                ) as connection,
                connection.cursor(row_factory=class_row(_EmployeeRow)) as cursor,
            ):
                _ = cursor.execute(
                    "SELECT employee_id, nrp, full_name, role FROM employees"
                    " WHERE status = 'Active' ORDER BY full_name"
                )
                rows = cursor.fetchall()
        except psycopg.Error as error:
            raise InfrastructureError(service="postgres", operation="load_employees") from error
        return tuple(
            Employee(
                id=EmployeeId(row.employee_id),
                external_id=row.nrp,
                name=row.full_name,
                role=EmployeeRole(row.role),
            )
            for row in rows
        )
