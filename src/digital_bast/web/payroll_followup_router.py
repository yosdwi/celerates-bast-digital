from __future__ import annotations

from typing import TYPE_CHECKING, Annotated

from fastapi import APIRouter, HTTPException, Query, Request, status
from pydantic import ValidationError

from digital_bast.application.attendance_closing_policy import payroll_cycle, payroll_cycle_for
from digital_bast.application.workflow_control import WorkflowRole
from digital_bast.config import SettingsConfigurationError, get_settings
from digital_bast.domain.time import JAKARTA
from digital_bast.infrastructure.payroll_closing_settings import (
    PostgresPayrollClosingSettingsStore,
)
from digital_bast.payroll_query_runtime import create_payroll_closing_query_service
from digital_bast.payroll_runtime import (
    create_payroll_digest_service,
    create_payroll_talent_reminder_service,
)
from digital_bast.web.payroll_contracts import (
    PayrollCycleResponse,
    PayrollDigestResponse,
    PayrollDigestSummaryResponse,
    PayrollFollowUpItemResponse,
    PayrollManualReminderInput,
    PayrollManualReminderPreviewResponse,
    PayrollManualReminderResponse,
)
from digital_bast.web.payroll_query_contracts import (
    PayrollClosingQueryInput,
    PayrollClosingQueryResponse,
)
from digital_bast.web.security import HeaderCsrf, require_session, verify_csrf

if TYPE_CHECKING:
    from datetime import datetime

    from digital_bast.application.attendance_closing_policy import PayrollCycle
    from digital_bast.application.payroll_closing_settings import PayrollClosingSettingsStore
    from digital_bast.application.payroll_digest import PayrollDigestService
    from digital_bast.application.payroll_query import PayrollClosingQueryService
    from digital_bast.application.payroll_reminders import PayrollTalentReminderService
    from digital_bast.application.workflow_control import WorkflowOperator
    from digital_bast.web.contracts import SessionRecord
    from digital_bast.web.dependencies import WebDependencies

_API_PREFIX = "/api/talentops/v1/payroll"
_ADMIN_ROLES = frozenset({"owner", "admin"})


def _cycle_response(cycle: PayrollCycle) -> PayrollCycleResponse:
    return PayrollCycleResponse(
        cycle_id=cycle.cycle_id,
        label=cycle.label,
        year=cycle.label_year,
        month=cycle.label_month,
        start=cycle.period.start,
        end=cycle.period.end,
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
    closing_day: int,
) -> PayrollCycle:
    if (year is None) != (month is None):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="year and month must be provided together",
        )
    if year is None or month is None:
        return payroll_cycle_for(now.astimezone(JAKARTA).date(), closing_day)
    return payroll_cycle(year, month, closing_day)


def payroll_followup_router(
    deps: WebDependencies,
    digest_service: PayrollDigestService | None = None,
    reminder_service: PayrollTalentReminderService | None = None,
    settings_store: PayrollClosingSettingsStore | None = None,
    query_service: PayrollClosingQueryService | None = None,
) -> APIRouter:
    router = APIRouter(prefix=_API_PREFIX, tags=["payroll-follow-up"])

    def closing_store() -> PayrollClosingSettingsStore:
        selected = settings_store or _configured_settings_store()
        if selected is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Payroll closing settings storage is unavailable",
            )
        return selected

    def digest_for(scope_key: str) -> PayrollDigestService:
        return digest_service or create_payroll_digest_service(scope_key)

    def reminders_for(scope_key: str) -> PayrollTalentReminderService:
        return reminder_service or create_payroll_talent_reminder_service(scope_key)

    def queries_for(scope_key: str) -> PayrollClosingQueryService:
        return query_service or create_payroll_closing_query_service(scope_key)

    async def context(
        request: Request,
        scope_key: str,
    ) -> tuple[SessionRecord, str]:
        _, record = await require_session(
            request,
            deps.sessions,
            deps.cookie,
            deps.now,
            api=True,
        )
        operator = await _authorized_operator(deps, record)
        return record, scope_key if operator is None else operator.scope_key

    async def digest(
        request: Request,
        year: Annotated[int | None, Query(ge=2020, le=2100)] = None,
        month: Annotated[int | None, Query(ge=1, le=12)] = None,
        scope_key: Annotated[str, Query(min_length=1, max_length=120)] = "default",
    ) -> PayrollDigestResponse:
        _, selected_scope = await context(request, scope_key)
        policy = await closing_store().load(selected_scope)
        cycle = _selected_cycle(year, month, deps.now(), policy.closing_day)
        projected = await digest_for(selected_scope).project(
            cycle,
            now=deps.now(),
            next_day_ready_hour=policy.next_day_ready_hour,
            target_roles=policy.target_roles,
        )
        return PayrollDigestResponse(
            cycle=_cycle_response(projected.cycle),
            evaluated_through=projected.evaluated_through,
            summary=PayrollDigestSummaryResponse.model_validate(projected.summary),
            items=tuple(
                PayrollFollowUpItemResponse.model_validate(item) for item in projected.items
            ),
        )

    async def closing_query(
        request: Request,
        payload: PayrollClosingQueryInput,
        year: Annotated[int | None, Query(ge=2020, le=2100)] = None,
        month: Annotated[int | None, Query(ge=1, le=12)] = None,
        scope_key: Annotated[str, Query(min_length=1, max_length=120)] = "default",
        csrf_token: HeaderCsrf = None,
    ) -> PayrollClosingQueryResponse:
        record, selected_scope = await context(request, scope_key)
        verify_csrf(record, csrf_token)
        policy = await closing_store().load(selected_scope)
        cycle = _selected_cycle(year, month, deps.now(), policy.closing_day)
        result = await queries_for(selected_scope).query(
            payload.question,
            cycle,
            now=deps.now(),
            next_day_ready_hour=policy.next_day_ready_hour,
            target_roles=policy.target_roles,
            role_filter=payload.role,
        )
        projected = result.digest
        return PayrollClosingQueryResponse(
            status=result.status,
            answer=result.answer,
            role_filter=payload.role,
            cycle=_cycle_response(projected.cycle),
            evaluated_through=projected.evaluated_through,
            summary=PayrollDigestSummaryResponse.model_validate(projected.summary),
            items=tuple(
                PayrollFollowUpItemResponse.model_validate(item) for item in projected.items
            ),
        )

    async def preview_reminder(
        request: Request,
        employee_id: str,
        year: Annotated[int | None, Query(ge=2020, le=2100)] = None,
        month: Annotated[int | None, Query(ge=1, le=12)] = None,
        scope_key: Annotated[str, Query(min_length=1, max_length=120)] = "default",
    ) -> PayrollManualReminderPreviewResponse:
        _, selected_scope = await context(request, scope_key)
        policy = await closing_store().load(selected_scope)
        cycle = _selected_cycle(year, month, deps.now(), policy.closing_day)
        preview = await reminders_for(selected_scope).preview_manual(
            employee_id,
            cycle,
            now=deps.now(),
        )
        return PayrollManualReminderPreviewResponse.model_validate(preview)

    async def send_reminder(  # noqa: PLR0913, PLR0917 - FastAPI route contract
        request: Request,
        employee_id: str,
        payload: PayrollManualReminderInput,
        year: Annotated[int | None, Query(ge=2020, le=2100)] = None,
        month: Annotated[int | None, Query(ge=1, le=12)] = None,
        scope_key: Annotated[str, Query(min_length=1, max_length=120)] = "default",
        csrf_token: HeaderCsrf = None,
    ) -> PayrollManualReminderResponse:
        record, selected_scope = await context(request, scope_key)
        verify_csrf(record, csrf_token)
        policy = await closing_store().load(selected_scope)
        cycle = _selected_cycle(year, month, deps.now(), policy.closing_day)
        result = await reminders_for(selected_scope).send_manual(
            employee_id,
            cycle,
            payload.request_id,
            now=deps.now(),
        )
        return PayrollManualReminderResponse.model_validate(result)

    router.add_api_route(
        "/digest",
        digest,
        methods=["GET"],
        response_model=PayrollDigestResponse,
    )
    router.add_api_route(
        "/query",
        closing_query,
        methods=["POST"],
        response_model=PayrollClosingQueryResponse,
    )
    router.add_api_route(
        # employee_id (e.g. "MTG-TF/2025070332") contains a literal "/" --
        # the :path converter is required so Starlette matches everything up
        # to the "/preview" suffix instead of splitting on that slash and
        # 404ing (a plain {employee_id} segment stops at the first "/").
        "/follow-up/{employee_id:path}/preview",
        preview_reminder,
        methods=["GET"],
        response_model=PayrollManualReminderPreviewResponse,
    )
    router.add_api_route(
        "/follow-up/{employee_id:path}/send",
        send_reminder,
        methods=["POST"],
        response_model=PayrollManualReminderResponse,
    )
    return router
