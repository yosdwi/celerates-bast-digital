"""BAST preview/final readiness gate and generation audit.

Preview is always available for investigation. Final generation is deterministic:
the selected team must be fully ready, unless an authorized operator explicitly
forces generation with a reason. The readiness decision never comes from an LLM.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, final
from uuid import UUID

import psycopg
from anyio.to_thread import run_sync

from digital_bast.domain.completion import CheckState
from digital_bast.domain.models import EmployeeRole
from digital_bast.infrastructure.errors import InfrastructureError

if TYPE_CHECKING:
    from digital_bast.application.talentops import TalentOpsService
    from digital_bast.domain.completion import DateRange


class BastGenerationMode(StrEnum):
    PREVIEW = "preview"
    FINAL = "final"


@dataclass(frozen=True, slots=True)
class BastBlocker:
    employee_id: str
    nrp: str
    name: str
    domain: str
    state: str
    issues: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class BastReadiness:
    report_type: str
    role: EmployeeRole
    total_talents: int
    ready_talents: int
    ready: bool
    blockers: tuple[BastBlocker, ...]


_REPORT_ROLE = {
    "developer": EmployeeRole.DEVELOPER,
    "iotoperation": EmployeeRole.IOT_OPERATIONS,
}


@final
class BastWorkflowService:
    def __init__(
        self,
        dsn: str,
        talentops: TalentOpsService,
        connect_timeout_seconds: int = 5,
    ) -> None:
        self._dsn = dsn
        self._talentops = talentops
        self._connect_timeout_seconds = connect_timeout_seconds

    async def readiness(self, period: DateRange, report_type: str) -> BastReadiness:
        role = _REPORT_ROLE[report_type]
        view = await self._talentops.command_center(period)
        members = tuple(item for item in view.readiness if item.role is role)
        blockers: list[BastBlocker] = []
        for item in view.attention:
            if item.role is not role:
                continue
            blockers.extend(
                BastBlocker(
                    employee_id=item.employee_id,
                    nrp=item.nrp,
                    name=item.name,
                    domain=blocker.domain,
                    state=blocker.state.value,
                    issues=blocker.issues,
                )
                for blocker in item.blockers
            )
        ready_talents = sum(item.overall_state is CheckState.COMPLETE for item in members)
        return BastReadiness(
            report_type=report_type,
            role=role,
            total_talents=len(members),
            ready_talents=ready_talents,
            ready=bool(members) and ready_talents == len(members),
            blockers=tuple(blockers),
        )

    async def record_generation(  # noqa: PLR0913 - immutable audit snapshot fields
        self,
        *,
        report_type: str,
        period: DateRange,
        mode: BastGenerationMode,
        forced: bool,
        force_reason: str | None,
        readiness: BastReadiness,
        generated_by: str,
        artifact_name: str | None,
        fingerprint: str | None,
    ) -> UUID:
        return await run_sync(
            self._record_generation,
            report_type,
            period.start.year,
            period.start.month,
            mode,
            forced,
            force_reason,
            readiness,
            generated_by,
            artifact_name,
            fingerprint,
        )

    def _record_generation(  # noqa: PLR0913, PLR0917 - persistence boundary
        self,
        report_type: str,
        year: int,
        month: int,
        mode: BastGenerationMode,
        forced: bool,
        force_reason: str | None,
        readiness: BastReadiness,
        generated_by: str,
        artifact_name: str | None,
        fingerprint: str | None,
    ) -> UUID:
        payload = [
            {
                "employee_id": item.employee_id,
                "nrp": item.nrp,
                "name": item.name,
                "domain": item.domain,
                "state": item.state,
                "issues": list(item.issues),
            }
            for item in readiness.blockers
        ]
        try:
            with psycopg.connect(
                self._dsn, connect_timeout=self._connect_timeout_seconds
            ) as connection, connection.cursor() as cursor:
                _ = cursor.execute(
                    """
                    INSERT INTO bast_generation_audit (
                        report_type, year, month, mode, forced, force_reason,
                        readiness_state, blockers, generated_by,
                        artifact_name, fingerprint
                    ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s,%s,%s)
                    RETURNING id
                    """,
                    (
                        report_type,
                        year,
                        month,
                        mode.value,
                        forced,
                        force_reason,
                        "ready" if readiness.ready else "blocked",
                        json.dumps(payload),
                        generated_by,
                        artifact_name,
                        fingerprint,
                    ),
                )
                row = cursor.fetchone()
                if row is None:  # pragma: no cover - RETURNING invariant
                    raise InfrastructureError(
                        service="postgres",
                        operation="record_bast_generation",
                    )
                return UUID(str(row[0]))
        except psycopg.Error as error:
            raise InfrastructureError(
                service="postgres",
                operation="record_bast_generation",
            ) from error
