from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import final
from uuid import UUID, uuid4

import psycopg
from anyio.to_thread import run_sync
from psycopg.rows import TupleRow, class_row
from psycopg.types.json import Jsonb

from digital_bast.web.contracts import (
    AttendanceRow,
    EmployeeOption,
    GenerationPlanInput,
    GenerationResult,
    ReportItem,
    ReportView,
    SectionInput,
    StreamSectionInput,
)
from digital_bast.web.csv_export import legacy_attendance_csv
from digital_bast.web.errors import WebBackendUnavailableError
from digital_bast.web.postgres_models import (
    AttendanceRecord,
    EmployeeRow,
    PlanRow,
    PlanSection,
    ReportRow,
    StoredPlan,
)
from digital_bast.web.postgres_sql import (
    ATTENDANCE,
    ATTENDANCE_LEGACY,
    EMPLOYEES,
    INSERT_PLAN,
    REPORT,
    UPDATE_PLAN,
)


@final
class PostgresWebBackend:
    def __init__(self, dsn: str, connect_timeout_seconds: int = 5) -> None:
        self._dsn = dsn
        self._connect_timeout_seconds = connect_timeout_seconds

    async def ready(self) -> bool:
        return await run_sync(self._ready)

    async def report(
        self, report_type: str, year: int, month: int, evidence_only: bool
    ) -> ReportView:
        return await run_sync(self._report, report_type, year, month, evidence_only)

    async def employees(self) -> tuple[EmployeeOption, ...]:
        return await run_sync(self._employees)

    async def attendance(
        self, employee_names: tuple[str, ...], start_date: date, end_date: date
    ) -> tuple[AttendanceRow, ...]:
        return await run_sync(self._attendance, employee_names, start_date, end_date)

    async def attendance_legacy(
        self, role: str, start_date: date, end_date: date, employee: str | None = None
    ) -> tuple[str, int]:
        return await run_sync(self._attendance_legacy, role, start_date, end_date, employee)

    async def create_plan(self, request: GenerationPlanInput) -> GenerationResult:
        return await run_sync(self._create_plan, request)

    async def generate_section(self, request: SectionInput) -> GenerationResult:
        return await run_sync(self._generate_section, request)

    async def bulk_data(self, plan_id: str) -> GenerationResult:
        return await run_sync(self._bulk_data, plan_id)

    async def store_section(self, request: StreamSectionInput) -> int:
        return await run_sync(self._store_section, request)

    def _ready(self) -> bool:
        try:
            with self._connect() as connection:
                row = connection.execute(
                    "SELECT to_regclass('public.tasks') IS NOT NULL"
                ).fetchone()
                return row is not None and row[0] is True
        except psycopg.Error:
            return False

    def _report(self, report_type: str, year: int, month: int, evidence_only: bool) -> ReportView:
        try:
            with (
                self._connect() as connection,
                connection.cursor(row_factory=class_row(ReportRow)) as cursor,
            ):
                _ = cursor.execute(REPORT, (year, month, report_type, evidence_only))
                rows = cursor.fetchall()
        except psycopg.Error as error:
            raise WebBackendUnavailableError(operation="report") from error
        items = tuple(
            ReportItem(
                label=row.title,
                value=" · ".join(
                    value for value in (str(row.work_date), row.status, row.achievement) if value
                ),
            )
            for row in rows
        )
        label = "IoT Operations" if report_type == "iotoperation" else "Developer"
        return ReportView(f"{label} report {year:04d}-{month:02d}", items)

    def _employees(self) -> tuple[EmployeeOption, ...]:
        try:
            with (
                self._connect() as connection,
                connection.cursor(row_factory=class_row(EmployeeRow)) as cursor,
            ):
                _ = cursor.execute(EMPLOYEES)
                return tuple(EmployeeOption(row.name, row.role) for row in cursor.fetchall())
        except psycopg.Error as error:
            raise WebBackendUnavailableError(operation="employees") from error

    def _attendance(
        self, employee_names: tuple[str, ...], start_date: date, end_date: date
    ) -> tuple[AttendanceRow, ...]:
        try:
            with (
                self._connect() as connection,
                connection.cursor(row_factory=class_row(AttendanceRecord)) as cursor,
            ):
                selected = list(employee_names)
                _ = cursor.execute(ATTENDANCE, (start_date, end_date, selected, selected))
                rows = cursor.fetchall()
        except psycopg.Error as error:
            raise WebBackendUnavailableError(operation="attendance") from error
        return tuple(
            AttendanceRow(
                employee_id=row.employee_id,
                full_name=row.full_name,
                work_date=row.work_date,
                shift=row.shift,
                schedule_in=row.schedule_in,
                schedule_out=row.schedule_out,
                attendance_code=row.attendance_code,
                check_in=row.check_in,
                check_out=row.check_out,
                notes=row.notes,
            )
            for row in rows
        )

    def _attendance_legacy(
        self, role: str, start_date: date, end_date: date, employee: str | None
    ) -> tuple[str, int]:
        try:
            with self._connect() as connection, connection.cursor() as cursor:
                _ = cursor.execute(
                    ATTENDANCE_LEGACY, (start_date, end_date, role, employee, employee)
                )
                rows = tuple(row[0] for row in cursor.fetchall())
        except psycopg.Error as error:
            raise WebBackendUnavailableError(operation="attendance_legacy") from error
        return legacy_attendance_csv(rows), len(rows)

    def _create_plan(self, request: GenerationPlanInput) -> GenerationResult:
        plan_id = uuid4()
        plan = StoredPlan(
            report_type=request.type,
            year=request.year,
            month=request.month,
            sections=(
                PlanSection(id=0, title="Executive summary"),
                PlanSection(id=1, title="Evidence"),
                PlanSection(id=2, title="Closing"),
            ),
        )
        try:
            with self._connect() as connection:
                _ = connection.execute(
                    INSERT_PLAN,
                    (
                        plan_id,
                        "owner",
                        Jsonb(plan.model_dump(mode="json")),
                        datetime.now(UTC) + timedelta(days=30),
                    ),
                )
        except psycopg.Error as error:
            raise WebBackendUnavailableError(operation="create_plan") from error
        return GenerationResult(success=True, plan_id=str(plan_id), title="Report plan")

    def _generate_section(self, request: SectionInput) -> GenerationResult:
        row = self._load_plan(request.plan_id)
        if row is None or request.section_id >= len(row.plan.sections):
            return GenerationResult(
                success=False, plan_id=request.plan_id, error="Plan or section not found"
            )
        section = row.plan.sections[request.section_id]
        report = self._report(
            row.plan.report_type,
            row.plan.year,
            row.plan.month,
            evidence_only=False,
        )
        lines = tuple(f"- {item.label}: {item.value}" for item in report.items)
        content = "\n".join(lines) if lines else "No matching records were found."
        updated = section.model_copy(update={"content": content})
        sections = tuple(updated if item.id == updated.id else item for item in row.plan.sections)
        self._save_plan(row.id, row.plan.model_copy(update={"sections": sections}), "running")
        return GenerationResult(
            success=True,
            plan_id=request.plan_id,
            section_id=section.id,
            title=section.title,
            content=content,
        )

    def _bulk_data(self, plan_id: str) -> GenerationResult:
        row = self._load_plan(plan_id)
        if row is None:
            return GenerationResult(success=False, plan_id=plan_id, error="Plan not found")
        content = "\n\n".join(
            f"## {section.title}\n{section.content}" for section in row.plan.sections
        )
        return GenerationResult(
            success=True, plan_id=plan_id, title="Generated report", content=content
        )

    def _store_section(self, request: StreamSectionInput) -> int:
        row = self._load_plan(request.plan_id)
        if row is None:
            return 0
        sections = tuple(
            section.model_copy(update={"content": request.content})
            if section.title == request.title
            else section
            for section in row.plan.sections
        )
        self._save_plan(row.id, row.plan.model_copy(update={"sections": sections}), "running")
        return sum(section.content != "" for section in sections)

    def _load_plan(self, plan_id: str) -> PlanRow | None:
        try:
            identifier = UUID(plan_id)
        except ValueError:
            return None
        try:
            with (
                self._connect() as connection,
                connection.cursor(row_factory=class_row(PlanRow)) as cursor,
            ):
                _ = cursor.execute(
                    "SELECT id, plan FROM generation_plans WHERE id = %s",
                    (identifier,),
                )
                return cursor.fetchone()
        except psycopg.Error as error:
            raise WebBackendUnavailableError(operation="load_plan") from error

    def _save_plan(self, plan_id: UUID, plan: StoredPlan, status: str) -> None:
        try:
            with self._connect() as connection:
                _ = connection.execute(
                    UPDATE_PLAN,
                    (Jsonb(plan.model_dump(mode="json")), status, plan_id),
                )
        except psycopg.Error as error:
            raise WebBackendUnavailableError(operation="save_plan") from error

    def _connect(self) -> psycopg.Connection[TupleRow]:
        return psycopg.connect(self._dsn, connect_timeout=self._connect_timeout_seconds)
