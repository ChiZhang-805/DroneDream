"""Outcome-blind, zero-provider physical stability preregistration.

P5 uses this contract before any comparative benchmark arm is allowed to run.
It freezes six user-representative PX4/Gazebo scenarios, one fixed baseline
controller, and ten common-random-number repeats per scenario.  The module does
not launch a simulator.  It only compiles a source-bound, content-addressed
trial plan that a later, separately authorized physical coordinator can consume.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Annotated, Any, Final, Literal, TypeAlias, cast

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.benchmarking.contracts import (
    CompositeExecutionInventoryV1,
    GitCommit,
    Identifier,
    Sha256Hex,
    canonical_sha256,
)
from app.optimization.prefinal_scenario_registry import (
    build_prefinal_scenario_registry,
)
from app.simulator.base import JobConfig, TrialContext
from app.simulator.scenario_effects import build_scenario_effect_request

PHYSICAL_STABILITY_SCHEMA_ID: Final = "dronedream.physical-stability-manifest/v1"
PHYSICAL_STABILITY_PLAN_SCHEMA_ID: Final = "dronedream.physical-stability-plan/v1"
PHYSICAL_STABILITY_PROTOCOL_SHA256: Final = (
    "734bb6b42ec25ffc92bd9f15bb6fa27bc3482b4ce0841ce9aa3b080eafb8caee"
)
PHYSICAL_STABILITY_VERSION: Final = "p5-zero-provider-baseline-stability-v1"
PHYSICAL_STABILITY_SEEDS: Final = tuple(range(31_001, 31_011))
StabilityLevel: TypeAlias = Literal["L1", "L2", "L3"]


class _StrictFrozen(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class PhysicalStabilityCapsV1(_StrictFrozen):
    schema_id: Literal["dronedream.physical-stability-caps/v1"] = (
        "dronedream.physical-stability-caps/v1"
    )
    trial_cap: Literal[60] = 60
    provider_logical_turn_cap: Literal[0] = 0
    provider_network_request_cap: Literal[0] = 0
    provider_token_cap: Literal[0] = 0
    provider_cost_microusd_cap: Literal[0] = 0
    per_trial_timeout_seconds: Annotated[int, Field(ge=60, le=3_600)] = 300
    wall_time_cap_seconds: Annotated[int, Field(ge=3_600, le=86_400)] = 21_600
    disk_byte_cap: Annotated[int, Field(ge=1_073_741_824, le=100_000_000_000)] = 20_000_000_000
    simulator_stdout_cap_bytes: Literal[16_777_216] = 16_777_216
    simulator_stderr_cap_bytes: Literal[8_388_608] = 8_388_608
    auxiliary_log_cap_bytes: Literal[2_097_152] = 2_097_152


class PhysicalStabilityJobConfigV1(_StrictFrozen):
    track_type: Literal["hover", "circle", "u_turn", "lemniscate"]
    start_point_x: float
    start_point_y: float
    altitude_m: Annotated[float, Field(gt=0.0, le=20.0)]
    wind_north: float
    wind_east: float
    wind_south: float
    wind_west: float
    sensor_noise_level: Literal["low", "medium", "high"]
    objective_profile: Literal["robust"] = "robust"
    reference_track: list[dict[str, float]] | None = None
    vehicle_profile: dict[str, Any]
    parameter_catalog_version: str
    selected_parameter_names: tuple[str, ...]

    @model_validator(mode="after")
    def _require_headless_x500(self) -> PhysicalStabilityJobConfigV1:
        required = {
            "vehicle_type": "multicopter",
            "airframe": "x500",
            "simulator_model": "gz_x500",
            "headless": True,
        }
        for key, expected in required.items():
            if self.vehicle_profile.get(key) != expected:
                raise ValueError(f"P5 requires vehicle_profile.{key}={expected!r}")
        if not self.selected_parameter_names:
            raise ValueError("P5 requires at least one selected PX4 parameter")
        return self


class PhysicalStabilityScenarioV1(_StrictFrozen):
    scenario_id: Identifier
    level: StabilityLevel
    task_family: Identifier
    user_relevance: Annotated[str, Field(min_length=1, max_length=512)]
    source_problem_id: Identifier
    source_problem_sha256: Sha256Hex
    derivation_notes: tuple[str, ...]
    job_config: PhysicalStabilityJobConfigV1
    scenario_type: Literal["wind_perturbed", "turbulence", "noise_perturbed", "combined_perturbed"]
    scenario_config: dict[str, Any]
    seeds: tuple[int, ...]

    @model_validator(mode="after")
    def _require_fixed_repeats(self) -> PhysicalStabilityScenarioV1:
        if self.seeds != PHYSICAL_STABILITY_SEEDS:
            raise ValueError("every P5 scenario must use the frozen ten-seed CRN block")
        return self


class PhysicalStabilityTrialPlanItemV1(_StrictFrozen):
    trial_ordinal: Annotated[int, Field(ge=1, le=60)]
    trial_id: Identifier
    job_id: Identifier
    candidate_id: Literal["p5-fixed-baseline"] = "p5-fixed-baseline"
    scenario_id: Identifier
    seed: int
    input_contract_sha256: Sha256Hex
    scenario_effect_request_sha256: Sha256Hex
    expected_effect_ids: tuple[Identifier, ...]


class PhysicalStabilityManifestV1(_StrictFrozen):
    schema_id: Literal["dronedream.physical-stability-manifest/v1"] = PHYSICAL_STABILITY_SCHEMA_ID
    manifest_version: Literal["p5-zero-provider-baseline-stability-v1"] = PHYSICAL_STABILITY_VERSION
    protocol_sha256: Literal["734bb6b42ec25ffc92bd9f15bb6fa27bc3482b4ce0841ce9aa3b080eafb8caee"] = (
        PHYSICAL_STABILITY_PROTOCOL_SHA256
    )
    repository_subject_commit: GitCommit
    composite_execution_inventory: CompositeExecutionInventoryV1
    source_registry_version: Literal["prefinal-realistic-px4-gazebo-v1"] = (
        "prefinal-realistic-px4-gazebo-v1"
    )
    source_registry_sha256: Sha256Hex
    status: Literal["preregistered_execution_blocked"] = "preregistered_execution_blocked"
    execution_authorized: Literal[False] = False
    evidence_scope: Literal["engineering_stability_only_not_comparative_not_report"] = (
        "engineering_stability_only_not_comparative_not_report"
    )
    simulator_backend: Literal["real_cli"] = "real_cli"
    provider_access: Literal[False] = False
    optimizer_access: Literal[False] = False
    fixed_baseline_parameters: dict[str, float]
    scenarios: tuple[PhysicalStabilityScenarioV1, ...]
    caps: PhysicalStabilityCapsV1
    selection_policy: dict[str, Any]

    @model_validator(mode="after")
    def _validate_preregistration(self) -> PhysicalStabilityManifestV1:
        expected_ids = (
            "hover-mild-crosswind",
            "circle-mild-crosswind",
            "u-turn-steady-wind",
            "figure-eight-light-gust",
            "circle-sensor-degradation",
            "composite-stress",
        )
        if tuple(item.scenario_id for item in self.scenarios) != expected_ids:
            raise ValueError("P5 requires the six preregistered scenarios in canonical order")
        inventory = self.composite_execution_inventory
        if not (
            self.repository_subject_commit
            == inventory.repository_subject_commit
            == inventory.evaluator_subject_commit
            == inventory.campaign_coordinator_subject_commit
        ):
            raise ValueError("repository/evaluator/coordinator subjects must be identical")
        if inventory.evidence_head_commit is not None:
            raise ValueError("execution inventory cannot carry a post-execution evidence head")
        parameter_names = tuple(self.fixed_baseline_parameters)
        if parameter_names != self.scenarios[0].job_config.selected_parameter_names:
            raise ValueError("baseline parameter order must match the selected PX4 parameter order")
        if any(
            item.job_config.selected_parameter_names != parameter_names for item in self.scenarios
        ):
            raise ValueError("every P5 scenario must use the same baseline parameter set")
        return self


class PhysicalStabilityTrialPlanV1(_StrictFrozen):
    schema_id: Literal["dronedream.physical-stability-plan/v1"] = PHYSICAL_STABILITY_PLAN_SCHEMA_ID
    manifest_sha256: Sha256Hex
    repository_subject_commit: GitCommit
    composite_execution_inventory_sha256: Sha256Hex
    trial_count: Literal[60] = 60
    provider_logical_turn_cap: Literal[0] = 0
    provider_network_request_cap: Literal[0] = 0
    execution_authorized: Literal[False] = False
    trials: tuple[PhysicalStabilityTrialPlanItemV1, ...]

    @model_validator(mode="after")
    def _validate_trial_order(self) -> PhysicalStabilityTrialPlanV1:
        if len(self.trials) != self.trial_count:
            raise ValueError("P5 trial plan must contain exactly 60 trials")
        if tuple(item.trial_ordinal for item in self.trials) != tuple(range(1, 61)):
            raise ValueError("P5 trial ordinals must be contiguous and deterministic")
        if len({item.trial_id for item in self.trials}) != self.trial_count:
            raise ValueError("P5 trial IDs must be unique")
        return self


_SCENARIO_DERIVATIONS: Final[tuple[tuple[str, StabilityLevel, str, str, str, str], ...]] = (
    (
        "hover-mild-crosswind",
        "L1",
        "representative-hover-crosswind",
        "station_keeping",
        "Station keeping under a steady outdoor crosswind.",
        "No mutation; preserves the existing moderate outdoor station-keeping contract.",
    ),
    (
        "circle-mild-crosswind",
        "L1",
        "representative-circle-crosswind",
        "orbit_inspection",
        "Orbit inspection under a moderate, directionally fixed crosswind.",
        "No mutation; preserves the existing directionally fixed orbit crosswind contract.",
    ),
    (
        "u-turn-steady-wind",
        "L2",
        "representative-u-turn-crosswind",
        "direction_reversal",
        "A row-end reversal with moderate lateral wind.",
        "No mutation; preserves the existing row-end reversal contract.",
    ),
    (
        "figure-eight-light-gust",
        "L2",
        "representative-circle-gust",
        "continuous_turning",
        "A figure-eight inspection path with periodic but non-extreme gusts.",
        "Track changes from circle to lemniscate; the existing 1.5 m/s, 8 s gust is retained.",
    ),
    (
        "circle-sensor-degradation",
        "L3",
        "representative-hover-sensor-noise",
        "orbit_inspection",
        "An orbit under bounded barometer and IMU degradation without GPS prearm drift.",
        (
            "Track changes to circle; GPS injection is held at zero while "
            "barometer and IMU degradation remain observable."
        ),
    ),
    (
        "composite-stress",
        "L3",
        "representative-circle-wind-noise",
        "orbit_inspection",
        "A payload-carrying orbit under moderate wind and bounded sensor degradation.",
        "Retains 2 m/s wind, holds GPS injection at zero, and adds a bounded 0.25 kg payload.",
    ),
)


def _source_problems() -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    registry = build_prefinal_scenario_registry()
    return registry, {item["problem_id"]: item for item in registry["problems"]}


def _baseline_parameters(job: dict[str, Any]) -> dict[str, float]:
    values = {str(item["name"]): float(item["baseline"]) for item in job["parameter_space"]}
    return values


def _derive_job(scenario_id: str, source: dict[str, Any]) -> dict[str, Any]:
    job = deepcopy(source["job_template"])
    advanced = deepcopy(job.get("advanced_scenario_config") or {})
    if scenario_id == "figure-eight-light-gust":
        job["track_type"] = "lemniscate"
    elif scenario_id == "circle-sensor-degradation":
        job["track_type"] = "circle"
        job["sensor_noise_level"] = "medium"
        advanced["sensor_degradation"] = {
            "gps_noise_m": 0.0,
            "baro_noise_m": 0.1,
            "imu_noise_scale": 1.1,
            "dropout_rate": 0.0,
        }
    elif scenario_id == "composite-stress":
        advanced["sensor_degradation"] = {
            "gps_noise_m": 0.0,
            "baro_noise_m": 0.1,
            "imu_noise_scale": 1.1,
            "dropout_rate": 0.0,
        }
        battery = dict(advanced.get("battery") or {})
        battery.update({"initial_percent": 85.0, "voltage_sag": False, "mass_payload_kg": 0.25})
        advanced["battery"] = battery
    job["advanced_scenario_config"] = advanced
    return cast(dict[str, Any], job)


def _scenario_config(job: dict[str, Any]) -> dict[str, Any]:
    return {"advanced_scenario_config": deepcopy(job.get("advanced_scenario_config") or {})}


def _job_config(job: dict[str, Any]) -> PhysicalStabilityJobConfigV1:
    wind = job["wind"]
    start = job["start_point"]
    parameters = _baseline_parameters(job)
    return PhysicalStabilityJobConfigV1(
        track_type=job["track_type"],
        start_point_x=float(start["x"]),
        start_point_y=float(start["y"]),
        altitude_m=float(job["altitude_m"]),
        wind_north=float(wind["north"]),
        wind_east=float(wind["east"]),
        wind_south=float(wind["south"]),
        wind_west=float(wind["west"]),
        sensor_noise_level=job["sensor_noise_level"],
        objective_profile="robust",
        reference_track=deepcopy(job.get("reference_track")),
        vehicle_profile=deepcopy(job["vehicle_profile"]),
        parameter_catalog_version=str(job["parameter_catalog_version"]),
        selected_parameter_names=tuple(parameters),
    )


def _materialize_scenarios() -> tuple[dict[str, Any], tuple[PhysicalStabilityScenarioV1, ...]]:
    registry, by_id = _source_problems()
    scenarios: list[PhysicalStabilityScenarioV1] = []
    for (
        scenario_id,
        level,
        source_id,
        task_family,
        user_relevance,
        derivation,
    ) in _SCENARIO_DERIVATIONS:
        source = by_id[source_id]
        job = _derive_job(scenario_id, source)
        source_sha = canonical_sha256(source)
        scenarios.append(
            PhysicalStabilityScenarioV1(
                scenario_id=scenario_id,
                level=level,
                task_family=task_family,
                user_relevance=user_relevance,
                source_problem_id=source_id,
                source_problem_sha256=source_sha,
                derivation_notes=(derivation,),
                job_config=_job_config(job),
                scenario_type=job["scenario_suite"]["cases"][0]["scenario_type"],
                scenario_config=_scenario_config(job),
                seeds=PHYSICAL_STABILITY_SEEDS,
            )
        )
    return registry, tuple(scenarios)


def build_physical_stability_manifest(
    *,
    repository_subject_commit: str,
    composite_execution_inventory: CompositeExecutionInventoryV1,
) -> PhysicalStabilityManifestV1:
    """Compile the deterministic P5 manifest without authorizing execution."""

    registry, scenarios = _materialize_scenarios()
    source_jobs = _source_problems()[1]
    baseline = _baseline_parameters(source_jobs[_SCENARIO_DERIVATIONS[0][2]]["job_template"])
    return PhysicalStabilityManifestV1(
        repository_subject_commit=repository_subject_commit,
        composite_execution_inventory=composite_execution_inventory,
        source_registry_sha256=registry["registry_sha256"],
        fixed_baseline_parameters=baseline,
        scenarios=scenarios,
        caps=PhysicalStabilityCapsV1(),
        selection_policy={
            "uses_comparative_arm_outcomes": False,
            "uses_provider": False,
            "uses_optimizer": False,
            "fixed_baseline_controller_only": True,
            "minimum_seed_repeats_per_scenario": 10,
            "criteria": [
                "effect_request_applied_and_read_back",
                "complete_telemetry_and_metric_evidence",
                "repeatable_baseline_behavior",
                "user_representativeness",
            ],
            "comparative_rank_or_direction_must_not_be_observed": True,
            "failures_and_indeterminate_trials_remain_in_denominator": True,
            "replacement_requires_new_manifest_version_and_audit_reason": True,
        },
    )


def _runtime_job_config(value: PhysicalStabilityJobConfigV1) -> JobConfig:
    return JobConfig(**value.model_dump(mode="python"))


def _trial_context(
    manifest: PhysicalStabilityManifestV1,
    scenario: PhysicalStabilityScenarioV1,
    *,
    seed: int,
    trial_ordinal: int,
) -> TrialContext:
    return TrialContext(
        trial_id=f"p5-{trial_ordinal:03d}-{scenario.scenario_id}-{seed}",
        job_id=f"p5-stability-{scenario.scenario_id}",
        job_config=_runtime_job_config(scenario.job_config),
        candidate_id="p5-fixed-baseline",
        parameters=dict(manifest.fixed_baseline_parameters),
        seed=seed,
        scenario_type=scenario.scenario_type,
        scenario_config=deepcopy(scenario.scenario_config),
    )


def compile_physical_stability_trial_plan(
    manifest: PhysicalStabilityManifestV1,
) -> PhysicalStabilityTrialPlanV1:
    """Freeze all 60 trial inputs and physical-effect requests by hash."""

    if manifest.execution_authorized:
        raise ValueError("P5 preregistration must remain execution-blocked")
    trials: list[PhysicalStabilityTrialPlanItemV1] = []
    ordinal = 0
    for scenario in manifest.scenarios:
        for seed in scenario.seeds:
            ordinal += 1
            ctx = _trial_context(manifest, scenario, seed=seed, trial_ordinal=ordinal)
            job_payload = scenario.job_config.model_dump(mode="json")
            effect_request = build_scenario_effect_request(
                execution_identity={
                    "trial_id": ctx.trial_id,
                    "job_id": ctx.job_id,
                    "candidate_id": ctx.candidate_id,
                    "seed": ctx.seed,
                    "attempt_count": ctx.attempt_count,
                },
                scenario_type=ctx.scenario_type,
                scenario_config=ctx.scenario_config or {},
                job_config={
                    "track_type": job_payload["track_type"],
                    "start_point": {
                        "x": job_payload["start_point_x"],
                        "y": job_payload["start_point_y"],
                    },
                    "altitude_m": job_payload["altitude_m"],
                    "wind": {
                        "north": job_payload["wind_north"],
                        "east": job_payload["wind_east"],
                        "south": job_payload["wind_south"],
                        "west": job_payload["wind_west"],
                    },
                    "sensor_noise_level": job_payload["sensor_noise_level"],
                    "objective_profile": job_payload["objective_profile"],
                    "vehicle_profile": job_payload["vehicle_profile"],
                    "parameter_catalog_version": job_payload["parameter_catalog_version"],
                    "px4_parameters": manifest.fixed_baseline_parameters,
                },
                advanced_config=(ctx.scenario_config or {}).get("advanced_scenario_config"),
            )
            unavailable = tuple(
                str(item["effect_id"])
                for item in effect_request["effects"]
                if item["capability"]["status"] != "available"
            )
            if unavailable:
                raise ValueError(
                    f"{scenario.scenario_id} requires unavailable effects: {unavailable}"
                )
            input_contract = {
                "schema_id": "dronedream.physical-stability-trial-input/v1",
                "manifest_sha256": canonical_sha256(manifest),
                "trial_id": ctx.trial_id,
                "job_id": ctx.job_id,
                "candidate_id": ctx.candidate_id,
                "scenario_id": scenario.scenario_id,
                "seed": seed,
                "job_config": job_payload,
                "scenario_type": ctx.scenario_type,
                "scenario_config": ctx.scenario_config,
                "parameters": manifest.fixed_baseline_parameters,
            }
            trials.append(
                PhysicalStabilityTrialPlanItemV1(
                    trial_ordinal=ordinal,
                    trial_id=ctx.trial_id,
                    job_id=ctx.job_id,
                    scenario_id=scenario.scenario_id,
                    seed=seed,
                    input_contract_sha256=canonical_sha256(input_contract),
                    scenario_effect_request_sha256=canonical_sha256(effect_request),
                    expected_effect_ids=tuple(
                        str(item["effect_id"]) for item in effect_request["effects"]
                    ),
                )
            )
    return PhysicalStabilityTrialPlanV1(
        manifest_sha256=canonical_sha256(manifest),
        repository_subject_commit=manifest.repository_subject_commit,
        composite_execution_inventory_sha256=canonical_sha256(
            manifest.composite_execution_inventory
        ),
        trials=tuple(trials),
    )


__all__ = [
    "PHYSICAL_STABILITY_PROTOCOL_SHA256",
    "PHYSICAL_STABILITY_SEEDS",
    "PHYSICAL_STABILITY_VERSION",
    "PhysicalStabilityManifestV1",
    "PhysicalStabilityTrialPlanV1",
    "build_physical_stability_manifest",
    "compile_physical_stability_trial_plan",
]
