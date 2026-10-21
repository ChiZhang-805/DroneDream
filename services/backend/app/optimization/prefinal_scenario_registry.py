"""Pre-final, outcome-blind PX4/Gazebo comparison scenario registry.

This registry is a design and validation artifact, not benchmark evidence.  It
freezes representative user tasks, a small easy/hard tail, equal simulation
budgets, disjoint holdout seeds, and all-arm retention before any comparative
outcomes are observed.  A baseline-only physical calibration must still freeze
the final thresholds and runtime inventory in a successor registry.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from dataclasses import dataclass
from typing import Any, Literal, TypedDict

from app.optimization.scenarios import scenario_matrix
from app.schemas import (
    AcceptanceCriteria,
    AdvancedScenarioConfig,
    JobCreateRequest,
    ParameterSelection,
    ScenarioCaseConfig,
    ScenarioSuiteConfig,
    TrackPoint,
    WindVector,
)
from app.simulator.scenario_effects import build_scenario_effect_request

PREFINAL_SCENARIO_REGISTRY_SCHEMA_VERSION = "dronedream.prefinal-scenario-registry/v1"
PREFINAL_SCENARIO_REGISTRY_MANIFEST_SCHEMA_VERSION = (
    "dronedream.prefinal-scenario-registry-manifest/v1"
)
PREFINAL_SCENARIO_REGISTRY_VERSION = "prefinal-realistic-px4-gazebo-v1"
PREFINAL_SCENARIO_REGISTRY_CLAIM_BOUNDARY = (
    "Outcome-blind experiment-design contract only. It makes no provider calls, "
    "runs no simulator, selects no winner, and establishes no optimizer, Harness, "
    "PX4/Gazebo, real-aircraft, safety, or global-optimum claim. Final thresholds "
    "and the exact Runtime/Engine Pack inventory require a separately frozen, "
    "baseline-only physical calibration before a locked comparative campaign."
)

Difficulty = Literal["easy", "representative", "hard"]


class _ParameterSpaceSpec(TypedDict):
    name: str
    baseline: float
    minimum: float
    maximum: float
    step: float


class _BudgetSpec(TypedDict):
    generation_cap: int
    candidate_slots_per_generation: int
    scenario_runs_per_candidate: int
    baseline_scenario_runs: int
    simulation_trial_cap: int
    provider_turn_cap_per_job: int
    provider_retry_cap: int
    wall_time_cap_s: int
    completion_policy: str
    continue_exploration_default: bool


class _AcceptanceCriteriaSpec(TypedDict):
    target_rmse: float
    target_max_error: float
    min_pass_rate: float


@dataclass(frozen=True)
class _ProblemSpec:
    problem_id: str
    difficulty: Difficulty
    task_family: str
    track_type: str
    altitude_m: float
    user_relevance: str
    scenario_type: str = "nominal"
    wind: tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0)
    sensor_noise_level: str = "medium"
    advanced: dict[str, Any] | None = None
    scenario_config: dict[str, Any] | None = None
    reference_track: tuple[tuple[float, float, float], ...] = ()
    tags: tuple[str, ...] = ()


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def _sha256(value: object) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


_RECTANGLE_TRACK = (
    (0.0, 0.0, 3.0),
    (6.0, 0.0, 3.0),
    (6.0, 4.0, 3.0),
    (0.0, 4.0, 3.0),
    (0.0, 0.0, 3.0),
)
_AISLE_TRACK = (
    (0.0, 0.0, 3.0),
    (8.0, 0.0, 3.0),
    (8.0, 2.5, 3.0),
    (1.0, 2.5, 3.0),
)


def _problem_specs() -> tuple[_ProblemSpec, ...]:
    """Return the outcome-blind candidate matrix in stable registry order."""

    return (
        _ProblemSpec(
            "easy-hover-calm",
            "easy",
            "takeoff_hover",
            "hover",
            3.0,
            "Basic vertical takeoff and stationary inspection in calm air.",
            tags=("onboarding", "hover"),
        ),
        _ProblemSpec(
            "easy-circle-calm",
            "easy",
            "orbit_inspection",
            "circle",
            3.0,
            "A common low-speed orbit around a point of interest.",
            tags=("onboarding", "orbit"),
        ),
        _ProblemSpec(
            "representative-u-turn-calm",
            "representative",
            "direction_reversal",
            "u_turn",
            3.0,
            "A corridor or row-inspection reversal without artificial disturbance.",
            tags=("reversal", "position_tracking"),
        ),
        _ProblemSpec(
            "representative-lemniscate-calm",
            "representative",
            "continuous_turning",
            "lemniscate",
            3.5,
            "Repeated left/right turns representative of camera and mapping practice.",
            tags=("continuous_turns", "tracking"),
        ),
        _ProblemSpec(
            "representative-hover-crosswind",
            "representative",
            "station_keeping",
            "hover",
            3.0,
            "Station keeping under a steady outdoor crosswind.",
            scenario_type="wind_perturbed",
            wind=(0.0, 1.5, 0.0, 0.0),
            tags=("hover", "steady_wind"),
        ),
        _ProblemSpec(
            "representative-circle-crosswind",
            "representative",
            "orbit_inspection",
            "circle",
            3.0,
            "Orbit inspection under a moderate, directionally fixed crosswind.",
            scenario_type="wind_perturbed",
            wind=(0.0, 2.5, 0.0, 0.0),
            tags=("orbit", "steady_wind"),
        ),
        _ProblemSpec(
            "representative-u-turn-crosswind",
            "representative",
            "direction_reversal",
            "u_turn",
            3.0,
            "A row-end reversal with moderate lateral wind.",
            scenario_type="wind_perturbed",
            wind=(2.0, 0.0, 0.0, 0.0),
            tags=("reversal", "steady_wind"),
        ),
        _ProblemSpec(
            "representative-circle-gust",
            "representative",
            "orbit_inspection",
            "circle",
            3.0,
            "An orbit with periodic but non-extreme gusts.",
            scenario_type="turbulence",
            advanced={
                "wind_gusts": {
                    "enabled": True,
                    "magnitude_mps": 1.5,
                    "direction_deg": 90.0,
                    "period_s": 8.0,
                }
            },
            tags=("orbit", "gust"),
        ),
        _ProblemSpec(
            "representative-hover-sensor-noise",
            "representative",
            "station_keeping",
            "hover",
            3.0,
            "Indoor or urban station keeping with modest navigation noise.",
            scenario_type="noise_perturbed",
            sensor_noise_level="high",
            advanced={
                "sensor_degradation": {
                    "gps_noise_m": 0.25,
                    "baro_noise_m": 0.10,
                    "imu_noise_scale": 1.10,
                    "dropout_rate": 0.0,
                }
            },
            tags=("hover", "sensor_noise"),
        ),
        _ProblemSpec(
            "representative-lemniscate-sensor-noise",
            "representative",
            "continuous_turning",
            "lemniscate",
            3.5,
            "Continuous turning with realistic moderate localization noise.",
            scenario_type="noise_perturbed",
            sensor_noise_level="high",
            advanced={
                "sensor_degradation": {
                    "gps_noise_m": 0.35,
                    "baro_noise_m": 0.15,
                    "imu_noise_scale": 1.15,
                    "dropout_rate": 0.0,
                }
            },
            tags=("continuous_turns", "sensor_noise"),
        ),
        _ProblemSpec(
            "representative-hover-payload",
            "representative",
            "payload_station_keeping",
            "hover",
            3.0,
            "Station keeping after attaching a small camera or sensor payload.",
            scenario_type="payload_changed",
            advanced={"battery": {"mass_payload_kg": 0.35}},
            tags=("hover", "payload"),
        ),
        _ProblemSpec(
            "representative-circle-battery-sag",
            "representative",
            "orbit_inspection",
            "circle",
            3.0,
            "Orbit inspection later in a battery cycle with voltage sag enabled.",
            scenario_type="battery_degraded",
            advanced={"battery": {"initial_percent": 70.0, "voltage_sag": True}},
            tags=("orbit", "battery"),
        ),
        _ProblemSpec(
            "representative-rectangle-inspection",
            "representative",
            "perimeter_inspection",
            "custom",
            3.0,
            "A rectangular building or fenced-area perimeter inspection.",
            reference_track=_RECTANGLE_TRACK,
            tags=("custom_track", "perimeter"),
        ),
        _ProblemSpec(
            "representative-aisle-crosswind",
            "representative",
            "aisle_inspection",
            "custom",
            3.0,
            "A long out-and-return inspection aisle under moderate crosswind.",
            scenario_type="wind_perturbed",
            wind=(0.0, 1.8, 0.0, 0.0),
            reference_track=_AISLE_TRACK,
            tags=("custom_track", "steady_wind"),
        ),
        _ProblemSpec(
            "representative-circle-wind-noise",
            "representative",
            "orbit_inspection",
            "circle",
            3.0,
            "A realistic combined orbit with moderate wind and navigation noise.",
            scenario_type="combined_perturbed",
            wind=(2.0, 0.0, 0.0, 0.0),
            sensor_noise_level="high",
            advanced={
                "sensor_degradation": {
                    "gps_noise_m": 0.20,
                    "baro_noise_m": 0.10,
                    "imu_noise_scale": 1.10,
                    "dropout_rate": 0.0,
                }
            },
            tags=("orbit", "combined"),
        ),
        _ProblemSpec(
            "hard-lemniscate-gust-noise",
            "hard",
            "continuous_turning",
            "lemniscate",
            4.0,
            "A demanding but plausible mapping path in strong wind, gusts, and noise.",
            scenario_type="combined_perturbed",
            wind=(4.0, 0.0, 0.0, 0.0),
            sensor_noise_level="high",
            advanced={
                "wind_gusts": {
                    "enabled": True,
                    "magnitude_mps": 2.0,
                    "direction_deg": 0.0,
                    "period_s": 7.0,
                },
                "sensor_degradation": {
                    "gps_noise_m": 0.40,
                    "baro_noise_m": 0.20,
                    "imu_noise_scale": 1.20,
                    "dropout_rate": 0.02,
                },
            },
            tags=("continuous_turns", "combined", "strong_wind"),
        ),
        _ProblemSpec(
            "hard-rectangle-wind-payload",
            "hard",
            "perimeter_inspection",
            "custom",
            3.0,
            "A payload-carrying perimeter inspection under strong but usable wind.",
            scenario_type="combined_perturbed",
            wind=(0.0, 4.0, 0.0, 0.0),
            advanced={
                "battery": {
                    "initial_percent": 65.0,
                    "voltage_sag": True,
                    "mass_payload_kg": 0.75,
                }
            },
            reference_track=_RECTANGLE_TRACK,
            tags=("custom_track", "payload", "strong_wind"),
        ),
        _ProblemSpec(
            "hard-hover-wind-dropout",
            "hard",
            "station_keeping",
            "hover",
            3.0,
            "Emergency or degraded-link station keeping with strong wind and sparse dropout.",
            scenario_type="combined_perturbed",
            wind=(3.5, 0.0, 0.0, 0.0),
            sensor_noise_level="high",
            advanced={
                "sensor_degradation": {
                    "gps_noise_m": 0.45,
                    "baro_noise_m": 0.20,
                    "imu_noise_scale": 1.20,
                    "dropout_rate": 0.04,
                }
            },
            tags=("hover", "dropout", "strong_wind"),
        ),
    )


_PARAMETER_SPACE: tuple[_ParameterSpaceSpec, ...] = (
    {"name": "MPC_XY_P", "baseline": 0.95, "minimum": 0.6, "maximum": 1.3, "step": 0.1},
    {
        "name": "MPC_XY_VEL_P_ACC",
        "baseline": 1.8,
        "minimum": 1.2,
        "maximum": 2.8,
        "step": 0.1,
    },
    {
        "name": "MPC_XY_VEL_I_ACC",
        "baseline": 0.4,
        "minimum": 0.1,
        "maximum": 1.0,
        "step": 0.02,
    },
    {
        "name": "MPC_XY_VEL_D_ACC",
        "baseline": 0.2,
        "minimum": 0.1,
        "maximum": 0.5,
        "step": 0.02,
    },
    {"name": "MPC_ACC_HOR", "baseline": 3.0, "minimum": 2.0, "maximum": 5.0, "step": 1.0},
    {
        "name": "MPC_ACC_HOR_MAX",
        "baseline": 5.0,
        "minimum": 5.0,
        "maximum": 10.0,
        "step": 1.0,
    },
)

_ARMS = (
    {
        "arm_id": "deterministic_default_policy",
        "label": "Deterministic default optimizer policy",
        "provider_access": False,
        "freeze_requirement": "implementation and tool versions bound before run",
    },
    {
        "arm_id": "fixed_cma_es",
        "label": "Fixed cma_es",
        "provider_access": False,
        "freeze_requirement": "cma_es configuration bound before run",
    },
    {
        "arm_id": "preselected_specialized_optimizer",
        "label": "Best single specialized optimizer selected before locked run",
        "provider_access": False,
        "freeze_requirement": (
            "select exactly one optimizer from the declared development-only pool using "
            "baseline-blind calibration, then freeze it before any locked outcome"
        ),
        "development_only_pool": [
            "constrained_mobo",
            "multi_fidelity_mobo",
            "turbo",
            "saasbo",
            "surrogate_cma_es",
            "bipop_cma_es",
        ],
    },
    {
        "arm_id": "deterministic_portfolio_no_model",
        "label": "Deterministic optimizer portfolio without model routing",
        "provider_access": False,
        "freeze_requirement": "portfolio membership and deterministic routing bound before run",
    },
    {
        "arm_id": "harness_without_reflection_recovery_memory",
        "label": "Harness routing without reflection/recovery memory",
        "provider_access": True,
        "freeze_requirement": (
            "same model snapshot and prompts; declared component intervention only"
        ),
    },
    {
        "arm_id": "full_harness",
        "label": "Full Harness",
        "provider_access": True,
        "freeze_requirement": "same model snapshot, prompts, tools, and adaptive-turn policy",
    },
)

_BUDGET: _BudgetSpec = {
    "generation_cap": 8,
    "candidate_slots_per_generation": 2,
    "scenario_runs_per_candidate": 4,
    "baseline_scenario_runs": 4,
    "simulation_trial_cap": 68,
    "provider_turn_cap_per_job": 32,
    "provider_retry_cap": 0,
    "wall_time_cap_s": 3_600,
    "completion_policy": "first_qualified_stop",
    "continue_exploration_default": False,
}

_CALIBRATION_THRESHOLDS: dict[Difficulty, _AcceptanceCriteriaSpec] = {
    "easy": {"target_rmse": 0.35, "target_max_error": 0.90, "min_pass_rate": 1.0},
    "representative": {"target_rmse": 0.55, "target_max_error": 1.35, "min_pass_rate": 1.0},
    "hard": {"target_rmse": 0.80, "target_max_error": 1.80, "min_pass_rate": 1.0},
}


def _scenario_suite(spec: _ProblemSpec, index: int) -> ScenarioSuiteConfig:
    base = index * 10
    config = dict(spec.scenario_config or {})
    return ScenarioSuiteConfig(
        common_random_numbers=True,
        cases=[
            ScenarioCaseConfig(
                id=f"{spec.problem_id}-train",
                scenario_type=spec.scenario_type,  # type: ignore[arg-type]
                seeds=[10_000 + base + 1, 10_000 + base + 2],
                holdout=False,
                config=config,
            ),
            ScenarioCaseConfig(
                id=f"{spec.problem_id}-holdout",
                scenario_type=spec.scenario_type,  # type: ignore[arg-type]
                seeds=[20_000 + base + 1, 20_000 + base + 2],
                holdout=True,
                config=config,
            ),
        ],
    )


def _job_template(spec: _ProblemSpec, index: int) -> JobCreateRequest:
    north, east, south, west = spec.wind
    return JobCreateRequest(
        display_name=f"Pre-final {spec.problem_id}",
        track_type=spec.track_type,  # type: ignore[arg-type]
        altitude_m=spec.altitude_m,
        wind=WindVector(north=north, east=east, south=south, west=west),
        sensor_noise_level=spec.sensor_noise_level,  # type: ignore[arg-type]
        objective_profile="robust",
        reference_track=[TrackPoint(x=x, y=y, z=z) for x, y, z in spec.reference_track]
        or None,
        advanced_scenario_config=(
            AdvancedScenarioConfig.model_validate(spec.advanced) if spec.advanced else None
        ),
        parameter_catalog_version="builtin-v1",
        parameter_space=[ParameterSelection.model_validate(item) for item in _PARAMETER_SPACE],
        scenario_suite=_scenario_suite(spec, index),
        simulator_backend="real_cli",
        optimizer_strategy="none",
        max_iterations=_BUDGET["generation_cap"],
        trials_per_candidate=_BUDGET["scenario_runs_per_candidate"],
        max_total_trials=_BUDGET["simulation_trial_cap"],
        completion_policy="first_qualified_stop",
        provider_turn_cap=0,
        acceptance_criteria=AcceptanceCriteria.model_validate(
            _CALIBRATION_THRESHOLDS[spec.difficulty]
        ),
    )


def _effect_contracts(
    spec: _ProblemSpec,
    index: int,
    job: JobCreateRequest,
) -> list[dict[str, Any]]:
    job_payload = job.model_dump(mode="json", exclude_none=True)
    contracts: list[dict[str, Any]] = []
    for run in scenario_matrix(job.scenario_suite):
        request = build_scenario_effect_request(
            execution_identity={
                "registry_version": PREFINAL_SCENARIO_REGISTRY_VERSION,
                "problem_id": spec.problem_id,
                "case_id": run.case_id,
                "seed": run.seed,
            },
            scenario_type=run.scenario_type,
            scenario_config=run.config,
            job_config={
                "wind": job_payload["wind"],
                "sensor_noise_level": job.sensor_noise_level,
            },
            advanced_config=job_payload.get("advanced_scenario_config"),
        )
        unavailable = [
            effect["effect_id"]
            for effect in request["effects"]
            if effect["capability"]["status"] != "available"
        ]
        if unavailable:
            raise ValueError(
                f"{spec.problem_id} requires unavailable runtime effects: {sorted(unavailable)}"
            )
        contracts.append(
            {
                "case_id": run.case_id,
                "seed": run.seed,
                "holdout": run.holdout,
                "effect_ids": [effect["effect_id"] for effect in request["effects"]],
                "request_sha256": _sha256(request),
            }
        )
    return contracts


def _materialize_problem(spec: _ProblemSpec, index: int) -> dict[str, Any]:
    job = _job_template(spec, index)
    effects = _effect_contracts(spec, index, job)
    return {
        "problem_id": spec.problem_id,
        "registry_ordinal": index,
        "difficulty": spec.difficulty,
        "task_family": spec.task_family,
        "user_relevance": spec.user_relevance,
        "tags": list(spec.tags),
        "threshold_status": "baseline_calibration_required",
        "provisional_acceptance_criteria": _CALIBRATION_THRESHOLDS[spec.difficulty],
        "job_template": job.model_dump(mode="json", exclude_none=True),
        "physical_effect_contracts": effects,
        "physical_effect_contracts_sha256": _sha256(effects),
    }


def build_prefinal_scenario_registry() -> dict[str, Any]:
    """Build and self-validate the deterministic pre-final registry."""

    specs = _problem_specs()
    problems = [_materialize_problem(spec, index) for index, spec in enumerate(specs, start=1)]
    counts = Counter(problem["difficulty"] for problem in problems)
    expected_counts = {"easy": 2, "representative": 13, "hard": 3}
    if dict(counts) != expected_counts:
        raise ValueError(f"unexpected difficulty distribution: {dict(counts)}")

    training_seeds = {
        seed
        for problem in problems
        for case in problem["job_template"]["scenario_suite"]["cases"]
        if not case["holdout"]
        for seed in case["seeds"]
    }
    holdout_seeds = {
        seed
        for problem in problems
        for case in problem["job_template"]["scenario_suite"]["cases"]
        if case["holdout"]
        for seed in case["seeds"]
    }
    if training_seeds & holdout_seeds:
        raise ValueError("registry training and holdout seeds overlap")

    unsigned: dict[str, Any] = {
        "schema_version": PREFINAL_SCENARIO_REGISTRY_SCHEMA_VERSION,
        "registry_version": PREFINAL_SCENARIO_REGISTRY_VERSION,
        "status": "design_only_not_execution_approved",
        "report_eligible": False,
        "claim_boundary": PREFINAL_SCENARIO_REGISTRY_CLAIM_BOUNDARY,
        "selection_policy": {
            "all_registered_problems_retained": True,
            "comparative_outcome_based_pruning_forbidden": True,
            "failures_and_competitor_wins_retained": True,
            "replacement_allowed_only_before_lock": True,
            "replacement_reasons": [
                "nonphysical_or_unavailable_runtime_effect",
                "invalid_or_unexecutable_track_contract",
                "baseline_only_calibration_proves_trivially_impossible_or_trivially_saturated",
            ],
            "replacement_requires_new_registry_version_and_audit_log": True,
        },
        "calibration_protocol": {
            "uses_comparative_arm_outcomes": False,
            "uses_provider": False,
            "uses_optimizer": False,
            "fixed_baseline_controller_only": True,
            "purpose": "freeze feasible thresholds and verify runtime execution before lock",
            "successor_required": "locked-realistic-px4-gazebo-v2",
        },
        "holdout_policy": {
            "training_and_holdout_seeds_disjoint": True,
            "holdout_hidden_during_candidate_selection": True,
            "holdout_revealed_only_after_candidate_freeze": True,
            "same_scenario_contract_across_arms": True,
            "common_random_numbers_across_arms": True,
            "continue_exploration_requires_independent_successor_holdout": True,
        },
        "primary_product_objective": {
            "name": "time_to_first_qualified_candidate",
            "stop_when_first_qualified": True,
            "secondary": [
                "simulations_to_first_qualified_candidate",
                "provider_calls_to_first_qualified_candidate",
                "qualification_rate",
                "holdout_pass_rate",
                "unsafe_or_invalid_proposal_rate",
                "wall_time_and_cost",
            ],
            "no_validated_winner_when_none_qualify": True,
        },
        "fairness_contract": {
            "same_parameter_space": True,
            "same_baseline_parameters": True,
            "same_simulation_trial_cap": True,
            "same_scenario_and_seed_matrix": True,
            "same_hard_safety_and_acceptance_gates": True,
            "provider_turns_may_differ_but_are_counted": True,
            "extra_provider_turns_do_not_grant_extra_simulations": True,
            "arrival_order_and_candidate_uuid_not_semantic_tie_breakers": True,
        },
        "deterministic_tie_break": [
            "all_hard_gates_and_holdout_pass",
            "fewer_consumed_simulation_trials",
            "earlier_generation_and_dispatch_ordinal",
            "pre_registered_objective_order",
        ],
        "budget": _BUDGET,
        "parameter_space": list(_PARAMETER_SPACE),
        "arms": list(_ARMS),
        "difficulty_distribution": expected_counts,
        "problem_count": len(problems),
        "training_seed_count": len(training_seeds),
        "holdout_seed_count": len(holdout_seeds),
        "problems": problems,
    }
    return {**unsigned, "registry_sha256": _sha256(unsigned)}


def verify_prefinal_scenario_registry(registry: dict[str, Any]) -> bool:
    """Verify both the embedded hash and exact deterministic regeneration."""

    expected = registry.get("registry_sha256")
    unsigned = {key: value for key, value in registry.items() if key != "registry_sha256"}
    return (
        isinstance(expected, str)
        and expected == _sha256(unsigned)
        and registry == build_prefinal_scenario_registry()
    )


__all__ = [
    "PREFINAL_SCENARIO_REGISTRY_CLAIM_BOUNDARY",
    "PREFINAL_SCENARIO_REGISTRY_MANIFEST_SCHEMA_VERSION",
    "PREFINAL_SCENARIO_REGISTRY_SCHEMA_VERSION",
    "PREFINAL_SCENARIO_REGISTRY_VERSION",
    "build_prefinal_scenario_registry",
    "verify_prefinal_scenario_registry",
]
