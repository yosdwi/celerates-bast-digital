from __future__ import annotations

from datetime import time
from typing import Annotated

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile, status

from digital_bast.application.talent_mobile_access import (
    TalentMobileClaims,
    verify_talent_mobile_token,
)
from digital_bast.bot.attendance_resolution import (
    AbsenceType,
    ResolutionType,
    SubmitOutcome,
)
from digital_bast.bot.evidence import MAX_IMAGE_BYTES, UploadOutcome
from digital_bast.config import get_settings
from digital_bast.domain.completion import DateRange
from digital_bast.domain.time import month_dates
from digital_bast.operations import (
    completion_status,
    create_activation_service,
    create_attendance_evidence_service,
    create_attendance_resolution_service,
    create_evidence_service,
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

_API_PREFIX = "/api/talent/v1"
_TOKEN_PREFIX = "bearer "


def _period(claims: TalentMobileClaims) -> DateRange:
    dates = month_dates(claims.year, claims.month)
    return DateRange(dates[0], dates[-1])


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


async def _claims(request: Request) -> TalentMobileClaims:
    authorization = request.headers.get("authorization", "")
    if not authorization.casefold().startswith(_TOKEN_PREFIX):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Link tidak valid")
    token = authorization[len(_TOKEN_PREFIX) :].strip()
    claims = verify_talent_mobile_token(_secret(), token)
    if claims is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Link sudah tidak valid atau kedaluwarsa",
        )
    employee_id = await create_activation_service().resolve(claims.jid)
    if employee_id != claims.employee_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Binding WhatsApp sudah berubah. Minta link baru dari bot.",
        )
    return claims


def _clock_label(value: time | None) -> str | None:
    return None if value is None else value.strftime("%H:%M")


def _gap(check_in: time | None, check_out: time | None) -> str:
    if check_in is None and check_out is None:
        return "missing_both"
    return "missing_clock_in" if check_in is None else "missing_clock_out"


def _request_label(resolution_type: ResolutionType, absence_type: AbsenceType | None) -> str:
    if resolution_type is ResolutionType.MISSING_CLOCK_IN:
        return "Koreksi Clock In"
    if resolution_type is ResolutionType.MISSING_CLOCK_OUT:
        return "Koreksi Clock Out"
    if resolution_type is ResolutionType.MISSING_BOTH_WORKED:
        return "Saya bekerja"
    return absence_type.value.capitalize() if absence_type is not None else "Attendance"


async def _read_upload(upload: UploadFile) -> bytes:
    try:
        content = await upload.read(MAX_IMAGE_BYTES + 1)
    finally:
        await upload.close()
    if len(content) > MAX_IMAGE_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="Ukuran evidence maksimal 5 MB",
        )
    if not content:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="File evidence kosong")
    return content


def _parse_time(value: str | None, label: str) -> time | None:
    if value is None or not value.strip():
        return None
    try:
        parsed = time.fromisoformat(value.strip())
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"{label} tidak valid",
        ) from error
    return parsed.replace(second=0, microsecond=0)


def _resolution_shape(
    gap: str,
    action: str,
    check_in_text: str | None,
    check_out_text: str | None,
) -> tuple[ResolutionType, time | None, time | None, AbsenceType | None]:
    normalized = action.strip().casefold()
    check_in = _parse_time(check_in_text, "Jam masuk")
    check_out = _parse_time(check_out_text, "Jam pulang")
    if gap == "missing_clock_in":
        if normalized != "worked" or check_in is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Isi jam masuk yang benar untuk melanjutkan",
            )
        return ResolutionType.MISSING_CLOCK_IN, check_in, None, None
    if gap == "missing_clock_out":
        if normalized != "worked" or check_out is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Isi jam pulang yang benar untuk melanjutkan",
            )
        return ResolutionType.MISSING_CLOCK_OUT, None, check_out, None
    if normalized == "worked":
        if check_in is None or check_out is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Isi jam masuk dan jam pulang untuk melanjutkan",
            )
        return ResolutionType.MISSING_BOTH_WORKED, check_in, check_out, None
    try:
        absence = AbsenceType(normalized)
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Pilih Saya bekerja, Sakit, Izin, atau Cuti",
        ) from error
    return ResolutionType.ABSENCE, None, None, absence


def talent_mobile_router() -> APIRouter:
    router = APIRouter(prefix=_API_PREFIX)

    async def overview(request: Request) -> TalentMobileOverview:
        claims = await _claims(request)
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

        task_service = create_evidence_service()
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
                complete=item.evidence_count > 0,
            )
            for item in period_tasks
        )
        task_complete = sum(item.complete for item in task_items)

        attendance_service = create_attendance_evidence_service()
        attendance_candidates = await attendance_service.list_candidates(
            claims.employee_id,
            frozenset(mine.log_1_pama_evidence_days),
        )
        attendance_items = tuple(
            TalentMobileAttendanceItem(
                attendance_key=item.attendance_key,
                work_date=item.work_date,
                check_in=_clock_label(item.check_in),
                check_out=_clock_label(item.check_out),
                gap=_gap(item.check_in, item.check_out),
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
                label=_request_label(item.resolution_type, item.absence_type),
                rejection_reason=item.rejection_reason,
            )
            for item in resolutions
            if period.start <= item.work_date <= period.end
        )

        return TalentMobileOverview(
            name=mine.name,
            period=TalentMobilePeriod(
                year=claims.year,
                month=claims.month,
                label=period.label(),
            ),
            task=TalentMobileTaskSummary(
                closed=len(task_items),
                complete=task_complete,
                missing=len(task_items) - task_complete,
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
        claims = await _claims(request)
        period = _period(claims)
        service = create_evidence_service()
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
        result = await service.upload(
            claims.employee_id,
            task_key,
            await _read_upload(file),
            caption.strip(),
        )
        if result.outcome is UploadOutcome.STORED:
            return TalentMobileMutationResponse(
                status="stored",
                message="Evidence task berhasil disimpan",
            )
        if result.outcome is UploadOutcome.DUPLICATE:
            return TalentMobileMutationResponse(
                status="already_present",
                message="Evidence ini sudah tersimpan pada task tersebut",
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

    async def submit_attendance(
        request: Request,
        attendance_key: str,
        action: Annotated[str, Form(max_length=32)],
        file: Annotated[UploadFile, File()],
        check_in: Annotated[str | None, Form(max_length=8)] = None,
        check_out: Annotated[str | None, Form(max_length=8)] = None,
        caption: Annotated[str, Form(max_length=500)] = "",
    ) -> TalentMobileMutationResponse:
        claims = await _claims(request)
        period = _period(claims)
        report = await completion_status(period)
        mine = next(
            (item for item in report.employees if item.employee_id == claims.employee_id),
            None,
        )
        if mine is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Attendance tidak tersedia")

        attendance_service = create_attendance_evidence_service()
        candidates = await attendance_service.list_candidates(
            claims.employee_id,
            frozenset(mine.log_1_pama_evidence_days),
        )
        target = next(
            (item for item in candidates if item.attendance_key == attendance_key),
            None,
        )
        if target is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Attendance sudah berubah. Refresh halaman sebelum melanjutkan.",
            )

        resolution_type, proposed_in, proposed_out, absence_type = _resolution_shape(
            _gap(target.check_in, target.check_out),
            action,
            check_in,
            check_out,
        )
        upload_result = await attendance_service.upload(
            claims.employee_id,
            attendance_key,
            await _read_upload(file),
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
            claims.jid,
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

    router.add_api_route("/overview", overview, methods=["GET"], response_model=TalentMobileOverview)
    router.add_api_route(
        "/tasks/{task_key}/evidence",
        upload_task_evidence,
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
