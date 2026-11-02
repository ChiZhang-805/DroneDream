"""Fail-closed contract for the standard Optuna multivariate-TPE arm.

The contract freezes package bytes and the exact ask/tell replay semantics for
the later isolated adapter.  It deliberately does not import Optuna or produce
a proposal.  Failed physical work remains visible to the benchmark accounting
but never receives a fabricated scalar objective merely to satisfy a sampler.
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

OPTUNA_TPE_CONTRACT_SCHEMA_ID: Final = "dronedream.benchmark-optuna-tpe-contract/v1"
OPTUNA_TPE_POLICY_VERSION: Final = "optuna-4.9.0-multivariate-tpe-v1"


class _StrictFrozen(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class OptunaDistributionLockV1(_StrictFrozen):
    schema_id: Literal["dronedream.benchmark-optuna-distribution-lock/v1"] = (
        "dronedream.benchmark-optuna-distribution-lock/v1"
    )
    package_name: Literal["optuna"] = "optuna"
    package_version: Literal["4.9.0"] = "4.9.0"
    upstream_tag: Literal["v4.9.0"] = "v4.9.0"
    upstream_commit: Literal["4db42e31c24b200e52595df9d4c00e2cdeefea2b"] = (
        "4db42e31c24b200e52595df9d4c00e2cdeefea2b"
    )
    wheel_filename: Literal["optuna-4.9.0-py3-none-any.whl"] = "optuna-4.9.0-py3-none-any.whl"
    wheel_sha256: Literal["f52f3be6148654850c92a5860d398fd88ec6b2c84ab68d9c3d07dcff02e7afee"] = (
        "f52f3be6148654850c92a5860d398fd88ec6b2c84ab68d9c3d07dcff02e7afee"
    )
    sdist_filename: Literal["optuna-4.9.0.tar.gz"] = "optuna-4.9.0.tar.gz"
    sdist_sha256: Literal["b322e5cbdf1655fb84c37646c4a7a1f391de1b47806bbe222e015825d0a82b87"] = (
        "b322e5cbdf1655fb84c37646c4a7a1f391de1b47806bbe222e015825d0a82b87"
    )
    license_spdx: Literal["MIT"] = "MIT"
    license_url: Literal["https://github.com/optuna/optuna/blob/v4.9.0/LICENSE"] = (
        "https://github.com/optuna/optuna/blob/v4.9.0/LICENSE"
    )
    third_party_notice_url: Literal[
        "https://github.com/optuna/optuna/blob/v4.9.0/LICENSE_THIRD_PARTY"
    ] = "https://github.com/optuna/optuna/blob/v4.9.0/LICENSE_THIRD_PARTY"
    third_party_notice_required: Literal[True] = True


class OptunaMultivariateTpePolicyV1(_StrictFrozen):
    schema_id: Literal["dronedream.benchmark-optuna-tpe-policy/v1"] = (
        "dronedream.benchmark-optuna-tpe-policy/v1"
    )
    policy_version: Literal["optuna-4.9.0-multivariate-tpe-v1"] = OPTUNA_TPE_POLICY_VERSION
    sampler_class: Literal["optuna.samplers.TPESampler"] = "optuna.samplers.TPESampler"
    coordinator_api: Literal["study-ask-tell-replay"] = "study-ask-tell-replay"
    storage: Literal["isolated-in-memory"] = "isolated-in-memory"
    multivariate: Literal[True] = True
    group: Literal[False] = False
    constant_liar: Literal[False] = False
    n_startup_trials: Literal[10] = 10
    n_ei_candidates: Literal[24] = 24
    sequential_max_in_flight: Literal[1] = 1
    objective_direction: Literal["minimize"] = "minimize"
    objective_value_source: Literal["BenchmarkOptimizerOutcomeV1.loss"] = (
        "BenchmarkOptimizerOutcomeV1.loss"
    )
    constraints_source: Literal["actual-nonnegative-violation-vector"] = (
        "actual-nonnegative-violation-vector"
    )
    complete_trial_mapping: Literal["completed-objective-with-real-loss"] = (
        "completed-objective-with-real-loss"
    )
    failed_trial_mapping: Literal["FAIL-without-values-no-fabricated-loss"] = (
        "FAIL-without-values-no-fabricated-loss"
    )
    pending_trial_policy: Literal["reject-proposal-until-terminal"] = (
        "reject-proposal-until-terminal"
    )
    holdout_visibility: Literal["sealed"] = "sealed"
    provider_access: Literal[False] = False
    provider_retries: Literal[0] = 0
    deprecated_sampler_arguments: tuple[()] = ()


OPTUNA_DISTRIBUTION_LOCK: Final = OptunaDistributionLockV1()
OPTUNA_DISTRIBUTION_LOCK_SHA256: Final = canonical_sha256(OPTUNA_DISTRIBUTION_LOCK)
OPTUNA_TPE_POLICY: Final = OptunaMultivariateTpePolicyV1()
OPTUNA_TPE_POLICY_SHA256: Final = canonical_sha256(OPTUNA_TPE_POLICY)


class OptunaTpePreparedContractV1(_StrictFrozen):
    schema_id: Literal["dronedream.benchmark-optuna-tpe-contract/v1"] = (
        OPTUNA_TPE_CONTRACT_SCHEMA_ID
    )
    adapter_id: Literal["optuna_tpe/v1"] = "optuna_tpe/v1"
    status: Literal["contract_only"] = "contract_only"
    execution_authorized: Literal[False] = False
    observation_sha256: Sha256Hex
    distribution_lock_sha256: Sha256Hex
    policy_sha256: Sha256Hex
    upstream_commit: GitCommit
    parameter_domain_sha256: Sha256Hex
    objective_spec_sha256: Sha256Hex
    constraint_spec_sha256: Sha256Hex
    history_replay_sha256: Sha256Hex
    dimensions: Annotated[int, Field(ge=1, le=128)]
    algorithm_seed: Annotated[int, Field(ge=0, le=4_294_967_295)]
    next_trial_number: Annotated[int, Field(ge=0, le=10_000)]
    completed_objective_trials: Annotated[int, Field(ge=0, le=10_000)]
    infeasible_objective_trials: Annotated[int, Field(ge=0, le=10_000)]
    failed_without_objective_trials: Annotated[int, Field(ge=0, le=10_000)]
    maximum_new_trials: Annotated[int, Field(ge=1)]
    required_runtime_symbols: tuple[
        Literal["optuna.create_study", "optuna.samplers.TPESampler", "study.ask", "study.tell"],
        Literal["optuna.create_study", "optuna.samplers.TPESampler", "study.ask", "study.tell"],
        Literal["optuna.create_study", "optuna.samplers.TPESampler", "study.ask", "study.tell"],
        Literal["optuna.create_study", "optuna.samplers.TPESampler", "study.ask", "study.tell"],
    ] = ("optuna.create_study", "optuna.samplers.TPESampler", "study.ask", "study.tell")
    blocker_codes: tuple[
        Literal["isolated-environment-missing", "ask-tell-adapter-missing"],
        Literal["isolated-environment-missing", "ask-tell-adapter-missing"],
    ] = ("isolated-environment-missing", "ask-tell-adapter-missing")
    binding_sha256: Sha256Hex

    @model_validator(mode="after")
    def _validate_binding(self) -> OptunaTpePreparedContractV1:
        if self.infeasible_objective_trials > self.completed_objective_trials:
            raise ValueError("infeasible Optuna trials cannot exceed completed objectives")
        if (
            self.completed_objective_trials + self.failed_without_objective_trials
            != self.next_trial_number
        ):
            raise ValueError("Optuna replay counts do not cover the frozen terminal history")
        payload = self.model_dump(mode="json", exclude={"binding_sha256"})
        if canonical_sha256(payload) != self.binding_sha256:
            raise ValueError("Optuna prepared-contract binding hash does not match")
        return self


def _validate_objective_spec(observation: BenchmarkObservationV2) -> None:
    required = {"name", "direction"}
    allowed = {*required, "weight", "normalization", "target"}
    names: list[str] = []
    for item in observation.objectives:
        if not required.issubset(item) or set(item).difference(allowed):
            raise BenchmarkAdapterError(
                "Optuna objective specs differ from the normalized server contract"
            )
        name = item.get("name")
        direction = item.get("direction")
        if not isinstance(name, str) or not name:
            raise BenchmarkAdapterError("Optuna objective names must be non-empty strings")
        if direction not in {"minimize", "maximize"}:
            raise BenchmarkAdapterError("Optuna objective directions must be minimize or maximize")
        names.append(name)
    if len(names) != len(set(names)):
        raise BenchmarkAdapterError("Optuna objective names must be unique")


def _constraint_names(observation: BenchmarkObservationV2) -> tuple[str, ...]:
    required = {"name", "operator", "threshold"}
    allowed = {*required, "hard", "penalty"}
    names: list[str] = []
    for item in observation.constraints:
        if not required.issubset(item) or set(item).difference(allowed):
            raise BenchmarkAdapterError(
                "Optuna constraint specs differ from the normalized server contract"
            )
        name = item.get("name")
        if not isinstance(name, str) or not name:
            raise BenchmarkAdapterError("Optuna constraint names must be non-empty strings")
        names.append(name)
    if len(names) != len(set(names)):
        raise BenchmarkAdapterError("Optuna constraint names must be unique")
    return tuple(names)


def _validate_history(observation: BenchmarkObservationV2) -> tuple[int, int, int]:
    space = search_space_from_observation(observation)
    expected_parameters = set(space.baseline())
    constraint_names = set(_constraint_names(observation))
    objective_directions = {
        item["name"]: item["direction"]
        for item in observation.objectives
        if isinstance(item.get("name"), str)
    }
    objective_names = set(objective_directions)
    dispatch_ordinals = [item.dispatch_ordinal for item in observation.history]
    if dispatch_ordinals != sorted(dispatch_ordinals) or len(dispatch_ordinals) != len(
        set(dispatch_ordinals)
    ):
        raise BenchmarkAdapterError("Optuna history must use unique ascending dispatch ordinals")
    expected_next_dispatch = dispatch_ordinals[-1] + 1 if dispatch_ordinals else 1
    if observation.next_dispatch_ordinal != expected_next_dispatch:
        raise BenchmarkAdapterError("Optuna history and next dispatch ordinal are not contiguous")
    candidate_refs = [item.candidate_ref for item in observation.history]
    if len(candidate_refs) != len(set(candidate_refs)):
        raise BenchmarkAdapterError("Optuna history candidate references must be unique")

    completed = 0
    infeasible = 0
    failed_without_objective = 0
    for item in observation.history:
        if item.screening_status == "pending":
            raise BenchmarkAdapterError(
                "Optuna sequential reference cannot propose while a trial is pending"
            )
        if set(item.parameters) != expected_parameters:
            raise BenchmarkAdapterError("Optuna replay requires every frozen parameter value")
        projected = space.project(item.parameters)
        if projected != item.parameters:
            raise BenchmarkAdapterError("Optuna replay parameters must already satisfy the domain")
        outcome = item.outcome
        if outcome.role == "objective":
            if set(outcome.objectives) != objective_names:
                raise BenchmarkAdapterError("Optuna replay objective names differ from the spec")
            if outcome.objective_directions != objective_directions:
                raise BenchmarkAdapterError(
                    "Optuna replay objective directions differ from the spec"
                )
            if set(outcome.constraint_violations) != constraint_names:
                raise BenchmarkAdapterError("Optuna replay constraint names differ from the spec")
            completed += 1
            infeasible += int(not outcome.feasible)
        else:
            failed_without_objective += 1
    return completed, infeasible, failed_without_objective


def prepare_optuna_tpe_contract(
    observation: BenchmarkObservationV2,
) -> OptunaTpePreparedContractV1:
    """Compile a non-executable, content-addressed Optuna replay contract."""

    if observation.simulator_budget_remaining < 1 or observation.wall_time_remaining_ms < 1:
        raise BenchmarkAdapterError("Optuna TPE reference requires remaining run budget")
    _validate_objective_spec(observation)
    completed, infeasible, failed_without_objective = _validate_history(observation)
    space = search_space_from_observation(observation)
    history_payload = [item.model_dump(mode="json") for item in observation.history]
    payload = {
        "schema_id": OPTUNA_TPE_CONTRACT_SCHEMA_ID,
        "adapter_id": "optuna_tpe/v1",
        "status": "contract_only",
        "execution_authorized": False,
        "observation_sha256": canonical_sha256(observation),
        "distribution_lock_sha256": OPTUNA_DISTRIBUTION_LOCK_SHA256,
        "policy_sha256": OPTUNA_TPE_POLICY_SHA256,
        "upstream_commit": OPTUNA_DISTRIBUTION_LOCK.upstream_commit,
        "parameter_domain_sha256": canonical_sha256(observation.parameter_domain),
        "objective_spec_sha256": canonical_sha256(observation.objectives),
        "constraint_spec_sha256": canonical_sha256(observation.constraints),
        "history_replay_sha256": canonical_sha256(history_payload),
        "dimensions": len(space.tunable),
        "algorithm_seed": int(observation.algorithm_seed % 2**32),
        "next_trial_number": len(observation.history),
        "completed_objective_trials": completed,
        "infeasible_objective_trials": infeasible,
        "failed_without_objective_trials": failed_without_objective,
        "maximum_new_trials": observation.simulator_budget_remaining,
        "required_runtime_symbols": (
            "optuna.create_study",
            "optuna.samplers.TPESampler",
            "study.ask",
            "study.tell",
        ),
        "blocker_codes": (
            "isolated-environment-missing",
            "ask-tell-adapter-missing",
        ),
    }
    return OptunaTpePreparedContractV1.model_validate(
        {
            **payload,
            "binding_sha256": canonical_sha256(payload),
        }
    )


__all__ = [
    "OPTUNA_DISTRIBUTION_LOCK",
    "OPTUNA_DISTRIBUTION_LOCK_SHA256",
    "OPTUNA_TPE_CONTRACT_SCHEMA_ID",
    "OPTUNA_TPE_POLICY",
    "OPTUNA_TPE_POLICY_SHA256",
    "OPTUNA_TPE_POLICY_VERSION",
    "OptunaDistributionLockV1",
    "OptunaMultivariateTpePolicyV1",
    "OptunaTpePreparedContractV1",
    "prepare_optuna_tpe_contract",
]
