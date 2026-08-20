"""One check for the two-network split: a dumped payload replays byte-identical."""

from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from pama_bridge import DumpIngest, replay


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


if __name__ == "__main__":
    test_dump_then_replay_round_trips()
    print("ok")
