from __future__ import annotations

import json
from typing import TYPE_CHECKING, Protocol, final

from digital_bast.application.operational_signals import (
    OperationalSignal,
    command_center_signals,
    talent_signals,
)
from digital_bast.application.talentops_investigation import (
    InvestigationEvidence,
    TalentOpsInvestigation,
    command_center_evidence,
    evidence_catalog,
    parse_investigation,
    talent_evidence,
)

if TYPE_CHECKING:
    from digital_bast.application.talentops import CommandCenterView, TalentDetailView


class TalentOpsChatClient(Protocol):
    async def complete(self, system_prompt: str, user_prompt: str) -> str | None: ...


_INVESTIGATION_SYSTEM_PROMPT = """Kamu adalah investigation assistant untuk PMO TalentOps.
Gunakan hanya fakta aplikasi, operational signals, dan evidence catalog yang diberikan.
Operational signals adalah relasi deterministik yang dihitung aplikasi. Status readiness tetap
ditentukan aplikasi, bukan AI.

Jangan mengarang angka, status, prioritas, penyebab, performa, utilisasi, kapasitas, SLA,
deadline, atau hubungan sebab-akibat yang tidak didukung fakta/signal. Jika ada dependency
explicit seperti attendance_blocks_timesheet, kamu boleh menyarankan urutan verifikasi sesuai
dependency tersebut. Jangan hanya membacakan ulang KPI.

Kembalikan HANYA satu JSON object valid tanpa markdown dengan schema berikut:
{
  "title": "...",
  "finding": "...",
  "impact": "... atau null",
  "suggested_action": "... atau null",
  "evidence_ids": ["id-dari-catalog"]
}

Aturan evidence:
- evidence_ids hanya boleh berisi ID yang benar-benar ada di evidence catalog.
- pilih evidence paling relevan, maksimal 8 ID.
- semua klaim faktual utama dalam finding/impact/action harus dapat ditelusuri ke evidence
  yang dipilih.
- jangan menulis evidence baru di luar catalog.
Gunakan bahasa pertanyaan user jika jelas. Ringkas dan operasional."""

_FOLLOW_UP_SYSTEM_PROMPT = """Kamu membantu PMO menulis satu pesan follow-up WhatsApp ke talent.
Gunakan HANYA fakta JSON dan operational_signals yang diberikan aplikasi.
Jangan mengarang blocker, tanggal, status, SLA, deadline, performa, atau penyebab.
Jangan mengatakan pesan sudah dikirim.
Tulis hanya isi pesan yang siap direview PMO, tanpa judul, tanpa markdown table.
Nada profesional, natural, singkat, dan actionable dalam Bahasa Indonesia."""


def _signal_context(signal: OperationalSignal) -> dict[str, object]:
    return {
        "kind": signal.kind.value,
        "title": signal.title,
        "summary": signal.summary,
        "domains": list(signal.domains),
        "dates": [item.isoformat() for item in signal.dates],
        "task_titles": list(signal.task_titles),
        "nrp": signal.nrp,
        "role": signal.role.value if signal.role is not None else None,
    }


def _command_center_context(view: CommandCenterView) -> str:
    signals = command_center_signals(view.attention, view.teams)
    payload = {
        "period": {
            "label": view.period.label,
            "start": view.period.start,
            "end": view.period.end,
        },
        "summary": {
            "active_talents": view.summary.active_talents,
            "bast_ready": view.summary.bast_ready,
            "need_attention": view.summary.need_attention,
            "open_tasks": view.summary.open_tasks,
            "evidence_ready": view.summary.evidence_ready,
        },
        "operational_signals": [_signal_context(signal) for signal in signals],
        "attention": [
            {
                "name": item.name,
                "nrp": item.nrp,
                "role": item.role.value,
                "overall_state": item.overall_state.value,
                "blockers": [
                    {
                        "domain": blocker.domain,
                        "state": blocker.state.value,
                        "issues": list(blocker.issues[:4]),
                    }
                    for blocker in item.blockers
                ],
            }
            for item in view.attention[:12]
        ],
        "teams": [
            {
                "role": team.role.value,
                "total": team.total,
                "ready": team.ready,
                "attendance_ready": team.checks.attendance_ready,
                "timesheet_ready": team.checks.timesheet_ready,
                "task_ready": team.checks.task_ready,
                "evidence_ready": team.checks.evidence_ready,
            }
            for team in view.teams
        ],
        "delivery": {
            "total_tasks": view.delivery.total_tasks,
            "closed_tasks": view.delivery.closed_tasks,
            "non_closed_tasks": view.delivery.non_closed_tasks,
            "status_counts": [
                {"status": item.status, "count": item.count}
                for item in view.delivery.status_counts
            ],
        },
        "sources": [
            {
                "source": item.label,
                "last_success_at": (
                    item.last_success_at.isoformat()
                    if item.last_success_at is not None
                    else None
                ),
                "age_seconds": item.age_seconds,
            }
            for item in view.sources
        ],
    }
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def _talent_context(view: TalentDetailView) -> str:
    signals = talent_signals(
        view.nrp,
        view.blockers,
        view.timesheet_days,
        view.tasks,
    )
    payload = {
        "period": {
            "label": view.period.label,
            "start": view.period.start,
            "end": view.period.end,
        },
        "talent": {
            "nrp": view.nrp,
            "name": view.name,
            "role": view.role.value,
            "overall_state": view.overall_state.value,
        },
        "checks": {
            "attendance": {
                "state": view.checks.attendance.state.value,
                "issue_count": view.checks.attendance.issue_count,
            },
            "timesheet": {
                "state": view.checks.timesheet.state.value,
                "issue_count": view.checks.timesheet.issue_count,
            },
            "task": {
                "state": view.checks.task.state.value,
                "issue_count": view.checks.task.issue_count,
            },
            "evidence": {
                "state": view.checks.evidence.state.value,
                "issue_count": view.checks.evidence.issue_count,
            },
        },
        "operational_signals": [_signal_context(signal) for signal in signals],
        "blockers": [
            {
                "domain": blocker.domain,
                "state": blocker.state.value,
                "issues": list(blocker.issues[:8]),
            }
            for blocker in view.blockers
        ],
        "attendance_issue_days": [
            {
                "work_date": day.work_date.isoformat(),
                "state": day.state.value,
                "has_record": day.has_record,
                "has_clock_in": day.has_clock_in,
                "has_clock_out": day.has_clock_out,
                "has_evidence": day.has_evidence,
            }
            for day in view.attendance_days
            if not day.is_off and day.state.value != "complete"
        ],
        "timesheet_issue_days": [
            {
                "work_date": day.work_date.isoformat(),
                "state": day.state.value,
                "has_record": day.has_record,
                "has_remarks": day.has_remarks,
                "blocked_by_attendance": day.blocked_by_attendance,
                "is_off": day.is_off,
            }
            for day in view.timesheet_days
            if day.state.value != "complete"
        ],
        "tasks": [
            {
                "work_date": task.work_date.isoformat(),
                "title": task.title,
                "status": task.status,
                "evidence_count": task.evidence_count,
                "evidence_ready": task.evidence_ready,
            }
            for task in view.tasks[:20]
        ],
        "availability": {
            "attendance": view.availability.attendance,
            "evidence": view.availability.evidence,
        },
    }
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


async def _investigate(
    client: TalentOpsChatClient,
    question: str,
    context: str,
    evidence: tuple[InvestigationEvidence, ...],
) -> TalentOpsInvestigation | None:
    user_prompt = (
        f"Pertanyaan PMO: {question.strip()}\n"
        f"Fakta aplikasi: {context}\n"
        f"Evidence catalog: {evidence_catalog(evidence)}"
    )
    raw = await client.complete(_INVESTIGATION_SYSTEM_PROMPT, user_prompt)
    if raw is None:
        return None
    return parse_investigation(raw, evidence)


@final
class TalentOpsAiService:
    def __init__(self, client: TalentOpsChatClient) -> None:
        self._client = client

    async def answer(
        self,
        question: str,
        view: CommandCenterView,
    ) -> TalentOpsInvestigation | None:
        return await _investigate(
            self._client,
            question,
            _command_center_context(view),
            command_center_evidence(view),
        )

    async def answer_talent(
        self,
        question: str,
        view: TalentDetailView,
    ) -> TalentOpsInvestigation | None:
        return await _investigate(
            self._client,
            question,
            _talent_context(view),
            talent_evidence(view),
        )

    async def draft_follow_up(self, view: TalentDetailView) -> str | None:
        user_prompt = (
            "Buat pesan follow-up untuk talent berdasarkan blocker readiness dan operational "
            "signals yang masih aktif. Jika tidak ada blocker, katakan pada PMO bahwa tidak ada "
            "follow-up yang perlu dibuat.\n"
            f"Fakta aplikasi: {_talent_context(view)}"
        )
        return await self._client.complete(_FOLLOW_UP_SYSTEM_PROMPT, user_prompt)
