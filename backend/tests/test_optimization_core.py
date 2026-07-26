from __future__ import annotations

from collections.abc import Callable
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.optimization.design import halton_design
from app.optimization.domain import ParameterDomain, SearchSpace
from app.optimization.outcome_contract import (
    OUTCOME_CONTRACT_SCHEMA,
    build_selection_key,
    compile_job_outcome_contract,
    compile_outcome_contract,
    selection_order_key,
)
from app.optimization.outcome_evidence import (
    authoritative_candidate_outcome_projection,
    authoritative_candidate_trial_outcome_projection,
    authoritative_outcome_projection,
    compile_candidate_outcome_evidence,
    trial_is_holdout,
    verify_candidate_outcome_evidence,
)
from app.optimization.pareto import ParetoPoint, nondominated_front, representative_points
from app.optimization.robust import aggregate_metric, evaluate_candidate
from app.optimization.scenarios import holdout_matrix, scenario_matrix, training_matrix
from app.schemas import (
    AcceptanceCriteria,
    ConstraintSpec,
    ObjectiveConfig,
    ObjectiveSpec,
    ParameterSelection,
    ScenarioCaseConfig,
    ScenarioSuiteConfig,
)


def _parameter_space() -> list[ParameterSelection]:
    return [
        ParameterSelection(name="MPC_XY_P", baseline=0.95, minimum=0.2, maximum=2.0, step=0.05),
        ParameterSelection(
            name="MPC_TILTMAX_AIR",
            baseline=45,
            minimum=20,
            maximum=70,
            step=1,
            value_type="integer",
        ),
        ParameterSelection(
            name="MC_AIRMODE",
            baseline=1,
            minimum=0,
            maximum=2,
            value_type="enum",
            choices=[0, 1, 2],
        ),
    ]


def test_parameter_domain_validation_rejects_unsafe_bounds() -> None:
    with pytest.raises(ValidationError, match="inside"):
        ParameterSelection(name="MPC_XY_P", baseline=2.5, minimum=0.2, maximum=2.0)
    with pytest.raises(ValidationError, match="log-scaled"):
        ParameterSelection(name="MPC_XY_P", baseline=1.0, minimum=0.0, maximum=2.0, scale="log")
    with pytest.raises(ValidationError, match="requires choices"):
        ParameterSelection(
            name="MC_AIRMODE",
            baseline=1,
            minimum=0,
            maximum=2,
            value_type="enum",
        )


def test_search_space_projects_discrete_and_stepped_values() -> None:
    space = SearchSpace.from_schema(_parameter_space())
    projected = space.project({"MPC_XY_P": 1.024, "MPC_TILTMAX_AIR": 54.6, "MC_AIRMODE": 1.8})
    assert projected == {
        "MPC_XY_P": 1.0,
        "MPC_TILTMAX_AIR": 55.0,
        "MC_AIRMODE": 2.0,
    }


def test_halton_design_is_deterministic_bounded_and_includes_baseline() -> None:
    space = SearchSpace.from_schema(_parameter_space())
    first = halton_design(space, 8)
    second = halton_design(space, 8)
    assert first == second
    assert first[0] == space.baseline()
    assert len(first) == 8
    assert len({tuple(sorted(candidate.items())) for candidate in first}) == 8
    for candidate in first:
        assert 0.2 <= candidate["MPC_XY_P"] <= 2.0
        assert candidate["MPC_TILTMAX_AIR"].is_integer()
        assert candidate["MC_AIRMODE"] in {0.0, 1.0, 2.0}


def test_robust_aggregations_follow_worst_objective_direction() -> None:
    values = [1.0, 2.0, 10.0]
    assert aggregate_metric(values, direction="minimize", mode="mean") == pytest.approx(13 / 3)
    assert aggregate_metric(values, direction="minimize", mode="worst") == 10.0
    assert aggregate_metric(values, direction="maximize", mode="worst") == 1.0
    assert aggregate_metric(values, direction="minimize", mode="cvar", cvar_alpha=0.2) == 10.0


def test_candidate_evaluation_enforces_worst_case_hard_constraints() -> None:
    config = ObjectiveConfig(
        objectives=[
            ObjectiveSpec(metric="rmse", direction="minimize", normalization=2.0),
            ObjectiveSpec(
                metric="completion_time",
                direction="minimize",
                weight=0.25,
                normalization=10.0,
            ),
        ],
        constraints=[ConstraintSpec(metric="crash_flag", operator="lte", threshold=0, hard=True)],
        robust_aggregation="mean",
    )
    evaluation = evaluate_candidate(
        [
            {"rmse": 0.8, "completion_time": 8.0, "crash_flag": 0.0},
            {"rmse": 1.2, "completion_time": 9.0, "crash_flag": 1.0},
        ],
        config,
    )
    assert evaluation.objectives["rmse"] == 1.0
    assert evaluation.feasible is False
    assert evaluation.total_violation == 1.0
    assert evaluation.hard_constraint_violation == 1.0
    assert evaluation.preference_loss == pytest.approx(0.57)
    assert evaluation.scalar_loss == pytest.approx(0.57)


def test_outcome_contract_is_content_addressed_and_seals_holdout_identity() -> None:
    objective_config = ObjectiveConfig(
        objectives=[
            ObjectiveSpec(
                metric="rmse",
                direction="minimize",
                weight=2.0,
                normalization=0.5,
            )
        ],
        constraints=[
            ConstraintSpec(
                metric="crash_flag",
                operator="lte",
                threshold=0,
                hard=True,
                penalty=100,
            )
        ],
        robust_aggregation="cvar",
        cvar_alpha=0.25,
    )
    suite = ScenarioSuiteConfig(
        cases=[
            ScenarioCaseConfig(id="train", seeds=[1, 2], weight=2),
            ScenarioCaseConfig(
                id="sealed",
                scenario_type="wind_perturbed",
                seeds=[91],
                holdout=True,
                config={"wind_mps": 8},
            ),
        ]
    )
    acceptance = AcceptanceCriteria(
        target_rmse=0.8,
        min_pass_rate=0.9,
    )

    first = compile_outcome_contract(
        objective_config,
        suite,
        acceptance,
        failed_trial_weight=1.5,
    )
    second = compile_outcome_contract(
        objective_config,
        suite,
        acceptance,
        failed_trial_weight=1.5,
    )

    assert first == second
    assert first.schema_id == OUTCOME_CONTRACT_SCHEMA
    assert first.contract_id.startswith("sha256:")
    assert len(first.contract_id) == 71
    assert first.objectives[0].metric.registry_id == "dronedream.metric.rmse.v1"
    assert first.objectives[0].weight_decimal == "2"
    assert (
        first.objectives[0].estimator_scope
        == "within_case_estimator_then_fixed_suite"
    )
    assert first.objectives[0].within_case_estimator == "cvar"
    assert first.objectives[0].across_case_estimator == "mean"
    assert first.objectives[0].sample_weight_policy == (
        "full_case_weight_after_within_case_estimator"
    )
    assert first.scenario_population.cases[1].holdout is True
    assert first.scenario_population.cases[1].config_sha256
    assert (
        first.scenario_population.replicate_semantics
        == "declared_within_case_estimator_with_failure_rate_separate"
    )
    assert (
        first.scenario_population.missing_metric_policy
        == "fail_dispatched_case_without_usable_metric"
    )
    assert (
        first.scenario_population.low_fidelity_case_coverage_policy
        == "every_training_case_before_additional_replicates"
    )
    assert first.domain_failure_policy.hard_constraint_penalty_in_scalar_loss is False
    assert (
        first.domain_failure_policy.trial_outcome_taxonomy_schema
        == "dronedream.trial-outcome-taxonomy/v1"
    )
    assert (
        first.domain_failure_policy.optimizer_learning_outcome_policy
        == "domain_and_unknown_failures_excluding_nonphysical_outcomes"
    )
    assert (
        first.domain_failure_policy.unknown_failure_policy
        == "conservative_optimizer_failure"
    )
    assert (
        first.domain_failure_policy.acceptance_non_success_policy
        == "all_non_successes_remain_in_denominator"
    )
    assert (
        first.domain_failure_policy.optimizer_learning_failure_rate_limit_decimal
        == "0.5"
    )
    assert first.selection_policy.precedence[:3] == (
        "evidence_complete",
        "hard_feasible",
        "hard_constraint_violation",
    )
    assert first.compiler_version == "2.3"
    assert first.metric_admission_policy == "registered_metrics_only"
    assert (
        first.metric_dependency_policy
        == "reject_known_alias_complement_and_composite_overlap"
    )
    assert (
        first.selection_policy.optimizer_objective_representation_policy
        == "one_representation_per_tool_call"
    )
    assert (
        first.selection_policy.bayesian_multiobjective_policy
        == "joint_objective_vector_else_scalar_loss"
    )
    assert first.selection_policy.scalar_optimizer_policy == "scalar_loss_only"
    assert (
        first.selection_policy.bayesian_objective_scale_policy
        == "fixed_job_objective_normalization"
    )
    assert (
        first.selection_policy.bayesian_scalarization_policy
        == "fixed_job_objective_weights"
    )
    assert (
        first.selection_policy.incomplete_objective_vector_policy
        == "scalar_loss_else_exploration"
    )
    assert (
        first.selection_policy.candidate_outcome_evidence_policy
        == "content_addressed_search_projection"
    )
    assert (
        first.selection_policy.candidate_outcome_context_binding_policy
        == "candidate_id_generation_parameter_sha256"
    )
    assert (
        first.selection_policy.candidate_outcome_trial_binding_policy
        == "canonical_training_trial_rows_sha256"
    )
    assert (
        first.selection_policy.portfolio_source_schema
        == "dronedream.portfolio-sources/v1"
    )
    assert (
        first.selection_policy.portfolio_exact_collision_policy
        == "equal_credit_across_unique_child_strategies"
    )
    assert (
        first.selection_policy.portfolio_material_change_policy
        == "superseded_source_ineligible_for_reward"
    )
    assert (
        first.selection_policy.portfolio_reward_contract
        == "fixed_scale_pre_generation_incumbent_v1"
    )
    assert first.selection_policy.portfolio_reward_scale_decimal == "1"
    assert (
        first.selection_policy.portfolio_incumbent_scope
        == "global_comparable_full_fidelity_before_generation"
    )
    assert (
        first.selection_policy.portfolio_generation_credit_policy
        == "best_attributed_reward_once_per_generation"
    )
    assert first.selection_policy.portfolio_reward_bound == "zero_to_one"
    assert (
        first.final_promotion_policy.projection_schema
        == "dronedream.acceptance-projection/v1"
    )
    assert (
        first.final_promotion_policy.rmse_estimator
        == "within_case_mean_then_fixed_suite_mean"
    )
    assert (
        first.final_promotion_policy.max_error_estimator
        == "worst_usable_seed"
    )
    assert (
        first.final_promotion_policy.pass_rate_estimator
        == "case_weighted_dispatched_seed_rate"
    )

    changed = compile_outcome_contract(
        objective_config,
        suite.model_copy(
            update={
                "cases": [
                    suite.cases[0],
                    suite.cases[1].model_copy(update={"seeds": [92]}),
                ]
            }
        ),
        acceptance,
        failed_trial_weight=1.5,
    )
    assert changed.contract_id != first.contract_id

    with pytest.raises(ValueError, match="failed_trial_weight"):
        compile_outcome_contract(
            objective_config,
            suite,
            acceptance,
            failed_trial_weight=float("nan"),
        )


def test_candidate_outcome_evidence_is_content_addressed_and_authoritative() -> None:
    aggregate = {
        "training_trial_count": 2,
        "training_completed_trial_count": 2,
        "training_failed_trial_count": 0,
        "training_passing_trial_count": 2,
        "training_trial_outcome_counts": {
            "success": 2,
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
        "objective_values": {"rmse": 0.4},
        "constraint_values": {"crash_flag:lte:0": 0.0},
        "constraint_violations": {"crash_flag:lte:0": 0.0},
        "feasible": True,
        "preference_loss": 0.4,
        "soft_constraint_penalty": 0.0,
        "scalar_loss": 0.4,
        "selection_key": build_selection_key(
            evidence_complete=True,
            hard_feasible=True,
            hard_constraint_violation=0.0,
            training_failure_rate=0.0,
            decision_loss=0.4,
        ),
        "acceptance_rmse": 0.4,
        "acceptance_max_error": 0.8,
        "acceptance_pass_rate": 1.0,
        "acceptance_completion_rate": 1.0,
        "holdout": {
            "validation_status": "passed",
            "feasible": True,
        },
    }
    evidence = compile_candidate_outcome_evidence(
        outcome_contract_id="sha256:" + "a" * 64,
        candidate_id="candidate-evidence",
        generation_index=2,
        parameter_snapshot={"MPC_XY_P": 0.95},
        trial_evidence_rows=[
            {"trial_id": "trial-1", "seed": 101, "rmse": 0.3},
            {"trial_id": "trial-2", "seed": 102, "rmse": 0.5},
        ],
        aggregate=aggregate,
    )

    assert verify_candidate_outcome_evidence(
        evidence.model_dump(mode="json")
    ) == evidence
    wrapped = {
        **aggregate,
        "candidate_outcome_evidence": evidence.model_dump(mode="json"),
    }
    wrapped["scalar_loss"] = -1_000_000.0
    projection = authoritative_outcome_projection(wrapped)
    assert projection["scalar_loss"] == pytest.approx(0.4)
    assert projection["holdout"]["validation_status"] == "passed"
    assert selection_order_key(wrapped, -1_000_000.0)[-1] == pytest.approx(0.4)
    candidate_projection = authoritative_candidate_outcome_projection(
        candidate_id="candidate-evidence",
        generation_index=2,
        parameter_snapshot={"MPC_XY_P": 0.95},
        aggregate=wrapped,
    )
    assert candidate_projection["scalar_loss"] == pytest.approx(0.4)
    assert (
        authoritative_candidate_outcome_projection(
            candidate_id="wrong-candidate",
            generation_index=2,
            parameter_snapshot={"MPC_XY_P": 0.95},
            aggregate=wrapped,
        )
        == {}
    )
    assert (
        authoritative_candidate_outcome_projection(
            candidate_id="candidate-evidence",
            generation_index=3,
            parameter_snapshot={"MPC_XY_P": 0.95},
            aggregate=wrapped,
        )
        == {}
    )
    trial_rows = [
        {"trial_id": "trial-1", "seed": 101, "rmse": 0.3},
        {"trial_id": "trial-2", "seed": 102, "rmse": 0.5},
    ]
    trial_projection = authoritative_candidate_trial_outcome_projection(
        candidate_id="candidate-evidence",
        generation_index=2,
        parameter_snapshot={"MPC_XY_P": 0.95},
        trial_evidence_rows=trial_rows,
        aggregate=wrapped,
    )
    assert trial_projection["scalar_loss"] == pytest.approx(0.4)
    changed_trial_rows = [
        *trial_rows[:1],
        {"trial_id": "trial-2", "seed": 102, "rmse": 99.0},
    ]
    assert (
        authoritative_candidate_trial_outcome_projection(
            candidate_id="candidate-evidence",
            generation_index=2,
            parameter_snapshot={"MPC_XY_P": 0.95},
            trial_evidence_rows=changed_trial_rows,
            aggregate=wrapped,
        )
        == {}
    )
    assert (
        authoritative_candidate_outcome_projection(
            candidate_id="candidate-evidence",
            generation_index=2,
            parameter_snapshot={"MPC_XY_P": 1.05},
            aggregate=wrapped,
        )
        == {}
    )

    holdout_tampered = {
        **wrapped,
        "holdout": {
            "validation_status": "failed",
            "feasible": False,
        },
    }
    assert authoritative_outcome_projection(holdout_tampered) == {}

    missing_evidence_payload = {
        **aggregate,
        "candidate_outcome_evidence": None,
    }
    assert authoritative_outcome_projection(missing_evidence_payload) == {}
    required_but_missing = {
        **aggregate,
        "candidate_outcome_evidence_required": True,
    }
    assert authoritative_outcome_projection(required_but_missing) == {}
    assert selection_order_key(required_but_missing, -1_000_000.0)[-1] == float(
        "inf"
    )

    tampered_evidence = evidence.model_dump(mode="json")
    tampered_evidence["scalar_loss"] = -1_000_000.0
    tampered = {
        **aggregate,
        "candidate_outcome_evidence": tampered_evidence,
    }
    assert verify_candidate_outcome_evidence(tampered_evidence) is None
    assert authoritative_outcome_projection(tampered) == {}
    assert selection_order_key(tampered, -1_000_000.0) == (
        1,
        1,
        float("inf"),
        float("inf"),
        float("inf"),
    )


def test_trial_holdout_role_requires_a_boolean_marker() -> None:
    assert trial_is_holdout(
        SimpleNamespace(scenario_config_json={"holdout": True})
    )
    assert not trial_is_holdout(
        SimpleNamespace(scenario_config_json={"holdout": False})
    )
    assert not trial_is_holdout(SimpleNamespace(scenario_config_json={}))
    with pytest.raises(ValueError, match="holdout marker must be a boolean"):
        trial_is_holdout(
            SimpleNamespace(scenario_config_json={"holdout": "false"})
        )


def test_outcome_contract_rejects_unregistered_adapter_raw_metrics() -> None:
    with pytest.raises(
        ValueError,
        match="unregistered optimization metric: custom_energy",
    ):
        compile_outcome_contract(
            ObjectiveConfig(
                objectives=[
                    ObjectiveSpec(
                        metric="custom_energy",
                        direction="minimize",
                    )
                ]
            ),
            ScenarioSuiteConfig(
                cases=[ScenarioCaseConfig(id="train", seeds=[1])],
            ),
            AcceptanceCriteria(),
            failed_trial_weight=1.5,
        )


@pytest.mark.parametrize(
    "objectives",
    [
        [
            ObjectiveSpec(metric="score"),
            ObjectiveSpec(metric="rmse"),
        ],
        [
            ObjectiveSpec(metric="completion_rate", direction="maximize"),
            ObjectiveSpec(metric="failure_rate"),
        ],
        [
            ObjectiveSpec(metric="failed_trial_rate"),
            ObjectiveSpec(metric="failure_rate"),
        ],
    ],
)
def test_outcome_contract_rejects_known_objective_dependency_overlap(
    objectives: list[ObjectiveSpec],
) -> None:
    with pytest.raises(ValueError, match="cannot be combined"):
        compile_outcome_contract(
            ObjectiveConfig(objectives=objectives),
            ScenarioSuiteConfig(
                cases=[ScenarioCaseConfig(id="train", seeds=[1])],
            ),
            AcceptanceCriteria(),
            failed_trial_weight=1.5,
        )


def test_outcome_contract_rejects_redundant_reliability_constraints() -> None:
    with pytest.raises(
        ValueError,
        match="dependent reliability constraint metrics cannot be combined",
    ):
        compile_outcome_contract(
            ObjectiveConfig(
                objectives=[ObjectiveSpec(metric="rmse")],
                constraints=[
                    ConstraintSpec(
                        metric="completion_rate",
                        operator="gte",
                        threshold=0.8,
                    ),
                    ConstraintSpec(
                        metric="failure_rate",
                        operator="lte",
                        threshold=0.2,
                    ),
                ],
            ),
            ScenarioSuiteConfig(
                cases=[ScenarioCaseConfig(id="train", seeds=[1])],
            ),
            AcceptanceCriteria(),
            failed_trial_weight=1.5,
        )


def test_outcome_contract_preserves_and_labels_supported_legacy_scenario_shape() -> None:
    legacy_suite = {
        "cases": [
            {
                "scenario_type": "wind",
                "seeds": [101],
            }
        ]
    }
    job = SimpleNamespace(
        objective_config_json=None,
        scenario_suite_json=legacy_suite,
        target_rmse=None,
        target_max_error=None,
        min_pass_rate=0.8,
    )

    contract = compile_job_outcome_contract(
        job,
        failed_trial_weight=1.5,
    )

    assert contract.compatibility_normalization == (
        "legacy_scenario_aliases_v1",
    )
    assert contract.scenario_population.cases[0].case_id == (
        "legacy-1-wind_perturbed"
    )
    assert contract.scenario_population.cases[0].scenario_type == (
        "wind_perturbed"
    )


def test_selection_key_is_lexicographic_not_magic_penalty_based() -> None:
    feasible = {
        "selection_key": build_selection_key(
            evidence_complete=True,
            hard_feasible=True,
            hard_constraint_violation=0,
            training_failure_rate=0,
            decision_loss=5000,
        )
    }
    infeasible = {
        "selection_key": build_selection_key(
            evidence_complete=True,
            hard_feasible=False,
            hard_constraint_violation=0.001,
            training_failure_rate=0,
            decision_loss=0,
        )
    }

    assert selection_order_key(feasible, 5000) < selection_order_key(
        infeasible,
        0,
    )

    maximize_reward = {
        "selection_key": build_selection_key(
            evidence_complete=True,
            hard_feasible=True,
            hard_constraint_violation=0,
            training_failure_rate=0,
            decision_loss=-1,
        )
    }
    assert selection_order_key(maximize_reward, -1)[-1] == -1


def test_constraint_observations_do_not_collide_for_two_bounds_on_one_metric() -> None:
    evaluation = evaluate_candidate(
        [{"corridor_margin": -1.0}, {"corridor_margin": 2.0}],
        ObjectiveConfig(
            objectives=[
                ObjectiveSpec(
                    metric="corridor_margin",
                    direction="maximize",
                )
            ],
            constraints=[
                ConstraintSpec(
                    metric="corridor_margin",
                    operator="gte",
                    threshold=0,
                    hard=True,
                ),
                ConstraintSpec(
                    metric="corridor_margin",
                    operator="lte",
                    threshold=1,
                    hard=True,
                ),
            ],
        ),
    )

    assert evaluation.constraint_values == {
        "corridor_margin:gte:0": -1.0,
        "corridor_margin:lte:1": 2.0,
    }
    assert set(evaluation.violations) == set(evaluation.constraint_values)


def test_objective_targets_apply_one_sided_aspiration_loss() -> None:
    config = ObjectiveConfig(
        objectives=[
            ObjectiveSpec(
                metric="rmse",
                direction="minimize",
                weight=1.0,
                normalization=2.0,
                target=1.0,
            ),
            ObjectiveSpec(
                metric="pass_rate",
                direction="maximize",
                weight=1.0,
                normalization=1.0,
                target=0.9,
            ),
        ]
    )

    met = evaluate_candidate(
        [{"rmse": 0.8, "pass_rate": 0.95}],
        config,
    )
    missed = evaluate_candidate(
        [{"rmse": 1.4, "pass_rate": 0.7}],
        config,
    )

    assert met.scalar_loss == 0.0
    # Equal objective weights: 0.5 * ((1.4 - 1.0) / 2) +
    # 0.5 * ((0.9 - 0.7) / 1) = 0.2.
    assert missed.scalar_loss == pytest.approx(0.2)


def test_pareto_front_is_constraint_aware_and_recommendations_are_stable() -> None:
    directions = {"rmse": "minimize", "speed": "maximize"}
    points = [
        ParetoPoint("unsafe", {"rmse": 0.1, "speed": 20}, directions, False, 0.2),
        ParetoPoint("stable", {"rmse": 0.5, "speed": 10}, directions),
        ParetoPoint("fast", {"rmse": 0.8, "speed": 15}, directions),
        ParetoPoint("dominated", {"rmse": 0.9, "speed": 9}, directions),
    ]
    front = nondominated_front(points)
    assert [point.id for point in front] == ["stable", "fast"]
    recommendations = representative_points(points)
    assert recommendations["best_rmse"].id == "stable"
    assert recommendations["best_speed"].id == "fast"
    assert recommendations["balanced"].id in {"stable", "fast"}


def test_pareto_diagnostics_never_recommend_an_infeasible_parameter_set() -> None:
    directions = {"rmse": "minimize"}
    unsafe = [
        ParetoPoint("less-unsafe", {"rmse": 0.4}, directions, False, 0.1),
        ParetoPoint("more-unsafe", {"rmse": 0.2}, directions, False, 0.8),
    ]

    assert [point.id for point in nondominated_front(unsafe)] == ["less-unsafe"]
    assert representative_points(unsafe) == {}


def test_scenario_suite_requires_unique_ids_and_seeds() -> None:
    with pytest.raises(ValidationError, match="seeds must be unique"):
        ScenarioCaseConfig(id="wind", scenario_type="wind_perturbed", seeds=[1, 1])
    with pytest.raises(ValidationError, match="case ids must be unique"):
        ScenarioSuiteConfig(
            cases=[
                ScenarioCaseConfig(id="same", seeds=[1]),
                ScenarioCaseConfig(id="same", seeds=[2]),
            ]
        )


@pytest.mark.parametrize(
    "factory",
    [
        lambda: ParameterDomain("", 0.5, 0.0, 1.0),
        lambda: ParameterDomain("x", 0.5, 1.0, 0.0),
        lambda: ParameterDomain("x", 2.0, 0.0, 1.0),
        lambda: ParameterDomain("x", 0.5, 0.0, 1.0, step=0.0),
        lambda: ParameterDomain("x", 0.5, 0.0, 1.0, scale="log"),
        lambda: ParameterDomain("x", 0.5, 0.0, 1.0, choices=(0.25, 1.5)),
    ],
)
def test_parameter_domain_rejects_invalid_runtime_contracts(
    factory: Callable[[], ParameterDomain],
) -> None:
    with pytest.raises(ValueError):
        factory()


def test_parameter_domain_rejects_nonfinite_and_boolean_proposals() -> None:
    domain = ParameterDomain("x", 0.5, 0.0, 1.0)
    with pytest.raises(ValueError):
        domain.from_unit(float("nan"))
    with pytest.raises(ValueError):
        domain.from_unit(True)
    with pytest.raises(ValueError):
        domain.project(False)


def test_scenario_matrix_is_fixed_across_candidates_and_splits_holdout() -> None:
    suite = ScenarioSuiteConfig(
        cases=[
            ScenarioCaseConfig(id="train", seeds=[3, 5], weight=2.0),
            ScenarioCaseConfig(
                id="validation",
                scenario_type="wind_perturbed",
                seeds=[11],
                holdout=True,
                config={"wind_mps": 9},
            ),
        ]
    )
    first = scenario_matrix(suite)
    second = scenario_matrix(suite)
    assert first == second
    assert [(run.case_id, run.seed) for run in training_matrix(suite)] == [
        ("train", 3),
        ("train", 5),
    ]
    assert [(run.case_id, run.seed) for run in holdout_matrix(suite)] == [("validation", 11)]
    assert first[-1].persistence_config() == {
        "wind_mps": 9,
        "scenario_case_id": "validation",
        "scenario_weight": 1.0,
        "holdout": True,
    }
