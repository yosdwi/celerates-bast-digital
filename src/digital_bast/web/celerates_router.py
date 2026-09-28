"""Celerates integration adapter, API v1 (docs/celerates-integration-v1.md).

A versioned, service-authenticated boundary over the *existing* services:
Payroll closing projection, correction submit/review, evidence, BAST gate and
generation jobs, canonical attendance export, and governed reminder campaigns.
No readiness, correction, export or BAST rule is re-implemented here; the
adapter only shapes requests/responses, authenticates Celerates, records the
Celerates actor, and replays idempotent commands.
"""

from __future__ import annotations

import functools
import hashlib
import json
import re
import secrets
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from functools import cache
from typing import TYPE_CHECKING, Annotated, Any, Final, Literal, cast
from uuid import UUID, uuid4

import anyio
from anyio.to_thread import run_sync
from fastapi import APIRouter, BackgroundTasks, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field, ValidationError

from digital_bast.application.attendance_closing import AttendanceClosingStatus
from digital_bast.application.attendance_closing_policy import payroll_cycle, payroll_cycle_for
from digital_bast.application.bast_generation_jobs import (
    BastGenerationJobService,
    display_status,
)
from digital_bast.application.bast_generation_jobs import execute as execute_bast_generation_job
from digital_bast.application.bast_workflow import BastGenerationMode, BastWorkflowService
from digital_bast.application.celerates_campaigns import (
    AudienceMember,
    CampaignError,
    CampaignLink,
    CampaignPolicy,
    CeleratesCampaignService,
)
from digital_bast.application.payroll_export import PayrollExportService
from digital_bast.application.payroll_read import PayrollReadService
from digital_bast.application.payroll_review import PayrollReviewDecision, PayrollReviewService
from digital_bast.application.talentops import TalentOpsService
from digital_bast.bot.attendance_evidence import AttendanceEvidenceService
from digital_bast.bot.attendance_resolution import AttendanceResolutionService, SubmitOutcome
from digital_bast.bot.evidence import UploadOutcome
from digital_bast.config import SettingsConfigurationError, get_settings
from digital_bast.domain.completion import DateRange
from digital_bast.domain.identity import daily_key
from digital_bast.domain.time import JAKARTA, month_dates
from digital_bast.infrastructure.celerates_integration_store import (
    PostgresCampaignStore,
    PostgresIdempotencyStore,
    PostgresIntegrationControl,
    PostgresIntegrationReads,
    PostgresPmoSummaryLedger,
)
from digital_bast.infrastructure.completion_source import CompletionSource
from digital_bast.infrastructure.local_completion_source import (
    PostgresAttendanceFactReader,
    PostgresTaskEvidenceReader,
)
from digital_bast.infrastructure.payroll_attendance import PostgresPayrollAttendanceReader
from digital_bast.infrastructure.payroll_export_history import PostgresPayrollExportHistoryStore
from digital_bast.infrastructure.postgres_employees import PostgresEmployeeSource
from digital_bast.infrastructure.repositories import PostgresDomainRepository
from digital_bast.infrastructure.source_sync_state import PostgresSourceSyncStateStore
from digital_bast.infrastructure.whatsapp_directory import PostgresTalentWhatsAppDirectory
from digital_bast.infrastructure.whatsapp_identity import PostgresWhatsAppIdentityResolver
from digital_bast.infrastructure.whatsapp_outbound import (
    BotBridgeWhatsAppOutboundGateway,
    UnavailableWhatsAppOutboundGateway,
)
from digital_bast.operations import bast_artifact_path, export_attendance_report
from digital_bast.web.attendance_forms import read_upload, resolution_shape
from digital_bast.web.postgres_backend import PostgresWebBackend

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Mapping
    from pathlib import Path

    from digital_bast.application.attendance_closing_policy import PayrollCycle
    from digital_bast.application.bast_generation_jobs import BastGenerationJob
    from digital_bast.application.payroll_read import PayrollDayView, PayrollOverview
    from digital_bast.application.payroll_review import PayrollReviewItem
    from digital_bast.web.dependencies import WebDependencies

API_PREFIX: Final = "/api/celerates/v1"
API_VERSION: Final = "1"
CAPABILITIES: Final = (
    "readiness",
    "talent_requirements",
    "attendance_corrections",
    "correction_review",
    "evidence",
    "bast",
    "attendance_export",
    "campaigns",
    "pmo_summary",
    "source_freshness",
)
_KEY = re.compile(r"^[A-Za-z0-9:_.\-]{8,160}$")
_SOURCE_LABELS: Final = {
    "attendance": "PAMA attendance",
    "redmine": "Redmine",
    "iot_sheet": "IoT task source",
}
_ALL_ACTIONS: Final = ("worked", "sakit", "izin", "cuti", "libur")


class AdapterError(Exception):
    def __init__(
        self,
        status: int,
        code: str,
        message: str,
        *,
        retryable: bool = False,
    ) -> None:
        super().__init__(code, message)
        self.status: int = status
        self.code: str = code
        self.message: str = message
        self.retryable: bool = retryable


def _error(error: AdapterError) -> JSONResponse:
    return JSONResponse(
        {"error": {"code": error.code, "message": error.message, "retryable": error.retryable}},
        status_code=error.status,
        headers={"Cache-Control": "no-store"},
    )


# -- services ------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class CeleratesServices:
    token: str
    public_url: str | None
    group_jid_reader: Callable[[], Awaitable[str | None]]
    employees: PostgresEmployeeSource
    payroll: PayrollReadService
    review: PayrollReviewService
    resolutions: AttendanceResolutionService
    evidence: AttendanceEvidenceService
    attendance_review: Any
    sources: PostgresSourceSyncStateStore
    bast_workflow: BastWorkflowService
    bast_jobs: BastGenerationJobService
    export: PayrollExportService
    campaigns: CeleratesCampaignService
    campaign_store: PostgresCampaignStore
    control: PostgresIntegrationControl
    idempotency: PostgresIdempotencyStore
    reads: PostgresIntegrationReads
    summaries: PostgresPmoSummaryLedger
    outbound: BotBridgeWhatsAppOutboundGateway | UnavailableWhatsAppOutboundGateway


class _PayrollAudience:
    """Campaign audience = the live Payroll projection + WhatsApp-bound boolean."""

    def __init__(self, payroll: PayrollReadService, reads: PostgresIntegrationReads) -> None:
        self._payroll = payroll
        self._reads = reads

    async def audience(self, cycle: PayrollCycle) -> Mapping[str, AudienceMember]:
        overview = await self._payroll.overview(cycle, now=datetime.now(UTC))
        bound = await self._reads.bound_employee_ids()
        return {
            talent.employee_id: AudienceMember(
                employee_id=talent.employee_id,
                nrp=talent.nrp,
                name=talent.name,
                actionable_dates=tuple(
                    day.work_date for day in talent.days if day.talent_action_required
                ),
                whatsapp_bound=talent.employee_id in bound,
            )
            for talent in overview.talents
        }


@cache
def _configured() -> CeleratesServices | None:
    try:
        settings = get_settings()
    except (OSError, ValueError, SettingsConfigurationError):
        return None
    if settings.database_dsn is None or settings.celerates_service_token is None:
        return None
    dsn = settings.database_dsn.get_secret_value()
    from digital_bast.application.attendance_review import AttendanceReviewService  # noqa: PLC0415

    employees = PostgresEmployeeSource(dsn)
    records = PostgresDomainRepository(dsn)
    payroll = PayrollReadService(employees, records, PostgresPayrollAttendanceReader(dsn))
    resolutions = AttendanceResolutionService(dsn)
    attendance_review = AttendanceReviewService(dsn)
    sources = PostgresSourceSyncStateStore(dsn)
    completion = CompletionSource(
        employees,
        records,
        PostgresAttendanceFactReader(dsn),
        PostgresTaskEvidenceReader(dsn),
    )
    talentops = TalentOpsService(completion, employees, records, sources)
    backend = PostgresWebBackend(dsn)

    async def exporter(
        period: DateRange, report_type: str, employee: str | None
    ) -> tuple[Path, int]:
        return await export_attendance_report(period, report_type, employee, backend=backend)

    outbound: BotBridgeWhatsAppOutboundGateway | UnavailableWhatsAppOutboundGateway = (
        BotBridgeWhatsAppOutboundGateway(
            str(settings.bot_bridge_base_url),
            settings.sync_ingest_token.get_secret_value(),
        )
        if settings.bot_bridge_base_url is not None and settings.sync_ingest_token is not None
        else UnavailableWhatsAppOutboundGateway()
    )
    reads = PostgresIntegrationReads(dsn)
    store = PostgresCampaignStore(dsn, payroll_cycle)
    public_url = (
        str(settings.celerates_public_url).rstrip("/") if settings.celerates_public_url else None
    )
    campaigns = CeleratesCampaignService(
        store,
        _PayrollAudience(payroll, reads),
        PostgresWhatsAppIdentityResolver(dsn),
        outbound,
        cycle_for=payroll_cycle,
        new_id=uuid4,
        sleep=anyio.sleep,
        allowed_link_prefix=public_url,
    )
    directory = PostgresTalentWhatsAppDirectory(dsn)

    async def group_jid() -> str | None:
        # The existing Payroll closing group (TalentOps WhatsApp directory setting).
        return (await directory.closing_group("default")).group_jid

    return CeleratesServices(
        token=settings.celerates_service_token.get_secret_value(),
        public_url=public_url,
        group_jid_reader=group_jid,
        employees=employees,
        payroll=payroll,
        review=PayrollReviewService(payroll, resolutions, attendance_review),
        resolutions=resolutions,
        evidence=AttendanceEvidenceService(dsn),
        attendance_review=attendance_review,
        sources=sources,
        bast_workflow=BastWorkflowService(dsn, talentops),
        bast_jobs=BastGenerationJobService(dsn),
        export=PayrollExportService(exporter, PostgresPayrollExportHistoryStore(dsn)),
        campaigns=campaigns,
        campaign_store=store,
        control=PostgresIntegrationControl(dsn),
        idempotency=PostgresIdempotencyStore(dsn),
        reads=reads,
        summaries=PostgresPmoSummaryLedger(dsn),
        outbound=outbound,
    )


def configured_services() -> CeleratesServices | None:
    """Services wired from settings; None when the integration is not configured."""
    return _configured()


# -- request helpers -----------------------------------------------------------
def _authorize(request: Request, services: CeleratesServices | None) -> CeleratesServices:
    if services is None:
        raise AdapterError(
            503, "integration_unconfigured", "Celerates integration is not configured"
        )
    scheme, _, token = request.headers.get("authorization", "").partition(" ")
    if scheme.casefold() != "bearer" or not secrets.compare_digest(
        token.strip().encode(), services.token.encode()
    ):
        raise AdapterError(401, "unauthorized", "Invalid service credentials")
    return services


def _actor(request: Request) -> str:
    actor = request.headers.get("x-celerates-actor", "").strip()
    if not actor or len(actor) > 200:  # noqa: PLR2004
        raise AdapterError(400, "actor_required", "X-Celerates-Actor is required")
    return actor


def _key(request: Request) -> str:
    key = request.headers.get("idempotency-key", "").strip()
    if not _KEY.fullmatch(key):
        raise AdapterError(400, "idempotency_key_required", "A valid Idempotency-Key is required")
    return key


def _cycle(year: int | None, month: int | None) -> PayrollCycle:
    if (year is None) != (month is None):
        raise AdapterError(422, "invalid_period", "year and month must be provided together")
    if year is None or month is None:
        return payroll_cycle_for(datetime.now(JAKARTA).date())
    if not (2020 <= year <= 2100 and 1 <= month <= 12):  # noqa: PLR2004
        raise AdapterError(422, "invalid_period", "Invalid year or month")
    return payroll_cycle(year, month)


def _calendar(year: int, month: int) -> DateRange:
    days = month_dates(year, month)
    return DateRange(days[0], days[-1])


def _previous(cycle: PayrollCycle) -> PayrollCycle:
    if cycle.label_month == 1:
        return payroll_cycle(cycle.label_year - 1, 12, cycle.closing_day)
    return payroll_cycle(cycle.label_year, cycle.label_month - 1, cycle.closing_day)


def _cycle_json(cycle: PayrollCycle) -> dict[str, object]:
    return {
        "id": cycle.cycle_id,
        "label": cycle.label,
        "year": cycle.label_year,
        "month": cycle.label_month,
        "start": cycle.period.start.isoformat(),
        "end": cycle.period.end.isoformat(),
        "closing_day": cycle.closing_day,
    }


def _iso(value: datetime | date | None) -> str | None:
    return None if value is None else value.isoformat()


def _gap(day: PayrollDayView) -> Literal["missing_clock_in", "missing_clock_out", "missing_both"]:
    if day.raw_check_in is None and day.raw_check_out is None:
        return "missing_both"
    return "missing_clock_in" if day.raw_check_in is None else "missing_clock_out"


def _requirement(day: PayrollDayView) -> dict[str, object]:
    gap = _gap(day)
    correction = (
        None
        if day.resolution_id is None
        else {
            "id": day.resolution_id,
            "status": day.resolution_status,
            "resolution_type": day.resolution_type,
            "absence_type": day.absence_type,
            "proposed_check_in": day.proposed_check_in,
            "proposed_check_out": day.proposed_check_out,
            "rejection_reason": day.rejection_reason,
        }
    )
    return {
        "requirement_id": f"attendance:{day.work_date.isoformat()}",
        "kind": "attendance_gap",
        "work_date": day.work_date.isoformat(),
        "attendance_key": day.attendance_key,
        "gap": gap,
        "raw_check_in": day.raw_check_in,
        "raw_check_out": day.raw_check_out,
        "state": "needs_action" if day.talent_action_required else "waiting_review",
        "reason": day.reason.value,
        "allowed_actions": list(_ALL_ACTIONS) if gap == "missing_both" else ["worked"],
        "has_evidence": day.has_evidence,
        "correction": correction,
    }


async def _overview(services: CeleratesServices, cycle: PayrollCycle) -> PayrollOverview:
    return await services.payroll.overview(cycle, now=datetime.now(UTC))


def _request_hash(payload: object) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()


async def _replay_or_run(  # noqa: PLR0913 - keyword-only command envelope
    services: CeleratesServices,
    *,
    key: str,
    route: str,
    request_hash: str,
    actor: str,
    run: Callable[[], Awaitable[tuple[int, object]]],
) -> JSONResponse:
    stored = await services.idempotency.get(key, route)
    if stored is not None:
        if stored.request_hash != request_hash:
            raise AdapterError(
                409, "idempotency_conflict", "Idempotency-Key reused with another request"
            )
        return JSONResponse(
            stored.body, status_code=stored.status_code, headers={"Idempotent-Replay": "true"}
        )
    status_code, body = await run()
    await services.idempotency.put(key, route, request_hash, status_code, body, actor)
    return JSONResponse(body, status_code=status_code, headers={"Cache-Control": "no-store"})


async def _json(request: Request) -> dict[str, object]:
    try:
        payload = cast("object", await request.json())
    except ValueError as error:
        raise AdapterError(400, "invalid_json", "Body must be JSON") from error
    if not isinstance(payload, dict):
        raise AdapterError(400, "invalid_json", "Body must be a JSON object")
    return cast("dict[str, object]", payload)


def _model[M: BaseModel](model: type[M], payload: dict[str, object]) -> M:
    try:
        return model.model_validate(payload)
    except ValidationError as error:
        first = error.errors()[0]
        field = ".".join(str(part) for part in first["loc"])
        raise AdapterError(422, "invalid_request", f"{field}: {first['msg']}") from error


class _PeriodBody(BaseModel):
    year: int = Field(ge=2020, le=2100)
    month: int = Field(ge=1, le=12)


class _DecisionBody(BaseModel):
    decision: Literal["approve", "reject"]
    reason: str | None = Field(default=None, max_length=500)


class _BastBody(_PeriodBody):
    report_type: Literal["developer", "iotoperation"]
    mode: Literal["preview", "final"] = "final"
    force: bool = False
    force_reason: str | None = Field(default=None, max_length=500)


class _ExportBody(_PeriodBody):
    report_type: Literal["developer", "shifting"]


class _CampaignBody(_PeriodBody):
    window_start_hour: int = 8
    window_end_hour: int = 18
    batch_size: int = 10
    cooldown_seconds: int = 600
    min_interval_seconds: int = 3
    max_attempts: int = 3


class _LinkBody(BaseModel):
    employee_id: str = Field(min_length=1, max_length=120)
    url: str = Field(min_length=8, max_length=500)
    expires_at: datetime


class _ApproveBody(BaseModel):
    links: list[_LinkBody] = Field(default_factory=list, max_length=500)


class _PauseBody(BaseModel):
    reason: str | None = Field(default=None, max_length=200)


class _ControlBody(BaseModel):
    kill_switch: bool


class _SummaryBody(_PeriodBody):
    link: str = Field(min_length=8, max_length=500)


def _campaign_json(
    services: CeleratesServices,
    campaign_id: UUID,
    found: tuple[Any, tuple[Any, ...]],
    events: tuple[dict[str, Any], ...] = (),
) -> dict[str, object]:
    campaign, recipients = found
    counts: dict[str, int] = {}
    for item in recipients:
        counts[item.state.value] = counts.get(item.state.value, 0) + 1
    preview = CeleratesCampaignPreview.message(
        campaign.cycle_label, f"{services.public_url or 'https://celerates.example'}/go/…"
    )
    return {
        "id": str(campaign_id),
        "kind": "talent_attendance",
        "state": campaign.state.value,
        "cycle": _cycle_json(payroll_cycle(campaign.cycle_year, campaign.cycle_month)),
        "policy": {
            "window_start_hour": campaign.policy.window_start_hour,
            "window_end_hour": campaign.policy.window_end_hour,
            "batch_size": campaign.policy.batch_size,
            "cooldown_seconds": campaign.policy.cooldown_seconds,
            "min_interval_seconds": campaign.policy.min_interval_seconds,
            "max_attempts": campaign.policy.max_attempts,
        },
        "created_by": campaign.created_by,
        "created_at": _iso(campaign.created_at),
        "approved_by": campaign.approved_by,
        "approved_at": _iso(campaign.approved_at),
        "finished_at": _iso(campaign.finished_at),
        "next_dispatch_at": _iso(campaign.next_dispatch_at),
        "pause_reason": campaign.pause_reason,
        "message_preview": preview,
        "counts": {
            "total": len(recipients),
            "eligible": sum(item.eligibility == "eligible" for item in recipients),
            **counts,
        },
        "recipients": [
            {
                "id": str(item.id),
                "employee_id": item.employee_id,
                "nrp": item.nrp,
                "name": item.name,
                "eligibility": item.eligibility,
                "actionable_days": item.actionable_days,
                "state": item.state.value,
                "attempt_count": item.attempt_count,
                "last_error": item.last_error,
                "sent_at": _iso(item.sent_at),
                "has_link": item.link_url is not None,
            }
            for item in recipients
        ],
        "events": [
            {
                "event": row["event"],
                "actor": row["actor"],
                "recipient_id": None if row["recipient_id"] is None else str(row["recipient_id"]),
                "at": _iso(cast("datetime", row["created_at"])),
            }
            for row in events
        ],
    }


class CeleratesCampaignPreview:
    @staticmethod
    def message(cycle_label: str, link: str) -> str:
        from digital_bast.application.celerates_campaigns import (  # noqa: PLC0415
            compose_talent_message,
        )

        sample_day = datetime.now(JAKARTA).date()
        return compose_talent_message(
            name="[Nama]",
            cycle_label=cycle_label,
            dates=(sample_day,),
            link=link,
            expires_at=datetime.now(UTC) + timedelta(hours=72),
        )


def compose_pmo_summary(overview: PayrollOverview, pending: int, link: str) -> str:
    summary = overview.summary
    return (
        f"Ringkasan closing {overview.cycle.label}\n"
        f"Lengkap: {summary.complete}/{summary.total_talents} Talent\n"
        f"Perlu aksi Talent: {summary.needs_talent_action}\n"
        f"Menunggu review PMO: {pending}\n"
        f"Belum terverifikasi: {summary.unverified}\n"
        f"Tinjau di Celerates: {link}"
    )


# -- router --------------------------------------------------------------------
def celerates_router(  # noqa: C901, PLR0915
    deps: WebDependencies,
    services: Callable[[], CeleratesServices | None] = _configured,
) -> APIRouter:
    router = APIRouter(prefix=API_PREFIX, include_in_schema=False)
    del deps  # built from settings so the router needs no optional WebDependencies

    def endpoint(
        handler: Callable[..., Awaitable[Response]],
    ) -> Callable[..., Awaitable[Response]]:
        @functools.wraps(handler)
        async def wrapped(*args: object, **kwargs: object) -> Response:
            try:
                return await handler(*args, **kwargs)
            except AdapterError as error:
                return _error(error)
            except CampaignError as error:
                status = 404 if error.code == "campaign_not_found" else 409
                if error.code in {
                    "invalid_policy",
                    "link_not_allowed",
                    "invalid_link_expiry",
                    "unknown_recipient",
                }:
                    status = 422
                return _error(AdapterError(status, error.code, error.message))
            except HTTPException as error:
                detail = str(error.detail) or "Request rejected"
                return _error(AdapterError(error.status_code, "invalid_request", detail))

        return wrapped

    @endpoint
    async def meta(request: Request) -> Response:
        _ = _authorize(request, services())
        return JSONResponse(
            {
                "api_version": API_VERSION,
                "service": "conform",
                "capabilities": list(CAPABILITIES),
                "now": datetime.now(UTC).isoformat(),
            }
        )

    @endpoint
    async def readiness(
        request: Request, year: int | None = None, month: int | None = None
    ) -> Response:
        svc = _authorize(request, services())
        cycle = _cycle(year, month)
        overview = await _overview(svc, cycle)
        bound = await svc.reads.bound_employee_ids()
        queue = await svc.review.queue(cycle, now=datetime.now(UTC))
        snapshots = {item.source_key: item for item in await svc.sources.load()}
        now = datetime.now(UTC)
        calendar = _calendar(cycle.label_year, cycle.label_month)
        bast: list[dict[str, object]] = []
        for report_type in ("developer", "iotoperation"):
            gate = await svc.bast_workflow.readiness(calendar, report_type)
            bast.append(
                {
                    "report_type": report_type,
                    "ready": gate.ready,
                    "ready_talents": gate.ready_talents,
                    "total_talents": gate.total_talents,
                }
            )
        return JSONResponse(
            {
                "cycle": _cycle_json(cycle),
                "evaluated_through": _iso(overview.evaluated_through),
                "summary": {
                    "total_talents": overview.summary.total_talents,
                    "complete": overview.summary.complete,
                    "waiting_submitted": overview.summary.waiting_submitted,
                    "needs_talent_action": overview.summary.needs_talent_action,
                    "unverified": overview.summary.unverified,
                },
                "talents": [
                    {
                        "employee_id": talent.employee_id,
                        "nrp": talent.nrp,
                        "name": talent.name,
                        "role": talent.role,
                        "status": talent.status.value,
                        "actionable_days": talent.actionable_days,
                        "waiting_days": talent.waiting_days,
                        "unverified_days": talent.unverified_days,
                        "whatsapp_bound": talent.employee_id in bound,
                    }
                    for talent in overview.talents
                ],
                "pending_corrections": queue.summary.total,
                "sources": [
                    {
                        "source_key": key,
                        "label": label,
                        "last_success_at": _iso(snapshots[key].last_success_at)
                        if key in snapshots
                        else None,
                        "age_seconds": int((now - snapshots[key].last_success_at).total_seconds())
                        if key in snapshots
                        else None,
                    }
                    for key, label in _SOURCE_LABELS.items()
                ],
                "bast": bast,
            },
            headers={"Cache-Control": "no-store"},
        )

    async def _talent(svc: CeleratesServices, employee_id: str) -> dict[str, object]:
        for employee in await svc.employees.load():
            if str(employee.id) == employee_id:
                bound = employee_id in await svc.reads.bound_employee_ids()
                return {
                    "employee_id": str(employee.id),
                    "nrp": employee.external_id,
                    "name": employee.name,
                    "role": employee.role.value,
                    "whatsapp_bound": bound,
                }
        raise AdapterError(404, "talent_not_found", "Talent not found or not active")

    @endpoint
    async def lookup(request: Request, employee_id: str) -> Response:
        svc = _authorize(request, services())
        return JSONResponse(await _talent(svc, employee_id.strip()))

    @endpoint
    async def requirements(
        request: Request, employee_id: str, year: int | None = None, month: int | None = None
    ) -> Response:
        svc = _authorize(request, services())
        cycle = _cycle(year, month)
        overview = await _overview(svc, cycle)
        talent = next((item for item in overview.talents if item.employee_id == employee_id), None)
        if talent is None:
            raise AdapterError(404, "talent_not_found", "Talent not found or not active")
        open_days = [
            day
            for day in talent.days
            if day.talent_action_required or day.status is AttendanceClosingStatus.WAITING_SUBMITTED
        ]
        return JSONResponse(
            {
                "cycle": _cycle_json(cycle),
                "evaluated_through": _iso(overview.evaluated_through),
                "talent": {
                    "employee_id": talent.employee_id,
                    "nrp": talent.nrp,
                    "name": talent.name,
                    "role": talent.role,
                    "status": talent.status.value,
                    "actionable_days": talent.actionable_days,
                    "waiting_days": talent.waiting_days,
                    "unverified_days": talent.unverified_days,
                },
                "requirements": [_requirement(day) for day in open_days],
            },
            headers={"Cache-Control": "no-store"},
        )

    @endpoint
    async def submit_correction(  # noqa: PLR0913, PLR0917
        request: Request,
        employee_id: Annotated[str, Form(max_length=120)],
        work_date: Annotated[date, Form()],
        action: Annotated[str, Form(max_length=32)],
        file: Annotated[UploadFile, File()],
        check_in: Annotated[str | None, Form(max_length=8)] = None,
        check_out: Annotated[str | None, Form(max_length=8)] = None,
        caption: Annotated[str, Form(max_length=500)] = "",
    ) -> Response:
        svc = _authorize(request, services())
        actor = _actor(request)
        key = _key(request)
        content = await read_upload(file)
        request_hash = _request_hash(
            {
                "employee_id": employee_id,
                "work_date": work_date,
                "action": action,
                "check_in": check_in,
                "check_out": check_out,
                "caption": caption,
                "file": hashlib.sha256(content).hexdigest(),
            }
        )

        async def run() -> tuple[int, object]:
            cycle = payroll_cycle_for(work_date)
            overview = await _overview(svc, cycle)
            talent = next(
                (item for item in overview.talents if item.employee_id == employee_id), None
            )
            day = (
                None
                if talent is None
                else next((item for item in talent.days if item.work_date == work_date), None)
            )
            # Re-validate against the live projection immediately before the write.
            if day is None or not day.talent_action_required:
                raise AdapterError(
                    409,
                    "requirement_not_actionable",
                    "This day no longer needs a correction. Refresh and try again.",
                )
            attendance_key = day.attendance_key
            if attendance_key is None:
                await svc.evidence.ensure_manual(employee_id, work_date)
                attendance_key = str(daily_key("attendance", work_date, employee_id))
            resolution_type, proposed_in, proposed_out, absence_type = resolution_shape(
                _gap(day), action, check_in, check_out
            )
            upload = await svc.evidence.upload(
                employee_id, attendance_key, content, caption.strip()
            )
            if upload.outcome not in {UploadOutcome.STORED, UploadOutcome.DUPLICATE}:
                if upload.outcome is UploadOutcome.TOO_LARGE:
                    raise AdapterError(413, "evidence_too_large", "Evidence is limited to 5 MB")
                if upload.outcome is UploadOutcome.UNSUPPORTED_TYPE:
                    raise AdapterError(415, "evidence_unsupported", "Use a JPG, PNG or WebP image")
                raise AdapterError(
                    409, "evidence_rejected", f"Evidence was not stored ({upload.outcome.value})"
                )
            result = await svc.resolutions.submit(
                employee_id,
                attendance_key,
                actor,
                resolution_type,
                proposed_check_in=proposed_in,
                proposed_check_out=proposed_out,
                absence_type=absence_type,
            )
            if result.outcome is SubmitOutcome.CREATED:
                status = "submitted"
            elif result.outcome is SubmitOutcome.ALREADY_OPEN:
                status = "already_open"
            else:
                raise AdapterError(
                    409,
                    f"submit_{result.outcome.value}",
                    "Attendance changed; the correction was not created",
                )
            return 201, {
                "status": status,
                "correction_id": None if result.request_id is None else str(result.request_id),
                "requirement_id": f"attendance:{work_date.isoformat()}",
            }

        return await _replay_or_run(
            svc,
            key=key,
            route="attendance-corrections",
            request_hash=request_hash,
            actor=actor,
            run=run,
        )

    def _correction_item(item: PayrollReviewItem) -> dict[str, object]:
        return {
            "id": str(item.request_id),
            "status": "pending",
            "employee_id": item.employee_id,
            "nrp": item.nrp,
            "name": item.name,
            "role": item.role,
            "work_date": item.work_date.isoformat(),
            "resolution_type": item.resolution_type.value,
            "absence_type": item.absence_type,
            "raw_check_in": item.raw_check_in,
            "raw_check_out": item.raw_check_out,
            "proposed_check_in": item.proposed_check_in,
            "proposed_check_out": item.proposed_check_out,
            "evidence": {
                "content_type": item.evidence_content_type,
                "byte_size": item.evidence_byte_size,
                "caption": item.evidence_caption,
                "uploaded_at": _iso(item.evidence_uploaded_at),
            },
            "requested_by": None,
            "submitted_at": _iso(item.submitted_at),
            "reviewable": item.reviewable,
            "reviewability_reason": None
            if item.reviewability_reason is None
            else item.reviewability_reason.value,
        }

    async def _queue_items(
        svc: CeleratesServices, cycles: tuple[PayrollCycle, ...]
    ) -> list[dict[str, object]]:
        items: list[dict[str, object]] = []
        seen: set[str] = set()
        for cycle in cycles:
            queue = await svc.review.queue(cycle, now=datetime.now(UTC))
            for item in queue.items:
                if str(item.request_id) in seen:
                    continue
                seen.add(str(item.request_id))
                entry = _correction_item(item)
                entry["cycle"] = _cycle_json(cycle)
                items.append(entry)
        return items

    @endpoint
    async def corrections(
        request: Request, year: int | None = None, month: int | None = None
    ) -> Response:
        svc = _authorize(request, services())
        if year is None and month is None:
            current = _cycle(None, None)
            cycles = (_previous(current), current)
        else:
            cycles = (_cycle(year, month),)
        items = await _queue_items(svc, cycles)
        return JSONResponse(
            {"items": items, "total": len(items)}, headers={"Cache-Control": "no-store"}
        )

    @endpoint
    async def correction(request: Request, request_id: UUID) -> Response:
        svc = _authorize(request, services())
        record = await svc.reads.correction(request_id)
        if record is None:
            raise AdapterError(404, "correction_not_found", "Correction not found")
        if record.status == "pending":
            cycle = payroll_cycle_for(record.work_date)
            for item in await _queue_items(svc, (cycle,)):
                if item["id"] == str(request_id):
                    return JSONResponse(item, headers={"Cache-Control": "no-store"})
        return JSONResponse(
            {
                "id": str(record.id),
                "status": record.status,
                "employee_id": record.employee_id,
                "work_date": record.work_date.isoformat(),
                "resolution_type": record.resolution_type,
                "reviewed_by": record.reviewed_by,
                "reviewed_at": _iso(record.reviewed_at),
                "rejection_reason": record.rejection_reason,
                "reviewable": False,
            },
            headers={"Cache-Control": "no-store"},
        )

    @endpoint
    async def correction_evidence(request: Request, request_id: UUID) -> Response:
        svc = _authorize(request, services())
        evidence = await svc.attendance_review.evidence(request_id)
        if evidence is None:
            raise AdapterError(404, "evidence_not_found", "Evidence not found")
        return Response(
            content=evidence.content,
            media_type=evidence.content_type,
            headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
        )

    @endpoint
    async def decide(request: Request, request_id: UUID) -> Response:
        svc = _authorize(request, services())
        actor = _actor(request)
        key = _key(request)
        body = _model(_DecisionBody, await _json(request))
        if body.decision == "reject" and not (body.reason or "").strip():
            raise AdapterError(422, "rejection_reason_required", "A rejection needs a reason")

        async def run() -> tuple[int, object]:
            record = await svc.reads.correction(request_id)
            if record is None:
                raise AdapterError(404, "correction_not_found", "Correction not found")
            if record.status != "pending":
                return 200, {
                    "status": "skipped",
                    "outcome": "already_resolved",
                    "correction_status": record.status,
                }
            result = await svc.review.bulk_decide(
                payroll_cycle_for(record.work_date),
                now=datetime.now(UTC),
                request_ids=(request_id,),
                decision=PayrollReviewDecision(body.decision),
                reviewer=actor,
                rejection_reason=(body.reason or "").strip() or None,
            )
            item = result.items[0]
            after = await svc.reads.correction(request_id)
            return 200, {
                "status": item.status.value,
                "outcome": item.outcome,
                "correction_status": None if after is None else after.status,
            }

        return await _replay_or_run(
            svc,
            key=key,
            route=f"decision:{request_id}",
            request_hash=_request_hash(body.model_dump()),
            actor=actor,
            run=run,
        )

    # -- BAST ------------------------------------------------------------------
    @endpoint
    async def bast_readiness(request: Request, year: int, month: int, report_type: str) -> Response:
        svc = _authorize(request, services())
        if report_type not in {"developer", "iotoperation"}:
            raise AdapterError(
                422, "invalid_report_type", "report_type must be developer or iotoperation"
            )
        gate = await svc.bast_workflow.readiness(_calendar(year, month), report_type)
        return JSONResponse(
            {
                "report_type": report_type,
                "year": year,
                "month": month,
                "ready": gate.ready,
                "ready_talents": gate.ready_talents,
                "total_talents": gate.total_talents,
                "blockers": [
                    {"nrp": b.nrp, "name": b.name, "domain": b.domain, "issues": list(b.issues)}
                    for b in gate.blockers
                ],
            },
            headers={"Cache-Control": "no-store"},
        )

    def _job_json(job: BastGenerationJob) -> dict[str, object]:
        params = job.parameters
        return {
            "id": str(job.id),
            "status": display_status(job, now=datetime.now(UTC)),
            "report_type": params.get("report_type"),
            "year": params.get("year"),
            "month": params.get("month"),
            "mode": params.get("mode"),
            "forced": params.get("force"),
            "requested_by": params.get("requested_by"),
            "result": job.result,
            "error_code": job.error_code,
            "created_at": _iso(job.created_at),
            "finished_at": _iso(job.finished_at),
        }

    @endpoint
    async def generate_bast(request: Request, background_tasks: BackgroundTasks) -> Response:
        svc = _authorize(request, services())
        actor = _actor(request)
        body = _model(_BastBody, await _json(request))
        period = _calendar(body.year, body.month)
        mode = BastGenerationMode(body.mode)
        gate = await svc.bast_workflow.readiness(period, body.report_type)
        reason = (body.force_reason or "").strip()
        if body.force and not reason:
            raise AdapterError(
                422, "force_reason_required", "force_reason is required when force=true"
            )
        if mode is BastGenerationMode.FINAL and not gate.ready and not body.force:
            return JSONResponse(
                {
                    "error": {
                        "code": "bast_not_ready",
                        "message": f"{gate.ready_talents}/{gate.total_talents} Talent ready",
                        "retryable": False,
                    },
                    "blockers": [
                        {"nrp": b.nrp, "name": b.name, "domain": b.domain, "issues": list(b.issues)}
                        for b in gate.blockers
                    ],
                },
                status_code=409,
            )
        job = await svc.bast_jobs.create(
            report_type=body.report_type,
            year=body.year,
            month=body.month,
            mode=mode.value,
            forced=body.force,
            force_reason=reason or None,
            requested_by=actor,
        )
        background_tasks.add_task(
            execute_bast_generation_job,
            job.id,
            svc.bast_jobs,
            svc.bast_workflow,
            selected_period=period,
            report_type=body.report_type,
            generation_mode=mode,
            forced=body.force,
            normalized_reason=reason or None,
            readiness=gate,
            generated_by=actor,
        )
        return JSONResponse(_job_json(job), status_code=202)

    @endpoint
    async def bast_job(request: Request, job_id: UUID) -> Response:
        svc = _authorize(request, services())
        job = await svc.bast_jobs.get(job_id)
        if job is None:
            raise AdapterError(404, "job_not_found", "Generation job not found")
        return JSONResponse(_job_json(job), headers={"Cache-Control": "no-store"})

    @endpoint
    async def bast_document(request: Request, job_id: UUID) -> Response:
        svc = _authorize(request, services())
        job = await svc.bast_jobs.get(job_id)
        if job is None:
            raise AdapterError(404, "job_not_found", "Generation job not found")
        if job.status != "succeeded" or job.result is None:
            raise AdapterError(
                409, "job_not_succeeded", "The document is not ready", retryable=True
            )
        params = job.parameters
        path = bast_artifact_path(
            str(params["report_type"]),
            int(cast("int", params["year"])),
            int(cast("int", params["month"])),
        )
        if path.name != job.result.get("artifact_name") or not await run_sync(path.exists):
            raise AdapterError(
                410, "document_unavailable", "The generated document is no longer available"
            )
        content = await run_sync(path.read_bytes)
        return Response(
            content=content,
            media_type="application/pdf",
            headers={
                "Cache-Control": "no-store",
                "Content-Disposition": f'attachment; filename="{path.name}"',
                "X-Bast-Fingerprint": str(job.result.get("fingerprint", "")),
            },
        )

    # -- export ----------------------------------------------------------------
    @endpoint
    async def export_attendance(request: Request) -> Response:
        svc = _authorize(request, services())
        actor = _actor(request)
        body = _model(_ExportBody, await _json(request))
        cycle = payroll_cycle(body.year, body.month)
        path, record = await svc.export.export(
            cycle, report_type=body.report_type, exported_by=actor
        )
        content = await run_sync(path.read_bytes)
        rows = max(content.count(b"\n") - 1, 0)
        return Response(
            content=content,
            media_type="text/csv; charset=utf-8",
            headers={
                "Cache-Control": "no-store",
                "Content-Disposition": f'attachment; filename="{path.name}"',
                "X-Export-Id": str(record.export_id),
                "X-Cycle-Id": record.cycle_id,
                "X-Row-Count": str(rows),
            },
        )

    # -- campaigns -------------------------------------------------------------
    async def _campaign_response(
        svc: CeleratesServices, campaign_id: UUID, status: int = 200
    ) -> tuple[int, object]:
        found = await svc.campaign_store.get(campaign_id)
        if found is None:
            raise AdapterError(404, "campaign_not_found", "Campaign not found")
        events = await svc.campaign_store.events(campaign_id)
        return status, _campaign_json(svc, campaign_id, found, events)

    @endpoint
    async def create_campaign(request: Request) -> Response:
        svc = _authorize(request, services())
        actor = _actor(request)
        key = _key(request)
        body = _model(_CampaignBody, await _json(request))

        async def run() -> tuple[int, object]:
            campaign_id = await svc.campaigns.create(
                payroll_cycle(body.year, body.month),
                CampaignPolicy(
                    window_start_hour=body.window_start_hour,
                    window_end_hour=body.window_end_hour,
                    batch_size=body.batch_size,
                    cooldown_seconds=body.cooldown_seconds,
                    min_interval_seconds=body.min_interval_seconds,
                    max_attempts=body.max_attempts,
                ),
                actor=actor,
                now=datetime.now(UTC),
            )
            return await _campaign_response(svc, campaign_id, 201)

        return await _replay_or_run(
            svc,
            key=key,
            route="campaigns",
            request_hash=_request_hash(body.model_dump()),
            actor=actor,
            run=run,
        )

    @endpoint
    async def list_campaigns(request: Request, limit: int = 20) -> Response:
        svc = _authorize(request, services())
        rows = await svc.campaign_store.list_recent(max(1, min(limit, 100)))
        return JSONResponse(
            {
                "items": [
                    {
                        "id": str(campaign.id),
                        "state": campaign.state.value,
                        "cycle": _cycle_json(
                            payroll_cycle(campaign.cycle_year, campaign.cycle_month)
                        ),
                        "created_by": campaign.created_by,
                        "created_at": _iso(campaign.created_at),
                        "approved_by": campaign.approved_by,
                        "pause_reason": campaign.pause_reason,
                        "counts": counts,
                    }
                    for campaign, counts in rows
                ]
            },
            headers={"Cache-Control": "no-store"},
        )

    @endpoint
    async def get_campaign(request: Request, campaign_id: UUID) -> Response:
        svc = _authorize(request, services())
        status, body = await _campaign_response(svc, campaign_id)
        return JSONResponse(body, status_code=status, headers={"Cache-Control": "no-store"})

    @endpoint
    async def approve_campaign(request: Request, campaign_id: UUID) -> Response:
        svc = _authorize(request, services())
        actor = _actor(request)
        key = _key(request)
        body = _model(_ApproveBody, await _json(request))

        async def run() -> tuple[int, object]:
            await svc.campaigns.approve(
                campaign_id,
                tuple(
                    CampaignLink(item.employee_id, item.url, item.expires_at.astimezone(UTC))
                    for item in body.links
                ),
                actor=actor,
                now=datetime.now(UTC),
            )
            return await _campaign_response(svc, campaign_id)

        return await _replay_or_run(
            svc,
            key=key,
            route=f"approve:{campaign_id}",
            request_hash=_request_hash(body.model_dump()),
            actor=actor,
            run=run,
        )

    def _control_endpoint(
        action: Literal["pause", "resume", "stop"],
    ) -> Callable[..., Awaitable[Response]]:
        @endpoint
        async def control(request: Request, campaign_id: UUID) -> Response:
            svc = _authorize(request, services())
            actor = _actor(request)
            key = _key(request)
            payload = await _json(request) if await request.body() else {}
            body = _model(_PauseBody, payload)

            async def run() -> tuple[int, object]:
                now = datetime.now(UTC)
                if action == "pause":
                    await svc.campaigns.pause(campaign_id, actor=actor, reason=body.reason)
                elif action == "resume":
                    await svc.campaigns.resume(campaign_id, actor=actor, now=now)
                else:
                    await svc.campaigns.stop(campaign_id, actor=actor, now=now)
                return await _campaign_response(svc, campaign_id)

            return await _replay_or_run(
                svc,
                key=key,
                route=f"{action}:{campaign_id}",
                request_hash=_request_hash(body.model_dump()),
                actor=actor,
                run=run,
            )

        control.__name__ = f"{action}_campaign"
        return control

    @endpoint
    async def dispatch(request: Request) -> Response:
        svc = _authorize(request, services())
        report = await svc.campaigns.dispatch(now=lambda: datetime.now(UTC))
        return JSONResponse(
            {
                "killed": report.killed,
                "campaigns": [
                    {
                        "id": str(tick.campaign_id),
                        "state": tick.state.value,
                        "sent": tick.sent,
                        "skipped": tick.skipped,
                        "failed": tick.failed,
                        "pause_reason": tick.pause_reason,
                    }
                    for tick in report.campaigns
                ],
            }
        )

    @endpoint
    async def get_control(request: Request) -> Response:
        svc = _authorize(request, services())
        kill_switch, updated_by, updated_at = await svc.control.get()
        return JSONResponse(
            {"kill_switch": kill_switch, "updated_by": updated_by, "updated_at": _iso(updated_at)}
        )

    @endpoint
    async def put_control(request: Request) -> Response:
        svc = _authorize(request, services())
        actor = _actor(request)
        _ = _key(request)
        body = _model(_ControlBody, await _json(request))
        await svc.control.set(kill_switch=body.kill_switch, actor=actor)
        kill_switch, updated_by, updated_at = await svc.control.get()
        return JSONResponse(
            {"kill_switch": kill_switch, "updated_by": updated_by, "updated_at": _iso(updated_at)}
        )

    # -- PMO group summary -----------------------------------------------------
    @endpoint
    async def summary_preview(request: Request, year: int, month: int, link: str) -> Response:
        svc = _authorize(request, services())
        cycle = _cycle(year, month)
        overview = await _overview(svc, cycle)
        queue = await svc.review.queue(cycle, now=datetime.now(UTC))
        return JSONResponse(
            {
                "text": compose_pmo_summary(overview, queue.summary.total, link),
                "group_configured": (await svc.group_jid_reader()) is not None,
            }
        )

    @endpoint
    async def summary_send(request: Request) -> Response:
        svc = _authorize(request, services())
        actor = _actor(request)
        key = _key(request)
        body = _model(_SummaryBody, await _json(request))
        if svc.public_url and not body.link.startswith(svc.public_url):
            raise AdapterError(422, "link_not_allowed", "Link is outside the Celerates public URL")

        async def run() -> tuple[int, object]:
            kill_switch, _, _ = await svc.control.get()
            if kill_switch:
                raise AdapterError(409, "kill_switch_on", "Sending is stopped by the kill switch")
            group = await svc.group_jid_reader()
            if group is None:
                raise AdapterError(
                    409, "group_not_configured", "PMO closing group is not configured"
                )
            cycle = _cycle(body.year, body.month)
            today = datetime.now(JAKARTA).date().isoformat()
            dedupe = f"{cycle.cycle_id}:{today}"
            if await svc.summaries.state(dedupe) == "sent":
                return 200, {"status": "duplicate"}
            overview = await _overview(svc, cycle)
            queue = await svc.review.queue(cycle, now=datetime.now(UTC))
            text = compose_pmo_summary(overview, queue.summary.total, body.link)
            receipt = await svc.outbound.send_group(group, text, f"celerates-pmo-summary:{dedupe}")
            state = "sent" if receipt.status == "sent" else "failed"
            await svc.summaries.record(
                dedupe,
                cycle.cycle_id,
                state,
                actor,
                receipt.provider_message_id,
                receipt.error_code,
            )
            return 200, {"status": state, "error": receipt.error_code}

        return await _replay_or_run(
            svc,
            key=key,
            route="pmo-summary",
            request_hash=_request_hash(body.model_dump()),
            actor=actor,
            run=run,
        )

    routes: tuple[tuple[str, Callable[..., Awaitable[Response]], str], ...] = (
        ("/meta", meta, "GET"),
        ("/readiness", readiness, "GET"),
        ("/talents/lookup", lookup, "GET"),
        ("/talents/requirements", requirements, "GET"),
        ("/talents/attendance-corrections", submit_correction, "POST"),
        ("/attendance-corrections", corrections, "GET"),
        ("/attendance-corrections/{request_id}", correction, "GET"),
        ("/attendance-corrections/{request_id}/evidence", correction_evidence, "GET"),
        ("/attendance-corrections/{request_id}/decision", decide, "POST"),
        ("/bast/readiness", bast_readiness, "GET"),
        ("/bast/generations", generate_bast, "POST"),
        ("/bast/generations/{job_id}", bast_job, "GET"),
        ("/bast/generations/{job_id}/document", bast_document, "GET"),
        ("/exports/attendance", export_attendance, "POST"),
        ("/campaigns", create_campaign, "POST"),
        ("/campaigns", list_campaigns, "GET"),
        ("/campaigns/dispatch", dispatch, "POST"),
        ("/campaigns/{campaign_id}", get_campaign, "GET"),
        ("/campaigns/{campaign_id}/approve", approve_campaign, "POST"),
        ("/campaigns/{campaign_id}/pause", _control_endpoint("pause"), "POST"),
        ("/campaigns/{campaign_id}/resume", _control_endpoint("resume"), "POST"),
        ("/campaigns/{campaign_id}/stop", _control_endpoint("stop"), "POST"),
        ("/control", get_control, "GET"),
        ("/control", put_control, "PUT"),
        ("/pmo-summary/preview", summary_preview, "GET"),
        ("/pmo-summary/send", summary_send, "POST"),
    )
    for path, handler, method in routes:
        router.add_api_route(path, handler, methods=[method], include_in_schema=False)
    return router
