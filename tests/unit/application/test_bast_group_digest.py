from __future__ import annotations

from datetime import UTC, date, datetime

from digital_bast.application.bast_closing import BastClosingSettings
from digital_bast.application.bast_group_digest import (
    BastGroupDigestRunSummary,
    BastGroupDigestService,
    BastWebLinks,
    compose_bast_group_digest,
)
from digital_bast.application.bast_snapshot import (
    BastClosingSnapshot,
    BastPendingApproval,
    BastTalentSnapshot,
)
from digital_bast.application.talentops import Blocker
from digital_bast.domain.completion import CheckState, DateRange

_PERIOD = DateRange(date(2026, 9, 1), date(2026, 9, 30))


class _Control:
    async def settings(self, scope_key: str) -> BastClosingSettings:
        assert scope_key == "default"
        return BastClosingSettings(
            scope_key="default",
            enabled=True,
            pmo_group_jid="120363000000000000@g.us",
        )


class _CaptureService(BastGroupDigestService):
    def __init__(self) -> None:
        super().__init__("default", _Control(), object(), object(), object())  # type: ignore[arg-type]
        self.call: dict[str, object] | None = None

    async def _deliver(
        self,
        period: DateRange,
        **kwargs: object,
    ) -> BastGroupDigestRunSummary:
        self.call = {"period": period, **kwargs}
        return BastGroupDigestRunSummary(
            enabled=True,
            due=True,
            milestone=str(kwargs["display_milestone"]),
            outcome="captured",
        )


def test_digest_is_pmo_action_briefing_with_clear_units_and_links() -> None:
    snapshot = BastClosingSnapshot(
        total_talents=3,
        complete=1,
        need_talent_action=1,
        waiting_pmo=1,
        source_review=0,
        talents=(
            BastTalentSnapshot(
                employee_id="EMP-1",
                nrp="1001",
                name="Talent One",
                actionable=(
                    Blocker(
                        "task",
                        CheckState.INCOMPLETE,
                        ('Task "API" belum Closed.', 'Task "Docs" belum Closed.'),
                    ),
                    Blocker(
                        "attendance",
                        CheckState.INCOMPLETE,
                        ("18 September — Clock Out belum terisi.",),
                    ),
                ),
                waiting_pmo=False,
                source_review=(),
            ),
        ),
        pending_approvals=(
            BastPendingApproval(
                request_id="REQ-1",
                employee_id="EMP-2",
                nrp="1002",
                name="Talent Two",
                work_date=date(2026, 9, 18),
                change="Clock Out → 17:31",
            ),
        ),
    )
    links = BastWebLinks(
        approval_url=(
            "https://bast.example.com/admin/talentops/actions?year=2026&month=9#approval-queue"
        ),
        readiness_url=(
            "https://bast.example.com/admin/talentops/bast-readiness?year=2026&month=9"
        ),
    )

    message = compose_bast_group_digest(snapshot, _PERIOD, "EOM-3", links)

    assert "Closing 30 Sep · H-3" in message
    assert "*Perlu tindakan PMO — 1 approval*" in message
    assert "Talent Two — 18 Sep — Clock Out → 17:31" in message
    assert links.approval_url in message
    assert "*Masih menunggu Talent — 1 orang*" in message
    assert "• 1 Talent: 2 Task Redmine belum Closed" in message
    assert "• 1 Talent: 1 tanggal attendance belum lengkap" in message
    assert "✅ Complete: 1 / 3" in message
    assert "🕒 Menunggu PMO: 1 Talent" in message
    assert links.readiness_url in message
    assert "Outstanding factual" not in message
    assert "• Task List:" not in message


async def test_manual_send_on_scheduled_date_consumes_same_slot_even_before_send_hour() -> None:
    service = _CaptureService()

    result = await service.send_manual(
        _PERIOD,
        "admin@example.com",
        datetime(2026, 9, 25, 1, 55, tzinfo=UTC),  # 08:55 WIB
    )

    assert result.milestone == "INITIAL"
    assert service.call is not None
    assert service.call["display_milestone"] == "INITIAL"
    assert service.call["delivery_milestone"] == "INITIAL"
    assert service.call["idempotency_key"] == "bast-digest:default:2026-09:INITIAL"


async def test_manual_send_outside_scheduled_date_is_unique_ad_hoc_batch() -> None:
    service = _CaptureService()

    result = await service.send_manual(
        _PERIOD,
        "admin@example.com",
        datetime(2026, 9, 22, 2, 0, tzinfo=UTC),
    )

    assert result.milestone == "MANUAL"
    assert service.call is not None
    assert str(service.call["delivery_milestone"]).startswith("MANUAL:")
    assert str(service.call["idempotency_key"]).startswith("bast-digest-manual:default:")
