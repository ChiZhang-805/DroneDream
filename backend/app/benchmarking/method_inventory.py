"""Machine-verifiable provenance and readiness for benchmark methods.

The registry answers *which* arm names exist.  This inventory answers whether
an arm is safe to execute and exactly which implementation it represents.  A
standard reference stays fail-closed until its isolated dependency environment,
source archive hash, and adapter are frozen; similar repository-native code may
never silently stand in for that reference.
"""

from __future__ import annotations

from types import MappingProxyType
from typing import Annotated, Final, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.benchmarking.contracts import canonical_sha256

MethodClassification = Literal[
    "standard_reference",
    "adapted_reference",
    "product_native",
    "product_inspired",
]
MethodReadiness = Literal["ready", "blocked"]
EnvironmentBoundary = Literal[
    "product_runtime",
    "isolated_benchmark",
    "provider_contract",
]
LicenseStatus = Literal["verified", "inherited_project", "unverified"]
BlockerCode = Literal[
    "adapter_not_implemented",
    "compatibility_unverified",
    "isolated_environment_missing",
    "license_unverified",
    "provider_contract_pending",
    "source_archive_hash_pending",
    "version_unresolved",
]


class _FrozenStrict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class BenchmarkMethodSourceV1(_FrozenStrict):
    """One implementation or dependency source without claiming installation."""

    schema_id: Literal["dronedream.benchmark-method-source/v1"] = (
        "dronedream.benchmark-method-source/v1"
    )
    source_id: Annotated[str, Field(min_length=1, max_length=128)]
    source_kind: Literal[
        "project_source",
        "python_package",
        "upstream_repository",
        "upstream_documentation",
    ]
    locator: Annotated[str, Field(min_length=1, max_length=1024)]
    version_candidate: Annotated[str, Field(min_length=1, max_length=128)] | None = None
    dependency_name: Annotated[str, Field(min_length=1, max_length=128)] | None = None
    license_status: LicenseStatus
    license_spdx: Annotated[str, Field(min_length=1, max_length=64)] | None = None
    license_locator: Annotated[str, Field(min_length=1, max_length=1024)] | None = None

    @model_validator(mode="after")
    def _validate_source_claim(self) -> BenchmarkMethodSourceV1:
        if self.locator.startswith("http://") or (
            self.license_locator is not None and self.license_locator.startswith("http://")
        ):
            raise ValueError("benchmark source locators must use HTTPS")
        if self.license_status in {"verified", "inherited_project"}:
            if self.license_spdx is None or self.license_locator is None:
                raise ValueError("verified licenses require SPDX and a license locator")
        elif self.license_spdx is not None:
            raise ValueError("unverified licenses cannot declare an SPDX identifier")
        if self.source_kind == "python_package" and self.dependency_name is None:
            raise ValueError("python package sources require dependency_name")
        return self


class BenchmarkMethodInventoryEntryV1(_FrozenStrict):
    schema_id: Literal["dronedream.benchmark-method-inventory-entry/v1"] = (
        "dronedream.benchmark-method-inventory-entry/v1"
    )
    adapter_id: Annotated[str, Field(pattern=r"^[a-z0-9][a-z0-9._/-]{0,127}$")]
    method_classification: MethodClassification
    implementation_label: Annotated[str, Field(min_length=1, max_length=255)]
    execution_readiness: MethodReadiness
    environment_boundary: EnvironmentBoundary
    sources: tuple[BenchmarkMethodSourceV1, ...] = Field(min_length=1, max_length=16)
    blocker_codes: tuple[BlockerCode, ...] = ()
    reproducibility_notes: tuple[Annotated[str, Field(min_length=1, max_length=512)], ...] = ()

    @model_validator(mode="after")
    def _validate_readiness(self) -> BenchmarkMethodInventoryEntryV1:
        if self.execution_readiness == "ready" and self.blocker_codes:
            raise ValueError("ready benchmark methods cannot retain blockers")
        if self.execution_readiness == "blocked" and not self.blocker_codes:
            raise ValueError("blocked benchmark methods require explicit blocker codes")
        if len(self.blocker_codes) != len(set(self.blocker_codes)):
            raise ValueError("benchmark method blocker codes must be unique")
        if any(source.license_status == "unverified" for source in self.sources):
            if "license_unverified" not in self.blocker_codes:
                raise ValueError("unverified source licenses require license_unverified")
            if self.execution_readiness != "blocked":
                raise ValueError("a method with an unverified license cannot execute")
        return self


_PROJECT_LICENSE_LOCATOR: Final = "LICENSE"


def _project_source(
    source_id: str,
    locator: str,
) -> BenchmarkMethodSourceV1:
    return BenchmarkMethodSourceV1(
        source_id=source_id,
        source_kind="project_source",
        locator=locator,
        version_candidate="repository-subject-commit",
        license_status="inherited_project",
        license_spdx="MIT",
        license_locator=_PROJECT_LICENSE_LOCATOR,
    )


def _ready_project(
    adapter_id: str,
    implementation_label: str,
    classification: MethodClassification,
    locator: str,
) -> BenchmarkMethodInventoryEntryV1:
    return BenchmarkMethodInventoryEntryV1(
        adapter_id=adapter_id,
        method_classification=classification,
        implementation_label=implementation_label,
        execution_readiness="ready",
        environment_boundary="product_runtime",
        sources=(_project_source(adapter_id.replace("/", "-"), locator),),
    )


_ENTRIES = (
    _ready_project(
        "random_search/v1",
        "stdlib-sha256-uniform-v1",
        "standard_reference",
        "backend/app/benchmarking/adapters.py",
    ),
    _ready_project(
        "seeded_halton/v1",
        "native-seed-offset-halton-v1",
        "standard_reference",
        "backend/app/benchmarking/adapters.py",
    ),
    _ready_project(
        "true_lhs/v1",
        "native-seeded-lhs-v1",
        "standard_reference",
        "backend/app/benchmarking/adapters.py",
    ),
    BenchmarkMethodInventoryEntryV1(
        adapter_id="bipop_cma_es/v1",
        method_classification="standard_reference",
        implementation_label="pycma-bipop-reference-adapter-pending",
        execution_readiness="blocked",
        environment_boundary="isolated_benchmark",
        sources=(
            BenchmarkMethodSourceV1(
                source_id="pycma-r4.4.4",
                source_kind="python_package",
                locator="https://github.com/CMA-ES/pycma/tree/r4.4.4",
                version_candidate="4.4.4",
                dependency_name="cma",
                license_status="verified",
                license_spdx="BSD-3-Clause",
                license_locator="https://github.com/CMA-ES/pycma/blob/r4.4.4/LICENSE",
            ),
        ),
        blocker_codes=(
            "adapter_not_implemented",
            "isolated_environment_missing",
            "source_archive_hash_pending",
        ),
        reproducibility_notes=(
            "The repository BIPOP-inspired implementation is a separate product arm.",
        ),
    ),
    BenchmarkMethodInventoryEntryV1(
        adapter_id="optuna_tpe/v1",
        method_classification="standard_reference",
        implementation_label="optuna-multivariate-tpe-reference-adapter-pending",
        execution_readiness="blocked",
        environment_boundary="isolated_benchmark",
        sources=(
            BenchmarkMethodSourceV1(
                source_id="optuna-v4.9.0",
                source_kind="python_package",
                locator="https://github.com/optuna/optuna/tree/v4.9.0",
                version_candidate="4.9.0",
                dependency_name="optuna",
                license_status="verified",
                license_spdx="MIT",
                license_locator="https://github.com/optuna/optuna/blob/v4.9.0/LICENSE",
            ),
            BenchmarkMethodSourceV1(
                source_id="optuna-tpe-4.9.0-docs",
                source_kind="upstream_documentation",
                locator=(
                    "https://optuna.readthedocs.io/en/stable/reference/samplers/"
                    "generated/optuna.samplers.TPESampler.html"
                ),
                version_candidate="4.9.0",
                license_status="verified",
                license_spdx="MIT",
                license_locator="https://github.com/optuna/optuna/blob/v4.9.0/LICENSE",
            ),
        ),
        blocker_codes=(
            "adapter_not_implemented",
            "isolated_environment_missing",
            "source_archive_hash_pending",
        ),
        reproducibility_notes=(
            "Freeze TPESampler(multivariate=True, seed=...) and sequential n_jobs=1.",
            "Unsafe, failed, and indeterminate trials cannot receive fabricated losses.",
        ),
    ),
    _ready_project(
        "repo_constrained_mobo/v1",
        "native-matern52-ard-gp",
        "product_native",
        "backend/app/optimization/bayesian_optimizers.py",
    ),
    BenchmarkMethodInventoryEntryV1(
        adapter_id="reference_turbo/v1",
        method_classification="standard_reference",
        implementation_label="botorch-turbo-reference-adapter-pending",
        execution_readiness="blocked",
        environment_boundary="isolated_benchmark",
        sources=(
            BenchmarkMethodSourceV1(
                source_id="botorch-v0.17.0-turbo",
                source_kind="python_package",
                locator="https://github.com/meta-pytorch/botorch/tree/v0.17.0",
                version_candidate="0.17.0",
                dependency_name="botorch",
                license_status="verified",
                license_spdx="MIT",
                license_locator=("https://github.com/meta-pytorch/botorch/blob/v0.17.0/LICENSE"),
            ),
        ),
        blocker_codes=(
            "adapter_not_implemented",
            "isolated_environment_missing",
            "source_archive_hash_pending",
        ),
        reproducibility_notes=(
            "The repository native_turbo implementation remains a product-inspired arm.",
        ),
    ),
    BenchmarkMethodInventoryEntryV1(
        adapter_id="reference_scbo/v1",
        method_classification="standard_reference",
        implementation_label="botorch-scbo-reference-adapter-pending",
        execution_readiness="blocked",
        environment_boundary="isolated_benchmark",
        sources=(
            BenchmarkMethodSourceV1(
                source_id="botorch-v0.17.0-scbo",
                source_kind="python_package",
                locator="https://github.com/meta-pytorch/botorch/tree/v0.17.0",
                version_candidate="0.17.0",
                dependency_name="botorch",
                license_status="verified",
                license_spdx="MIT",
                license_locator=("https://github.com/meta-pytorch/botorch/blob/v0.17.0/LICENSE"),
            ),
        ),
        blocker_codes=(
            "adapter_not_implemented",
            "isolated_environment_missing",
            "source_archive_hash_pending",
        ),
    ),
    BenchmarkMethodInventoryEntryV1(
        adapter_id="hebo/v1",
        method_classification="standard_reference",
        implementation_label="hebo-reference-adapter-pending",
        execution_readiness="blocked",
        environment_boundary="isolated_benchmark",
        sources=(
            BenchmarkMethodSourceV1(
                source_id="huawei-noah-hebo",
                source_kind="upstream_repository",
                locator="https://github.com/huawei-noah/HEBO",
                dependency_name="hebo",
                license_status="unverified",
            ),
        ),
        blocker_codes=(
            "adapter_not_implemented",
            "compatibility_unverified",
            "isolated_environment_missing",
            "license_unverified",
            "source_archive_hash_pending",
            "version_unresolved",
        ),
        reproducibility_notes=(
            "The repository root does not establish a verified license for the HEBO subtree.",
            "Mixed-domain, constraint, Python, and NumPy compatibility remain unresolved.",
        ),
    ),
    _ready_project(
        "optimizer_portfolio/v1",
        "native-deterministic-portfolio",
        "product_native",
        "backend/app/optimization/portfolio_optimizer.py",
    ),
    _ready_project(
        "repo_turbo_inspired/v1",
        "native-turbo-matern52-ard-gp",
        "product_inspired",
        "backend/app/optimization/bayesian_optimizers.py",
    ),
    _ready_project(
        "repo_bipop_cma_inspired/v1",
        "numpy-full-covariance-bipop-inspired",
        "product_inspired",
        "backend/app/optimization/cma_optimizers.py",
    ),
    _ready_project(
        "repo_surrogate_cma/v1",
        "numpy-full-covariance-cma-rbf",
        "product_native",
        "backend/app/optimization/cma_optimizers.py",
    ),
    BenchmarkMethodInventoryEntryV1(
        adapter_id="llm_direct/v1",
        method_classification="adapted_reference",
        implementation_label="durable-chat-completions-direct-v1",
        execution_readiness="ready",
        environment_boundary="provider_contract",
        sources=(
            _project_source(
                "llm-direct-durable-runtime",
                "backend/app/benchmarking/llm_durable_runtime.py",
            ),
            _project_source(
                "llm-direct-job-secret-transport",
                "backend/app/benchmarking/provider_transport.py",
            ),
            _project_source(
                "llm-direct-job-dispatch",
                "backend/app/orchestration/job_manager.py",
            ),
        ),
        reproducibility_notes=(
            "One durable direct proposal turn and one actual request per generation.",
            "The transport uses one same-Job encrypted BYOK slot and never an environment key.",
            "Formal execution requires zero provider retries and preregistered provider capacity.",
        ),
    ),
    BenchmarkMethodInventoryEntryV1(
        adapter_id="llm_react/v1",
        method_classification="adapted_reference",
        implementation_label="durable-bounded-react-v1",
        execution_readiness="ready",
        environment_boundary="provider_contract",
        sources=(
            _project_source(
                "llm-react-durable-runtime",
                "backend/app/benchmarking/llm_durable_runtime.py",
            ),
            _project_source(
                "llm-react-closed-contract",
                "backend/app/benchmarking/llm_arm_contracts.py",
            ),
            _project_source(
                "llm-react-job-secret-transport",
                "backend/app/benchmarking/provider_transport.py",
            ),
        ),
        reproducibility_notes=(
            "One to four durable action turns per generation with one request per turn.",
            "Only allowlisted deterministic local proposal adapters may be invoked.",
            "Every successful turn checkpoints validated state before the next turn.",
            "Formal execution requires zero provider retries and preregistered capacity.",
        ),
    ),
    BenchmarkMethodInventoryEntryV1(
        adapter_id="llambo_uav/v1",
        method_classification="adapted_reference",
        implementation_label="durable-noisy-constrained-uav-llambo-adaptation-v1",
        execution_readiness="ready",
        environment_boundary="provider_contract",
        sources=(
            _project_source(
                "llambo-uav-durable-runtime",
                "backend/app/benchmarking/llm_durable_runtime.py",
            ),
            _project_source(
                "llambo-uav-closed-contract",
                "backend/app/benchmarking/llm_arm_contracts.py",
            ),
            _project_source(
                "llambo-uav-job-secret-transport",
                "backend/app/benchmarking/provider_transport.py",
            ),
        ),
        reproducibility_notes=(
            "One durable proposal turn and one actual request per generation.",
            "Uses the shared holdout-free UAV observation under noisy constrained BO instructions.",
            (
                "This is a DroneDream UAV adaptation and is not claimed as a standard "
                "LLAMBO reproduction."
            ),
            "The transport uses one same-Job encrypted BYOK slot with zero provider retries.",
        ),
    ),
    BenchmarkMethodInventoryEntryV1(
        adapter_id="dronedream_fixed_two_turn/v1",
        method_classification="product_native",
        implementation_label="durable-fixed-plan-revision-v1",
        execution_readiness="ready",
        environment_boundary="provider_contract",
        sources=(
            _project_source(
                "fixed-two-turn-durable-runtime",
                "backend/app/benchmarking/llm_durable_runtime.py",
            ),
            _project_source(
                "fixed-two-turn-closed-contract",
                "backend/app/benchmarking/llm_arm_contracts.py",
            ),
            _project_source(
                "fixed-two-turn-job-secret-transport",
                "backend/app/benchmarking/provider_transport.py",
            ),
        ),
        reproducibility_notes=(
            "Exactly two durable provider turns per generation: plan, then revision.",
            "The plan invokes one or two allowlisted deterministic local proposal tools.",
            "Revision may dispatch only an existing proposal reference or abandon.",
            "Local tools add no provider requests; provider retries remain zero.",
        ),
    ),
    BenchmarkMethodInventoryEntryV1(
        adapter_id="dronedream_adaptive_1_4/v1",
        method_classification="product_native",
        implementation_label="durable-adaptive-one-four-v1",
        execution_readiness="ready",
        environment_boundary="provider_contract",
        sources=(
            _project_source(
                "adaptive-durable-runtime",
                "backend/app/benchmarking/llm_durable_runtime.py",
            ),
            _project_source(
                "adaptive-trigger-policy",
                "backend/app/benchmarking/adaptive_triggers.py",
            ),
            _project_source(
                "adaptive-closed-contract",
                "backend/app/benchmarking/llm_arm_contracts.py",
            ),
            _project_source(
                "adaptive-job-secret-transport",
                "backend/app/benchmarking/provider_transport.py",
            ),
        ),
        reproducibility_notes=(
            "One or two provider turns by default, with a hard four-turn ceiling.",
            "Optional diagnosis and critic turns require deterministic versioned triggers.",
            "Diagnosis may only keep, replace with an existing proposal, or abandon.",
            "Critic may only approve the current proposal or veto; retries remain zero.",
            "Durable checkpoints prevent paid provider-turn replay after interruption.",
        ),
    ),
)

BENCHMARK_METHOD_INVENTORY = MappingProxyType({entry.adapter_id: entry for entry in _ENTRIES})
if len(BENCHMARK_METHOD_INVENTORY) != len(_ENTRIES):
    raise RuntimeError("duplicate adapter_id in benchmark method inventory")

BENCHMARK_METHOD_INVENTORY_SHA256: Final = canonical_sha256(
    [
        BENCHMARK_METHOD_INVENTORY[adapter_id].model_dump(mode="json")
        for adapter_id in sorted(BENCHMARK_METHOD_INVENTORY)
    ]
)


def require_method_inventory_entry(adapter_id: str) -> BenchmarkMethodInventoryEntryV1:
    try:
        return BENCHMARK_METHOD_INVENTORY[adapter_id]
    except KeyError as exc:
        raise ValueError(f"benchmark adapter has no method inventory: {adapter_id}") from exc


def require_execution_ready_method(adapter_id: str) -> BenchmarkMethodInventoryEntryV1:
    entry = require_method_inventory_entry(adapter_id)
    if entry.execution_readiness != "ready":
        blockers = ",".join(entry.blocker_codes)
        raise ValueError(f"benchmark method is blocked: {adapter_id} ({blockers})")
    return entry


__all__ = [
    "BENCHMARK_METHOD_INVENTORY",
    "BENCHMARK_METHOD_INVENTORY_SHA256",
    "BenchmarkMethodInventoryEntryV1",
    "BenchmarkMethodSourceV1",
    "require_execution_ready_method",
    "require_method_inventory_entry",
]
