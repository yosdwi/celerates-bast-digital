"""WhatsApp identity binding: wa_jid -> internal employee_id.

Normal talent onboarding is NRP + full-name confirmation (see
resolve_employee_by_nrp / ActivationService.claim/bind) -- talent know their
NRP and name, not the internal Employee ID. The employee-ID + activation-code
path (issue_codes/activate) is kept only as an admin fallback; it is no longer
the normal user-facing flow. Codes are bcrypt-hashed at rest (mirrors
web/nocodb_postgres_auth.py::_verify_password), expire on first successful
use, and lock an employee out for 15 minutes after 5 wrong attempts.
"""

from __future__ import annotations

import secrets
import string
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import TYPE_CHECKING, Final, final

import bcrypt
import psycopg
from anyio.to_thread import run_sync
from psycopg.rows import class_row

from digital_bast.domain.identity import canonical_text
from digital_bast.infrastructure.errors import InfrastructureError

if TYPE_CHECKING:
    from digital_bast.domain.models import Employee

_CODE_ALPHABET: Final = string.ascii_uppercase + string.digits
_CODE_LENGTH: Final = 8
_MAX_ATTEMPTS: Final = 5
_LOCKOUT: Final = timedelta(minutes=15)


def _is_one_edit_away(a: str, b: str) -> bool:
    """A single missed/extra/mistyped character -- the common phone-keyboard
    slip -- away from equal. Not a general edit-distance metric: only ever
    called to compare against a *different* string (see resolve_employee_by_nrp),
    so equal inputs are intentionally not treated as "one edit away".
    """
    if len(a) == len(b):
        diffs = sum(1 for x, y in zip(a, b, strict=True) if x != y)
        return diffs == 1
    if abs(len(a) - len(b)) != 1:
        return False
    shorter, longer = (a, b) if len(a) < len(b) else (b, a)
    i = skipped = 0
    for char in longer:
        if i < len(shorter) and shorter[i] == char:
            i += 1
            continue
        if skipped:
            return False
        skipped = 1
    return i == len(shorter)


def resolve_employee_by_nrp(nrp: str, employees: tuple[Employee, ...]) -> Employee | None:
    needle = canonical_text(nrp)
    if not needle:
        return None
    matches = [employee for employee in employees if canonical_text(employee.external_id) == needle]
    if matches:
        return matches[0] if len(matches) == 1 else None
    # No exact match -- tolerate one typo'd character, but only when exactly
    # one employee is close enough to guess at. The YA/BUKAN confirmation
    # afterward is a second check on a single good guess, not a license to
    # pick among several near-matches; multiple close candidates is exactly
    # the ambiguous case exact matching already refuses to resolve.
    close = [
        employee
        for employee in employees
        if _is_one_edit_away(canonical_text(employee.external_id), needle)
    ]
    return close[0] if len(close) == 1 else None


class ActivationOutcome(StrEnum):
    SUCCESS = "success"
    UNKNOWN_EMPLOYEE = "unknown_employee"
    INVALID_CODE = "invalid_code"
    ALREADY_USED = "already_used"
    LOCKED = "locked"
    ALREADY_BOUND = "already_bound"


@dataclass(frozen=True, slots=True)
class ActivationResult:
    outcome: ActivationOutcome


def _generate_code() -> str:
    return "".join(secrets.choice(_CODE_ALPHABET) for _ in range(_CODE_LENGTH))


class _ActivationCodeRow:
    __slots__ = ("code_hash", "failed_attempts", "locked_until", "used_at")

    def __init__(
        self,
        code_hash: str,
        used_at: datetime | None,
        failed_attempts: int,
        locked_until: datetime | None,
    ) -> None:
        self.code_hash = code_hash
        self.used_at = used_at
        self.failed_attempts = failed_attempts
        self.locked_until = locked_until


def _verify(plain_code: str, stored_hash: str) -> bool:
    if not stored_hash.startswith(("$2a$", "$2b$")):
        return False
    try:
        return bcrypt.checkpw(plain_code.encode("utf-8"), stored_hash.encode("utf-8"))
    except ValueError:
        return False


@final
class ActivationService:
    def __init__(self, dsn: str, connect_timeout_seconds: int = 5) -> None:
        self._dsn = dsn
        self._connect_timeout_seconds = connect_timeout_seconds

    async def issue_codes(self, employee_ids: tuple[str, ...]) -> dict[str, str]:
        return await run_sync(self._issue_codes, employee_ids)

    async def resolve(self, wa_jid: str) -> str | None:
        return await run_sync(self._resolve, wa_jid)

    async def activate(self, wa_jid: str, employee_id: str, code: str) -> ActivationResult:
        return await run_sync(self._activate, wa_jid, employee_id, code)

    async def claim(self, wa_jid: str, employee_id: str) -> None:
        await run_sync(self._claim, wa_jid, employee_id)

    async def pending_claim(self, wa_jid: str) -> str | None:
        return await run_sync(self._pending_claim, wa_jid)

    async def clear_claim(self, wa_jid: str) -> None:
        await run_sync(self._clear_claim, wa_jid)

    async def bind(self, wa_jid: str, employee_id: str) -> ActivationOutcome:
        return await run_sync(self._bind, wa_jid, employee_id)

    async def unbind(self, employee_id: str) -> bool:
        return await run_sync(self._unbind, employee_id)

    async def unbind_jid(self, wa_jid: str) -> bool:
        return await run_sync(self._unbind_jid, wa_jid)

    def _connect(self) -> psycopg.Connection[tuple[object, ...]]:
        return psycopg.connect(self._dsn, connect_timeout=self._connect_timeout_seconds)

    def _issue_codes(self, employee_ids: tuple[str, ...]) -> dict[str, str]:
        codes = {employee_id: _generate_code() for employee_id in employee_ids}
        try:
            with self._connect() as connection, connection.cursor() as cursor:
                for employee_id, code in codes.items():
                    code_hash = bcrypt.hashpw(code.encode("utf-8"), bcrypt.gensalt()).decode(
                        "utf-8"
                    )
                    _ = cursor.execute(
                        """
                        INSERT INTO activation_codes (employee_id, code_hash)
                        VALUES (%s, %s)
                        ON CONFLICT (employee_id) DO UPDATE SET
                            code_hash = EXCLUDED.code_hash,
                            issued_at = now(),
                            used_at = NULL,
                            failed_attempts = 0,
                            locked_until = NULL
                        """,
                        (employee_id, code_hash),
                    )
        except psycopg.Error as error:
            raise InfrastructureError(
                service="postgres", operation="issue_activation_codes"
            ) from error
        return codes

    def _resolve(self, wa_jid: str) -> str | None:
        try:
            with self._connect() as connection, connection.cursor() as cursor:
                _ = cursor.execute(
                    "SELECT employee_id FROM wa_identity WHERE wa_jid = %s", (wa_jid,)
                )
                row = cursor.fetchone()
        except psycopg.Error as error:
            raise InfrastructureError(service="postgres", operation="resolve_identity") from error
        return None if row is None else str(row[0])

    def _claim(self, wa_jid: str, employee_id: str) -> None:
        try:
            with self._connect() as connection, connection.cursor() as cursor:
                _ = cursor.execute(
                    """
                    INSERT INTO bot_conversations (wa_jid, pending_employee_id)
                    VALUES (%s, %s)
                    ON CONFLICT (wa_jid) DO UPDATE SET
                        pending_employee_id = EXCLUDED.pending_employee_id,
                        updated_at = now()
                    """,
                    (wa_jid, employee_id),
                )
        except psycopg.Error as error:
            raise InfrastructureError(service="postgres", operation="claim_identity") from error

    def _pending_claim(self, wa_jid: str) -> str | None:
        try:
            with self._connect() as connection, connection.cursor() as cursor:
                _ = cursor.execute(
                    """
                    SELECT pending_employee_id FROM bot_conversations
                    WHERE wa_jid = %s AND updated_at > now() - interval '15 minutes'
                    """,
                    (wa_jid,),
                )
                row = cursor.fetchone()
        except psycopg.Error as error:
            raise InfrastructureError(service="postgres", operation="load_pending_claim") from error
        return None if row is None or row[0] is None else str(row[0])

    def _clear_claim(self, wa_jid: str) -> None:
        try:
            with self._connect() as connection, connection.cursor() as cursor:
                _ = cursor.execute(
                    "UPDATE bot_conversations SET pending_employee_id = NULL WHERE wa_jid = %s",
                    (wa_jid,),
                )
        except psycopg.Error as error:
            raise InfrastructureError(service="postgres", operation="clear_claim") from error

    def _bind(self, wa_jid: str, employee_id: str) -> ActivationOutcome:
        try:
            with self._connect() as connection, connection.cursor() as cursor:
                try:
                    _ = cursor.execute(
                        "INSERT INTO wa_identity (wa_jid, employee_id) VALUES (%s, %s)",
                        (wa_jid, employee_id),
                    )
                except psycopg.errors.UniqueViolation:
                    connection.rollback()
                    return ActivationOutcome.ALREADY_BOUND
                _ = cursor.execute(
                    "UPDATE bot_conversations SET pending_employee_id = NULL WHERE wa_jid = %s",
                    (wa_jid,),
                )
                return ActivationOutcome.SUCCESS
        except psycopg.Error as error:
            raise InfrastructureError(service="postgres", operation="bind_identity") from error

    def _unbind(self, employee_id: str) -> bool:
        try:
            with self._connect() as connection, connection.cursor() as cursor:
                _ = cursor.execute("DELETE FROM wa_identity WHERE employee_id = %s", (employee_id,))
                deleted = cursor.rowcount > 0
        except psycopg.Error as error:
            raise InfrastructureError(service="postgres", operation="unbind_identity") from error
        return deleted

    def _unbind_jid(self, wa_jid: str) -> bool:
        try:
            with self._connect() as connection, connection.cursor() as cursor:
                _ = cursor.execute("DELETE FROM wa_identity WHERE wa_jid = %s", (wa_jid,))
                deleted = cursor.rowcount > 0
        except psycopg.Error as error:
            raise InfrastructureError(
                service="postgres", operation="unbind_identity_jid"
            ) from error
        return deleted

    def _activate(self, wa_jid: str, employee_id: str, code: str) -> ActivationResult:
        try:
            with (
                self._connect() as connection,
                connection.cursor(row_factory=class_row(_ActivationCodeRow)) as cursor,
            ):
                _ = cursor.execute(
                    """
                    SELECT code_hash, used_at, failed_attempts, locked_until
                    FROM activation_codes WHERE employee_id = %s
                    FOR UPDATE
                    """,
                    (employee_id,),
                )
                row = cursor.fetchone()
                if row is None:
                    return ActivationResult(ActivationOutcome.UNKNOWN_EMPLOYEE)
                now = datetime.now(UTC)
                if row.locked_until is not None and row.locked_until > now:
                    return ActivationResult(ActivationOutcome.LOCKED)
                if row.used_at is not None:
                    return ActivationResult(ActivationOutcome.ALREADY_USED)
                if not _verify(code, row.code_hash):
                    attempts = row.failed_attempts + 1
                    lock = now + _LOCKOUT if attempts >= _MAX_ATTEMPTS else None
                    _ = cursor.execute(
                        """
                        UPDATE activation_codes SET failed_attempts = %s, locked_until = %s
                        WHERE employee_id = %s
                        """,
                        (attempts, lock, employee_id),
                    )
                    return ActivationResult(
                        ActivationOutcome.LOCKED
                        if lock is not None
                        else ActivationOutcome.INVALID_CODE
                    )
                _ = cursor.execute(
                    "UPDATE activation_codes SET used_at = now() WHERE employee_id = %s",
                    (employee_id,),
                )
                try:
                    _ = cursor.execute(
                        "INSERT INTO wa_identity (wa_jid, employee_id) VALUES (%s, %s)",
                        (wa_jid, employee_id),
                    )
                except psycopg.errors.UniqueViolation:
                    connection.rollback()
                    return ActivationResult(ActivationOutcome.ALREADY_BOUND)
                return ActivationResult(ActivationOutcome.SUCCESS)
        except psycopg.Error as error:
            raise InfrastructureError(service="postgres", operation="activate") from error
