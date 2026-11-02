from __future__ import annotations

import copy
from pathlib import Path

import pytest

from app.optimization.prefinal_scenario_registry import (
    build_prefinal_scenario_registry,
    verify_prefinal_scenario_registry,
)
from app.schemas import JobCreateRequest
from scripts.freeze_prefinal_scenario_registry import (
    render_prefinal_scenario_registry_files,
    write_prefinal_scenario_registry_files,
)


def test_registry_has_expected_gradient_and_six_preregistered_arms() -> None:
    registry = build_prefinal_scenario_registry()

    assert registry["problem_count"] == 18
    assert registry["difficulty_distribution"] == {
        "easy": 2,
        "representative": 13,
        "hard": 3,
    }
    assert [arm["arm_id"] for arm in registry["arms"]] == [
        "deterministic_default_policy",
        "fixed_cma_es",
        "preselected_specialized_optimizer",
        "deterministic_portfolio_no_model",
        "harness_without_reflection_recovery_memory",
        "full_harness",
    ]


def test_every_job_template_validates_and_uses_a_sealed_disjoint_holdout() -> None:
    registry = build_prefinal_scenario_registry()
    all_training: set[int] = set()
    all_holdout: set[int] = set()

    for problem in registry["problems"]:
        job = JobCreateRequest.model_validate(problem["job_template"])
        assert job.simulator_backend == "real_cli"
        assert job.optimizer_strategy == "none"
        assert job.completion_policy == "first_qualified_stop"
        assert job.provider_turn_cap == 0
        assert len(job.parameter_space) == 6
        training = {
            seed for case in job.scenario_suite.cases if not case.holdout for seed in case.seeds
        }
        holdout = {
            seed for case in job.scenario_suite.cases if case.holdout for seed in case.seeds
        }
        assert len(training) == 2
        assert len(holdout) == 2
        assert training.isdisjoint(holdout)
        all_training.update(training)
        all_holdout.update(holdout)

    assert all_training.isdisjoint(all_holdout)
    assert len(all_training) == len(all_holdout) == 36


def test_every_registered_physical_effect_is_bundled_and_hashed() -> None:
    registry = build_prefinal_scenario_registry()

    for problem in registry["problems"]:
        contracts = problem["physical_effect_contracts"]
        assert len(contracts) == 4
        assert all(len(item["request_sha256"]) == 64 for item in contracts)
        assert len(problem["physical_effect_contracts_sha256"]) == 64


def test_selection_and_calibration_policy_forbid_favorable_outcome_pruning() -> None:
    registry = build_prefinal_scenario_registry()

    assert registry["selection_policy"]["all_registered_problems_retained"] is True
    assert registry["selection_policy"]["comparative_outcome_based_pruning_forbidden"] is True
    assert registry["selection_policy"]["failures_and_competitor_wins_retained"] is True
    assert registry["calibration_protocol"]["uses_comparative_arm_outcomes"] is False
    assert registry["calibration_protocol"]["uses_provider"] is False
    assert registry["report_eligible"] is False


def test_budget_is_simulation_fair_and_provider_calls_are_reported_not_hidden() -> None:
    registry = build_prefinal_scenario_registry()
    budget = registry["budget"]

    assert budget["simulation_trial_cap"] == (
        budget["baseline_scenario_runs"]
        + budget["generation_cap"]
        * budget["candidate_slots_per_generation"]
        * budget["scenario_runs_per_candidate"]
    )
    assert budget["provider_retry_cap"] == 0
    assert registry["fairness_contract"]["same_simulation_trial_cap"] is True
    assert registry["fairness_contract"]["provider_turns_may_differ_but_are_counted"] is True
    assert (
        registry["fairness_contract"]["extra_provider_turns_do_not_grant_extra_simulations"]
        is True
    )


def test_registry_hash_detects_any_silent_change() -> None:
    registry = build_prefinal_scenario_registry()
    assert verify_prefinal_scenario_registry(registry) is True

    tampered = copy.deepcopy(registry)
    tampered["problems"][0]["difficulty"] = "hard"
    assert verify_prefinal_scenario_registry(tampered) is False


def test_rendering_is_byte_reproducible_and_contains_no_execution_claim() -> None:
    registry = build_prefinal_scenario_registry()
    first = render_prefinal_scenario_registry_files(
        registry,
        json_name="registry.json",
        csv_name="registry.csv",
        manifest_name="registry.manifest.json",
    )
    second = render_prefinal_scenario_registry_files(
        registry,
        json_name="registry.json",
        csv_name="registry.csv",
        manifest_name="registry.manifest.json",
    )

    assert first == second
    assert b'"report_eligible": false' in first[0]
    assert b'"status": "design_only_not_execution_approved"' in first[0]


def test_cli_writer_is_non_overwriting_and_check_mode_is_exact(tmp_path: Path) -> None:
    paths = {
        "json_path": tmp_path / "registry.json",
        "csv_path": tmp_path / "registry.csv",
        "manifest_path": tmp_path / "registry.manifest.json",
        "sha256_path": tmp_path / "registry.sha256",
    }
    result = write_prefinal_scenario_registry_files(**paths)

    assert result["problem_count"] == 18
    write_prefinal_scenario_registry_files(**paths, check=True)
    with pytest.raises(FileExistsError):
        write_prefinal_scenario_registry_files(**paths)

    paths["csv_path"].write_text("tampered\n", encoding="utf-8")
    with pytest.raises(ValueError, match="stale"):
        write_prefinal_scenario_registry_files(**paths, check=True)
