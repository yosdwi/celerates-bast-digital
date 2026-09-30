from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

import pytest

from digital_bast.application.attendance_closing_policy import payroll_cycle
from digital_bast.application.celerates_campaigns import (
    AudienceMember,
    Campaign,
    CampaignError,
    CampaignLink,
    CampaignPolicy,
    CampaignState,
    CeleratesCampaignService,
    Recipient,
    RecipientState,
    blocker_fingerprint,
    compose_talent_message,
)
from digital_bast.application.talentops_followups import WhatsAppSendReceipt

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

    from digital_bast.application.attendance_closing_policy import PayrollCycle

# 10:00 WIB on a Monday -- inside the default 08-18 window.
NOW = datetime(2026, 9, 28, 3, 0, tzinfo=UTC)
PREFIX = "https://celerates.example"
DAY = date(2026, 9, 1)


class FakeStore:
    def __init__(self) -> None:
        self.campaigns: dict[UUID, Campaign] = {}
        self.recipients: dict[UUID, Recipient] = {}
        self.events: list[tuple[str, str]] = []
        self.killed = False
        self.recent: set[str] = set()

    async def create(self, campaign: Campaign, recipients: tuple[Recipient, ...]) -> None:
        self.campaigns[campaign.id] = campaign
        for item in recipients:
            self.recipients[item.id] = item

    async def get(self, campaign_id: UUID) -> tuple[Campaign, tuple[Recipient, ...]] | None:
        campaign = self.campaigns.get(campaign_id)
        if campaign is None:
            return None
        rows = tuple(r for r in self.recipients.values() if r.campaign_id == campaign_id)
        return campaign, tuple(sorted(rows, key=lambda r: r.name))

    async def save_campaign(self, campaign: Campaign, *, actor: str, event: str) -> None:
        self.campaigns[campaign.id] = campaign
        self.events.append((event, actor))

    async def save_recipient(self, recipient: Recipient, *, actor: str, event: str) -> None:
        self.recipients[recipient.id] = recipient
        self.events.append((event, actor))

    async def lease_due(self, now: datetime, lease_until: datetime) -> tuple[Campaign, ...]:
        due: list[Campaign] = []
        for campaign in list(self.campaigns.values()):
            if campaign.state is CampaignState.RUNNING and (
                campaign.next_dispatch_at is None or campaign.next_dispatch_at <= now
            ):
                leased = replace(campaign, next_dispatch_at=lease_until)
                self.campaigns[campaign.id] = leased
                due.append(leased)
        return tuple(due)

    async def claim(self, recipient_id: UUID) -> bool:
        item = self.recipients[recipient_id]
        if item.state not in {RecipientState.PENDING, RecipientState.FAILED_RETRYABLE}:
            return False
        self.recipients[recipient_id] = replace(item, state=RecipientState.SENDING)
        return True

    async def recover_interrupted(self, campaign_id: UUID) -> int:
        count = 0
        for key, item in list(self.recipients.items()):
            if item.campaign_id == campaign_id and item.state is RecipientState.SENDING:
                self.recipients[key] = replace(item, state=RecipientState.UNKNOWN)
                count += 1
        return count

    async def recent_send_exists(
        self, employee_id: str, since: datetime, exclude_campaign: UUID
    ) -> bool:
        del since, exclude_campaign
        return employee_id in self.recent

    async def kill_switch(self) -> bool:
        return self.killed


class FakeAudience:
    def __init__(self, members: dict[str, AudienceMember]) -> None:
        self.members = members

    async def audience(self, cycle: PayrollCycle) -> Mapping[str, AudienceMember]:
        del cycle
        return dict(self.members)


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


def member(
    employee_id: str, name: str, *, dates: tuple[date, ...] = (DAY,), bound: bool = True
) -> AudienceMember:
    return AudienceMember(employee_id, f"NRP{employee_id[-1]}", name, dates, bound)


def service(
    members: dict[str, AudienceMember],
    rand: Callable[[], float] | None = None,
) -> tuple[CeleratesCampaignService, FakeStore, FakeAudience, FakeGateway, list[float]]:
    store = FakeStore()
    audience = FakeAudience(members)
    gateway = FakeGateway()
    sleeps: list[float] = []

    async def sleep(seconds: float) -> None:
        sleeps.append(seconds)

    svc = CeleratesCampaignService(
        store,
        audience,
        FakeJids(),
        gateway,
        cycle_for=payroll_cycle,
        new_id=uuid4,
        sleep=sleep,
        rand=rand,
        allowed_link_prefix=PREFIX,
    )
    return svc, store, audience, gateway, sleeps


def links(*employee_ids: str) -> tuple[CampaignLink, ...]:
    return tuple(
        CampaignLink(item, f"{PREFIX}/go/{item[-1]}", NOW + timedelta(hours=72))
        for item in employee_ids
    )


async def started(
    members: dict[str, AudienceMember],
    policy: CampaignPolicy | None = None,
    linked: tuple[str, ...] | None = None,
) -> tuple[UUID, FakeStore, FakeAudience, FakeGateway, list[float], CeleratesCampaignService]:
    svc, store, audience, gateway, sleeps = service(members)
    campaign_id = await svc.create(
        payroll_cycle(2026, 9), policy or CampaignPolicy(), actor="pmo", now=NOW
    )
    await svc.approve(
        campaign_id,
        links(*(linked if linked is not None else tuple(members))),
        actor="lead",
        now=NOW,
    )
    return campaign_id, store, audience, gateway, sleeps, svc


def states(store: FakeStore) -> dict[str, RecipientState]:
    return {item.employee_id: item.state for item in store.recipients.values()}


async def test_audience_snapshot_marks_eligibility_and_a_draft_sends_nothing() -> None:
    svc, store, _, gateway, _ = service(
        {
            "E-1": member("E-1", "Ayu"),
            "E-UNBOUND": member("E-UNBOUND", "Budi", bound=False),
            "E-3": member("E-3", "Citra", dates=()),
        }
    )
    await svc.create(payroll_cycle(2026, 9), CampaignPolicy(), actor="pmo", now=NOW)
    assert {r.employee_id: r.eligibility for r in store.recipients.values()} == {
        "E-1": "eligible",
        "E-UNBOUND": "not_bound",
    }, "only Talent with an active blocker are in the snapshot"
    report = await svc.dispatch(now=lambda: NOW)
    assert report.campaigns == ()
    assert gateway.sent == [], "a draft campaign is never dispatched"


async def test_approval_rejects_foreign_links_and_marks_unlinked_recipients() -> None:
    svc, store, _, _, _ = service({"E-1": member("E-1", "Ayu"), "E-2": member("E-2", "Bima")})
    campaign_id = await svc.create(payroll_cycle(2026, 9), CampaignPolicy(), actor="pmo", now=NOW)
    with pytest.raises(CampaignError) as denied:
        await svc.approve(
            campaign_id,
            (CampaignLink("E-1", "https://evil.example/x", NOW + timedelta(hours=1)),),
            actor="lead",
            now=NOW,
        )
    assert denied.value.code == "link_not_allowed"
    with pytest.raises(CampaignError):
        await svc.approve(
            campaign_id,
            (CampaignLink("E-1", f"{PREFIX}/go/a", NOW + timedelta(days=8)),),
            actor="lead",
            now=NOW,
        )
    await svc.approve(campaign_id, links("E-1"), actor="lead", now=NOW)
    assert states(store)["E-2"] is RecipientState.SKIPPED_NO_ACCOUNT
    assert store.campaigns[campaign_id].approved_by == "lead"
    with pytest.raises(CampaignError):
        await svc.approve(campaign_id, links("E-1"), actor="lead", now=NOW)


async def test_bounded_batch_paces_sends_and_completes_over_ticks() -> None:
    members = {f"E-{i}": member(f"E-{i}", f"Talent {i}") for i in (1, 2, 3)}
    campaign_id, store, _, gateway, sleeps, svc = await started(
        members, CampaignPolicy(batch_size=2, min_interval_seconds=4, cooldown_seconds=600)
    )
    first = await svc.dispatch(now=lambda: NOW)
    assert [tick.sent for tick in first.campaigns] == [2]
    assert sleeps == [4], "one pause between the two sends of a batch"
    assert store.campaigns[campaign_id].next_dispatch_at == NOW + timedelta(seconds=600)
    assert (await svc.dispatch(now=lambda: NOW + timedelta(seconds=10))).campaigns == (), "cooldown"
    later = NOW + timedelta(seconds=601)
    second = await svc.dispatch(now=lambda: later)
    assert second.campaigns[0].sent == 1
    assert store.campaigns[campaign_id].state is CampaignState.COMPLETED
    assert len(gateway.sent) == 3
    assert {request for _, _, request in gateway.sent} == {
        f"celerates-campaign:{r.id}" for r in store.recipients.values()
    }, "a stable per-recipient request id makes a bridge retry idempotent"


async def test_outside_the_sending_window_nothing_is_sent() -> None:
    campaign_id, store, _, gateway, _, svc = await started({"E-1": member("E-1", "Ayu")})
    night = datetime(2026, 9, 28, 14, 0, tzinfo=UTC)  # 21:00 WIB
    await svc.dispatch(now=lambda: night)
    assert gateway.sent == []
    assert store.campaigns[campaign_id].next_dispatch_at == datetime(2026, 9, 29, 1, 0, tzinfo=UTC)


async def test_follow_up_only_while_the_blocker_is_active() -> None:
    campaign_id, store, audience, gateway, _, svc = await started(
        {"E-1": member("E-1", "Ayu"), "E-2": member("E-2", "Bima")}
    )
    audience.members["E-1"] = member("E-1", "Ayu", dates=())  # resolved after the snapshot
    await svc.dispatch(now=lambda: NOW)
    assert states(store)["E-1"] is RecipientState.SKIPPED_RESOLVED
    assert [jid for jid, _, _ in gateway.sent] == ["622@c.us"]
    assert store.campaigns[campaign_id].state is CampaignState.COMPLETED


async def test_recent_send_in_another_campaign_is_deduplicated() -> None:
    _, store, _, gateway, _, svc = await started({"E-1": member("E-1", "Ayu")})
    store.recent.add("E-1")
    await svc.dispatch(now=lambda: NOW)
    assert states(store)["E-1"] is RecipientState.SKIPPED_RECENT
    assert gateway.sent == []


async def test_transport_failure_auto_pauses_and_retry_is_limited() -> None:
    campaign_id, store, _, gateway, _, svc = await started(
        {"E-1": member("E-1", "Ayu"), "E-2": member("E-2", "Bima")},
        CampaignPolicy(max_attempts=2),
    )
    gateway.next = [WhatsAppSendReceipt("bridge_unavailable", error_code="whatsapp_not_connected")]
    report = await svc.dispatch(now=lambda: NOW)
    assert report.campaigns[0].pause_reason == "transport_unavailable"
    assert store.campaigns[campaign_id].state is CampaignState.PAUSED
    assert len(gateway.sent) == 1, "the batch stops at the first transport failure"
    assert states(store)["E-1"] is RecipientState.FAILED_RETRYABLE
    await svc.resume(campaign_id, actor="lead", now=NOW)
    gateway.next = [WhatsAppSendReceipt("bridge_unavailable", error_code="whatsapp_not_connected")]
    await svc.dispatch(now=lambda: NOW)
    assert states(store)["E-1"] is RecipientState.FAILED_FINAL, "max_attempts reached"


async def test_unknown_delivery_is_never_retried() -> None:
    campaign_id, store, _, gateway, _, svc = await started({"E-1": member("E-1", "Ayu")})
    gateway.next = [
        WhatsAppSendReceipt("bridge_unavailable", error_code="delivery_outcome_unknown")
    ]
    await svc.dispatch(now=lambda: NOW)
    assert states(store)["E-1"] is RecipientState.UNKNOWN
    assert store.campaigns[campaign_id].pause_reason == "delivery_unknown"
    await svc.resume(campaign_id, actor="lead", now=NOW)
    await svc.dispatch(now=lambda: NOW)
    assert len(gateway.sent) == 1


async def test_interrupted_send_claim_becomes_unknown_and_pauses() -> None:
    campaign_id, store, _, gateway, _, svc = await started({"E-1": member("E-1", "Ayu")})
    only = next(iter(store.recipients.values()))
    store.recipients[only.id] = replace(only, state=RecipientState.SENDING)
    await svc.dispatch(now=lambda: NOW)
    assert states(store)["E-1"] is RecipientState.UNKNOWN
    assert store.campaigns[campaign_id].state is CampaignState.PAUSED
    assert gateway.sent == []


async def test_kill_switch_stops_every_dispatch() -> None:
    _, store, _, gateway, _, svc = await started({"E-1": member("E-1", "Ayu")})
    store.killed = True
    report = await svc.dispatch(now=lambda: NOW)
    assert report.killed
    assert gateway.sent == []


async def test_pause_and_stop_are_explicit_and_audited() -> None:
    campaign_id, store, _, gateway, _, svc = await started({"E-1": member("E-1", "Ayu")})
    await svc.pause(campaign_id, actor="lead", reason="cek data")
    assert (await svc.dispatch(now=lambda: NOW)).campaigns == ()
    await svc.stop(campaign_id, actor="lead", now=NOW)
    assert states(store)["E-1"] is RecipientState.SKIPPED_STOPPED
    assert store.campaigns[campaign_id].state is CampaignState.STOPPED
    assert ("paused", "lead") in store.events
    assert ("stopped", "lead") in store.events
    assert gateway.sent == []


def test_talent_message_carries_only_the_opaque_link() -> None:
    text = compose_talent_message(
        name="Rina Synthetic",
        cycle_label="Payroll September 2026",
        dates=(date(2026, 9, 1), date(2026, 9, 2)),
        link=f"{PREFIX}/go/abc",
        deadline_year=2026,
        deadline_month=9,
    )
    assert text.startswith("Halo Rina,")
    assert "*Timesheet September 2026*" in text
    assert "- *Attendance:* 1, 2 Sep 2026" in text
    assert "Batas melengkapi: 2 Okt 2026, 12:00 WIB" in text
    assert f"{PREFIX}/go/abc" in text
    assert "MTG" not in text
    assert "@c.us" not in text


def task_member(
    employee_id: str, name: str, *, dates: tuple[date, ...] = (), tasks: tuple[str, ...] = ("t1",)
) -> AudienceMember:
    return AudienceMember(
        employee_id,
        f"NRP{employee_id[-1]}",
        name,
        dates,
        whatsapp_bound=True,
        missing_task_keys=tasks,
    )


async def test_audience_includes_tasks_without_evidence_and_fingerprints_both() -> None:
    svc, store, _, _, _ = service(
        {
            "E-1": task_member("E-1", "Ayu"),
            "E-2": task_member("E-2", "Bima", dates=(DAY,), tasks=()),
            "E-3": task_member("E-3", "Citra", tasks=()),
        }
    )
    _ = await svc.create(payroll_cycle(2026, 9), CampaignPolicy(), actor="pmo", now=NOW)
    rows = {r.employee_id: r for r in store.recipients.values()}
    assert set(rows) == {"E-1", "E-2"}, "attendance days OR tasks without evidence"
    assert (rows["E-1"].actionable_days, rows["E-1"].missing_tasks) == (0, 1)
    assert blocker_fingerprint((DAY,)) != blocker_fingerprint((DAY,), ("t1",))
    assert blocker_fingerprint((DAY,)) == rows["E-2"].blocker_fingerprint


async def test_blocker_recheck_at_dispatch_covers_tasks() -> None:
    _, store, audience, gateway, _, svc = await started(
        {
            "E-1": task_member("E-1", "Ayu", dates=(DAY,)),
            "E-2": task_member("E-2", "Bima", dates=(DAY,)),
        }
    )
    audience.members["E-1"] = task_member("E-1", "Ayu", tasks=())  # everything resolved
    audience.members["E-2"] = task_member("E-2", "Bima", tasks=("t1", "t2"))  # tasks still open
    _ = await svc.dispatch(now=lambda: NOW)
    assert states(store) == {"E-1": RecipientState.SKIPPED_RESOLVED, "E-2": RecipientState.SENT}
    [(_, text, _)] = gateway.sent
    assert text.startswith("Halo Bima,")
    assert "*Timesheet September 2026*" in text
    assert "- *Tasklist:* 2 task belum closed" in text


async def test_links_without_expiry_are_accepted_and_never_expire() -> None:
    svc, store, _, gateway, _ = service({"E-1": task_member("E-1", "Ayu", dates=(DAY,))})
    campaign_id = await svc.create(payroll_cycle(2026, 9), CampaignPolicy(), actor="pmo", now=NOW)
    await svc.approve(
        campaign_id, (CampaignLink("E-1", f"{PREFIX}/go/1", None),), actor="lead", now=NOW
    )
    later = NOW + timedelta(days=30)
    _ = await svc.dispatch(now=lambda: later)
    assert states(store)["E-1"] is RecipientState.SENT
    text = gateway.sent[0][1]
    assert "*Timesheet September 2026*" in text
    assert "- *Attendance:*" in text
    assert "- *Tasklist:* 1 task belum closed" in text, "the message mentions both counts"
    assert "Batas melengkapi: 2 Okt 2026, 12:00 WIB" in text, "fixed rule, not the link's expiry"


async def test_cooldown_jitter_extends_the_next_dispatch_by_a_random_amount() -> None:
    """batch_size=1 sends one recipient per tick; a fixed cooldown every tick would still be a
    predictable, blast-shaped pattern, so the next tick must land at a random offset."""
    policy = CampaignPolicy(batch_size=1, cooldown_seconds=7200, cooldown_jitter_seconds=3600)
    members = {"E-1": task_member("E-1", "Ayu", dates=(DAY,)), "E-2": task_member("E-2", "Bima")}

    async def next_dispatch_offset(rand: Callable[[], float]) -> float:
        svc, store, _, _, _ = service(members, rand=rand)
        campaign_id = await svc.create(payroll_cycle(2026, 9), policy, actor="pmo", now=NOW)
        await svc.approve(campaign_id, links("E-1", "E-2"), actor="lead", now=NOW)
        _ = await svc.dispatch(now=lambda: NOW)
        campaign = store.campaigns[campaign_id]
        assert campaign.state is CampaignState.RUNNING, "one recipient is still open"
        assert campaign.next_dispatch_at is not None
        return (campaign.next_dispatch_at - NOW).total_seconds()

    lowest = await next_dispatch_offset(lambda: 0.0)
    highest = await next_dispatch_offset(lambda: 1.0)
    assert lowest == 7200  # cooldown_seconds, no jitter added
    assert highest == 10800  # cooldown_seconds + cooldown_jitter_seconds, full jitter
    assert lowest != highest
