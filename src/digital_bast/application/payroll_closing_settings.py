"""Typed Payroll closing policy independent from legacy BAST reminder dates."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Final, Protocol

_SUPPORTED_ROLES: Final = frozenset({"Developer", "IoT Operations"})
_DEFAULT_ROLES: Final = ("Developer", "IoT Operations")
_DEFAULT_OFFSETS: Final = (5, 3, 1)


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
        if not self.scope_key.strip():
            raise ValueError("scope_key must not be blank")
        if not 1 <= self.closing_day <= 31:
            raise ValueError("closing_day must be between 1 and 31")
        if not 0 <= self.reminder_hour <= 23:
            raise ValueError("reminder_hour must be between 0 and 23")
        if not 0 <= self.next_day_ready_hour <= 23:
            raise ValueError("next_day_ready_hour must be between 0 and 23")
        if not self.reminder_offsets or len(self.reminder_offsets) > 10:
            raise ValueError("reminder_offsets must contain between 1 and 10 values")
        if any(offset <= 0 or offset > 31 for offset in self.reminder_offsets):
            raise ValueError("reminder_offsets must be between 1 and 31")
        if tuple(sorted(set(self.reminder_offsets), reverse=True)) != self.reminder_offsets:
            raise ValueError("reminder_offsets must be unique and sorted descending")
        if not self.target_roles or len(self.target_roles) > 10:
            raise ValueError("target_roles must contain between 1 and 10 roles")
        if len(set(self.target_roles)) != len(self.target_roles):
            raise ValueError("target_roles must be unique")
        if any(role not in _SUPPORTED_ROLES for role in self.target_roles):
            raise ValueError("target_roles contains an unsupported role")
        if self.desired_version <= 0:
            raise ValueError("desired_version must be greater than zero")
        if not 0 <= self.applied_version <= self.desired_version:
            raise ValueError("applied_version must be between zero and desired_version")

    @property
    def dispatch_enabled(self) -> bool:
        return self.enabled and not self.paused

    def with_desired_update(
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
        normalized_roles = tuple(dict.fromkeys(role.strip() for role in target_roles if role.strip()))
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
