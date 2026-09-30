from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

import pytest

from digital_bast.application.attendance_closing_policy import payroll_cycle
from digital_bast.application.celerates_campaigns import AudienceMember
from digital_bast.application.celerates_direct_messages import (
    DIRECT_DEDUPE_WINDOW,
    CeleratesDirectMessageService,
    DirectMessage,
    DirectMessageError,
    DirectMessageResult,
    DirectMessageStatus,
)
from digital_bast.application.talentops_followups import WhatsAppSendReceipt

if TYPE_CHECKING:
    from digital_bast.application.attendance_closing_policy import PayrollCycle

NOW = datetime(2026, 9, 28, 14, 0, tzinfo=UTC)  # 21:00 WIB: outside any campaign window
PREFIX = "https://celerates.example"
CYCLE = payroll_cycle(2026, 9)


class FakeStore:
    def __init__(self) -> None:
        self.killed = False
        self.rows: dict[UUID, tuple[DirectMessage, DirectMessageStatus, str | None]] = {}
        self.sent_times: dict[str, datetime] = {}

    async def kill_switch(self) -> bool:
        return self.killed

    async def begin(self, message: DirectMessage, *, since: datetime) -> bool:
        for row, status, _ in self.rows.values():
            if (
                row.employee_id == message.employee_id
                and status is not DirectMessageStatus.FAILED
                and row.created_at >= since
            ):
                return False
        self.rows[message.id] = (message, DirectMessageStatus.SENDING, None)
        return True

    async def finish(
        self,
        message_id: UUID,
        status: DirectMessageStatus,
        *,
        provider_message_id: str | None,
        error: str | None,
        sent_at: datetime | None,
    ) -> None:
        del provider_message_id, sent_at
        message, _, _ = self.rows[message_id]
        self.rows[message_id] = (message, status, error)


class FakeItems:
    def __init__(self) -> None:
        self.members = {
            "E-1": AudienceMember(
                "E-1",
                "NRP1",
                "Rina Synthetic",
                (date(2026, 9, 1),),
                whatsapp_bound=True,
                missing_task_keys=("t1", "t2"),
            ),
            "E-2": AudienceMember("E-2", "NRP2", "Bima Synthetic", (), whatsapp_bound=True),
            "E-UNBOUND": AudienceMember("E-UNBOUND", "NRP3", "Citra", (), whatsapp_bound=False),
        }

    async def open_items(self, employee_id: str, cycle: PayrollCycle) -> AudienceMember | None:
        del cycle
        return self.members.get(employee_id)


class FakeJids:
    async def jid_for_employee(self, employee_id: str) -> str | None:
        return None if employee_id == "E-UNBOUND" else f"62{employee_id[-1]}@c.us"


class FakeGateway:
    def __init__(self) -> None:
        self.sent: list[tuple[str, str, str]] = []
        self.next: list[WhatsAppSendReceipt] = []

    async def send(self, jid: str, text: str, request_id: str) -> WhatsAppSendReceipt:
        self.sent.append((jid, text, request_id))
        return self.next.pop(0) if self.next else WhatsAppSendReceipt("sent", "msg-1")


class Clock:
    def __init__(self) -> None:
        self.now = NOW

    def __call__(self) -> datetime:
        return self.now


def build() -> tuple[CeleratesDirectMessageService, FakeStore, FakeGateway, Clock]:
    store, gateway, clock = FakeStore(), FakeGateway(), Clock()
    svc = CeleratesDirectMessageService(
        store,
        FakeItems(),
        FakeJids(),
        gateway,
        new_id=uuid4,
        clock=clock,
        allowed_link_prefix=PREFIX,
    )
    return svc, store, gateway, clock


async def send(svc: CeleratesDirectMessageService, employee_id: str = "E-1") -> DirectMessageResult:
    return await svc.send(
        employee_id, CYCLE, link_url=f"{PREFIX}/go/abc", link_expires_at=None, actor="pmo"
    )


async def code_of(svc: CeleratesDirectMessageService, employee_id: str = "E-1") -> str:
    with pytest.raises(DirectMessageError) as refused:
        _ = await send(svc, employee_id)
    return refused.value.code


async def test_sends_one_personal_message_outside_the_campaign_window() -> None:
    svc, store, gateway, _ = build()
    result = await svc.send(
        "E-1", CYCLE, link_url=f"{PREFIX}/go/abc", link_expires_at=None, actor="pmo"
    )
    assert result.status == "sent"
    assert result.sent_at == NOW
    [(jid, text, request_id)] = gateway.sent
    assert jid == "621@c.us"
    assert request_id == f"celerates-direct:{result.message_id}"
    assert text.startswith("Halo Rina,")
    assert "*Timesheet September 2026*" in text
    assert "- *Attendance:* 1 Sep 2026" in text
    assert "- *Tasklist:* 2 task belum closed" in text
    assert f"{PREFIX}/go/abc" in text
    assert "E-1" not in text
    assert "@c.us" not in text
    assert store.rows[result.message_id][1] is DirectMessageStatus.SENT


async def test_nothing_open_still_sends_the_link() -> None:
    svc, _, gateway, _ = build()
    _ = await send(svc, "E-2")
    text = gateway.sent[0][1]
    assert "sudah lengkap" in text
    assert f"{PREFIX}/go/abc" in text


async def test_checks_run_in_contract_order() -> None:
    svc, store, gateway, clock = build()
    store.killed = True
    assert await code_of(svc, "E-UNBOUND") == "kill_switch", "kill switch before binding"
    store.killed = False
    assert await code_of(svc, "E-UNBOUND") == "not_bound"
    assert await code_of(svc, "E-404") == "talent_not_found"
    _ = await send(svc)
    assert await code_of(svc) == "recently_sent"
    clock.now = NOW + DIRECT_DEDUPE_WINDOW + timedelta(seconds=1)
    _ = await send(svc)
    assert len(gateway.sent) == 2


async def test_link_prefix_and_past_expiry_are_rejected() -> None:
    svc, _, gateway, _ = build()
    with pytest.raises(DirectMessageError) as foreign:
        _ = await svc.send(
            "E-1", CYCLE, link_url="https://evil.example/x", link_expires_at=None, actor="pmo"
        )
    assert foreign.value.code == "link_not_allowed"
    with pytest.raises(DirectMessageError) as expired:
        _ = await svc.send(
            "E-1",
            CYCLE,
            link_url=f"{PREFIX}/go/a",
            link_expires_at=NOW - timedelta(minutes=1),
            actor="pmo",
        )
    assert expired.value.code == "invalid_link_expiry"
    assert gateway.sent == []


@pytest.mark.parametrize(
    ("receipt", "code", "retryable", "status"),
    [
        (
            WhatsAppSendReceipt("bridge_unavailable", error_code="whatsapp_not_connected"),
            "transport_unavailable",
            True,
            DirectMessageStatus.FAILED,
        ),
        (
            WhatsAppSendReceipt("failed", error_code="bridge_auth_failed"),
            "transport_auth_failed",
            False,
            DirectMessageStatus.FAILED,
        ),
        (
            WhatsAppSendReceipt("failed", error_code="bridge_http_400"),
            "delivery_failed",
            False,
            DirectMessageStatus.FAILED,
        ),
    ],
)
async def test_transport_failures_are_recorded_and_retry_is_allowed(
    receipt: WhatsAppSendReceipt, code: str, retryable: bool, status: DirectMessageStatus
) -> None:
    svc, store, gateway, _ = build()
    gateway.next = [receipt]
    with pytest.raises(DirectMessageError) as failed:
        _ = await send(svc)
    assert (failed.value.code, failed.value.retryable) == (code, retryable)
    assert [row[1] for row in store.rows.values()] == [status]
    _ = await send(svc)
    assert len(gateway.sent) == 2, "a failed attempt does not block the dedupe window"


async def test_unknown_delivery_is_reported_and_blocks_a_resend() -> None:
    svc, store, gateway, _ = build()
    gateway.next = [
        WhatsAppSendReceipt("bridge_unavailable", error_code="delivery_outcome_unknown")
    ]
    result = await send(svc)
    assert result.status == "unknown"
    assert [row[1] for row in store.rows.values()] == [DirectMessageStatus.UNKNOWN]
    assert await code_of(svc) == "recently_sent"
    assert len(gateway.sent) == 1
