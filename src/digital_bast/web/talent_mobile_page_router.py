from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter, status
from fastapi.responses import FileResponse, HTMLResponse, Response

if TYPE_CHECKING:
    from pathlib import Path


def talent_mobile_page_router(dist_dir: Path) -> APIRouter:
    router = APIRouter()

    async def page() -> Response:
        index = dist_dir / "index.html"
        if not index.is_file():
            return HTMLResponse(
                (
                    "<!doctype html><html><body>"
                    "<h1>Talent mobile frontend is not built.</h1>"
                    "<p>Run the frontend build, then retry this page.</p>"
                    "</body></html>"
                ),
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        return FileResponse(index, media_type="text/html")

    router.add_api_route(
        "/talent/mobile",
        page,
        methods=["GET"],
        response_class=HTMLResponse,
    )
    router.add_api_route(
        "/talent/mobile/",
        page,
        methods=["GET"],
        response_class=HTMLResponse,
    )
    return router
