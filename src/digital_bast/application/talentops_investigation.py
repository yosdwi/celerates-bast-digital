from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

from digital_bast.application.operational_signals import (
    command_center_signals,
    talent_signals,
)

if TYPE_CHECKING:
    from datetime import date

    from digital_bast.application.operational_signals import OperationalSignal
    from digital_bast.application.talentops import CommandCenterView, TalentDetailView


@dataclass(frozen=True, slots=True)
class InvestigationEvidence:
    id: str
    kind: str
    label: str
    detail: str
    domains: tuple[str, ...] = ()
    work_date: date | None = None
    task_title: str | None = None
    nrp: str | None = None


@dataclass(frozen=True, slots=True)
class TalentOpsInvestigation:
    title: str
    finding: str
    impact: str | None
    suggested_action: str | None
    evidence: tuple[InvestigationEvidence, ...]


def _signal_evidence(
    prefix: str,
    signals: tuple[OperationalSignal, ...],
) -> list[InvestigationEvidence]:
    result: list[InvestigationEvidence] = []
    for index, signal in enumerate(signals):
        result.append(
            InvestigationEvidence(
                id=f"{prefix}:{index}",
                kind="signal",
                label=signal.title,
                detail=signal.summary,
                domains=signal.domains,
                work_date=signal.dates[0] if len(signal.dates) == 1 else None,
                task_title=signal.task_titles[0] if len(signal.task_titles) == 1 else None,
                nrp=signal.nrp,
            )
        )
    return result


def command_center_evidence(view: CommandCenterView) -> tuple[InvestigationEvidence, ...]:
    signals = command_center_signals(view.attention, view.teams)
    evidence = _signal_evidence("signal", signals)
    evidence.append(
        InvestigationEvidence(
            id="summary:period",
            kind="summary",
            label="Command Center summary",
            detail=(
                f"{view.summary.bast_ready}/{view.summary.active_talents} BAST ready; "
                f"{view.summary.need_attention} need attention; "
                f"{view.summary.open_tasks} open tasks; "
                f"{view.summary.evidence_ready}/{view.summary.active_talents} evidence ready."
            ),
        )
    )
    for item in view.attention[:12]:
        for blocker in item.blockers:
            detail = "; ".join(blocker.issues[:4]) or f"State: {blocker.state.value}"
            evidence.append(
                InvestigationEvidence(
                    id=f"blocker:{item.nrp}:{blocker.domain}",
                    kind="blocker",
                    label=f"{item.name} · {blocker.domain}",
                    detail=detail,
                    domains=(blocker.domain,),
                    nrp=item.nrp,
                )
            )
    for source in view.sources:
        if source.last_success_at is None:
            detail = "No successful ingest observed."
        else:
            detail = (
                f"Last successful ingest: {source.last_success_at.isoformat()}; "
                f"observed age: {source.age_seconds} seconds."
            )
        evidence.append(
            InvestigationEvidence(
                id=f"source:{source.source_key}",
                kind="source",
                label=source.label,
                detail=detail,
            )
        )
    return tuple(evidence)


def talent_evidence(view: TalentDetailView) -> tuple[InvestigationEvidence, ...]:
    signals = talent_signals(
        view.nrp,
        view.blockers,
        view.timesheet_days,
        view.tasks,
    )
    evidence = _signal_evidence("signal", signals)
    evidence.append(
        InvestigationEvidence(
            id="summary:talent",
            kind="summary",
            label=f"{view.name} readiness summary",
            detail=(
                f"overall={view.overall_state.value}; "
                f"attendance={view.checks.attendance.state.value}; "
                f"timesheet={view.checks.timesheet.state.value}; "
                f"task={view.checks.task.state.value}; "
                f"evidence={view.checks.evidence.state.value}."
            ),
            nrp=view.nrp,
        )
    )

    for blocker in view.blockers:
        detail = "; ".join(blocker.issues[:6]) or f"State: {blocker.state.value}"
        evidence.append(
            InvestigationEvidence(
                id=f"blocker:{blocker.domain}",
                kind="blocker",
                label=f"{blocker.domain} readiness blocker",
                detail=detail,
                domains=(blocker.domain,),
                nrp=view.nrp,
            )
        )

    for day in view.attendance_days:
        if day.is_off or day.state.value == "complete":
            continue
        evidence.append(
            InvestigationEvidence(
                id=f"attendance:{day.work_date.isoformat()}",
                kind="attendance",
                label=f"Attendance · {day.work_date.isoformat()}",
                detail=(
                    f"state={day.state.value}; record={day.has_record}; "
                    f"clock_in={day.has_clock_in}; clock_out={day.has_clock_out}; "
                    f"evidence={day.has_evidence}."
                ),
                domains=("attendance",),
                work_date=day.work_date,
                nrp=view.nrp,
            )
        )

    for day in view.timesheet_days:
        if day.state.value == "complete":
            continue
        evidence.append(
            InvestigationEvidence(
                id=f"timesheet:{day.work_date.isoformat()}",
                kind="timesheet",
                label=f"Timesheet · {day.work_date.isoformat()}",
                detail=(
                    f"state={day.state.value}; record={day.has_record}; "
                    f"remarks={day.has_remarks}; off={day.is_off}; "
                    f"blocked_by_attendance={day.blocked_by_attendance}."
                ),
                domains=("timesheet",),
                work_date=day.work_date,
                nrp=view.nrp,
            )
        )

    for index, task in enumerate(view.tasks[:20]):
        if not task.is_closed or task.evidence_ready is not False:
            continue
        evidence.append(
            InvestigationEvidence(
                id=f"task:{index}",
                kind="task",
                label=f"Closed task · {task.title}",
                detail=(
                    f"work_date={task.work_date.isoformat()}; status={task.status}; "
                    f"evidence_count={task.evidence_count}; evidence_ready=false."
                ),
                domains=("task", "evidence"),
                work_date=task.work_date,
                task_title=task.title,
                nrp=view.nrp,
            )
        )
    return tuple(evidence)


def evidence_catalog(evidence: tuple[InvestigationEvidence, ...]) -> str:
    payload = [
        {
            "id": item.id,
            "kind": item.kind,
            "label": item.label,
            "detail": item.detail,
            "domains": list(item.domains),
            "work_date": item.work_date.isoformat() if item.work_date is not None else None,
            "task_title": item.task_title,
            "nrp": item.nrp,
        }
        for item in evidence
    ]
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def parse_investigation(
    raw: str,
    evidence: tuple[InvestigationEvidence, ...],
) -> TalentOpsInvestigation | None:
    payload = _decode_payload(raw)
    if payload is None:
        return None

    title = _clean_text(payload.get("title"), 160)
    finding = _clean_text(payload.get("finding"), 800)
    if title is None or finding is None:
        return None

    selected = _select_evidence(payload.get("evidence_ids"), evidence)
    if selected is None:
        return None

    return TalentOpsInvestigation(
        title=title,
        finding=finding,
        impact=_clean_text(payload.get("impact"), 500),
        suggested_action=_clean_text(payload.get("suggested_action"), 500),
        evidence=selected,
    )


def _decode_payload(raw: str) -> dict[str, object] | None:
    try:
        decoded = cast("object", json.loads(_strip_code_fence(raw)))
    except json.JSONDecodeError:
        return None
    if not isinstance(decoded, dict):
        return None
    return cast("dict[str, object]", decoded)


def _strip_code_fence(raw: str) -> str:
    value = raw.strip()
    if not value.startswith("```"):
        return value

    lines = value.splitlines()[1:]
    if lines and lines[-1].strip() == "```":
        lines = lines[:-1]
    return "\n".join(lines).strip()


def _select_evidence(
    raw_ids: object,
    evidence: tuple[InvestigationEvidence, ...],
) -> tuple[InvestigationEvidence, ...] | None:
    if not isinstance(raw_ids, list):
        return None

    candidate_ids = cast("list[object]", raw_ids)
    by_id = {item.id: item for item in evidence}
    selected: list[InvestigationEvidence] = []
    seen: set[str] = set()
    for raw_id in candidate_ids[:8]:
        if not isinstance(raw_id, str) or raw_id in seen:
            continue
        item = by_id.get(raw_id)
        if item is None:
            continue
        selected.append(item)
        seen.add(raw_id)

    if evidence and not selected:
        return None
    return tuple(selected)


def _clean_text(value: object, limit: int) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = " ".join(value.split()).strip()
    if not cleaned:
        return None
    return cleaned[:limit]
