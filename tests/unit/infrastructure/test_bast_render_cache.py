from __future__ import annotations

import asyncio
import os
import time
from typing import TYPE_CHECKING

import pytest

from digital_bast.infrastructure.bast_render_cache import BastRenderCache, cache_key

if TYPE_CHECKING:
    from pathlib import Path

_PDF = b"%PDF-1.7\n" + b"x" * 64 + b"\n%%EOF"


class _RendererDownError(Exception):
    pass


def test_key_follows_the_rendered_html_so_a_template_change_is_never_served_stale() -> None:
    assert cache_key("<html>a</html>") == cache_key("<html>a</html>")
    assert cache_key("<html>a</html>") != cache_key("<html>b</html>")


async def test_identical_report_is_rendered_once_then_served_from_cache(tmp_path: Path) -> None:
    cache = BastRenderCache(tmp_path)
    renders: list[int] = []

    async def render() -> bytes:
        renders.append(1)
        return _PDF

    first, first_cached = await cache.get_or_render("developer", 2026, 9, "k1", render)
    second, second_cached = await cache.get_or_render("developer", 2026, 9, "k1", render)

    assert (first, first_cached) == (_PDF, False)
    assert (second, second_cached) == (_PDF, True)
    assert len(renders) == 1


async def test_changed_content_renders_again_and_only_the_newest_render_is_kept(
    tmp_path: Path,
) -> None:
    cache = BastRenderCache(tmp_path)

    async def render_old() -> bytes:
        return _PDF

    async def render_new() -> bytes:
        return _PDF + b"new"

    _ = await cache.get_or_render("developer", 2026, 9, "old-key", render_old)
    pdf, cached = await cache.get_or_render("developer", 2026, 9, "new-key", render_new)

    assert (pdf, cached) == (_PDF + b"new", False)
    assert cache.lookup("developer", 2026, 9, "old-key") is None
    assert cache.lookup("developer", 2026, 9, "new-key") == _PDF + b"new"


async def test_other_reports_and_months_do_not_share_or_evict_each_other(tmp_path: Path) -> None:
    cache = BastRenderCache(tmp_path)

    async def render() -> bytes:
        return _PDF

    for report_type, month in (("developer", 9), ("iotoperation", 9), ("developer", 8)):
        _ = await cache.get_or_render(report_type, 2026, month, "k", render)

    assert all(
        cache.lookup(report_type, 2026, month, "k") == _PDF
        for report_type, month in (("developer", 9), ("iotoperation", 9), ("developer", 8))
    )


async def test_concurrent_identical_requests_share_a_single_render(tmp_path: Path) -> None:
    cache = BastRenderCache(tmp_path)
    started = 0

    async def slow_render() -> bytes:
        nonlocal started
        started += 1
        await asyncio.sleep(0.4)
        return _PDF

    results = await asyncio.gather(
        *(cache.get_or_render("iotoperation", 2026, 9, "same", slow_render) for _ in range(4))
    )

    assert started == 1
    assert all(pdf == _PDF for pdf, _ in results)
    assert sorted(cached for _, cached in results) == [False, True, True, True]


async def test_a_failed_render_is_not_cached_and_releases_the_lock(tmp_path: Path) -> None:
    cache = BastRenderCache(tmp_path)

    async def broken() -> bytes:
        raise _RendererDownError

    with pytest.raises(_RendererDownError):
        _ = await cache.get_or_render("developer", 2026, 9, "k", broken)

    async def healthy() -> bytes:
        return _PDF

    pdf, cached = await cache.get_or_render("developer", 2026, 9, "k", healthy)
    assert (pdf, cached) == (_PDF, False)


def test_a_file_that_is_not_a_pdf_is_ignored(tmp_path: Path) -> None:
    cache = BastRenderCache(tmp_path)
    cache.store("developer", 2026, 9, "k", _PDF)
    stem = next(tmp_path.glob("*.pdf"))
    _ = stem.write_bytes(b"<html>truncated or corrupted")
    assert cache.lookup("developer", 2026, 9, "k") is None


def test_renders_older_than_120_days_are_pruned_on_the_next_store(tmp_path: Path) -> None:
    cache = BastRenderCache(tmp_path)
    cache.store("developer", 2026, 1, "k", _PDF)
    ancient = next(tmp_path.glob("developer_2026-01_*.pdf"))
    old = time.time() - 121 * 86_400
    os.utime(ancient, (old, old))

    cache.store("developer", 2026, 9, "k", _PDF)

    assert cache.lookup("developer", 2026, 1, "k") is None
    assert cache.lookup("developer", 2026, 9, "k") == _PDF
