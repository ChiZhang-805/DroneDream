"""Pure, secret-free execution and capacity contracts for benchmark providers."""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Annotated, Any, Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app import schemas
from app.benchmarking.contracts import BenchmarkUsageDeltaV1, Sha256Hex
from app.benchmarking.llm_arm_contracts import (
    BENCHMARK_LLM_ARM_POLICIES_SHA256,
    BENCHMARK_LLM_MAX_RESPONSE_BYTES,
)

BENCHMARK_PROVIDER_EXECUTION_SCHEMA_ID: Literal["dronedream.benchmark-provider-execution/v1"] = (
    "dronedream.benchmark-provider-execution/v1"
)
BENCHMARK_DIRECT_RESERVATION_REASON = "benchmark-provider-execution"
BENCHMARK_DIRECT_MAX_REQUEST_BYTES = 65_536
BENCHMARK_PROVIDER_BASE_URLS = MappingProxyType(
    {
        "deepseek": "https://api.deepseek.com/v1",
        "openai": "https://api.openai.com/v1",
    }
)


@dataclass(frozen=True, repr=False)
class BenchmarkProviderRequestEnvelope:
    """In-memory exact request bytes shared by accounting and transport.

    The canonical body can contain prompts, so its representation is deliberately
    redacted and it is never part of a durable receipt.  Passing these exact bytes
    to the transport prevents an implementation from rebuilding a subtly different
    request (for example, dropping the preregistered provider seed).
    """

    _canonical_request_body: bytes
    request_body_sha256: Sha256Hex
    request_body_utf8_bytes: int

    @classmethod
    def from_request_body(
        cls,
        request_body: Mapping[str, Any],
    ) -> BenchmarkProviderRequestEnvelope:
        from app.benchmarking.contracts import canonical_json_bytes

        body = dict(request_body)
        encoded = canonical_json_bytes(body)
        return cls(
            _canonical_request_body=encoded,
            request_body_sha256=hashlib.sha256(encoded).hexdigest(),
            request_body_utf8_bytes=len(encoded),
        )

    def request_body(self) -> dict[str, Any]:
        """Decode a fresh request mapping and verify the immutable byte binding."""

        from app.benchmarking.contracts import canonical_json_bytes

        try:
            value = json.loads(self._canonical_request_body)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:  # pragma: no cover
            raise ValueError("benchmark provider request envelope is invalid") from exc
        if not isinstance(value, dict):  # pragma: no cover - constructor always uses a mapping.
            raise ValueError("benchmark provider request envelope is not an object")
        encoded = canonical_json_bytes(value)
        if (
            encoded != self._canonical_request_body
            or len(encoded) != self.request_body_utf8_bytes
            or hashlib.sha256(encoded).hexdigest() != self.request_body_sha256
        ):
            raise ValueError("benchmark provider request envelope hash drifted")
        return value

    def __repr__(self) -> str:
        return (
            "BenchmarkProviderRequestEnvelope("
            f"request_body_sha256={self.request_body_sha256!r}, "
            f"request_body_utf8_bytes={self.request_body_utf8_bytes})"
        )


class _StrictFrozen(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class BenchmarkProviderExecutionConfigV1(_StrictFrozen):
    """Provider identity and hard budgets frozen inside one arm manifest."""

    schema_id: Literal["dronedream.benchmark-provider-execution/v1"] = (
        BENCHMARK_PROVIDER_EXECUTION_SCHEMA_ID
    )
    provider: Annotated[str, Field(pattern=r"^[a-z0-9][a-z0-9._-]{0,63}$")]
    model_snapshot: Annotated[str, Field(min_length=1, max_length=128)]
    api_surface: Literal["chat_completions"] = "chat_completions"
    base_url: Annotated[str, Field(min_length=8, max_length=2048)]
    region: Annotated[str, Field(min_length=1, max_length=64)] | None = None
    temperature: Annotated[float, Field(ge=0, le=2)]
    top_p: Annotated[float, Field(gt=0, le=1)]
    randomness_policy: Literal["fixed_seed", "provider_managed"]
    response_format: Literal["json_schema"] = "json_schema"
    maximum_generations: Annotated[int, Field(ge=1, le=128)]
    maximum_request_utf8_bytes: Annotated[
        int,
        Field(ge=1, le=BENCHMARK_DIRECT_MAX_REQUEST_BYTES),
    ]
    maximum_response_utf8_bytes: Annotated[
        int,
        Field(ge=1, le=BENCHMARK_LLM_MAX_RESPONSE_BYTES),
    ]
    maximum_output_tokens: Annotated[int, Field(ge=1, le=8192)]
    request_timeout_ms: Annotated[int, Field(ge=1000, le=600_000)]
    provider_retry_cap: Literal[0] = 0
    llm_policy_registry_sha256: Sha256Hex
    model_matrix_sha256: Sha256Hex
    price_snapshot: schemas.ProviderPriceSnapshot

    @model_validator(mode="after")
    def _require_current_llm_policy(self) -> BenchmarkProviderExecutionConfigV1:
        if self.llm_policy_registry_sha256 != BENCHMARK_LLM_ARM_POLICIES_SHA256:
            raise ValueError("provider execution uses a different LLM policy registry")
        if self.price_snapshot.source != "preregistered":
            raise ValueError("formal provider execution requires preregistered prices")
        expected_base_url = BENCHMARK_PROVIDER_BASE_URLS.get(self.provider)
        parsed_base_url = urlsplit(self.base_url)
        if (
            expected_base_url is None
            or self.base_url != expected_base_url
            or parsed_base_url.scheme != "https"
            or parsed_base_url.username is not None
            or parsed_base_url.password is not None
            or parsed_base_url.query
            or parsed_base_url.fragment
            or parsed_base_url.port not in {None, 443}
        ):
            raise ValueError(
                "formal provider execution requires an exact approved "
                "credential-free HTTPS base URL"
            )
        return self


def direct_provider_run_capacity(
    config: BenchmarkProviderExecutionConfigV1,
) -> BenchmarkUsageDeltaV1:
    """Return the immutable worst-case capacity reserved for one direct run."""

    return provider_run_capacity(config, maximum_turns_per_generation=1)


def provider_run_capacity(
    config: BenchmarkProviderExecutionConfigV1,
    *,
    maximum_turns_per_generation: int,
) -> BenchmarkUsageDeltaV1:
    """Return immutable worst-case provider capacity for one bounded LLM run."""

    if not 1 <= maximum_turns_per_generation <= 4:
        raise ValueError("provider turns per generation must be between one and four")

    input_rate = config.price_snapshot.input_microusd_per_million_tokens
    output_rate = config.price_snapshot.output_microusd_per_million_tokens
    if input_rate is None or output_rate is None:  # pragma: no cover - model validator guards.
        raise ValueError("provider price snapshot is incomplete")
    per_generation_cost = math.ceil(
        (
            config.maximum_request_utf8_bytes * input_rate
            + config.maximum_output_tokens * output_rate
        )
        / 1_000_000
    )
    generations = config.maximum_generations
    turns = generations * maximum_turns_per_generation
    return BenchmarkUsageDeltaV1(
        logical_turns=turns,
        network_requests=turns,
        input_utf8_bytes=config.maximum_request_utf8_bytes * turns,
        output_utf8_bytes=config.maximum_response_utf8_bytes * turns,
        provider_tokens=(config.maximum_request_utf8_bytes + config.maximum_output_tokens) * turns,
        provider_cost_microusd=per_generation_cost * turns,
        wall_time_seconds=math.ceil(config.request_timeout_ms / 1000) * turns,
    )


__all__ = [
    "BENCHMARK_DIRECT_MAX_REQUEST_BYTES",
    "BENCHMARK_DIRECT_RESERVATION_REASON",
    "BENCHMARK_PROVIDER_BASE_URLS",
    "BENCHMARK_PROVIDER_EXECUTION_SCHEMA_ID",
    "BenchmarkProviderExecutionConfigV1",
    "BenchmarkProviderRequestEnvelope",
    "direct_provider_run_capacity",
    "provider_run_capacity",
]
