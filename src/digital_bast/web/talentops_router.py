from __future__ import annotations

from typing import TYPE_CHECKING, Annotated, Literal
from urllib.parse import urlsplit
from uuid import UUID  # noqa: TC003 - FastAPI runtime metadata

from anyio.to_thread import run_sync
from fastapi import (
    APIRouter,
    BackgroundTasks,
    File,
    Form,
    HTTPException,
    Query,
    Request,
    Response,
    UploadFile,
    status,
)

from digital_bast.application.bast_generation_jobs import (
    display_status as bast_job_display_status,
)
from digital_bast.application.bast_generation_jobs import (
    execute as execute_bast_generation_job,
)
from digital_bast.application.bast_workflow import BastGenerationMode
from digital_bast.application.operational_signals import (
    command_center_signals,
    talent_signals,
)
from digital_bast.application.talentops_followups import FollowUpSendCommand
from digital_bast.application.workflow_control import WorkflowRole
from digital_bast.bot.attendance_resolution import DecisionOutcome, ResolutionStatus, SubmitOutcome
from digital_bast.bot.evidence import UploadOutcome
from digital_bast.bot.rebind import RebindDecisionOutcome, RebindStatus
from digital_bast.domain.completion import DateRange
from digital_bast.domain.time import JAKARTA, month_dates
from digital_bast.operations import (
    bast_artifact_path,
    completion_status,
    create_attendance_evidence_service,
)
from digital_bast.web.attendance_forms import clock_label, gap_for, read_upload, resolution_shape
from digital_bast.web.security import HeaderCsrf, require_session, verify_csrf
from digital_bast.web.talentops_contracts import (
    AiCommandCenterInput,
    AiCommandCenterResponse,
    AiInvestigationResponse,
    AttendanceGapItemResponse,
    AttendanceGapMutationResponse,
    AttendanceGapsResponse,
    AttendanceResolutionDecisionResponse,
    AttendanceResolutionRejectInput,
    AttendanceResolutionResponse,
    BastGenerationJobResponse,
    BastReadinessResponse,
    CommandCenterResponse,
    FollowUpDraftInput,
    FollowUpDraftResponse,
    FollowUpSendInput,
    FollowUpSendResponse,
    IdentityRebindDecisionResponse,
    IdentityRebindRejectInput,
    IdentityRebindResponse,
    NotificationSettingsInput,
    NotificationSettingsResponse,
    OperationalSignalResponse,
    PeriodResponse,
    SessionUserResponse,
    TalentDetailResponse,
    TalentMobileSettingsInput,
    TalentMobileSettingsResponse,
    TalentOpsSessionResponse,
    WhatsAppInviteResponse,
    WhatsAppStatusResponse,
    WhatsAppUnlinkResponse,
    WorkflowOperatorResponse,
    WorkflowOperatorUpsertInput,
)

if TYPE_CHECKING:
    from datetime import datetime

    from digital_bast.application.attendance_review import AttendanceReviewService
    from digital_bast.application.bast_generation_jobs import (
        BastGenerationJob,
        BastGenerationJobService,
    )
    from digital_bast.application.bast_workflow import BastWorkflowService
    from digital_bast.application.talentops import TalentOpsService
    from digital_bast.application.talentops_followups import TalentOpsFollowUpService
    from digital_bast.application.workflow_control import (
        WorkflowControlService,
        WorkflowOperator,
    )
    from digital_bast.bot.attendance_resolution import AttendanceResolutionService, SubmitResult
    from digital_bast.bot.rebind import IdentityRebindService
    from digital_bast.infrastructure.whatsapp_outbound import BotBridgeWhatsAppOutboundGateway
    from digital_bast.web.contracts import SessionRecord
    from digital_bast.web.dependencies import WebDependencies

_API_PREFIX = "/api/talentops/v1"
_TIMEZONE_NAME = "Asia/Jakarta"
_ADMIN_ROLES = frozenset({"owner", "admin"})
type Capability = Literal["attendance", "rebind", "generate"]


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


async def _apply_submitted_gap(
    resolutions: AttendanceResolutionService, submit: SubmitResult, reviewer: str
) -> AttendanceGapMutationResponse:
    if submit.outcome is SubmitOutcome.CREATED:
        # PMO is the approver, and PMO is the one filling this form in -- there's
        # no separate reviewer to hand a pending request to, so apply it
        # immediately instead of leaving it stuck in the queue.
        if submit.request_id is not None:
            _ = await resolutions.decide(submit.request_id, reviewer, approve=True)
        return AttendanceGapMutationResponse(status="applied", message="Attendance sudah diperbarui")
    if submit.outcome is SubmitOutcome.ALREADY_OPEN:
        return AttendanceGapMutationResponse(
            status="already_open",
            message="Pengajuan attendance ini sudah menunggu review",
        )
    if submit.outcome is SubmitOutcome.EVIDENCE_REQUIRED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Evidence belum terhubung. Coba upload ulang.",
        )
    raise HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail="Attendance sudah berubah dan pengajuan tidak dapat dibuat",
    )


def _attendance_review(deps: WebDependencies) -> AttendanceReviewService:
    if deps.attendance_review is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Attendance evidence review service is unavailable",
        )
    return deps.attendance_review


def _workflow(deps: WebDependencies) -> WorkflowControlService:
    if deps.workflow_control is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Workflow authorization service is unavailable",
        )
    return deps.workflow_control


def _rebinds(deps: WebDependencies) -> IdentityRebindService:
    if deps.identity_rebinds is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Identity rebind service is unavailable",
        )
    return deps.identity_rebinds


def _bast_workflow(deps: WebDependencies) -> BastWorkflowService:
    if deps.bast_workflow is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="BAST workflow service is unavailable",
        )
    return deps.bast_workflow


def _bast_jobs(deps: WebDependencies) -> BastGenerationJobService:
    if deps.bast_generation_jobs is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="BAST generation job service is unavailable",
        )
    return deps.bast_generation_jobs


def _bast_job_response(job: BastGenerationJob, *, now: datetime) -> BastGenerationJobResponse:
    result = job.result or {}
    return BastGenerationJobResponse.model_validate({
        "id": str(job.id),
        "status": job.status,
        "display_status": bast_job_display_status(job, now=now),
        "report_type": job.parameters["report_type"],
        "year": job.parameters["year"],
        "month": job.parameters["month"],
        "mode": job.parameters["mode"],
        "forced": job.parameters["force"],
        "force_reason": job.parameters.get("force_reason"),
        "requested_by": job.parameters["requested_by"],
        "artifact_name": result.get("artifact_name"),
        "fingerprint": result.get("fingerprint"),
        "error_code": job.error_code,
        "error_message": result.get("error_message"),
        "created_at": job.created_at,
        "started_at": job.started_at,
        "finished_at": job.finished_at,
    })


def _bot_bridge(deps: WebDependencies) -> BotBridgeWhatsAppOutboundGateway:
    if deps.bot_bridge_status is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="WhatsApp bridge status is unavailable",
        )
    return deps.bot_bridge_status


def _is_admin(record: SessionRecord) -> bool:
    return record.user.role.casefold() in _ADMIN_ROLES


def _require_admin(record: SessionRecord) -> None:
    if not _is_admin(record):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access is required",
        )


def _normalize_talent_mobile_public_url(value: str | None) -> str | None:
    if value is None or not value.strip():
        return None
    raw = value.strip().rstrip("/")
    try:
        parsed = urlsplit(raw)
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Talent Mobile Public URL is invalid",
        ) from error
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Use an origin only, for example https://talentops.example.com",
        )
    loopback = parsed.hostname in {"localhost", "127.0.0.1", "::1"}
    if parsed.scheme != "https" and not loopback:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Talent Mobile Public URL must use HTTPS",
        )
    return raw


async def _authorized_operator(
    deps: WebDependencies,
    record: SessionRecord,
    capability: Capability | None = None,
) -> WorkflowOperator | None:
    # NocoDB owner/admin remains the super-admin bootstrap path and does not
    # require a workflow_operators row. Every PMO session does.
    if _is_admin(record):
        return None
    operator = await _workflow(deps).operator(record.user.email)
    if operator is None or not operator.active or operator.role is not WorkflowRole.PMO:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="PMO access is inactive")
    allowed = (
        capability is None
        or (capability == "attendance" and operator.can_approve_attendance)
        or (capability == "rebind" and operator.can_approve_rebind)
        or (capability == "generate" and operator.can_generate_bast)
    )
    if not allowed:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"PMO permission '{capability}' is not granted",
        )
    return operator


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


def _rebind_error(outcome: RebindDecisionOutcome, existing: RebindStatus | None) -> None:
    if outcome is RebindDecisionOutcome.NOT_FOUND:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Request not found")
    if outcome is RebindDecisionOutcome.ALREADY_RESOLVED:
        detail = (
            f"Request already {existing.value}"
            if existing is not None
            else "Request already resolved"
        )
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=detail)
    if outcome is RebindDecisionOutcome.SOURCE_CHANGED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Current WhatsApp binding changed; refresh before reviewing",
        )
    if outcome is RebindDecisionOutcome.NEW_NUMBER_ALREADY_BOUND:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="New WhatsApp number is already bound",
        )
    if outcome is RebindDecisionOutcome.REJECTION_REASON_REQUIRED:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Rejection reason is required",
        )
    raise HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail="Identity rebind decision failed",
    )


def talentops_router(  # noqa: C901, PLR0915
    deps: WebDependencies,
) -> APIRouter:
    router = APIRouter(prefix=_API_PREFIX, tags=["talentops"])

    async def session(request: Request) -> TalentOpsSessionResponse:
        _, record = await require_session(request, deps.sessions, deps.cookie, deps.now, api=True)
        return TalentOpsSessionResponse(
            user=SessionUserResponse(name=record.user.name, role=record.user.role),
            csrf_token=record.csrf_token,
            timezone=_TIMEZONE_NAME,
        )

    async def whatsapp_status(request: Request) -> WhatsAppStatusResponse:
        _ = await require_session(request, deps.sessions, deps.cookie, deps.now, api=True)
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
        _, record = await require_session(request, deps.sessions, deps.cookie, deps.now, api=True)
        _ = await _authorized_operator(deps, record)
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
        _, record = await require_session(request, deps.sessions, deps.cookie, deps.now, api=True)
        _ = await _authorized_operator(deps, record)
        selected_period = _period(year, month, deps.now())
        view = await _service(deps).talent_detail(selected_period, nrp)
        if view is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Talent not found")
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
        _, record = await require_session(request, deps.sessions, deps.cookie, deps.now, api=True)
        _ = await _authorized_operator(deps, record, "attendance")
        requests = await _attendance_resolutions(deps).pending()
        return tuple(AttendanceResolutionResponse.model_validate(item) for item in requests)

    async def attendance_resolution_evidence(
        request: Request,
        request_id: UUID,
    ) -> Response:
        _, record = await require_session(request, deps.sessions, deps.cookie, deps.now, api=True)
        _ = await _authorized_operator(deps, record, "attendance")
        evidence = await _attendance_review(deps).evidence(request_id)
        if evidence is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Evidence not found")
        return Response(
            content=evidence.content,
            media_type=evidence.content_type,
            headers={
                "Cache-Control": "private, no-store",
                "Content-Disposition": f'inline; filename="attendance-{evidence.evidence_id}"',
            },
        )

    async def approve_attendance_resolution(
        request: Request,
        request_id: UUID,
        csrf_token: HeaderCsrf = None,
    ) -> AttendanceResolutionDecisionResponse:
        _, record = await require_session(request, deps.sessions, deps.cookie, deps.now, api=True)
        verify_csrf(record, csrf_token)
        _ = await _authorized_operator(deps, record, "attendance")
        result = await _attendance_resolutions(deps).decide(
            request_id, record.user.email, approve=True
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
        _, record = await require_session(request, deps.sessions, deps.cookie, deps.now, api=True)
        verify_csrf(record, csrf_token)
        _ = await _authorized_operator(deps, record, "attendance")
        result = await _attendance_resolutions(deps).decide(
            request_id,
            record.user.email,
            approve=False,
            rejection_reason=payload.reason,
        )
        if result.outcome is not DecisionOutcome.UPDATED or result.status is None:
            _decision_error(result.outcome, result.status)
        return AttendanceResolutionDecisionResponse(status="rejected")

    async def identity_rebind_queue(
        request: Request,
    ) -> tuple[IdentityRebindResponse, ...]:
        _, record = await require_session(request, deps.sessions, deps.cookie, deps.now, api=True)
        operator = await _authorized_operator(deps, record, "rebind")
        scope = None if operator is None else operator.scope_key
        requests = await _rebinds(deps).pending(scope)
        return tuple(IdentityRebindResponse.model_validate(item) for item in requests)

    async def approve_identity_rebind(
        request: Request,
        request_id: UUID,
        csrf_token: HeaderCsrf = None,
    ) -> IdentityRebindDecisionResponse:
        _, record = await require_session(request, deps.sessions, deps.cookie, deps.now, api=True)
        verify_csrf(record, csrf_token)
        _ = await _authorized_operator(deps, record, "rebind")
        result = await _rebinds(deps).decide(
            request_id,
            record.user.email,
            approve=True,
        )
        if result.outcome is not RebindDecisionOutcome.UPDATED or result.status is None:
            _rebind_error(result.outcome, result.status)
        return IdentityRebindDecisionResponse(status="approved")

    async def reject_identity_rebind(
        request: Request,
        request_id: UUID,
        payload: IdentityRebindRejectInput,
        csrf_token: HeaderCsrf = None,
    ) -> IdentityRebindDecisionResponse:
        _, record = await require_session(request, deps.sessions, deps.cookie, deps.now, api=True)
        verify_csrf(record, csrf_token)
        _ = await _authorized_operator(deps, record, "rebind")
        result = await _rebinds(deps).decide(
            request_id,
            record.user.email,
            approve=False,
            rejection_reason=payload.reason,
        )
        if result.outcome is not RebindDecisionOutcome.UPDATED or result.status is None:
            _rebind_error(result.outcome, result.status)
        return IdentityRebindDecisionResponse(status="rejected")

    async def list_operators(request: Request) -> tuple[WorkflowOperatorResponse, ...]:
        _, record = await require_session(request, deps.sessions, deps.cookie, deps.now, api=True)
        _require_admin(record)
        operators = await _workflow(deps).list_operators()
        return tuple(WorkflowOperatorResponse.model_validate(item) for item in operators)

    async def upsert_operator(
        request: Request,
        email: str,
        payload: WorkflowOperatorUpsertInput,
        csrf_token: HeaderCsrf = None,
    ) -> WorkflowOperatorResponse:
        _, record = await require_session(request, deps.sessions, deps.cookie, deps.now, api=True)
        verify_csrf(record, csrf_token)
        _require_admin(record)
        operator = await _workflow(deps).upsert_operator(
            email=email,
            display_name=payload.display_name,
            role=WorkflowRole.PMO,
            scope_key=payload.scope_key,
            active=payload.active,
            can_approve_attendance=payload.can_approve_attendance,
            can_approve_rebind=payload.can_approve_rebind,
            can_generate_bast=payload.can_generate_bast,
            whatsapp_notify=payload.whatsapp_notify,
            actor=record.user.email,
        )
        return WorkflowOperatorResponse.model_validate(operator)

    async def issue_operator_whatsapp_invite(
        request: Request,
        email: str,
        csrf_token: HeaderCsrf = None,
    ) -> WhatsAppInviteResponse:
        _, record = await require_session(request, deps.sessions, deps.cookie, deps.now, api=True)
        verify_csrf(record, csrf_token)
        _require_admin(record)
        invite = await _workflow(deps).issue_whatsapp_invite(email, record.user.email)
        if invite is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Operator must be an active provisioned PMO",
            )
        return WhatsAppInviteResponse.model_validate(invite)

    async def unlink_operator_whatsapp(
        request: Request,
        email: str,
        csrf_token: HeaderCsrf = None,
    ) -> WhatsAppUnlinkResponse:
        _, record = await require_session(request, deps.sessions, deps.cookie, deps.now, api=True)
        verify_csrf(record, csrf_token)
        _require_admin(record)
        removed = await _workflow(deps).unlink_whatsapp(email)
        return WhatsAppUnlinkResponse(removed=removed)

    async def notification_settings(
        request: Request,
        scope_key: Annotated[str, Query(min_length=1, max_length=120)] = "default",
    ) -> NotificationSettingsResponse:
        _, record = await require_session(request, deps.sessions, deps.cookie, deps.now, api=True)
        operator = await _authorized_operator(deps, record)
        selected_scope = scope_key if operator is None else operator.scope_key
        settings = await _workflow(deps).notification_settings(selected_scope)
        return NotificationSettingsResponse.model_validate(settings)

    async def save_notification_settings(
        request: Request,
        payload: NotificationSettingsInput,
        scope_key: Annotated[str, Query(min_length=1, max_length=120)] = "default",
        csrf_token: HeaderCsrf = None,
    ) -> NotificationSettingsResponse:
        _, record = await require_session(request, deps.sessions, deps.cookie, deps.now, api=True)
        verify_csrf(record, csrf_token)
        _require_admin(record)
        invalid_talent_days = tuple(
            day for day in payload.talent_reminder_days if not 1 <= day <= 31
        )
        invalid_pmo_days = tuple(day for day in payload.pmo_reminder_days if not 1 <= day <= 31)
        if invalid_talent_days or invalid_pmo_days:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="Reminder dates must be calendar days between 1 and 31",
            )
        saved = await _workflow(deps).save_notification_settings(
            scope_key=scope_key,
            attendance_immediate=payload.attendance_immediate,
            rebind_immediate=payload.rebind_immediate,
            reminder_hour=payload.reminder_hour,
            talent_reminder_days=payload.talent_reminder_days,
            pmo_reminder_days=payload.pmo_reminder_days,
            actor=record.user.email,
        )
        return NotificationSettingsResponse.model_validate(saved)

    async def talent_mobile_settings(
        request: Request,
        scope_key: Annotated[str, Query(min_length=1, max_length=120)] = "default",
    ) -> TalentMobileSettingsResponse:
        _, record = await require_session(request, deps.sessions, deps.cookie, deps.now, api=True)
        _require_admin(record)
        settings = await _workflow(deps).talent_mobile_settings(scope_key)
        return TalentMobileSettingsResponse.model_validate(settings)

    async def save_talent_mobile_settings(
        request: Request,
        payload: TalentMobileSettingsInput,
        scope_key: Annotated[str, Query(min_length=1, max_length=120)] = "default",
        csrf_token: HeaderCsrf = None,
    ) -> TalentMobileSettingsResponse:
        _, record = await require_session(request, deps.sessions, deps.cookie, deps.now, api=True)
        verify_csrf(record, csrf_token)
        _require_admin(record)
        saved = await _workflow(deps).save_talent_mobile_settings(
            scope_key=scope_key,
            public_url=_normalize_talent_mobile_public_url(payload.public_url),
            actor=record.user.email,
        )
        return TalentMobileSettingsResponse.model_validate(saved)

    async def bast_readiness(
        request: Request,
        year: Annotated[int, Query(ge=2020, le=2100)],
        month: Annotated[int, Query(ge=1, le=12)],
        report_type: Annotated[str, Query(pattern="^(developer|iotoperation)$")],
    ) -> BastReadinessResponse:
        _, record = await require_session(request, deps.sessions, deps.cookie, deps.now, api=True)
        _ = await _authorized_operator(deps, record)
        selected_period = _period(year, month, deps.now())
        readiness = await _bast_workflow(deps).readiness(selected_period, report_type)
        return BastReadinessResponse.model_validate(readiness)

    async def generate_bast_document(
        request: Request,
        background_tasks: BackgroundTasks,
        year: Annotated[int, Query(ge=2020, le=2100)],
        month: Annotated[int, Query(ge=1, le=12)],
        report_type: Annotated[str, Query(pattern="^(developer|iotoperation)$")],
        mode: Annotated[str, Query(pattern="^(preview|final)$")] = "final",
        force: bool = False,
        force_reason: Annotated[str | None, Query(max_length=500)] = None,
        csrf_token: HeaderCsrf = None,
    ) -> BastGenerationJobResponse:
        _, record = await require_session(request, deps.sessions, deps.cookie, deps.now, api=True)
        verify_csrf(record, csrf_token)
        _ = await _authorized_operator(deps, record, "generate")
        selected_period = _period(year, month, deps.now())
        generation_mode = BastGenerationMode(mode)
        readiness = await _bast_workflow(deps).readiness(selected_period, report_type)
        if generation_mode is BastGenerationMode.FINAL and not readiness.ready and not force:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "code": "bast_not_ready",
                    "ready_talents": readiness.ready_talents,
                    "total_talents": readiness.total_talents,
                    "blockers": [
                        {
                            "nrp": item.nrp,
                            "name": item.name,
                            "domain": item.domain,
                            "issues": list(item.issues),
                        }
                        for item in readiness.blockers
                    ],
                },
            )
        normalized_reason = (force_reason or "").strip()
        if force and not normalized_reason:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="force_reason is required when force=true",
            )
        job = await _bast_jobs(deps).create(
            report_type=report_type,
            year=selected_period.start.year,
            month=selected_period.start.month,
            mode=generation_mode.value,
            forced=force,
            force_reason=normalized_reason or None,
            requested_by=record.user.email,
        )
        background_tasks.add_task(
            execute_bast_generation_job,
            job.id,
            _bast_jobs(deps),
            _bast_workflow(deps),
            selected_period=selected_period,
            report_type=report_type,
            generation_mode=generation_mode,
            forced=force,
            normalized_reason=normalized_reason or None,
            readiness=readiness,
            generated_by=record.user.email,
        )
        return _bast_job_response(job, now=deps.now())

    async def get_bast_generation_job(
        request: Request,
        job_id: UUID,
    ) -> BastGenerationJobResponse:
        _, record = await require_session(request, deps.sessions, deps.cookie, deps.now, api=True)
        _ = await _authorized_operator(deps, record, "generate")
        job = await _bast_jobs(deps).get(job_id)
        if job is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Generation job not found")
        return _bast_job_response(job, now=deps.now())

    async def list_bast_generation_jobs(
        request: Request,
        limit: Annotated[int, Query(ge=1, le=100)] = 20,
    ) -> tuple[BastGenerationJobResponse, ...]:
        _, record = await require_session(request, deps.sessions, deps.cookie, deps.now, api=True)
        _ = await _authorized_operator(deps, record, "generate")
        jobs = await _bast_jobs(deps).list_recent(limit=limit)
        now = deps.now()
        return tuple(_bast_job_response(job, now=now) for job in jobs)

    async def download_bast_document(
        request: Request,
        year: Annotated[int, Query(ge=2020, le=2100)],
        month: Annotated[int, Query(ge=1, le=12)],
        report_type: Annotated[str, Query(pattern="^(developer|iotoperation)$")],
    ) -> Response:
        _, record = await require_session(request, deps.sessions, deps.cookie, deps.now, api=True)
        _ = await _authorized_operator(deps, record, "generate")
        selected_period = _period(year, month, deps.now())
        path = bast_artifact_path(report_type, selected_period.start.year, selected_period.start.month)
        if not await run_sync(path.exists):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="BAST document not generated yet for this period",
            )
        pdf_bytes = await run_sync(path.read_bytes)
        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={
                "Cache-Control": "no-store",
                "Content-Disposition": f'attachment; filename="{path.name}"',
            },
        )

    async def ask_command_center(
        request: Request,
        payload: AiCommandCenterInput,
        csrf_token: HeaderCsrf = None,
    ) -> AiCommandCenterResponse:
        _, record = await require_session(request, deps.sessions, deps.cookie, deps.now, api=True)
        verify_csrf(record, csrf_token)
        _ = await _authorized_operator(deps, record)
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
        _, record = await require_session(request, deps.sessions, deps.cookie, deps.now, api=True)
        verify_csrf(record, csrf_token)
        _ = await _authorized_operator(deps, record)
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

    async def follow_up_draft(
        request: Request,
        nrp: str,
        payload: FollowUpDraftInput,
        csrf_token: HeaderCsrf = None,
    ) -> FollowUpDraftResponse:
        _, record = await require_session(request, deps.sessions, deps.cookie, deps.now, api=True)
        verify_csrf(record, csrf_token)
        _ = await _authorized_operator(deps, record)
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
        _, record = await require_session(request, deps.sessions, deps.cookie, deps.now, api=True)
        verify_csrf(record, csrf_token)
        _ = await _authorized_operator(deps, record)
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

    async def attendance_gaps(
        request: Request,
        year: Annotated[int | None, Query(ge=2020, le=2100)] = None,
        month: Annotated[int | None, Query(ge=1, le=12)] = None,
    ) -> AttendanceGapsResponse:
        _, record = await require_session(request, deps.sessions, deps.cookie, deps.now, api=True)
        _ = await _authorized_operator(deps, record, "attendance")
        selected_period = _period(year, month, deps.now())
        report = await completion_status(selected_period)
        evidence_service = create_attendance_evidence_service()
        items: list[AttendanceGapItemResponse] = []
        for employee in report.employees:
            candidates = (
                await evidence_service.list_candidates(
                    employee.employee_id,
                    frozenset(employee.log_1_pama_evidence_days),
                )
            ) + (
                await evidence_service.list_missing(
                    employee.employee_id,
                    frozenset(employee.log_1_pama_missing_data_days),
                )
            )
            items.extend(
                AttendanceGapItemResponse(
                    employee_id=employee.employee_id,
                    name=employee.name,
                    attendance_key=item.attendance_key,
                    work_date=item.work_date,
                    check_in=clock_label(item.check_in),
                    check_out=clock_label(item.check_out),
                    gap=gap_for(item.check_in, item.check_out),
                    evidence_count=item.evidence_count,
                )
                for item in candidates
            )
        items.sort(key=lambda item: (item.work_date, item.name))
        return AttendanceGapsResponse(
            period=PeriodResponse(
                year=selected_period.start.year,
                month=selected_period.start.month,
                start=selected_period.start.isoformat(),
                end=selected_period.end.isoformat(),
                label=selected_period.label(),
            ),
            items=tuple(items),
        )

    async def submit_attendance_gap(
        request: Request,
        # employee_id (e.g. "MTG-TF/2024110292") and attendance_key (e.g.
        # "attendance:2026-08-17:MTG-TF/2024110292") both contain literal "/"
        # characters -- unroutable as path segments (splits into extra
        # segments/404s for every employee), so they travel as form fields
        # instead, same as the rest of this multipart POST body.
        employee_id: Annotated[str, Form(max_length=200)],
        attendance_key: Annotated[str, Form(max_length=200)],
        action: Annotated[str, Form(max_length=32)],
        file: Annotated[UploadFile, File()],
        check_in: Annotated[str | None, Form(max_length=8)] = None,
        check_out: Annotated[str | None, Form(max_length=8)] = None,
        caption: Annotated[str, Form(max_length=500)] = "",
        year: Annotated[int | None, Query(ge=2020, le=2100)] = None,
        month: Annotated[int | None, Query(ge=1, le=12)] = None,
        csrf_token: HeaderCsrf = None,
    ) -> AttendanceGapMutationResponse:
        _, record = await require_session(request, deps.sessions, deps.cookie, deps.now, api=True)
        verify_csrf(record, csrf_token)
        _ = await _authorized_operator(deps, record, "attendance")
        selected_period = _period(year, month, deps.now())
        report = await completion_status(selected_period)
        employee = next(
            (item for item in report.employees if item.employee_id == employee_id),
            None,
        )
        if employee is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Talent not found")

        evidence_service = create_attendance_evidence_service()
        candidates = await evidence_service.list_candidates(
            employee_id,
            frozenset(employee.log_1_pama_evidence_days),
        )
        missing_candidates = await evidence_service.list_missing(
            employee_id,
            frozenset(employee.log_1_pama_missing_data_days),
        )
        target = next(
            (
                item
                for item in candidates + missing_candidates
                if item.attendance_key == attendance_key
            ),
            None,
        )
        if target is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Attendance gap sudah berubah, refresh dan coba lagi",
            )
        if target in missing_candidates:
            await evidence_service.ensure_manual(employee_id, target.work_date)

        resolution_type, proposed_in, proposed_out, absence_type = resolution_shape(
            gap_for(target.check_in, target.check_out),
            action,
            check_in,
            check_out,
        )
        upload_result = await evidence_service.upload(
            employee_id,
            attendance_key,
            await read_upload(file),
            caption.strip(),
        )
        if upload_result.outcome not in {UploadOutcome.STORED, UploadOutcome.DUPLICATE}:
            if upload_result.outcome is UploadOutcome.TOO_LARGE:
                raise HTTPException(
                    status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                    detail="Ukuran evidence maksimal 5 MB",
                )
            if upload_result.outcome is UploadOutcome.UNSUPPORTED_TYPE:
                raise HTTPException(
                    status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                    detail="Gunakan gambar JPG, PNG, atau WebP",
                )
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Evidence attendance tidak dapat disimpan",
            )

        resolutions = _attendance_resolutions(deps)
        submit = await resolutions.submit(
            employee_id,
            attendance_key,
            f"pmo-web:{record.user.email}",
            resolution_type,
            proposed_check_in=proposed_in,
            proposed_check_out=proposed_out,
            absence_type=absence_type,
        )
        return await _apply_submitted_gap(resolutions, submit, record.user.email)

    router.add_api_route(
        "/session", session, methods=["GET"], response_model=TalentOpsSessionResponse
    )
    router.add_api_route(
        "/system/whatsapp", whatsapp_status, methods=["GET"], response_model=WhatsAppStatusResponse
    )
    router.add_api_route(
        "/command-center", command_center, methods=["GET"], response_model=CommandCenterResponse
    )
    router.add_api_route(
        "/talents/{nrp}", talent_detail, methods=["GET"], response_model=TalentDetailResponse
    )
    router.add_api_route(
        "/attendance-resolutions",
        attendance_resolution_queue,
        methods=["GET"],
        response_model=tuple[AttendanceResolutionResponse, ...],
    )
    router.add_api_route(
        "/attendance-resolutions/{request_id}/evidence",
        attendance_resolution_evidence,
        methods=["GET"],
        response_class=Response,
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
        "/identity-rebinds",
        identity_rebind_queue,
        methods=["GET"],
        response_model=tuple[IdentityRebindResponse, ...],
    )
    router.add_api_route(
        "/identity-rebinds/{request_id}/approve",
        approve_identity_rebind,
        methods=["POST"],
        response_model=IdentityRebindDecisionResponse,
    )
    router.add_api_route(
        "/identity-rebinds/{request_id}/reject",
        reject_identity_rebind,
        methods=["POST"],
        response_model=IdentityRebindDecisionResponse,
    )
    router.add_api_route(
        "/operators",
        list_operators,
        methods=["GET"],
        response_model=tuple[WorkflowOperatorResponse, ...],
    )
    router.add_api_route(
        "/operators/{email}",
        upsert_operator,
        methods=["PUT"],
        response_model=WorkflowOperatorResponse,
    )
    router.add_api_route(
        "/operators/{email}/whatsapp-invite",
        issue_operator_whatsapp_invite,
        methods=["POST"],
        response_model=WhatsAppInviteResponse,
    )
    router.add_api_route(
        "/operators/{email}/whatsapp",
        unlink_operator_whatsapp,
        methods=["DELETE"],
        response_model=WhatsAppUnlinkResponse,
    )
    router.add_api_route(
        "/notification-settings",
        notification_settings,
        methods=["GET"],
        response_model=NotificationSettingsResponse,
    )
    router.add_api_route(
        "/notification-settings",
        save_notification_settings,
        methods=["PUT"],
        response_model=NotificationSettingsResponse,
    )
    router.add_api_route(
        "/talent-mobile-settings",
        talent_mobile_settings,
        methods=["GET"],
        response_model=TalentMobileSettingsResponse,
    )
    router.add_api_route(
        "/talent-mobile-settings",
        save_talent_mobile_settings,
        methods=["PUT"],
        response_model=TalentMobileSettingsResponse,
    )
    router.add_api_route(
        "/bast/readiness",
        bast_readiness,
        methods=["GET"],
        response_model=BastReadinessResponse,
    )
    router.add_api_route(
        "/bast/generate",
        generate_bast_document,
        methods=["POST"],
        response_model=BastGenerationJobResponse,
        status_code=status.HTTP_202_ACCEPTED,
    )
    router.add_api_route(
        "/bast/generate/jobs/{job_id}",
        get_bast_generation_job,
        methods=["GET"],
        response_model=BastGenerationJobResponse,
    )
    router.add_api_route(
        "/bast/generate/jobs",
        list_bast_generation_jobs,
        methods=["GET"],
        response_model=tuple[BastGenerationJobResponse, ...],
    )
    router.add_api_route(
        "/bast/generate/download",
        download_bast_document,
        methods=["GET"],
        response_class=Response,
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
    router.add_api_route(
        "/attendance-gaps",
        attendance_gaps,
        methods=["GET"],
        response_model=AttendanceGapsResponse,
    )
    router.add_api_route(
        "/attendance-gaps",
        submit_attendance_gap,
        methods=["POST"],
        response_model=AttendanceGapMutationResponse,
    )
    return router
