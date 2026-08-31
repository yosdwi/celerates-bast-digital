from datetime import date

from digital_bast.web.talent_mobile_contracts import (
    TalentMobileAttendanceItem,
    TalentMobileAttendanceSummary,
    TalentMobileOverview,
    TalentMobilePeriod,
    TalentMobileTaskSummary,
)


def test_talent_mobile_overview_resolves_date_fields_at_runtime() -> None:
    work_date = date(2026, 9, 1)
    overview = TalentMobileOverview(
        name="Talent Test",
        period=TalentMobilePeriod(year=2026, month=9, label="September 2026"),
        task=TalentMobileTaskSummary(closed=0, complete=0, missing=0, items=()),
        attendance=TalentMobileAttendanceSummary(
            total_work_days=1,
            needs_action=1,
            missing_data_days=(work_date,),
            items=(
                TalentMobileAttendanceItem(
                    attendance_key="attendance-1",
                    work_date=work_date,
                    check_in=None,
                    check_out=None,
                    gap="missing_both",
                    evidence_count=0,
                ),
            ),
            requests=(),
        ),
    )

    payload = overview.model_dump(mode="json")
    assert payload["attendance"]["missing_data_days"] == ["2026-09-01"]
    assert payload["attendance"]["items"][0]["work_date"] == "2026-09-01"
