"""Contract tests for the deterministic synthetic optimizer benchmark."""

from __future__ import annotations

import math
from pathlib import Path

import pytest

from scripts.benchmark_experimental_optimizers import (
    _evaluate,
    _search_space,
    run_benchmark,
    write_new_benchmark_result,
)

EXPECTED_STRATEGIES = {
    "constrained_mobo",
    "multi_fidelity_mobo",
    "turbo",
    "saasbo",
    "surrogate_cma_es",
    "bipop_cma_es",
    "optimizer_portfolio",
}


def test_benchmark_reports_all_seven_strategies_under_one_contract() -> None:
    result = run_benchmark(generations=1, batch_size=1, seed=805)
    rows = result["results"]

    assert result["benchmark"] == "dronedream-constrained-synthetic-v1"
    assert "not PX4/Gazebo" in result["warning"]
    assert {row["strategy"] for row in rows} == EXPECTED_STRATEGIES
    assert sorted(row["rank"] for row in rows) == list(range(1, 8))
    assert result["initial_failed_observations"] == 2
    assert result["feedback_contract"]["failed_observations_keep_constraints"] is True
    assert len(result["result_digest"]) == 64
    assert all(row["evaluations"] == 1 for row in rows)
    assert all(row["failed_evaluations"] <= row["evaluations"] for row in rows)
    assert all(math.isfinite(row["best_feasible_loss"]) for row in rows)
    assert all(
        row["oracle_best_queried_loss"] <= row["best_feasible_loss"] + 1e-12
        for row in rows
    )
    assert all(0.0 < row["effective_fidelity_cost"] <= 1.0 for row in rows)


def test_benchmark_is_repeatable_for_the_same_seed() -> None:
    first = run_benchmark(strategies=("turbo",), generations=2, batch_size=2, seed=149)
    second = run_benchmark(strategies=("turbo",), generations=2, batch_size=2, seed=149)

    assert first == second


def test_benchmark_preserves_requested_and_effective_fidelity() -> None:
    space = _search_space()
    observation = _evaluate(
        space,
        space.baseline(),
        candidate_id="fidelity-contract",
        generation=1,
        fidelity=0.5,
        requested_fidelity=0.75,
        optimizer_strategy="multi_fidelity_mobo",
    )

    assert observation.fidelity == 0.5
    assert observation.requested_fidelity == 0.75


def test_benchmark_rejects_duplicate_strategies() -> None:
    with pytest.raises(ValueError, match="duplicates"):
        run_benchmark(
            strategies=("turbo", "turbo"),
            generations=1,
            batch_size=1,
        )


def test_benchmark_output_never_replaces_an_existing_result(tmp_path: Path) -> None:
    output = tmp_path / "benchmark.json"
    write_new_benchmark_result(output, "first\n")

    with pytest.raises(ValueError, match="already exists"):
        write_new_benchmark_result(output, "second\n")

    assert output.read_text(encoding="utf-8") == "first\n"
