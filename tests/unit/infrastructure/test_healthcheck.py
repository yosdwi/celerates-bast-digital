import pytest

from digital_bast.infrastructure.errors import InvalidIdentifierError
from digital_bast.infrastructure.healthcheck import PostgresHealthcheck


def test_procedure_identifier_rejects_sql_injection_before_connecting() -> None:
    adapter = PostgresHealthcheck("postgresql://unused")

    with pytest.raises(InvalidIdentifierError):
        adapter.call_procedure("public", "safe(); DROP TABLE durable_records; --")
