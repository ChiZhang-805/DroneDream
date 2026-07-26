"""Fair, reproducible scenario matrices shared by every candidate."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.schemas import ScenarioCaseConfig, ScenarioSuiteConfig


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


@dataclass(frozen=True)
class ScenarioCaseResolution:
    """Result of binding persisted Trial evidence to one configured case."""

    group_key: str
    case: ScenarioCaseConfig | None
    error: str | None = None

    @property
    def matched(self) -> bool:
        return self.case is not None and self.error is None


def resolve_scenario_case(
    suite: ScenarioSuiteConfig,
    *,
    scenario_type: str,
    scenario_config: object,
    seed: object,
) -> ScenarioCaseResolution:
    """Strictly bind Trial scenario evidence to its configured suite case.

    Modern evidence carries an explicit case id and must match that case's
    scenario type and training/holdout role exactly. Legacy evidence without
    an id is accepted only when the type/role pair identifies one enabled case
    unambiguously. This deliberately never guesses across cases.
    """

    if isinstance(seed, bool) or not isinstance(seed, int):
        return ScenarioCaseResolution(
            group_key=f"type:{scenario_type}:invalid",
            case=None,
            error="invalid_scenario_seed",
        )
    if not isinstance(scenario_config, dict):
        return ScenarioCaseResolution(
            group_key=f"type:{scenario_type}:invalid",
            case=None,
            error="invalid_scenario_config",
        )
    raw_holdout = scenario_config.get("holdout", False)
    if not isinstance(raw_holdout, bool):
        return ScenarioCaseResolution(
            group_key=f"type:{scenario_type}:invalid",
            case=None,
            error="invalid_holdout_role",
        )

    enabled_cases = [case for case in suite.cases if case.enabled]
    raw_case_id = scenario_config.get("scenario_case_id")
    if raw_case_id is None:
        matches = [
            case
            for case in enabled_cases
            if case.scenario_type == scenario_type
            and case.holdout is raw_holdout
            and seed in case.seeds
        ]
        if len(matches) == 1:
            legacy_case = matches[0]
            return ScenarioCaseResolution(
                group_key=f"id:{legacy_case.id}",
                case=legacy_case,
            )
        return ScenarioCaseResolution(
            group_key=f"type:{scenario_type}:{'holdout' if raw_holdout else 'training'}",
            case=None,
            error=("unknown_scenario_case" if not matches else "ambiguous_legacy_scenario_case"),
        )

    if not isinstance(raw_case_id, str) or not raw_case_id:
        return ScenarioCaseResolution(
            group_key=f"type:{scenario_type}:invalid",
            case=None,
            error="invalid_scenario_case_id",
        )
    case = next((item for item in enabled_cases if item.id == raw_case_id), None)
    if case is None:
        return ScenarioCaseResolution(
            group_key=f"id:{raw_case_id}",
            case=None,
            error="unknown_scenario_case_id",
        )
    if case.scenario_type != scenario_type:
        return ScenarioCaseResolution(
            group_key=f"id:{raw_case_id}",
            case=None,
            error="scenario_type_mismatch",
        )
    if case.holdout is not raw_holdout:
        return ScenarioCaseResolution(
            group_key=f"id:{raw_case_id}",
            case=None,
            error="scenario_role_mismatch",
        )
    if seed not in case.seeds:
        return ScenarioCaseResolution(
            group_key=f"id:{raw_case_id}",
            case=None,
            error="scenario_seed_mismatch",
        )
    return ScenarioCaseResolution(group_key=f"id:{raw_case_id}", case=case)


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


__all__ = [
    "ScenarioCaseResolution",
    "ScenarioRun",
    "holdout_matrix",
    "resolve_scenario_case",
    "scenario_matrix",
    "training_matrix",
]
