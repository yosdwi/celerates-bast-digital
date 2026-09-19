from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Final, final

import psycopg
from anyio.to_thread import run_sync
from psycopg.rows import class_row

from digital_bast.infrastructure.errors import InfrastructureError

_DIRECT_JID: Final = re.compile(r"^[0-9]+@(c\.us|lid)$")
_GROUP_JID: Final = re.compile(r"^[0-9]+(?:-[0-9]+)?@g\.us$")


@dataclass(frozen=True, slots=True)
class TalentWhatsAppDirectoryRow:
    employee_id: str
    nrp: str
    full_name: str
    role: str
    wa_jid: str | None
    bound_at: datetime | None


@dataclass(frozen=True, slots=True)
class PayrollClosingGroupSetting:
    scope_key: str
    group_jid: str | None


class TalentWhatsAppBindOutcome(StrEnum):
    BOUND = "bound"
    UNCHANGED = "unchanged"
    INVALID_JID = "invalid_jid"
    EMPLOYEE_NOT_FOUND = "employee_not_found"
    EMPLOYEE_ALREADY_BOUND = "employee_already_bound"
    JID_ALREADY_BOUND = "jid_already_bound"


@dataclass(frozen=True, slots=True)
class TalentWhatsAppBindResult:
    outcome: TalentWhatsAppBindOutcome
    employee_id: str
    wa_jid: str


class _DirectoryRow:
    __slots__ = ("bound_at", "employee_id", "full_name", "nrp", "role", "wa_jid")

    def __init__(
        self,
        employee_id: str,
        nrp: str,
        full_name: str,
        role: str,
        wa_jid: str | None,
        bound_at: datetime | None,
    ) -> None:
        self.employee_id = employee_id
        self.nrp = nrp
        self.full_name = full_name
        self.role = role
        self.wa_jid = wa_jid
        self.bound_at = bound_at


@final
class PostgresTalentWhatsAppDirectory:
    def __init__(self, dsn: str, connect_timeout_seconds: int = 5) -> None:
        self._dsn = dsn
        self._connect_timeout_seconds = connect_timeout_seconds

    def _connect(self) -> psycopg.Connection[tuple[object, ...]]:
        return psycopg.connect(self._dsn, connect_timeout=self._connect_timeout_seconds)

    async def list_talents(self) -> tuple[TalentWhatsAppDirectoryRow, ...]:
        return await run_sync(self._list_talents)

    async def bind(self, employee_id: str, wa_jid: str) -> TalentWhatsAppBindResult:
        return await run_sync(self._bind, employee_id, wa_jid)

    async def unbind(self, employee_id: str) -> bool:
        return await run_sync(self._unbind, employee_id)

    async def closing_group(self, scope_key: str) -> PayrollClosingGroupSetting:
        return await run_sync(self._closing_group, scope_key)

    async def save_closing_group(
        self,
        scope_key: str,
        group_jid: str | None,
        actor: str,
    ) -> PayrollClosingGroupSetting:
        return await run_sync(self._save_closing_group, scope_key, group_jid, actor)

    @staticmethod
    def valid_group_jid(value: str) -> bool:
        return _GROUP_JID.fullmatch(value.strip()) is not None

    def _list_talents(self) -> tuple[TalentWhatsAppDirectoryRow, ...]:
        try:
            with (
                self._connect() as connection,
                connection.cursor(row_factory=class_row(_DirectoryRow)) as cursor,
            ):
                _ = cursor.execute(
                    """
                    SELECT e.employee_id,
                           e.nrp,
                           e.full_name,
                           e.role,
                           wi.wa_jid,
                           wi.bound_at
                    FROM employees e
                    LEFT JOIN wa_identity wi ON wi.employee_id = e.employee_id
                    WHERE e.status = 'Active'
                    ORDER BY e.full_name, e.nrp
                    """
                )
                rows = cursor.fetchall()
        except psycopg.Error as error:
            raise InfrastructureError(
                service="postgres",
                operation="list_talent_whatsapp_directory",
            ) from error
        return tuple(
            TalentWhatsAppDirectoryRow(
                employee_id=row.employee_id,
                nrp=row.nrp,
                full_name=row.full_name,
                role=row.role,
                wa_jid=row.wa_jid,
                bound_at=row.bound_at,
            )
            for row in rows
        )

    def _bind(self, employee_id: str, wa_jid: str) -> TalentWhatsAppBindResult:
        normalized_employee = employee_id.strip()
        normalized_jid = wa_jid.strip()
        if _DIRECT_JID.fullmatch(normalized_jid) is None:
            return TalentWhatsAppBindResult(
                TalentWhatsAppBindOutcome.INVALID_JID,
                normalized_employee,
                normalized_jid,
            )
        try:
            with self._connect() as connection, connection.cursor() as cursor:
                _ = cursor.execute(
                    "SELECT 1 FROM employees WHERE employee_id = %s AND status = 'Active'",
                    (normalized_employee,),
                )
                if cursor.fetchone() is None:
                    return TalentWhatsAppBindResult(
                        TalentWhatsAppBindOutcome.EMPLOYEE_NOT_FOUND,
                        normalized_employee,
                        normalized_jid,
                    )
                _ = cursor.execute(
                    "SELECT wa_jid, employee_id FROM wa_identity "
                    "WHERE employee_id = %s OR wa_jid = %s FOR UPDATE",
                    (normalized_employee, normalized_jid),
                )
                rows = cursor.fetchall()
                for current_jid, current_employee in rows:
                    if str(current_employee) == normalized_employee and str(current_jid) == normalized_jid:
                        return TalentWhatsAppBindResult(
                            TalentWhatsAppBindOutcome.UNCHANGED,
                            normalized_employee,
                            normalized_jid,
                        )
                    if str(current_employee) == normalized_employee:
                        return TalentWhatsAppBindResult(
                            TalentWhatsAppBindOutcome.EMPLOYEE_ALREADY_BOUND,
                            normalized_employee,
                            normalized_jid,
                        )
                    if str(current_jid) == normalized_jid:
                        return TalentWhatsAppBindResult(
                            TalentWhatsAppBindOutcome.JID_ALREADY_BOUND,
                            normalized_employee,
                            normalized_jid,
                        )
                _ = cursor.execute(
                    "INSERT INTO wa_identity (wa_jid, employee_id) VALUES (%s, %s)",
                    (normalized_jid, normalized_employee),
                )
        except psycopg.Error as error:
            raise InfrastructureError(
                service="postgres",
                operation="bind_talent_whatsapp_directory",
            ) from error
        return TalentWhatsAppBindResult(
            TalentWhatsAppBindOutcome.BOUND,
            normalized_employee,
            normalized_jid,
        )

    def _unbind(self, employee_id: str) -> bool:
        try:
            with self._connect() as connection, connection.cursor() as cursor:
                _ = cursor.execute(
                    "DELETE FROM wa_identity WHERE employee_id = %s",
                    (employee_id.strip(),),
                )
                return cursor.rowcount > 0
        except psycopg.Error as error:
            raise InfrastructureError(
                service="postgres",
                operation="unbind_talent_whatsapp_directory",
            ) from error

    def _closing_group(self, scope_key: str) -> PayrollClosingGroupSetting:
        normalized_scope = scope_key.strip() or "default"
        try:
            with self._connect() as connection, connection.cursor() as cursor:
                _ = cursor.execute(
                    "SELECT payroll_closing_group_jid FROM workflow_notification_settings "
                    "WHERE scope_key = %s",
                    (normalized_scope,),
                )
                row = cursor.fetchone()
        except psycopg.Error as error:
            raise InfrastructureError(
                service="postgres",
                operation="read_payroll_closing_group",
            ) from error
        group_jid = None if row is None or row[0] is None else str(row[0])
        return PayrollClosingGroupSetting(normalized_scope, group_jid)

    def _save_closing_group(
        self,
        scope_key: str,
        group_jid: str | None,
        actor: str,
    ) -> PayrollClosingGroupSetting:
        normalized_scope = scope_key.strip() or "default"
        normalized_jid = None if group_jid is None or not group_jid.strip() else group_jid.strip()
        if normalized_jid is not None and _GROUP_JID.fullmatch(normalized_jid) is None:
            msg = "group_jid must be a WhatsApp group JID ending in @g.us"
            raise ValueError(msg)
        try:
            with self._connect() as connection, connection.cursor() as cursor:
                _ = cursor.execute(
                    """
                    INSERT INTO workflow_notification_settings (
                        scope_key,
                        payroll_closing_group_jid,
                        updated_by
                    ) VALUES (%s, %s, %s)
                    ON CONFLICT (scope_key) DO UPDATE SET
                        payroll_closing_group_jid = EXCLUDED.payroll_closing_group_jid,
                        updated_by = EXCLUDED.updated_by,
                        updated_at = now()
                    """,
                    (normalized_scope, normalized_jid, actor),
                )
        except psycopg.Error as error:
            raise InfrastructureError(
                service="postgres",
                operation="save_payroll_closing_group",
            ) from error
        return PayrollClosingGroupSetting(normalized_scope, normalized_jid)
