from collections.abc import Awaitable, Callable
from pathlib import Path

from fastapi import FastAPI, Request, status
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from digital_bast.web.attendance_router import attendance_router
from digital_bast.web.auth_router import auth_router
from digital_bast.web.dependencies import WebDependencies
from digital_bast.web.errors import (
    AuthenticationUnavailableError,
    SessionUnavailableError,
    WebBackendUnavailableError,
)
from digital_bast.web.page_router import page_router
from digital_bast.web.report_router import report_router
from digital_bast.web.sync_router import router as sync_router


def create_app(dependencies: WebDependencies) -> FastAPI:
    project_root = Path(__file__).resolve().parents[3]
    templates = Jinja2Templates(directory=project_root / "templates")
    templates.env.autoescape = True
    app = FastAPI(
        title="Digital BAST Admin",
        version="2.0.0",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.state.web_dependencies = dependencies
    app.add_middleware(GZipMiddleware, minimum_size=1_000)
    app.mount("/static", StaticFiles(directory=project_root / "static"), name="static")
    app.mount("/admin/static", StaticFiles(directory=project_root / "static"), name="admin-static")
    app.include_router(auth_router(dependencies, templates))
    app.include_router(page_router(dependencies, templates))
    app.include_router(report_router(dependencies, templates))
    app.include_router(attendance_router(dependencies, templates))
    # Machine-to-machine ingest from the PAMA bridge: bearer-token auth of
    # its own, no session cookie, and excluded from the schema.
    app.include_router(sync_router)

    async def _security_headers(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; img-src 'self' data:; style-src 'self'; "
            "script-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
        )
        response.headers["Referrer-Policy"] = "same-origin"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        return response

    async def _session_unavailable(_request: Request, _error: Exception) -> JSONResponse:
        return JSONResponse(
            {"detail": "Session service is temporarily unavailable."},
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        )

    async def _auth_unavailable(_request: Request, _error: Exception) -> JSONResponse:
        return JSONResponse(
            {"detail": "Authentication service is temporarily unavailable."},
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        )

    async def _backend_unavailable(_request: Request, _error: Exception) -> JSONResponse:
        return JSONResponse(
            {"detail": "Report service is temporarily unavailable."},
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        )

    async def _liveness() -> JSONResponse:
        return JSONResponse({"status": "healthy", "service": "digital-bast-admin"})

    async def _readiness() -> JSONResponse:
        ready = all(
            (
                await dependencies.sessions.ready(),
                await dependencies.authenticator.ready(),
                await dependencies.backend.ready(),
            )
        )
        return JSONResponse(
            {"status": "ready" if ready else "not_ready"},
            status_code=status.HTTP_200_OK if ready else status.HTTP_503_SERVICE_UNAVAILABLE,
        )

    _ = app.middleware("http")(_security_headers)
    app.add_exception_handler(SessionUnavailableError, _session_unavailable)
    app.add_exception_handler(AuthenticationUnavailableError, _auth_unavailable)
    app.add_exception_handler(WebBackendUnavailableError, _backend_unavailable)
    app.add_api_route("/health/live", _liveness, methods=["GET"])
    app.add_api_route("/health", _liveness, methods=["GET"])
    app.add_api_route("/health/ready", _readiness, methods=["GET"])
    return app
