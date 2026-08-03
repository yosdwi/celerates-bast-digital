from typing import override


class DomainError(Exception):
    pass


class MissingFieldError(DomainError):
    def __init__(self, field: str) -> None:
        super().__init__(field)
        self.field: str = field

    @override
    def __str__(self) -> str:
        return f"required field is missing: {self.field}"


class InvalidTimeError(DomainError):
    def __init__(self, value: str) -> None:
        super().__init__(value)
        self.value: str = value

    @override
    def __str__(self) -> str:
        return f"invalid time value: {self.value}"


class InvalidMonthError(DomainError):
    def __init__(self, year: int, month: int) -> None:
        super().__init__(year, month)
        self.year: int = year
        self.month: int = month

    @override
    def __str__(self) -> str:
        return f"invalid calendar month: {self.year:04d}-{self.month:02d}"


class CursorRegressionError(DomainError):
    def __init__(self, source: str) -> None:
        super().__init__(source)
        self.source: str = source

    @override
    def __str__(self) -> str:
        return f"cursor for {self.source} cannot move backwards"


class InvalidAchievementError(DomainError):
    def __init__(self, value: int) -> None:
        super().__init__(value)
        self.value: int = value

    @override
    def __str__(self) -> str:
        return f"achievement must be between 0 and 100: {self.value}"
