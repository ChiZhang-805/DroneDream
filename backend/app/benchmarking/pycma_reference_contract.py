"""Fail-closed contract for the standard pycma BIPOP reference arm.

The repository already contains a product-inspired BIPOP-like optimizer.  It is
not equivalent to pycma's official restart coordinator.  This module freezes
the upstream distribution and the exact coordinator semantics that a later
isolated runtime must implement.  It deliberately does not import ``cma`` or
authorize execution.
"""

from __future__ import annotations

from typing import Annotated, Final, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.benchmarking.adapters import BenchmarkAdapterError, search_space_from_observation
from app.benchmarking.contracts import (
    BenchmarkObservationV2,
    GitCommit,
    Sha256Hex,
    canonical_sha256,
)

PYCMA_BIPOP_CONTRACT_SCHEMA_ID: Final = "dronedream.benchmark-pycma-bipop-contract/v1"
PYCMA_BIPOP_POLICY_VERSION: Final = "pycma-4.4.4-fmin2-bipop-v1"


class _StrictFrozen(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class PycmaDistributionLockV1(_StrictFrozen):
    schema_id: Literal["dronedream.benchmark-pycma-distribution-lock/v1"] = (
        "dronedream.benchmark-pycma-distribution-lock/v1"
    )
    package_name: Literal["cma"] = "cma"
    package_version: Literal["4.4.4"] = "4.4.4"
    upstream_tag: Literal["r4.4.4"] = "r4.4.4"
    upstream_commit: Literal["83089d1d681165b8cc849f4a05c9f1c1869d79a3"] = (
        "83089d1d681165b8cc849f4a05c9f1c1869d79a3"
    )
    wheel_filename: Literal["cma-4.4.4-py3-none-any.whl"] = "cma-4.4.4-py3-none-any.whl"
    wheel_sha256: Literal["edb6d02eb2aac2d54650f16a8f0c70711ff17445957de7c9de92ff7fd4b7ef38"] = (
        "edb6d02eb2aac2d54650f16a8f0c70711ff17445957de7c9de92ff7fd4b7ef38"
    )
    sdist_filename: Literal["cma-4.4.4.tar.gz"] = "cma-4.4.4.tar.gz"
    sdist_sha256: Literal["632bd654b5dce04c0eaa3166679d3e4773ce7a79eab7934e7f363c341b9a8170"] = (
        "632bd654b5dce04c0eaa3166679d3e4773ce7a79eab7934e7f363c341b9a8170"
    )
    license_spdx: Literal["BSD-3-Clause"] = "BSD-3-Clause"
    license_url: Literal["https://github.com/CMA-ES/pycma/blob/r4.4.4/LICENSE"] = (
        "https://github.com/CMA-ES/pycma/blob/r4.4.4/LICENSE"
    )


class PycmaBipopPolicyV1(_StrictFrozen):
    schema_id: Literal["dronedream.benchmark-pycma-bipop-policy/v1"] = (
        "dronedream.benchmark-pycma-bipop-policy/v1"
    )
    policy_version: Literal["pycma-4.4.4-fmin2-bipop-v1"] = PYCMA_BIPOP_POLICY_VERSION
    coordinator_api: Literal["cma.fmin2"] = "cma.fmin2"
    execution_mode: Literal["isolated-objective-callback-coordinator"] = (
        "isolated-objective-callback-coordinator"
    )
    bipop: Literal[True] = True
    restarts: Literal[9] = 9
    initial_sigma_unit: Annotated[float, Field(gt=0.0, le=1.0)] = 0.25
    normalized_bounds: tuple[float, float] = (0.0, 1.0)
    initial_mean_policy: Literal["seeded-callable-per-restart"] = "seeded-callable-per-restart"
    candidate_evaluation_policy: Literal["sequential-single-evaluator"] = (
        "sequential-single-evaluator"
    )
    provider_access: Literal[False] = False
    provider_retries: Literal[0] = 0
    holdout_visibility: Literal["sealed"] = "sealed"
    failed_trial_policy: Literal["competing-terminal-event-no-fabricated-fitness"] = (
        "competing-terminal-event-no-fabricated-fitness"
    )
    unsafe_trial_policy: Literal["competing-terminal-event-no-fabricated-fitness"] = (
        "competing-terminal-event-no-fabricated-fitness"
    )
    one_candidate_adapter_equivalent: Literal[False] = False
    filesystem_logging: Literal[False] = False
    console_verbosity: Literal[-9] = -9

    @model_validator(mode="after")
    def _freeze_numerical_policy(self) -> PycmaBipopPolicyV1:
        if self.initial_sigma_unit != 0.25:
            raise ValueError("pycma BIPOP initial sigma must match the frozen policy")
        if self.normalized_bounds != (0.0, 1.0):
            raise ValueError("pycma BIPOP bounds must match the frozen normalized domain")
        return self


PYCMA_DISTRIBUTION_LOCK: Final = PycmaDistributionLockV1()
PYCMA_DISTRIBUTION_LOCK_SHA256: Final = canonical_sha256(PYCMA_DISTRIBUTION_LOCK)
PYCMA_BIPOP_POLICY: Final = PycmaBipopPolicyV1()
PYCMA_BIPOP_POLICY_SHA256: Final = canonical_sha256(PYCMA_BIPOP_POLICY)


class PycmaBipopPreparedContractV1(_StrictFrozen):
    schema_id: Literal["dronedream.benchmark-pycma-bipop-contract/v1"] = (
        PYCMA_BIPOP_CONTRACT_SCHEMA_ID
    )
    adapter_id: Literal["bipop_cma_es/v1"] = "bipop_cma_es/v1"
    status: Literal["contract_only"] = "contract_only"
    execution_authorized: Literal[False] = False
    observation_sha256: Sha256Hex
    distribution_lock_sha256: Sha256Hex
    policy_sha256: Sha256Hex
    upstream_commit: GitCommit
    dimensions: Annotated[int, Field(ge=1, le=128)]
    initial_mean_unit: tuple[float, ...] = Field(min_length=1, max_length=128)
    algorithm_seed: Annotated[int, Field(ge=1, le=2_147_483_646)]
    maximum_objective_evaluations: Annotated[int, Field(ge=1)]
    required_runtime_symbols: tuple[
        Literal["cma.fmin2", "cma.CMAEvolutionStrategy"],
        Literal["cma.fmin2", "cma.CMAEvolutionStrategy"],
    ] = ("cma.fmin2", "cma.CMAEvolutionStrategy")
    blocker_codes: tuple[
        Literal["isolated-environment-missing", "objective-callback-coordinator-missing"],
        Literal["isolated-environment-missing", "objective-callback-coordinator-missing"],
    ] = ("isolated-environment-missing", "objective-callback-coordinator-missing")
    binding_sha256: Sha256Hex

    @model_validator(mode="after")
    def _validate_binding(self) -> PycmaBipopPreparedContractV1:
        if len(self.initial_mean_unit) != self.dimensions:
            raise ValueError("pycma initial mean dimension does not match the frozen domain")
        if any(not 0.0 <= value <= 1.0 for value in self.initial_mean_unit):
            raise ValueError("pycma initial mean must remain inside normalized bounds")
        payload = self.model_dump(mode="json", exclude={"binding_sha256"})
        if canonical_sha256(payload) != self.binding_sha256:
            raise ValueError("pycma prepared-contract binding hash does not match")
        return self


def prepare_pycma_bipop_contract(
    observation: BenchmarkObservationV2,
) -> PycmaBipopPreparedContractV1:
    """Compile a non-executable, content-addressed standard-reference contract."""

    if observation.generation_index != 1 or observation.next_dispatch_ordinal != 1:
        raise BenchmarkAdapterError("pycma BIPOP coordinator must own the run from generation one")
    if observation.history:
        raise BenchmarkAdapterError("pycma BIPOP coordinator cannot attach to pre-existing history")
    if observation.simulator_budget_remaining < 1 or observation.wall_time_remaining_ms < 1:
        raise BenchmarkAdapterError("pycma BIPOP coordinator requires remaining run budget")
    space = search_space_from_observation(observation)
    unsupported = tuple(
        item.name
        for item in space.tunable
        if item.value_type != "float" or item.step is not None or item.choices
    )
    if unsupported:
        raise BenchmarkAdapterError(
            "pycma BIPOP reference v1 supports only continuous float domains: "
            + ", ".join(unsupported)
        )
    initial_mean = tuple(space.to_unit_vector(space.baseline()))
    seed = int(observation.algorithm_seed % 2_147_483_646) + 1
    payload = {
        "schema_id": PYCMA_BIPOP_CONTRACT_SCHEMA_ID,
        "adapter_id": "bipop_cma_es/v1",
        "status": "contract_only",
        "execution_authorized": False,
        "observation_sha256": canonical_sha256(observation),
        "distribution_lock_sha256": PYCMA_DISTRIBUTION_LOCK_SHA256,
        "policy_sha256": PYCMA_BIPOP_POLICY_SHA256,
        "upstream_commit": PYCMA_DISTRIBUTION_LOCK.upstream_commit,
        "dimensions": len(initial_mean),
        "initial_mean_unit": initial_mean,
        "algorithm_seed": seed,
        "maximum_objective_evaluations": observation.simulator_budget_remaining,
        "required_runtime_symbols": ("cma.fmin2", "cma.CMAEvolutionStrategy"),
        "blocker_codes": (
            "isolated-environment-missing",
            "objective-callback-coordinator-missing",
        ),
    }
    return PycmaBipopPreparedContractV1.model_validate(
        {
            **payload,
            "binding_sha256": canonical_sha256(payload),
        }
    )


__all__ = [
    "PYCMA_BIPOP_CONTRACT_SCHEMA_ID",
    "PYCMA_BIPOP_POLICY",
    "PYCMA_BIPOP_POLICY_SHA256",
    "PYCMA_BIPOP_POLICY_VERSION",
    "PYCMA_DISTRIBUTION_LOCK",
    "PYCMA_DISTRIBUTION_LOCK_SHA256",
    "PycmaBipopPolicyV1",
    "PycmaBipopPreparedContractV1",
    "PycmaDistributionLockV1",
    "prepare_pycma_bipop_contract",
]
