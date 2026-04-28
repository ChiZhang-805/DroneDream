"""Application configuration loaded from environment variables."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

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
    worker_lease_seconds: int = Field(default=900)
    worker_stale_running_reclaim_enabled: bool = Field(default=True)
    artifact_storage_backend: Literal["local", "s3"] = Field(default="local")
    s3_endpoint_url: str | None = Field(default=None)
    s3_region: str | None = Field(default=None)
    s3_bucket: str | None = Field(default=None)
    s3_access_key_id: str | None = Field(default=None)
    s3_secret_access_key: str | None = Field(default=None)
    s3_prefix: str = Field(default="dronedream/")
    auth_mode: str = Field(default="disabled")
    demo_auth_tokens: str = Field(default="")

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

    @property
    def demo_auth_token_map(self) -> dict[str, str]:
        pairs = [p.strip() for p in self.demo_auth_tokens.split(",") if p.strip()]
        mapping: dict[str, str] = {}
        for pair in pairs:
            if ":" not in pair:
                continue
            email, token = pair.split(":", 1)
            email = email.strip()
            token = token.strip()
            if email and token:
                mapping[token] = email
        return mapping


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a cached Settings instance."""

    return Settings()
