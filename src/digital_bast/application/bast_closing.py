"""BAST closing campaign policy and evidence requirement control plane.

The 15-minute Prefect notification flow remains the scheduler heartbeat. This
module only decides whether a calendar-month BAST reminder is due and stores
admin-controlled evidence requirements. Task status itself always remains a
source-system fact (for example Redmine); this module never mutates tasks.
"""

from __future__ import annotations

from calendar import monthrange
from dataclasses import dataclass
from datetime import date, timedelta
from typing import TYPE_CHECKING, final

import psycopg
from anyio.to_thread import run_sync
from psycopg.rows import class_row

from digital_bast.infrastructure.errors import InfrastructureError

if TYPE_CHECKING:
    from collections.abc import Sequence

_DEFAULT_INITIAL_DAY = 25
_DEFAULT_FOLLOWUP_OFFSETS = (3, 1)
_DEFAULT_SEND_HOUR = 9
_MAX_CALENDAR_DAY = 31
_MAX_HOUR = 23
_INITIAL_DAY_ERROR = "initial_day must be between 1 and 31"
_SEND_HOUR_ERROR = "send_hour must be between 0 and 23"


@dataclass(frozen=True, slots=True)
class BastClosingSettings:
    scope_key: str
    enabled: bool = False
    initial_day: int = _DEFAULT_INITIAL_DAY
    followup_offsets: tuple[int, ...] = _DEFAULT_FOLLOWUP_OFFSETS
    send_hour: int = _DEFAULT_SEND_HOUR
    talent_reminder_enabled: bool = True
    pmo_summary_enabled: bool = True
    pmo_group_jid: str | None = None


@dataclass(frozen=True, slots=True)
class BastEvidenceRule:
    task_category: str
    evidence_required: bool


@dataclass(frozen=True, slots=True)
class BastClosingSchedule:
    year: int
    month: int
    initial_date: date
    followup_dates: tuple[date, ...]
    closing_date: date

    @property
    def talent_reminder_dates(self) -> tuple[date, ...]:
        """Unique chronological Talent reminder dates for this month."""
        return tuple(sorted({self.initial_date, *self.followup_dates}))

    def is_talent_reminder_date(self, value: date) -> bool:
        return value in self.talent_reminder_dates


class _SettingsRow:
    __slots__ = (
        "enabled",
        "followup_offsets",
        "initial_day",
        "pmo_group_jid",
        "pmo_summary_enabled",
        "scope_key",
        "send_hour",
        "talent_reminder_enabled",
    )

    def __init__(  # noqa: PLR0913, PLR0917 - mirrors one settings row
        self,
        scope_key: str,
        enabled: bool,
        initial_day: int,
        followup_offsets: Sequence[int],
        send_hour: int,
        talent_reminder_enabled: bool,
        pmo_summary_enabled: bool,
        pmo_group_jid: str | None,
    ) -> None:
        self.scope_key = scope_key
        self.enabled = enabled
        self.initial_day = int(initial_day)
        self.followup_offsets = tuple(int(value) for value in followup_offsets)
        self.send_hour = int(send_hour)
        self.talent_reminder_enabled = talent_reminder_enabled
        self.pmo_summary_enabled = pmo_summary_enabled
        self.pmo_group_jid = pmo_group_jid


class _EvidenceRuleRow:
    __slots__ = ("evidence_required", "task_category")

    def __init__(self, task_category: str, evidence_required: bool) -> None:
        self.task_category = task_category
        self.evidence_required = evidence_required


def _normalize_offsets(values: Sequence[int]) -> tuple[int, ...]:
    return tuple(
        sorted(
            {
                int(value)
                for value in values
                if 1 <= int(value) <= _MAX_CALENDAR_DAY
            },
            reverse=True,
        )
    )


def closing_schedule(
    year: int,
    month: int,
    settings: BastClosingSettings,
) -> BastClosingSchedule:
    """Resolve day-25/EOM-relative policy into concrete, collision-safe dates."""
    last_day = monthrange(year, month)[1]
    closing = date(year, month, last_day)
    initial = date(year, month, min(settings.initial_day, last_day))
    followups = tuple(
        closing - timedelta(days=offset)
        for offset in _normalize_offsets(settings.followup_offsets)
        if offset < last_day
    )
    # Keep the semantic initial date separately while removing collisions from
    # follow-ups (February commonly has day 25 == EOM-3).
    unique_followups = tuple(sorted({item for item in followups if item != initial}))
    return BastClosingSchedule(
        year=year,
        month=month,
        initial_date=initial,
        followup_dates=unique_followups,
        closing_date=closing,
    )


@final
class BastClosingControlService:
    def __init__(self, dsn: str, connect_timeout_seconds: int = 5) -> None:
        self._dsn = dsn
        self._connect_timeout_seconds = connect_timeout_seconds

    def _connect(self) -> psycopg.Connection[tuple[object, ...]]:
        return psycopg.connect(self._dsn, connect_timeout=self._connect_timeout_seconds)

    async def settings(self, scope_key: str = "default") -> BastClosingSettings:
        return await run_sync(self._settings, scope_key)

    async def save_settings(  # noqa: PLR0913 - explicit persisted settings contract
        self,
        *,
        scope_key: str,
        enabled: bool,
        initial_day: int,
        followup_offsets: tuple[int, ...],
        send_hour: int,
        talent_reminder_enabled: bool,
        pmo_summary_enabled: bool,
        pmo_group_jid: str | None,
        actor: str,
    ) -> BastClosingSettings:
        return await run_sync(
            self._save_settings,
            scope_key,
            enabled,
            initial_day,
            followup_offsets,
            send_hour,
            talent_reminder_enabled,
            pmo_summary_enabled,
            pmo_group_jid,
            actor,
        )

    async def evidence_rules(self, scope_key: str = "default") -> tuple[BastEvidenceRule, ...]:
        return await run_sync(self._evidence_rules, scope_key)

    async def evidence_requirements(self, scope_key: str = "default") -> dict[str, bool]:
        rules = await self.evidence_rules(scope_key)
        return {rule.task_category: rule.evidence_required for rule in rules}

    async def save_evidence_rules(
        self,
        scope_key: str,
        rules: tuple[BastEvidenceRule, ...],
        actor: str,
    ) -> tuple[BastEvidenceRule, ...]:
        return await run_sync(self._save_evidence_rules, scope_key, rules, actor)

    def _settings(self, scope_key: str) -> BastClosingSettings:
        try:
            with (
                self._connect() as connection,
                connection.cursor(row_factory=class_row(_SettingsRow)) as cursor,
            ):
                _ = cursor.execute(
                    """
                    SELECT scope_key, enabled, initial_day, followup_offsets,
                           send_hour, talent_reminder_enabled,
                           pmo_summary_enabled, pmo_group_jid
                    FROM bast_closing_settings
                    WHERE scope_key = %s
                    """,
                    (scope_key,),
                )
                row = cursor.fetchone()
        except psycopg.Error as error:
            raise InfrastructureError(
                service="postgres",
                operation="bast_closing_settings",
            ) from error
        if row is None:
            return BastClosingSettings(scope_key=scope_key)
        return BastClosingSettings(
            scope_key=row.scope_key,
            enabled=row.enabled,
            initial_day=row.initial_day,
            followup_offsets=_normalize_offsets(row.followup_offsets),
            send_hour=row.send_hour,
            talent_reminder_enabled=row.talent_reminder_enabled,
            pmo_summary_enabled=row.pmo_summary_enabled,
            pmo_group_jid=row.pmo_group_jid,
        )

    def _save_settings(  # noqa: PLR0913, PLR0917 - persisted settings contract
        self,
        scope_key: str,
        enabled: bool,
        initial_day: int,
        followup_offsets: tuple[int, ...],
        send_hour: int,
        talent_reminder_enabled: bool,
        pmo_summary_enabled: bool,
        pmo_group_jid: str | None,
        actor: str,
    ) -> BastClosingSettings:
        normalized_scope = scope_key.strip() or "default"
        normalized_offsets = _normalize_offsets(followup_offsets)
        normalized_group = (pmo_group_jid or "").strip() or None
        if not 1 <= initial_day <= _MAX_CALENDAR_DAY:
            raise ValueError(_INITIAL_DAY_ERROR)
        if not 0 <= send_hour <= _MAX_HOUR:
            raise ValueError(_SEND_HOUR_ERROR)
        try:
            with self._connect() as connection, connection.cursor() as cursor:
                _ = cursor.execute(
                    """
                    INSERT INTO bast_closing_settings (
                        scope_key, enabled, initial_day, followup_offsets,
                        send_hour, talent_reminder_enabled,
                        pmo_summary_enabled, pmo_group_jid, updated_by
                    ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    ON CONFLICT (scope_key) DO UPDATE SET
                        enabled = EXCLUDED.enabled,
                        initial_day = EXCLUDED.initial_day,
                        followup_offsets = EXCLUDED.followup_offsets,
                        send_hour = EXCLUDED.send_hour,
                        talent_reminder_enabled = EXCLUDED.talent_reminder_enabled,
                        pmo_summary_enabled = EXCLUDED.pmo_summary_enabled,
                        pmo_group_jid = EXCLUDED.pmo_group_jid,
                        updated_by = EXCLUDED.updated_by,
                        updated_at = now()
                    """,
                    (
                        normalized_scope,
                        enabled,
                        initial_day,
                        list(normalized_offsets),
                        send_hour,
                        talent_reminder_enabled,
                        pmo_summary_enabled,
                        normalized_group,
                        actor,
                    ),
                )
        except psycopg.Error as error:
            raise InfrastructureError(
                service="postgres",
                operation="save_bast_closing_settings",
            ) from error
        return BastClosingSettings(
            scope_key=normalized_scope,
            enabled=enabled,
            initial_day=initial_day,
            followup_offsets=normalized_offsets,
            send_hour=send_hour,
            talent_reminder_enabled=talent_reminder_enabled,
            pmo_summary_enabled=pmo_summary_enabled,
            pmo_group_jid=normalized_group,
        )

    def _evidence_rules(self, scope_key: str) -> tuple[BastEvidenceRule, ...]:
        try:
            with (
                self._connect() as connection,
                connection.cursor(row_factory=class_row(_EvidenceRuleRow)) as cursor,
            ):
                _ = cursor.execute(
                    """
                    SELECT task_category, evidence_required
                    FROM bast_evidence_rules
                    WHERE scope_key = %s
                    ORDER BY task_category
                    """,
                    (scope_key,),
                )
                rows = cursor.fetchall()
        except psycopg.Error as error:
            raise InfrastructureError(
                service="postgres",
                operation="bast_evidence_rules",
            ) from error
        return tuple(BastEvidenceRule(row.task_category, row.evidence_required) for row in rows)

    def _save_evidence_rules(
        self,
        scope_key: str,
        rules: tuple[BastEvidenceRule, ...],
        actor: str,
    ) -> tuple[BastEvidenceRule, ...]:
        normalized_scope = scope_key.strip() or "default"
        normalized: dict[str, bool] = {}
        for rule in rules:
            category = rule.task_category.strip()
            if category:
                normalized[category] = bool(rule.evidence_required)
        try:
            with self._connect() as connection, connection.cursor() as cursor:
                _ = cursor.execute(
                    "DELETE FROM bast_evidence_rules WHERE scope_key = %s",
                    (normalized_scope,),
                )
                for category, required in sorted(normalized.items()):
                    _ = cursor.execute(
                        """
                        INSERT INTO bast_evidence_rules (
                            scope_key, task_category, evidence_required, updated_by
                        ) VALUES (%s,%s,%s,%s)
                        """,
                        (normalized_scope, category, required, actor),
                    )
        except psycopg.Error as error:
            raise InfrastructureError(
                service="postgres",
                operation="save_bast_evidence_rules",
            ) from error
        return tuple(
            BastEvidenceRule(task_category=category, evidence_required=required)
            for category, required in sorted(normalized.items())
        )
