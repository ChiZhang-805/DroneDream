from __future__ import annotations

import json
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any

import pytest

from app.benchmarking.llm_arm_contracts import BENCHMARK_LLM_ARM_POLICIES_SHA256
from app.benchmarking.provider_execution_contract import (
    BenchmarkProviderExecutionConfigV1,
    BenchmarkProviderRequestEnvelope,
)
from app.benchmarking.provider_transport import (
    StrictBenchmarkChatCompletionsTransport,
)
from app.schemas import ProviderPriceSnapshot


def _config() -> BenchmarkProviderExecutionConfigV1:
    return BenchmarkProviderExecutionConfigV1(
        provider="openai",
        model_snapshot="gpt-4.1-2025-04-14",
        base_url="https://api.openai.com/v1",
        region="global",
        temperature=0.0,
        top_p=1.0,
        randomness_policy="fixed_seed",
        maximum_generations=2,
        maximum_request_utf8_bytes=65_536,
        maximum_response_utf8_bytes=8_192,
        maximum_output_tokens=128,
        request_timeout_ms=10_000,
        llm_policy_registry_sha256=BENCHMARK_LLM_ARM_POLICIES_SHA256,
        model_matrix_sha256="6" * 64,
        price_snapshot=ProviderPriceSnapshot(
            schema_version="dronedream.provider-price-snapshot/v1",
            source="preregistered",
            input_microusd_per_million_tokens=2_000_000,
            output_microusd_per_million_tokens=8_000_000,
            effective_at=datetime(2026, 8, 5, tzinfo=timezone.utc),
        ),
    )


def _body() -> dict[str, Any]:
    return {
        "model": "gpt-4.1-2025-04-14",
        "messages": [
            {"role": "system", "content": "secret-free system fixture"},
            {"role": "user", "content": "bounded observation fixture"},
        ],
        "temperature": 0.0,
        "top_p": 1.0,
        "max_tokens": 128,
        "response_format": {
            "type": "json_schema",
            "json_schema": {"name": "fixture", "strict": True, "schema": {}},
        },
        "seed": 20260805,
    }


class _Completions:
    def __init__(self, response: object) -> None:
        self.response = response
        self.calls: list[dict[str, Any]] = []

    def create(self, **body: Any) -> object:
        self.calls.append(body)
        if isinstance(self.response, BaseException):
            raise self.response
        return self.response


class _Factory:
    def __init__(self, response: object) -> None:
        self.completions = _Completions(response)
        self.calls: list[dict[str, Any]] = []

    def __call__(self, **kwargs: Any) -> object:
        self.calls.append(kwargs)
        return SimpleNamespace(chat=SimpleNamespace(completions=self.completions))


def _response(*, with_usage: bool = True) -> object:
    usage = (
        SimpleNamespace(prompt_tokens=100, completion_tokens=20, total_tokens=120)
        if with_usage
        else None
    )
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content='{"ok":true}'))],
        usage=usage,
    )


def test_request_envelope_preserves_exact_canonical_body_and_redacts_repr() -> None:
    body = _body()
    envelope = BenchmarkProviderRequestEnvelope.from_request_body(body)

    assert envelope.request_body() == body
    assert envelope.request_body_utf8_bytes == len(
        json.dumps(
            body,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    )
    assert "system fixture" not in repr(envelope)
    assert "bounded observation" not in repr(envelope)


def test_strict_transport_sends_exact_accounted_body_once_with_zero_retries() -> None:
    api_key = "test-only-key-never-persist"
    body = _body()
    envelope = BenchmarkProviderRequestEnvelope.from_request_body(body)
    factory = _Factory(_response())
    transport = StrictBenchmarkChatCompletionsTransport(
        api_key,
        client_factory=factory,
    )

    result = transport.complete(envelope, _config())

    assert factory.calls == [
        {
            "api_key": api_key,
            "base_url": "https://api.openai.com/v1",
            "timeout": 10.0,
            "max_retries": 0,
        }
    ]
    assert factory.completions.calls == [body]
    assert factory.completions.calls[0]["seed"] == 20260805
    assert result.response_text == '{"ok":true}'
    assert result.usage.total_tokens == 120
    assert api_key not in repr(transport)


def test_strict_transport_never_retries_or_drops_response_format() -> None:
    factory = _Factory(RuntimeError("response_format is unsupported"))
    transport = StrictBenchmarkChatCompletionsTransport(
        "test-only-key",
        client_factory=factory,
    )

    with pytest.raises(RuntimeError, match="unsupported"):
        transport.complete(
            BenchmarkProviderRequestEnvelope.from_request_body(_body()),
            _config(),
        )

    assert len(factory.calls) == 1
    assert len(factory.completions.calls) == 1
    assert "response_format" in factory.completions.calls[0]


def test_strict_transport_does_not_fabricate_missing_usage() -> None:
    factory = _Factory(_response(with_usage=False))
    result = StrictBenchmarkChatCompletionsTransport(
        "test-only-key",
        client_factory=factory,
    ).complete(
        BenchmarkProviderRequestEnvelope.from_request_body(_body()),
        _config(),
    )

    assert result.usage.input_tokens is None
    assert result.usage.output_tokens is None
    assert result.usage.total_tokens is None


def test_strict_transport_rejects_request_config_drift_before_client_creation() -> None:
    body = _body()
    body["model"] = "different-model"
    factory = _Factory(_response())
    transport = StrictBenchmarkChatCompletionsTransport(
        "test-only-key",
        client_factory=factory,
    )

    with pytest.raises(RuntimeError, match="differs from frozen config"):
        transport.complete(
            BenchmarkProviderRequestEnvelope.from_request_body(body),
            _config(),
        )

    assert factory.calls == []
