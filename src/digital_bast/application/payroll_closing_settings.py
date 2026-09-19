"""Typed Payroll closing policy independent from legacy BAST reminder dates."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Final, Protocol

_MAX_CALENDAR_DAY: Final = 31
_MAX_CLOCK_HOUR: Final = 23
_MAX_POLICY_ITEMS: Final = 10
_SUPPORTED_ROLES: Final = frozenset({"Developer", "IoT Operations"})
_DEFAULT_ROLES: Final = ("Developer", "IoT Operations")
_DEFAULT_OFFSETS: Final = (5, 3, 1)


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


@dataclass(frozen=True, slots=True)
class PayrollClosingSettings:
    scope_key: str = "default"
    enabled: bool = False
    paused: bool = False
    closing_day: int = 20
    reminder_hour: int = 9
    reminder_offsets: tuple[int, ...] = _DEFAULT_OFFSETS
    target_roles: tuple[str, ...] = _DEFAULT_ROLES
    next_day_ready_hour: int = 6
    desired_version: int = 1
    applied_version: int = 0
    updated_by: str | None = None

    def __post_init__(self) -> None:
        _require(bool(self.scope_key.strip()), "scope_key must not be blank")
        _require(
            1 <= self.closing_day <= _MAX_CALENDAR_DAY,
            "closing_day must be between 1 and 31",
        )
        _require(
            0 <= self.reminder_hour <= _MAX_CLOCK_HOUR,
            "reminder_hour must be between 0 and 23",
        )
        _require(
            0 <= self.next_day_ready_hour <= _MAX_CLOCK_HOUR,
            "next_day_ready_hour must be between 0 and 23",
        )
        _require(
            1 <= len(self.reminder_offsets) <= _MAX_POLICY_ITEMS,
            "reminder_offsets must contain between 1 and 10 values",
        )
        _require(
            all(1 <= offset <= _MAX_CALENDAR_DAY for offset in self.reminder_offsets),
            "reminder_offsets must be between 1 and 31",
        )
        _require(
            tuple(sorted(set(self.reminder_offsets), reverse=True)) == self.reminder_offsets,
            "reminder_offsets must be unique and sorted descending",
        )
        _require(
            1 <= len(self.target_roles) <= _MAX_POLICY_ITEMS,
            "target_roles must contain between 1 and 10 roles",
        )
        _require(
            len(set(self.target_roles)) == len(self.target_roles),
            "target_roles must be unique",
        )
        _require(
            all(role in _SUPPORTED_ROLES for role in self.target_roles),
            "target_roles contains an unsupported role",
        )
        _require(self.desired_version > 0, "desired_version must be greater than zero")
        _require(
            0 <= self.applied_version <= self.desired_version,
            "applied_version must be between zero and desired_version",
        )

    @property
    def dispatch_enabled(self) -> bool:
        return self.enabled and not self.paused

    def with_desired_update(  # noqa: PLR0913 - mirrors the typed settings form
        self,
        *,
        enabled: bool,
        paused: bool,
        closing_day: int,
        reminder_hour: int,
        reminder_offsets: tuple[int, ...],
        target_roles: tuple[str, ...],
        next_day_ready_hour: int,
        actor: str,
    ) -> PayrollClosingSettings:
        normalized_offsets = tuple(sorted(set(reminder_offsets), reverse=True))
        normalized_roles = tuple(
            dict.fromkeys(role.strip() for role in target_roles if role.strip())
        )
        return replace(
            self,
            enabled=enabled,
            paused=paused,
            closing_day=closing_day,
            reminder_hour=reminder_hour,
            reminder_offsets=normalized_offsets,
            target_roles=normalized_roles,
            next_day_ready_hour=next_day_ready_hour,
            desired_version=self.desired_version + 1,
            updated_by=actor.strip(),
        )


class PayrollClosingSettingsStore(Protocol):
    async def load(self, scope_key: str = "default") -> PayrollClosingSettings: ...

    async def save(self, settings: PayrollClosingSettings) -> PayrollClosingSettings: ...

    async def mark_applied(self, scope_key: str, version: int) -> PayrollClosingSettings: ...
