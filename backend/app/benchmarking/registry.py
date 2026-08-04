"""Server-owned registry for benchmark proposal adapters.

Entries may be preregistered before their implementation exists, but a campaign
cannot mark such an arm executable.  P1 promotes adapters one at a time only
after the common fake-provider/numerical-landscape contract passes.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True, slots=True)
class BenchmarkAdapterDescriptor:
    adapter_id: str
    family: Literal["traditional", "llm_harness"]
    availability: Literal["contract_only", "implemented"]
    implementation_label: str


_DESCRIPTORS = (
    BenchmarkAdapterDescriptor("random_search/v1", "traditional", "contract_only", "P1"),
    BenchmarkAdapterDescriptor("seeded_halton/v1", "traditional", "contract_only", "P1"),
    BenchmarkAdapterDescriptor("bipop_cma_es/v1", "traditional", "contract_only", "P1"),
    BenchmarkAdapterDescriptor("optuna_tpe/v1", "traditional", "contract_only", "P1"),
    BenchmarkAdapterDescriptor("repo_constrained_mobo/v1", "traditional", "contract_only", "P1"),
    BenchmarkAdapterDescriptor("reference_scbo/v1", "traditional", "contract_only", "P1"),
    BenchmarkAdapterDescriptor("hebo/v1", "traditional", "contract_only", "P1"),
    BenchmarkAdapterDescriptor(
        "optimizer_portfolio/v1", "traditional", "contract_only", "P1"
    ),
    BenchmarkAdapterDescriptor("llm_direct/v1", "llm_harness", "contract_only", "P1"),
    BenchmarkAdapterDescriptor("llm_react/v1", "llm_harness", "contract_only", "P1"),
    BenchmarkAdapterDescriptor("llambo_uav/v1", "llm_harness", "contract_only", "P1"),
    BenchmarkAdapterDescriptor(
        "dronedream_fixed_two_turn/v1", "llm_harness", "contract_only", "P1"
    ),
    BenchmarkAdapterDescriptor(
        "dronedream_adaptive_1_4/v1", "llm_harness", "contract_only", "P1"
    ),
)

BENCHMARK_ADAPTER_REGISTRY = {item.adapter_id: item for item in _DESCRIPTORS}


def require_registered_adapter(adapter_id: str) -> BenchmarkAdapterDescriptor:
    try:
        return BENCHMARK_ADAPTER_REGISTRY[adapter_id]
    except KeyError as exc:
        raise ValueError(f"unregistered benchmark proposal adapter: {adapter_id}") from exc


__all__ = [
    "BENCHMARK_ADAPTER_REGISTRY",
    "BenchmarkAdapterDescriptor",
    "require_registered_adapter",
]
