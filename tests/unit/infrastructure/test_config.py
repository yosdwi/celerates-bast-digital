from pathlib import Path

import pytest
from pydantic import ValidationError

from digital_bast.config import Settings


def test_settings_reads_secret_files_when_paths_are_configured(tmp_path: Path) -> None:
    secret_path = tmp_path / "database"
    secret_path.write_text("postgresql://app:password@db/app\n", encoding="utf-8")
    secret_path.chmod(0o600)

    settings = Settings(
        environment="development",
        database_dsn_file=secret_path,
    )

    assert settings.database_dsn is not None
    assert settings.database_dsn.get_secret_value() == "postgresql://app:password@db/app"


def test_settings_reads_group_readable_compose_secret(tmp_path: Path) -> None:
    secret_path = tmp_path / "database"
    secret_path.write_text("postgresql://app:password@db/app\n", encoding="utf-8")
    secret_path.chmod(0o640)

    settings = Settings(
        environment="development",
        database_dsn_file=secret_path,
    )

    assert settings.database_dsn is not None
    assert settings.database_dsn.get_secret_value() == "postgresql://app:password@db/app"


def test_settings_reads_legacy_database_dsn_file(tmp_path: Path) -> None:
    secret_path = tmp_path / "legacy-database"
    secret_path.write_text("postgresql://legacy:password@legacy-db/neondb\n", encoding="utf-8")
    secret_path.chmod(0o640)

    settings = Settings(
        environment="development",
        legacy_database_dsn_file=secret_path,
    )

    assert settings.legacy_database_dsn is not None
    assert (
        settings.legacy_database_dsn.get_secret_value()
        == "postgresql://legacy:password@legacy-db/neondb"
    )


def test_settings_rejects_missing_production_secrets() -> None:
    with pytest.raises(ValidationError):
        Settings(environment="production")


def test_settings_rejects_world_readable_secret_file(tmp_path: Path) -> None:
    secret_path = tmp_path / "database"
    secret_path.write_text("postgresql://app:password@db/app", encoding="utf-8")
    secret_path.chmod(0o644)

    with pytest.raises(ValidationError):
        Settings(environment="development", database_dsn_file=secret_path)
