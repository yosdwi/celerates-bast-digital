from datetime import UTC, date, datetime
from types import SimpleNamespace
from typing import Any, cast

import pytest
from starlette.requests import Request

import digital_bast.web.talent_mobile_links_router as links_router_module
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


class _TalentOpsStub:
    async def command_center(self, _period: DateRange) -> SimpleNamespace:
        talent = SimpleNamespace(
            employee_id="employee-unbound",
            nrp="NRP001",
            name="Unbound Talent",
            role=SimpleNamespace(value="Developer"),
        )
        return SimpleNamespace(readiness=(talent,))


class _WorkflowControlStub:
    async def talent_mobile_settings(self, _scope_key: str) -> SimpleNamespace:
        return SimpleNamespace(public_url="https://talent.example.test")


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


@pytest.mark.asyncio
async def test_pmo_link_directory_issues_url_for_unbound_talent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _operator_context(
        _request: Request,
        _dependencies: object,
    ) -> tuple[str, str]:
        return "default", "pmo.operator@celerates.co.id"

    monkeypatch.setattr(links_router_module, "_operator_context", _operator_context)
    monkeypatch.setattr(
        links_router_module,
        "create_rebind_onboarding_service",
        lambda: _IdentityStub(None),
    )
    monkeypatch.setattr(
        links_router_module,
        "configured_pmo_talent_mobile_url",
        lambda _employee_id, _issuer, _period, _tab, *, public_url=None: (
            f"{public_url}/talent/mobile?t=signed"
        ),
    )
    dependencies = cast(
        Any,
        SimpleNamespace(
            talentops=_TalentOpsStub(),
            workflow_control=_WorkflowControlStub(),
        ),
    )

    response = await links_router_module._links(_request("unused"), dependencies, 2026, 9)

    assert len(response.items) == 1
    item = response.items[0]
    assert item.employee_id == "employee-unbound"
    assert item.whatsapp_bound is False
    assert item.status == "ready"
    assert item.url == "https://talent.example.test/talent/mobile?t=signed"
