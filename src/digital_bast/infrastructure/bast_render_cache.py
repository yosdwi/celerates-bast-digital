"""Content-addressed cache of rendered BAST PDFs.

A September report is 100+ image-heavy pages and takes 4-11 minutes to render
(Chromium, batches of 10 pages), and the renderer runs one render at a time.
Asking for the same report again -- a second person, a retry after a timeout,
the web and WhatsApp side by side -- used to pay that cost again every time.

The cache key is the sha256 of the *rendered editor HTML*, not of the source
rows: that HTML is a pure function of the data AND the templates/CSS, so a data
change, a template change or a CSS fix each produce a new key and can never be
served a stale PDF. (`assemble()` is deterministic: two runs of the same report
produced byte-identical HTML.)

Concurrent requests for the same key are coalesced with an advisory file lock
on the shared exports volume: the first renders, the others wait and then find
the PDF in the cache instead of queueing a second render.
"""

from __future__ import annotations

import fcntl
import hashlib
import os
import time
from typing import TYPE_CHECKING, Final

import anyio

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable
    from pathlib import Path

_PDF_MAGIC: Final = b"%PDF-"
_LOCK_POLL_SECONDS: Final = 1.0
# Slightly above the renderer request cap (1200s, pdf_export.py) so a waiter
# outlasts the render it is waiting on.
_LOCK_WAIT_SECONDS: Final = 1300.0
_MAX_AGE_SECONDS: Final = 120 * 86_400


def cache_key(editor_html: str) -> str:
    return hashlib.sha256(editor_html.encode("utf-8")).hexdigest()


class BastRenderCache:
    def __init__(self, root: Path) -> None:
        self._root = root

    def _stem(self, report_type: str, year: int, month: int, key: str) -> Path:
        return self._root / f"{report_type}_{year}-{month:02d}_{key[:24]}"

    def lookup(self, report_type: str, year: int, month: int, key: str) -> bytes | None:
        path = self._stem(report_type, year, month, key).with_suffix(".pdf")
        try:
            data = path.read_bytes()
        except OSError:
            return None
        return data if data.startswith(_PDF_MAGIC) else None

    def store(self, report_type: str, year: int, month: int, key: str, pdf: bytes) -> None:
        self._root.mkdir(parents=True, exist_ok=True)
        target = self._stem(report_type, year, month, key).with_suffix(".pdf")
        temporary = target.with_suffix(f".tmp-{os.getpid()}")
        _ = temporary.write_bytes(pdf)
        _ = temporary.replace(target)  # atomic: a reader never sees a half-written PDF
        self._prune(report_type, year, month, keep=target)

    def _prune(self, report_type: str, year: int, month: int, keep: Path) -> None:
        """Keep only the newest render per report/month, and drop anything very old."""
        prefix = f"{report_type}_{year}-{month:02d}_"
        cutoff = time.time() - _MAX_AGE_SECONDS
        for candidate in self._root.glob("*.pdf"):
            if candidate == keep:
                continue
            try:
                if candidate.name.startswith(prefix) or candidate.stat().st_mtime < cutoff:
                    candidate.unlink()
            except OSError:
                continue

    async def get_or_render(
        self,
        report_type: str,
        year: int,
        month: int,
        key: str,
        render: Callable[[], Awaitable[bytes]],
    ) -> tuple[bytes, bool]:
        """Return `(pdf, was_cached)`. Renders at most once per key at a time."""
        hit = self.lookup(report_type, year, month, key)
        if hit is not None:
            return hit, True
        self._root.mkdir(parents=True, exist_ok=True)
        lock_path = self._stem(report_type, year, month, key).with_suffix(".lock")
        descriptor = await _acquire(lock_path)
        try:
            # Another process may have finished the same render while we waited.
            hit = self.lookup(report_type, year, month, key)
            if hit is not None:
                return hit, True
            pdf = await render()
            self.store(report_type, year, month, key, pdf)
            return pdf, False
        finally:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
            os.close(descriptor)


async def _acquire(lock_path: Path) -> int:
    # Polling LOCK_NB (not a blocking flock in a thread) so a cancelled request
    # never leaves a thread parked on the lock holding a file descriptor.
    descriptor = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o640)
    deadline = time.monotonic() + _LOCK_WAIT_SECONDS
    while True:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            if time.monotonic() >= deadline:
                os.close(descriptor)
                message = "timed out waiting for another BAST render of the same report"
                raise TimeoutError(message) from None
            await anyio.sleep(_LOCK_POLL_SECONDS)
        except BaseException:
            os.close(descriptor)
            raise
        else:
            return descriptor
