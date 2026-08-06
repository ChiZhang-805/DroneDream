"""Fail-closed contract for the standard HEBO 0.3.6 reference arm.

The PyPI wheel is frozen, but it is intentionally not imported into the
product environment.  HEBO's core optimizer consumes one finite scalar loss
and does not implement constraint modelling.  The later isolated adapter must
therefore replay only real feasible objective observations, keep every failed
or unsafe trial in benchmark accounting, advance the Sobol stream for every
dispatched candidate, and never invent a penalty merely to satisfy ``observe``.
"""

from __future__ import annotations

from typing import Annotated, Final, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.benchmarking.adapters import BenchmarkAdapterError, search_space_from_observation
from app.benchmarking.contracts import BenchmarkObservationV2, Sha256Hex, canonical_sha256

HEBO_CONTRACT_SCHEMA_ID: Final = "dronedream.benchmark-hebo-contract/v1"
HEBO_POLICY_VERSION: Final = "hebo-0.3.6-sequential-scalar-v1"


class _StrictFrozen(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class HeboDistributionLockV1(_StrictFrozen):
    schema_id: Literal["dronedream.benchmark-hebo-distribution-lock/v1"] = (
        "dronedream.benchmark-hebo-distribution-lock/v1"
    )
    package_name: Literal["HEBO"] = "HEBO"
    package_version: Literal["0.3.6"] = "0.3.6"
    wheel_filename: Literal["HEBO-0.3.6-py3-none-any.whl"] = (
        "HEBO-0.3.6-py3-none-any.whl"
    )
    wheel_size_bytes: Literal[114720] = 114720
    wheel_sha256: Literal[
        "f3d46a106205eac5340822e5ad1aeb389109ea302dfe35f17d24e69c7c1d0665"
    ] = "f3d46a106205eac5340822e5ad1aeb389109ea302dfe35f17d24e69c7c1d0665"
    wheel_url: Literal[
        "https://files.pythonhosted.org/packages/46/21/62d5e593b2b38cc1d2f148e89ad072fe973a3584492eab2d0c47c7b8c8e8/HEBO-0.3.6-py3-none-any.whl"
    ] = (
        "https://files.pythonhosted.org/packages/46/21/"
        "62d5e593b2b38cc1d2f148e89ad072fe973a3584492eab2d0c47c7b8c8e8/"
        "HEBO-0.3.6-py3-none-any.whl"
    )
    wheel_metadata_path: Literal["HEBO-0.3.6.dist-info/METADATA"] = (
        "HEBO-0.3.6.dist-info/METADATA"
    )
    wheel_license_path: Literal["HEBO-0.3.6.dist-info/LICENSE"] = (
        "HEBO-0.3.6.dist-info/LICENSE"
    )
    source_distribution_available: Literal[False] = False
    license_spdx: Literal["MIT"] = "MIT"
    license_url: Literal["https://pypi.org/project/HEBO/0.3.6/"] = (
        "https://pypi.org/project/HEBO/0.3.6/"
    )
    requires_dist: tuple[str, ...] = (
        "numpy<1.25,>=1.16",
        "pandas>=1.0.1",
        "torch>=1.9.0",
        "pymoo==0.6.0",
        "scikit-learn>=0.22",
        "gpytorch>=1.4.0",
        "GPy>=1.9.9",
        "catboost>=0.24.4",
        "disjoint-set",
    )


class HeboSequentialScalarPolicyV1(_StrictFrozen):
    schema_id: Literal["dronedream.benchmark-hebo-policy/v1"] = (
        "dronedream.benchmark-hebo-policy/v1"
    )
    policy_version: Literal["hebo-0.3.6-sequential-scalar-v1"] = HEBO_POLICY_VERSION
    optimizer_class: Literal["hebo.optimizers.hebo.HEBO"] = "hebo.optimizers.hebo.HEBO"
    design_space_class: Literal["hebo.design_space.design_space.DesignSpace"] = (
        "hebo.design_space.design_space.DesignSpace"
    )
    linear_parameter_mapping: Literal["num"] = "num"
    log_parameter_mapping: Literal["pow-base-10"] = "pow-base-10"
    n_suggestions: Literal[1] = 1
    sequential_max_in_flight: Literal[1] = 1
    model_name: Literal["gp"] = "gp"
    acquisition_class: Literal["MACE"] = "MACE"
    evolutionary_optimizer: Literal["nsga2"] = "nsga2"
    random_sample_count: Literal["1+dimensions"] = "1+dimensions"
    initial_design: Literal["scrambled-sobol"] = "scrambled-sobol"
    sobol_seed_source: Literal["algorithm_seed"] = "algorithm_seed"
    numpy_seed_source: Literal["algorithm_seed"] = "algorithm_seed"
    torch_seed_source: Literal["algorithm_seed"] = "algorithm_seed"
    replay_order: Literal["ascending-dispatch-ordinal"] = "ascending-dispatch-ordinal"
    sobol_replay_policy: Literal["fast-forward-all-dispatched-candidates"] = (
        "fast-forward-all-dispatched-candidates"
    )
    objective_value_source: Literal["BenchmarkOptimizerOutcomeV1.loss"] = (
        "BenchmarkOptimizerOutcomeV1.loss"
    )
    feasible_observation_mapping: Literal["observe-real-finite-loss"] = (
        "observe-real-finite-loss"
    )
    infeasible_observation_mapping: Literal["account-only-do-not-observe"] = (
        "account-only-do-not-observe"
    )
    failed_observation_mapping: Literal["account-only-no-fabricated-loss"] = (
        "account-only-no-fabricated-loss"
    )
    native_constraint_model: Literal[False] = False
    duplicate_guard_scope: Literal["all-dispatched-history"] = "all-dispatched-history"
    holdout_visibility: Literal["sealed"] = "sealed"
    provider_access: Literal[False] = False
    provider_retries: Literal[0] = 0


HEBO_DISTRIBUTION_LOCK: Final = HeboDistributionLockV1()
HEBO_DISTRIBUTION_LOCK_SHA256: Final = canonical_sha256(HEBO_DISTRIBUTION_LOCK)
HEBO_POLICY: Final = HeboSequentialScalarPolicyV1()
HEBO_POLICY_SHA256: Final = canonical_sha256(HEBO_POLICY)


class HeboPreparedContractV1(_StrictFrozen):
    schema_id: Literal["dronedream.benchmark-hebo-contract/v1"] = HEBO_CONTRACT_SCHEMA_ID
    adapter_id: Literal["hebo/v1"] = "hebo/v1"
    status: Literal["contract_only"] = "contract_only"
    execution_authorized: Literal[False] = False
    observation_sha256: Sha256Hex
    distribution_lock_sha256: Sha256Hex
    policy_sha256: Sha256Hex
    parameter_domain_sha256: Sha256Hex
    objective_spec_sha256: Sha256Hex
    constraint_spec_sha256: Sha256Hex
    history_replay_sha256: Sha256Hex
    feasible_observation_sha256: Sha256Hex
    excluded_outcome_sha256: Sha256Hex
    dimensions: Annotated[int, Field(ge=1, le=128)]
    algorithm_seed: Annotated[int, Field(ge=0, le=4_294_967_295)]
    next_trial_number: Annotated[int, Field(ge=0, le=10_000)]
    sobol_draws_consumed: Annotated[int, Field(ge=0, le=10_000)]
    feasible_objective_observations: Annotated[int, Field(ge=0, le=10_000)]
    infeasible_objective_outcomes: Annotated[int, Field(ge=0, le=10_000)]
    nonobjective_outcomes: Annotated[int, Field(ge=0, le=10_000)]
    maximum_new_trials: Annotated[int, Field(ge=1)]
    requires_isolated_numpy_lt_1_25: Literal[True] = True
    required_runtime_symbols: tuple[
        Literal[
            "hebo.design_space.design_space.DesignSpace",
            "hebo.optimizers.hebo.HEBO",
            "HEBO.sobol.fast_forward",
            "HEBO.suggest",
            "HEBO.observe",
        ],
        Literal[
            "hebo.design_space.design_space.DesignSpace",
            "hebo.optimizers.hebo.HEBO",
            "HEBO.sobol.fast_forward",
            "HEBO.suggest",
            "HEBO.observe",
        ],
        Literal[
            "hebo.design_space.design_space.DesignSpace",
            "hebo.optimizers.hebo.HEBO",
            "HEBO.sobol.fast_forward",
            "HEBO.suggest",
            "HEBO.observe",
        ],
        Literal[
            "hebo.design_space.design_space.DesignSpace",
            "hebo.optimizers.hebo.HEBO",
            "HEBO.sobol.fast_forward",
            "HEBO.suggest",
            "HEBO.observe",
        ],
        Literal[
            "hebo.design_space.design_space.DesignSpace",
            "hebo.optimizers.hebo.HEBO",
            "HEBO.sobol.fast_forward",
            "HEBO.suggest",
            "HEBO.observe",
        ],
    ] = (
        "hebo.design_space.design_space.DesignSpace",
        "hebo.optimizers.hebo.HEBO",
        "HEBO.sobol.fast_forward",
        "HEBO.suggest",
        "HEBO.observe",
    )
    blocker_codes: tuple[
        Literal["isolated-environment-missing", "runner-compatibility-unverified"],
        Literal["isolated-environment-missing", "runner-compatibility-unverified"],
    ] = ("isolated-environment-missing", "runner-compatibility-unverified")
    binding_sha256: Sha256Hex

    @model_validator(mode="after")
    def _validate_binding(self) -> HeboPreparedContractV1:
        if self.sobol_draws_consumed != self.next_trial_number:
            raise ValueError("HEBO Sobol replay must account for every dispatched candidate")
        if (
            self.feasible_objective_observations
            + self.infeasible_objective_outcomes
            + self.nonobjective_outcomes
            != self.next_trial_number
        ):
            raise ValueError("HEBO replay counts do not cover the frozen terminal history")
        payload = self.model_dump(mode="json", exclude={"binding_sha256"})
        if canonical_sha256(payload) != self.binding_sha256:
            raise ValueError("HEBO prepared-contract binding hash does not match")
        return self


def _validate_specs(
    observation: BenchmarkObservationV2,
) -> tuple[dict[str, Literal["minimize", "maximize"]], set[str]]:
    objective_directions: dict[str, Literal["minimize", "maximize"]] = {}
    for item in observation.objectives:
        if not {"name", "direction"} <= set(item) <= {
            "name",
            "direction",
            "weight",
            "normalization",
            "target",
        }:
            raise BenchmarkAdapterError("HEBO objective specs differ from the server contract")
        name = item.get("name")
        if not isinstance(name, str) or not name:
            raise BenchmarkAdapterError("HEBO objective names must be non-empty strings")
        direction = item.get("direction")
        if direction not in {"minimize", "maximize"}:
            raise BenchmarkAdapterError("HEBO objective directions are unsupported")
        if name in objective_directions:
            raise BenchmarkAdapterError("HEBO objective names must be unique")
        objective_directions[name] = direction

    constraint_names: list[str] = []
    for item in observation.constraints:
        if not {"name", "operator", "threshold"} <= set(item) <= {
            "name",
            "operator",
            "threshold",
            "hard",
            "penalty",
        }:
            raise BenchmarkAdapterError("HEBO constraint specs differ from the server contract")
        name = item.get("name")
        if not isinstance(name, str) or not name:
            raise BenchmarkAdapterError("HEBO constraint names must be non-empty strings")
        constraint_names.append(name)
    if len(constraint_names) != len(set(constraint_names)):
        raise BenchmarkAdapterError("HEBO constraint names must be unique")
    return objective_directions, set(constraint_names)


def _partition_history(
    observation: BenchmarkObservationV2,
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    space = search_space_from_observation(observation)
    expected_parameters = set(space.baseline())
    objective_directions, constraint_names = _validate_specs(observation)
    ordinals = [item.dispatch_ordinal for item in observation.history]
    if ordinals != sorted(ordinals) or len(ordinals) != len(set(ordinals)):
        raise BenchmarkAdapterError("HEBO history must use unique ascending dispatch ordinals")
    expected_next = ordinals[-1] + 1 if ordinals else 1
    if observation.next_dispatch_ordinal != expected_next:
        raise BenchmarkAdapterError("HEBO history and next dispatch ordinal are not contiguous")
    candidate_refs = [item.candidate_ref for item in observation.history]
    if len(candidate_refs) != len(set(candidate_refs)):
        raise BenchmarkAdapterError("HEBO history candidate references must be unique")

    feasible: list[dict[str, object]] = []
    excluded: list[dict[str, object]] = []
    for item in observation.history:
        if item.screening_status == "pending":
            raise BenchmarkAdapterError("HEBO sequential reference cannot propose while pending")
        if set(item.parameters) != expected_parameters:
            raise BenchmarkAdapterError("HEBO replay requires every frozen parameter value")
        if space.project(item.parameters) != item.parameters:
            raise BenchmarkAdapterError("HEBO replay parameters must already satisfy the domain")
        outcome = item.outcome
        if outcome.role == "objective":
            if set(outcome.objectives) != set(objective_directions):
                raise BenchmarkAdapterError("HEBO replay objective names differ from the spec")
            if outcome.objective_directions != objective_directions:
                raise BenchmarkAdapterError("HEBO replay objective directions differ from the spec")
            if set(outcome.constraint_violations) != constraint_names:
                raise BenchmarkAdapterError("HEBO replay constraint names differ from the spec")
        record = {
            "candidate_ref": item.candidate_ref,
            "dispatch_ordinal": item.dispatch_ordinal,
            "parameters": item.parameters,
            "screening_status": item.screening_status,
            "outcome": outcome.model_dump(mode="json"),
        }
        if outcome.role == "objective" and outcome.feasible:
            feasible.append(record)
        else:
            excluded.append(record)
    return feasible, excluded


def prepare_hebo_contract(observation: BenchmarkObservationV2) -> HeboPreparedContractV1:
    """Compile a non-executable, content-addressed HEBO replay contract."""

    if observation.simulator_budget_remaining < 1 or observation.wall_time_remaining_ms < 1:
        raise BenchmarkAdapterError("HEBO reference requires remaining run budget")
    feasible, excluded = _partition_history(observation)
    space = search_space_from_observation(observation)
    infeasible = sum(
        1
        for item in observation.history
        if item.outcome.role == "objective" and not item.outcome.feasible
    )
    nonobjective = len(observation.history) - len(feasible) - infeasible
    history_payload = [item.model_dump(mode="json") for item in observation.history]
    payload = {
        "schema_id": HEBO_CONTRACT_SCHEMA_ID,
        "adapter_id": "hebo/v1",
        "status": "contract_only",
        "execution_authorized": False,
        "observation_sha256": canonical_sha256(observation),
        "distribution_lock_sha256": HEBO_DISTRIBUTION_LOCK_SHA256,
        "policy_sha256": HEBO_POLICY_SHA256,
        "parameter_domain_sha256": canonical_sha256(observation.parameter_domain),
        "objective_spec_sha256": canonical_sha256(observation.objectives),
        "constraint_spec_sha256": canonical_sha256(observation.constraints),
        "history_replay_sha256": canonical_sha256(history_payload),
        "feasible_observation_sha256": canonical_sha256(feasible),
        "excluded_outcome_sha256": canonical_sha256(excluded),
        "dimensions": len(space.tunable),
        "algorithm_seed": int(observation.algorithm_seed % 2**32),
        "next_trial_number": len(observation.history),
        "sobol_draws_consumed": len(observation.history),
        "feasible_objective_observations": len(feasible),
        "infeasible_objective_outcomes": infeasible,
        "nonobjective_outcomes": nonobjective,
        "maximum_new_trials": observation.simulator_budget_remaining,
        "requires_isolated_numpy_lt_1_25": True,
        "required_runtime_symbols": (
            "hebo.design_space.design_space.DesignSpace",
            "hebo.optimizers.hebo.HEBO",
            "HEBO.sobol.fast_forward",
            "HEBO.suggest",
            "HEBO.observe",
        ),
        "blocker_codes": (
            "isolated-environment-missing",
            "runner-compatibility-unverified",
        ),
    }
    return HeboPreparedContractV1.model_validate(
        {**payload, "binding_sha256": canonical_sha256(payload)}
    )


__all__ = [
    "HEBO_CONTRACT_SCHEMA_ID",
    "HEBO_DISTRIBUTION_LOCK",
    "HEBO_DISTRIBUTION_LOCK_SHA256",
    "HEBO_POLICY",
    "HEBO_POLICY_SHA256",
    "HEBO_POLICY_VERSION",
    "HeboDistributionLockV1",
    "HeboPreparedContractV1",
    "HeboSequentialScalarPolicyV1",
    "prepare_hebo_contract",
]
