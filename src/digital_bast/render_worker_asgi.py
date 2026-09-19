"""Standalone ASGI app for headless-Chromium PDF/PNG rendering, isolated from
the main web app's process (see infrastructure/pdf_export.py's render_pdf/
render_png -- unchanged, this just exposes them over HTTP).

Runs as its own container (`bast-renderer` in compose.yaml) instead of inside
the same uvicorn process/thread pool as the API that serves live traffic
(Command Center, Talents, BAST readiness, etc). A 100+ page BAST render can
tie up the process for 10+ minutes and push memory close to its container
limit; when that happened inside the API container itself, unrelated
requests degraded or failed alongside it (Cloudflare 522s, "readiness gate
unavailable") because they shared the same event loop's thread pool and the
same memory cgroup. Isolating rendering into a separate container/process
means a heavy render can only ever affect itself.

No database, secrets, or other application dependencies -- deliberately
stateless (HTML/PNG-fragment in, bytes out) so it doesn't need `*app`'s
depends_on: postgres/redis/prefect-server, and can't crash-loop if those are
briefly unavailable.
"""

from __future__ import annotations

import asyncio

from fastapi import FastAPI, Request, Response

from digital_bast.infrastructure.pdf_export import _render_pdf_local, _render_png_local

app = FastAPI()

# One render at a time, VPS-wide (2026-09-04). This is the single choke
# point every trigger funnels through -- the WhatsApp bot's "generate bast"
# command, the admin panel's Preview/Final Generate buttons (both fire an
# async job that calls back in here), and the status-matrix PNG export --
# so a Semaphore here is enough to stop two heavy renders from ever running
# concurrently, without needing a distributed lock across those separate
# processes. Callers wait rather than fail: they're already async jobs
# polled from "Generation history", so queuing behind another render is
# invisible to whoever triggered it, and pdf_export.py's own HTTP client
# timeout (20 min) comfortably outlasts a reasonable queue wait.
_RENDER_SEMAPHORE = asyncio.Semaphore(1)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/internal/render-pdf")
async def render_pdf_endpoint(request: Request) -> Response:
    editor_html = (await request.body()).decode("utf-8")
    async with _RENDER_SEMAPHORE:
        pdf_bytes = await _render_pdf_local(editor_html)
    return Response(content=pdf_bytes, media_type="application/pdf")


@app.post("/internal/render-png")
async def render_png_endpoint(request: Request) -> Response:
    html = (await request.body()).decode("utf-8")
    async with _RENDER_SEMAPHORE:
        png_bytes = await _render_png_local(html)
    return Response(content=png_bytes, media_type="image/png")
