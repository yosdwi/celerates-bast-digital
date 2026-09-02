from collections.abc import Awaitable, Callable
from pathlib import Path

from fastapi import FastAPI, Request, status
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from digital_bast.infrastructure.errors import InfrastructureError
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
from digital_bast.web.talent_mobile_links_router import talent_mobile_links_router
from digital_bast.web.talent_mobile_page_router import talent_mobile_page_router
from digital_bast.web.talent_mobile_router import talent_mobile_router
from digital_bast.web.talentops_page_router import talentops_page_router
from digital_bast.web.talentops_router import talentops_router
from digital_bast.web.task_evidence_router import task_evidence_router


def create_app(dependencies: WebDependencies) -> FastAPI:
    project_root = Path(__file__).resolve().parents[3]
    templates = Jinja2Templates(directory=project_root / "templates")
    templates.env.autoescape = True
    talentops_dist = project_root / "frontend" / "dist"
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
    # check_dir=False keeps ordinary Python import/test collection working before
    # a local frontend build exists. Production images always copy frontend/dist.
    app.mount(
        "/admin/talentops/assets",
        StaticFiles(directory=talentops_dist / "assets", check_dir=False),
        name="talentops-assets",
    )
    app.include_router(auth_router(dependencies, templates))
    app.include_router(page_router(dependencies, templates))
    app.include_router(report_router(dependencies, templates))
    app.include_router(attendance_router(dependencies, templates))
    app.include_router(talentops_router(dependencies))
    app.include_router(talent_mobile_links_router(dependencies))
    app.include_router(task_evidence_router(dependencies))
    app.include_router(talent_mobile_router())
    app.include_router(talent_mobile_page_router(talentops_dist))
    app.include_router(talentops_page_router(dependencies, talentops_dist))
    # Machine-to-machine ingest from the PAMA bridge: bearer-token auth of
    # its own, no session cookie, and excluded from the schema.
    app.include_router(sync_router)

    async def _security_headers(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; img-src 'self' data: blob:; style-src 'self'; "
            "script-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
        )
        response.headers["Referrer-Policy"] = (
            "no-referrer" if request.url.path.startswith("/talent/") else "same-origin"
        )
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

    async def _infrastructure_unavailable(_request: Request, _error: Exception) -> JSONResponse:
        return JSONResponse(
            {"detail": "A required backend service is temporarily unavailable. Please retry."},
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        )

    async def _liveness() -> JSONResponse:
        return JSONResponse({"status": "healthy", "service": "digital-bast-admin"})

    async def _readiness() -> JSONResponse:
        session_ready = await dependencies.sessions.ready()
        auth_ready = await dependencies.authenticator.ready()
        backend_ready = await dependencies.backend.ready()
        ready = session_ready and auth_ready and backend_ready
        return JSONResponse(
            {
                "status": "ready" if ready else "not_ready",
                "components": {
                    "session": "ready" if session_ready else "not_ready",
                    "authentication": "ready" if auth_ready else "not_ready",
                    "backend": "ready" if backend_ready else "not_ready",
                },
            },
            status_code=status.HTTP_200_OK if ready else status.HTTP_503_SERVICE_UNAVAILABLE,
        )

    _ = app.middleware("http")(_security_headers)
    app.add_exception_handler(SessionUnavailableError, _session_unavailable)
    app.add_exception_handler(AuthenticationUnavailableError, _auth_unavailable)
    app.add_exception_handler(WebBackendUnavailableError, _backend_unavailable)
    app.add_exception_handler(InfrastructureError, _infrastructure_unavailable)
    app.add_api_route("/health/live", _liveness, methods=["GET"])
    app.add_api_route("/health", _liveness, methods=["GET"])
    app.add_api_route("/health/ready", _readiness, methods=["GET"])
    return app
