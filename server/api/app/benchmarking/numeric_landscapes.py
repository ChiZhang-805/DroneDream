"""Cheap deterministic landscapes for fair proposal-adapter regressions.

These evaluators are engineering gates only.  Their outputs are never evidence
of PX4/Gazebo performance or flight-controller quality.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Final, Literal

from app.benchmarking.contracts import (
    BENCHMARK_EVALUATOR_CONTRACT_ID,
    BenchmarkEvaluationV1,
    BenchmarkProposalV1,
    canonical_sha256,
)
from app.optimization.domain import SearchSpace

NUMERIC_LANDSCAPE_ID: Final = "dronedream.constrained-numeric-landscape/v1"


@dataclass(frozen=True, slots=True)
class DeterministicConstrainedLandscapeV1:
    """One bounded multi-objective landscape with failures and constraints."""

    search_space: SearchSpace
    evaluator_contract_id: str = BENCHMARK_EVALUATOR_CONTRACT_ID
    landscape_id: str = NUMERIC_LANDSCAPE_ID

    def evaluate(self, proposal: BenchmarkProposalV1) -> BenchmarkEvaluationV1:
        expected_names = {domain.name for domain in self.search_space.domains}
        received_names = set(proposal.parameters)
        if received_names != expected_names:
            missing = sorted(expected_names - received_names)
            unknown = sorted(received_names - expected_names)
            raise ValueError(
                "proposal parameter set differs from the frozen landscape domain "
                f"(missing={missing}, unknown={unknown})"
            )
        parameters = self.search_space.project(proposal.parameters)
        unit = self.search_space.to_unit_vector(parameters)
        if not unit:
            raise ValueError("numeric landscape requires at least one tunable parameter")

        targets = tuple(
            0.2 + 0.6 * ((index * 0.6180339887498949) % 1.0) for index in range(len(unit))
        )
        weights = tuple(1.0 + 0.25 * index for index in range(len(unit)))
        tracking = sum(
            weight * (value - target) ** 2
            for value, target, weight in zip(unit, targets, weights, strict=True)
        ) / sum(weights)
        smoothness = sum(
            (right - left) ** 2 for left, right in zip(unit, unit[1:], strict=False)
        ) / max(1, len(unit) - 1)
        energy = sum((value - 0.35) ** 2 for value in unit) / len(unit)
        mean_control = sum(unit) / len(unit)
        high_authority_violation = max(0.0, mean_control - 0.78)
        low_authority_violation = max(0.0, 0.12 - mean_control)
        unsafe = max(unit) > 0.985 and mean_control > 0.65
        feasible = not unsafe and high_authority_violation <= 0.0 and low_authority_violation <= 0.0
        status: Literal["passed", "failed", "unsafe"] = (
            "unsafe" if unsafe else ("passed" if feasible else "failed")
        )
        metric_summary: dict[str, float | int | bool | None] = {
            "tracking_error": round(tracking, 15),
            "smoothness_penalty": round(smoothness, 15),
            "energy_penalty": round(energy, 15),
            "high_authority_violation": round(high_authority_violation, 15),
            "low_authority_violation": round(low_authority_violation, 15),
            "feasible": feasible,
        }
        if not all(
            math.isfinite(float(value))
            for value in metric_summary.values()
            if isinstance(value, int | float) and not isinstance(value, bool)
        ):
            raise ValueError("numeric landscape produced a non-finite metric")
        evidence_payload = {
            "candidate_ref": proposal.candidate_ref,
            "landscape_id": self.landscape_id,
            "metric_summary": metric_summary,
            "parameters": parameters,
            "schema_id": "dronedream.numeric-landscape-evidence/v1",
            "status": status,
        }
        return BenchmarkEvaluationV1(
            candidate_ref=proposal.candidate_ref,
            status=status,
            completed_trials=1,
            attempted_trials=1,
            metric_summary=metric_summary,
            safety_gates_passed=not unsafe,
            evidence_complete=True,
            failure_code=(
                "synthetic-unsafe-region"
                if unsafe
                else (None if feasible else "synthetic-constraint-violation")
            ),
            evidence_sha256=canonical_sha256(evidence_payload),
        )


__all__ = ["NUMERIC_LANDSCAPE_ID", "DeterministicConstrainedLandscapeV1"]
