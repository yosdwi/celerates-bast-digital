from datetime import datetime
from typing import ClassVar

from pydantic import BaseModel, ConfigDict, TypeAdapter

from digital_bast.domain.models import DomainRecord, EntityKind
from digital_bast.infrastructure.nocodb import JsonValue

DOMAIN_RECORD_ADAPTER: TypeAdapter[DomainRecord] = TypeAdapter(DomainRecord)


class DomainRecordRow(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    entity_kind: EntityKind
    payload: dict[str, JsonValue]


class PayloadRow(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    payload: dict[str, JsonValue]


class CursorRow(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    cursor_value: str
    watermark: datetime
