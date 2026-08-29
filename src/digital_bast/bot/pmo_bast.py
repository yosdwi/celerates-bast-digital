"""PMO WhatsApp BAST readiness and generation workflow.

The DM surface uses the same deterministic readiness rules and generation audit
as TalentOps Web. A generated file is returned only to the requesting PMO DM;
this module deliberately has no group-distribution action.
"""

from __future__ import annotations

import json
from collections import Counter
from datetime import datetime
from typing import TYPE_CHECKING, Final

from digital_bast.application.bast_workflow import BastGenerationMode, BastWorkflowService
from digital_bast.bot.interactive import interactive
from digital_bast.domain.completion import DateRange
from digital_bast.domain.time import JAKARTA, month_dates
from digital_bast.operations import generate_bast as generate_bast_artifact

if TYPE_CHECKING:
    from digital_bast.application.bast_workflow import BastReadiness
    from digital_bast.application.workflow_control import WorkflowOperator

_REPORT_LABELS: Final = {
    "developer": "Developer",
    "iotoperation": "IoT Operations",
}
_FORCE_REASON: Final = "Confirmed via PMO WhatsApp after readiness warning"


def _period_now() -> DateRange:
    local = datetime.now(JAKARTA)
    dates = month_dates(local.year, local.month)
    return DateRange(dates[0], dates[-1])


def _bast_service() -> BastWorkflowService:
    # Keep production wiring lazy so ordinary Talent/PMO DM messages do not
    # import the heavier TalentOps persistence stack unless BAST is opened.
    from pydantic import ValidationError  # noqa: PLC0415

    from digital_bast.application.talentops import TalentOpsService  # noqa: PLC0415
    from digital_bast.config import SettingsConfigurationError, get_settings  # noqa: PLC0415
    from digital_bast.infrastructure.completion_source import CompletionSource  # noqa: PLC0415
    from digital_bast.infrastructure.local_completion_source import (  # noqa: PLC0415
        PostgresAttendanceFactReader,
        PostgresTaskEvidenceReader,
    )
    from digital_bast.infrastructure.postgres_employees import (  # noqa: PLC0415
        PostgresEmployeeSource,
    )
    from digital_bast.infrastructure.repositories import (  # noqa: PLC0415
        PostgresDomainRepository,
    )
    from digital_bast.infrastructure.source_sync_state import (  # noqa: PLC0415
        PostgresSourceSyncStateStore,
    )
    from digital_bast.operations import OperationConfigurationError  # noqa: PLC0415

    try:
        settings = get_settings()
    except (ValidationError, SettingsConfigurationError, OSError) as error:
        raise OperationConfigurationError("application settings are invalid") from error
    if settings.database_dsn is None:
        raise OperationConfigurationError("APP_DATABASE_DSN")
    dsn = settings.database_dsn.get_secret_value()
    employees = PostgresEmployeeSource(dsn)
    records = PostgresDomainRepository(dsn)
    completion = CompletionSource(
        employees,
        records,
        PostgresAttendanceFactReader(dsn),
        PostgresTaskEvidenceReader(dsn),
    )
    talentops = TalentOpsService(
        completion,
        employees,
        records,
        PostgresSourceSyncStateStore(dsn),
    )
    return BastWorkflowService(dsn, talentops)


def _team_menu() -> str:
    return interactive(
        "*BAST — pilih tim*\nStatus dan generation memakai readiness yang sama dengan TalentOps Web.",
        ("pmo:bast:developer", "Developer"),
        ("pmo:bast:iotoperation", "IoT Operations"),
        ("pmo:menu", "Kembali"),
        footer="File generation dikirim ke DM ini saja",
    )


def _status_text(readiness: BastReadiness, period: DateRange) -> str:
    label = _REPORT_LABELS[readiness.report_type]
    lines = [
        f"*BAST {label} — {period.label()}*",
        "",
        f"Talent Ready : {readiness.ready_talents} / {readiness.total_talents}",
        f"Status       : {'READY ✅' if readiness.ready else 'BELUM READY ⚠️'}",
    ]
    if readiness.blockers:
        counts = Counter(item.domain for item in readiness.blockers)
        lines.extend(("", "Masih ada:"))
        labels = {
            "attendance": "Attendance",
            "timesheet": "Timesheet",
            "task": "Task",
            "evidence": "Evidence",
        }
        for domain in ("attendance", "timesheet", "task", "evidence"):
            count = counts.get(domain, 0)
            if count:
                lines.append(f"• {count} {labels[domain]} blocker")
        other_count = sum(
            count for domain, count in counts.items() if domain not in labels
        )
        if other_count:
            lines.append(f"• {other_count} blocker lain")
    return "\n".join(lines)


async def _status(operator: WorkflowOperator, report_type: str) -> str:
    period = _period_now()
    readiness = await _bast_service().readiness(period, report_type)
    actions: list[tuple[str, str]] = []
    if operator.can_generate_bast:
        actions.append((f"pmo:bast:{report_type}:preview", "Preview PDF"))
        if readiness.ready:
            actions.append((f"pmo:bast:{report_type}:generate", "Generate Final"))
        else:
            actions.append((f"pmo:bast:{report_type}:force", "Generate Anyway"))
    actions.append(("pmo:bast", "Kembali"))
    return interactive(
        _status_text(readiness, period),
        *actions,
        footer=(
            "Preview selalu mengikuti raw/current data; Final dicatat di generation audit"
            if operator.can_generate_bast
            else "Akun ini hanya dapat melihat status BAST"
        ),
    )


async def _force_confirmation(operator: WorkflowOperator, report_type: str) -> str:
    if not operator.can_generate_bast:
        return "Akun PMO ini tidak punya permission generate BAST."
    period = _period_now()
    readiness = await _bast_service().readiness(period, report_type)
    if readiness.ready:
        return await _status(operator, report_type)
    text = (
        f"{_status_text(readiness, period)}\n\n"
        "BAST belum sepenuhnya ready. Tetap generate Final dengan kondisi saat ini?"
    )
    return interactive(
        text,
        (f"pmo:bast:{report_type}:confirm-force", "Ya, Generate"),
        (f"pmo:bast:{report_type}", "Kembali"),
        footer="Konfirmasi ini dicatat bersama snapshot blocker",
    )


async def _generate(
    operator: WorkflowOperator,
    report_type: str,
    mode: BastGenerationMode,
    *,
    force: bool = False,
) -> str:
    if not operator.can_generate_bast:
        return "Akun PMO ini tidak punya permission generate BAST."
    period = _period_now()
    workflow = _bast_service()
    readiness = await workflow.readiness(period, report_type)
    if mode is BastGenerationMode.FINAL and not readiness.ready and not force:
        return await _status(operator, report_type)

    forced = mode is BastGenerationMode.FINAL and force and not readiness.ready
    path, report = await generate_bast_artifact(period, report_type)
    await workflow.record_generation(
        report_type=report_type,
        period=period,
        mode=mode,
        forced=forced,
        force_reason=_FORCE_REASON if forced else None,
        readiness=readiness,
        generated_by=operator.email,
        artifact_name=path.name,
        fingerprint=report.fingerprint,
    )
    label = _REPORT_LABELS[report_type]
    mode_label = "Preview" if mode is BastGenerationMode.PREVIEW else "Final"
    forced_label = " · Force Generate" if forced else ""
    return json.dumps(
        {
            "kind": "file",
            "path": str(path),
            "filename": path.name,
            "caption": (
                f"✅ BAST {label} {period.label()} — {mode_label}{forced_label}\n"
                f"Readiness: {readiness.ready_talents}/{readiness.total_talents} talent ready.\n"
                "Kirim `bast` untuk kembali ke menu BAST."
            ),
        },
        ensure_ascii=False,
    )


def _report_type_from_text(lowered: str) -> str | None:
    if "iot" in lowered or "shifting" in lowered:
        return "iotoperation"
    if "developer" in lowered or "dev" in lowered:
        return "developer"
    return None


async def reply(operator: WorkflowOperator, text: str) -> str:  # noqa: PLR0911
    """Handle only the PMO BAST sub-flow; caller owns the top-level PMO menu."""
    normalized = text.strip()
    lowered = normalized.casefold()
    if lowered in {"bast", "status bast", "generate bast", "pmo:bast"}:
        return _team_menu()

    parts = lowered.split(":")
    if len(parts) >= 3 and parts[0] == "pmo" and parts[1] == "bast":
        report_type = parts[2]
        if report_type not in _REPORT_LABELS:
            return _team_menu()
        if len(parts) == 3:
            return await _status(operator, report_type)
        if len(parts) == 4:
            action = parts[3]
            if action == "preview":
                return await _generate(operator, report_type, BastGenerationMode.PREVIEW)
            if action == "generate":
                return await _generate(operator, report_type, BastGenerationMode.FINAL)
            if action == "force":
                return await _force_confirmation(operator, report_type)
            if action == "confirm-force":
                return await _generate(
                    operator,
                    report_type,
                    BastGenerationMode.FINAL,
                    force=True,
                )

    if "bast" in lowered:
        report_type = _report_type_from_text(lowered)
        if report_type is None:
            return _team_menu()
        if "preview" in lowered:
            return await _generate(operator, report_type, BastGenerationMode.PREVIEW)
        if "generate" in lowered and "force" in lowered:
            return await _force_confirmation(operator, report_type)
        return await _status(operator, report_type)
    return _team_menu()
