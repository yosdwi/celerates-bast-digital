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

    router.add_api_route("/", dashboard, methods=["GET"], response_class=HTMLResponse)
    router.add_api_route("/admin/", dashboard, methods=["GET"], response_class=HTMLResponse)

    async def admin_redirect() -> RedirectResponse:
        return RedirectResponse("/admin/", status_code=status.HTTP_308_PERMANENT_REDIRECT)

    router.add_api_route("/admin", admin_redirect, methods=["GET"])
    return router
