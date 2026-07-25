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
    ExperimentalOptimizerStrategy,
    ExperimentalProposal,
    OptimizerObservation,
    OptimizerRequest,
)
from app.optimization.outcome_contract import (
    OPTIMIZER_LEARNING_FAILURE_RATE_LIMIT,
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
            "feasible_observations": self.feasible_observations,
            "normalized_improvement": self.normalized_improvement,
            "recent_improvement": self.recent_improvement,
            "feasibility_rate": self.feasibility_rate,
            "score": self.score,
        }


def _strategy_matches(observation: OptimizerObservation, strategy: str) -> bool:
    value = observation.optimizer_strategy or ""
    return value == strategy or value.endswith(f":{strategy}") or strategy in value.split("/")


def _optimizer_metadata(observation: OptimizerObservation) -> Mapping[str, Any]:
    metadata = observation.optimizer_metadata
    return metadata if isinstance(metadata, Mapping) else {}


def _reward_eligible(observation: OptimizerObservation) -> bool:
    metadata = _optimizer_metadata(observation)
    explicit = metadata.get("portfolio_reward_eligible")
    if isinstance(explicit, bool):
        return explicit
    return str(metadata.get("optimizer_generated_by", "")) != "halton_fallback"


def _full_fidelity_reward_observation(observation: OptimizerObservation) -> bool:
    return (
        observation.completed
        and observation.requested_fidelity >= 1.0 - 1e-9
        and _reward_eligible(observation)
    )


def _finite_feasible_generation_losses(
    observations: list[OptimizerObservation],
) -> list[tuple[int, float]]:
    """Return one best comparable loss per optimizer generation."""

    generation_best: dict[int, float] = {}
    for item in observations:
        if (
            not item.feasible
            or item.failure_rate
            >= OPTIMIZER_LEARNING_FAILURE_RATE_LIMIT
            or item.loss is None
            or not math.isfinite(item.loss)
        ):
            continue
        loss = float(item.loss)
        generation_best[item.generation_index] = min(
            loss,
            generation_best.get(item.generation_index, math.inf),
        )
    return sorted(generation_best.items())


def _improvement_statistics(
    losses: list[tuple[int, float]],
    *,
    common_baseline: float | None,
) -> tuple[float, float]:
    if not losses or common_baseline is None or not math.isfinite(common_baseline):
        return 0.0, 0.0
    best = min(item[1] for item in losses)
    scale = max(1e-9, abs(common_baseline), abs(best))
    normalized = max(0.0, common_baseline - best) / scale

    split = max(1, len(losses) // 2)
    earlier_best = min(common_baseline, *(item[1] for item in losses[:split]))
    recent_rows = losses[split:]
    if not recent_rows:
        return normalized, 0.0
    recent_best = min(item[1] for item in recent_rows)
    recent_scale = max(1e-9, abs(earlier_best), abs(recent_best))
    recent = max(0.0, earlier_best - recent_best) / recent_scale
    return normalized, recent


def portfolio_statistics(request: OptimizerRequest) -> tuple[PortfolioStatistic, ...]:
    """Compute UCB-style utility from ownership metadata and measured progress."""

    grouped: dict[str, list[OptimizerObservation]] = defaultdict(list)
    for observation in request.observations:
        for strategy in _CHILD_STRATEGIES:
            if _strategy_matches(observation, strategy):
                grouped[strategy].append(observation)
                break
    reward_history = {
        strategy: [item for item in grouped[strategy] if _full_fidelity_reward_observation(item)]
        for strategy in _CHILD_STRATEGIES
    }
    global_comparable = [
        item for item in request.observations if _full_fidelity_reward_observation(item)
    ]
    global_losses = _finite_feasible_generation_losses(global_comparable)
    common_baseline = global_losses[0][1] if global_losses else None
    # Only completed full-fidelity evaluations are comparable enough to award
    # improvement credit. Lower-fidelity results still inform each child model
    # and the safety signal below, but cannot win portfolio budget by appearing
    # artificially better on a smaller scenario matrix.
    total = sum(len(reward_history[strategy]) for strategy in _CHILD_STRATEGIES)
    statistics: list[PortfolioStatistic] = []
    for strategy in _CHILD_STRATEGIES:
        history = grouped[strategy]
        comparable_history = reward_history[strategy]
        losses = _finite_feasible_generation_losses(comparable_history)
        normalized, recent = _improvement_statistics(
            losses,
            common_baseline=common_baseline,
        )
        feasibility_rate = (
            sum(
                item.feasible
                and item.failure_rate
                < OPTIMIZER_LEARNING_FAILURE_RATE_LIMIT
                for item in comparable_history
            )
            / len(comparable_history)
            if comparable_history
            else 0.5
        )
        # Improvement dominates.  The exploration bonus prevents an initially
        # unlucky algorithm from being permanently starved.
        exploration = math.sqrt(
            math.log(total + len(_CHILD_STRATEGIES) + 1.0) / (len(comparable_history) + 1.0)
        )
        cold_start = 0.35 if not comparable_history else 0.0
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
                feasible_observations=sum(
                    item.feasible
                    and item.failure_rate
                    < OPTIMIZER_LEARNING_FAILURE_RATE_LIMIT
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
        if item.parameters and item.requested_fidelity >= 1.0 - 1e-9
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
        actual_role = (
            "fallback"
            if generated_by == "halton_fallback"
            else str(metadata.get("portfolio_slot_role", planned_role))
        )
        metadata.update(
            {
                "strategy": "optimizer_portfolio",
                "child_strategy": strategy,
                "optimizer_generated_by": generated_by,
                "optimizer_update_eligible": bool(metadata.get("optimizer_update_eligible", True)),
                "portfolio_reward_eligible": bool(metadata.get("portfolio_reward_eligible", True)),
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
            existing_requested = float(
                existing.metadata.get(
                    "requested_fidelity",
                    existing.metadata.get("fidelity", 1.0),
                )
            )
            if requested_fidelity <= existing_requested + 1e-9:
                return False
            previous_strategy = _child_strategy_from_metadata(existing.metadata)
            realized[previous_strategy] -= 1
            proposals[existing_index] = proposal
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
