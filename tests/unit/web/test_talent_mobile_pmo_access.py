from datetime import UTC, date, datetime

import pytest
from starlette.requests import Request

import digital_bast.web.talent_mobile_router as mobile_router_module
from digital_bast.application.talent_mobile_access import (
    issue_pmo_talent_mobile_token,
    issue_talent_mobile_token,
)
from digital_bast.domain.completion import DateRange


class _IdentityStub:
    def __init__(self, jid: str | None) -> None:
        self._jid = jid

    async def existing_jid(self, _employee_id: str) -> str | None:
        return self._jid


def _request(token: str) -> Request:
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/talent/mobile",
            "headers": [(b"authorization", f"Bearer {token}".encode())],
        }
    )


@pytest.mark.asyncio
async def test_pmo_grant_does_not_require_whatsapp_binding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret = "x" * 48
    period = DateRange(date(2026, 9, 1), date(2026, 9, 30))
    token = issue_pmo_talent_mobile_token(
        secret,
        "employee-unbound",
        "pmo.operator@celerates.co.id",
        period,
        now=datetime(2026, 9, 1, 5, 0, tzinfo=UTC),
    )
    monkeypatch.setattr(mobile_router_module, "_secret", lambda: secret)

    def _unexpected_identity_lookup() -> _IdentityStub:
        raise AssertionError("PMO-issued grants must not require a WhatsApp identity")

    monkeypatch.setattr(
        mobile_router_module,
        "create_rebind_onboarding_service",
        _unexpected_identity_lookup,
    )

    claims, audit_actor = await mobile_router_module._claims(_request(token))

    assert claims.access_mode == "pmo"
    assert claims.actor_tag is not None
    assert audit_actor == f"pmo-web:{claims.actor_tag}"


@pytest.mark.asyncio
async def test_whatsapp_grant_still_requires_current_binding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret = "x" * 48
    jid = "628123@s.whatsapp.net"
    period = DateRange(date(2026, 9, 1), date(2026, 9, 30))
    token = issue_talent_mobile_token(
        secret,
        "employee-bound",
        jid,
        period,
        now=datetime(2026, 9, 1, 5, 0, tzinfo=UTC),
    )
    monkeypatch.setattr(mobile_router_module, "_secret", lambda: secret)
    monkeypatch.setattr(
        mobile_router_module,
        "create_rebind_onboarding_service",
        lambda: _IdentityStub(jid),
    )

    claims, audit_actor = await mobile_router_module._claims(_request(token))

    assert claims.access_mode == "whatsapp"
    assert audit_actor == jid
