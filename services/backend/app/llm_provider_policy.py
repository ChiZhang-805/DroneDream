"""Shared policy for user-configured OpenAI-compatible provider endpoints."""

from __future__ import annotations

from app.config import Settings, get_settings


def llm_base_url_is_allowed(
    base_url: str | None,
    *,
    settings: Settings | None = None,
) -> bool:
    """Return whether a normalized provider URL may be contacted.

    Local desktop deployments deliberately allow an explicitly user-entered
    OpenAI-compatible endpoint. Production deployments, or any deployment
    that configures an allowlist, fail closed to the exact normalized entries
    in ``LLM_ALLOWED_BASE_URLS``. Schema validation separately rejects
    credentials, queries, fragments, and non-HTTP(S) URLs.
    """

    if not base_url:
        return True
    effective_settings = settings or get_settings()
    allowed = {
        item.strip().rstrip("/")
        for item in effective_settings.llm_allowed_base_urls.split(",")
        if item.strip()
    }
    is_production = effective_settings.app_env.strip().lower() in {
        "prod",
        "production",
    }
    if not is_production and not allowed:
        return True
    return base_url.rstrip("/") in allowed


__all__ = ["llm_base_url_is_allowed"]
