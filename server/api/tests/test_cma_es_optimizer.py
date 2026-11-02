"""Unit tests for dependency-free CMA-ES-style proposal generation."""

from __future__ import annotations

import re

import pytest

from app import models, schemas
from app.optimization.outcome_contract import build_selection_key
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
    aggregate: dict[str, object] | None = None,
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
        aggregated_metric_json=aggregate,
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
    pattern = r"kp_xy=([0-9.]+)"
    early_match = re.search(pattern, early.strategy)
    late_match = re.search(pattern, late.strategy)
    assert early_match is not None and late_match is not None
    early_sigma = float(early_match.group(1))
    late_sigma = float(late_match.group(1))
    assert late_sigma < early_sigma


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


def test_cma_es_supports_user_selected_px4_parameter_space():
    job = _make_job("job_px4_space")
    selections = [
        schemas.ParameterSelection(
            name="MPC_XY_P", baseline=0.95, minimum=0.2, maximum=2.0, step=0.05
        ),
        schemas.ParameterSelection(
            name="MPC_TILTMAX_AIR",
            baseline=45,
            minimum=20,
            maximum=70,
            step=1,
            value_type="integer",
        ),
        schemas.ParameterSelection(
            name="MC_AIRMODE",
            baseline=1,
            minimum=0,
            maximum=2,
            value_type="enum",
            choices=[0, 1, 2],
            locked=True,
        ),
    ]
    job.parameter_space_json = [item.model_dump(mode="json") for item in selections]
    baseline = {"MPC_XY_P": 0.95, "MPC_TILTMAX_AIR": 45.0, "MC_AIRMODE": 1.0}
    history = [
        _candidate(
            cid="cand_px4_base",
            generation_index=0,
            score=1.0,
            label="baseline",
            params=baseline,
            is_baseline=True,
        )
    ]
    proposal = propose_next_generation(
        job=job,
        candidates=history,
        safe_ranges=constants.PARAMETER_SAFE_RANGES,
        baseline_parameters=constants.BASELINE_PARAMETERS,
        generation_index=1,
    )
    assert set(proposal.parameters) == {
        "MPC_XY_P",
        "MPC_TILTMAX_AIR",
        "MC_AIRMODE",
    }
    assert 0.2 <= proposal.parameters["MPC_XY_P"] <= 2.0
    assert (proposal.parameters["MPC_XY_P"] - 0.2) / 0.05 == pytest.approx(
        round((proposal.parameters["MPC_XY_P"] - 0.2) / 0.05)
    )
    assert proposal.parameters["MPC_TILTMAX_AIR"].is_integer()
    assert proposal.parameters["MC_AIRMODE"] == 1.0


def test_cma_es_ignores_corrupt_scored_history_when_selecting_center() -> None:
    baseline = dict(constants.BASELINE_PARAMETERS)
    corrupt = _candidate(
        cid="corrupt",
        generation_index=1,
        score=-100.0,
        label="corrupt",
        params={**baseline, "kp_xy": float("nan")},
    )
    proposal = propose_next_generation(
        job=_make_job("job_corrupt_history"),
        candidates=[corrupt],
        safe_ranges=constants.PARAMETER_SAFE_RANGES,
        baseline_parameters=baseline,
        generation_index=2,
    )

    assert "center=baseline" in proposal.strategy
    assert all(value == value for value in proposal.parameters.values())


def test_cma_es_center_respects_hard_feasibility_before_numeric_score() -> None:
    baseline = dict(constants.BASELINE_PARAMETERS)
    infeasible = _candidate(
        cid="unsafe-low-score",
        generation_index=1,
        score=0.0,
        label="unsafe",
        params={**baseline, "kp_xy": 2.0},
        aggregate={
            "selection_key": build_selection_key(
                evidence_complete=True,
                hard_feasible=False,
                hard_constraint_violation=0.01,
                training_failure_rate=0,
                decision_loss=0,
            )
        },
    )
    feasible = _candidate(
        cid="safe-high-score",
        generation_index=1,
        score=5000.0,
        label="safe",
        params={**baseline, "kp_xy": 0.5},
        aggregate={
            "selection_key": build_selection_key(
                evidence_complete=True,
                hard_feasible=True,
                hard_constraint_violation=0,
                training_failure_rate=0,
                decision_loss=5000,
            )
        },
    )

    proposal = propose_next_generation(
        job=_make_job("job_feasibility_first"),
        candidates=[infeasible, feasible],
        safe_ranges=constants.PARAMETER_SAFE_RANGES,
        baseline_parameters=baseline,
        generation_index=2,
    )

    assert "center=safe" in proposal.strategy


@pytest.mark.parametrize("generation", [True, -1])
def test_cma_es_rejects_invalid_generation_index(generation: object) -> None:
    with pytest.raises(ValueError):
        propose_next_generation(
            job=_make_job("job_invalid_generation"),
            candidates=[],
            safe_ranges=constants.PARAMETER_SAFE_RANGES,
            baseline_parameters=dict(constants.BASELINE_PARAMETERS),
            generation_index=generation,  # type: ignore[arg-type]
        )
