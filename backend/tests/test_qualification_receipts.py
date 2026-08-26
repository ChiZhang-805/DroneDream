from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from app import models
from app.orchestration.attempt_evidence import TrialAcceptedAttemptEvidenceV1
from app.orchestration.qualification_receipts import (
    QualificationReceiptError,
    QualificationTrialEvidenceV1,
    compile_qualification_trial_evidence,
    record_qualification_trial_receipt,
    require_qualification_trial_receipt,
)


def _sha256_id(value: object) -> str:
    payload = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _artifact_evidence(*, trial_id: str = "tri-1") -> dict[str, object]:
    return {
        "schema_id": "dronedream.trial-artifact-evidence/v1",
        "trial_id": trial_id,
        "artifact_count": 1,
        "sealed_artifact_count": 1,
        "metadata_only_artifact_count": 0,
        "artifacts": [
            {
                "artifact_id": "art-1",
                "content_evidence": "sealed-bytes",
                "content_sha256": "a" * 64,
            }
        ],
    }


def _accepted(
    *,
    terminal_status: str,
    outcome_class: str,
    artifact_evidence: dict[str, object],
    metric_sha256: str | None,
) -> TrialAcceptedAttemptEvidenceV1:
    return TrialAcceptedAttemptEvidenceV1.model_validate(
        {
            "trial_id": "tri-1",
            "attempt_id": "attempt-1",
            "attempt_count": 1,
            "claim_evidence_id": "sha256:" + "1" * 64,
            "outcome_evidence_id": "sha256:" + "2" * 64,
            "terminal_status": terminal_status,
            "outcome_class": outcome_class,
            "metric_sha256": metric_sha256,
            "artifact_evidence_sha256": _sha256_id(artifact_evidence),
        }
    )


def _compile(**overrides: object) -> QualificationTrialEvidenceV1:
    payload: dict[str, object] = {
        "qualification_id": "qlf-1",
        "trial_id": "tri-1",
        "job_id": "job-1",
        "candidate_id": "cand-1",
        "holdout_contract_sha256": "f" * 64,
        "phase": "screening",
        "ordinal": 1,
        "accepted_attempt": None,
        "artifact_evidence": None,
        "metric_snapshot": None,
        "failure_code": None,
        "finalized_at": datetime(2026, 8, 4, 1, 2, 3, tzinfo=timezone.utc),
    }
    payload.update(overrides)
    return compile_qualification_trial_evidence(**payload)  # type: ignore[arg-type]


def test_missing_accepted_attempt_is_content_addressed_indeterminate() -> None:
    receipt = _compile()

    assert receipt.terminal_status == "INDETERMINATE"
    assert receipt.passed is False
    assert receipt.evidence_complete is False
    assert receipt.evidence_failure_reason == "missing_accepted_attempt"
    assert receipt.accepted_attempt_evidence_sha256 is None
    assert receipt.artifact_evidence_sha256 is None
    assert receipt.finalized_at == "2026-08-04T01:02:03+00:00"

    payload = receipt.model_dump(mode="json")
    payload["candidate_id"] = "cand-tampered"
    with pytest.raises(ValidationError, match="ID does not match"):
        QualificationTrialEvidenceV1.model_validate(payload)


def test_domain_failure_remains_visible_and_cannot_pass() -> None:
    artifacts = _artifact_evidence()
    accepted = _accepted(
        terminal_status="FAILED",
        outcome_class="domain_failure",
        artifact_evidence=artifacts,
        metric_sha256=None,
    )

    receipt = _compile(
        accepted_attempt=accepted,
        artifact_evidence=artifacts,
        failure_code="PX4_CRASH",
    )

    assert receipt.terminal_status == "FAILED"
    assert receipt.safety_critical_failure is True
    assert receipt.passed is False
    assert receipt.evidence_failure_reason == "terminal_without_px4_metric"


def test_bare_pass_flag_without_valid_px4_evidence_cannot_qualify() -> None:
    artifacts = _artifact_evidence()
    metric = {
        "rmse": 0.1,
        "max_error": 0.2,
        "overshoot_count": 0,
        "completion_time": 3.0,
        "crash_flag": False,
        "timeout_flag": False,
        "score": 0.3,
        "final_error": 0.1,
        "pass_flag": True,
        "instability_flag": False,
        "raw_metric_json": {},
    }
    accepted = _accepted(
        terminal_status="COMPLETED",
        outcome_class="success",
        artifact_evidence=artifacts,
        metric_sha256=_sha256_id(metric),
    )

    receipt = _compile(
        accepted_attempt=accepted,
        artifact_evidence=artifacts,
        metric_snapshot=metric,
    )

    assert receipt.passed is False
    assert receipt.effect_readback_complete is False
    assert receipt.evidence_complete is False
    assert receipt.evidence_failure_reason == "metric_evidence_invalid"


def test_accepted_attempt_hash_divergence_fails_hard() -> None:
    artifacts = _artifact_evidence()
    accepted = _accepted(
        terminal_status="FAILED",
        outcome_class="infrastructure_failure",
        artifact_evidence=artifacts,
        metric_sha256=None,
    )
    tampered = _artifact_evidence(trial_id="tri-other")

    with pytest.raises(QualificationReceiptError, match="artifact evidence diverged"):
        _compile(accepted_attempt=accepted, artifact_evidence=tampered)


class _RecordingSession:
    def __init__(self) -> None:
        self.added: list[object] = []

    def add(self, value: object) -> None:
        self.added.append(value)


def _bound_trial() -> models.Trial:
    qualification = models.CandidateQualification(
        id="qlf-1",
        job_id="job-1",
        candidate_id="cand-1",
        contract_schema="dronedream.candidate-qualification/v1",
        rule_version="screen-4-sealed-9of10-8to20-18of20/v1",
        rule_sha256="a" * 64,
        holdout_contract_sha256="f" * 64,
        selection_snapshot_sha256="b" * 64,
        state="screening",
        state_revision=1,
    )
    trial = models.Trial(
        id="tri-1",
        job_id="job-1",
        candidate_id="cand-1",
        qualification_id="qlf-1",
        evaluation_phase="screening",
        qualification_ordinal=1,
        seed=101,
        scenario_type="nominal",
        status="FAILED",
        finished_at=datetime(2026, 8, 4, 1, 2, 3, tzinfo=timezone.utc),
    )
    trial.qualification = qualification
    return trial


def test_record_receipt_is_insert_once_and_revalidates_existing_binding() -> None:
    trial = _bound_trial()
    db = _RecordingSession()

    first = record_qualification_trial_receipt(  # type: ignore[arg-type]
        db,
        trial=trial,
        accepted_attempt=None,
        artifact_evidence=None,
    )
    second = record_qualification_trial_receipt(  # type: ignore[arg-type]
        db,
        trial=trial,
        accepted_attempt=None,
        artifact_evidence=None,
    )

    assert first is second
    assert db.added == [first]
    assert require_qualification_trial_receipt(first, trial=trial).terminal_status == (
        "INDETERMINATE"
    )

    first.passed = True
    with pytest.raises(QualificationReceiptError, match="scalars diverged"):
        require_qualification_trial_receipt(first, trial=trial)


def test_record_receipt_rejects_nonterminal_or_mismatched_attempt() -> None:
    trial = _bound_trial()
    db = _RecordingSession()
    trial.status = "RUNNING"
    with pytest.raises(QualificationReceiptError, match="not a terminal"):
        record_qualification_trial_receipt(  # type: ignore[arg-type]
            db,
            trial=trial,
            accepted_attempt=None,
            artifact_evidence=None,
        )

    trial.status = "FAILED"
    artifacts = _artifact_evidence()
    accepted = _accepted(
        terminal_status="CANCELLED",
        outcome_class="cancelled",
        artifact_evidence=artifacts,
        metric_sha256=None,
    )
    with pytest.raises(QualificationReceiptError, match="terminal status diverged"):
        record_qualification_trial_receipt(  # type: ignore[arg-type]
            db,
            trial=trial,
            accepted_attempt=accepted,
            artifact_evidence=artifacts,
        )
