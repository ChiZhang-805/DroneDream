"""Unit tests for dependency-free CMA-ES-style proposal generation."""

from __future__ import annotations

from app import models
from app.orchestration import constants
from app.orchestration.cma_es_optimizer import propose_next_generation


def _make_job(job_id: str = "job_cma") -> models.Job:
    return models.Job(
        id=job_id,
        track_type="circle",
        start_point_x=0.0,
        start_point_y=0.0,
        altitude_m=3.0,
        wind_north=0.0,
        wind_east=0.0,
        wind_south=0.0,
        wind_west=0.0,
        sensor_noise_level="medium",
        objective_profile="robust",
        status="RUNNING",
        simulator_backend_requested="mock",
        optimizer_strategy="cma_es",
        max_iterations=5,
        trials_per_candidate=3,
        max_total_trials=100,
    )


def _candidate(
    *,
    cid: str,
    generation_index: int,
    score: float | None,
    label: str,
    params: dict[str, float],
    is_baseline: bool = False,
) -> models.CandidateParameterSet:
    return models.CandidateParameterSet(
        id=cid,
        job_id="job_cma",
        generation_index=generation_index,
        source_type="baseline" if is_baseline else "optimizer",
        label=label,
        parameter_json=params,
        is_baseline=is_baseline,
        aggregated_score=score,
    )


def test_cma_es_proposal_respects_safe_ranges():
    baseline = dict(constants.BASELINE_PARAMETERS)
    history = [
        _candidate(
            cid="cand_base",
            generation_index=0,
            score=1.0,
            label="baseline",
            params=baseline,
            is_baseline=True,
        )
    ]
    proposal = propose_next_generation(
        job=_make_job(),
        candidates=history,
        safe_ranges=constants.PARAMETER_SAFE_RANGES,
        baseline_parameters=baseline,
        generation_index=1,
    )
    for key, value in proposal.parameters.items():
        lo, hi = constants.PARAMETER_SAFE_RANGES[key]
        assert lo <= value <= hi


def test_cma_es_proposal_is_deterministic_for_same_history():
    baseline = dict(constants.BASELINE_PARAMETERS)
    history = [
        _candidate(
            cid="cand_base",
            generation_index=0,
            score=1.0,
            label="baseline",
            params=baseline,
            is_baseline=True,
        ),
        _candidate(
            cid="cand_1",
            generation_index=1,
            score=0.8,
            label="cma_es_gen_1",
            params={**baseline, "kp_xy": 1.3},
        ),
    ]
    job = _make_job("job_same")
    a = propose_next_generation(
        job=job,
        candidates=history,
        safe_ranges=constants.PARAMETER_SAFE_RANGES,
        baseline_parameters=baseline,
        generation_index=2,
    )
    b = propose_next_generation(
        job=job,
        candidates=history,
        safe_ranges=constants.PARAMETER_SAFE_RANGES,
        baseline_parameters=baseline,
        generation_index=2,
    )
    assert a.parameters == b.parameters
    assert a.label == b.label == "cma_es_gen_2"


def test_cma_es_sigma_shrinks_with_generation():
    baseline = dict(constants.BASELINE_PARAMETERS)
    history = [
        _candidate(
            cid="cand_base",
            generation_index=0,
            score=1.0,
            label="baseline",
            params=baseline,
            is_baseline=True,
        )
    ]
    job = _make_job("job_sigma")
    early = propose_next_generation(
        job=job,
        candidates=history,
        safe_ranges=constants.PARAMETER_SAFE_RANGES,
        baseline_parameters=baseline,
        generation_index=1,
    )
    late = propose_next_generation(
        job=job,
        candidates=history,
        safe_ranges=constants.PARAMETER_SAFE_RANGES,
        baseline_parameters=baseline,
        generation_index=4,
    )
    early_delta = sum(abs(early.parameters[k] - baseline[k]) for k in constants.BASELINE_PARAMETERS)
    late_delta = sum(abs(late.parameters[k] - baseline[k]) for k in constants.BASELINE_PARAMETERS)
    assert late_delta <= early_delta


def test_cma_es_avoids_duplicate_history_candidate():
    baseline = dict(constants.BASELINE_PARAMETERS)
    prior = {
        "kp_xy": 1.04,
        "kd_xy": 0.23,
        "ki_xy": 0.07,
        "vel_limit": 5.2,
        "accel_limit": 3.9,
        "disturbance_rejection": 0.55,
    }
    history = [
        _candidate(
            cid="cand_base",
            generation_index=0,
            score=1.0,
            label="baseline",
            params=baseline,
            is_baseline=True,
        ),
        _candidate(
            cid="cand_1",
            generation_index=1,
            score=0.9,
            label="cma_es_gen_1",
            params=prior,
        ),
    ]
    proposal = propose_next_generation(
        job=_make_job("job_dup"),
        candidates=history,
        safe_ranges=constants.PARAMETER_SAFE_RANGES,
        baseline_parameters=baseline,
        generation_index=2,
    )
    assert proposal.parameters != prior
