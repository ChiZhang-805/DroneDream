"""Fair, reproducible scenario matrices shared by every candidate."""

from __future__ import annotations

import copy
import math
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


@dataclass(frozen=True)
class ScenarioExecutionContract:
    """Exact configured-suite payload expected by one executable Trial."""

    expected_config: dict[str, Any] | None
    error: str | None = None

    @property
    def valid(self) -> bool:
        return self.expected_config is not None and self.error is None


def optimizer_fidelity(metadata: object) -> float:
    """Return the sealed effective optimizer coverage or zero when invalid."""

    if not isinstance(metadata, dict):
        return 1.0
    raw = metadata.get("effective_fidelity", metadata.get("fidelity", 1.0))
    if isinstance(raw, bool) or not isinstance(raw, str | int | float):
        return 0.0
    try:
        fidelity = float(raw)
    except (TypeError, ValueError):
        return 0.0
    return fidelity if 0.0 < fidelity <= 1.0 and math.isfinite(fidelity) else 0.0


def optimizer_requested_fidelity(metadata: object) -> float:
    """Return the sealed nominal optimizer coverage or zero when invalid."""

    if not isinstance(metadata, dict):
        return 1.0
    raw = metadata.get("requested_fidelity", metadata.get("fidelity", 1.0))
    if isinstance(raw, bool) or not isinstance(raw, str | int | float):
        return 0.0
    try:
        fidelity = float(raw)
    except (TypeError, ValueError):
        return 0.0
    return fidelity if 0.0 < fidelity <= 1.0 and math.isfinite(fidelity) else 0.0


def scenario_execution_payload(
    run: ScenarioRun,
    *,
    source: str,
    generation_index: int,
    advanced_scenario_config: object,
    optimizer_fidelity_value: float | None = None,
    optimizer_requested_fidelity_value: float | None = None,
) -> dict[str, Any]:
    """Build the one authoritative payload persisted and later revalidated."""

    if source not in {"baseline", "optimizer", "llm_optimizer"}:
        raise ValueError("scenario source is not executable")
    if (
        isinstance(generation_index, bool)
        or not isinstance(generation_index, int)
        or generation_index < 0
    ):
        raise ValueError("generation_index must be a non-negative integer")
    if advanced_scenario_config is not None and not isinstance(
        advanced_scenario_config,
        dict,
    ):
        raise ValueError("advanced_scenario_config must be an object")
    payload = {
        **copy.deepcopy(run.persistence_config()),
        "scenario": run.scenario_type,
        "source": source,
        "generation_index": generation_index,
        "scenario_case_id": run.case_id,
        "scenario_weight": run.weight,
        "holdout": run.holdout,
        "advanced_scenario_config": copy.deepcopy(
            advanced_scenario_config or {}
        ),
    }
    if source == "optimizer":
        if (
            optimizer_fidelity_value is None
            or optimizer_requested_fidelity_value is None
            or not math.isfinite(optimizer_fidelity_value)
            or not math.isfinite(optimizer_requested_fidelity_value)
            or not 0.0 < optimizer_fidelity_value <= 1.0
            or not 0.0 < optimizer_requested_fidelity_value <= 1.0
        ):
            raise ValueError("optimizer scenario payload requires valid fidelity")
        payload["optimizer_fidelity"] = optimizer_fidelity_value
        payload["optimizer_requested_fidelity"] = (
            optimizer_requested_fidelity_value
        )
    return payload


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
    raw_generation = scenario_config.get("generation_index", 0)
    if (
        isinstance(raw_generation, bool)
        or not isinstance(raw_generation, int)
        or raw_generation < 0
    ):
        return ScenarioCaseResolution(
            group_key=f"type:{scenario_type}:invalid",
            case=None,
            error="invalid_scenario_generation",
        )
    raw_holdout = scenario_config.get("holdout", False)
    if not isinstance(raw_holdout, bool):
        return ScenarioCaseResolution(
            group_key=f"type:{scenario_type}:invalid",
            case=None,
            error="invalid_holdout_role",
        )

    configured_runs = scenario_matrix_for_generation(
        suite,
        generation_index=raw_generation,
    )
    enabled_cases = [case for case in suite.cases if case.enabled]
    raw_case_id = scenario_config.get("scenario_case_id")
    if raw_case_id is None:
        matched_case_ids = {
            run.case_id
            for run in configured_runs
            if run.scenario_type == scenario_type
            and run.holdout is raw_holdout
            and run.seed == seed
        }
        if len(matched_case_ids) == 1:
            legacy_case = next(
                case for case in enabled_cases if case.id in matched_case_ids
            )
            return ScenarioCaseResolution(
                group_key=f"id:{legacy_case.id}",
                case=legacy_case,
            )
        return ScenarioCaseResolution(
            group_key=f"type:{scenario_type}:{'holdout' if raw_holdout else 'training'}",
            case=None,
            error=(
                "unknown_scenario_case"
                if not matched_case_ids
                else "ambiguous_legacy_scenario_case"
            ),
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
    if not any(
        run.case_id == case.id
        and run.scenario_type == scenario_type
        and run.holdout is raw_holdout
        and run.seed == seed
        for run in configured_runs
    ):
        return ScenarioCaseResolution(
            group_key=f"id:{raw_case_id}",
            case=None,
            error="scenario_seed_mismatch",
        )
    return ScenarioCaseResolution(group_key=f"id:{raw_case_id}", case=case)


def validate_scenario_execution_contract(
    suite: ScenarioSuiteConfig,
    *,
    scenario_type: str,
    scenario_config: object,
    seed: object,
    candidate_source: object,
    candidate_generation: object,
    candidate_is_baseline: object,
    optimizer_metadata: object,
    advanced_scenario_config: object,
) -> ScenarioExecutionContract:
    """Fail closed unless a Trial is exactly one authorized suite dispatch."""

    if (
        isinstance(candidate_generation, bool)
        or not isinstance(candidate_generation, int)
        or candidate_generation < 0
    ):
        return ScenarioExecutionContract(
            expected_config=None,
            error="invalid_candidate_generation",
        )
    if candidate_source not in {"baseline", "optimizer", "llm_optimizer"}:
        return ScenarioExecutionContract(
            expected_config=None,
            error="invalid_candidate_source",
        )
    if not isinstance(candidate_is_baseline, bool):
        return ScenarioExecutionContract(
            expected_config=None,
            error="invalid_candidate_baseline_role",
        )
    if candidate_is_baseline is not (candidate_source == "baseline"):
        return ScenarioExecutionContract(
            expected_config=None,
            error="candidate_baseline_role_mismatch",
        )
    if candidate_source == "baseline" and candidate_generation != 0:
        return ScenarioExecutionContract(
            expected_config=None,
            error="baseline_generation_mismatch",
        )
    if not isinstance(scenario_config, dict):
        return ScenarioExecutionContract(
            expected_config=None,
            error="invalid_scenario_config",
        )
    resolution = resolve_scenario_case(
        suite,
        scenario_type=scenario_type,
        scenario_config=scenario_config,
        seed=seed,
    )
    if not resolution.matched or resolution.case is None:
        return ScenarioExecutionContract(
            expected_config=None,
            error=resolution.error or "scenario_case_mismatch",
        )
    raw_generation = scenario_config.get("generation_index")
    if raw_generation != candidate_generation:
        return ScenarioExecutionContract(
            expected_config=None,
            error="scenario_generation_mismatch",
        )

    configured_runs = scenario_matrix_for_generation(
        suite,
        generation_index=candidate_generation,
    )
    fidelity: float | None = None
    requested_fidelity: float | None = None
    if candidate_source == "optimizer":
        fidelity = optimizer_fidelity(optimizer_metadata)
        requested_fidelity = optimizer_requested_fidelity(optimizer_metadata)
        if fidelity <= 0.0 or requested_fidelity <= 0.0:
            return ScenarioExecutionContract(
                expected_config=None,
                error="invalid_optimizer_fidelity",
            )
        if requested_fidelity >= 1.0 - 1e-12:
            if not math.isclose(
                fidelity,
                1.0,
                rel_tol=0.0,
                abs_tol=1e-12,
            ):
                return ScenarioExecutionContract(
                    expected_config=None,
                    error="optimizer_fidelity_mismatch",
                )
        else:
            full_training_count = sum(
                1 for run in configured_runs if not run.holdout
            )
            configured_runs = training_matrix_for_fidelity(
                configured_runs,
                requested_fidelity,
            )
            if full_training_count <= 0:
                return ScenarioExecutionContract(
                    expected_config=None,
                    error="empty_training_scenario_matrix",
                )
            actual_fidelity = len(configured_runs) / full_training_count
            if not math.isclose(
                fidelity,
                actual_fidelity,
                rel_tol=0.0,
                abs_tol=1e-12,
            ):
                return ScenarioExecutionContract(
                    expected_config=None,
                    error="optimizer_fidelity_mismatch",
                )
    run = next(
        (
            item
            for item in configured_runs
            if item.case_id == resolution.case.id
            and item.scenario_type == scenario_type
            and item.seed == seed
            and item.holdout is resolution.case.holdout
        ),
        None,
    )
    if run is None:
        return ScenarioExecutionContract(
            expected_config=None,
            error="scenario_not_dispatched_at_fidelity",
        )
    try:
        expected = scenario_execution_payload(
            run,
            source=candidate_source,
            generation_index=candidate_generation,
            advanced_scenario_config=advanced_scenario_config,
            optimizer_fidelity_value=fidelity,
            optimizer_requested_fidelity_value=requested_fidelity,
        )
    except ValueError:
        return ScenarioExecutionContract(
            expected_config=None,
            error="invalid_scenario_contract_source",
        )
    if scenario_config != expected:
        return ScenarioExecutionContract(
            expected_config=expected,
            error="scenario_payload_mismatch",
        )
    return ScenarioExecutionContract(expected_config=expected)


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
                    config=copy.deepcopy(case.config),
                )
            )
    return runs


def scenario_matrix_for_generation(
    suite: ScenarioSuiteConfig,
    *,
    generation_index: int,
) -> list[ScenarioRun]:
    """Return the exact deterministic matrix dispatched for one generation."""

    if (
        isinstance(generation_index, bool)
        or not isinstance(generation_index, int)
        or generation_index < 0
    ):
        raise ValueError("generation_index must be a non-negative integer")
    runs = scenario_matrix(suite)
    if suite.common_random_numbers or generation_index == 0:
        return runs
    offset = generation_index * 1_000_003
    seed_modulus = 2_147_483_648
    return [
        ScenarioRun(
            case_id=run.case_id,
            scenario_type=run.scenario_type,
            seed=(run.seed + offset) % seed_modulus,
            weight=run.weight,
            holdout=run.holdout,
            config=copy.deepcopy(run.config),
        )
        for run in runs
    ]


def training_matrix_for_fidelity(
    configured_runs: list[ScenarioRun],
    requested_fidelity: float,
) -> list[ScenarioRun]:
    """Select the deterministic case-stratified training coverage."""

    if not math.isfinite(requested_fidelity) or not 0.0 < requested_fidelity <= 1.0:
        raise ValueError("requested_fidelity must be finite and inside (0, 1]")
    training_runs = [run for run in configured_runs if not run.holdout]
    if not training_runs:
        return []
    grouped: dict[str, list[ScenarioRun]] = {}
    for run in training_runs:
        grouped.setdefault(run.case_id, []).append(run)
    target = min(
        len(training_runs),
        max(len(grouped), math.ceil(len(training_runs) * requested_fidelity)),
    )
    selected: list[ScenarioRun] = []
    seed_index = 0
    while len(selected) < target:
        added = False
        for case_runs in grouped.values():
            if seed_index < len(case_runs):
                selected.append(case_runs[seed_index])
                added = True
                if len(selected) >= target:
                    break
        if not added:
            break
        seed_index += 1
    return selected


def training_matrix(suite: ScenarioSuiteConfig) -> list[ScenarioRun]:
    return [run for run in scenario_matrix(suite) if not run.holdout]


def holdout_matrix(suite: ScenarioSuiteConfig) -> list[ScenarioRun]:
    return [run for run in scenario_matrix(suite) if run.holdout]


__all__ = [
    "ScenarioCaseResolution",
    "ScenarioExecutionContract",
    "ScenarioRun",
    "holdout_matrix",
    "optimizer_fidelity",
    "optimizer_requested_fidelity",
    "resolve_scenario_case",
    "scenario_execution_payload",
    "scenario_matrix",
    "scenario_matrix_for_generation",
    "training_matrix_for_fidelity",
    "training_matrix",
    "validate_scenario_execution_contract",
]
