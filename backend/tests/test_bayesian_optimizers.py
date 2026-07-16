from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from typing import cast

import pytest
from app.optimization import bayesian_optimizers
from app.optimization.bayesian_optimizers import propose_bayesian_candidates
from app.optimization.domain import ParameterDomain, SearchSpace
from app.optimization.experimental_types import (
    ExperimentalOptimizerStrategy,
    ExperimentalProposal,
    OptimizerObservation,
    OptimizerRequest,
)
from app.optimization.gaussian_process import Matern52ARDGaussianProcess, matern52_ard

_AUTO_LOSS = object()


def _space(*, validate: bool = False) -> SearchSpace:
    def validator(candidate: dict[str, float]) -> None:
        if candidate["x"] + candidate["y"] > 1.65:
            raise ValueError("coupled safety limit")

    return SearchSpace(
        [
            ParameterDomain("x", 0.4, 0.0, 1.0, step=0.025),
            ParameterDomain("y", 0.5, 0.0, 1.0, step=0.025),
        ],
        candidate_validator=validator if validate else None,
    )


def _observation(
    index: int,
    x: float,
    y: float,
    *,
    feasible: bool = True,
    fidelity: float = 1.0,
    loss: float | None | object = _AUTO_LOSS,
) -> OptimizerObservation:
    measured_loss = (
        (x - 0.82) ** 2 + 0.15 * (y - 0.25) ** 2
        if loss is _AUTO_LOSS
        else cast(float | None, loss)
    )
    return OptimizerObservation(
        candidate_id=f"candidate-{index}",
        generation_index=index,
        parameters={"x": x, "y": y},
        unit_vector=(x, y),
        loss=measured_loss,
        objectives=(
            {"tracking": measured_loss, "speed": x}
            if measured_loss is not None
            else {}
        ),
        objective_directions=(
            {"tracking": "minimize", "speed": "maximize"}
            if measured_loss is not None
            else {}
        ),
        constraints={"instability_margin": 0.0 if feasible else 1.0},
        feasible=feasible,
        failure_rate=0.0 if feasible else 1.0,
        fidelity=fidelity,
        requested_fidelity=fidelity,
    )


def _grid_observations(*, failures: bool = False) -> tuple[OptimizerObservation, ...]:
    observations: list[OptimizerObservation] = []
    for index in range(30):
        x = (index % 6) / 5
        y = (index // 6) / 4
        observations.append(_observation(index, x, y, feasible=not (failures and x >= 0.6)))
    return tuple(observations)


def _request(
    strategy: str,
    observations: tuple[OptimizerObservation, ...] = (),
    *,
    seed: int = 23,
    batch_size: int = 3,
) -> OptimizerRequest:
    return OptimizerRequest(
        strategy=cast(ExperimentalOptimizerStrategy, strategy),
        generation_index=7,
        batch_size=batch_size,
        random_seed=seed,
        observations=observations,
    )


def test_matern52_ard_gp_is_deterministic_and_reduces_observed_uncertainty() -> None:
    features = [(0.0, 0.0), (0.25, 0.8), (0.5, 0.2), (0.75, 0.9), (1.0, 0.1)]
    targets = [(x - 0.7) ** 2 + 0.05 * y for x, y in features]
    first = Matern52ARDGaussianProcess(noise=1e-6).fit(features, targets)
    second = Matern52ARDGaussianProcess(noise=1e-6).fit(features, targets)

    observed = first.predict(features[2])
    unobserved = first.predict((0.9, 0.55))
    assert first.length_scales == second.length_scales
    assert first.predict((0.61, 0.33)) == second.predict((0.61, 0.33))
    assert observed.mean == pytest.approx(targets[2], abs=2e-4)
    assert observed.standard_deviation < unobserved.standard_deviation
    assert first.length_scales[0] != first.length_scales[1]
    assert matern52_ard((0.2, 0.2), (0.2, 0.2), (0.3, 0.7)) == pytest.approx(1.0)


def test_constant_target_gp_retains_epistemic_uncertainty() -> None:
    model = Matern52ARDGaussianProcess(noise=1e-6).fit(
        [(0.0,), (1.0,)],
        [5.0, 5.0],
    )

    observed = model.predict((0.0,))
    unobserved = model.predict((0.5,))

    assert observed.mean == pytest.approx(5.0, abs=1e-9)
    assert unobserved.mean == pytest.approx(5.0, abs=1e-9)
    assert unobserved.standard_deviation > 0.01
    assert unobserved.standard_deviation > observed.standard_deviation * 10


@pytest.mark.parametrize(
    ("factory", "message"),
    [
        (lambda: Matern52ARDGaussianProcess(noise=float("nan")), "noise"),
        (lambda: Matern52ARDGaussianProcess(amplitude=float("inf")), "amplitude"),
        (
            lambda: Matern52ARDGaussianProcess(length_scales=[float("nan")]),
            "length_scales",
        ),
    ],
)
def test_gp_rejects_non_finite_hyperparameters(
    factory: Callable[[], object], message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        factory()


def test_gp_rejects_non_finite_noise_and_prediction_inputs() -> None:
    with pytest.raises(ValueError, match="observation_noise"):
        Matern52ARDGaussianProcess().fit(
            [(0.0,), (1.0,)],
            [0.0, 1.0],
            observation_noise=[0.0, float("nan")],
        )
    model = Matern52ARDGaussianProcess().fit([(0.0,), (1.0,)], [0.0, 1.0])
    with pytest.raises(ValueError, match="prediction features"):
        model.predict((float("inf"),))


def test_gp_active_set_leaves_small_histories_unchanged() -> None:
    entries = tuple(
        bayesian_optimizers._ActiveSetEntry(
            observation=observation,
            features=observation.unit_vector,
            target=float(observation.loss or 0.0),
        )
        for observation in _grid_observations()[:10]
    )

    selected = bayesian_optimizers._select_gp_active_set(
        entries,
        minimize_target=True,
        limit=10,
    )

    assert selected == entries


def test_gp_active_set_preserves_elite_recent_failure_boundary_and_space_coverage() -> None:
    observations: list[OptimizerObservation] = []
    for index in range(40):
        x = 0.2 + 0.6 * ((index * 17) % 41) / 40
        y = 0.2 + 0.6 * ((index * 11) % 41) / 40
        observations.append(_observation(index, x, y, loss=10.0 + index))
    observations[5] = _observation(5, 0.53, 0.47, loss=-100.0)
    observations[20] = replace(
        _observation(20, 0.45, 0.55, feasible=False, loss=25.0),
        failure_rate=1.0,
    )
    observations[21] = _observation(21, 0.0, 0.55, loss=31.0)
    entries = tuple(
        bayesian_optimizers._ActiveSetEntry(
            observation=observation,
            features=observation.unit_vector,
            target=float(observation.loss or 0.0),
        )
        for observation in observations
    )

    selected = bayesian_optimizers._select_gp_active_set(
        entries,
        minimize_target=True,
        limit=12,
    )
    selected_ids = {entry.observation.candidate_id for entry in selected}

    assert len(selected) == 12
    assert "candidate-5" in selected_ids  # global elite
    assert "candidate-39" in selected_ids  # newest generation
    assert "candidate-20" in selected_ids  # explicit simulator failure
    assert "candidate-21" in selected_ids  # exact parameter-space boundary
    assert len({entry.features for entry in selected}) == 12

    renamed_reversed = tuple(
        replace(entry, observation=replace(entry.observation, candidate_id=f"uuid-{index}"))
        for index, entry in enumerate(reversed(entries))
    )
    selected_again = bayesian_optimizers._select_gp_active_set(
        renamed_reversed,
        minimize_target=True,
        limit=12,
    )
    assert {(entry.features, entry.target) for entry in selected} == {
        (entry.features, entry.target) for entry in selected_again
    }


def test_large_history_reports_objective_and_feasibility_active_sets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(bayesian_optimizers, "_EXACT_GP_ACTIVE_SET_LIMIT", 12)
    observations = tuple(
        _observation(
            index,
            (index % 8) / 7,
            (index // 8) / 4,
            feasible=index % 9 != 0,
        )
        for index in range(40)
    )

    proposals = propose_bayesian_candidates(
        _space(),
        _request("constrained_mobo", observations, seed=83, batch_size=1),
    )

    training = proposals[0].metadata["gp_training_set"]
    assert training["active"] is True
    assert training["limit_per_exact_gp"] == 12
    assert "active set" in training["method"]
    assert training["feasibility"] == {"source": 40, "active": 12}
    assert training["metrics"]["__loss__"] == {"source": 40, "active": 12}
    assert training["metrics"]["tracking"] == {"source": 40, "active": 12}
    assert training["metrics"]["speed"] == {"source": 40, "active": 12}


def test_failure_only_cold_start_reports_feasibility_active_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(bayesian_optimizers, "_EXACT_GP_ACTIVE_SET_LIMIT", 12)
    crashes = tuple(
        replace(
            _observation(index, (index % 8) / 7, (index // 8) / 4),
            loss=None,
            objectives={},
            feasible=False,
            failure_rate=1.0,
        )
        for index in range(40)
    )

    proposal = propose_bayesian_candidates(
        _space(),
        _request("constrained_mobo", crashes, seed=89, batch_size=1),
    )[0]

    assert proposal.metadata["cold_start"] is True
    training = proposal.metadata["gp_training_set"]
    assert training["active"] is True
    assert training["feasibility"] == {"source": 40, "active": 12}


def test_pending_observations_are_reserved_but_never_train_models() -> None:
    pending = tuple(
        replace(
            _observation(index, (index % 5) / 4, (index // 5) / 3),
            completed=False,
        )
        for index in range(20)
    )

    proposals = propose_bayesian_candidates(
        _space(),
        _request("constrained_mobo", pending, seed=97, batch_size=2),
    )

    assert all(proposal.metadata["cold_start"] is True for proposal in proposals)
    assert all(
        proposal.metadata["gp_training_set"]["feasibility"]
        == {"source": 0, "active": 0}
        for proposal in proposals
    )
    pending_parameters = {_proposal_key(item.parameters) for item in pending}
    assert all(_proposal_key(item.parameters) not in pending_parameters for item in proposals)
    assert all(
        proposal.metadata["gp_training_set"]["metrics"] == {}
        for proposal in proposals
    )


def test_scalarized_incumbent_is_an_achievable_joint_objective_vector() -> None:
    observations = (
        replace(
            _observation(1, 0.2, 0.2),
            objectives={"first": 0.0, "second": 1.0},
            objective_directions={"first": "minimize", "second": "minimize"},
        ),
        replace(
            _observation(2, 0.8, 0.8),
            objectives={"first": 1.0, "second": 0.0},
            objective_directions={"first": "minimize", "second": "minimize"},
        ),
    )
    _, models = bayesian_optimizers._fit_models(
        observations,
        feature_builder=lambda observation: observation.unit_vector,
    )

    incumbents = bayesian_optimizers._joint_scalarized_incumbents(
        observations,
        models,
        ((0.5, 0.5),),
    )

    # Independent metric minima would produce the impossible utopia value 0.
    assert incumbents == pytest.approx((0.5,))


def test_scalarized_incumbent_does_not_invent_utopia_from_partial_objectives() -> None:
    observations = (
        replace(
            _observation(1, 0.2, 0.2),
            objectives={"first": 0.0},
            objective_directions={"first": "minimize", "second": "minimize"},
        ),
        replace(
            _observation(2, 0.8, 0.8),
            objectives={"second": 0.0},
            objective_directions={"first": "minimize", "second": "minimize"},
        ),
    )
    _, models = bayesian_optimizers._fit_models(
        observations,
        feature_builder=lambda observation: observation.unit_vector,
    )
    scalarizations = ((0.5, 0.5),)

    incumbents = bayesian_optimizers._joint_scalarized_incumbents(
        observations,
        models,
        scalarizations,
    )

    assert incumbents == ()
    assert (
        bayesian_optimizers._multiobjective_utility(
            (0.5, 0.5),
            models,
            scalarizations,
            incumbents,
        )
        == 0.0
    )


def test_constraint_violation_magnitude_softens_feasibility_without_overriding_crash() -> None:
    base = replace(
        _observation(1, 0.4, 0.5, feasible=False),
        loss=0.4,
        failure_rate=0.0,
        constraints={},
    )
    mild = replace(base, constraints={"stability": 0.01})
    severe = replace(base, constraints={"stability": 10.0})
    multiple = replace(
        base,
        constraints={"stability": 1.0, "control_authority": 1.0},
    )

    no_margin_target = bayesian_optimizers._soft_feasibility_target(base)
    mild_target = bayesian_optimizers._soft_feasibility_target(mild)
    severe_target = bayesian_optimizers._soft_feasibility_target(severe)
    multiple_target = bayesian_optimizers._soft_feasibility_target(multiple)

    assert no_margin_target == pytest.approx(0.25)
    assert no_margin_target > mild_target > severe_target > 0.02
    assert multiple_target < mild_target

    severe_model_observation = replace(
        severe,
        candidate_id="severe-boundary",
        parameters={"x": 0.8, "y": 0.8},
        unit_vector=(0.8, 0.8),
    )
    feasibility_model = bayesian_optimizers._FeasibilityModel(
        (mild, severe_model_observation),
        _space(),
        feature_builder=lambda observation: observation.unit_vector,
    )
    assert feasibility_model.probability(mild.unit_vector) > feasibility_model.probability(
        severe_model_observation.unit_vector
    )

    clean_crash = replace(base, loss=None, failure_rate=1.0, constraints={})
    diagnostic_crash = replace(
        clean_crash,
        constraints={"stability": 100.0, "control_authority": 50.0},
    )
    assert bayesian_optimizers._soft_feasibility_target(clean_crash) == pytest.approx(0.02)
    assert bayesian_optimizers._soft_feasibility_target(diagnostic_crash) == pytest.approx(0.02)


def test_full_target_scalarization_never_uses_reduced_fidelity_incumbent() -> None:
    reduced = (
        replace(
            _observation(1, 0.2, 0.2, fidelity=0.25),
            objectives={"first": 0.0, "second": 1.0},
            objective_directions={"first": "minimize", "second": "minimize"},
        ),
        replace(
            _observation(2, 0.8, 0.8, fidelity=0.5),
            objectives={"first": 1.0, "second": 0.0},
            objective_directions={"first": "minimize", "second": "minimize"},
        ),
    )
    _, models = bayesian_optimizers._fit_models(
        reduced,
        feature_builder=lambda observation: (*observation.unit_vector, observation.fidelity),
    )
    scalarizations = ((0.5, 0.5),)

    assert bayesian_optimizers._joint_scalarized_incumbents(
        reduced,
        models,
        scalarizations,
    ) == pytest.approx((0.5,))
    assert (
        bayesian_optimizers._joint_scalarized_incumbents(
            reduced,
            models,
            scalarizations,
            prefer_full_fidelity=True,
        )
        == ()
    )

    full = replace(
        _observation(3, 0.5, 0.5, fidelity=1.0),
        objectives={"first": 0.8, "second": 0.8},
        objective_directions={"first": "minimize", "second": "minimize"},
    )
    _, models_with_full = bayesian_optimizers._fit_models(
        (*reduced, full),
        feature_builder=lambda observation: (*observation.unit_vector, observation.fidelity),
    )
    assert bayesian_optimizers._joint_scalarized_incumbents(
        (*reduced, full),
        models_with_full,
        scalarizations,
        prefer_full_fidelity=True,
    ) == pytest.approx((0.8,))


@pytest.mark.parametrize(
    "strategy",
    ["constrained_mobo", "multi_fidelity_mobo", "turbo", "saasbo"],
)
def test_every_bayesian_strategy_has_deterministic_legal_unique_cold_start(
    strategy: str,
) -> None:
    search_space = _space(validate=True)
    first = propose_bayesian_candidates(search_space, _request(strategy))
    second = propose_bayesian_candidates(search_space, _request(strategy))

    assert first == second
    assert len(first) == 3
    assert len({_proposal_key(proposal.parameters) for proposal in first}) == 3
    for proposal in first:
        assert proposal.metadata["strategy"] == strategy
        assert isinstance(proposal.metadata["backend"], str)
        assert 0.05 <= float(proposal.metadata["fidelity"]) <= 1.0
        assert proposal.metadata["cold_start"] is True
        assert proposal.parameters["x"] + proposal.parameters["y"] <= 1.65
        assert proposal.parameters["x"] * 40 == pytest.approx(round(proposal.parameters["x"] * 40))


def test_cold_start_uses_failure_feedback_in_candidate_selection() -> None:
    observed = tuple(
        _observation(index, x, y, loss=None)
        for index, (x, y) in enumerate(
            ((0.0, 0.0), (0.0, 0.25), (0.25, 0.0), (0.25, 0.25))
        )
    )
    feasible_history = tuple(
        replace(item, feasible=True, failure_rate=0.0) for item in observed
    )
    crash_history = tuple(
        replace(item, feasible=False, failure_rate=1.0) for item in observed
    )

    safe = propose_bayesian_candidates(
        _space(), _request("constrained_mobo", feasible_history, seed=811)
    )
    failed = propose_bayesian_candidates(
        _space(), _request("constrained_mobo", crash_history, seed=811)
    )

    assert [item.parameters for item in safe] != [item.parameters for item in failed]
    assert all(
        item.metadata["selection_role"] == "failure_aware_screening" for item in safe
    )


def test_bayesian_seed_uses_high_uint64_bits() -> None:
    low = propose_bayesian_candidates(
        _space(), _request("constrained_mobo", seed=123, batch_size=2)
    )
    high = propose_bayesian_candidates(
        _space(), _request("constrained_mobo", seed=123 + 2**32, batch_size=2)
    )

    assert [item.parameters for item in low] != [item.parameters for item in high]


@pytest.mark.parametrize("dimension", [62, 63, 64, 65, 100])
def test_high_dimensional_cold_start_falls_back_after_halton_capacity(
    dimension: int,
) -> None:
    search_space = SearchSpace(
        [
            ParameterDomain(f"x_{axis}", 0.5, 0.0, 1.0)
            for axis in range(dimension)
        ]
    )
    request = OptimizerRequest(
        strategy="saasbo",
        generation_index=0,
        batch_size=2,
        random_seed=2**48 + 17,
        observations=(),
    )

    proposals = propose_bayesian_candidates(search_space, request)

    assert len(proposals) == 2
    assert all(search_space.project(item.parameters) == item.parameters for item in proposals)


def _proposal_key(parameters: dict[str, float]) -> tuple[tuple[str, float], ...]:
    return tuple(sorted(parameters.items()))


def test_constrained_mobo_uses_failures_instead_of_fabricated_penalty() -> None:
    search_space = _space()
    unconstrained = propose_bayesian_candidates(
        search_space, _request("constrained_mobo", _grid_observations())
    )
    failure_aware = propose_bayesian_candidates(
        search_space,
        _request("constrained_mobo", _grid_observations(failures=True)),
    )

    assert min(proposal.parameters["x"] for proposal in unconstrained) >= 0.75
    assert max(proposal.parameters["x"] for proposal in failure_aware) < 0.6
    assert all(
        proposal.metadata["acquisition"] == "constrained_random_scalarized_log_ei"
        for proposal in failure_aware
    )
    assert all(
        float(proposal.metadata["feasibility_probability"]) < 0.95 for proposal in failure_aware
    )


def test_constrained_mobo_honors_objective_direction_when_loss_is_uninformative() -> None:
    search_space = _space()
    observations = tuple(
        OptimizerObservation(
            candidate_id=f"direction-{index}",
            generation_index=index,
            parameters={"x": (index % 6) / 5, "y": (index // 6) / 4},
            unit_vector=((index % 6) / 5, (index // 6) / 4),
            loss=1.0,
            objectives={"position": (index % 6) / 5},
            objective_directions={"position": "maximize"},
        )
        for index in range(30)
    )
    maximize = propose_bayesian_candidates(search_space, _request("constrained_mobo", observations))
    minimize = propose_bayesian_candidates(
        search_space,
        _request(
            "constrained_mobo",
            tuple(
                replace(item, objective_directions={"position": "minimize"})
                for item in observations
            ),
        ),
    )

    assert min(proposal.parameters["x"] for proposal in maximize) > 0.9
    assert max(proposal.parameters["x"] for proposal in minimize) < 0.1


def test_non_mf_safety_model_ignores_reduced_fidelity_labels() -> None:
    full_history = _grid_observations()[:16]
    reduced = _observation(
        100,
        0.95,
        0.95,
        fidelity=0.25,
        loss=None,
    )
    reduced_safe = replace(reduced, feasible=True, failure_rate=0.0)
    reduced_crash = replace(reduced, feasible=False, failure_rate=1.0)

    safe = propose_bayesian_candidates(
        _space(),
        _request("constrained_mobo", (*full_history, reduced_safe), seed=733),
    )
    crash = propose_bayesian_candidates(
        _space(),
        _request("constrained_mobo", (*full_history, reduced_crash), seed=733),
    )

    assert safe == crash


def test_multi_fidelity_model_changes_decision_when_fidelity_history_changes() -> None:
    search_space = _space()

    def history(reverse: bool) -> tuple[OptimizerObservation, ...]:
        result: list[OptimizerObservation] = []
        for index in range(24):
            x = (index % 6) / 5
            y = (index // 6) / 3
            fidelity = 0.25 if index < 12 else 1.0
            if reverse:
                fidelity = 1.25 - fidelity
            # The best x changes with fidelity, making fidelity an informative
            # input rather than passive proposal metadata.
            loss = (x - (0.2 + 0.6 * fidelity)) ** 2 + 0.1 * (y - 0.3) ** 2
            result.append(_observation(index, x, y, fidelity=fidelity, loss=loss))
        return tuple(result)

    normal = propose_bayesian_candidates(
        search_space, _request("multi_fidelity_mobo", history(False), seed=9)
    )
    reversed_history = propose_bayesian_candidates(
        search_space, _request("multi_fidelity_mobo", history(True), seed=9)
    )

    assert normal != reversed_history
    assert all(
        proposal.metadata["backend"] == "native_cost_aware_matern52_ard_gp" for proposal in normal
    )
    assert all(proposal.metadata["fidelity_levels"] == [0.25, 0.5, 1.0] for proposal in normal)


def test_multi_fidelity_cold_start_records_effective_matrix_coverage() -> None:
    request = replace(
        _request("multi_fidelity_mobo", batch_size=1),
        fidelity_mapping=((0.25, 1.0 / 3.0), (0.5, 2.0 / 3.0), (1.0, 1.0)),
    )

    proposal = propose_bayesian_candidates(_space(), request)[0]

    assert proposal.metadata["requested_fidelity"] == pytest.approx(0.25)
    assert proposal.metadata["effective_fidelity"] == pytest.approx(1.0 / 3.0)
    assert proposal.metadata["fidelity"] == pytest.approx(1.0 / 3.0)


def test_multi_fidelity_collapses_nominal_levels_with_identical_execution_coverage() -> None:
    observations = _grid_observations()[:12]
    request = replace(
        _request("multi_fidelity_mobo", observations, batch_size=2),
        fidelity_mapping=((0.25, 0.5), (0.5, 0.5), (1.0, 1.0)),
    )

    proposals = propose_bayesian_candidates(_space(), request)

    assert proposals
    assert all(item.metadata["fidelity_levels"] == [0.25, 1.0] for item in proposals)


def test_multi_fidelity_cold_start_deduplicates_equal_effective_coverage() -> None:
    quarter_request = _observation(1, 0.2, 0.7, fidelity=0.25, loss=0.2)
    executed_half_matrix = replace(quarter_request, fidelity=0.5)
    request = replace(
        _request("multi_fidelity_mobo", (executed_half_matrix,), batch_size=1),
        fidelity_mapping=((0.25, 0.5), (0.5, 0.5), (1.0, 1.0)),
        required_fidelity=0.5,
    )

    proposal = propose_bayesian_candidates(_space(), request)[0]

    assert proposal.parameters != executed_half_matrix.parameters
    assert proposal.metadata["requested_fidelity"] == pytest.approx(0.5)
    assert proposal.metadata["effective_fidelity"] == pytest.approx(0.5)
    assert proposal.metadata["promotion_from_fidelity"] is None


def test_multi_fidelity_never_downgrades_a_fully_evaluated_parameter_set() -> None:
    search_space = SearchSpace(
        [ParameterDomain("mode", 0.0, 0.0, 1.0, step=1.0)]
    )
    observations = tuple(
        OptimizerObservation(
            candidate_id=f"full-{mode}",
            generation_index=mode,
            parameters={"mode": float(mode)},
            unit_vector=(float(mode),),
            loss=float(mode),
            objectives={"loss": float(mode)},
            objective_directions={"loss": "minimize"},
            feasible=True,
            fidelity=1.0,
            requested_fidelity=1.0,
        )
        for mode in (0, 1)
    )
    request = replace(
        _request("multi_fidelity_mobo", observations, batch_size=2),
        required_fidelity=0.25,
    )

    proposals = propose_bayesian_candidates(search_space, request)

    assert proposals == []


def test_required_full_fidelity_promotes_the_best_reduced_fidelity_incumbent() -> None:
    observations = (
        _observation(1, 0.2, 0.7, fidelity=0.25, loss=0.8),
        _observation(2, 0.8, 0.25, fidelity=0.25, loss=0.1),
    )
    request = replace(
        _request("multi_fidelity_mobo", observations, batch_size=1),
        fidelity_mapping=((0.25, 1.0 / 3.0), (0.5, 2.0 / 3.0), (1.0, 1.0)),
        required_fidelity=1.0,
    )

    proposal = propose_bayesian_candidates(_space(), request)[0]

    assert proposal.parameters == observations[1].parameters
    assert proposal.metadata["requested_fidelity"] == pytest.approx(1.0)
    assert proposal.metadata["effective_fidelity"] == pytest.approx(1.0)
    assert proposal.metadata["promotion_from_fidelity"] == pytest.approx(0.25)


def test_turbo_contracts_after_recent_non_improvements() -> None:
    search_space = _space()
    observations = [
        replace(observation, optimizer_strategy="turbo")
        for observation in _grid_observations()[:12]
    ]
    # Four newer, feasible evaluations fail to beat the incumbent, so the
    # stateless reconstruction of TuRBO state contracts the region.
    for offset in range(4):
        observations.append(
            replace(
                _observation(100 + offset, 0.1 + 0.025 * offset, 0.9, loss=5.0 + offset),
                optimizer_strategy="turbo",
            )
        )
    proposals = propose_bayesian_candidates(
        search_space, _request("turbo", tuple(observations), seed=17)
    )

    assert len(proposals) == 3
    assert all(proposal.metadata["trust_region_radius"] == 0.2 for proposal in proposals)
    assert all(
        proposal.metadata["backend"] == "native_turbo_matern52_ard_gp" for proposal in proposals
    )


def test_turbo_radius_is_invariant_to_candidate_ids_and_batch_order() -> None:
    search_space = _space()
    observations: list[OptimizerObservation] = []
    for generation, losses in enumerate(((5.0, 4.0), (3.5, 3.0), (3.4, 3.2), (2.5, 2.0)), 1):
        for batch_index, loss in enumerate(losses):
            observations.append(
                replace(
                    _observation(
                        generation * 10 + batch_index,
                        0.1 * generation + 0.025 * batch_index,
                        0.2 + 0.05 * batch_index,
                        loss=loss,
                    ),
                    generation_index=generation,
                    optimizer_strategy="turbo",
                )
            )
    renamed = tuple(
        replace(observation, candidate_id=f"renamed-{len(observations) - index:03d}")
        for index, observation in enumerate(reversed(observations))
    )

    first = propose_bayesian_candidates(
        search_space,
        _request("turbo", tuple(observations), seed=71),
    )
    second = propose_bayesian_candidates(
        search_space,
        _request("turbo", renamed, seed=71),
    )

    assert first == second
    assert all(item.metadata["trust_region_radius"] == 0.8 for item in first)


def test_turbo_counts_all_crash_generations_as_failures() -> None:
    search_space = _space()
    observations = [
        replace(
            _observation(generation, 0.1 * generation, 0.2, loss=5.0 - generation),
            generation_index=generation,
            optimizer_strategy="turbo",
        )
        for generation in range(1, 5)
    ]
    observations.extend(
        replace(
            _observation(100 + generation, 0.7, 0.8, feasible=False, loss=None),
            generation_index=generation,
            optimizer_strategy="turbo",
        )
        for generation in range(5, 9)
    )

    proposals = propose_bayesian_candidates(
        search_space,
        _request("turbo", tuple(observations), seed=73),
    )

    assert proposals
    assert all(item.metadata["trust_region_radius"] == 0.2 for item in proposals)


def test_turbo_radius_ignores_other_portfolio_children() -> None:
    search_space = _space()
    turbo_history = [
        replace(
            _observation(generation, 0.1 * generation, 0.2, loss=5.0 - generation),
            generation_index=generation,
            optimizer_strategy="optimizer_portfolio:turbo",
        )
        for generation in range(1, 5)
    ]
    other_child_crashes = [
        replace(
            _observation(100 + generation, 0.8, 0.8, feasible=False, loss=None),
            generation_index=generation,
            optimizer_strategy="optimizer_portfolio:saasbo",
        )
        for generation in range(5, 9)
    ]

    proposals = propose_bayesian_candidates(
        search_space,
        _request("turbo", tuple([*turbo_history, *other_child_crashes]), seed=79),
    )

    assert proposals
    assert all(item.metadata["trust_region_radius"] == 0.8 for item in proposals)


def test_saasbo_metadata_truthfully_identifies_sparse_ensemble_approximation() -> None:
    proposals = propose_bayesian_candidates(
        _space(), _request("saasbo", _grid_observations(), seed=31, batch_size=2)
    )

    assert len(proposals) == 2
    for proposal in proposals:
        assert proposal.metadata["fully_bayesian"] is False
        assert proposal.metadata["backend"] == "native_sparse_axis_gp_ensemble_approximation"
        assert "12-member" in str(proposal.metadata["approximation"])


def test_experimental_contracts_snapshot_nested_mappings() -> None:
    parameters = {"x": 0.25, "y": 0.75}
    metadata = {"nested": {"levels": [0.25, 1.0]}}
    proposal = ExperimentalProposal(
        label="snapshot",
        parameters=parameters,
        rationale="contract test",
        metadata=metadata,
    )
    parameters["x"] = 1.0
    metadata["nested"]["levels"].append(2.0)

    assert proposal.parameters["x"] == 0.25
    assert proposal.metadata["nested"]["levels"] == [0.25, 1.0]
    with pytest.raises(TypeError, match="immutable"):
        proposal.parameters["x"] = 0.5
    with pytest.raises(TypeError, match="immutable"):
        proposal.metadata["nested"]["levels"].append(3.0)


@pytest.mark.parametrize(
    "changes",
    [
        {"failure_rate": float("nan")},
        {"fidelity": 0.0},
        {"requested_fidelity": 1.1},
        {"unit_vector": (float("inf"), 0.5)},
        {"objective_directions": {"tracking": "minimum"}},
        {"loss": True},
        {"feasible": "yes"},
        {"failure_rate": False},
        {"fidelity": True},
        {"requested_fidelity": True},
        {"unit_vector": (False, 0.5)},
        {"optimizer_strategy": ""},
        {"optimizer_metadata": {"bad": float("nan")}},
    ],
)
def test_observation_contract_rejects_invalid_numeric_state(
    changes: dict[str, object],
) -> None:
    observation = _observation(1, 0.2, 0.3)

    with pytest.raises(ValueError):
        replace(observation, **changes)


@pytest.mark.parametrize(
    "mapping",
    [
        ((0.25, 0.25), (0.25, 0.5)),
        ((0.25, 0.75), (0.5, 0.5), (1.0, 1.0)),
        ((0.25, float("nan")), (1.0, 1.0)),
        ((1.0, 0.5),),
        ((True, 1.0),),
    ],
)
def test_request_contract_rejects_invalid_fidelity_mapping(
    mapping: tuple[tuple[float, float], ...],
) -> None:
    with pytest.raises(ValueError):
        OptimizerRequest(
            strategy="multi_fidelity_mobo",
            generation_index=0,
            batch_size=1,
            random_seed=1,
            observations=(),
            fidelity_mapping=mapping,
        )
