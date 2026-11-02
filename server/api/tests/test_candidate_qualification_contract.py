from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError
from sqlalchemy.orm import configure_mappers

from app import models, schemas


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _qualification_payload(**overrides: object) -> dict[str, object]:
    now = _now()
    payload: dict[str, object] = {
        "contract_schema": "dronedream.candidate-qualification/v1",
        "id": "qlf_example",
        "job_id": "job_example",
        "candidate_id": "cand_example",
        "rule_version": "screen-4-sealed-9of10-8to20-18of20/v1",
        "rule_sha256": "a" * 64,
        "holdout_contract_sha256": "b" * 64,
        "selection_snapshot_sha256": "c" * 64,
        "state": "qualified",
        "state_revision": 5,
        "qualification_sequence": 2,
        "sealed_at": now,
        "decided_at": now,
        "created_at": now,
        "updated_at": now,
    }
    payload.update(overrides)
    return payload


def _receipt_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "receipt_schema": "dronedream.qualification-trial-receipt/v1",
        "id": "qtr_example",
        "qualification_id": "qlf_example",
        "trial_id": "tri_example",
        "phase": "qualification",
        "ordinal": 10,
        "terminal_status": "COMPLETED",
        "passed": True,
        "safety_critical_failure": False,
        "effect_readback_complete": True,
        "evidence_complete": True,
        "evidence_id": "sha256:" + "d" * 64,
        "finalized_at": _now(),
    }
    payload.update(overrides)
    return payload


def test_candidate_qualification_models_freeze_two_stage_contract() -> None:
    configure_mappers()

    qualification_constraints = {
        constraint.name for constraint in models.CandidateQualification.__table__.constraints
    }
    trial_constraints = {constraint.name for constraint in models.Trial.__table__.constraints}
    receipt_constraints = {
        constraint.name for constraint in models.QualificationTrialReceipt.__table__.constraints
    }

    assert "ck_candidate_qualification_rule_v1" in qualification_constraints
    assert "uq_candidate_qualification_candidate" in qualification_constraints
    assert "uq_candidate_qualification_job_sequence" in qualification_constraints
    assert "ck_trial_evaluation_phase_binding" in trial_constraints
    assert "uq_trial_qualification_phase_ordinal" in trial_constraints
    assert "ck_qualification_trial_receipt_ordinal" in receipt_constraints
    assert "uq_qualification_trial_receipt_trial" in receipt_constraints


def test_candidate_qualification_schema_requires_exact_terminal_binding() -> None:
    qualified = schemas.CandidateQualification(**_qualification_payload())

    assert qualified.screening_required == 4
    assert qualified.qualification_initial_required == 10
    assert qualified.qualification_extended_required == 20
    assert qualified.direct_pass_min == 9
    assert qualified.extension_trigger_passes == 8
    assert qualified.extended_pass_min == 18
    assert qualified.max_candidates_per_run == 2

    with pytest.raises(ValidationError, match="server sequence"):
        schemas.CandidateQualification(**_qualification_payload(qualification_sequence=None))
    with pytest.raises(ValidationError, match="sealed_at"):
        schemas.CandidateQualification(**_qualification_payload(sealed_at=None))
    with pytest.raises(ValidationError, match="only a qualified state"):
        schemas.CandidateQualification(
            **_qualification_payload(
                state="qualification_failed",
                qualification_sequence=1,
            )
        )


def test_qualification_trial_receipt_fails_closed_on_incomplete_or_unsafe_pass() -> None:
    receipt = schemas.QualificationTrialReceipt(**_receipt_payload())
    assert receipt.passed is True

    for override in (
        {"terminal_status": "FAILED"},
        {"safety_critical_failure": True},
        {"effect_readback_complete": False},
        {"evidence_complete": False},
    ):
        with pytest.raises(ValidationError, match="complete, safe evidence"):
            schemas.QualificationTrialReceipt(**_receipt_payload(**override))

    with pytest.raises(ValidationError, match="four-repeat"):
        schemas.QualificationTrialReceipt(**_receipt_payload(phase="screening", ordinal=5))
    with pytest.raises(ValidationError):
        schemas.QualificationTrialReceipt(**_receipt_payload(evidence_id="sha256:" + "X" * 64))


def test_legacy_trial_defaults_to_optimization_without_qualification_binding() -> None:
    trial = models.Trial(
        id="tri_legacy",
        job_id="job_legacy",
        candidate_id="cand_legacy",
        seed=1,
        scenario_type="nominal",
        status="PENDING",
    )

    evaluation_phase = models.Trial.__table__.c.evaluation_phase
    assert evaluation_phase.default is not None
    assert evaluation_phase.default.arg == "optimization"
    assert evaluation_phase.server_default is not None
    assert evaluation_phase.server_default.arg == "optimization"
    assert trial.evaluation_phase is None
    assert trial.qualification_id is None
    assert trial.qualification_ordinal is None
