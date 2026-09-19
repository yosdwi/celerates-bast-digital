from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import Enum
from typing import Sequence


class AttendanceClosingStatus(Enum):
    """Payroll-facing attendance closing state for one employee or attendance day."""

    NEEDS_TALENT_ACTION = "NEEDS_TALENT_ACTION"
    WAITING_SUBMITTED = "WAITING_SUBMITTED"
    COMPLETE = "COMPLETE"


class AttendanceClosingReason(Enum):
    """Deterministic explanation for a per-day closing state."""

    RAW_COMPLETE = "RAW_COMPLETE"
    GAP_UNCOVERED = "GAP_UNCOVERED"
    GAP_COVERED_BY_SUBMITTED_REQUEST = "GAP_COVERED_BY_SUBMITTED_REQUEST"
    GAP_COVERED_BY_APPROVED_CORRECTION = "GAP_COVERED_BY_APPROVED_CORRECTION"


@dataclass(frozen=True)
class AttendanceClosingDayInput:
    """Normalized attendance/correction facts consumed by the closing projection."""

    attendance_id: int
    attendance_date: date
    clock_in_local: str | None
    clock_out_local: str | None
    request_submitted: bool = False
    request_approved: bool = False
    correction_covers_clock_in: bool = False
    correction_covers_clock_out: bool = False
    has_evidence: bool = False


@dataclass(frozen=True)
class AttendanceClosingDayDetail:
    """Per-day decision emitted as part of an employee closing projection."""

    attendance_id: int
    attendance_date: date
    missing_clock_in: bool
    missing_clock_out: bool
    status: AttendanceClosingStatus
    reason: AttendanceClosingReason


@dataclass(frozen=True)
class AttendanceClosingResult:
    """Payroll-facing closing projection for one employee."""

    employee_id: int
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
    Project attendance and correction facts into a deterministic payroll state.

    This service intentionally does not own the existing correction lifecycle.
    Callers normalize lifecycle-specific request/approval data into coverage facts,
    then this projection answers whether payroll can close the employee.
    """

    def evaluate(
        self,
        *,
        employee_id: int,
        rows: Sequence[AttendanceClosingDayInput],
        evaluated_through: date,
    ) -> AttendanceClosingResult:
        considered_rows = sorted(
            (row for row in rows if row.attendance_date <= evaluated_through),
            key=lambda row: (row.attendance_date, row.attendance_id),
        )
        day_details = tuple(self._evaluate_day(row) for row in considered_rows)

        if any(
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

        if not missing_clock_in and not missing_clock_out:
            return AttendanceClosingDayDetail(
                attendance_id=row.attendance_id,
                attendance_date=row.attendance_date,
                missing_clock_in=False,
                missing_clock_out=False,
                status=AttendanceClosingStatus.COMPLETE,
                reason=AttendanceClosingReason.RAW_COMPLETE,
            )

        covers_clock_in = not missing_clock_in or row.correction_covers_clock_in
        covers_clock_out = not missing_clock_out or row.correction_covers_clock_out
        fully_covered = covers_clock_in and covers_clock_out

        if fully_covered and row.request_approved:
            status = AttendanceClosingStatus.COMPLETE
            reason = AttendanceClosingReason.GAP_COVERED_BY_APPROVED_CORRECTION
        elif fully_covered and row.request_submitted:
            status = AttendanceClosingStatus.WAITING_SUBMITTED
            reason = AttendanceClosingReason.GAP_COVERED_BY_SUBMITTED_REQUEST
        else:
            status = AttendanceClosingStatus.NEEDS_TALENT_ACTION
            reason = AttendanceClosingReason.GAP_UNCOVERED

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
