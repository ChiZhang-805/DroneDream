"""Frozen contracts shared by every Model + Harness benchmark arm.

This module deliberately contains no provider or simulator implementation.  It
defines the only observation, proposal, and evaluation shapes that a registered
benchmark adapter may use.  Keeping those shapes server-side prevents campaign
scripts from granting one arm extra history, holdout outcomes, or simulator
budget through a temporary monkeypatch.
"""

from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime
from typing import Annotated, Any, Final, Literal, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field, model_validator

Sha256Hex = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
GitCommit = Annotated[str, Field(pattern=r"^[0-9a-f]{40}$")]
Identifier = Annotated[str, Field(pattern=r"^[a-z0-9][a-z0-9._/-]{0,127}$")]

BENCHMARK_OBSERVATION_SCHEMA_ID: Final[Literal["dronedream.benchmark-observation/v1"]] = (
    "dronedream.benchmark-observation/v1"
)
BENCHMARK_OBSERVATION_SCHEMA_ID_V2: Final[
    Literal["dronedream.benchmark-observation/v2"]
] = "dronedream.benchmark-observation/v2"
BENCHMARK_PROPOSAL_SCHEMA_ID: Final[Literal["dronedream.benchmark-proposal/v1"]] = (
    "dronedream.benchmark-proposal/v1"
)
BENCHMARK_EVALUATION_SCHEMA_ID: Final[Literal["dronedream.benchmark-evaluation/v1"]] = (
    "dronedream.benchmark-evaluation/v1"
)
BENCHMARK_EVALUATOR_CONTRACT_ID: Final[
    Literal["dronedream.candidate-evaluator/v1"]
] = "dronedream.candidate-evaluator/v1"

_SENSITIVE_KEYS = {
    "api_key",
    "authorization",
    "cookie",
    "password",
    "provider_request_id",
    "raw_chat",
    "raw_chat_history",
    "raw_prompt",
    "secret",
}


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


def _reject_sensitive_keys(value: object, *, path: str = "$") -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            normalized = str(key).strip().lower()
            if normalized in _SENSITIVE_KEYS:
                raise ValueError(
                    "sensitive field is forbidden in benchmark manifests: "
                    f"{path}.{key}"
                )
            _reject_sensitive_keys(item, path=f"{path}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _reject_sensitive_keys(item, path=f"{path}[{index}]")


def canonical_json_bytes(value: BaseModel | dict[str, Any] | list[Any]) -> bytes:
    """Serialize a contract deterministically for immutable SHA-256 bindings."""

    payload: object
    if isinstance(value, BaseModel):
        payload = value.model_dump(mode="json", exclude_none=False)
    else:
        payload = value
    _reject_sensitive_keys(payload)
    return json.dumps(
        payload,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def canonical_sha256(value: BaseModel | dict[str, Any] | list[Any]) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


class BenchmarkHistoryItemV1(_Strict):
    candidate_ref: Annotated[str, Field(min_length=1, max_length=128)]
    generation_index: Annotated[int, Field(ge=0)]
    dispatch_ordinal: Annotated[int, Field(ge=1)]
    parameters: dict[str, float]
    screening_status: Literal[
        "pending",
        "passed",
        "failed",
        "unsafe",
        "timeout",
        "indeterminate",
        "cancelled",
    ]
    metric_summary: dict[str, float | int | bool | None] = Field(default_factory=dict)
    failure_code: str | None = Field(default=None, max_length=128)


class BenchmarkObservationV1(_Strict):
    """Identical information boundary presented to every proposal arm.

    Qualification holdout outcomes are intentionally absent.  They may only be
    consumed by the sealed evaluator after candidate selection.
    """

    schema_id: Literal["dronedream.benchmark-observation/v1"] = (
        BENCHMARK_OBSERVATION_SCHEMA_ID
    )
    campaign_id: Annotated[str, Field(min_length=1, max_length=64)]
    run_id: Annotated[str, Field(min_length=1, max_length=64)]
    benchmark_arm_id: Identifier
    generation_index: Annotated[int, Field(ge=0)]
    next_dispatch_ordinal: Annotated[int, Field(ge=1)]
    algorithm_seed: int
    simulator_seed_block_id: Identifier
    parameter_domain: list[dict[str, Any]] = Field(min_length=1, max_length=64)
    objectives: list[dict[str, Any]] = Field(min_length=1, max_length=32)
    constraints: list[dict[str, Any]] = Field(default_factory=list, max_length=64)
    history: list[BenchmarkHistoryItemV1] = Field(default_factory=list, max_length=10_000)
    failure_semantics: dict[str, Any]
    simulator_budget_remaining: Annotated[int, Field(ge=0)]
    wall_time_remaining_ms: Annotated[int, Field(ge=0)]

    @model_validator(mode="after")
    def _exclude_sensitive_or_hidden_payloads(self) -> BenchmarkObservationV1:
        _reject_sensitive_keys(self.model_dump(mode="json"))
        return self


class BenchmarkProposalContextV1(_Strict):
    """Safe proposal provenance needed to reconstruct stateful local optimizers."""

    schema_id: Literal["dronedream.benchmark-proposal-context/v1"] = (
        "dronedream.benchmark-proposal-context/v1"
    )
    proposal_adapter_id: Identifier
    reason_code: Identifier
    proposal_receipt_sha256: Sha256Hex
    optimizer_strategy: Identifier | None = None
    optimizer_metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _bound_safe_metadata(self) -> BenchmarkProposalContextV1:
        payload = self.model_dump(mode="json")
        _reject_sensitive_keys(payload)
        if len(canonical_json_bytes(self.optimizer_metadata)) > 65_536:
            raise ValueError("optimizer_metadata exceeds 65536 UTF-8 bytes")
        return self


class BenchmarkOptimizerOutcomeV1(_Strict):
    """Structured learning outcome; failures never receive a fabricated loss."""

    schema_id: Literal["dronedream.benchmark-optimizer-outcome/v1"] = (
        "dronedream.benchmark-optimizer-outcome/v1"
    )
    role: Literal["objective", "constraint_only", "pending_reservation", "quarantined"]
    loss: float | None = None
    objectives: dict[str, float] = Field(default_factory=dict)
    objective_directions: dict[str, Literal["minimize", "maximize"]] = Field(
        default_factory=dict
    )
    constraint_violations: dict[str, float] = Field(default_factory=dict)
    feasible: bool
    failure_rate: Annotated[float, Field(ge=0.0, le=1.0)]
    fidelity: Annotated[float, Field(gt=0.0, le=1.0)] = 1.0
    requested_fidelity: Annotated[float, Field(gt=0.0, le=1.0)] = 1.0
    completed: bool

    @model_validator(mode="after")
    def _validate_learning_semantics(self) -> BenchmarkOptimizerOutcomeV1:
        numeric_values = [
            *self.objectives.values(),
            *self.constraint_violations.values(),
            self.failure_rate,
            self.fidelity,
            self.requested_fidelity,
        ]
        if self.loss is not None:
            numeric_values.append(self.loss)
        if not all(math.isfinite(float(value)) for value in numeric_values):
            raise ValueError("optimizer outcome values must be finite")
        if any(value < 0.0 for value in self.constraint_violations.values()):
            raise ValueError("constraint_violations must be non-negative")
        if set(self.objectives) != set(self.objective_directions):
            raise ValueError("every objective requires exactly one direction")
        if self.role == "objective":
            if not self.completed or self.loss is None or not self.objectives:
                raise ValueError(
                    "objective outcomes must be completed with loss and objective values"
                )
        elif self.role == "constraint_only":
            if not self.completed or self.loss is not None or self.objectives:
                raise ValueError(
                    "constraint-only outcomes must be completed without objective values"
                )
            if self.feasible:
                raise ValueError("constraint-only outcomes cannot be feasible")
        elif self.role == "pending_reservation":
            if self.completed or self.loss is not None or self.objectives:
                raise ValueError(
                    "pending reservations must be incomplete without objective values"
                )
        elif not self.completed or self.loss is not None or self.objectives:
            raise ValueError(
                "quarantined outcomes must be completed without optimizer objective values"
            )
        return self


class BenchmarkHistoryItemV2(_Strict):
    candidate_ref: Annotated[str, Field(min_length=1, max_length=128)]
    generation_index: Annotated[int, Field(ge=0)]
    dispatch_ordinal: Annotated[int, Field(ge=1)]
    parameters: dict[str, float]
    screening_status: Literal[
        "pending",
        "passed",
        "failed",
        "unsafe",
        "timeout",
        "indeterminate",
        "cancelled",
    ]
    proposal_context: BenchmarkProposalContextV1 | None = None
    outcome: BenchmarkOptimizerOutcomeV1
    failure_code: str | None = Field(default=None, max_length=128)

    @model_validator(mode="after")
    def _validate_status_role(self) -> BenchmarkHistoryItemV2:
        if self.screening_status == "pending" and self.outcome.role != "pending_reservation":
            raise ValueError("pending history requires a pending_reservation outcome")
        if self.screening_status == "passed" and self.outcome.role != "objective":
            raise ValueError("passed history requires an objective outcome")
        if self.screening_status == "unsafe" and self.outcome.role != "constraint_only":
            raise ValueError("unsafe history requires a constraint_only outcome")
        if self.screening_status in {"indeterminate", "cancelled"} and (
            self.outcome.role != "quarantined"
        ):
            raise ValueError(
                "indeterminate and cancelled history must be quarantined from learning"
            )
        return self


class BenchmarkObservationV2(_Strict):
    """Executable observation with lossless, safe optimizer-history provenance."""

    schema_id: Literal["dronedream.benchmark-observation/v2"] = (
        BENCHMARK_OBSERVATION_SCHEMA_ID_V2
    )
    campaign_id: Annotated[str, Field(min_length=1, max_length=64)]
    run_id: Annotated[str, Field(min_length=1, max_length=64)]
    benchmark_arm_id: Identifier
    generation_index: Annotated[int, Field(ge=0)]
    next_dispatch_ordinal: Annotated[int, Field(ge=1)]
    algorithm_seed: int
    simulator_seed_block_id: Identifier
    parameter_domain: list[dict[str, Any]] = Field(min_length=1, max_length=64)
    objectives: list[dict[str, Any]] = Field(min_length=1, max_length=32)
    constraints: list[dict[str, Any]] = Field(default_factory=list, max_length=64)
    history: list[BenchmarkHistoryItemV2] = Field(default_factory=list, max_length=10_000)
    failure_semantics: dict[str, Any]
    simulator_budget_remaining: Annotated[int, Field(ge=0)]
    wall_time_remaining_ms: Annotated[int, Field(ge=0)]

    @model_validator(mode="after")
    def _exclude_sensitive_or_hidden_payloads(self) -> BenchmarkObservationV2:
        payload = self.model_dump(mode="json")
        _reject_sensitive_keys(payload)
        canonical_json_bytes(payload)
        return self


class BenchmarkProposalV1(_Strict):
    schema_id: Literal["dronedream.benchmark-proposal/v1"] = BENCHMARK_PROPOSAL_SCHEMA_ID
    candidate_ref: Annotated[str, Field(min_length=1, max_length=128)]
    parameters: dict[str, float] = Field(min_length=1, max_length=64)
    reason_code: Identifier
    proposal_receipt: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _exclude_sensitive_payloads(self) -> BenchmarkProposalV1:
        _reject_sensitive_keys(self.model_dump(mode="json"))
        return self


class BenchmarkEvaluationV1(_Strict):
    schema_id: Literal["dronedream.benchmark-evaluation/v1"] = (
        BENCHMARK_EVALUATION_SCHEMA_ID
    )
    evaluator_contract_id: Literal["dronedream.candidate-evaluator/v1"] = (
        BENCHMARK_EVALUATOR_CONTRACT_ID
    )
    candidate_ref: Annotated[str, Field(min_length=1, max_length=128)]
    status: Literal[
        "passed",
        "failed",
        "unsafe",
        "timeout",
        "indeterminate",
        "cancelled",
    ]
    completed_trials: Annotated[int, Field(ge=0)]
    attempted_trials: Annotated[int, Field(ge=0)]
    metric_summary: dict[str, float | int | bool | None] = Field(default_factory=dict)
    safety_gates_passed: bool
    evidence_complete: bool
    failure_code: str | None = Field(default=None, max_length=128)
    evidence_sha256: Sha256Hex

    @model_validator(mode="after")
    def _validate_counts(self) -> BenchmarkEvaluationV1:
        if self.completed_trials > self.attempted_trials:
            raise ValueError("completed_trials cannot exceed attempted_trials")
        return self


@runtime_checkable
class BenchmarkProposalAdapter(Protocol):
    @property
    def adapter_id(self) -> str:
        """Stable registry identifier for the immutable adapter implementation."""

        ...

    def propose(self, observation: BenchmarkObservationV2) -> BenchmarkProposalV1:
        """Return one bounded proposal without reading sealed holdout outcomes."""


@runtime_checkable
class BenchmarkCandidateEvaluator(Protocol):
    evaluator_contract_id: str

    def evaluate(self, proposal: BenchmarkProposalV1) -> BenchmarkEvaluationV1:
        """Evaluate one proposal under the campaign's shared simulator contract."""


class ExecutionComponentV1(_Strict):
    component_id: Annotated[str, Field(min_length=1, max_length=255)]
    version: Annotated[str, Field(min_length=1, max_length=255)]
    source_commit: GitCommit | None = None
    artifact_sha256: Sha256Hex | None = None
    manifest_sha256: Sha256Hex


class CompositeExecutionInventoryV1(_Strict):
    schema_id: Literal["dronedream.composite-execution-inventory/v1"] = (
        "dronedream.composite-execution-inventory/v1"
    )
    repository_subject_commit: GitCommit
    evaluator_subject_commit: GitCommit
    campaign_coordinator_subject_commit: GitCommit
    evidence_head_commit: GitCommit | None = None
    desktop: ExecutionComponentV1 | None = None
    runtime_base: ExecutionComponentV1
    engine_pack: ExecutionComponentV1
    px4: ExecutionComponentV1
    gazebo: ExecutionComponentV1
    prompt_registry_sha256: Sha256Hex
    response_schema_sha256: Sha256Hex
    tool_registry_sha256: Sha256Hex
    model_matrix_sha256: Sha256Hex
    machine_profile_sha256: Sha256Hex
    concurrency_profile_sha256: Sha256Hex


class BenchmarkFairnessContractV1(_Strict):
    schema_id: Literal["dronedream.benchmark-fairness/v1"] = (
        "dronedream.benchmark-fairness/v1"
    )
    observation_contract_sha256: Sha256Hex
    evaluator_contract_id: Literal["dronedream.candidate-evaluator/v1"] = (
        BENCHMARK_EVALUATOR_CONTRACT_ID
    )
    parameter_domain_sha256: Sha256Hex
    objective_contract_sha256: Sha256Hex
    constraint_contract_sha256: Sha256Hex
    history_contract_sha256: Sha256Hex
    failure_semantics_sha256: Sha256Hex
    simulator_budget_sha256: Sha256Hex
    qualification_rule_sha256: Sha256Hex
    scenario_manifest_sha256: Sha256Hex
    seed_block_manifest_sha256: Sha256Hex

    @model_validator(mode="after")
    def _require_unified_observation_contract(self) -> BenchmarkFairnessContractV1:
        if self.observation_contract_sha256 != BENCHMARK_OBSERVATION_CONTRACT_SHA256:
            raise ValueError("campaign must use the server's frozen observation contract")
        return self


class BenchmarkBudgetCapsV1(_Strict):
    schema_id: Literal["dronedream.benchmark-budget-caps/v1"] = (
        "dronedream.benchmark-budget-caps/v1"
    )
    jobs: Annotated[int, Field(ge=1, le=100_000)]
    trials: Annotated[int, Field(ge=1, le=10_000_000)]
    logical_turns: Annotated[int, Field(ge=0, le=1_000_000)]
    network_requests: Annotated[int, Field(ge=0, le=1_000_000)]
    input_utf8_bytes: Annotated[int, Field(ge=0, le=1_000_000_000_000)]
    output_utf8_bytes: Annotated[int, Field(ge=0, le=1_000_000_000_000)]
    provider_tokens: Annotated[int, Field(ge=0, le=10_000_000_000)]
    provider_cost_microusd: Annotated[int, Field(ge=0, le=1_000_000_000_000)]
    wall_time_seconds: Annotated[int, Field(ge=1, le=31_536_000)]
    disk_bytes: Annotated[int, Field(ge=1, le=10_000_000_000_000)]


class BenchmarkDependencyV1(_Strict):
    name: Annotated[str, Field(min_length=1, max_length=255)]
    version: Annotated[str, Field(min_length=1, max_length=255)]
    license_spdx: Annotated[str, Field(min_length=1, max_length=128)]
    source_sha256: Sha256Hex


class BenchmarkArmManifestV1(_Strict):
    schema_id: Literal["dronedream.benchmark-arm/v1"] = "dronedream.benchmark-arm/v1"
    benchmark_arm_id: Identifier
    arm_version: Annotated[str, Field(min_length=1, max_length=64)]
    arm_family: Literal["traditional", "llm_harness"]
    proposal_adapter_id: Identifier
    evaluator_contract_id: Literal["dronedream.candidate-evaluator/v1"] = (
        BENCHMARK_EVALUATOR_CONTRACT_ID
    )
    intervention: dict[str, Any] = Field(default_factory=dict)
    provider_contract_sha256: Sha256Hex | None = None
    dependencies: list[BenchmarkDependencyV1] = Field(default_factory=list, max_length=64)
    execution_enabled: bool = False

    @model_validator(mode="after")
    def _validate_arm_boundary(self) -> BenchmarkArmManifestV1:
        _reject_sensitive_keys(self.intervention)
        if self.arm_family == "llm_harness" and self.provider_contract_sha256 is None:
            raise ValueError("LLM/Harness arms require provider_contract_sha256")
        return self


class BenchmarkCampaignManifestV1(_Strict):
    schema_id: Literal["dronedream.benchmark-campaign/v1"] = (
        "dronedream.benchmark-campaign/v1"
    )
    campaign_key: Identifier
    campaign_version: Annotated[str, Field(min_length=1, max_length=64)]
    name: Annotated[str, Field(min_length=1, max_length=255)]
    panel: Literal["A", "B", "C", "engineering"]
    protocol_sha256: Sha256Hex
    generated_at: Annotated[datetime, Field(strict=False)]
    composite_execution_inventory: CompositeExecutionInventoryV1
    fairness: BenchmarkFairnessContractV1
    budget_caps: BenchmarkBudgetCapsV1
    arms: list[BenchmarkArmManifestV1] = Field(min_length=1, max_length=64)

    @model_validator(mode="after")
    def _validate_unique_arms(self) -> BenchmarkCampaignManifestV1:
        arm_ids = [arm.benchmark_arm_id for arm in self.arms]
        if len(arm_ids) != len(set(arm_ids)):
            raise ValueError("benchmark_arm_id values must be unique within a campaign")
        _reject_sensitive_keys(self.model_dump(mode="json"))
        return self


class BenchmarkCampaignCreateRequest(_Strict):
    manifest: BenchmarkCampaignManifestV1


class BenchmarkArmRecordV1(_Strict):
    id: str
    benchmark_arm_id: str
    arm_version: str
    arm_family: Literal["traditional", "llm_harness"]
    proposal_adapter_id: str
    evaluator_contract_id: str
    manifest_sha256: Sha256Hex
    execution_enabled: bool
    created_at: datetime


class BenchmarkCampaignRecordV1(_Strict):
    id: str
    campaign_key: str
    campaign_version: str
    name: str
    panel: Literal["A", "B", "C", "engineering"]
    status: Literal["PREREGISTERED", "ACTIVE", "COMPLETED", "FAILED", "CANCELLED"]
    control_version: Annotated[int, Field(ge=1)]
    protocol_sha256: Sha256Hex
    manifest_sha256: Sha256Hex
    composite_inventory_sha256: Sha256Hex
    budget_caps: BenchmarkBudgetCapsV1
    arms: list[BenchmarkArmRecordV1]
    preregistered_at: datetime
    created_at: datetime
    updated_at: datetime


class BenchmarkCoordinatorClaimRequestV1(_Strict):
    owner_id: Identifier
    lease_seconds: Annotated[int, Field(ge=5, le=300)] = 60


class BenchmarkCoordinatorLeaseV1(_Strict):
    campaign_id: str
    owner_id: str
    lease_token: Annotated[str, Field(min_length=32, max_length=256)]
    lease_generation: Annotated[int, Field(ge=1)]
    lease_expires_at: datetime


class BenchmarkCoordinatorRenewRequestV1(_Strict):
    lease_generation: Annotated[int, Field(ge=1)]
    lease_seconds: Annotated[int, Field(ge=5, le=300)] = 60


class BenchmarkCoordinatorReleaseRequestV1(_Strict):
    lease_generation: Annotated[int, Field(ge=1)]


class BenchmarkResourceVectorV1(_Strict):
    jobs: Annotated[int, Field(ge=0)] = 0
    trials: Annotated[int, Field(ge=0)] = 0
    logical_turns: Annotated[int, Field(ge=0)] = 0
    network_requests: Annotated[int, Field(ge=0)] = 0
    input_utf8_bytes: Annotated[int, Field(ge=0)] = 0
    output_utf8_bytes: Annotated[int, Field(ge=0)] = 0
    provider_tokens: Annotated[int, Field(ge=0)] = 0
    provider_cost_microusd: Annotated[int, Field(ge=0)] = 0
    wall_time_seconds: Annotated[int, Field(ge=0)] = 0
    disk_bytes: Annotated[int, Field(ge=0)] = 0


class BenchmarkUsageDeltaV1(BenchmarkResourceVectorV1):

    @model_validator(mode="after")
    def _require_consumed_resource(self) -> BenchmarkUsageDeltaV1:
        if not any(self.model_dump().values()):
            raise ValueError("a budget reservation must consume at least one resource")
        return self


class BenchmarkBudgetReservationRequestV1(_Strict):
    reservation_key: Identifier
    lease_generation: Annotated[int, Field(ge=1)]
    reason: Identifier
    usage: BenchmarkUsageDeltaV1


class BenchmarkBudgetReservationRecordV1(_Strict):
    id: str
    campaign_id: str
    reservation_key: str
    lease_generation: int
    reason: str
    reservation_sha256: Sha256Hex
    usage: BenchmarkUsageDeltaV1
    created_at: datetime


class BenchmarkCampaignUsageV1(_Strict):
    campaign_id: str
    status: Literal["PREREGISTERED", "ACTIVE", "COMPLETED", "FAILED", "CANCELLED"]
    caps: BenchmarkBudgetCapsV1
    used: BenchmarkResourceVectorV1
    remaining: BenchmarkResourceVectorV1
    lease_owner: str | None = None
    lease_generation: Annotated[int, Field(ge=0)]
    lease_expires_at: datetime | None = None


class BenchmarkRunBindingRequestV1(_Strict):
    run_key: Annotated[
        str,
        Field(pattern=r"^[a-z0-9][a-z0-9._/-]{0,95}$"),
    ]
    job_id: Annotated[str, Field(min_length=1, max_length=64)]
    benchmark_arm_id: Identifier
    arm_version: Annotated[str, Field(min_length=1, max_length=64)]
    algorithm_seed: Annotated[int, Field(ge=0, le=9_223_372_036_854_775_807)]
    simulator_seed_block: Identifier
    provider_randomness_policy: Literal[
        "not_applicable",
        "fixed_seed",
        "provider_managed",
    ]
    provider_seed: Annotated[
        int,
        Field(ge=0, le=9_223_372_036_854_775_807),
    ] | None = None

    @model_validator(mode="after")
    def _validate_provider_randomness(self) -> BenchmarkRunBindingRequestV1:
        if (self.provider_randomness_policy == "fixed_seed") != (
            self.provider_seed is not None
        ):
            raise ValueError("fixed_seed requires provider_seed and other policies forbid it")
        return self


class BenchmarkBatchBindingRequestV1(_Strict):
    schema_id: Literal["dronedream.benchmark-batch-binding/v1"] = (
        "dronedream.benchmark-batch-binding/v1"
    )
    binding_key: Annotated[
        str,
        Field(pattern=r"^[a-z0-9][a-z0-9._/-]{0,95}$"),
    ]
    lease_generation: Annotated[int, Field(ge=1)]
    batch_id: Annotated[str, Field(min_length=1, max_length=64)]
    runs: list[BenchmarkRunBindingRequestV1] = Field(min_length=1, max_length=50)

    @model_validator(mode="after")
    def _validate_unique_runs(self) -> BenchmarkBatchBindingRequestV1:
        run_keys = [run.run_key for run in self.runs]
        job_ids = [run.job_id for run in self.runs]
        if len(run_keys) != len(set(run_keys)):
            raise ValueError("run_key values must be unique within a Batch binding")
        if len(job_ids) != len(set(job_ids)):
            raise ValueError("job_id values must be unique within a Batch binding")
        return self


class BenchmarkRunBindingRecordV1(_Strict):
    id: str
    run_key: str
    job_id: str
    benchmark_arm_id: str
    arm_version: str
    run_ordinal: Annotated[int, Field(ge=1)]
    batch_run_ordinal: Annotated[int, Field(ge=1)]
    algorithm_seed: int
    simulator_seed_block: str
    provider_randomness_policy: Literal[
        "not_applicable",
        "fixed_seed",
        "provider_managed",
    ]
    provider_seed: int | None
    qualification_policy_version: str | None = None
    scenario_suite_sha256: Sha256Hex | None = None
    qualification_contract_sha256: Sha256Hex | None = None
    binding_sha256: Sha256Hex
    created_at: datetime


class BenchmarkBatchBindingRecordV1(_Strict):
    id: str
    campaign_id: str
    binding_key: str
    batch_id: str
    batch_ordinal: Annotated[int, Field(ge=1)]
    lease_generation: Annotated[int, Field(ge=1)]
    job_count: Annotated[int, Field(ge=1, le=50)]
    binding_sha256: Sha256Hex
    budget_reservation_id: str
    runs: list[BenchmarkRunBindingRecordV1]
    created_at: datetime


# The hash is derived from the actual server-side schema rather than a hand-kept
# string, so a shape change necessarily changes every campaign fairness binding.
BENCHMARK_OBSERVATION_V1_CONTRACT_SHA256 = canonical_sha256(
    BenchmarkObservationV1.model_json_schema()
)
BENCHMARK_OBSERVATION_CONTRACT_SHA256 = canonical_sha256(
    BenchmarkObservationV2.model_json_schema()
)


__all__ = [
    "BENCHMARK_EVALUATOR_CONTRACT_ID",
    "BENCHMARK_OBSERVATION_CONTRACT_SHA256",
    "BENCHMARK_OBSERVATION_V1_CONTRACT_SHA256",
    "BenchmarkArmManifestV1",
    "BenchmarkBudgetCapsV1",
    "BenchmarkBatchBindingRecordV1",
    "BenchmarkBatchBindingRequestV1",
    "BenchmarkCampaignManifestV1",
    "BenchmarkCampaignCreateRequest",
    "BenchmarkCampaignRecordV1",
    "BenchmarkCampaignUsageV1",
    "BenchmarkCoordinatorClaimRequestV1",
    "BenchmarkCoordinatorLeaseV1",
    "BenchmarkCoordinatorReleaseRequestV1",
    "BenchmarkCoordinatorRenewRequestV1",
    "BenchmarkCandidateEvaluator",
    "BenchmarkEvaluationV1",
    "BenchmarkFairnessContractV1",
    "BenchmarkHistoryItemV2",
    "BenchmarkObservationV1",
    "BenchmarkObservationV2",
    "BenchmarkOptimizerOutcomeV1",
    "BenchmarkProposalContextV1",
    "BenchmarkProposalAdapter",
    "BenchmarkProposalV1",
    "BenchmarkArmRecordV1",
    "BenchmarkBudgetReservationRecordV1",
    "BenchmarkBudgetReservationRequestV1",
    "BenchmarkResourceVectorV1",
    "BenchmarkRunBindingRecordV1",
    "BenchmarkRunBindingRequestV1",
    "BenchmarkUsageDeltaV1",
    "CompositeExecutionInventoryV1",
    "ExecutionComponentV1",
    "canonical_json_bytes",
    "canonical_sha256",
]
