"""Factual BAST closing snapshot used by scheduled and manual reminders."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol, final

from digital_bast.application.talentops import Blocker
from digital_bast.domain.completion import CheckState

if TYPE_CHECKING:
    from digital_bast.application.talentops import AttentionItem, TalentOpsService
    from digital_bast.domain.completion import DateRange


class PendingAttendanceSource(Protocol):
    async def pending(self) -> tuple[object, ...]: ...


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


def _pending_nrps(requests: tuple[object, ...]) -> frozenset[str]:
    values: set[str] = set()
    for request in requests:
        nrp = getattr(request, "nrp", None)
        if isinstance(nrp, str) and nrp.strip():
            values.add(nrp.strip().casefold())
    return frozenset(values)


def _actionable_blockers(item: AttentionItem, attendance_pending: bool) -> tuple[Blocker, ...]:
    result: list[Blocker] = []
    for blocker in item.blockers:
        if blocker.state is not CheckState.INCOMPLETE:
            continue
        if attendance_pending and blocker.domain == "attendance":
            continue
        if attendance_pending and blocker.domain == "timesheet":
            remaining = tuple(
                issue for issue in blocker.issues if "Log 1 PAMA belum valid" not in issue
            )
            if not remaining:
                continue
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
        pending = _pending_nrps(await self._attendance_resolutions.pending())
        talents: list[BastTalentSnapshot] = []
        waiting = 0
        source_review_count = 0
        actionable_count = 0

        for item in view.attention:
            attendance_pending = item.nrp.strip().casefold() in pending
            actionable = _actionable_blockers(item, attendance_pending)
            source_review = tuple(
                blocker for blocker in item.blockers if blocker.state is CheckState.NEEDS_REVIEW
            )
            is_waiting = attendance_pending and not actionable and not source_review
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

        complete = max(view.summary.active_talents - len(view.attention), 0)
        return BastClosingSnapshot(
            total_talents=view.summary.active_talents,
            complete=complete,
            need_talent_action=actionable_count,
            waiting_pmo=waiting,
            source_review=source_review_count,
            talents=tuple(talents),
        )
