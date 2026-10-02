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
    alive: bool = True
    ready: bool = False
    connection: str
    me: str = ""
    qr_data_url: str | None = Field(default=None, alias="qrDataUrl")
    pairing_code: str | None = Field(default=None, alias="pairingCode")
    operator_action_required: bool = Field(default=False, alias="operatorActionRequired")
    operator_reason: str | None = Field(default=None, alias="operatorReason")
    connection_changed_at: datetime | None = Field(default=None, alias="connectionChangedAt")
    recovery_state: str = Field(default="unavailable", alias="recoveryState")
    recovery_reason: str | None = Field(default=None, alias="recoveryReason")
    recovery_paused: bool = Field(default=False, alias="recoveryPaused")
    last_probe_at: datetime | None = Field(default=None, alias="lastProbeAt")
    last_ready_at: datetime | None = Field(default=None, alias="lastReadyAt")
    last_ack_at: datetime | None = Field(default=None, alias="lastAckAt")
    cooldown_until: datetime | None = Field(default=None, alias="cooldownUntil")
    recovery_attempts: int = Field(default=0, alias="recoveryAttempts")
    recovery_max_attempts: int = Field(default=0, alias="recoveryMaxAttempts")
    recovery_policy_version: int = Field(default=0, alias="recoveryPolicyVersion")
    applied_recovery_policy_version: int = Field(default=0, alias="appliedRecoveryPolicyVersion")
    owner_acquired: bool = Field(default=False, alias="ownerAcquired")
    owner_conflict_id: str | None = Field(default=None, alias="ownerConflictId")
    owner_conflict_heartbeat_at: datetime | None = Field(
        default=None,
        alias="ownerConflictHeartbeatAt",
    )
    storage_healthy: bool = Field(default=False, alias="storageHealthy")
    storage_reasons: list[str] = Field(default_factory=list, alias="storageReasons")
    free_bytes: int | None = Field(default=None, alias="freeBytes")
    free_inodes: int | None = Field(default=None, alias="freeInodes")
    receipt_store_healthy: bool = Field(default=False, alias="receiptStoreHealthy")
    receipt_store_error: str | None = Field(default=None, alias="receiptStoreError")
    receipt_sent: int = Field(default=0, alias="receiptSent")
    receipt_unknown: int = Field(default=0, alias="receiptUnknown")
    receipt_in_flight: int = Field(default=0, alias="receiptInFlight")
    transport: str = "whatsapp-web.js"


class _BridgeControlResponse(BaseModel):
    accepted: bool
    reason: str


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
    alive: bool = False
    ready: bool = False
    me: str = ""
    qr_data_url: str | None = None
    pairing_code: str | None = None
    operator_action_required: bool = False
    operator_reason: str | None = None
    connection_changed_at: datetime | None = None
    recovery_state: str = "unavailable"
    recovery_reason: str | None = None
    recovery_paused: bool = False
    last_probe_at: datetime | None = None
    last_ready_at: datetime | None = None
    last_ack_at: datetime | None = None
    cooldown_until: datetime | None = None
    recovery_attempts: int = 0
    recovery_max_attempts: int = 0
    recovery_policy_version: int = 0
    applied_recovery_policy_version: int = 0
    owner_acquired: bool = False
    owner_conflict_id: str | None = None
    owner_conflict_heartbeat_at: datetime | None = None
    storage_healthy: bool = False
    storage_reasons: tuple[str, ...] = ()
    free_bytes: int | None = None
    free_inodes: int | None = None
    receipt_store_healthy: bool = False
    receipt_store_error: str | None = None
    receipt_sent: int = 0
    receipt_unknown: int = 0
    receipt_in_flight: int = 0
    transport: str = "whatsapp-web.js"


@dataclass(frozen=True, slots=True)
class BotBridgeControlResult:
    accepted: bool
    reason: str


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


def _unavailable_receipt() -> WhatsAppSendReceipt:
    return WhatsAppSendReceipt(
        status="bridge_unavailable",
        error_code="bridge_not_configured",
    )


def _response_error(response: httpx.Response, fallback: str) -> str:
    try:
        payload = response.json()
    except ValueError:
        return fallback
    if not isinstance(payload, dict):
        return fallback
    error = payload.get("error")
    return str(error) if error else fallback


@final
class UnavailableWhatsAppOutboundGateway:
    async def send(self, jid: str, text: str, request_id: str) -> WhatsAppSendReceipt:
        _ = (jid, text, request_id)
        return _unavailable_receipt()

    async def send_group(
        self,
        group_jid: str,
        text: str,
        request_id: str,
    ) -> WhatsAppSendReceipt:
        _ = (group_jid, text, request_id)
        return _unavailable_receipt()


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
        return await self._send_to("/internal/v1/messages", jid, text, request_id)

    async def send_group(
        self,
        group_jid: str,
        text: str,
        request_id: str,
    ) -> WhatsAppSendReceipt:
        return await self._send_to(
            "/internal/v1/group-messages",
            group_jid,
            text,
            request_id,
        )

    async def _send_to(
        self,
        path: str,
        jid: str,
        text: str,
        request_id: str,
    ) -> WhatsAppSendReceipt:
        try:
            async with httpx.AsyncClient(
                base_url=self._base_url,
                timeout=self._timeout_seconds,
            ) as client:
                response = await client.post(
                    path,
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
                error_code=_response_error(response, "whatsapp_not_connected"),
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
            alive=parsed.alive,
            ready=parsed.ready,
            me=parsed.me,
            qr_data_url=parsed.qr_data_url,
            pairing_code=parsed.pairing_code,
            operator_action_required=parsed.operator_action_required,
            operator_reason=parsed.operator_reason,
            connection_changed_at=parsed.connection_changed_at,
            recovery_state=parsed.recovery_state,
            recovery_reason=parsed.recovery_reason,
            recovery_paused=parsed.recovery_paused,
            last_probe_at=parsed.last_probe_at,
            last_ready_at=parsed.last_ready_at,
            last_ack_at=parsed.last_ack_at,
            cooldown_until=parsed.cooldown_until,
            recovery_attempts=parsed.recovery_attempts,
            recovery_max_attempts=parsed.recovery_max_attempts,
            recovery_policy_version=parsed.recovery_policy_version,
            applied_recovery_policy_version=parsed.applied_recovery_policy_version,
            owner_acquired=parsed.owner_acquired,
            owner_conflict_id=parsed.owner_conflict_id,
            owner_conflict_heartbeat_at=parsed.owner_conflict_heartbeat_at,
            storage_healthy=parsed.storage_healthy,
            storage_reasons=tuple(parsed.storage_reasons),
            free_bytes=parsed.free_bytes,
            free_inodes=parsed.free_inodes,
            receipt_store_healthy=parsed.receipt_store_healthy,
            receipt_store_error=parsed.receipt_store_error,
            receipt_sent=parsed.receipt_sent,
            receipt_unknown=parsed.receipt_unknown,
            receipt_in_flight=parsed.receipt_in_flight,
            transport=parsed.transport,
        )

    async def control_recovery(
        self,
        action: Literal["pause", "resume", "reconnect"],
    ) -> BotBridgeControlResult:
        return await self._control(f"/internal/v1/recovery/{action}")

    async def start_pairing(self) -> BotBridgeControlResult:
        return await self._control("/internal/v1/pair")

    async def _control(self, path: str) -> BotBridgeControlResult:
        try:
            async with httpx.AsyncClient(
                base_url=self._base_url,
                timeout=self._timeout_seconds,
            ) as client:
                response = await client.post(
                    path,
                    headers={"X-Bridge-Token": self._token},
                )
        except httpx.HTTPError:
            return BotBridgeControlResult(accepted=False, reason="bridge_request_failed")
        try:
            parsed = _BridgeControlResponse.model_validate(response.json())
        except (ValueError, ValidationError):
            return BotBridgeControlResult(
                accepted=False,
                reason=f"bridge_http_{response.status_code}",
            )
        return BotBridgeControlResult(accepted=parsed.accepted, reason=parsed.reason)

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
