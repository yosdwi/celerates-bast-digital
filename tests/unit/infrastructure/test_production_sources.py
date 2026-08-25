from __future__ import annotations

from datetime import date

from digital_bast.domain.models import Employee, EmployeeId, EmployeeRole
from digital_bast.flows.models import Period
from digital_bast.infrastructure.production_sources import parse_iot_sheet, parse_schedule_rows


def _employee() -> Employee:
    return Employee(
        id=EmployeeId("7"),
        external_id="IOT-7",
        name="Operator One",
        role=EmployeeRole.IOT_OPERATIONS,
    )


def test_parse_schedule_rows_reads_one_month_block() -> None:
    # Column 0 is always the employee name/label -- month blocks start at
    # column 1, same as scripts/import_schedule_csv.py's real CSV layout
    # (a legend block occupies rows 0-9, weekday row 11 is unused here).
    rows = [
        [],  # 0
        [],  # 1
        [],  # 2
        [],  # 3
        [],  # 4
        [],  # 5
        [],  # 6
        [],  # 7
        [],  # 8
        [],  # 9
        ["", "March 2024", ""],  # 10: month header
        ["", "Fri", "Sat"],  # 11: weekday row, unused
        ["", "1", "2"],  # 12: day numbers
        ["Operator One (P)", "P", "L"],  # 13: first data row
    ]

    schedule = parse_schedule_rows(rows, {"Operator One": "7"})

    assert schedule == {
        ("7", date(2024, 3, 1)): "P",
        ("7", date(2024, 3, 2)): "L",
    }


def test_parse_schedule_rows_skips_unmatched_and_blank_rows() -> None:
    rows = [
        [],
        [],
        [],
        [],
        [],
        [],
        [],
        [],
        [],
        [],
        ["", "March 2024"],
        ["", "Fri"],
        ["", "1"],
        ["Unknown Person (P)", "P"],
        ["Operator One (P)", ""],
    ]

    schedule = parse_schedule_rows(rows, {"Operator One": "7"})

    assert schedule == {}


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
