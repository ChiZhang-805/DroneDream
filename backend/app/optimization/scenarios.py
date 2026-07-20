"""Fair, reproducible scenario matrices shared by every candidate."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.schemas import ScenarioSuiteConfig


@dataclass(frozen=True)
class ScenarioRun:
    case_id: str
    scenario_type: str
    seed: int
    weight: float
    holdout: bool
    config: dict[str, Any]

    def persistence_config(self) -> dict[str, Any]:
        return {
            **self.config,
            "scenario_case_id": self.case_id,
            "scenario_weight": self.weight,
            "holdout": self.holdout,
        }


def scenario_matrix(suite: ScenarioSuiteConfig) -> list[ScenarioRun]:
    """Flatten enabled cases into a stable case/seed evaluation matrix."""

    runs: list[ScenarioRun] = []
    for case in suite.cases:
        if not case.enabled:
            continue
        for seed in case.seeds:
            runs.append(
                ScenarioRun(
                    case_id=case.id,
                    scenario_type=case.scenario_type,
                    seed=seed,
                    weight=case.weight,
                    holdout=case.holdout,
                    config=dict(case.config),
                )
            )
    return runs


def training_matrix(suite: ScenarioSuiteConfig) -> list[ScenarioRun]:
    return [run for run in scenario_matrix(suite) if not run.holdout]


def holdout_matrix(suite: ScenarioSuiteConfig) -> list[ScenarioRun]:
    return [run for run in scenario_matrix(suite) if run.holdout]


__all__ = ["ScenarioRun", "holdout_matrix", "scenario_matrix", "training_matrix"]
