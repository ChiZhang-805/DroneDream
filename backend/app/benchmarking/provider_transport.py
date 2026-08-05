"""Strict one-request provider transport for formal benchmark execution.

Credentials exist only in this in-memory object and are never included in its
representation, provider receipts, or raised public errors.  The durable caller
persists the attempted request before invoking this transport and owns all
accounting and fail-closed outcome semantics.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

from app.benchmarking.llm_durable_runtime import BenchmarkProviderTransportResult
from app.benchmarking.provider_execution_contract import (
    BenchmarkProviderExecutionConfigV1,
    BenchmarkProviderRequestEnvelope,
)
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

    __slots__ = ("__api_key", "_client_factory")

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

    def __repr__(self) -> str:
        return "StrictBenchmarkChatCompletionsTransport(api_key=<redacted>)"

    def complete(
        self,
        request: BenchmarkProviderRequestEnvelope,
        config: BenchmarkProviderExecutionConfigV1,
    ) -> BenchmarkProviderTransportResult:
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
            api_key=self.__api_key,
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


__all__ = ["StrictBenchmarkChatCompletionsTransport"]
