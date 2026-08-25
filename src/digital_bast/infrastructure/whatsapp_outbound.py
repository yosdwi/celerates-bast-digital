from __future__ import annotations

from typing import Literal, final

import httpx
from pydantic import BaseModel, ValidationError

from digital_bast.application.talentops_followups import WhatsAppSendReceipt


class _BridgeResponse(BaseModel):
    status: Literal["sent"]
    provider_message_id: str | None = None


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

        if response.status_code == 503:
            return WhatsAppSendReceipt(
                status="bridge_unavailable",
                error_code="whatsapp_not_connected",
            )
        if response.status_code in {401, 403}:
            return WhatsAppSendReceipt(
                status="failed",
                error_code="bridge_auth_failed",
            )
        if response.status_code >= 400:
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
