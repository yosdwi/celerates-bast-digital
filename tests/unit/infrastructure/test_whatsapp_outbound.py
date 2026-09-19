from __future__ import annotations

import asyncio

import httpx
import respx

from digital_bast.infrastructure.whatsapp_outbound import BotBridgeWhatsAppOutboundGateway


def test_group_directory_parses_contact_metadata_and_group_members() -> None:
    with respx.mock(base_url="http://bridge.local") as mock:
        route = mock.get("/internal/v1/groups").mock(
            return_value=httpx.Response(
                200,
                json={
                    "ready": True,
                    "connection": "connected",
                    "discovered_at": "2026-09-19T14:00:00Z",
                    "groups": [
                        {
                            "jid": "120363000000000000@g.us",
                            "subject": "Payroll Closing",
                            "member_count": 1,
                            "participants": [
                                {
                                    "jid": "628111@c.us",
                                    "display_name": "Andi WA",
                                    "number": "628111",
                                    "is_my_contact": True,
                                    "is_admin": True,
                                    "is_super_admin": False,
                                }
                            ],
                        }
                    ],
                },
            )
        )
        gateway = BotBridgeWhatsAppOutboundGateway("http://bridge.local", "bridge-token")

        directory = asyncio.run(gateway.get_groups())

    assert route.called
    assert route.calls.last.request.headers["x-bridge-token"] == "bridge-token"
    assert directory.ready is True
    group = directory.groups[0]
    assert group.subject == "Payroll Closing"
    assert group.member_count == 1
    member = group.participants[0]
    assert member.jid == "628111@c.us"
    assert member.display_name == "Andi WA"
    assert member.number == "628111"
    assert member.is_my_contact is True
    assert member.is_admin is True


def test_group_directory_fails_closed_when_bridge_is_unavailable() -> None:
    with respx.mock(base_url="http://bridge.local") as mock:
        mock.get("/internal/v1/groups").mock(
            return_value=httpx.Response(503, json={"status": "unavailable"})
        )
        gateway = BotBridgeWhatsAppOutboundGateway("http://bridge.local", "bridge-token")

        directory = asyncio.run(gateway.get_groups())

    assert directory.ready is False
    assert directory.connection == "unavailable"
    assert directory.groups == ()


def test_group_outbound_uses_group_only_bridge_endpoint() -> None:
    with respx.mock(base_url="http://bridge.local") as mock:
        route = mock.post("/internal/v1/group-messages").mock(
            return_value=httpx.Response(
                200,
                json={"status": "sent", "provider_message_id": "group-message-1"},
            )
        )
        gateway = BotBridgeWhatsAppOutboundGateway("http://bridge.local", "bridge-token")

        receipt = asyncio.run(
            gateway.send_group(
                "120363000000000000-1@g.us",
                "Payroll digest",
                "payroll:abc123",
            )
        )

    assert route.called
    request = route.calls.last.request
    assert request.headers["x-bridge-token"] == "bridge-token"
    assert request.url.path == "/internal/v1/group-messages"
    assert request.content == (
        b'{"jid":"120363000000000000-1@g.us","text":"Payroll digest",'
        b'"request_id":"payroll:abc123"}'
    )
    assert receipt.status == "sent"
    assert receipt.provider_message_id == "group-message-1"


def test_direct_outbound_keeps_direct_message_endpoint() -> None:
    with respx.mock(base_url="http://bridge.local") as mock:
        route = mock.post("/internal/v1/messages").mock(
            return_value=httpx.Response(
                200,
                json={"status": "sent", "provider_message_id": "direct-message-1"},
            )
        )
        gateway = BotBridgeWhatsAppOutboundGateway("http://bridge.local", "bridge-token")

        receipt = asyncio.run(gateway.send("628111@c.us", "Reminder", "payroll:def456"))

    assert route.called
    assert route.calls.last.request.url.path == "/internal/v1/messages"
    assert receipt.status == "sent"
    assert receipt.provider_message_id == "direct-message-1"
