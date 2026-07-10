"""Application configuration loaded from environment variables."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from pydantic import Field, model_validator
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
    database_auto_create: bool = Field(default=True)
    cors_origins: str = Field(
        default="http://localhost:5173,http://127.0.0.1:5173"
    )

    # Phase 9: artifact roots for generated job/trial outputs and safe downloads.
    # Keep this default aligned with app.simulator.real_cli._DEFAULT_ARTIFACT_ROOT
    # so generated real-simulator artifacts are always downloadable by default.
    real_simulator_artifact_root: str = Field(default="./artifacts")
    artifact_root: str = Field(default="/tmp/drone_dream_artifacts")
    worker_lease_seconds: int = Field(default=900, ge=1)
    worker_lease_heartbeat_seconds: float = Field(default=30.0, gt=0)
    worker_stale_running_reclaim_enabled: bool = Field(default=True)
    redis_url: str | None = Field(default=None)
    require_worker_heartbeat: bool = Field(default=False)
    worker_presence_interval_seconds: float = Field(default=10.0, gt=0)
    worker_presence_ttl_seconds: int = Field(default=45, ge=5)
    worker_presence_key: str = Field(default="dronedream:workers:last_seen")
    artifact_storage_backend: Literal["local", "s3"] = Field(default="local")
    s3_endpoint_url: str | None = Field(default=None)
    s3_region: str | None = Field(default=None)
    s3_bucket: str | None = Field(default=None)
    s3_access_key_id: str | None = Field(default=None)
    s3_secret_access_key: str | None = Field(default=None)
    s3_prefix: str = Field(default="dronedream/")
    artifact_presign_expiry_seconds: int = Field(default=900, ge=60, le=86400)
    llm_allowed_base_urls: str = Field(default="")
    auth_mode: Literal["disabled", "demo_token", "oidc_jwt"] = Field(
        default="disabled"
    )
    demo_auth_tokens: str = Field(default="")
    oidc_issuer: str | None = Field(default=None)
    oidc_audience: str | None = Field(default=None)
    oidc_jwks_url: str | None = Field(default=None)
    oidc_algorithms: str = Field(default="RS256,ES256")
    oidc_email_claim: str = Field(default="email")
    oidc_name_claim: str = Field(default="name")
    oidc_clock_skew_seconds: int = Field(default=30, ge=0, le=300)

    @model_validator(mode="after")
    def validate_production_safety(self) -> Settings:
        """Reject the development-only anonymous identity in production."""

        is_production = self.app_env.strip().lower() in {"prod", "production"}
        if self.auth_mode == "oidc_jwt":
            missing = [
                name
                for name, value in (
                    ("OIDC_ISSUER", self.oidc_issuer),
                    ("OIDC_AUDIENCE", self.oidc_audience),
                    ("OIDC_JWKS_URL", self.oidc_jwks_url),
                )
                if not value or not value.strip()
            ]
            if missing:
                raise ValueError(
                    "AUTH_MODE=oidc_jwt requires " + ", ".join(missing)
                )
            assert self.oidc_jwks_url is not None
            parsed_jwks = urlsplit(self.oidc_jwks_url)
            if parsed_jwks.scheme not in {"http", "https"} or not parsed_jwks.hostname:
                raise ValueError("OIDC_JWKS_URL must be an absolute HTTP(S) URL")
            if is_production and parsed_jwks.scheme != "https":
                raise ValueError("OIDC_JWKS_URL must use HTTPS in production")
            allowed_algorithms = {"RS256", "RS384", "RS512", "ES256", "ES384", "EdDSA"}
            if not self.oidc_algorithm_list or not set(self.oidc_algorithm_list).issubset(
                allowed_algorithms
            ):
                raise ValueError(
                    "OIDC_ALGORITHMS must contain only asymmetric algorithms: "
                    + ", ".join(sorted(allowed_algorithms))
                )
        if is_production:
            if self.auth_mode == "disabled":
                raise ValueError(
                    "AUTH_MODE=disabled is forbidden when APP_ENV=production; "
                    "configure an authenticated mode before starting the service"
                )
            if self.auth_mode == "demo_token" and not self.demo_auth_token_map:
                raise ValueError(
                    "DEMO_AUTH_TOKENS must contain at least one email:token pair "
                    "when AUTH_MODE=demo_token in production"
                )
        return self

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

    @property
    def oidc_audience_list(self) -> list[str]:
        return [
            item.strip()
            for item in (self.oidc_audience or "").split(",")
            if item.strip()
        ]

    @property
    def oidc_algorithm_list(self) -> list[str]:
        return [item.strip() for item in self.oidc_algorithms.split(",") if item.strip()]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a cached Settings instance."""

    return Settings()
