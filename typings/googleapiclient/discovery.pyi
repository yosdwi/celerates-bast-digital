from collections.abc import Sequence
from typing import Protocol

from google.auth.credentials import Credentials

type JsonScalar = str | int | float | bool | None
type JsonValue = JsonScalar | list[JsonValue] | dict[str, JsonValue]
type GooglePayload = dict[str, JsonValue]

class BatchGetRequest(Protocol):
    def execute(self) -> GooglePayload: ...

class ValuesResource(Protocol):
    def batchGet(
        self,
        *,
        spreadsheetId: str,
        ranges: Sequence[str],
        majorDimension: str,
        valueRenderOption: str,
    ) -> BatchGetRequest: ...

class SpreadsheetsResource(Protocol):
    def values(self) -> ValuesResource: ...

class SheetsService(Protocol):
    def spreadsheets(self) -> SpreadsheetsResource: ...

def build(
    serviceName: str,
    version: str,
    *,
    credentials: Credentials | None = ...,
    cache_discovery: bool = ...,
) -> SheetsService: ...
