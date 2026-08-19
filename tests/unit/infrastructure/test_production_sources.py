from __future__ import annotations

from digital_bast.domain.models import Employee, EmployeeId, EmployeeRole
from digital_bast.flows.models import Period
from digital_bast.infrastructure.production_sources import parse_iot_sheet


def _employee() -> Employee:
    return Employee(
        id=EmployeeId("7"),
        external_id="IOT-7",
        name="Operator One",
        role=EmployeeRole.IOT_OPERATIONS,
    )


def test_google_sheet_columns_are_parsed_and_matched_to_employee() -> None:
    employees = (_employee(),)
    payload = {
        "valueRanges": [
            {"values": [["Date", "2026/08/03"]]},
            {"values": [["Start Time", "1:02"]]},
            {"values": [["Close Time", ""]]},
            {"values": [["Response Time", "1:05"]]},
            {"values": [["First Responder", " operator one "]]},
            {"values": [["Issue Type", "PENGECEKAN SMOKING PHONING"]]},
            {"values": [["Issue Description", "Sensor offline"]]},
        ]
    }

    rows = parse_iot_sheet(payload, Period.parse("2026-08"), employees)

    assert len(rows) == 1
    assert rows[0].employee_id == EmployeeId("7")
    assert rows[0].start_at is not None
    assert rows[0].start_at.isoformat() == "2026-08-03T01:02:00+07:00"
    assert rows[0].close_at is None


def test_response_and_close_times_roll_forward_past_midnight() -> None:
    payload = {
        "valueRanges": [
            {"values": [["Date", "2026/08/03"]]},
            {"values": [["Start Time", "23:59"]]},
            {"values": [["Close Time", "23:59"]]},
            {"values": [["Response Time", "0:00"]]},
            {"values": [["First Responder", "IOT_TEAM"]]},
            {"values": [["Issue Type", "Request HO"]]},
            {"values": [["Issue Description", "Pengecekan vlog Critical"]]},
        ]
    }

    rows = parse_iot_sheet(payload, Period.parse("2026-08"), employees=())

    assert len(rows) == 1
    assert rows[0].start_at is not None
    assert rows[0].start_at.isoformat() == "2026-08-03T23:59:00+07:00"
    assert rows[0].response_at is not None
    assert rows[0].response_at.isoformat() == "2026-08-04T00:00:00+07:00"
    assert rows[0].close_at is not None
    assert rows[0].close_at.isoformat() == "2026-08-03T23:59:00+07:00"
