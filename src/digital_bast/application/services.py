from dataclasses import dataclass
from typing import final

from digital_bast.application.ports import (
    CursorStore,
    DomainRepository,
    StoredProcedurePort,
    SyncCursor,
)
from digital_bast.domain.errors import CursorRegressionError
from digital_bast.domain.models import DomainRecord
from digital_bast.domain.rules import merge_pipeline_record
from digital_bast.domain.scheduling import UPDATE_IOT_PIC


@dataclass(frozen=True, slots=True)
class BatchResult:
    created_or_updated: int
    unchanged: int
    locked: int


@final
class PipelineService:
    __slots__ = ("_cursors", "_procedures", "_records")

    def __init__(
        self,
        records: DomainRepository,
        cursors: CursorStore,
        procedures: StoredProcedurePort,
    ) -> None:
        self._records = records
        self._cursors = cursors
        self._procedures = procedures

    async def upsert(self, records: tuple[DomainRecord, ...]) -> BatchResult:
        changed = 0
        unchanged = 0
        locked = 0
        unique_records = {record.key: record for record in sorted(records, key=repr)}
        for key in sorted(unique_records, key=str):
            incoming = unique_records[key]
            result = merge_pipeline_record(await self._records.get(key), incoming)
            if result.locked:
                locked += 1
            elif result.changed:
                await self._records.upsert(result.record)
                changed += 1
            else:
                unchanged += 1
        return BatchResult(changed, unchanged, locked)

    async def advance_cursor(self, cursor: SyncCursor) -> None:
        current = await self._cursors.load(cursor.source)
        if current is not None and cursor.watermark < current.watermark:
            raise CursorRegressionError(cursor.source)
        await self._cursors.save(cursor)

    async def trigger_iot_pic_update(self) -> None:
        await self._procedures.execute(UPDATE_IOT_PIC)
