from __future__ import annotations

from typing import TYPE_CHECKING, Annotated, Literal

from anyio.to_thread import run_sync
from fastapi import APIRouter, HTTPException, Query, Request, Response, status

from digital_bast.application.talentops_followups import FollowUpSendCommand
from digital_bast.domain.completion import DateRange
from digital_bast.domain.time import JAKARTA, month_dates
from digital_bast.operations import generate_bast as generate_bast_artifact
from digital_bast.web.security import HeaderCsrf, require_session, verify_csrf
from digital_bast.web.talentops_contracts import (
    AiCommandCenterInput,
    AiCommandCenterResponse,
    CommandCenterResponse,
    FollowUpDraftInput,
    FollowUpDraftResponse,
    FollowUpSendInput,
    FollowUpSendResponse,
    SessionUserResponse,
    TalentDetailResponse,
    TalentOpsSessionResponse,
)

if TYPE_CHECKING:
    from datetime import datetime

    from digital_bast.application.talentops import TalentOpsService
    from digital_bast.application.talentops_followups import TalentOpsFollowUpService
    from digital_bast.web.dependencies import WebDependencies

_API_PREFIX = "/api/talentops/v1"
_TIMEZONE_NAME = "Asia/Jakarta"


def _period(
    year: int | None,
    month: int | None,
    now: datetime,
) -> DateRange:
    if (year is None) != (month is None):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="year and month must be provided together",
        )
    local_now = now.astimezone(JAKARTA)
    selected_year = local_now.year if year is None else year
    selected_month = local_now.month if month is None else month
    dates = month_dates(selected_year, selected_month)
    return DateRange(dates[0], dates[-1])


def _service(deps: WebDependencies) -> TalentOpsService:
    if deps.talentops is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="TalentOps service is unavailable",
        )
    return deps.talentops


def _followups(deps: WebDependencies) -> TalentOpsFollowUpService:
    if deps.talentops_followups is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="TalentOps follow-up service is unavailable",
        )
    return deps.talentops_followups


def talentops_router(  # noqa: C901, PLR0915 - one composition root for related API routes
    deps: WebDependencies,
) -> APIRouter:
    router = APIRouter(prefix=_API_PREFIX, tags=["talentops"])

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
        view = await _service(deps).command_center(selected_period)
        return CommandCenterResponse.model_validate(view)

    async def talent_detail(
        request: Request,
        nrp: str,
        year: Annotated[int | None, Query(ge=2020, le=2100)] = None,
        month: Annotated[int | None, Query(ge=1, le=12)] = None,
    ) -> TalentDetailResponse:
        _ = await require_session(
            request,
            deps.sessions,
            deps.cookie,
            deps.now,
            api=True,
        )
        selected_period = _period(year, month, deps.now())
        view = await _service(deps).talent_detail(selected_period, nrp)
        if view is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Talent not found",
            )
        return TalentDetailResponse.model_validate(view)

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
        service = _service(deps)
        if deps.talentops_ai is None:
            return AiCommandCenterResponse(status="unavailable", answer=None)
        view = await service.command_center(selected_period)
        answer = await deps.talentops_ai.answer(payload.question, view)
        if answer is None:
            return AiCommandCenterResponse(status="unavailable", answer=None)
        return AiCommandCenterResponse(status="ok", answer=answer)

    async def ask_talent(
        request: Request,
        nrp: str,
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
        view = await _service(deps).talent_detail(selected_period, nrp)
        if view is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Talent not found")
        if deps.talentops_ai is None:
            return AiCommandCenterResponse(status="unavailable", answer=None)
        answer = await deps.talentops_ai.answer_talent(payload.question, view)
        if answer is None:
            return AiCommandCenterResponse(status="unavailable", answer=None)
        return AiCommandCenterResponse(status="ok", answer=answer)

    async def generate_bast_document(
        request: Request,
        year: Annotated[int, Query(ge=2020, le=2100)],
        month: Annotated[int, Query(ge=1, le=12)],
        report_type: Annotated[Literal["developer", "iotoperation"], Query()],
        csrf_token: HeaderCsrf = None,
    ) -> Response:
        _, record = await require_session(
            request,
            deps.sessions,
            deps.cookie,
            deps.now,
            api=True,
        )
        verify_csrf(record, csrf_token)
        selected_period = _period(year, month, deps.now())
        path, report = await generate_bast_artifact(selected_period, report_type)
        pdf_bytes = await run_sync(path.read_bytes)
        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={
                "Cache-Control": "no-store",
                "Content-Disposition": f'attachment; filename="{path.name}"',
                "X-BAST-Fingerprint": report.fingerprint,
            },
        )

    async def follow_up_draft(
        request: Request,
        nrp: str,
        payload: FollowUpDraftInput,
        csrf_token: HeaderCsrf = None,
    ) -> FollowUpDraftResponse:
        _, record = await require_session(
            request,
            deps.sessions,
            deps.cookie,
            deps.now,
            api=True,
        )
        verify_csrf(record, csrf_token)
        selected_period = _period(payload.year, payload.month, deps.now())
        draft = await _followups(deps).draft(selected_period, nrp)
        if draft is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Talent not found")
        return FollowUpDraftResponse.model_validate(draft)

    async def send_follow_up(
        request: Request,
        nrp: str,
        payload: FollowUpSendInput,
        csrf_token: HeaderCsrf = None,
    ) -> FollowUpSendResponse:
        _, record = await require_session(
            request,
            deps.sessions,
            deps.cookie,
            deps.now,
            api=True,
        )
        verify_csrf(record, csrf_token)
        result = await _followups(deps).send(
            FollowUpSendCommand(
                period=_period(payload.year, payload.month, deps.now()),
                nrp=nrp,
                message=payload.message,
                idempotency_key=str(payload.idempotency_key),
                created_by=record.user.email,
                source=payload.source,
            )
        )
        if result is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Talent not found")
        return FollowUpSendResponse.model_validate(result)

    router.add_api_route(
        "/session",
        session,
        methods=["GET"],
        response_model=TalentOpsSessionResponse,
    )
    router.add_api_route(
        "/command-center",
        command_center,
        methods=["GET"],
        response_model=CommandCenterResponse,
    )
    router.add_api_route(
        "/talents/{nrp}",
        talent_detail,
        methods=["GET"],
        response_model=TalentDetailResponse,
    )
    router.add_api_route(
        "/ai/command-center",
        ask_command_center,
        methods=["POST"],
        response_model=AiCommandCenterResponse,
    )
    router.add_api_route(
        "/ai/talents/{nrp}",
        ask_talent,
        methods=["POST"],
        response_model=AiCommandCenterResponse,
    )
    router.add_api_route(
        "/bast/generate",
        generate_bast_document,
        methods=["POST"],
        response_class=Response,
    )
    router.add_api_route(
        "/talents/{nrp}/follow-up-draft",
        follow_up_draft,
        methods=["POST"],
        response_model=FollowUpDraftResponse,
    )
    router.add_api_route(
        "/talents/{nrp}/follow-ups",
        send_follow_up,
        methods=["POST"],
        response_model=FollowUpSendResponse,
    )
    return router
