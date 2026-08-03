from dataclasses import asdict
from typing import Annotated

from fastapi import APIRouter, Form, Query, Request, status
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from digital_bast.web.contracts import GenerationPlanInput, SectionInput, StreamSectionInput
from digital_bast.web.dependencies import WebDependencies
from digital_bast.web.security import FormCsrf, HeaderCsrf, require_session, verify_csrf


def _add_stream_route(router: APIRouter, deps: WebDependencies) -> None:
    async def stream_section(
        request: Request, payload: StreamSectionInput, csrf_token: HeaderCsrf = None
    ) -> JSONResponse:
        _, session = await require_session(request, deps.sessions, deps.cookie, deps.now, api=True)
        verify_csrf(session, csrf_token)
        count = await deps.backend.store_section(payload)
        return JSONResponse({"success": True, "stored_count": count})

    router.add_api_route("/api/stream/section", stream_section, methods=["POST"])


def report_router(deps: WebDependencies, templates: Jinja2Templates) -> APIRouter:
    router = APIRouter()

    async def render_report(
        request: Request,
        report_type: Annotated[
            str, Form(alias="type", pattern="^(iotoperations|iotoperation|developer)$")
        ],
        month: Annotated[int, Form(ge=1, le=12)],
        csrf_token: FormCsrf = None,
    ) -> HTMLResponse:
        _, session = await require_session(request, deps.sessions, deps.cookie, deps.now, api=True)
        verify_csrf(session, csrf_token)
        normalized = "iotoperation" if report_type == "iotoperations" else report_type
        report = await deps.backend.report(normalized, deps.now().year, month, evidence_only=True)
        return templates.TemplateResponse(request, "report.html", {"report": report})

    router.add_api_route(
        "/report/evidence", render_report, methods=["POST"], response_class=HTMLResponse
    )

    async def all_report(
        request: Request,
        report_type: Annotated[str, Form(alias="type", pattern="^(iotoperation|developer)$")],
        month: Annotated[int, Form(ge=1, le=12)],
        csrf_token: FormCsrf = None,
    ) -> RedirectResponse:
        _, session = await require_session(request, deps.sessions, deps.cookie, deps.now, api=True)
        verify_csrf(session, csrf_token)
        result = await deps.backend.create_plan(
            GenerationPlanInput(type=report_type, month=month, year=deps.now().year)
        )
        if not result.success:
            return RedirectResponse("/admin/", status_code=status.HTTP_303_SEE_OTHER)
        return RedirectResponse(
            f"/admin/progressive-generator?plan_id={result.plan_id}",
            status_code=status.HTTP_303_SEE_OTHER,
        )

    router.add_api_route("/report/all", all_report, methods=["POST"])

    async def progressive_generator(
        request: Request, plan_id: Annotated[str, Query(min_length=1, max_length=128)]
    ) -> HTMLResponse:
        _, session = await require_session(request, deps.sessions, deps.cookie, deps.now, api=False)
        return templates.TemplateResponse(
            request,
            "progressive.html",
            {"plan_id": plan_id, "csrf_token": session.csrf_token},
        )

    router.add_api_route(
        "/admin/progressive-generator",
        progressive_generator,
        methods=["GET"],
        response_class=HTMLResponse,
    )

    async def report_editor(
        request: Request, plan_id: Annotated[str, Query(min_length=1, max_length=128)]
    ) -> HTMLResponse:
        _, session = await require_session(request, deps.sessions, deps.cookie, deps.now, api=False)
        result = await deps.backend.bulk_data(plan_id)
        return templates.TemplateResponse(
            request,
            "report_editor.html",
            {"result": result, "csrf_token": session.csrf_token},
        )

    router.add_api_route(
        "/admin/report-editor", report_editor, methods=["GET"], response_class=HTMLResponse
    )

    async def editor_post(
        request: Request,
        plan_id: Annotated[str, Form(min_length=1, max_length=128)],
        csrf_token: FormCsrf = None,
    ) -> RedirectResponse:
        _, session = await require_session(request, deps.sessions, deps.cookie, deps.now, api=True)
        verify_csrf(session, csrf_token)
        return RedirectResponse(
            f"/admin/report-editor?plan_id={plan_id}", status_code=status.HTTP_303_SEE_OTHER
        )

    router.add_api_route("/admin/report-editor", editor_post, methods=["POST"])

    async def generate_plan(
        request: Request,
        report_type: Annotated[str, Form(alias="type", pattern="^(iotoperation|developer)$")],
        month: Annotated[int, Form(ge=1, le=12)],
        csrf_token: FormCsrf = None,
    ) -> JSONResponse:
        _, session = await require_session(request, deps.sessions, deps.cookie, deps.now, api=True)
        verify_csrf(session, csrf_token)
        result = await deps.backend.create_plan(
            GenerationPlanInput(type=report_type, month=month, year=deps.now().year)
        )
        return JSONResponse(asdict(result))

    router.add_api_route("/api/generate/plan", generate_plan, methods=["POST"])

    async def generate_section(
        request: Request,
        section_id: Annotated[int, Form(ge=0)],
        plan_id: Annotated[str, Form(min_length=1, max_length=128)],
        csrf_token: FormCsrf = None,
    ) -> JSONResponse:
        _, session = await require_session(request, deps.sessions, deps.cookie, deps.now, api=True)
        verify_csrf(session, csrf_token)
        result = await deps.backend.generate_section(
            SectionInput(plan_id=plan_id, section_id=section_id)
        )
        return JSONResponse(asdict(result))

    router.add_api_route("/api/generate/section", generate_section, methods=["POST"])
    router.add_api_route("/api/generate/retry", generate_section, methods=["POST"])

    async def bulk_data(
        request: Request,
        plan_id: Annotated[str, Form(min_length=1, max_length=128)],
        csrf_token: FormCsrf = None,
    ) -> JSONResponse:
        _, session = await require_session(request, deps.sessions, deps.cookie, deps.now, api=True)
        verify_csrf(session, csrf_token)
        result = await deps.backend.bulk_data(plan_id)
        return JSONResponse(asdict(result))

    router.add_api_route("/api/generate/bulk-data", bulk_data, methods=["POST"])

    _add_stream_route(router, deps)
    return router
