from collections.abc import ItemsView
from datetime import date

class HolidayCalendar:
    def items(self) -> ItemsView[date, str]: ...

def country_holidays(country: str, *, years: int) -> HolidayCalendar: ...
