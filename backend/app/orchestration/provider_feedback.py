"""Verified training feedback shared by model-facing optimization paths.

Candidate aggregate columns remain useful compatibility fields, but modern
Candidates also carry content-addressed outcome evidence bound to their
parameter snapshot and canonical training Trial rows.  Once that evidence is
present, a model-facing consumer must never fall back to the mutable sibling
fields when verification fails: doing so would let stale or partially written
feedback steer the next optimization decision.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Literal

from app import models, schemas
from app.optimization.outcome_evidence import (
    authoritative_candidate_trial_outcome_projection,
    candidate_outcome_evidence_required,
    candidate_training_trial_evidence_rows,
)
from app.optimization.outcome_taxonomy import (
    classify_trial_outcome,
    is_optimizer_learning_failure,
    is_optimizer_learning_outcome,
)
from app.optimization.scenarios import resolve_scenario_case
from app.orchestration import constants

CandidateFeedbackStatus = Literal[
    "verified",
    "legacy_unsealed",
    "quarantined",
]


@dataclass(frozen=True)
class CandidateFeedbackView:
    """Closed feedback projection safe for optimizer/model consumption."""

    aggregate: dict[str, Any]
    score: float | None
    feedback_status: CandidateFeedbackStatus
    learning_trial_count: int
    completed_trial_count: int
    failed_trial_count: int
    feasible: bool | None

    @property
    def usable(self) -> bool:
        return self.feedback_status != "quarantined"


def _finite(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    numeric = float(value)
    return numeric if math.isfinite(numeric) else None


def _legacy_learning_counts(
    candidate: models.CandidateParameterSet,
    scenario_suite: schemas.ScenarioSuiteConfig | None,
) -> tuple[int, int, int]:
    """Compile the closed training taxonomy for pre-evidence Candidates."""

    learning_count = 0
    completed_count = 0
    failed_count = 0
    for trial in candidate.trials:
        scenario_matched = True
        scenario_holdout = False
        if scenario_suite is not None:
            resolution = resolve_scenario_case(
                scenario_suite,
                scenario_type=trial.scenario_type,
                scenario_config=trial.scenario_config_json,
                seed=trial.seed,
            )
            scenario_matched = resolution.matched and resolution.case is not None
            scenario_holdout = (
                resolution.case.holdout if resolution.case is not None else False
            )
        else:
            scenario_config = trial.scenario_config_json
            if not isinstance(scenario_config, dict):
                scenario_matched = False
            else:
                holdout = scenario_config.get("holdout", False)
                if not isinstance(holdout, bool):
                    scenario_matched = False
                else:
                    scenario_holdout = holdout
        metric = trial.metric
        usable_metric = (
            trial.status == "COMPLETED"
            and metric is not None
            and _finite(metric.rmse) is not None
            and _finite(metric.max_error) is not None
            and _finite(metric.completion_time) is not None
        )
        if not scenario_matched or scenario_holdout:
            continue
        outcome_class = classify_trial_outcome(
            status=trial.status,
            failure_code=trial.failure_code,
            usable_metric=usable_metric,
        )
        if not is_optimizer_learning_outcome(outcome_class):
            continue
        learning_count += 1
        if outcome_class == "success":
            completed_count += 1
        elif is_optimizer_learning_failure(outcome_class):
            failed_count += 1
    return learning_count, completed_count, failed_count


def _verified_learning_counts(
    projection: dict[str, Any],
) -> tuple[int, int, int] | None:
    raw_counts = projection.get("training_trial_outcome_counts")
    if not isinstance(raw_counts, dict):
        return None

    def count(name: str) -> int | None:
        value = raw_counts.get(name)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            return None
        return value

    completed = count("success")
    failed = count("domain_failure")
    if completed is None or failed is None:
        return None
    return completed + failed, completed, failed


def _verified_score(projection: dict[str, Any]) -> float | None:
    selection_key = projection.get("selection_key")
    if not isinstance(selection_key, dict):
        return None
    decision_loss = _finite(selection_key.get("decision_loss"))
    failure_rate = _finite(projection.get("optimizer_learning_failure_rate"))
    if (
        decision_loss is None
        or failure_rate is None
        or not 0.0 <= failure_rate <= 1.0
    ):
        return None
    return round(
        decision_loss
        + constants.SCORE_WEIGHTS["failed_trial"] * failure_rate,
        8,
    )


def compile_candidate_feedback(
    candidate: models.CandidateParameterSet,
    *,
    scenario_suite: schemas.ScenarioSuiteConfig | None,
) -> CandidateFeedbackView:
    """Return verified training feedback, quarantining divergent modern rows.

    Legacy Candidates without an evidence marker retain their historical
    behavior for migration compatibility.  Once evidence is required, the
    current parameters and canonical training Trial rows must reproduce the
    stored content-addressed projection.  Any mismatch yields an empty,
    explicitly quarantined view rather than trusting mutable aggregate fields
    or manufacturing a numeric penalty.
    """

    raw_aggregate = (
        candidate.aggregated_metric_json
        if isinstance(candidate.aggregated_metric_json, dict)
        else {}
    )
    if not candidate_outcome_evidence_required(raw_aggregate):
        counts = _legacy_learning_counts(candidate, scenario_suite)
        feasible = raw_aggregate.get("feasible")
        return CandidateFeedbackView(
            aggregate=dict(raw_aggregate),
            score=_finite(candidate.aggregated_score),
            feedback_status="legacy_unsealed",
            learning_trial_count=counts[0],
            completed_trial_count=counts[1],
            failed_trial_count=counts[2],
            feasible=feasible if isinstance(feasible, bool) else None,
        )

    trial_rows = candidate_training_trial_evidence_rows(candidate)
    if trial_rows is None:
        return CandidateFeedbackView(
            aggregate={},
            score=None,
            feedback_status="quarantined",
            learning_trial_count=0,
            completed_trial_count=0,
            failed_trial_count=0,
            feasible=None,
        )
    projection = authoritative_candidate_trial_outcome_projection(
        candidate_id=candidate.id,
        generation_index=candidate.generation_index,
        parameter_snapshot=candidate.parameter_json,
        trial_evidence_rows=trial_rows,
        aggregate=raw_aggregate,
    )
    verified_counts = _verified_learning_counts(projection) if projection else None
    score = _verified_score(projection) if projection else None
    if not projection or verified_counts is None or score is None:
        return CandidateFeedbackView(
            aggregate={},
            score=None,
            feedback_status="quarantined",
            learning_trial_count=0,
            completed_trial_count=0,
            failed_trial_count=0,
            feasible=None,
        )

    aggregate = dict(projection)
    aggregate["aggregated_score"] = score
    # Preserve the existing provider schema while sourcing these compatibility
    # metrics from the verified training-only acceptance projection.
    if (rmse := _finite(projection.get("acceptance_rmse"))) is not None:
        aggregate["rmse"] = rmse
    if (max_error := _finite(projection.get("acceptance_max_error"))) is not None:
        aggregate["max_error"] = max_error
    feasible = projection.get("feasible")
    return CandidateFeedbackView(
        aggregate=aggregate,
        score=score,
        feedback_status="verified",
        learning_trial_count=verified_counts[0],
        completed_trial_count=verified_counts[1],
        failed_trial_count=verified_counts[2],
        feasible=feasible if isinstance(feasible, bool) else None,
    )


__all__ = [
    "CandidateFeedbackStatus",
    "CandidateFeedbackView",
    "compile_candidate_feedback",
]
