"""Phase 5 tests: optimizer candidate generation, aggregation scoring,
and best-candidate selection.

These tests stay at the module level — no FastAPI app, no worker loop — so
the optimizer/aggregation contracts are exercised in isolation. See
``test_orchestration.py`` for the end-to-end loop that actually writes to
the DB and drives the runner.
"""

from __future__ import annotations

from collections.abc import Mapping
from types import SimpleNamespace

import pytest

from app import models, schemas
from app.optimization.domain import ParameterDomain, SearchSpace
from app.optimization.outcome_contract import build_selection_key, selection_order_key
from app.optimization.outcome_evidence import (
    compile_candidate_outcome_evidence,
    trial_outcome_evidence_row,
)
from app.optimization.outcome_taxonomy import classify_trial_outcome
from app.optimization.scenarios import ScenarioRun
from app.orchestration import acceptance, aggregation, constants, job_manager
from app.orchestration.experimental_optimizer import observations_for_job
from app.orchestration.optimizer import (
    generate_candidates,
    generate_selected_parameter_candidates,
)
from app.parameters import validate_parameter_values
from app.simulator.base import (
    FAILURE_EXECUTION_TIMEOUT,
    FAILURE_INVALID_RESULT,
    FAILURE_UNVERIFIED_REPORT,
)

# --- Candidate generation --------------------------------------------------


def test_generate_candidates_returns_default_count() -> None:
    proposals = generate_candidates(dict(constants.BASELINE_PARAMETERS))
    assert len(proposals) == constants.OPTIMIZER_CANDIDATE_COUNT
    assert 2 <= len(proposals) <= 5


def test_generate_candidates_is_deterministic() -> None:
    a = generate_candidates(dict(constants.BASELINE_PARAMETERS))
    b = generate_candidates(dict(constants.BASELINE_PARAMETERS))
    assert [p.parameters for p in a] == [p.parameters for p in b]
    assert [p.label for p in a] == [p.label for p in b]


def test_duplicate_detection_compares_only_selected_tuning_dimensions() -> None:
    job = models.Job(
        id="job_duplicate",
        track_type="circle",
        altitude_m=3.0,
        sensor_noise_level="medium",
        objective_profile="robust",
        parameter_space_json=[{"name": "MPC_XY_P", "enabled": True}],
    )
    job.candidates.append(
        models.CandidateParameterSet(
            id="candidate_existing",
            job_id=job.id,
            parameter_json={
                **constants.BASELINE_PARAMETERS,
                "MPC_XY_P": 0.95,
            },
        )
    )

    assert job_manager._is_duplicate_proposal(job, {"MPC_XY_P": 0.95}) is True
    assert job_manager._is_duplicate_proposal(job, {"MPC_XY_P": 1.05}) is False


def test_candidate_completion_cannot_change_unselected_legacy_parameters() -> None:
    job = models.Job(
        id="job_selected_parameter_boundary",
        track_type="circle",
        altitude_m=3.0,
        sensor_noise_level="medium",
        objective_profile="robust",
        parameter_space_json=[
            {
                "name": "MPC_XY_P",
                "enabled": True,
                "baseline": 0.95,
            }
        ],
    )

    completed = job_manager._complete_candidate_parameters(job, {"MPC_XY_P": 1.05})
    assert completed["MPC_XY_P"] == pytest.approx(1.05)
    assert completed["kp_xy"] == pytest.approx(constants.BASELINE_PARAMETERS["kp_xy"])

    with pytest.raises(ValueError, match="unselected parameter kp_xy"):
        job_manager._complete_candidate_parameters(job, {"kp_xy": 1.2})


def test_optimizer_fidelity_prefers_effective_coverage_and_rejects_invalid_values() -> None:
    assert job_manager._optimizer_fidelity(
        {"fidelity": 0.5, "effective_fidelity": 0.25}
    ) == pytest.approx(0.25)
    assert job_manager._optimizer_fidelity({"fidelity": float("nan")}) == 0.0
    assert job_manager._optimizer_fidelity({"fidelity": True}) == 0.0
    assert job_manager._optimizer_requested_fidelity({"requested_fidelity": "invalid"}) == 0.0


def test_generate_candidates_uses_only_whitelisted_keys() -> None:
    proposals = generate_candidates(dict(constants.BASELINE_PARAMETERS))
    for proposal in proposals:
        assert set(proposal.parameters.keys()) == set(constants.BASELINE_PARAMETERS.keys())


def test_generate_candidates_respects_safe_ranges() -> None:
    # Use an extreme baseline that would push perturbations outside the safe
    # range unless the optimizer clamps them back in.
    extreme_baseline = {
        "kp_xy": 2.4,
        "kd_xy": 0.75,
        "ki_xy": 0.24,
        "vel_limit": 9.5,
        "accel_limit": 7.5,
        "disturbance_rejection": 0.95,
    }
    proposals = generate_candidates(extreme_baseline)
    for proposal in proposals:
        for key, value in proposal.parameters.items():
            lo, hi = constants.PARAMETER_SAFE_RANGES[key]
            assert lo - 1e-9 <= value <= hi + 1e-9, (
                f"candidate {proposal.label} param {key}={value} outside [{lo}, {hi}]"
            )


def test_generate_candidates_differ_from_baseline() -> None:
    baseline = dict(constants.BASELINE_PARAMETERS)
    proposals = generate_candidates(baseline)
    for proposal in proposals:
        assert proposal.parameters != baseline, (
            f"optimizer candidate {proposal.label} matched baseline exactly"
        )


def test_generate_candidates_rejects_out_of_range_count() -> None:
    assert len(generate_candidates(dict(constants.BASELINE_PARAMETERS), count=1)) == 1
    with pytest.raises(ValueError):
        generate_candidates(dict(constants.BASELINE_PARAMETERS), count=0)
    with pytest.raises(ValueError):
        generate_candidates(dict(constants.BASELINE_PARAMETERS), count=6)


def test_generate_candidates_rejects_missing_tunable_keys() -> None:
    incomplete = dict(constants.BASELINE_PARAMETERS)
    del incomplete["kp_xy"]
    with pytest.raises(ValueError):
        generate_candidates(incomplete)


@pytest.mark.parametrize("unsafe", [True, float("nan"), float("inf")])
def test_generate_candidates_rejects_unsafe_numeric_values(unsafe: object) -> None:
    baseline = dict(constants.BASELINE_PARAMETERS)
    baseline["kp_xy"] = unsafe  # type: ignore[assignment]
    with pytest.raises(ValueError):
        generate_candidates(baseline)


def test_generate_candidates_rejects_boolean_count() -> None:
    with pytest.raises(ValueError):
        generate_candidates(dict(constants.BASELINE_PARAMETERS), count=True)


def test_generate_candidates_generation_index_starts_at_one() -> None:
    proposals = generate_candidates(dict(constants.BASELINE_PARAMETERS))
    assert [p.generation_index for p in proposals] == list(range(1, len(proposals) + 1))


def test_generate_selected_parameter_candidates_uses_declared_domain() -> None:
    proposals = generate_selected_parameter_candidates(
        [
            {
                "name": "MPC_XY_P",
                "baseline": 0.95,
                "minimum": 0.2,
                "maximum": 2.0,
                "step": 0.05,
                "scale": "linear",
                "value_type": "float",
                "enabled": True,
                "locked": False,
            },
            {
                "name": "MPC_TILTMAX_AIR",
                "baseline": 45,
                "minimum": 20,
                "maximum": 70,
                "step": 1,
                "scale": "linear",
                "value_type": "integer",
                "enabled": True,
                "locked": False,
            },
        ],
        count=4,
    )
    assert len(proposals) == 4
    assert len({tuple(sorted(item.parameters.items())) for item in proposals}) == 4
    assert all(set(item.parameters) == {"MPC_XY_P", "MPC_TILTMAX_AIR"} for item in proposals)
    assert all(item.parameters["MPC_TILTMAX_AIR"].is_integer() for item in proposals)


def test_selected_parameter_design_skips_catalog_coupling_violations() -> None:
    def validate(parameters: Mapping[str, float]) -> None:
        validate_parameter_values(parameters, px4_version="v1.16")

    proposals = generate_selected_parameter_candidates(
        [
            {
                "name": "MPC_ACC_HOR",
                "baseline": 3,
                "minimum": 2,
                "maximum": 8,
                "step": 1,
            },
            {
                "name": "MPC_ACC_HOR_MAX",
                "baseline": 5,
                "minimum": 3,
                "maximum": 10,
                "step": 1,
            },
        ],
        count=20,
        candidate_validator=validate,
    )

    assert len(proposals) == 20
    assert all(
        proposal.parameters["MPC_ACC_HOR"] <= proposal.parameters["MPC_ACC_HOR_MAX"]
        for proposal in proposals
    )


def test_selected_parameter_design_supports_more_than_halton_dimension_cap() -> None:
    parameter_space = [
        {
            "name": f"TEST_PARAM_{index:02d}",
            "baseline": 0.5,
            "minimum": 0.0,
            "maximum": 1.0,
            "step": 0.001,
        }
        for index in range(63)
    ]
    first = generate_selected_parameter_candidates(parameter_space, count=3)
    second = generate_selected_parameter_candidates(parameter_space, count=3)

    assert len(first) == 3
    assert [proposal.parameters for proposal in first] == [
        proposal.parameters for proposal in second
    ]
    assert all(len(proposal.parameters) == 63 for proposal in first)


# --- Aggregation scoring ---------------------------------------------------


class _FakeMetric:
    """Duck-typed stand-in for a TrialMetric ORM row."""

    def __init__(
        self,
        *,
        rmse: float,
        max_error: float,
        completion_time: float,
        crash: bool = False,
        timeout: bool = False,
        instability: bool = False,
    ) -> None:
        self.rmse = rmse
        self.max_error = max_error
        self.overshoot_count = 0
        self.completion_time = completion_time
        self.crash_flag = crash
        self.timeout_flag = timeout
        self.score = rmse
        self.final_error = 0.0
        self.pass_flag = not (crash or timeout or instability)
        self.instability_flag = instability


def _aggregation_trial(
    *,
    candidate: models.CandidateParameterSet,
    trial_id: str,
    case_id: str,
    seed: int,
    status: str = "COMPLETED",
    rmse: float = 1.0,
    max_error: float = 1.0,
    passed: bool = True,
    holdout: bool = False,
    scenario_type: str = "nominal",
) -> models.Trial:
    trial = models.Trial(
        id=trial_id,
        job_id=candidate.job_id,
        candidate_id=candidate.id,
        seed=seed,
        scenario_type=scenario_type,
        scenario_config_json={"scenario_case_id": case_id, "holdout": holdout},
        status=status,
    )
    if status == "COMPLETED":
        trial.metric = models.TrialMetric(
            trial_id=trial.id,
            rmse=rmse,
            max_error=max_error,
            overshoot_count=0,
            completion_time=10.0,
            crash_flag=False,
            timeout_flag=False,
            score=rmse,
            final_error=0.0,
            pass_flag=passed,
            instability_flag=False,
            raw_metric_json={},
        )
    return trial


def test_score_candidate_is_deterministic_and_documented() -> None:
    metrics = [
        _FakeMetric(rmse=0.5, max_error=1.0, completion_time=12.0),
        _FakeMetric(rmse=0.4, max_error=0.9, completion_time=11.0),
    ]
    score = aggregation._score_candidate(metrics, trial_count=2, failed=0)
    # rmse: (0.5+0.4)/2 = 0.45  -> 0.45 * 1.0 = 0.45
    # max_error: (1.0+0.9)/2 = 0.95 -> 0.95 * 0.5 = 0.475
    # completion: (12+11)/2 = 11.5 -> 11.5 * 0.05 = 0.575
    # no penalties
    # total = 1.5
    assert score == round(0.45 + 0.475 + 0.575, 4)


def test_score_candidate_penalises_failed_trials() -> None:
    base = [_FakeMetric(rmse=0.5, max_error=0.8, completion_time=12.0)]
    no_fail = aggregation._score_candidate(base, trial_count=2, failed=0)
    with_fail = aggregation._score_candidate(base, trial_count=2, failed=1)
    # failed_rate goes from 0 to 0.5, weighted by 1.5 = +0.75.
    assert with_fail > no_fail
    assert round(with_fail - no_fail, 4) == round(constants.SCORE_WEIGHTS["failed_trial"] * 0.5, 4)


def test_score_candidate_penalises_crash_timeout_instability() -> None:
    clean = [_FakeMetric(rmse=0.5, max_error=0.8, completion_time=12.0)]
    bad = [
        _FakeMetric(
            rmse=0.5,
            max_error=0.8,
            completion_time=12.0,
            crash=True,
            timeout=True,
            instability=True,
        )
    ]
    assert aggregation._score_candidate(
        bad, trial_count=1, failed=0
    ) > aggregation._score_candidate(clean, trial_count=1, failed=0)


def test_aggregation_rejects_completed_trial_with_missing_required_metric() -> None:
    candidate = models.CandidateParameterSet(
        id="candidate_missing_metric",
        job_id="job_missing_metric",
        generation_index=1,
        source_type="optimizer",
        parameter_json={"MPC_XY_P": 1.0},
    )
    trial = _aggregation_trial(
        candidate=candidate,
        trial_id="trial_missing_metric",
        case_id="nominal",
        seed=101,
    )
    assert trial.metric is not None
    trial.metric.rmse = None

    result = aggregation._aggregate_candidate(candidate, [trial])

    assert result is None
    assert candidate.completed_trial_count == 0
    assert candidate.failed_trial_count == 1
    assert candidate.aggregated_score is None


@pytest.mark.parametrize(
    ("case_id", "scenario_type", "holdout"),
    [
        ("unknown", "nominal", False),
        ("training", "wind_perturbed", False),
        ("validation", "nominal", False),
    ],
)
def test_aggregation_rejects_mismatched_scenario_evidence(
    case_id: str,
    scenario_type: str,
    holdout: bool,
) -> None:
    candidate = models.CandidateParameterSet(
        id="candidate_mismatched_scenario",
        job_id="job_mismatched_scenario",
        generation_index=1,
        source_type="optimizer",
        parameter_json={"MPC_XY_P": 1.0},
    )
    trial = _aggregation_trial(
        candidate=candidate,
        trial_id="trial_mismatched_scenario",
        case_id=case_id,
        seed=1,
        scenario_type=scenario_type,
        holdout=holdout,
    )
    suite = schemas.ScenarioSuiteConfig(
        cases=[
            schemas.ScenarioCaseConfig(
                id="training",
                scenario_type="nominal",
                seeds=[1],
            ),
            schemas.ScenarioCaseConfig(
                id="validation",
                scenario_type="nominal",
                seeds=[2],
                holdout=True,
            ),
        ]
    )

    with pytest.raises(ValueError, match="scenario evidence does not match configured suite"):
        aggregation._aggregate_candidate(
            candidate,
            [trial],
            scenario_suite=suite,
        )


def test_aggregation_rejects_seed_outside_declared_scenario_case() -> None:
    candidate = models.CandidateParameterSet(
        id="candidate_wrong_seed",
        job_id="job_wrong_seed",
        generation_index=1,
        source_type="optimizer",
        parameter_json={"MPC_XY_P": 1.0},
    )
    trial = _aggregation_trial(
        candidate=candidate,
        trial_id="trial_wrong_seed",
        case_id="training",
        seed=999,
    )
    suite = schemas.ScenarioSuiteConfig(
        cases=[schemas.ScenarioCaseConfig(id="training", seeds=[1])]
    )

    with pytest.raises(
        ValueError, match="scenario evidence does not match configured suite"
    ):
        aggregation._aggregate_candidate(
            candidate,
            [trial],
            scenario_suite=suite,
        )


def test_aggregation_rejects_ambiguous_legacy_scenario_evidence() -> None:
    candidate = models.CandidateParameterSet(
        id="candidate_ambiguous_scenario",
        job_id="job_ambiguous_scenario",
        generation_index=1,
        source_type="optimizer",
        parameter_json={"MPC_XY_P": 1.0},
    )
    trial = _aggregation_trial(
        candidate=candidate,
        trial_id="trial_ambiguous_scenario",
        case_id="ignored",
        seed=1,
    )
    trial.scenario_config_json = {"holdout": False}
    suite = schemas.ScenarioSuiteConfig(
        cases=[
            schemas.ScenarioCaseConfig(id="nominal-a", seeds=[1]),
            schemas.ScenarioCaseConfig(id="nominal-b", seeds=[1]),
        ]
    )

    with pytest.raises(ValueError, match="scenario evidence does not match configured suite"):
        aggregation._aggregate_candidate(
            candidate,
            [trial],
            scenario_suite=suite,
        )


def test_scenario_payload_preserves_authoritative_orchestrator_fields() -> None:
    run = ScenarioRun(
        case_id="trusted-case",
        scenario_type="wind_perturbed",
        seed=101,
        weight=2.0,
        holdout=True,
        config={
            "scenario": "nominal",
            "source": "forged",
            "generation_index": -999,
            "scenario_case_id": "forged-case",
            "scenario_weight": 999.0,
            "holdout": False,
            "advanced_scenario_config": {"forged": True},
        },
    )
    job = models.Job(advanced_scenario_config_json={"wind_gusts": {"enabled": True}})

    payload = job_manager._scenario_payload(
        job,
        run,
        source="optimizer",
        generation_index=7,
    )

    assert payload["scenario"] == "wind_perturbed"
    assert payload["source"] == "optimizer"
    assert payload["generation_index"] == 7
    assert payload["scenario_case_id"] == "trusted-case"
    assert payload["scenario_weight"] == 2.0
    assert payload["holdout"] is True
    assert payload["advanced_scenario_config"] == {"wind_gusts": {"enabled": True}}


@pytest.mark.parametrize(
    ("status", "failure_code", "usable_metric", "expected"),
    [
        ("COMPLETED", None, True, "success"),
        ("FAILED", "TIMEOUT", False, "domain_failure"),
        (
            "FAILED",
            "ADAPTER_UNAVAILABLE",
            False,
            "infrastructure_failure",
        ),
        ("CANCELLED", "CANCELLED", False, "cancelled"),
        ("FAILED", FAILURE_EXECUTION_TIMEOUT, False, "infrastructure_failure"),
        ("FAILED", FAILURE_INVALID_RESULT, False, "invalid_evidence"),
        ("FAILED", FAILURE_UNVERIFIED_REPORT, False, "invalid_evidence"),
        ("COMPLETED", None, False, "invalid_evidence"),
        ("FAILED", "UNRECOGNIZED_FAILURE", False, "unknown_failure"),
    ],
)
def test_trial_outcome_taxonomy_is_closed_and_unknowns_stay_explicit(
    status: str,
    failure_code: str | None,
    usable_metric: bool,
    expected: str,
) -> None:
    assert (
        classify_trial_outcome(
            status=status,
            failure_code=failure_code,
            usable_metric=usable_metric,
        )
        == expected
    )


def test_infrastructure_failures_block_acceptance_without_poisoning_optimizer() -> None:
    candidate = models.CandidateParameterSet(
        id="candidate_failure_taxonomy",
        job_id="job_failure_taxonomy",
        generation_index=1,
        source_type="optimizer",
        parameter_json={"MPC_XY_P": 1.0},
    )
    completed = _aggregation_trial(
        candidate=candidate,
        trial_id="taxonomy_success",
        case_id="nominal",
        seed=1,
        rmse=0.2,
    )
    infrastructure = _aggregation_trial(
        candidate=candidate,
        trial_id="taxonomy_infrastructure",
        case_id="nominal",
        seed=2,
        status="FAILED",
    )
    infrastructure.failure_code = "ADAPTER_UNAVAILABLE"

    result = aggregation._aggregate_candidate(
        candidate,
        [completed, infrastructure],
        objective_config=schemas.ObjectiveConfig(objectives=[schemas.ObjectiveSpec(metric="rmse")]),
        scenario_suite=schemas.ScenarioSuiteConfig(
            cases=[
                schemas.ScenarioCaseConfig(
                    id="nominal",
                    seeds=[1, 2],
                )
            ]
        ),
    )

    assert result is not None
    assert result["training_failure_rate"] == pytest.approx(0.5)
    assert result["optimizer_learning_failure_rate"] == pytest.approx(0.0)
    assert result["aggregated_score"] == pytest.approx(result["scalar_loss"])
    assert result["training_trial_outcome_counts"] == {
        "success": 1,
        "domain_failure": 0,
        "infrastructure_failure": 1,
        "cancelled": 0,
        "invalid_evidence": 0,
        "unknown_failure": 0,
    }
    acceptance_result = acceptance.evaluate_candidate(
        candidate,
        acceptance.AcceptanceCriteria(
            target_rmse=1.0,
            target_max_error=1.0,
            min_pass_rate=1.0,
        ),
    )
    assert acceptance_result.passed is False
    assert acceptance_result.reason == "pass_rate_too_low"


def test_score_weights_match_expected_public_values() -> None:
    # If a weight changes, this test flags the scoring-formula change so it
    # can be documented in a migration note.
    assert constants.SCORE_WEIGHTS == {
        "rmse": 1.0,
        "max_error": 0.5,
        "completion_time": 0.05,
        "crash": 2.0,
        "timeout": 1.5,
        "instability": 1.0,
        "failed_trial": 1.5,
    }


def test_multiobjective_aggregation_uses_robust_score_and_hard_constraints() -> None:
    candidate = models.CandidateParameterSet(
        id="cand_robust",
        job_id="job_robust",
        generation_index=1,
        source_type="optimizer",
        parameter_json={"MPC_XY_P": 1.0},
    )
    trials: list[models.Trial] = []
    for index, (rmse, crashed) in enumerate(((0.5, False), (2.0, True)), start=1):
        trial = models.Trial(
            id=f"trial_{index}",
            job_id="job_robust",
            candidate_id=candidate.id,
            seed=index,
            scenario_type="wind_perturbed",
            scenario_config_json={"scenario_case_id": "wind"},
            status="COMPLETED",
        )
        trial.metric = models.TrialMetric(
            trial_id=trial.id,
            rmse=rmse,
            max_error=rmse * 2,
            overshoot_count=0,
            completion_time=10,
            crash_flag=crashed,
            timeout_flag=False,
            score=rmse,
            final_error=0,
            pass_flag=not crashed,
            instability_flag=False,
        )
        trials.append(trial)
    objective_config = schemas.ObjectiveConfig(
        objectives=[schemas.ObjectiveSpec(metric="rmse", direction="minimize")],
        constraints=[
            schemas.ConstraintSpec(metric="crash_flag", operator="lte", threshold=0, hard=True)
        ],
        robust_aggregation="worst",
    )
    scenario_suite = schemas.ScenarioSuiteConfig(
        cases=[schemas.ScenarioCaseConfig(id="wind", scenario_type="wind_perturbed", seeds=[1, 2])]
    )
    result = aggregation._aggregate_candidate(
        candidate,
        trials,
        objective_config=objective_config,
        scenario_suite=scenario_suite,
    )
    assert result is not None
    assert result["objective_values"] == {"rmse": 2.0}
    assert result["feasible"] is False
    assert result["constraint_violations"]
    assert result["hard_constraint_violation"] == pytest.approx(1.0)
    assert result["preference_loss"] == pytest.approx(2.0)
    assert result["selection_key"]["hard_feasible"] is False
    assert candidate.aggregated_score is not None
    assert candidate.aggregated_score == pytest.approx(2.0)


def test_raw_adapter_metrics_cannot_override_canonical_safety_metrics() -> None:
    from app.services.jobs import _metric_sample

    candidate = models.CandidateParameterSet(
        id="candidate_reserved_metrics",
        job_id="job_reserved_metrics",
        generation_index=1,
        source_type="optimizer",
        parameter_json={"MPC_XY_P": 1.0},
    )
    trial = _aggregation_trial(
        candidate=candidate,
        trial_id="trial_reserved_metrics",
        case_id="nominal",
        seed=101,
        rmse=1.25,
    )
    assert trial.metric is not None
    trial.metric.raw_metric_json = {
        "rmse": 0.0,
        "pass_flag": True,
        "custom_energy": 7.5,
    }
    objective_config = schemas.ObjectiveConfig(
        objectives=[
            schemas.ObjectiveSpec(metric="rmse", direction="minimize"),
            schemas.ObjectiveSpec(metric="custom_energy", direction="minimize"),
        ]
    )
    scenario_suite = schemas.ScenarioSuiteConfig(
        cases=[schemas.ScenarioCaseConfig(id="nominal", scenario_type="nominal", seeds=[101])]
    )

    result = aggregation._aggregate_candidate(
        candidate,
        [trial],
        objective_config=objective_config,
        scenario_suite=scenario_suite,
    )

    assert result is not None
    assert result["objective_values"] == {
        "rmse": pytest.approx(1.25),
        "custom_energy": pytest.approx(7.5),
    }
    sample = _metric_sample(trial.metric)
    assert sample["rmse"] == pytest.approx(1.25)
    assert sample["custom_energy"] == pytest.approx(7.5)


def test_scenario_case_weight_is_independent_of_seed_count() -> None:
    candidate = models.CandidateParameterSet(
        id="candidate_case_weights",
        job_id="job_case_weights",
        generation_index=1,
        source_type="optimizer",
        parameter_json={"MPC_XY_P": 1.0},
    )
    trials: list[models.Trial] = []
    for index, (case_id, rmse) in enumerate(
        (("case-a", 0.0), ("case-a", 2.0), ("case-b", 3.0)), start=1
    ):
        trial = models.Trial(
            id=f"case_weight_trial_{index}",
            job_id=candidate.job_id,
            candidate_id=candidate.id,
            seed=index,
            scenario_type="nominal" if case_id == "case-a" else "wind_perturbed",
            scenario_config_json={"scenario_case_id": case_id},
            status="COMPLETED",
        )
        trial.metric = models.TrialMetric(
            trial_id=trial.id,
            rmse=rmse,
            max_error=rmse,
            overshoot_count=0,
            completion_time=10,
            crash_flag=False,
            timeout_flag=False,
            score=rmse,
            final_error=0,
            pass_flag=True,
            instability_flag=False,
        )
        trials.append(trial)
    result = aggregation._aggregate_candidate(
        candidate,
        trials,
        objective_config=schemas.ObjectiveConfig(
            objectives=[schemas.ObjectiveSpec(metric="rmse")],
            robust_aggregation="mean",
        ),
        scenario_suite=schemas.ScenarioSuiteConfig(
            cases=[
                schemas.ScenarioCaseConfig(
                    id="case-a", scenario_type="nominal", seeds=[1, 2], weight=1
                ),
                schemas.ScenarioCaseConfig(
                    id="case-b", scenario_type="wind_perturbed", seeds=[3], weight=1
                ),
            ]
        ),
    )

    assert result is not None
    # case-a contributes its seed mean (1.0), case-b contributes 3.0; equal
    # case weights therefore aggregate to 2.0 rather than 5/3.
    assert result["objective_values"]["rmse"] == pytest.approx(2.0)
    assert result["rmse"] == pytest.approx(2.0)
    assert result["acceptance_rmse"] == pytest.approx(2.0)


def test_case_weighted_rates_include_failed_seeds_in_each_case_denominator() -> None:
    candidate = models.CandidateParameterSet(
        id="candidate_weighted_rates",
        job_id="job_weighted_rates",
        generation_index=1,
        source_type="optimizer",
        parameter_json={"MPC_XY_P": 1.0},
    )
    trials = [
        _aggregation_trial(
            candidate=candidate,
            trial_id=f"case_a_{seed}",
            case_id="case-a",
            seed=seed,
            rmse=0.0,
        )
        for seed in (1, 2, 3)
    ]
    trials.append(
        _aggregation_trial(
            candidate=candidate,
            trial_id="case_a_failed",
            case_id="case-a",
            seed=4,
            status="FAILED",
        )
    )
    trials.append(
        _aggregation_trial(
            candidate=candidate,
            trial_id="case_b_completed_not_passing",
            case_id="case-b",
            seed=5,
            rmse=4.0,
            passed=False,
            scenario_type="wind_perturbed",
        )
    )

    result = aggregation._aggregate_candidate(
        candidate,
        trials,
        objective_config=schemas.ObjectiveConfig(
            objectives=[schemas.ObjectiveSpec(metric="rmse")],
            robust_aggregation="mean",
        ),
        scenario_suite=schemas.ScenarioSuiteConfig(
            cases=[
                schemas.ScenarioCaseConfig(
                    id="case-a", scenario_type="nominal", seeds=[1, 2, 3, 4], weight=1
                ),
                schemas.ScenarioCaseConfig(
                    id="case-b", scenario_type="wind_perturbed", seeds=[5], weight=3
                ),
            ]
        ),
    )

    assert result is not None
    # case-a: completion/pass/failure = .75/.75/.25 at weight 1
    # case-b: completion/pass/failure = 1/0/0 at weight 3
    assert result["training_completion_rate"] == pytest.approx(0.9375)
    assert result["training_pass_rate"] == pytest.approx(0.1875)
    assert result["training_failure_rate"] == pytest.approx(0.0625)
    assert result["optimizer_learning_failure_rate"] == pytest.approx(0.0)
    assert result["training_completed_trial_count"] == 4
    assert result["training_failed_trial_count"] == 1
    # Replicates are reduced within each case before the fixed case weights
    # are applied. The failed seed affects reliability, but cannot silently
    # shrink case-a's objective-distribution weight.
    assert result["objective_values"]["rmse"] == pytest.approx(3.0)
    assert result["rmse"] == pytest.approx(3.0)
    assert result["acceptance_rmse"] == pytest.approx(3.0)
    assert result["objective_estimator"] == "within_case_mean_then_fixed_suite_mean_v1"
    assert result["constraint_estimator"] == "worst_usable_seed_v1"
    assert result["training_scenario_case_rates"] == [
        {
            "scenario_case_id": "case-a",
            "scenario_type": "nominal",
            "weight": 1.0,
            "trial_count": 4,
            "completed_trial_count": 3,
            "failed_trial_count": 1,
            "passing_trial_count": 3,
            "completion_rate": 0.75,
            "failure_rate": 0.25,
            "pass_rate": 0.75,
            "trial_outcome_counts": {
                "success": 3,
                "domain_failure": 0,
                "infrastructure_failure": 0,
                "cancelled": 0,
                "invalid_evidence": 0,
                "unknown_failure": 1,
            },
            "optimizer_learning_failure_rate": 0.0,
        },
        {
            "scenario_case_id": "case-b",
            "scenario_type": "wind_perturbed",
            "weight": 3.0,
            "trial_count": 1,
            "completed_trial_count": 1,
            "failed_trial_count": 0,
            "passing_trial_count": 0,
            "completion_rate": 1.0,
            "failure_rate": 0.0,
            "pass_rate": 0.0,
            "trial_outcome_counts": {
                "success": 1,
                "domain_failure": 0,
                "infrastructure_failure": 0,
                "cancelled": 0,
                "invalid_evidence": 0,
                "unknown_failure": 0,
            },
            "optimizer_learning_failure_rate": 0.0,
        },
    ]
    # The missing failure code remains in completion/acceptance denominators,
    # but cannot alter the optimizer objective until it is classified as a
    # trusted physical domain failure.
    assert result["aggregated_score"] == pytest.approx(3.0)
    acceptance_result = acceptance.evaluate_candidate(
        candidate,
        acceptance.AcceptanceCriteria(target_rmse=None, target_max_error=None, min_pass_rate=0.2),
    )
    assert acceptance_result.passed is False
    assert acceptance_result.reason == "pass_rate_too_low"
    assert acceptance_result.pass_rate == pytest.approx(0.1875)
    assert acceptance_result.completion_rate == pytest.approx(0.9375)


def test_case_mean_objectives_keep_seed_level_constraint_extremes() -> None:
    candidate = models.CandidateParameterSet(
        id="candidate_nested_estimator",
        job_id="job_nested_estimator",
        generation_index=1,
        source_type="optimizer",
        parameter_json={"MPC_XY_P": 1.0},
    )
    trials = [
        _aggregation_trial(
            candidate=candidate,
            trial_id="case_a_seed_1",
            case_id="case-a",
            seed=1,
            rmse=0.0,
        ),
        _aggregation_trial(
            candidate=candidate,
            trial_id="case_a_seed_2",
            case_id="case-a",
            seed=2,
            rmse=10.0,
        ),
        _aggregation_trial(
            candidate=candidate,
            trial_id="case_b_seed_1",
            case_id="case-b",
            seed=3,
            rmse=0.0,
            scenario_type="wind_perturbed",
        ),
    ]

    result = aggregation._aggregate_candidate(
        candidate,
        trials,
        objective_config=schemas.ObjectiveConfig(
            objectives=[schemas.ObjectiveSpec(metric="rmse")],
            constraints=[
                schemas.ConstraintSpec(
                    metric="rmse",
                    operator="lte",
                    threshold=6.0,
                    hard=True,
                )
            ],
            robust_aggregation="mean",
        ),
        scenario_suite=schemas.ScenarioSuiteConfig(
            cases=[
                schemas.ScenarioCaseConfig(
                    id="case-a",
                    scenario_type="nominal",
                    seeds=[1, 2],
                    weight=1,
                ),
                schemas.ScenarioCaseConfig(
                    id="case-b",
                    scenario_type="wind_perturbed",
                    seeds=[3],
                    weight=1,
                ),
            ]
        ),
    )

    assert result is not None
    # case-a mean = 5 and case-b mean = 0, then equal case weights => 2.5.
    assert result["objective_values"]["rmse"] == pytest.approx(2.5)
    # Safety constraints retain the worst physical seed rather than seeing
    # only the safer case mean.
    assert result["constraint_values"]["rmse:lte:6"] == pytest.approx(10.0)
    assert result["feasible"] is False


def test_cvar_is_estimated_within_case_before_fixed_suite_weights() -> None:
    candidate = models.CandidateParameterSet(
        id="candidate_nested_cvar",
        job_id="job_nested_cvar",
        generation_index=1,
        source_type="optimizer",
        parameter_json={"MPC_XY_P": 1.0},
    )
    trials = [
        _aggregation_trial(
            candidate=candidate,
            trial_id=f"case_a_{seed}",
            case_id="case-a",
            seed=seed,
            rmse=rmse,
        )
        for seed, rmse in ((1, 0.0), (2, 10.0))
    ]
    trials.extend(
        [
            _aggregation_trial(
                candidate=candidate,
                trial_id=f"case_b_{seed}",
                case_id="case-b",
                seed=seed,
                rmse=rmse,
                scenario_type="wind_perturbed",
            )
            for seed, rmse in ((3, 0.0), (4, 4.0))
        ]
    )

    result = aggregation._aggregate_candidate(
        candidate,
        trials,
        objective_config=schemas.ObjectiveConfig(
            objectives=[schemas.ObjectiveSpec(metric="rmse")],
            robust_aggregation="cvar",
            cvar_alpha=0.25,
        ),
        scenario_suite=schemas.ScenarioSuiteConfig(
            cases=[
                schemas.ScenarioCaseConfig(
                    id="case-a",
                    scenario_type="nominal",
                    seeds=[1, 2],
                    weight=1,
                ),
                schemas.ScenarioCaseConfig(
                    id="case-b",
                    scenario_type="wind_perturbed",
                    seeds=[3, 4],
                    weight=1,
                ),
            ]
        ),
    )

    assert result is not None
    # The upper-tail value is 10 for case-a and 4 for case-b; fixed equal
    # case weights then produce 7. A flat CVaR over all seeds would return 10.
    assert result["objective_values"]["rmse"] == pytest.approx(7.0)
    assert result["acceptance_rmse"] == pytest.approx(3.5)
    assert result["objective_estimator"] == "within_case_cvar_then_fixed_suite_mean_v1"


def test_dispatched_case_without_any_usable_metric_has_no_scalar_objective() -> None:
    candidate = models.CandidateParameterSet(
        id="candidate_missing_case",
        job_id="job_missing_case",
        generation_index=1,
        source_type="optimizer",
        parameter_json={"MPC_XY_P": 1.0},
    )
    trials = [
        _aggregation_trial(
            candidate=candidate,
            trial_id="case_a_failed",
            case_id="case-a",
            seed=1,
            status="FAILED",
        ),
        _aggregation_trial(
            candidate=candidate,
            trial_id="case_b_completed",
            case_id="case-b",
            seed=2,
            rmse=1.0,
            scenario_type="wind_perturbed",
        ),
    ]

    result = aggregation._aggregate_candidate(
        candidate,
        trials,
        objective_config=schemas.ObjectiveConfig(
            objectives=[schemas.ObjectiveSpec(metric="rmse")],
        ),
        scenario_suite=schemas.ScenarioSuiteConfig(
            cases=[
                schemas.ScenarioCaseConfig(
                    id="case-a",
                    scenario_type="nominal",
                    seeds=[1],
                ),
                schemas.ScenarioCaseConfig(
                    id="case-b",
                    scenario_type="wind_perturbed",
                    seeds=[2],
                ),
            ]
        ),
    )

    assert result is not None
    assert result["objective_evaluation_error"] == (
        "scenario case case-a has no usable metric samples"
    )
    assert candidate.aggregated_score is None
    assert "objective_values" not in result


def test_acceptance_uses_worst_trial_max_error_and_keeps_legacy_mean() -> None:
    candidate = models.CandidateParameterSet(
        id="candidate_max_error",
        job_id="job_max_error",
        generation_index=1,
        source_type="optimizer",
        parameter_json={"MPC_XY_P": 1.0},
    )
    trials = [
        _aggregation_trial(
            candidate=candidate,
            trial_id="max_error_low",
            case_id="nominal",
            seed=1,
            max_error=0.1,
        ),
        _aggregation_trial(
            candidate=candidate,
            trial_id="max_error_high",
            case_id="nominal",
            seed=2,
            max_error=10.0,
        ),
    ]

    result = aggregation._aggregate_candidate(candidate, trials)

    assert result is not None
    assert result["max_error"] == pytest.approx(5.05)
    assert result["max_error_mean"] == pytest.approx(5.05)
    assert result["max_error_worst"] == pytest.approx(10.0)
    target_five = acceptance.evaluate_candidate(
        candidate,
        acceptance.AcceptanceCriteria(target_rmse=None, target_max_error=5.0, min_pass_rate=0.0),
    )
    assert target_five.passed is False
    assert target_five.reason == "max_error_above_target"
    assert target_five.max_error == pytest.approx(10.0)
    # This threshold distinguishes the new worst-trial semantics from the
    # historical 5.05 mean, which would otherwise have passed.
    assert not acceptance.evaluate_candidate(
        candidate,
        acceptance.AcceptanceCriteria(target_rmse=None, target_max_error=6.0, min_pass_rate=0.0),
    ).passed


def test_partial_holdout_failure_is_reported_and_never_marked_feasible() -> None:
    candidate = models.CandidateParameterSet(
        id="candidate_partial_holdout",
        job_id="job_partial_holdout",
        generation_index=1,
        source_type="optimizer",
        parameter_json={"MPC_XY_P": 1.0},
    )
    trials = [
        _aggregation_trial(
            candidate=candidate,
            trial_id="training_complete",
            case_id="training",
            seed=1,
        ),
        _aggregation_trial(
            candidate=candidate,
            trial_id="holdout_complete",
            case_id="validation",
            seed=2,
            rmse=0.2,
            max_error=0.3,
            holdout=True,
        ),
        _aggregation_trial(
            candidate=candidate,
            trial_id="holdout_failed",
            case_id="validation",
            seed=3,
            status="FAILED",
            holdout=True,
        ),
    ]
    result = aggregation._aggregate_candidate(
        candidate,
        trials,
        objective_config=schemas.ObjectiveConfig(objectives=[schemas.ObjectiveSpec(metric="rmse")]),
        scenario_suite=schemas.ScenarioSuiteConfig(
            cases=[
                schemas.ScenarioCaseConfig(id="training", seeds=[1]),
                schemas.ScenarioCaseConfig(id="validation", seeds=[2, 3], holdout=True, weight=2),
            ]
        ),
    )

    assert result is not None
    holdout = result["holdout"]
    assert holdout["trial_count"] == 2
    assert holdout["completed_trial_count"] == 1
    assert holdout["failed_trial_count"] == 1
    assert holdout["passing_trial_count"] == 1
    assert holdout["completion_rate"] == pytest.approx(0.5)
    assert holdout["failure_rate"] == pytest.approx(0.5)
    assert holdout["pass_rate"] == pytest.approx(0.5)
    assert holdout["objective_feasible"] is True
    assert holdout["validation_status"] == "incomplete"
    assert holdout["feasible"] is False


# --- Best candidate selection ---------------------------------------------


class _FakeCandidate:
    """Duck-typed stand-in for a CandidateParameterSet ORM row.

    Only the attributes aggregation._is_eligible / _rank_and_select_best read
    need to be present. Using a plain class keeps these tests independent
    from the SQLAlchemy mapper.
    """

    def __init__(
        self,
        *,
        candidate_id: str,
        score: float | None,
        is_baseline: bool = False,
        trial_count: int = 3,
        completed: int = 3,
        generation_index: int = 1,
        fidelity: float = 1.0,
        parameters: dict[str, float] | None = None,
    ) -> None:
        self.id = candidate_id
        self.parameter_json = parameters or {"MPC_XY_P": 0.95}
        self.aggregated_score = score
        self.aggregated_metric_json: dict[str, float] | None = (
            None if score is None else {"aggregated_score": score}
        )
        self.is_baseline = is_baseline
        self.trial_count = trial_count
        self.completed_trial_count = completed
        self.failed_trial_count = trial_count - completed
        self.generation_index = generation_index
        self.optimizer_metadata_json = {"requested_fidelity": fidelity}
        self.rank_in_job: int | None = None
        self.is_best: bool = False


def test_rank_and_select_best_picks_lowest_score() -> None:
    baseline = _FakeCandidate(
        candidate_id="c_base", score=2.0, is_baseline=True, generation_index=0
    )
    opt_a = _FakeCandidate(candidate_id="c_a", score=1.5, generation_index=1)
    opt_b = _FakeCandidate(candidate_id="c_b", score=1.2, generation_index=2)
    opt_c = _FakeCandidate(candidate_id="c_c", score=1.8, generation_index=3)

    winner = aggregation._rank_and_select_best([baseline, opt_a, opt_b, opt_c])
    assert winner is opt_b
    assert winner.is_best is True
    assert [c.rank_in_job for c in (opt_b, opt_a, opt_c, baseline)] == [1, 2, 3, 4]
    # Only one winner.
    others = [c for c in (baseline, opt_a, opt_c) if c.is_best]
    assert others == []


def test_low_fidelity_candidate_is_visible_but_unranked_until_verified() -> None:
    baseline = _FakeCandidate(
        candidate_id="baseline",
        score=2.0,
        is_baseline=True,
        generation_index=0,
    )
    screened = _FakeCandidate(
        candidate_id="screened",
        score=0.1,
        generation_index=1,
        fidelity=0.25,
    )

    winner = aggregation._rank_and_select_best([baseline, screened])

    assert winner is baseline
    assert baseline.rank_in_job == 1
    assert screened.rank_in_job is None
    assert screened.is_best is False


def test_rank_and_select_best_skips_ineligible_optimizer() -> None:
    baseline = _FakeCandidate(
        candidate_id="c_base",
        score=2.0,
        is_baseline=True,
        trial_count=4,
        completed=4,
        generation_index=0,
    )
    # Ineligible: only 1/3 trials completed — below the 0.5 ratio threshold.
    flaky = _FakeCandidate(
        candidate_id="c_flaky",
        score=0.1,
        trial_count=3,
        completed=1,
        generation_index=1,
    )
    healthy = _FakeCandidate(
        candidate_id="c_healthy",
        score=1.5,
        trial_count=3,
        completed=3,
        generation_index=2,
    )

    winner = aggregation._rank_and_select_best([baseline, flaky, healthy])
    # Flaky has the lowest score but is ineligible; the next-lowest eligible
    # candidate (healthy, 1.5) should win.
    assert winner is healthy
    assert winner.is_best is True


def test_rank_and_select_best_breaks_ties_in_favor_of_optimizer() -> None:
    baseline = _FakeCandidate(
        candidate_id="c_base", score=1.5, is_baseline=True, generation_index=0
    )
    opt = _FakeCandidate(candidate_id="c_opt", score=1.5, generation_index=1)

    winner = aggregation._rank_and_select_best([baseline, opt])
    # The Phase 5 report is more informative when the "optimized" column
    # differs from baseline, so tie -> optimizer wins.
    assert winner is opt
    assert opt.rank_in_job == 1
    assert baseline.rank_in_job == 2


def test_rank_and_select_best_does_not_publish_partial_baseline() -> None:
    baseline = _FakeCandidate(
        candidate_id="c_base",
        score=1.5,
        is_baseline=True,
        trial_count=4,
        completed=1,
        generation_index=0,
    )
    ineligible = _FakeCandidate(
        candidate_id="c_bad",
        score=0.9,
        trial_count=3,
        completed=1,
        generation_index=1,
    )
    winner = aggregation._rank_and_select_best([baseline, ineligible])
    assert winner is None
    assert baseline.rank_in_job is None
    assert baseline.is_best is False


@pytest.mark.parametrize(
    "raw_metric_json",
    [
        {
            "mode": "dry_run",
            "px4_outcome_evidence": {
                "schema_id": "dronedream.px4-outcome-evidence/v1",
                "synthetic": False,
            },
        },
        {
            "mode": "site_dry_run",
            "px4_outcome_evidence": {
                "schema_id": "dronedream.px4-outcome-evidence/v1",
                "synthetic": False,
            },
        },
        {
            "mode": "live",
            "px4_outcome_evidence": {
                "schema_id": "dronedream.px4-outcome-evidence/v1",
                "synthetic": True,
            },
        },
        {
            "mode": "live",
            "px4_outcome_evidence": {
                "schema_id": "dronedream.px4-outcome-evidence/v1",
            },
        },
    ],
    ids=["dry-run-mode", "site-dry-run-mode", "synthetic-evidence", "missing-provenance"],
)
def test_publishable_gate_rejects_synthetic_px4_runner_metrics(
    raw_metric_json: dict[str, object],
) -> None:
    candidate = _FakeCandidate(
        candidate_id="synthetic-px4",
        score=0.1,
        trial_count=1,
        completed=1,
    )
    candidate.trials = [
        SimpleNamespace(
            status="COMPLETED",
            metric=SimpleNamespace(
                rmse=0.1,
                max_error=0.2,
                overshoot_count=0,
                completion_time=1.0,
                crash_flag=False,
                timeout_flag=False,
                score=0.1,
                final_error=0.05,
                pass_flag=True,
                instability_flag=False,
                raw_metric_json=raw_metric_json,
            ),
        )
    ]

    assert aggregation.candidate_is_publishable(candidate) is False
    assert aggregation._rank_and_select_best([candidate]) is None


def test_publishable_gate_accepts_explicitly_nonsynthetic_px4_metrics() -> None:
    candidate = _FakeCandidate(
        candidate_id="physical-px4",
        score=0.1,
        trial_count=1,
        completed=1,
    )
    candidate.trials = [
        SimpleNamespace(
            status="COMPLETED",
            metric=SimpleNamespace(
                rmse=0.1,
                max_error=0.2,
                overshoot_count=0,
                completion_time=1.0,
                crash_flag=False,
                timeout_flag=False,
                score=0.1,
                final_error=0.05,
                pass_flag=True,
                instability_flag=False,
                raw_metric_json={
                    "mode": "live",
                    "px4_outcome_evidence": {
                        "schema_id": "dronedream.px4-outcome-evidence/v1",
                        "synthetic": False,
                    },
                },
            ),
        )
    ]

    assert aggregation.candidate_is_publishable(candidate) is True


def test_rank_and_select_best_rejects_failed_holdout_verification() -> None:
    baseline = _FakeCandidate(
        candidate_id="baseline",
        score=2.0,
        is_baseline=True,
        generation_index=0,
    )
    failed_holdout = _FakeCandidate(
        candidate_id="failed-holdout",
        score=0.1,
        generation_index=1,
    )
    assert failed_holdout.aggregated_metric_json is not None
    failed_holdout.aggregated_metric_json["feasible"] = True
    failed_holdout.aggregated_metric_json["holdout"] = {
        "validation_status": "failed",
        "feasible": False,
    }

    winner = aggregation._rank_and_select_best([baseline, failed_holdout])

    assert winner is baseline
    assert failed_holdout.rank_in_job is None
    assert failed_holdout.is_best is False


def test_publishable_gate_requires_the_complete_configured_holdout_matrix() -> None:
    candidate = _FakeCandidate(
        candidate_id="missing-holdout",
        score=0.1,
        generation_index=1,
        trial_count=1,
        completed=1,
    )
    candidate.job = SimpleNamespace(
        optimizer_strategy="turbo",
        scenario_suite_json={
            "cases": [
                {"id": "train", "scenario_type": "nominal", "seeds": [101]},
                {
                    "id": "verify",
                    "scenario_type": "wind",
                    "seeds": [805],
                    "holdout": True,
                },
            ]
        },
    )
    candidate.trials = [
        SimpleNamespace(
            status="COMPLETED",
            seed=101,
            scenario_config_json={"scenario_case_id": "train", "holdout": False},
        )
    ]
    assert candidate.aggregated_metric_json is not None
    candidate.aggregated_metric_json["feasible"] = True

    assert aggregation.candidate_is_publishable(candidate) is False


def test_experimental_candidate_requires_an_explicit_feasibility_result() -> None:
    candidate = _FakeCandidate(
        candidate_id="missing-feasibility",
        score=0.1,
        generation_index=1,
    )
    candidate.job = SimpleNamespace(
        optimizer_strategy="constrained_mobo",
        scenario_suite_json=None,
    )

    assert aggregation.candidate_is_publishable(candidate) is False


def test_rank_and_select_best_returns_none_when_nothing_scorable() -> None:
    c = _FakeCandidate(candidate_id="c", score=None, generation_index=1)
    assert aggregation._rank_and_select_best([c]) is None


def test_acceptance_prefers_verified_candidate_outcome_evidence() -> None:
    candidate = _FakeCandidate(
        candidate_id="verified-acceptance",
        score=0.1,
        generation_index=1,
    )
    aggregate = {
        "training_trial_count": 3,
        "training_completed_trial_count": 3,
        "training_failed_trial_count": 0,
        "training_passing_trial_count": 3,
        "training_trial_outcome_counts": {
            "success": 3,
            "domain_failure": 0,
            "infrastructure_failure": 0,
            "cancelled": 0,
            "invalid_evidence": 0,
            "unknown_failure": 0,
        },
        "training_trial_outcome_rates": {
            "success": 1.0,
            "domain_failure": 0.0,
            "infrastructure_failure": 0.0,
            "cancelled": 0.0,
            "invalid_evidence": 0.0,
            "unknown_failure": 0.0,
        },
        "optimizer_learning_failure_rate": 0.0,
        "objective_values": {"rmse": 0.1},
        "constraint_values": {},
        "constraint_violations": {},
        "feasible": True,
        "preference_loss": 0.1,
        "soft_constraint_penalty": 0.0,
        "scalar_loss": 0.1,
        "selection_key": build_selection_key(
            evidence_complete=True,
            hard_feasible=True,
            hard_constraint_violation=0.0,
            training_failure_rate=0.0,
            decision_loss=0.1,
        ),
        "acceptance_rmse": 0.1,
        "acceptance_max_error": 0.2,
        "acceptance_pass_rate": 1.0,
        "acceptance_completion_rate": 1.0,
    }
    candidate.trials = [
        SimpleNamespace(
            id=f"trial-{index}",
            status="COMPLETED",
            seed=100 + index,
            scenario_type="nominal",
            scenario_config_json={},
            failure_code=None,
            metric=SimpleNamespace(
                rmse=0.1,
                max_error=0.2,
                overshoot_count=0,
                completion_time=1.0,
                crash_flag=False,
                timeout_flag=False,
                score=0.1,
                final_error=0.05,
                pass_flag=True,
                instability_flag=False,
            ),
        )
        for index in range(3)
    ]
    evidence = compile_candidate_outcome_evidence(
        outcome_contract_id="sha256:" + "b" * 64,
        candidate_id=candidate.id,
        generation_index=candidate.generation_index,
        parameter_snapshot={"MPC_XY_P": 0.95},
        trial_evidence_rows=[trial_outcome_evidence_row(trial) for trial in candidate.trials],
        aggregate=aggregate,
    )
    candidate.aggregated_metric_json = {
        **aggregate,
        "acceptance_rmse": 999.0,
        "candidate_outcome_evidence": evidence.model_dump(mode="json"),
    }

    result = acceptance.evaluate_candidate(
        candidate,
        acceptance.AcceptanceCriteria(
            target_rmse=0.2,
            target_max_error=0.3,
            min_pass_rate=1.0,
        ),
    )

    assert result.passed is True
    assert result.rmse == pytest.approx(0.1)
    assert aggregation.candidate_is_publishable(candidate) is True

    candidate.parameter_json = {"MPC_XY_P": 1.05}
    wrong_parameters = acceptance.evaluate_candidate(
        candidate,
        acceptance.AcceptanceCriteria(
            target_rmse=0.2,
            target_max_error=0.3,
            min_pass_rate=1.0,
        ),
    )
    assert wrong_parameters.passed is False
    assert wrong_parameters.reason == "invalid_outcome_evidence"
    assert aggregation.candidate_is_publishable(candidate) is False
    candidate.parameter_json = {"MPC_XY_P": 0.95}
    optimizer_job = SimpleNamespace(
        objective_config_json={
            "objectives": [
                {
                    "metric": "rmse",
                    "direction": "minimize",
                }
            ]
        }
    )
    search_space = SearchSpace(
        (
            ParameterDomain(
                name="MPC_XY_P",
                baseline=0.95,
                minimum=0.6,
                maximum=1.3,
            ),
        )
    )
    observation = observations_for_job(
        optimizer_job,
        search_space=search_space,
        candidates=[candidate],
    )[0]
    assert observation.loss == pytest.approx(0.1)
    candidate.parameter_json = {"MPC_XY_P": 1.05}
    assert (
        observations_for_job(
            optimizer_job,
            search_space=search_space,
            candidates=[candidate],
        )
        == ()
    )
    candidate.parameter_json = {"MPC_XY_P": 0.95}

    candidate.trials[0].metric.rmse = 99.0
    changed_trial = acceptance.evaluate_candidate(
        candidate,
        acceptance.AcceptanceCriteria(
            target_rmse=0.2,
            target_max_error=0.3,
            min_pass_rate=1.0,
        ),
    )
    assert changed_trial.passed is False
    assert changed_trial.reason == "invalid_outcome_evidence"
    assert aggregation.candidate_is_publishable(candidate) is False
    assert (
        observations_for_job(
            optimizer_job,
            search_space=search_space,
            candidates=[candidate],
        )
        == ()
    )
    candidate.trials[0].metric.rmse = 0.1

    candidate.aggregated_metric_json["candidate_outcome_evidence"]["scalar_loss"] = -1.0
    invalid = acceptance.evaluate_candidate(
        candidate,
        acceptance.AcceptanceCriteria(
            target_rmse=0.2,
            target_max_error=0.3,
            min_pass_rate=1.0,
        ),
    )
    assert invalid.passed is False
    assert invalid.reason == "invalid_outcome_evidence"


@pytest.mark.parametrize("unsafe", (float("nan"), float("inf"), True))
def test_acceptance_never_treats_invalid_metrics_as_passing(unsafe: object) -> None:
    candidate = _FakeCandidate(
        candidate_id="invalid-metric",
        score=1.0,
        generation_index=1,
    )
    assert candidate.aggregated_metric_json is not None
    candidate.aggregated_metric_json.update(
        {"rmse": unsafe, "max_error_worst": unsafe, "pass_rate": 1.0}
    )
    result = acceptance.evaluate_candidate(
        candidate,
        acceptance.AcceptanceCriteria(
            target_rmse=1.0,
            target_max_error=1.0,
            min_pass_rate=0.5,
        ),
    )

    assert result.passed is False


@pytest.mark.parametrize(
    ("rate_field", "unsafe_rate"),
    (
        ("acceptance_pass_rate", -0.01),
        ("acceptance_pass_rate", 1.01),
        ("acceptance_pass_rate", float("nan")),
        ("acceptance_completion_rate", -0.01),
        ("acceptance_completion_rate", 1.01),
        ("acceptance_completion_rate", float("inf")),
    ),
)
def test_acceptance_rejects_corrupted_persisted_rates(
    rate_field: str,
    unsafe_rate: float,
) -> None:
    candidate = _FakeCandidate(
        candidate_id="invalid-rate",
        score=1.0,
        generation_index=1,
    )
    candidate.aggregated_metric_json = {
        "training_trial_count": 3,
        "training_completed_trial_count": 3,
        "training_passing_trial_count": 3,
        "acceptance_rmse": 0.1,
        "acceptance_max_error": 0.1,
        "acceptance_pass_rate": 1.0,
        "acceptance_completion_rate": 1.0,
        rate_field: unsafe_rate,
    }

    result = acceptance.evaluate_candidate(
        candidate,
        acceptance.AcceptanceCriteria(
            target_rmse=1.0,
            target_max_error=1.0,
            min_pass_rate=0.5,
        ),
    )

    assert result.passed is False
    assert result.reason == "invalid_rate_evidence"


def test_acceptance_rejects_corrupted_legacy_case_weighted_rate() -> None:
    candidate = _FakeCandidate(
        candidate_id="invalid-legacy-rate",
        score=1.0,
        generation_index=1,
    )
    candidate.aggregated_metric_json = {
        "training_trial_count": 3,
        "training_completed_trial_count": 3,
        "training_passing_trial_count": 3,
        "rmse": 0.1,
        "max_error_worst": 0.1,
        "rate_aggregation": "scenario_case_weighted_v1",
        "pass_rate": 1.2,
        "completion_rate": 1.0,
    }

    result = acceptance.evaluate_candidate(
        candidate,
        acceptance.AcceptanceCriteria(
            target_rmse=1.0,
            target_max_error=1.0,
            min_pass_rate=0.5,
        ),
    )

    assert result.passed is False
    assert result.reason == "invalid_rate_evidence"


def test_acceptance_uses_unrounded_versioned_projection_fields() -> None:
    candidate = _FakeCandidate(
        candidate_id="exact-acceptance-projection",
        score=0.1,
        generation_index=1,
    )
    assert candidate.aggregated_metric_json is not None
    candidate.aggregated_metric_json.update(
        {
            "rmse": 0.1234,
            "max_error_worst": 0.5,
            "pass_rate": 1.0,
            "acceptance_projection_schema": "dronedream.acceptance-projection/v1",
            "acceptance_rmse": 0.123456,
            "acceptance_max_error": 0.500006,
            "acceptance_pass_rate": 1.0,
            "acceptance_completion_rate": 1.0,
        }
    )

    result = acceptance.evaluate_candidate(
        candidate,
        acceptance.AcceptanceCriteria(
            target_rmse=0.12345,
            target_max_error=0.50001,
            min_pass_rate=1.0,
        ),
    )

    assert result.passed is False
    assert result.reason == "rmse_above_target"
    assert result.rmse == pytest.approx(0.123456)
    assert result.max_error == pytest.approx(0.500006)


def test_selection_order_uses_unrounded_decision_loss_not_display_metric() -> None:
    """Display-equivalent candidates retain their canonical numerical order."""

    better_loss = 0.123441
    worse_loss = 0.123442
    better = {
        "rmse": round(better_loss, 4),
        "selection_key": build_selection_key(
            evidence_complete=True,
            hard_feasible=True,
            hard_constraint_violation=0.0,
            training_failure_rate=0.0,
            decision_loss=better_loss,
        ),
    }
    worse = {
        "rmse": round(worse_loss, 4),
        "selection_key": build_selection_key(
            evidence_complete=True,
            hard_feasible=True,
            hard_constraint_violation=0.0,
            training_failure_rate=0.0,
            decision_loss=worse_loss,
        ),
    }

    assert better["rmse"] == worse["rmse"] == 0.1234
    assert selection_order_key(better, better["rmse"]) < selection_order_key(
        worse,
        worse["rmse"],
    )


@pytest.mark.parametrize("unsafe_count", (float("nan"), float("inf"), True, -1))
def test_acceptance_fails_closed_for_invalid_trial_counts(unsafe_count: object) -> None:
    candidate = _FakeCandidate(
        candidate_id="invalid-count",
        score=1.0,
        generation_index=1,
    )
    candidate.aggregated_metric_json = {
        "training_trial_count": unsafe_count,  # type: ignore[dict-item]
        "training_completed_trial_count": unsafe_count,  # type: ignore[dict-item]
        "rmse": 0.1,
        "max_error_worst": 0.1,
        "pass_rate": 1.0,
    }

    result = acceptance.evaluate_candidate(
        candidate,
        acceptance.AcceptanceCriteria(
            target_rmse=1.0,
            target_max_error=1.0,
            min_pass_rate=0.5,
        ),
    )

    assert result.passed is False
    assert result.reason == "no_metrics"


def test_acceptance_rejects_nonfinite_criteria() -> None:
    candidate = _FakeCandidate(
        candidate_id="invalid-criteria",
        score=1.0,
        generation_index=1,
    )
    assert candidate.aggregated_metric_json is not None
    candidate.aggregated_metric_json.update(
        {"rmse": 0.1, "max_error_worst": 0.1, "passing_trial_count": 3}
    )

    result = acceptance.evaluate_candidate(
        candidate,
        acceptance.AcceptanceCriteria(
            target_rmse=float("nan"),
            target_max_error=1.0,
            min_pass_rate=0.5,
        ),
    )

    assert result.passed is False
    assert result.reason == "invalid_criteria"
