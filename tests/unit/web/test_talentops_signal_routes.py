from tests.unit.web.test_talentops_routes import make_client


def test_talent_detail_exposes_deterministic_operational_signals() -> None:
    response = make_client(authenticated=True).get(
        "/api/talentops/v1/talents/JIMT24002?year=2026&month=8"
    )

    assert response.status_code == 200
    payload = response.json()
    kinds = {signal["kind"] for signal in payload["signals"]}
    assert "attendance_blocks_timesheet" in kinds
    assert "closed_task_missing_evidence" in kinds

    dependency = next(
        signal
        for signal in payload["signals"]
        if signal["kind"] == "attendance_blocks_timesheet"
    )
    assert dependency["dates"] == ["2026-08-01"]
    assert dependency["domains"] == ["attendance", "timesheet"]
