from __future__ import annotations

from datetime import date

from digital_bast.domain.models import EmployeeRole
from digital_bast.infrastructure.pama_attendance import derive_day

WORK_DAY = date(2026, 8, 20)


def test_no_schedule_at_all_reads_as_day_off() -> None:
    # The pre-fix behavior for every IoT Ops day, still correct when there
    # really is no roster entry (see web/sync_router.py::_load_shift_codes,
    # which now only returns this None for a genuine gap).
    derived = derive_day(EmployeeRole.IOT_OPERATIONS, "7", WORK_DAY, "06:47", "15:02", None, {})

    assert derived["shift"] == "Day Off"


def test_raw_pama_roster_code_resolves_to_named_shift_with_window() -> None:
    derived = derive_day(EmployeeRole.IOT_OPERATIONS, "7", WORK_DAY, "06:47", "15:02", "P", {})

    assert derived["shift"] == "SHIFT 1"
    assert derived["schedule_in"] == "07:00"
    assert derived["schedule_out"] == "15:00"


def test_resolved_shift_name_from_schedules_table_is_not_day_off() -> None:
    # Regression: web/sync_router.py's _load_shift_codes reads
    # schedules.shift_name, which already holds the *resolved* name (e.g.
    # "SHIFT 1", written by scripts/import_schedule_csv.py via SHIFT_LEGEND)
    # rather than the raw roster code ("P") -- derive_day must still report
    # the real shift, not fall back to "Day Off" just because the resolved
    # name isn't a literal SHIFT_LEGEND key. schedule_in/out are lost
    # (nothing to look up a window by) but that's strictly better than the
    # previous always-None bug, which lost the shift label too.
    derived = derive_day(
        EmployeeRole.IOT_OPERATIONS, "7", WORK_DAY, "06:47", "15:02", "SHIFT 1", {}
    )

    assert derived["shift"] == "SHIFT 1"
    assert derived["schedule_in"] == ""
    assert derived["schedule_out"] == ""


def test_resolved_day_off_name_still_reads_as_day_off() -> None:
    derived = derive_day(EmployeeRole.IOT_OPERATIONS, "7", WORK_DAY, "", "", "Libur", {})

    assert derived["shift"] == "Day Off"
