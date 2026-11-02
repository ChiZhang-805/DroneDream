"""Fail-closed contracts for the BoTorch TuRBO and SCBO reference arms.

BoTorch publishes the reference algorithms as versioned tutorial recipes, not
as one stable ``TuRBO`` or ``SCBO`` adapter class.  These contracts freeze the
upstream bytes and the parts of those recipes that matter to a fair benchmark.
They intentionally do not import BoTorch, fit a model, or emit a candidate.

The product benchmark currently dispatches one candidate per generation while
the frozen tutorials demonstrate batch-size four.  That difference is kept as
an explicit blocker instead of silently relabelling a sequential adaptation as
the upstream reference.
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

BOTORCH_REFERENCE_CONTRACT_SCHEMA_ID: Final = "dronedream.benchmark-botorch-reference-contract/v1"
BOTORCH_TURBO_POLICY_VERSION: Final = "botorch-0.17.0-turbo1-ts-tutorial-contract-v1"
BOTORCH_SCBO_POLICY_VERSION: Final = "botorch-0.17.0-scbo-ts-tutorial-contract-v1"


class _StrictFrozen(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class BoTorchDistributionLockV1(_StrictFrozen):
    schema_id: Literal["dronedream.benchmark-botorch-distribution-lock/v1"] = (
        "dronedream.benchmark-botorch-distribution-lock/v1"
    )
    package_name: Literal["botorch"] = "botorch"
    package_version: Literal["0.17.0"] = "0.17.0"
    python_requires: Literal[">=3.11"] = ">=3.11"
    upstream_tag: Literal["v0.17.0"] = "v0.17.0"
    upstream_commit: Literal["1855320f0bbef1766b5a010ebaad6253e8cf072b"] = (
        "1855320f0bbef1766b5a010ebaad6253e8cf072b"
    )
    wheel_filename: Literal["botorch-0.17.0-py3-none-any.whl"] = "botorch-0.17.0-py3-none-any.whl"
    wheel_sha256: Literal["fb8610cbf43a48746aa5935141b12063723abf0f8c353132cfcd9757703d02c2"] = (
        "fb8610cbf43a48746aa5935141b12063723abf0f8c353132cfcd9757703d02c2"
    )
    wheel_bytes: Literal[4562423] = 4_562_423
    sdist_filename: Literal["botorch-0.17.0.tar.gz"] = "botorch-0.17.0.tar.gz"
    sdist_sha256: Literal["32e5c3ee99504b909d3a495e35c0b193566a5851e6a50e761b67338d11086749"] = (
        "32e5c3ee99504b909d3a495e35c0b193566a5851e6a50e761b67338d11086749"
    )
    sdist_bytes: Literal[3745790] = 3_745_790
    minimum_dependencies: tuple[
        Literal["torch>=2.2"],
        Literal["gpytorch>=1.15.1"],
        Literal["linear_operator>=0.6"],
        Literal["pyro-ppl>=1.8.4"],
    ] = (
        "torch>=2.2",
        "gpytorch>=1.15.1",
        "linear_operator>=0.6",
        "pyro-ppl>=1.8.4",
    )
    transitive_dependency_lock_complete: Literal[False] = False
    license_spdx: Literal["MIT"] = "MIT"
    license_url: Literal["https://github.com/meta-pytorch/botorch/blob/v0.17.0/LICENSE"] = (
        "https://github.com/meta-pytorch/botorch/blob/v0.17.0/LICENSE"
    )


class BoTorchReferencePolicyV1(_StrictFrozen):
    schema_id: Literal["dronedream.benchmark-botorch-reference-policy/v1"] = (
        "dronedream.benchmark-botorch-reference-policy/v1"
    )
    adapter_id: Literal["reference_turbo/v1", "reference_scbo/v1"]
    policy_version: Literal[
        "botorch-0.17.0-turbo1-ts-tutorial-contract-v1",
        "botorch-0.17.0-scbo-ts-tutorial-contract-v1",
    ]
    tutorial_url: Literal[
        "https://botorch.org/docs/v0.17.0/tutorials/turbo_1",
        "https://botorch.org/docs/v0.17.0/tutorials/scalable_constrained_bo",
    ]
    recipe_name: Literal["TuRBO-1", "SCBO"]
    candidate_strategy: Literal["max-posterior-sampling"] = "max-posterior-sampling"
    normalized_bounds: tuple[float, float] = (0.0, 1.0)
    tutorial_batch_size: Literal[4] = 4
    product_proposal_batch_size: Literal[1] = 1
    batch_semantics_resolved: Literal[False] = False
    initial_design_policy: Literal["2*dimension", "tutorial-fixed-10-for-10d"]
    trust_region_initial_length: Annotated[float, Field(gt=0.0)] = 0.8
    trust_region_minimum_length: Annotated[float, Field(gt=0.0)] = 0.5**7
    trust_region_maximum_length: Annotated[float, Field(gt=0.0)] = 1.6
    success_tolerance: Literal[10] = 10
    failure_tolerance_formula: Literal["ceil(max(4/batch_size,dimension/batch_size))"] = (
        "ceil(max(4/batch_size,dimension/batch_size))"
    )
    candidate_pool_formula: Literal["min(5000,max(2000,200*dimension))"] = (
        "min(5000,max(2000,200*dimension))"
    )
    objective_transform: Literal["negate-frozen-minimization-loss-for-maximization"] = (
        "negate-frozen-minimization-loss-for-maximization"
    )
    constraints_modelled: bool
    constraint_sign_convention: Literal["violation<=0-feasible"] | None
    external_hard_gate_policy: Literal["all-campaign-hard-gates-remain-authoritative"] = (
        "all-campaign-hard-gates-remain-authoritative"
    )
    completed_objective_policy: Literal["real-objective-only"] = "real-objective-only"
    failed_trial_policy: Literal["excluded-from-fit-competing-event-no-fabricated-target"] = (
        "excluded-from-fit-competing-event-no-fabricated-target"
    )
    pending_trial_policy: Literal["reject-until-terminal"] = "reject-until-terminal"
    holdout_visibility: Literal["sealed"] = "sealed"
    provider_access: Literal[False] = False

    @model_validator(mode="after")
    def _validate_recipe(self) -> BoTorchReferencePolicyV1:
        expected = {
            "reference_turbo/v1": (
                BOTORCH_TURBO_POLICY_VERSION,
                "TuRBO-1",
                "https://botorch.org/docs/v0.17.0/tutorials/turbo_1",
                "2*dimension",
                False,
                None,
            ),
            "reference_scbo/v1": (
                BOTORCH_SCBO_POLICY_VERSION,
                "SCBO",
                "https://botorch.org/docs/v0.17.0/tutorials/scalable_constrained_bo",
                "tutorial-fixed-10-for-10d",
                True,
                "violation<=0-feasible",
            ),
        }[self.adapter_id]
        actual = (
            self.policy_version,
            self.recipe_name,
            self.tutorial_url,
            self.initial_design_policy,
            self.constraints_modelled,
            self.constraint_sign_convention,
        )
        if actual != expected:
            raise ValueError("BoTorch recipe fields do not match the frozen adapter")
        if self.normalized_bounds != (0.0, 1.0):
            raise ValueError("BoTorch reference bounds must remain normalized")
        if (
            self.trust_region_initial_length,
            self.trust_region_minimum_length,
            self.trust_region_maximum_length,
        ) != (0.8, 0.5**7, 1.6):
            raise ValueError("BoTorch trust-region lengths differ from the frozen tutorial")
        return self


BOTORCH_DISTRIBUTION_LOCK: Final = BoTorchDistributionLockV1()
BOTORCH_DISTRIBUTION_LOCK_SHA256: Final = canonical_sha256(BOTORCH_DISTRIBUTION_LOCK)
BOTORCH_TURBO_POLICY: Final = BoTorchReferencePolicyV1(
    adapter_id="reference_turbo/v1",
    policy_version=BOTORCH_TURBO_POLICY_VERSION,
    tutorial_url="https://botorch.org/docs/v0.17.0/tutorials/turbo_1",
    recipe_name="TuRBO-1",
    initial_design_policy="2*dimension",
    constraints_modelled=False,
    constraint_sign_convention=None,
)
BOTORCH_TURBO_POLICY_SHA256: Final = canonical_sha256(BOTORCH_TURBO_POLICY)
BOTORCH_SCBO_POLICY: Final = BoTorchReferencePolicyV1(
    adapter_id="reference_scbo/v1",
    policy_version=BOTORCH_SCBO_POLICY_VERSION,
    tutorial_url="https://botorch.org/docs/v0.17.0/tutorials/scalable_constrained_bo",
    recipe_name="SCBO",
    initial_design_policy="tutorial-fixed-10-for-10d",
    constraints_modelled=True,
    constraint_sign_convention="violation<=0-feasible",
)
BOTORCH_SCBO_POLICY_SHA256: Final = canonical_sha256(BOTORCH_SCBO_POLICY)


class BoTorchPreparedReferenceContractV1(_StrictFrozen):
    schema_id: Literal["dronedream.benchmark-botorch-reference-contract/v1"] = (
        BOTORCH_REFERENCE_CONTRACT_SCHEMA_ID
    )
    adapter_id: Literal["reference_turbo/v1", "reference_scbo/v1"]
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
    completed_objective_observations: Annotated[int, Field(ge=0, le=10_000)]
    infeasible_objective_observations: Annotated[int, Field(ge=0, le=10_000)]
    excluded_without_objective_observations: Annotated[int, Field(ge=0, le=10_000)]
    terminal_history_observations: Annotated[int, Field(ge=0, le=10_000)]
    maximum_new_trials: Annotated[int, Field(ge=1)]
    tutorial_batch_size: Literal[4] = 4
    product_proposal_batch_size: Literal[1] = 1
    batch_semantics_resolved: Literal[False] = False
    required_runtime_symbols: tuple[str, str]
    blocker_codes: tuple[
        Literal["isolated-environment-missing"],
        Literal["reference-adapter-missing"],
        Literal["sequential-batch-semantics-unresolved"],
        Literal["transitive-dependency-lock-missing"],
    ] = (
        "isolated-environment-missing",
        "reference-adapter-missing",
        "sequential-batch-semantics-unresolved",
        "transitive-dependency-lock-missing",
    )
    binding_sha256: Sha256Hex

    @model_validator(mode="after")
    def _validate_binding(self) -> BoTorchPreparedReferenceContractV1:
        if self.infeasible_objective_observations > self.completed_objective_observations:
            raise ValueError("infeasible observations cannot exceed completed objectives")
        if (
            self.completed_objective_observations + self.excluded_without_objective_observations
            != self.terminal_history_observations
        ):
            raise ValueError("BoTorch history counts do not cover every terminal observation")
        expected_policy_sha = (
            BOTORCH_TURBO_POLICY_SHA256
            if self.adapter_id == "reference_turbo/v1"
            else BOTORCH_SCBO_POLICY_SHA256
        )
        expected_symbols = (
            ("botorch.models.SingleTaskGP", "botorch.generation.MaxPosteriorSampling")
            if self.adapter_id == "reference_turbo/v1"
            else (
                "botorch.models.SingleTaskGP",
                "botorch.generation.sampling.ConstrainedMaxPosteriorSampling",
            )
        )
        if self.distribution_lock_sha256 != BOTORCH_DISTRIBUTION_LOCK_SHA256:
            raise ValueError("BoTorch distribution lock differs from the frozen source")
        if self.policy_sha256 != expected_policy_sha:
            raise ValueError("BoTorch policy hash differs from the selected adapter")
        if self.upstream_commit != BOTORCH_DISTRIBUTION_LOCK.upstream_commit:
            raise ValueError("BoTorch upstream commit differs from the frozen source")
        if self.required_runtime_symbols != expected_symbols:
            raise ValueError("BoTorch runtime symbols differ from the selected adapter")
        payload = self.model_dump(mode="json", exclude={"binding_sha256"})
        if canonical_sha256(payload) != self.binding_sha256:
            raise ValueError("BoTorch prepared-contract binding hash does not match")
        return self


def _validate_objectives(observation: BenchmarkObservationV2) -> dict[str, str]:
    required = {"name", "direction"}
    allowed = {*required, "weight", "normalization", "target"}
    result: dict[str, str] = {}
    for item in observation.objectives:
        if not required.issubset(item) or set(item).difference(allowed):
            raise BenchmarkAdapterError("BoTorch objective specs are not normalized")
        name = item.get("name")
        direction = item.get("direction")
        if not isinstance(name, str) or not name or direction not in {"minimize", "maximize"}:
            raise BenchmarkAdapterError("BoTorch objective name or direction is invalid")
        if name in result:
            raise BenchmarkAdapterError("BoTorch objective names must be unique")
        result[name] = direction
    return result


def _constraint_names(observation: BenchmarkObservationV2) -> tuple[str, ...]:
    required = {"name", "operator", "threshold"}
    allowed = {*required, "hard", "penalty"}
    names: list[str] = []
    for item in observation.constraints:
        if not required.issubset(item) or set(item).difference(allowed):
            raise BenchmarkAdapterError("BoTorch constraint specs are not normalized")
        name = item.get("name")
        if not isinstance(name, str) or not name:
            raise BenchmarkAdapterError("BoTorch constraint names must be non-empty")
        names.append(name)
    if len(names) != len(set(names)):
        raise BenchmarkAdapterError("BoTorch constraint names must be unique")
    return tuple(names)


def _validate_history(
    observation: BenchmarkObservationV2,
    *,
    adapter_id: Literal["reference_turbo/v1", "reference_scbo/v1"],
) -> tuple[int, int, int]:
    space = search_space_from_observation(observation)
    expected_parameters = set(space.baseline())
    objective_directions = _validate_objectives(observation)
    objective_names = set(objective_directions)
    constraint_names = set(_constraint_names(observation))
    ordinals = [item.dispatch_ordinal for item in observation.history]
    if ordinals != sorted(ordinals) or len(ordinals) != len(set(ordinals)):
        raise BenchmarkAdapterError("BoTorch history must use unique ascending dispatch ordinals")
    expected_next = ordinals[-1] + 1 if ordinals else 1
    if observation.next_dispatch_ordinal != expected_next:
        raise BenchmarkAdapterError("BoTorch history and next dispatch ordinal are not contiguous")
    refs = [item.candidate_ref for item in observation.history]
    if len(refs) != len(set(refs)):
        raise BenchmarkAdapterError("BoTorch history candidate references must be unique")

    completed = 0
    infeasible = 0
    excluded = 0
    for item in observation.history:
        if item.screening_status == "pending":
            raise BenchmarkAdapterError("BoTorch sequential contract rejects pending history")
        if set(item.parameters) != expected_parameters:
            raise BenchmarkAdapterError("BoTorch history requires every frozen parameter")
        if space.project(item.parameters) != item.parameters:
            raise BenchmarkAdapterError("BoTorch history parameters must satisfy the domain")
        outcome = item.outcome
        if outcome.role == "objective":
            if set(outcome.objectives) != objective_names:
                raise BenchmarkAdapterError("BoTorch history objective names differ from the spec")
            if outcome.objective_directions != objective_directions:
                raise BenchmarkAdapterError(
                    "BoTorch history objective directions differ from the spec"
                )
            if set(outcome.constraint_violations) != constraint_names:
                raise BenchmarkAdapterError(
                    "BoTorch history constraint values differ from the spec"
                )
            completed += 1
            infeasible += int(not outcome.feasible)
        else:
            excluded += 1
            if (
                adapter_id == "reference_scbo/v1"
                and outcome.role == "constraint_only"
                and set(outcome.constraint_violations) != constraint_names
            ):
                raise BenchmarkAdapterError(
                    "SCBO constraint-only history differs from the constraint spec"
                )
    return completed, infeasible, excluded


def prepare_botorch_reference_contract(
    observation: BenchmarkObservationV2,
    adapter_id: Literal["reference_turbo/v1", "reference_scbo/v1"],
) -> BoTorchPreparedReferenceContractV1:
    """Compile a deterministic non-executable reference-recipe contract."""

    if observation.simulator_budget_remaining < 1 or observation.wall_time_remaining_ms < 1:
        raise BenchmarkAdapterError("BoTorch reference requires remaining run budget")
    space = search_space_from_observation(observation)
    unsupported = tuple(
        item.name
        for item in space.tunable
        if item.value_type != "float" or item.step is not None or item.choices
    )
    if unsupported:
        raise BenchmarkAdapterError(
            "BoTorch reference v1 supports only continuous float domains: " + ", ".join(unsupported)
        )
    constraints = _constraint_names(observation)
    if adapter_id == "reference_scbo/v1" and not constraints:
        raise BenchmarkAdapterError("SCBO requires at least one frozen constraint")
    completed, infeasible, excluded = _validate_history(observation, adapter_id=adapter_id)
    policy = BOTORCH_TURBO_POLICY if adapter_id == "reference_turbo/v1" else BOTORCH_SCBO_POLICY
    policy_sha = (
        BOTORCH_TURBO_POLICY_SHA256
        if adapter_id == "reference_turbo/v1"
        else BOTORCH_SCBO_POLICY_SHA256
    )
    symbols = (
        ("botorch.models.SingleTaskGP", "botorch.generation.MaxPosteriorSampling")
        if adapter_id == "reference_turbo/v1"
        else (
            "botorch.models.SingleTaskGP",
            "botorch.generation.sampling.ConstrainedMaxPosteriorSampling",
        )
    )
    payload = {
        "schema_id": BOTORCH_REFERENCE_CONTRACT_SCHEMA_ID,
        "adapter_id": adapter_id,
        "status": "contract_only",
        "execution_authorized": False,
        "observation_sha256": canonical_sha256(observation),
        "distribution_lock_sha256": BOTORCH_DISTRIBUTION_LOCK_SHA256,
        "policy_sha256": policy_sha,
        "upstream_commit": BOTORCH_DISTRIBUTION_LOCK.upstream_commit,
        "parameter_domain_sha256": canonical_sha256(observation.parameter_domain),
        "objective_spec_sha256": canonical_sha256(observation.objectives),
        "constraint_spec_sha256": canonical_sha256(observation.constraints),
        "history_replay_sha256": canonical_sha256(
            [item.model_dump(mode="json") for item in observation.history]
        ),
        "dimensions": len(space.tunable),
        "algorithm_seed": observation.algorithm_seed % 4_294_967_296,
        "completed_objective_observations": completed,
        "infeasible_objective_observations": infeasible,
        "excluded_without_objective_observations": excluded,
        "terminal_history_observations": len(observation.history),
        "maximum_new_trials": observation.simulator_budget_remaining,
        "tutorial_batch_size": policy.tutorial_batch_size,
        "product_proposal_batch_size": policy.product_proposal_batch_size,
        "batch_semantics_resolved": policy.batch_semantics_resolved,
        "required_runtime_symbols": symbols,
        "blocker_codes": (
            "isolated-environment-missing",
            "reference-adapter-missing",
            "sequential-batch-semantics-unresolved",
            "transitive-dependency-lock-missing",
        ),
    }
    return BoTorchPreparedReferenceContractV1.model_validate(
        {**payload, "binding_sha256": canonical_sha256(payload)}
    )


__all__ = [
    "BOTORCH_DISTRIBUTION_LOCK",
    "BOTORCH_DISTRIBUTION_LOCK_SHA256",
    "BOTORCH_REFERENCE_CONTRACT_SCHEMA_ID",
    "BOTORCH_SCBO_POLICY",
    "BOTORCH_SCBO_POLICY_SHA256",
    "BOTORCH_SCBO_POLICY_VERSION",
    "BOTORCH_TURBO_POLICY",
    "BOTORCH_TURBO_POLICY_SHA256",
    "BOTORCH_TURBO_POLICY_VERSION",
    "BoTorchDistributionLockV1",
    "BoTorchPreparedReferenceContractV1",
    "BoTorchReferencePolicyV1",
    "prepare_botorch_reference_contract",
]
