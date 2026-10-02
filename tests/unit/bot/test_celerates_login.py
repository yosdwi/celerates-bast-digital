from __future__ import annotations

import json

import httpx
import pytest

from digital_bast.bot import celerates_login
from digital_bast.bot.celerates_login import (
    FAILED_REPLY,
    NO_ACCOUNT_REPLY,
    HttpTalentLinkGateway,
    LinkGrant,
    LinkGrantOutcome,
    celerates_login_reply,
)

BASE = "https://celerates.example"
JID = "6281100000001@c.us"


class FakePort:
    def __init__(self, grant: LinkGrant) -> None:
        self.grant_result = grant
        self.calls: list[str] = []

    async def grant(self, employee_id: str) -> LinkGrant:
        self.calls.append(employee_id)
        return self.grant_result


async def bound(jid: str) -> str | None:
    return "E-1" if jid == JID else None


async def no_draft(jid: str) -> bool:
    del jid
    return False


async def open_draft(jid: str) -> bool:
    del jid
    return True


@pytest.mark.parametrize("text", ["masuk", "  LOGIN ", "Link"])
async def test_bound_login_word_replies_with_a_single_use_link(text: str) -> None:
    port = FakePort(LinkGrant(LinkGrantOutcome.GRANTED, f"{BASE}/go/abc"))
    reply = await celerates_login_reply(text, JID, port=port, resolve=bound, draft_pending=no_draft)
    assert reply is not None
    assert f"{BASE}/go/abc" in reply
    assert "Link ini hanya bisa dipakai sekali." in reply
    assert port.calls == ["E-1"]


async def test_no_account_and_failure_replies() -> None:
    no_account = await celerates_login_reply(
        "masuk",
        JID,
        port=FakePort(LinkGrant(LinkGrantOutcome.NO_ACCOUNT)),
        resolve=bound,
        draft_pending=no_draft,
    )
    assert no_account == NO_ACCOUNT_REPLY
    assert "PMO" in no_account
    failed = await celerates_login_reply(
        "login",
        JID,
        port=FakePort(LinkGrant(LinkGrantOutcome.FAILED)),
        resolve=bound,
        draft_pending=no_draft,
    )
    assert failed == FAILED_REPLY


async def test_unconfigured_unbound_other_text_and_open_draft_fall_through() -> None:
    port = FakePort(LinkGrant(LinkGrantOutcome.GRANTED, f"{BASE}/go/x"))
    assert (
        await celerates_login_reply("masuk", JID, port=None, resolve=bound, draft_pending=no_draft)
        is None
    ), "unconfigured: existing behaviour"
    assert (
        await celerates_login_reply(
            "masuk", "620@c.us", port=port, resolve=bound, draft_pending=no_draft
        )
        is None
    ), "unbound: existing not-bound reply"
    assert (
        await celerates_login_reply(
            "masuk kerja", JID, port=port, resolve=bound, draft_pending=no_draft
        )
        is None
    ), "only the whole message"
    assert (
        await celerates_login_reply(
            "masuk", JID, port=port, resolve=bound, draft_pending=open_draft
        )
        is None
    ), "`masuk` answers an open attendance draft"
    assert (
        await celerates_login_reply("link", JID, port=port, resolve=bound, draft_pending=open_draft)
        is not None
    )
    assert port.calls == ["E-1"]


async def test_login_reply_is_a_no_op_without_configuration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(celerates_login, "configured_link_port", lambda: None)
    assert await celerates_login.login_reply("masuk", JID) is None
    assert await celerates_login.login_reply("halo", JID) is None


async def test_http_gateway_maps_the_celerates_responses() -> None:
    seen: list[httpx.Request] = []
    replies = iter(
        [
            httpx.Response(200, json={"url": f"{BASE}/go/abc", "expires_at": None}),
            httpx.Response(404, json={"error": {"code": "no_account"}}),
            httpx.Response(503, json={"error": {"code": "unconfigured"}}),
            httpx.Response(200, json={"url": "https://evil.example/go/x"}),
        ]
    )

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return next(replies)

    gateway = HttpTalentLinkGateway(f"{BASE}/", "s" * 40, transport=httpx.MockTransport(handler))
    assert await gateway.grant("E-1") == LinkGrant(LinkGrantOutcome.GRANTED, f"{BASE}/go/abc")
    assert (await gateway.grant("E-1")).outcome is LinkGrantOutcome.NO_ACCOUNT
    assert (await gateway.grant("E-1")).outcome is LinkGrantOutcome.FAILED
    assert (await gateway.grant("E-1")).outcome is LinkGrantOutcome.FAILED, "foreign host"
    first = seen[0]
    assert str(first.url) == f"{BASE}/api/internal/talent/links"
    assert first.headers["authorization"] == f"Bearer {'s' * 40}"
    assert json.loads(first.content) == {"employee_id": "E-1"}
