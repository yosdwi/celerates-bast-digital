from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from fastapi import APIRouter, HTTPException, Request, status

from digital_bast.application.workflow_control import WorkflowRole
from digital_bast.web.security import HeaderCsrf, require_session, verify_csrf
from digital_bast.web.whatsapp_ops_contracts import (
    WhatsAppOperationsControlResponse,
    WhatsAppOperationsStatusResponse,
)

if TYPE_CHECKING:
    from digital_bast.infrastructure.whatsapp_outbound import BotBridgeWhatsAppOutboundGateway
    from digital_bast.web.contracts import SessionRecord
    from digital_bast.web.dependencies import WebDependencies

_API_PREFIX = "/api/talentops/v1/system/whatsapp"
_ADMIN_ROLES = frozenset({"owner", "admin"})


def _bridge(deps: WebDependencies) -> BotBridgeWhatsAppOutboundGateway:
    if deps.bot_bridge_status is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="WhatsApp bridge status is unavailable",
        )
    return deps.bot_bridge_status


def _is_admin(record: SessionRecord) -> bool:
    return record.user.role.casefold() in _ADMIN_ROLES


async def _authorized_operator(deps: WebDependencies, record: SessionRecord) -> None:
    if _is_admin(record):
        return
    if deps.workflow_control is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Workflow authorization service is unavailable",
        )
    operator = await deps.workflow_control.operator(record.user.email)
    if operator is None or not operator.active or operator.role is not WorkflowRole.PMO:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="PMO access is inactive",
        )


def whatsapp_ops_router(deps: WebDependencies) -> APIRouter:
    router = APIRouter(prefix=_API_PREFIX, tags=["whatsapp-operations"])

    async def session(request: Request) -> SessionRecord:
        _, record = await require_session(
            request,
            deps.sessions,
            deps.cookie,
            deps.now,
            api=True,
        )
        return record

    async def operations_status(request: Request) -> WhatsAppOperationsStatusResponse:
        _ = await session(request)
        result = await _bridge(deps).get_status()
        return WhatsAppOperationsStatusResponse.model_validate(result)

    async def recovery_control(
        request: Request,
        action: Literal["pause", "resume", "reconnect"],
        csrf_token: HeaderCsrf = None,
    ) -> WhatsAppOperationsControlResponse:
        record = await session(request)
        await _authorized_operator(deps, record)
        verify_csrf(record, csrf_token)
        result = await _bridge(deps).control_recovery(action)
        return WhatsAppOperationsControlResponse.model_validate(result)

    async def controlled_pairing(
        request: Request,
        csrf_token: HeaderCsrf = None,
    ) -> WhatsAppOperationsControlResponse:
        record = await session(request)
        if not _is_admin(record):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Admin access is required for WhatsApp pairing",
            )
        verify_csrf(record, csrf_token)
        bridge = _bridge(deps)
        current = await bridge.get_status()
        if not current.operator_action_required and current.connection != "pairing-required":
            return WhatsAppOperationsControlResponse(
                accepted=False,
                reason="pairing_not_required",
            )
        result = await bridge.start_pairing()
        return WhatsAppOperationsControlResponse.model_validate(result)

    router.add_api_route(
        "/operations",
        operations_status,
        methods=["GET"],
        response_model=WhatsAppOperationsStatusResponse,
    )
    router.add_api_route(
        "/recovery/{action}",
        recovery_control,
        methods=["POST"],
        response_model=WhatsAppOperationsControlResponse,
    )
    router.add_api_route(
        "/pair",
        controlled_pairing,
        methods=["POST"],
        response_model=WhatsAppOperationsControlResponse,
    )
    return router
