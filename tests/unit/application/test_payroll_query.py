from __future__ import annotations

from datetime import date, datetime

from digital_bast.application.attendance_closing_policy import payroll_cycle
from digital_bast.application.payroll_digest import (
    PayrollClosingDigest,
    PayrollDigestSummary,
    PayrollFollowUpItem,
    PayrollFollowUpReason,
)
from digital_bast.application.payroll_query import (
    PayrollClosingQueryAi,
    PayrollClosingQueryService,
    payroll_query_context,
)
from digital_bast.domain.time import JAKARTA

_CYCLE = payroll_cycle(2026, 9)
_NOW = datetime(2026, 9, 19, 10, 0, tzinfo=JAKARTA)


def _digest() -> PayrollClosingDigest:
    return PayrollClosingDigest(
        cycle=_CYCLE,
        evaluated_through=date(2026, 9, 18),
        summary=PayrollDigestSummary(
            total_talents=2,
            complete=0,
            waiting_submitted=1,
            needs_talent_action=1,
            unverified=0,
            successful_reminder_deliveries=1,
            successfully_reminded_talents=1,
            unresponded_talents=1,
            actionable_not_reminded=0,
            delivery_retryable_failed=0,
            delivery_final_failed=0,
            delivery_unknown=0,
        ),
        items=(
            PayrollFollowUpItem(
                employee_id="EMP-1",
                nrp="10001",
                name="Andi",
                role="Developer",
                status="NEEDS_TALENT_ACTION",
                actionable_days=1,
                waiting_days=0,
                unverified_days=0,
                reason=PayrollFollowUpReason.UNRESPONDED,
            ),
            PayrollFollowUpItem(
                employee_id="EMP-2",
                nrp="10002",
                name="Budi",
                role="Developer",
                status="WAITING_SUBMITTED",
                actionable_days=0,
                waiting_days=1,
                unverified_days=0,
                reason=PayrollFollowUpReason.WAITING_REVIEW,
            ),
        ),
    )


class _DigestReader:
    def __init__(self) -> None:
        self.roles: tuple[str, ...] | None = None

    async def project(self, cycle: object, **kwargs: object) -> PayrollClosingDigest:
        assert cycle == _CYCLE
        assert kwargs["now"] == _NOW
        self.roles = kwargs["target_roles"]
        return _digest()


class _Client:
    def __init__(self, response: str | None) -> None:
        self.response = response
        self.calls: list[tuple[str, str]] = []

    async def complete(self, system_prompt: str, user_prompt: str) -> str | None:
        self.calls.append((system_prompt, user_prompt))
        return self.response


def test_payroll_query_context_exposes_correlated_unresponded_facts() -> None:
    context = payroll_query_context(_digest(), "Developer")

    assert '"unresponded_talents":1' in context
    assert '"reason":"UNRESPONDED"' in context
    assert '"reason":"WAITING_REVIEW"' in context
    assert '"role_filter":"Developer"' in context


async def test_query_applies_role_filter_before_digest_and_ai_only_summarizes() -> None:
    digest = _DigestReader()
    client = _Client("Andi belum merespons reminder Payroll; Budi menunggu review PMO.")
    service = PayrollClosingQueryService(digest, PayrollClosingQueryAi(client))

    result = await service.query(
        "Siapa yang belum merespons dan siapa yang menunggu review?",
        _CYCLE,
        now=_NOW,
        next_day_ready_hour=6,
        target_roles=("Developer", "IoT Operations"),
        role_filter="Developer",
    )

    assert digest.roles == ("Developer",)
    assert result.status == "ok"
    assert result.answer is not None
    assert result.digest.summary.unresponded_talents == 1
    assert "UNRESPONDED" in client.calls[0][1]
    assert "WAITING_REVIEW" in client.calls[0][1]


async def test_query_returns_deterministic_facts_when_ai_is_unavailable() -> None:
    digest = _DigestReader()
    service = PayrollClosingQueryService(digest, None)

    result = await service.query(
        "Status closing sekarang?",
        _CYCLE,
        now=_NOW,
        next_day_ready_hour=6,
        target_roles=("Developer",),
    )

    assert result.status == "unavailable"
    assert result.answer is None
    assert result.digest.summary.needs_talent_action == 1
    assert len(result.digest.items) == 2
