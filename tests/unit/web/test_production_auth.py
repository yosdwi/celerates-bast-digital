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


@pytest.mark.anyio
async def test_nocodb_dict_owner_role_authenticates() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v1/auth/user/signin":
            return httpx.Response(200, json={"token": "signed-token"})
        return httpx.Response(
            200,
            json={
                "id": "user-1",
                "email": "owner@example.com",
                "roles": {"owner": True, "org-level-viewer": True},
            },
        )

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url="https://noco.test",
    ) as client:
        user = await OfficialNocoDBOwnerAuthenticator(client).authenticate_owner(
            "owner@example.com",
            "valid-password",
        )

    assert user is not None
    assert user.id == "user-1"


@pytest.mark.anyio
async def test_nocodb_dict_viewer_role_is_insufficient_permissions() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v1/auth/user/signin":
            return httpx.Response(200, json={"token": "signed-token"})
        return httpx.Response(
            200,
            json={
                "id": "user-1",
                "email": "viewer@example.com",
                "roles": {"org-level-viewer": True},
            },
        )

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url="https://noco.test",
    ) as client:
        user = await OfficialNocoDBOwnerAuthenticator(client).authenticate_owner(
            "viewer@example.com",
            "valid-password",
        )

    assert user is None


@pytest.mark.anyio
async def test_nocodb_super_creator_role_authenticates() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v1/auth/user/signin":
            return httpx.Response(200, json={"token": "signed-token"})
        return httpx.Response(
            200,
            json={
                "id": "user-1",
                "email": "creator@example.com",
                "roles": {"org-level-creator": True, "super": True},
            },
        )

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url="https://noco.test",
    ) as client:
        user = await OfficialNocoDBOwnerAuthenticator(client).authenticate_owner(
            "creator@example.com",
            "valid-password",
        )

    assert user is not None
    assert user.id == "user-1"
