from __future__ import annotations

from typing import TYPE_CHECKING, Annotated

from fastapi import APIRouter, HTTPException, Query, Request, status
from fastapi.responses import FileResponse
from pydantic import ValidationError

from digital_bast.application.attendance_closing_policy import payroll_cycle, payroll_cycle_for
from digital_bast.application.payroll_export import PayrollExportService
from digital_bast.application.workflow_control import WorkflowRole
from digital_bast.config import SettingsConfigurationError, get_settings
from digital_bast.domain.time import JAKARTA
from digital_bast.infrastructure.payroll_export_history import PostgresPayrollExportHistoryStore
from digital_bast.operations import export_attendance_report
from digital_bast.web.payroll_export_contracts import (
    PayrollExportHistoryItemResponse,
    PayrollExportHistoryResponse,
    PayrollExportInput,
)
from digital_bast.web.postgres_backend import PostgresWebBackend
from digital_bast.web.security import HeaderCsrf, require_session, verify_csrf

if TYPE_CHECKING:
    from datetime import datetime
    from pathlib import Path

    from digital_bast.application.attendance_closing_policy import PayrollCycle
    from digital_bast.domain.completion import DateRange
    from digital_bast.web.contracts import SessionRecord
    from digital_bast.web.dependencies import WebDependencies

_API_PREFIX = "/api/talentops/v1/payroll"
_ADMIN_ROLES = frozenset({"owner", "admin"})


def _configured_service(deps: WebDependencies) -> PayrollExportService | None:
    try:
        settings = get_settings()
    except (OSError, ValidationError, SettingsConfigurationError):
        return None
    if settings.database_dsn is None:
        return None

    dsn = settings.database_dsn.get_secret_value()
    backend = PostgresWebBackend(dsn)

    async def exporter(
        period: DateRange,
        report_type: str,
        employee: str | None,
    ) -> tuple[Path, int]:
        return await export_attendance_report(
            period,
            report_type,
            employee,
            backend=backend,
        )

    return PayrollExportService(
        exporter,
        PostgresPayrollExportHistoryStore(dsn),
        now=deps.now,
    )


async def _authorize(deps: WebDependencies, record: SessionRecord) -> None:
    if record.user.role.casefold() in _ADMIN_ROLES:
        return
    if deps.workflow_control is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Workflow authorization service is unavailable",
        )
    operator = await deps.workflow_control.operator(record.user.email)
    if operator is None or not operator.active or operator.role is not WorkflowRole.PMO:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="PMO access is inactive",
        )


def _selected_cycle(
    year: int | None,
    month: int | None,
    now: datetime,
) -> PayrollCycle:
    if (year is None) != (month is None):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="year and month must be provided together",
        )
    if year is None or month is None:
        return payroll_cycle_for(now.astimezone(JAKARTA).date())
    return payroll_cycle(year, month)


def payroll_export_router(
    deps: WebDependencies,
    export_service: PayrollExportService | None = None,
) -> APIRouter:
    router = APIRouter(prefix=_API_PREFIX, tags=["payroll"])

    def service() -> PayrollExportService:
        selected = export_service or _configured_service(deps)
        if selected is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Payroll export service is unavailable",
            )
        return selected

    async def export_csv(
        request: Request,
        payload: PayrollExportInput,
        year: Annotated[int | None, Query(ge=2020, le=2100)] = None,
        month: Annotated[int | None, Query(ge=1, le=12)] = None,
        csrf_token: HeaderCsrf = None,
    ) -> FileResponse:
        _, record = await require_session(
            request,
            deps.sessions,
            deps.cookie,
            deps.now,
            api=True,
        )
        verify_csrf(record, csrf_token)
        await _authorize(deps, record)
        cycle = _selected_cycle(year, month, deps.now())
        try:
            path, item = await service().export(
                cycle,
                report_type=payload.report_type,
                employee=payload.employee,
                exported_by=record.user.email,
            )
        except ValueError as error:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=str(error),
            ) from error
        return FileResponse(
            path,
            media_type="text/csv; charset=utf-8",
            filename=path.name,
            headers={
                "X-Payroll-Export-Id": str(item.export_id),
                "X-Payroll-Cycle-Id": item.cycle_id,
                "X-Payroll-Row-Count": str(item.row_count),
            },
        )

    async def history(
        request: Request,
        year: Annotated[int | None, Query(ge=2020, le=2100)] = None,
        month: Annotated[int | None, Query(ge=1, le=12)] = None,
        limit: Annotated[int, Query(ge=1, le=100)] = 20,
    ) -> PayrollExportHistoryResponse:
        _, record = await require_session(
            request,
            deps.sessions,
            deps.cookie,
            deps.now,
            api=True,
        )
        await _authorize(deps, record)
        cycle = _selected_cycle(year, month, deps.now())
        items = await service().history(cycle_id=cycle.cycle_id, limit=limit)
        return PayrollExportHistoryResponse(
            cycle_id=cycle.cycle_id,
            cycle_label=cycle.label,
            start_date=cycle.period.start,
            end_date=cycle.period.end,
            items=tuple(
                PayrollExportHistoryItemResponse.model_validate(item)
                for item in items
            ),
        )

    router.add_api_route("/exports", export_csv, methods=["POST"])
    router.add_api_route(
        "/exports/history",
        history,
        methods=["GET"],
        response_model=PayrollExportHistoryResponse,
    )
    return router
