from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from digital_bast.infrastructure.nocodb import JsonValue

FIXTURES: Final = Path(__file__).parents[1] / "fixtures"


def load_fixture(name: str) -> dict[str, JsonValue]:
    with (FIXTURES / name).open(encoding="utf-8") as fixture_file:
        return json.load(fixture_file)


def test_monthly_shadow_fixture_has_sanitized_month_boundary_contract() -> None:
    given = load_fixture("monthly_shadow.json")

    when = given

    then = when["schema_version"] == 1
    assert then
    assert when["target_month"] == "2024-02"
    assert len(when["employees"]) == 2
    assert len(when["attendance_source"]) == 4
    assert when["attendance_source"][0]["date"] == when["attendance_source"][1]["date"]
    assert when["attendance_source"][2]["start_time"] is None
    assert when["attendance_source"][3]["end_time"] is None
    assert when["holidays"][0]["date"] == "2024-02-29"
    assert when["existing_attendance"][0]["manual_lock"] is True
    assert when["existing_timesheets"][0]["manual_lock"] is True


def test_web_route_inventory_has_unique_method_path_pairs() -> None:
    given = load_fixture("web_routes_v1.json")

    when = [tuple(route) for route in given["routes"]]

    then = set(when)
    assert given["schema_version"] == 1
    assert len(when) == len(then)
    assert ("GET", "/health") in then
    assert ("POST", "/report/all") in then
