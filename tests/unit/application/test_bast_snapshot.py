from __future__ import annotations

from datetime import date
from types import SimpleNamespace

from digital_bast.application.bast_snapshot import BastClosingSnapshotService
from digital_bast.application.talentops import Blocker
from digital_bast.domain.completion import CheckState, DateRange

_PERIOD = DateRange(date(2026, 9, 1), date(2026, 9, 30))


class _TalentOps:
    def __init__(self, view: object) -> None:
        self.view = view

    async def command_center(self, period: DateRange) -> object:
        assert period == _PERIOD
        return self.view


class _Pending:
    def __init__(self, rows: tuple[object, ...]) -> None:
        self.rows = rows

    async def pending(self) -> tuple[object, ...]:
        return self.rows


def _view(*, attention: tuple[object, ...], readiness: tuple[object, ...], total: int = 1) -> object:
    return SimpleNamespace(
        attention=attention,
        readiness=readiness,
        summary=SimpleNamespace(active_talents=total),
    )


async def test_pending_one_date_does_not_hide_other_attendance_gap() -> None:
    attendance = Blocker(
        "attendance",
        CheckState.INCOMPLETE,
        (
            "1 September — Clock Out belum terisi dan Evidence Attendance belum tersedia.",
            "15 September — Clock In belum terisi dan Evidence Attendance belum tersedia.",
        ),
    )
    item = SimpleNamespace(
        employee_id="EMP-1",
        nrp="1001",
        name="Talent One",
        blockers=(attendance,),
    )
    readiness = SimpleNamespace(employee_id="EMP-1", nrp="1001", name="Talent One")
    pending = SimpleNamespace(employee_id="EMP-1", work_date=date(2026, 9, 1))
    service = BastClosingSnapshotService(
        _TalentOps(_view(attention=(item,), readiness=(readiness,))),
        _Pending((pending,)),
    )

    snapshot = await service.build(_PERIOD)

    assert snapshot.need_talent_action == 1
    assert snapshot.waiting_pmo == 0
    assert snapshot.complete == 0
    assert len(snapshot.talents) == 1
    assert snapshot.talents[0].actionable[0].issues == (
        "15 September — Clock In belum terisi dan Evidence Attendance belum tersedia.",
    )


async def test_pending_only_talent_is_not_misclassified_complete() -> None:
    readiness = SimpleNamespace(employee_id="EMP-1", nrp="1001", name="Talent One")
    pending = SimpleNamespace(employee_id="EMP-1", work_date=date(2026, 9, 18))
    service = BastClosingSnapshotService(
        _TalentOps(_view(attention=(), readiness=(readiness,))),
        _Pending((pending,)),
    )

    snapshot = await service.build(_PERIOD)

    assert snapshot.need_talent_action == 0
    assert snapshot.waiting_pmo == 1
    assert snapshot.complete == 0
    assert snapshot.talents[0].waiting_pmo is True
    assert snapshot.talents[0].actionable == ()


async def test_source_review_is_separate_from_talent_action() -> None:
    item = SimpleNamespace(
        employee_id="EMP-1",
        nrp="1001",
        name="Talent One",
        blockers=(
            Blocker(
                "task",
                CheckState.NEEDS_REVIEW,
                ("Belum ada Task List pada periode.",),
            ),
        ),
    )
    readiness = SimpleNamespace(employee_id="EMP-1", nrp="1001", name="Talent One")
    service = BastClosingSnapshotService(
        _TalentOps(_view(attention=(item,), readiness=(readiness,))),
        _Pending(()),
    )

    snapshot = await service.build(_PERIOD)

    assert snapshot.need_talent_action == 0
    assert snapshot.waiting_pmo == 0
    assert snapshot.source_review == 1
    assert snapshot.complete == 0
    assert snapshot.talents[0].source_review[0].domain == "task"
