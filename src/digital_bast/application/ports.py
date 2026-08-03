from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from digital_bast.domain.errors import InvalidTimeError
from digital_bast.domain.models import DomainRecord, EntityKind, Month, RecordKey
from digital_bast.domain.scheduling import ProcedureName
from digital_bast.domain.time import in_jakarta


class DomainRepository(Protocol):
    async def get(self, key: RecordKey) -> DomainRecord | None: ...

    async def upsert(self, record: DomainRecord) -> None: ...

    async def list_month(self, kind: EntityKind, period: Month) -> tuple[DomainRecord, ...]: ...


class CursorStore(Protocol):
    async def load(self, source: str) -> "SyncCursor | None": ...

    async def save(self, cursor: "SyncCursor") -> None: ...


class StoredProcedurePort(Protocol):
    async def execute(self, procedure: ProcedureName) -> None: ...


class Clock(Protocol):
    def now(self) -> datetime: ...


@dataclass(frozen=True, slots=True)
class SourceWindow:
    start: datetime
    end: datetime

    def __post_init__(self) -> None:
        start = in_jakarta(self.start)
        end = in_jakarta(self.end)
        if end <= start:
            raise InvalidTimeError(end.isoformat())


@dataclass(frozen=True, slots=True)
class SyncCursor:
    source: str
    token: str
    watermark: datetime

    def __post_init__(self) -> None:
        _ = in_jakarta(self.watermark)


@dataclass(frozen=True, slots=True)
class SourceBatch[T_co]:
    items: tuple[T_co, ...]
    cursor: SyncCursor


class IncrementalSource[T_co](Protocol):
    async def fetch(
        self,
        window: SourceWindow,
        cursor: SyncCursor | None,
    ) -> SourceBatch[T_co]: ...
