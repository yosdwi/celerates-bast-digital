from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Request, status

from digital_bast.domain.completion import DateRange
from digital_bast.domain.time import JAKARTA, month_dates
from digital_bast.web.dependencies import WebDependencies
from digital_bast.web.security import HeaderCsrf, require_session, verify_csrf
from digital_bast.web.talentops_contracts import (
    AiCommandCenterInput,
    AiCommandCenterResponse,
    CommandCenterResponse,
    SessionUserResponse,
    TalentOpsSessionResponse,
)

_API_PREFIX = "/api/talentops/v1"
_TIMEZONE_NAME = "Asia/Jakarta"


def _period(
    year: int | None,
    month: int | None,
    now: datetime,
) -> DateRange:
    if (year is None) != (month is None):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="year and month must be provided together",
        )
    local_now = now.astimezone(JAKARTA)
    selected_year = local_now.year if year is None else year
    selected_month = local_now.month if month is None else month
    dates = month_dates(selected_year, selected_month)
    return DateRange(dates[0], dates[-1])


def talentops_router(deps: WebDependencies) -> APIRouter:
    router = APIRouter(prefix=_API_PREFIX, tags=["talentops"])

    @router.get("/session", response_model=TalentOpsSessionResponse)
    async def session(request: Request) -> TalentOpsSessionResponse:
        _, record = await require_session(
            request,
            deps.sessions,
            deps.cookie,
            deps.now,
            api=True,
        )
        return TalentOpsSessionResponse(
            user=SessionUserResponse(
                name=record.user.name,
                role=record.user.role,
            ),
            csrf_token=record.csrf_token,
            timezone=_TIMEZONE_NAME,
        )

    @router.get("/command-center", response_model=CommandCenterResponse)
    async def command_center(
        request: Request,
        year: Annotated[int | None, Query(ge=2020, le=2100)] = None,
        month: Annotated[int | None, Query(ge=1, le=12)] = None,
    ) -> CommandCenterResponse:
        _ = await require_session(
            request,
            deps.sessions,
            deps.cookie,
            deps.now,
            api=True,
        )
        selected_period = _period(year, month, deps.now())
        if deps.talentops is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="TalentOps service is unavailable",
            )
        view = await deps.talentops.command_center(selected_period)
        return CommandCenterResponse.model_validate(view)

    @router.post(
        "/ai/command-center",
        response_model=AiCommandCenterResponse,
    )
    async def ask_command_center(
        request: Request,
        payload: AiCommandCenterInput,
        csrf_token: HeaderCsrf = None,
    ) -> AiCommandCenterResponse:
        _, record = await require_session(
            request,
            deps.sessions,
            deps.cookie,
            deps.now,
            api=True,
        )
        verify_csrf(record, csrf_token)
        selected_period = _period(payload.year, payload.month, deps.now())
        if deps.talentops is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="TalentOps service is unavailable",
            )
        if deps.talentops_ai is None:
            return AiCommandCenterResponse(status="unavailable", answer=None)
        view = await deps.talentops.command_center(selected_period)
        answer = await deps.talentops_ai.answer(payload.question, view)
        if answer is None:
            return AiCommandCenterResponse(status="unavailable", answer=None)
        return AiCommandCenterResponse(status="ok", answer=answer)

    return router
