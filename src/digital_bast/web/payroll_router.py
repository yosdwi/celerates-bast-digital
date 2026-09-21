from __future__ import annotations

from typing import TYPE_CHECKING, Annotated

from fastapi import APIRouter, HTTPException, Query, Request, status
from pydantic import ValidationError

from digital_bast.application.attendance_closing_policy import (
    payroll_cycle,
    payroll_cycle_for,
    reminder_milestones,
)
from digital_bast.application.payroll_review import PayrollReviewService
from digital_bast.application.workflow_control import WorkflowRole
from digital_bast.config import SettingsConfigurationError, get_settings
from digital_bast.domain.time import JAKARTA
from digital_bast.infrastructure.payroll_closing_settings import (
    PostgresPayrollClosingSettingsStore,
)
from digital_bast.web.payroll_contracts import (
    PayrollClosingMilestoneResponse,
    PayrollClosingPreviewResponse,
    PayrollClosingSettingsInput,
    PayrollClosingSettingsResponse,
    PayrollCycleResponse,
    PayrollCyclesResponse,
    PayrollDayResponse,
    PayrollOverviewResponse,
    PayrollReviewDecisionInput,
    PayrollReviewDecisionResponse,
    PayrollReviewItemResponse,
    PayrollReviewQueueResponse,
    PayrollReviewSummaryResponse,
    PayrollSummaryResponse,
    PayrollTalentDetailResponse,
    PayrollTalentRowResponse,
)
from digital_bast.web.security import HeaderCsrf, require_session, verify_csrf

if TYPE_CHECKING:
    from datetime import datetime

    from digital_bast.application.attendance_closing_policy import PayrollCycle
    from digital_bast.application.payroll_closing_settings import (
        PayrollClosingSettings,
        PayrollClosingSettingsStore,
    )
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


def _review_service(deps: WebDependencies) -> PayrollReviewService:
    if deps.payroll_read is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Payroll attendance service is unavailable",
        )
    if deps.attendance_resolutions is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Attendance approval service is unavailable",
        )
    if deps.attendance_review is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Attendance review evidence service is unavailable",
        )
    return PayrollReviewService(
        deps.payroll_read,
        deps.attendance_resolutions,
        deps.attendance_review,
    )


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


async def _authorized_attendance_reviewer(
    deps: WebDependencies,
    record: SessionRecord,
) -> WorkflowOperator | None:
    operator = await _authorized_operator(deps, record)
    if operator is not None and not operator.can_approve_attendance:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Attendance approval permission is required",
        )
    return operator


def _require_admin(record: SessionRecord) -> None:
    if record.user.role.casefold() not in _ADMIN_ROLES:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access is required",
        )


def _configured_settings_store() -> PayrollClosingSettingsStore | None:
    try:
        settings = get_settings()
    except (OSError, ValidationError, SettingsConfigurationError):
        return None
    if settings.database_dsn is None:
        return None
    return PostgresPayrollClosingSettingsStore(settings.database_dsn.get_secret_value())


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


async def _closing_settings_response(
    deps: WebDependencies,
    settings: PayrollClosingSettings,
) -> PayrollClosingSettingsResponse:
    now = deps.now()
    cycle = payroll_cycle_for(
        now.astimezone(JAKARTA).date(),
        settings.closing_day,
    )
    overview = await _service(deps).overview(
        cycle,
        now=now,
        next_day_ready_hour=settings.next_day_ready_hour,
    )
    in_audience = tuple(
        talent for talent in overview.talents if talent.role in settings.target_roles
    )
    return PayrollClosingSettingsResponse(
        scope_key=settings.scope_key,
        enabled=settings.enabled,
        paused=settings.paused,
        closing_day=settings.closing_day,
        reminder_hour=settings.reminder_hour,
        reminder_offsets=settings.reminder_offsets,
        target_roles=settings.target_roles,
        next_day_ready_hour=settings.next_day_ready_hour,
        desired_version=settings.desired_version,
        applied_version=settings.applied_version,
        updated_by=settings.updated_by,
        preview=PayrollClosingPreviewResponse(
            cycle=_cycle_response(cycle),
            milestones=tuple(
                PayrollClosingMilestoneResponse(
                    label=item.label,
                    days_before=item.days_before,
                    work_date=item.work_date,
                )
                for item in reminder_milestones(cycle, settings.reminder_offsets)
            ),
            estimated_actionable_talents=sum(
                talent.talent_action_required for talent in in_audience
            ),
            estimated_unverified_talents=sum(
                talent.unverified_days > 0 for talent in in_audience
            ),
        ),
    )


def payroll_router(  # noqa: C901, PLR0915 - route handlers stay co-located
    deps: WebDependencies,
    settings_store: PayrollClosingSettingsStore | None = None,
) -> APIRouter:
    router = APIRouter(prefix=_API_PREFIX, tags=["payroll"])

    def closing_store() -> PayrollClosingSettingsStore:
        selected = settings_store or _configured_settings_store()
        if selected is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Payroll closing settings storage is unavailable",
            )
        return selected

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

    async def closing_settings(
        request: Request,
        scope_key: Annotated[str, Query(min_length=1, max_length=120)] = "default",
    ) -> PayrollClosingSettingsResponse:
        _, record = await require_session(
            request,
            deps.sessions,
            deps.cookie,
            deps.now,
            api=True,
        )
        operator = await _authorized_operator(deps, record)
        selected_scope = scope_key if operator is None else operator.scope_key
        settings = await closing_store().load(selected_scope)
        return await _closing_settings_response(deps, settings)

    async def save_closing_settings(
        request: Request,
        payload: PayrollClosingSettingsInput,
        scope_key: Annotated[str, Query(min_length=1, max_length=120)] = "default",
        csrf_token: HeaderCsrf = None,
    ) -> PayrollClosingSettingsResponse:
        _, record = await require_session(
            request,
            deps.sessions,
            deps.cookie,
            deps.now,
            api=True,
        )
        verify_csrf(record, csrf_token)
        _require_admin(record)
        store = closing_store()
        current = await store.load(scope_key)
        try:
            desired = current.with_desired_update(
                enabled=payload.enabled,
                paused=payload.paused,
                closing_day=payload.closing_day,
                reminder_hour=payload.reminder_hour,
                reminder_offsets=payload.reminder_offsets,
                target_roles=payload.target_roles,
                next_day_ready_hour=payload.next_day_ready_hour,
                actor=record.user.email,
            )
        except ValueError as error:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=str(error),
            ) from error
        saved = await store.save(desired)
        return await _closing_settings_response(deps, saved)

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

    async def review_queue(
        request: Request,
        year: Annotated[int | None, Query(ge=2020, le=2100)] = None,
        month: Annotated[int | None, Query(ge=1, le=12)] = None,
    ) -> PayrollReviewQueueResponse:
        _, record = await require_session(
            request,
            deps.sessions,
            deps.cookie,
            deps.now,
            api=True,
        )
        _ = await _authorized_attendance_reviewer(deps, record)
        now = deps.now()
        cycle = _selected_cycle(year, month, now)
        queue = await _review_service(deps).queue(cycle, now=now)
        return PayrollReviewQueueResponse(
            cycle=_cycle_response(queue.cycle),
            summary=PayrollReviewSummaryResponse.model_validate(queue.summary),
            items=tuple(PayrollReviewItemResponse.model_validate(item) for item in queue.items),
        )

    async def decide_review_queue(
        request: Request,
        payload: PayrollReviewDecisionInput,
        year: Annotated[int | None, Query(ge=2020, le=2100)] = None,
        month: Annotated[int | None, Query(ge=1, le=12)] = None,
        csrf_token: HeaderCsrf = None,
    ) -> PayrollReviewDecisionResponse:
        _, record = await require_session(
            request,
            deps.sessions,
            deps.cookie,
            deps.now,
            api=True,
        )
        verify_csrf(record, csrf_token)
        _ = await _authorized_attendance_reviewer(deps, record)
        now = deps.now()
        cycle = _selected_cycle(year, month, now)
        try:
            result = await _review_service(deps).bulk_decide(
                cycle,
                now=now,
                request_ids=payload.request_ids,
                decision=payload.decision,
                reviewer=record.user.email,
                rejection_reason=payload.rejection_reason,
            )
        except ValueError as error:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=str(error),
            ) from error
        return PayrollReviewDecisionResponse.model_validate(result)

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
        "/settings",
        closing_settings,
        methods=["GET"],
        response_model=PayrollClosingSettingsResponse,
    )
    router.add_api_route(
        "/settings",
        save_closing_settings,
        methods=["PUT"],
        response_model=PayrollClosingSettingsResponse,
    )
    router.add_api_route(
        # employee_id (e.g. "MTG-TF/2025070332") contains a literal "/" --
        # a plain {employee_id} segment stops at the first "/" and 404s.
        "/talents/{employee_id:path}",
        talent_detail,
        methods=["GET"],
        response_model=PayrollTalentDetailResponse,
    )
    router.add_api_route(
        "/review-queue",
        review_queue,
        methods=["GET"],
        response_model=PayrollReviewQueueResponse,
    )
    router.add_api_route(
        "/review-queue/decide",
        decide_review_queue,
        methods=["POST"],
        response_model=PayrollReviewDecisionResponse,
    )
    return router
