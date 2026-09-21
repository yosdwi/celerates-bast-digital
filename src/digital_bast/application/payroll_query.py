"""Grounded PMO query service for Payroll closing facts."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal, Protocol, final

if TYPE_CHECKING:
    from datetime import datetime

    from digital_bast.application.attendance_closing_policy import PayrollCycle
    from digital_bast.application.payroll_digest import PayrollClosingDigest
    from digital_bast.application.talentops_ai import TalentOpsChatClient

_QUERY_SYSTEM_PROMPT = """Kamu adalah asisten PMO untuk Payroll Attendance Closing.
Jawab HANYA dari fakta JSON yang diberikan aplikasi. Fakta aplikasi adalah authority untuk
cycle, status closing, jumlah actionable/waiting/complete, status reminder, response,
delivery UNKNOWN, dan reason follow-up.

Dilarang mengarang status, nama Talent, jumlah, alasan, approval, delivery, response, SLA,
deadline, readiness, atau kesimpulan yang tidak ada di fakta. Jangan mengubah arti UNKNOWN
menjadi gagal/terkirim. UNRESPONDED hanya berarti aplikasi punya reminder SENT yang belum
punya attendance-action response terkorrelasi; jangan menyamakannya dengan chat biasa.
Jika pertanyaan meminta data yang tidak ada, katakan fakta itu tidak tersedia.
Jawab ringkas, operasional, dalam Bahasa Indonesia. Tidak perlu markdown table."""


class PayrollClosingDigestReader(Protocol):
    async def project(
        self,
        cycle: PayrollCycle,
        *,
        now: datetime,
        next_day_ready_hour: int = 6,
        target_roles: tuple[str, ...] | None = None,
    ) -> PayrollClosingDigest: ...


@dataclass(frozen=True, slots=True)
class PayrollClosingQueryResult:
    digest: PayrollClosingDigest
    status: Literal["ok", "unavailable"]
    answer: str | None
    role_filter: str | None = None


def payroll_query_context(digest: PayrollClosingDigest, role_filter: str | None) -> str:
    summary = digest.summary
    payload = {
        "cycle": {
            "cycle_id": digest.cycle.cycle_id,
            "label": digest.cycle.label,
            "start": digest.cycle.period.start.isoformat(),
            "end": digest.cycle.period.end.isoformat(),
            "evaluated_through": (
                digest.evaluated_through.isoformat()
                if digest.evaluated_through is not None
                else None
            ),
            "role_filter": role_filter,
        },
        "summary": {
            "total_talents": summary.total_talents,
            "complete": summary.complete,
            "waiting_submitted": summary.waiting_submitted,
            "needs_talent_action": summary.needs_talent_action,
            "unverified": summary.unverified,
            "successfully_reminded_talents": summary.successfully_reminded_talents,
            "unresponded_talents": summary.unresponded_talents,
            "actionable_not_reminded": summary.actionable_not_reminded,
            "delivery_retryable_failed": summary.delivery_retryable_failed,
            "delivery_final_failed": summary.delivery_final_failed,
            "delivery_unknown": summary.delivery_unknown,
        },
        "outstanding": [
            {
                "employee_id": item.employee_id,
                "nrp": item.nrp,
                "name": item.name,
                "role": item.role,
                "status": item.status,
                "actionable_days": item.actionable_days,
                "waiting_days": item.waiting_days,
                "unverified_days": item.unverified_days,
                "reason": item.reason.value,
                "latest_delivery_state": (
                    item.latest_delivery_state.value
                    if item.latest_delivery_state is not None
                    else None
                ),
                "latest_milestone": item.latest_milestone,
                "latest_sent_at": (
                    item.latest_sent_at.isoformat() if item.latest_sent_at is not None else None
                ),
                "responded_at": (
                    item.responded_at.isoformat() if item.responded_at is not None else None
                ),
                "error_code": item.error_code,
            }
            for item in digest.items
        ],
    }
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


@final
class PayrollClosingQueryAi:
    def __init__(self, client: TalentOpsChatClient) -> None:
        self._client = client

    async def answer(
        self,
        question: str,
        digest: PayrollClosingDigest,
        *,
        role_filter: str | None = None,
    ) -> str | None:
        user_prompt = (
            f"Pertanyaan PMO: {question.strip()}\n"
            f"Fakta Payroll: {payroll_query_context(digest, role_filter)}"
        )
        return await self._client.complete(_QUERY_SYSTEM_PROMPT, user_prompt)


@final
class PayrollClosingQueryService:
    def __init__(
        self,
        digest: PayrollClosingDigestReader,
        ai: PayrollClosingQueryAi | None,
    ) -> None:
        self._digest = digest
        self._ai = ai

    async def query(
        self,
        question: str,
        cycle: PayrollCycle,
        *,
        now: datetime,
        next_day_ready_hour: int,
        target_roles: tuple[str, ...],
        role_filter: str | None = None,
    ) -> PayrollClosingQueryResult:
        effective_roles = target_roles
        if role_filter is not None:
            effective_roles = tuple(role for role in target_roles if role == role_filter)
        digest = await self._digest.project(
            cycle,
            now=now,
            next_day_ready_hour=next_day_ready_hour,
            target_roles=effective_roles,
        )
        if self._ai is None:
            return PayrollClosingQueryResult(
                digest=digest,
                status="unavailable",
                answer=None,
                role_filter=role_filter,
            )
        answer = await self._ai.answer(question, digest, role_filter=role_filter)
        return PayrollClosingQueryResult(
            digest=digest,
            status="ok" if answer is not None else "unavailable",
            answer=answer,
            role_filter=role_filter,
        )
