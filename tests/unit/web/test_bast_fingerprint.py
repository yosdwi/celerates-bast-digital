from __future__ import annotations

from datetime import UTC, datetime

from digital_bast.web.bast_assembler import compute_fingerprint

_WHEN = datetime(2026, 8, 19, 12, 0, 0, tzinfo=UTC)


def _durable(version: int = 1) -> tuple[tuple[str, str, int, datetime], ...]:
    return (("domain", "task:2026-08-12:MTG-TF/1:abc", version, _WHEN),)


def _evidence(sha256: str = "hash1") -> tuple[tuple[str, str], ...]:
    return (("evidence-id-1", sha256),)


def test_fingerprint_is_stable_for_identical_input() -> None:
    first = compute_fingerprint(_durable(), _evidence())
    second = compute_fingerprint(_durable(), _evidence())

    assert first == second


def test_fingerprint_is_order_independent() -> None:
    durable = (
        ("domain", "task:a", 1, _WHEN),
        ("domain", "task:b", 1, _WHEN),
    )
    reversed_durable = tuple(reversed(durable))

    assert compute_fingerprint(durable, ()) == compute_fingerprint(reversed_durable, ())


def test_fingerprint_changes_when_a_task_version_bumps() -> None:
    before = compute_fingerprint(_durable(version=1), _evidence())
    after = compute_fingerprint(_durable(version=2), _evidence())

    assert before != after


def test_fingerprint_changes_when_an_evidence_row_is_added() -> None:
    before = compute_fingerprint(_durable(), _evidence())
    after = compute_fingerprint(_durable(), (*_evidence(), ("evidence-id-2", "hash2")))

    assert before != after


def test_fingerprint_changes_when_evidence_sha256_changes() -> None:
    before = compute_fingerprint(_durable(), _evidence(sha256="hash1"))
    after = compute_fingerprint(_durable(), _evidence(sha256="hash2"))

    assert before != after
