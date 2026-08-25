from __future__ import annotations

import json
from typing import TYPE_CHECKING, Protocol, final

if TYPE_CHECKING:
    from digital_bast.application.talentops import CommandCenterView, TalentDetailView


class TalentOpsChatClient(Protocol):
    async def complete(self, system_prompt: str, user_prompt: str) -> str | None: ...


_SYSTEM_PROMPT = """Kamu adalah asisten analitik PMO TalentOps.
Jawab hanya berdasarkan fakta JSON yang diberikan aplikasi.
Jangan mengarang angka, status, prioritas, penyebab, performa, utilisasi, kapasitas,
atau informasi yang tidak ada di fakta.
Status readiness ditentukan aplikasi; kamu hanya menjelaskan.
Jika fakta tidak cukup, katakan data yang tersedia belum cukup.
Jawab ringkas dan operasional. Gunakan bahasa pertanyaan user jika jelas."""

_FOLLOW_UP_SYSTEM_PROMPT = """Kamu membantu PMO menulis satu pesan follow-up WhatsApp ke talent.
Gunakan HANYA fakta JSON yang diberikan aplikasi.
Jangan mengarang blocker, tanggal, status, SLA, deadline, performa, atau penyebab.
Jangan mengatakan pesan sudah dikirim.
Tulis hanya isi pesan yang siap direview PMO, tanpa judul, tanpa markdown table.
Nada profesional, natural, singkat, dan actionable dalam Bahasa Indonesia."""


def _command_center_context(view: CommandCenterView) -> str:
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
        "blockers": [
            {
                "domain": blocker.domain,
                "state": blocker.state.value,
                "issues": list(blocker.issues[:8]),
            }
            for blocker in view.blockers
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


@final
class TalentOpsAiService:
    def __init__(self, client: TalentOpsChatClient) -> None:
        self._client = client

    async def answer(
        self,
        question: str,
        view: CommandCenterView,
    ) -> str | None:
        user_prompt = (
            f"Pertanyaan PMO: {question.strip()}\n"
            f"Fakta aplikasi: {_command_center_context(view)}"
        )
        return await self._client.complete(_SYSTEM_PROMPT, user_prompt)

    async def answer_talent(
        self,
        question: str,
        view: TalentDetailView,
    ) -> str | None:
        user_prompt = (
            f"Pertanyaan PMO tentang talent ini: {question.strip()}\n"
            f"Fakta aplikasi: {_talent_context(view)}"
        )
        return await self._client.complete(_SYSTEM_PROMPT, user_prompt)

    async def draft_follow_up(self, view: TalentDetailView) -> str | None:
        user_prompt = (
            "Buat pesan follow-up untuk talent berdasarkan blocker readiness yang masih aktif. "
            "Jika tidak ada blocker, katakan pada PMO bahwa tidak ada follow-up yang perlu dibuat.\n"
            f"Fakta aplikasi: {_talent_context(view)}"
        )
        return await self._client.complete(_FOLLOW_UP_SYSTEM_PROMPT, user_prompt)
