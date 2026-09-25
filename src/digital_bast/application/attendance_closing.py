from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence
    from datetime import date


class AttendanceClosingStatus(Enum):
    """Payroll-facing attendance closing state for one employee or attendance day."""

    NEEDS_TALENT_ACTION = "NEEDS_TALENT_ACTION"
    WAITING_SUBMITTED = "WAITING_SUBMITTED"
    COMPLETE = "COMPLETE"


class AttendanceCorrectionState(Enum):
    """Normalized correction lifecycle facts consumed by the closing projection."""

    NONE = "NONE"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class AttendanceScheduleState(Enum):
    """Whether attendance is expected for the source row."""

    WORKING = "WORKING"
    OFF = "OFF"


class AttendanceSourceState(Enum):
    """Whether the attendance source is trustworthy enough to evaluate the row."""

    AVAILABLE = "AVAILABLE"
    UNAVAILABLE = "UNAVAILABLE"


class AttendanceClosingReason(Enum):
    """Deterministic explanation for a per-day closing state."""

    RAW_COMPLETE = "RAW_COMPLETE"
    SCHEDULED_OFF = "SCHEDULED_OFF"
    SOURCE_UNAVAILABLE = "SOURCE_UNAVAILABLE"
    GAP_UNCOVERED = "GAP_UNCOVERED"
    CORRECTION_REJECTED = "CORRECTION_REJECTED"
    GAP_COVERED_BY_SUBMITTED_REQUEST = "GAP_COVERED_BY_SUBMITTED_REQUEST"
    GAP_COVERED_BY_APPROVED_CORRECTION = "GAP_COVERED_BY_APPROVED_CORRECTION"


@dataclass(frozen=True, slots=True)
class AttendanceClosingDayInput:
    """Normalized attendance/correction facts consumed by the closing projection."""

    attendance_id: int | None
    attendance_date: date
    clock_in_local: str | None
    clock_out_local: str | None
    correction_state: AttendanceCorrectionState = AttendanceCorrectionState.NONE
    correction_covers_clock_in: bool = False
    correction_covers_clock_out: bool = False
    schedule_state: AttendanceScheduleState = AttendanceScheduleState.WORKING
    source_state: AttendanceSourceState = AttendanceSourceState.AVAILABLE
    has_evidence: bool = False


@dataclass(frozen=True, slots=True)
class AttendanceClosingDayDetail:
    """Per-day decision emitted as part of an employee closing projection."""

    attendance_id: int | None
    attendance_date: date
    missing_clock_in: bool
    missing_clock_out: bool
    status: AttendanceClosingStatus
    reason: AttendanceClosingReason


@dataclass(frozen=True, slots=True)
class AttendanceClosingResult:
    """Payroll-facing closing projection for one employee."""

    employee_id: str
    status: AttendanceClosingStatus
    days: tuple[AttendanceClosingDayDetail, ...]

    @property
    def needs_action(self) -> bool:
        return self.status is AttendanceClosingStatus.NEEDS_TALENT_ACTION

    @property
    def waiting(self) -> bool:
        return self.status is AttendanceClosingStatus.WAITING_SUBMITTED

    @property
    def complete(self) -> bool:
        return self.status is AttendanceClosingStatus.COMPLETE


class AttendanceClosingService:
    """
    Project normalized attendance and correction facts into a payroll closing state.

    The service intentionally does not own the existing correction lifecycle. P03
    adapts source-specific attendance/review data into these normalized facts.
    """

    def evaluate(
        self,
        *,
        employee_id: str,
        rows: Sequence[AttendanceClosingDayInput],
        evaluated_through: date,
    ) -> AttendanceClosingResult:
        considered_rows = sorted(
            (row for row in rows if row.attendance_date <= evaluated_through),
            key=lambda row: (
                row.attendance_date,
                -1 if row.attendance_id is None else row.attendance_id,
            ),
        )
        day_details = tuple(self._evaluate_day(row) for row in considered_rows)

        if not day_details or any(
            detail.status is AttendanceClosingStatus.NEEDS_TALENT_ACTION
            for detail in day_details
        ):
            status = AttendanceClosingStatus.NEEDS_TALENT_ACTION
        elif any(
            detail.status is AttendanceClosingStatus.WAITING_SUBMITTED
            for detail in day_details
        ):
            status = AttendanceClosingStatus.WAITING_SUBMITTED
        else:
            status = AttendanceClosingStatus.COMPLETE

        return AttendanceClosingResult(
            employee_id=employee_id,
            status=status,
            days=day_details,
        )

    @classmethod
    def _evaluate_day(
        cls,
        row: AttendanceClosingDayInput,
    ) -> AttendanceClosingDayDetail:
        missing_clock_in = cls._is_missing_time(row.clock_in_local)
        missing_clock_out = cls._is_missing_time(row.clock_out_local)

        if row.source_state is AttendanceSourceState.UNAVAILABLE:
            return cls._detail(
                row=row,
                missing_clock_in=missing_clock_in,
                missing_clock_out=missing_clock_out,
                status=AttendanceClosingStatus.NEEDS_TALENT_ACTION,
                reason=AttendanceClosingReason.SOURCE_UNAVAILABLE,
            )

        if row.schedule_state is AttendanceScheduleState.OFF:
            return cls._detail(
                row=row,
                missing_clock_in=missing_clock_in,
                missing_clock_out=missing_clock_out,
                status=AttendanceClosingStatus.COMPLETE,
                reason=AttendanceClosingReason.SCHEDULED_OFF,
            )

        if not missing_clock_in and not missing_clock_out:
            return cls._detail(
                row=row,
                missing_clock_in=False,
                missing_clock_out=False,
                status=AttendanceClosingStatus.COMPLETE,
                reason=AttendanceClosingReason.RAW_COMPLETE,
            )

        if row.correction_state is AttendanceCorrectionState.REJECTED:
            return cls._detail(
                row=row,
                missing_clock_in=missing_clock_in,
                missing_clock_out=missing_clock_out,
                status=AttendanceClosingStatus.NEEDS_TALENT_ACTION,
                reason=AttendanceClosingReason.CORRECTION_REJECTED,
            )

        covers_clock_in = not missing_clock_in or row.correction_covers_clock_in
        covers_clock_out = not missing_clock_out or row.correction_covers_clock_out
        fully_covered = covers_clock_in and covers_clock_out

        if fully_covered and row.correction_state is AttendanceCorrectionState.APPROVED:
            status = AttendanceClosingStatus.COMPLETE
            reason = AttendanceClosingReason.GAP_COVERED_BY_APPROVED_CORRECTION
        elif (
            fully_covered
            and row.correction_state is AttendanceCorrectionState.SUBMITTED
        ):
            status = AttendanceClosingStatus.WAITING_SUBMITTED
            reason = AttendanceClosingReason.GAP_COVERED_BY_SUBMITTED_REQUEST
        else:
            status = AttendanceClosingStatus.NEEDS_TALENT_ACTION
            reason = AttendanceClosingReason.GAP_UNCOVERED

        return cls._detail(
            row=row,
            missing_clock_in=missing_clock_in,
            missing_clock_out=missing_clock_out,
            status=status,
            reason=reason,
        )

    @staticmethod
    def _detail(
        *,
        row: AttendanceClosingDayInput,
        missing_clock_in: bool,
        missing_clock_out: bool,
        status: AttendanceClosingStatus,
        reason: AttendanceClosingReason,
    ) -> AttendanceClosingDayDetail:
        return AttendanceClosingDayDetail(
            attendance_id=row.attendance_id,
            attendance_date=row.attendance_date,
            missing_clock_in=missing_clock_in,
            missing_clock_out=missing_clock_out,
            status=status,
            reason=reason,
        )

    @staticmethod
    def _is_missing_time(value: str | None) -> bool:
        return value is None or not value.strip()
