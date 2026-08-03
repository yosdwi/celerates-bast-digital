from dataclasses import dataclass

from digital_bast.domain.models import DomainRecord, RecordOrigin


@dataclass(frozen=True, slots=True)
class MergeResult:
    record: DomainRecord
    changed: bool
    locked: bool


def merge_pipeline_record(
    existing: DomainRecord | None,
    incoming: DomainRecord,
) -> MergeResult:
    if existing is None:
        return MergeResult(record=incoming, changed=True, locked=False)
    if existing.origin is RecordOrigin.MANUAL:
        return MergeResult(record=existing, changed=False, locked=True)
    if existing == incoming:
        return MergeResult(record=existing, changed=False, locked=False)
    return MergeResult(record=incoming, changed=True, locked=False)
