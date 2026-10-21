from __future__ import annotations

from copy import deepcopy

import pytest

from app import models
from app.orchestration.qualification import compile_sealed_qualification_contract
from app.orchestration.qualification_dispatch import (
    QualificationDispatchError,
    candidate_selection_snapshot_sha256,
    ensure_candidate_screening_qualification,
    qualification_runs,
    qualification_trial_binding,
    screening_runs,
    sealed_contract_for_job,
)
from app.schemas import ScenarioCaseConfig, ScenarioSuiteConfig


class _RecordingSession:
    def __init__(self) -> None:
        self.added: list[object] = []

    def add(self, value: object) -> None:
        self.added.append(value)


def _suite() -> ScenarioSuiteConfig:
    return ScenarioSuiteConfig(
        common_random_numbers=True,
        cases=[
            ScenarioCaseConfig(
                id="screen-nominal",
                scenario_type="nominal",
                seeds=[101, 102, 103, 104],
                config={"wind_mps": 0.0},
            ),
            ScenarioCaseConfig(
                id="holdout-composite",
                scenario_type="combined_perturbed",
                seeds=list(range(901, 921)),
                holdout=True,
                config={"wind_mps": 3.0, "noise_scale": 1.1},
            ),
        ],
    )


def _sealed_job() -> models.Job:
    suite = _suite()
    contract = compile_sealed_qualification_contract(suite)
    return models.Job(
        id="job-1",
        holdout_policy_version="sealed-two-stage-v1",
        holdout_contract_json=contract.model_dump(mode="json"),
        scenario_suite_json=suite.model_dump(mode="json"),
    )


def _candidate() -> models.CandidateParameterSet:
    return models.CandidateParameterSet(
        id="cand-1",
        job_id="job-1",
        generation_index=1,
        dispatch_ordinal=2,
        source_type="optimizer",
        parameter_json={"MPC_XY_P": 0.95},
        is_baseline=False,
    )


def test_known_legacy_policies_preserve_existing_dispatch_semantics() -> None:
    for policy in ("legacy-visible-v0", "continuation-independent-holdout-v1"):
        job = models.Job(id=f"job-{policy}", holdout_policy_version=policy)
        assert sealed_contract_for_job(job) is None

    with pytest.raises(QualificationDispatchError, match="unknown holdout policy"):
        sealed_contract_for_job(models.Job(id="job-unknown", holdout_policy_version="invented-v9"))


def test_sealed_contract_must_exactly_match_persisted_scenario_suite() -> None:
    job = _sealed_job()
    assert sealed_contract_for_job(job) is not None

    mutated = deepcopy(job.holdout_contract_json)
    assert isinstance(mutated, dict)
    mutated["qualification"][0]["config_json"] = '{"noise_scale":1.1,"wind_mps":4.0}'
    job.holdout_contract_json = mutated
    with pytest.raises(QualificationDispatchError, match="diverges"):
        sealed_contract_for_job(job)


def test_candidate_screening_binding_is_insert_once_and_parameter_bound() -> None:
    job = _sealed_job()
    candidate = _candidate()
    candidate.job = job
    db = _RecordingSession()

    qualification, contract = ensure_candidate_screening_qualification(  # type: ignore[arg-type]
        db,
        job=job,
        candidate=candidate,
    )
    assert qualification is not None
    assert contract is not None
    assert qualification.state == "screening"
    assert qualification.candidate_id == candidate.id
    assert db.added == [qualification]

    repeated, repeated_contract = ensure_candidate_screening_qualification(  # type: ignore[arg-type]
        db,
        job=job,
        candidate=candidate,
    )
    assert repeated is qualification
    assert repeated_contract == contract
    assert db.added == [qualification]

    candidate.parameter_json = {"MPC_XY_P": 1.05}
    with pytest.raises(QualificationDispatchError, match="insert-once"):
        ensure_candidate_screening_qualification(  # type: ignore[arg-type]
            db,
            job=job,
            candidate=candidate,
        )


def test_selection_snapshot_requires_server_dispatch_order() -> None:
    candidate = _candidate()
    candidate.dispatch_ordinal = None
    with pytest.raises(QualificationDispatchError, match="server candidate dispatch ordinal"):
        candidate_selection_snapshot_sha256(
            candidate=candidate,
            holdout_contract_sha256="a" * 64,
        )


def test_screening_and_qualification_runs_preserve_preregistered_roles() -> None:
    contract = compile_sealed_qualification_contract(_suite())

    screening = screening_runs(contract)
    first_ten = qualification_runs(contract)
    extension = qualification_runs(contract, start_ordinal=11, end_ordinal=20)

    assert [run.seed for run in screening] == [101, 102, 103, 104]
    assert all(run.holdout is False for run in screening)
    assert [run.seed for run in first_ten] == list(range(901, 911))
    assert [run.seed for run in extension] == list(range(911, 921))
    assert all(run.holdout is True for run in (*first_ten, *extension))

    with pytest.raises(QualificationDispatchError, match="ordinal slice"):
        qualification_runs(contract, start_ordinal=10, end_ordinal=21)


def test_trial_binding_matches_database_phase_constraints() -> None:
    qualification = models.CandidateQualification(id="qlf-1")
    assert qualification_trial_binding(
        qualification=qualification,
        phase="screening",
        ordinal=4,
    ) == {
        "qualification_id": "qlf-1",
        "evaluation_phase": "screening",
        "qualification_ordinal": 4,
    }
    assert (
        qualification_trial_binding(
            qualification=qualification,
            phase="qualification",
            ordinal=20,
        )["qualification_ordinal"]
        == 20
    )
    with pytest.raises(QualificationDispatchError, match="phase/ordinal"):
        qualification_trial_binding(
            qualification=qualification,
            phase="screening",
            ordinal=5,
        )
