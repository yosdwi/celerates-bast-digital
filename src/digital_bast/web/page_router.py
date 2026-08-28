from fastapi import APIRouter, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from digital_bast.web.dependencies import WebDependencies
from digital_bast.web.security import require_session


def page_router(deps: WebDependencies, templates: Jinja2Templates) -> APIRouter:
    router = APIRouter()

    async def dashboard(request: Request) -> HTMLResponse:
        _, session = await require_session(request, deps.sessions, deps.cookie, deps.now, api=False)
        return templates.TemplateResponse(
            request,
            "dashboard.html",
            {"user": session.user, "csrf_token": session.csrf_token},
        )

    # TalentOps is the front door now; the legacy dashboard (BAST generation,
    # attendance CSV export -- neither has a TalentOps equivalent yet) moves
    # here instead of disappearing.
    router.add_api_route(
        "/admin/legacy-reports", dashboard, methods=["GET"], response_class=HTMLResponse
    )

    async def to_talentops() -> RedirectResponse:
        return RedirectResponse("/admin/talentops/", status_code=status.HTTP_303_SEE_OTHER)

    router.add_api_route("/", to_talentops, methods=["GET"])
    router.add_api_route("/admin/", to_talentops, methods=["GET"])
    router.add_api_route("/admin", to_talentops, methods=["GET"])
    return router
