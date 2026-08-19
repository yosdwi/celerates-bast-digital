from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC
from typing import ClassVar, Protocol, final

from anyio.to_thread import run_sync
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from digital_bast.application.ports import SourceBatch, SourceWindow, SyncCursor
from digital_bast.infrastructure.errors import InfrastructureError
from digital_bast.infrastructure.json_types import JsonValue

type GooglePayload = dict[str, JsonValue]


class DriveChanges(Protocol):
    def list_changes(self, page_token: str) -> GooglePayload: ...

    def start_page_token(self) -> str: ...


class SheetsValues(Protocol):
    def read(self, spreadsheet_id: str, range_name: str) -> GooglePayload: ...


class _File(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore", frozen=True)

    id: str
    mime_type: str = Field(default="", alias="mimeType")
    trashed: bool = False


class _Change(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore", frozen=True)

    removed: bool = False
    file: _File | None = None


class _ChangesPage(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore", frozen=True)

    changes: list[_Change] = Field(default_factory=list)
    next_page_token: str | None = Field(default=None, alias="nextPageToken")
    new_start_page_token: str | None = Field(default=None, alias="newStartPageToken")


@dataclass(frozen=True, slots=True)
class SheetChangeBatch:
    spreadsheet_ids: tuple[str, ...]
    next_cursor: str


@final
class GoogleSheetsChangeSource:
    def __init__(self, drive: DriveChanges, sheets: SheetsValues) -> None:
        self._drive: DriveChanges = drive
        self._sheets: SheetsValues = sheets

    def initial_cursor(self) -> str:
        return self._drive.start_page_token()

    def changes_since(self, cursor: str) -> SheetChangeBatch:
        page_token = cursor
        spreadsheet_ids: dict[str, None] = {}
        final_cursor: str | None = None
        while final_cursor is None:
            try:
                page = _ChangesPage.model_validate(self._drive.list_changes(page_token))
            except ValidationError as error:
                raise InfrastructureError(
                    service="google_drive",
                    operation="parse_changes",
                ) from error
            for change in page.changes:
                file = change.file
                if (
                    file is not None
                    and not change.removed
                    and not file.trashed
                    and file.mime_type == "application/vnd.google-apps.spreadsheet"
                ):
                    spreadsheet_ids[file.id] = None
            if page.next_page_token is not None:
                page_token = page.next_page_token
            elif page.new_start_page_token is not None:
                final_cursor = page.new_start_page_token
            else:
                raise InfrastructureError(service="google_drive", operation="advance_cursor")
        return SheetChangeBatch(tuple(spreadsheet_ids), final_cursor)

    def read_values(self, spreadsheet_id: str, range_name: str) -> GooglePayload:
        return self._sheets.read(spreadsheet_id, range_name)

    async def fetch(
        self,
        window: SourceWindow,
        cursor: SyncCursor | None,
    ) -> SourceBatch[str]:
        token = await run_sync(self.initial_cursor) if cursor is None else cursor.token
        batch = await run_sync(self.changes_since, token)
        watermark = window.end.astimezone(UTC)
        return SourceBatch(
            batch.spreadsheet_ids,
            SyncCursor("google_sheets", batch.next_cursor, watermark),
        )
