from __future__ import annotations

from typing import TYPE_CHECKING, Annotated

from fastapi import APIRouter, HTTPException, Query, Request, status

from digital_bast.application.attendance_closing_policy import payroll_cycle, payroll_cycle_for
from digital_bast.application.workflow_control import WorkflowRole
from digital_bast.domain.time import JAKARTA
from digital_bast.web.payroll_contracts import (
    PayrollCycleResponse,
    PayrollCyclesResponse,
    PayrollDayResponse,
    PayrollOverviewResponse,
    PayrollSummaryResponse,
    PayrollTalentDetailResponse,
    PayrollTalentRowResponse,
)
from digital_bast.web.security import require_session

if TYPE_CHECKING:
    from datetime import datetime

    from digital_bast.application.attendance_closing_policy import PayrollCycle
    from digital_bast.application.payroll_read import PayrollOverview, PayrollReadService
    from digital_bast.application.workflow_control import WorkflowOperator
    from digital_bast.web.contracts import SessionRecord
    from digital_bast.web.dependencies import WebDependencies

_API_PREFIX = "/api/talentops/v1/payroll"
_ADMIN_ROLES = frozenset({"owner", "admin"})
_CYCLE_HISTORY_COUNT = 12


def _service(deps: WebDependencies) -> PayrollReadService:
    if deps.payroll_read is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Payroll attendance service is unavailable",
        )
    return deps.payroll_read


async def _authorized_operator(
    deps: WebDependencies,
    record: SessionRecord,
) -> WorkflowOperator | None:
    if record.user.role.casefold() in _ADMIN_ROLES:
        return None
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
    return operator


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


def _previous_cycle(cycle: PayrollCycle) -> PayrollCycle:
    if cycle.label_month == 1:
        return payroll_cycle(cycle.label_year - 1, 12, cycle.closing_day)
    return payroll_cycle(cycle.label_year, cycle.label_month - 1, cycle.closing_day)


def _cycle_response(cycle: PayrollCycle) -> PayrollCycleResponse:
    return PayrollCycleResponse(
        cycle_id=cycle.cycle_id,
        label=cycle.label,
        year=cycle.label_year,
        month=cycle.label_month,
        start=cycle.period.start,
        end=cycle.period.end,
    )


def _overview_response(view: PayrollOverview) -> PayrollOverviewResponse:
    return PayrollOverviewResponse(
        cycle=_cycle_response(view.cycle),
        evaluated_through=view.evaluated_through,
        summary=PayrollSummaryResponse.model_validate(view.summary),
        talents=tuple(PayrollTalentRowResponse.model_validate(item) for item in view.talents),
    )


def payroll_router(deps: WebDependencies) -> APIRouter:
    router = APIRouter(prefix=_API_PREFIX, tags=["payroll"])

    async def cycles(request: Request) -> PayrollCyclesResponse:
        _, record = await require_session(
            request,
            deps.sessions,
            deps.cookie,
            deps.now,
            api=True,
        )
        _ = await _authorized_operator(deps, record)
        current = payroll_cycle_for(deps.now().astimezone(JAKARTA).date())
        items = [current]
        for _ in range(_CYCLE_HISTORY_COUNT - 1):
            items.append(_previous_cycle(items[-1]))
        return PayrollCyclesResponse(
            current_cycle_id=current.cycle_id,
            cycles=tuple(_cycle_response(item) for item in items),
        )

    async def overview(
        request: Request,
        year: Annotated[int | None, Query(ge=2020, le=2100)] = None,
        month: Annotated[int | None, Query(ge=1, le=12)] = None,
    ) -> PayrollOverviewResponse:
        _, record = await require_session(
            request,
            deps.sessions,
            deps.cookie,
            deps.now,
            api=True,
        )
        _ = await _authorized_operator(deps, record)
        now = deps.now()
        cycle = _selected_cycle(year, month, now)
        view = await _service(deps).overview(cycle, now=now)
        return _overview_response(view)

    async def talent_detail(
        request: Request,
        employee_id: str,
        year: Annotated[int | None, Query(ge=2020, le=2100)] = None,
        month: Annotated[int | None, Query(ge=1, le=12)] = None,
    ) -> PayrollTalentDetailResponse:
        _, record = await require_session(
            request,
            deps.sessions,
            deps.cookie,
            deps.now,
            api=True,
        )
        _ = await _authorized_operator(deps, record)
        now = deps.now()
        cycle = _selected_cycle(year, month, now)
        view = await _service(deps).overview(cycle, now=now)
        talent = next(
            (item for item in view.talents if item.employee_id == employee_id),
            None,
        )
        if talent is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Talent not found",
            )
        row = PayrollTalentRowResponse.model_validate(talent)
        return PayrollTalentDetailResponse(
            **row.model_dump(),
            cycle=_cycle_response(view.cycle),
            evaluated_through=view.evaluated_through,
            days=tuple(PayrollDayResponse.model_validate(day) for day in talent.days),
        )

    router.add_api_route(
        "/cycles",
        cycles,
        methods=["GET"],
        response_model=PayrollCyclesResponse,
    )
    router.add_api_route(
        "/overview",
        overview,
        methods=["GET"],
        response_model=PayrollOverviewResponse,
    )
    router.add_api_route(
        "/talents/{employee_id}",
        talent_detail,
        methods=["GET"],
        response_model=PayrollTalentDetailResponse,
    )
    return router
