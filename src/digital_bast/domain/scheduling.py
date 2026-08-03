from dataclasses import dataclass
from datetime import datetime, time, timedelta
from typing import Final, NewType

from digital_bast.domain.errors import InvalidTimeError
from digital_bast.domain.time import JAKARTA, MAX_REALTIME_INTERVAL, in_jakarta


@dataclass(frozen=True, slots=True)
class SyncSchedule:
    realtime_interval: timedelta = MAX_REALTIME_INTERVAL
    nightly_at: time = time(1, 0, tzinfo=JAKARTA)

    def __post_init__(self) -> None:
        if not timedelta(0) < self.realtime_interval <= MAX_REALTIME_INTERVAL:
            raise InvalidTimeError(str(self.realtime_interval))
        if self.nightly_at.tzinfo is None:
            raise InvalidTimeError(str(self.nightly_at))

    def next_realtime_after(self, value: datetime) -> datetime:
        return in_jakarta(value) + self.realtime_interval

    def next_nightly_after(self, value: datetime) -> datetime:
        local = in_jakarta(value)
        candidate = datetime.combine(local.date(), self.nightly_at)
        return candidate if candidate > local else candidate + timedelta(days=1)


ProcedureName = NewType("ProcedureName", str)
UPDATE_IOT_PIC: Final = ProcedureName("public.sp_update_tasklist_iot_pic")
