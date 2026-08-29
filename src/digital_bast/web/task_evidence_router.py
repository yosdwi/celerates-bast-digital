from __future__ import annotations

from typing import TYPE_CHECKING, Annotated
from uuid import UUID  # noqa: TC003 - FastAPI runtime metadata

from fastapi import APIRouter, HTTPException, Query, Request, Response, status

from digital_bast.application.workflow_control import WorkflowRole
from digital_bast.domain.completion import DateRange
from digital_bast.domain.time import JAKARTA, month_dates
from digital_bast.web.security import require_session
from digital_bast.web.task_evidence_contracts import (
    TaskEvidenceItemResponse,
    TaskEvidencePageResponse,
)

if TYPE_CHECKING:
    from datetime import datetime

    from digital_bast.application.task_evidence_review import TaskEvidenceReviewService
    from digital_bast.web.contracts import SessionRecord
    from digital_bast.web.dependencies import WebDependencies

_API_PREFIX = "/api/talentops/v1"
_ADMIN_ROLES = frozenset({"owner", "admin"})


def _review(deps: WebDependencies) -> TaskEvidenceReviewService:
    if deps.task_evidence_review is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Task evidence review service is unavailable",
        )
    return deps.task_evidence_review


def _selected_period(year: int, month: int, now: datetime) -> DateRange:
    local_now = now.astimezone(JAKARTA)
    _ = local_now  # timezone-normalize the clock consistently with TalentOps
    dates = month_dates(year, month)
    return DateRange(dates[0], dates[-1])


async def _authorize_read(deps: WebDependencies, record: SessionRecord) -> None:
    if record.user.role.casefold() in _ADMIN_ROLES:
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


def task_evidence_router(deps: WebDependencies) -> APIRouter:
    router = APIRouter(prefix=_API_PREFIX)

    async def list_task_evidence(  # noqa: PLR0913, PLR0917 - FastAPI parameters
        request: Request,
        year: Annotated[int, Query(ge=2020, le=2100)],
        month: Annotated[int, Query(ge=1, le=12)],
        nrp: Annotated[str | None, Query(max_length=120)] = None,
        limit: Annotated[int, Query(ge=1, le=200)] = 60,
        offset: Annotated[int, Query(ge=0)] = 0,
    ) -> TaskEvidencePageResponse:
        _, record = await require_session(request, deps.sessions, deps.cookie, deps.now, api=True)
        await _authorize_read(deps, record)
        selected_period = _selected_period(year, month, deps.now())
        page = await _review(deps).list_evidence(
            selected_period,
            nrp=nrp,
            limit=limit,
            offset=offset,
        )
        return TaskEvidencePageResponse(
            items=tuple(
                TaskEvidenceItemResponse(
                    id=item.id,
                    employee_id=item.employee_id,
                    nrp=item.nrp,
                    full_name=item.full_name,
                    role=item.role,
                    task_id=item.task_id,
                    work_date=item.work_date,
                    task_title=item.task_title,
                    task_source=item.task_source,
                    caption=item.caption,
                    content_type=item.content_type,
                    byte_size=item.byte_size,
                    uploaded_at=item.uploaded_at,
                    image_url=f"{_API_PREFIX}/task-evidence/{item.id}/image",
                )
                for item in page.items
            ),
            total=page.total,
            limit=page.limit,
            offset=page.offset,
        )

    async def task_evidence_image(request: Request, evidence_id: UUID) -> Response:
        _, record = await require_session(request, deps.sessions, deps.cookie, deps.now, api=True)
        await _authorize_read(deps, record)
        evidence = await _review(deps).content(evidence_id)
        if evidence is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Evidence not found")
        return Response(
            content=evidence.content,
            media_type=evidence.content_type,
            headers={
                "Cache-Control": "private, no-store",
                "Content-Length": str(evidence.byte_size),
            },
        )

    router.add_api_route(
        "/task-evidence",
        list_task_evidence,
        methods=["GET"],
        response_model=TaskEvidencePageResponse,
    )
    router.add_api_route(
        "/task-evidence/{evidence_id}/image",
        task_evidence_image,
        methods=["GET"],
        response_class=Response,
    )
    return router
