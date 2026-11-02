from __future__ import annotations

import pytest

from app import models
from app.orchestration.job_manager import (
    _dispatch_baseline_trials,
    _dispatch_llm_candidate_trials,
    _dispatch_optimizer_trials,
)
from app.orchestration.qualification import compile_sealed_qualification_contract
from app.schemas import ScenarioCaseConfig, ScenarioSuiteConfig


class _RecordingSession:
    def __init__(self) -> None:
        self.added: list[object] = []
        self._trial_counter = 0

    def add(self, value: object) -> None:
        self.added.append(value)

    def flush(self) -> None:
        for value in self.added:
            if isinstance(value, models.Trial) and value.id is None:
                self._trial_counter += 1
                value.id = f"tri-{self._trial_counter}"


def _sealed_job() -> models.Job:
    suite = ScenarioSuiteConfig(
        cases=[
            ScenarioCaseConfig(
                id="screen",
                scenario_type="nominal",
                seeds=[101, 102, 103, 104],
                config={"wind_mps": 0.0},
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
    contract = compile_sealed_qualification_contract(suite)
    return models.Job(
        id="job-1",
        holdout_policy_version="sealed-two-stage-v1",
        holdout_contract_json=contract.model_dump(mode="json"),
        scenario_suite_json=suite.model_dump(mode="json"),
        advanced_scenario_config_json=None,
    )


def _candidate(
    *,
    candidate_id: str,
    source_type: str,
    baseline: bool,
) -> models.CandidateParameterSet:
    return models.CandidateParameterSet(
        id=candidate_id,
        job_id="job-1",
        generation_index=0 if baseline else 1,
        dispatch_ordinal=1,
        source_type=source_type,
        parameter_json={"MPC_XY_P": 0.95},
        optimizer_metadata_json={} if source_type == "optimizer" else None,
        is_baseline=baseline,
    )


@pytest.mark.parametrize("dispatch_kind", ["baseline", "llm", "optimizer"])
def test_all_candidate_sources_dispatch_only_four_bound_screening_trials(
    dispatch_kind: str,
) -> None:
    job = _sealed_job()
    db = _RecordingSession()
    candidate = _candidate(
        candidate_id=f"cand-{dispatch_kind}",
        source_type=(
            "baseline"
            if dispatch_kind == "baseline"
            else "llm_optimizer"
            if dispatch_kind == "llm"
            else "optimizer"
        ),
        baseline=dispatch_kind == "baseline",
    )
    candidate.job = job

    if dispatch_kind == "baseline":
        trials = _dispatch_baseline_trials(db, job, candidate)  # type: ignore[arg-type]
    elif dispatch_kind == "llm":
        trials = _dispatch_llm_candidate_trials(  # type: ignore[arg-type]
            db,
            job,
            candidate,
            trials_per_candidate=99,
        )
    else:
        trials = _dispatch_optimizer_trials(  # type: ignore[arg-type]
            db,
            job,
            candidate,
            trials_per_candidate=99,
        )

    assert len(trials) == 4
    assert candidate.trial_count == 4
    assert candidate.qualification is not None
    assert candidate.qualification.state == "screening"
    assert [trial.seed for trial in trials] == [101, 102, 103, 104]
    assert [trial.qualification_ordinal for trial in trials] == [1, 2, 3, 4]
    assert all(trial.qualification_id == candidate.qualification.id for trial in trials)
    assert all(trial.evaluation_phase == "screening" for trial in trials)
    assert all(trial.scenario_config_json["holdout"] is False for trial in trials)


def test_sealed_optimizer_refuses_reduced_fidelity_screening() -> None:
    job = _sealed_job()
    db = _RecordingSession()
    candidate = _candidate(
        candidate_id="cand-low-fidelity",
        source_type="optimizer",
        baseline=False,
    )
    candidate.optimizer_metadata_json = {
        "requested_fidelity": 0.5,
        "effective_fidelity": 0.5,
    }
    candidate.job = job

    with pytest.raises(RuntimeError, match="requires full fidelity"):
        _dispatch_optimizer_trials(  # type: ignore[arg-type]
            db,
            job,
            candidate,
            trials_per_candidate=4,
        )
    assert not any(isinstance(item, models.Trial) for item in db.added)
