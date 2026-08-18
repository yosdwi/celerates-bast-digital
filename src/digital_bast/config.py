from __future__ import annotations

import stat
from functools import lru_cache
from typing import ClassVar, Final, Self, final, override

from pydantic import AnyHttpUrl, Field, FilePath, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_DUPLICATE_CREDENTIAL_SOURCE: Final = "duplicate secret sources"
_CREDENTIAL_FILE_UNAVAILABLE: Final = "secret file unavailable"
_CREDENTIAL_FILE_PERMISSIONS: Final = "secret file permissions too broad"
_CREDENTIAL_FILE_UNREADABLE: Final = "secret file unreadable"
_CREDENTIAL_FILE_EMPTY: Final = "secret file empty"
_MISSING_CREDENTIALS: Final = "missing production secrets"
_MISSING_FILE: Final = "missing production file"
_WEAK_SESSION_KEY: Final = "weak production secret"
_MISSING_REDIS_AUTH: Final = "missing Redis authentication"
_MINIMUM_SESSION_SECRET_LENGTH: Final = 32


class SettingsConfigurationError(ValueError):
    def __init__(self, code: str, detail: str) -> None:
        super().__init__(code, detail)
        self.code: str = code
        self.detail: str = detail

    @override
    def __str__(self) -> str:
        return f"{self.code}: {self.detail}"


def _read_secret(
    current: SecretStr | None,
    path: FilePath | None,
    field_name: str,
) -> SecretStr | None:
    if path is None:
        return current
    if current is not None:
        raise SettingsConfigurationError(_DUPLICATE_CREDENTIAL_SOURCE, field_name)
    try:
        mode = stat.S_IMODE(path.stat().st_mode)
    except OSError as error:
        raise SettingsConfigurationError(_CREDENTIAL_FILE_UNAVAILABLE, str(path)) from error
    if mode & 0o037:
        raise SettingsConfigurationError(_CREDENTIAL_FILE_PERMISSIONS, str(path))
    try:
        value = path.read_text(encoding="utf-8").strip()
    except OSError as error:
        raise SettingsConfigurationError(_CREDENTIAL_FILE_UNREADABLE, str(path)) from error
    if not value:
        raise SettingsConfigurationError(_CREDENTIAL_FILE_EMPTY, str(path))
    return SecretStr(value)


@final
class Settings(BaseSettings):
    model_config: ClassVar[SettingsConfigDict] = SettingsConfigDict(
        env_file=".env",
        extra="ignore",
        populate_by_name=True,
        case_sensitive=False,
    )

    environment: str = Field(default="development", validation_alias="APP_ENVIRONMENT")
    log_level: str = Field(default="INFO", validation_alias="APP_LOG_LEVEL")
    session_ttl_seconds: int = Field(
        default=86400,
        ge=60,
        le=604800,
        validation_alias="APP_SESSION_TTL_SECONDS",
    )
    session_secret: SecretStr | None = Field(default=None, validation_alias="APP_SESSION_SECRET")
    session_secret_file: FilePath | None = Field(
        default=None,
        validation_alias="APP_SESSION_SECRET_FILE",
    )
    database_dsn: SecretStr | None = Field(default=None, validation_alias="APP_DATABASE_DSN")
    database_dsn_file: FilePath | None = Field(
        default=None,
        validation_alias="APP_DATABASE_DSN_FILE",
    )
    legacy_database_dsn: SecretStr | None = Field(
        default=None,
        validation_alias="LEGACY_DATABASE_DSN",
    )
    legacy_database_dsn_file: FilePath | None = Field(
        default=None,
        validation_alias="LEGACY_DATABASE_DSN_FILE",
    )
    prefect_api_url: AnyHttpUrl | None = Field(default=None, validation_alias="PREFECT_API_URL")
    prefect_api_auth_string: SecretStr | None = Field(
        default=None,
        validation_alias="PREFECT_API_AUTH_STRING",
    )
    prefect_api_auth_string_file: FilePath | None = Field(
        default=None,
        validation_alias="PREFECT_API_AUTH_STRING_FILE",
    )
    prefect_database_dsn: SecretStr | None = Field(
        default=None,
        validation_alias="PREFECT_DATABASE_DSN",
    )
    prefect_database_dsn_file: FilePath | None = Field(
        default=None,
        validation_alias="PREFECT_DATABASE_DSN_FILE",
    )
    redis_url: SecretStr | None = Field(default=None, validation_alias="REDIS_URL")
    redis_url_file: FilePath | None = Field(default=None, validation_alias="REDIS_URL_FILE")
    redis_password: SecretStr | None = Field(default=None, validation_alias="REDIS_PASSWORD")
    redis_password_file: FilePath | None = Field(
        default=None,
        validation_alias="REDIS_PASSWORD_FILE",
    )
    nocodb_base_url: AnyHttpUrl | None = Field(default=None, validation_alias="NOCODB_BASE_URL")
    nocodb_token: SecretStr | None = Field(default=None, validation_alias="NOCODB_TOKEN")
    nocodb_token_file: FilePath | None = Field(
        default=None,
        validation_alias="NOCODB_TOKEN_FILE",
    )
    nocodb_employee_table_id: str = Field(
        default="mhwyla9uh1ici8j",
        min_length=1,
        validation_alias="NOCODB_EMPLOYEE_TABLE_ID",
    )
    nocodb_database_dsn: SecretStr | None = Field(
        default=None,
        validation_alias="NOCODB_DATABASE_DSN",
    )
    nocodb_database_dsn_file: FilePath | None = Field(
        default=None,
        validation_alias="NOCODB_DATABASE_DSN_FILE",
    )
    nocodb_base_id: str | None = Field(default=None, validation_alias="NOCODB_BASE_ID")
    nocodb_attendance_mapping: str | None = Field(
        default=None,
        validation_alias="NOCODB_ATTENDANCE_MAPPING",
    )
    nocodb_task_evidence_column: str | None = Field(
        default=None,
        validation_alias="NOCODB_TASK_EVIDENCE_COLUMN",
    )
    google_application_credentials: FilePath | None = Field(
        default=None,
        validation_alias="GOOGLE_APPLICATION_CREDENTIALS",
    )
    google_iot_spreadsheet_id: str = Field(
        default="1bzAndOjRR-9GOrB8a2_FD5ayE5uPLLrg7gK4bKcmKbo",
        min_length=1,
        validation_alias="GOOGLE_IOT_SPREADSHEET_ID",
    )
    google_iot_sheet_name: str = Field(
        default="Master Support Ticket MS",
        min_length=1,
        validation_alias="GOOGLE_IOT_SHEET_NAME",
    )
    timesheet_weekday_activity: str = Field(
        default="P01-Development",
        min_length=1,
        validation_alias="TIMESHEET_WEEKDAY_ACTIVITY",
    )
    timesheet_weekend_activity: str = Field(
        default="L05-Public Holiday",
        min_length=1,
        validation_alias="TIMESHEET_WEEKEND_ACTIVITY",
    )
    timesheet_iot_activity: str = Field(
        default="P05-Support",
        min_length=1,
        validation_alias="TIMESHEET_IOT_ACTIVITY",
    )
    timesheet_default_project: str = Field(
        default=("MTG/PR/202301/000100-Pamapersada Nusantara-Talent Force Jan-Dec 2026-for PAMA"),
        min_length=1,
        validation_alias="TIMESHEET_DEFAULT_PROJECT",
    )
    sqlserver_connection_string: SecretStr | None = Field(
        default=None,
        validation_alias="SQLSERVER_CONNECTION_STRING",
    )
    sqlserver_connection_string_file: FilePath | None = Field(
        default=None,
        validation_alias="SQLSERVER_CONNECTION_STRING_FILE",
    )
    outbound_timeout_seconds: float = Field(default=30.0, gt=0, le=120)

    @model_validator(mode="after")
    def resolve_files_and_validate(self) -> Self:
        self.session_secret = _read_secret(
            self.session_secret,
            self.session_secret_file,
            "session_secret",
        )
        self.database_dsn = _read_secret(self.database_dsn, self.database_dsn_file, "database_dsn")
        self.legacy_database_dsn = _read_secret(
            self.legacy_database_dsn,
            self.legacy_database_dsn_file,
            "legacy_database_dsn",
        )
        self.prefect_api_auth_string = _read_secret(
            self.prefect_api_auth_string,
            self.prefect_api_auth_string_file,
            "prefect_api_auth_string",
        )
        self.prefect_database_dsn = _read_secret(
            self.prefect_database_dsn,
            self.prefect_database_dsn_file,
            "prefect_database_dsn",
        )
        self.redis_url = _read_secret(self.redis_url, self.redis_url_file, "redis_url")
        self.redis_password = _read_secret(
            self.redis_password,
            self.redis_password_file,
            "redis_password",
        )
        self.nocodb_token = _read_secret(self.nocodb_token, self.nocodb_token_file, "nocodb_token")
        self.nocodb_database_dsn = _read_secret(
            self.nocodb_database_dsn,
            self.nocodb_database_dsn_file,
            "nocodb_database_dsn",
        )
        self.sqlserver_connection_string = _read_secret(
            self.sqlserver_connection_string,
            self.sqlserver_connection_string_file,
            "sqlserver_connection_string",
        )
        if self.environment.casefold() == "production":
            self._validate_production()
        return self

    def _validate_production(self) -> None:
        secrets = (
            ("session_secret", self.session_secret),
            ("database_dsn", self.database_dsn),
            ("legacy_database_dsn", self.legacy_database_dsn),
            ("prefect_api_auth_string", self.prefect_api_auth_string),
            ("prefect_database_dsn", self.prefect_database_dsn),
            ("redis_url", self.redis_url),
            ("sqlserver_connection_string", self.sqlserver_connection_string),
            ("nocodb_database_dsn", self.nocodb_database_dsn),
        )
        missing = ", ".join(name for name, value in secrets if value is None)
        if missing:
            raise SettingsConfigurationError(_MISSING_CREDENTIALS, missing)
        if self.nocodb_base_id is None:
            raise SettingsConfigurationError(_MISSING_CREDENTIALS, "nocodb_base_id")
        credentials = self.google_application_credentials
        if credentials is None or not credentials.is_file():
            raise SettingsConfigurationError(
                _MISSING_FILE,
                "GOOGLE_APPLICATION_CREDENTIALS",
            )
        if (
            self.session_secret is not None
            and len(self.session_secret.get_secret_value()) < _MINIMUM_SESSION_SECRET_LENGTH
        ):
            raise SettingsConfigurationError(_WEAK_SESSION_KEY, "APP_SESSION_SECRET")
        if (
            self.redis_password is None
            and self.redis_url is not None
            and "@" not in self.redis_url.get_secret_value()
        ):
            raise SettingsConfigurationError(_MISSING_REDIS_AUTH, "REDIS_PASSWORD")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
