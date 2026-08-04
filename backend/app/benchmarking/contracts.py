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
from datetime import datetime
from typing import Annotated, Any, Final, Literal, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field, model_validator

Sha256Hex = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
GitCommit = Annotated[str, Field(pattern=r"^[0-9a-f]{40}$")]
Identifier = Annotated[str, Field(pattern=r"^[a-z0-9][a-z0-9._/-]{0,127}$")]

BENCHMARK_OBSERVATION_SCHEMA_ID: Final[Literal["dronedream.benchmark-observation/v1"]] = (
    "dronedream.benchmark-observation/v1"
)
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
    adapter_id: str

    def propose(self, observation: BenchmarkObservationV1) -> BenchmarkProposalV1:
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


# The hash is derived from the actual server-side schema rather than a hand-kept
# string, so a shape change necessarily changes every campaign fairness binding.
BENCHMARK_OBSERVATION_CONTRACT_SHA256 = canonical_sha256(
    BenchmarkObservationV1.model_json_schema()
)


__all__ = [
    "BENCHMARK_EVALUATOR_CONTRACT_ID",
    "BENCHMARK_OBSERVATION_CONTRACT_SHA256",
    "BenchmarkArmManifestV1",
    "BenchmarkBudgetCapsV1",
    "BenchmarkCampaignManifestV1",
    "BenchmarkCampaignCreateRequest",
    "BenchmarkCampaignRecordV1",
    "BenchmarkCandidateEvaluator",
    "BenchmarkEvaluationV1",
    "BenchmarkFairnessContractV1",
    "BenchmarkObservationV1",
    "BenchmarkProposalAdapter",
    "BenchmarkProposalV1",
    "BenchmarkArmRecordV1",
    "CompositeExecutionInventoryV1",
    "ExecutionComponentV1",
    "canonical_json_bytes",
    "canonical_sha256",
]
