from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime  # noqa: TC003 - Pydantic resolves this type at runtime
from http import HTTPStatus
from typing import Literal, final

import httpx
from pydantic import BaseModel, Field, ValidationError

from digital_bast.application.talentops_followups import WhatsAppSendReceipt


class _BridgeResponse(BaseModel):
    status: Literal["sent"]
    provider_message_id: str | None = None


class _BridgeStatusResponse(BaseModel):
    connection: str
    me: str = ""
    qr_data_url: str | None = Field(default=None, alias="qrDataUrl")
    pairing_code: str | None = Field(default=None, alias="pairingCode")


class _BridgeGroupParticipantResponse(BaseModel):
    jid: str
    display_name: str = ""
    number: str = ""
    is_my_contact: bool = False
    is_admin: bool = False
    is_super_admin: bool = False


class _BridgeGroupResponse(BaseModel):
    jid: str
    subject: str = ""
    member_count: int = 0
    participants: list[_BridgeGroupParticipantResponse] = Field(default_factory=list)


class _BridgeGroupsResponse(BaseModel):
    ready: bool = False
    connection: str = "unavailable"
    discovered_at: datetime | None = None
    groups: list[_BridgeGroupResponse] = Field(default_factory=list)


@dataclass(frozen=True, slots=True)
class BotBridgeStatus:
    connection: str
    me: str = ""
    qr_data_url: str | None = None
    pairing_code: str | None = None


@dataclass(frozen=True, slots=True)
class WhatsAppGroupParticipant:
    jid: str
    display_name: str = ""
    number: str = ""
    is_my_contact: bool = False
    is_admin: bool = False
    is_super_admin: bool = False


@dataclass(frozen=True, slots=True)
class WhatsAppGroup:
    jid: str
    subject: str
    participants: tuple[WhatsAppGroupParticipant, ...]

    @property
    def member_count(self) -> int:
        return len(self.participants)


@dataclass(frozen=True, slots=True)
class WhatsAppGroupDirectory:
    ready: bool
    connection: str
    groups: tuple[WhatsAppGroup, ...]
    discovered_at: datetime | None = None


@final
class UnavailableWhatsAppOutboundGateway:
    async def send(self, jid: str, text: str, request_id: str) -> WhatsAppSendReceipt:
        _ = (jid, text, request_id)
        return WhatsAppSendReceipt(
            status="bridge_unavailable",
            error_code="bridge_not_configured",
        )


@final
class BotBridgeWhatsAppOutboundGateway:
    def __init__(
        self,
        base_url: str,
        token: str,
        timeout_seconds: float = 15.0,
    ) -> None:
        self._base_url = base_url
        self._token = token
        self._timeout_seconds = timeout_seconds

    async def send(self, jid: str, text: str, request_id: str) -> WhatsAppSendReceipt:
        try:
            async with httpx.AsyncClient(
                base_url=self._base_url,
                timeout=self._timeout_seconds,
            ) as client:
                response = await client.post(
                    "/internal/v1/messages",
                    headers={"X-Bridge-Token": self._token},
                    json={"jid": jid, "text": text, "request_id": request_id},
                )
        except httpx.HTTPError:
            return WhatsAppSendReceipt(
                status="bridge_unavailable",
                error_code="bridge_request_failed",
            )

        if response.status_code == HTTPStatus.SERVICE_UNAVAILABLE:
            return WhatsAppSendReceipt(
                status="bridge_unavailable",
                error_code="whatsapp_not_connected",
            )
        if response.status_code in {HTTPStatus.UNAUTHORIZED, HTTPStatus.FORBIDDEN}:
            return WhatsAppSendReceipt(
                status="failed",
                error_code="bridge_auth_failed",
            )
        if response.status_code >= HTTPStatus.BAD_REQUEST:
            return WhatsAppSendReceipt(
                status="failed",
                error_code=f"bridge_http_{response.status_code}",
            )
        try:
            parsed = _BridgeResponse.model_validate(response.json())
        except (ValueError, ValidationError):
            return WhatsAppSendReceipt(
                status="failed",
                error_code="bridge_invalid_response",
            )
        return WhatsAppSendReceipt(
            status="sent",
            provider_message_id=parsed.provider_message_id,
        )

    async def get_status(self) -> BotBridgeStatus:
        try:
            async with httpx.AsyncClient(
                base_url=self._base_url,
                timeout=self._timeout_seconds,
            ) as client:
                response = await client.get(
                    "/internal/v1/status",
                    headers={"X-Bridge-Token": self._token},
                )
        except httpx.HTTPError:
            return BotBridgeStatus(connection="unavailable")

        if response.status_code != HTTPStatus.OK:
            return BotBridgeStatus(connection="unavailable")
        try:
            parsed = _BridgeStatusResponse.model_validate(response.json())
        except (ValueError, ValidationError):
            return BotBridgeStatus(connection="unavailable")
        return BotBridgeStatus(
            connection=parsed.connection,
            me=parsed.me,
            qr_data_url=parsed.qr_data_url,
            pairing_code=parsed.pairing_code,
        )

    async def get_groups(self) -> WhatsAppGroupDirectory:
        try:
            async with httpx.AsyncClient(
                base_url=self._base_url,
                timeout=self._timeout_seconds,
            ) as client:
                response = await client.get(
                    "/internal/v1/groups",
                    headers={"X-Bridge-Token": self._token},
                )
        except httpx.HTTPError:
            return WhatsAppGroupDirectory(
                ready=False,
                connection="unavailable",
                groups=(),
            )

        if response.status_code != HTTPStatus.OK:
            return WhatsAppGroupDirectory(
                ready=False,
                connection="unavailable",
                groups=(),
            )
        try:
            parsed = _BridgeGroupsResponse.model_validate(response.json())
        except (ValueError, ValidationError):
            return WhatsAppGroupDirectory(
                ready=False,
                connection="unavailable",
                groups=(),
            )
        return WhatsAppGroupDirectory(
            ready=parsed.ready,
            connection=parsed.connection,
            discovered_at=parsed.discovered_at,
            groups=tuple(
                WhatsAppGroup(
                    jid=group.jid,
                    subject=group.subject,
                    participants=tuple(
                        WhatsAppGroupParticipant(
                            jid=participant.jid,
                            display_name=participant.display_name,
                            number=participant.number,
                            is_my_contact=participant.is_my_contact,
                            is_admin=participant.is_admin,
                            is_super_admin=participant.is_super_admin,
                        )
                        for participant in group.participants
                    ),
                )
                for group in parsed.groups
            ),
        )
