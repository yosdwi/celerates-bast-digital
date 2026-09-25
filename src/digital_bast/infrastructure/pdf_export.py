"""Headless-Chromium PDF export driving V1's own jsPDF exporter (docs/bast-e2e-plan.md WP4/§3.8).

Deliberately not Chromium's native `page.pdf()` -- that is a different
rasteriser and would produce different output than the one a human gets from
the ported "Export PDF" button in report_editor.html. This module drives that
exact same html2canvas rendering per page (`window.__bastCapturePage()` in
templates/bast/report_editor.html -- same scale/quality/options as the
human-facing `__bastExportPdf()` button handler), but assembles the final PDF
here in Python (`_assemble_pdf`) instead of accumulating every page into one
in-browser jsPDF document -- that document gets slower to append to as it
grows, badly enough that a 100+ page report took ~30 minutes end to end.

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
# Chromium's renderer memory grows with total pages captured in one browser
# session and is never fully reclaimed by normal GC between html2canvas
# calls -- confirmed empirically: raising the container memory limit from
# 3G to 5G on a 126-page report only delayed the crash (from ~70s to
# ~310s), it did not prevent it; memory kept climbing at roughly the same
# rate regardless of the ceiling. Capturing in bounded batches, relaunching
# a fresh browser process between batches, keeps peak memory bounded
# (proportional to batch size, not total page count) instead of growing
# without limit across a 100+ page report.
# 2026-09-04: 25 still let peak memory climb close to bast-renderer's 5G
# cgroup ceiling on a dense report (this box only has 7.6G total, so a
# render camped near its own limit leaves little headroom for postgres/
# redis/nginx/ollama sharing the same host) -- 10 trades more frequent
# browser restarts (cheap: ~1-2s each) for a tighter peak-memory bound.
_PAGES_PER_BROWSER_BATCH: Final = 10


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


_A4_WIDTH_MM: Final = 210.0
_A4_HEIGHT_MM: Final = 297.0
# jsPDF's own 'a4' format constant is rounded to 2 decimal places (not the
# full-precision 595.275590551181/841.889763779528) -- matched exactly here
# so the MediaBox is identical to what jsPDF itself emits, not just close.
_A4_WIDTH_PT: Final = 595.28
_A4_HEIGHT_PT: Final = 841.89


def _assemble_pdf(pages: list[tuple[bytes, int, int]]) -> bytes:
    # jsPDF's own doc.addImage(imgData, 'JPEG', 0, 0, 210, canvas.height*210/
    # canvas.width) on a fixed-size 'a4' document -- reproduced here per page
    # (same width->mm scale, same implicit clip to the A4 MediaBox for any
    # page taller than 297mm) so a multi-hundred-page report doesn't have to
    # accumulate into one ever-growing in-browser jsPDF document (that grows
    # worse than linearly slower per page added -- a 126-page IoT report took
    # ~30 minutes). html2canvas/toDataURL themselves are untouched (see
    # __bastCapturePage in report_editor.html) -- this only changes how the
    # already-identical per-page JPEGs get assembled into one PDF.
    #
    # Deliberately NOT Pillow's own Image.save(format="PDF") here: verified
    # (see docs/bast-e2e-plan.md verification notes) that it always fully
    # decodes+re-encodes the JPEG through its own encoder when writing a PDF
    # -- regardless of img.mode/format -- which produced a measurable, if
    # visually subtle, pixel difference from jsPDF's own embed of the exact
    # same bytes (jsPDF, like every other real PDF generator, embeds a JPEG
    # XObject's compressed bytes verbatim -- DCTDecode passthrough, no
    # re-encode). This hand-assembles the same minimal structure (one
    # DCTDecode image XObject + one 3-line content stream per page) so each
    # page's PDF bytes are byte-for-byte identical to what jsPDF would have
    # produced for the same html2canvas JPEG -- confirmed page-by-page
    # against a real jsPDF-generated PDF before this replaced the Pillow
    # version.
    import io  # noqa: PLC0415

    from PIL import Image  # noqa: PLC0415

    objects: list[bytes] = []

    def add_object(body: bytes) -> int:
        objects.append(body)
        return len(objects)

    catalog_num = add_object(b"")
    pages_num = add_object(b"")

    page_obj_nums: list[int] = []
    for jpeg_bytes, width, height in pages:
        max_height_px = round(width * _A4_HEIGHT_MM / _A4_WIDTH_MM)
        if height > max_height_px:
            # Rare (content is designed to fit one A4 page): cropping
            # necessarily produces new pixel data, so this path re-encodes
            # (unlike the passthrough path below, which never touches the
            # original compressed bytes).
            img = Image.open(io.BytesIO(jpeg_bytes))
            img.load()
            img = img.crop((0, 0, width, max_height_px)).convert("RGB")
            buffer = io.BytesIO()
            img.save(buffer, format="JPEG", quality=95)
            jpeg_bytes = buffer.getvalue()
            width, height = img.size

        img_num = add_object(
            b"<< /Type /XObject /Subtype /Image /Width %d /Height %d "
            b"/ColorSpace /DeviceRGB /BitsPerComponent 8 /Filter /DCTDecode "
            b"/Length %d >>\nstream\n" % (width, height, len(jpeg_bytes)) + jpeg_bytes + b"\nendstream"
        )
        content = b"q\n%f 0 0 %f 0 0 cm\n/Im0 Do\nQ" % (_A4_WIDTH_PT, _A4_HEIGHT_PT)
        content_num = add_object(b"<< /Length %d >>\nstream\n" % len(content) + content + b"\nendstream")
        page_num = add_object(
            b"<< /Type /Page /Parent %d 0 R /MediaBox [0 0 %f %f] "
            b"/Resources << /XObject << /Im0 %d 0 R >> /ProcSet [/PDF /ImageC] >> "
            b"/Contents %d 0 R >>" % (pages_num, _A4_WIDTH_PT, _A4_HEIGHT_PT, img_num, content_num)
        )
        page_obj_nums.append(page_num)

    kids = b" ".join(b"%d 0 R" % n for n in page_obj_nums)
    objects[pages_num - 1] = b"<< /Type /Pages /Kids [%s] /Count %d >>" % (kids, len(page_obj_nums))
    objects[catalog_num - 1] = b"<< /Type /Catalog /Pages %d 0 R >>" % pages_num

    buffer = io.BytesIO()
    buffer.write(b"%PDF-1.4\n")
    offsets = [0]
    for index, body in enumerate(objects, start=1):
        offsets.append(buffer.tell())
        buffer.write(b"%d 0 obj\n" % index)
        buffer.write(body)
        buffer.write(b"\nendobj\n")
    xref_offset = buffer.tell()
    total = len(objects) + 1
    buffer.write(b"xref\n0 %d\n" % total)
    buffer.write(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        buffer.write(b"%010d 00000 n \n" % offset)
    buffer.write(b"trailer\n<< /Size %d /Root 1 0 R >>\n" % total)
    buffer.write(b"startxref\n%d\n%%%%EOF" % xref_offset)
    return buffer.getvalue()


def _open_page(playwright, url: str):  # noqa: ANN001, ANN202
    browser = playwright.chromium.launch(args=["--no-sandbox", "--disable-dev-shm-usage"])
    page = browser.new_page()
    page.set_default_timeout(_EXPORT_TIMEOUT_MS)
    _ = page.goto(url, wait_until="domcontentloaded")
    # networkidle is an imprecise proxy for "the CDN scripts finished
    # loading" -- wait for the globals they define directly instead.
    _ = page.wait_for_function("() => window.jspdf && window.html2canvas")
    return browser, page


def _capture(url: str, count: int) -> bytes:
    from playwright.sync_api import sync_playwright  # noqa: PLC0415

    with sync_playwright() as playwright:
        pages: list[tuple[bytes, int, int]] = []
        start = 0
        while start < count:
            end = min(start + _PAGES_PER_BROWSER_BATCH, count)
            browser, page = _open_page(playwright, url)
            try:
                for index in range(start, end):
                    result = page.evaluate("(i) => window.__bastCapturePage(i)", index)
                    _, _, encoded = result["dataUrl"].partition(",")
                    pages.append((base64.b64decode(encoded), result["width"], result["height"]))
            finally:
                browser.close()
            start = end
    return _assemble_pdf(pages)


def _render(editor_html: str) -> bytes:
    import tempfile  # noqa: PLC0415

    from playwright.sync_api import Error as PlaywrightError  # noqa: PLC0415
    from playwright.sync_api import TimeoutError as PlaywrightTimeoutError  # noqa: PLC0415

    # 2026-09-04: used to ask the browser (window.__bastPageCount(), a bare
    # document.querySelectorAll('.page').length) -- but that meant loading
    # the ENTIRE multi-hundred-page document into one Chromium tab just to
    # count it, before any of the batching below ever kicks in. A dense IoT
    # report (the "3. Detail Respon..." table alone can run 50 rows/page
    # across several pages) crashed Chromium ("Target crashed") on exactly
    # this step. report_editor.html only ever emits `<div class="page
    # portrait ...">` for actual pages (page-container/page-header are
    # different classes, not prefix-matched by this), so Python can count
    # the same thing for free from the HTML it already has in hand.
    count = editor_html.count('class="page portrait')

    with tempfile.TemporaryDirectory() as raw_root:
        root = Path(raw_root)
        _write_server_root(root, editor_html)
        try:
            with _serve(root) as port:
                return _capture(f"http://127.0.0.1:{port}/editor.html", count)
        except PlaywrightTimeoutError as error:
            raise UpstreamTimeoutError(service="playwright", operation="export_pdf") from error
        except PlaywrightError as error:
            raise InfrastructureError(service="playwright", operation="export_pdf") from error


async def _render_pdf_local(editor_html: str) -> bytes:
    return await run_sync(_render, editor_html)


async def render_pdf(editor_html: str) -> bytes:
    # When BAST_RENDERER_URL is set, delegate to the dedicated bast-renderer
    # container instead of running Chromium in this process -- keeps a
    # 10+ minute, memory-heavy render from sharing this process's event
    # loop/thread pool/memory cgroup with unrelated API traffic (Command
    # Center, BAST readiness, etc). Falls back to local rendering when unset
    # (e.g. the renderer container itself, or a dev environment without the
    # separate service).
    import os  # noqa: PLC0415

    renderer_url = os.environ.get("BAST_RENDERER_URL")
    if not renderer_url:
        return await _render_pdf_local(editor_html)

    import httpx  # noqa: PLC0415

    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(1200.0, connect=10.0)) as client:
            response = await client.post(
                f"{renderer_url}/internal/render-pdf",
                content=editor_html.encode("utf-8"),
                headers={"Content-Type": "text/html; charset=utf-8"},
            )
            response.raise_for_status()
            return response.content
    except httpx.TimeoutException as error:
        raise UpstreamTimeoutError(service="bast-renderer", operation="export_pdf") from error
    except httpx.HTTPError as error:
        raise InfrastructureError(service="bast-renderer", operation="export_pdf") from error


def _render_png(html: str) -> bytes:
    from playwright.sync_api import Error as PlaywrightError  # noqa: PLC0415
    from playwright.sync_api import TimeoutError as PlaywrightTimeoutError  # noqa: PLC0415
    from playwright.sync_api import sync_playwright  # noqa: PLC0415

    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(args=["--no-sandbox", "--disable-dev-shm-usage"])
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


async def _render_png_local(html: str) -> bytes:
    return await run_sync(_render_png, html)


async def render_png(html: str) -> bytes:
    """Self-contained HTML (no external assets, expects a `#card` element to
    frame the screenshot) -> PNG bytes. Used for the WhatsApp group status
    matrix (§7) -- an internal image render, not the jsPDF/report_editor.html
    pipeline above, so it needs neither a local static server nor jspdf.

    Delegates to bast-renderer when BAST_RENDERER_URL is set (see
    render_pdf) -- this render is small/fast on its own, but still uses the
    same Chromium/Playwright machinery, so it's isolated the same way for
    consistency.
    """
    import os  # noqa: PLC0415

    renderer_url = os.environ.get("BAST_RENDERER_URL")
    if not renderer_url:
        return await _render_png_local(html)

    import httpx  # noqa: PLC0415

    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(60.0, connect=10.0)) as client:
            response = await client.post(
                f"{renderer_url}/internal/render-png",
                content=html.encode("utf-8"),
                headers={"Content-Type": "text/html; charset=utf-8"},
            )
            response.raise_for_status()
            return response.content
    except httpx.TimeoutException as error:
        raise UpstreamTimeoutError(service="bast-renderer", operation="render_png") from error
    except httpx.HTTPError as error:
        raise InfrastructureError(service="bast-renderer", operation="render_png") from error
