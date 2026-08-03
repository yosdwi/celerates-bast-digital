from datetime import UTC, datetime

import pytest

from digital_bast.application.ports import SourceWindow, SyncCursor
from digital_bast.infrastructure.google import GooglePayload, GoogleSheetsChangeSource


class FakeDrive:
    def __init__(self) -> None:
        self.tokens: list[str] = []

    def start_page_token(self) -> str:
        return "start"

    def list_changes(self, page_cursor: str) -> GooglePayload:
        self.tokens.append(page_cursor)
        if page_cursor == "cursor-1":
            return {
                "changes": [
                    {
                        "file": {
                            "id": "sheet-1",
                            "mimeType": "application/vnd.google-apps.spreadsheet",
                        }
                    }
                ],
                "nextPageToken": "page-2",
            }
        return {
            "changes": [
                {
                    "file": {
                        "id": "sheet-1",
                        "mimeType": "application/vnd.google-apps.spreadsheet",
                    }
                }
            ],
            "newStartPageToken": "cursor-2",
        }


class FakeSheets:
    def read(self, spreadsheet_id: str, range_name: str) -> GooglePayload:
        return {"values": [[spreadsheet_id, range_name]]}


@pytest.mark.asyncio
async def test_cursor_replay_deduplicates_changes_and_advances_after_final_page() -> None:
    drive = FakeDrive()
    source = GoogleSheetsChangeSource(drive, FakeSheets())
    end = datetime(2026, 8, 3, 12, tzinfo=UTC)

    batch = await source.fetch(
        SourceWindow(datetime(2026, 8, 3, 11, tzinfo=UTC), end),
        SyncCursor("google_sheets", "cursor-1", datetime(2026, 8, 3, 11, tzinfo=UTC)),
    )

    assert batch.items == ("sheet-1",)
    next_marker = batch.cursor.token
    assert next_marker == "cursor-2"
    assert drive.tokens == ["cursor-1", "page-2"]
