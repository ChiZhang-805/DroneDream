"""Application configuration loaded from environment variables."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Backend settings. Values come from env vars or a local .env file."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    app_env: str = Field(default="development")
    backend_host: str = Field(default="127.0.0.1")
    backend_port: int = Field(default=8000)
    log_level: str = Field(default="info")
    database_url: str = Field(default="sqlite:///./drone_dream.db")
    cors_origins: str = Field(
        default="http://localhost:5173,http://127.0.0.1:5173"
    )

    # Phase 9: artifact roots for generated job/trial outputs and safe downloads.
    # Keep this default aligned with app.simulator.real_cli._DEFAULT_ARTIFACT_ROOT
    # so generated real-simulator artifacts are always downloadable by default.
    real_simulator_artifact_root: str = Field(default="./artifacts")
    artifact_root: str = Field(default="/tmp/drone_dream_artifacts")

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def real_artifact_root_path(self) -> Path:
        return Path(self.real_simulator_artifact_root).resolve()

    @property
    def default_artifact_root_path(self) -> Path:
        return Path(self.artifact_root).resolve()

    @property
    def allowed_artifact_roots(self) -> list[Path]:
        roots = [self.real_artifact_root_path, self.default_artifact_root_path]
        dedup: list[Path] = []
        for root in roots:
            if root not in dedup:
                dedup.append(root)
        return dedup


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a cached Settings instance."""

    return Settings()
