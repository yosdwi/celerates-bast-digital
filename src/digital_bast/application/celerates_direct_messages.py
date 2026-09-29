"""One personal WhatsApp reminder to one Talent, requested by a PMO in Celerates.

Contract: docs/celerates-integration-v1.md ("Direct messages"). A single,
human-initiated message, so the campaign sending window does not apply; the
kill switch, the WhatsApp binding and a short same-Talent dedupe do. The open
items (attendance days and tasks without evidence) come from the same audience
projection the campaigns use, so no readiness rule is duplicated here.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from enum import StrEnum
from typing import TYPE_CHECKING, Final, Literal, NoReturn, Protocol, final

from digital_bast.application.celerates_campaigns import (
    calendar_month_label,
    compose_talent_message,
)

if TYPE_CHECKING:
    from collections.abc import Callable
    from datetime import datetime
    from uuid import UUID

    from digital_bast.application.attendance_closing_policy import PayrollCycle
    from digital_bast.application.celerates_campaigns import (
        AudienceMember,
        JidResolver,
        OutboundGateway,
    )
    from digital_bast.application.talentops_followups import WhatsAppSendReceipt

DIRECT_DEDUPE_WINDOW: Final = timedelta(minutes=10)


class DirectMessageStatus(StrEnum):
    SENDING = "sending"
    SENT = "sent"
    FAILED = "failed"
    UNKNOWN = "unknown"


class DirectMessageError(Exception):
    """A direct message the current state does not allow, or a transport failure."""

    def __init__(self, code: str, message: str, *, retryable: bool = False) -> None:
        super().__init__(code, message)
        self.code: str = code
        self.message: str = message
        self.retryable: bool = retryable


def _refuse(code: str, message: str, *, retryable: bool = False) -> NoReturn:
    raise DirectMessageError(code, message, retryable=retryable)


@dataclass(frozen=True, slots=True)
class DirectMessage:
    id: UUID
    employee_id: str
    cycle_id: str
    cycle_year: int
    cycle_month: int
    actor: str
    link_url: str
    link_expires_at: datetime | None
    attendance_days: int
    missing_tasks: int
    created_at: datetime


@dataclass(frozen=True, slots=True)
class DirectMessageResult:
    status: Literal["sent", "unknown"]
    message_id: UUID
    sent_at: datetime | None


class OpenItemsReader(Protocol):
    async def open_items(self, employee_id: str, cycle: PayrollCycle) -> AudienceMember | None: ...


class DirectMessageStore(Protocol):
    async def kill_switch(self) -> bool: ...

    async def begin(self, message: DirectMessage, *, since: datetime) -> bool:
        """Record `message` as sending unless one was sent to the Talent since `since`.

        The check and the insert are atomic per employee.
        """
        ...

    async def finish(
        self,
        message_id: UUID,
        status: DirectMessageStatus,
        *,
        provider_message_id: str | None,
        error: str | None,
        sent_at: datetime | None,
    ) -> None: ...


@final
class CeleratesDirectMessageService:
    def __init__(  # noqa: PLR0913
        self,
        store: DirectMessageStore,
        items: OpenItemsReader,
        jids: JidResolver,
        gateway: OutboundGateway,
        *,
        new_id: Callable[[], UUID],
        clock: Callable[[], datetime],
        allowed_link_prefix: str | None = None,
    ) -> None:
        self._store = store
        self._items = items
        self._jids = jids
        self._gateway = gateway
        self._new_id = new_id
        self._clock = clock
        self._allowed_prefix = allowed_link_prefix

    async def send(
        self,
        employee_id: str,
        cycle: PayrollCycle,
        *,
        link_url: str,
        link_expires_at: datetime | None,
        actor: str,
    ) -> DirectMessageResult:
        now = self._clock()
        if self._allowed_prefix and not link_url.startswith(self._allowed_prefix):
            _refuse("link_not_allowed", "Link is outside the Celerates public URL")
        if link_expires_at is not None and link_expires_at <= now:
            _refuse("invalid_link_expiry", "Link has already expired")
        member = await self._items.open_items(employee_id, cycle)
        if member is None:
            _refuse("talent_not_found", "Talent not found or not active")
        # Checks in contract order: kill switch, binding, recent direct message.
        if await self._store.kill_switch():
            _refuse("kill_switch", "Sending is stopped by the kill switch")
        jid = await self._jids.jid_for_employee(employee_id)
        if jid is None:
            _refuse("not_bound", "Talent has no bound WhatsApp number")
        message = DirectMessage(
            id=self._new_id(),
            employee_id=employee_id,
            cycle_id=cycle.cycle_id,
            cycle_year=cycle.label_year,
            cycle_month=cycle.label_month,
            actor=actor,
            link_url=link_url,
            link_expires_at=link_expires_at,
            attendance_days=len(member.actionable_dates),
            missing_tasks=len(member.missing_task_keys),
            created_at=now,
        )
        if not await self._store.begin(message, since=now - DIRECT_DEDUPE_WINDOW):
            _refuse("recently_sent", "A reminder was sent to this Talent in the last 10 minutes")
        text = compose_talent_message(
            name=member.name,
            cycle_label=cycle.label,
            dates=member.actionable_dates,
            link=link_url,
            expires_at=link_expires_at,
            missing_tasks=len(member.missing_task_keys),
            task_month_label=calendar_month_label(cycle.label_year, cycle.label_month),
        )
        receipt = await self._gateway.send(jid, text, f"celerates-direct:{message.id}")
        return await self._record(message.id, receipt)

    async def _record(self, message_id: UUID, receipt: WhatsAppSendReceipt) -> DirectMessageResult:
        """Record the transport outcome; failures raise the contract error."""
        error = receipt.error_code
        if receipt.status == "sent":
            sent_at = self._clock()
            await self._store.finish(
                message_id,
                DirectMessageStatus.SENT,
                provider_message_id=receipt.provider_message_id,
                error=None,
                sent_at=sent_at,
            )
            return DirectMessageResult("sent", message_id, sent_at)
        if receipt.status == "bridge_unavailable" and error == "delivery_outcome_unknown":
            await self._store.finish(
                message_id,
                DirectMessageStatus.UNKNOWN,
                provider_message_id=receipt.provider_message_id,
                error=error,
                sent_at=None,
            )
            return DirectMessageResult("unknown", message_id, None)
        await self._store.finish(
            message_id,
            DirectMessageStatus.FAILED,
            provider_message_id=None,
            error=error,
            sent_at=None,
        )
        if receipt.status == "bridge_unavailable":
            _refuse("transport_unavailable", "WhatsApp transport is unavailable", retryable=True)
        if error == "bridge_auth_failed":
            _refuse("transport_auth_failed", "WhatsApp transport rejected the credentials")
        _refuse("delivery_failed", f"The message was not delivered ({error or 'failed'})")
