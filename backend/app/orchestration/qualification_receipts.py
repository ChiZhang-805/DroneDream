"""Content-addressed terminal evidence for sealed qualification Trials."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from app.orchestration.attempt_evidence import TrialAcceptedAttemptEvidenceV1
from app.orchestration.qualification import (
    QUALIFICATION_TRIAL_RECEIPT_SCHEMA,
    QualificationContractError,
    QualificationPhase,
    QualificationTerminalStatus,
)
from app.simulator.px4_metric_evidence import (
    Px4CoreMetricEvidenceError,
    Px4OutcomeEvidenceV1,
    Px4OutcomePolicyV1,
    require_px4_outcome_binding,
)
from app.storage.evidence import TRIAL_ARTIFACT_EVIDENCE_SCHEMA
from app.time_utils import canonical_utc_iso

Sha256Id = Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]
Sha256Hex = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]

QUALIFICATION_TRIAL_EVIDENCE_SCHEMA: Literal["dronedream.qualification-trial-evidence/v1"] = (
    "dronedream.qualification-trial-evidence/v1"
)

EvidenceFailureReason = Literal[
    "none",
    "missing_accepted_attempt",
    "missing_or_unsealed_artifacts",
    "terminal_without_px4_metric",
    "metric_evidence_invalid",
    "synthetic_px4_evidence",
]

_TIMEOUT_FAILURE_CODES = frozenset(
    {
        "SIMULATION_TIMEOUT",
        "EXECUTION_TIMEOUT",
        "TIMEOUT",
    }
)


class QualificationReceiptError(QualificationContractError):
    """Raised when a terminal Trial cannot be bound to immutable evidence."""


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


class QualificationTrialEvidenceV1(BaseModel):
    """Secret-free, immutable projection of one accepted physical attempt."""

    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    schema_id: Literal["dronedream.qualification-trial-evidence/v1"] = (
        QUALIFICATION_TRIAL_EVIDENCE_SCHEMA
    )
    evidence_id: Sha256Id
    receipt_schema: Literal["dronedream.qualification-trial-receipt/v1"] = (
        "dronedream.qualification-trial-receipt/v1"
    )
    qualification_id: str = Field(min_length=1, max_length=128)
    trial_id: str = Field(min_length=1, max_length=128)
    job_id: str = Field(min_length=1, max_length=128)
    candidate_id: str = Field(min_length=1, max_length=128)
    holdout_contract_sha256: Sha256Hex
    phase: QualificationPhase
    ordinal: int = Field(ge=1, le=20)
    terminal_status: QualificationTerminalStatus
    passed: bool
    safety_critical_failure: bool
    effect_readback_complete: bool
    evidence_complete: bool
    evidence_failure_reason: EvidenceFailureReason
    accepted_attempt_evidence_sha256: Sha256Id | None
    artifact_evidence_sha256: Sha256Id | None
    metric_sha256: Sha256Id | None
    px4_outcome_policy_id: Sha256Id | None
    px4_outcome_evidence_id: Sha256Id | None
    failure_code: str | None = Field(default=None, max_length=128)
    finalized_at: str = Field(min_length=20, max_length=64)

    @model_validator(mode="after")
    def _validate_content_address_and_verdict(self) -> QualificationTrialEvidenceV1:
        payload = self.model_dump(mode="json")
        evidence_id = payload.pop("evidence_id")
        if evidence_id != _sha256_id(payload):
            raise ValueError("qualification Trial evidence ID does not match its content")
        if self.phase == "screening" and self.ordinal > 4:
            raise ValueError("screening ordinal exceeds the four-repeat gate")
        if self.evidence_complete != (self.evidence_failure_reason == "none"):
            raise ValueError("qualification evidence completeness and reason diverged")
        if self.passed and (
            self.terminal_status != "COMPLETED"
            or self.safety_critical_failure
            or not self.effect_readback_complete
            or not self.evidence_complete
        ):
            raise ValueError("passing qualification evidence violates a mandatory gate")
        return self


def _artifact_projection(
    artifact_evidence: Mapping[str, Any] | None,
    *,
    trial_id: str,
) -> tuple[str | None, bool]:
    if artifact_evidence is None:
        return None, False
    try:
        if (
            artifact_evidence.get("schema_id") != TRIAL_ARTIFACT_EVIDENCE_SCHEMA
            or artifact_evidence.get("trial_id") != trial_id
        ):
            return None, False
        total_raw = artifact_evidence.get("artifact_count")
        sealed_raw = artifact_evidence.get("sealed_artifact_count")
        metadata_raw = artifact_evidence.get("metadata_only_artifact_count")
        if (
            isinstance(total_raw, bool)
            or not isinstance(total_raw, int)
            or total_raw < 0
            or isinstance(sealed_raw, bool)
            or not isinstance(sealed_raw, int)
            or sealed_raw < 0
            or isinstance(metadata_raw, bool)
            or not isinstance(metadata_raw, int)
            or metadata_raw < 0
        ):
            return None, False
        total, sealed, metadata_only = total_raw, sealed_raw, metadata_raw
        if sealed + metadata_only != total:
            return None, False
        digest = _sha256_id(artifact_evidence)
    except (TypeError, ValueError):
        return None, False
    return digest, total > 0 and sealed == total and metadata_only == 0


def _terminal_status(
    accepted_attempt: TrialAcceptedAttemptEvidenceV1 | None,
    *,
    failure_code: str | None,
) -> QualificationTerminalStatus:
    if accepted_attempt is None:
        return "INDETERMINATE"
    if accepted_attempt.terminal_status == "FAILED" and failure_code in _TIMEOUT_FAILURE_CODES:
        return "TIMEOUT"
    return accepted_attempt.terminal_status


def compile_qualification_trial_evidence(
    *,
    qualification_id: str,
    trial_id: str,
    job_id: str,
    candidate_id: str,
    holdout_contract_sha256: str,
    phase: QualificationPhase,
    ordinal: int,
    accepted_attempt: TrialAcceptedAttemptEvidenceV1 | None,
    artifact_evidence: Mapping[str, Any] | None,
    metric_snapshot: Mapping[str, Any] | None,
    failure_code: str | None,
    finalized_at: datetime,
) -> QualificationTrialEvidenceV1:
    """Compile one fail-closed receipt without trusting a bare ``pass_flag``."""

    timestamp = canonical_utc_iso(finalized_at)
    if timestamp is None:
        raise QualificationReceiptError("qualification Trial requires a UTC finalization time")

    accepted_sha256: str | None = None
    if accepted_attempt is not None:
        if accepted_attempt.trial_id != trial_id:
            raise QualificationReceiptError("accepted attempt belongs to another Trial")
        accepted_sha256 = _sha256_id(accepted_attempt.model_dump(mode="json"))

    artifact_sha256, artifacts_complete = _artifact_projection(
        artifact_evidence,
        trial_id=trial_id,
    )
    if (
        accepted_attempt is not None
        and artifact_sha256 != accepted_attempt.artifact_evidence_sha256
    ):
        raise QualificationReceiptError("accepted attempt artifact evidence diverged")

    metric_sha256: str | None = None
    px4_policy_id: str | None = None
    px4_evidence_id: str | None = None
    px4_binding_valid = False
    physical_evidence = False
    effect_readback_complete = False
    safety_critical_failure = bool(
        accepted_attempt is not None and accepted_attempt.outcome_class == "domain_failure"
    )
    px4_passed = False

    if metric_snapshot is not None:
        try:
            metric_sha256 = _sha256_id(metric_snapshot)
        except (TypeError, ValueError) as exc:
            raise QualificationReceiptError("qualification metric is not finite JSON") from exc
        if accepted_attempt is None or accepted_attempt.metric_sha256 != metric_sha256:
            raise QualificationReceiptError("accepted attempt metric evidence diverged")
        raw_metric = metric_snapshot.get("raw_metric_json")
        try:
            if not isinstance(raw_metric, Mapping):
                raise ValueError("PX4 raw metric is missing")
            policy = Px4OutcomePolicyV1.model_validate(raw_metric.get("px4_outcome_policy"))
            outcome = Px4OutcomeEvidenceV1.model_validate(raw_metric.get("px4_outcome_evidence"))
            require_px4_outcome_binding(metric_snapshot, policy=policy, evidence=outcome)
            px4_policy_id = policy.policy_id
            px4_evidence_id = outcome.evidence_id
            px4_binding_valid = True
            physical_evidence = not outcome.synthetic
            effect_readback_complete = physical_evidence and outcome.scenario_effects_ready
            safety_critical_failure = (
                safety_critical_failure
                or outcome.crash_flag
                or outcome.timeout_flag
                or outcome.instability_flag
            )
            px4_passed = outcome.pass_flag
        except (Px4CoreMetricEvidenceError, TypeError, ValueError, ValidationError):
            px4_binding_valid = False

    terminal_status = _terminal_status(accepted_attempt, failure_code=failure_code)
    if accepted_attempt is None:
        reason: EvidenceFailureReason = "missing_accepted_attempt"
    elif not artifacts_complete:
        reason = "missing_or_unsealed_artifacts"
    elif terminal_status != "COMPLETED" or metric_snapshot is None:
        reason = "terminal_without_px4_metric"
    elif not px4_binding_valid:
        reason = "metric_evidence_invalid"
    elif not physical_evidence:
        reason = "synthetic_px4_evidence"
    else:
        reason = "none"
    evidence_complete = reason == "none"
    passed = bool(
        terminal_status == "COMPLETED"
        and metric_snapshot is not None
        and metric_snapshot.get("pass_flag") is True
        and px4_passed
        and not safety_critical_failure
        and effect_readback_complete
        and evidence_complete
    )

    payload: dict[str, object] = {
        "schema_id": QUALIFICATION_TRIAL_EVIDENCE_SCHEMA,
        "receipt_schema": QUALIFICATION_TRIAL_RECEIPT_SCHEMA,
        "qualification_id": qualification_id,
        "trial_id": trial_id,
        "job_id": job_id,
        "candidate_id": candidate_id,
        "holdout_contract_sha256": holdout_contract_sha256,
        "phase": phase,
        "ordinal": ordinal,
        "terminal_status": terminal_status,
        "passed": passed,
        "safety_critical_failure": safety_critical_failure,
        "effect_readback_complete": effect_readback_complete,
        "evidence_complete": evidence_complete,
        "evidence_failure_reason": reason,
        "accepted_attempt_evidence_sha256": accepted_sha256,
        "artifact_evidence_sha256": artifact_sha256,
        "metric_sha256": metric_sha256,
        "px4_outcome_policy_id": px4_policy_id,
        "px4_outcome_evidence_id": px4_evidence_id,
        "failure_code": failure_code,
        "finalized_at": timestamp,
    }
    return QualificationTrialEvidenceV1.model_validate(
        {"evidence_id": _sha256_id(payload), **payload}
    )


__all__ = [
    "QUALIFICATION_TRIAL_EVIDENCE_SCHEMA",
    "QualificationReceiptError",
    "QualificationTrialEvidenceV1",
    "compile_qualification_trial_evidence",
]
