from __future__ import annotations

from digital_bast.domain.models import EmployeeId, EmployeeRole
from digital_bast.flows.models import Period
from digital_bast.infrastructure.production_sources import parse_employees, parse_iot_sheet


def test_employee_payload_is_parsed_into_typed_active_inventory() -> None:
    records = [
        {
            "Id": 7,
            "Employee ID": "IOT-7",
            "Employee Name": "Operator One",
            "Role": "IoT Operations",
            "Status": "Active",
        },
        {
            "Id": 8,
            "Employee ID": "DEV-8",
            "Employee Name": "Developer One",
            "Role": "Developer",
            "Status": "Inactive",
        },
    ]

    employees = parse_employees(records)

    assert len(employees) == 1
    assert employees[0].id == EmployeeId("7")
    assert employees[0].role is EmployeeRole.IOT_OPERATIONS


def test_google_sheet_columns_are_parsed_and_matched_to_employee() -> None:
    employees = parse_employees(
        [
            {
                "Id": 7,
                "Employee ID": "IOT-7",
                "Employee Name": "Operator One",
                "Role": "IoT Operations",
                "Status": "Active",
            }
        ]
    )
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
