from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.benchmarking.adapters import search_space_from_observation
from app.benchmarking.contracts import BenchmarkObservationV2, canonical_sha256
from app.benchmarking.offline_matrix import (
    BenchmarkOfflineMatrixV1,
    run_offline_structural_matrix,
)
from app.benchmarking.registry import require_registered_adapter
from app.optimization.domain import ParameterDomain, SearchSpace

_OFFLINE_FIXTURE_ARMS = (
    "random_search/v1",
    "seeded_halton/v1",
    "repo_constrained_mobo/v1",
    "optimizer_portfolio/v1",
    "llm_direct/v1",
    "llm_react/v1",
    "llambo_uav/v1",
    "dronedream_fixed_two_turn/v1",
    "dronedream_adaptive_1_4/v1",
)


def _observation() -> BenchmarkObservationV2:
    return BenchmarkObservationV2(
        campaign_id="base-campaign",
        run_id="base-run",
        benchmark_arm_id="base-arm",
        generation_index=0,
        next_dispatch_ordinal=1,
        algorithm_seed=20260804,
        simulator_seed_block_id="paired-crn-1",
        parameter_domain=[
            {
                "name": "kp",
                "baseline": 1.0,
                "minimum": 0.5,
                "maximum": 2.0,
                "step": None,
                "scale": "linear",
                "value_type": "float",
                "choices": [],
                "enabled": True,
                "locked": False,
            },
            {
                "name": "kd",
                "baseline": 0.3,
                "minimum": 0.05,
                "maximum": 1.0,
                "step": 0.01,
                "scale": "linear",
                "value_type": "float",
                "choices": [],
                "enabled": True,
                "locked": False,
            },
            {
                "name": "mode",
                "baseline": 1.0,
                "minimum": 0.0,
                "maximum": 2.0,
                "step": None,
                "scale": "linear",
                "value_type": "enum",
                "choices": [0.0, 1.0, 2.0],
                "enabled": True,
                "locked": False,
            },
        ],
        objectives=[
            {
                "name": "tracking_error",
                "direction": "minimize",
                "weight": 1.0,
                "normalization": 1.0,
            }
        ],
        constraints=[{"name": "safety", "operator": "le", "threshold": 0.0}],
        history=[],
        failure_semantics={"unsafe": "constraint-only", "timeout": "terminal"},
        simulator_budget_remaining=3,
        wall_time_remaining_ms=60_000,
    )


def test_all_current_stage_zero_arms_receive_three_equal_numeric_evaluations() -> None:
    observation = _observation()
    matrix = run_offline_structural_matrix(
        observation,
        adapter_ids=_OFFLINE_FIXTURE_ARMS,
        requested_generations=3,
        search_space=search_space_from_observation(observation),
    )

    assert matrix.structural_fairness_passed, matrix.model_dump_json(indent=2)
    assert matrix.evidence_scope == "engineering-only-no-provider-no-px4"
    assert len(matrix.results) == len(_OFFLINE_FIXTURE_ARMS)
    for result in matrix.results:
        assert result.simulator_evaluations_attempted == 3
        assert result.simulator_evaluations_completed == 3
        assert result.proposals_dispatched == 3
        assert sum(result.status_counts.values()) == 3
        assert not result.failure_codes
        if require_registered_adapter(result.adapter_id).family == "llm_harness":
            assert 3 <= result.provider_turns_attempted <= 12
            assert result.provider_turns_attempted == result.provider_turns_succeeded
        else:
            assert result.provider_turns_attempted == result.provider_turns_succeeded == 0


def test_offline_matrix_is_byte_reproducible_and_contains_no_performance_ranking() -> None:
    observation = _observation()
    kwargs = {
        "adapter_ids": _OFFLINE_FIXTURE_ARMS,
        "requested_generations": 2,
        "search_space": search_space_from_observation(observation),
    }
    first = run_offline_structural_matrix(observation, **kwargs)
    second = run_offline_structural_matrix(observation, **kwargs)

    assert canonical_sha256(first) == canonical_sha256(second)
    serialized = str(first.model_dump(mode="json")).lower()
    assert "winner" not in serialized
    assert "ranking" not in serialized
    assert "no-px4" in first.evidence_scope
    assert "no-provider" in first.evidence_scope


def test_contract_only_external_arm_stays_a_visible_matrix_failure() -> None:
    observation = _observation()
    matrix = run_offline_structural_matrix(
        observation,
        adapter_ids=("true_lhs/v1",),
        requested_generations=2,
        search_space=search_space_from_observation(observation),
    )
    assert not matrix.structural_fairness_passed
    assert matrix.results[0].simulator_evaluations_attempted == 0
    assert matrix.results[0].failure_codes == ("offline-arm-execution-failed",)


def test_offline_matrix_rejects_tampered_counts_and_generation_contract() -> None:
    observation = _observation()
    matrix = run_offline_structural_matrix(
        observation,
        adapter_ids=("random_search/v1",),
        requested_generations=2,
        search_space=search_space_from_observation(observation),
    )
    negative_count = matrix.model_dump(mode="python")
    negative_count["results"][0]["status_counts"] = {"passed": -1}
    with pytest.raises(ValidationError):
        BenchmarkOfflineMatrixV1.model_validate(negative_count)

    mismatched_generations = matrix.model_dump(mode="python")
    mismatched_generations["requested_generations_per_arm"] = 3
    with pytest.raises(ValidationError, match="requested generations differ"):
        BenchmarkOfflineMatrixV1.model_validate(mismatched_generations)


def test_search_space_drift_fails_before_any_arm_runs() -> None:
    observation = _observation()
    drifted = SearchSpace(
        (
            ParameterDomain(
                name="kp",
                baseline=1.0,
                minimum=0.1,
                maximum=2.0,
            ),
        )
    )
    try:
        run_offline_structural_matrix(
            observation,
            adapter_ids=("random_search/v1",),
            requested_generations=2,
            search_space=drifted,
        )
    except ValueError as exc:
        assert "differs" in str(exc)
    else:
        raise AssertionError("search-space drift was not rejected")
