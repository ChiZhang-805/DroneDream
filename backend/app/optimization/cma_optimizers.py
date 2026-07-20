"""Full-covariance evolutionary optimizers for experimental tuning.

The orchestration layer deliberately does not persist an opaque optimizer
object.  Instead, this module reconstructs the complete CMA state from the
ordered observation history on every call.  That makes a proposal reproducible
from a job manifest and avoids version-specific pickle state.

Both optimizers minimize ``OptimizerObservation.loss``.  Failed observations
remain useful: they participate in feasibility ranking and train a smooth
feasibility surrogate instead of receiving an arbitrary giant objective loss.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal

import numpy as np
from numpy.typing import NDArray

from app.optimization.domain import SearchSpace
from app.optimization.experimental_types import (
    ExperimentalProposal,
    OptimizerObservation,
    OptimizerRequest,
)

FloatArray = NDArray[np.float64]

_MIN_EIGENVALUE = 1e-10
_MAX_EIGENVALUE = 1e6
_MAX_CONDITION_NUMBER = 1e10
_MAX_PROJECTION_ATTEMPTS = 80
_RBF_ACTIVE_SET_LIMIT = 160
_CMA_CONTRACT_VERSION = 1


@dataclass(frozen=True)
class CMAState:
    """JSON-independent numerical state reconstructed from observations."""

    mean: FloatArray
    covariance: FloatArray
    sigma: float
    path_c: FloatArray
    path_sigma: FloatArray
    updates: int
    population_size: int
    restart_index: int = 0
    pending_offspring: int = 0

    def _digest_payload(self, *, include_pending: bool) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "mean": self.mean.tolist(),
            "covariance": self.covariance.tolist(),
            "sigma": float(self.sigma),
            "path_c": self.path_c.tolist(),
            "path_sigma": self.path_sigma.tolist(),
            "updates": self.updates,
            "population_size": self.population_size,
            "restart_index": self.restart_index,
        }
        if include_pending:
            payload["pending_offspring"] = self.pending_offspring
        return payload

    def distribution_sha256(self) -> str:
        """Fingerprint the sampling distribution, excluding cohort progress."""

        return hashlib.sha256(
            json.dumps(
                self._digest_payload(include_pending=False),
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()

    def json_summary(self) -> dict[str, Any]:
        """Return a compact, hash-verifiable summary of reconstructed state.

        The complete state is deterministically rebuilt from observation
        history. Repeating an O(d^2) covariance matrix in every candidate row
        would bloat the database and report artifacts without improving replay.
        """

        full_state = self._digest_payload(include_pending=True)
        digest = hashlib.sha256(
            json.dumps(full_state, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        eigenvalues = np.linalg.eigvalsh(self.covariance)
        smallest = max(1e-15, float(np.min(eigenvalues)))
        return {
            "mean": self.mean.tolist(),
            "covariance_diagonal": np.diag(self.covariance).tolist(),
            "covariance_condition_number": float(np.max(eigenvalues)) / smallest,
            "sigma": float(self.sigma),
            "updates": self.updates,
            "population_size": self.population_size,
            "restart_index": self.restart_index,
            "pending_offspring": self.pending_offspring,
            "state_sha256": digest,
            "distribution_sha256": self.distribution_sha256(),
            "reconstruction": "completed_cma_population_history_v2",
        }


@dataclass(frozen=True)
class BIPOPRestartPlan:
    """One deterministic BIPOP restart configuration."""

    restart_index: int
    regime: Literal["large", "small"]
    population_size: int
    initial_sigma: float

    def json_summary(self) -> dict[str, Any]:
        return {
            "restart_index": self.restart_index,
            "restart_regime": self.regime,
            "population_size": self.population_size,
            "initial_sigma": self.initial_sigma,
            "schedule_semantics": "deterministic_bipop_inspired_alternation",
        }


@dataclass(frozen=True)
class _TrainingPoint:
    observation: OptimizerObservation
    vector: FloatArray


@dataclass(frozen=True)
class _CohortRecord:
    restart_index: int
    cohort_index: int
    cohort_id: str
    population_size: int
    distribution_sha256: str
    positions: Mapping[int, OptimizerObservation]

    @property
    def persisted_count(self) -> int:
        return len(self.positions)

    @property
    def complete(self) -> bool:
        return self.persisted_count == self.population_size and all(
            item.completed for item in self.positions.values()
        )


class _RBFRegressor:
    """Small deterministic kernel regressor with predictive uncertainty."""

    def __init__(
        self,
        x: FloatArray,
        y: FloatArray,
        *,
        ridge: float = 0.04,
        prior: float | None = None,
    ) -> None:
        self._x = x
        self._prior = float(np.mean(y)) if prior is None else prior
        if len(x) <= 1:
            self._length_scale = 0.25
        else:
            differences = x[:, np.newaxis, :] - x[np.newaxis, :, :]
            distances = np.sqrt(np.sum(differences * differences, axis=2))
            positive = distances[distances > 1e-12]
            median = float(np.median(positive)) if positive.size else 0.25
            self._length_scale = min(0.75, max(0.08, median))
        kernel = self._kernel(x, x)
        regularized = kernel + np.eye(len(x), dtype=np.float64) * ridge
        self._inverse = np.linalg.pinv(regularized, hermitian=True)
        self._alpha = self._inverse @ (y - self._prior)

    @property
    def training_size(self) -> int:
        return len(self._x)

    def _kernel(self, first: FloatArray, second: FloatArray) -> FloatArray:
        differences = first[:, np.newaxis, :] - second[np.newaxis, :, :]
        squared = np.sum(differences * differences, axis=2)
        scale = 2.0 * self._length_scale * self._length_scale
        return np.asarray(np.exp(-squared / scale), dtype=np.float64)

    def predict(self, x: FloatArray) -> tuple[FloatArray, FloatArray]:
        cross = self._kernel(x, self._x)
        means = self._prior + cross @ self._alpha
        projected = cross @ self._inverse
        variances = 1.0 - np.sum(projected * cross, axis=1)
        return means, np.sqrt(np.maximum(0.0, variances))


def _observation_seed_payload(item: OptimizerObservation) -> dict[str, Any]:
    """Canonical observation content independent of database-generated IDs."""

    return {
        "generation": item.generation_index,
        "unit": list(item.unit_vector),
        "parameters": item.parameters,
        "loss": item.loss,
        "objectives": item.objectives,
        "objective_directions": item.objective_directions,
        "feasible": item.feasible,
        "failure_rate": item.failure_rate,
        "constraints": item.constraints,
        "strategy": item.optimizer_strategy,
        "effective_fidelity": item.fidelity,
        "requested_fidelity": item.requested_fidelity,
    }


def _observation_order_key(item: OptimizerObservation) -> tuple[int, str]:
    payload = _observation_seed_payload(item)
    return (
        item.generation_index,
        json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False),
    )


def _optimizer_metadata(item: OptimizerObservation) -> Mapping[str, Any]:
    metadata = item.optimizer_metadata
    return metadata if isinstance(metadata, Mapping) else {}


def _metadata_int(metadata: Mapping[str, Any], key: str) -> int | None:
    value = metadata.get(key)
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    numeric = float(value)
    if not math.isfinite(numeric) or not numeric.is_integer():
        return None
    return int(numeric)


def _metadata_bool(metadata: Mapping[str, Any], key: str, *, default: bool) -> bool:
    value = metadata.get(key)
    return value if isinstance(value, bool) else default


def _has_explicit_cma_contract(item: OptimizerObservation) -> bool:
    metadata = _optimizer_metadata(item)
    return _metadata_int(metadata, "cma_contract_version") == _CMA_CONTRACT_VERSION


def _is_explicit_cma_offspring(
    item: OptimizerObservation,
    *,
    strategy: str,
) -> bool:
    metadata = _optimizer_metadata(item)
    return (
        _has_explicit_cma_contract(item)
        and str(metadata.get("optimizer_generated_by", "")) == strategy
        and _metadata_bool(metadata, "optimizer_update_eligible", default=False)
        and _strategy_matches(item, strategy)
        and item.requested_fidelity >= 1.0 - 1e-9
    )


def _is_legacy_cma_offspring(item: OptimizerObservation, *, strategy: str) -> bool:
    metadata = _optimizer_metadata(item)
    generated_by = metadata.get("optimizer_generated_by")
    return (
        not _has_explicit_cma_contract(item)
        and _strategy_matches(item, strategy)
        and (generated_by is None or str(generated_by) == strategy)
        and _metadata_bool(metadata, "optimizer_update_eligible", default=True)
        and item.requested_fidelity >= 1.0 - 1e-9
    )


def _cma_update_vector(
    search_space: SearchSpace,
    observation: OptimizerObservation,
) -> FloatArray | None:
    metadata = _optimizer_metadata(observation)
    raw = metadata.get("cma_update_vector")
    dimensions = len(search_space.tunable)
    if isinstance(raw, list | tuple) and len(raw) == dimensions:
        try:
            vector = np.asarray(raw, dtype=np.float64)
        except (TypeError, ValueError):
            vector = np.empty(0, dtype=np.float64)
        if len(vector) == dimensions and np.all(np.isfinite(vector)):
            return np.clip(vector, 0.0, 1.0)
    return _observation_vector(search_space, observation)


def _canonical_seed(
    request: OptimizerRequest,
    *,
    namespace: str,
    extra: dict[str, Any] | None = None,
) -> int:
    observations = sorted(
        request.observations,
        key=_observation_order_key,
    )
    payload = {
        "namespace": namespace,
        "random_seed": request.random_seed,
        "generation_index": request.generation_index,
        "batch_size": request.batch_size,
        "history": [_observation_seed_payload(item) for item in observations],
        "extra": extra or {},
    }
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return int.from_bytes(hashlib.sha256(encoded).digest()[:8], "big", signed=False)


def _observation_vector(
    search_space: SearchSpace,
    observation: OptimizerObservation,
) -> FloatArray | None:
    dimensions = len(search_space.tunable)
    if len(observation.unit_vector) == dimensions:
        vector = np.asarray(observation.unit_vector, dtype=np.float64)
        if np.all(np.isfinite(vector)):
            return np.clip(vector, 0.0, 1.0)
    try:
        vector = np.asarray(
            search_space.to_unit_vector(search_space.project(observation.parameters)),
            dtype=np.float64,
        )
    except (KeyError, TypeError, ValueError):
        return None
    return vector if np.all(np.isfinite(vector)) else None


def _training_points(
    search_space: SearchSpace,
    observations: Iterable[OptimizerObservation],
) -> list[_TrainingPoint]:
    points: list[_TrainingPoint] = []
    for observation in sorted(
        observations,
        key=_observation_order_key,
    ):
        vector = _observation_vector(search_space, observation)
        if vector is not None:
            points.append(_TrainingPoint(observation, vector))
    return points


def _constraint_violation(observation: OptimizerObservation) -> float:
    # The orchestration adapter supplies direction-aware, non-negative
    # violation margins (not raw metric values). ``feasible`` remains the
    # canonical label and the margins only order already-infeasible points.
    violation = 0.0 if observation.feasible else 1.0
    if not observation.feasible and observation.constraints:
        margin = sum(max(0.0, float(value)) for value in observation.constraints.values())
        violation += 0.05 * math.log1p(margin)
    return violation + max(0.0, min(1.0, observation.failure_rate))


def _soft_feasibility_target(observation: OptimizerObservation) -> float:
    """Retain violation severity instead of collapsing every failure to zero."""

    failure = max(0.0, min(1.0, float(observation.failure_rate)))
    residual = 1.0
    for value in observation.constraints.values():
        residual /= 1.0 + max(0.0, float(value))
    violation_severity = max(0.0, min(1.0, 1.0 - residual))
    if failure >= 1.0 - 1e-12:
        return 0.02
    if observation.feasible:
        probability = (
            0.98
            - 0.73 * failure
            - 0.18 * (1.0 - failure) * violation_severity
        )
    else:
        probability = (
            0.02
            + 0.23 * (1.0 - failure)
            - 0.20 * (1.0 - failure) * violation_severity
        )
    return max(0.01, min(0.99, probability))


def _is_effectively_feasible(observation: OptimizerObservation) -> bool:
    return observation.feasible and observation.failure_rate < 0.5


def _rank_key(point: _TrainingPoint) -> tuple[float, float, float, tuple[float, ...]]:
    observation = point.observation
    feasible = _is_effectively_feasible(observation)
    finite_loss = (
        float(observation.loss)
        if observation.loss is not None and math.isfinite(observation.loss)
        else float("inf")
    )
    return (
        0.0 if feasible and math.isfinite(finite_loss) else 1.0,
        _constraint_violation(observation),
        finite_loss,
        tuple(float(value) for value in point.vector),
    )


def _strategy_matches(observation: OptimizerObservation, strategy: str) -> bool:
    value = observation.optimizer_strategy or ""
    return value == strategy or value.endswith(f":{strategy}") or strategy in value.split("/")


def _full_fidelity_observations(
    observations: Sequence[OptimizerObservation],
) -> tuple[OptimizerObservation, ...]:
    return tuple(
        item
        for item in observations
        if item.requested_fidelity >= 1.0 - 1e-9
    )


def _explicit_cohort_records(
    observations: Sequence[OptimizerObservation],
    *,
    strategy: str,
    restart_index: int | None = None,
) -> list[_CohortRecord]:
    grouped: dict[tuple[int, int, str], dict[int, OptimizerObservation]] = {}
    contracts: dict[tuple[int, int, str], tuple[int, str]] = {}
    for item in observations:
        if not _is_explicit_cma_offspring(item, strategy=strategy):
            continue
        metadata = _optimizer_metadata(item)
        restart = _metadata_int(metadata, "cma_restart_index")
        cohort = _metadata_int(metadata, "cma_cohort_index")
        position = _metadata_int(metadata, "cma_cohort_position")
        population = _metadata_int(metadata, "cma_population_size")
        cohort_id = metadata.get("cma_cohort_id")
        distribution = metadata.get("cma_distribution_sha256")
        if (
            restart is None
            or restart < 0
            or cohort is None
            or cohort < 0
            or position is None
            or population is None
            or population < 2
            or not isinstance(cohort_id, str)
            or not cohort_id
            or not isinstance(distribution, str)
            or len(distribution) != 64
        ):
            raise ValueError("malformed explicit CMA cohort metadata")
        if restart_index is not None and restart != restart_index:
            continue
        if not 0 <= position < population:
            raise ValueError("CMA cohort position is outside its population")
        key = (restart, cohort, cohort_id)
        expected = contracts.setdefault(key, (population, distribution))
        if expected != (population, distribution):
            raise ValueError("CMA cohort mixes population sizes or distributions")
        positions = grouped.setdefault(key, {})
        if position in positions:
            raise ValueError("CMA cohort contains a duplicate position")
        positions[position] = item
    return [
        _CohortRecord(
            restart_index=key[0],
            cohort_index=key[1],
            cohort_id=key[2],
            population_size=contracts[key][0],
            distribution_sha256=contracts[key][1],
            positions=positions,
        )
        for key, positions in sorted(grouped.items(), key=lambda item: item[0])
    ]


def _legacy_generation_cohorts(
    points: Sequence[_TrainingPoint],
    *,
    population_size: int,
) -> list[list[_TrainingPoint]]:
    """Conservatively replay pre-contract rows only when a generation is exact."""

    grouped: dict[int, list[_TrainingPoint]] = defaultdict(list)
    for point in points:
        grouped[point.observation.generation_index].append(point)
    return [
        sorted(grouped[generation], key=_rank_key)
        for generation in sorted(grouped)
        if len(grouped[generation]) == population_size
        and all(point.observation.completed for point in grouped[generation])
    ]


def _elite_weights(count: int) -> FloatArray:
    raw = np.log(count + 0.5) - np.log(np.arange(1, count + 1, dtype=np.float64))
    raw = np.maximum(raw, 1e-12)
    return np.asarray(raw / float(np.sum(raw)), dtype=np.float64)


def _stabilize_covariance(covariance: FloatArray) -> FloatArray:
    """Repair a covariance matrix without discarding its global scale.

    CMA-ES adapts the sampling covariance as ``sigma**2 * covariance``.  Trace
    normalization without compensating ``sigma`` silently changes that
    distribution, so normal updates only receive an SPD/condition repair here.
    """

    if (
        covariance.ndim != 2
        or covariance.shape[0] != covariance.shape[1]
        or not np.all(np.isfinite(covariance))
    ):
        raise ValueError("CMA covariance must be a finite square matrix")
    if covariance.shape[0] == 0:
        return covariance.copy()
    symmetric = (covariance + covariance.T) * 0.5
    try:
        eigenvalues, eigenvectors = np.linalg.eigh(symmetric)
    except np.linalg.LinAlgError as exc:
        raise ValueError("CMA covariance eigendecomposition failed") from exc
    clipped_maximum = min(
        _MAX_EIGENVALUE,
        max(_MIN_EIGENVALUE, float(np.max(eigenvalues))),
    )
    floor = max(_MIN_EIGENVALUE, clipped_maximum / _MAX_CONDITION_NUMBER)
    eigenvalues = np.clip(eigenvalues, floor, _MAX_EIGENVALUE)
    stable = (eigenvectors * eigenvalues) @ eigenvectors.T
    return np.asarray((stable + stable.T) * 0.5, dtype=np.float64)


def _normalize_initial_covariance(covariance: FloatArray) -> FloatArray:
    """Normalize only a warm-start shape before the configured initial sigma."""

    stable = _stabilize_covariance(covariance)
    if stable.shape[0] == 0:
        return stable
    scale = float(np.mean(np.diag(stable)))
    if not math.isfinite(scale) or scale <= 0.0:
        raise ValueError("CMA warm-start covariance has invalid scale")
    return _stabilize_covariance(stable / scale)


def _inverse_sqrt(covariance: FloatArray) -> FloatArray:
    eigenvalues, eigenvectors = np.linalg.eigh(_stabilize_covariance(covariance))
    inverse = 1.0 / np.sqrt(np.maximum(eigenvalues, _MIN_EIGENVALUE))
    return np.asarray((eigenvectors * inverse) @ eigenvectors.T, dtype=np.float64)


def _initial_state(
    search_space: SearchSpace,
    warm_points: Sequence[_TrainingPoint],
    *,
    population_size: int,
    initial_sigma: float,
    restart_index: int,
    initial_mean: FloatArray | None = None,
) -> CMAState:
    dimensions = len(search_space.tunable)
    baseline = np.asarray(
        search_space.to_unit_vector(search_space.baseline()),
        dtype=np.float64,
    )
    mean = baseline.copy() if initial_mean is None else np.clip(initial_mean, 0.0, 1.0)
    covariance = np.eye(dimensions, dtype=np.float64)

    ranked = sorted(warm_points, key=_rank_key) if initial_mean is None else []
    useful = [
        point
        for point in ranked
        if point.observation.loss is not None
        and math.isfinite(point.observation.loss)
        and _is_effectively_feasible(point.observation)
    ]
    if useful:
        elite_count = min(len(useful), max(1, population_size // 2))
        elites = np.stack([point.vector for point in useful[:elite_count]])
        weights = _elite_weights(elite_count)
        mean = weights @ elites
        if elite_count >= 2:
            deviations = elites - mean
            empirical = np.einsum("i,ij,ik->jk", weights, deviations, deviations)
            covariance = _normalize_initial_covariance(
                empirical / max(initial_sigma * initial_sigma, 1e-8)
                + np.eye(dimensions, dtype=np.float64) * 0.15
            )

    return CMAState(
        mean=np.clip(mean, 0.0, 1.0),
        covariance=covariance,
        sigma=initial_sigma,
        path_c=np.zeros(dimensions, dtype=np.float64),
        path_sigma=np.zeros(dimensions, dtype=np.float64),
        updates=0,
        population_size=population_size,
        restart_index=restart_index,
        pending_offspring=0,
    )


def _update_state(state: CMAState, generation: Sequence[_TrainingPoint]) -> CMAState:
    dimensions = len(state.mean)
    if dimensions == 0 or not generation:
        return state
    ranked = sorted(generation, key=_rank_key)
    elite_count = min(len(ranked), max(1, state.population_size // 2))
    elites = np.stack([point.vector for point in ranked[:elite_count]])
    weights = _elite_weights(elite_count)
    mu_eff = 1.0 / float(np.sum(weights * weights))

    cc = (4.0 + mu_eff / dimensions) / (dimensions + 4.0 + 2.0 * mu_eff / dimensions)
    cs = (mu_eff + 2.0) / (dimensions + mu_eff + 5.0)
    c1 = 2.0 / ((dimensions + 1.3) ** 2 + mu_eff)
    cmu = min(
        1.0 - c1,
        2.0 * (mu_eff - 2.0 + 1.0 / mu_eff) / ((dimensions + 2.0) ** 2 + mu_eff),
    )
    damping = 1.0 + 2.0 * max(0.0, math.sqrt((mu_eff - 1.0) / (dimensions + 1.0)) - 1.0)
    damping += cs

    old_mean = state.mean
    new_mean = np.clip(weights @ elites, 0.0, 1.0)
    weighted_step = (new_mean - old_mean) / max(state.sigma, 1e-12)
    inverse_sqrt = _inverse_sqrt(state.covariance)
    path_sigma = (1.0 - cs) * state.path_sigma + math.sqrt(cs * (2.0 - cs) * mu_eff) * (
        inverse_sqrt @ weighted_step
    )
    expected_norm = math.sqrt(dimensions) * (
        1.0 - 1.0 / (4.0 * dimensions) + 1.0 / (21.0 * dimensions * dimensions)
    )
    normalized_path = np.linalg.norm(path_sigma) / math.sqrt(
        max(1e-12, 1.0 - (1.0 - cs) ** (2.0 * (state.updates + 1)))
    )
    h_sigma = float(normalized_path < (1.4 + 2.0 / (dimensions + 1.0)) * expected_norm)
    path_c = (1.0 - cc) * state.path_c + h_sigma * math.sqrt(
        cc * (2.0 - cc) * mu_eff
    ) * weighted_step

    normalized_steps = (elites - old_mean) / max(state.sigma, 1e-12)
    rank_mu = np.einsum("i,ij,ik->jk", weights, normalized_steps, normalized_steps)
    covariance = (
        (1.0 - c1 - cmu) * state.covariance
        + c1 * (np.outer(path_c, path_c) + (1.0 - h_sigma) * cc * (2.0 - cc) * state.covariance)
        + cmu * rank_mu
    )
    covariance = _stabilize_covariance(covariance)
    sigma = state.sigma * math.exp(
        (cs / damping) * (float(np.linalg.norm(path_sigma)) / expected_norm - 1.0)
    )
    sigma = min(0.8, max(0.005, sigma))
    return CMAState(
        mean=new_mean,
        covariance=covariance,
        sigma=sigma,
        path_c=path_c,
        path_sigma=path_sigma,
        updates=state.updates + 1,
        population_size=state.population_size,
        restart_index=state.restart_index,
        pending_offspring=state.pending_offspring,
    )


def _deterministic_restart_mean(dimensions: int, restart_index: int) -> FloatArray:
    """Return a reproducible space-filling restart centre.

    A BIPOP restart must not be anchored to the optimum of the distribution it
    just abandoned.  Irrational rotations give every restart a distinct basin
    without introducing hidden mutable RNG state.
    """

    if dimensions <= 0:
        return np.empty(0, dtype=np.float64)
    golden = 0.6180339887498949
    silver = 0.4142135623730950
    return np.asarray(
        [
            ((restart_index + 1) * golden + (dimension + 1) * silver) % 1.0
            for dimension in range(dimensions)
        ],
        dtype=np.float64,
    )


def reconstruct_cma_state(
    search_space: SearchSpace,
    observations: Sequence[OptimizerObservation],
    *,
    strategy: Literal["surrogate_cma_es", "bipop_cma_es"],
    population_size: int | None = None,
    initial_sigma: float = 0.24,
    restart_index: int = 0,
    minimum_generation: int | None = None,
) -> CMAState:
    """Rebuild a full-covariance CMA state from an immutable history."""

    dimensions = len(search_space.tunable)
    observations = _full_fidelity_observations(observations)
    default_population = max(4, 4 + int(3 * math.log(max(2, dimensions))))
    population = max(2, population_size or default_population)
    points = _training_points(search_space, observations)
    all_own_points = [
        point for point in points if _strategy_matches(point.observation, strategy)
    ]
    explicit_mode = any(
        _is_explicit_cma_offspring(item, strategy=strategy) for item in observations
    )
    legacy_own_points = [
        point
        for point in all_own_points
        if _is_legacy_cma_offspring(point.observation, strategy=strategy)
        and (minimum_generation is None or point.observation.generation_index >= minimum_generation)
    ]
    own_points = legacy_own_points if not explicit_mode else []
    first_own_generation = min(
        (
            point.observation.generation_index
            for point in all_own_points
            if _is_explicit_cma_offspring(point.observation, strategy=strategy)
            or _is_legacy_cma_offspring(point.observation, strategy=strategy)
        ),
        default=None,
    )
    warm_points = [
        point
        for point in points
        if not _strategy_matches(point.observation, strategy)
        and _is_effectively_feasible(point.observation)
        and (
            first_own_generation is None
            or point.observation.generation_index < first_own_generation
        )
    ]
    is_restart = restart_index > 0 or minimum_generation is not None
    if is_restart:
        # A restart starts a genuinely new distribution.  Other optimizers may
        # still inform the separate feasibility model, but neither the old
        # BIPOP optimum nor a cross-strategy optimum may choose the new mean.
        warm_points = []
    state = _initial_state(
        search_space,
        warm_points,
        population_size=population,
        initial_sigma=initial_sigma,
        restart_index=restart_index,
        initial_mean=(
            _deterministic_restart_mean(dimensions, restart_index)
            if is_restart
            else None
        ),
    )

    pending = 0
    if explicit_mode:
        legacy_cohorts = _legacy_generation_cohorts(
            legacy_own_points,
            population_size=population,
        )
        for cohort in legacy_cohorts:
            state = _update_state(state, cohort)
        records = _explicit_cohort_records(
            observations,
            strategy=strategy,
            restart_index=restart_index,
        )
        expected_cohort = state.updates
        for record_index, record in enumerate(records):
            if record.cohort_index != expected_cohort:
                raise ValueError("CMA cohort history contains a gap")
            if record.population_size != population:
                raise ValueError("CMA cohort population differs from reconstructed state")
            if record.distribution_sha256 != state.distribution_sha256():
                raise ValueError("CMA cohort distribution fingerprint does not match history")
            if not record.complete:
                if record_index != len(records) - 1:
                    raise ValueError("an incomplete CMA cohort is followed by a later cohort")
                pending = record.persisted_count
                break
            cohort_points: list[_TrainingPoint] = []
            for position in range(population):
                observation = record.positions[position]
                vector = _cma_update_vector(search_space, observation)
                if vector is None:
                    raise ValueError("CMA cohort contains an invalid update vector")
                cohort_points.append(_TrainingPoint(observation, vector))
            state = _update_state(state, cohort_points)
            expected_cohort += 1
    else:
        cohorts = _legacy_generation_cohorts(
            own_points,
            population_size=population,
        )
        for cohort in cohorts:
            state = _update_state(state, cohort)
        replayed = sum(len(cohort) for cohort in cohorts)
        pending = max(0, len(own_points) - replayed)
    return CMAState(
        mean=state.mean,
        covariance=state.covariance,
        sigma=state.sigma,
        path_c=state.path_c,
        path_sigma=state.path_sigma,
        updates=state.updates,
        population_size=state.population_size,
        restart_index=state.restart_index,
        pending_offspring=pending,
    )


def _reflect_unit(vector: FloatArray) -> FloatArray:
    wrapped = np.mod(vector, 2.0)
    return np.where(wrapped <= 1.0, wrapped, 2.0 - wrapped)


def _history_keys(
    search_space: SearchSpace,
    observations: Sequence[OptimizerObservation],
) -> set[tuple[float, ...]]:
    keys: set[tuple[float, ...]] = set()
    for point in _training_points(search_space, observations):
        try:
            projected = search_space.from_unit_vector(point.vector.tolist())
        except ValueError:
            continue
        keys.add(tuple(search_space.to_unit_vector(projected)))
    return keys


def _sample_projected_pool(
    search_space: SearchSpace,
    state: CMAState,
    rng: np.random.Generator,
    *,
    requested: int,
    observations: Sequence[OptimizerObservation],
) -> list[tuple[dict[str, float], FloatArray, FloatArray, float]]:
    if requested <= 0:
        return []
    dimensions = len(search_space.tunable)
    if dimensions == 0:
        empty = np.empty(0, dtype=np.float64)
        return [(search_space.baseline(), empty, empty, 0.0)]
    covariance = _stabilize_covariance(state.covariance)
    eigenvalues, eigenvectors = np.linalg.eigh(covariance)
    transform = eigenvectors @ np.diag(np.sqrt(np.maximum(eigenvalues, _MIN_EIGENVALUE)))
    seen = _history_keys(search_space, observations)
    pool: list[tuple[dict[str, float], FloatArray, FloatArray, float]] = []
    attempts = 0
    max_attempts = max(_MAX_PROJECTION_ATTEMPTS, requested * 30)
    while len(pool) < requested and attempts < max_attempts:
        standard = rng.standard_normal(dimensions)
        raw = state.mean + state.sigma * (transform @ standard)
        reflected = _reflect_unit(raw)
        attempts += 1
        try:
            parameters = search_space.from_unit_vector(reflected.tolist())
        except ValueError:
            continue
        projected = np.asarray(search_space.to_unit_vector(parameters), dtype=np.float64)
        key = tuple(projected.tolist())
        if key in seen:
            continue
        seen.add(key)
        pool.append(
            (
                parameters,
                projected,
                np.asarray(reflected, dtype=np.float64),
                float(np.dot(standard, standard)),
            )
        )
    return pool


def _active_rbf_points(
    points: Sequence[_TrainingPoint],
    *,
    purpose: Literal["objective", "feasibility"],
    limit: int = _RBF_ACTIVE_SET_LIMIT,
) -> list[_TrainingPoint]:
    """Choose a bounded deterministic set with elites, failures and coverage."""

    if len(points) <= limit:
        return list(points)
    selected: set[int] = set()

    def retain(indices: Iterable[int], count: int) -> None:
        for index in indices:
            if len(selected) >= limit or count <= 0:
                return
            if index not in selected:
                selected.add(index)
                count -= 1

    reserve = max(1, limit // 5)
    if purpose == "objective":
        ranked = sorted(range(len(points)), key=lambda index: _rank_key(points[index]))
    else:
        ranked = sorted(
            range(len(points)),
            key=lambda index: (
                0.0 if not _is_effectively_feasible(points[index].observation) else 1.0,
                -points[index].observation.failure_rate,
                _constraint_violation(points[index].observation),
                _observation_order_key(points[index].observation),
            ),
        )
    retain(ranked, reserve)
    recent = sorted(
        range(len(points)),
        key=lambda index: (
            -points[index].observation.generation_index,
            _observation_order_key(points[index].observation),
        ),
    )
    retain(recent, reserve)

    if points and len(points[0].vector):
        for dimension in range(len(points[0].vector)):
            retain(
                sorted(
                    range(len(points)),
                    key=lambda index: (
                        points[index].vector[dimension],
                        tuple(points[index].vector.tolist()),
                    ),
                )[:1],
                1,
            )
            retain(
                sorted(
                    range(len(points)),
                    key=lambda index: (
                        -points[index].vector[dimension],
                        tuple(points[index].vector.tolist()),
                    ),
                )[:1],
                1,
            )

    if not selected:
        selected.add(0)
    while len(selected) < limit:
        remaining = [index for index in range(len(points)) if index not in selected]
        if not remaining:
            break
        chosen = max(
            remaining,
            key=lambda index: (
                min(
                    float(np.linalg.norm(points[index].vector - points[other].vector))
                    for other in selected
                ),
                tuple(-float(value) for value in points[index].vector),
                _observation_order_key(points[index].observation),
            ),
        )
        selected.add(chosen)
    return [points[index] for index in sorted(selected)]


def _surrogate_models(
    search_space: SearchSpace,
    observations: Sequence[OptimizerObservation],
    *,
    objective_observations: Sequence[OptimizerObservation] | None = None,
) -> tuple[_RBFRegressor | None, _RBFRegressor | None, float, float, dict[str, int]]:
    points = [
        point
        for point in _training_points(search_space, observations)
        if point.observation.completed
    ]
    feasibility_source_count = len(points)
    objective_points = [
        point
        for point in _training_points(
            search_space,
            observations if objective_observations is None else objective_observations,
        )
        if point.observation.completed
    ]
    successful = [
        point
        for point in objective_points
        if _is_effectively_feasible(point.observation)
        and point.observation.loss is not None
        and math.isfinite(point.observation.loss)
    ]
    objective_source_count = len(successful)
    successful = _active_rbf_points(successful, purpose="objective")
    objective_model: _RBFRegressor | None = None
    loss_center = 0.0
    loss_scale = 1.0
    if len(successful) >= 3:
        finite_losses: list[float] = []
        for point in successful:
            loss = point.observation.loss
            if loss is not None:
                finite_losses.append(float(loss))
        losses = np.asarray(finite_losses, dtype=np.float64)
        loss_center = float(np.median(losses))
        loss_scale = float(np.median(np.abs(losses - loss_center))) * 1.4826
        if loss_scale < 1e-9:
            loss_scale = max(float(np.std(losses)), 1.0)
        objective_model = _RBFRegressor(
            np.stack([point.vector for point in successful]),
            (losses - loss_center) / loss_scale,
            ridge=0.03,
            prior=0.0,
        )

    feasibility_model: _RBFRegressor | None = None
    points = _active_rbf_points(points, purpose="feasibility")
    if points:
        targets = np.asarray(
            [_soft_feasibility_target(point.observation) for point in points],
            dtype=np.float64,
        )
        feasibility_model = _RBFRegressor(
            np.stack([point.vector for point in points]),
            targets,
            ridge=0.06,
            prior=0.5,
        )
    diagnostics = {
        "limit": _RBF_ACTIVE_SET_LIMIT,
        "objective_source": objective_source_count,
        "objective_active": objective_model.training_size if objective_model is not None else 0,
        "feasibility_source": feasibility_source_count,
        "feasibility_active": (
            feasibility_model.training_size if feasibility_model is not None else 0
        ),
    }
    return objective_model, feasibility_model, loss_center, loss_scale, diagnostics


def _score_pool(
    pool: Sequence[tuple[dict[str, float], FloatArray, FloatArray, float]],
    objective_model: _RBFRegressor | None,
    feasibility_model: _RBFRegressor | None,
) -> list[tuple[float, float, float]]:
    if not pool:
        return []
    vectors = np.stack([item[1] for item in pool])
    if objective_model is None:
        objective_mean = np.zeros(len(pool), dtype=np.float64)
        objective_uncertainty = np.ones(len(pool), dtype=np.float64)
    else:
        objective_mean, objective_uncertainty = objective_model.predict(vectors)
    if feasibility_model is None:
        feasibility = np.full(len(pool), 0.75, dtype=np.float64)
    else:
        raw_feasibility, feasibility_uncertainty = feasibility_model.predict(vectors)
        feasibility = 0.5 + (raw_feasibility - 0.5) * (1.0 - feasibility_uncertainty)
        feasibility = np.clip(feasibility, 0.01, 0.99)
    acquisition = objective_mean - 0.3 * objective_uncertainty + 3.5 * (1.0 - feasibility)
    return [
        (float(acquisition[index]), float(feasibility[index]), float(objective_mean[index]))
        for index in range(len(pool))
    ]


def _select_diverse(
    pool: Sequence[tuple[dict[str, float], FloatArray, FloatArray, float]],
    scores: Sequence[tuple[float, float, float]],
    count: int,
) -> list[int]:
    if count <= 0:
        return []
    remaining = set(range(len(pool)))
    selected: list[int] = []
    while remaining and len(selected) < count:
        best_index = min(
            remaining,
            key=lambda index: (
                scores[index][0]
                - (
                    0.12
                    * min(
                        float(np.linalg.norm(pool[index][1] - pool[chosen][1]))
                        for chosen in selected
                    )
                    if selected
                    else 0.0
                ),
                tuple(pool[index][1].tolist()),
            ),
        )
        selected.append(best_index)
        remaining.remove(best_index)
    return selected


def _proposal_metadata(
    *,
    strategy: str,
    backend: str,
    state: CMAState,
    seed: int,
    predicted_feasibility: float,
    predicted_standardized_loss: float,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    metadata: dict[str, Any] = {
        "strategy": strategy,
        "child_strategy": strategy,
        "optimizer_generated_by": strategy,
        "optimizer_update_eligible": True,
        "portfolio_reward_eligible": True,
        "fidelity": 1.0,
        "backend": backend,
        # JSON numbers above 2**53 lose bits in JavaScript.  Keep the full
        # uint64 seed as a fixed-width hexadecimal string in public metadata.
        "reconstruction_seed": f"{seed:016x}",
        "predicted_feasibility": predicted_feasibility,
        "predicted_standardized_loss": predicted_standardized_loss,
        "cma_state": state.json_summary(),
    }
    metadata.update(extra or {})
    return metadata


def _next_cohort_contract(
    observations: Sequence[OptimizerObservation],
    *,
    strategy: Literal["surrogate_cma_es", "bipop_cma_es"],
    state: CMAState,
) -> tuple[int, str, list[int]]:
    records = _explicit_cohort_records(
        _full_fidelity_observations(observations),
        strategy=strategy,
        restart_index=state.restart_index,
    )
    cohort_index = state.updates
    current = next(
        (record for record in records if record.cohort_index == cohort_index),
        None,
    )
    distribution = state.distribution_sha256()
    if current is None:
        used: set[int] = set()
    else:
        if current.population_size != state.population_size:
            raise ValueError("open CMA cohort population does not match state")
        if current.distribution_sha256 != distribution:
            raise ValueError("open CMA cohort distribution does not match state")
        used = set(current.positions)
    missing = [position for position in range(state.population_size) if position not in used]
    cohort_id = f"{strategy}:r{state.restart_index}:c{cohort_index}:{distribution[:12]}"
    if current is not None and current.cohort_id != cohort_id:
        raise ValueError("open CMA cohort identifier does not match reconstructed state")
    return cohort_index, cohort_id, missing


def propose_surrogate_cma_es(
    search_space: SearchSpace,
    request: OptimizerRequest,
) -> list[ExperimentalProposal]:
    """Propose a batch using full CMA adaptation and RBF preselection."""

    if request.batch_size <= 0:
        return []
    full_fidelity_history = _full_fidelity_observations(request.observations)
    dimensions = len(search_space.tunable)
    if dimensions == 0:
        return [
            ExperimentalProposal(
                label=f"surrogate_cma_es_g{request.generation_index}_1",
                parameters=search_space.baseline(),
                rationale="No tunable dimensions; returning the projected baseline",
                metadata={
                    "strategy": "surrogate_cma_es",
                    "child_strategy": "surrogate_cma_es",
                    "optimizer_generated_by": "projected_baseline",
                    "optimizer_update_eligible": False,
                    "portfolio_reward_eligible": False,
                    "fidelity": 1.0,
                    "backend": "projected_baseline",
                },
            )
        ]
    # Lambda is a property of the CMA distribution, not of the orchestrator's
    # currently available batch capacity.  Keeping it dimension-derived makes
    # state reconstruction invariant when a standalone/portfolio allocation
    # changes from one request to the next.
    population_size = 4 + int(3 * math.log(max(2, dimensions)))
    state = reconstruct_cma_state(
        search_space,
        full_fidelity_history,
        strategy="surrogate_cma_es",
        population_size=population_size,
        initial_sigma=0.24,
    )
    cohort_index, cohort_id, missing_positions = _next_cohort_contract(
        full_fidelity_history,
        strategy="surrogate_cma_es",
        state=state,
    )
    requested_count = min(request.batch_size, len(missing_positions))
    if requested_count <= 0:
        return []
    seed = _canonical_seed(request, namespace="surrogate_cma_es")
    rng = np.random.Generator(np.random.PCG64(seed))
    pool_size = max(requested_count * 16, population_size * 6)
    pool = _sample_projected_pool(
        search_space,
        state,
        rng,
        requested=pool_size,
        observations=full_fidelity_history,
    )
    objective_model, feasibility_model, _, _, rbf_diagnostics = _surrogate_models(
        search_space,
        request.observations,
        objective_observations=full_fidelity_history,
    )
    scores = _score_pool(pool, objective_model, feasibility_model)
    chosen = _select_diverse(pool, scores, requested_count)
    proposals: list[ExperimentalProposal] = []
    for rank, pool_index in enumerate(chosen, start=1):
        parameters, _, update_vector, _ = pool[pool_index]
        cohort_position = missing_positions[rank - 1]
        acquisition, feasibility, predicted_loss = scores[pool_index]
        proposals.append(
            ExperimentalProposal(
                label=f"surrogate_cma_es_g{request.generation_index}_{rank}",
                parameters=parameters,
                rationale=(
                    "Full-covariance CMA-ES proposal preselected by objective and "
                    "failure-aware RBF surrogates"
                ),
                metadata=_proposal_metadata(
                    strategy="surrogate_cma_es",
                    backend="numpy_full_covariance_cma_rbf",
                    state=state,
                    seed=seed,
                    predicted_feasibility=feasibility,
                    predicted_standardized_loss=predicted_loss,
                    extra={
                        "acquisition": acquisition,
                        "pool_size": len(pool),
                        "rbf_training_set": rbf_diagnostics,
                        "cma_contract_version": _CMA_CONTRACT_VERSION,
                        "cma_restart_index": state.restart_index,
                        "cma_cohort_index": cohort_index,
                        "cma_cohort_id": cohort_id,
                        "cma_cohort_position": cohort_position,
                        "cma_population_size": state.population_size,
                        "cma_distribution_sha256": state.distribution_sha256(),
                        "cma_update_vector": update_vector.tolist(),
                        "cma_ask_seed": f"{seed:016x}",
                    },
                ),
            )
        )
    return proposals


def bipop_restart_plan(restart_index: int, dimensions: int) -> BIPOPRestartPlan:
    """Return a deterministic BIPOP-inspired alternating restart schedule.

    This schedule intentionally does not claim the original algorithm's
    evaluation-budget balancing; that distinction is exposed in metadata.
    """

    if restart_index < 0:
        raise ValueError("restart_index must be non-negative")
    if dimensions < 1:
        raise ValueError("dimensions must be positive")
    base_population = 4 + int(3 * math.log(max(2, dimensions)))
    if restart_index % 2 == 0:
        large_index = restart_index // 2
        return BIPOPRestartPlan(
            restart_index=restart_index,
            regime="large",
            population_size=base_population * (2**large_index),
            initial_sigma=0.30,
        )
    large_index = (restart_index - 1) // 2
    upper_population = base_population * (2 ** (large_index + 1))
    fraction = ((restart_index * 0.6180339887498949) % 1.0) ** 2
    population = base_population + int(fraction * max(1, upper_population - base_population))
    sigma_fraction = (restart_index * 0.4142135623730950) % 1.0
    initial_sigma = 0.02 * ((0.20 / 0.02) ** sigma_fraction)
    return BIPOPRestartPlan(
        restart_index=restart_index,
        regime="small",
        population_size=max(base_population, population),
        initial_sigma=initial_sigma,
    )


def _restart_boundaries(
    observations: Sequence[OptimizerObservation],
    *,
    strategy: str,
    dimensions: int,
    patience: int = 3,
) -> list[int]:
    """Locate BIPOP restarts from completed CMA populations.

    A single offspring carries no selection information and therefore cannot
    count as a CMA generation.  This is especially important inside the
    portfolio, where one child may receive only one slot per orchestration
    generation.  We buffer those observations until the current BIPOP lambda
    has completed before updating stagnation or triggering a restart.
    """

    relevant = [
        item
        for item in observations
        if _strategy_matches(item, strategy) and item.requested_fidelity >= 1.0 - 1e-9
    ]
    boundaries: list[int] = []
    best = float("inf")
    stagnant = 0
    age = 0
    restart_index = 0
    cohorts: list[tuple[int, int, list[OptimizerObservation]]] = []
    explicit = _explicit_cohort_records(relevant, strategy=strategy)
    if explicit:
        cohorts = [
            (
                record.restart_index,
                max(item.generation_index for item in record.positions.values()),
                [record.positions[position] for position in range(record.population_size)],
            )
            for record in explicit
            if record.complete
        ]
    else:
        by_generation: dict[int, list[OptimizerObservation]] = defaultdict(list)
        for item in relevant:
            if _is_legacy_cma_offspring(item, strategy=strategy):
                by_generation[item.generation_index].append(item)
        for generation_index in sorted(by_generation):
            population_size = bipop_restart_plan(restart_index, dimensions).population_size
            cohort = by_generation[generation_index]
            if len(cohort) != population_size or not all(item.completed for item in cohort):
                continue
            cohorts.append((restart_index, generation_index, cohort))

    for recorded_restart, generation_index, cohort in cohorts:
        if recorded_restart < restart_index:
            continue
        if recorded_restart > restart_index:
            restart_index = recorded_restart
            best = float("inf")
            stagnant = 0
            age = 0
        finite = [
            float(item.loss)
            for item in cohort
            if item.loss is not None and math.isfinite(item.loss) and _is_effectively_feasible(item)
        ]
        generation_best = min(finite, default=float("inf"))
        improved = math.isfinite(generation_best) and (
            not math.isfinite(best)
            or generation_best < best - (1e-8 * max(1.0, abs(best)))
        )
        if improved:
            best = generation_best
            stagnant = 0
        else:
            stagnant += 1
        age += 1
        if stagnant >= patience or age >= 8:
            boundaries.append(generation_index + 1)
            restart_index += 1
            best = float("inf")
            stagnant = 0
            age = 0
    return boundaries


def propose_bipop_cma_es(
    search_space: SearchSpace,
    request: OptimizerRequest,
) -> list[ExperimentalProposal]:
    """Propose a batch with full CMA updates and BIPOP restart sizing."""

    if request.batch_size <= 0:
        return []
    full_fidelity_history = _full_fidelity_observations(request.observations)
    dimensions = len(search_space.tunable)
    if dimensions == 0:
        return [
            ExperimentalProposal(
                label=f"bipop_cma_es_g{request.generation_index}_1",
                parameters=search_space.baseline(),
                rationale="No tunable dimensions; returning the projected baseline",
                metadata={
                    "strategy": "bipop_cma_es",
                    "child_strategy": "bipop_cma_es",
                    "optimizer_generated_by": "projected_baseline",
                    "optimizer_update_eligible": False,
                    "portfolio_reward_eligible": False,
                    "fidelity": 1.0,
                    "backend": "projected_baseline",
                },
            )
        ]
    boundaries = _restart_boundaries(
        full_fidelity_history,
        strategy="bipop_cma_es",
        dimensions=dimensions,
    )
    restart_index = len(boundaries)
    current_start = boundaries[-1] if boundaries else None
    plan = bipop_restart_plan(restart_index, dimensions)
    state = reconstruct_cma_state(
        search_space,
        full_fidelity_history,
        strategy="bipop_cma_es",
        population_size=plan.population_size,
        initial_sigma=plan.initial_sigma,
        restart_index=restart_index,
        minimum_generation=current_start,
    )
    cohort_index, cohort_id, missing_positions = _next_cohort_contract(
        full_fidelity_history,
        strategy="bipop_cma_es",
        state=state,
    )
    requested_count = min(request.batch_size, len(missing_positions))
    if requested_count <= 0:
        return []
    seed = _canonical_seed(
        request,
        namespace="bipop_cma_es",
        extra=plan.json_summary(),
    )
    rng = np.random.Generator(np.random.PCG64(seed))
    pool_size = max(requested_count * 12, min(plan.population_size * 5, 512))
    pool = _sample_projected_pool(
        search_space,
        state,
        rng,
        requested=pool_size,
        observations=full_fidelity_history,
    )
    _, feasibility_model, _, _, rbf_diagnostics = _surrogate_models(
        search_space,
        request.observations,
        objective_observations=full_fidelity_history,
    )
    scores = _score_pool(pool, None, feasibility_model)
    chosen = _select_diverse(pool, scores, requested_count)
    proposals: list[ExperimentalProposal] = []
    for rank, pool_index in enumerate(chosen, start=1):
        parameters, _, update_vector, mahalanobis = pool[pool_index]
        cohort_position = missing_positions[rank - 1]
        acquisition, feasibility, _ = scores[pool_index]
        proposals.append(
            ExperimentalProposal(
                label=f"bipop_cma_es_r{restart_index}_g{request.generation_index}_{rank}",
                parameters=parameters,
                rationale=(
                    f"Full-covariance BIPOP-inspired CMA {plan.regime} restart proposal "
                    "screened by historical feasibility"
                ),
                metadata=_proposal_metadata(
                    strategy="bipop_cma_es",
                    backend="numpy_full_covariance_bipop_cma",
                    state=state,
                    seed=seed,
                    predicted_feasibility=feasibility,
                    predicted_standardized_loss=0.0,
                    extra={
                        **plan.json_summary(),
                        "acquisition": acquisition,
                        "mahalanobis_squared": mahalanobis,
                        "restart_boundaries": boundaries,
                        "rbf_training_set": rbf_diagnostics,
                        "cma_contract_version": _CMA_CONTRACT_VERSION,
                        "cma_restart_index": state.restart_index,
                        "cma_cohort_index": cohort_index,
                        "cma_cohort_id": cohort_id,
                        "cma_cohort_position": cohort_position,
                        "cma_population_size": state.population_size,
                        "cma_distribution_sha256": state.distribution_sha256(),
                        "cma_update_vector": update_vector.tolist(),
                        "cma_ask_seed": f"{seed:016x}",
                    },
                ),
            )
        )
    return proposals


def propose_evolutionary_candidates(
    search_space: SearchSpace,
    request: OptimizerRequest,
) -> list[ExperimentalProposal]:
    """Dispatch the evolutionary strategies through their shared contract."""

    if request.strategy == "surrogate_cma_es":
        return propose_surrogate_cma_es(search_space, request)
    if request.strategy == "bipop_cma_es":
        return propose_bipop_cma_es(search_space, request)
    if request.strategy == "optimizer_portfolio":
        # Delayed import avoids a module cycle: the portfolio delegates its
        # evolutionary child allocations back through this dispatcher.
        from app.optimization.portfolio_optimizer import propose_optimizer_portfolio

        return propose_optimizer_portfolio(search_space, request)
    raise ValueError(f"unsupported evolutionary optimizer: {request.strategy}")


__all__ = [
    "BIPOPRestartPlan",
    "CMAState",
    "bipop_restart_plan",
    "propose_bipop_cma_es",
    "propose_evolutionary_candidates",
    "propose_surrogate_cma_es",
    "reconstruct_cma_state",
]
