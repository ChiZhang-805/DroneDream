"""Server-owned registry for benchmark proposal adapters.

Entries may be preregistered before their implementation exists, but a campaign
cannot mark such an arm executable.  P1 promotes adapters one at a time only
after the common fake-provider/numerical-landscape contract passes.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

from app.benchmarking.contracts import BenchmarkProposalAdapter


@dataclass(frozen=True, slots=True)
class BenchmarkAdapterDescriptor:
    adapter_id: str
    family: Literal["traditional", "llm_harness"]
    availability: Literal["contract_only", "implemented"]
    implementation_label: str
    method_classification: Literal[
        "standard_reference",
        "adapted_reference",
        "product_native",
        "product_inspired",
    ]


_DESCRIPTORS = (
    BenchmarkAdapterDescriptor(
        "random_search/v1",
        "traditional",
        "implemented",
        "stdlib-sha256-uniform-v1",
        "standard_reference",
    ),
    BenchmarkAdapterDescriptor(
        "seeded_halton/v1",
        "traditional",
        "implemented",
        "native-seed-offset-halton-v1",
        "standard_reference",
    ),
    BenchmarkAdapterDescriptor(
        "bipop_cma_es/v1",
        "traditional",
        "contract_only",
        "reference-adapter-pending",
        "standard_reference",
    ),
    BenchmarkAdapterDescriptor(
        "optuna_tpe/v1",
        "traditional",
        "contract_only",
        "optuna-adapter-pending",
        "standard_reference",
    ),
    BenchmarkAdapterDescriptor(
        "repo_constrained_mobo/v1",
        "traditional",
        "implemented",
        "native-matern52-ard-gp",
        "product_native",
    ),
    BenchmarkAdapterDescriptor(
        "reference_scbo/v1",
        "traditional",
        "contract_only",
        "botorch-reference-adapter-pending",
        "standard_reference",
    ),
    BenchmarkAdapterDescriptor(
        "hebo/v1", "traditional", "contract_only", "hebo-adapter-pending", "standard_reference"
    ),
    BenchmarkAdapterDescriptor(
        "optimizer_portfolio/v1",
        "traditional",
        "implemented",
        "native-deterministic-portfolio",
        "product_native",
    ),
    BenchmarkAdapterDescriptor(
        "llm_direct/v1",
        "llm_harness",
        "contract_only",
        "direct-adapter-pending",
        "adapted_reference",
    ),
    BenchmarkAdapterDescriptor(
        "llm_react/v1",
        "llm_harness",
        "contract_only",
        "bounded-react-adapter-pending",
        "adapted_reference",
    ),
    BenchmarkAdapterDescriptor(
        "llambo_uav/v1",
        "llm_harness",
        "contract_only",
        "noisy-uav-adaptation-pending",
        "adapted_reference",
    ),
    BenchmarkAdapterDescriptor(
        "dronedream_fixed_two_turn/v1",
        "llm_harness",
        "contract_only",
        "fixed-two-turn-pending",
        "product_native",
    ),
    BenchmarkAdapterDescriptor(
        "dronedream_adaptive_1_4/v1",
        "llm_harness",
        "contract_only",
        "adaptive-one-four-pending",
        "product_native",
    ),
)

BENCHMARK_ADAPTER_REGISTRY = {item.adapter_id: item for item in _DESCRIPTORS}


def require_registered_adapter(adapter_id: str) -> BenchmarkAdapterDescriptor:
    try:
        return BENCHMARK_ADAPTER_REGISTRY[adapter_id]
    except KeyError as exc:
        raise ValueError(f"unregistered benchmark proposal adapter: {adapter_id}") from exc


def create_benchmark_adapter(adapter_id: str) -> BenchmarkProposalAdapter:
    """Instantiate only adapters whose server implementation is reviewable."""

    descriptor = require_registered_adapter(adapter_id)
    if descriptor.availability != "implemented":
        raise ValueError(f"benchmark proposal adapter is not implemented: {adapter_id}")
    from app.benchmarking.adapters import (
        ProductNativeOptimizerAdapterV1,
        RandomSearchAdapterV1,
        SeededHaltonAdapterV1,
    )

    implementations: dict[str, Callable[[], BenchmarkProposalAdapter]] = {
        "random_search/v1": RandomSearchAdapterV1,
        "seeded_halton/v1": SeededHaltonAdapterV1,
        "repo_constrained_mobo/v1": lambda: ProductNativeOptimizerAdapterV1(
            "repo_constrained_mobo/v1", "constrained_mobo"
        ),
        "optimizer_portfolio/v1": lambda: ProductNativeOptimizerAdapterV1(
            "optimizer_portfolio/v1", "optimizer_portfolio"
        ),
    }
    implementation = implementations.get(adapter_id)
    if implementation is None:
        raise RuntimeError(
            f"implemented benchmark adapter has no server factory binding: {adapter_id}"
        )
    return implementation()


__all__ = [
    "BENCHMARK_ADAPTER_REGISTRY",
    "BenchmarkAdapterDescriptor",
    "create_benchmark_adapter",
    "require_registered_adapter",
]
