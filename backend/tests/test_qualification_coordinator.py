from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone

import pytest

from app import models
from app.orchestration import aggregation
from app.orchestration.acceptance import AcceptanceResult
from app.orchestration.first_qualified import freeze_first_qualified_candidate
from app.orchestration.qualification import (
    QUALIFICATION_CONTRACT_SCHEMA,
    QUALIFICATION_RULE_SHA256,
    QUALIFICATION_RULE_VERSION,
    compile_sealed_qualification_contract,
    sealed_qualification_contract_sha256,
)
from app.orchestration.qualification_coordinator import (
    QualificationCoordinatorError,
    advance_sealed_qualifications,
    qualified_candidate_evidence_projection,
)
from app.orchestration.qualification_receipts import (
    QUALIFICATION_TRIAL_EVIDENCE_SCHEMA,
)
from app.schemas import ScenarioCaseConfig, ScenarioSuiteConfig


class _RecordingSession:
    def __init__(self) -> None:
        self.added: list[object] = []

    def add(self, value: object) -> None:
        if isinstance(value, models.Trial) and value.id is None:
            value.id = (
                f"tri-{value.qualification_id}-{value.evaluation_phase}-"
                f"{value.qualification_ordinal}"
            )
        self.added.append(value)

    class _NoRows:
        @staticmethod
        def first() -> None:
            return None

    def scalars(self, _statement: object) -> _NoRows:
        return self._NoRows()


def _sha256_id(value: object) -> str:
    payload = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _suite() -> ScenarioSuiteConfig:
    return ScenarioSuiteConfig(
        cases=[
            ScenarioCaseConfig(
                id="screen",
                scenario_type="nominal",
                seeds=[101, 102, 103, 104],
            ),
            ScenarioCaseConfig(
                id="holdout",
                scenario_type="combined_perturbed",
                seeds=list(range(901, 921)),
                holdout=True,
                config={"wind_mps": 3.0},
            ),
        ]
    )


def _receipt(
    qualification: models.CandidateQualification,
    trial: models.Trial,
    *,
    passed: bool = True,
) -> models.QualificationTrialReceipt:
    finalized_at = trial.finished_at or datetime(
        2026, 8, 4, 1, 2, 3, tzinfo=timezone.utc
    )
    payload: dict[str, object] = {
        "schema_id": QUALIFICATION_TRIAL_EVIDENCE_SCHEMA,
        "receipt_schema": "dronedream.qualification-trial-receipt/v1",
        "qualification_id": qualification.id,
        "trial_id": trial.id,
        "job_id": qualification.job_id,
        "candidate_id": qualification.candidate_id,
        "holdout_contract_sha256": qualification.holdout_contract_sha256,
        "phase": trial.evaluation_phase,
        "ordinal": trial.qualification_ordinal,
        "terminal_status": "COMPLETED",
        "passed": passed,
        "safety_critical_failure": False,
        "effect_readback_complete": True,
        "evidence_complete": True,
        "evidence_failure_reason": "none",
        "accepted_attempt_evidence_sha256": "sha256:" + "1" * 64,
        "artifact_evidence_sha256": "sha256:" + "2" * 64,
        "metric_sha256": "sha256:" + "3" * 64,
        "px4_outcome_policy_id": "sha256:" + "4" * 64,
        "px4_outcome_evidence_id": "sha256:" + "5" * 64,
        "failure_code": None,
        "finalized_at": finalized_at.isoformat(),
    }
    evidence_id = _sha256_id(payload)
    evidence = {"evidence_id": evidence_id, **payload}
    receipt = models.QualificationTrialReceipt(
        id=f"qtr-{qualification.id}-{trial.qualification_ordinal}",
        qualification_id=qualification.id,
        trial_id=trial.id,
        receipt_schema="dronedream.qualification-trial-receipt/v1",
        phase=trial.evaluation_phase,
        ordinal=int(trial.qualification_ordinal or 0),
        terminal_status="COMPLETED",
        passed=passed,
        safety_critical_failure=False,
        effect_readback_complete=True,
        evidence_complete=True,
        evidence_id=evidence_id,
        evidence_json=evidence,
        finalized_at=finalized_at,
    )
    receipt.trial = trial
    receipt.qualification = qualification
    return receipt


def _job_with_screened_candidates(
    *,
    max_total_trials: int = 100,
) -> models.Job:
    suite = _suite()
    contract = compile_sealed_qualification_contract(suite)
    job = models.Job(
        id="job-1",
        status="FINALIZING",
        holdout_policy_version="sealed-two-stage-v1",
        holdout_contract_json=contract.model_dump(mode="json"),
        scenario_suite_json=suite.model_dump(mode="json"),
        advanced_scenario_config_json=None,
        progress_total_trials=12,
        max_total_trials=max_total_trials,
        next_qualification_sequence=1,
    )
    for candidate_id, generation, dispatch in (
        ("cand-z", 1, 3),
        ("cand-a", 0, 2),
        ("cand-m", 0, 1),
    ):
        candidate = models.CandidateParameterSet(
            id=candidate_id,
            job_id=job.id,
            generation_index=generation,
            dispatch_ordinal=dispatch,
            source_type="optimizer",
            parameter_json={"MPC_XY_P": 0.9 + dispatch / 100},
            optimizer_metadata_json={},
            trial_count=4,
        )
        candidate.job = job
        qualification = models.CandidateQualification(
            id=f"qlf-{candidate_id}",
            job_id=job.id,
            candidate_id=candidate.id,
            contract_schema=QUALIFICATION_CONTRACT_SCHEMA,
            rule_version=QUALIFICATION_RULE_VERSION,
            rule_sha256=QUALIFICATION_RULE_SHA256,
            holdout_contract_sha256=sealed_qualification_contract_sha256(contract),
            selection_snapshot_sha256=("a" * 64),
            state="screening",
            state_revision=1,
        )
        qualification.job = job
        qualification.candidate = candidate
        for ordinal, seed in enumerate((101, 102, 103, 104), start=1):
            trial = models.Trial(
                id=f"tri-{candidate_id}-{ordinal}",
                job_id=job.id,
                candidate_id=candidate.id,
                qualification_id=qualification.id,
                evaluation_phase="screening",
                qualification_ordinal=ordinal,
                seed=seed,
                scenario_type="nominal",
                scenario_config_json={"holdout": False},
                status="COMPLETED",
                finished_at=datetime(2026, 8, 4, 1, 2, 3, tzinfo=timezone.utc),
            )
            trial.job = job
            trial.candidate = candidate
            trial.qualification = qualification
            _receipt(qualification, trial)
    return job


def test_coordinator_selects_two_by_server_order_and_dispatches_exact_holdout() -> None:
    job = _job_with_screened_candidates()
    db = _RecordingSession()

    result = advance_sealed_qualifications(db, job=job)  # type: ignore[arg-type]

    assert result.dispatched_trials == 20
    assert result.state_changes == 3
    assert job.progress_total_trials == 32
    assert job.next_qualification_sequence == 3
    by_id = {item.candidate_id: item for item in job.candidate_qualifications}
    assert by_id["cand-m"].qualification_sequence == 1
    assert by_id["cand-a"].qualification_sequence == 2
    assert by_id["cand-z"].qualification_sequence is None
    assert by_id["cand-z"].state == "cancelled"
    for candidate_id in ("cand-m", "cand-a"):
        qualification = by_id[candidate_id]
        assert qualification.state == "qualification_10"
        holdout_trials = [
            trial
            for trial in qualification.trials
            if trial.evaluation_phase == "qualification"
        ]
        assert [trial.qualification_ordinal for trial in holdout_trials] == list(
            range(1, 11)
        )
        assert [trial.seed for trial in holdout_trials] == list(range(901, 911))
        assert all(trial.scenario_config_json["holdout"] is True for trial in holdout_trials)
        assert qualification.candidate.trial_count == 14


def test_coordinator_fails_closed_before_exceeding_trial_cap() -> None:
    job = _job_with_screened_candidates(max_total_trials=31)

    with pytest.raises(QualificationCoordinatorError, match="Trial cap"):
        advance_sealed_qualifications(  # type: ignore[arg-type]
            _RecordingSession(),
            job=job,
        )


def test_first_qualified_stops_before_another_candidate_extension() -> None:
    job = _job_with_screened_candidates()
    db = _RecordingSession()
    advance_sealed_qualifications(db, job=job)  # type: ignore[arg-type]
    by_id = {item.candidate_id: item for item in job.candidate_qualifications}
    extending = by_id["cand-m"]
    direct = by_id["cand-a"]
    for qualification, pass_count in ((extending, 8), (direct, 9)):
        holdout_trials = [
            trial
            for trial in qualification.trials
            if trial.evaluation_phase == "qualification"
        ]
        for index, trial in enumerate(holdout_trials, start=1):
            trial.status = "COMPLETED"
            trial.finished_at = datetime(2026, 8, 4, 1, 3, 3, tzinfo=timezone.utc)
            _receipt(qualification, trial, passed=index <= pass_count)

    result = advance_sealed_qualifications(db, job=job)  # type: ignore[arg-type]

    assert result.dispatched_trials == 0
    assert result.qualified_candidates == ("cand-a",)
    assert direct.state == "qualified"
    assert direct.candidate.qualification_sequence == 2
    assert direct.candidate.qualified_at == direct.decided_at
    assert extending.state == "cancelled"
    assert len(extending.trials) == 14
    projection = qualified_candidate_evidence_projection(direct.candidate)
    assert projection is not None
    assert projection["qualification_target"] == 10
    assert projection["qualification_passed"] == 9
    configured = aggregation._configured_scenario_contract(direct.candidate)
    assert configured is not None
    expected_cases, expects_holdout = configured
    assert expected_cases[("screen", False)] == 4
    assert expected_cases[("holdout", True)] == 10
    assert sum(expected_cases.values()) == 14
    assert expects_holdout is True

    aware_evidence_id = projection["evidence_id"]
    assert direct.decided_at is not None
    direct.decided_at = direct.decided_at.replace(tzinfo=None)
    assert direct.candidate.qualified_at is not None
    direct.candidate.qualified_at = direct.candidate.qualified_at.replace(tzinfo=None)
    roundtrip_projection = qualified_candidate_evidence_projection(direct.candidate)
    assert roundtrip_projection is not None
    assert roundtrip_projection["evidence_id"] == aware_evidence_id
    assert roundtrip_projection["decided_at"].endswith("Z")

    original_rule_sha256 = direct.rule_sha256
    direct.rule_sha256 = "f" * 64
    with pytest.raises(QualificationCoordinatorError, match="frozen rule"):
        qualified_candidate_evidence_projection(direct.candidate)
    direct.rule_sha256 = original_rule_sha256


def test_eight_of_ten_extends_only_when_no_candidate_qualified() -> None:
    job = _job_with_screened_candidates()
    db = _RecordingSession()
    advance_sealed_qualifications(db, job=job)  # type: ignore[arg-type]
    by_id = {item.candidate_id: item for item in job.candidate_qualifications}
    extending = by_id["cand-m"]
    failing = by_id["cand-a"]
    for qualification, pass_count in ((extending, 8), (failing, 7)):
        holdout_trials = [
            trial
            for trial in qualification.trials
            if trial.evaluation_phase == "qualification"
        ]
        for index, trial in enumerate(holdout_trials, start=1):
            trial.status = "COMPLETED"
            trial.finished_at = datetime(2026, 8, 4, 1, 3, 3, tzinfo=timezone.utc)
            _receipt(qualification, trial, passed=index <= pass_count)

    result = advance_sealed_qualifications(db, job=job)  # type: ignore[arg-type]

    assert result.dispatched_trials == 10
    assert result.qualified_candidates == ()
    assert extending.state == "qualification_extended_20"
    assert extending.candidate.trial_count == 24
    assert len(extending.trials) == 24
    assert [
        trial.qualification_ordinal
        for trial in extending.trials
        if trial.evaluation_phase == "qualification"
    ] == list(range(1, 21))
    assert failing.state == "qualification_failed"


def test_first_qualified_freeze_reuses_server_verdict_order_and_time() -> None:
    job = _job_with_screened_candidates()
    job.created_at = datetime(2026, 8, 4, 1, 0, 0, tzinfo=timezone.utc)
    job.completion_policy = "first_qualified_stop"
    job.current_generation = 0
    job.provider_turns_attempted = 0
    job.provider_turns_succeeded = 0
    db = _RecordingSession()
    advance_sealed_qualifications(db, job=job)  # type: ignore[arg-type]
    by_id = {item.candidate_id: item for item in job.candidate_qualifications}
    direct = by_id["cand-a"]
    other = by_id["cand-m"]
    for qualification, pass_count in ((other, 7), (direct, 9)):
        for index, trial in enumerate(
            (
                item
                for item in qualification.trials
                if item.evaluation_phase == "qualification"
            ),
            start=1,
        ):
            trial.status = "COMPLETED"
            trial.finished_at = datetime(2026, 8, 4, 1, 3, 3, tzinfo=timezone.utc)
            _receipt(qualification, trial, passed=index <= pass_count)
    advance_sealed_qualifications(db, job=job)  # type: ignore[arg-type]
    assert direct.decided_at is not None
    frozen_decision_time = direct.decided_at
    next_sequence_before_freeze = job.next_qualification_sequence

    receipt = freeze_first_qualified_candidate(  # type: ignore[arg-type]
        db,
        job=job,
        qualified=[
            (
                direct.candidate,
                AcceptanceResult(
                    passed=True,
                    reason="sealed qualification passed",
                    pass_rate=0.9,
                    completion_rate=1.0,
                    rmse=0.25,
                    max_error=0.5,
                ),
            )
        ],
        frozen_at=frozen_decision_time,
    )

    assert receipt is not None
    assert receipt.candidate_id == "cand-a"
    assert receipt.qualification_sequence == 2
    assert receipt.frozen_at == frozen_decision_time
    assert job.first_qualified_at == frozen_decision_time
    assert job.next_qualification_sequence == next_sequence_before_freeze
