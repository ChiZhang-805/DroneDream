"""Application configuration loaded from environment variables."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit
from uuid import UUID

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_PLACEHOLDER_MARKERS = (
    "change-me",
    "changeme",
    "example-token",
    "replace-me",
    "replace-with",
    "your-token",
)


def _is_obvious_placeholder(value: str) -> bool:
    normalized = value.strip().lower().replace("_", "-")
    return any(marker in normalized for marker in _PLACEHOLDER_MARKERS)


class Settings(BaseSettings):
    """Backend settings. Values come from env vars or a local .env file."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
        protected_namespaces=("model_validate", "model_dump", "settings_"),
    )

    app_env: str = Field(default="development")
    backend_host: str = Field(default="127.0.0.1")
    backend_port: int = Field(default=8000)
    dronedream_runtime_id: str | None = Field(default=None)
    dronedream_px4_executable: str | None = Field(default=None)
    dronedream_gazebo_executable: str | None = Field(default=None)
    log_level: str = Field(default="info")
    database_url: str = Field(default="sqlite:///./drone_dream.db")
    database_auto_create: bool = Field(default=True)
    cors_origins: str = Field(
        default=(
            "http://localhost:5173,http://127.0.0.1:5173,http://tauri.localhost,tauri://localhost"
        )
    )

    # Phase 9: artifact roots for generated job/trial outputs and safe downloads.
    # Keep this default aligned with app.simulator.real_cli._DEFAULT_ARTIFACT_ROOT
    # so generated real-simulator artifacts are always downloadable by default.
    real_simulator_artifact_root: str = Field(default="./artifacts")
    artifact_root: str = Field(default="./artifacts")
    worker_lease_seconds: int = Field(default=900, ge=1)
    worker_lease_heartbeat_seconds: float = Field(default=30.0, gt=0)
    worker_stale_running_reclaim_enabled: bool = Field(default=True)
    redis_url: str | None = Field(default=None)
    require_worker_heartbeat: bool = Field(default=False)
    worker_presence_interval_seconds: float = Field(default=10.0, gt=0)
    worker_presence_ttl_seconds: int = Field(default=45, ge=5)
    worker_presence_key: str = Field(default="dronedream:workers:last_seen")
    artifact_storage_backend: Literal["local", "s3"] = Field(default="local")
    # Local artifact lifecycle is deliberately opt-in. Operators can enable
    # periodic scans in dry-run mode first, inspect statistics, and only then
    # allow deletion. A value of 0 disables the corresponding age/size limit.
    artifact_cleanup_enabled: bool = Field(default=False)
    artifact_cleanup_dry_run: bool = Field(default=True)
    artifact_cleanup_interval_seconds: int = Field(default=3600, ge=60, le=86400)
    artifact_retention_max_total_bytes: int = Field(default=0, ge=0)
    artifact_retention_max_age_seconds: int = Field(default=0, ge=0)
    artifact_retention_min_age_seconds: int = Field(default=86400, ge=0)
    artifact_retention_keep_recent_terminal_jobs: int = Field(default=20, ge=0, le=10000)
    artifact_orphan_grace_seconds: int = Field(default=86400, ge=0)
    s3_endpoint_url: str | None = Field(default=None)
    s3_region: str | None = Field(default=None)
    s3_bucket: str | None = Field(default=None)
    s3_access_key_id: str | None = Field(default=None)
    s3_secret_access_key: str | None = Field(default=None)
    s3_prefix: str = Field(default="dronedream/")
    s3_connect_timeout_seconds: float = Field(default=10.0, ge=1.0, le=120.0)
    s3_read_timeout_seconds: float = Field(default=60.0, ge=1.0, le=600.0)
    s3_max_attempts: int = Field(default=3, ge=1, le=10)
    artifact_presign_expiry_seconds: int = Field(default=900, ge=60, le=86400)
    llm_allowed_base_urls: str = Field(default="")
    llm_request_timeout_seconds: float = Field(default=60.0, ge=5.0, le=600.0)
    llm_max_retries: int = Field(default=1, ge=0, le=5)
    llm_max_response_bytes: int = Field(default=1_000_000, ge=1024, le=10_000_000)
    llm_max_prompt_bytes: int = Field(default=262_144, ge=32_768, le=2_000_000)
    model_gateway_base_url: str = Field(default="")
    assistant_orchestrator_url: str = Field(default="")
    assistant_orchestrator_timeout_seconds: float = Field(default=10.0, ge=1.0, le=30.0)
    assistant_orchestrator_max_response_bytes: int = Field(
        default=2 * 1024 * 1024,
        ge=4096,
        le=8 * 1024 * 1024,
    )
    model_gateway_managed_model_alias: str = Field(
        default="DroneDream Managed",
        min_length=1,
        max_length=128,
    )
    # User-supplied LLM credentials are deliberately short-lived even if a job
    # remains queued because no worker is available.  Terminal jobs purge them
    # earlier through the normal lifecycle hooks.
    job_secret_ttl_seconds: int = Field(default=86400, ge=300, le=604800)
    job_secret_cleanup_interval_seconds: int = Field(default=60, ge=10, le=3600)
    finalization_lease_seconds: int = Field(default=900, ge=60, le=7200)
    finalization_lease_heartbeat_seconds: float = Field(
        default=30.0,
        gt=0,
    )
    sqlite_busy_timeout_seconds: int = Field(default=30, ge=1, le=300)
    auth_mode: Literal["disabled", "demo_token", "oidc_jwt"] = Field(default="disabled")
    demo_auth_tokens: str = Field(default="")
    oidc_issuer: str | None = Field(default=None)
    oidc_audience: str | None = Field(default=None)
    oidc_jwks_url: str | None = Field(default=None)
    oidc_jwks_timeout_seconds: int = Field(default=5, ge=1, le=30)
    oidc_jwks_max_bytes: int = Field(
        default=1024 * 1024,
        ge=4096,
        le=16 * 1024 * 1024,
    )
    oidc_algorithms: str = Field(default="RS256,ES256")
    oidc_email_claim: str = Field(default="email")
    oidc_name_claim: str = Field(default="name")
    oidc_clock_skew_seconds: int = Field(default=30, ge=0, le=300)
    desktop_bridge_required: bool = Field(default=False)
    desktop_bridge_clock_skew_seconds: int = Field(default=30, ge=5, le=300)
    desktop_bridge_nonce_retention_seconds: int = Field(default=600, ge=60, le=86400)

    @field_validator("dronedream_runtime_id", mode="before")
    @classmethod
    def normalize_runtime_id(cls, value: object) -> str | None:
        """Normalize the optional desktop-runtime identity to canonical UUID text."""

        if value is None or not str(value).strip():
            return None
        raw = str(value).strip()
        try:
            parsed = UUID(raw)
        except ValueError as error:
            raise ValueError("DRONEDREAM_RUNTIME_ID must be a canonical UUID") from error
        canonical = str(parsed)
        if canonical != raw.lower():
            raise ValueError("DRONEDREAM_RUNTIME_ID must be a canonical UUID")
        return canonical

    @model_validator(mode="after")
    def validate_production_safety(self) -> Settings:
        """Reject the development-only anonymous identity in production."""

        protected_environment = self.app_env.strip().lower() in {
            "desktop",
            "prod",
            "production",
        }
        if self.worker_lease_heartbeat_seconds >= self.worker_lease_seconds:
            raise ValueError(
                "WORKER_LEASE_HEARTBEAT_SECONDS must be less than WORKER_LEASE_SECONDS"
            )
        if (
            self.finalization_lease_heartbeat_seconds
            >= self.finalization_lease_seconds
        ):
            raise ValueError(
                "FINALIZATION_LEASE_HEARTBEAT_SECONDS must be less than "
                "FINALIZATION_LEASE_SECONDS"
            )
        if self.worker_presence_interval_seconds >= self.worker_presence_ttl_seconds:
            raise ValueError(
                "WORKER_PRESENCE_INTERVAL_SECONDS must be less than WORKER_PRESENCE_TTL_SECONDS"
            )
        for setting_name, raw_root in (
            ("ARTIFACT_ROOT", self.artifact_root),
            ("REAL_SIMULATOR_ARTIFACT_ROOT", self.real_simulator_artifact_root),
        ):
            if not raw_root.strip():
                raise ValueError(f"{setting_name} cannot be blank")
            resolved_root = Path(raw_root).resolve()
            if resolved_root == Path(resolved_root.anchor):
                raise ValueError(f"{setting_name} cannot be a filesystem root")
        if (
            len(self.s3_prefix) > 512
            or any(ord(char) < 32 for char in self.s3_prefix)
            or self.s3_prefix.startswith("/")
            or "//" in self.s3_prefix
        ):
            raise ValueError("S3_PREFIX must be a relative object prefix of at most 512 chars")
        minimum_finalization_lease = (
            self.llm_request_timeout_seconds * (self.llm_max_retries + 1) + 60
        )
        if self.finalization_lease_seconds < minimum_finalization_lease:
            raise ValueError(
                "FINALIZATION_LEASE_SECONDS must be at least "
                "LLM_REQUEST_TIMEOUT_SECONDS * (LLM_MAX_RETRIES + 1) + 60 "
                "to prevent duplicate finalization and LLM calls"
            )
        if "*" in self.cors_origin_list:
            raise ValueError(
                "CORS_ORIGINS must list exact trusted origins; wildcard origins "
                "are incompatible with credentialed CORS"
            )
        if self.model_gateway_base_url.strip():
            gateway_url = urlsplit(self.model_gateway_base_url.strip().rstrip("/"))
            if (
                gateway_url.scheme != "https"
                or not gateway_url.hostname
                or gateway_url.username
                or gateway_url.password
                or gateway_url.query
                or gateway_url.fragment
            ):
                raise ValueError(
                    "MODEL_GATEWAY_BASE_URL must be a credential-free absolute HTTPS URL"
                )
        if self.assistant_orchestrator_url.strip():
            orchestrator_url = urlsplit(self.assistant_orchestrator_url.strip().rstrip("/"))
            if (
                orchestrator_url.scheme != "https"
                or not orchestrator_url.hostname
                or orchestrator_url.username
                or orchestrator_url.password
                or orchestrator_url.query
                or orchestrator_url.fragment
            ):
                raise ValueError(
                    "ASSISTANT_ORCHESTRATOR_URL must be a credential-free absolute HTTPS URL"
                )
            if self.oidc_issuer:
                issuer_url = urlsplit(self.oidc_issuer.strip().rstrip("/"))
                if (
                    orchestrator_url.scheme != issuer_url.scheme
                    or orchestrator_url.netloc != issuer_url.netloc
                ):
                    raise ValueError(
                        "ASSISTANT_ORCHESTRATOR_URL must share the trusted OIDC issuer origin"
                    )
        for origin in self.cors_origin_list:
            parsed_origin = urlsplit(origin)
            try:
                _ = parsed_origin.port
            except ValueError as exc:
                raise ValueError(f"CORS_ORIGINS contains an invalid port: {origin!r}") from exc
            if (
                parsed_origin.scheme not in {"http", "https", "tauri"}
                or not parsed_origin.hostname
                or parsed_origin.username
                or parsed_origin.password
                or parsed_origin.query
                or parsed_origin.fragment
                or parsed_origin.path not in {"", "/"}
                or parsed_origin.netloc.endswith(":")
            ):
                raise ValueError(
                    f"CORS_ORIGINS contains an invalid origin (scheme/host/port only): {origin!r}"
                )
            if (
                protected_environment
                and parsed_origin.scheme == "http"
                and parsed_origin.hostname not in {"localhost", "127.0.0.1", "::1"}
                and not parsed_origin.hostname.endswith(".localhost")
            ):
                raise ValueError("Production web CORS origins must use HTTPS (localhost is exempt)")
        if self.auth_mode == "demo_token" and self.demo_auth_tokens.strip():
            raw_pairs = [pair.strip() for pair in self.demo_auth_tokens.split(",") if pair.strip()]
            parsed_tokens: list[str] = []
            for pair in raw_pairs:
                if ":" not in pair:
                    raise ValueError("DEMO_AUTH_TOKENS entries must use the email:token format")
                email, token = (part.strip() for part in pair.split(":", 1))
                if (
                    not email
                    or len(email) > 255
                    or not token
                    or len(token) > 4096
                    or any(ord(char) < 32 for char in email + token)
                ):
                    raise ValueError("DEMO_AUTH_TOKENS contains an invalid email:token entry")
                if protected_environment and (
                    len(token.encode("utf-8")) < 32
                    or len(set(token)) < 8
                    or _is_obvious_placeholder(token)
                ):
                    raise ValueError(
                        "Production DEMO_AUTH_TOKENS must use non-placeholder tokens "
                        "of at least 32 UTF-8 bytes with adequate character diversity"
                    )
                parsed_tokens.append(token)
            if len(set(parsed_tokens)) != len(parsed_tokens):
                raise ValueError("DEMO_AUTH_TOKENS cannot assign the same token more than once")
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
                raise ValueError("AUTH_MODE=oidc_jwt requires " + ", ".join(missing))
            jwks_url = self.oidc_jwks_url
            if jwks_url is None:  # Defensive guard for future validator changes.
                raise ValueError("AUTH_MODE=oidc_jwt requires OIDC_JWKS_URL")
            parsed_jwks = urlsplit(jwks_url)
            try:
                _ = parsed_jwks.port
            except ValueError as exc:
                raise ValueError("OIDC_JWKS_URL contains an invalid port") from exc
            if (
                parsed_jwks.scheme not in {"http", "https"}
                or not parsed_jwks.hostname
                or parsed_jwks.username
                or parsed_jwks.password
                or parsed_jwks.fragment
            ):
                raise ValueError("OIDC_JWKS_URL must be an absolute HTTP(S) URL")
            if protected_environment and parsed_jwks.scheme != "https":
                raise ValueError(
                    "OIDC_JWKS_URL must use HTTPS in desktop and production environments"
                )
            allowed_algorithms = {"RS256", "RS384", "RS512", "ES256", "ES384", "EdDSA"}
            if not self.oidc_algorithm_list or not set(self.oidc_algorithm_list).issubset(
                allowed_algorithms
            ):
                raise ValueError(
                    "OIDC_ALGORITHMS must contain only asymmetric algorithms: "
                    + ", ".join(sorted(allowed_algorithms))
                )
        if protected_environment:
            if self.auth_mode == "disabled":
                raise ValueError(
                    "AUTH_MODE=disabled is forbidden when APP_ENV is desktop or production; "
                    "configure an authenticated mode before starting the service"
                )
            if self.auth_mode == "demo_token" and not self.demo_auth_token_map:
                raise ValueError(
                    "DEMO_AUTH_TOKENS must contain at least one email:token pair "
                    "when AUTH_MODE=demo_token in desktop or production"
                )
        if self.app_env.strip().lower() == "desktop" and not self.desktop_bridge_required:
            raise ValueError(
                "DESKTOP_BRIDGE_REQUIRED=true is mandatory when APP_ENV=desktop"
            )
        if self.app_env.strip().lower() == "desktop" and self.auth_mode != "oidc_jwt":
            raise ValueError(
                "Packaged APP_ENV=desktop requires AUTH_MODE=oidc_jwt"
            )
        if self.desktop_bridge_required:
            if self.app_env.strip().lower() != "desktop":
                raise ValueError(
                    "DESKTOP_BRIDGE_REQUIRED may be enabled only when APP_ENV=desktop"
                )
            if self.dronedream_runtime_id is None:
                raise ValueError(
                    "DESKTOP_BRIDGE_REQUIRED requires DRONEDREAM_RUNTIME_ID"
                )
        return self

    @property
    def cors_origin_list(self) -> list[str]:
        origins: list[str] = []
        for raw_origin in self.cors_origins.split(","):
            origin = raw_origin.strip()
            if origin and origin not in origins:
                origins.append(origin)
        return origins

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
    def managed_artifact_roots(self) -> list[Path]:
        """Directories exclusively managed by DroneDream cleanup.

        Cleanup never treats an entire operator-configured root as disposable.
        Only the ``jobs`` subtree used by report and trial persistence is
        eligible, which protects unrelated files when a broad parent directory
        was configured accidentally.
        """

        roots = [root / "jobs" for root in self.allowed_artifact_roots]
        dedup: list[Path] = []
        for root in roots:
            resolved = root.resolve()
            if resolved not in dedup:
                dedup.append(resolved)
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
        return [item.strip() for item in (self.oidc_audience or "").split(",") if item.strip()]

    @property
    def oidc_algorithm_list(self) -> list[str]:
        return [item.strip() for item in self.oidc_algorithms.split(",") if item.strip()]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a cached Settings instance."""

    return Settings()
