from digital_bast.bot.task_evidence_submission import TASK_EVIDENCE_SOURCES
from digital_bast.domain.models import TaskSource


def test_talent_mobile_task_evidence_accepts_redmine_and_shifting_iot() -> None:
    assert TASK_EVIDENCE_SOURCES == (
        TaskSource.REDMINE.value,
        TaskSource.GOOGLE_SHEET.value,
    )
