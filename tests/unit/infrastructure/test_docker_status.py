from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from digital_bast.infrastructure.docker_status import (
    DockerUnavailableError,
    ServiceStatus,
    evaluate_services,
    parse_compose_ps,
    system_status,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

DOCKER_MISSING = "docker executable not found on PATH"
RUNNING_SERVICES = (
    "postgres",
    "redis",
    "prefect-server",
    "prefect-services",
    "worker",
    "runner",
    "reverse-proxy",
)


def entry(service: str, state: str = "running", health: str = "healthy") -> dict[str, str]:
    return {
        "Name": f"digital-bast-{service}-1",
        "Service": service,
        "State": state,
        "Health": health,
    }


def payload(*entries: dict[str, str]) -> str:
    return json.dumps(list(entries))


def healthy_entries(slot: str = "web-blue") -> tuple[dict[str, str], ...]:
    services = [
        entry(name, health="healthy" if name != "worker" else "") for name in RUNNING_SERVICES
    ]
    return (*services, entry(slot))


def runner_for(text: str):  # noqa: ANN201
    def run(arguments: Sequence[str], project_dir: Path) -> str:
        assert "ps" in arguments
        assert isinstance(project_dir, Path)
        return text

    return run


def test_all_services_healthy() -> None:
    status = system_status(Path(), runner_for(payload(*healthy_entries())))

    assert status.overall == "healthy"
    assert any(item.service == "web-blue" for item in status.services)


def test_unhealthy_postgres_is_degraded() -> None:
    entries = list(healthy_entries())
    entries[0] = entry("postgres", health="unhealthy")

    status = system_status(Path(), runner_for(payload(*entries)))

    assert status.overall == "degraded"


def test_only_web_green_is_valid() -> None:
    status = system_status(Path(), runner_for(payload(*healthy_entries("web-green"))))

    assert status.overall == "healthy"


def test_missing_web_slot_is_degraded() -> None:
    entries = [entry(name, health="") for name in RUNNING_SERVICES]

    status = system_status(Path(), runner_for(payload(*entries)))

    assert status.overall == "degraded"
    assert any(item.service == "web-blue" and item.state == "missing" for item in status.services)


def test_missing_required_service_is_degraded() -> None:
    entries = [item for item in healthy_entries() if item["Service"] != "redis"]

    status = system_status(Path(), runner_for(payload(*entries)))

    assert status.overall == "degraded"
    assert ServiceStatus("redis", "missing", "") in status.services


def test_newline_delimited_output_is_supported() -> None:
    text = "\n".join(json.dumps(item) for item in healthy_entries())

    assert len(parse_compose_ps(text)) == len(healthy_entries())


def test_invalid_json_raises_clear_error() -> None:
    with pytest.raises(DockerUnavailableError):
        _ = parse_compose_ps("not json")


def test_docker_unavailable_surfaces_reason() -> None:
    def failing(arguments: Sequence[str], project_dir: Path) -> str:
        _ = (arguments, project_dir)
        raise DockerUnavailableError(DOCKER_MISSING)

    with pytest.raises(DockerUnavailableError, match="not found on PATH"):
        _ = system_status(Path(), failing)


def test_empty_output_yields_degraded_status() -> None:
    assert evaluate_services(parse_compose_ps("")).overall == "degraded"
