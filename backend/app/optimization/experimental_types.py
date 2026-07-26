"""Shared contracts for DroneDream's experimental optimization engines.

The numerical optimizers are deliberately simulator and database independent.
They consume normalized observations produced by the orchestration layer and
return parameter-space proposals plus JSON-safe metadata.  Keeping this seam
small lets every algorithm compete on the same history and makes proposals
fully reproducible from a job manifest.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any, Literal, Self, SupportsIndex

ExperimentalOptimizerStrategy = Literal[
    "constrained_mobo",
    "multi_fidelity_mobo",
    "turbo",
    "saasbo",
    "surrogate_cma_es",
    "bipop_cma_es",
    "optimizer_portfolio",
]

EXPERIMENTAL_OPTIMIZER_STRATEGIES: tuple[ExperimentalOptimizerStrategy, ...] = (
    "constrained_mobo",
    "multi_fidelity_mobo",
    "turbo",
    "saasbo",
    "surrogate_cma_es",
    "bipop_cma_es",
    "optimizer_portfolio",
)
OPTIMIZER_SEED_FLOAT_SIGNIFICANT_DIGITS = 12


def canonical_optimizer_seed_value(value: Any) -> Any:
    """Return stable JSON state for deterministic optimizer seed derivation.

    Supported Python runtimes can differ by one binary ULP when aggregating
    the same finite metrics. Hashing the raw float spelling would turn that
    harmless representation noise into an unrelated optimizer random stream.
    """

    if value is None or isinstance(value, str | bool | int):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("optimizer seed state must contain only finite numbers")
        normalized = float(
            format(value, f".{OPTIMIZER_SEED_FLOAT_SIGNIFICANT_DIGITS}g")
        )
        return 0.0 if normalized == 0.0 else normalized
    if isinstance(value, Mapping):
        return {
            str(key): canonical_optimizer_seed_value(item)
            for key, item in value.items()
        }
    if isinstance(value, list | tuple):
        return [canonical_optimizer_seed_value(item) for item in value]
    raise ValueError(
        f"optimizer seed state contains unsupported {type(value).__name__}"
    )


class _FrozenDict(dict[str, Any]):
    """JSON-serializable dict snapshot that rejects post-construction mutation."""

    @staticmethod
    def _immutable(*_args: object, **_kwargs: object) -> None:
        raise TypeError("optimizer contracts are immutable")

    __setitem__ = _immutable
    __delitem__ = _immutable
    clear = _immutable
    pop = _immutable
    setdefault = _immutable
    update = _immutable

    def popitem(self) -> tuple[str, Any]:
        raise TypeError("optimizer contracts are immutable")

    def __ior__(self, _value: object) -> Self:  # type: ignore[override,misc]
        raise TypeError("optimizer contracts are immutable")

    def __deepcopy__(self, _memo: dict[int, object]) -> _FrozenDict:
        return self


class _FrozenList(list[Any]):
    """JSON-serializable list snapshot that rejects mutation."""

    @staticmethod
    def _immutable(*_args: object, **_kwargs: object) -> None:
        raise TypeError("optimizer contracts are immutable")

    __setitem__ = _immutable
    __delitem__ = _immutable
    append = _immutable
    clear = _immutable
    extend = _immutable
    insert = _immutable
    pop = _immutable
    remove = _immutable
    reverse = _immutable
    sort = _immutable

    def __iadd__(self, _value: Iterable[Any]) -> Self:  # type: ignore[misc]
        raise TypeError("optimizer contracts are immutable")

    def __imul__(self, _value: SupportsIndex) -> Self:
        raise TypeError("optimizer contracts are immutable")

    def __deepcopy__(self, _memo: dict[int, object]) -> _FrozenList:
        return self


def _freeze_json(value: Any) -> Any:
    if isinstance(value, Mapping):
        frozen = {
            str(key): _freeze_json(item)
            for key, item in deepcopy(dict(value)).items()
        }
        return _FrozenDict(frozen)
    if isinstance(value, list):
        return _FrozenList(_freeze_json(item) for item in deepcopy(value))
    if isinstance(value, tuple):
        return tuple(_freeze_json(item) for item in value)
    return deepcopy(value)


def _finite_numeric_mapping(name: str, values: Mapping[str, object]) -> None:
    for key, value in values.items():
        if not isinstance(key, str) or not key:
            raise ValueError(f"{name} keys must be non-empty strings")
        if isinstance(value, bool) or not isinstance(value, int | float):
            raise ValueError(f"{name} values must be numeric")
        if not math.isfinite(float(value)):
            raise ValueError(f"{name} values must be finite")


def _validate_json_compatible(name: str, value: object) -> None:
    """Bound optimizer metadata to finite, JSON-compatible diagnostic values."""

    nodes = 0

    def visit(item: object, *, path: str, depth: int) -> None:
        nonlocal nodes
        nodes += 1
        if nodes > 10_000:
            raise ValueError(f"{name} exceeds 10000 JSON values")
        if depth > 32:
            raise ValueError(f"{name} nesting exceeds 32 levels")
        if item is None or isinstance(item, str | bool | int):
            return
        if isinstance(item, float):
            if not math.isfinite(item):
                raise ValueError(f"{path} must contain only finite numbers")
            return
        if isinstance(item, Mapping):
            for key, child in item.items():
                if not isinstance(key, str) or not key:
                    raise ValueError(f"{path} keys must be non-empty strings")
                visit(child, path=f"{path}.{key}", depth=depth + 1)
            return
        if isinstance(item, list | tuple):
            for index, child in enumerate(item):
                visit(child, path=f"{path}[{index}]", depth=depth + 1)
            return
        raise ValueError(f"{path} must be JSON-compatible")

    visit(value, path=name, depth=0)


@dataclass(frozen=True)
class OptimizerObservation:
    """One completed or failed candidate visible to an optimizer.

    ``loss`` is always minimized.  A failed candidate may have ``loss=None``;
    it still contributes to the feasibility model instead of being discarded
    or receiving an arbitrary giant objective value.
    """

    candidate_id: str
    generation_index: int
    parameters: dict[str, float]
    unit_vector: tuple[float, ...]
    loss: float | None
    objectives: dict[str, float] = field(default_factory=dict)
    objective_directions: dict[str, str] = field(default_factory=dict)
    constraints: dict[str, float] = field(default_factory=dict)
    feasible: bool = True
    failure_rate: float = 0.0
    # ``fidelity`` is the effective fraction of the training matrix that was
    # actually executed. ``requested_fidelity`` preserves the optimizer's
    # nominal level and, critically, distinguishes a reduced training run from
    # a fully verified run that also includes the configured holdout matrix.
    fidelity: float = 1.0
    requested_fidelity: float = 1.0
    optimizer_strategy: str | None = None
    # Full proposal metadata is persisted on the candidate row.  CMA uses the
    # cohort/distribution fields to ensure tell() never mixes two asks, while
    # the portfolio uses eligibility fields to exclude fallback proposals.
    optimizer_metadata: dict[str, Any] = field(default_factory=dict)
    completed: bool = True

    def __post_init__(self) -> None:
        if not isinstance(self.candidate_id, str) or not self.candidate_id:
            raise ValueError("candidate_id must be a non-empty string")
        if (
            isinstance(self.generation_index, bool)
            or not isinstance(self.generation_index, int)
            or self.generation_index < 0
        ):
            raise ValueError("generation_index must be a non-negative integer")
        _finite_numeric_mapping("parameters", self.parameters)
        _finite_numeric_mapping("objectives", self.objectives)
        _finite_numeric_mapping("constraints", self.constraints)
        if any(
            isinstance(value, bool) or not isinstance(value, int | float)
            for value in self.unit_vector
        ):
            raise ValueError("unit_vector values must be numeric")
        vector = tuple(float(value) for value in self.unit_vector)
        if not all(math.isfinite(value) and -1e-12 <= value <= 1.0 + 1e-12 for value in vector):
            raise ValueError("unit_vector values must be finite and inside [0, 1]")
        if self.loss is not None and (
            isinstance(self.loss, bool)
            or not isinstance(self.loss, int | float)
            or not math.isfinite(float(self.loss))
        ):
            raise ValueError("loss must be a finite number when provided")
        if not isinstance(self.feasible, bool):
            raise ValueError("feasible must be a boolean")
        if (
            isinstance(self.failure_rate, bool)
            or not isinstance(self.failure_rate, int | float)
            or not math.isfinite(float(self.failure_rate))
            or not 0.0 <= float(self.failure_rate) <= 1.0
        ):
            raise ValueError("failure_rate must be finite and inside [0, 1]")
        if any(
            not isinstance(metric, str)
            or not metric
            or direction not in {"minimize", "maximize"}
            for metric, direction in self.objective_directions.items()
        ):
            raise ValueError(
                "objective directions require non-empty metric names and "
                "'minimize' or 'maximize' values"
            )
        for field_name, value in (
            ("fidelity", self.fidelity),
            ("requested_fidelity", self.requested_fidelity),
        ):
            if (
                isinstance(value, bool)
                or not isinstance(value, int | float)
                or not math.isfinite(float(value))
                or not 0.0 < float(value) <= 1.0
            ):
                raise ValueError(f"{field_name} must be finite and inside (0, 1]")
        if self.optimizer_strategy is not None and (
            not isinstance(self.optimizer_strategy, str)
            or not self.optimizer_strategy
        ):
            raise ValueError("optimizer_strategy must be a non-empty string when provided")
        if not isinstance(self.completed, bool):
            raise ValueError("completed must be a boolean")
        _validate_json_compatible("optimizer_metadata", self.optimizer_metadata)
        object.__setattr__(self, "parameters", _freeze_json(self.parameters))
        object.__setattr__(self, "unit_vector", vector)
        object.__setattr__(self, "objectives", _freeze_json(self.objectives))
        object.__setattr__(self, "objective_directions", _freeze_json(self.objective_directions))
        object.__setattr__(self, "constraints", _freeze_json(self.constraints))
        object.__setattr__(self, "optimizer_metadata", _freeze_json(self.optimizer_metadata))


@dataclass(frozen=True)
class ExperimentalProposal:
    """One candidate proposed by an experimental optimizer."""

    label: str
    parameters: dict[str, float]
    rationale: str
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.label, str) or not self.label:
            raise ValueError("proposal label must be a non-empty string")
        if not isinstance(self.rationale, str) or not self.rationale:
            raise ValueError("proposal rationale must be a non-empty string")
        _finite_numeric_mapping("proposal parameters", self.parameters)
        _validate_json_compatible("proposal metadata", self.metadata)
        object.__setattr__(self, "parameters", _freeze_json(self.parameters))
        object.__setattr__(self, "metadata", _freeze_json(self.metadata))


@dataclass(frozen=True)
class OptimizerRequest:
    """Immutable input to a generation-level optimizer call."""

    strategy: ExperimentalOptimizerStrategy
    generation_index: int
    batch_size: int
    random_seed: int
    observations: tuple[OptimizerObservation, ...]
    # Frozen Job preference inputs. Bayesian vector acquisitions use these
    # instead of adapting objective scales or weights from observed extrema.
    objective_weights: tuple[tuple[str, float], ...] = ()
    objective_normalizations: tuple[tuple[str, float], ...] = ()
    # Pairs are (requested level, effective training-matrix coverage). The
    # orchestration layer derives them from the concrete scenario/seed matrix.
    fidelity_mapping: tuple[tuple[float, float], ...] = ()
    required_fidelity: float | None = None

    def __post_init__(self) -> None:
        if self.strategy not in EXPERIMENTAL_OPTIMIZER_STRATEGIES:
            raise ValueError(f"unsupported experimental optimizer strategy: {self.strategy}")
        if (
            isinstance(self.generation_index, bool)
            or not isinstance(self.generation_index, int)
            or self.generation_index < 0
        ):
            raise ValueError("generation_index must be a non-negative integer")
        if (
            isinstance(self.batch_size, bool)
            or not isinstance(self.batch_size, int)
            or self.batch_size < 0
        ):
            raise ValueError("batch_size must be a non-negative integer")
        if (
            isinstance(self.random_seed, bool)
            or not isinstance(self.random_seed, int)
            or not 0 <= self.random_seed < 2**64
        ):
            raise ValueError("random_seed must be a uint64 integer")
        observations = tuple(self.observations)
        if not all(isinstance(item, OptimizerObservation) for item in observations):
            raise ValueError("observations must contain OptimizerObservation values")
        for field_name, pairs in (
            ("objective_weights", self.objective_weights),
            ("objective_normalizations", self.objective_normalizations),
        ):
            names = [name for name, _value in pairs]
            if (
                any(not isinstance(name, str) or not name for name in names)
                or len(set(names)) != len(names)
                or any(
                    isinstance(value, bool)
                    or not isinstance(value, int | float)
                    or not math.isfinite(float(value))
                    or float(value) <= 0.0
                    for _name, value in pairs
                )
            ):
                raise ValueError(
                    f"{field_name} must contain unique metric names and "
                    "finite positive values"
                )
        weight_names = {name for name, _value in self.objective_weights}
        normalization_names = {
            name for name, _value in self.objective_normalizations
        }
        if weight_names != normalization_names:
            raise ValueError(
                "objective_weights and objective_normalizations must declare "
                "the same metric names"
            )
        if any(
            isinstance(value, bool) or not isinstance(value, int | float)
            for pair in self.fidelity_mapping
            for value in pair
        ):
            raise ValueError("fidelity_mapping values must be numeric")
        mapping = tuple(
            (float(requested), float(effective))
            for requested, effective in self.fidelity_mapping
        )
        if any(
            not math.isfinite(value) or not 0.0 < value <= 1.0
            for pair in mapping
            for value in pair
        ):
            raise ValueError("fidelity_mapping values must be finite and inside (0, 1]")
        requested_levels = [requested for requested, _ in mapping]
        if len({round(value, 12) for value in requested_levels}) != len(mapping):
            raise ValueError("fidelity_mapping requested levels must be unique")
        ordered_mapping = tuple(sorted(mapping))
        if any(
            right[1] + 1e-12 < left[1]
            for left, right in zip(
                ordered_mapping,
                ordered_mapping[1:],
                strict=False,
            )
        ):
            raise ValueError("fidelity_mapping effective coverage must be monotonic")
        for requested, effective in ordered_mapping:
            if requested >= 1.0 - 1e-12 and effective < 1.0 - 1e-12:
                raise ValueError("full requested fidelity must map to full effective coverage")
        if self.required_fidelity is not None and (
            isinstance(self.required_fidelity, bool)
            or not isinstance(self.required_fidelity, int | float)
            or not math.isfinite(float(self.required_fidelity))
            or not 0.0 < float(self.required_fidelity) <= 1.0
        ):
            raise ValueError("required_fidelity must be finite and inside (0, 1]")
        object.__setattr__(self, "observations", observations)
        object.__setattr__(
            self,
            "objective_weights",
            tuple(
                (name, float(value))
                for name, value in self.objective_weights
            ),
        )
        object.__setattr__(
            self,
            "objective_normalizations",
            tuple(
                (name, float(value))
                for name, value in self.objective_normalizations
            ),
        )
        object.__setattr__(self, "fidelity_mapping", ordered_mapping)


__all__ = [
    "EXPERIMENTAL_OPTIMIZER_STRATEGIES",
    "ExperimentalOptimizerStrategy",
    "ExperimentalProposal",
    "OptimizerObservation",
    "OptimizerRequest",
]
