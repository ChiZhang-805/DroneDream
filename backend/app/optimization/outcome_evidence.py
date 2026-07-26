"""Content-addressed Candidate outcome projections.

This is the migration-safe compatibility layer for CandidateOutcomeEvidenceV1.
Newly aggregated Jobs persist one verified search-role projection inside the
legacy aggregate JSON. Critical consumers read that projection when present and
fail closed if its content hash or schema no longer verifies. A future schema
migration can move the same payload into an append-only relational ledger.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, ValidationError

from app.optimization.outcome_taxonomy import (
    TRIAL_OUTCOME_TAXONOMY_SCHEMA,
)

CANDIDATE_OUTCOME_EVIDENCE_SCHEMA = "dronedream.candidate-outcome-evidence/v1"

FiniteFloat = Annotated[float, Field(allow_inf_nan=False)]
NonnegativeFloat = Annotated[float, Field(ge=0.0, allow_inf_nan=False)]
Rate = Annotated[float, Field(ge=0.0, le=1.0, allow_inf_nan=False)]
NonnegativeInt = Annotated[int, Field(ge=0)]
Sha256Id = Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]


class _FrozenModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        allow_inf_nan=False,
    )


class CandidateSelectionKeyV1(_FrozenModel):
    schema_version: Literal["1.0"] = "1.0"
    evidence_complete: StrictBool
    hard_feasible: StrictBool
    hard_constraint_violation: NonnegativeFloat
    training_failure_rate: Rate
    decision_loss: FiniteFloat


class CandidateAcceptanceProjectionV1(_FrozenModel):
    schema_id: Literal["dronedream.acceptance-projection/v1"] = (
        "dronedream.acceptance-projection/v1"
    )
    rmse: NonnegativeFloat | None
    max_error: NonnegativeFloat | None
    pass_rate: Rate
    completion_rate: Rate


class CandidateOutcomeEvidenceV1(_FrozenModel):
    schema_id: Literal["dronedream.candidate-outcome-evidence/v1"] = (
        "dronedream.candidate-outcome-evidence/v1"
    )
    evidence_id: Sha256Id
    role: Literal["search"] = "search"
    outcome_contract_id: Sha256Id
    candidate_id: str = Field(min_length=1, max_length=128)
    generation_index: NonnegativeInt
    parameter_sha256: Sha256Id
    trial_evidence_sha256: Sha256Id
    holdout_projection_sha256: Sha256Id | None
    trial_count: NonnegativeInt
    completed_trial_count: NonnegativeInt
    failed_trial_count: NonnegativeInt
    passing_trial_count: NonnegativeInt
    trial_outcome_taxonomy_schema: Literal[
        "dronedream.trial-outcome-taxonomy/v1"
    ]
    trial_outcome_counts: dict[str, NonnegativeInt]
    trial_outcome_rates: dict[str, Rate]
    optimizer_learning_failure_rate: Rate
    objective_values: dict[str, FiniteFloat]
    constraint_values: dict[str, FiniteFloat]
    constraint_violations: dict[str, NonnegativeFloat]
    feasible: StrictBool
    preference_loss: FiniteFloat
    soft_constraint_penalty: NonnegativeFloat
    scalar_loss: FiniteFloat
    selection_key: CandidateSelectionKeyV1
    acceptance_projection: CandidateAcceptanceProjectionV1


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def _sha256_id(value: object) -> str:
    return "sha256:" + hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _finite_number(value: object, *, field_name: str) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, int | float)
        or not math.isfinite(float(value))
    ):
        raise ValueError(f"{field_name} must be finite")
    return float(value)


def _nonnegative_int(value: object, *, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{field_name} must be a non-negative integer")
    return value


def _finite_mapping(value: object, *, field_name: str) -> dict[str, float]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{field_name} must be an object")
    result: dict[str, float] = {}
    for name, raw in value.items():
        if not isinstance(name, str) or not name:
            raise ValueError(f"{field_name} metric names must be non-empty strings")
        result[name] = _finite_number(
            raw,
            field_name=f"{field_name}.{name}",
        )
    return result


def trial_outcome_evidence_row(trial: object) -> dict[str, Any]:
    """Compile the canonical Trial snapshot bound into Candidate evidence."""

    trial_id = getattr(trial, "id", None)
    status = getattr(trial, "status", None)
    seed = getattr(trial, "seed", None)
    scenario_type = getattr(trial, "scenario_type", None)
    raw_scenario_config = getattr(trial, "scenario_config_json", None)
    failure_code = getattr(trial, "failure_code", None)
    if not isinstance(trial_id, str) or not trial_id:
        raise ValueError("trial evidence requires a non-empty trial id")
    if not isinstance(status, str) or not status:
        raise ValueError("trial evidence requires a non-empty status")
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise ValueError("trial evidence requires an integer seed")
    if not isinstance(scenario_type, str) or not scenario_type:
        raise ValueError("trial evidence requires a non-empty scenario type")
    if raw_scenario_config is None:
        scenario_config: dict[str, Any] = {}
    elif isinstance(raw_scenario_config, Mapping):
        scenario_config = dict(raw_scenario_config)
    else:
        raise ValueError("trial evidence scenario config must be an object")
    if failure_code is not None and (
        not isinstance(failure_code, str) or not failure_code
    ):
        raise ValueError("trial evidence failure code must be non-empty")

    metric = getattr(trial, "metric", None)
    metric_payload = (
        {
            "rmse": getattr(metric, "rmse", None),
            "max_error": getattr(metric, "max_error", None),
            "overshoot_count": getattr(metric, "overshoot_count", None),
            "completion_time": getattr(metric, "completion_time", None),
            "crash_flag": getattr(metric, "crash_flag", None),
            "timeout_flag": getattr(metric, "timeout_flag", None),
            "score": getattr(metric, "score", None),
            "final_error": getattr(metric, "final_error", None),
            "pass_flag": getattr(metric, "pass_flag", None),
            "instability_flag": getattr(metric, "instability_flag", None),
        }
        if metric is not None
        else None
    )
    row = {
        "trial_id": trial_id,
        "status": status,
        "seed": seed,
        "scenario_type": scenario_type,
        "scenario_config": scenario_config,
        "failure_code": failure_code,
        "metric": metric_payload,
    }
    _canonical_json(row)
    return row


def trial_is_holdout(trial: object) -> bool:
    """Return the strict persisted Trial role used by every evidence path."""

    raw_scenario_config = getattr(trial, "scenario_config_json", None)
    if raw_scenario_config is None:
        return False
    if not isinstance(raw_scenario_config, Mapping):
        raise ValueError("trial evidence scenario config must be an object")
    holdout = raw_scenario_config.get("holdout", False)
    if not isinstance(holdout, bool):
        raise ValueError("trial evidence holdout marker must be a boolean")
    return holdout


def candidate_training_trial_evidence_rows(
    candidate: object,
) -> tuple[dict[str, Any], ...] | None:
    """Return current canonical training Trial rows, or ``None`` if unreadable."""

    try:
        raw_trials = candidate.trials  # type: ignore[attr-defined]
        trials = list(raw_trials)
    except Exception:  # pragma: no cover - detached/lazy ORM state fails closed
        return None
    rows: list[dict[str, Any]] = []
    try:
        for trial in trials:
            row = trial_outcome_evidence_row(trial)
            if trial_is_holdout(trial):
                continue
            rows.append(row)
    except Exception:  # pragma: no cover - malformed ORM evidence fails closed
        return None
    return tuple(
        sorted(
            rows,
            key=lambda row: (
                str(row["scenario_type"]),
                int(row["seed"]),
                str(row["trial_id"]),
            ),
        )
    )


def compile_candidate_outcome_evidence(
    *,
    outcome_contract_id: str,
    candidate_id: str,
    generation_index: int,
    parameter_snapshot: Mapping[str, Any],
    trial_evidence_rows: Sequence[Mapping[str, Any]],
    aggregate: Mapping[str, Any],
) -> CandidateOutcomeEvidenceV1:
    """Compile one deterministic search-role projection from accepted evidence."""

    selection_key = CandidateSelectionKeyV1.model_validate(
        aggregate.get("selection_key")
    )
    acceptance_projection = CandidateAcceptanceProjectionV1(
        rmse=_finite_number(
            aggregate.get("acceptance_rmse"),
            field_name="acceptance_rmse",
        ),
        max_error=_finite_number(
            aggregate.get("acceptance_max_error"),
            field_name="acceptance_max_error",
        ),
        pass_rate=_finite_number(
            aggregate.get("acceptance_pass_rate"),
            field_name="acceptance_pass_rate",
        ),
        completion_rate=_finite_number(
            aggregate.get("acceptance_completion_rate"),
            field_name="acceptance_completion_rate",
        ),
    )
    payload = {
        "schema_id": CANDIDATE_OUTCOME_EVIDENCE_SCHEMA,
        "role": "search",
        "outcome_contract_id": outcome_contract_id,
        "candidate_id": candidate_id,
        "generation_index": generation_index,
        "parameter_sha256": _sha256_id(parameter_snapshot),
        "trial_evidence_sha256": _sha256_id(list(trial_evidence_rows)),
        "holdout_projection_sha256": (
            _sha256_id(aggregate["holdout"])
            if "holdout" in aggregate
            else None
        ),
        "trial_count": _nonnegative_int(
            aggregate.get("training_trial_count"),
            field_name="training_trial_count",
        ),
        "completed_trial_count": _nonnegative_int(
            aggregate.get("training_completed_trial_count"),
            field_name="training_completed_trial_count",
        ),
        "failed_trial_count": _nonnegative_int(
            aggregate.get("training_failed_trial_count"),
            field_name="training_failed_trial_count",
        ),
        "passing_trial_count": _nonnegative_int(
            aggregate.get("training_passing_trial_count"),
            field_name="training_passing_trial_count",
        ),
        "trial_outcome_taxonomy_schema": (
            TRIAL_OUTCOME_TAXONOMY_SCHEMA
        ),
        "trial_outcome_counts": aggregate.get(
            "training_trial_outcome_counts"
        ),
        "trial_outcome_rates": aggregate.get(
            "training_trial_outcome_rates"
        ),
        "optimizer_learning_failure_rate": _finite_number(
            aggregate.get("optimizer_learning_failure_rate"),
            field_name="optimizer_learning_failure_rate",
        ),
        "objective_values": _finite_mapping(
            aggregate.get("objective_values"),
            field_name="objective_values",
        ),
        "constraint_values": _finite_mapping(
            aggregate.get("constraint_values"),
            field_name="constraint_values",
        ),
        "constraint_violations": _finite_mapping(
            aggregate.get("constraint_violations"),
            field_name="constraint_violations",
        ),
        "feasible": aggregate.get("feasible"),
        "preference_loss": _finite_number(
            aggregate.get("preference_loss"),
            field_name="preference_loss",
        ),
        "soft_constraint_penalty": _finite_number(
            aggregate.get("soft_constraint_penalty"),
            field_name="soft_constraint_penalty",
        ),
        "scalar_loss": _finite_number(
            aggregate.get("scalar_loss"),
            field_name="scalar_loss",
        ),
        "selection_key": selection_key.model_dump(mode="json"),
        "acceptance_projection": acceptance_projection.model_dump(mode="json"),
    }
    return CandidateOutcomeEvidenceV1.model_validate(
        {
            "evidence_id": _sha256_id(payload),
            **payload,
        }
    )


def verify_candidate_outcome_evidence(
    value: object,
) -> CandidateOutcomeEvidenceV1 | None:
    """Return the parsed projection only when schema and content hash verify."""

    try:
        evidence = CandidateOutcomeEvidenceV1.model_validate(value)
    except ValidationError:
        return None
    payload = evidence.model_dump(mode="json")
    evidence_id = payload.pop("evidence_id")
    if evidence_id != _sha256_id(payload):
        return None
    return evidence


def candidate_outcome_evidence_required(aggregate: object) -> bool:
    return isinstance(aggregate, dict) and (
        "candidate_outcome_evidence" in aggregate
        or aggregate.get("candidate_outcome_evidence_required") is True
    )


def authoritative_outcome_projection(aggregate: object) -> dict[str, Any]:
    """Resolve critical fields from verified evidence, preserving legacy rows.

    Aggregates created before CandidateOutcomeEvidenceV1 remain readable. Once
    the evidence field exists, however, a malformed or hash-mismatched payload
    returns an empty projection so callers fail closed instead of trusting the
    mutable compatibility fields beside it.
    """

    if not isinstance(aggregate, dict):
        return {}
    if "candidate_outcome_evidence" not in aggregate:
        if aggregate.get("candidate_outcome_evidence_required") is True:
            return {}
        return aggregate
    raw_evidence = aggregate.get("candidate_outcome_evidence")
    evidence = verify_candidate_outcome_evidence(raw_evidence)
    if evidence is None:
        return {}
    holdout = aggregate.get("holdout")
    if evidence.holdout_projection_sha256 is None:
        if "holdout" in aggregate:
            return {}
    elif evidence.holdout_projection_sha256 != _sha256_id(holdout):
        return {}
    acceptance = evidence.acceptance_projection
    projection = {
        "candidate_outcome_evidence_id": evidence.evidence_id,
        "candidate_outcome_evidence_required": True,
        "outcome_contract_id": evidence.outcome_contract_id,
        "objective_values": dict(evidence.objective_values),
        "constraint_values": dict(evidence.constraint_values),
        "constraint_violations": dict(evidence.constraint_violations),
        "feasible": evidence.feasible,
        "preference_loss": evidence.preference_loss,
        "soft_constraint_penalty": evidence.soft_constraint_penalty,
        "scalar_loss": evidence.scalar_loss,
        "selection_key": evidence.selection_key.model_dump(mode="json"),
        "training_trial_count": evidence.trial_count,
        "training_completed_trial_count": evidence.completed_trial_count,
        "training_failed_trial_count": evidence.failed_trial_count,
        "training_passing_trial_count": evidence.passing_trial_count,
        "trial_outcome_taxonomy_schema": (
            evidence.trial_outcome_taxonomy_schema
        ),
        "training_trial_outcome_counts": dict(
            evidence.trial_outcome_counts
        ),
        "training_trial_outcome_rates": dict(
            evidence.trial_outcome_rates
        ),
        "optimizer_learning_failure_rate": (
            evidence.optimizer_learning_failure_rate
        ),
        "training_failure_rate": evidence.selection_key.training_failure_rate,
        "failure_rate": evidence.selection_key.training_failure_rate,
        "acceptance_projection_schema": acceptance.schema_id,
        "acceptance_rmse": acceptance.rmse,
        "acceptance_max_error": acceptance.max_error,
        "acceptance_pass_rate": acceptance.pass_rate,
        "acceptance_completion_rate": acceptance.completion_rate,
    }
    if evidence.holdout_projection_sha256 is not None:
        projection["holdout"] = holdout
    return projection


def authoritative_candidate_outcome_projection(
    *,
    candidate_id: object,
    generation_index: object,
    parameter_snapshot: object,
    aggregate: object,
) -> dict[str, Any]:
    """Resolve evidence only when it still belongs to the current Candidate.

    ``authoritative_outcome_projection`` verifies the evidence payload and its
    holdout binding. This candidate-aware boundary additionally checks the
    immutable identity fields that the evidence was compiled from. Legacy
    aggregates remain readable until their migration marker requires evidence.
    """

    projection = authoritative_outcome_projection(aggregate)
    if not candidate_outcome_evidence_required(aggregate):
        return projection
    if not projection or not isinstance(aggregate, Mapping):
        return {}
    evidence = verify_candidate_outcome_evidence(
        aggregate.get("candidate_outcome_evidence")
    )
    if (
        evidence is None
        or not isinstance(candidate_id, str)
        or candidate_id != evidence.candidate_id
        or isinstance(generation_index, bool)
        or not isinstance(generation_index, int)
        or generation_index != evidence.generation_index
        or not isinstance(parameter_snapshot, Mapping)
    ):
        return {}
    try:
        current_parameter_sha256 = _sha256_id(parameter_snapshot)
    except (TypeError, ValueError):
        return {}
    if current_parameter_sha256 != evidence.parameter_sha256:
        return {}
    return projection


def authoritative_candidate_trial_outcome_projection(
    *,
    candidate_id: object,
    generation_index: object,
    parameter_snapshot: object,
    trial_evidence_rows: object,
    aggregate: object,
) -> dict[str, Any]:
    """Resolve evidence only when current training Trial rows still match."""

    projection = authoritative_candidate_outcome_projection(
        candidate_id=candidate_id,
        generation_index=generation_index,
        parameter_snapshot=parameter_snapshot,
        aggregate=aggregate,
    )
    if not candidate_outcome_evidence_required(aggregate):
        return projection
    if (
        not projection
        or not isinstance(aggregate, Mapping)
        or isinstance(trial_evidence_rows, str | bytes)
        or not isinstance(trial_evidence_rows, Sequence)
    ):
        return {}
    evidence = verify_candidate_outcome_evidence(
        aggregate.get("candidate_outcome_evidence")
    )
    if evidence is None or any(
        not isinstance(row, Mapping) for row in trial_evidence_rows
    ):
        return {}
    try:
        current_trial_sha256 = _sha256_id(list(trial_evidence_rows))
    except (TypeError, ValueError):
        return {}
    if current_trial_sha256 != evidence.trial_evidence_sha256:
        return {}
    return projection


__all__ = [
    "CANDIDATE_OUTCOME_EVIDENCE_SCHEMA",
    "CandidateAcceptanceProjectionV1",
    "CandidateOutcomeEvidenceV1",
    "CandidateSelectionKeyV1",
    "authoritative_candidate_outcome_projection",
    "authoritative_candidate_trial_outcome_projection",
    "authoritative_outcome_projection",
    "candidate_training_trial_evidence_rows",
    "candidate_outcome_evidence_required",
    "compile_candidate_outcome_evidence",
    "trial_is_holdout",
    "trial_outcome_evidence_row",
    "verify_candidate_outcome_evidence",
]
