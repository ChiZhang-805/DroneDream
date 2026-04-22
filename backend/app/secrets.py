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

logger = logging.getLogger("drone_dream.secrets")

_DEV_MARKER = "DRONEDREAM_DEV::"


class SecretStoreError(RuntimeError):
    """Raised when secret encryption or decryption cannot be performed."""


def _load_fernet() -> object | None:
    """Return a Fernet cipher if a real key is configured, else ``None``."""

    raw = os.environ.get("APP_SECRET_KEY") or os.environ.get("DRONEDREAM_SECRET_KEY")
    if not raw:
        return None
    try:
        from cryptography.fernet import Fernet
    except ImportError:  # pragma: no cover — dev convenience only
        logger.warning(
            "cryptography is not installed; falling back to local-dev secret store"
        )
        return None

    normalized = raw.strip()
    try:
        Fernet(normalized.encode("ascii"))
        key_bytes = normalized.encode("ascii")
    except Exception:
        digest = hashlib.sha256(normalized.encode("utf-8")).digest()
        key_bytes = base64.urlsafe_b64encode(digest)
    return Fernet(key_bytes)


def is_configured() -> bool:
    """Whether a production-grade Fernet key is configured."""

    return _load_fernet() is not None


def encrypt_secret(value: str) -> str:
    """Encrypt ``value`` and return an opaque string."""

    if not value:
        raise SecretStoreError("Cannot encrypt an empty secret.")
    cipher = _load_fernet()
    if cipher is not None:
        from cryptography.fernet import Fernet

        assert isinstance(cipher, Fernet)
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
            return base64.urlsafe_b64decode(
                token.removeprefix(_DEV_MARKER).encode("ascii")
            ).decode("utf-8")
        except Exception as exc:
            raise SecretStoreError("Local-dev secret token is malformed.") from exc
    cipher = _load_fernet()
    if cipher is None:
        raise SecretStoreError(
            "APP_SECRET_KEY is not configured but an encrypted secret was stored."
        )
    from cryptography.fernet import Fernet, InvalidToken

    assert isinstance(cipher, Fernet)
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
