from __future__ import annotations

import pytest

from app.secrets import SecretStoreError, decrypt_secret, encrypt_secret, is_configured


def test_development_passphrase_is_supported(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("APP_SECRET_KEY", "short-development-passphrase")
    monkeypatch.delenv("DRONEDREAM_SECRET_KEY", raising=False)

    token = encrypt_secret("api-key-value")

    assert is_configured() is True
    assert decrypt_secret(token) == "api-key-value"


@pytest.mark.parametrize("app_env", ["desktop", "production"])
@pytest.mark.parametrize(
    "key",
    [
        "too-short",
        "x" * 32,
        "replace-with-a-generated-fernet-key",
    ],
)
def test_production_rejects_weak_or_placeholder_secret_keys(
    monkeypatch: pytest.MonkeyPatch,
    app_env: str,
    key: str,
) -> None:
    monkeypatch.setenv("APP_ENV", app_env)
    monkeypatch.setenv("APP_SECRET_KEY", key)
    monkeypatch.delenv("DRONEDREAM_SECRET_KEY", raising=False)

    assert is_configured() is False
    with pytest.raises(SecretStoreError, match="non-placeholder value"):
        encrypt_secret("api-key-value")


def test_production_accepts_strong_secret_passphrase(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv(
        "APP_SECRET_KEY",
        "prod-secret-key-0123456789-ABCDEFGH-!@#$",
    )
    monkeypatch.delenv("DRONEDREAM_SECRET_KEY", raising=False)

    token = encrypt_secret("api-key-value")

    assert is_configured() is True
    assert decrypt_secret(token) == "api-key-value"


@pytest.mark.parametrize("app_env", ["desktop", "production"])
def test_protected_environment_rejects_a_migrated_development_token(
    monkeypatch: pytest.MonkeyPatch,
    app_env: str,
) -> None:
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.delenv("APP_SECRET_KEY", raising=False)
    monkeypatch.delenv("DRONEDREAM_SECRET_KEY", raising=False)
    development_token = encrypt_secret("api-key-value")
    assert development_token.startswith("DRONEDREAM_DEV::")

    monkeypatch.setenv("APP_ENV", app_env)
    monkeypatch.setenv(
        "APP_SECRET_KEY",
        "prod-secret-key-0123456789-ABCDEFGH-!@#$",
    )

    with pytest.raises(SecretStoreError, match="forbidden"):
        decrypt_secret(development_token)
