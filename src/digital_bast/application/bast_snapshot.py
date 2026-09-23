"""Factual BAST closing snapshot used by scheduled and manual reminders."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol, final

from digital_bast.application.talentops import Blocker
from digital_bast.domain.completion import CheckState, format_day

if TYPE_CHECKING:
    from datetime import date

    from digital_bast.application.talentops import AttentionItem, TalentOpsService
    from digital_bast.domain.completion import DateRange


class PendingAttendanceSource(Protocol):
    async def pending(self) -> tuple[object, ...]: ...


@dataclass(frozen=True, slots=True)
class BastPendingApproval:
    request_id: str
    employee_id: str
    nrp: str
    name: str
    work_date: date
    change: str


@dataclass(frozen=True, slots=True)
class BastTalentSnapshot:
    employee_id: str
    nrp: str
    name: str
    actionable: tuple[Blocker, ...]
    waiting_pmo: bool
    source_review: tuple[Blocker, ...]

    @property
    def actionable_count(self) -> int:
        return sum(max(len(item.issues), 1) for item in self.actionable)


@dataclass(frozen=True, slots=True)
class BastClosingSnapshot:
    total_talents: int
    complete: int
    need_talent_action: int
    waiting_pmo: int
    source_review: int
    talents: tuple[BastTalentSnapshot, ...]
    pending_approvals: tuple[BastPendingApproval, ...] = ()


def _text_value(value: object | None) -> str | None:
    if value is None:
        return None
    raw = getattr(value, "value", value)
    text = str(raw).strip()
    return text or None


def _clock_label(value: object | None) -> str:
    if value is None:
        return "-"
    return str(value)[:5]


def _approval_change(request: object) -> str:
    resolution_type = _text_value(getattr(request, "resolution_type", None))
    check_in = _clock_label(getattr(request, "proposed_check_in", None))
    check_out = _clock_label(getattr(request, "proposed_check_out", None))
    if resolution_type == "missing_clock_in":
        return f"Clock In → {check_in}"
    if resolution_type == "missing_clock_out":
        return f"Clock Out → {check_out}"
    if resolution_type == "missing_both_worked":
        return f"Clock In {check_in} · Clock Out {check_out}"
    if resolution_type == "absence":
        absence_type = _text_value(getattr(request, "absence_type", None))
        return (absence_type or "Tidak masuk").replace("_", " ").title()
    return "Koreksi attendance"


def _pending_approvals(
    requests: tuple[object, ...],
    period: DateRange,
) -> tuple[BastPendingApproval, ...]:
    values: list[BastPendingApproval] = []
    for request in requests:
        employee_id = getattr(request, "employee_id", None)
        work_date = getattr(request, "work_date", None)
        if (
            not isinstance(employee_id, str)
            or not employee_id.strip()
            or work_date is None
            or not period.start <= work_date <= period.end
        ):
            continue
        request_id = str(getattr(request, "id", "")).strip()
        nrp = str(getattr(request, "nrp", "")).strip()
        name = str(
            getattr(request, "full_name", None)
            or getattr(request, "name", None)
            or nrp
            or employee_id
        ).strip()
        values.append(
            BastPendingApproval(
                request_id=request_id,
                employee_id=employee_id,
                nrp=nrp,
                name=name,
                work_date=work_date,
                change=_approval_change(request),
            )
        )
    return tuple(
        sorted(
            values,
            key=lambda item: (item.work_date, item.name.casefold(), item.request_id),
        )
    )


def _pending_dates(
    requests: tuple[object, ...],
    period: DateRange,
) -> dict[str, frozenset[date]]:
    values: dict[str, set[date]] = {}
    for request in requests:
        employee_id = getattr(request, "employee_id", None)
        work_date = getattr(request, "work_date", None)
        if (
            isinstance(employee_id, str)
            and employee_id.strip()
            and work_date is not None
            and period.start <= work_date <= period.end
        ):
            values.setdefault(employee_id, set()).add(work_date)
    return {employee_id: frozenset(days) for employee_id, days in values.items()}


def _matches_pending_day(issue: str, pending_dates: frozenset[date]) -> bool:
    return any(issue.startswith(f"{format_day(work_date)} —") for work_date in pending_dates)


def _actionable_blockers(
    item: AttentionItem,
    pending_dates: frozenset[date],
) -> tuple[Blocker, ...]:
    """Suppress only the exact attendance dates already waiting for PMO.

    A Talent may have one submitted correction and another unresolved gap in the
    same month. A coarse employee-level suppression would hide the second gap
    and incorrectly stop reminders, so filtering is deliberately per work date.
    """
    result: list[Blocker] = []
    for blocker in item.blockers:
        if blocker.state is not CheckState.INCOMPLETE:
            continue
        if blocker.domain == "attendance" and pending_dates:
            remaining = tuple(
                issue
                for issue in blocker.issues
                if not _matches_pending_day(issue, pending_dates)
            )
            if remaining:
                result.append(Blocker(blocker.domain, blocker.state, remaining))
            continue
        if blocker.domain == "timesheet" and pending_dates:
            remaining = tuple(
                issue
                for issue in blocker.issues
                if not (
                    "Log 1 PAMA belum valid" in issue
                    and _matches_pending_day(issue, pending_dates)
                )
            )
            if remaining:
                result.append(Blocker(blocker.domain, blocker.state, remaining))
            continue
        result.append(blocker)
    return tuple(result)


@final
class BastClosingSnapshotService:
    def __init__(
        self,
        talentops: TalentOpsService,
        attendance_resolutions: PendingAttendanceSource,
    ) -> None:
        self._talentops = talentops
        self._attendance_resolutions = attendance_resolutions

    async def build(self, period: DateRange) -> BastClosingSnapshot:
        view = await self._talentops.command_center(period)
        pending_requests = await self._attendance_resolutions.pending()
        pending = _pending_dates(pending_requests, period)
        pending_approvals = _pending_approvals(pending_requests, period)
        talents: list[BastTalentSnapshot] = []
        waiting = 0
        source_review_count = 0
        actionable_count = 0
        seen: set[str] = set()

        for item in view.attention:
            seen.add(item.employee_id)
            employee_pending = pending.get(item.employee_id, frozenset())
            actionable = _actionable_blockers(item, employee_pending)
            source_review = tuple(
                blocker for blocker in item.blockers if blocker.state is CheckState.NEEDS_REVIEW
            )
            is_waiting = bool(employee_pending) and not actionable and not source_review
            actionable_count += int(bool(actionable))
            waiting += int(is_waiting)
            source_review_count += int(bool(source_review) and not actionable)
            talents.append(
                BastTalentSnapshot(
                    employee_id=item.employee_id,
                    nrp=item.nrp,
                    name=item.name,
                    actionable=actionable,
                    waiting_pmo=is_waiting,
                    source_review=source_review,
                )
            )

        # A submitted correction carries evidence. The legacy completion rule
        # intentionally accepts evidence for Log 1 PAMA, so a Talent whose only
        # remaining state is a pending PMO correction can disappear from
        # ``view.attention``. Re-insert that factual WAITING_PMO state here so
        # closing summaries never misclassify it as COMPLETE.
        readiness_by_employee = {item.employee_id: item for item in view.readiness}
        for employee_id in pending:
            if employee_id in seen:
                continue
            readiness = readiness_by_employee.get(employee_id)
            if readiness is None:
                continue
            waiting += 1
            talents.append(
                BastTalentSnapshot(
                    employee_id=readiness.employee_id,
                    nrp=readiness.nrp,
                    name=readiness.name,
                    actionable=(),
                    waiting_pmo=True,
                    source_review=(),
                )
            )

        complete = max(
            view.summary.active_talents - actionable_count - waiting - source_review_count,
            0,
        )
        return BastClosingSnapshot(
            total_talents=view.summary.active_talents,
            complete=complete,
            need_talent_action=actionable_count,
            waiting_pmo=waiting,
            source_review=source_review_count,
            talents=tuple(talents),
            pending_approvals=pending_approvals,
        )
