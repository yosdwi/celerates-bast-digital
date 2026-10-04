import httpx

from digital_bast.infrastructure.nocodb import NocoDBAuthClient


def test_owner_signin_contract_uses_v1_auth_and_verifies_token() -> None:
    observed: list[tuple[str, str, str | None]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        observed.append((request.method, request.url.path, request.headers.get("xc-auth")))
        if request.url.path == "/api/v1/auth/user/signin":
            return httpx.Response(200, json={"token": "token-1"})
        return httpx.Response(
            200,
            json={"id": "user-1", "email": "owner@example.com", "roles": ["owner"]},
        )

    with httpx.Client(transport=httpx.MockTransport(handler), base_url="https://noco.test") as http:
        user = NocoDBAuthClient(http).sign_in("owner@example.com", "secret")

    assert user.roles == ("owner",)
    assert observed == [
        ("POST", "/api/v1/auth/user/signin", None),
        ("GET", "/api/v1/auth/user/me", "token-1"),
    ]
