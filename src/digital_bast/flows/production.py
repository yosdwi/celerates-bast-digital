from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Final, Protocol, final, override

from holidays import country_holidays

from digital_bast.application.services import BatchResult, PipelineService
from digital_bast.config import get_settings
from digital_bast.domain.reference import HolidayInput, transform_holiday
from digital_bast.domain.timesheets import TimesheetOptions
from digital_bast.flows.models import Operation, Period, StepSummary
from digital_bast.flows.production_operations import (
    IoTPicUpdateOperation,
    IoTTaskImportOperation,
    ReconciliationOperation,
    RedmineTaskImportOperation,
    ScheduleSyncOperation,
    TimesheetGenerationOperation,
)
from digital_bast.infrastructure.google_api import GoogleApiSheetBatchReader
from digital_bast.infrastructure.healthcheck import PostgresHealthcheck
from digital_bast.infrastructure.legacy_pic import LegacyIoTPicUpdater
from digital_bast.infrastructure.nocodb_repository import NocoDBDomainRepository
from digital_bast.infrastructure.production_sources import (
    EmployeeSource,
    GoogleIoTTaskSource,
    NocoDBPostgresEmployeeSource,
    SqlServerRedmineTaskSource,
)
from digital_bast.infrastructure.repositories import (
    PostgresCursorStore,
    PostgresStoredProcedureAdapter,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

    from digital_bast.application.ports import DomainRepository
    from digital_bast.domain.models import DomainRecord


class ProductionOperationUnavailableError(RuntimeError):
    def __init__(self, operation: Operation, gap: str) -> None:
        super().__init__(operation, gap)
        self.operation: Operation = operation
        self.gap: str = gap

    @override
    def __str__(self) -> str:
        return (
            f"operation {self.operation.value!r} requires unavailable production adapter: "
            f"{self.gap}"
        )


class DisabledOperationsConfigurationError(ValueError):
    def __init__(self, value: str) -> None:
        super().__init__(value)
        self.value: str = value

    @override
    def __str__(self) -> str:
        return f"invalid disabled operation {self.value!r}"


class HolidaySource(Protocol):
    def load(self, year: int) -> tuple[HolidayInput, ...]: ...


class RecordUpserter(Protocol):
    async def upsert(self, records: tuple[DomainRecord, ...]) -> BatchResult: ...


class ProductionOperation(Protocol):
    async def execute(self, period: Period) -> StepSummary: ...


_LOCAL_EMPLOYEE_FILE: Final = Path(__file__).resolve().parents[3] / "employee_data.json"

_OPERATION_GAPS: Final = {
    Operation.ATTENDANCE_IMPORT: "SQL Server attendance-to-employee mapping",
    Operation.REDMINE_IMPORT: "SQL Server Redmine employee mapping",
    Operation.IOT_TASK_IMPORT: "Google Sheets task source and field mapping",
    Operation.RECONCILIATION: "reconciliation rule adapter",
    Operation.HOLIDAY_SYNC: "holiday sync adapter",
    Operation.SCHEDULE_SYNC: "IoT employee source and schedule mapping",
    Operation.TIMESHEET_GENERATION: "employee inventory and production timesheet options",
    Operation.IOT_PIC_UPDATE: "legacy NocoDB PostgreSQL DSN for sp_update_tasklist_iot_pic",
}


@final
class IndonesiaHolidaySource:
    def load(self, year: int) -> tuple[HolidayInput, ...]:
        calendar = country_holidays("ID", years=year)
        return tuple(HolidayInput(work_date, name) for work_date, name in calendar.items())


@final
class HolidaySyncOperation:
    def __init__(self, source: HolidaySource, records: RecordUpserter) -> None:
        self._source: HolidaySource = source
        self._records: RecordUpserter = records

    async def execute(self, period: Period) -> StepSummary:
        holidays = tuple(transform_holiday(value) for value in self._source.load(period.year))
        result = await self._records.upsert(holidays)
        return StepSummary(
            operation=Operation.HOLIDAY_SYNC,
            read=len(holidays),
            written=result.created_or_updated,
            unchanged=result.unchanged,
            locked=result.locked,
        )


@final
class ProductionRunContext:
    def __init__(
        self,
        disabled_operations: frozenset[Operation] = frozenset(),
        operations: Mapping[Operation, ProductionOperation] | None = None,
    ) -> None:
        self._disabled_operations: frozenset[Operation] = disabled_operations
        self._operations: dict[Operation, ProductionOperation] = dict(operations or {})

    def now(self) -> datetime:
        return datetime.now(UTC)

    async def execute(self, operation: Operation, period: Period) -> StepSummary:
        if operation in self._disabled_operations:
            return StepSummary(operation=operation, read=0, written=0)
        active = self._operations.get(operation)
        if active is None:
            raise ProductionOperationUnavailableError(operation, _OPERATION_GAPS[operation])
        return await active.execute(period)


def disabled_operations(value: str | None) -> frozenset[Operation]:
    if value is None or not value.strip():
        return frozenset()
    try:
        return frozenset(Operation(item.strip()) for item in value.split(","))
    except ValueError as error:
        raise DisabledOperationsConfigurationError(value) from error


def create_run_context() -> ProductionRunContext:
    # local: NocoDB/the OVH VPS is unreachable. When NOCODB_DATABASE_DSN and
    # NOCODB_BASE_ID aren't set, wire the same PipelineService against
    # PostgresDomainRepository + LocalEmployeeSource instead -- same fallback
    # shape as operations.py::_default_completion_source. Operations whose
    # adapter isn't configured (IOT_PIC_UPDATE without NocoDB, IOT_TASK_IMPORT
    # without Google credentials) are left out of the map entirely and report
    # unavailable if run, rather than blocking every other operation.
    from digital_bast.infrastructure.local_completion_source import (  # noqa: PLC0415
        LocalEmployeeSource,
    )
    from digital_bast.infrastructure.repositories import (  # noqa: PLC0415
        PostgresDomainRepository,
    )

    settings = get_settings()
    database_dsn = settings.database_dsn
    if database_dsn is None:
        raise ProductionOperationUnavailableError(
            Operation.HOLIDAY_SYNC,
            "APP_DATABASE_DSN",
        )
    dsn = database_dsn.get_secret_value()
    nocodb_database_dsn = settings.nocodb_database_dsn
    nocodb_base_id = settings.nocodb_base_id

    repository: DomainRepository
    employees: EmployeeSource
    if nocodb_database_dsn is not None and nocodb_base_id is not None:
        nocodb_dsn = nocodb_database_dsn.get_secret_value()
        repository = NocoDBDomainRepository(nocodb_dsn, nocodb_base_id)
        employees = NocoDBPostgresEmployeeSource(nocodb_dsn, nocodb_base_id)
    else:
        repository = PostgresDomainRepository(dsn)
        employees = LocalEmployeeSource(_LOCAL_EMPLOYEE_FILE)

    pipeline = PipelineService(
        repository,
        PostgresCursorStore(dsn),
        PostgresStoredProcedureAdapter(PostgresHealthcheck(dsn)),
    )
    operations: dict[Operation, ProductionOperation] = {
        Operation.RECONCILIATION: ReconciliationOperation(repository),
        Operation.HOLIDAY_SYNC: HolidaySyncOperation(IndonesiaHolidaySource(), pipeline),
        Operation.SCHEDULE_SYNC: ScheduleSyncOperation(employees, pipeline),
        Operation.TIMESHEET_GENERATION: TimesheetGenerationOperation(
            employees,
            repository,
            pipeline,
            TimesheetOptions(
                settings.timesheet_weekday_activity,
                settings.timesheet_weekend_activity,
                settings.timesheet_iot_activity,
                settings.timesheet_default_project,
            ),
        ),
    }
    google_credentials = settings.google_application_credentials
    if google_credentials is not None:
        iot_source = GoogleIoTTaskSource(
            GoogleApiSheetBatchReader(google_credentials),
            settings.google_iot_spreadsheet_id,
            settings.google_iot_sheet_name,
        )
        operations[Operation.IOT_TASK_IMPORT] = IoTTaskImportOperation(
            employees, iot_source, pipeline
        )
    if nocodb_database_dsn is not None and nocodb_base_id is not None:
        operations[Operation.IOT_PIC_UPDATE] = IoTPicUpdateOperation(
            LegacyIoTPicUpdater(nocodb_database_dsn.get_secret_value()),
        )
    redmine_password = settings.redmine_db_password
    if settings.redmine_db_server is not None and redmine_password is not None:
        redmine_source = SqlServerRedmineTaskSource(
            settings.redmine_db_server,
            settings.redmine_db_username or "",
            redmine_password.get_secret_value(),
            settings.redmine_db_name,
        )
        operations[Operation.REDMINE_IMPORT] = RedmineTaskImportOperation(
            employees, redmine_source, pipeline
        )

    return ProductionRunContext(
        disabled_operations(os.getenv("DIGITAL_BAST_DISABLED_OPERATIONS")),
        operations,
    )
