from __future__ import annotations

from typing import TYPE_CHECKING, Annotated, Literal

from fastapi import APIRouter, HTTPException, Query, Request, status
from pydantic import BaseModel, Field, ValidationError

from digital_bast.application.bast_closing import (
    BastClosingControlService,
    BastEvidenceRule,
    closing_schedule,
)
from digital_bast.bast_runtime import (
    create_bast_group_digest_service,
    create_bast_talent_reminder_service,
)
from digital_bast.config import SettingsConfigurationError, get_settings
from digital_bast.domain.completion import DateRange
from digital_bast.domain.models import TaskCategory
from digital_bast.domain.time import JAKARTA, month_dates
from digital_bast.web.security import HeaderCsrf, require_session, verify_csrf

if TYPE_CHECKING:
    from digital_bast.web.contracts import SessionRecord
    from digital_bast.web.dependencies import WebDependencies

_API_PREFIX = "/api/talentops/v1/bast-closing"
_ADMIN_ROLES = frozenset({"owner", "admin"})
ScopeKeyQuery = Annotated[str, Query()]
YearQuery = Annotated[int, Query(ge=2020, le=2100)]
MonthQuery = Annotated[int, Query(ge=1, le=12)]
OptionalYearQuery = Annotated[int | None, Query(ge=2020, le=2100)]
OptionalMonthQuery = Annotated[int | None, Query(ge=1, le=12)]
TargetQuery = Annotated[Literal["talent"], Query()]


class BastClosingSettingsInput(BaseModel):
    enabled: bool = False
    initial_day: int = Field(default=25, ge=1, le=31)
    followup_offsets: tuple[int, ...] = (3, 1)
    send_hour: int = Field(default=9, ge=0, le=23)
    talent_reminder_enabled: bool = True
    pmo_summary_enabled: bool = True
    pmo_group_jid: str | None = Field(default=None, max_length=255)


class EvidenceRuleInput(BaseModel):
    task_category: TaskCategory
    evidence_required: bool


class EvidenceRulesInput(BaseModel):
    rules: tuple[EvidenceRuleInput, ...]


class ManualBlastResponse(BaseModel):
    batch_id: str
    eligible: int
    sent: int
    skipped: int
    failed: int
    scheduled_slot_consumed: bool


class PmoDigestSendResponse(BaseModel):
    enabled: bool
    due: bool
    milestone: str | None
    outcome: str
    sent: int


def _control() -> BastClosingControlService:
    try:
        settings = get_settings()
    except (OSError, ValidationError, SettingsConfigurationError) as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="BAST closing configuration is unavailable",
        ) from error
    if settings.database_dsn is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="BAST closing database is unavailable",
        )
    return BastClosingControlService(settings.database_dsn.get_secret_value())


def _period(year: int, month: int) -> DateRange:
    dates = month_dates(year, month)
    return DateRange(dates[0], dates[-1])


async def _session(deps: WebDependencies, request: Request) -> SessionRecord:
    _, record = await require_session(request, deps.sessions, deps.cookie, deps.now, api=True)
    return record


async def _require_bast_operator(deps: WebDependencies, request: Request) -> SessionRecord:
    record = await _session(deps, request)
    if record.user.role.casefold() in _ADMIN_ROLES:
        return record
    if deps.workflow_control is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Workflow authorization is unavailable",
        )
    operator = await deps.workflow_control.operator(record.user.email)
    if operator is None or not operator.active or not operator.can_generate_bast:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="BAST operation permission is required",
        )
    return record


def _require_admin(record: SessionRecord) -> None:
    if record.user.role.casefold() not in _ADMIN_ROLES:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access is required",
        )


def bast_closing_router(deps: WebDependencies) -> APIRouter:
    router = APIRouter(prefix=_API_PREFIX, tags=["talentops-bast-closing"])

    @router.get("/settings")
    async def settings_view(
        request: Request,
        scope_key: ScopeKeyQuery = "default",
        year: OptionalYearQuery = None,
        month: OptionalMonthQuery = None,
    ) -> dict[str, object]:
        _ = await _require_bast_operator(deps, request)
        current = deps.now().astimezone(JAKARTA)
        selected_year = year or current.year
        selected_month = month or current.month
        value = await _control().settings(scope_key)
        schedule = closing_schedule(selected_year, selected_month, value)
        return {
            "scope_key": value.scope_key,
            "enabled": value.enabled,
            "initial_day": value.initial_day,
            "followup_offsets": value.followup_offsets,
            "send_hour": value.send_hour,
            "timezone": "Asia/Jakarta",
            "talent_reminder_enabled": value.talent_reminder_enabled,
            "pmo_summary_enabled": value.pmo_summary_enabled,
            "pmo_group_jid": value.pmo_group_jid,
            "schedule": {
                "initial": schedule.initial_date.isoformat(),
                "followups": tuple(item.isoformat() for item in schedule.followup_dates),
                "closing": schedule.closing_date.isoformat(),
                "talent_reminder_dates": tuple(
                    item.isoformat() for item in schedule.talent_reminder_dates
                ),
            },
        }

    @router.put("/settings")
    async def save_settings(
        payload: BastClosingSettingsInput,
        request: Request,
        csrf: HeaderCsrf,
        scope_key: ScopeKeyQuery = "default",
    ) -> dict[str, object]:
        record = await _session(deps, request)
        _require_admin(record)
        verify_csrf(record, csrf)
        value = await _control().save_settings(
            scope_key=scope_key,
            enabled=payload.enabled,
            initial_day=payload.initial_day,
            followup_offsets=payload.followup_offsets,
            send_hour=payload.send_hour,
            talent_reminder_enabled=payload.talent_reminder_enabled,
            pmo_summary_enabled=payload.pmo_summary_enabled,
            pmo_group_jid=payload.pmo_group_jid,
            actor=record.user.email,
        )
        return {
            "scope_key": value.scope_key,
            "enabled": value.enabled,
            "initial_day": value.initial_day,
            "followup_offsets": value.followup_offsets,
            "send_hour": value.send_hour,
            "talent_reminder_enabled": value.talent_reminder_enabled,
            "pmo_summary_enabled": value.pmo_summary_enabled,
            "pmo_group_jid": value.pmo_group_jid,
        }

    @router.get("/evidence-rules")
    async def evidence_rules(
        request: Request,
        scope_key: ScopeKeyQuery = "default",
    ) -> dict[str, object]:
        _ = await _require_bast_operator(deps, request)
        configured = {
            item.task_category: item.evidence_required
            for item in await _control().evidence_rules(scope_key)
        }
        return {
            "scope_key": scope_key,
            "rules": tuple(
                {
                    "task_category": category.value,
                    "evidence_required": configured.get(category.value, False),
                }
                for category in TaskCategory
            ),
        }

    @router.put("/evidence-rules")
    async def save_evidence_rules(
        payload: EvidenceRulesInput,
        request: Request,
        csrf: HeaderCsrf,
        scope_key: ScopeKeyQuery = "default",
    ) -> dict[str, object]:
        record = await _session(deps, request)
        _require_admin(record)
        verify_csrf(record, csrf)
        saved = await _control().save_evidence_rules(
            scope_key,
            tuple(
                BastEvidenceRule(item.task_category.value, item.evidence_required)
                for item in payload.rules
            ),
            record.user.email,
        )
        return {
            "scope_key": scope_key,
            "rules": tuple(
                {
                    "task_category": item.task_category,
                    "evidence_required": item.evidence_required,
                }
                for item in saved
            ),
        }

    @router.get("/blast/preview")
    async def blast_preview(
        request: Request,
        year: YearQuery,
        month: MonthQuery,
        scope_key: ScopeKeyQuery = "default",
        target: TargetQuery = "talent",
    ) -> dict[str, object]:
        _ = target
        _ = await _require_bast_operator(deps, request)
        preview = await create_bast_talent_reminder_service(scope_key).preview(
            _period(year, month)
        )
        return {
            "total": preview.total,
            "will_send": preview.will_send,
            "waiting_pmo": preview.waiting_pmo,
            "complete": preview.complete,
            "source_review": preview.source_review,
            "rows": tuple(
                {
                    "nrp": item.nrp,
                    "name": item.name,
                    "actionable_count": item.actionable_count,
                    "status": item.status,
                }
                for item in preview.rows
            ),
        }

    @router.post("/blast/send", response_model=ManualBlastResponse)
    async def blast_send(
        request: Request,
        csrf: HeaderCsrf,
        year: YearQuery,
        month: MonthQuery,
        scope_key: ScopeKeyQuery = "default",
    ) -> ManualBlastResponse:
        record = await _require_bast_operator(deps, request)
        verify_csrf(record, csrf)
        result = await create_bast_talent_reminder_service(scope_key).send_manual(
            _period(year, month),
            record.user.email,
            deps.now(),
        )
        return ManualBlastResponse.model_validate(result, from_attributes=True)

    @router.get("/pmo-digest/preview")
    async def pmo_digest_preview(
        request: Request,
        year: YearQuery,
        month: MonthQuery,
        scope_key: ScopeKeyQuery = "default",
    ) -> dict[str, object]:
        _ = await _require_bast_operator(deps, request)
        preview = await create_bast_group_digest_service(scope_key).preview(
            _period(year, month)
        )
        return {
            "configured": preview.configured,
            "group_jid": preview.group_jid,
            "message": preview.message,
            "total": preview.total,
            "complete": preview.complete,
            "need_talent_action": preview.need_talent_action,
            "waiting_pmo": preview.waiting_pmo,
            "source_review": preview.source_review,
        }

    @router.post("/pmo-digest/send", response_model=PmoDigestSendResponse)
    async def pmo_digest_send(
        request: Request,
        csrf: HeaderCsrf,
        year: YearQuery,
        month: MonthQuery,
        scope_key: ScopeKeyQuery = "default",
    ) -> PmoDigestSendResponse:
        record = await _require_bast_operator(deps, request)
        verify_csrf(record, csrf)
        result = await create_bast_group_digest_service(scope_key).send_manual(
            _period(year, month),
            record.user.email,
            deps.now(),
        )
        return PmoDigestSendResponse.model_validate(result, from_attributes=True)

    return router
