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

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    ValidationError,
    model_validator,
)

from app.optimization.outcome_taxonomy import (
    TRIAL_OUTCOME_TAXONOMY_SCHEMA,
)
from app.orchestration.attempt_evidence import (
    TRIAL_ACCEPTED_ATTEMPT_EVIDENCE_SCHEMA,
    TrialAcceptedAttemptEvidenceV1,
    accepted_trial_attempt_evidence,
)
from app.storage.evidence import (
    MOCK_METADATA_ARTIFACT_EVIDENCE,
    SEALED_ARTIFACT_EVIDENCE,
    TRIAL_ARTIFACT_EVIDENCE_SCHEMA,
    candidate_trial_artifact_evidence,
)

CANDIDATE_OUTCOME_EVIDENCE_SCHEMA = "dronedream.candidate-outcome-evidence/v1"
CANDIDATE_REPORT_EVIDENCE_SCHEMA = "dronedream.candidate-report-evidence/v1"
CANDIDATE_OUTCOME_EVIDENCE_V2_SCHEMA = (
    "dronedream.candidate-outcome-evidence/v2"
)
CANDIDATE_REPORT_EVIDENCE_V2_SCHEMA = (
    "dronedream.candidate-report-evidence/v2"
)
CANDIDATE_OUTCOME_EVIDENCE_V3_SCHEMA = (
    "dronedream.candidate-outcome-evidence/v3"
)
CANDIDATE_REPORT_EVIDENCE_V3_SCHEMA = (
    "dronedream.candidate-report-evidence/v3"
)
TRIAL_OUTCOME_EVIDENCE_V2_SCHEMA = "dronedream.trial-outcome-evidence/v2"
TRIAL_OUTCOME_EVIDENCE_V3_SCHEMA = "dronedream.trial-outcome-evidence/v3"

FiniteFloat = Annotated[float, Field(allow_inf_nan=False)]
NonnegativeFloat = Annotated[float, Field(ge=0.0, allow_inf_nan=False)]
Rate = Annotated[float, Field(ge=0.0, le=1.0, allow_inf_nan=False)]
NonnegativeInt = Annotated[int, Field(ge=0)]
Sha256Id = Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]
Sha256Hex = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


class _FrozenModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        allow_inf_nan=False,
    )


class TrialArtifactItemEvidenceV1(_FrozenModel):
    artifact_id: str = Field(min_length=1, max_length=128)
    owner_type: Literal["trial"] = "trial"
    owner_id: str = Field(min_length=1, max_length=128)
    artifact_type: str = Field(min_length=1, max_length=128)
    mime_type: str | None = Field(default=None, max_length=128)
    content_evidence: Literal["sealed-bytes", "mock-metadata-only"]
    receipt_id: str | None = Field(default=None, min_length=1, max_length=128)
    receipt_evidence_id: Sha256Id | None
    content_sha256: Sha256Hex | None
    content_size_bytes: NonnegativeInt | None
    storage_path_sha256: Sha256Hex

    @model_validator(mode="after")
    def _validate_content_boundary(self) -> TrialArtifactItemEvidenceV1:
        sealed_fields = (
            self.receipt_id,
            self.receipt_evidence_id,
            self.content_sha256,
            self.content_size_bytes,
        )
        if self.content_evidence == SEALED_ARTIFACT_EVIDENCE:
            if any(value is None for value in sealed_fields):
                raise ValueError(
                    "sealed artifact evidence requires a complete byte receipt"
                )
        elif any(value is not None for value in sealed_fields):
            raise ValueError(
                "mock metadata-only evidence cannot claim sealed bytes"
            )
        return self


class TrialArtifactEvidenceV1(_FrozenModel):
    schema_id: Literal["dronedream.trial-artifact-evidence/v1"] = (
        "dronedream.trial-artifact-evidence/v1"
    )
    trial_id: str = Field(min_length=1, max_length=128)
    artifact_count: NonnegativeInt
    sealed_artifact_count: NonnegativeInt
    metadata_only_artifact_count: NonnegativeInt
    artifacts: tuple[TrialArtifactItemEvidenceV1, ...]

    @model_validator(mode="after")
    def _validate_set(self) -> TrialArtifactEvidenceV1:
        if self.artifact_count != len(self.artifacts):
            raise ValueError("artifact evidence count does not match rows")
        sealed_count = sum(
            item.content_evidence == SEALED_ARTIFACT_EVIDENCE
            for item in self.artifacts
        )
        metadata_count = sum(
            item.content_evidence == MOCK_METADATA_ARTIFACT_EVIDENCE
            for item in self.artifacts
        )
        if (
            sealed_count != self.sealed_artifact_count
            or metadata_count != self.metadata_only_artifact_count
            or sealed_count + metadata_count != self.artifact_count
        ):
            raise ValueError("artifact evidence class counts diverged")
        if any(item.owner_id != self.trial_id for item in self.artifacts):
            raise ValueError(
                "artifact evidence contains a different Trial owner"
            )
        ordering = [
            (item.artifact_type, item.artifact_id)
            for item in self.artifacts
        ]
        if ordering != sorted(ordering) or len(set(ordering)) != len(ordering):
            raise ValueError(
                "artifact evidence rows must be unique and canonical"
            )
        return self


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


class CandidateOutcomeEvidenceV2(_FrozenModel):
    schema_id: Literal["dronedream.candidate-outcome-evidence/v2"] = (
        "dronedream.candidate-outcome-evidence/v2"
    )
    evidence_id: Sha256Id
    role: Literal["search"] = "search"
    outcome_contract_id: Sha256Id
    candidate_id: str = Field(min_length=1, max_length=128)
    generation_index: NonnegativeInt
    parameter_sha256: Sha256Id
    trial_evidence_schema: Literal[
        "dronedream.trial-outcome-evidence/v2"
    ] = "dronedream.trial-outcome-evidence/v2"
    trial_artifact_evidence_schema: Literal[
        "dronedream.trial-artifact-evidence/v1"
    ] = "dronedream.trial-artifact-evidence/v1"
    trial_evidence_sha256: Sha256Id
    artifact_count: NonnegativeInt
    sealed_artifact_count: NonnegativeInt
    metadata_only_artifact_count: NonnegativeInt
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


class CandidateOutcomeEvidenceV3(_FrozenModel):
    schema_id: Literal["dronedream.candidate-outcome-evidence/v3"] = (
        "dronedream.candidate-outcome-evidence/v3"
    )
    evidence_id: Sha256Id
    role: Literal["search"] = "search"
    outcome_contract_id: Sha256Id
    candidate_id: str = Field(min_length=1, max_length=128)
    generation_index: NonnegativeInt
    parameter_sha256: Sha256Id
    trial_evidence_schema: Literal[
        "dronedream.trial-outcome-evidence/v3"
    ] = "dronedream.trial-outcome-evidence/v3"
    trial_artifact_evidence_schema: Literal[
        "dronedream.trial-artifact-evidence/v1"
    ] = "dronedream.trial-artifact-evidence/v1"
    trial_attempt_evidence_schema: Literal[
        "dronedream.trial-accepted-attempt-evidence/v1"
    ] = "dronedream.trial-accepted-attempt-evidence/v1"
    trial_evidence_sha256: Sha256Id
    artifact_count: NonnegativeInt
    sealed_artifact_count: NonnegativeInt
    metadata_only_artifact_count: NonnegativeInt
    accepted_attempt_count: NonnegativeInt
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

    @model_validator(mode="after")
    def _validate_accepted_attempt_count(
        self,
    ) -> CandidateOutcomeEvidenceV3:
        if self.accepted_attempt_count != self.trial_count:
            raise ValueError(
                "every training Trial requires one accepted physical attempt"
            )
        return self


class CandidateReportProjectionV1(_FrozenModel):
    schema_id: Literal["dronedream.candidate-report-projection/v1"] = (
        "dronedream.candidate-report-projection/v1"
    )
    rmse: NonnegativeFloat
    max_error: NonnegativeFloat
    max_error_mean: NonnegativeFloat
    max_error_worst: NonnegativeFloat
    overshoot_count: NonnegativeInt
    completion_time: NonnegativeFloat
    score: FiniteFloat
    aggregated_score: FiniteFloat
    completion_rate: Rate
    failure_rate: Rate
    pass_rate: Rate


class CandidateReportEvidenceV1(_FrozenModel):
    schema_id: Literal["dronedream.candidate-report-evidence/v1"] = (
        "dronedream.candidate-report-evidence/v1"
    )
    evidence_id: Sha256Id
    candidate_outcome_evidence_id: Sha256Id
    report_trial_evidence_sha256: Sha256Id
    projection: CandidateReportProjectionV1


class CandidateReportEvidenceV2(_FrozenModel):
    schema_id: Literal["dronedream.candidate-report-evidence/v2"] = (
        "dronedream.candidate-report-evidence/v2"
    )
    evidence_id: Sha256Id
    candidate_outcome_evidence_id: Sha256Id
    report_trial_evidence_schema: Literal[
        "dronedream.trial-outcome-evidence/v2"
    ] = "dronedream.trial-outcome-evidence/v2"
    trial_artifact_evidence_schema: Literal[
        "dronedream.trial-artifact-evidence/v1"
    ] = "dronedream.trial-artifact-evidence/v1"
    report_trial_evidence_sha256: Sha256Id
    artifact_count: NonnegativeInt
    sealed_artifact_count: NonnegativeInt
    metadata_only_artifact_count: NonnegativeInt
    projection: CandidateReportProjectionV1


class CandidateReportEvidenceV3(_FrozenModel):
    schema_id: Literal["dronedream.candidate-report-evidence/v3"] = (
        "dronedream.candidate-report-evidence/v3"
    )
    evidence_id: Sha256Id
    candidate_outcome_evidence_id: Sha256Id
    report_trial_evidence_schema: Literal[
        "dronedream.trial-outcome-evidence/v3"
    ] = "dronedream.trial-outcome-evidence/v3"
    trial_artifact_evidence_schema: Literal[
        "dronedream.trial-artifact-evidence/v1"
    ] = "dronedream.trial-artifact-evidence/v1"
    trial_attempt_evidence_schema: Literal[
        "dronedream.trial-accepted-attempt-evidence/v1"
    ] = "dronedream.trial-accepted-attempt-evidence/v1"
    report_trial_evidence_sha256: Sha256Id
    artifact_count: NonnegativeInt
    sealed_artifact_count: NonnegativeInt
    metadata_only_artifact_count: NonnegativeInt
    accepted_attempt_count: NonnegativeInt
    projection: CandidateReportProjectionV1


class CandidateReportEvidenceError(ValueError):
    """Raised when a required Candidate report projection does not verify."""


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


def trial_outcome_evidence_row(
    trial: object,
    *,
    artifact_evidence: Mapping[str, Any] | None = None,
    accepted_attempt_evidence: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
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
    if artifact_evidence is not None:
        parsed_artifacts = TrialArtifactEvidenceV1.model_validate(
            artifact_evidence
        )
        if parsed_artifacts.trial_id != trial_id:
            raise ValueError(
                "Trial artifact evidence belongs to a different Trial"
            )
        row["evidence_schema"] = TRIAL_OUTCOME_EVIDENCE_V2_SCHEMA
        row["artifact_evidence"] = parsed_artifacts.model_dump(mode="json")
        if accepted_attempt_evidence is not None:
            parsed_attempt = TrialAcceptedAttemptEvidenceV1.model_validate(
                accepted_attempt_evidence
            )
            if parsed_attempt.trial_id != trial_id:
                raise ValueError(
                    "accepted attempt evidence belongs to a different Trial"
                )
            if (
                parsed_attempt.artifact_evidence_sha256
                != _sha256_id(parsed_artifacts.model_dump(mode="json"))
            ):
                raise ValueError(
                    "accepted attempt does not bind this artifact evidence"
                )
            row["evidence_schema"] = TRIAL_OUTCOME_EVIDENCE_V3_SCHEMA
            row["accepted_attempt_evidence"] = parsed_attempt.model_dump(
                mode="json"
            )
    elif accepted_attempt_evidence is not None:
        raise ValueError(
            "accepted attempt evidence requires Trial artifact evidence"
        )
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


def _candidate_evidence_binds_artifacts(candidate: object) -> bool:
    aggregate = getattr(candidate, "aggregated_metric_json", None)
    if not isinstance(aggregate, Mapping):
        return False
    evidence = aggregate.get("candidate_outcome_evidence")
    return (
        isinstance(evidence, Mapping)
        and evidence.get("schema_id")
        in {
            CANDIDATE_OUTCOME_EVIDENCE_V2_SCHEMA,
            CANDIDATE_OUTCOME_EVIDENCE_V3_SCHEMA,
        }
    )


def _candidate_evidence_binds_attempts(candidate: object) -> bool:
    try:
        if list(candidate.evidence_receipts):  # type: ignore[attr-defined]
            return True
    except Exception:
        pass
    aggregate = getattr(candidate, "aggregated_metric_json", None)
    if not isinstance(aggregate, Mapping):
        return False
    evidence = aggregate.get("candidate_outcome_evidence")
    return (
        isinstance(evidence, Mapping)
        and evidence.get("schema_id")
        == CANDIDATE_OUTCOME_EVIDENCE_V3_SCHEMA
    )


def _candidate_artifact_evidence_map(
    candidate: object,
    trials: Sequence[object],
    *,
    bind_artifacts: bool,
    verify_artifact_bytes: bool,
) -> dict[str, dict[str, Any]] | None:
    if not bind_artifacts:
        return {}
    try:
        return candidate_trial_artifact_evidence(
            candidate,
            trials,
            verify_bytes=verify_artifact_bytes,
        )
    except Exception:  # pragma: no cover - integrity/read failures fail closed
        return None


def _candidate_attempt_evidence_map(
    trials: Sequence[object],
    *,
    artifact_map: Mapping[str, Mapping[str, Any]],
    bind_attempts: bool,
) -> dict[str, dict[str, Any]] | None:
    if not bind_attempts:
        return {}
    result: dict[str, dict[str, Any]] = {}
    try:
        for trial in trials:
            trial_id = str(getattr(trial, "id", ""))
            artifacts = artifact_map.get(trial_id)
            if not trial_id or artifacts is None:
                return None
            evidence = accepted_trial_attempt_evidence(
                trial,  # type: ignore[arg-type]
                artifact_evidence=artifacts,
            )
            if evidence is None:
                return None
            result[trial_id] = evidence.model_dump(mode="json")
    except Exception:  # pragma: no cover - malformed ORM evidence fails closed
        return None
    return result


def candidate_training_trial_evidence_rows(
    candidate: object,
    *,
    bind_artifacts: bool | None = None,
    bind_attempts: bool | None = None,
    verify_artifact_bytes: bool = False,
) -> tuple[dict[str, Any], ...] | None:
    """Return current canonical training Trial rows, or ``None`` if unreadable."""

    try:
        raw_trials = candidate.trials  # type: ignore[attr-defined]
        trials = list(raw_trials)
    except Exception:  # pragma: no cover - detached/lazy ORM state fails closed
        return None
    attempt_binding = (
        _candidate_evidence_binds_attempts(candidate)
        if bind_attempts is None
        else bind_attempts
    )
    artifact_binding = (
        _candidate_evidence_binds_artifacts(candidate)
        if bind_artifacts is None
        else bind_artifacts
    ) or attempt_binding
    artifact_map = _candidate_artifact_evidence_map(
        candidate,
        trials,
        bind_artifacts=artifact_binding,
        verify_artifact_bytes=verify_artifact_bytes,
    )
    if artifact_map is None:
        return None
    attempt_map = _candidate_attempt_evidence_map(
        trials,
        artifact_map=artifact_map,
        bind_attempts=attempt_binding,
    )
    if attempt_map is None:
        return None
    rows: list[dict[str, Any]] = []
    try:
        for trial in trials:
            row = trial_outcome_evidence_row(
                trial,
                artifact_evidence=(
                    artifact_map.get(str(getattr(trial, "id", "")))
                    if artifact_binding
                    else None
                ),
                accepted_attempt_evidence=(
                    attempt_map.get(str(getattr(trial, "id", "")))
                    if attempt_binding
                    else None
                ),
            )
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


def candidate_report_trial_evidence_rows(
    candidate: object,
    *,
    bind_artifacts: bool | None = None,
    bind_attempts: bool | None = None,
    verify_artifact_bytes: bool = False,
) -> tuple[dict[str, Any], ...] | None:
    """Return every current Trial row used by final report artifacts."""

    try:
        raw_trials = candidate.trials  # type: ignore[attr-defined]
        trials = list(raw_trials)
    except Exception:  # pragma: no cover - detached/lazy ORM state fails closed
        return None
    attempt_binding = (
        _candidate_evidence_binds_attempts(candidate)
        if bind_attempts is None
        else bind_attempts
    )
    artifact_binding = (
        _candidate_evidence_binds_artifacts(candidate)
        if bind_artifacts is None
        else bind_artifacts
    ) or attempt_binding
    artifact_map = _candidate_artifact_evidence_map(
        candidate,
        trials,
        bind_artifacts=artifact_binding,
        verify_artifact_bytes=verify_artifact_bytes,
    )
    if artifact_map is None:
        return None
    attempt_map = _candidate_attempt_evidence_map(
        trials,
        artifact_map=artifact_map,
        bind_attempts=attempt_binding,
    )
    if attempt_map is None:
        return None
    try:
        rows = [
            trial_outcome_evidence_row(
                trial,
                artifact_evidence=(
                    artifact_map.get(str(getattr(trial, "id", "")))
                    if artifact_binding
                    else None
                ),
                accepted_attempt_evidence=(
                    attempt_map.get(str(getattr(trial, "id", "")))
                    if attempt_binding
                    else None
                ),
            )
            for trial in trials
        ]
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


def _bound_trial_evidence_counts(
    trial_evidence_rows: Sequence[Mapping[str, Any]],
    *,
    bind_attempts: bool,
) -> tuple[int, int, int, int]:
    canonical_order: list[tuple[str, int, str]] = []
    artifact_count = 0
    sealed_count = 0
    metadata_only_count = 0
    accepted_attempt_count = 0
    expected_schema = (
        TRIAL_OUTCOME_EVIDENCE_V3_SCHEMA
        if bind_attempts
        else TRIAL_OUTCOME_EVIDENCE_V2_SCHEMA
    )
    for row in trial_evidence_rows:
        trial_id = row.get("trial_id")
        scenario_type = row.get("scenario_type")
        seed = row.get("seed")
        if (
            not isinstance(trial_id, str)
            or not trial_id
            or not isinstance(scenario_type, str)
            or not scenario_type
            or isinstance(seed, bool)
            or not isinstance(seed, int)
            or row.get("evidence_schema") != expected_schema
        ):
            raise ValueError(
                "bound Candidate evidence requires canonical Trial rows"
            )
        parsed = TrialArtifactEvidenceV1.model_validate(
            row.get("artifact_evidence")
        )
        if parsed.trial_id != trial_id:
            raise ValueError(
                "artifact evidence does not belong to its Trial row"
            )
        canonical_order.append((scenario_type, seed, trial_id))
        artifact_count += parsed.artifact_count
        sealed_count += parsed.sealed_artifact_count
        metadata_only_count += parsed.metadata_only_artifact_count
        if bind_attempts:
            parsed_attempt = TrialAcceptedAttemptEvidenceV1.model_validate(
                row.get("accepted_attempt_evidence")
            )
            if (
                parsed_attempt.trial_id != trial_id
                or parsed_attempt.artifact_evidence_sha256
                != _sha256_id(parsed.model_dump(mode="json"))
            ):
                raise ValueError(
                    "accepted attempt evidence does not bind its Trial row"
                )
            accepted_attempt_count += 1
    if (
        canonical_order != sorted(canonical_order)
        or len({item[2] for item in canonical_order})
        != len(canonical_order)
    ):
        raise ValueError(
            "artifact-bound Trial evidence rows must be unique and canonical"
        )
    return (
        artifact_count,
        sealed_count,
        metadata_only_count,
        accepted_attempt_count,
    )


def compile_candidate_outcome_evidence(
    *,
    outcome_contract_id: str,
    candidate_id: str,
    generation_index: int,
    parameter_snapshot: Mapping[str, Any],
    trial_evidence_rows: Sequence[Mapping[str, Any]],
    aggregate: Mapping[str, Any],
    bind_trial_artifacts: bool = False,
    bind_trial_attempts: bool = False,
) -> (
    CandidateOutcomeEvidenceV1
    | CandidateOutcomeEvidenceV2
    | CandidateOutcomeEvidenceV3
):
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
    if bind_trial_attempts and not bind_trial_artifacts:
        raise ValueError(
            "physical-attempt evidence requires Trial artifact binding"
        )
    bound_counts = (
        _bound_trial_evidence_counts(
            trial_evidence_rows,
            bind_attempts=bind_trial_attempts,
        )
        if bind_trial_artifacts
        else None
    )
    payload: dict[str, Any] = {
        "schema_id": (
            CANDIDATE_OUTCOME_EVIDENCE_V3_SCHEMA
            if bind_trial_attempts
            else (
                CANDIDATE_OUTCOME_EVIDENCE_V2_SCHEMA
                if bind_trial_artifacts
                else CANDIDATE_OUTCOME_EVIDENCE_SCHEMA
            )
        ),
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
    if bound_counts is not None:
        (
            artifact_count,
            sealed_artifact_count,
            metadata_only_artifact_count,
            accepted_attempt_count,
        ) = bound_counts
        payload.update(
            {
                "trial_evidence_schema": (
                    TRIAL_OUTCOME_EVIDENCE_V3_SCHEMA
                    if bind_trial_attempts
                    else TRIAL_OUTCOME_EVIDENCE_V2_SCHEMA
                ),
                "trial_artifact_evidence_schema": (
                    TRIAL_ARTIFACT_EVIDENCE_SCHEMA
                ),
                "artifact_count": artifact_count,
                "sealed_artifact_count": sealed_artifact_count,
                "metadata_only_artifact_count": (
                    metadata_only_artifact_count
                ),
            }
        )
        if bind_trial_attempts:
            payload.update(
                {
                    "trial_attempt_evidence_schema": (
                        TRIAL_ACCEPTED_ATTEMPT_EVIDENCE_SCHEMA
                    ),
                    "accepted_attempt_count": accepted_attempt_count,
                }
            )
    model = (
        CandidateOutcomeEvidenceV3
        if bind_trial_attempts
        else (
            CandidateOutcomeEvidenceV2
            if bind_trial_artifacts
            else CandidateOutcomeEvidenceV1
        )
    )
    return model.model_validate(
        {
            "evidence_id": _sha256_id(payload),
            **payload,
        }
    )


def compile_candidate_report_evidence(
    *,
    candidate_outcome_evidence: object,
    report_trial_evidence_rows: Sequence[Mapping[str, Any]],
    aggregate: Mapping[str, Any],
) -> (
    CandidateReportEvidenceV1
    | CandidateReportEvidenceV2
    | CandidateReportEvidenceV3
):
    """Compile immutable report metrics from one verified outcome projection."""

    outcome_evidence = verify_candidate_outcome_evidence(
        candidate_outcome_evidence
    )
    if outcome_evidence is None:
        raise ValueError("candidate report evidence requires valid outcome evidence")
    binds_artifacts = isinstance(
        outcome_evidence,
        CandidateOutcomeEvidenceV2 | CandidateOutcomeEvidenceV3,
    )
    binds_attempts = isinstance(
        outcome_evidence,
        CandidateOutcomeEvidenceV3,
    )
    bound_counts = (
        _bound_trial_evidence_counts(
            report_trial_evidence_rows,
            bind_attempts=binds_attempts,
        )
        if binds_artifacts
        else None
    )
    max_error = _finite_number(
        aggregate.get("max_error"),
        field_name="max_error",
    )
    projection = CandidateReportProjectionV1(
        rmse=_finite_number(aggregate.get("rmse"), field_name="rmse"),
        max_error=max_error,
        max_error_mean=_finite_number(
            aggregate.get("max_error_mean", max_error),
            field_name="max_error_mean",
        ),
        max_error_worst=_finite_number(
            aggregate.get("max_error_worst", max_error),
            field_name="max_error_worst",
        ),
        overshoot_count=_nonnegative_int(
            aggregate.get("overshoot_count"),
            field_name="overshoot_count",
        ),
        completion_time=_finite_number(
            aggregate.get("completion_time"),
            field_name="completion_time",
        ),
        score=_finite_number(aggregate.get("score"), field_name="score"),
        aggregated_score=_finite_number(
            aggregate.get("aggregated_score"),
            field_name="aggregated_score",
        ),
        completion_rate=_finite_number(
            aggregate.get("completion_rate"),
            field_name="completion_rate",
        ),
        failure_rate=_finite_number(
            aggregate.get("failure_rate"),
            field_name="failure_rate",
        ),
        pass_rate=_finite_number(
            aggregate.get("pass_rate"),
            field_name="pass_rate",
        ),
    )
    payload: dict[str, Any] = {
        "schema_id": (
            CANDIDATE_REPORT_EVIDENCE_V3_SCHEMA
            if binds_attempts
            else (
                CANDIDATE_REPORT_EVIDENCE_V2_SCHEMA
                if binds_artifacts
                else CANDIDATE_REPORT_EVIDENCE_SCHEMA
            )
        ),
        "candidate_outcome_evidence_id": outcome_evidence.evidence_id,
        "report_trial_evidence_sha256": _sha256_id(
            list(report_trial_evidence_rows)
        ),
        "projection": projection.model_dump(mode="json"),
    }
    if bound_counts is not None:
        (
            artifact_count,
            sealed_artifact_count,
            metadata_only_artifact_count,
            accepted_attempt_count,
        ) = bound_counts
        payload.update(
            {
                "report_trial_evidence_schema": (
                    TRIAL_OUTCOME_EVIDENCE_V3_SCHEMA
                    if binds_attempts
                    else TRIAL_OUTCOME_EVIDENCE_V2_SCHEMA
                ),
                "trial_artifact_evidence_schema": (
                    TRIAL_ARTIFACT_EVIDENCE_SCHEMA
                ),
                "artifact_count": artifact_count,
                "sealed_artifact_count": sealed_artifact_count,
                "metadata_only_artifact_count": (
                    metadata_only_artifact_count
                ),
            }
        )
        if binds_attempts:
            payload.update(
                {
                    "trial_attempt_evidence_schema": (
                        TRIAL_ACCEPTED_ATTEMPT_EVIDENCE_SCHEMA
                    ),
                    "accepted_attempt_count": accepted_attempt_count,
                }
            )
    model = (
        CandidateReportEvidenceV3
        if binds_attempts
        else (
            CandidateReportEvidenceV2
            if binds_artifacts
            else CandidateReportEvidenceV1
        )
    )
    return model.model_validate(
        {
            "evidence_id": _sha256_id(payload),
            **payload,
        }
    )


def verify_candidate_report_evidence(
    value: object,
) -> (
    CandidateReportEvidenceV1
    | CandidateReportEvidenceV2
    | CandidateReportEvidenceV3
    | None
):
    """Return parsed report evidence only when its content hash verifies."""

    if not isinstance(value, Mapping):
        return None
    model: (
        type[CandidateReportEvidenceV1]
        | type[CandidateReportEvidenceV2]
        | type[CandidateReportEvidenceV3]
    )
    if value.get("schema_id") == CANDIDATE_REPORT_EVIDENCE_SCHEMA:
        model = CandidateReportEvidenceV1
    elif value.get("schema_id") == CANDIDATE_REPORT_EVIDENCE_V2_SCHEMA:
        model = CandidateReportEvidenceV2
    elif value.get("schema_id") == CANDIDATE_REPORT_EVIDENCE_V3_SCHEMA:
        model = CandidateReportEvidenceV3
    else:
        return None
    try:
        evidence = model.model_validate(value)
    except ValidationError:
        return None
    payload = evidence.model_dump(mode="json")
    evidence_id = payload.pop("evidence_id")
    if evidence_id != _sha256_id(payload):
        return None
    return evidence


def verify_candidate_outcome_evidence(
    value: object,
) -> (
    CandidateOutcomeEvidenceV1
    | CandidateOutcomeEvidenceV2
    | CandidateOutcomeEvidenceV3
    | None
):
    """Return the parsed projection only when schema and content hash verify."""

    if not isinstance(value, Mapping):
        return None
    model: (
        type[CandidateOutcomeEvidenceV1]
        | type[CandidateOutcomeEvidenceV2]
        | type[CandidateOutcomeEvidenceV3]
    )
    if value.get("schema_id") == CANDIDATE_OUTCOME_EVIDENCE_SCHEMA:
        model = CandidateOutcomeEvidenceV1
    elif value.get("schema_id") == CANDIDATE_OUTCOME_EVIDENCE_V2_SCHEMA:
        model = CandidateOutcomeEvidenceV2
    elif value.get("schema_id") == CANDIDATE_OUTCOME_EVIDENCE_V3_SCHEMA:
        model = CandidateOutcomeEvidenceV3
    else:
        return None
    try:
        evidence = model.model_validate(value)
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


def candidate_report_evidence_required(aggregate: object) -> bool:
    return isinstance(aggregate, dict) and (
        "candidate_report_evidence" in aggregate
        or aggregate.get("candidate_report_evidence_required") is True
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
    if isinstance(
        evidence,
        CandidateOutcomeEvidenceV2 | CandidateOutcomeEvidenceV3,
    ):
        projection.update(
            {
                "trial_evidence_schema": evidence.trial_evidence_schema,
                "trial_artifact_evidence_schema": (
                    evidence.trial_artifact_evidence_schema
                ),
                "artifact_count": evidence.artifact_count,
                "sealed_artifact_count": evidence.sealed_artifact_count,
                "metadata_only_artifact_count": (
                    evidence.metadata_only_artifact_count
                ),
            }
        )
    if isinstance(evidence, CandidateOutcomeEvidenceV3):
        projection.update(
            {
                "trial_attempt_evidence_schema": (
                    evidence.trial_attempt_evidence_schema
                ),
                "accepted_attempt_count": evidence.accepted_attempt_count,
            }
        )
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


def authoritative_candidate_report_projection(
    *,
    candidate_id: object,
    generation_index: object,
    parameter_snapshot: object,
    trial_evidence_rows: object,
    report_trial_evidence_rows: object,
    aggregate: object,
) -> dict[str, Any]:
    """Resolve report fields only from a verified Candidate-bound projection."""

    outcome_projection = authoritative_candidate_trial_outcome_projection(
        candidate_id=candidate_id,
        generation_index=generation_index,
        parameter_snapshot=parameter_snapshot,
        trial_evidence_rows=trial_evidence_rows,
        aggregate=aggregate,
    )
    report_required = candidate_report_evidence_required(aggregate)
    if not report_required:
        if candidate_outcome_evidence_required(aggregate) and not outcome_projection:
            return {}
        return dict(aggregate) if isinstance(aggregate, Mapping) else {}
    if not outcome_projection or not isinstance(aggregate, Mapping):
        return {}
    if (
        isinstance(report_trial_evidence_rows, str | bytes)
        or not isinstance(report_trial_evidence_rows, Sequence)
        or any(
            not isinstance(row, Mapping)
            for row in report_trial_evidence_rows
        )
    ):
        return {}
    report_evidence = verify_candidate_report_evidence(
        aggregate.get("candidate_report_evidence")
    )
    if (
        report_evidence is None
        or report_evidence.candidate_outcome_evidence_id
        != outcome_projection.get("candidate_outcome_evidence_id")
    ):
        return {}
    try:
        current_report_trial_sha256 = _sha256_id(
            list(report_trial_evidence_rows)
        )
    except (TypeError, ValueError):
        return {}
    if (
        current_report_trial_sha256
        != report_evidence.report_trial_evidence_sha256
    ):
        return {}
    projection = report_evidence.projection.model_dump(mode="json")
    projection["candidate_report_evidence_id"] = report_evidence.evidence_id
    projection["candidate_outcome_evidence_id"] = (
        report_evidence.candidate_outcome_evidence_id
    )
    if isinstance(
        report_evidence,
        CandidateReportEvidenceV2 | CandidateReportEvidenceV3,
    ):
        projection.update(
            {
                "report_trial_evidence_schema": (
                    report_evidence.report_trial_evidence_schema
                ),
                "trial_artifact_evidence_schema": (
                    report_evidence.trial_artifact_evidence_schema
                ),
                "artifact_count": report_evidence.artifact_count,
                "sealed_artifact_count": (
                    report_evidence.sealed_artifact_count
                ),
                "metadata_only_artifact_count": (
                    report_evidence.metadata_only_artifact_count
                ),
            }
        )
    if isinstance(report_evidence, CandidateReportEvidenceV3):
        projection.update(
            {
                "trial_attempt_evidence_schema": (
                    report_evidence.trial_attempt_evidence_schema
                ),
                "accepted_attempt_count": (
                    report_evidence.accepted_attempt_count
                ),
            }
        )
    if "holdout" in outcome_projection:
        projection["holdout"] = outcome_projection["holdout"]
    return projection


def require_authoritative_candidate_report_projection(
    candidate: object,
    aggregate: object | None = None,
    *,
    verify_artifact_bytes: bool = False,
) -> dict[str, Any]:
    """Resolve one ORM-like Candidate and reject invalid required evidence."""

    raw_aggregate = (
        aggregate
        if aggregate is not None
        else getattr(candidate, "aggregated_metric_json", None)
    )
    from app.optimization.candidate_evidence_ledger import (
        candidate_evidence_chain_matches_current,
        candidate_evidence_receipt_required,
    )

    if (
        candidate_evidence_receipt_required(candidate)
        and not candidate_evidence_chain_matches_current(
            candidate,  # type: ignore[arg-type]
            raw_aggregate,
        )
    ):
        raise CandidateReportEvidenceError(
            "required relational Candidate evidence does not match the "
            "current aggregate"
        )
    projection = authoritative_candidate_report_projection(
        candidate_id=getattr(candidate, "id", None),
        generation_index=getattr(candidate, "generation_index", None),
        parameter_snapshot=getattr(candidate, "parameter_json", None),
        trial_evidence_rows=candidate_training_trial_evidence_rows(
            candidate,
            verify_artifact_bytes=verify_artifact_bytes,
        ),
        report_trial_evidence_rows=candidate_report_trial_evidence_rows(
            candidate,
            verify_artifact_bytes=verify_artifact_bytes,
        ),
        aggregate=raw_aggregate,
    )
    if (
        candidate_outcome_evidence_required(raw_aggregate)
        or candidate_report_evidence_required(raw_aggregate)
    ) and not projection:
        raise CandidateReportEvidenceError(
            "required Candidate report evidence does not match current "
            "Candidate or Trial evidence"
        )
    return projection


__all__ = [
    "CANDIDATE_OUTCOME_EVIDENCE_SCHEMA",
    "CANDIDATE_OUTCOME_EVIDENCE_V2_SCHEMA",
    "CANDIDATE_OUTCOME_EVIDENCE_V3_SCHEMA",
    "CANDIDATE_REPORT_EVIDENCE_SCHEMA",
    "CANDIDATE_REPORT_EVIDENCE_V2_SCHEMA",
    "CANDIDATE_REPORT_EVIDENCE_V3_SCHEMA",
    "TRIAL_OUTCOME_EVIDENCE_V2_SCHEMA",
    "TRIAL_OUTCOME_EVIDENCE_V3_SCHEMA",
    "CandidateAcceptanceProjectionV1",
    "CandidateOutcomeEvidenceV1",
    "CandidateOutcomeEvidenceV2",
    "CandidateOutcomeEvidenceV3",
    "CandidateReportEvidenceError",
    "CandidateReportEvidenceV1",
    "CandidateReportEvidenceV2",
    "CandidateReportEvidenceV3",
    "CandidateReportProjectionV1",
    "CandidateSelectionKeyV1",
    "TrialArtifactEvidenceV1",
    "TrialArtifactItemEvidenceV1",
    "authoritative_candidate_report_projection",
    "authoritative_candidate_outcome_projection",
    "authoritative_candidate_trial_outcome_projection",
    "authoritative_outcome_projection",
    "candidate_report_trial_evidence_rows",
    "candidate_training_trial_evidence_rows",
    "candidate_outcome_evidence_required",
    "candidate_report_evidence_required",
    "compile_candidate_outcome_evidence",
    "compile_candidate_report_evidence",
    "require_authoritative_candidate_report_projection",
    "trial_is_holdout",
    "trial_outcome_evidence_row",
    "verify_candidate_outcome_evidence",
    "verify_candidate_report_evidence",
]
