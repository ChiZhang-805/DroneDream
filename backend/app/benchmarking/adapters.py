"""Deterministic proposal adapters for the frozen benchmark observation contract.

The adapters in this module are deliberately simulator- and provider-independent.
They consume only :class:`BenchmarkObservationV2`, never sealed qualification
outcomes, and return exactly one bounded proposal.  Publication campaigns may
therefore compare them under the same evaluator and simulator budget.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Final, Literal, cast

from app.benchmarking.contracts import (
    BenchmarkObservationV2,
    BenchmarkProposalV1,
    canonical_json_bytes,
    canonical_sha256,
)
from app.optimization.design import halton_design
from app.optimization.domain import ParameterDomain, SearchSpace
from app.optimization.experimental_types import (
    ExperimentalOptimizerStrategy,
    OptimizerObservation,
    OptimizerRequest,
)

_DOMAIN_KEYS: Final = {
    "name",
    "baseline",
    "minimum",
    "maximum",
    "step",
    "scale",
    "value_type",
    "choices",
    "enabled",
    "locked",
}
_MAX_SELECTION_ATTEMPTS: Final = 4096
_HALTON_SEED_OFFSET_MODULUS: Final = 1_000_003


class BenchmarkAdapterError(ValueError):
    """Raised when a proposal cannot be produced without violating the contract."""


def _strict_number(value: object, *, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise BenchmarkAdapterError(f"parameter-domain {field} must be numeric")
    return float(value)


def _optional_number(value: object, *, field: str) -> float | None:
    if value is None:
        return None
    return _strict_number(value, field=field)


def _strict_bool(value: object, *, field: str, default: bool) -> bool:
    if value is None:
        return default
    if not isinstance(value, bool):
        raise BenchmarkAdapterError(f"parameter-domain {field} must be boolean")
    return value


def _domain_from_payload(payload: Mapping[str, Any]) -> ParameterDomain:
    unknown = set(payload).difference(_DOMAIN_KEYS)
    if unknown:
        raise BenchmarkAdapterError(
            "unsupported parameter-domain fields: " + ", ".join(sorted(unknown))
        )
    name = payload.get("name")
    if not isinstance(name, str) or not name:
        raise BenchmarkAdapterError("parameter-domain name must be a non-empty string")
    choices_payload = payload.get("choices", ())
    if choices_payload is None:
        choices_payload = ()
    if not isinstance(choices_payload, list | tuple):
        raise BenchmarkAdapterError("parameter-domain choices must be an array")
    choices = tuple(
        _strict_number(value, field=f"choices[{index}]")
        for index, value in enumerate(choices_payload)
    )
    scale = payload.get("scale", "linear")
    value_type = payload.get("value_type", "float")
    if not isinstance(scale, str) or not isinstance(value_type, str):
        raise BenchmarkAdapterError("parameter-domain scale and value_type must be strings")
    try:
        return ParameterDomain(
            name=name,
            baseline=_strict_number(payload.get("baseline"), field="baseline"),
            minimum=_strict_number(payload.get("minimum"), field="minimum"),
            maximum=_strict_number(payload.get("maximum"), field="maximum"),
            step=_optional_number(payload.get("step"), field="step"),
            scale=scale,
            value_type=value_type,
            choices=choices,
            enabled=_strict_bool(payload.get("enabled"), field="enabled", default=True),
            locked=_strict_bool(payload.get("locked"), field="locked", default=False),
        )
    except ValueError as exc:
        raise BenchmarkAdapterError(str(exc)) from exc


def search_space_from_observation(observation: BenchmarkObservationV2) -> SearchSpace:
    """Build the one allowed search-space view from a frozen observation."""

    try:
        domains = tuple(_domain_from_payload(item) for item in observation.parameter_domain)
        space = SearchSpace(domains)
    except (TypeError, ValueError) as exc:
        if isinstance(exc, BenchmarkAdapterError):
            raise
        raise BenchmarkAdapterError(f"invalid benchmark parameter domain: {exc}") from exc
    if not space.tunable:
        raise BenchmarkAdapterError("benchmark parameter domain has no tunable parameters")
    return space


def _candidate_key(parameters: Mapping[str, float]) -> tuple[tuple[str, float], ...]:
    return tuple(sorted((name, float(value)) for name, value in parameters.items()))


def _seen_candidates(
    observation: BenchmarkObservationV2,
    space: SearchSpace,
) -> set[tuple[tuple[str, float], ...]]:
    seen: set[tuple[tuple[str, float], ...]] = set()
    for item in observation.history:
        try:
            projected = space.project(item.parameters)
        except ValueError as exc:
            raise BenchmarkAdapterError(
                f"history candidate {item.candidate_ref!r} violates the frozen domain: {exc}"
            ) from exc
        seen.add(_candidate_key(projected))
    return seen


def _require_available_budget(observation: BenchmarkObservationV2) -> None:
    if observation.simulator_budget_remaining < 1:
        raise BenchmarkAdapterError("simulator budget is exhausted")
    if observation.wall_time_remaining_ms < 1:
        raise BenchmarkAdapterError("wall-time budget is exhausted")


def _seed_material(observation: BenchmarkObservationV2, adapter_id: str) -> bytes:
    payload = {
        "adapter_id": adapter_id,
        "algorithm_seed": observation.algorithm_seed,
        "generation_index": observation.generation_index,
        "next_dispatch_ordinal": observation.next_dispatch_ordinal,
        "schema_id": "dronedream.benchmark-adapter-seed/v1",
    }
    return hashlib.sha256(canonical_json_bytes(payload)).digest()


def _sha_uniform(seed: bytes, *, attempt: int, dimension: int) -> float:
    digest = hashlib.sha256(
        seed
        + attempt.to_bytes(8, byteorder="big", signed=False)
        + dimension.to_bytes(4, byteorder="big", signed=False)
    ).digest()
    return int.from_bytes(digest[:8], byteorder="big", signed=False) / 2**64


def _proposal(
    *,
    adapter_id: str,
    observation: BenchmarkObservationV2,
    parameters: dict[str, float],
    reason_code: str,
    seed: bytes,
    selection_attempt: int,
    sequence_index: int | None = None,
    extra_receipt: Mapping[str, Any] | None = None,
) -> BenchmarkProposalV1:
    parameter_sha256 = canonical_sha256(parameters)
    receipt: dict[str, Any] = {
        "adapter_id": adapter_id,
        "adapter_contract_id": "dronedream.benchmark-proposal-adapter/v1",
        "observation_sha256": canonical_sha256(observation),
        "parameter_sha256": parameter_sha256,
        "seed_material_sha256": hashlib.sha256(seed).hexdigest(),
        "selection_attempt": selection_attempt,
    }
    if sequence_index is not None:
        receipt["sequence_index"] = sequence_index
    if extra_receipt:
        collisions = set(receipt).intersection(extra_receipt)
        if collisions:
            raise BenchmarkAdapterError(
                "extra proposal receipt overwrites reserved fields: "
                + ", ".join(sorted(collisions))
            )
        receipt.update(extra_receipt)
    label = adapter_id.split("/", maxsplit=1)[0].replace("_", "-")
    return BenchmarkProposalV1(
        candidate_ref=(
            f"{label}-g{observation.generation_index:06d}-"
            f"d{observation.next_dispatch_ordinal:06d}-{parameter_sha256[:12]}"
        ),
        parameters=parameters,
        reason_code=reason_code,
        proposal_receipt=receipt,
    )


@dataclass(frozen=True, slots=True)
class RandomSearchAdapterV1:
    """Dependency-free, seeded uniform random-search reference adapter."""

    adapter_id: str = "random_search/v1"

    def propose(self, observation: BenchmarkObservationV2) -> BenchmarkProposalV1:
        _require_available_budget(observation)
        space = search_space_from_observation(observation)
        seen = _seen_candidates(observation, space)
        seed = _seed_material(observation, self.adapter_id)
        dimensions = len(space.tunable)
        for attempt in range(_MAX_SELECTION_ATTEMPTS):
            vector = tuple(
                _sha_uniform(seed, attempt=attempt, dimension=dimension)
                for dimension in range(dimensions)
            )
            try:
                parameters = space.from_unit_vector(vector)
            except ValueError:
                continue
            if _candidate_key(parameters) in seen:
                continue
            return _proposal(
                adapter_id=self.adapter_id,
                observation=observation,
                parameters=parameters,
                reason_code="uniform-random-proposal",
                seed=seed,
                selection_attempt=attempt,
            )
        raise BenchmarkAdapterError(
            f"random search exhausted {_MAX_SELECTION_ATTEMPTS} bounded unique attempts"
        )


@dataclass(frozen=True, slots=True)
class SeededHaltonAdapterV1:
    """Seed-offset Halton reference adapter; this is not labelled as LHS."""

    adapter_id: str = "seeded_halton/v1"

    def propose(self, observation: BenchmarkObservationV2) -> BenchmarkProposalV1:
        _require_available_budget(observation)
        space = search_space_from_observation(observation)
        seen = _seen_candidates(observation, space)
        seed = _seed_material(observation, self.adapter_id)
        offset = int.from_bytes(seed[:8], byteorder="big", signed=False)
        base_index = (
            1 + offset % _HALTON_SEED_OFFSET_MODULUS + observation.next_dispatch_ordinal - 1
        )
        for attempt in range(_MAX_SELECTION_ATTEMPTS):
            sequence_index = base_index + attempt
            candidates = halton_design(
                space,
                1,
                start_index=sequence_index,
                include_baseline=False,
            )
            if not candidates:
                continue
            parameters = candidates[0]
            if _candidate_key(parameters) in seen:
                continue
            return _proposal(
                adapter_id=self.adapter_id,
                observation=observation,
                parameters=parameters,
                reason_code="seeded-halton-proposal",
                seed=seed,
                selection_attempt=attempt,
                sequence_index=sequence_index,
            )
        raise BenchmarkAdapterError(
            f"seeded Halton exhausted {_MAX_SELECTION_ATTEMPTS} bounded unique attempts"
        )


def _positive_preference(
    payload: Mapping[str, Any],
    *,
    field: str,
    default: float,
) -> float:
    value = payload.get(field, default)
    numeric = _strict_number(value, field=f"objectives.{field}")
    if numeric <= 0.0:
        raise BenchmarkAdapterError(f"objective {field} must be > 0")
    return numeric


def _objective_preferences(
    observation: BenchmarkObservationV2,
) -> tuple[tuple[tuple[str, float], ...], tuple[tuple[str, float], ...]]:
    weights: list[tuple[str, float]] = []
    normalizations: list[tuple[str, float]] = []
    seen: set[str] = set()
    for index, payload in enumerate(observation.objectives):
        name = payload.get("name")
        direction = payload.get("direction")
        if not isinstance(name, str) or not name:
            raise BenchmarkAdapterError(f"objectives[{index}].name must be a non-empty string")
        if name in seen:
            raise BenchmarkAdapterError(f"duplicate benchmark objective: {name}")
        if direction not in {"minimize", "maximize"}:
            raise BenchmarkAdapterError(
                f"objectives[{index}].direction must be minimize or maximize"
            )
        seen.add(name)
        weights.append((name, _positive_preference(payload, field="weight", default=1.0)))
        normalizations.append(
            (name, _positive_preference(payload, field="normalization", default=1.0))
        )
    return tuple(weights), tuple(normalizations)


def native_optimizer_request_from_observation(
    observation: BenchmarkObservationV2,
    *,
    strategy: Literal["constrained_mobo", "optimizer_portfolio"],
) -> OptimizerRequest:
    """Translate v2 history without fabricating learning signal for failures."""

    space = search_space_from_observation(observation)
    converted: list[OptimizerObservation] = []
    for item in sorted(
        observation.history,
        key=lambda value: (value.generation_index, value.dispatch_ordinal),
    ):
        outcome = item.outcome
        if outcome.role == "quarantined":
            continue
        try:
            parameters = space.project(item.parameters)
        except ValueError as exc:
            raise BenchmarkAdapterError(
                f"history candidate {item.candidate_ref!r} violates the frozen domain: {exc}"
            ) from exc
        proposal_context = item.proposal_context
        optimizer_metadata = (
            dict(proposal_context.optimizer_metadata) if proposal_context is not None else {}
        )
        optimizer_metadata.update(
            {
                "benchmark_candidate_ref": item.candidate_ref,
                "benchmark_dispatch_ordinal": item.dispatch_ordinal,
                "benchmark_screening_status": item.screening_status,
            }
        )
        source_strategy = (
            proposal_context.optimizer_strategy
            if proposal_context is not None and proposal_context.optimizer_strategy is not None
            else strategy
        )
        converted.append(
            OptimizerObservation(
                candidate_id=item.candidate_ref,
                generation_index=item.generation_index,
                parameters=parameters,
                unit_vector=space.to_unit_vector(parameters),
                loss=outcome.loss,
                objectives=dict(outcome.objectives),
                objective_directions=dict(outcome.objective_directions),
                constraints=dict(outcome.constraint_violations),
                feasible=outcome.feasible,
                failure_rate=outcome.failure_rate,
                fidelity=outcome.fidelity,
                requested_fidelity=outcome.requested_fidelity,
                optimizer_strategy=source_strategy,
                optimizer_metadata=optimizer_metadata,
                completed=outcome.completed,
                role=outcome.role,
            )
        )
    weights, normalizations = _objective_preferences(observation)
    seed = _seed_material(observation, f"product-native/{strategy}")
    return OptimizerRequest(
        strategy=cast(ExperimentalOptimizerStrategy, strategy),
        generation_index=observation.generation_index,
        batch_size=1,
        random_seed=int.from_bytes(seed[:8], byteorder="big", signed=False),
        observations=tuple(converted),
        objective_weights=weights,
        objective_normalizations=normalizations,
        fidelity_mapping=((1.0, 1.0),),
        required_fidelity=1.0,
    )


@dataclass(frozen=True, slots=True)
class ProductNativeOptimizerAdapterV1:
    """Bridge one reviewed product-native optimizer into the benchmark contract."""

    adapter_id: Literal["repo_constrained_mobo/v1", "optimizer_portfolio/v1"]
    strategy: Literal["constrained_mobo", "optimizer_portfolio"]

    def propose(self, observation: BenchmarkObservationV2) -> BenchmarkProposalV1:
        _require_available_budget(observation)
        space = search_space_from_observation(observation)
        request = native_optimizer_request_from_observation(
            observation,
            strategy=self.strategy,
        )
        if self.strategy == "constrained_mobo":
            from app.optimization.bayesian_optimizers import propose_bayesian_candidates

            proposals = propose_bayesian_candidates(space, request)
        else:
            from app.optimization.cma_optimizers import propose_evolutionary_candidates

            proposals = propose_evolutionary_candidates(space, request)
        if len(proposals) != 1:
            raise BenchmarkAdapterError(
                f"{self.adapter_id} returned {len(proposals)} proposals for a one-candidate request"
            )
        native = proposals[0]
        parameters = space.project(native.parameters)
        if _candidate_key(parameters) in _seen_candidates(observation, space):
            raise BenchmarkAdapterError(
                f"{self.adapter_id} repeated a previously dispatched candidate"
            )
        seed = _seed_material(observation, f"product-native/{self.strategy}")
        return _proposal(
            adapter_id=self.adapter_id,
            observation=observation,
            parameters=parameters,
            reason_code=f"product-native-{self.strategy.replace('_', '-')}",
            seed=seed,
            selection_attempt=0,
            extra_receipt={
                "method_classification": "product_native",
                "native_label": native.label,
                "native_metadata": dict(native.metadata),
                "native_metadata_sha256": canonical_sha256(dict(native.metadata)),
                "native_rationale_sha256": hashlib.sha256(
                    native.rationale.encode("utf-8")
                ).hexdigest(),
                "native_strategy": self.strategy,
            },
        )


__all__ = [
    "BenchmarkAdapterError",
    "ProductNativeOptimizerAdapterV1",
    "RandomSearchAdapterV1",
    "SeededHaltonAdapterV1",
    "native_optimizer_request_from_observation",
    "search_space_from_observation",
]
