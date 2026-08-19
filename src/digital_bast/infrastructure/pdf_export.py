"""Headless-Chromium PDF export driving V1's own jsPDF exporter (docs/bast-e2e-plan.md WP4/§3.8).

Deliberately not Chromium's native `page.pdf()` -- that is a different
rasteriser and would produce different output than the one a human gets from
the ported "Export PDF" button in report_editor.html. This module drives that
exact same html2canvas + jsPDF pipeline via `window.__bastExportPdf()`
(templates/bast/report_editor.html), just headless and returning bytes
instead of triggering a browser download.

The rendered editor HTML references `/admin/static/img/...` (verbatim from
v1-prod, including one path hardcoded outside any template variable in
timesheet_report_template.html) and is too large in places for a bare
`file://` load to behave consistently across Chromium versions, so this
spins up a throwaway local static file server for the duration of the export
-- not the full FastAPI admin app (auth/sessions/Redis), just static files.
"""

from __future__ import annotations

import base64
import functools
import http.server
import socketserver
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Final

from anyio.to_thread import run_sync

from digital_bast.infrastructure.errors import InfrastructureError, UpstreamTimeoutError

if TYPE_CHECKING:
    from collections.abc import Generator

_EXPORT_TIMEOUT_MS: Final = 180_000
_STATIC_DIR: Final = Path(__file__).resolve().parents[3] / "templates" / "bast" / "static" / "img"


class _QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        del format, args


def _write_server_root(root: Path, editor_html: str) -> None:
    admin_static = root / "admin" / "static" / "img"
    admin_static.mkdir(parents=True)
    for asset in _STATIC_DIR.iterdir():
        _ = (admin_static / asset.name).write_bytes(asset.read_bytes())
    _ = (root / "editor.html").write_text(editor_html, encoding="utf-8")


@contextmanager
def _serve(root: Path) -> Generator[int]:
    handler = functools.partial(_QuietHandler, directory=str(root))
    with socketserver.TCPServer(("127.0.0.1", 0), handler) as httpd:
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        try:
            yield httpd.server_address[1]
        finally:
            httpd.shutdown()
            thread.join(timeout=5)


def _capture(url: str) -> bytes:
    from playwright.sync_api import sync_playwright  # noqa: PLC0415

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            page = browser.new_page()
            page.set_default_timeout(_EXPORT_TIMEOUT_MS)
            _ = page.goto(url, wait_until="domcontentloaded")
            # networkidle is an imprecise proxy for "the CDN scripts finished
            # loading" -- wait for the globals they define directly instead.
            _ = page.wait_for_function("() => window.jspdf && window.html2canvas")
            data_uri: str = page.evaluate("() => window.__bastExportPdf()")
        finally:
            browser.close()
    _, _, encoded = data_uri.partition(",")
    return base64.b64decode(encoded)


def _render(editor_html: str) -> bytes:
    import tempfile  # noqa: PLC0415

    from playwright.sync_api import Error as PlaywrightError  # noqa: PLC0415
    from playwright.sync_api import TimeoutError as PlaywrightTimeoutError  # noqa: PLC0415

    with tempfile.TemporaryDirectory() as raw_root:
        root = Path(raw_root)
        _write_server_root(root, editor_html)
        try:
            with _serve(root) as port:
                return _capture(f"http://127.0.0.1:{port}/editor.html")
        except PlaywrightTimeoutError as error:
            raise UpstreamTimeoutError(service="playwright", operation="export_pdf") from error
        except PlaywrightError as error:
            raise InfrastructureError(service="playwright", operation="export_pdf") from error


async def render_pdf(editor_html: str) -> bytes:
    return await run_sync(_render, editor_html)


def _render_png(html: str) -> bytes:
    from playwright.sync_api import Error as PlaywrightError  # noqa: PLC0415
    from playwright.sync_api import TimeoutError as PlaywrightTimeoutError  # noqa: PLC0415
    from playwright.sync_api import sync_playwright  # noqa: PLC0415

    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            try:
                page = browser.new_page()
                page.set_default_timeout(_EXPORT_TIMEOUT_MS)
                page.set_content(html, wait_until="domcontentloaded")
                return page.locator("#card").screenshot()
            finally:
                browser.close()
    except PlaywrightTimeoutError as error:
        raise UpstreamTimeoutError(service="playwright", operation="render_png") from error
    except PlaywrightError as error:
        raise InfrastructureError(service="playwright", operation="render_png") from error


async def render_png(html: str) -> bytes:
    """Self-contained HTML (no external assets, expects a `#card` element to
    frame the screenshot) -> PNG bytes. Used for the WhatsApp group status
    matrix (§7) -- an internal image render, not the jsPDF/report_editor.html
    pipeline above, so it needs neither a local static server nor jspdf.
    """
    return await run_sync(_render_png, html)
