"""PostgreSQL adapter for the independent Payroll closing policy."""

from __future__ import annotations

from collections.abc import Sequence
from typing import LiteralString, cast, final

import psycopg
from anyio.to_thread import run_sync

from digital_bast.application.payroll_closing_settings import PayrollClosingSettings
from digital_bast.infrastructure.errors import InfrastructureError


@final
class PostgresPayrollClosingSettingsStore:
    def __init__(self, dsn: str, connect_timeout_seconds: int = 5) -> None:
        self._dsn = dsn
        self._connect_timeout_seconds = connect_timeout_seconds

    def _connect(self) -> psycopg.Connection[tuple[object, ...]]:
        return psycopg.connect(self._dsn, connect_timeout=self._connect_timeout_seconds)

    async def load(self, scope_key: str = "default") -> PayrollClosingSettings:
        return await run_sync(self._load, scope_key)

    async def save(self, settings: PayrollClosingSettings) -> PayrollClosingSettings:
        return await run_sync(self._save, settings)

    async def mark_applied(self, scope_key: str, version: int) -> PayrollClosingSettings:
        return await run_sync(self._mark_applied, scope_key, version)

    @staticmethod
    def _settings(row: tuple[object, ...] | None, scope_key: str) -> PayrollClosingSettings:
        if row is None:
            return PayrollClosingSettings(scope_key=scope_key)
        raw_offsets = row[5]
        raw_roles = row[6]
        offsets = (
            tuple(
                int(cast("int | str", value))
                for value in cast("Sequence[object]", raw_offsets)
            )
            if isinstance(raw_offsets, Sequence) and not isinstance(raw_offsets, (str, bytes))
            else ()
        )
        roles = (
            tuple(str(value) for value in cast("Sequence[object]", raw_roles))
            if isinstance(raw_roles, Sequence) and not isinstance(raw_roles, (str, bytes))
            else ()
        )
        return PayrollClosingSettings(
            scope_key=str(row[0]),
            enabled=bool(row[1]),
            paused=bool(row[2]),
            closing_day=int(cast("int | str", row[3])),
            reminder_hour=int(cast("int | str", row[4])),
            reminder_offsets=offsets,
            target_roles=roles,
            next_day_ready_hour=int(cast("int | str", row[7])),
            desired_version=int(cast("int | str", row[8])),
            applied_version=int(cast("int | str", row[9])),
            updated_by=None if row[10] is None else str(row[10]),
        )

    @staticmethod
    def _select_sql() -> LiteralString:
        return """
            SELECT scope_key,
                   payroll_closing_enabled,
                   payroll_closing_paused,
                   payroll_closing_day,
                   payroll_reminder_hour,
                   payroll_reminder_offsets,
                   payroll_target_roles,
                   payroll_next_day_ready_hour,
                   payroll_policy_desired_version,
                   payroll_policy_applied_version,
                   updated_by
            FROM workflow_notification_settings
        """

    def _load(self, scope_key: str) -> PayrollClosingSettings:
        normalized = scope_key.strip() or "default"
        try:
            with self._connect() as connection, connection.cursor() as cursor:
                _ = cursor.execute(
                    self._select_sql() + " WHERE scope_key = %s",
                    (normalized,),
                )
                row = cursor.fetchone()
        except psycopg.Error as error:
            raise InfrastructureError(
                service="postgres",
                operation="payroll_closing_settings",
            ) from error
        return self._settings(row, normalized)

    def _save(self, settings: PayrollClosingSettings) -> PayrollClosingSettings:
        actor = (settings.updated_by or "system").strip() or "system"
        try:
            with self._connect() as connection, connection.cursor() as cursor:
                _ = cursor.execute(
                    """
                    INSERT INTO workflow_notification_settings (
                        scope_key,
                        payroll_closing_enabled,
                        payroll_closing_paused,
                        payroll_closing_day,
                        payroll_reminder_hour,
                        payroll_reminder_offsets,
                        payroll_target_roles,
                        payroll_next_day_ready_hour,
                        payroll_policy_desired_version,
                        payroll_policy_applied_version,
                        updated_by
                    ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,1,0,%s)
                    ON CONFLICT (scope_key) DO UPDATE SET
                        payroll_closing_enabled = EXCLUDED.payroll_closing_enabled,
                        payroll_closing_paused = EXCLUDED.payroll_closing_paused,
                        payroll_closing_day = EXCLUDED.payroll_closing_day,
                        payroll_reminder_hour = EXCLUDED.payroll_reminder_hour,
                        payroll_reminder_offsets = EXCLUDED.payroll_reminder_offsets,
                        payroll_target_roles = EXCLUDED.payroll_target_roles,
                        payroll_next_day_ready_hour = EXCLUDED.payroll_next_day_ready_hour,
                        payroll_policy_desired_version =
                            workflow_notification_settings.payroll_policy_desired_version + 1,
                        updated_by = EXCLUDED.updated_by,
                        updated_at = now()
                    RETURNING scope_key,
                              payroll_closing_enabled,
                              payroll_closing_paused,
                              payroll_closing_day,
                              payroll_reminder_hour,
                              payroll_reminder_offsets,
                              payroll_target_roles,
                              payroll_next_day_ready_hour,
                              payroll_policy_desired_version,
                              payroll_policy_applied_version,
                              updated_by
                    """,
                    (
                        settings.scope_key,
                        settings.enabled,
                        settings.paused,
                        settings.closing_day,
                        settings.reminder_hour,
                        list(settings.reminder_offsets),
                        list(settings.target_roles),
                        settings.next_day_ready_hour,
                        actor,
                    ),
                )
                row = cursor.fetchone()
        except psycopg.Error as error:
            raise InfrastructureError(
                service="postgres",
                operation="save_payroll_closing_settings",
            ) from error
        if row is None:  # pragma: no cover - RETURNING invariant
            raise InfrastructureError(
                service="postgres",
                operation="reload_payroll_closing_settings",
            )
        return self._settings(row, settings.scope_key)

    def _mark_applied(self, scope_key: str, version: int) -> PayrollClosingSettings:
        normalized = scope_key.strip() or "default"
        try:
            with self._connect() as connection, connection.cursor() as cursor:
                _ = cursor.execute(
                    """
                    UPDATE workflow_notification_settings
                    SET payroll_policy_applied_version = GREATEST(
                            payroll_policy_applied_version,
                            %s
                        ),
                        updated_at = now()
                    WHERE scope_key = %s
                      AND %s <= payroll_policy_desired_version
                    """,
                    (version, normalized, version),
                )
        except psycopg.Error as error:
            raise InfrastructureError(
                service="postgres",
                operation="apply_payroll_closing_settings",
            ) from error
        return self._load(normalized)
