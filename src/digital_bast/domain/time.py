from calendar import monthrange
from datetime import date, datetime, timedelta
from typing import Final
from zoneinfo import ZoneInfo

from digital_bast.domain.errors import InvalidTimeError

JAKARTA: Final = ZoneInfo("Asia/Jakarta")
MAX_REALTIME_INTERVAL: Final = timedelta(minutes=15)


def in_jakarta(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise InvalidTimeError(value.isoformat())
    return value.astimezone(JAKARTA)


def month_dates(year: int, month: int) -> tuple[date, ...]:
    return tuple(date(year, month, day) for day in range(1, monthrange(year, month)[1] + 1))


def month_bounds(year: int, month: int) -> tuple[datetime, datetime]:
    dates = month_dates(year, month)
    start = datetime.combine(dates[0], datetime.min.time(), JAKARTA)
    end = datetime.combine(dates[-1] + timedelta(days=1), datetime.min.time(), JAKARTA)
    return start, end
