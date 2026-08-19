"""Shared PAMA attendance rules.

Lifted out of scripts/load_pama_attendance.py so the ingest endpoint
(web/sync_router.py) and the direct-load script apply exactly the same shift
legend, punch bucketing, and Day Off / Keterangan derivation. Two copies of
this would drift, and the difference would only show up as wrong hours in a
signed BAST.

The SQL lives here too so bridge/pama_bridge.py can import one authoritative
query instead of a pasted duplicate.
"""

from __future__ import annotations

from datetime import datetime, time
from typing import TYPE_CHECKING, Final, Protocol

from digital_bast.domain.identity import daily_key, holiday_key
from digital_bast.domain.models import EmployeeRole, Holiday, RecordOrigin, Schedule
from digital_bast.domain.timesheets import day_status

if TYPE_CHECKING:
    from datetime import date


class HolidayLookup(Protocol):
    """Only the lookup `derive_day` actually performs.

    Avoids depending on the `holidays` package's own typing, which resolves to
    Unknown here and would leak into every caller's signature.
    """

    def get(self, key: date, /) -> object | None: ...


# Column names verified against the live server on 2026-08-20. The previous
# spelling (att_hour / att_type, wrapped in FORMAT) does not exist there and
# failed with "Invalid column name 'att_hour'" -- it had never actually been
# run, because the attendance host was unreachable from the dev sandbox when
# this query was written. The real columns are attendance_hour ('HH:MM:SS'
# varchar, so LEFT(...,5) gives HH:MM) and trans ('IN'/'OUT').
#
# The u.is_pama = 0 AND u.active = 1 join filter is load-bearing and was
# checked against all 17 roster members: every one passes. It silently drops
# anyone it does not match, so re-check it when the roster changes.
ATTENDANCE_QUERY: Final = """
DECLARE @NRP AS VARCHAR(20) = %s;
DECLARE @RANGE_START AS DATE = %s;
DECLARE @RANGE_END AS DATE = %s;

WITH data_raw AS (
    SELECT h.attendance_date,
           CONCAT(LEFT(h.attendance_hour, 5), ' (', h.trans, ')') AS att_hour_label
    FROM [db_attendance].[attend].[tbl_t_att_daily_history] h
    LEFT JOIN [db_pamamobile].[dbo].[tbl_user] u ON u.nrp = h.nrp
    WHERE h.nrp = @NRP AND h.attendance_date BETWEEN @RANGE_START AND @RANGE_END
      AND u.is_pama = 0 AND u.active = 1
    UNION ALL
    SELECT d.attendance_date,
           CONCAT(LEFT(d.attendance_hour, 5), ' (', d.trans, ')') AS att_hour_label
    FROM [db_attendance].[attend].[tbl_t_att_daily] d
    LEFT JOIN [db_pamamobile].[dbo].[tbl_user] u ON u.nrp = d.nrp
    WHERE d.nrp = @NRP AND d.attendance_date BETWEEN @RANGE_START AND @RANGE_END
      AND u.is_pama = 0 AND u.active = 1
)
SELECT attendance_date, att_hour_label FROM data_raw ORDER BY attendance_date, att_hour_label;
"""

SHIFT_LEGEND: Final[dict[str, tuple[str, str, str]]] = {
    "P": ("SHIFT 1", "07:00", "15:00"),
    "PS": ("SHIFT 1.5", "12:00", "20:00"),
    "S": ("SHIFT 2", "15:00", "23:00"),
    "M": ("SHIFT 3", "23:00", "07:00"),
    "L": ("Libur", "", ""),
    "LS": ("Libur", "", ""),
    "TS": ("Tugas Site", "", ""),
    "C": ("Cuti", "", ""),
    "I": ("Sakit", "", ""),
}

DEVELOPER_SCHEDULE: Final = ("07:30", "16:30")

# Codes that mean "scheduled absence", so no clock window applies.
_NON_WORKING_CODES: Final = frozenset({"L", "LS", "TS", "C", "I"})


def bucket_punches(labels: list[str]) -> tuple[str, str]:
    """First `(IN)` and last `(OUT)` of a day, as `HH:MM` strings.

    Sorting is what makes "first" and "last" meaningful -- the source returns
    one row per punch with no ordering guarantee beyond the query's ORDER BY.
    """
    check_in = ""
    check_out = ""
    for label in sorted(labels):
        if "(IN)" in label and not check_in:
            check_in = label.replace(" (IN)", "").strip()
        elif "(OUT)" in label:
            check_out = label.replace(" (OUT)", "").strip()
    return check_in, check_out


def parse_clock(value: str) -> time | None:
    if not value.strip():
        return None
    try:
        return datetime.strptime(value.strip(), "%H:%M").time()  # noqa: DTZ007
    except ValueError:
        return None


def derive_day(  # noqa: PLR0913, PLR0917
    role: EmployeeRole,
    employee_id: str,
    work_date: date,
    check_in: str,
    check_out: str,
    shift_code: str | None,
    id_holidays: HolidayLookup,
) -> dict[str, str]:
    """Shift / schedule window / Keterangan for one employee-day.

    IoT Operations follows the roster shift code; Developers follow a fixed
    07:30-16:30 window and only count as a working day when they actually
    punched.
    """
    if role is EmployeeRole.IOT_OPERATIONS:
        shift_name = (
            None if shift_code is None else SHIFT_LEGEND.get(shift_code, (shift_code, "", ""))[0]
        )
        schedule = Schedule(
            daily_key("schedule", work_date, employee_id),
            employee_id,  # type: ignore[arg-type]
            work_date,
            shift_name,
            RecordOrigin.PIPELINE,
        )
        is_holiday, notes = day_status(role, work_date.weekday(), None, schedule)
        if shift_code is not None and shift_code in SHIFT_LEGEND:
            if shift_code in _NON_WORKING_CODES:
                schedule_in, schedule_out = "", ""
            else:
                _, schedule_in, schedule_out = SHIFT_LEGEND[shift_code]
        else:
            schedule_in, schedule_out = "", ""
        shift = "Day Off" if is_holiday else (shift_name or "")
    else:
        holiday_name = id_holidays.get(work_date)
        holiday = (
            Holiday(holiday_key(work_date), work_date, str(holiday_name))
            if holiday_name is not None
            else None
        )
        is_holiday, notes = day_status(role, work_date.weekday(), holiday, None)
        if is_holiday or not (check_in or check_out):
            shift, schedule_in, schedule_out = "Day Off", "", ""
        else:
            shift, schedule_in, schedule_out = "N", *DEVELOPER_SCHEDULE
    return {
        "shift": shift,
        "schedule_in": schedule_in,
        "schedule_out": schedule_out,
        "attendance_code": "",
        "notes": notes,
    }
