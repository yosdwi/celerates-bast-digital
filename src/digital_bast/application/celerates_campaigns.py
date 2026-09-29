"""Governed Talent reminder campaigns requested by Celerates (integration v1).

Policy only: audience snapshot, eligibility, per-recipient dedupe, follow-up
only while the blocker is active, bounded batches, sending windows, pacing,
limited retry, approval, pause/resume/stop, kill switch and auto-pause on
transport failure. Persistence, readiness projection and the WhatsApp bridge
are ports, so no readiness or delivery rule is duplicated here.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime, time, timedelta
from enum import StrEnum
from typing import TYPE_CHECKING, Final, NoReturn, Protocol, final

from digital_bast.domain.completion import MONTH_NAMES
from digital_bast.domain.time import JAKARTA

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Mapping
    from uuid import UUID

    from digital_bast.application.attendance_closing_policy import PayrollCycle
    from digital_bast.application.talentops_followups import WhatsAppSendReceipt

RECENT_SEND_WINDOW: Final = timedelta(hours=20)
MAX_LINK_TTL: Final = timedelta(days=7)
TICK_LEASE: Final = timedelta(minutes=10)
_MONTHS: Final = (
    "Jan",
    "Feb",
    "Mar",
    "Apr",
    "Mei",
    "Jun",
    "Jul",
    "Agu",
    "Sep",
    "Okt",
    "Nov",
    "Des",
)
_DAYS: Final = ("Sen", "Sel", "Rab", "Kam", "Jum", "Sab", "Min")
_MAX_LISTED_DATES: Final = 5


class CampaignState(StrEnum):
    DRAFT = "draft"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    STOPPED = "stopped"


class RecipientState(StrEnum):
    PENDING = "pending"
    SENDING = "sending"
    SENT = "sent"
    FAILED_RETRYABLE = "failed_retryable"
    FAILED_FINAL = "failed_final"
    UNKNOWN = "unknown"
    SKIPPED_RESOLVED = "skipped_resolved"
    SKIPPED_RECENT = "skipped_recent"
    SKIPPED_LINK_EXPIRED = "skipped_link_expired"
    SKIPPED_NO_ACCOUNT = "skipped_no_account"
    SKIPPED_NOT_BOUND = "skipped_not_bound"
    SKIPPED_STOPPED = "skipped_stopped"


OPEN_RECIPIENT_STATES: Final = frozenset({RecipientState.PENDING, RecipientState.FAILED_RETRYABLE})


class CampaignError(Exception):
    """A request that the campaign's current state or policy does not allow."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(code, message)
        self.code: str = code
        self.message: str = message


def _refuse(code: str, message: str) -> NoReturn:
    raise CampaignError(code, message)


@dataclass(frozen=True, slots=True)
class CampaignPolicy:
    window_start_hour: int = 8
    window_end_hour: int = 18
    batch_size: int = 10
    cooldown_seconds: int = 600
    min_interval_seconds: int = 3
    max_attempts: int = 3

    def validate(self) -> None:
        if not (0 <= self.window_start_hour < self.window_end_hour <= 24):  # noqa: PLR2004
            _refuse("invalid_policy", "Sending window must be within 0-24 and non-empty")
        if not 1 <= self.batch_size <= 50:  # noqa: PLR2004
            _refuse("invalid_policy", "batch_size must be between 1 and 50")
        if not 60 <= self.cooldown_seconds <= 86400:  # noqa: PLR2004
            _refuse("invalid_policy", "cooldown_seconds must be between 60 and 86400")
        if not 0 <= self.min_interval_seconds <= 60:  # noqa: PLR2004
            _refuse("invalid_policy", "min_interval_seconds must be between 0 and 60")
        if not 1 <= self.max_attempts <= 5:  # noqa: PLR2004
            _refuse("invalid_policy", "max_attempts must be between 1 and 5")

    def in_window(self, now: datetime) -> bool:
        return self.window_start_hour <= now.astimezone(JAKARTA).hour < self.window_end_hour

    def next_window_start(self, now: datetime) -> datetime:
        local = now.astimezone(JAKARTA)
        start = datetime.combine(local.date(), time(self.window_start_hour), JAKARTA)
        if local.hour >= self.window_end_hour or start <= local:
            start += timedelta(days=1)
        return start


@dataclass(frozen=True, slots=True)
class Campaign:
    id: UUID
    cycle_id: str
    cycle_year: int
    cycle_month: int
    cycle_label: str
    state: CampaignState
    policy: CampaignPolicy
    created_by: str
    created_at: datetime
    next_dispatch_at: datetime | None = None
    pause_reason: str | None = None
    approved_by: str | None = None
    approved_at: datetime | None = None
    finished_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class Recipient:
    id: UUID
    campaign_id: UUID
    employee_id: str
    nrp: str
    name: str
    eligibility: str
    actionable_days: int
    blocker_fingerprint: str
    state: RecipientState = RecipientState.PENDING
    link_url: str | None = None
    link_expires_at: datetime | None = None
    attempt_count: int = 0
    last_error: str | None = None
    provider_message_id: str | None = None
    sent_at: datetime | None = None
    missing_tasks: int = 0


@dataclass(frozen=True, slots=True)
class AudienceMember:
    employee_id: str
    nrp: str
    name: str
    actionable_dates: tuple[date, ...]
    whatsapp_bound: bool
    # Closed tasks in the cycle's calendar month (year, month) without evidence.
    missing_task_keys: tuple[str, ...] = ()

    @property
    def has_blocker(self) -> bool:
        return bool(self.actionable_dates or self.missing_task_keys)


@dataclass(frozen=True, slots=True)
class CampaignLink:
    employee_id: str
    url: str
    # None: the link never expires by time (Celerates enforces single use).
    expires_at: datetime | None


@dataclass(frozen=True, slots=True)
class RecipientOutcome:
    recipient_id: UUID
    state: RecipientState
    error: str | None = None


@dataclass(frozen=True, slots=True)
class CampaignTick:
    campaign_id: UUID
    sent: int = 0
    skipped: int = 0
    failed: int = 0
    state: CampaignState = CampaignState.RUNNING
    pause_reason: str | None = None
    outcomes: tuple[RecipientOutcome, ...] = ()


@dataclass(frozen=True, slots=True)
class DispatchReport:
    killed: bool = False
    campaigns: tuple[CampaignTick, ...] = field(default_factory=tuple)


class AudienceReader(Protocol):
    async def audience(self, cycle: PayrollCycle) -> Mapping[str, AudienceMember]: ...


class CampaignStore(Protocol):
    async def create(self, campaign: Campaign, recipients: tuple[Recipient, ...]) -> None: ...

    async def get(self, campaign_id: UUID) -> tuple[Campaign, tuple[Recipient, ...]] | None: ...

    async def save_campaign(self, campaign: Campaign, *, actor: str, event: str) -> None: ...

    async def save_recipient(self, recipient: Recipient, *, actor: str, event: str) -> None: ...

    async def lease_due(self, now: datetime, lease_until: datetime) -> tuple[Campaign, ...]: ...

    async def claim(self, recipient_id: UUID) -> bool: ...

    async def recover_interrupted(self, campaign_id: UUID) -> int: ...

    async def recent_send_exists(
        self, employee_id: str, since: datetime, exclude_campaign: UUID
    ) -> bool: ...

    async def kill_switch(self) -> bool: ...


class JidResolver(Protocol):
    async def jid_for_employee(self, employee_id: str) -> str | None: ...


class OutboundGateway(Protocol):
    async def send(self, jid: str, text: str, request_id: str) -> WhatsAppSendReceipt: ...


def blocker_fingerprint(dates: tuple[date, ...], task_keys: tuple[str, ...] = ()) -> str:
    joined = ",".join(sorted(item.isoformat() for item in dates))
    if task_keys:
        joined += "|tasks:" + ",".join(sorted(task_keys))
    return hashlib.sha256(joined.encode()).hexdigest()[:32]


def calendar_month_label(year: int, month: int) -> str:
    return f"{MONTH_NAMES[month - 1]} {year}"


def _short_date(value: date) -> str:
    return f"{_DAYS[value.weekday()]} {value.day} {_MONTHS[value.month - 1]}"


def _expiry_label(value: datetime) -> str:
    local = value.astimezone(JAKARTA)
    return f"{local.day} {_MONTHS[local.month - 1]} {local:%H:%M} WIB"


def compose_talent_message(  # noqa: PLR0913 - keyword-only message facts
    *,
    name: str,
    cycle_label: str,
    dates: tuple[date, ...],
    link: str,
    expires_at: datetime | None,
    missing_tasks: int = 0,
    task_month_label: str | None = None,
) -> str:
    """Personal DM. Carries only an opaque Celerates link -- no ids or phone numbers."""
    first = name.split(maxsplit=1)[0] if name.strip() else "Talent"
    ordered = sorted(dates)
    month = task_month_label or "ini"
    tasks = f"{missing_tasks} task bulan {month} yang belum ada evidence-nya"
    if ordered:
        listed = ", ".join(_short_date(item) for item in ordered[:_MAX_LISTED_DATES])
        more = (
            f" dan {len(ordered) - _MAX_LISTED_DATES} lainnya"
            if len(ordered) > _MAX_LISTED_DATES
            else ""
        )
        opening = (
            f"Halo {first}, ada {len(ordered)} hari attendance periode {cycle_label} "
            f"yang perlu dilengkapi ({listed}{more})"
        )
        opening += f", dan {tasks}.\n" if missing_tasks > 0 else ".\n"
    elif missing_tasks > 0:
        opening = f"Halo {first}, ada {tasks}.\n"
    else:
        done = f" dan task bulan {task_month_label}" if task_month_label else ""
        return (
            f"Halo {first}, attendance periode {cycle_label}{done} sudah lengkap. "
            "Terima kasih!\n"
            f"Cek di Celerates: {link}\n"
            f"{_link_note(expires_at)}"
        )
    return (
        f"{opening}"
        f"Lengkapi di Celerates: {link}\n"
        f"{_link_note(expires_at)} Abaikan pesan ini bila sudah dilengkapi."
    )


def _link_note(expires_at: datetime | None) -> str:
    if expires_at is None:
        return "Tautan pribadi, jangan dibagikan."
    return f"Tautan pribadi, berlaku sampai {_expiry_label(expires_at)}."


@final
class CeleratesCampaignService:
    def __init__(  # noqa: PLR0913
        self,
        store: CampaignStore,
        audience: AudienceReader,
        jids: JidResolver,
        gateway: OutboundGateway,
        *,
        cycle_for: Callable[[int, int], PayrollCycle],
        new_id: Callable[[], UUID],
        sleep: Callable[[float], Awaitable[None]],
        allowed_link_prefix: str | None = None,
    ) -> None:
        self._store = store
        self._audience = audience
        self._jids = jids
        self._gateway = gateway
        self._cycle_for = cycle_for
        self._new_id = new_id
        self._sleep = sleep
        self._allowed_prefix = allowed_link_prefix

    async def create(
        self,
        cycle: PayrollCycle,
        policy: CampaignPolicy,
        *,
        actor: str,
        now: datetime,
    ) -> UUID:
        policy.validate()
        members = await self._audience.audience(cycle)
        campaign = Campaign(
            id=self._new_id(),
            cycle_id=cycle.cycle_id,
            cycle_year=cycle.label_year,
            cycle_month=cycle.label_month,
            cycle_label=cycle.label,
            state=CampaignState.DRAFT,
            policy=policy,
            created_by=actor,
            created_at=now,
        )
        recipients = tuple(
            Recipient(
                id=self._new_id(),
                campaign_id=campaign.id,
                employee_id=member.employee_id,
                nrp=member.nrp,
                name=member.name,
                eligibility="eligible" if member.whatsapp_bound else "not_bound",
                actionable_days=len(member.actionable_dates),
                blocker_fingerprint=blocker_fingerprint(
                    member.actionable_dates, member.missing_task_keys
                ),
                missing_tasks=len(member.missing_task_keys),
            )
            for member in sorted(members.values(), key=lambda item: (item.name, item.employee_id))
            if member.has_blocker
        )
        await self._store.create(campaign, recipients)
        return campaign.id

    async def _require(self, campaign_id: UUID) -> tuple[Campaign, tuple[Recipient, ...]]:
        found = await self._store.get(campaign_id)
        if found is None:
            _refuse("campaign_not_found", "Campaign not found")
        return found

    async def approve(
        self,
        campaign_id: UUID,
        links: tuple[CampaignLink, ...],
        *,
        actor: str,
        now: datetime,
    ) -> None:
        campaign, recipients = await self._require(campaign_id)
        if campaign.state is not CampaignState.DRAFT:
            _refuse("invalid_state", "Only a draft campaign can be approved")
        by_employee = {link.employee_id: link for link in links}
        known = {item.employee_id for item in recipients}
        unknown = set(by_employee) - known
        if unknown:
            _refuse("unknown_recipient", "A link names a Talent outside the audience")
        for link in links:
            if self._allowed_prefix and not link.url.startswith(self._allowed_prefix):
                _refuse("link_not_allowed", "Link is outside the Celerates public URL")
            if link.expires_at is not None and not now < link.expires_at <= now + MAX_LINK_TTL:
                _refuse("invalid_link_expiry", "Link expiry must be within 7 days")
        for recipient in recipients:
            link = by_employee.get(recipient.employee_id)
            if recipient.eligibility != "eligible":
                updated = replace(recipient, state=RecipientState.SKIPPED_NOT_BOUND)
            elif link is None:
                updated = replace(recipient, state=RecipientState.SKIPPED_NO_ACCOUNT)
            else:
                updated = replace(recipient, link_url=link.url, link_expires_at=link.expires_at)
            await self._store.save_recipient(updated, actor=actor, event="recipient_prepared")
        await self._store.save_campaign(
            replace(
                campaign,
                state=CampaignState.RUNNING,
                approved_by=actor,
                approved_at=now,
                next_dispatch_at=now,
            ),
            actor=actor,
            event="approved",
        )

    async def pause(self, campaign_id: UUID, *, actor: str, reason: str | None) -> None:
        campaign, _ = await self._require(campaign_id)
        if campaign.state is not CampaignState.RUNNING:
            _refuse("invalid_state", "Only a running campaign can be paused")
        await self._store.save_campaign(
            replace(campaign, state=CampaignState.PAUSED, pause_reason=reason or "paused_by_pmo"),
            actor=actor,
            event="paused",
        )

    async def resume(self, campaign_id: UUID, *, actor: str, now: datetime) -> None:
        campaign, _ = await self._require(campaign_id)
        if campaign.state is not CampaignState.PAUSED:
            _refuse("invalid_state", "Only a paused campaign can be resumed")
        await self._store.save_campaign(
            replace(campaign, state=CampaignState.RUNNING, pause_reason=None, next_dispatch_at=now),
            actor=actor,
            event="resumed",
        )

    async def stop(self, campaign_id: UUID, *, actor: str, now: datetime) -> None:
        campaign, recipients = await self._require(campaign_id)
        if campaign.state in {CampaignState.COMPLETED, CampaignState.STOPPED}:
            _refuse("invalid_state", "Campaign already finished")
        for recipient in recipients:
            if recipient.state in OPEN_RECIPIENT_STATES:
                await self._store.save_recipient(
                    replace(recipient, state=RecipientState.SKIPPED_STOPPED),
                    actor=actor,
                    event="recipient_stopped",
                )
        await self._store.save_campaign(
            replace(campaign, state=CampaignState.STOPPED, finished_at=now),
            actor=actor,
            event="stopped",
        )

    async def dispatch(
        self, *, now: Callable[[], datetime], actor: str = "dispatcher"
    ) -> DispatchReport:
        """One scheduler tick. Sends at most `batch_size` per leased running campaign."""
        if await self._store.kill_switch():
            return DispatchReport(killed=True)
        started = now()
        due = await self._store.lease_due(started, started + TICK_LEASE)
        ticks = [await self._tick(campaign, now=now, actor=actor) for campaign in due]
        return DispatchReport(killed=False, campaigns=tuple(ticks))

    async def _finish(  # noqa: PLR0913
        self,
        campaign: Campaign,
        *,
        actor: str,
        at: datetime,
        next_at: datetime,
        pause_reason: str | None,
        tick: CampaignTick,
    ) -> CampaignTick:
        found = await self._store.get(campaign.id)
        recipients = found[1] if found else ()
        open_left = any(item.state in OPEN_RECIPIENT_STATES for item in recipients)
        if pause_reason is not None:
            state, event = CampaignState.PAUSED, "auto_paused"
        elif not open_left:
            state, event = CampaignState.COMPLETED, "completed"
        else:
            state, event = CampaignState.RUNNING, "tick"
        await self._store.save_campaign(
            replace(
                campaign,
                state=state,
                pause_reason=pause_reason,
                next_dispatch_at=next_at if state is CampaignState.RUNNING else None,
                finished_at=at if state is CampaignState.COMPLETED else None,
            ),
            actor=actor,
            event=event,
        )
        return replace(tick, state=state, pause_reason=pause_reason)

    async def _tick(  # noqa: C901, PLR0912, PLR0915
        self,
        campaign: Campaign,
        *,
        now: Callable[[], datetime],
        actor: str,
    ) -> CampaignTick:
        policy = campaign.policy
        started = now()
        tick = CampaignTick(campaign_id=campaign.id)
        if not policy.in_window(started):
            return await self._finish(
                campaign,
                actor=actor,
                at=started,
                next_at=policy.next_window_start(started),
                pause_reason=None,
                tick=tick,
            )
        interrupted = await self._store.recover_interrupted(campaign.id)
        if interrupted:
            return await self._finish(
                campaign,
                actor=actor,
                at=started,
                next_at=started,
                pause_reason="delivery_unknown",
                tick=tick,
            )
        found = await self._store.get(campaign.id)
        recipients = found[1] if found else ()
        batch = [item for item in recipients if item.state in OPEN_RECIPIENT_STATES][
            : policy.batch_size
        ]
        members = await self._audience.audience(
            self._cycle_for(campaign.cycle_year, campaign.cycle_month)
        )
        outcomes: list[RecipientOutcome] = []
        pause_reason: str | None = None
        sent = skipped = failed = 0
        for index, recipient in enumerate(batch):
            moment = now()
            if not policy.in_window(moment):
                break
            member = members.get(recipient.employee_id)
            skip: RecipientState | None = None
            if member is None or not member.has_blocker:
                skip = RecipientState.SKIPPED_RESOLVED
            elif recipient.link_url is None:
                skip = RecipientState.SKIPPED_NO_ACCOUNT
            elif recipient.link_expires_at is not None and recipient.link_expires_at <= moment:
                skip = RecipientState.SKIPPED_LINK_EXPIRED
            elif await self._store.recent_send_exists(
                recipient.employee_id, moment - RECENT_SEND_WINDOW, campaign.id
            ):
                skip = RecipientState.SKIPPED_RECENT
            jid = None if skip else await self._jids.jid_for_employee(recipient.employee_id)
            if skip is None and jid is None:
                skip = RecipientState.SKIPPED_NOT_BOUND
            if skip is not None or member is None or jid is None:
                state = skip or RecipientState.SKIPPED_RESOLVED
                await self._store.save_recipient(
                    replace(recipient, state=state), actor=actor, event="recipient_skipped"
                )
                outcomes.append(RecipientOutcome(recipient.id, state))
                skipped += 1
                continue
            if not await self._store.claim(recipient.id):
                continue
            text = compose_talent_message(
                name=recipient.name,
                cycle_label=campaign.cycle_label,
                dates=member.actionable_dates,
                link=recipient.link_url or "",
                expires_at=recipient.link_expires_at,
                missing_tasks=len(member.missing_task_keys),
                task_month_label=calendar_month_label(campaign.cycle_year, campaign.cycle_month),
            )
            receipt = await self._gateway.send(jid, text, f"celerates-campaign:{recipient.id}")
            attempts = recipient.attempt_count + 1
            error = receipt.error_code
            if receipt.status == "sent":
                state = RecipientState.SENT
                sent += 1
            elif receipt.status == "bridge_unavailable" and error == "delivery_outcome_unknown":
                state, pause_reason = RecipientState.UNKNOWN, "delivery_unknown"
                failed += 1
            elif receipt.status == "bridge_unavailable":
                state = (
                    RecipientState.FAILED_FINAL
                    if attempts >= policy.max_attempts
                    else RecipientState.FAILED_RETRYABLE
                )
                pause_reason = "transport_unavailable"
                failed += 1
            elif error == "bridge_auth_failed":
                state, pause_reason = RecipientState.FAILED_RETRYABLE, "transport_auth_failed"
                failed += 1
            else:
                state = RecipientState.FAILED_FINAL
                failed += 1
            await self._store.save_recipient(
                replace(
                    recipient,
                    state=state,
                    attempt_count=attempts,
                    last_error=error,
                    provider_message_id=receipt.provider_message_id,
                    sent_at=moment if state is RecipientState.SENT else recipient.sent_at,
                    blocker_fingerprint=blocker_fingerprint(
                        member.actionable_dates, member.missing_task_keys
                    ),
                    actionable_days=len(member.actionable_dates),
                    missing_tasks=len(member.missing_task_keys),
                ),
                actor=actor,
                event=f"recipient_{state.value}",
            )
            outcomes.append(RecipientOutcome(recipient.id, state, error))
            if pause_reason is not None:
                break
            if index < len(batch) - 1 and policy.min_interval_seconds:
                await self._sleep(policy.min_interval_seconds)
        finished_at = now()
        return await self._finish(
            campaign,
            actor=actor,
            at=finished_at,
            next_at=finished_at + timedelta(seconds=policy.cooldown_seconds),
            pause_reason=pause_reason,
            tick=replace(tick, sent=sent, skipped=skipped, failed=failed, outcomes=tuple(outcomes)),
        )


def utc_now() -> datetime:
    return datetime.now(UTC)
