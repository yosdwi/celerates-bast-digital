from __future__ import annotations

import asyncio
from typing import Final, Literal

from fastapi import APIRouter, HTTPException, Query, Request, status
from pydantic import BaseModel, ConfigDict

from digital_bast.application.talent_mobile_access import configured_talent_mobile_url
from digital_bast.application.workflow_control import WorkflowRole
from digital_bast.domain.completion import DateRange
from digital_bast.domain.time import month_dates
from digital_bast.operations import create_rebind_onboarding_service
from digital_bast.web.dependencies import WebDependencies
from digital_bast.web.security import require_session

_API_PREFIX: Final = "/api/talentops/v1"
_ADMIN_ROLES: Final = frozenset({"owner", "admin"})
_LINK_TTL_SECONDS: Final = 30 * 60


class TalentMobileLinkItem(BaseModel):
    model_config = ConfigDict(frozen=True)

    employee_id: str
    nrp: str
    name: str
    role: str
    whatsapp_bound: bool
    status: Literal["ready", "unbound", "not_configured"]
    url: str | None


class TalentMobileLinksResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    year: int
    month: int
    period_label: str
    ttl_seconds: int
    items: tuple[TalentMobileLinkItem, ...]


def _period(year: int, month: int) -> DateRange:
    try:
        dates = month_dates(year, month)
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Periode tidak valid",
        ) from error
    return DateRange(dates[0], dates[-1])


async def _operator_scope(request: Request, dependencies: WebDependencies) -> str:
    _, session = await require_session(
        request,
        dependencies.sessions,
        dependencies.cookie,
        dependencies.now,
        api=True,
    )
    if session.user.role.strip().casefold() in _ADMIN_ROLES:
        return "default"
    if dependencies.workflow_control is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Workflow control belum tersedia",
        )
    operator = await dependencies.workflow_control.operator(session.user.email)
    if operator is None or not operator.active or operator.role is not WorkflowRole.PMO:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Akses PMO diperlukan")
    return operator.scope_key


async def _links(
    request: Request,
    dependencies: WebDependencies,
    year: int,
    month: int,
) -> TalentMobileLinksResponse:
    if dependencies.talentops is None or dependencies.workflow_control is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="TalentOps belum tersedia",
        )
    scope_key = await _operator_scope(request, dependencies)
    period = _period(year, month)
    view = await dependencies.talentops.command_center(period)
    mobile = await dependencies.workflow_control.talent_mobile_settings(scope_key)
    identity = create_rebind_onboarding_service()
    jids = await asyncio.gather(
        *(identity.existing_jid(item.employee_id) for item in view.readiness)
    )

    items: list[TalentMobileLinkItem] = []
    for talent, jid in zip(view.readiness, jids, strict=True):
        if jid is None:
            link_status: Literal["ready", "unbound", "not_configured"] = "unbound"
            url = None
        else:
            url = configured_talent_mobile_url(
                talent.employee_id,
                jid,
                period,
                "attendance",
                public_url=mobile.public_url,
            )
            link_status = "ready" if url is not None else "not_configured"
        items.append(
            TalentMobileLinkItem(
                employee_id=talent.employee_id,
                nrp=talent.nrp,
                name=talent.name,
                role=talent.role.value,
                whatsapp_bound=jid is not None,
                status=link_status,
                url=url,
            )
        )

    return TalentMobileLinksResponse(
        year=period.start.year,
        month=period.start.month,
        period_label=period.label(),
        ttl_seconds=_LINK_TTL_SECONDS,
        items=tuple(items),
    )


def talent_mobile_links_router(dependencies: WebDependencies) -> APIRouter:
    router = APIRouter(prefix=_API_PREFIX, tags=["talentops"])

    async def links(
        request: Request,
        year: int = Query(ge=2020, le=2100),
        month: int = Query(ge=1, le=12),
    ) -> TalentMobileLinksResponse:
        return await _links(request, dependencies, year, month)

    router.add_api_route(
        "/talent-mobile-links",
        links,
        methods=["GET"],
        response_model=TalentMobileLinksResponse,
    )
    return router
