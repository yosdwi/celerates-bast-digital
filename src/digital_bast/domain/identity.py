import hashlib
import unicodedata
from datetime import date

from digital_bast.domain.models import EmployeeId, RecordKey


def canonical_text(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).split()).casefold()


def daily_key(kind: str, work_date: date, employee_id: EmployeeId | str) -> RecordKey:
    return RecordKey(f"{kind}:{work_date.isoformat()}:{employee_id}")


def holiday_key(work_date: date) -> RecordKey:
    return RecordKey(f"holiday:{work_date.isoformat()}")


def task_key(
    work_date: date,
    employee_id: EmployeeId,
    title: str,
    source: str,
    source_id: str,
) -> RecordKey:
    identity = "\x1f".join((source, source_id.strip(), canonical_text(title)))
    digest = hashlib.sha256(identity.encode()).hexdigest()[:24]
    return RecordKey(f"task:{work_date.isoformat()}:{employee_id}:{digest}")


def task_day_key(work_date: date, employee_id: EmployeeId) -> str:
    return f"{work_date.isoformat()}_{employee_id}"
