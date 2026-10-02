from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar, final

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from digital_bast.infrastructure.errors import (
    AuthenticationError,
    InfrastructureError,
    UpstreamTimeoutError,
    UpstreamUnavailableError,
)

type JsonScalar = str | int | float | bool | None
type JsonValue = JsonScalar | list[JsonValue] | dict[str, JsonValue]
type JsonRecordList = list[dict[str, JsonValue]]


class _TokenResponse(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore", frozen=True)

    token: str = Field(min_length=1)


class _UserResponse(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore", frozen=True)

    id: str
    email: str
    roles: str | list[str] = Field(default_factory=list)


class _RecordListResponse(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore", frozen=True)

    records: list[dict[str, JsonValue]] = Field(default_factory=list, alias="list")


@dataclass(frozen=True, slots=True)
class AuthenticatedUser:
    user_id: str
    email: str
    roles: tuple[str, ...]
    token: str


@final
class NocoDBAuthClient:
    def __init__(self, client: httpx.Client) -> None:
        self._client: httpx.Client = client

    def sign_in(self, email: str, password: str) -> AuthenticatedUser:
        try:
            response = self._client.post(
                "/api/v1/auth/user/signin",
                json={"email": email, "password": password},
            )
            if response.status_code in {401, 403}:
                raise AuthenticationError(service="nocodb", operation="sign_in")
            _ = response.raise_for_status()
            token = _TokenResponse.model_validate(response.json()).token
            me_response = self._client.get(
                "/api/v1/auth/user/me",
                headers={"xc-auth": token},
            )
            if me_response.status_code in {401, 403}:
                raise AuthenticationError(service="nocodb", operation="verify_identity")
            _ = me_response.raise_for_status()
            user = _UserResponse.model_validate(me_response.json())
        except httpx.TimeoutException as error:
            raise UpstreamTimeoutError(service="nocodb", operation="sign_in") from error
        except httpx.HTTPError as error:
            raise UpstreamUnavailableError(service="nocodb", operation="sign_in") from error
        except ValidationError as error:
            raise InfrastructureError(service="nocodb", operation="parse_auth_response") from error
        roles = tuple(user.roles.split(",")) if isinstance(user.roles, str) else tuple(user.roles)
        return AuthenticatedUser(
            user_id=user.id,
            email=user.email,
            roles=roles,
            token=token,
        )


@final
class NocoDBClient:
    def __init__(self, client: httpx.Client, token: str) -> None:
        self._client: httpx.Client = client
        self._headers: dict[str, str] = {"xc-token": token}

    def list_records(
        self,
        table_id: str,
        *,
        where: str | None = None,
        limit: int = 1000,
        offset: int = 0,
    ) -> list[dict[str, JsonValue]]:
        params: dict[str, str | int] = {"limit": limit, "offset": offset}
        if where is not None:
            params["where"] = where
        payload = self._request(
            "GET",
            f"/api/v2/tables/{table_id}/records",
            params=params,
        )
        try:
            return _RecordListResponse.model_validate(payload).records
        except ValidationError as error:
            raise InfrastructureError(service="nocodb", operation="parse_records") from error

    def create_records(
        self,
        table_id: str,
        records: list[dict[str, JsonValue]],
    ) -> JsonValue:
        return self._request(
            "POST",
            f"/api/v2/tables/{table_id}/records",
            json=records,
        )

    def update_records(
        self,
        table_id: str,
        records: list[dict[str, JsonValue]],
    ) -> JsonValue:
        return self._request(
            "PATCH",
            f"/api/v2/tables/{table_id}/records",
            json=records,
        )

    def delete_records(self, table_id: str, record_ids: list[int | str]) -> JsonValue:
        return self._request(
            "DELETE",
            f"/api/v2/tables/{table_id}/records",
            json=[{"Id": record_id} for record_id in record_ids],
        )

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, str | int] | None = None,
        json: JsonValue | JsonRecordList = None,
    ) -> JsonValue:
        try:
            response = self._client.request(
                method,
                path,
                headers=self._headers,
                params=params,
                json=json,
            )
            if response.status_code in {401, 403}:
                raise AuthenticationError(service="nocodb", operation="records")
            _ = response.raise_for_status()
        except httpx.TimeoutException as error:
            raise UpstreamTimeoutError(service="nocodb", operation="records") from error
        except httpx.HTTPError as error:
            raise UpstreamUnavailableError(service="nocodb", operation="records") from error
        value: JsonValue = response.json()
        return value


def create_http_client(base_url: str, timeout_seconds: float = 30.0) -> httpx.Client:
    limits = httpx.Limits(
        max_connections=100,
        max_keepalive_connections=20,
        keepalive_expiry=30.0,
    )
    timeout = httpx.Timeout(
        connect=min(timeout_seconds, 5.0),
        read=timeout_seconds,
        write=min(timeout_seconds, 10.0),
        pool=min(timeout_seconds, 10.0),
    )
    transport = httpx.HTTPTransport(retries=2, limits=limits)
    return httpx.Client(
        base_url=base_url,
        timeout=timeout,
        transport=transport,
        follow_redirects=False,
        headers={"Accept": "application/json"},
    )
