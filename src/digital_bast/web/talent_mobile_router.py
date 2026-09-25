from __future__ import annotations

from typing import TYPE_CHECKING, Annotated

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile, status

from digital_bast.application.talent_mobile_access import (
    TalentMobileClaims,
    talent_mobile_binding_matches,
    verify_talent_mobile_token,
)
from digital_bast.bot.attendance_resolution import SubmitOutcome
from digital_bast.bot.evidence import UploadOutcome
from digital_bast.config import get_settings
from digital_bast.operations import (
    completion_status,
    create_attendance_evidence_service,
    create_attendance_resolution_service,
    create_rebind_onboarding_service,
    create_task_evidence_submission_service,
)
from digital_bast.web.attendance_forms import (
    clock_label,
    gap_for,
    read_upload,
    request_label,
    resolution_shape,
)
from digital_bast.web.talent_mobile_contracts import (
    TalentMobileAttendanceItem,
    TalentMobileAttendanceRequest,
    TalentMobileAttendanceSummary,
    TalentMobileMutationResponse,
    TalentMobileOverview,
    TalentMobilePeriod,
    TalentMobileTask,
    TalentMobileTaskSummary,
)

if TYPE_CHECKING:
    from digital_bast.domain.completion import DateRange

_API_PREFIX = "/api/talent/v1"
_AUTH_SCHEME = "bearer"


def _period(claims: TalentMobileClaims) -> DateRange:
    return claims.period


def _secret() -> str:
    try:
        settings = get_settings()
    except (OSError, ValueError) as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Talent mobile access is unavailable",
        ) from error
    if settings.session_secret is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Talent mobile access is unavailable",
        )
    return settings.session_secret.get_secret_value()


async def _claims(request: Request) -> tuple[TalentMobileClaims, str]:
    authorization = request.headers.get("authorization", "")
    scheme, separator, token = authorization.partition(" ")
    if not separator or scheme.casefold() != _AUTH_SCHEME:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Link tidak valid")
    secret = _secret()
    claims = verify_talent_mobile_token(secret, token.strip())
    if claims is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Link sudah tidak valid atau kedaluwarsa",
        )
    if claims.access_mode == "pmo":
        if claims.actor_tag is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Link tidak valid")
        return claims, f"pmo-web:{claims.actor_tag}"
    if claims.binding_tag is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Link tidak valid")
    current_jid = await create_rebind_onboarding_service().existing_jid(claims.employee_id)
    if current_jid is None or not talent_mobile_binding_matches(
        secret,
        current_jid,
        claims.binding_tag,
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Binding WhatsApp sudah berubah. Minta link baru dari bot.",
        )
    return claims, current_jid


def talent_mobile_router() -> APIRouter:  # noqa: C901, PLR0915
    router = APIRouter(prefix=_API_PREFIX)

    async def overview(request: Request) -> TalentMobileOverview:
        claims, _audit_actor = await _claims(request)
        period = _period(claims)
        report = await completion_status(period)
        mine = next(
            (item for item in report.employees if item.employee_id == claims.employee_id),
            None,
        )
        if mine is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Data talent belum tersedia untuk periode ini",
            )

        task_service = create_task_evidence_submission_service()
        period_tasks = tuple(
            item
            for item in await task_service.list_candidates(claims.employee_id)
            if period.start <= item.work_date <= period.end
        )
        task_items = tuple(
            TalentMobileTask(
                task_key=item.task_key,
                title=item.title,
                work_date=item.work_date,
                task_source=item.task_source,
                evidence_count=item.evidence_count,
                staged_count=item.staged_count,
                complete=item.evidence_count > 0,
            )
            for item in period_tasks
        )
        task_complete = sum(item.complete for item in task_items)
        task_staged = sum(not item.complete and item.staged_count > 0 for item in task_items)

        attendance_service = create_attendance_evidence_service()
        attendance_candidates = (
            await attendance_service.list_candidates(
                claims.employee_id,
                frozenset(mine.log_1_pama_evidence_days),
            )
        ) + (
            await attendance_service.list_missing(
                claims.employee_id,
                frozenset(mine.log_1_pama_missing_data_days),
            )
        )
        attendance_items = tuple(
            TalentMobileAttendanceItem(
                attendance_key=item.attendance_key,
                work_date=item.work_date,
                check_in=clock_label(item.check_in),
                check_out=clock_label(item.check_out),
                gap=gap_for(item.check_in, item.check_out),
                evidence_count=item.evidence_count,
            )
            for item in attendance_candidates
        )

        resolutions = await create_attendance_resolution_service().for_employee(claims.employee_id)
        request_items = tuple(
            TalentMobileAttendanceRequest(
                id=str(item.id),
                work_date=item.work_date,
                status=item.status.value,
                label=request_label(item.resolution_type, item.absence_type),
                rejection_reason=item.rejection_reason,
            )
            for item in resolutions
            if period.start <= item.work_date <= period.end
        )

        return TalentMobileOverview(
            name=mine.name,
            period=TalentMobilePeriod(
                year=period.start.year,
                month=period.start.month,
                label=period.label(),
            ),
            task=TalentMobileTaskSummary(
                closed=len(task_items),
                complete=task_complete,
                missing=len(task_items) - task_complete,
                staged=task_staged,
                items=task_items,
            ),
            attendance=TalentMobileAttendanceSummary(
                total_work_days=mine.total_work_days,
                needs_action=len(attendance_items),
                missing_data_days=mine.log_1_pama_missing_data_days,
                items=attendance_items,
                requests=request_items,
            ),
        )

    async def upload_task_evidence(
        request: Request,
        task_key: str,
        file: Annotated[UploadFile, File()],
        caption: Annotated[str, Form(max_length=500)] = "",
    ) -> TalentMobileMutationResponse:
        claims, _audit_actor = await _claims(request)
        period = _period(claims)
        service = create_task_evidence_submission_service()
        candidates = tuple(
            item
            for item in await service.list_candidates(claims.employee_id)
            if period.start <= item.work_date <= period.end
        )
        target = next((item for item in candidates if item.task_key == task_key), None)
        if target is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Task tidak tersedia pada periode link ini",
            )
        result = await service.stage(
            claims.employee_id,
            task_key,
            await read_upload(file),
            caption.strip(),
        )
        if result.outcome is UploadOutcome.STORED:
            return TalentMobileMutationResponse(
                status="staged",
                message="Evidence ditambahkan. Setelah semua lengkap, tekan Ajukan ke PMO.",
            )
        if result.outcome is UploadOutcome.DUPLICATE:
            return TalentMobileMutationResponse(
                status="already_present",
                message="Evidence ini sudah ditambahkan pada task tersebut",
            )
        if result.outcome is UploadOutcome.TOO_LARGE:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail="Ukuran evidence maksimal 5 MB",
            )
        if result.outcome is UploadOutcome.UNSUPPORTED_TYPE:
            raise HTTPException(
                status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                detail="Gunakan gambar JPG, PNG, atau WebP",
            )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Task sudah berubah dan evidence tidak dapat disimpan",
        )

    async def submit_task_evidence(request: Request) -> TalentMobileMutationResponse:
        claims, audit_actor = await _claims(request)
        period = _period(claims)
        service = create_task_evidence_submission_service()
        candidates = tuple(
            item
            for item in await service.list_candidates(claims.employee_id)
            if period.start <= item.work_date <= period.end
        )
        if not any(item.staged_count > 0 for item in candidates):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Belum ada evidence baru yang siap diajukan ke PMO",
            )
        submitted = await service.submit(claims.employee_id, period, audit_actor)
        if submitted <= 0:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Task sudah berubah. Refresh halaman sebelum mengajukan kembali.",
            )
        return TalentMobileMutationResponse(
            status="submitted",
            message="Task & Evidence berhasil diajukan ke PMO dan masuk ke Conform.",
        )

    async def submit_attendance(  # noqa: PLR0913, PLR0917
        request: Request,
        attendance_key: str,
        action: Annotated[str, Form(max_length=32)],
        file: Annotated[UploadFile, File()],
        check_in: Annotated[str | None, Form(max_length=8)] = None,
        check_out: Annotated[str | None, Form(max_length=8)] = None,
        caption: Annotated[str, Form(max_length=500)] = "",
    ) -> TalentMobileMutationResponse:
        claims, audit_actor = await _claims(request)
        period = _period(claims)
        report = await completion_status(period)
        mine = next(
            (item for item in report.employees if item.employee_id == claims.employee_id),
            None,
        )
        if mine is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Attendance tidak tersedia",
            )

        attendance_service = create_attendance_evidence_service()
        candidates = await attendance_service.list_candidates(
            claims.employee_id,
            frozenset(mine.log_1_pama_evidence_days),
        )
        missing_candidates = await attendance_service.list_missing(
            claims.employee_id,
            frozenset(mine.log_1_pama_missing_data_days),
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
                detail="Attendance sudah berubah. Refresh halaman sebelum melanjutkan.",
            )
        if target in missing_candidates:
            # No attendance row exists yet for this day -- create the stub
            # row the rest of this flow (upload -> resolution submit) needs
            # to attach to. Safe against a concurrent PAMA sync: same
            # record_key, ON CONFLICT DO NOTHING (see AttendanceEvidenceService.ensure_manual).
            await attendance_service.ensure_manual(claims.employee_id, target.work_date)

        resolution_type, proposed_in, proposed_out, absence_type = resolution_shape(
            gap_for(target.check_in, target.check_out),
            action,
            check_in,
            check_out,
        )
        upload_result = await attendance_service.upload(
            claims.employee_id,
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

        submit = await create_attendance_resolution_service().submit(
            claims.employee_id,
            attendance_key,
            audit_actor,
            resolution_type,
            proposed_check_in=proposed_in,
            proposed_check_out=proposed_out,
            absence_type=absence_type,
        )
        if submit.outcome is SubmitOutcome.CREATED:
            return TalentMobileMutationResponse(
                status="submitted",
                message="Pengajuan attendance sudah dikirim ke PMO",
            )
        if submit.outcome is SubmitOutcome.ALREADY_OPEN:
            return TalentMobileMutationResponse(
                status="already_open",
                message="Pengajuan attendance ini sudah menunggu review PMO",
            )
        if submit.outcome is SubmitOutcome.EVIDENCE_REQUIRED:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Evidence belum terhubung. Coba upload ulang dari card ini.",
            )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Attendance sudah berubah dan pengajuan tidak dapat dibuat",
        )

    router.add_api_route(
        "/overview",
        overview,
        methods=["GET"],
        response_model=TalentMobileOverview,
    )
    router.add_api_route(
        "/tasks/{task_key}/evidence",
        upload_task_evidence,
        methods=["POST"],
        response_model=TalentMobileMutationResponse,
    )
    router.add_api_route(
        "/tasks/evidence/submit",
        submit_task_evidence,
        methods=["POST"],
        response_model=TalentMobileMutationResponse,
    )
    router.add_api_route(
        "/attendance/{attendance_key}/resolution",
        submit_attendance,
        methods=["POST"],
        response_model=TalentMobileMutationResponse,
    )
    return router
