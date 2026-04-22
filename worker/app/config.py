"""Worker configuration loaded from environment variables."""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class WorkerSettings(BaseSettings):
    """Worker settings. Values come from env vars or a local .env file."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    app_env: str = Field(default="development")
    database_url: str = Field(default="sqlite:///./drone_dream.db")
    worker_poll_interval_seconds: float = Field(default=1.0, ge=0.05)
    worker_log_level: str = Field(default="info")


@lru_cache(maxsize=1)
def get_settings() -> WorkerSettings:
    return WorkerSettings()
