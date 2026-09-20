"""PostgreSQL metadata history for Payroll attendance CSV exports."""

from __future__ import annotations

from typing import TYPE_CHECKING, final

import psycopg
from anyio.to_thread import run_sync
from psycopg.rows import class_row

from digital_bast.application.payroll_export import PayrollExportRecord
from digital_bast.infrastructure.errors import InfrastructureError

if TYPE_CHECKING:
    from datetime import date, datetime
    from uuid import UUID

_MAX_HISTORY_LIMIT = 200

_INSERT_SQL = """
    INSERT INTO payroll_export_history (
        export_id,
        cycle_id,
        cycle_label,
        start_date,
        end_date,
        exported_at,
        exported_by,
        report_type,
        role_filter,
        employee_filter,
        filename,
        result,
        row_count
    )
    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
    RETURNING
        export_id,
        cycle_id,
        cycle_label,
        start_date,
        end_date,
        exported_at,
        exported_by,
        report_type,
        role_filter,
        employee_filter,
        filename,
        result,
        row_count
"""
_LIST_SQL = """
    SELECT
        export_id,
        cycle_id,
        cycle_label,
        start_date,
        end_date,
        exported_at,
        exported_by,
        report_type,
        role_filter,
        employee_filter,
        filename,
        result,
        row_count
    FROM payroll_export_history
    ORDER BY exported_at DESC, export_id DESC
    LIMIT %s
"""
_LIST_CYCLE_SQL = """
    SELECT
        export_id,
        cycle_id,
        cycle_label,
        start_date,
        end_date,
        exported_at,
        exported_by,
        report_type,
        role_filter,
        employee_filter,
        filename,
        result,
        row_count
    FROM payroll_export_history
    WHERE cycle_id = %s
    ORDER BY exported_at DESC, export_id DESC
    LIMIT %s
"""


class _PayrollExportRow:
    __slots__ = (
        "cycle_id",
        "cycle_label",
        "employee_filter",
        "end_date",
        "export_id",
        "exported_at",
        "exported_by",
        "filename",
        "report_type",
        "result",
        "role_filter",
        "row_count",
        "start_date",
    )

    def __init__(  # noqa: PLR0913, PLR0917 - mirrors selected database columns
        self,
        export_id: UUID,
        cycle_id: str,
        cycle_label: str,
        start_date: date,
        end_date: date,
        exported_at: datetime,
        exported_by: str,
        report_type: str,
        role_filter: str,
        employee_filter: str | None,
        filename: str,
        result: str,
        row_count: int,
    ) -> None:
        self.export_id = export_id
        self.cycle_id = cycle_id
        self.cycle_label = cycle_label
        self.start_date = start_date
        self.end_date = end_date
        self.exported_at = exported_at
        self.exported_by = exported_by
        self.report_type = report_type
        self.role_filter = role_filter
        self.employee_filter = employee_filter
        self.filename = filename
        self.result = result
        self.row_count = row_count


def _record(row: _PayrollExportRow) -> PayrollExportRecord:
    return PayrollExportRecord(
        export_id=row.export_id,
        cycle_id=row.cycle_id,
        cycle_label=row.cycle_label,
        start_date=row.start_date,
        end_date=row.end_date,
        exported_at=row.exported_at,
        exported_by=row.exported_by,
        report_type=row.report_type,
        role_filter=row.role_filter,
        employee_filter=row.employee_filter,
        filename=row.filename,
        result=row.result,
        row_count=row.row_count,
    )


@final
class PostgresPayrollExportHistoryStore:
    def __init__(self, dsn: str, connect_timeout_seconds: int = 5) -> None:
        self._dsn = dsn
        self._connect_timeout_seconds = connect_timeout_seconds

    def _connect(self) -> psycopg.Connection[tuple[object, ...]]:
        return psycopg.connect(self._dsn, connect_timeout=self._connect_timeout_seconds)

    async def record(self, item: PayrollExportRecord) -> PayrollExportRecord:
        return await run_sync(self._record, item)

    async def list(
        self,
        *,
        cycle_id: str | None = None,
        limit: int = 50,
    ) -> tuple[PayrollExportRecord, ...]:
        if not 1 <= limit <= _MAX_HISTORY_LIMIT:
            message = (
                "payroll export history limit must be between "
                f"1 and {_MAX_HISTORY_LIMIT}"
            )
            raise ValueError(message)
        return await run_sync(self._list, cycle_id, limit)

    def _record(self, item: PayrollExportRecord) -> PayrollExportRecord:
        try:
            with (
                self._connect() as connection,
                connection.cursor(row_factory=class_row(_PayrollExportRow)) as cursor,
            ):
                _ = cursor.execute(
                    _INSERT_SQL,
                    (
                        item.export_id,
                        item.cycle_id,
                        item.cycle_label,
                        item.start_date,
                        item.end_date,
                        item.exported_at,
                        item.exported_by,
                        item.report_type,
                        item.role_filter,
                        item.employee_filter,
                        item.filename,
                        item.result,
                        item.row_count,
                    ),
                )
                row = cursor.fetchone()
        except psycopg.Error as error:
            raise InfrastructureError(
                service="postgres",
                operation="record_payroll_export_history",
            ) from error
        if row is None:
            raise InfrastructureError(
                service="postgres",
                operation="reload_payroll_export_history",
            )
        return _record(row)

    def _list(
        self,
        cycle_id: str | None,
        limit: int,
    ) -> tuple[PayrollExportRecord, ...]:
        try:
            with (
                self._connect() as connection,
                connection.cursor(row_factory=class_row(_PayrollExportRow)) as cursor,
            ):
                if cycle_id is None:
                    _ = cursor.execute(_LIST_SQL, (limit,))
                else:
                    _ = cursor.execute(_LIST_CYCLE_SQL, (cycle_id, limit))
                rows = cursor.fetchall()
        except psycopg.Error as error:
            raise InfrastructureError(
                service="postgres",
                operation="list_payroll_export_history",
            ) from error
        return tuple(_record(row) for row in rows)
