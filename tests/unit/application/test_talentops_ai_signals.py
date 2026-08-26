from digital_bast.application.talentops_ai import TalentOpsAiService
from tests.unit.web.test_talentops_routes import talent_detail_view


class CapturingClient:
    def __init__(self) -> None:
        self.system_prompt = ""
        self.user_prompt = ""

    async def complete(self, system_prompt: str, user_prompt: str) -> str | None:
        self.system_prompt = system_prompt
        self.user_prompt = user_prompt
        return "Grounded investigation"


async def test_talent_ai_receives_operational_signals_and_date_level_evidence() -> None:
    client = CapturingClient()
    service = TalentOpsAiService(client)

    answer = await service.answer_talent(
        "Which dates should I verify first?",
        talent_detail_view(),
    )

    assert answer == "Grounded investigation"
    assert "operational_signals" in client.user_prompt
    assert "attendance_blocks_timesheet" in client.user_prompt
    assert "closed_task_missing_evidence" in client.user_prompt
    assert "attendance_issue_days" in client.user_prompt
    assert "timesheet_issue_days" in client.user_prompt
    assert "2026-08-01" in client.user_prompt
    assert "dependency" in client.system_prompt.casefold()
