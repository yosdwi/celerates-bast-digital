from datetime import date, datetime, UTC

import pytest

from digital_bast.application.talentops import (
    Blocker,
    CheckSummary,
    PeriodView,
    ReadinessChecks,
    TalentDataAvailability,
    TalentDetailView,
)
from digital_bast.application.talentops_followups import (
    FollowUpRecord,
    TalentOpsFollowUpService,
    WhatsAppSendReceipt,
)
from digital_bast.domain.completion import CheckState, DateRange
from digital_bast.domain.models import Employee, EmployeeId, EmployeeRole


PERIOD = DateRange(date(2026, 8, 1), date(2026, 8, 31))


def detail(blocked: bool = True) -> TalentDetailView:
    blockers = (
        Blocker("evidence", CheckState.INCOMPLETE, ("Evidence missing for Closed task A",)),
    ) if blocked else ()
    state = CheckState.INCOMPLETE if blocked else CheckState.COMPLETE
    return TalentDetailView(
        period=PeriodView(2026, 8, "2026-08-01", "2026-08-31", "1-31 Agustus 2026"),
        nrp="JIMT24002",
        name="Yoses Dwi Maheswara",
        role=EmployeeRole.DEVELOPER,
        overall_state=state,
        checks=ReadinessChecks(
            attendance=CheckSummary(CheckState.COMPLETE, 0),
            timesheet=CheckSummary(CheckState.COMPLETE, 0),
            task=CheckSummary(CheckState.COMPLETE, 0),
            evidence=CheckSummary(state, 1 if blocked else 0),
        ),
        blockers=blockers,
        attendance_days=(),
        timesheet_days=(),
        tasks=(),
        availability=TalentDataAvailability(attendance=True, evidence=True),
    )


class TalentOps:
    def __init__(self, value: TalentDetailView | None) -> None:
        self.value = value

    async def talent_detail(self, period: DateRange, nrp: str) -> TalentDetailView | None:
        _ = (period, nrp)
        return self.value


class Roster:
    async def load(self) -> tuple[Employee, ...]:
        return (
            Employee(
                EmployeeId("employee-1"),
                "JIMT24002",
                "Yoses Dwi Maheswara",
                EmployeeRole.DEVELOPER,
            ),
        )


class Identity:
    def __init__(self, jid: str | None) -> None:
        self.jid = jid

    async def jid_for_employee(self, employee_id: str) -> str | None:
        assert employee_id == "employee-1"
        return self.jid


class Outbound:
    def __init__(self, receipt: WhatsAppSendReceipt) -> None:
        self.receipt = receipt
        self.calls: list[tuple[str, str, str]] = []

    async def send(self, jid: str, text: str, request_id: str) -> WhatsAppSendReceipt:
        self.calls.append((jid, text, request_id))
        return self.receipt


class Repo:
    def __init__(self) -> None:
        self.records: dict[str, FollowUpRecord] = {}

    async def by_idempotency(self, idempotency_key: str) -> FollowUpRecord | None:
        return self.records.get(idempotency_key)

    async def latest_for_employee(self, employee_id: str) -> FollowUpRecord | None:
        values = [item for item in self.records.values() if item.employee_id == employee_id]
        return values[-1] if values else None

    async def record(self, **kwargs: object) -> FollowUpRecord:
        key = str(kwargs["idempotency_key"])
        sent_at = kwargs["sent_at"]
        record = FollowUpRecord(
            id=f"delivery-{len(self.records) + 1}",
            idempotency_key=key,
            employee_id=str(kwargs["employee_id"]),
            period_start="2026-08-01",
            period_end="2026-08-31",
            channel="whatsapp",
            message=str(kwargs["message"]),
            source=str(kwargs["source"]),
            status=str(kwargs["status"]),
            provider_message_id=(
                None if kwargs["provider_message_id"] is None else str(kwargs["provider_message_id"])
            ),
            created_by=str(kwargs["created_by"]),
            created_at=datetime(2026, 8, 25, tzinfo=UTC),
            sent_at=sent_at if isinstance(sent_at, datetime) else None,
            error_code=None if kwargs["error_code"] is None else str(kwargs["error_code"]),
        )
        self.records[key] = record
        return record


class Ai:
    async def draft_follow_up(self, view: TalentDetailView) -> str | None:
        assert view.nrp == "JIMT24002"
        return "Halo Yoses, Evidence untuk Closed task A masih perlu dilengkapi."


def service(
    *,
    jid: str | None = "628123@s.whatsapp.net",
    blocked: bool = True,
    ai: Ai | None = None,
) -> tuple[TalentOpsFollowUpService, Outbound, Repo]:
    outbound = Outbound(WhatsAppSendReceipt("sent", provider_message_id="wa-1"))
    repo = Repo()
    result = TalentOpsFollowUpService(
        TalentOps(detail(blocked)),  # type: ignore[arg-type]
        Roster(),
        Identity(jid),
        outbound,
        repo,
        ai,  # type: ignore[arg-type]
    )
    return result, outbound, repo


@pytest.mark.asyncio
async def test_draft_is_deterministic_without_ai_and_reports_binding() -> None:
    followups, _, _ = service(ai=None)
    draft = await followups.draft(PERIOD, "JIMT24002")

    assert draft is not None
    assert draft.source == "deterministic"
    assert draft.whatsapp_bound is True
    assert "Evidence missing" in draft.message


@pytest.mark.asyncio
async def test_ai_may_improve_draft_but_not_send_it() -> None:
    followups, outbound, _ = service(ai=Ai())
    draft = await followups.draft(PERIOD, "JIMT24002")

    assert draft is not None
    assert draft.source == "ai"
    assert draft.message.startswith("Halo Yoses")
    assert outbound.calls == []


@pytest.mark.asyncio
async def test_send_requires_bound_whatsapp_identity() -> None:
    followups, outbound, repo = service(jid=None)
    result = await followups.send(
        period=PERIOD,
        nrp="JIMT24002",
        message="Please review the blocker",
        idempotency_key="11111111-1111-4111-8111-111111111111",
        created_by="owner@example.com",
        source="edited",
    )

    assert result is not None
    assert result.status == "not_bound"
    assert outbound.calls == []
    assert repo.records == {}


@pytest.mark.asyncio
async def test_send_is_idempotent_and_records_provider_receipt() -> None:
    followups, outbound, _ = service()
    key = "22222222-2222-4222-8222-222222222222"
    first = await followups.send(
        period=PERIOD,
        nrp="JIMT24002",
        message="Please review the blocker",
        idempotency_key=key,
        created_by="owner@example.com",
        source="edited",
    )
    second = await followups.send(
        period=PERIOD,
        nrp="JIMT24002",
        message="Please review the blocker",
        idempotency_key=key,
        created_by="owner@example.com",
        source="edited",
    )

    assert first is not None and first.status == "sent"
    assert first.provider_message_id == "wa-1"
    assert second is not None and second.duplicate is True
    assert len(outbound.calls) == 1


@pytest.mark.asyncio
async def test_send_rechecks_current_blockers_before_delivery() -> None:
    followups, outbound, _ = service(blocked=False)
    result = await followups.send(
        period=PERIOD,
        nrp="JIMT24002",
        message="Stale reminder",
        idempotency_key="33333333-3333-4333-8333-333333333333",
        created_by="owner@example.com",
        source="edited",
    )

    assert result is not None
    assert result.status == "no_blockers"
    assert outbound.calls == []
