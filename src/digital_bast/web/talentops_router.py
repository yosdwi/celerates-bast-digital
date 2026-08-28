from __future__ import annotations

from typing import TYPE_CHECKING, Annotated
from uuid import UUID  # noqa: TC003 - FastAPI path annotation is runtime metadata

from anyio.to_thread import run_sync
from fastapi import APIRouter, HTTPException, Query, Request, Response, status

from digital_bast.application.operational_signals import (
    command_center_signals,
    talent_signals,
)
from digital_bast.application.talentops_followups import FollowUpSendCommand
from digital_bast.bot.attendance_resolution import DecisionOutcome, ResolutionStatus
from digital_bast.domain.completion import DateRange
from digital_bast.domain.time import JAKARTA, month_dates
from digital_bast.operations import generate_bast as generate_bast_artifact
from digital_bast.web.security import HeaderCsrf, require_session, verify_csrf
from digital_bast.web.talentops_contracts import (
    AiCommandCenterInput,
    AiCommandCenterResponse,
    AiInvestigationResponse,
    AttendanceResolutionDecisionResponse,
    AttendanceResolutionRejectInput,
    AttendanceResolutionResponse,
    CommandCenterResponse,
    FollowUpDraftInput,
    FollowUpDraftResponse,
    FollowUpSendInput,
    FollowUpSendResponse,
    OperationalSignalResponse,
    SessionUserResponse,
    TalentDetailResponse,
    TalentOpsSessionResponse,
    WhatsAppStatusResponse,
)

if TYPE_CHECKING:
    from datetime import datetime

    from digital_bast.application.talentops import TalentOpsService
    from digital_bast.application.talentops_followups import TalentOpsFollowUpService
    from digital_bast.bot.attendance_resolution import AttendanceResolutionService
    from digital_bast.infrastructure.whatsapp_outbound import BotBridgeWhatsAppOutboundGateway
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


def _attendance_resolutions(deps: WebDependencies) -> AttendanceResolutionService:
    if deps.attendance_resolutions is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Attendance approval service is unavailable",
        )
    return deps.attendance_resolutions


def _bot_bridge(deps: WebDependencies) -> BotBridgeWhatsAppOutboundGateway:
    if deps.bot_bridge_status is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="WhatsApp bridge status is unavailable",
        )
    return deps.bot_bridge_status


def _decision_error(outcome: DecisionOutcome, existing: ResolutionStatus | None) -> None:
    if outcome is DecisionOutcome.NOT_FOUND:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Request not found")
    if outcome is DecisionOutcome.ALREADY_RESOLVED:
        detail = (
            f"Request already {existing.value}"
            if existing is not None
            else "Request already resolved"
        )
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=detail)
    if outcome is DecisionOutcome.SOURCE_CHANGED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Client attendance changed; refresh before reviewing this request",
        )
    if outcome is DecisionOutcome.REJECTION_REASON_REQUIRED:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Rejection reason is required",
        )
    raise HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail="Attendance decision failed",
    )


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

    async def whatsapp_status(request: Request) -> WhatsAppStatusResponse:
        _ = await require_session(
            request,
            deps.sessions,
            deps.cookie,
            deps.now,
            api=True,
        )
        result = await _bot_bridge(deps).get_status()
        return WhatsAppStatusResponse(
            connection=result.connection,
            me=result.me,
            qr_data_url=result.qr_data_url,
            pairing_code=result.pairing_code,
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
        response = CommandCenterResponse.model_validate(view)
        signals = tuple(
            OperationalSignalResponse.model_validate(signal)
            for signal in command_center_signals(view.attention, view.teams)
        )
        return response.model_copy(update={"signals": signals})

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
        response = TalentDetailResponse.model_validate(view)
        signals = tuple(
            OperationalSignalResponse.model_validate(signal)
            for signal in talent_signals(
                view.nrp,
                view.blockers,
                view.timesheet_days,
                view.tasks,
            )
        )
        return response.model_copy(update={"signals": signals})

    async def attendance_resolution_queue(
        request: Request,
    ) -> tuple[AttendanceResolutionResponse, ...]:
        _ = await require_session(
            request,
            deps.sessions,
            deps.cookie,
            deps.now,
            api=True,
        )
        requests = await _attendance_resolutions(deps).pending()
        return tuple(AttendanceResolutionResponse.model_validate(item) for item in requests)

    async def approve_attendance_resolution(
        request: Request,
        request_id: UUID,
        csrf_token: HeaderCsrf = None,
    ) -> AttendanceResolutionDecisionResponse:
        _, record = await require_session(
            request,
            deps.sessions,
            deps.cookie,
            deps.now,
            api=True,
        )
        verify_csrf(record, csrf_token)
        result = await _attendance_resolutions(deps).decide(
            request_id,
            record.user.email,
            approve=True,
        )
        if result.outcome is not DecisionOutcome.UPDATED or result.status is None:
            _decision_error(result.outcome, result.status)
        return AttendanceResolutionDecisionResponse(status="approved")

    async def reject_attendance_resolution(
        request: Request,
        request_id: UUID,
        payload: AttendanceResolutionRejectInput,
        csrf_token: HeaderCsrf = None,
    ) -> AttendanceResolutionDecisionResponse:
        _, record = await require_session(
            request,
            deps.sessions,
            deps.cookie,
            deps.now,
            api=True,
        )
        verify_csrf(record, csrf_token)
        result = await _attendance_resolutions(deps).decide(
            request_id,
            record.user.email,
            approve=False,
            rejection_reason=payload.reason,
        )
        if result.outcome is not DecisionOutcome.UPDATED or result.status is None:
            _decision_error(result.outcome, result.status)
        return AttendanceResolutionDecisionResponse(status="rejected")

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
        investigation = await deps.talentops_ai.answer(payload.question, view)
        if investigation is None:
            return AiCommandCenterResponse(status="unavailable", answer=None)
        return AiCommandCenterResponse(
            status="ok",
            answer=investigation.finding,
            investigation=AiInvestigationResponse.model_validate(investigation),
        )

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
        investigation = await deps.talentops_ai.answer_talent(payload.question, view)
        if investigation is None:
            return AiCommandCenterResponse(status="unavailable", answer=None)
        return AiCommandCenterResponse(
            status="ok",
            answer=investigation.finding,
            investigation=AiInvestigationResponse.model_validate(investigation),
        )

    async def generate_bast_document(
        request: Request,
        year: Annotated[int, Query(ge=2020, le=2100)],
        month: Annotated[int, Query(ge=1, le=12)],
        report_type: Annotated[str, Query(pattern="^(developer|iotoperation)$")],
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
        "/system/whatsapp",
        whatsapp_status,
        methods=["GET"],
        response_model=WhatsAppStatusResponse,
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
        "/attendance-resolutions",
        attendance_resolution_queue,
        methods=["GET"],
        response_model=tuple[AttendanceResolutionResponse, ...],
    )
    router.add_api_route(
        "/attendance-resolutions/{request_id}/approve",
        approve_attendance_resolution,
        methods=["POST"],
        response_model=AttendanceResolutionDecisionResponse,
    )
    router.add_api_route(
        "/attendance-resolutions/{request_id}/reject",
        reject_attendance_resolution,
        methods=["POST"],
        response_model=AttendanceResolutionDecisionResponse,
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
