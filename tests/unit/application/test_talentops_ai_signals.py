from digital_bast.application.talentops_ai import TalentOpsAiService
from digital_bast.application.talentops_investigation import talent_evidence
from tests.unit.web.test_talentops_routes import talent_detail_view


class CapturingClient:
    def __init__(self) -> None:
        self.system_prompt = ""
        self.user_prompt = ""

    async def complete(self, system_prompt: str, user_prompt: str) -> str | None:
        self.system_prompt = system_prompt
        self.user_prompt = user_prompt
        return (
            '{"title":"Attendance blocks Timesheet",'
            '"finding":"Attendance on 1 Aug must be reviewed before Timesheet can complete.",'
            '"impact":"Readiness remains incomplete for the affected domains.",'
            '"suggested_action":"Verify Attendance on 1 Aug first.",'
            '"evidence_ids":["signal:0","attendance:2026-08-01",'
            '"timesheet:2026-08-01","invented:1"]}'
        )


async def test_talent_ai_receives_operational_signals_and_date_level_evidence() -> None:
    client = CapturingClient()
    service = TalentOpsAiService(client)

    investigation = await service.answer_talent(
        "Which dates should I verify first?",
        talent_detail_view(),
    )

    assert investigation is not None
    assert investigation.title == "Attendance blocks Timesheet"
    assert investigation.suggested_action == "Verify Attendance on 1 Aug first."
    assert tuple(item.id for item in investigation.evidence) == (
        "signal:0",
        "attendance:2026-08-01",
        "timesheet:2026-08-01",
    )
    assert "invented:1" not in tuple(item.id for item in investigation.evidence)
    assert "operational_signals" in client.user_prompt
    assert "attendance_blocks_timesheet" in client.user_prompt
    assert "closed_task_missing_evidence" in client.user_prompt
    assert "attendance_issue_days" in client.user_prompt
    assert "timesheet_issue_days" in client.user_prompt
    assert "summary:talent" in client.user_prompt
    assert "Evidence catalog" in client.user_prompt
    assert "2026-08-01" in client.user_prompt
    assert "evidence_ids" in client.system_prompt


def test_talent_evidence_always_contains_summary_fact() -> None:
    evidence = talent_evidence(talent_detail_view())

    summary = next(item for item in evidence if item.id == "summary:talent")
    assert summary.kind == "summary"
    assert "overall=incomplete" in summary.detail
