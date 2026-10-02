from __future__ import annotations

from datetime import datetime  # noqa: TC003 - Pydantic resolves this type at runtime
from typing import TYPE_CHECKING, Annotated, Protocol

from fastapi import APIRouter, HTTPException, Query, Request, status
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from digital_bast.config import get_settings
from digital_bast.infrastructure.whatsapp_directory import (
    PayrollClosingGroupSetting,
    PostgresTalentWhatsAppDirectory,
    TalentWhatsAppBindOutcome,
    TalentWhatsAppBindResult,
    TalentWhatsAppDirectoryRow,
)
from digital_bast.infrastructure.whatsapp_outbound import (
    WhatsAppGroupDirectory,
    WhatsAppGroupParticipant,
)
from digital_bast.web.security import HeaderCsrf, require_session, verify_csrf

if TYPE_CHECKING:
    from digital_bast.web.dependencies import WebDependencies

_API_PREFIX = "/api/talentops/v1/whatsapp-directory"
_ADMIN_ROLES = frozenset({"owner", "admin"})


class DirectoryStore(Protocol):
    async def list_talents(self) -> tuple[TalentWhatsAppDirectoryRow, ...]: ...

    async def bind(self, employee_id: str, wa_jid: str) -> TalentWhatsAppBindResult: ...

    async def unbind(self, employee_id: str) -> bool: ...

    async def closing_group(self, scope_key: str) -> PayrollClosingGroupSetting: ...

    async def save_closing_group(
        self,
        scope_key: str,
        group_jid: str | None,
        actor: str,
    ) -> PayrollClosingGroupSetting: ...


class WhatsAppMappingInput(BaseModel):
    model_config = ConfigDict(frozen=True)

    wa_jid: str = Field(min_length=1, max_length=160)


class PayrollClosingGroupInput(BaseModel):
    model_config = ConfigDict(frozen=True)

    group_jid: str | None = Field(default=None, max_length=200)


class TalentDirectoryResponse(BaseModel):
    employee_id: str
    nrp: str
    full_name: str
    role: str
    wa_jid: str | None
    bound_at: datetime | None
    discovered_in_groups: bool


class GroupParticipantResponse(BaseModel):
    jid: str
    display_name: str
    number: str
    is_my_contact: bool
    is_admin: bool
    is_super_admin: bool
    employee_id: str | None = None
    nrp: str | None = None
    full_name: str | None = None


class WhatsAppGroupResponse(BaseModel):
    jid: str
    subject: str
    member_count: int
    participants: tuple[GroupParticipantResponse, ...]


class WhatsAppDirectoryResponse(BaseModel):
    ready: bool
    connection: str
    discovered_at: datetime | None
    groups: tuple[WhatsAppGroupResponse, ...]
    talents: tuple[TalentDirectoryResponse, ...]


class WhatsAppMappingResponse(BaseModel):
    outcome: str
    employee_id: str
    wa_jid: str | None


class PayrollClosingGroupResponse(BaseModel):
    scope_key: str
    group_jid: str | None
    bridge_ready: bool
    verified: bool
    group_subject: str | None = None


def _require_admin(role: str) -> None:
    if role.casefold() not in _ADMIN_ROLES:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access is required",
        )


def _configured_store() -> DirectoryStore | None:
    try:
        settings = get_settings()
    except (OSError, ValidationError):
        return None
    if settings.database_dsn is None:
        return None
    return PostgresTalentWhatsAppDirectory(settings.database_dsn.get_secret_value())


async def _groups(deps: WebDependencies) -> WhatsAppGroupDirectory:
    if deps.bot_bridge_status is None:
        return WhatsAppGroupDirectory(
            ready=False,
            connection="unavailable",
            groups=(),
        )
    return await deps.bot_bridge_status.get_groups()


def _participant_response(
    participant: WhatsAppGroupParticipant,
    talent_by_jid: dict[str, TalentWhatsAppDirectoryRow],
) -> GroupParticipantResponse:
    mapped = talent_by_jid.get(participant.jid)
    return GroupParticipantResponse(
        jid=participant.jid,
        display_name=participant.display_name,
        number=participant.number,
        is_my_contact=participant.is_my_contact,
        is_admin=participant.is_admin,
        is_super_admin=participant.is_super_admin,
        employee_id=None if mapped is None else mapped.employee_id,
        nrp=None if mapped is None else mapped.nrp,
        full_name=None if mapped is None else mapped.full_name,
    )


def _closing_response(
    setting: PayrollClosingGroupSetting,
    directory: WhatsAppGroupDirectory,
) -> PayrollClosingGroupResponse:
    matched = next((group for group in directory.groups if group.jid == setting.group_jid), None)
    return PayrollClosingGroupResponse(
        scope_key=setting.scope_key,
        group_jid=setting.group_jid,
        bridge_ready=directory.ready,
        verified=setting.group_jid is not None and directory.ready and matched is not None,
        group_subject=None if matched is None else matched.subject,
    )


def whatsapp_directory_router(  # noqa: C901 - cohesive API route factory
    deps: WebDependencies,
    store: DirectoryStore | None = None,
) -> APIRouter:
    router = APIRouter(prefix=_API_PREFIX, tags=["talentops-whatsapp-directory"])

    def selected_store() -> DirectoryStore:
        selected = store or _configured_store()
        if selected is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="WhatsApp directory storage is unavailable",
            )
        return selected

    async def directory(request: Request) -> WhatsAppDirectoryResponse:
        _ = await require_session(request, deps.sessions, deps.cookie, deps.now, api=True)
        talents = await selected_store().list_talents()
        groups = await _groups(deps)
        talent_by_jid = {
            talent.wa_jid: talent
            for talent in talents
            if talent.wa_jid is not None
        }
        discovered_jids = {
            participant.jid
            for group in groups.groups
            for participant in group.participants
        }
        return WhatsAppDirectoryResponse(
            ready=groups.ready,
            connection=groups.connection,
            discovered_at=groups.discovered_at,
            groups=tuple(
                WhatsAppGroupResponse(
                    jid=group.jid,
                    subject=group.subject,
                    member_count=group.member_count,
                    participants=tuple(
                        _participant_response(participant, talent_by_jid)
                        for participant in group.participants
                    ),
                )
                for group in groups.groups
            ),
            talents=tuple(
                TalentDirectoryResponse(
                    employee_id=talent.employee_id,
                    nrp=talent.nrp,
                    full_name=talent.full_name,
                    role=talent.role,
                    wa_jid=talent.wa_jid,
                    bound_at=talent.bound_at,
                    discovered_in_groups=talent.wa_jid in discovered_jids,
                )
                for talent in talents
            ),
        )

    async def bind_mapping(
        request: Request,
        employee_id: str,
        payload: WhatsAppMappingInput,
        csrf_token: HeaderCsrf = None,
    ) -> WhatsAppMappingResponse:
        _, record = await require_session(
            request,
            deps.sessions,
            deps.cookie,
            deps.now,
            api=True,
        )
        verify_csrf(record, csrf_token)
        _require_admin(record.user.role)
        result = await selected_store().bind(employee_id, payload.wa_jid)
        if result.outcome is TalentWhatsAppBindOutcome.INVALID_JID:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="Talent WhatsApp identity must be a direct @c.us or @lid JID",
            )
        if result.outcome is TalentWhatsAppBindOutcome.EMPLOYEE_NOT_FOUND:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Active Talent not found",
            )
        if result.outcome in {
            TalentWhatsAppBindOutcome.EMPLOYEE_ALREADY_BOUND,
            TalentWhatsAppBindOutcome.JID_ALREADY_BOUND,
        }:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=result.outcome.value,
            )
        return WhatsAppMappingResponse(
            outcome=result.outcome.value,
            employee_id=result.employee_id,
            wa_jid=result.wa_jid,
        )

    async def unbind_mapping(
        request: Request,
        employee_id: str,
        csrf_token: HeaderCsrf = None,
    ) -> WhatsAppMappingResponse:
        _, record = await require_session(
            request,
            deps.sessions,
            deps.cookie,
            deps.now,
            api=True,
        )
        verify_csrf(record, csrf_token)
        _require_admin(record.user.role)
        removed = await selected_store().unbind(employee_id)
        return WhatsAppMappingResponse(
            outcome="unbound" if removed else "not_bound",
            employee_id=employee_id,
            wa_jid=None,
        )

    async def closing_group(
        request: Request,
        scope_key: Annotated[str, Query(min_length=1, max_length=120)] = "default",
    ) -> PayrollClosingGroupResponse:
        _ = await require_session(request, deps.sessions, deps.cookie, deps.now, api=True)
        setting = await selected_store().closing_group(scope_key)
        return _closing_response(setting, await _groups(deps))

    async def save_closing_group(
        request: Request,
        payload: PayrollClosingGroupInput,
        scope_key: Annotated[str, Query(min_length=1, max_length=120)] = "default",
        csrf_token: HeaderCsrf = None,
    ) -> PayrollClosingGroupResponse:
        _, record = await require_session(
            request,
            deps.sessions,
            deps.cookie,
            deps.now,
            api=True,
        )
        verify_csrf(record, csrf_token)
        _require_admin(record.user.role)
        group_jid = (
            None
            if payload.group_jid is None or not payload.group_jid.strip()
            else payload.group_jid.strip()
        )
        groups = await _groups(deps)
        if (
            group_jid is not None
            and groups.ready
            and all(group.jid != group_jid for group in groups.groups)
        ):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Selected WhatsApp group is not present in the current discovery snapshot",
            )
        try:
            setting = await selected_store().save_closing_group(
                scope_key,
                group_jid,
                record.user.email,
            )
        except ValueError as error:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=str(error),
            ) from error
        return _closing_response(setting, groups)

    router.add_api_route(
        "",
        directory,
        methods=["GET"],
        response_model=WhatsAppDirectoryResponse,
    )
    router.add_api_route(
        "/mappings/{employee_id}",
        bind_mapping,
        methods=["PUT"],
        response_model=WhatsAppMappingResponse,
    )
    router.add_api_route(
        "/mappings/{employee_id}",
        unbind_mapping,
        methods=["DELETE"],
        response_model=WhatsAppMappingResponse,
    )
    router.add_api_route(
        "/closing-group",
        closing_group,
        methods=["GET"],
        response_model=PayrollClosingGroupResponse,
    )
    router.add_api_route(
        "/closing-group",
        save_closing_group,
        methods=["PUT"],
        response_model=PayrollClosingGroupResponse,
    )
    return router
