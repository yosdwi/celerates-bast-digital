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
