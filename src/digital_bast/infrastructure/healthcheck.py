from __future__ import annotations

import re
from typing import final

import psycopg
from psycopg import sql

from digital_bast.infrastructure.errors import InfrastructureError, InvalidIdentifierError

_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


@final
class PostgresHealthcheck:
    def __init__(self, dsn: str, connect_timeout_seconds: int = 5) -> None:
        self._dsn: str = dsn
        self._connect_timeout_seconds: int = connect_timeout_seconds

    def ping(self) -> bool:
        try:
            with (
                psycopg.connect(
                    self._dsn,
                    connect_timeout=self._connect_timeout_seconds,
                ) as connection,
                connection.cursor() as cursor,
            ):
                _ = cursor.execute("SELECT 1")
                row = cursor.fetchone()
                return row is not None and row[0] == 1
        except psycopg.Error as error:
            raise InfrastructureError(service="postgres", operation="healthcheck") from error

    def call_procedure(self, schema: str, procedure: str) -> None:
        for identifier in (schema, procedure):
            if _IDENTIFIER.fullmatch(identifier) is None:
                raise InvalidIdentifierError(
                    service="postgres",
                    operation="call_procedure",
                    identifier=identifier,
                )
        statement = sql.SQL("CALL {}.{}()").format(
            sql.Identifier(schema),
            sql.Identifier(procedure),
        )
        try:
            with (
                psycopg.connect(
                    self._dsn,
                    connect_timeout=self._connect_timeout_seconds,
                ) as connection,
                connection.cursor() as cursor,
            ):
                _ = cursor.execute(statement)
        except psycopg.Error as error:
            raise InfrastructureError(service="postgres", operation="call_procedure") from error

    def run_step10(self) -> None:
        self.call_procedure("public", "sp_update_tasklist_iot_pic")
