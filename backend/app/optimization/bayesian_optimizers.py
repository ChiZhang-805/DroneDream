"""Dependency-free experimental Bayesian optimizers.

The implementations in this module are numerical cores, not marketing aliases
for BoTorch algorithms.  They share a Matérn-5/2 ARD surrogate and provide four
distinct policies:

* constrained multi-objective random-scalarized log expected improvement;
* cost-aware multi-fidelity constrained optimization;
* a local trust-region (TuRBO-inspired) policy;
* a strongly shrunk sparse-axis GP ensemble (SAAS-inspired approximation).

All policies consume failed observations through a probabilistic feasibility
model.  Objective observations with partial numeric results remain useful, but
a simulator/runtime failure with no loss is never converted into a fabricated
large loss.
"""

from __future__ import annotations

import hashlib
import math
import random
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Literal, Protocol

from app.optimization.design import MAX_HALTON_DIMENSIONS, halton_design
from app.optimization.domain import SearchSpace
from app.optimization.experimental_types import (
    OPTIMIZER_LEARNING_OBSERVATION_ROLES,
    ExperimentalProposal,
    OptimizerObservation,
    OptimizerRequest,
)
from app.optimization.gaussian_process import (
    GaussianPrediction,
    GaussianProcessEnsemble,
    Matern52ARDGaussianProcess,
    infer_ard_length_scales,
)
from app.optimization.proposal_provenance import (
    verified_observation_source_membership,
)

_STRATEGY_OFFSETS = {
    "constrained_mobo": 101,
    "multi_fidelity_mobo": 211,
    "turbo": 307,
    "saasbo": 401,
}

# The dependency-free GP uses a dense covariance matrix and a pure-Python
# Cholesky factorization.  Letting a 10,000-trial campaign reach ``fit``
# unchanged would therefore require cubic work and quadratic memory.  This
# deliberately conservative ceiling still gives the exact surrogate a rich
# training set, while the selector below spends every slot on useful evidence.
_EXACT_GP_ACTIVE_SET_LIMIT = 160
_ACTIVE_SET_METHOD = (
    "deterministic accuracy-first active set: global elite, recent, "
    "failure, boundary, and farthest-point coverage"
)


class _Predictor(Protocol):
    def predict(self, features: Sequence[float]) -> GaussianPrediction: ...


@dataclass(frozen=True)
class _MetricModel:
    name: str
    predictor: _Predictor
    minimum: float
    maximum: float
    best: float
    source_count: int
    training_count: int
    fixed_scale: float | None = None

    @property
    def span(self) -> float:
        if self.fixed_scale is not None:
            return self.fixed_scale
        observed_span = self.maximum - self.minimum
        if observed_span > 1e-9:
            return observed_span
        # GP.fit intentionally retains prior uncertainty for a constant
        # target.  Use a meaningful original-unit scale here instead of
        # dividing that uncertainty by 1e-9 and letting a flat auxiliary
        # metric overwhelm every informative objective.
        return max(1.0, abs(self.best) * 0.05)


_AcquisitionRepresentation = Literal[
    "objective_vector",
    "scalar_loss",
    "exploration_only",
]


@dataclass(frozen=True)
class _Candidate:
    parameters: dict[str, float]
    vector: tuple[float, ...]
    fidelity: float = 1.0


@dataclass(frozen=True)
class _ActiveSetEntry:
    observation: OptimizerObservation
    features: tuple[float, ...]
    target: float


def _active_set_stable_key(entry: _ActiveSetEntry) -> tuple[object, ...]:
    """Numeric, candidate-id-independent ordering for reproducible thinning."""

    observation = entry.observation
    return (
        observation.generation_index,
        tuple(round(value, 14) for value in entry.features),
        _parameter_key(observation.parameters),
        round(entry.target, 14),
        observation.feasible,
        round(observation.failure_rate, 14),
        round(observation.fidelity, 14),
        round(observation.requested_fidelity, 14),
    )


def _select_gp_active_set(
    entries: Sequence[_ActiveSetEntry],
    *,
    minimize_target: bool,
    limit: int = _EXACT_GP_ACTIVE_SET_LIMIT,
) -> tuple[_ActiveSetEntry, ...]:
    """Select a deterministic, accuracy-first subset for one exact GP.

    Small and medium histories are returned byte-for-byte in their original
    order.  Large histories retain several complementary forms of evidence,
    then use greedy farthest-point sampling to cover gaps in normalized feature
    space.  ``minimize_target=False`` is used by the feasibility model, where
    probability extremes are more informative than treating either class as a
    numerical optimum.
    """

    if limit <= 0:
        raise ValueError("GP active-set limit must be positive")
    if len(entries) <= limit:
        return tuple(entries)

    selected: set[int] = set()

    def add(indices: Sequence[int], quota: int) -> None:
        for index in indices:
            if len(selected) >= limit or quota <= 0:
                break
            if index in selected:
                continue
            selected.add(index)
            quota -= 1

    def stable(index: int) -> tuple[object, ...]:
        return _active_set_stable_key(entries[index])

    elite_quota = max(1, round(limit * 0.25))
    recent_quota = max(1, round(limit * 0.25))
    failure_quota = max(1, round(limit * 0.20))
    boundary_quota = max(1, round(limit * 0.15))

    if minimize_target:
        feasible = [index for index, entry in enumerate(entries) if entry.observation.feasible]
        elite_pool = feasible or list(range(len(entries)))
        elite = sorted(elite_pool, key=lambda index: (entries[index].target, stable(index)))
        best_quota = max(1, round(elite_quota * 0.75))
        add(elite, best_quota)
        # Preserve the opposite target extreme as well.  It is not an
        # optimization incumbent, but keeps normalization and response-scale
        # inference anchored to the full observed range.
        add(list(reversed(elite)), elite_quota - best_quota)
    else:
        # Both confident failures and confident successes anchor a calibrated
        # classifier.  Distance from 0.5 gives equal priority to both classes.
        elite = sorted(
            range(len(entries)),
            key=lambda index: (-abs(entries[index].target - 0.5), stable(index)),
        )
        add(elite, elite_quota)

    recent = sorted(
        range(len(entries)),
        key=lambda index: (-entries[index].observation.generation_index, stable(index)),
    )
    add(recent, recent_quota)

    failures = sorted(
        (
            index
            for index, entry in enumerate(entries)
            if not entry.observation.feasible or entry.observation.failure_rate > 0.0
        ),
        key=lambda index: (
            -entries[index].observation.failure_rate,
            -entries[index].observation.generation_index,
            stable(index),
        ),
    )
    add(failures, failure_quota)

    def boundary_distance(index: int) -> float:
        # Fidelity is an input feature for the MF model, but it is not a
        # parameter-space boundary. Prefer the original normalized control
        # vector so full-fidelity rows do not consume the whole boundary quota.
        parameter_dimension = len(entries[index].observation.unit_vector)
        features = (
            entries[index].features[:parameter_dimension]
            if 0 < parameter_dimension <= len(entries[index].features)
            else entries[index].features
        )
        return min(
            (min(abs(value), abs(1.0 - value)) for value in features),
            default=0.0,
        )

    boundary = sorted(
        range(len(entries)),
        key=lambda index: (boundary_distance(index), stable(index)),
    )
    add(boundary, boundary_quota)

    # Fill every remaining slot by maximizing distance from the evidence
    # already retained.  This protects interior and interaction coverage rather
    # than allowing recency or elite selection to collapse into one basin.
    remaining = set(range(len(entries))) - selected
    nearest_distance: dict[int, float] = {}
    for index in remaining:
        nearest_distance[index] = min(
            sum(
                (left - right) ** 2
                for left, right in zip(
                    entries[index].features,
                    entries[chosen].features,
                    strict=True,
                )
            )
            for chosen in selected
        )
    while remaining and len(selected) < limit:
        winner = max(
            remaining,
            key=lambda index: (nearest_distance[index], stable(index)),
        )
        selected.add(winner)
        remaining.remove(winner)
        winner_features = entries[winner].features
        for index in remaining:
            distance = sum(
                (left - right) ** 2
                for left, right in zip(
                    entries[index].features,
                    winner_features,
                    strict=True,
                )
            )
            nearest_distance[index] = min(nearest_distance[index], distance)

    # Fitting order does not change the exact GP result.  Sorting the active set
    # makes it invariant to database retrieval order as well as candidate UUIDs.
    return tuple(entries[index] for index in sorted(selected, key=stable))


class BayesianOptimizerError(ValueError):
    """Raised when this module receives an unsupported strategy."""


def _full_fidelity_request(request: OptimizerRequest) -> OptimizerRequest:
    """Return objective history comparable to a full evaluation.

    Portfolio children share safety evidence, but a non-MF optimizer must not
    mistake a cheap screen for a complete objective measurement.
    """

    return replace(
        request,
        observations=tuple(
            item
            for item in request.observations
            if item.requested_fidelity >= 1.0 - 1e-9 and item.fidelity >= 1.0 - 1e-9
        ),
    )


def _stable_seed(request: OptimizerRequest) -> int:
    payload = (
        f"{int(request.random_seed)}:{int(request.generation_index)}:"
        f"{request.strategy}:{_STRATEGY_OFFSETS.get(request.strategy, 0)}"
    ).encode()
    return int.from_bytes(hashlib.sha256(payload).digest()[:8], "big")


def _observation_vector(
    observation: OptimizerObservation, search_space: SearchSpace
) -> tuple[float, ...]:
    dimension = len(search_space.tunable)
    if len(observation.unit_vector) == dimension and all(
        math.isfinite(value) for value in observation.unit_vector
    ):
        return tuple(max(0.0, min(1.0, float(value))) for value in observation.unit_vector)
    return search_space.to_unit_vector(observation.parameters)


def _parameter_key(parameters: Mapping[str, float]) -> tuple[tuple[str, float], ...]:
    return tuple(sorted((name, round(float(value), 12)) for name, value in parameters.items()))


def _observation_covers_fidelity(
    observation: OptimizerObservation,
    *,
    effective_fidelity: float,
    requested_fidelity: float,
) -> bool:
    """Return whether an existing run makes the target run redundant.

    Effective scenario coverage is monotonic: a run that executed a larger
    training matrix already contains the evidence from every smaller matrix.
    Full verification is deliberately stricter because it may also include a
    holdout matrix; a reduced run that happens to cover the same number of
    training scenarios must never masquerade as full verification.
    """

    if observation.fidelity < effective_fidelity - 1e-9:
        return False
    if requested_fidelity >= 1.0 - 1e-9:
        return observation.requested_fidelity >= 1.0 - 1e-9
    return True


def _normal_cdf(value: float) -> float:
    return 0.5 * (1.0 + math.erf(value / math.sqrt(2.0)))


def _expected_improvement(mean: float, deviation: float, best: float) -> float:
    if deviation <= 1e-12:
        return max(0.0, best - mean)
    standardized = (best - mean) / deviation
    density = math.exp(-0.5 * standardized * standardized) / math.sqrt(2.0 * math.pi)
    return max(0.0, (best - mean) * _normal_cdf(standardized) + deviation * density)


def _soft_feasibility_target(observation: OptimizerObservation) -> float:
    failure = max(0.0, min(1.0, float(observation.failure_rate)))
    # A completed aggregate carries direction-aware, non-negative violation
    # margins.  Preserve the canonical feasible label, but retain how far an
    # infeasible run crossed one or more boundaries instead of reducing every
    # constraint failure to the same binary target.  Multiplying reciprocal
    # margins is bounded and remains stable even for very large finite values.
    residual = 1.0
    for value in observation.constraints.values():
        residual /= 1.0 + max(0.0, float(value))
    violation_severity = max(0.0, min(1.0, 1.0 - residual))

    # A confirmed simulator/runtime crash remains the strongest signal and is
    # deliberately independent of any partial constraint diagnostics that
    # happened to be collected before the process failed.
    if failure >= 1.0 - 1e-12:
        return 0.02
    if observation.feasible:
        probability = 0.98 - 0.73 * failure - 0.18 * (1.0 - failure) * violation_severity
    else:
        probability = 0.02 + 0.23 * (1.0 - failure) - 0.20 * (1.0 - failure) * violation_severity
    return max(0.01, min(0.99, probability))


class _FeasibilityModel:
    def __init__(
        self,
        observations: Sequence[OptimizerObservation],
        search_space: SearchSpace,
        *,
        feature_builder: Callable[[OptimizerObservation], tuple[float, ...]],
    ) -> None:
        observations = tuple(
            item
            for item in observations
            if item.completed
            and item.role in OPTIMIZER_LEARNING_OBSERVATION_ROLES
        )
        self.source_count = len(observations)
        self.sample_count = len(observations)
        if not observations:
            self._prior = 0.8
            self._model: Matern52ARDGaussianProcess | None = None
            return
        entries = tuple(
            _ActiveSetEntry(
                observation=observation,
                features=feature_builder(observation),
                target=_soft_feasibility_target(observation),
            )
            for observation in observations
        )
        active = _select_gp_active_set(
            entries,
            minimize_target=False,
            limit=_EXACT_GP_ACTIVE_SET_LIMIT,
        )
        self.sample_count = len(active)
        all_probabilities = [entry.target for entry in entries]
        probabilities = [entry.target for entry in active]
        # A smoothed empirical prior prevents a single initial crash from
        # making the entire domain appear impossible.  The prior uses the full
        # history so deliberate failure oversampling in the active set cannot
        # distort the observed global failure rate.
        self._prior = (sum(all_probabilities) + 1.6) / (len(all_probabilities) + 2.0)
        logits = [math.log(value / (1.0 - value)) for value in probabilities]
        features = [entry.features for entry in active]
        noises = [0.02 + 0.2 * entry.observation.failure_rate for entry in active]
        self._model = Matern52ARDGaussianProcess(noise=2e-4).fit(
            features, logits, observation_noise=noises
        )

    @property
    def active_set_approximation(self) -> bool:
        return self.sample_count < self.source_count

    def probability(self, features: Sequence[float]) -> float:
        if self._model is None:
            return self._prior
        prediction = self._model.predict(features)
        # Logistic-Gaussian moment approximation.  Blending a small empirical
        # component keeps extrapolation calibrated far away from observations.
        denominator = math.sqrt(1.0 + math.pi * prediction.standard_deviation**2 / 8.0)
        logistic = 1.0 / (1.0 + math.exp(-max(-40.0, min(40.0, prediction.mean / denominator))))
        return max(0.01, min(0.99, 0.9 * logistic + 0.1 * self._prior))


def _oriented_objective(observation: OptimizerObservation, metric: str) -> float | None:
    value = observation.objectives.get(metric)
    if value is None or not math.isfinite(value):
        return None
    direction = observation.objective_directions.get(metric, "minimize")
    return -float(value) if direction == "maximize" else float(value)


def _metric_names(observations: Sequence[OptimizerObservation]) -> tuple[str, ...]:
    names = sorted(
        {
            name
            for observation in observations
            if observation.completed and observation.role == "objective"
            for name, value in observation.objectives.items()
            if math.isfinite(value)
        }
    )
    return tuple(names)


def _informative_count(observations: Sequence[OptimizerObservation]) -> int:
    return sum(
        observation.completed
        and observation.role == "objective"
        and (
            observation.loss is not None
            or any(math.isfinite(value) for value in observation.objectives.values())
        )
        for observation in observations
    )


def _fit_metric_model(
    name: str,
    observations: Sequence[OptimizerObservation],
    *,
    feature_builder: Callable[[OptimizerObservation], tuple[float, ...]],
    predictor_factory: Callable[
        [Sequence[Sequence[float]], Sequence[float], Sequence[float]], _Predictor
    ]
    | None = None,
    normalization: float | None = None,
) -> _MetricModel | None:
    entries: list[_ActiveSetEntry] = []
    for observation in observations:
        if not observation.completed or observation.role != "objective":
            continue
        if name == "__loss__":
            value = observation.loss
            if value is not None and math.isfinite(value):
                target = float(value)
            else:
                continue
        else:
            oriented = _oriented_objective(observation, name)
            if oriented is None:
                continue
            target = oriented
        entries.append(
            _ActiveSetEntry(
                observation=observation,
                features=feature_builder(observation),
                target=target,
            )
        )
    if not entries:
        return None
    source_count = len(entries)
    active = _select_gp_active_set(
        entries,
        minimize_target=True,
        limit=_EXACT_GP_ACTIVE_SET_LIMIT,
    )
    features = [entry.features for entry in active]
    targets = [entry.target for entry in active]
    target_feasibility = [entry.observation.feasible for entry in active]
    noises: list[float] = []
    for entry in active:
        observation = entry.observation
        # Low-fidelity and failure-prone partial measurements should influence
        # the surrogate without pretending to be equally precise.
        noises.append(
            0.01
            + 0.12 * max(0.0, min(1.0, observation.failure_rate))
            + 0.08 * (1.0 - max(0.0, min(1.0, observation.fidelity)))
        )
    predictor = (
        predictor_factory(features, targets, noises)
        if predictor_factory is not None
        else Matern52ARDGaussianProcess(noise=1e-4).fit(features, targets, observation_noise=noises)
    )
    feasible_targets = [
        target for target, feasible in zip(targets, target_feasibility, strict=True) if feasible
    ]
    best = min(feasible_targets or targets)
    return _MetricModel(
        name=name,
        predictor=predictor,
        minimum=min(targets),
        maximum=max(targets),
        best=best,
        source_count=source_count,
        training_count=len(active),
        fixed_scale=normalization,
    )


def _fit_models(
    observations: Sequence[OptimizerObservation],
    *,
    feature_builder: Callable[[OptimizerObservation], tuple[float, ...]],
    predictor_factory: Callable[
        [Sequence[Sequence[float]], Sequence[float], Sequence[float]], _Predictor
    ]
    | None = None,
    objective_normalizations: Mapping[str, float] | None = None,
) -> tuple[_MetricModel | None, tuple[_MetricModel, ...]]:
    normalizations = objective_normalizations or {}
    loss_model = _fit_metric_model(
        "__loss__",
        observations,
        feature_builder=feature_builder,
        predictor_factory=predictor_factory,
    )
    objectives = tuple(
        model
        for name in _metric_names(observations)
        if (
            model := _fit_metric_model(
                name,
                observations,
                feature_builder=feature_builder,
                predictor_factory=predictor_factory,
                normalization=normalizations.get(name),
            )
        )
        is not None
    )
    return loss_model, objectives


def _gp_active_set_metadata(
    feasibility: _FeasibilityModel,
    loss_model: _MetricModel | None,
    objective_models: Sequence[_MetricModel],
) -> dict[str, object]:
    """Return an honest account of exact-GP training-set approximation."""

    metric_models = ([loss_model] if loss_model is not None else []) + list(objective_models)
    metric_counts = {
        model.name: {
            "source": model.source_count,
            "active": model.training_count,
        }
        for model in metric_models
    }
    approximation_active = feasibility.active_set_approximation or any(
        model.training_count < model.source_count for model in metric_models
    )
    return {
        "active": approximation_active,
        "limit_per_exact_gp": _EXACT_GP_ACTIVE_SET_LIMIT,
        "method": _ACTIVE_SET_METHOD,
        "feasibility": {
            "source": feasibility.source_count,
            "active": feasibility.sample_count,
        },
        "metrics": metric_counts,
    }


def _random_scalarizations(count: int, dimension: int, rng: random.Random) -> list[list[float]]:
    if dimension <= 0:
        return []
    weights: list[list[float]] = []
    for _ in range(count):
        raw = [-math.log(max(1e-12, rng.random())) for _ in range(dimension)]
        total = sum(raw)
        weights.append([value / total for value in raw])
    return weights


def _objective_scalarizations(
    models: Sequence[_MetricModel],
    request: OptimizerRequest,
    rng: random.Random,
    *,
    fallback_count: int,
) -> tuple[list[list[float]], str]:
    configured = dict(request.objective_weights)
    normalizations = dict(request.objective_normalizations)
    model_names = {model.name for model in models}
    configured_names = set(configured)
    if configured_names or normalizations:
        if (
            not models
            or model_names != configured_names
            or model_names != set(normalizations)
        ):
            return [], "blocked_incomplete_job_objective_vector"
        raw = [configured[model.name] for model in models]
        total = sum(raw)
        return (
            [[value / total for value in raw]],
            "fixed_configured_objective_weights",
        )
    return (
        _random_scalarizations(fallback_count, len(models), rng),
        "deterministic_random_fallback_without_job_preferences",
    )


def _joint_scalarized_incumbents(
    observations: Sequence[OptimizerObservation],
    models: Sequence[_MetricModel],
    scalarizations: Sequence[Sequence[float]],
    *,
    prefer_full_fidelity: bool = False,
) -> tuple[float, ...]:
    """Best achievable observed scalarization for every weight vector.

    Taking each metric's independent best constructs an unattainable utopia
    point whenever objectives conflict. Random-scalarized EI must instead
    compare a prediction with a joint objective vector that one feasible
    candidate actually achieved.
    """

    rows: list[tuple[OptimizerObservation, tuple[float, ...]]] = []
    for observation in observations:
        if (
            not observation.completed
            or observation.role != "objective"
            or not observation.feasible
        ):
            continue
        values: list[float] = []
        for model in models:
            value = _oriented_objective(observation, model.name)
            if value is None:
                break
            values.append((value - model.minimum) / model.span)
        if len(values) == len(models):
            rows.append((observation, tuple(values)))
    if prefer_full_fidelity:
        # A reduced-fidelity joint objective can be systematically biased.  It
        # must never become the incumbent against which a full-target
        # prediction computes EI.  With no complete full-fidelity row, return
        # no incumbent and let scalar loss or uncertainty drive acquisition.
        rows = [
            row
            for row in rows
            if row[0].requested_fidelity >= 1.0 - 1e-9 and row[0].fidelity >= 1.0 - 1e-9
        ]
    if not rows:
        # Independent per-metric minima can belong to different candidates and
        # therefore form an unattainable utopia point.  With no complete joint
        # observation, disable this acquisition component and let scalar loss
        # (or pure exploration) drive the proposal instead.
        return ()
    return tuple(
        min(
            sum(weight * value for weight, value in zip(weights, row, strict=True))
            for _, row in rows
        )
        for weights in scalarizations
    )


def _multiobjective_utility(
    features: Sequence[float],
    models: Sequence[_MetricModel],
    scalarizations: Sequence[Sequence[float]],
    incumbents: Sequence[float],
) -> float:
    if not models or not scalarizations or len(incumbents) != len(scalarizations):
        return 0.0
    predictions = [model.predictor.predict(features) for model in models]
    normalized_means = [
        (prediction.mean - model.minimum) / model.span
        for prediction, model in zip(predictions, models, strict=True)
    ]
    normalized_deviations = [
        prediction.standard_deviation / model.span
        for prediction, model in zip(predictions, models, strict=True)
    ]
    total = 0.0
    for weights, best in zip(scalarizations, incumbents, strict=True):
        mean = sum(weight * value for weight, value in zip(weights, normalized_means, strict=True))
        deviation = math.sqrt(
            sum(
                (weight * value) ** 2
                for weight, value in zip(weights, normalized_deviations, strict=True)
            )
        )
        total += math.log1p(_expected_improvement(mean, deviation, best))
    return total / max(1, len(scalarizations))


def _loss_utility(features: Sequence[float], model: _MetricModel | None) -> float:
    if model is None:
        return 0.0
    prediction = model.predictor.predict(features)
    improvement = _expected_improvement(prediction.mean, prediction.standard_deviation, model.best)
    return math.log1p(improvement / model.span)


def _select_acquisition_representation(
    loss_model: _MetricModel | None,
    objective_models: Sequence[_MetricModel],
    scalarizations: Sequence[Sequence[float]],
    incumbents: Sequence[float],
) -> tuple[
    _AcquisitionRepresentation,
    _MetricModel | None,
    tuple[_MetricModel, ...],
]:
    """Select exactly one objective representation for one optimizer call.

    A complete joint objective incumbent is required before vector acquisition
    is meaningful.  Otherwise the declared scalar loss is the only objective
    authority.  The two representations are never blended because scalar loss
    is derived from the same objective evidence and would count it twice.
    """

    objective_tuple = tuple(objective_models)
    if (
        objective_tuple
        and scalarizations
        and len(incumbents) == len(scalarizations)
    ):
        return "objective_vector", None, objective_tuple
    if loss_model is not None:
        return "scalar_loss", loss_model, ()
    return "exploration_only", None, ()


def _acquisition_utility(
    features: Sequence[float],
    *,
    representation: _AcquisitionRepresentation,
    loss_model: _MetricModel | None,
    objective_models: Sequence[_MetricModel],
    scalarizations: Sequence[Sequence[float]],
    incumbents: Sequence[float],
) -> float:
    if representation == "objective_vector":
        return _multiobjective_utility(
            features,
            objective_models,
            scalarizations,
            incumbents,
        )
    if representation == "scalar_loss":
        return _loss_utility(features, loss_model)
    return 0.0


def _representation_uncertainty(
    features: Sequence[float],
    *,
    loss_model: _MetricModel | None,
    objective_models: Sequence[_MetricModel],
) -> float:
    models = list(objective_models)
    if loss_model is not None:
        models.append(loss_model)
    if not models:
        return 1.0
    return sum(
        model.predictor.predict(features).standard_deviation / model.span
        for model in models
    ) / len(models)


def _make_candidate(
    search_space: SearchSpace, vector: Sequence[float], *, fidelity: float = 1.0
) -> _Candidate | None:
    try:
        parameters = search_space.from_unit_vector(vector)
    except ValueError:
        return None
    return _Candidate(
        parameters=parameters,
        vector=search_space.to_unit_vector(parameters),
        fidelity=max(0.05, min(1.0, float(fidelity))),
    )


def _candidate_pool(
    search_space: SearchSpace,
    request: OptimizerRequest,
    rng: random.Random,
    *,
    center: Sequence[float] | None = None,
    radius: float = 1.0,
    include_observed: bool = False,
) -> list[_Candidate]:
    dimension = len(search_space.tunable)
    target = max(128, min(2048, 96 * max(1, dimension)))
    candidates: list[_Candidate] = []
    seen: set[tuple[tuple[str, float], ...]] = set()

    def append(candidate: _Candidate | None) -> None:
        if candidate is None:
            return
        key = _parameter_key(candidate.parameters)
        if key not in seen:
            candidates.append(candidate)
            seen.add(key)

    if center is None and dimension <= MAX_HALTON_DIMENSIONS:
        start = 1 + (_stable_seed(request) % 10_007)
        for parameters in halton_design(
            search_space,
            min(target // 2, 512),
            start_index=start,
            include_baseline=False,
        ):
            append(
                _Candidate(
                    parameters=parameters,
                    vector=search_space.to_unit_vector(parameters),
                )
            )
    if include_observed:
        for observation in request.observations:
            try:
                projected = search_space.project(observation.parameters)
            except ValueError:
                continue
            append(_Candidate(projected, search_space.to_unit_vector(projected)))

    attempts = 0
    while len(candidates) < target and attempts < target * 30:
        if center is None:
            vector = [rng.random() for _ in range(dimension)]
        else:
            vector = [
                max(0.0, min(1.0, float(value) + rng.uniform(-radius, radius))) for value in center
            ]
        append(_make_candidate(search_space, vector))
        attempts += 1
    return candidates


def _cold_start(
    search_space: SearchSpace,
    request: OptimizerRequest,
    feasibility: _FeasibilityModel,
    *,
    fidelity: float,
    backend: str,
    requested_fidelity: float | None = None,
) -> list[ExperimentalProposal]:
    count = max(0, request.batch_size)
    if count == 0:
        return []
    target_requested_fidelity = fidelity if requested_fidelity is None else requested_fidelity
    if request.strategy == "multi_fidelity_mobo":
        observed = {
            _parameter_key(observation.parameters)
            for observation in request.observations
            if _observation_covers_fidelity(
                observation,
                effective_fidelity=fidelity,
                requested_fidelity=target_requested_fidelity,
            )
        }
    else:
        observed = {_parameter_key(observation.parameters) for observation in request.observations}
    start = 1 + ((_stable_seed(request) + 17) % 10_007)
    design_count = max(count * 8, count + len(observed))
    if len(search_space.tunable) <= MAX_HALTON_DIMENSIONS:
        design = halton_design(
            search_space,
            design_count,
            start_index=start,
            include_baseline=not request.observations,
        )
    else:
        # The Halton implementation has one prime per supported dimension.
        # Large PX4 catalogs must remain usable, so switch to the same seeded,
        # validity-aware random pool used by the warm optimizer path.
        design = [
            candidate.parameters
            for candidate in _candidate_pool(
                search_space,
                request,
                random.Random(_stable_seed(request) + 17),  # noqa: S311 - optimizer RNG
                include_observed=False,
            )
        ]
    promotion_sources: dict[tuple[tuple[str, float], ...], float] = {}
    promoted_parameters: list[dict[str, float]] = []
    if request.strategy == "multi_fidelity_mobo":
        for observation in sorted(
            request.observations,
            key=lambda item: (
                not item.feasible,
                float("inf") if item.loss is None else item.loss,
                -item.requested_fidelity,
                _parameter_key(item.parameters),
            ),
        ):
            if (
                not observation.completed
                or observation.role != "objective"
                or not observation.feasible
                or observation.loss is None
                or not math.isfinite(observation.loss)
                or observation.requested_fidelity >= target_requested_fidelity - 1e-9
                or _observation_covers_fidelity(
                    observation,
                    effective_fidelity=fidelity,
                    requested_fidelity=target_requested_fidelity,
                )
            ):
                continue
            try:
                projected = search_space.project(observation.parameters)
            except ValueError:
                continue
            key = _parameter_key(projected)
            if key in observed or key in promotion_sources:
                continue
            promotion_sources[key] = observation.requested_fidelity
            promoted_parameters.append(projected)

    candidate_pool: list[_Candidate] = []
    probabilities: dict[tuple[tuple[str, float], ...], float] = {}
    scores: dict[tuple[tuple[str, float], ...], float] = {}
    queued: set[tuple[tuple[str, float], ...]] = set()
    for parameters in [*promoted_parameters, *design]:
        key = _parameter_key(parameters)
        if key in observed or key in queued:
            continue
        queued.add(key)
        vector = search_space.to_unit_vector(parameters)
        probability = (
            feasibility.probability((*vector, fidelity))
            if request.strategy == "multi_fidelity_mobo"
            else feasibility.probability(vector)
        )
        candidate_pool.append(_Candidate(parameters=parameters, vector=vector))
        probabilities[key] = probability
        # Promotions have already passed a cheaper screen, but they still
        # compete on predicted safety.  The small bonus prevents an uncertain
        # model from starving every promotion while never overriding a strong
        # failure signal.
        scores[key] = probability * (1.12 if key in promotion_sources else 1.0)

    exploration_slots = 1 if count >= 5 and len(candidate_pool) > count else 0
    selected = _select_diverse(
        candidate_pool,
        scores,
        count=count - exploration_slots,
        observed=set(),
    )
    if exploration_slots:
        selected_keys = {_parameter_key(candidate.parameters) for candidate in selected}
        remaining = [
            candidate
            for candidate in candidate_pool
            if _parameter_key(candidate.parameters) not in selected_keys
        ]
        if remaining:
            # One explicit space-filling slot prevents an early, poorly
            # calibrated feasibility model from permanently sealing off a
            # region.  It is selected independently of outcomes.
            explorer = max(
                remaining,
                key=lambda candidate: (
                    min(
                        (
                            sum(
                                (left - right) ** 2
                                for left, right in zip(candidate.vector, chosen.vector, strict=True)
                            )
                            for chosen in selected
                        ),
                        default=math.inf,
                    ),
                    candidate.vector,
                ),
            )
            selected.append(explorer)

    proposals: list[ExperimentalProposal] = []
    for candidate in selected:
        parameters = candidate.parameters
        key = _parameter_key(parameters)
        probability = probabilities[key]
        promotion_from = promotion_sources.get(key)
        metadata = {
            "strategy": request.strategy,
            "backend": backend,
            "fidelity": fidelity,
            "feasibility_probability": round(probability, 8),
            "cold_start": True,
            "selection_role": (
                "space_filling_exploration"
                if exploration_slots and candidate is selected[-1]
                else "failure_aware_screening"
            ),
            "gp_training_set": _gp_active_set_metadata(feasibility, None, ()),
            "random_seed": request.random_seed,
        }
        if request.strategy == "multi_fidelity_mobo":
            metadata.update(
                {
                    "requested_fidelity": target_requested_fidelity,
                    "effective_fidelity": fidelity,
                    "promotion_from_fidelity": promotion_from,
                }
            )
        proposals.append(
            ExperimentalProposal(
                label=f"{request.strategy}-g{request.generation_index}-{len(proposals) + 1}",
                parameters=parameters,
                rationale=(
                    "Promote a promising reduced-fidelity point for stronger verification."
                    if promotion_from is not None
                    else "Deterministic space-filling cold start with failure-aware screening."
                ),
                metadata=metadata,
            )
        )
    return proposals


def _select_diverse(
    pool: Sequence[_Candidate],
    scores: Mapping[tuple[tuple[str, float], ...], float],
    *,
    count: int,
    observed: set[tuple[tuple[str, float], ...]],
) -> list[_Candidate]:
    selected: list[_Candidate] = []
    remaining = [
        candidate for candidate in pool if _parameter_key(candidate.parameters) not in observed
    ]
    while remaining and len(selected) < count:

        def adjusted(candidate: _Candidate) -> float:
            base = scores.get(_parameter_key(candidate.parameters), -math.inf)
            if not selected:
                return base
            minimum_distance = min(
                math.sqrt(
                    sum(
                        (left - right) ** 2
                        for left, right in zip(candidate.vector, other.vector, strict=True)
                    )
                    / max(1, len(candidate.vector))
                )
                for other in selected
            )
            return base * (0.35 + 0.65 * min(1.0, minimum_distance / 0.2))

        winner = max(remaining, key=lambda item: (adjusted(item), item.vector))
        selected.append(winner)
        winner_key = _parameter_key(winner.parameters)
        remaining = [item for item in remaining if _parameter_key(item.parameters) != winner_key]
    return selected


def _standard_constrained_mobo(
    search_space: SearchSpace, request: OptimizerRequest
) -> list[ExperimentalProposal]:
    rng = random.Random(_stable_seed(request))  # noqa: S311 - deterministic optimizer RNG
    model_request = _full_fidelity_request(request)

    def feature_builder(observation: OptimizerObservation) -> tuple[float, ...]:
        return _observation_vector(observation, search_space)

    feasibility = _FeasibilityModel(
        model_request.observations, search_space, feature_builder=feature_builder
    )
    loss_model, objective_models = _fit_models(
        model_request.observations,
        feature_builder=feature_builder,
        objective_normalizations=dict(
            model_request.objective_normalizations
        ),
    )
    informative = _informative_count(model_request.observations)
    if informative < max(4, 2 * len(search_space.tunable)):
        return _cold_start(
            search_space,
            model_request,
            feasibility,
            fidelity=1.0,
            backend="native_matern52_ard_gp",
        )
    pool = _candidate_pool(search_space, model_request, rng)
    scalarizations, scalarization_policy = _objective_scalarizations(
        objective_models,
        model_request,
        rng,
        fallback_count=24,
    )
    incumbents = _joint_scalarized_incumbents(
        model_request.observations,
        objective_models,
        scalarizations,
    )
    representation, loss_model, objective_models = (
        _select_acquisition_representation(
            loss_model,
            objective_models,
            scalarizations,
            incumbents,
        )
    )
    scores: dict[tuple[tuple[str, float], ...], float] = {}
    probabilities: dict[tuple[tuple[str, float], ...], float] = {}
    for candidate in pool:
        probability = feasibility.probability(candidate.vector)
        utility = _acquisition_utility(
            candidate.vector,
            representation=representation,
            loss_model=loss_model,
            objective_models=objective_models,
            scalarizations=scalarizations,
            incumbents=incumbents,
        )
        exploration = _representation_uncertainty(
            candidate.vector,
            loss_model=loss_model,
            objective_models=objective_models,
        )
        utility += 0.015 * exploration
        key = _parameter_key(candidate.parameters)
        scores[key] = max(1e-15, utility) * probability**1.5
        probabilities[key] = probability
    observed = {_parameter_key(item.parameters) for item in model_request.observations}
    selected = _select_diverse(pool, scores, count=request.batch_size, observed=observed)
    return [
        ExperimentalProposal(
            label=f"constrained-mobo-g{request.generation_index}-{index + 1}",
            parameters=candidate.parameters,
            rationale="Failure-aware constrained multi-objective log-EI candidate.",
            metadata={
                "strategy": request.strategy,
                "backend": "native_matern52_ard_gp",
                "acquisition": "constrained_random_scalarized_log_ei",
                "fidelity": 1.0,
                "feasibility_probability": round(
                    probabilities[_parameter_key(candidate.parameters)], 8
                ),
                "acquisition_score": round(scores[_parameter_key(candidate.parameters)], 12),
                "acquisition_representation": representation,
                "scalarization_policy": (
                    scalarization_policy
                    if representation == "objective_vector"
                    else "not_used_for_scalar_loss"
                ),
                "objective_preference_policy": scalarization_policy,
                "objective_models": [model.name for model in objective_models],
                "objective_weights": dict(model_request.objective_weights),
                "objective_normalizations": {
                    model.name: model.span for model in objective_models
                },
                "uses_scalar_loss": loss_model is not None,
                "training_observations": len(request.observations),
                "gp_training_set": _gp_active_set_metadata(
                    feasibility, loss_model, objective_models
                ),
                "random_seed": request.random_seed,
            },
        )
        for index, candidate in enumerate(selected)
    ]


def _effective_fidelity(request: OptimizerRequest, requested_fidelity: float) -> float:
    for requested, effective in request.fidelity_mapping:
        if math.isclose(requested, requested_fidelity, abs_tol=1e-9):
            return max(0.05, min(1.0, float(effective)))
    return max(0.05, min(1.0, requested_fidelity))


def _fidelity_levels(request: OptimizerRequest) -> tuple[float, ...]:
    if request.required_fidelity is not None:
        return (max(0.05, min(1.0, request.required_fidelity)),)
    levels = {0.25, 0.5, 1.0}
    levels.update(
        round(max(0.05, min(1.0, observation.requested_fidelity)), 4)
        for observation in request.observations
    )
    unique: dict[tuple[float, bool], float] = {}
    for level in sorted(levels):
        identity = (
            round(_effective_fidelity(request, level), 12),
            level >= 1.0 - 1e-9,
        )
        # If a tiny matrix maps two nominal screening levels to the same
        # number of executed runs, evaluating both would be identical work.
        unique.setdefault(identity, level)
    return tuple(unique.values())


def _multi_fidelity_mobo(
    search_space: SearchSpace, request: OptimizerRequest
) -> list[ExperimentalProposal]:
    rng = random.Random(_stable_seed(request))  # noqa: S311 - deterministic optimizer RNG

    def feature_builder(observation: OptimizerObservation) -> tuple[float, ...]:
        return (
            *_observation_vector(observation, search_space),
            max(0.05, min(1.0, observation.fidelity)),
        )

    feasibility = _FeasibilityModel(
        request.observations, search_space, feature_builder=feature_builder
    )
    loss_model, objective_models = _fit_models(
        request.observations,
        feature_builder=feature_builder,
        objective_normalizations=dict(request.objective_normalizations),
    )
    informative = _informative_count(request.observations)
    if informative < max(4, len(search_space.tunable) + 2):
        requested_fidelity = (
            max(0.05, min(1.0, request.required_fidelity))
            if request.required_fidelity is not None
            else 0.25
        )
        return _cold_start(
            search_space,
            request,
            feasibility,
            fidelity=_effective_fidelity(request, requested_fidelity),
            backend="native_cost_aware_matern52_ard_gp",
            requested_fidelity=requested_fidelity,
        )

    base_pool = _candidate_pool(search_space, request, rng, include_observed=True)
    levels = _fidelity_levels(request)
    scalarizations, scalarization_policy = _objective_scalarizations(
        objective_models,
        request,
        rng,
        fallback_count=24,
    )
    incumbents = _joint_scalarized_incumbents(
        request.observations,
        objective_models,
        scalarizations,
        prefer_full_fidelity=True,
    )
    representation, loss_model, objective_models = (
        _select_acquisition_representation(
            loss_model,
            objective_models,
            scalarizations,
            incumbents,
        )
    )
    evaluated_by_parameter: dict[tuple[tuple[str, float], ...], list[OptimizerObservation]] = {}
    for observation in request.observations:
        evaluated_by_parameter.setdefault(_parameter_key(observation.parameters), []).append(
            observation
        )
    scored: list[tuple[float, _Candidate, float]] = []
    for base in base_pool:
        target_features = (*base.vector, 1.0)
        target_value = max(
            1e-12,
            _acquisition_utility(
                target_features,
                representation=representation,
                loss_model=loss_model,
                objective_models=objective_models,
                scalarizations=scalarizations,
                incumbents=incumbents,
            ),
        )
        for requested_fidelity in levels:
            effective_fidelity = _effective_fidelity(request, requested_fidelity)
            if any(
                _observation_covers_fidelity(
                    observation,
                    effective_fidelity=effective_fidelity,
                    requested_fidelity=requested_fidelity,
                )
                for observation in evaluated_by_parameter.get(_parameter_key(base.parameters), ())
            ):
                continue
            features = (*base.vector, effective_fidelity)
            probability = feasibility.probability(features)
            information = max(
                0.02,
                _representation_uncertainty(
                    features,
                    loss_model=loss_model,
                    objective_models=objective_models,
                ),
            )
            # A sublinear cost curve reflects that startup overhead is not free,
            # while still rewarding cheap screening evaluations.
            relative_cost = 0.18 + 0.82 * effective_fidelity**1.35
            proximity_to_target = math.exp(-1.4 * (1.0 - effective_fidelity))
            score = (
                target_value * probability**1.5 * information * proximity_to_target / relative_cost
            )
            scored.append(
                (
                    score,
                    _Candidate(base.parameters, base.vector, requested_fidelity),
                    probability,
                )
            )
    scored.sort(key=lambda item: (item[0], item[1].vector, item[1].fidelity), reverse=True)
    selected: list[tuple[float, _Candidate, float]] = []
    parameter_keys: set[tuple[tuple[str, float], ...]] = set()
    for item in scored:
        key = _parameter_key(item[1].parameters)
        if key in parameter_keys:
            continue
        selected.append(item)
        parameter_keys.add(key)
        if len(selected) >= request.batch_size:
            break
    return [
        ExperimentalProposal(
            label=f"multi-fidelity-mobo-g{request.generation_index}-{index + 1}",
            parameters=candidate.parameters,
            rationale="Cost-aware failure-constrained evaluation at the selected fidelity.",
            metadata={
                "strategy": request.strategy,
                "backend": "native_cost_aware_matern52_ard_gp",
                "acquisition": "cost_aware_constrained_random_scalarized_log_ei",
                "fidelity": _effective_fidelity(request, candidate.fidelity),
                "requested_fidelity": candidate.fidelity,
                "effective_fidelity": _effective_fidelity(request, candidate.fidelity),
                "feasibility_probability": round(probability, 8),
                "acquisition_score": round(score, 12),
                "fidelity_levels": list(levels),
                "effective_fidelity_levels": {
                    str(level): _effective_fidelity(request, level) for level in levels
                },
                "required_fidelity": request.required_fidelity,
                "acquisition_representation": representation,
                "scalarization_policy": (
                    scalarization_policy
                    if representation == "objective_vector"
                    else "not_used_for_scalar_loss"
                ),
                "objective_preference_policy": scalarization_policy,
                "objective_models": [model.name for model in objective_models],
                "objective_weights": dict(request.objective_weights),
                "objective_normalizations": {
                    model.name: model.span for model in objective_models
                },
                "uses_scalar_loss": loss_model is not None,
                "training_observations": len(request.observations),
                "gp_training_set": _gp_active_set_metadata(
                    feasibility, loss_model, objective_models
                ),
                "random_seed": request.random_seed,
            },
        )
        for index, (score, candidate, probability) in enumerate(selected)
    ]


def _is_turbo_observation(observation: OptimizerObservation) -> bool:
    verified_membership = verified_observation_source_membership(
        observation,
        "turbo",
    )
    if verified_membership is not None:
        return verified_membership
    strategy = observation.optimizer_strategy or ""
    return strategy == "turbo" or strategy.endswith(":turbo") or "turbo" in strategy.split("/")


def _turbo_radius(observations: Sequence[OptimizerObservation]) -> float:
    """Reconstruct trust-region state from generation-level TuRBO outcomes.

    A parallel generation is one optimizer decision, so it contributes at most
    one success or failure regardless of batch size or candidate identifiers.
    Generations where every owned candidate crashed or violated a constraint
    are explicit failures instead of disappearing from the state history.
    """

    generation_losses: dict[int, list[float]] = {}
    for observation in observations:
        if (
            not observation.completed
            or observation.role not in OPTIMIZER_LEARNING_OBSERVATION_ROLES
            or observation.requested_fidelity < 1.0 - 1e-9
            or not _is_turbo_observation(observation)
        ):
            continue
        values = generation_losses.setdefault(observation.generation_index, [])
        if (
            observation.feasible
            and observation.loss is not None
            and math.isfinite(observation.loss)
        ):
            values.append(float(observation.loss))

    if len(generation_losses) < 4:
        return 0.5
    running_best = math.inf
    improvements: list[bool] = []
    for generation in sorted(generation_losses):
        losses = generation_losses[generation]
        generation_best = min(losses) if losses else None
        improved = generation_best is not None and (
            running_best == math.inf
            or generation_best < (running_best - 1e-9 * max(1.0, abs(running_best)))
        )
        improvements.append(improved)
        if generation_best is not None:
            running_best = min(running_best, generation_best)
    recent = improvements[-4:]
    if sum(recent) >= 2:
        return 0.8
    if not any(recent):
        return 0.2
    return 0.4


def _turbo(search_space: SearchSpace, request: OptimizerRequest) -> list[ExperimentalProposal]:
    rng = random.Random(_stable_seed(request))  # noqa: S311 - deterministic optimizer RNG
    model_request = _full_fidelity_request(request)

    def feature_builder(observation: OptimizerObservation) -> tuple[float, ...]:
        return _observation_vector(observation, search_space)

    feasibility = _FeasibilityModel(
        model_request.observations, search_space, feature_builder=feature_builder
    )
    loss_model = _fit_metric_model(
        "__loss__",
        model_request.observations, feature_builder=feature_builder
    )
    valid = [
        observation
        for observation in model_request.observations
        if observation.completed
        and observation.role == "objective"
        and observation.feasible
        and observation.loss is not None
        and math.isfinite(observation.loss)
    ]
    if len(valid) < max(3, len(search_space.tunable) + 1):
        return _cold_start(
            search_space,
            model_request,
            feasibility,
            fidelity=1.0,
            backend="native_turbo_matern52_ard_gp",
        )
    center_observation = min(
        valid,
        key=lambda value: (
            float(value.loss) if value.loss is not None else math.inf,
            _parameter_key(value.parameters),
        ),
    )
    center = _observation_vector(center_observation, search_space)
    radius = _turbo_radius(model_request.observations)
    pool = _candidate_pool(
        search_space,
        model_request,
        rng,
        center=center,
        radius=radius,
    )
    scores: dict[tuple[tuple[str, float], ...], float] = {}
    probabilities: dict[tuple[tuple[str, float], ...], float] = {}
    for candidate in pool:
        probability = feasibility.probability(candidate.vector)
        local_loss = _loss_utility(candidate.vector, loss_model)
        distance = math.sqrt(
            sum((left - right) ** 2 for left, right in zip(candidate.vector, center, strict=True))
            / max(1, len(center))
        )
        trust_weight = math.exp(-0.5 * (distance / max(0.05, radius)) ** 2)
        key = _parameter_key(candidate.parameters)
        scores[key] = max(1e-15, local_loss) * probability**1.5 * trust_weight
        probabilities[key] = probability
    observed = {_parameter_key(item.parameters) for item in model_request.observations}
    selected = _select_diverse(pool, scores, count=request.batch_size, observed=observed)
    return [
        ExperimentalProposal(
            label=f"turbo-g{request.generation_index}-{index + 1}",
            parameters=candidate.parameters,
            rationale="Failure-constrained local trust-region improvement around the incumbent.",
            metadata={
                "strategy": request.strategy,
                "backend": "native_turbo_matern52_ard_gp",
                "acquisition": "constrained_local_log_ei",
                "fidelity": 1.0,
                "trust_region_radius": radius,
                "trust_region_center": list(center),
                "feasibility_probability": round(
                    probabilities[_parameter_key(candidate.parameters)], 8
                ),
                "acquisition_score": round(scores[_parameter_key(candidate.parameters)], 12),
                "acquisition_representation": "scalar_loss",
                "objective_models": [],
                "uses_scalar_loss": loss_model is not None,
                "training_observations": len(request.observations),
                "gp_training_set": _gp_active_set_metadata(
                    feasibility, loss_model, ()
                ),
                "random_seed": request.random_seed,
            },
        )
        for index, candidate in enumerate(selected)
    ]


def _sparse_ensemble_factory(
    rng: random.Random,
) -> Callable[[Sequence[Sequence[float]], Sequence[float], Sequence[float]], _Predictor]:
    def factory(
        features: Sequence[Sequence[float]],
        targets: Sequence[float],
        noises: Sequence[float],
    ) -> _Predictor:
        dimension = len(features[0])
        base = infer_ard_length_scales(features, targets)
        active_count = max(1, min(dimension, int(round(math.sqrt(dimension)))))
        relevance = [1.0 / max(1e-6, value) for value in base]
        members: list[Matern52ARDGaussianProcess] = []
        for _ in range(12):
            priorities = [
                (relevance[axis] * (0.65 + 0.7 * rng.random()), axis) for axis in range(dimension)
            ]
            active = {axis for _, axis in sorted(priorities, reverse=True)[:active_count]}
            scales = [
                max(0.04, min(0.9, base[axis] * (0.65 + 0.7 * rng.random())))
                if axis in active
                else 6.0 + 8.0 * rng.random()
                for axis in range(dimension)
            ]
            members.append(
                Matern52ARDGaussianProcess(length_scales=scales, noise=2e-4).fit(
                    features, targets, observation_noise=noises
                )
            )
        return GaussianProcessEnsemble(members)

    return factory


def _saasbo(search_space: SearchSpace, request: OptimizerRequest) -> list[ExperimentalProposal]:
    rng = random.Random(_stable_seed(request))  # noqa: S311 - deterministic optimizer RNG
    model_request = _full_fidelity_request(request)

    def feature_builder(observation: OptimizerObservation) -> tuple[float, ...]:
        return _observation_vector(observation, search_space)

    feasibility = _FeasibilityModel(
        model_request.observations, search_space, feature_builder=feature_builder
    )
    informative = _informative_count(model_request.observations)
    if informative < max(6, 2 * len(search_space.tunable)):
        return _cold_start(
            search_space,
            model_request,
            feasibility,
            fidelity=1.0,
            backend="native_sparse_axis_gp_ensemble_approximation",
        )
    factory = _sparse_ensemble_factory(rng)
    loss_model, objective_models = _fit_models(
        model_request.observations,
        feature_builder=feature_builder,
        predictor_factory=factory,
        objective_normalizations=dict(
            model_request.objective_normalizations
        ),
    )
    pool = _candidate_pool(search_space, model_request, rng)
    scalarizations, scalarization_policy = _objective_scalarizations(
        objective_models,
        model_request,
        rng,
        fallback_count=24,
    )
    incumbents = _joint_scalarized_incumbents(
        model_request.observations,
        objective_models,
        scalarizations,
    )
    representation, loss_model, objective_models = (
        _select_acquisition_representation(
            loss_model,
            objective_models,
            scalarizations,
            incumbents,
        )
    )
    scores: dict[tuple[tuple[str, float], ...], float] = {}
    probabilities: dict[tuple[tuple[str, float], ...], float] = {}
    for candidate in pool:
        probability = feasibility.probability(candidate.vector)
        utility = _acquisition_utility(
            candidate.vector,
            representation=representation,
            loss_model=loss_model,
            objective_models=objective_models,
            scalarizations=scalarizations,
            incumbents=incumbents,
        )
        key = _parameter_key(candidate.parameters)
        scores[key] = max(1e-15, utility) * probability**1.5
        probabilities[key] = probability
    observed = {_parameter_key(item.parameters) for item in model_request.observations}
    selected = _select_diverse(pool, scores, count=request.batch_size, observed=observed)
    return [
        ExperimentalProposal(
            label=f"saasbo-g{request.generation_index}-{index + 1}",
            parameters=candidate.parameters,
            rationale="Strong-shrinkage sparse-axis GP ensemble candidate.",
            metadata={
                "strategy": request.strategy,
                "backend": "native_sparse_axis_gp_ensemble_approximation",
                "acquisition": "constrained_sparse_ensemble_log_ei",
                "fidelity": 1.0,
                "fully_bayesian": False,
                "approximation": "12-member strongly-shrunk sparse-axis GP ensemble",
                "feasibility_probability": round(
                    probabilities[_parameter_key(candidate.parameters)], 8
                ),
                "acquisition_score": round(scores[_parameter_key(candidate.parameters)], 12),
                "acquisition_representation": representation,
                "scalarization_policy": (
                    scalarization_policy
                    if representation == "objective_vector"
                    else "not_used_for_scalar_loss"
                ),
                "objective_preference_policy": scalarization_policy,
                "objective_models": [model.name for model in objective_models],
                "objective_weights": dict(model_request.objective_weights),
                "objective_normalizations": {
                    model.name: model.span for model in objective_models
                },
                "uses_scalar_loss": loss_model is not None,
                "training_observations": len(request.observations),
                "gp_training_set": _gp_active_set_metadata(
                    feasibility, loss_model, objective_models
                ),
                "random_seed": request.random_seed,
            },
        )
        for index, candidate in enumerate(selected)
    ]


def propose_bayesian_candidates(
    search_space: SearchSpace, request: OptimizerRequest
) -> list[ExperimentalProposal]:
    """Dispatch one of the four Bayesian experimental optimization policies."""

    if request.batch_size < 0:
        raise ValueError("batch_size must be non-negative")
    if not search_space.tunable or request.batch_size == 0:
        return []
    if request.strategy == "constrained_mobo":
        proposals = _standard_constrained_mobo(search_space, request)
    elif request.strategy == "multi_fidelity_mobo":
        proposals = _multi_fidelity_mobo(search_space, request)
    elif request.strategy == "turbo":
        proposals = _turbo(search_space, request)
    elif request.strategy == "saasbo":
        proposals = _saasbo(search_space, request)
    else:
        raise BayesianOptimizerError(f"unsupported Bayesian optimizer strategy: {request.strategy}")
    # The final projection is intentional defense-in-depth for catalog step,
    # enum, and coupled-parameter validators.
    validated: list[ExperimentalProposal] = []
    seen: set[tuple[tuple[str, float], ...]] = set()
    for proposal in proposals:
        projected = search_space.project(proposal.parameters)
        key = _parameter_key(projected)
        if key in seen:
            continue
        seen.add(key)
        validated.append(
            ExperimentalProposal(
                label=proposal.label,
                parameters=projected,
                rationale=proposal.rationale,
                metadata=proposal.metadata,
            )
        )
        if len(validated) >= request.batch_size:
            break
    return validated


__all__ = ["BayesianOptimizerError", "propose_bayesian_candidates"]
