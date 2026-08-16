"""Fail-closed assessment for P5 zero-provider physical stability evidence."""

from __future__ import annotations

import json
import math
import os
import statistics
import tempfile
from collections import Counter
from pathlib import Path
from typing import Annotated, Literal, TypeAlias

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.benchmarking.contracts import GitCommit, Identifier, Sha256Hex, canonical_sha256
from app.benchmarking.physical_stability import (
    PhysicalStabilityManifestV1,
    PhysicalStabilityTrialPlanItemV1,
    PhysicalStabilityTrialPlanV1,
)

DifficultySignal: TypeAlias = Literal[
    "baseline_trivially_impossible",
    "graded",
    "baseline_trivially_saturated",
    "not_assessable",
]
FinalCandidateStatus: TypeAlias = Literal[
    "eligible_for_final_freeze", "replacement_required", "physical_contract_invalid"
]


class _StrictFrozen(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class PhysicalStabilityMetricsV1(_StrictFrozen):
    rmse: Annotated[float, Field(ge=0.0)]
    max_error: Annotated[float, Field(ge=0.0)]
    completion_time_seconds: Annotated[float, Field(ge=0.0)]
    pass_flag: bool
    crash_flag: bool
    timeout_flag: bool
    instability_flag: bool

    @model_validator(mode="after")
    def _validate_metrics(self) -> PhysicalStabilityMetricsV1:
        values = (self.rmse, self.max_error, self.completion_time_seconds)
        if not all(math.isfinite(value) for value in values):
            raise ValueError("physical stability metrics must be finite")
        if self.pass_flag and (self.crash_flag or self.timeout_flag or self.instability_flag):
            raise ValueError("an unsafe or incomplete trial cannot pass")
        return self


class PhysicalStabilityTrialObservationV1(_StrictFrozen):
    schema_id: Literal["dronedream.physical-stability-trial-observation/v1"] = (
        "dronedream.physical-stability-trial-observation/v1"
    )
    manifest_sha256: Sha256Hex
    plan_sha256: Sha256Hex
    repository_subject_commit: GitCommit
    composite_execution_inventory_sha256: Sha256Hex
    trial_id: Identifier
    scenario_id: Identifier
    seed: int
    attempt_count: Literal[1] = 1
    input_contract_sha256: Sha256Hex
    scenario_effect_request_sha256: Sha256Hex
    terminal_status: Literal["completed", "failed", "timeout", "cancelled", "indeterminate"]
    metrics: PhysicalStabilityMetricsV1 | None = None
    effect_request_applied: bool
    effect_readback_verified: bool
    parameter_readback_verified: bool
    telemetry_evidence_sha256: Sha256Hex | None = None
    metric_evidence_sha256: Sha256Hex | None = None
    artifact_inventory_sha256: Sha256Hex | None = None
    failure_code: Annotated[str, Field(min_length=1, max_length=128)] | None = None

    @model_validator(mode="after")
    def _validate_terminal_semantics(self) -> PhysicalStabilityTrialObservationV1:
        evidence = (
            self.telemetry_evidence_sha256,
            self.metric_evidence_sha256,
            self.artifact_inventory_sha256,
        )
        if self.terminal_status == "completed":
            if self.metrics is None or self.failure_code is not None:
                raise ValueError("completed observations require metrics and forbid failure_code")
            if not all(evidence):
                raise ValueError("completed observations require all evidence hashes")
        elif self.metrics is not None or self.failure_code is None:
            raise ValueError("non-completed observations require failure_code and forbid metrics")
        return self


class PhysicalStabilityScenarioAssessmentV1(_StrictFrozen):
    scenario_id: Identifier
    trial_count: Literal[10] = 10
    terminal_status_counts: dict[str, int]
    completed_count: Annotated[int, Field(ge=0, le=10)]
    pass_count: Annotated[int, Field(ge=0, le=10)]
    safety_critical_failure_count: Annotated[int, Field(ge=0, le=10)]
    effect_applied_and_read_back_count: Annotated[int, Field(ge=0, le=10)]
    parameter_readback_verified_count: Annotated[int, Field(ge=0, le=10)]
    complete_evidence_count: Annotated[int, Field(ge=0, le=10)]
    rmse_median: float | None
    rmse_normalized_mad: float | None
    max_error_median: float | None
    max_error_normalized_mad: float | None
    physical_contract_passed: bool
    repeatability_passed: bool
    difficulty_signal: DifficultySignal
    final_candidate_status: FinalCandidateStatus
    rejection_reasons: tuple[str, ...]


class PhysicalStabilityAssessmentV1(_StrictFrozen):
    schema_id: Literal["dronedream.physical-stability-assessment/v1"] = (
        "dronedream.physical-stability-assessment/v1"
    )
    manifest_sha256: Sha256Hex
    plan_sha256: Sha256Hex
    repository_subject_commit: GitCommit
    composite_execution_inventory_sha256: Sha256Hex
    evidence_scope: Literal["engineering_stability_only_not_comparative_not_report"] = (
        "engineering_stability_only_not_comparative_not_report"
    )
    provider_logical_turns_attempted: Literal[0] = 0
    provider_network_requests_attempted: Literal[0] = 0
    comparative_arm_outcomes_observed: Literal[False] = False
    trial_count: Literal[60] = 60
    terminal_status_counts: dict[str, int]
    scenarios: tuple[PhysicalStabilityScenarioAssessmentV1, ...]
    eligible_scenario_ids: tuple[Identifier, ...]
    all_failures_retained_in_denominator: Literal[True] = True
    pilot_selection_ready: bool
    all_preregistered_candidates_eligible: bool
    final_scenario_freeze_ready: Literal[False] = False


def _normalized_mad(values: list[float]) -> tuple[float, float]:
    median = float(statistics.median(values))
    mad = float(statistics.median(abs(value - median) for value in values))
    denominator = max(abs(median), 1e-9)
    return median, min(mad / denominator, 1_000_000_000.0)


def _expected_trial_map(
    plan: PhysicalStabilityTrialPlanV1,
) -> dict[str, PhysicalStabilityTrialPlanItemV1]:
    return {item.trial_id: item for item in plan.trials}


def _validate_observation_binding(
    *,
    manifest: PhysicalStabilityManifestV1,
    plan: PhysicalStabilityTrialPlanV1,
    observation: PhysicalStabilityTrialObservationV1,
    expected: PhysicalStabilityTrialPlanItemV1,
) -> None:
    manifest_sha = canonical_sha256(manifest)
    plan_sha = canonical_sha256(plan)
    expected_values = {
        "manifest_sha256": manifest_sha,
        "plan_sha256": plan_sha,
        "repository_subject_commit": plan.repository_subject_commit,
        "composite_execution_inventory_sha256": plan.composite_execution_inventory_sha256,
        "trial_id": expected.trial_id,
        "scenario_id": expected.scenario_id,
        "seed": expected.seed,
        "input_contract_sha256": expected.input_contract_sha256,
        "scenario_effect_request_sha256": expected.scenario_effect_request_sha256,
    }
    for field_name, expected_value in expected_values.items():
        if getattr(observation, field_name) != expected_value:
            raise ValueError(f"physical stability observation binding mismatch: {field_name}")


def _assess_scenario(
    scenario_id: str,
    observations: list[PhysicalStabilityTrialObservationV1],
) -> PhysicalStabilityScenarioAssessmentV1:
    status_counts = Counter(item.terminal_status for item in observations)
    completed = [item for item in observations if item.terminal_status == "completed"]
    metrics = [item.metrics for item in completed if item.metrics is not None]
    pass_count = sum(item.pass_flag for item in metrics)
    safety_failures = sum(
        item.crash_flag or item.timeout_flag or item.instability_flag for item in metrics
    ) + sum(item.terminal_status in {"timeout", "indeterminate"} for item in observations)
    effect_count = sum(
        item.effect_request_applied and item.effect_readback_verified for item in observations
    )
    parameter_readback_count = sum(item.parameter_readback_verified for item in observations)
    evidence_count = sum(
        bool(
            item.telemetry_evidence_sha256
            and item.metric_evidence_sha256
            and item.artifact_inventory_sha256
        )
        for item in observations
    )

    rmse_median: float | None
    rmse_mad: float | None
    max_error_median: float | None
    max_error_mad: float | None
    if metrics:
        rmse_median, rmse_mad = _normalized_mad([item.rmse for item in metrics])
        max_error_median, max_error_mad = _normalized_mad([item.max_error for item in metrics])
    else:
        rmse_median = rmse_mad = max_error_median = max_error_mad = None

    physical_contract_passed = (
        len(observations) == 10
        and len(completed) == 10
        and safety_failures == 0
        and effect_count == 10
        and parameter_readback_count == 10
        and evidence_count == 10
    )
    repeatability_passed = bool(
        len(metrics) == 10
        and rmse_mad is not None
        and max_error_mad is not None
        and rmse_mad <= 0.35
        and max_error_mad <= 0.35
    )
    difficulty_signal: DifficultySignal
    if len(metrics) != 10:
        difficulty_signal = "not_assessable"
    elif pass_count <= 1:
        difficulty_signal = "baseline_trivially_impossible"
    elif pass_count >= 9:
        difficulty_signal = "baseline_trivially_saturated"
    else:
        difficulty_signal = "graded"

    reasons: list[str] = []
    if not physical_contract_passed:
        reasons.append("physical_contract_incomplete_or_unsafe")
    if not repeatability_passed:
        reasons.append("baseline_repeatability_not_demonstrated")
    if difficulty_signal != "graded":
        reasons.append(difficulty_signal)
    status: FinalCandidateStatus
    if not physical_contract_passed or not repeatability_passed:
        status = "physical_contract_invalid"
    elif difficulty_signal != "graded":
        status = "replacement_required"
    else:
        status = "eligible_for_final_freeze"

    return PhysicalStabilityScenarioAssessmentV1(
        scenario_id=scenario_id,
        terminal_status_counts=dict(sorted(status_counts.items())),
        completed_count=len(completed),
        pass_count=pass_count,
        safety_critical_failure_count=safety_failures,
        effect_applied_and_read_back_count=effect_count,
        parameter_readback_verified_count=parameter_readback_count,
        complete_evidence_count=evidence_count,
        rmse_median=rmse_median,
        rmse_normalized_mad=rmse_mad,
        max_error_median=max_error_median,
        max_error_normalized_mad=max_error_mad,
        physical_contract_passed=physical_contract_passed,
        repeatability_passed=repeatability_passed,
        difficulty_signal=difficulty_signal,
        final_candidate_status=status,
        rejection_reasons=tuple(reasons),
    )


def assess_physical_stability_campaign(
    *,
    manifest: PhysicalStabilityManifestV1,
    plan: PhysicalStabilityTrialPlanV1,
    observations: list[PhysicalStabilityTrialObservationV1],
) -> PhysicalStabilityAssessmentV1:
    """Assess exactly 60 terminal observations without dropping failures."""

    if plan.manifest_sha256 != canonical_sha256(manifest):
        raise ValueError("physical stability plan is not bound to the manifest")
    expected_by_id = _expected_trial_map(plan)
    received_ids = [item.trial_id for item in observations]
    if len(received_ids) != len(set(received_ids)):
        raise ValueError("duplicate physical stability trial observation")
    missing = sorted(set(expected_by_id) - set(received_ids))
    extra = sorted(set(received_ids) - set(expected_by_id))
    if missing or extra:
        raise ValueError(
            f"physical stability observations are incomplete: missing={missing}, extra={extra}"
        )
    for observation in observations:
        _validate_observation_binding(
            manifest=manifest,
            plan=plan,
            observation=observation,
            expected=expected_by_id[observation.trial_id],
        )

    by_scenario: dict[str, list[PhysicalStabilityTrialObservationV1]] = {
        item.scenario_id: [] for item in manifest.scenarios
    }
    for observation in observations:
        by_scenario[observation.scenario_id].append(observation)
    assessments = tuple(
        _assess_scenario(item.scenario_id, by_scenario[item.scenario_id])
        for item in manifest.scenarios
    )
    eligible = tuple(
        item.scenario_id
        for item in assessments
        if item.final_candidate_status == "eligible_for_final_freeze"
    )
    status_counts = Counter(item.terminal_status for item in observations)
    return PhysicalStabilityAssessmentV1(
        manifest_sha256=canonical_sha256(manifest),
        plan_sha256=canonical_sha256(plan),
        repository_subject_commit=plan.repository_subject_commit,
        composite_execution_inventory_sha256=plan.composite_execution_inventory_sha256,
        terminal_status_counts=dict(sorted(status_counts.items())),
        scenarios=assessments,
        eligible_scenario_ids=eligible,
        pilot_selection_ready=len(eligible) >= 2,
        all_preregistered_candidates_eligible=len(eligible) == len(manifest.scenarios),
    )


def write_physical_stability_assessment(
    path: Path,
    assessment: PhysicalStabilityAssessmentV1,
) -> None:
    """Atomically create a new assessment; an existing path is never replaced."""

    destination = path.resolve()
    if not destination.parent.is_dir():
        raise FileNotFoundError(f"assessment parent directory does not exist: {destination.parent}")
    payload = (
        json.dumps(
            assessment.model_dump(mode="json"),
            indent=2,
            sort_keys=True,
            ensure_ascii=False,
            allow_nan=False,
        )
        + "\n"
    )
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            prefix=f".{destination.name}.",
            suffix=".tmp",
            dir=destination.parent,
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.link(temporary, destination)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


__all__ = [
    "PhysicalStabilityAssessmentV1",
    "PhysicalStabilityMetricsV1",
    "PhysicalStabilityTrialObservationV1",
    "assess_physical_stability_campaign",
    "write_physical_stability_assessment",
]
