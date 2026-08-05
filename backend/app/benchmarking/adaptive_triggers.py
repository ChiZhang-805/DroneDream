"""Pure, versioned trigger policy for the adaptive benchmark Harness.

The trigger evaluator is deliberately independent of provider, database, and
simulator I/O.  Offline fixtures and the durable production runtime therefore
consume the same deterministic diagnosis/critic authorization decision.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Annotated, Final, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.benchmarking.adapters import search_space_from_observation
from app.benchmarking.contracts import (
    BenchmarkObservationV2,
    BenchmarkProposalV1,
    canonical_sha256,
)

BENCHMARK_ADAPTIVE_TRIGGER_POLICY_VERSION: Final = "benchmark-adaptive-trigger-v1"

_TRIGGER_FAMILY: Final = {
    "trailing_stagnation": "progress",
    "tool_direction_conflict": "conflict",
    "prediction_outcome_mismatch": "mismatch",
    "domain_failure_spike": "physical_failure",
    "ood_no_transfer_memory": "ood",
    "crash_or_instability": "physical_failure",
    "timeout_or_sensor_anomaly": "physical_failure",
    "near_threshold_uncertain": "threshold",
    "hard_boundary_candidate": "boundary",
}
_TRIGGER_SEVERITY: Final = {
    "trailing_stagnation": 1,
    "tool_direction_conflict": 1,
    "prediction_outcome_mismatch": 1,
    "domain_failure_spike": 1,
    "ood_no_transfer_memory": 1,
    "near_threshold_uncertain": 1,
    "crash_or_instability": 2,
    "timeout_or_sensor_anomaly": 2,
    "hard_boundary_candidate": 2,
}


class BenchmarkAdaptiveTriggerPolicyManifestV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    schema_id: Literal["dronedream.benchmark-adaptive-trigger-policy/v1"] = (
        "dronedream.benchmark-adaptive-trigger-policy/v1"
    )
    policy_version: Literal["benchmark-adaptive-trigger-v1"] = "benchmark-adaptive-trigger-v1"
    cooldown_generations: Literal[1] = 1
    severity_upgrade_bypasses_cooldown: Literal[True] = True
    reason_family: tuple[tuple[str, str], ...]
    reason_severity: tuple[tuple[str, int], ...]


BENCHMARK_ADAPTIVE_TRIGGER_POLICY_MANIFEST: Final = BenchmarkAdaptiveTriggerPolicyManifestV1(
    reason_family=tuple(sorted(_TRIGGER_FAMILY.items())),
    reason_severity=tuple(sorted(_TRIGGER_SEVERITY.items())),
)
BENCHMARK_ADAPTIVE_TRIGGER_POLICY_SHA256: Final = canonical_sha256(
    BENCHMARK_ADAPTIVE_TRIGGER_POLICY_MANIFEST
)


class BenchmarkAdaptiveTriggerDecisionV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    schema_id: Literal["dronedream.benchmark-adaptive-trigger-decision/v1"] = (
        "dronedream.benchmark-adaptive-trigger-decision/v1"
    )
    policy_version: Literal["benchmark-adaptive-trigger-v1"] = "benchmark-adaptive-trigger-v1"
    policy_sha256: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")] = (
        BENCHMARK_ADAPTIVE_TRIGGER_POLICY_SHA256
    )
    diagnosis_reasons: tuple[str, ...] = Field(default=(), max_length=9)
    critic_reasons: tuple[str, ...] = Field(default=(), max_length=9)
    suppressed_by_cooldown: tuple[str, ...] = Field(default=(), max_length=9)
    evidence_sha256: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    next_family_state: dict[str, tuple[int, int]] = Field(default_factory=dict)


class BenchmarkAdaptiveTriggerContractError(ValueError):
    """The selected proposal or prior cooldown state violates the trigger contract."""


def _objective_losses(observation: BenchmarkObservationV2) -> list[float]:
    return [
        float(item.outcome.loss)
        for item in observation.history
        if item.outcome.role == "objective" and item.outcome.loss is not None
    ]


def _tool_direction_conflict(
    observation: BenchmarkObservationV2,
    proposals: Sequence[BenchmarkProposalV1],
) -> bool:
    if len(proposals) < 2:
        return False
    space = search_space_from_observation(observation)
    vectors = [space.to_unit_vector(proposal.parameters) for proposal in proposals]
    dimensions = max(1, len(vectors[0]))
    for left_index, left in enumerate(vectors):
        for right in vectors[left_index + 1 :]:
            distance = math.sqrt(sum((a - b) ** 2 for a, b in zip(left, right, strict=True)))
            if distance / math.sqrt(dimensions) >= 0.5:
                return True
    return False


def _prediction_outcome_mismatch(observation: BenchmarkObservationV2) -> bool:
    for item in reversed(observation.history):
        context = item.proposal_context
        actual = item.outcome.loss
        if context is None or actual is None:
            continue
        predicted = context.optimizer_metadata.get("predicted_loss")
        if isinstance(predicted, bool) or not isinstance(predicted, int | float):
            continue
        if not math.isfinite(float(predicted)):
            continue
        return abs(float(actual) - float(predicted)) > max(0.1, abs(float(predicted)) * 0.5)
    return False


def _hard_boundary_candidate(
    observation: BenchmarkObservationV2,
    proposal: BenchmarkProposalV1,
) -> bool:
    vector = search_space_from_observation(observation).to_unit_vector(proposal.parameters)
    return any(value <= 0.02 or value >= 0.98 for value in vector)


def evaluate_benchmark_adaptive_triggers(
    observation: BenchmarkObservationV2,
    proposals: Sequence[BenchmarkProposalV1],
    selected_proposal: BenchmarkProposalV1,
    *,
    previous_family_state: Mapping[str, tuple[int, int]] | None = None,
) -> BenchmarkAdaptiveTriggerDecisionV1:
    """Authorize optional T3/T4 with deterministic one-generation cooldown."""

    proposal_refs = [proposal.candidate_ref for proposal in proposals]
    if (
        not proposal_refs
        or len(proposal_refs) != len(set(proposal_refs))
        or selected_proposal.candidate_ref not in proposal_refs
    ):
        raise BenchmarkAdaptiveTriggerContractError(
            "adaptive trigger proposals must be non-empty, unique, and contain the selection"
        )
    matching = proposals[proposal_refs.index(selected_proposal.candidate_ref)]
    if canonical_sha256(matching) != canonical_sha256(selected_proposal):
        raise BenchmarkAdaptiveTriggerContractError(
            "adaptive trigger selected proposal differs from its frozen proposal reference"
        )
    valid_families = set(_TRIGGER_FAMILY.values())
    for family, state in (previous_family_state or {}).items():
        if (
            family not in valid_families
            or not isinstance(state, tuple)
            or len(state) != 2
            or isinstance(state[0], bool)
            or not isinstance(state[0], int)
            or not 0 <= state[0] <= observation.generation_index
            or isinstance(state[1], bool)
            or not isinstance(state[1], int)
            or state[1] not in {1, 2}
        ):
            raise BenchmarkAdaptiveTriggerContractError(
                "adaptive trigger cooldown state is invalid or from a future generation"
            )

    diagnosis: list[str] = []
    critic: list[str] = []
    losses = _objective_losses(observation)
    if len(losses) >= 3 and min(losses[-3:]) >= min(losses[:-2]) - 1e-12:
        diagnosis.append("trailing_stagnation")
    if _tool_direction_conflict(observation, proposals):
        diagnosis.append("tool_direction_conflict")
    if _prediction_outcome_mismatch(observation):
        diagnosis.append("prediction_outcome_mismatch")
    recent = observation.history[-3:]
    if sum(item.screening_status in {"failed", "unsafe", "timeout"} for item in recent) >= 2:
        diagnosis.append("domain_failure_spike")
    if (
        observation.failure_semantics.get("scenario_distribution") == "ood"
        and not observation.history
    ):
        diagnosis.append("ood_no_transfer_memory")

    failure_codes = tuple((item.failure_code or "").lower() for item in recent)
    if any("crash" in code or "unstable" in code for code in failure_codes) or any(
        item.screening_status == "unsafe" for item in recent
    ):
        critic.append("crash_or_instability")
    if any("sensor" in code for code in failure_codes) or any(
        item.screening_status == "timeout" for item in recent
    ):
        critic.append("timeout_or_sensor_anomaly")
    if any(
        0.0 < violation <= 0.05
        for item in recent
        for violation in item.outcome.constraint_violations.values()
    ):
        critic.append("near_threshold_uncertain")
    if _hard_boundary_candidate(observation, selected_proposal):
        critic.append("hard_boundary_candidate")

    prior = dict(previous_family_state or {})
    suppressed: list[str] = []

    def apply_cooldown(reasons: Sequence[str]) -> tuple[str, ...]:
        accepted: list[str] = []
        for reason in reasons:
            family = _TRIGGER_FAMILY[reason]
            severity = _TRIGGER_SEVERITY[reason]
            previous = prior.get(family)
            if (
                previous is not None
                and observation.generation_index - previous[0] <= 1
                and severity <= previous[1]
            ):
                suppressed.append(reason)
                continue
            accepted.append(reason)
            prior[family] = (observation.generation_index, severity)
        return tuple(accepted)

    diagnosis_reasons = apply_cooldown(diagnosis)
    critic_reasons = apply_cooldown(critic)
    evidence = {
        "schema_id": "dronedream.benchmark-adaptive-trigger-evidence/v1",
        "policy_sha256": BENCHMARK_ADAPTIVE_TRIGGER_POLICY_SHA256,
        "generation_index": observation.generation_index,
        "history_statuses": [item.screening_status for item in recent],
        "losses_sha256": canonical_sha256(losses),
        "proposal_parameter_sha256": [canonical_sha256(item.parameters) for item in proposals],
        "selected_parameter_sha256": canonical_sha256(selected_proposal.parameters),
        "previous_family_state": {
            key: list(value) for key, value in sorted((previous_family_state or {}).items())
        },
    }
    return BenchmarkAdaptiveTriggerDecisionV1(
        diagnosis_reasons=diagnosis_reasons,
        critic_reasons=critic_reasons,
        suppressed_by_cooldown=tuple(dict.fromkeys(suppressed)),
        evidence_sha256=canonical_sha256(evidence),
        next_family_state=prior,
    )


__all__ = [
    "BENCHMARK_ADAPTIVE_TRIGGER_POLICY_MANIFEST",
    "BENCHMARK_ADAPTIVE_TRIGGER_POLICY_SHA256",
    "BENCHMARK_ADAPTIVE_TRIGGER_POLICY_VERSION",
    "BenchmarkAdaptiveTriggerContractError",
    "BenchmarkAdaptiveTriggerDecisionV1",
    "BenchmarkAdaptiveTriggerPolicyManifestV1",
    "evaluate_benchmark_adaptive_triggers",
]
