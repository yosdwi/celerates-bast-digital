import pytest

from digital_bast.infrastructure.errors import InfrastructureError
from tests.unit.web.test_talentops_routes import TalentOps, make_client


def test_infrastructure_failure_returns_service_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fail_command_center(self: TalentOps, period: object) -> object:
        del self, period
        raise InfrastructureError(service="postgres", operation="command_center")

    monkeypatch.setattr(TalentOps, "command_center", fail_command_center)
    response = make_client(authenticated=True).get("/api/talentops/v1/command-center")

    assert response.status_code == 503
    assert response.json() == {
        "detail": "A required backend service is temporarily unavailable. Please retry."
    }
