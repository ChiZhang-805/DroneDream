"""Per-job secret storage (Phase 8).

Stores short-lived user-supplied credentials — currently only the OpenAI API
key used by the GPT parameter proposer — as Fernet-encrypted ciphertext.
The key is never logged, never returned to clients, and is wiped from the
``job_secrets`` table as soon as the job reaches a terminal state.

The module intentionally falls back to an obvious local-dev-only scheme
when neither ``APP_SECRET_KEY`` nor ``DRONEDREAM_SECRET_KEY`` is configured:
it base64-encodes the ciphertext with a static development token so the
iterative GPT loop still works on a developer's laptop. Production
deployments must set the env var; the service layer rejects GPT jobs when
no secret key is configured and the user asked for a GPT-backed run.
"""

from __future__ import annotations

import base64
import hashlib
import logging
import os
from typing import Protocol

logger = logging.getLogger("drone_dream.secrets")

_DEV_MARKER = "DRONEDREAM_DEV::"
_PRODUCTION_ENVS = frozenset({"prod", "production"})
_PLACEHOLDER_MARKERS = (
    "change-me",
    "changeme",
    "example-key",
    "replace-me",
    "replace-with",
    "your-key",
)


class SecretStoreError(RuntimeError):
    """Raised when secret encryption or decryption cannot be performed."""


class _FernetCipher(Protocol):
    def encrypt(self, data: bytes) -> bytes: ...

    def decrypt(self, token: bytes) -> bytes: ...


def _is_production() -> bool:
    return os.environ.get("APP_ENV", "development").strip().lower() in _PRODUCTION_ENVS


def _validate_production_key(raw: str) -> None:
    if not _is_production():
        return
    normalized = raw.strip()
    marker_value = normalized.lower().replace("_", "-")
    if (
        len(normalized.encode("utf-8")) < 32
        or len(set(normalized)) < 8
        or any(marker in marker_value for marker in _PLACEHOLDER_MARKERS)
    ):
        raise SecretStoreError(
            "APP_SECRET_KEY must be a non-placeholder value of at least 32 UTF-8 "
            "bytes with adequate character diversity in production."
        )


def _load_fernet() -> _FernetCipher | None:
    """Return a Fernet cipher if a real key is configured, else ``None``."""

    raw = os.environ.get("APP_SECRET_KEY") or os.environ.get("DRONEDREAM_SECRET_KEY")
    if not raw:
        return None
    _validate_production_key(raw)
    try:
        from cryptography.fernet import Fernet
    except ImportError:  # pragma: no cover — dev convenience only
        if _is_production():
            raise SecretStoreError(
                "cryptography is required for production secret storage."
            ) from None
        logger.warning("cryptography is not installed; falling back to local-dev secret store")
        return None

    normalized = raw.strip()
    # An all-whitespace value must behave exactly like an unset value.  Without
    # this guard it would be hashed into the publicly reproducible SHA-256 of
    # the empty string and incorrectly reported as production-grade storage.
    if not normalized:
        return None
    try:
        Fernet(normalized.encode("ascii"))
        key_bytes = normalized.encode("ascii")
    except Exception:
        digest = hashlib.sha256(normalized.encode("utf-8")).digest()
        key_bytes = base64.urlsafe_b64encode(digest)
    return Fernet(key_bytes)


def is_configured() -> bool:
    """Whether a production-grade Fernet key is configured."""

    try:
        return _load_fernet() is not None
    except SecretStoreError:
        return False


def encrypt_secret(value: str) -> str:
    """Encrypt ``value`` and return an opaque string."""

    if not value:
        raise SecretStoreError("Cannot encrypt an empty secret.")
    cipher = _load_fernet()
    if cipher is not None:
        token = cipher.encrypt(value.encode("utf-8")).decode("ascii")
        return token
    encoded = base64.urlsafe_b64encode(value.encode("utf-8")).decode("ascii")
    return f"{_DEV_MARKER}{encoded}"


def decrypt_secret(token: str) -> str:
    """Reverse :func:`encrypt_secret`. Raises :class:`SecretStoreError` on error."""

    if not token:
        raise SecretStoreError("Cannot decrypt an empty token.")
    if token.startswith(_DEV_MARKER):
        try:
            return base64.urlsafe_b64decode(token.removeprefix(_DEV_MARKER).encode("ascii")).decode(
                "utf-8"
            )
        except Exception as exc:
            raise SecretStoreError("Local-dev secret token is malformed.") from exc
    cipher = _load_fernet()
    if cipher is None:
        raise SecretStoreError(
            "APP_SECRET_KEY is not configured but an encrypted secret was stored."
        )
    from cryptography.fernet import InvalidToken

    try:
        return cipher.decrypt(token.encode("ascii")).decode("utf-8")
    except InvalidToken as exc:
        raise SecretStoreError("Secret token failed Fernet validation.") from exc


__all__ = [
    "SecretStoreError",
    "decrypt_secret",
    "encrypt_secret",
    "is_configured",
]
