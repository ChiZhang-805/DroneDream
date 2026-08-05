"""Strict one-request provider transport for formal benchmark execution.

Credentials exist only in this in-memory object and are never included in its
representation, provider receipts, or raised public errors.  The durable caller
persists the attempted request before invoking this transport and owns all
accounting and fail-closed outcome semantics.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import models
from app import secrets as job_secrets
from app.benchmarking.llm_durable_runtime import (
    BenchmarkDurableLLMBlocked,
    BenchmarkProviderTransportResult,
)
from app.benchmarking.provider_execution_contract import (
    BenchmarkProviderExecutionConfigV1,
    BenchmarkProviderRequestEnvelope,
)
from app.orchestration.events import record_event
from app.orchestration.provider_request_accounting import ProviderUsage

_ClientFactory = Callable[..., Any]


def _openai_client_factory(**kwargs: Any) -> Any:
    from openai import OpenAI

    return OpenAI(**kwargs)


def _optional_nonnegative_int(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value


class StrictBenchmarkChatCompletionsTransport:
    """Send exactly the accounted Chat Completions body, once, with zero retries."""

    __slots__ = ("__api_key", "_client_factory", "_used")

    def __init__(
        self,
        api_key: str,
        *,
        client_factory: _ClientFactory = _openai_client_factory,
    ) -> None:
        if not isinstance(api_key, str) or not api_key.strip():
            raise ValueError("benchmark provider credential is unavailable")
        self.__api_key = api_key
        self._client_factory = client_factory
        self._used = False

    def __repr__(self) -> str:
        return "StrictBenchmarkChatCompletionsTransport(api_key=<redacted>)"

    def complete(
        self,
        request: BenchmarkProviderRequestEnvelope,
        config: BenchmarkProviderExecutionConfigV1,
    ) -> BenchmarkProviderTransportResult:
        if self._used:
            raise RuntimeError("benchmark provider transport is single-use")
        self._used = True
        api_key = self.__api_key
        # Drop the object's long-lived reference before validation or network
        # I/O. The local variable survives only for this one call frame.
        self.__api_key = ""
        if config.api_surface != "chat_completions" or config.provider_retry_cap != 0:
            raise RuntimeError("benchmark provider transport contract is unsupported")
        body = request.request_body()
        if (
            body.get("model") != config.model_snapshot
            or body.get("temperature") != config.temperature
            or body.get("top_p") != config.top_p
            or body.get("max_tokens") != config.maximum_output_tokens
            or not isinstance(body.get("messages"), list)
            or not isinstance(body.get("response_format"), dict)
        ):
            raise RuntimeError("benchmark provider request differs from frozen config")

        client = self._client_factory(
            api_key=api_key,
            base_url=config.base_url,
            timeout=config.request_timeout_ms / 1000,
            max_retries=0,
        )
        started_ns = time.perf_counter_ns()
        response = client.chat.completions.create(**body)
        latency_ms = max(0, (time.perf_counter_ns() - started_ns) // 1_000_000)

        choices = getattr(response, "choices", None)
        message = getattr(choices[0], "message", None) if choices else None
        content = getattr(message, "content", None)
        response_text = content if isinstance(content, str) else ""
        usage = getattr(response, "usage", None)
        return BenchmarkProviderTransportResult(
            response_text=response_text,
            usage=ProviderUsage(
                input_tokens=_optional_nonnegative_int(
                    getattr(usage, "prompt_tokens", None)
                ),
                output_tokens=_optional_nonnegative_int(
                    getattr(usage, "completion_tokens", None)
                ),
                total_tokens=_optional_nonnegative_int(
                    getattr(usage, "total_tokens", None)
                ),
            ),
            latency_ms=latency_ms,
        )


def _as_utc(value: datetime) -> datetime:
    # SQLite may round-trip timezone-aware columns as naive values.
    return (
        value.replace(tzinfo=timezone.utc)
        if value.tzinfo is None
        else value.astimezone(timezone.utc)
    )


def build_job_secret_benchmark_transport(
    db: Session,
    job: models.Job,
    config: BenchmarkProviderExecutionConfigV1,
    *,
    client_factory: _ClientFactory = _openai_client_factory,
) -> StrictBenchmarkChatCompletionsTransport:
    """Resolve one Job-bound BYOK credential without exposing its plaintext.

    Existing product Jobs use ``provider='openai'`` as the encrypted slot name
    for every OpenAI-compatible BYOK credential, including DeepSeek. Provider,
    model and endpoint identity remain frozen separately on the Job and arm;
    this resolver therefore requires one unambiguous slot on the same Job and
    never falls back to an environment variable or another Job.
    """

    if (
        job.llm_access_mode != "byok"
        or job.llm_provider != config.provider
        or config.provider not in {"openai", "deepseek"}
    ):
        raise BenchmarkDurableLLMBlocked(
            "benchmark_provider_credential_context_mismatch",
            "Benchmark provider credential context differs from the frozen Job.",
        )

    now = datetime.now(timezone.utc)
    stored = list(
        db.scalars(
            select(models.JobSecret)
            .where(
                models.JobSecret.job_id == job.id,
                models.JobSecret.deleted_at.is_(None),
                models.JobSecret.encrypted_api_key != "",
            )
            .order_by(models.JobSecret.created_at, models.JobSecret.id)
        )
    )
    expired = [
        secret
        for secret in stored
        if secret.expires_at is not None and _as_utc(secret.expires_at) <= now
    ]
    if expired:
        for secret in expired:
            secret.deleted_at = now
            secret.encrypted_api_key = ""
        record_event(
            db,
            job.id,
            "job_secrets_purged",
            {"reason": "secret_expired", "count": len(expired)},
        )
        db.flush()
    active = [secret for secret in stored if secret not in expired]
    if len(active) != 1 or active[0].provider != "openai":
        raise BenchmarkDurableLLMBlocked(
            "benchmark_provider_credential_unavailable",
            "Exactly one active Job-bound BYOK credential is required.",
        )
    try:
        credential = job_secrets.decrypt_secret(active[0].encrypted_api_key)
    except job_secrets.SecretStoreError as exc:
        raise BenchmarkDurableLLMBlocked(
            "benchmark_provider_credential_invalid",
            "The Job-bound BYOK credential cannot be decrypted.",
        ) from exc
    try:
        return StrictBenchmarkChatCompletionsTransport(
            credential,
            client_factory=client_factory,
        )
    finally:
        credential = ""


__all__ = [
    "StrictBenchmarkChatCompletionsTransport",
    "build_job_secret_benchmark_transport",
]
