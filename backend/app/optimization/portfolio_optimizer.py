"""Adaptive budget portfolio over DroneDream's six base optimizers."""

from __future__ import annotations

import hashlib
import math
import random
from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass, replace
from typing import Any, cast

from app.optimization.design import MAX_HALTON_DIMENSIONS, halton_design
from app.optimization.domain import SearchSpace
from app.optimization.experimental_types import (
    OPTIMIZER_LEARNING_OBSERVATION_ROLES,
    ExperimentalOptimizerStrategy,
    ExperimentalProposal,
    OptimizerObservation,
    OptimizerRequest,
)
from app.optimization.outcome_contract import (
    OPTIMIZER_LEARNING_FAILURE_RATE_LIMIT,
    PORTFOLIO_REWARD_SCALE,
)
from app.optimization.proposal_provenance import (
    OPTIMIZER_SOURCE_EVIDENCE_REQUIRED_FIELD,
    PORTFOLIO_SOURCES_V2_SCHEMA,
    classify_optimizer_source_role,
    verified_observation_source_evidence,
)

_CHILD_STRATEGIES: tuple[ExperimentalOptimizerStrategy, ...] = (
    "constrained_mobo",
    "multi_fidelity_mobo",
    "turbo",
    "saasbo",
    "surrogate_cma_es",
    "bipop_cma_es",
)
_BAYESIAN_STRATEGIES = frozenset(_CHILD_STRATEGIES[:4])
_PORTFOLIO_SOURCES_SCHEMA = PORTFOLIO_SOURCES_V2_SCHEMA


def _child_strategy_from_metadata(
    metadata: Mapping[str, Any],
) -> ExperimentalOptimizerStrategy:
    raw = metadata.get("child_strategy")
    if raw not in _CHILD_STRATEGIES:
        raise ValueError("portfolio child proposal is missing valid child_strategy metadata")
    return cast(ExperimentalOptimizerStrategy, raw)


@dataclass(frozen=True)
class PortfolioStatistic:
    """Auditable history summary used for budget allocation."""

    strategy: ExperimentalOptimizerStrategy
    observations: int
    full_fidelity_observations: int
    reward_credit: float
    feasible_observations: int
    normalized_improvement: float
    recent_improvement: float
    feasibility_rate: float
    score: float

    def json_summary(self) -> dict[str, Any]:
        return {
            "strategy": self.strategy,
            "observations": self.observations,
            "full_fidelity_observations": self.full_fidelity_observations,
            "reward_credit": self.reward_credit,
            "feasible_observations": self.feasible_observations,
            "normalized_improvement": self.normalized_improvement,
            "recent_improvement": self.recent_improvement,
            "feasibility_rate": self.feasibility_rate,
            "score": self.score,
        }


def _strategy_matches(observation: OptimizerObservation, strategy: str) -> bool:
    value = observation.optimizer_strategy or ""
    return value == strategy or value.endswith(f":{strategy}") or strategy in value.split("/")


def _portfolio_source_strategies(
    observation: OptimizerObservation,
) -> tuple[ExperimentalOptimizerStrategy, ...]:
    metadata = _optimizer_metadata(observation)
    verified = verified_observation_source_evidence(observation)
    if verified is not None:
        return tuple(source.child_strategy for source in verified.sources if source.materialized)
    if metadata.get(OPTIMIZER_SOURCE_EVIDENCE_REQUIRED_FIELD) is True:
        return ()
    if "portfolio_sources" not in metadata:
        return tuple(
            strategy for strategy in _CHILD_STRATEGIES if _strategy_matches(observation, strategy)
        )[:1]
    if metadata.get("portfolio_sources_schema") != _PORTFOLIO_SOURCES_SCHEMA:
        return ()
    raw_sources = metadata.get("portfolio_sources")
    if not isinstance(raw_sources, list | tuple):
        return ()
    strategies: list[ExperimentalOptimizerStrategy] = []
    for source in raw_sources:
        if not isinstance(source, Mapping) or source.get("materialized") is not True:
            continue
        raw_strategy = source.get("child_strategy")
        if raw_strategy not in _CHILD_STRATEGIES:
            return ()
        strategy = cast(ExperimentalOptimizerStrategy, raw_strategy)
        if strategy not in strategies:
            strategies.append(strategy)
    return tuple(strategies)


def _portfolio_source_credits(
    observation: OptimizerObservation,
) -> tuple[tuple[ExperimentalOptimizerStrategy, float], ...]:
    metadata = _optimizer_metadata(observation)
    verified = verified_observation_source_evidence(observation)
    if verified is not None:
        return tuple((credit.child_strategy, credit.share) for credit in verified.reward_credits)
    if metadata.get(OPTIMIZER_SOURCE_EVIDENCE_REQUIRED_FIELD) is True:
        return ()
    if "portfolio_source_credits" not in metadata:
        if not _reward_eligible(observation):
            return ()
        strategies = _portfolio_source_strategies(observation)
        return ((strategies[0], 1.0),) if len(strategies) == 1 else ()
    raw_credits = metadata.get("portfolio_source_credits")
    if not isinstance(raw_credits, list | tuple) or not raw_credits:
        return ()
    credits: list[tuple[ExperimentalOptimizerStrategy, float]] = []
    seen: set[str] = set()
    for item in raw_credits:
        if not isinstance(item, Mapping):
            return ()
        raw_strategy = item.get("child_strategy")
        raw_share = item.get("share")
        if (
            raw_strategy not in _CHILD_STRATEGIES
            or raw_strategy in seen
            or isinstance(raw_share, bool)
            or not isinstance(raw_share, int | float)
            or not math.isfinite(float(raw_share))
            or float(raw_share) <= 0.0
        ):
            return ()
        seen.add(str(raw_strategy))
        credits.append(
            (
                cast(ExperimentalOptimizerStrategy, raw_strategy),
                float(raw_share),
            )
        )
    if not math.isclose(
        sum(share for _strategy, share in credits),
        1.0,
        rel_tol=0.0,
        abs_tol=1e-9,
    ):
        return ()
    materialized = set(_portfolio_source_strategies(observation))
    if any(strategy not in materialized for strategy, _share in credits):
        return ()
    return tuple(credits)


def _optimizer_metadata(observation: OptimizerObservation) -> Mapping[str, Any]:
    metadata = observation.optimizer_metadata
    return metadata if isinstance(metadata, Mapping) else {}


def _reward_eligible(observation: OptimizerObservation) -> bool:
    metadata = _optimizer_metadata(observation)
    verified = verified_observation_source_evidence(observation)
    if verified is not None:
        return bool(verified.reward_credits)
    if metadata.get(OPTIMIZER_SOURCE_EVIDENCE_REQUIRED_FIELD) is True:
        return False
    explicit = metadata.get("portfolio_reward_eligible")
    if isinstance(explicit, bool):
        return explicit
    return str(metadata.get("optimizer_generated_by", "")) != "halton_fallback"


def _full_fidelity_observation(observation: OptimizerObservation) -> bool:
    return (
        observation.completed
        and observation.role in OPTIMIZER_LEARNING_OBSERVATION_ROLES
        and observation.fidelity >= 1.0 - 1e-9
        and observation.requested_fidelity >= 1.0 - 1e-9
    )


def _full_fidelity_reward_observation(observation: OptimizerObservation) -> bool:
    return _full_fidelity_observation(observation) and _reward_eligible(observation)


def _comparable_loss(observation: OptimizerObservation) -> float | None:
    if (
        not observation.feasible
        or observation.failure_rate >= OPTIMIZER_LEARNING_FAILURE_RATE_LIMIT
        or observation.loss is None
        or not math.isfinite(observation.loss)
    ):
        return None
    return float(observation.loss)


def _pre_generation_incumbents(
    observations: list[OptimizerObservation],
) -> dict[int, float | None]:
    """Freeze the best earlier loss before each generation starts."""

    by_generation: dict[int, list[OptimizerObservation]] = defaultdict(list)
    for observation in observations:
        by_generation[observation.generation_index].append(observation)
    incumbent: float | None = None
    result: dict[int, float | None] = {}
    for generation in sorted(by_generation):
        result[generation] = incumbent
        generation_losses = [
            loss
            for observation in by_generation[generation]
            if (loss := _comparable_loss(observation)) is not None
        ]
        if generation_losses:
            generation_best = min(generation_losses)
            incumbent = generation_best if incumbent is None else min(incumbent, generation_best)
    return result


def _attributed_improvement_statistics(
    entries: list[tuple[OptimizerObservation, float]],
    *,
    pre_generation_incumbents: Mapping[int, float | None],
) -> tuple[float, float]:
    """Return bounded fixed-scale reward with at most one credit per generation."""

    generation_rewards: dict[int, float] = {}
    for observation, share in entries:
        incumbent = pre_generation_incumbents.get(observation.generation_index)
        loss = _comparable_loss(observation)
        if incumbent is None or loss is None:
            reward = 0.0
        else:
            reward = (
                min(
                    1.0,
                    max(0.0, incumbent - loss) / PORTFOLIO_REWARD_SCALE,
                )
                * share
            )
        generation_rewards[observation.generation_index] = max(
            reward,
            generation_rewards.get(observation.generation_index, 0.0),
        )
    ordered = sorted(generation_rewards.items())
    if not ordered:
        return 0.0, 0.0
    total = min(1.0, sum(reward for _generation, reward in ordered))
    split = max(1, len(ordered) // 2)
    recent = min(
        1.0,
        sum(reward for _generation, reward in ordered[split:]),
    )
    return total, recent


def portfolio_statistics(request: OptimizerRequest) -> tuple[PortfolioStatistic, ...]:
    """Compute UCB-style utility from ownership metadata and measured progress."""

    grouped: dict[str, list[OptimizerObservation]] = defaultdict(list)
    credited: dict[
        str,
        list[tuple[OptimizerObservation, float]],
    ] = defaultdict(list)
    for observation in request.observations:
        for strategy in _portfolio_source_strategies(observation):
            grouped[strategy].append(observation)
        for strategy, share in _portfolio_source_credits(observation):
            credited[strategy].append((observation, share))
    reward_history = {
        strategy: [
            (item, share)
            for item, share in credited[strategy]
            if _full_fidelity_reward_observation(item)
        ]
        for strategy in _CHILD_STRATEGIES
    }
    global_comparable = [item for item in request.observations if _full_fidelity_observation(item)]
    pre_generation_incumbents = _pre_generation_incumbents(global_comparable)
    # Only completed full-fidelity evaluations are comparable enough to award
    # improvement credit. Lower-fidelity results still inform each child model
    # and the safety signal below, but cannot win portfolio budget by appearing
    # artificially better on a smaller scenario matrix.
    total_credit = sum(
        share for strategy in _CHILD_STRATEGIES for _item, share in reward_history[strategy]
    )
    statistics: list[PortfolioStatistic] = []
    for strategy in _CHILD_STRATEGIES:
        history = grouped[strategy]
        comparable_entries = reward_history[strategy]
        comparable_history = [item for item, _share in comparable_entries]
        reward_credit = sum(share for _item, share in comparable_entries)
        normalized, recent = _attributed_improvement_statistics(
            comparable_entries,
            pre_generation_incumbents=pre_generation_incumbents,
        )
        feasibility_rate = (
            sum(
                share
                * (item.feasible and item.failure_rate < OPTIMIZER_LEARNING_FAILURE_RATE_LIMIT)
                for item, share in comparable_entries
            )
            / reward_credit
            if reward_credit > 0.0
            else 0.5
        )
        # Improvement dominates.  The exploration bonus prevents an initially
        # unlucky algorithm from being permanently starved.
        exploration = math.sqrt(
            math.log(total_credit + len(_CHILD_STRATEGIES) + 1.0) / (reward_credit + 1.0)
        )
        cold_start = 0.35 if reward_credit <= 0.0 else 0.0
        score = (
            1.7 * normalized
            + 1.1 * recent
            + 0.25 * feasibility_rate
            + 0.65 * exploration
            + cold_start
        )
        statistics.append(
            PortfolioStatistic(
                strategy=strategy,
                observations=len(history),
                full_fidelity_observations=len(comparable_history),
                reward_credit=reward_credit,
                feasible_observations=sum(
                    item.feasible
                    and item.failure_rate < OPTIMIZER_LEARNING_FAILURE_RATE_LIMIT
                    and item.loss is not None
                    and math.isfinite(item.loss)
                    for item in comparable_history
                ),
                normalized_improvement=normalized,
                recent_improvement=recent,
                feasibility_rate=feasibility_rate,
                score=score,
            )
        )
    return tuple(statistics)


def _tie_value(request: OptimizerRequest, strategy: str) -> int:
    payload = (f"{request.random_seed}:{request.generation_index}:{strategy}:portfolio").encode()
    return int.from_bytes(hashlib.sha256(payload).digest()[:8], "big")


def _portfolio_plan(
    request: OptimizerRequest,
) -> tuple[
    dict[ExperimentalOptimizerStrategy, int],
    dict[ExperimentalOptimizerStrategy, list[str]],
]:
    if request.batch_size <= 0:
        return {}, {}
    statistics = portfolio_statistics(request)
    by_strategy = {item.strategy: item for item in statistics}
    allocations: dict[ExperimentalOptimizerStrategy, int] = {
        strategy: 0 for strategy in _CHILD_STRATEGIES
    }
    roles: dict[ExperimentalOptimizerStrategy, list[str]] = {
        strategy: [] for strategy in _CHILD_STRATEGIES
    }

    remaining = request.batch_size
    coverage_order = sorted(
        (
            strategy
            for strategy in _CHILD_STRATEGIES
            if by_strategy[strategy].full_fidelity_observations == 0
        ),
        key=lambda strategy: _tie_value(request, strategy),
    )
    for strategy in coverage_order[:remaining]:
        allocations[strategy] += 1
        roles[strategy].append("coverage")
        remaining -= 1

    if remaining > 0 and not coverage_order:
        if request.batch_size == 1:
            # A literal 20% slot cannot fit in a serial batch. Explore every
            # fifth warm generation and exploit on the other four.
            exploration_slots = int(request.generation_index % 5 == 0)
        else:
            # Round rather than ceil: batch 6 gets one exploration slot and
            # batch 8 gets two, staying close to 20% after cold-start coverage.
            exploration_slots = max(1, int(round(request.batch_size * 0.2)))
        exploration_slots = min(remaining, exploration_slots)
        exploration_order = sorted(
            _CHILD_STRATEGIES,
            key=lambda strategy: (
                by_strategy[strategy].full_fidelity_observations,
                _tie_value(request, strategy),
            ),
        )
        for strategy in exploration_order[:exploration_slots]:
            allocations[strategy] += 1
            roles[strategy].append("exploration")
            remaining -= 1

    while remaining > 0:
        selected = max(
            _CHILD_STRATEGIES,
            key=lambda strategy: (
                by_strategy[strategy].score
                + 0.35
                / math.sqrt(
                    by_strategy[strategy].full_fidelity_observations + allocations[strategy] + 1.0
                ),
                -_tie_value(request, strategy),
            ),
        )
        allocations[selected] += 1
        roles[selected].append("exploitation")
        remaining -= 1
    filtered = {strategy: count for strategy, count in allocations.items() if count > 0}
    return filtered, {strategy: roles[strategy] for strategy in filtered}


def portfolio_allocation(request: OptimizerRequest) -> dict[ExperimentalOptimizerStrategy, int]:
    """Allocate a batch by UCB reward while reserving explicit exploration."""

    allocation, _ = _portfolio_plan(request)
    return allocation


def _child_seed(request: OptimizerRequest, strategy: str) -> int:
    payload = (f"{request.random_seed}:{request.generation_index}:{strategy}:child").encode()
    return int.from_bytes(hashlib.sha256(payload).digest()[:8], "big")


def _seed_hex(value: int) -> str:
    """Serialize RNG provenance without exceeding JavaScript's safe integer range."""

    return f"{int(value) & 0xFFFFFFFFFFFFFFFF:016x}"


def _seeded_random_fallback_design(
    search_space: SearchSpace,
    count: int,
    *,
    seed: int,
    excluded: set[tuple[float, ...]],
) -> list[dict[str, float]]:
    """Build a deterministic, validity-aware design beyond Halton's dimension cap."""

    if count <= 0:
        return []
    rng = random.Random(seed)  # noqa: S311 - deterministic optimizer RNG
    dimensions = len(search_space.tunable)
    seen = set(excluded)
    candidates: list[dict[str, float]] = []
    # Coupled PX4 constraints can reject a substantial part of the rectangular
    # unit cube. Keep trying deterministically, while retaining a hard bound for
    # impossible or very small discrete domains.
    max_attempts = max(2_048, count * 200)
    attempts = 0
    while len(candidates) < count and attempts < max_attempts:
        vector = [rng.random() for _ in range(dimensions)]
        attempts += 1
        try:
            candidate = search_space.from_unit_vector(vector)
        except ValueError:
            continue
        key = tuple(search_space.to_unit_vector(candidate))
        if key in seen:
            continue
        seen.add(key)
        candidates.append(candidate)
    return candidates


def _fallback_candidates(
    search_space: SearchSpace,
    request: OptimizerRequest,
    strategy: ExperimentalOptimizerStrategy,
    count: int,
    *,
    excluded: set[tuple[float, ...]] | None = None,
) -> list[ExperimentalProposal]:
    """Deterministic child-owned recovery path for missing/collapsed proposals."""

    seed_offset = (
        int.from_bytes(
            hashlib.sha256(
                f"{request.random_seed}:{request.generation_index}:{strategy}:fallback".encode()
            ).digest()[:4],
            "big",
        )
        % 100_003
    )
    start = 1 + request.generation_index * 97 + _CHILD_STRATEGIES.index(strategy) * 17 + seed_offset
    existing = {
        tuple(search_space.to_unit_vector(item.parameters))
        for item in request.observations
        if item.parameters
        and item.requested_fidelity >= 1.0 - 1e-9
        and item.fidelity >= 1.0 - 1e-9
    }
    existing.update(excluded or set())
    design_count = max(64, count * 16, count + len(existing) * 2)
    if len(search_space.tunable) <= MAX_HALTON_DIMENSIONS:
        candidates = halton_design(
            search_space,
            design_count,
            start_index=start,
            include_baseline=False,
        )
        generated_by = "halton_fallback"
        backend = "halton_emergency_fallback"
    else:
        fallback_seed = _child_seed(request, strategy) ^ int.from_bytes(
            hashlib.sha256(
                f"{request.random_seed}:{request.generation_index}:{strategy}:random-fallback".encode()
            ).digest()[:8],
            "big",
        )
        candidates = _seeded_random_fallback_design(
            search_space,
            design_count,
            seed=fallback_seed,
            excluded=existing,
        )
        generated_by = "seeded_random_fallback"
        backend = "seeded_random_emergency_fallback"
    proposals: list[ExperimentalProposal] = []
    for candidate in candidates:
        key = tuple(search_space.to_unit_vector(candidate))
        if key in existing:
            continue
        existing.add(key)
        proposals.append(
            ExperimentalProposal(
                label=(
                    f"portfolio_{strategy}_fallback_g{request.generation_index}_"
                    f"{len(proposals) + 1}"
                ),
                parameters=candidate,
                rationale=f"Deterministic portfolio fallback for unavailable {strategy} backend",
                metadata={
                    "strategy": "optimizer_portfolio",
                    "child_strategy": strategy,
                    "optimizer_generated_by": generated_by,
                    "optimizer_update_eligible": False,
                    "portfolio_reward_eligible": False,
                    "portfolio_slot_role": "fallback",
                    "fidelity": 1.0,
                    "requested_fidelity": 1.0,
                    "effective_fidelity": 1.0,
                    "backend": backend,
                },
            )
        )
        if len(proposals) >= count:
            break
    return proposals


def _delegate(
    search_space: SearchSpace,
    request: OptimizerRequest,
    strategy: ExperimentalOptimizerStrategy,
    count: int,
) -> list[ExperimentalProposal]:
    child_request = replace(
        request,
        strategy=strategy,
        batch_size=count,
        random_seed=_child_seed(request, strategy),
    )
    if strategy in _BAYESIAN_STRATEGIES:
        try:
            from app.optimization.bayesian_optimizers import propose_bayesian_candidates
        except ImportError:
            return _fallback_candidates(search_space, request, strategy, count)
        return propose_bayesian_candidates(search_space, child_request)

    from app.optimization.cma_optimizers import propose_evolutionary_candidates

    return propose_evolutionary_candidates(search_space, child_request)


def _source_entry(
    metadata: Mapping[str, Any],
    *,
    strategy: ExperimentalOptimizerStrategy,
    planned_role: str,
    effective_fidelity: float,
    requested_fidelity: float,
) -> dict[str, Any]:
    generated_by = str(metadata.get("optimizer_generated_by", strategy))
    source_role = classify_optimizer_source_role(strategy, generated_by)
    return {
        "child_strategy": strategy,
        "source_role": source_role,
        "generated_by": generated_by,
        "planned_slot_role": planned_role,
        "effective_fidelity": effective_fidelity,
        "requested_fidelity": requested_fidelity,
        "materialized": True,
        "reward_eligible": source_role == "native_optimizer",
        "exclusion_reason": None,
    }


def _with_portfolio_sources(
    metadata: Mapping[str, Any],
    sources: list[dict[str, Any]],
) -> dict[str, Any]:
    # Same-tool duplicates collapse to one source so a child cannot multiply
    # its credit by returning the same action more than once.
    by_strategy: dict[str, dict[str, Any]] = {}
    for source in sources:
        raw_strategy = source.get("child_strategy")
        if raw_strategy not in _CHILD_STRATEGIES:
            continue
        strategy_key = str(raw_strategy)
        current = by_strategy.get(strategy_key)
        candidate_priority = (
            source.get("materialized") is True,
            source.get("reward_eligible") is True,
            source.get("exclusion_reason") is None,
        )
        current_priority = (
            (
                current.get("materialized") is True,
                current.get("reward_eligible") is True,
                current.get("exclusion_reason") is None,
            )
            if current is not None
            else (False, False, False)
        )
        if current is None or candidate_priority > current_priority:
            by_strategy[strategy_key] = dict(source)
    ordered = [by_strategy[strategy] for strategy in _CHILD_STRATEGIES if strategy in by_strategy]
    credited_strategies = [
        cast(ExperimentalOptimizerStrategy, source["child_strategy"])
        for source in ordered
        if source.get("materialized") is True
        and source.get("reward_eligible") is True
        and source.get("exclusion_reason") is None
    ]
    share = 1.0 / len(credited_strategies) if credited_strategies else 0.0
    return {
        **metadata,
        "portfolio_sources_schema": _PORTFOLIO_SOURCES_SCHEMA,
        "portfolio_sources": ordered,
        "portfolio_source_credits": [
            {
                "child_strategy": strategy,
                "share": share,
            }
            for strategy in credited_strategies
        ],
    }


def _excluded_sources(
    sources: list[dict[str, Any]],
    *,
    reason: str,
) -> list[dict[str, Any]]:
    return [
        {
            **source,
            "materialized": False,
            "reward_eligible": False,
            "exclusion_reason": reason,
        }
        for source in sources
    ]


def propose_optimizer_portfolio(
    search_space: SearchSpace,
    request: OptimizerRequest,
) -> list[ExperimentalProposal]:
    """Propose candidates from the adaptive six-algorithm portfolio."""

    if request.strategy != "optimizer_portfolio":
        raise ValueError("portfolio request must use strategy='optimizer_portfolio'")
    if request.batch_size <= 0:
        return []
    allocation = portfolio_allocation(request)
    default_allocation, default_roles = _portfolio_plan(request)
    if allocation == default_allocation:
        planned_roles = default_roles
    else:
        planned_roles = {
            strategy: ["externally_planned"] * count for strategy, count in allocation.items()
        }
    statistics = {item.strategy: item for item in portfolio_statistics(request)}
    proposals: list[ExperimentalProposal] = []
    historical_seen: set[tuple[tuple[float, ...], float, bool]] = {
        (
            tuple(search_space.to_unit_vector(item.parameters)),
            round(float(item.fidelity), 12),
            item.requested_fidelity >= 1.0 - 1e-9,
        )
        for item in request.observations
        if item.parameters
    }
    batch_proposal_index: dict[tuple[float, ...], int] = {}
    realized: dict[ExperimentalOptimizerStrategy, int] = {
        strategy: 0 for strategy in _CHILD_STRATEGIES
    }

    def wrap(
        child: ExperimentalProposal,
        strategy: ExperimentalOptimizerStrategy,
        planned_role: str,
    ) -> ExperimentalProposal | None:
        try:
            projected = search_space.project(child.parameters)
        except ValueError:
            return None
        metadata = dict(child.metadata)
        effective_fidelity = float(
            metadata.get("effective_fidelity", metadata.get("fidelity", 1.0))
        )
        requested_fidelity = float(metadata.get("requested_fidelity", effective_fidelity))
        generated_by = str(metadata.get("optimizer_generated_by", strategy))
        source_role = classify_optimizer_source_role(strategy, generated_by)
        actual_role = (
            "fallback"
            if source_role == "emergency_fallback"
            else str(metadata.get("portfolio_slot_role", planned_role))
        )
        metadata.update(
            {
                "strategy": "optimizer_portfolio",
                "child_strategy": strategy,
                "optimizer_generated_by": generated_by,
                "optimizer_source_role": source_role,
                "optimizer_update_eligible": source_role == "native_optimizer",
                "portfolio_reward_eligible": source_role == "native_optimizer",
                "portfolio_slot_role": actual_role,
                "portfolio_planned_slot_role": planned_role,
                "fidelity": effective_fidelity,
                "effective_fidelity": effective_fidelity,
                "requested_fidelity": requested_fidelity,
                "backend": str(metadata.get("backend", "unknown_child_backend")),
                "portfolio_random_seed": _seed_hex(request.random_seed),
                "child_random_seed": _seed_hex(_child_seed(request, strategy)),
                "portfolio_planned_allocation": dict(allocation),
                "portfolio_statistic": statistics[strategy].json_summary(),
                "exploration_retained": actual_role in {"coverage", "exploration"},
            }
        )
        metadata = _with_portfolio_sources(
            metadata,
            [
                _source_entry(
                    metadata,
                    strategy=strategy,
                    planned_role=planned_role,
                    effective_fidelity=effective_fidelity,
                    requested_fidelity=requested_fidelity,
                )
            ],
        )
        return ExperimentalProposal(
            label=f"portfolio_{strategy}_{child.label}",
            parameters=projected,
            rationale=f"Portfolio allocation to {strategy}: {child.rationale}",
            metadata=metadata,
        )

    def try_add(proposal: ExperimentalProposal) -> bool:
        vector_key = tuple(search_space.to_unit_vector(proposal.parameters))
        effective_fidelity = float(proposal.metadata.get("fidelity", 1.0))
        requested_fidelity = float(proposal.metadata.get("requested_fidelity", effective_fidelity))
        identity = (
            vector_key,
            round(effective_fidelity, 12),
            requested_fidelity >= 1.0 - 1e-9,
        )
        if identity in historical_seen:
            return False
        strategy = _child_strategy_from_metadata(proposal.metadata)
        existing_index = batch_proposal_index.get(vector_key)
        if existing_index is not None:
            existing = proposals[existing_index]
            existing_effective = float(existing.metadata.get("effective_fidelity", 1.0))
            existing_requested = float(
                existing.metadata.get(
                    "requested_fidelity",
                    existing.metadata.get("fidelity", 1.0),
                )
            )
            existing_sources = [
                dict(source)
                for source in existing.metadata.get("portfolio_sources", [])
                if isinstance(source, Mapping)
            ]
            proposal_sources = [
                dict(source)
                for source in proposal.metadata.get("portfolio_sources", [])
                if isinstance(source, Mapping)
            ]
            new_priority = (
                requested_fidelity >= 1.0 - 1e-9,
                round(effective_fidelity, 12),
                round(requested_fidelity, 12),
            )
            existing_priority = (
                existing_requested >= 1.0 - 1e-9,
                round(existing_effective, 12),
                round(existing_requested, 12),
            )
            if new_priority == existing_priority:
                existing_strategy = _child_strategy_from_metadata(existing.metadata)
                existing_is_native = any(
                    source.get("child_strategy") == existing_strategy
                    and source.get("source_role") == "native_optimizer"
                    and source.get("materialized") is True
                    for source in existing_sources
                )
                proposal_is_native = any(
                    source.get("child_strategy") == strategy
                    and source.get("source_role") == "native_optimizer"
                    and source.get("materialized") is True
                    for source in proposal_sources
                )
                # Exact action collisions retain every source for reward
                # attribution, but child-local state must come from a native
                # optimizer whenever one exists.  Keeping a fallback envelope
                # merely because it arrived first can leave an eligible native
                # source without a learning owner and abort the generation.
                if proposal_is_native and not existing_is_native:
                    merged_base = proposal
                    merged_sources = [*existing_sources, *proposal_sources]
                    if existing_strategy != strategy:
                        realized[existing_strategy] -= 1
                        realized[strategy] += 1
                else:
                    merged_base = existing
                    merged_sources = [*existing_sources, *proposal_sources]
                proposals[existing_index] = replace(
                    merged_base,
                    rationale=(
                        f"{existing.rationale} Exact action independently proposed by {strategy}."
                    ),
                    metadata=_with_portfolio_sources(
                        merged_base.metadata,
                        merged_sources,
                    ),
                )
                return False
            if new_priority < existing_priority:
                proposals[existing_index] = replace(
                    existing,
                    metadata=_with_portfolio_sources(
                        existing.metadata,
                        [
                            *existing_sources,
                            *_excluded_sources(
                                proposal_sources,
                                reason="lower_fidelity_collision",
                            ),
                        ],
                    ),
                )
                return False
            previous_strategy = _child_strategy_from_metadata(existing.metadata)
            realized[previous_strategy] -= 1
            proposals[existing_index] = replace(
                proposal,
                metadata=_with_portfolio_sources(
                    proposal.metadata,
                    [
                        *_excluded_sources(
                            existing_sources,
                            reason="superseded_by_higher_fidelity",
                        ),
                        *proposal_sources,
                    ],
                ),
            )
        else:
            batch_proposal_index[vector_key] = len(proposals)
            proposals.append(proposal)
        realized[strategy] += 1
        return True

    for strategy in _CHILD_STRATEGIES:
        count = allocation.get(strategy, 0)
        if count <= 0:
            continue
        # Ask for exactly the awarded budget. Projected collisions are handled
        # below by the explicitly ineligible recovery path; silently inflating
        # a child request wastes model evaluations and makes CMA ask accounting
        # disagree with the portfolio allocation.
        children = _delegate(
            search_space,
            request,
            strategy,
            count,
        )
        for child in children:
            role_index = min(realized[strategy], len(planned_roles[strategy]) - 1)
            wrapped = wrap(child, strategy, planned_roles[strategy][role_index])
            if wrapped is None:
                continue
            try_add(wrapped)
            if realized[strategy] >= count:
                break

    # Preserve the planned child coverage after any low-to-full-fidelity
    # replacement.  Recovery remains owned by the child that lost the slot.
    for strategy in _CHILD_STRATEGIES:
        deficit = allocation.get(strategy, 0) - realized[strategy]
        if deficit <= 0:
            continue
        fallbacks = _fallback_candidates(
            search_space,
            request,
            strategy,
            deficit,
            excluded=set(batch_proposal_index),
        )
        for fallback in fallbacks:
            role_index = min(realized[strategy], len(planned_roles[strategy]) - 1)
            wrapped = wrap(fallback, strategy, planned_roles[strategy][role_index])
            if wrapped is None:
                continue
            try_add(wrapped)

    if len(proposals) < request.batch_size:
        # If a child genuinely exhausts a tiny discrete domain, give the spare
        # slots to the strongest current statistic while retaining ownership.
        fallback_strategy = max(statistics.values(), key=lambda item: item.score).strategy
        fallbacks = _fallback_candidates(
            search_space,
            request,
            fallback_strategy,
            request.batch_size - len(proposals),
            excluded=set(batch_proposal_index),
        )
        for fallback in fallbacks:
            role_index = min(
                realized[fallback_strategy],
                len(planned_roles.get(fallback_strategy, ["reallocated"])) - 1,
            )
            role_choices = planned_roles.get(fallback_strategy, ["reallocated"])
            wrapped = wrap(fallback, fallback_strategy, role_choices[role_index])
            if wrapped is not None:
                try_add(wrapped)

    realized_allocation = {strategy: count for strategy, count in realized.items() if count > 0}
    return [
        replace(
            proposal,
            metadata={
                **proposal.metadata,
                "portfolio_allocation": realized_allocation,
            },
        )
        for proposal in proposals[: request.batch_size]
    ]


__all__ = [
    "PortfolioStatistic",
    "portfolio_allocation",
    "portfolio_statistics",
    "propose_optimizer_portfolio",
]
