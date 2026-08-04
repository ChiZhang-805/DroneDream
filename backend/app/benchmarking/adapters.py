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
from typing import Any, Final

from app.benchmarking.contracts import (
    BenchmarkObservationV2,
    BenchmarkProposalV1,
    canonical_json_bytes,
    canonical_sha256,
)
from app.optimization.design import halton_design
from app.optimization.domain import ParameterDomain, SearchSpace

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


__all__ = [
    "BenchmarkAdapterError",
    "RandomSearchAdapterV1",
    "SeededHaltonAdapterV1",
    "search_space_from_observation",
]
