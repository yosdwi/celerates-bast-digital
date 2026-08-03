from typing import Annotated

from fastapi import APIRouter, Form, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from digital_bast.web.contracts import SessionId
from digital_bast.web.dependencies import WebDependencies
from digital_bast.web.errors import AuthenticationUnavailableError
from digital_bast.web.security import (
    FormCsrf,
    clear_session_cookie,
    load_session,
    new_session_record,
    set_session_cookie,
    verify_csrf,
)


def _add_logout_routes(
    router: APIRouter, deps: WebDependencies, templates: Jinja2Templates
) -> None:
    async def logout_confirmation(request: Request) -> HTMLResponse:
        loaded = await load_session(request, deps.sessions, deps.cookie, deps.now)
        csrf = loaded[1].csrf_token if loaded is not None else ""
        return templates.TemplateResponse(request, "logout.html", {"csrf_token": csrf})

    async def logout(request: Request, csrf_token: FormCsrf = None) -> RedirectResponse:
        loaded = await load_session(request, deps.sessions, deps.cookie, deps.now)
        if loaded is not None:
            verify_csrf(loaded[1], csrf_token)
            await deps.sessions.delete(loaded[0])
        response = RedirectResponse("/admin/login", status_code=status.HTTP_303_SEE_OTHER)
        clear_session_cookie(response, deps.cookie)
        return response

    for path in ("/auth/logout", "/admin/auth/logout"):
        router.add_api_route(
            path, logout_confirmation, methods=["GET"], response_class=HTMLResponse
        )
        router.add_api_route(path, logout, methods=["POST"])


def auth_router(deps: WebDependencies, templates: Jinja2Templates) -> APIRouter:
    router = APIRouter()

    async def login_page(request: Request) -> HTMLResponse | RedirectResponse:
        loaded = await load_session(request, deps.sessions, deps.cookie, deps.now)
        if loaded is not None:
            return RedirectResponse("/admin/", status_code=status.HTTP_303_SEE_OTHER)
        return templates.TemplateResponse(request, "login.html", {})

    router.add_api_route(
        "/login",
        login_page,
        methods=["GET"],
        response_class=HTMLResponse,
        response_model=None,
    )
    router.add_api_route(
        "/admin/login",
        login_page,
        methods=["GET"],
        response_class=HTMLResponse,
        response_model=None,
    )

    async def login(
        request: Request,
        email: Annotated[str, Form(min_length=3, max_length=320)],
        password: Annotated[str, Form(min_length=1, max_length=1024)],
    ) -> HTMLResponse | RedirectResponse:
        try:
            user = await deps.authenticator.authenticate_owner(email.strip().lower(), password)
        except AuthenticationUnavailableError:
            return templates.TemplateResponse(
                request,
                "login.html",
                {"error": "Authentication service is temporarily unavailable."},
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        if user is None or user.role != "owner":
            return templates.TemplateResponse(
                request,
                "login.html",
                {"error": "Invalid credentials or insufficient permissions."},
                status_code=status.HTTP_401_UNAUTHORIZED,
            )
        previous = await load_session(request, deps.sessions, deps.cookie, deps.now)
        if previous is not None:
            await deps.sessions.delete(previous[0])
        session_id = SessionId(deps.session_id())
        record = new_session_record(user, deps.now(), deps.cookie.ttl_seconds)
        await deps.sessions.create(session_id, record, deps.cookie.ttl_seconds)
        response = RedirectResponse("/admin/", status_code=status.HTTP_303_SEE_OTHER)
        set_session_cookie(response, session_id, deps.cookie)
        return response

    router.add_api_route("/auth/login", login, methods=["POST"], response_model=None)
    router.add_api_route("/admin/auth/login", login, methods=["POST"], response_model=None)

    _add_logout_routes(router, deps, templates)
    return router
