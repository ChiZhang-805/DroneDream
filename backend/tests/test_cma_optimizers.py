"""Tests for the full-covariance CMA engines and adaptive portfolio."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from typing import Literal

import numpy as np
import pytest

from app.optimization import portfolio_optimizer
from app.optimization.cma_optimizers import (
    _MAX_CONDITION_NUMBER,
    _soft_feasibility_target,
    _stabilize_covariance,
    bipop_restart_plan,
    propose_bipop_cma_es,
    propose_evolutionary_candidates,
    propose_surrogate_cma_es,
    reconstruct_cma_state,
)
from app.optimization.domain import SearchSpace
from app.optimization.experimental_types import (
    ExperimentalOptimizerStrategy,
    ExperimentalProposal,
    OptimizerObservation,
    OptimizerRequest,
)
from app.optimization.portfolio_optimizer import (
    portfolio_allocation,
    portfolio_statistics,
    propose_optimizer_portfolio,
)
from app.schemas import ParameterSelection

CHILD_STRATEGIES: tuple[ExperimentalOptimizerStrategy, ...] = (
    "constrained_mobo",
    "multi_fidelity_mobo",
    "turbo",
    "saasbo",
    "surrogate_cma_es",
    "bipop_cma_es",
)


def _space() -> SearchSpace:
    return SearchSpace.from_schema(
        [
            ParameterSelection(
                name="TEST_GAIN_X",
                baseline=0.5,
                minimum=0.0,
                maximum=1.0,
                step=0.01,
            ),
            ParameterSelection(
                name="TEST_GAIN_Y",
                baseline=0.5,
                minimum=0.0,
                maximum=1.0,
                step=0.01,
            ),
            ParameterSelection(
                name="TEST_COUNT",
                baseline=2,
                minimum=0,
                maximum=4,
                step=1,
                value_type="integer",
            ),
            ParameterSelection(
                name="TEST_MODE",
                baseline=1,
                minimum=0,
                maximum=2,
                value_type="enum",
                choices=[0, 1, 2],
            ),
        ]
    )


def _high_dimensional_space(dimensions: int) -> SearchSpace:
    def validate(candidate: dict[str, float]) -> None:
        # Exercise the validity-aware retry path instead of accepting every
        # rectangular random vector.
        if candidate["TEST_PARAM_000"] > candidate["TEST_PARAM_001"]:
            raise ValueError("coupled test constraint rejected the candidate")

    return SearchSpace.from_schema(
        [
            ParameterSelection(
                name=f"TEST_PARAM_{index:03d}",
                baseline=0.5,
                minimum=0.0,
                maximum=1.0,
            )
            for index in range(dimensions)
        ],
        candidate_validator=validate,
    )


def _observation(
    space: SearchSpace,
    *,
    candidate_id: str,
    generation: int,
    vector: tuple[float, ...],
    loss: float | None,
    strategy: str,
    feasible: bool = True,
    failure_rate: float = 0.0,
    constraints: dict[str, float] | None = None,
    fidelity: float = 1.0,
    optimizer_metadata: dict[str, object] | None = None,
    completed: bool = True,
) -> OptimizerObservation:
    parameters = space.from_unit_vector(vector)
    projected_vector = space.to_unit_vector(parameters)
    return OptimizerObservation(
        candidate_id=candidate_id,
        generation_index=generation,
        parameters=parameters,
        unit_vector=projected_vector,
        loss=loss,
        feasible=feasible,
        failure_rate=failure_rate,
        constraints=constraints or {},
        optimizer_strategy=strategy,
        fidelity=fidelity,
        requested_fidelity=fidelity,
        optimizer_metadata=optimizer_metadata or {},
        completed=completed,
    )


def _request(
    strategy: ExperimentalOptimizerStrategy,
    observations: tuple[OptimizerObservation, ...] = (),
    *,
    generation: int = 3,
    batch_size: int = 4,
    seed: int = 20260714,
) -> OptimizerRequest:
    return OptimizerRequest(
        strategy=strategy,
        generation_index=generation,
        batch_size=batch_size,
        random_seed=seed,
        observations=observations,
    )


def _observation_from_proposal(
    space: SearchSpace,
    proposal: ExperimentalProposal,
    *,
    candidate_id: str,
    generation: int,
    loss: float | None,
    completed: bool = True,
) -> OptimizerObservation:
    metadata = dict(proposal.metadata)
    child_strategy = str(metadata.get("child_strategy", metadata.get("strategy", "")))
    parameters = dict(proposal.parameters)
    return OptimizerObservation(
        candidate_id=candidate_id,
        generation_index=generation,
        parameters=parameters,
        unit_vector=space.to_unit_vector(parameters),
        loss=loss,
        feasible=loss is not None,
        failure_rate=0.0 if loss is not None else 1.0,
        fidelity=float(metadata.get("effective_fidelity", metadata.get("fidelity", 1.0))),
        requested_fidelity=float(
            metadata.get("requested_fidelity", metadata.get("fidelity", 1.0))
        ),
        optimizer_strategy=child_strategy,
        optimizer_metadata=metadata,
        completed=completed,
    )


def test_full_covariance_reconstruction_learns_correlated_elites() -> None:
    space = _space()
    vectors = (
        (0.18, 0.20, 0.25, 0.0),
        (0.28, 0.30, 0.25, 0.0),
        (0.40, 0.42, 0.50, 0.5),
        (0.62, 0.64, 0.50, 0.5),
        (0.76, 0.78, 0.75, 1.0),
        (0.90, 0.92, 0.75, 1.0),
    )
    observations = tuple(
        _observation(
            space,
            candidate_id=f"corr-{index}",
            generation=1,
            vector=vector,
            loss=float(index),
            strategy="surrogate_cma_es",
        )
        for index, vector in enumerate(vectors)
    )
    state = reconstruct_cma_state(
        space,
        observations,
        strategy="surrogate_cma_es",
        population_size=6,
    )
    assert state.updates == 1
    assert state.covariance.shape == (4, 4)
    assert state.covariance[0, 1] > 0.02
    assert np.all(np.linalg.eigvalsh(state.covariance) > 0.0)


def test_surrogate_cma_is_exactly_reconstructible_and_projects_discrete_values() -> None:
    space = _space()
    observations = tuple(
        _observation(
            space,
            candidate_id=f"history-{index}",
            generation=1,
            vector=(value, value, value, value),
            loss=(value - 0.3) ** 2,
            strategy="surrogate_cma_es",
        )
        for index, value in enumerate((0.1, 0.25, 0.45, 0.7))
    )
    request = _request("surrogate_cma_es", observations)
    first = propose_surrogate_cma_es(space, request)
    second = propose_surrogate_cma_es(space, request)
    assert first == second
    assert len(first) == request.batch_size
    for proposal in first:
        assert 0.0 <= proposal.parameters["TEST_GAIN_X"] <= 1.0
        assert 0.0 <= proposal.parameters["TEST_GAIN_Y"] <= 1.0
        assert proposal.parameters["TEST_COUNT"].is_integer()
        assert proposal.parameters["TEST_MODE"] in {0.0, 1.0, 2.0}
        assert proposal.metadata["strategy"] == "surrogate_cma_es"
        assert proposal.metadata["child_strategy"] == "surrogate_cma_es"
        assert proposal.metadata["fidelity"] == 1.0
        assert proposal.metadata["backend"] == "numpy_full_covariance_cma_rbf"
        state_summary = proposal.metadata["cma_state"]
        assert "covariance" not in state_summary
        assert len(state_summary["covariance_diagonal"]) == 4
        assert len(state_summary["state_sha256"]) == 64
        assert len(proposal.metadata["reconstruction_seed"]) == 16
        int(proposal.metadata["reconstruction_seed"], 16)


def test_cma_buffers_offspring_until_a_selectable_population_is_complete() -> None:
    space = _space()
    observation = _observation(
        space,
        candidate_id="only-offspring",
        generation=1,
        vector=(0.05, 0.05, 0.0, 0.0),
        loss=0.01,
        strategy="surrogate_cma_es",
    )

    state = reconstruct_cma_state(
        space,
        (observation,),
        strategy="surrogate_cma_es",
        population_size=6,
    )

    assert state.updates == 0
    assert state.pending_offspring == 1
    assert state.mean == pytest.approx((0.5, 0.5, 0.5, 0.5))


def test_cma_explicit_cohort_caps_tail_and_never_mixes_distributions() -> None:
    space = _space()
    history: tuple[OptimizerObservation, ...] = ()
    cohort_ids: list[str] = []
    positions: list[int] = []

    for generation, expected_count in ((1, 3), (2, 3), (3, 2)):
        proposals = propose_surrogate_cma_es(
            space,
            _request(
                "surrogate_cma_es",
                history,
                generation=generation,
                batch_size=3,
                seed=700 + generation,
            ),
        )
        assert len(proposals) == expected_count
        cohort_ids.extend(str(item.metadata["cma_cohort_id"]) for item in proposals)
        positions.extend(int(item.metadata["cma_cohort_position"]) for item in proposals)
        new_rows = tuple(
            _observation_from_proposal(
                space,
                proposal,
                candidate_id=f"cohort-0-{generation}-{index}",
                generation=generation,
                loss=float(20 - len(history) - index),
            )
            for index, proposal in enumerate(proposals)
        )
        history = (*history, *new_rows)

    assert len(set(cohort_ids)) == 1
    assert positions == list(range(8))
    completed = reconstruct_cma_state(
        space,
        history,
        strategy="surrogate_cma_es",
        population_size=8,
    )
    assert completed.updates == 1
    assert completed.pending_offspring == 0

    next_proposals = propose_surrogate_cma_es(
        space,
        _request("surrogate_cma_es", history, generation=4, batch_size=3, seed=704),
    )
    assert len(next_proposals) == 3
    assert {int(item.metadata["cma_cohort_index"]) for item in next_proposals} == {1}
    assert {int(item.metadata["cma_cohort_position"]) for item in next_proposals} == {
        0,
        1,
        2,
    }
    assert {str(item.metadata["cma_cohort_id"]) for item in next_proposals} != {
        cohort_ids[0]
    }


@pytest.mark.parametrize(
    ("strategy", "proposer"),
    (
        ("surrogate_cma_es", propose_surrogate_cma_es),
        ("bipop_cma_es", propose_bipop_cma_es),
    ),
)
def test_cma_contract_replays_multiple_complete_cohorts(
    strategy: Literal["surrogate_cma_es", "bipop_cma_es"],
    proposer: Callable[[SearchSpace, OptimizerRequest], list[ExperimentalProposal]],
) -> None:
    space = _space()
    history: tuple[OptimizerObservation, ...] = ()
    generation = 1
    while True:
        proposals = proposer(
            space,
            _request(strategy, history, generation=generation, batch_size=3, seed=900 + generation),
        )
        history = (
            *history,
            *(
                _observation_from_proposal(
                    space,
                    proposal,
                    candidate_id=f"{strategy}-{generation}-{index}",
                    generation=generation,
                    loss=float(100 - generation * 4 - index),
                )
                for index, proposal in enumerate(proposals)
            ),
        )
        state = reconstruct_cma_state(
            space,
            history,
            strategy=strategy,
            population_size=8,
            initial_sigma=0.30 if strategy == "bipop_cma_es" else 0.24,
        )
        if state.updates >= 2:
            break
        generation += 1
        assert generation <= 8

    cohorts: dict[str, set[int]] = {}
    for observation in history:
        metadata = observation.optimizer_metadata
        cohort_id = str(metadata["cma_cohort_id"])
        cohorts.setdefault(cohort_id, set()).add(int(metadata["cma_cohort_position"]))
    assert len(cohorts) == 2
    assert all(positions == set(range(8)) for positions in cohorts.values())


def test_cma_explicit_cohort_replay_uses_positions_not_outcome_sort_order() -> None:
    space = _space()
    proposals = propose_surrogate_cma_es(
        space,
        _request("surrogate_cma_es", generation=1, batch_size=8, seed=811),
    )
    observations = tuple(
        _observation_from_proposal(
            space,
            proposal,
            candidate_id=f"first-{index}",
            generation=1,
            loss=float((index - 3) ** 2),
        )
        for index, proposal in enumerate(proposals)
    )
    replay = tuple(
        replace(item, candidate_id=f"renamed-{index}")
        for index, item in enumerate(reversed(observations))
    )

    first = reconstruct_cma_state(
        space,
        observations,
        strategy="surrogate_cma_es",
        population_size=8,
    )
    second = reconstruct_cma_state(
        space,
        replay,
        strategy="surrogate_cma_es",
        population_size=8,
    )

    assert first.updates == second.updates == 1
    assert first.mean == pytest.approx(second.mean)
    assert first.covariance == pytest.approx(second.covariance)


def test_cma_waits_for_every_persisted_cohort_member_to_finish() -> None:
    space = _space()
    proposals = propose_surrogate_cma_es(
        space,
        _request("surrogate_cma_es", generation=1, batch_size=8, seed=812),
    )
    observations = tuple(
        _observation_from_proposal(
            space,
            proposal,
            candidate_id=f"pending-{index}",
            generation=1,
            loss=None if index == 7 else float(index),
            completed=index != 7,
        )
        for index, proposal in enumerate(proposals)
    )

    waiting = reconstruct_cma_state(
        space,
        observations,
        strategy="surrogate_cma_es",
        population_size=8,
    )
    assert waiting.updates == 0
    assert waiting.pending_offspring == 8
    assert (
        propose_surrogate_cma_es(
            space,
            _request("surrogate_cma_es", observations, generation=2, batch_size=3),
        )
        == []
    )

    terminal_failure = replace(
        observations[-1],
        completed=True,
        role="constraint_only",
    )
    completed = reconstruct_cma_state(
        space,
        (*observations[:-1], terminal_failure),
        strategy="surrogate_cma_es",
        population_size=8,
    )
    assert completed.updates == 1


def test_cma_reissues_a_quarantined_cohort_position_without_updating_state() -> None:
    space = _space()
    proposals = propose_surrogate_cma_es(
        space,
        _request("surrogate_cma_es", generation=1, batch_size=8, seed=813),
    )
    observations = tuple(
        _observation_from_proposal(
            space,
            proposal,
            candidate_id=f"learning-{index}",
            generation=1,
            loss=float(index),
        )
        for index, proposal in enumerate(proposals[:-1])
    )

    state = reconstruct_cma_state(
        space,
        observations,
        strategy="surrogate_cma_es",
        population_size=8,
    )
    retried = propose_surrogate_cma_es(
        space,
        _request(
            "surrogate_cma_es",
            observations,
            generation=2,
            batch_size=3,
            seed=814,
        ),
    )

    assert state.updates == 0
    assert state.pending_offspring == 7
    assert len(retried) == 1
    assert retried[0].metadata["cma_cohort_index"] == 0
    assert retried[0].metadata["cma_cohort_position"] == 7
    assert retried[0].metadata["cma_distribution_sha256"] == (
        proposals[-1].metadata["cma_distribution_sha256"]
    )


def test_covariance_repair_preserves_regular_scale_and_bounds_condition() -> None:
    regular = np.diag(np.asarray((0.25, 0.5, 2.0, 4.0), dtype=np.float64))
    repaired = _stabilize_covariance(regular)
    assert repaired == pytest.approx(regular)

    extreme = np.diag(np.asarray((1e-18, 1e-8, 1e8, 1e18), dtype=np.float64))
    stable = _stabilize_covariance(extreme)
    eigenvalues = np.linalg.eigvalsh(stable)
    assert np.all(np.isfinite(stable))
    assert stable == pytest.approx(stable.T)
    assert np.all(eigenvalues > 0.0)
    assert float(np.max(eigenvalues) / np.min(eigenvalues)) <= _MAX_CONDITION_NUMBER * (
        1.0 + 1e-8
    )


def test_surrogate_cma_reconstruction_does_not_depend_on_current_batch_size() -> None:
    space = _space()
    population = 4 + int(3 * np.log(4))
    observations = tuple(
        _observation(
            space,
            candidate_id=f"cohort-{index}",
            generation=1,
            vector=(index / population, index / population, 0.5, 0.5),
            loss=float(population - index),
            strategy="surrogate_cma_es",
        )
        for index in range(population)
    )

    small = propose_surrogate_cma_es(
        space,
        _request("surrogate_cma_es", observations, batch_size=1),
    )[0].metadata["cma_state"]
    large = propose_surrogate_cma_es(
        space,
        _request("surrogate_cma_es", observations, batch_size=6),
    )[0].metadata["cma_state"]

    assert small == large
    assert small["updates"] == 1


def test_failures_train_feasibility_without_fake_objective_losses() -> None:
    space = _space()
    successes = tuple(
        _observation(
            space,
            candidate_id=f"ok-{index}",
            generation=1,
            vector=(value, value, 0.25, 0.0),
            loss=0.2 + value,
            strategy="surrogate_cma_es",
        )
        for index, value in enumerate((0.12, 0.22, 0.32))
    )
    failures = tuple(
        _observation(
            space,
            candidate_id=f"failed-{index}",
            generation=2,
            vector=(value, value, 0.75, 1.0),
            loss=None,
            strategy="surrogate_cma_es",
            feasible=False,
            failure_rate=1.0,
            constraints={"crash": 1.0},
        )
        for index, value in enumerate((0.78, 0.88, 0.98))
    )
    with_failures = propose_surrogate_cma_es(
        space,
        _request("surrogate_cma_es", successes + failures, seed=91),
    )
    without_failures = propose_surrogate_cma_es(
        space,
        _request("surrogate_cma_es", successes, seed=91),
    )
    assert with_failures != without_failures
    assert all(
        0.0 < float(proposal.metadata["predicted_feasibility"]) < 1.0 for proposal in with_failures
    )
    assert all(observation.loss is None for observation in failures)


def test_cma_feasibility_targets_preserve_constraint_severity_and_crash_priority() -> None:
    space = _space()

    def failed(
        candidate_id: str,
        *,
        constraints: dict[str, float],
        failure_rate: float = 0.0,
    ) -> OptimizerObservation:
        return _observation(
            space,
            candidate_id=candidate_id,
            generation=1,
            vector=(0.5, 0.5, 0.5, 0.5),
            loss=None,
            strategy="surrogate_cma_es",
            feasible=False,
            failure_rate=failure_rate,
            constraints=constraints,
        )

    no_margin = _soft_feasibility_target(failed("no-margin", constraints={}))
    mild = _soft_feasibility_target(failed("mild", constraints={"overshoot": 0.1}))
    severe = _soft_feasibility_target(failed("severe", constraints={"overshoot": 10.0}))
    multiple = _soft_feasibility_target(
        failed("multiple", constraints={"overshoot": 10.0, "settling": 10.0})
    )
    crash_without_margin = _soft_feasibility_target(
        failed("crash-no-margin", constraints={}, failure_rate=1.0)
    )
    crash_with_margin = _soft_feasibility_target(
        failed("crash-with-margin", constraints={"overshoot": 10.0}, failure_rate=1.0)
    )

    assert 0.01 <= multiple < severe < mild < no_margin < 0.5
    assert crash_without_margin == crash_with_margin == pytest.approx(0.02)


def test_surrogate_cma_bounds_dense_rbf_training_history() -> None:
    space = _space()
    observations = tuple(
        _observation(
            space,
            candidate_id=f"rbf-history-{index}",
            generation=index // 8,
            vector=(
                (index % 101) / 100,
                ((index * 37) % 101) / 100,
                ((index * 3) % 5) / 4,
                (index % 3) / 2,
            ),
            loss=float(((index * 17) % 101) / 100),
            strategy="constrained_mobo",
        )
        for index in range(175)
    )

    proposal = propose_surrogate_cma_es(
        space,
        _request("surrogate_cma_es", observations, generation=23, batch_size=1),
    )[0]
    diagnostics = proposal.metadata["rbf_training_set"]

    assert diagnostics["objective_source"] == 175
    assert diagnostics["feasibility_source"] == 175
    assert diagnostics["objective_active"] == diagnostics["limit"] == 160
    assert diagnostics["feasibility_active"] == diagnostics["limit"] == 160


def test_bipop_restart_schedule_alternates_and_grows_large_populations() -> None:
    initial = bipop_restart_plan(0, 8)
    small = bipop_restart_plan(1, 8)
    larger = bipop_restart_plan(2, 8)
    assert initial.regime == "large"
    assert small.regime == "small"
    assert larger.regime == "large"
    assert larger.population_size == initial.population_size * 2
    assert 0.02 <= small.initial_sigma <= 0.20


def test_bipop_detects_stagnation_and_dispatcher_returns_bounded_batch() -> None:
    space = _space()
    observations = tuple(
        _observation(
            space,
            candidate_id=f"stagnant-{generation}-{offspring}",
            generation=generation,
            vector=(0.4, 0.4, 0.5, 0.5),
            loss=1.0,
            strategy="bipop_cma_es",
        )
        for generation in range(1, 5)
        for offspring in range(bipop_restart_plan(0, 4).population_size)
    )
    request = _request(
        "bipop_cma_es",
        observations,
        generation=5,
        batch_size=3,
    )
    proposals = propose_evolutionary_candidates(space, request)
    assert proposals == propose_bipop_cma_es(space, request)
    assert 0 < len(proposals) <= 3
    assert all(proposal.metadata["restart_index"] == 1 for proposal in proposals)
    assert all(proposal.metadata["restart_regime"] == "small" for proposal in proposals)


def test_bipop_restart_uses_a_new_basin_not_the_abandoned_optimum() -> None:
    space = _space()
    population = bipop_restart_plan(0, 4).population_size
    observations = tuple(
        _observation(
            space,
            candidate_id=f"old-basin-{generation}-{offspring}",
            generation=generation,
            vector=(0.1, 0.1, 0.0, 0.0),
            loss=1.0,
            strategy="bipop_cma_es",
        )
        for generation in range(1, 5)
        for offspring in range(population)
    )

    proposal = propose_bipop_cma_es(
        space,
        _request("bipop_cma_es", observations, generation=4, batch_size=1),
    )[0]
    state = proposal.metadata["cma_state"]

    assert proposal.metadata["restart_index"] == 1
    assert state["updates"] == 0
    assert state["pending_offspring"] == 0
    assert state["mean"] != pytest.approx((0.1, 0.1, 0.0, 0.0))


def test_cma_seed_metadata_is_js_safe_and_fidelity_sensitive() -> None:
    space = _space()
    base = _observation(
        space,
        candidate_id="same-row",
        generation=1,
        vector=(0.3, 0.3, 0.5, 0.5),
        loss=0.4,
        strategy="surrogate_cma_es",
    )
    reduced = replace(base, fidelity=0.5, requested_fidelity=0.5)

    full_seed = propose_surrogate_cma_es(
        space,
        _request("surrogate_cma_es", (base,), batch_size=1),
    )[0].metadata["reconstruction_seed"]
    reduced_seed = propose_surrogate_cma_es(
        space,
        _request("surrogate_cma_es", (reduced,), batch_size=1),
    )[0].metadata["reconstruction_seed"]

    assert isinstance(full_seed, str)
    assert len(full_seed) == 16
    assert int(full_seed, 16) >= 0
    assert full_seed != reduced_seed


def test_cma_replay_is_independent_of_database_candidate_ids() -> None:
    space = _space()
    observations = tuple(
        _observation(
            space,
            candidate_id=f"first-db-{index}",
            generation=1,
            vector=(value, 1.0 - value, 0.5, 0.5),
            loss=(value - 0.35) ** 2,
            strategy="surrogate_cma_es",
        )
        for index, value in enumerate((0.05, 0.15, 0.25, 0.35, 0.45, 0.55, 0.65, 0.75))
    )
    renamed = tuple(
        replace(item, candidate_id=f"second-db-{index}")
        for index, item in enumerate(reversed(observations))
    )

    first = propose_surrogate_cma_es(
        space,
        _request("surrogate_cma_es", observations, batch_size=3),
    )
    second = propose_surrogate_cma_es(
        space,
        _request("surrogate_cma_es", renamed, batch_size=3),
    )

    assert first == second


def test_bipop_does_not_restart_while_the_best_loss_keeps_improving() -> None:
    space = _space()
    population = bipop_restart_plan(0, 4).population_size
    observations = tuple(
        _observation(
            space,
            candidate_id=f"improving-{generation}-{offspring}",
            generation=generation,
            vector=(
                0.2 + 0.01 * offspring,
                0.3 + 0.01 * offspring,
                0.5,
                0.5,
            ),
            loss=loss + 0.01 * offspring,
            strategy="bipop_cma_es",
        )
        for generation, loss in enumerate((10.0, 8.0, 6.0, 4.0), start=1)
        for offspring in range(population)
    )

    proposals = propose_bipop_cma_es(
        space,
        _request("bipop_cma_es", observations, generation=5, batch_size=3),
    )

    assert proposals
    assert all(proposal.metadata["restart_index"] == 0 for proposal in proposals)


def test_portfolio_rewards_improvement_but_keeps_an_exploration_slot() -> None:
    space = _space()
    observations: list[OptimizerObservation] = []
    for generation, loss in enumerate((1.0, 0.7, 0.35), start=1):
        observations.append(
            _observation(
                space,
                candidate_id=f"surrogate-{generation}",
                generation=generation,
                vector=(0.1 * generation, 0.1 * generation, 0.25, 0.0),
                loss=loss,
                strategy="surrogate_cma_es",
            )
        )
    for generation, loss in enumerate((1.0, 1.05, 1.1), start=1):
        observations.append(
            _observation(
                space,
                candidate_id=f"bipop-{generation}",
                generation=generation,
                vector=(0.5 + 0.1 * generation, 0.4, 0.75, 1.0),
                loss=loss,
                strategy="bipop_cma_es",
            )
        )
    request = _request(
        "optimizer_portfolio",
        tuple(observations),
        batch_size=5,
    )
    allocation = portfolio_allocation(request)
    statistics = {item.strategy: item for item in portfolio_statistics(request)}
    assert sum(allocation.values()) == 5
    assert allocation["surrogate_cma_es"] >= 1
    assert len(allocation) >= 2
    assert (
        statistics["surrogate_cma_es"].normalized_improvement
        > statistics["bipop_cma_es"].normalized_improvement
    )


def test_portfolio_only_awards_improvement_credit_at_full_fidelity() -> None:
    space = _space()
    low_fidelity_history = tuple(
        _observation(
            space,
            candidate_id=f"mf-low-{generation}",
            generation=generation,
            vector=(0.2 * generation, 0.4, 0.5, 0.5),
            loss=loss,
            strategy="multi_fidelity_mobo",
            fidelity=0.25,
        )
        for generation, loss in enumerate((10.0, 1.0), start=1)
    )

    statistic = {
        item.strategy: item
        for item in portfolio_statistics(
            _request("optimizer_portfolio", low_fidelity_history, generation=3)
        )
    }["multi_fidelity_mobo"]

    assert statistic.observations == 2
    assert statistic.full_fidelity_observations == 0
    assert statistic.normalized_improvement == 0.0


def test_portfolio_rejects_nominal_full_fidelity_with_partial_effective_coverage() -> None:
    space = _space()
    partial = replace(
        _observation(
            space,
            candidate_id="nominal-full-effective-partial",
            generation=1,
            vector=(0.4, 0.4, 0.5, 0.5),
            loss=0.1,
            strategy="multi_fidelity_mobo",
        ),
        fidelity=0.25,
        requested_fidelity=1.0,
    )

    statistic = {
        item.strategy: item
        for item in portfolio_statistics(
            _request("optimizer_portfolio", (partial,), generation=2)
        )
    }["multi_fidelity_mobo"]

    assert statistic.observations == 1
    assert statistic.full_fidelity_observations == 0
    assert statistic.normalized_improvement == 0.0


def test_portfolio_uses_a_common_baseline_instead_of_each_childs_bad_start() -> None:
    space = _space()
    baseline = _observation(
        space,
        candidate_id="common-baseline",
        generation=0,
        vector=(0.5, 0.5, 0.5, 0.5),
        loss=1.0,
        strategy="baseline",
    )
    history = (
        baseline,
        _observation(
            space,
            candidate_id="surrogate-bad-start",
            generation=1,
            vector=(0.1, 0.1, 0.25, 0.0),
            loss=10.0,
            strategy="surrogate_cma_es",
        ),
        _observation(
            space,
            candidate_id="surrogate-still-bad",
            generation=2,
            vector=(0.2, 0.2, 0.25, 0.0),
            loss=5.0,
            strategy="surrogate_cma_es",
        ),
        _observation(
            space,
            candidate_id="bipop-good-start",
            generation=1,
            vector=(0.7, 0.7, 0.75, 1.0),
            loss=0.9,
            strategy="bipop_cma_es",
        ),
        _observation(
            space,
            candidate_id="bipop-better",
            generation=2,
            vector=(0.8, 0.8, 0.75, 1.0),
            loss=0.8,
            strategy="bipop_cma_es",
        ),
    )
    statistics = {
        item.strategy: item
        for item in portfolio_statistics(
            _request("optimizer_portfolio", history, generation=3)
        )
    }

    assert statistics["surrogate_cma_es"].normalized_improvement == 0.0
    assert statistics["bipop_cma_es"].normalized_improvement == pytest.approx(0.2)


def test_portfolio_only_rewards_improvement_over_the_pre_generation_incumbent() -> None:
    space = _space()
    history = (
        _observation(
            space,
            candidate_id="baseline",
            generation=0,
            vector=(0.5, 0.5, 0.5, 0.5),
            loss=1.0,
            strategy="baseline",
        ),
        _observation(
            space,
            candidate_id="first-improvement",
            generation=1,
            vector=(0.4, 0.4, 0.5, 0.5),
            loss=0.4,
            strategy="surrogate_cma_es",
        ),
        _observation(
            space,
            candidate_id="late-non-improvement",
            generation=2,
            vector=(0.6, 0.6, 0.5, 0.5),
            loss=0.6,
            strategy="bipop_cma_es",
        ),
    )
    statistics = {
        item.strategy: item
        for item in portfolio_statistics(
            _request("optimizer_portfolio", history, generation=3)
        )
    }

    assert statistics["surrogate_cma_es"].normalized_improvement == pytest.approx(0.6)
    assert statistics["bipop_cma_es"].normalized_improvement == 0.0


def test_portfolio_incumbent_includes_reward_ineligible_valid_candidates() -> None:
    space = _space()
    history = (
        _observation(
            space,
            candidate_id="baseline",
            generation=0,
            vector=(0.5, 0.5, 0.5, 0.5),
            loss=1.0,
            strategy="baseline",
        ),
        _observation(
            space,
            candidate_id="ineligible-but-valid-incumbent",
            generation=1,
            vector=(0.4, 0.4, 0.5, 0.5),
            loss=0.4,
            strategy="surrogate_cma_es",
            optimizer_metadata={"portfolio_reward_eligible": False},
        ),
        _observation(
            space,
            candidate_id="later-worse-than-incumbent",
            generation=2,
            vector=(0.6, 0.6, 0.5, 0.5),
            loss=0.6,
            strategy="turbo",
        ),
    )
    statistics = {
        item.strategy: item
        for item in portfolio_statistics(
            _request("optimizer_portfolio", history, generation=3)
        )
    }

    assert statistics["surrogate_cma_es"].normalized_improvement == 0.0
    assert statistics["turbo"].normalized_improvement == 0.0


def test_portfolio_reward_uses_a_fixed_loss_scale() -> None:
    space = _space()

    def reward(*, baseline_loss: float, improved_loss: float) -> float:
        history = (
            _observation(
                space,
                candidate_id=f"baseline-{baseline_loss}",
                generation=0,
                vector=(0.5, 0.5, 0.5, 0.5),
                loss=baseline_loss,
                strategy="baseline",
            ),
            _observation(
                space,
                candidate_id=f"improved-{improved_loss}",
                generation=1,
                vector=(0.4, 0.4, 0.5, 0.5),
                loss=improved_loss,
                strategy="turbo",
            ),
        )
        return {
            item.strategy: item
            for item in portfolio_statistics(
                _request("optimizer_portfolio", history, generation=2)
            )
        }["turbo"].normalized_improvement

    assert reward(baseline_loss=1.0, improved_loss=0.75) == pytest.approx(0.25)
    assert reward(baseline_loss=100.0, improved_loss=99.75) == pytest.approx(0.25)
    assert reward(baseline_loss=100.0, improved_loss=98.0) == 1.0


def test_portfolio_counts_at_most_one_best_reward_per_tool_generation() -> None:
    space = _space()
    history = (
        _observation(
            space,
            candidate_id="baseline",
            generation=0,
            vector=(0.5, 0.5, 0.5, 0.5),
            loss=1.0,
            strategy="baseline",
        ),
        _observation(
            space,
            candidate_id="same-generation-good",
            generation=1,
            vector=(0.4, 0.4, 0.5, 0.5),
            loss=0.8,
            strategy="surrogate_cma_es",
        ),
        _observation(
            space,
            candidate_id="same-generation-best",
            generation=1,
            vector=(0.3, 0.3, 0.5, 0.5),
            loss=0.7,
            strategy="surrogate_cma_es",
        ),
    )
    statistic = {
        item.strategy: item
        for item in portfolio_statistics(
            _request("optimizer_portfolio", history, generation=2)
        )
    }["surrogate_cma_es"]

    assert statistic.normalized_improvement == pytest.approx(0.3)


def test_portfolio_full_fidelity_feasibility_ignores_easy_low_fidelity_rows() -> None:
    space = _space()
    history = (
        _observation(
            space,
            candidate_id="low-easy",
            generation=1,
            vector=(0.2, 0.2, 0.25, 0.0),
            loss=0.1,
            strategy="multi_fidelity_mobo",
            fidelity=0.25,
        ),
        _observation(
            space,
            candidate_id="full-failed",
            generation=2,
            vector=(0.3, 0.3, 0.25, 0.0),
            loss=None,
            strategy="multi_fidelity_mobo",
            feasible=False,
            failure_rate=1.0,
        ),
    )
    statistic = {
        item.strategy: item
        for item in portfolio_statistics(
            _request("optimizer_portfolio", history, generation=3)
        )
    }["multi_fidelity_mobo"]

    assert statistic.full_fidelity_observations == 1
    assert statistic.feasibility_rate == 0.0


def test_portfolio_fallback_never_updates_or_rewards_the_nominal_cma_child(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    space = _space()
    monkeypatch.setattr(
        portfolio_optimizer,
        "portfolio_allocation",
        lambda request: {"surrogate_cma_es": request.batch_size},
    )
    monkeypatch.setattr(
        portfolio_optimizer,
        "_delegate",
        lambda search_space, request, strategy, count: [],
    )
    request = _request("optimizer_portfolio", generation=1, batch_size=8, seed=901)
    proposals = propose_optimizer_portfolio(space, request)
    assert len(proposals) == 8
    assert all(item.metadata["optimizer_generated_by"] == "halton_fallback" for item in proposals)
    assert all(item.metadata["optimizer_update_eligible"] is False for item in proposals)
    assert all(item.metadata["portfolio_reward_eligible"] is False for item in proposals)
    assert all(item.metadata["portfolio_slot_role"] == "fallback" for item in proposals)

    observations = tuple(
        _observation_from_proposal(
            space,
            proposal,
            candidate_id=f"fallback-{index}",
            generation=1,
            loss=0.01,
        )
        for index, proposal in enumerate(proposals)
    )
    state = reconstruct_cma_state(
        space,
        observations,
        strategy="surrogate_cma_es",
        population_size=8,
    )
    statistic = {
        item.strategy: item
        for item in portfolio_statistics(
            _request("optimizer_portfolio", observations, generation=2)
        )
    }["surrogate_cma_es"]

    assert state.updates == 0
    assert statistic.full_fidelity_observations == 0
    assert statistic.normalized_improvement == 0.0


@pytest.mark.parametrize("dimensions", [63, 100])
def test_portfolio_fallback_supports_catalogs_beyond_halton_dimension_limit(
    monkeypatch: pytest.MonkeyPatch,
    dimensions: int,
) -> None:
    space = _high_dimensional_space(dimensions)
    monkeypatch.setattr(
        portfolio_optimizer,
        "portfolio_allocation",
        lambda request: {"surrogate_cma_es": request.batch_size},
    )
    monkeypatch.setattr(
        portfolio_optimizer,
        "_delegate",
        lambda search_space, request, strategy, count: [],
    )
    request = _request("optimizer_portfolio", generation=2, batch_size=3, seed=902)

    first = propose_optimizer_portfolio(space, request)
    second = propose_optimizer_portfolio(space, request)
    different_seed = propose_optimizer_portfolio(space, replace(request, random_seed=903))

    assert first == second
    assert len(first) == request.batch_size
    assert first != different_seed
    assert len({tuple(item.parameters.items()) for item in first}) == len(first)
    for proposal in first:
        assert len(proposal.parameters) == dimensions
        assert proposal.parameters["TEST_PARAM_000"] <= proposal.parameters["TEST_PARAM_001"]
        assert proposal.metadata["optimizer_generated_by"] == "seeded_random_fallback"
        assert proposal.metadata["optimizer_update_eligible"] is False
        assert proposal.metadata["portfolio_reward_eligible"] is False
        assert proposal.metadata["portfolio_slot_role"] == "fallback"
        assert proposal.metadata["backend"] == "seeded_random_emergency_fallback"


def test_portfolio_improvement_is_generation_and_candidate_id_invariant() -> None:
    space = _space()
    history = (
        _observation(
            space,
            candidate_id="first-worse",
            generation=1,
            vector=(0.2, 0.2, 0.25, 0.0),
            loss=10.0,
            strategy="surrogate_cma_es",
        ),
        _observation(
            space,
            candidate_id="first-best",
            generation=1,
            vector=(0.3, 0.3, 0.25, 0.0),
            loss=8.0,
            strategy="surrogate_cma_es",
        ),
        _observation(
            space,
            candidate_id="second-best",
            generation=2,
            vector=(0.4, 0.4, 0.5, 0.5),
            loss=4.0,
            strategy="surrogate_cma_es",
        ),
    )
    renamed = tuple(
        replace(item, candidate_id=f"renamed-{index}")
        for index, item in enumerate(reversed(history))
    )
    renamed_with_extra_dominated_candidate = (
        *renamed,
        _observation(
            space,
            candidate_id="extra-same-generation",
            generation=2,
            vector=(0.45, 0.45, 0.5, 0.5),
            loss=9.0,
            strategy="surrogate_cma_es",
        ),
    )

    first = {
        item.strategy: item
        for item in portfolio_statistics(
            _request("optimizer_portfolio", history, generation=3)
        )
    }["surrogate_cma_es"]
    second = {
        item.strategy: item
        for item in portfolio_statistics(
            _request(
                "optimizer_portfolio",
                renamed_with_extra_dominated_candidate,
                generation=3,
            )
        )
    }["surrogate_cma_es"]

    assert first.normalized_improvement == second.normalized_improvement
    assert first.recent_improvement == second.recent_improvement


def test_portfolio_keeps_a_multi_fidelity_promotion_of_seen_parameters(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    space = _space()
    observed = _observation(
        space,
        candidate_id="mf-quarter",
        generation=1,
        vector=(0.4, 0.4, 0.5, 0.5),
        loss=1.0,
        strategy="multi_fidelity_mobo",
        fidelity=0.25,
    )
    monkeypatch.setattr(
        portfolio_optimizer,
        "portfolio_allocation",
        lambda request: {"multi_fidelity_mobo": 1},
    )
    monkeypatch.setattr(
        portfolio_optimizer,
        "_delegate",
        lambda search_space, request, strategy, count: [
            ExperimentalProposal(
                label="promote-quarter-to-half",
                parameters=observed.parameters,
                rationale="promote a promising low-fidelity point",
                metadata={
                    "strategy": "multi_fidelity_mobo",
                    "fidelity": 0.5,
                    "backend": "test",
                },
            )
        ],
    )

    proposals = propose_optimizer_portfolio(
        space,
        _request("optimizer_portfolio", (observed,), generation=2, batch_size=1),
    )

    assert len(proposals) == 1
    assert proposals[0].parameters == observed.parameters
    assert proposals[0].metadata["fidelity"] == pytest.approx(0.5)


def test_portfolio_replaces_a_same_batch_low_fidelity_collision_with_full_fidelity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    space = _space()
    shared_parameters = space.from_unit_vector((0.4, 0.4, 0.5, 0.5))
    monkeypatch.setattr(
        portfolio_optimizer,
        "portfolio_allocation",
        lambda request: {"multi_fidelity_mobo": 1, "turbo": 1},
    )

    def delegate(
        search_space: SearchSpace,
        request: OptimizerRequest,
        strategy: ExperimentalOptimizerStrategy,
        count: int,
    ) -> list[ExperimentalProposal]:
        fidelity = 0.25 if strategy == "multi_fidelity_mobo" else 1.0
        return [
            ExperimentalProposal(
                label=f"same-{strategy}",
                parameters=shared_parameters,
                rationale="deliberate projected collision",
                metadata={
                    "strategy": strategy,
                    "fidelity": fidelity,
                    "requested_fidelity": fidelity,
                    "backend": "test",
                },
            )
        ]

    monkeypatch.setattr(portfolio_optimizer, "_delegate", delegate)

    proposals = propose_optimizer_portfolio(
        space,
        _request("optimizer_portfolio", generation=1, batch_size=2),
    )
    shared = [item for item in proposals if item.parameters == shared_parameters]

    assert len(shared) == 1
    assert shared[0].metadata["child_strategy"] == "turbo"
    assert shared[0].metadata["requested_fidelity"] == pytest.approx(1.0)
    sources = {
        item["child_strategy"]: item
        for item in shared[0].metadata["portfolio_sources"]
    }
    assert sources["multi_fidelity_mobo"]["materialized"] is False
    assert (
        sources["multi_fidelity_mobo"]["exclusion_reason"]
        == "superseded_by_higher_fidelity"
    )
    assert sources["turbo"]["materialized"] is True
    assert shared[0].metadata["portfolio_source_credits"] == [
        {"child_strategy": "turbo", "share": 1.0}
    ]


def test_portfolio_exact_collision_preserves_equal_cross_tool_credit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    space = _space()
    shared_parameters = space.from_unit_vector((0.4, 0.4, 0.5, 0.5))
    monkeypatch.setattr(
        portfolio_optimizer,
        "portfolio_allocation",
        lambda request: {"constrained_mobo": 1, "turbo": 1},
    )

    def delegate(
        search_space: SearchSpace,
        request: OptimizerRequest,
        strategy: ExperimentalOptimizerStrategy,
        count: int,
    ) -> list[ExperimentalProposal]:
        return [
            ExperimentalProposal(
                label=f"same-{strategy}",
                parameters=shared_parameters,
                rationale="deliberate exact action collision",
                metadata={
                    "strategy": strategy,
                    "fidelity": 1.0,
                    "requested_fidelity": 1.0,
                    "backend": "test",
                },
            )
        ]

    monkeypatch.setattr(portfolio_optimizer, "_delegate", delegate)

    proposals = propose_optimizer_portfolio(
        space,
        _request("optimizer_portfolio", generation=1, batch_size=2),
    )
    shared = next(
        item for item in proposals if item.parameters == shared_parameters
    )

    assert len(proposals) == 2
    assert {
        item["child_strategy"]
        for item in shared.metadata["portfolio_sources"]
        if item["materialized"]
    } == {"constrained_mobo", "turbo"}
    assert shared.metadata["portfolio_source_credits"] == [
        {"child_strategy": "constrained_mobo", "share": 0.5},
        {"child_strategy": "turbo", "share": 0.5},
    ]

    observation = _observation_from_proposal(
        space,
        shared,
        candidate_id="shared-credit",
        generation=1,
        loss=0.5,
    )
    baseline = _observation(
        space,
        candidate_id="shared-credit-baseline",
        generation=0,
        vector=(0.5, 0.5, 0.5, 0.5),
        loss=1.0,
        strategy="baseline",
    )
    statistics = {
        item.strategy: item
        for item in portfolio_statistics(
            _request(
                "optimizer_portfolio",
                (baseline, observation),
                generation=2,
            )
        )
    }
    assert statistics["constrained_mobo"].full_fidelity_observations == 1
    assert statistics["turbo"].full_fidelity_observations == 1
    assert statistics["constrained_mobo"].reward_credit == pytest.approx(0.5)
    assert statistics["turbo"].reward_credit == pytest.approx(0.5)
    assert statistics["constrained_mobo"].normalized_improvement == pytest.approx(
        0.25
    )
    assert statistics["turbo"].normalized_improvement == pytest.approx(0.25)


def test_portfolio_same_child_fidelity_upgrade_keeps_one_materialized_source(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    space = _space()
    shared_parameters = space.from_unit_vector((0.4, 0.4, 0.5, 0.5))
    monkeypatch.setattr(
        portfolio_optimizer,
        "portfolio_allocation",
        lambda request: {"multi_fidelity_mobo": 2},
    )
    monkeypatch.setattr(
        portfolio_optimizer,
        "_delegate",
        lambda search_space, request, strategy, count: [
            ExperimentalProposal(
                label=f"same-child-{fidelity}",
                parameters=shared_parameters,
                rationale="same child fidelity upgrade",
                metadata={
                    "strategy": strategy,
                    "fidelity": fidelity,
                    "requested_fidelity": fidelity,
                    "backend": "test",
                },
            )
            for fidelity in (0.25, 1.0)
        ],
    )

    proposals = propose_optimizer_portfolio(
        space,
        _request("optimizer_portfolio", generation=1, batch_size=2),
    )
    upgraded = next(
        item for item in proposals if item.parameters == shared_parameters
    )

    assert upgraded.metadata["requested_fidelity"] == pytest.approx(1.0)
    assert upgraded.metadata["portfolio_sources"] == [
        {
            "child_strategy": "multi_fidelity_mobo",
            "generated_by": "multi_fidelity_mobo",
            "planned_slot_role": "externally_planned",
            "effective_fidelity": 1.0,
            "requested_fidelity": 1.0,
            "materialized": True,
            "reward_eligible": True,
            "exclusion_reason": None,
        }
    ]
    assert upgraded.metadata["portfolio_source_credits"] == [
        {"child_strategy": "multi_fidelity_mobo", "share": 1.0}
    ]


def test_serial_portfolio_exploits_four_generations_and_periodically_explores() -> None:
    space = _space()
    observations: list[OptimizerObservation] = []
    child_strategies = (
        "constrained_mobo",
        "multi_fidelity_mobo",
        "turbo",
        "saasbo",
        "surrogate_cma_es",
        "bipop_cma_es",
    )
    for index, strategy in enumerate(child_strategies):
        observations.append(
            _observation(
                space,
                candidate_id=f"initial-{strategy}",
                generation=1,
                vector=(0.1 + index * 0.1, 0.2, 0.25, 0.0),
                loss=1.0,
                strategy=strategy,
            )
        )
    observations.extend(
        [
            _observation(
                space,
                candidate_id="surrogate-improved-1",
                generation=2,
                vector=(0.25, 0.25, 0.5, 0.5),
                loss=0.5,
                strategy="surrogate_cma_es",
            ),
            _observation(
                space,
                candidate_id="surrogate-improved-2",
                generation=3,
                vector=(0.3, 0.3, 0.5, 0.5),
                loss=0.2,
                strategy="surrogate_cma_es",
            ),
        ]
    )
    exploit = portfolio_allocation(
        _request(
            "optimizer_portfolio",
            tuple(observations),
            generation=4,
            batch_size=1,
        )
    )
    explore = portfolio_allocation(
        _request(
            "optimizer_portfolio",
            tuple(observations),
            generation=5,
            batch_size=1,
        )
    )
    assert exploit == {"surrogate_cma_es": 1}
    assert explore != exploit
    assert sum(explore.values()) == 1


@pytest.mark.parametrize(
    ("batch_size", "expected_exploration"),
    [(6, 1), (8, 2)],
)
def test_warm_portfolio_uses_twenty_percent_exploration_instead_of_six_way_coverage(
    batch_size: int,
    expected_exploration: int,
) -> None:
    space = _space()
    child_strategies = (
        "constrained_mobo",
        "multi_fidelity_mobo",
        "turbo",
        "saasbo",
        "surrogate_cma_es",
        "bipop_cma_es",
    )
    observations = [
        _observation(
            space,
            candidate_id=f"covered-{strategy}",
            generation=1,
            vector=(0.1 + index * 0.1, 0.2, 0.25, 0.0),
            loss=1.0,
            strategy=strategy,
        )
        for index, strategy in enumerate(child_strategies)
    ]
    observations.extend(
        [
            _observation(
                space,
                candidate_id="surrogate-warm-improved-1",
                generation=2,
                vector=(0.25, 0.25, 0.5, 0.5),
                loss=0.5,
                strategy="surrogate_cma_es",
            ),
            _observation(
                space,
                candidate_id="surrogate-warm-improved-2",
                generation=3,
                vector=(0.3, 0.3, 0.5, 0.5),
                loss=0.2,
                strategy="surrogate_cma_es",
            ),
        ]
    )
    request = _request(
        "optimizer_portfolio",
        tuple(observations),
        generation=4,
        batch_size=batch_size,
    )

    allocation, roles = portfolio_optimizer._portfolio_plan(request)
    assigned_roles = [role for strategy_roles in roles.values() for role in strategy_roles]

    assert sum(allocation.values()) == batch_size
    assert "coverage" not in assigned_roles
    assert assigned_roles.count("exploration") == expected_exploration
    assert assigned_roles.count("exploitation") == batch_size - expected_exploration
    assert allocation["surrogate_cma_es"] >= batch_size - expected_exploration


def test_portfolio_proposals_expose_child_ownership_and_backend() -> None:
    space = _space()
    request = _request("optimizer_portfolio", batch_size=6, generation=1)
    proposals = propose_optimizer_portfolio(space, request)
    dispatched = propose_evolutionary_candidates(space, request)
    # Some integration fixtures deliberately reload all ``app.*`` modules.
    # Validate the delayed dispatcher contract structurally instead of relying
    # on dataclass equality across two otherwise equivalent module instances.
    assert len(dispatched) == request.batch_size
    assert all(item.metadata["strategy"] == "optimizer_portfolio" for item in dispatched)
    assert all(item.metadata["child_strategy"] in CHILD_STRATEGIES for item in dispatched)
    assert len(proposals) == request.batch_size
    assert len({tuple(sorted(item.parameters.items())) for item in proposals}) == len(proposals)
    assert {item.metadata["child_strategy"] for item in proposals} == {
        "constrained_mobo",
        "multi_fidelity_mobo",
        "turbo",
        "saasbo",
        "surrogate_cma_es",
        "bipop_cma_es",
    }
    for proposal in proposals:
        assert proposal.metadata["strategy"] == "optimizer_portfolio"
        assert proposal.metadata["child_strategy"] in {
            "constrained_mobo",
            "multi_fidelity_mobo",
            "turbo",
            "saasbo",
            "surrogate_cma_es",
            "bipop_cma_es",
        }
        assert 0.05 <= float(proposal.metadata["fidelity"]) <= 1.0
        assert proposal.metadata["backend"]
        assert proposal.metadata["portfolio_slot_role"] == "coverage"
        assert proposal.metadata["portfolio_planned_slot_role"] == "coverage"
        assert proposal.metadata["exploration_retained"] is True
        assert proposal.metadata["portfolio_allocation"] == {
            "constrained_mobo": 1,
            "multi_fidelity_mobo": 1,
            "turbo": 1,
            "saasbo": 1,
            "surrogate_cma_es": 1,
            "bipop_cma_es": 1,
        }
        for seed_key in ("portfolio_random_seed", "child_random_seed"):
            seed = proposal.metadata[seed_key]
            assert isinstance(seed, str)
            assert len(seed) == 16
            int(seed, 16)


def test_portfolio_delegates_exactly_each_childs_awarded_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    space = _space()
    delegated: dict[str, int] = {}

    def delegate(
        search_space: SearchSpace,
        request: OptimizerRequest,
        strategy: ExperimentalOptimizerStrategy,
        count: int,
    ) -> list[ExperimentalProposal]:
        delegated[strategy] = count
        index = tuple(CHILD_STRATEGIES).index(strategy)
        return [
            ExperimentalProposal(
                label=f"delegated-{strategy}",
                parameters=search_space.from_unit_vector(
                    (0.08 + index * 0.14, 0.2, 0.25, 0.0)
                ),
                rationale="capture the child budget",
                metadata={"strategy": strategy, "fidelity": 1.0, "backend": "test"},
            )
        ]

    monkeypatch.setattr(portfolio_optimizer, "_delegate", delegate)

    proposals = propose_optimizer_portfolio(
        space,
        _request("optimizer_portfolio", batch_size=6, generation=1),
    )

    assert len(proposals) == 6
    assert delegated == {strategy: 1 for strategy in CHILD_STRATEGIES}


def test_evolutionary_dispatch_rejects_non_evolutionary_strategy() -> None:
    with pytest.raises(ValueError, match="unsupported evolutionary optimizer"):
        propose_evolutionary_candidates(
            _space(),
            _request("constrained_mobo"),
        )
