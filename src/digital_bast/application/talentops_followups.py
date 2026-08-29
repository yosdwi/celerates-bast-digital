from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Literal, Protocol, cast, final

if TYPE_CHECKING:
    from digital_bast.application.talentops import RosterSource, TalentDetailView, TalentOpsService
    from digital_bast.application.talentops_ai import TalentOpsAiService
    from digital_bast.domain.completion import DateRange

FollowUpSource = Literal["deterministic", "ai", "edited"]
FollowUpStatus = Literal["sent", "not_bound", "bridge_unavailable", "failed", "no_blockers"]
_VALID_STATUSES = frozenset({"sent", "not_bound", "bridge_unavailable", "failed", "no_blockers"})


@dataclass(frozen=True, slots=True)
class WhatsAppSendReceipt:
    status: Literal["sent", "bridge_unavailable", "failed"]
    provider_message_id: str | None = None
    error_code: str | None = None


@dataclass(frozen=True, slots=True)
class FollowUpRecord:
    id: str
    idempotency_key: str
    employee_id: str
    period_start: str
    period_end: str
    channel: str
    message: str
    source: str
    status: str
    provider_message_id: str | None
    created_by: str
    created_at: datetime
    sent_at: datetime | None
    error_code: str | None


@dataclass(frozen=True, slots=True)
class FollowUpDraftView:
    nrp: str
    name: str
    whatsapp_bound: bool
    message: str
    source: FollowUpSource
    last_follow_up: FollowUpRecord | None


@dataclass(frozen=True, slots=True)
class FollowUpSendView:
    status: FollowUpStatus
    delivery_id: str | None
    provider_message_id: str | None
    sent_at: datetime | None
    error_code: str | None
    duplicate: bool = False


@dataclass(frozen=True, slots=True)
class FollowUpSendCommand:
    period: DateRange
    nrp: str
    message: str
    idempotency_key: str
    created_by: str
    source: FollowUpSource


@dataclass(frozen=True, slots=True)
class FollowUpWrite:
    idempotency_key: str
    employee_id: str
    period: DateRange
    message: str
    source: FollowUpSource
    status: FollowUpStatus
    provider_message_id: str | None
    created_by: str
    sent_at: datetime | None
    error_code: str | None


class WhatsAppIdentityResolver(Protocol):
    async def jid_for_employee(self, employee_id: str) -> str | None: ...


class WhatsAppOutboundGateway(Protocol):
    async def send(self, jid: str, text: str, request_id: str) -> WhatsAppSendReceipt: ...


class FollowUpRepository(Protocol):
    async def by_idempotency(self, idempotency_key: str) -> FollowUpRecord | None: ...

    async def latest_for_employee(self, employee_id: str) -> FollowUpRecord | None: ...

    async def record(self, write: FollowUpWrite) -> FollowUpRecord: ...


def _known_status(value: str) -> FollowUpStatus:
    return cast("FollowUpStatus", value if value in _VALID_STATUSES else "failed")


def _deterministic_draft(view: TalentDetailView) -> str:
    if not view.blockers:
        return (
            f"Halo {view.name}, untuk periode {view.period.label} saat ini tidak ada blocker "
            "readiness yang perlu ditindaklanjuti."
        )
    items: list[str] = []
    labels = {
        "attendance": "Attendance",
        "timesheet": "Timesheet",
        "task": "Task List",
        "evidence": "Evidence",
    }
    for blocker in view.blockers:
        label = labels.get(blocker.domain, blocker.domain.title())
        if blocker.issues:
            detail = "; ".join(blocker.issues[:2])
            items.append(f"{label}: {detail}")
        else:
            items.append(f"{label}: perlu direview")
    joined = " | ".join(items)
    return (
        f"Halo {view.name}, untuk kesiapan BAST periode {view.period.label} masih ada item "
        f"yang perlu dicek: {joined}. Mohon direview dan dilengkapi jika sudah ada datanya. "
        "Terima kasih."
    )


@final
class TalentOpsFollowUpService:
    def __init__(  # noqa: PLR0913, PLR0917 - explicit ports keep side effects visible
        self,
        talentops: TalentOpsService,
        roster: RosterSource,
        identities: WhatsAppIdentityResolver,
        outbound: WhatsAppOutboundGateway,
        repository: FollowUpRepository,
        ai: TalentOpsAiService | None = None,
    ) -> None:
        self._talentops = talentops
        self._roster = roster
        self._identities = identities
        self._outbound = outbound
        self._repository = repository
        self._ai = ai

    async def draft(self, period: DateRange, nrp: str) -> FollowUpDraftView | None:
        resolved = await self._resolve(period, nrp)
        if resolved is None:
            return None
        employee_id, view = resolved
        jid = await self._identities.jid_for_employee(employee_id)
        message = _deterministic_draft(view)
        source: FollowUpSource = "deterministic"
        if view.blockers and self._ai is not None:
            generated = await self._ai.draft_follow_up(view)
            if generated is not None and generated.strip():
                message = generated.strip()
                source = "ai"
        return FollowUpDraftView(
            nrp=view.nrp,
            name=view.name,
            whatsapp_bound=jid is not None,
            message=message,
            source=source,
            last_follow_up=await self._repository.latest_for_employee(employee_id),
        )

    async def send(self, command: FollowUpSendCommand) -> FollowUpSendView | None:
        previous = await self._repository.by_idempotency(command.idempotency_key)
        # A successful delivery is immutable/idempotent. Failed bridge attempts
        # may retry with the same key on a later worker cycle; the repository
        # upserts that delivery record instead of creating a second logical send.
        if previous is not None and previous.status == "sent":
            return FollowUpSendView(
                status="sent",
                delivery_id=previous.id,
                provider_message_id=previous.provider_message_id,
                sent_at=previous.sent_at,
                error_code=previous.error_code,
                duplicate=True,
            )

        resolved = await self._resolve(command.period, command.nrp)
        if resolved is None:
            return None
        employee_id, view = resolved
        if not view.blockers:
            return FollowUpSendView(
                status="no_blockers",
                delivery_id=None,
                provider_message_id=None,
                sent_at=None,
                error_code="no_current_blockers",
            )

        jid = await self._identities.jid_for_employee(employee_id)
        if jid is None:
            return FollowUpSendView(
                status="not_bound",
                delivery_id=None,
                provider_message_id=None,
                sent_at=None,
                error_code="whatsapp_identity_not_bound",
            )

        message = command.message.strip()
        receipt = await self._outbound.send(jid, message, command.idempotency_key)
        status: FollowUpStatus = receipt.status
        sent_at = datetime.now(UTC) if status == "sent" else None
        stored = await self._repository.record(
            FollowUpWrite(
                idempotency_key=command.idempotency_key,
                employee_id=employee_id,
                period=command.period,
                message=message,
                source=command.source,
                status=status,
                provider_message_id=receipt.provider_message_id,
                created_by=command.created_by,
                sent_at=sent_at,
                error_code=receipt.error_code,
            )
        )
        return FollowUpSendView(
            status=status,
            delivery_id=stored.id,
            provider_message_id=stored.provider_message_id,
            sent_at=stored.sent_at,
            error_code=stored.error_code,
        )

    async def _resolve(
        self,
        period: DateRange,
        nrp: str,
    ) -> tuple[str, TalentDetailView] | None:
        view = await self._talentops.talent_detail(period, nrp)
        if view is None:
            return None
        roster = await self._roster.load()
        person = next(
            (item for item in roster if item.external_id.casefold() == nrp.strip().casefold()),
            None,
        )
        if person is None:
            return None
        return str(person.id), view
