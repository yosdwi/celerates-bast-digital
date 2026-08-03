import httpx
import pytest

from digital_bast.web.production import OfficialNocoDBOwnerAuthenticator


@pytest.mark.anyio
async def test_nocodb_signin_400_returns_invalid_credentials() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v1/auth/user/signin":
            return httpx.Response(400, json={"msg": "Invalid credentials"})
        message = f"unexpected request {request.method} {request.url.path}"
        raise AssertionError(message)

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url="https://noco.test",
    ) as client:
        user = await OfficialNocoDBOwnerAuthenticator(client).authenticate_owner(
            "owner@example.com",
            "wrong",
        )

    assert user is None
