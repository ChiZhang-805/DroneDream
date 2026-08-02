"""Repeatable synthetic smoke benchmark for DroneDream's seven optimizers.

This deliberately does *not* estimate real PX4/Gazebo performance.  It gives
every optimizer the same mixed feasible/failed history, constrained objectives,
evaluation budget, and deterministic seed so numerical regressions can be
compared cheaply before an expensive simulator campaign.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, cast

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.optimization.bayesian_optimizers import (  # noqa: E402
    propose_bayesian_candidates,
)
from app.optimization.cma_optimizers import (  # noqa: E402
    propose_evolutionary_candidates,
)
from app.optimization.domain import ParameterDomain, SearchSpace  # noqa: E402
from app.optimization.experimental_types import (  # noqa: E402
    EXPERIMENTAL_OPTIMIZER_STRATEGIES,
    ExperimentalOptimizerStrategy,
    OptimizerObservation,
    OptimizerRequest,
)

_BAYESIAN = {"constrained_mobo", "multi_fidelity_mobo", "turbo", "saasbo"}
_INITIAL_POINTS = (
    (0.50, 0.50, 0.50, 0.50),
    (0.15, 0.25, 0.75, 0.35),
    (0.85, 0.20, 0.30, 0.70),
    (0.30, 0.80, 0.20, 0.60),
    (0.70, 0.65, 0.55, 0.15),
    (0.45, 0.10, 0.90, 0.80),
    # Two deterministic simulator-failure analogues.  Their loss is absent,
    # while constraint and failure feedback remain available to every policy.
    (0.95, 0.70, 0.10, 0.40),
    (0.20, 0.45, 0.45, 0.98),
)


@dataclass(frozen=True)
class StrategyResult:
    strategy: str
    rank: int
    evaluations: int
    full_fidelity_evaluations: int
    feasible_evaluations: int
    failed_evaluations: int
    best_feasible_loss: float
    oracle_best_queried_loss: float
    initial_best_feasible_loss: float
    improvement: float
    effective_fidelity_cost: float
    best_parameters: dict[str, float]


def _search_space() -> SearchSpace:
    return SearchSpace(
        (
            ParameterDomain("kp_xy", 1.5, 0.5, 2.5),
            ParameterDomain("kd_xy", 0.3, 0.05, 1.0),
            ParameterDomain("ki_xy", 0.08, 0.0, 0.3),
            ParameterDomain("vel_limit", 5.0, 2.0, 8.0),
        )
    )


def _truth(unit: tuple[float, ...]) -> tuple[dict[str, float], dict[str, float], bool]:
    u0, u1, u2, u3 = unit
    tracking = (
        2.0 * (u0 - 0.67) ** 2
        + 1.4 * (u1 - 0.31) ** 2
        + 0.8 * (u2 - 0.58) ** 2
        + 0.7 * (u3 - 0.46) ** 2
        + 0.35 * (u1 - u0 * (1.0 - u0)) ** 2
    )
    energy = (
        0.9 * (u0 - 0.42) ** 2
        + 0.5 * (u1 - 0.55) ** 2
        + 0.4 * (u2 - 0.35) ** 2
        + 1.2 * (u3 - 0.30) ** 2
    )
    raw_constraints = {
        # Canonical form is <= 0.  The optimizer consumes the explicit
        # direction-aware feasible flag and retains raw margins for diagnostics.
        "stability_margin": u0 + 0.85 * u1 - 1.28,
        "control_authority": 0.56 - (u0 + 0.55 * u2),
    }
    hard_failure = raw_constraints["stability_margin"] > 0.16 or u3 > 0.94
    return {"tracking": tracking, "energy": energy}, raw_constraints, hard_failure


def _evaluate(
    space: SearchSpace,
    parameters: dict[str, float],
    *,
    candidate_id: str,
    generation: int,
    fidelity: float,
    optimizer_strategy: str | None,
    requested_fidelity: float | None = None,
    optimizer_metadata: dict[str, Any] | None = None,
) -> OptimizerObservation:
    projected = space.project(parameters)
    unit = space.to_unit_vector(projected)
    true_objectives, raw_constraints, hard_failure = _truth(unit)
    fidelity = max(0.05, min(1.0, float(fidelity)))
    requested_fidelity = max(
        0.05,
        min(1.0, float(fidelity if requested_fidelity is None else requested_fidelity)),
    )
    bias = (1.0 - fidelity) * (
        0.035
        + 0.025 * math.sin(7.0 * unit[0] + 3.0 * unit[2])
        + 0.015 * math.cos(5.0 * unit[1] - 2.0 * unit[3])
    )
    objectives = {
        "tracking": max(0.0, true_objectives["tracking"] + bias),
        "energy": max(0.0, true_objectives["energy"] + 0.5 * bias),
    }
    feasible = not hard_failure and all(value <= 0.0 for value in raw_constraints.values())
    constraint_violations = {
        name: max(0.0, value) for name, value in raw_constraints.items()
    }
    loss = None if hard_failure else objectives["tracking"] + 0.25 * objectives["energy"]
    return OptimizerObservation(
        candidate_id=candidate_id,
        generation_index=generation,
        parameters=projected,
        unit_vector=unit,
        loss=loss,
        objectives=objectives if loss is not None else {},
        objective_directions={"tracking": "minimize", "energy": "minimize"},
        constraints=constraint_violations,
        feasible=feasible,
        failure_rate=1.0 if hard_failure else 0.0,
        fidelity=fidelity,
        requested_fidelity=requested_fidelity,
        optimizer_strategy=optimizer_strategy,
        optimizer_metadata=optimizer_metadata or {},
        completed=True,
    )


def _initial_observations(space: SearchSpace) -> list[OptimizerObservation]:
    return [
        _evaluate(
            space,
            space.from_unit_vector(point),
            candidate_id=f"initial-{index}",
            generation=0,
            fidelity=1.0,
            requested_fidelity=1.0,
            optimizer_strategy=None,
        )
        for index, point in enumerate(_INITIAL_POINTS)
    ]


def _full_fidelity_loss(observation: OptimizerObservation) -> float | None:
    objectives, constraints, hard_failure = _truth(observation.unit_vector)
    if hard_failure or any(value > 0.0 for value in constraints.values()):
        return None
    return objectives["tracking"] + 0.25 * objectives["energy"]


def _run_strategy(
    strategy: ExperimentalOptimizerStrategy,
    *,
    generations: int,
    batch_size: int,
    seed: int,
) -> dict[str, Any]:
    space = _search_space()
    observations = _initial_observations(space)
    initial_best = min(
        loss for item in observations if (loss := _full_fidelity_loss(item)) is not None
    )
    for generation in range(1, generations + 1):
        request = OptimizerRequest(
            strategy=strategy,
            generation_index=generation,
            batch_size=batch_size,
            random_seed=seed + 1009 * generation,
            observations=tuple(observations),
        )
        proposals = (
            propose_bayesian_candidates(space, request)
            if strategy in _BAYESIAN
            else propose_evolutionary_candidates(space, request)
        )
        for index, proposal in enumerate(proposals):
            fidelity = float(
                proposal.metadata.get(
                    "effective_fidelity",
                    proposal.metadata.get("fidelity", 1.0),
                )
            )
            requested_fidelity = float(
                proposal.metadata.get("requested_fidelity", fidelity)
            )
            child_strategy = str(proposal.metadata.get("child_strategy") or strategy)
            observations.append(
                _evaluate(
                    space,
                    proposal.parameters,
                    candidate_id=f"{strategy}-g{generation}-{index}",
                    generation=generation,
                    fidelity=fidelity,
                    requested_fidelity=requested_fidelity,
                    optimizer_strategy=child_strategy,
                    optimizer_metadata=dict(proposal.metadata),
                )
            )

    evaluated = [item for item in observations if item.generation_index > 0]
    verified_losses = [
        (float(item.loss), item)
        for item in observations
        if item.requested_fidelity >= 1.0 - 1e-12
        and item.fidelity >= 1.0 - 1e-12
        and item.feasible
        and item.loss is not None
        and math.isfinite(item.loss)
    ]
    best_loss, best_observation = min(verified_losses, key=lambda item: item[0])
    oracle_losses = [
        loss
        for item in observations
        if (loss := _full_fidelity_loss(item)) is not None
    ]
    return {
        "strategy": strategy,
        "evaluations": len(evaluated),
        "full_fidelity_evaluations": sum(
            item.requested_fidelity >= 1.0 - 1e-12
            and math.isclose(item.fidelity, 1.0, abs_tol=1e-12)
            for item in evaluated
        ),
        "feasible_evaluations": sum(item.feasible for item in evaluated),
        "failed_evaluations": sum(item.loss is None for item in evaluated),
        "best_feasible_loss": round(best_loss, 12),
        "oracle_best_queried_loss": round(min(oracle_losses), 12),
        "initial_best_feasible_loss": round(initial_best, 12),
        "improvement": round(initial_best - best_loss, 12),
        "effective_fidelity_cost": round(sum(item.fidelity for item in evaluated), 12),
        "best_parameters": best_observation.parameters,
    }


def run_benchmark(
    *,
    strategies: tuple[str, ...] = EXPERIMENTAL_OPTIMIZER_STRATEGIES,
    generations: int = 3,
    batch_size: int = 3,
    seed: int = 805,
) -> dict[str, Any]:
    """Run the deterministic synthetic campaign and return JSON-safe results."""

    if generations < 1 or batch_size < 1:
        raise ValueError("generations and batch_size must both be positive")
    unknown = set(strategies).difference(EXPERIMENTAL_OPTIMIZER_STRATEGIES)
    if unknown:
        raise ValueError(f"unsupported strategies: {', '.join(sorted(unknown))}")
    if len(set(strategies)) != len(strategies):
        raise ValueError("strategies must not contain duplicates")

    common_initial = _initial_observations(_search_space())
    raw = [
        _run_strategy(
            cast(ExperimentalOptimizerStrategy, strategy),
            generations=generations,
            batch_size=batch_size,
            seed=seed,
        )
        for strategy in strategies
    ]
    ordered = sorted(raw, key=lambda item: (item["best_feasible_loss"], item["strategy"]))
    results = [
        asdict(StrategyResult(rank=rank, **item)) for rank, item in enumerate(ordered, start=1)
    ]
    digest_payload = json.dumps(results, sort_keys=True, separators=(",", ":"))
    return {
        "benchmark": "dronedream-constrained-synthetic-v1",
        "purpose": "deterministic numerical regression smoke test",
        "warning": "Synthetic scores are not PX4/Gazebo or real-flight rankings.",
        "seed": seed,
        "generations": generations,
        "batch_size": batch_size,
        "initial_observations": len(_INITIAL_POINTS),
        "initial_failed_observations": sum(
            observation.loss is None for observation in common_initial
        ),
        "feedback_contract": {
            "loss_direction": "minimize",
            "objectives": {"tracking": "minimize", "energy": "minimize"},
            "constraint_convention": (
                "direction-aware violation margins are non-negative; "
                "feasible when every violation is zero"
            ),
            "failed_observations_keep_constraints": True,
        },
        "result_digest": hashlib.sha256(digest_payload.encode("utf-8")).hexdigest(),
        "results": results,
    }


def write_new_benchmark_result(path: Path, payload: str) -> None:
    """Publish one benchmark result without replacing an earlier run."""

    path = path.resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    created = False
    try:
        with path.open("x", encoding="utf-8", newline="\n") as handle:
            created = True
            handle.write(payload)
    except FileExistsError as exc:
        raise ValueError(f"benchmark output already exists: {path}") from exc
    except Exception:
        if created:
            path.unlink(missing_ok=True)
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--generations", type=int, default=3)
    parser.add_argument("--batch-size", type=int, default=3)
    parser.add_argument("--seed", type=int, default=805)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = run_benchmark(
        generations=args.generations,
        batch_size=args.batch_size,
        seed=args.seed,
    )
    payload = json.dumps(result, indent=2, ensure_ascii=False, sort_keys=True) + "\n"
    if args.output is not None:
        write_new_benchmark_result(args.output, payload)
    else:
        print(payload, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
