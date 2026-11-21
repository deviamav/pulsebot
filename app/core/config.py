"""Application configuration powered by Pydantic Settings."""
from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class BotSettings(BaseSettings):
    """Telegram bot related settings."""

    token: SecretStr = Field(..., alias="BOT_TOKEN")

    # Stored as raw string to avoid pydantic-settings' built-in JSON
    # parsing for ``list[int]`` fields (which would reject plain
    # comma-separated values from .env).  Parsed lazily by ``admin_ids``.
    admin_ids_raw: str = Field(default="", alias="ADMIN_IDS")

    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    @property
    def admin_ids(self) -> list[int]:
        """Parse the raw ADMIN_IDS env into a list of Telegram IDs.

        Accepts both formats:

        * ``ADMIN_IDS=12345,67890``
        * ``ADMIN_IDS=[12345, 67890]``
        """
        text = (self.admin_ids_raw or "").strip()
        if not text:
            return []
        if text.startswith("[") and text.endswith("]"):
            text = text[1:-1]
        result: list[int] = []
        for item in text.split(","):
            item = item.strip()
            if not item:
                continue
            try:
                result.append(int(item))
            except ValueError as exc:
                raise ValueError(
                    f"ADMIN_IDS contains a non-integer value: {item!r}"
                ) from exc
        return result


class PostgresSettings(BaseSettings):
    """PostgreSQL connection settings."""

    host: str = Field(..., alias="POSTGRES_HOST")
    port: int = Field(5432, alias="POSTGRES_PORT")
    db: str = Field(..., alias="POSTGRES_DB")
    user: str = Field(..., alias="POSTGRES_USER")
    password: SecretStr = Field(..., alias="POSTGRES_PASSWORD")

    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    @property
    def dsn(self) -> str:
        """Async SQLAlchemy DSN."""
        return (
            f"postgresql+asyncpg://{self.user}:{self.password.get_secret_value()}"
            f"@{self.host}:{self.port}/{self.db}"
        )

    @property
    def sync_dsn(self) -> str:
        """Synchronous DSN used by Alembic."""
        return (
            f"postgresql+psycopg2://{self.user}:{self.password.get_secret_value()}"
            f"@{self.host}:{self.port}/{self.db}"
        )


class RedisSettings(BaseSettings):
    """Redis connection settings used for FSM storage and throttling."""

    host: str = Field("redis", alias="REDIS_HOST")
    port: int = Field(6379, alias="REDIS_PORT")
    db: int = Field(0, alias="REDIS_DB")
    password: SecretStr | None = Field(default=None, alias="REDIS_PASSWORD")

    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    @property
    def url(self) -> str:
        auth = ""
        if self.password and self.password.get_secret_value():
            auth = f":{self.password.get_secret_value()}@"
        return f"redis://{auth}{self.host}:{self.port}/{self.db}"


class AppSettings(BaseSettings):
    """Top-level application settings."""

    env: Literal["development", "production"] = Field(
        "production", alias="APP_ENV"
    )
    log_level: str = Field("INFO", alias="LOG_LEVEL")
    healthcheck_host: str = Field("0.0.0.0", alias="HEALTHCHECK_HOST")
    healthcheck_port: int = Field(8080, alias="HEALTHCHECK_PORT")
    rate_limit_per_second: float = Field(2.0, alias="RATE_LIMIT_PER_SECOND")
    reminder_check_interval_seconds: int = Field(
        300, alias="REMINDER_CHECK_INTERVAL_SECONDS"
    )

    bot: BotSettings = Field(default_factory=BotSettings)
    postgres: PostgresSettings = Field(default_factory=PostgresSettings)
    redis: RedisSettings = Field(default_factory=RedisSettings)

    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )


@lru_cache(maxsize=1)
def get_settings() -> AppSettings:
    """Return cached application settings."""
    return AppSettings()
