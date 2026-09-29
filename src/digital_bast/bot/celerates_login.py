"""WhatsApp re-entry: `masuk` / `login` / `link` -> a fresh single-use Celerates link.

Celerates is the grant authority (docs/celerates-integration-v1.md, "Bot
`masuk`"). ConForm only asks it for a link for the bound Talent and relays the
answer. Without CELERATES_PUBLIC_URL and the Celerates service token the words
are not intercepted at all, so the existing DM behaviour is unchanged. An
unbound sender is not intercepted either and keeps the existing not-bound
reply. While an attendance draft is open, `masuk` stays a draft answer
("masuk kerja") and is not intercepted.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from http import HTTPStatus
from typing import TYPE_CHECKING, Final, Protocol, cast, final

import httpx

from digital_bast.config import SettingsConfigurationError, get_settings
from digital_bast.operations import (
    create_activation_service,
    create_attendance_resolution_dm_state_service,
)

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

LOGIN_WORDS: Final = frozenset({"masuk", "login", "link"})
_DRAFT_ANSWER_WORDS: Final = frozenset({"masuk"})
_TIMEOUT_SECONDS: Final = 5.0

GRANTED_REPLY: Final = "Ini link masuk Celerates kamu:\n{url}\nLink ini hanya bisa dipakai sekali."
NO_ACCOUNT_REPLY: Final = "Akun Celerates kamu belum aktif. Hubungi PMO untuk mengaktifkannya."
FAILED_REPLY: Final = "Link Celerates belum bisa dibuat sekarang. Coba lagi nanti ya."


class LinkGrantOutcome(StrEnum):
    GRANTED = "granted"
    NO_ACCOUNT = "no_account"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class LinkGrant:
    outcome: LinkGrantOutcome
    url: str | None = None


class TalentLinkPort(Protocol):
    async def grant(self, employee_id: str) -> LinkGrant: ...


@final
class HttpTalentLinkGateway:
    """POST {CELERATES_PUBLIC_URL}/api/internal/talent/links with the shared bearer secret."""

    def __init__(
        self,
        base_url: str,
        token: str,
        timeout_seconds: float = _TIMEOUT_SECONDS,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._token = token
        self._timeout_seconds = timeout_seconds
        self._transport = transport

    async def grant(self, employee_id: str) -> LinkGrant:
        try:
            async with httpx.AsyncClient(
                timeout=self._timeout_seconds, transport=self._transport
            ) as client:
                response = await client.post(
                    f"{self._base_url}/api/internal/talent/links",
                    headers={"Authorization": f"Bearer {self._token}"},
                    json={"employee_id": employee_id},
                )
        except httpx.HTTPError:
            return LinkGrant(LinkGrantOutcome.FAILED)
        try:
            payload = cast("object", response.json())
        except ValueError:
            payload = None
        body = cast("dict[str, object]", payload) if isinstance(payload, dict) else {}
        if response.status_code == HTTPStatus.OK:
            url = body.get("url")
            if isinstance(url, str) and url.startswith(self._base_url):
                return LinkGrant(LinkGrantOutcome.GRANTED, url)
            return LinkGrant(LinkGrantOutcome.FAILED)
        if response.status_code == HTTPStatus.NOT_FOUND:
            error = body.get("error")
            code = cast("dict[str, object]", error).get("code") if isinstance(error, dict) else None
            if code == "no_account":
                return LinkGrant(LinkGrantOutcome.NO_ACCOUNT)
        return LinkGrant(LinkGrantOutcome.FAILED)


def is_login_request(text: str) -> bool:
    return text.strip().casefold() in LOGIN_WORDS


def render_grant(grant: LinkGrant) -> str:
    if grant.outcome is LinkGrantOutcome.GRANTED and grant.url:
        return GRANTED_REPLY.format(url=grant.url)
    if grant.outcome is LinkGrantOutcome.NO_ACCOUNT:
        return NO_ACCOUNT_REPLY
    return FAILED_REPLY


async def celerates_login_reply(
    text: str,
    jid: str,
    *,
    port: TalentLinkPort | None,
    resolve: Callable[[str], Awaitable[str | None]],
    draft_pending: Callable[[str], Awaitable[bool]],
) -> str | None:
    """The reply for a login word, or None to let the existing DM routing answer."""
    normalized = text.strip().casefold()
    if normalized not in LOGIN_WORDS or port is None:
        return None
    if normalized in _DRAFT_ANSWER_WORDS and await draft_pending(jid):
        return None
    employee_id = await resolve(jid)
    if employee_id is None:
        return None
    return render_grant(await port.grant(employee_id))


def configured_link_port() -> TalentLinkPort | None:
    try:
        settings = get_settings()
    except (OSError, ValueError, SettingsConfigurationError):
        return None
    if settings.celerates_public_url is None or settings.celerates_service_token is None:
        return None
    return HttpTalentLinkGateway(
        str(settings.celerates_public_url),
        settings.celerates_service_token.get_secret_value(),
    )


async def login_reply(text: str, jid: str) -> str | None:
    """Runtime wiring for the DM entry points."""
    if not is_login_request(text):
        return None
    port = configured_link_port()
    if port is None:
        return None

    async def draft_pending(wa_jid: str) -> bool:
        return await create_attendance_resolution_dm_state_service().pending(wa_jid) is not None

    return await celerates_login_reply(
        text,
        jid,
        port=port,
        resolve=create_activation_service().resolve,
        draft_pending=draft_pending,
    )
