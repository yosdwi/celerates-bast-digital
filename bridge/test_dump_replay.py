"""One check for the two-network split: a dumped payload replays byte-identical."""

from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from pama_bridge import _MAX_CHUNK_CHARS, DumpIngest, _chunks, replay


class _Recorder:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        self.calls.append((path, payload))
        return {"upserted": len(payload["rows"])}


def test_dump_then_replay_round_trips() -> None:
    with TemporaryDirectory() as raw:
        directory = Path(raw)
        dump = DumpIngest(directory)
        first = {"rows": [{"nrp": "JI260011", "att_date": "2026-07-01"}]}
        second = {"period_start": "2026-07-01", "rows": [{"nrp": "JI260011"}]}
        assert dump.post("/internal/sync/attendance", first) == {"upserted": 1, "received": 0}
        _ = dump.post("/internal/sync/redmine", second)

        recorder = _Recorder()
        assert replay(recorder, directory) == 2  # pyright: ignore[reportArgumentType]
        assert recorder.calls == [
            ("/internal/sync/attendance", first),
            ("/internal/sync/redmine", second),
        ]
        assert json.loads(sorted(directory.glob("*.json"))[0].read_text())["path"] == (
            "/internal/sync/attendance"
        )


def test_chunks_stay_under_the_sheets_cell_limit_for_verbose_rows() -> None:
    # A real 109-row redmine dump once landed in a single 79,778-char chunk
    # under the old fixed-row-count batching -- already past Sheets' 50,000
    # char single-cell limit. Verbose rows (titles/descriptions), not row
    # count, are what blow the budget.
    verbose_rows = [{"title": "x" * 700, "id": i} for i in range(109)]

    chunks = _chunks(verbose_rows)

    assert sum(len(chunk) for chunk in chunks) == len(verbose_rows)
    assert all(len(json.dumps(chunk)) <= _MAX_CHUNK_CHARS + 2_000 for chunk in chunks)


def test_chunks_of_empty_rows_is_one_empty_chunk() -> None:
    assert _chunks([]) == [[]]


if __name__ == "__main__":
    test_dump_then_replay_round_trips()
    test_chunks_stay_under_the_sheets_cell_limit_for_verbose_rows()
    test_chunks_of_empty_rows_is_one_empty_chunk()
    print("ok")
