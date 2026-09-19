import httpx
import pytest

from digital_bast.infrastructure.errors import AuthenticationError, UpstreamTimeoutError
from digital_bast.infrastructure.nocodb import NocoDBAuthClient


def test_nocodb_signin_verifies_identity_with_me_endpoint() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path.endswith("signin"):
            return httpx.Response(200, json={"token": "signed-token"})
        return httpx.Response(
            200,
            json={"id": "user-1", "email": "operator@example.com", "roles": "org-level-creator"},
        )

    with httpx.Client(transport=httpx.MockTransport(handler), base_url="https://noco.test") as http:
        client = NocoDBAuthClient(http)
        result = client.sign_in("operator@example.com", "valid-password")

    assert result.user_id == "user-1"
    assert requests[1].headers["xc-auth"] == "signed-token"


def test_nocodb_signin_maps_bad_credentials() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, request=request)

    with (
        httpx.Client(transport=httpx.MockTransport(handler), base_url="https://noco.test") as http,
        pytest.raises(AuthenticationError),
    ):
        NocoDBAuthClient(http).sign_in("operator@example.com", "wrong-password")


def test_nocodb_signin_maps_timeouts() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        message = "late"
        raise httpx.ReadTimeout(message, request=request)

    with (
        httpx.Client(transport=httpx.MockTransport(handler), base_url="https://noco.test") as http,
        pytest.raises(UpstreamTimeoutError),
    ):
        NocoDBAuthClient(http).sign_in("operator@example.com", "password")
