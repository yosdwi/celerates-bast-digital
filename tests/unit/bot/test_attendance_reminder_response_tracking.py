from __future__ import annotations

from datetime import date, datetime, timedelta

from digital_bast.bot.attendance_context import AttendanceReminderContext
from digital_bast.bot.attendance_reminder_routing import (
    AttendanceReminderRouteResult,
    AttendanceReminderRouteStatus,
)
from digital_bast.bot.attendance_reminder_runtime import TrackedAttendanceReminderRoutingService
from digital_bast.domain.time import JAKARTA

_NOW = datetime(2026, 9, 19, 10, 0, tzinfo=JAKARTA)
_CONTEXT = AttendanceReminderContext.create(
    "EMP-1",
    "2026-09:2026-08-21:2026-09-20",
    ("attendance:2026-09-04",),
    _NOW + timedelta(days=7),
)


class _Routing:
    def __init__(self, status: AttendanceReminderRouteStatus) -> None:
        self.status = status

    async def first_actionable(
        self,
        context: AttendanceReminderContext,
        *,
        employee_id: str,
        now: datetime,
    ) -> AttendanceReminderRouteResult:
        assert context == _CONTEXT
        assert employee_id == "EMP-1"
        assert now == _NOW
        return AttendanceReminderRouteResult(self.status)

    async def actionable_on(
        self,
        context: AttendanceReminderContext,
        *,
        employee_id: str,
        work_date: date,
        now: datetime,
    ) -> AttendanceReminderRouteResult:
        assert context == _CONTEXT
        assert employee_id == "EMP-1"
        assert work_date == date(2026, 9, 4)
        assert now == _NOW
        return AttendanceReminderRouteResult(self.status)


class _Deliveries:
    def __init__(self) -> None:
        self.calls: list[tuple[object, str, datetime]] = []

    async def mark_attendance_response(
        self,
        *,
        context_id: object,
        employee_id: str,
        responded_at: datetime,
    ) -> bool:
        self.calls.append((context_id, employee_id, responded_at))
        return True


async def test_open_attendance_action_marks_correlated_response() -> None:
    deliveries = _Deliveries()
    service = TrackedAttendanceReminderRoutingService(  # type: ignore[arg-type]
        _Routing(AttendanceReminderRouteStatus.OPEN),
        deliveries,  # type: ignore[arg-type]
    )

    result = await service.first_actionable(_CONTEXT, employee_id="EMP-1", now=_NOW)

    assert result.status is AttendanceReminderRouteStatus.OPEN
    assert deliveries.calls == [(_CONTEXT.context_id, "EMP-1", _NOW)]


async def test_non_actionable_route_does_not_count_as_response() -> None:
    deliveries = _Deliveries()
    service = TrackedAttendanceReminderRoutingService(  # type: ignore[arg-type]
        _Routing(AttendanceReminderRouteStatus.NO_ACTION),
        deliveries,  # type: ignore[arg-type]
    )

    result = await service.first_actionable(_CONTEXT, employee_id="EMP-1", now=_NOW)

    assert result.status is AttendanceReminderRouteStatus.NO_ACTION
    assert deliveries.calls == []


async def test_actionable_on_is_exposed_and_marks_correlated_response() -> None:
    """Regression test: TrackedAttendanceReminderRoutingService wrapped
    first_actionable() but had no passthrough for actionable_on(), so every
    caller (dm_message_entry.py's exact-date revalidation) crashed with
    AttributeError at runtime -- basedpyright caught it as a missing
    attribute; this locks the fix at the behavior level.
    """
    deliveries = _Deliveries()
    service = TrackedAttendanceReminderRoutingService(  # type: ignore[arg-type]
        _Routing(AttendanceReminderRouteStatus.OPEN),
        deliveries,  # type: ignore[arg-type]
    )

    result = await service.actionable_on(
        _CONTEXT, employee_id="EMP-1", work_date=date(2026, 9, 4), now=_NOW
    )

    assert result.status is AttendanceReminderRouteStatus.OPEN
    assert deliveries.calls == [(_CONTEXT.context_id, "EMP-1", _NOW)]
