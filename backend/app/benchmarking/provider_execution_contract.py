"""Pure, secret-free execution and capacity contracts for benchmark providers."""

from __future__ import annotations

import math
from types import MappingProxyType
from typing import Annotated, Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app import schemas
from app.benchmarking.contracts import BenchmarkUsageDeltaV1, Sha256Hex
from app.benchmarking.llm_arm_contracts import (
    BENCHMARK_LLM_ARM_POLICIES_SHA256,
    BENCHMARK_LLM_MAX_RESPONSE_BYTES,
)

BENCHMARK_PROVIDER_EXECUTION_SCHEMA_ID: Literal[
    "dronedream.benchmark-provider-execution/v1"
] = "dronedream.benchmark-provider-execution/v1"
BENCHMARK_DIRECT_RESERVATION_REASON = "benchmark-provider-execution"
BENCHMARK_DIRECT_MAX_REQUEST_BYTES = 65_536
BENCHMARK_PROVIDER_BASE_URLS = MappingProxyType(
    {
        "deepseek": "https://api.deepseek.com/v1",
        "openai": "https://api.openai.com/v1",
    }
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
    return BenchmarkUsageDeltaV1(
        logical_turns=generations,
        network_requests=generations,
        input_utf8_bytes=config.maximum_request_utf8_bytes * generations,
        output_utf8_bytes=config.maximum_response_utf8_bytes * generations,
        provider_tokens=(
            config.maximum_request_utf8_bytes + config.maximum_output_tokens
        )
        * generations,
        provider_cost_microusd=per_generation_cost * generations,
        wall_time_seconds=math.ceil(config.request_timeout_ms / 1000) * generations,
    )


__all__ = [
    "BENCHMARK_DIRECT_MAX_REQUEST_BYTES",
    "BENCHMARK_DIRECT_RESERVATION_REASON",
    "BENCHMARK_PROVIDER_BASE_URLS",
    "BENCHMARK_PROVIDER_EXECUTION_SCHEMA_ID",
    "BenchmarkProviderExecutionConfigV1",
    "direct_provider_run_capacity",
]
