from __future__ import annotations

from typing import TYPE_CHECKING, Final, Protocol, final

from google.oauth2 import service_account
from googleapiclient.discovery import build

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

    from google.auth.credentials import Credentials
    from googleapiclient.discovery import SheetsService

    from digital_bast.infrastructure.google import GooglePayload

_SHEETS_READONLY_SCOPE: Final = "https://www.googleapis.com/auth/spreadsheets.readonly"
_SERVICE_ACCOUNT_LOADER_NAME: Final = "from_service_account_file"


class _ServiceAccountLoader(Protocol):
    def __call__(self, filename: str, *, scopes: Sequence[str]) -> Credentials: ...


@final
class GoogleApiSheetBatchReader:
    def __init__(self, credentials_path: str | Path) -> None:
        loader: _ServiceAccountLoader = getattr(
            service_account.Credentials,
            _SERVICE_ACCOUNT_LOADER_NAME,
        )
        credentials: Credentials = loader(
            str(credentials_path),
            scopes=[_SHEETS_READONLY_SCOPE],
        )
        self._service: SheetsService = build(
            "sheets",
            "v4",
            credentials=credentials,
            cache_discovery=False,
        )

    def batch_get(self, spreadsheet_id: str, ranges: tuple[str, ...]) -> GooglePayload:
        request = (
            self._service.spreadsheets()
            .values()
            .batchGet(
                spreadsheetId=spreadsheet_id,
                ranges=list(ranges),
                majorDimension="COLUMNS",
                valueRenderOption="FORMATTED_VALUE",
            )
        )
        return request.execute()
