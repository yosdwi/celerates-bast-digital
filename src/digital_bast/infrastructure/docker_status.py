from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Final, override

from digital_bast.infrastructure.errors import InfrastructureError

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

REQUIRED_SERVICES: Final = (
    "postgres",
    "redis",
    "prefect-server",
    "prefect-services",
    "worker",
    "runner",
    "reverse-proxy",
)
WEB_SLOTS: Final = ("web-blue", "web-green")
COMPOSE_ARGUMENTS: Final = (
    "compose",
    "--profile",
    "blue",
    "--profile",
    "green",
    "ps",
    "--all",
    "--format",
    "json",
)
HEALTHY: Final = "healthy"
RUNNING: Final = "running"
MISSING: Final = "missing"
DEGRADED: Final = "degraded"
_COMPOSE_TIMEOUT_SECONDS: Final = 30
_DOCKER_MISSING: Final = "docker executable not found on PATH"
_COMPOSE_FAILED: Final = "docker compose ps failed"
_INVALID_JSON: Final = "docker compose ps returned invalid JSON"

type ComposeRunner = Callable[[Sequence[str], Path], str]


class DockerUnavailableError(InfrastructureError):
    def __init__(self, detail: str) -> None:
        super().__init__(service="docker", operation="compose_ps")
        self.detail: str = detail

    @override
    def __str__(self) -> str:
        return f"docker compose status unavailable: {self.detail}"


@dataclass(frozen=True, slots=True)
class ServiceStatus:
    service: str
    state: str
    health: str

    @property
    def ok(self) -> bool:
        if self.state != RUNNING:
            return False
        return self.health in {"", HEALTHY}


@dataclass(frozen=True, slots=True)
class SystemStatus:
    overall: str
    services: tuple[ServiceStatus, ...]


def project_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _run_compose(arguments: Sequence[str], project_dir: Path) -> str:
    executable = shutil.which("docker")
    if executable is None:
        raise DockerUnavailableError(_DOCKER_MISSING)
    try:
        completed = subprocess.run(  # noqa: S603
            [executable, *arguments],
            capture_output=True,
            check=False,
            cwd=project_dir,
            text=True,
            timeout=_COMPOSE_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise DockerUnavailableError(str(error)) from error
    if completed.returncode != 0:
        raise DockerUnavailableError(completed.stderr.strip() or _COMPOSE_FAILED)
    return completed.stdout


def parse_compose_ps(payload: str) -> tuple[ServiceStatus, ...]:
    entries: list[dict[str, object]] = []
    stripped = payload.strip()
    if not stripped:
        return ()
    try:
        if stripped.startswith("["):
            entries = json.loads(stripped)
        else:
            entries = [json.loads(line) for line in stripped.splitlines() if line.strip()]
    except json.JSONDecodeError as error:
        raise DockerUnavailableError(_INVALID_JSON) from error
    return tuple(
        ServiceStatus(
            service=str(entry.get("Service") or entry.get("Name") or ""),
            state=str(entry.get("State") or "").casefold(),
            health=str(entry.get("Health") or "").casefold(),
        )
        for entry in entries
    )


def evaluate_services(observed: tuple[ServiceStatus, ...]) -> SystemStatus:
    by_service = {item.service: item for item in observed}
    services = [
        by_service.get(name, ServiceStatus(name, MISSING, ""))
        for name in (*REQUIRED_SERVICES, *WEB_SLOTS)
        if name in REQUIRED_SERVICES or name in by_service
    ]
    required_ok = all(
        by_service.get(name, ServiceStatus(name, MISSING, "")).ok for name in REQUIRED_SERVICES
    )
    slots = tuple(by_service[name] for name in WEB_SLOTS if name in by_service)
    slot_ok = any(slot.ok for slot in slots)
    if not slots:
        services.append(ServiceStatus("web-blue", MISSING, ""))
    overall = HEALTHY if required_ok and slot_ok else DEGRADED
    return SystemStatus(overall=overall, services=tuple(services))


def system_status(
    project_dir: Path | None = None,
    runner: ComposeRunner = _run_compose,
) -> SystemStatus:
    payload = runner(COMPOSE_ARGUMENTS, project_dir or project_root())
    return evaluate_services(parse_compose_ps(payload))
