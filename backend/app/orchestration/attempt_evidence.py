"""Immutable claim/outcome evidence for physical Trial executions."""

from __future__ import annotations

import copy
import hashlib
import json
from collections.abc import Mapping
from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    ValidationError,
    model_validator,
)
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import models
from app.storage.evidence import TRIAL_ARTIFACT_EVIDENCE_SCHEMA
from app.time_utils import canonical_utc_iso

TRIAL_ATTEMPT_CLAIM_EVIDENCE_SCHEMA: Literal[
    "dronedream.trial-execution-attempt-claim/v2"
] = (
    "dronedream.trial-execution-attempt-claim/v2"
)
TRIAL_ATTEMPT_CLAIM_EVIDENCE_V1_SCHEMA: Literal[
    "dronedream.trial-execution-attempt-claim/v1"
] = "dronedream.trial-execution-attempt-claim/v1"
TRIAL_ATTEMPT_OUTCOME_EVIDENCE_SCHEMA: Literal[
    "dronedream.trial-execution-attempt-outcome/v1"
] = (
    "dronedream.trial-execution-attempt-outcome/v1"
)
TRIAL_ACCEPTED_ATTEMPT_EVIDENCE_SCHEMA: Literal[
    "dronedream.trial-accepted-attempt-evidence/v1"
] = (
    "dronedream.trial-accepted-attempt-evidence/v1"
)

Sha256Id = Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]
Sha256Hex = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
NonnegativeInt = Annotated[int, Field(ge=0)]
PositiveInt = Annotated[int, Field(ge=1)]

_ACCEPTED_TERMINAL_STATUSES = {"COMPLETED", "FAILED", "CANCELLED"}
_OUTCOME_CLASSES = {
    "success",
    "domain_failure",
    "infrastructure_failure",
    "cancelled",
    "invalid_evidence",
    "unknown_failure",
    "superseded",
}


class TrialAttemptEvidenceError(ValueError):
    """Raised when physical-attempt identity or immutable evidence diverges."""


class _FrozenModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        allow_inf_nan=False,
    )


class _TrialAttemptClaimEvidenceBase(_FrozenModel):
    evidence_id: Sha256Id
    trial_id: str = Field(min_length=1, max_length=128)
    job_id: str = Field(min_length=1, max_length=128)
    candidate_id: str = Field(min_length=1, max_length=128)
    attempt_count: PositiveInt
    claim_kind: Literal["initial", "stale-reclaim"]
    worker_id_sha256: Sha256Hex
    lease_token_sha256: Sha256Id
    simulator_backend: str = Field(min_length=1, max_length=128)
    parameter_sha256: Sha256Id
    scenario_sha256: Sha256Id
    job_config_sha256: Sha256Id
    claimed_at: str = Field(min_length=20, max_length=64)


class TrialAttemptClaimEvidenceV1(_TrialAttemptClaimEvidenceBase):
    """Legacy three-hash claim receipt retained exactly as originally frozen."""

    schema_id: Literal[
        "dronedream.trial-execution-attempt-claim/v1"
    ] = TRIAL_ATTEMPT_CLAIM_EVIDENCE_V1_SCHEMA


class TrialAttemptClaimEvidenceV2(_TrialAttemptClaimEvidenceBase):
    """Claim receipt binding one combined snapshot used by the simulator."""

    schema_id: Literal[
        "dronedream.trial-execution-attempt-claim/v2"
    ] = TRIAL_ATTEMPT_CLAIM_EVIDENCE_SCHEMA
    execution_input_sha256: Sha256Id


TrialAttemptClaimEvidence = (
    TrialAttemptClaimEvidenceV1 | TrialAttemptClaimEvidenceV2
)


class TrialAttemptOutcomeEvidenceV1(_FrozenModel):
    schema_id: Literal[
        "dronedream.trial-execution-attempt-outcome/v1"
    ] = TRIAL_ATTEMPT_OUTCOME_EVIDENCE_SCHEMA
    evidence_id: Sha256Id
    attempt_id: str = Field(min_length=1, max_length=128)
    claim_evidence_id: Sha256Id
    trial_id: str = Field(min_length=1, max_length=128)
    job_id: str = Field(min_length=1, max_length=128)
    candidate_id: str = Field(min_length=1, max_length=128)
    attempt_count: PositiveInt
    terminal_status: Literal[
        "COMPLETED",
        "FAILED",
        "CANCELLED",
        "SUPERSEDED",
    ]
    outcome_class: Literal[
        "success",
        "domain_failure",
        "infrastructure_failure",
        "cancelled",
        "invalid_evidence",
        "unknown_failure",
        "superseded",
    ]
    accepted: StrictBool
    failure_code: str | None = Field(default=None, min_length=1, max_length=128)
    metric_sha256: Sha256Id | None
    artifact_evidence_schema: Literal[
        "dronedream.trial-artifact-evidence/v1"
    ] = "dronedream.trial-artifact-evidence/v1"
    artifact_evidence_sha256: Sha256Id
    artifact_count: NonnegativeInt
    sealed_artifact_count: NonnegativeInt
    metadata_only_artifact_count: NonnegativeInt
    superseded_by_attempt_count: PositiveInt | None
    finished_at: str = Field(min_length=20, max_length=64)

    @model_validator(mode="after")
    def _validate_terminal_semantics(
        self,
    ) -> TrialAttemptOutcomeEvidenceV1:
        if self.outcome_class not in _OUTCOME_CLASSES:
            raise ValueError("unknown physical-attempt outcome class")
        if self.accepted:
            if (
                self.terminal_status not in _ACCEPTED_TERMINAL_STATUSES
                or self.outcome_class == "superseded"
                or self.superseded_by_attempt_count is not None
            ):
                raise ValueError("accepted attempt has invalid terminal semantics")
        elif (
            self.terminal_status != "SUPERSEDED"
            or self.outcome_class != "superseded"
            or self.superseded_by_attempt_count is None
            or self.superseded_by_attempt_count <= self.attempt_count
            or self.metric_sha256 is not None
            or self.artifact_count != 0
            or self.sealed_artifact_count != 0
            or self.metadata_only_artifact_count != 0
        ):
            raise ValueError("superseded attempt has invalid terminal semantics")
        if self.terminal_status == "COMPLETED":
            if (
                self.outcome_class != "success"
                or self.metric_sha256 is None
                or self.failure_code is not None
            ):
                raise ValueError(
                    "completed attempt requires one successful metric"
                )
        elif self.accepted and self.metric_sha256 is not None:
            raise ValueError("non-completed attempt cannot claim a metric")
        if (
            self.sealed_artifact_count
            + self.metadata_only_artifact_count
            != self.artifact_count
        ):
            raise ValueError("attempt artifact counts diverged")
        return self


class TrialAcceptedAttemptEvidenceV1(_FrozenModel):
    schema_id: Literal[
        "dronedream.trial-accepted-attempt-evidence/v1"
    ] = TRIAL_ACCEPTED_ATTEMPT_EVIDENCE_SCHEMA
    trial_id: str = Field(min_length=1, max_length=128)
    attempt_id: str = Field(min_length=1, max_length=128)
    attempt_count: PositiveInt
    claim_evidence_id: Sha256Id
    outcome_evidence_id: Sha256Id
    terminal_status: Literal["COMPLETED", "FAILED", "CANCELLED"]
    outcome_class: Literal[
        "success",
        "domain_failure",
        "infrastructure_failure",
        "cancelled",
        "invalid_evidence",
        "unknown_failure",
    ]
    metric_sha256: Sha256Id | None
    artifact_evidence_sha256: Sha256Id


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def _sha256_id(value: object) -> str:
    return "sha256:" + hashlib.sha256(
        _canonical_json(value).encode("utf-8")
    ).hexdigest()


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _timestamp(value: datetime) -> str:
    normalized = canonical_utc_iso(value)
    if normalized is None:
        raise TrialAttemptEvidenceError(
            "attempt evidence requires a timezone-aware timestamp"
        )
    return normalized


def _job_input_snapshot(job: models.Job) -> dict[str, Any]:
    return {
        "track_type": job.track_type,
        "start_point_x": job.start_point_x,
        "start_point_y": job.start_point_y,
        "altitude_m": job.altitude_m,
        "wind_north": job.wind_north,
        "wind_east": job.wind_east,
        "wind_south": job.wind_south,
        "wind_west": job.wind_west,
        "sensor_noise_level": job.sensor_noise_level,
        "objective_profile": job.objective_profile,
        "reference_track": job.reference_track_json,
        "vehicle_profile": job.vehicle_profile_json,
        "parameter_catalog_version": job.parameter_catalog_version,
        "parameter_space": job.parameter_space_json,
        "objective_config": job.objective_config_json,
        "scenario_suite": job.scenario_suite_json,
    }


def snapshot_trial_attempt_inputs(
    *,
    trial: models.Trial,
    job: models.Job,
    candidate: models.CandidateParameterSet,
) -> dict[str, Any]:
    """Deep-copy the exact claim-time inputs shared by execution and evidence."""

    parameters = candidate.parameter_json
    if parameters is None:
        parameters = {}
    scenario_config = trial.scenario_config_json
    snapshot = {
        "trial": {
            "trial_id": trial.id,
            "job_id": trial.job_id,
            "candidate_id": trial.candidate_id,
            "attempt_count": trial.attempt_count,
            "seed": trial.seed,
            "scenario_type": trial.scenario_type,
            "scenario_config": scenario_config,
        },
        "candidate_parameters": parameters,
        "job_config": _job_input_snapshot(job),
    }
    # Detach nested JSON containers from SQLAlchemy mutable values before the
    # claim transaction is committed and those ORM rows can be changed.
    frozen = copy.deepcopy(snapshot)
    try:
        _canonical_json(frozen)
    except (TypeError, ValueError) as exc:
        raise TrialAttemptEvidenceError(
            "trial execution inputs must be finite JSON"
        ) from exc
    return frozen


def compile_trial_attempt_claim(
    *,
    trial: models.Trial,
    job: models.Job,
    candidate: models.CandidateParameterSet,
    worker_id: str,
    simulator_backend: str,
    claim_kind: Literal["initial", "stale-reclaim"],
    claimed_at: datetime,
    input_snapshot: Mapping[str, Any] | None = None,
) -> TrialAttemptClaimEvidenceV2:
    """Compile one content-addressed claim without retaining the worker ID."""

    frozen_inputs = (
        copy.deepcopy(dict(input_snapshot))
        if input_snapshot is not None
        else snapshot_trial_attempt_inputs(
            trial=trial,
            job=job,
            candidate=candidate,
        )
    )
    raw_trial = frozen_inputs.get("trial")
    raw_parameters = frozen_inputs.get("candidate_parameters")
    raw_job_config = frozen_inputs.get("job_config")
    if (
        not isinstance(raw_trial, dict)
        or not isinstance(raw_job_config, dict)
    ):
        raise TrialAttemptEvidenceError(
            "trial execution input snapshot has an invalid shape"
        )
    if (
        raw_trial.get("trial_id") != trial.id
        or raw_trial.get("job_id") != trial.job_id
        or raw_trial.get("candidate_id") != trial.candidate_id
        or raw_trial.get("attempt_count") != trial.attempt_count
    ):
        raise TrialAttemptEvidenceError(
            "trial execution input snapshot belongs to another claim"
        )
    lease_token = {
        "trial_id": trial.id,
        "worker_id_sha256": _sha256_text(worker_id),
        "attempt_count": trial.attempt_count,
    }
    payload: dict[str, Any] = {
        "schema_id": TRIAL_ATTEMPT_CLAIM_EVIDENCE_SCHEMA,
        "trial_id": trial.id,
        "job_id": trial.job_id,
        "candidate_id": trial.candidate_id,
        "attempt_count": trial.attempt_count,
        "claim_kind": claim_kind,
        "worker_id_sha256": lease_token["worker_id_sha256"],
        "lease_token_sha256": _sha256_id(lease_token),
        "simulator_backend": simulator_backend,
        "parameter_sha256": _sha256_id(raw_parameters),
        "scenario_sha256": _sha256_id(
            {
                "seed": raw_trial.get("seed"),
                "scenario_type": raw_trial.get("scenario_type"),
                "scenario_config": raw_trial.get("scenario_config"),
            }
        ),
        "job_config_sha256": _sha256_id(raw_job_config),
        "execution_input_sha256": _sha256_id(frozen_inputs),
        "claimed_at": _timestamp(claimed_at),
    }
    return TrialAttemptClaimEvidenceV2.model_validate(
        {"evidence_id": _sha256_id(payload), **payload}
    )


def verify_trial_attempt_claim(
    value: object,
) -> TrialAttemptClaimEvidence | None:
    if not isinstance(value, Mapping):
        return None
    schema_id = value.get("schema_id")
    model_type: (
        type[TrialAttemptClaimEvidenceV1]
        | type[TrialAttemptClaimEvidenceV2]
    )
    if schema_id == TRIAL_ATTEMPT_CLAIM_EVIDENCE_V1_SCHEMA:
        model_type = TrialAttemptClaimEvidenceV1
    elif schema_id == TRIAL_ATTEMPT_CLAIM_EVIDENCE_SCHEMA:
        model_type = TrialAttemptClaimEvidenceV2
    else:
        return None
    try:
        evidence = model_type.model_validate(value)
    except ValidationError:
        return None
    payload = evidence.model_dump(mode="json")
    evidence_id = payload.pop("evidence_id")
    return evidence if evidence_id == _sha256_id(payload) else None


def record_trial_attempt_claim(
    db: Session,
    *,
    trial: models.Trial,
    job: models.Job,
    candidate: models.CandidateParameterSet,
    worker_id: str,
    simulator_backend: str,
    claim_kind: Literal["initial", "stale-reclaim"],
    claimed_at: datetime,
    input_snapshot: Mapping[str, Any] | None = None,
) -> models.TrialExecutionAttempt:
    evidence = compile_trial_attempt_claim(
        trial=trial,
        job=job,
        candidate=candidate,
        worker_id=worker_id,
        simulator_backend=simulator_backend,
        claim_kind=claim_kind,
        claimed_at=claimed_at,
        input_snapshot=input_snapshot,
    )
    existing = db.scalar(
        select(models.TrialExecutionAttempt).where(
            models.TrialExecutionAttempt.trial_id == trial.id,
            models.TrialExecutionAttempt.attempt_count
            == trial.attempt_count,
        )
    )
    if existing is not None:
        verified = verify_trial_attempt_claim(existing.claim_evidence_json)
        if (
            verified != evidence
            or existing.claim_evidence_id != evidence.evidence_id
        ):
            raise TrialAttemptEvidenceError(
                "Trial attempt claim identity already exists with other evidence"
            )
        return existing
    attempt = models.TrialExecutionAttempt(
        id="tea_" + evidence.evidence_id.removeprefix("sha256:")[:32],
        trial_id=trial.id,
        job_id=trial.job_id,
        candidate_id=trial.candidate_id,
        attempt_count=trial.attempt_count,
        worker_id_sha256=evidence.worker_id_sha256,
        simulator_backend=simulator_backend,
        claim_evidence_id=evidence.evidence_id,
        claim_evidence_json=evidence.model_dump(mode="json"),
        claimed_at=claimed_at,
    )
    db.add(attempt)
    return attempt


def _metric_snapshot(trial: models.Trial) -> dict[str, Any] | None:
    metric = trial.metric
    if metric is None:
        return None
    return {
        "rmse": metric.rmse,
        "max_error": metric.max_error,
        "overshoot_count": metric.overshoot_count,
        "completion_time": metric.completion_time,
        "crash_flag": metric.crash_flag,
        "timeout_flag": metric.timeout_flag,
        "score": metric.score,
        "final_error": metric.final_error,
        "pass_flag": metric.pass_flag,
        "instability_flag": metric.instability_flag,
        "raw_metric_json": metric.raw_metric_json,
    }


def _artifact_counts(
    artifact_evidence: Mapping[str, Any],
    *,
    trial_id: str,
) -> tuple[int, int, int]:
    if artifact_evidence.get("schema_id") != TRIAL_ARTIFACT_EVIDENCE_SCHEMA:
        raise TrialAttemptEvidenceError(
            "attempt outcome requires Trial artifact evidence"
        )
    if artifact_evidence.get("trial_id") != trial_id:
        raise TrialAttemptEvidenceError(
            "attempt artifact evidence belongs to another Trial"
        )
    counts: list[int] = []
    for name in (
        "artifact_count",
        "sealed_artifact_count",
        "metadata_only_artifact_count",
    ):
        value = artifact_evidence.get(name)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise TrialAttemptEvidenceError(
                f"attempt artifact evidence has invalid {name}"
            )
        counts.append(value)
    if counts[1] + counts[2] != counts[0]:
        raise TrialAttemptEvidenceError("attempt artifact counts diverged")
    return counts[0], counts[1], counts[2]


def _compile_attempt_outcome(
    *,
    attempt: models.TrialExecutionAttempt,
    terminal_status: str,
    outcome_class: str,
    accepted: bool,
    failure_code: str | None,
    metric_snapshot: Mapping[str, Any] | None,
    artifact_evidence: Mapping[str, Any],
    finished_at: datetime,
    superseded_by_attempt_count: int | None,
) -> TrialAttemptOutcomeEvidenceV1:
    claim = verify_trial_attempt_claim(attempt.claim_evidence_json)
    if (
        claim is None
        or claim.evidence_id != attempt.claim_evidence_id
        or claim.trial_id != attempt.trial_id
        or claim.job_id != attempt.job_id
        or claim.candidate_id != attempt.candidate_id
        or claim.attempt_count != attempt.attempt_count
        or claim.worker_id_sha256 != attempt.worker_id_sha256
        or claim.simulator_backend != attempt.simulator_backend
    ):
        raise TrialAttemptEvidenceError(
            "Trial attempt row no longer matches its claim evidence"
        )
    artifact_count, sealed_count, metadata_count = _artifact_counts(
        artifact_evidence,
        trial_id=attempt.trial_id,
    )
    payload: dict[str, Any] = {
        "schema_id": TRIAL_ATTEMPT_OUTCOME_EVIDENCE_SCHEMA,
        "attempt_id": attempt.id,
        "claim_evidence_id": claim.evidence_id,
        "trial_id": attempt.trial_id,
        "job_id": attempt.job_id,
        "candidate_id": attempt.candidate_id,
        "attempt_count": attempt.attempt_count,
        "terminal_status": terminal_status,
        "outcome_class": outcome_class,
        "accepted": accepted,
        "failure_code": failure_code,
        "metric_sha256": (
            _sha256_id(metric_snapshot)
            if metric_snapshot is not None
            else None
        ),
        "artifact_evidence_schema": TRIAL_ARTIFACT_EVIDENCE_SCHEMA,
        "artifact_evidence_sha256": _sha256_id(artifact_evidence),
        "artifact_count": artifact_count,
        "sealed_artifact_count": sealed_count,
        "metadata_only_artifact_count": metadata_count,
        "superseded_by_attempt_count": superseded_by_attempt_count,
        "finished_at": _timestamp(finished_at),
    }
    return TrialAttemptOutcomeEvidenceV1.model_validate(
        {"evidence_id": _sha256_id(payload), **payload}
    )


def verify_trial_attempt_outcome(
    value: object,
) -> TrialAttemptOutcomeEvidenceV1 | None:
    try:
        evidence = TrialAttemptOutcomeEvidenceV1.model_validate(value)
    except ValidationError:
        return None
    payload = evidence.model_dump(mode="json")
    evidence_id = payload.pop("evidence_id")
    return evidence if evidence_id == _sha256_id(payload) else None


def _empty_artifact_evidence(trial_id: str) -> dict[str, Any]:
    return {
        "schema_id": TRIAL_ARTIFACT_EVIDENCE_SCHEMA,
        "trial_id": trial_id,
        "artifact_count": 0,
        "sealed_artifact_count": 0,
        "metadata_only_artifact_count": 0,
        "artifacts": [],
    }


def _record_attempt_outcome(
    db: Session,
    *,
    attempt: models.TrialExecutionAttempt,
    evidence: TrialAttemptOutcomeEvidenceV1,
) -> models.TrialExecutionAttemptOutcome:
    existing = db.scalar(
        select(models.TrialExecutionAttemptOutcome).where(
            models.TrialExecutionAttemptOutcome.attempt_id == attempt.id
        )
    )
    if existing is not None:
        verified = verify_trial_attempt_outcome(existing.evidence_json)
        if (
            verified != evidence
            or existing.evidence_id != evidence.evidence_id
        ):
            raise TrialAttemptEvidenceError(
                "Trial attempt already has a different terminal outcome"
            )
        return existing
    outcome = models.TrialExecutionAttemptOutcome(
        id="tao_" + evidence.evidence_id.removeprefix("sha256:")[:32],
        attempt_id=attempt.id,
        evidence_id=evidence.evidence_id,
        terminal_status=evidence.terminal_status,
        outcome_class=evidence.outcome_class,
        accepted=evidence.accepted,
        evidence_json=evidence.model_dump(mode="json"),
        finished_at=datetime.fromisoformat(
            evidence.finished_at.replace("Z", "+00:00")
        ),
    )
    db.add(outcome)
    return outcome


def record_accepted_trial_attempt_outcome(
    db: Session,
    *,
    trial: models.Trial,
    attempt: models.TrialExecutionAttempt,
    outcome_class: str,
    artifact_evidence: Mapping[str, Any],
) -> models.TrialExecutionAttemptOutcome:
    if (
        attempt.trial_id != trial.id
        or attempt.job_id != trial.job_id
        or attempt.candidate_id != trial.candidate_id
        or attempt.attempt_count != trial.attempt_count
        or trial.status not in _ACCEPTED_TERMINAL_STATUSES
        or trial.finished_at is None
    ):
        raise TrialAttemptEvidenceError(
            "accepted attempt does not match terminal logical Trial"
        )
    evidence = _compile_attempt_outcome(
        attempt=attempt,
        terminal_status=trial.status,
        outcome_class=outcome_class,
        accepted=True,
        failure_code=trial.failure_code,
        metric_snapshot=_metric_snapshot(trial),
        artifact_evidence=artifact_evidence,
        finished_at=trial.finished_at,
        superseded_by_attempt_count=None,
    )
    outcome = _record_attempt_outcome(
        db,
        attempt=attempt,
        evidence=evidence,
    )
    if trial.accepted_attempt_id not in {None, attempt.id}:
        raise TrialAttemptEvidenceError(
            "logical Trial already accepted another physical attempt"
        )
    trial.accepted_attempt_id = attempt.id
    return outcome


def record_superseded_trial_attempt_outcome(
    db: Session,
    *,
    attempt: models.TrialExecutionAttempt,
    superseded_by_attempt_count: int,
    finished_at: datetime,
) -> models.TrialExecutionAttemptOutcome:
    evidence = _compile_attempt_outcome(
        attempt=attempt,
        terminal_status="SUPERSEDED",
        outcome_class="superseded",
        accepted=False,
        failure_code=None,
        metric_snapshot=None,
        artifact_evidence=_empty_artifact_evidence(attempt.trial_id),
        finished_at=finished_at,
        superseded_by_attempt_count=superseded_by_attempt_count,
    )
    return _record_attempt_outcome(
        db,
        attempt=attempt,
        evidence=evidence,
    )


def trial_attempt_claim_matches_current_inputs(
    trial: models.Trial,
    *,
    attempt: models.TrialExecutionAttempt,
) -> bool:
    """Fail closed when mutable source rows diverge from a claim-time snapshot."""

    claim = verify_trial_attempt_claim(attempt.claim_evidence_json)
    if claim is None:
        return False
    try:
        current_inputs = snapshot_trial_attempt_inputs(
            trial=trial,
            job=trial.job,
            candidate=trial.candidate,
        )
        raw_trial = current_inputs["trial"]
        raw_parameters = current_inputs["candidate_parameters"]
        raw_job_config = current_inputs["job_config"]
    except (AttributeError, KeyError, TypeError, ValueError):
        return False
    if not isinstance(raw_trial, dict):
        return False
    execution_input_sha256 = (
        claim.execution_input_sha256
        if isinstance(claim, TrialAttemptClaimEvidenceV2)
        else None
    )
    return not (
        attempt.trial_id != trial.id
        or attempt.job_id != trial.job_id
        or attempt.candidate_id != trial.candidate_id
        or attempt.attempt_count != trial.attempt_count
        or claim.trial_id != trial.id
        or claim.job_id != trial.job_id
        or claim.candidate_id != trial.candidate_id
        or claim.attempt_count != trial.attempt_count
        or claim.parameter_sha256
        != _sha256_id(
            raw_parameters
            if execution_input_sha256 is not None
            else trial.candidate.parameter_json
        )
        or claim.scenario_sha256
        != _sha256_id(
            {
                "seed": raw_trial.get("seed"),
                "scenario_type": raw_trial.get("scenario_type"),
                "scenario_config": raw_trial.get("scenario_config"),
            }
        )
        or claim.job_config_sha256 != _sha256_id(raw_job_config)
        or (
            execution_input_sha256 is not None
            and execution_input_sha256 != _sha256_id(current_inputs)
        )
    )


def accepted_trial_attempt_evidence(
    trial: models.Trial,
    *,
    artifact_evidence: Mapping[str, Any],
) -> TrialAcceptedAttemptEvidenceV1 | None:
    attempt = trial.accepted_attempt
    if attempt is None or attempt.outcome is None:
        return None
    claim = verify_trial_attempt_claim(attempt.claim_evidence_json)
    outcome = verify_trial_attempt_outcome(attempt.outcome.evidence_json)
    if (
        claim is None
        or outcome is None
        or not trial_attempt_claim_matches_current_inputs(
            trial,
            attempt=attempt,
        )
        or not outcome.accepted
        or outcome.terminal_status == "SUPERSEDED"
        or outcome.outcome_class == "superseded"
        or attempt.claim_evidence_id != claim.evidence_id
        or claim.trial_id != trial.id
        or claim.job_id != trial.job_id
        or claim.candidate_id != trial.candidate_id
        or claim.attempt_count != trial.attempt_count
        or claim.worker_id_sha256 != attempt.worker_id_sha256
        or claim.simulator_backend != attempt.simulator_backend
        or claim.claimed_at != _timestamp(attempt.claimed_at)
        or claim.lease_token_sha256
        != _sha256_id(
            {
                "trial_id": trial.id,
                "worker_id_sha256": attempt.worker_id_sha256,
                "attempt_count": attempt.attempt_count,
            }
        )
        or attempt.outcome.evidence_id != outcome.evidence_id
        or attempt.outcome.terminal_status != outcome.terminal_status
        or attempt.outcome.outcome_class != outcome.outcome_class
        or attempt.outcome.accepted != outcome.accepted
        or _timestamp(attempt.outcome.finished_at) != outcome.finished_at
        or trial.accepted_attempt_id != attempt.id
        or attempt.trial_id != trial.id
        or attempt.job_id != trial.job_id
        or attempt.candidate_id != trial.candidate_id
        or attempt.attempt_count != trial.attempt_count
        or outcome.terminal_status != trial.status
        or outcome.failure_code != trial.failure_code
        or trial.finished_at is None
    ):
        return None
    try:
        current = _compile_attempt_outcome(
            attempt=attempt,
            terminal_status=trial.status,
            outcome_class=outcome.outcome_class,
            accepted=True,
            failure_code=trial.failure_code,
            metric_snapshot=_metric_snapshot(trial),
            artifact_evidence=artifact_evidence,
            finished_at=trial.finished_at,
            superseded_by_attempt_count=None,
        )
    except (TypeError, ValueError):
        return None
    if current != outcome:
        return None
    return TrialAcceptedAttemptEvidenceV1(
        trial_id=trial.id,
        attempt_id=attempt.id,
        attempt_count=attempt.attempt_count,
        claim_evidence_id=attempt.claim_evidence_id,
        outcome_evidence_id=outcome.evidence_id,
        terminal_status=outcome.terminal_status,
        outcome_class=outcome.outcome_class,
        metric_sha256=outcome.metric_sha256,
        artifact_evidence_sha256=outcome.artifact_evidence_sha256,
    )


def authorize_trial_attempt_deletion(
    db: Session,
    *,
    attempt: models.TrialExecutionAttempt,
    reason: str,
) -> None:
    normalized_reason = reason.strip()
    if not normalized_reason or len(normalized_reason) > 64:
        raise TrialAttemptEvidenceError(
            "Trial attempt deletion requires a bounded reason"
        )
    existing = db.get(
        models.TrialExecutionAttemptDeleteAuthorization,
        attempt.id,
    )
    if existing is not None:
        if existing.reason != normalized_reason:
            raise TrialAttemptEvidenceError(
                "Trial attempt deletion authorization reason diverged"
            )
        return
    db.add(
        models.TrialExecutionAttemptDeleteAuthorization(
            attempt_id=attempt.id,
            reason=normalized_reason,
        )
    )
    db.flush()


__all__ = [
    "TRIAL_ACCEPTED_ATTEMPT_EVIDENCE_SCHEMA",
    "TRIAL_ATTEMPT_CLAIM_EVIDENCE_SCHEMA",
    "TRIAL_ATTEMPT_CLAIM_EVIDENCE_V1_SCHEMA",
    "TRIAL_ATTEMPT_OUTCOME_EVIDENCE_SCHEMA",
    "TrialAcceptedAttemptEvidenceV1",
    "TrialAttemptClaimEvidenceV1",
    "TrialAttemptClaimEvidenceV2",
    "TrialAttemptEvidenceError",
    "TrialAttemptOutcomeEvidenceV1",
    "accepted_trial_attempt_evidence",
    "authorize_trial_attempt_deletion",
    "compile_trial_attempt_claim",
    "record_accepted_trial_attempt_outcome",
    "record_superseded_trial_attempt_outcome",
    "record_trial_attempt_claim",
    "snapshot_trial_attempt_inputs",
    "trial_attempt_claim_matches_current_inputs",
    "verify_trial_attempt_claim",
    "verify_trial_attempt_outcome",
]
