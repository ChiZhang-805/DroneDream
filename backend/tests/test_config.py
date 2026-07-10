from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.config import Settings, get_settings


def test_default_cors_origins_include_web_and_desktop_clients() -> None:
    origins = Settings().cors_origin_list

    assert set(origins) == {
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://tauri.localhost",
        "tauri://localhost",
    }
    assert "*" not in origins


def test_cors_origins_are_deduplicated_in_order() -> None:
    settings = Settings(
        cors_origins="http://localhost:5173, http://localhost:5173,tauri://localhost"
    )

    assert settings.cors_origin_list == [
        "http://localhost:5173",
        "tauri://localhost",
    ]


def test_cors_rejects_wildcard_with_credentials() -> None:
    with pytest.raises(ValidationError, match="wildcard origins"):
        Settings(cors_origins="*")


def test_finalization_lease_covers_llm_retry_window() -> None:
    with pytest.raises(ValidationError, match="FINALIZATION_LEASE_SECONDS"):
        Settings(
            llm_request_timeout_seconds=600,
            llm_max_retries=5,
            finalization_lease_seconds=900,
        )

    settings = Settings(
        llm_request_timeout_seconds=600,
        llm_max_retries=5,
        finalization_lease_seconds=3700,
    )
    assert settings.finalization_lease_seconds == 3700


def test_runtime_id_is_optional_and_requires_a_canonical_uuid() -> None:
    assert Settings().dronedream_runtime_id is None
    assert (
        Settings(
            dronedream_runtime_id="123E4567-E89B-12D3-A456-426614174000"
        ).dronedream_runtime_id
        == "123e4567-e89b-12d3-a456-426614174000"
    )
    with pytest.raises(ValidationError, match="canonical UUID"):
        Settings(dronedream_runtime_id="runtime-development")


def test_default_real_simulator_artifact_root_matches_cli_default(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("REAL_SIMULATOR_ARTIFACT_ROOT", raising=False)
    monkeypatch.delenv("ARTIFACT_ROOT", raising=False)
    get_settings.cache_clear()

    settings = get_settings()

    assert settings.real_simulator_artifact_root == "./artifacts"
    assert settings.real_artifact_root_path == (tmp_path / "artifacts").resolve()
    assert settings.real_artifact_root_path in settings.allowed_artifact_roots

    get_settings.cache_clear()


def test_production_rejects_disabled_auth() -> None:
    with pytest.raises(ValidationError, match="AUTH_MODE=disabled is forbidden"):
        Settings(app_env="production", auth_mode="disabled")


def test_production_demo_auth_requires_at_least_one_token() -> None:
    with pytest.raises(ValidationError, match="DEMO_AUTH_TOKENS"):
        Settings(app_env="production", auth_mode="demo_token", demo_auth_tokens="")


def test_production_demo_auth_accepts_configured_token() -> None:
    settings = Settings(
        app_env="production",
        auth_mode="demo_token",
        demo_auth_tokens="operator@example.com:secret",
    )
    assert settings.demo_auth_token_map == {"secret": "operator@example.com"}


def test_oidc_auth_requires_complete_verifier_configuration() -> None:
    with pytest.raises(ValidationError, match="OIDC_ISSUER"):
        Settings(app_env="production", auth_mode="oidc_jwt")


def test_production_oidc_auth_accepts_asymmetric_https_configuration() -> None:
    settings = Settings(
        app_env="production",
        auth_mode="oidc_jwt",
        oidc_issuer="https://identity.example.com/",
        oidc_audience="dronedream-api",
        oidc_jwks_url="https://identity.example.com/.well-known/jwks.json",
        oidc_algorithms="RS256,ES256",
    )
    assert settings.oidc_audience_list == ["dronedream-api"]
    assert settings.oidc_algorithm_list == ["RS256", "ES256"]


def test_oidc_auth_rejects_symmetric_token_algorithms() -> None:
    with pytest.raises(ValidationError, match="asymmetric algorithms"):
        Settings(
            auth_mode="oidc_jwt",
            oidc_issuer="https://identity.example.com/",
            oidc_audience="dronedream-api",
            oidc_jwks_url="https://identity.example.com/jwks.json",
            oidc_algorithms="HS256",
        )
