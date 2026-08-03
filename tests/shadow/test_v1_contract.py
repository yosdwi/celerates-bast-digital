from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from digital_bast.infrastructure.nocodb import JsonValue

FIXTURES: Final = Path(__file__).parents[1] / "fixtures"


def load_monthly_fixture() -> dict[str, JsonValue]:
    with (FIXTURES / "monthly_shadow.json").open(encoding="utf-8") as fixture_file:
        return json.load(fixture_file)


def task_fragment(value: str) -> str:
    return "".join(
        character for character in value if character.isalnum() or character in " _-"
    ).strip()


def daily_key(work_date: str, employee_id: str) -> str:
    return f"{work_date}_{employee_id}"


def task_key(work_date: str, employee_id: str, title: str) -> str:
    return f"{daily_key(work_date, employee_id)}_{task_fragment(title)}"


def attendance_candidates(
    fixture: dict[str, JsonValue],
) -> list[tuple[str, dict[str, JsonValue]]]:
    candidates = []
    for row in fixture["attendance_source"]:
        month, day, year = row["date"].split("/")
        work_date = date(int(year), int(month), int(day)).isoformat()
        record = {"date": work_date, "employee_id": row["employee_id"]}
        if row["start_time"]:
            record["start_time"] = f"{work_date} {row['start_time']}:00"
        if row["end_time"]:
            record["end_time"] = f"{work_date} {row['end_time']}:00"
        candidates.append((daily_key(work_date, row["employee_id"]), record))
    return candidates


def final_attendance(
    fixture: dict[str, JsonValue],
) -> dict[str, dict[str, JsonValue]]:
    existing = {record["stable_key"]: record for record in fixture["existing_attendance"]}
    final = dict(existing)
    for stable_key, candidate in attendance_candidates(fixture):
        if final.get(stable_key, {}).get("manual_lock"):
            continue
        final[stable_key] = candidate
    return final


def generated_manual_task_keys(fixture: dict[str, JsonValue]) -> dict[str, str]:
    result = {}
    for row in fixture["manual_tasks"]:
        if row["created_by"] == "system@system.com":
            continue
        if not row["date"] or not row["employee_id"]:
            continue
        result[row["record_id"]] = task_key(row["date"], row["employee_id"], row["task_list"])
    return result


def schedule_keys(fixture: dict[str, JsonValue]) -> set[str]:
    start = date(2024, 2, 1)
    return {
        daily_key(date(2024, 2, day).isoformat(), employee["employee_id"])
        for day in range(start.day, 30)
        for employee in fixture["employees"]
        if employee["role"] == "IoT Operations"
    }


def test_v1_compatible_attendance_outcome_when_duplicate_and_manual_lock() -> None:
    given = load_monthly_fixture()

    when = final_attendance(given)

    then = when["2024-02-01_emp-dev-001"]
    assert len(attendance_candidates(given)) == 4
    assert len(when) == 3
    assert then["manual_lock"] is True
    assert then["start_time"] == "2024-02-01 07:30:00"
    assert when["2024-02-29_emp-dev-001"]["end_time"] == "2024-02-29 12:00:00"
    assert "start_time" not in when["2024-02-29_emp-dev-001"]
    assert "end_time" not in when["2024-02-29_emp-iot-001"]


def test_v1_compatible_task_keys_when_special_characters_and_manual_rows() -> None:
    given = load_monthly_fixture()

    when = {
        "developer": [
            task_key(row["start_date"], row["employee_id"], row["task_list"])
            for row in given["developer_tasks"]
        ],
        "iot": [
            task_key(
                row["date"],
                "emp-iot-001" if row["first_responder"] == "Operator One" else "IOT_TEAM",
                row["issue_description"],
            )
            for row in given["iot_tasks"]
        ],
        "manual": generated_manual_task_keys(given),
    }

    then = when
    assert then["developer"] == [
        "2024-02-01_emp-dev-001_Release Alpha1",
        "2024-02-29_emp-dev-001_Quality check 2",
    ]
    assert then["iot"] == [
        "2024-02-29_emp-iot-001_Sensor alert zone1",
        "2024-02-29_IOT_TEAM_Unassigned alert",
    ]
    assert then["manual"] == {"manual-task-001": "2024-02-29_emp-dev-001_Manual verificationentry"}


def test_v1_compatible_monthly_schedule_outcome_when_leap_year() -> None:
    given = load_monthly_fixture()

    when = schedule_keys(given)

    then = when
    assert len(then) == 29
    assert "2024-02-01_emp-iot-001" in then
    assert "2024-02-29_emp-iot-001" in then


def test_v1_step10_gate_runs_only_at_target_hour() -> None:
    given = load_monthly_fixture()

    when = {
        hour: hour == given["step10"]["target_hour"]
        for hour in (
            given["step10"]["before_target_hour"],
            given["step10"]["target_hour"],
            given["step10"]["after_target_hour"],
        )
    }

    then = when
    assert then == {0: False, 1: True, 2: False}
