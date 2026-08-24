from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Request, status
from fastapi.responses import FileResponse, HTMLResponse, Response

from digital_bast.web.dependencies import WebDependencies
from digital_bast.web.security import require_session


def talentops_page_router(
    deps: WebDependencies,
    dist_dir: Path,
) -> APIRouter:
    router = APIRouter()

    async def page(
        request: Request,
    ) -> Response:
        _ = await require_session(
            request,
            deps.sessions,
            deps.cookie,
            deps.now,
            api=False,
        )
        index = dist_dir / "index.html"
        if not index.is_file():
            return HTMLResponse(
                (
                    "<!doctype html><html><body>"
                    "<h1>TalentOps frontend is not built.</h1>"
                    "<p>Run the frontend build, then retry this page.</p>"
                    "</body></html>"
                ),
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        return FileResponse(index, media_type="text/html")

    async def client_route(
        request: Request,
        _path: str,
    ) -> Response:
        return await page(request)

    router.add_api_route(
        "/admin/talentops",
        page,
        methods=["GET"],
        response_class=HTMLResponse,
    )
    router.add_api_route(
        "/admin/talentops/",
        page,
        methods=["GET"],
        response_class=HTMLResponse,
    )
    router.add_api_route(
        "/admin/talentops/{_path:path}",
        client_route,
        methods=["GET"],
        response_class=HTMLResponse,
    )
    return router
