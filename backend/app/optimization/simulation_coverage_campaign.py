"""Reproducible synthetic campaign for cross-scenario optimizer coverage.

This campaign is deliberately limited to the deterministic mock simulator.
It proves that the production optimizer can search a non-trivial, scenario-
dependent finite landscape and generalize to disjoint seeds. It does not claim
PX4/Gazebo physical fidelity.
"""

from __future__ import annotations

import hashlib
import itertools
import json
import math
import os
import tempfile
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.optimization.cma_optimizers import propose_evolutionary_candidates
from app.optimization.design import halton_design
from app.optimization.domain import ParameterDomain, SearchSpace
from app.optimization.experimental_types import (
    OptimizerObservation,
    OptimizerRequest,
    canonical_optimizer_seed_value,
)
from app.schemas import ScenarioCaseConfig, ScenarioSuiteConfig
from app.simulator import JobConfig, MockSimulatorAdapter, TrialContext

SIMULATION_COVERAGE_SCHEMA_VERSION: Literal[
    "dronedream.simulation-coverage-campaign.v1"
] = "dronedream.simulation-coverage-campaign.v1"
MOCK_LANDSCAPE_SCHEMA_VERSION: Literal[
    "dronedream.mock.synthetic.v2"
] = "dronedream.mock.synthetic.v2"
_OPTIMIZER_SEED = 12_345
_INITIAL_DESIGN_SIZE = 13
_GENERATION_COUNT = 8
_BATCH_SIZE = 6
_LOSS_TOLERANCE = 1e-12
_SHA256_PATTERN = r"^[0-9a-f]{64}$"
_TRANSCRIPT_EVIDENCE_FIELDS: tuple[str, ...] = (
    "candidate_id",
    "generation_index",
    "parameters",
    "training_loss",
    "feasible",
    "optimizer_strategy",
)
_TRANSCRIPT_ROUTE_METADATA_FIELDS: tuple[str, ...] = (
    "design",
    "design_index",
    "child_strategy",
    "optimizer_generated_by",
    "effective_fidelity",
    "requested_fidelity",
    "portfolio_slot_role",
    "cma_cohort_position",
    "cma_restart_index",
)

_SCENARIO_TYPES: tuple[str, ...] = (
    "nominal",
    "noise_perturbed",
    "wind_perturbed",
    "combined_perturbed",
    "turbulence",
    "gps_dropout",
    "payload_changed",
    "battery_degraded",
    "actuator_delay",
    "custom",
)
_SCENARIO_CONFIGS: dict[str, dict[str, Any]] = {
    "nominal": {},
    "noise_perturbed": {},
    "wind_perturbed": {},
    "combined_perturbed": {},
    "turbulence": {"intensity": 0.8},
    "gps_dropout": {"dropout_rate": 0.35},
    "payload_changed": {"mass_payload_kg": 1.5},
    "battery_degraded": {},
    "actuator_delay": {"delay_ms": 80.0},
    "custom": {"profile": "synthetic-cross-scenario"},
}
_PARAMETER_CHOICES: dict[str, tuple[float, ...]] = {
    "kp_xy": (0.8, 1.0, 1.1, 1.2, 1.3, 1.4),
    "kd_xy": (0.2, 0.25, 0.3, 0.35, 0.4),
    "ki_xy": (0.03, 0.05, 0.07),
    "vel_limit": (5.0, 5.5, 6.0),
    "accel_limit": (4.0, 4.5, 5.0),
    "disturbance_rejection": (0.5, 0.75, 1.0),
}
_BASELINE_PARAMETERS = {
    "kp_xy": 1.0,
    "kd_xy": 0.2,
    "ki_xy": 0.05,
    "vel_limit": 5.0,
    "accel_limit": 4.0,
    "disturbance_rejection": 0.5,
}


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class SimulationCoveragePoint(_FrozenModel):
    parameters: dict[str, float]
    training_loss: float
    holdout_loss: float
    training_by_scenario: dict[str, float]
    holdout_by_scenario: dict[str, float]
    training_all_pass: bool
    holdout_all_pass: bool


class SimulationCoverageArtifact(_FrozenModel):
    schema_version: Literal["dronedream.simulation-coverage-campaign.v1"]
    simulator_backend: Literal["mock"]
    mock_landscape_schema: Literal["dronedream.mock.synthetic.v2"]
    physical_fidelity: Literal[False]
    campaign_spec_sha256: str = Field(pattern=_SHA256_PATTERN)
    optimizer_transcript_sha256: str = Field(pattern=_SHA256_PATTERN)
    optimizer_strategy: Literal["optimizer_portfolio"]
    optimizer_seed: int
    scenario_types: tuple[str, ...]
    training_seeds: dict[str, int]
    holdout_seeds: dict[str, int]
    initial_design_size: int
    generation_count: int
    batch_size: int
    candidate_budget: int
    evaluated_candidate_count: int
    exhaustive_oracle_candidate_count: int
    baseline: SimulationCoveragePoint
    selected: SimulationCoveragePoint
    oracle: SimulationCoveragePoint
    oracle_tie_count: int
    training_oracle_regret: float
    holdout_oracle_regret: float
    baseline_to_selected_improvement_rate: float
    holdout_improvement_by_scenario: dict[str, float]
    all_scenarios_improved: bool
    qualified: bool
    failed_requirements: tuple[str, ...]


def _canonical_sha256(value: object) -> str:
    payload = json.dumps(
        canonical_optimizer_seed_value(value),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _optimizer_transcript_evidence_payload(
    transcript: list[dict[str, object]],
) -> list[dict[str, object]]:
    """Project optimizer events onto causal, cross-platform evidence.

    The complete optimizer metadata remains available to runtime diagnostics,
    but it contains floating-point GP/CMA internals whose equivalent values can
    vary across BLAS kernels. A frozen campaign transcript binds the decisions
    that were actually executed: candidate identity/order, parameters, loss,
    feasibility, selected optimizer route, fidelity, and CMA cohort position.
    Cosmetic numerical diagnostics cannot invalidate otherwise identical
    executions, while any candidate, result, or route change still changes the
    transcript hash.
    """

    payload: list[dict[str, object]] = []
    for entry in transcript:
        metadata = entry.get("optimizer_metadata")
        if not isinstance(metadata, dict):
            raise ValueError("optimizer transcript metadata must be an object")
        causal = {field: entry[field] for field in _TRANSCRIPT_EVIDENCE_FIELDS}
        causal["optimizer_route"] = {
            field: metadata[field]
            for field in _TRANSCRIPT_ROUTE_METADATA_FIELDS
            if field in metadata
        }
        payload.append(causal)
    return payload


def _optimizer_transcript_sha256(transcript: list[dict[str, object]]) -> str:
    return _canonical_sha256(_optimizer_transcript_evidence_payload(transcript))


def _search_space() -> SearchSpace:
    return SearchSpace(
        [
            ParameterDomain(
                name=name,
                baseline=_BASELINE_PARAMETERS[name],
                minimum=min(choices),
                maximum=max(choices),
                choices=choices,
            )
            for name, choices in _PARAMETER_CHOICES.items()
        ]
    )


def _scenario_suite() -> ScenarioSuiteConfig:
    training = [
        ScenarioCaseConfig(
            id=f"training-{scenario_type}",
            scenario_type=scenario_type,  # type: ignore[arg-type]
            seeds=[101 + index],
            config=dict(_SCENARIO_CONFIGS[scenario_type]),
        )
        for index, scenario_type in enumerate(_SCENARIO_TYPES)
    ]
    holdout = [
        ScenarioCaseConfig(
            id=f"holdout-{scenario_type}",
            scenario_type=scenario_type,  # type: ignore[arg-type]
            seeds=[901 + index],
            holdout=True,
            config=dict(_SCENARIO_CONFIGS[scenario_type]),
        )
        for index, scenario_type in enumerate(_SCENARIO_TYPES)
    ]
    return ScenarioSuiteConfig(cases=[*training, *holdout])


def _job_config() -> JobConfig:
    return JobConfig(
        track_type="circle",
        start_point_x=0.0,
        start_point_y=0.0,
        altitude_m=3.0,
        wind_north=4.0,
        wind_east=1.0,
        wind_south=0.0,
        wind_west=0.0,
        sensor_noise_level="high",
        objective_profile="robust",
    )


def _campaign_spec() -> dict[str, object]:
    suite = _scenario_suite()
    return {
        "schema_version": SIMULATION_COVERAGE_SCHEMA_VERSION,
        "simulator_backend": "mock",
        "mock_landscape_schema": MOCK_LANDSCAPE_SCHEMA_VERSION,
        "physical_fidelity": False,
        "optimizer_strategy": "optimizer_portfolio",
        "optimizer_seed": _OPTIMIZER_SEED,
        "initial_design_size": _INITIAL_DESIGN_SIZE,
        "generation_count": _GENERATION_COUNT,
        "batch_size": _BATCH_SIZE,
        "parameter_choices": {
            name: list(values) for name, values in _PARAMETER_CHOICES.items()
        },
        "baseline_parameters": _BASELINE_PARAMETERS,
        "scenario_suite": suite.model_dump(mode="json"),
        "job_config": {
            "track_type": "circle",
            "altitude_m": 3.0,
            "wind": [4.0, 1.0, 0.0, 0.0],
            "sensor_noise_level": "high",
            "objective_profile": "robust",
        },
        "objective": {
            "metric": "rmse",
            "direction": "minimize",
            "aggregation": "equal_scenario_mean",
        },
    }


def _parameter_key(parameters: dict[str, float]) -> str:
    return json.dumps(parameters, sort_keys=True, separators=(",", ":"))


def _evaluate_parameters(
    parameters: dict[str, float],
    *,
    suite: ScenarioSuiteConfig,
    holdout: bool,
) -> tuple[float, dict[str, float], bool]:
    adapter = MockSimulatorAdapter()
    job = _job_config()
    by_scenario: dict[str, float] = {}
    all_pass = True
    for case in suite.cases:
        if not case.enabled or case.holdout is not holdout:
            continue
        values: list[float] = []
        for seed in case.seeds:
            result = adapter.run_trial(
                TrialContext(
                    trial_id=f"coverage:{case.id}:{seed}:{_parameter_key(parameters)}",
                    job_id="simulation-coverage-campaign",
                    job_config=job,
                    candidate_id=_parameter_key(parameters),
                    parameters=parameters,
                    seed=seed,
                    scenario_type=case.scenario_type,
                    scenario_config=dict(case.config),
                )
            )
            if not result.success or result.metrics is None:
                raise RuntimeError(
                    f"mock scenario campaign failed for {case.id} seed {seed}"
                )
            raw = result.metrics.raw_metric_json
            if (
                raw.get("mock_landscape_schema") != MOCK_LANDSCAPE_SCHEMA_VERSION
                or raw.get("physical_fidelity") is not False
            ):
                raise RuntimeError("mock simulator returned an unexpected fidelity contract")
            values.append(float(result.metrics.rmse))
            all_pass = all_pass and result.metrics.pass_flag
        by_scenario[case.scenario_type] = round(sum(values) / len(values), 8)
    if set(by_scenario) != set(_SCENARIO_TYPES):
        raise RuntimeError("scenario campaign did not evaluate every declared scenario")
    loss = round(sum(by_scenario.values()) / len(by_scenario), 8)
    return loss, by_scenario, all_pass


def _point(
    parameters: dict[str, float],
    *,
    suite: ScenarioSuiteConfig,
) -> SimulationCoveragePoint:
    training_loss, training_by_scenario, training_all_pass = _evaluate_parameters(
        parameters,
        suite=suite,
        holdout=False,
    )
    holdout_loss, holdout_by_scenario, holdout_all_pass = _evaluate_parameters(
        parameters,
        suite=suite,
        holdout=True,
    )
    return SimulationCoveragePoint(
        parameters=parameters,
        training_loss=training_loss,
        holdout_loss=holdout_loss,
        training_by_scenario=training_by_scenario,
        holdout_by_scenario=holdout_by_scenario,
        training_all_pass=training_all_pass,
        holdout_all_pass=holdout_all_pass,
    )


def _optimizer_search(
    *,
    space: SearchSpace,
    suite: ScenarioSuiteConfig,
) -> tuple[SimulationCoveragePoint, list[dict[str, object]]]:
    observations: list[OptimizerObservation] = []
    transcript: list[dict[str, object]] = []
    seen: set[str] = set()

    def record(
        *,
        candidate_id: str,
        generation_index: int,
        parameters: dict[str, float],
        strategy: str,
        metadata: dict[str, Any],
    ) -> None:
        key = _parameter_key(parameters)
        if key in seen:
            raise RuntimeError("optimizer proposed a duplicate campaign candidate")
        seen.add(key)
        training_loss, _by_scenario, all_pass = _evaluate_parameters(
            parameters,
            suite=suite,
            holdout=False,
        )
        observation = OptimizerObservation(
            candidate_id=candidate_id,
            generation_index=generation_index,
            parameters=parameters,
            unit_vector=space.to_unit_vector(parameters),
            loss=training_loss,
            objectives={"rmse": training_loss},
            objective_directions={"rmse": "minimize"},
            feasible=all_pass,
            optimizer_strategy=strategy,
            optimizer_metadata=metadata,
            completed=True,
        )
        observations.append(observation)
        transcript.append(
            {
                "candidate_id": candidate_id,
                "generation_index": generation_index,
                "parameters": parameters,
                "training_loss": training_loss,
                "feasible": all_pass,
                "optimizer_strategy": strategy,
                "optimizer_metadata": metadata,
            }
        )

    for index, parameters in enumerate(
        halton_design(
            space,
            _INITIAL_DESIGN_SIZE,
            include_baseline=True,
        )
    ):
        record(
            candidate_id=f"initial-{index:03d}",
            generation_index=0,
            parameters=parameters,
            strategy="initial_halton",
            metadata={"design": "halton", "design_index": index},
        )

    for generation_index in range(1, _GENERATION_COUNT + 1):
        request = OptimizerRequest(
            strategy="optimizer_portfolio",
            generation_index=generation_index,
            batch_size=_BATCH_SIZE,
            random_seed=_OPTIMIZER_SEED,
            observations=tuple(observations),
            objective_weights=(("rmse", 1.0),),
            objective_normalizations=(("rmse", 1.0),),
        )
        proposals = propose_evolutionary_candidates(space, request)
        if len(proposals) != _BATCH_SIZE:
            raise RuntimeError(
                "optimizer portfolio did not fill the fixed campaign batch"
            )
        for index, proposal in enumerate(proposals):
            record(
                candidate_id=f"generation-{generation_index:02d}-{index:02d}",
                generation_index=generation_index,
                parameters=dict(proposal.parameters),
                strategy="optimizer_portfolio",
                metadata=dict(proposal.metadata),
            )

    selected = min(
        observations,
        key=lambda item: (
            math.inf if item.loss is None else item.loss,
            _parameter_key(dict(item.parameters)),
        ),
    )
    return _point(dict(selected.parameters), suite=suite), transcript


def _exhaustive_oracle(
    *,
    suite: ScenarioSuiteConfig,
) -> tuple[SimulationCoveragePoint, int, int]:
    best_loss = math.inf
    best_parameters: dict[str, float] | None = None
    tie_count = 0
    candidate_count = 0
    names = tuple(_PARAMETER_CHOICES)
    for values in itertools.product(*(_PARAMETER_CHOICES[name] for name in names)):
        parameters = dict(zip(names, values, strict=True))
        candidate_count += 1
        loss, _by_scenario, _all_pass = _evaluate_parameters(
            parameters,
            suite=suite,
            holdout=False,
        )
        if loss < best_loss - _LOSS_TOLERANCE:
            best_loss = loss
            best_parameters = parameters
            tie_count = 1
        elif math.isclose(loss, best_loss, rel_tol=0.0, abs_tol=_LOSS_TOLERANCE):
            tie_count += 1
    if best_parameters is None:
        raise RuntimeError("exhaustive scenario oracle did not evaluate a candidate")
    return _point(best_parameters, suite=suite), candidate_count, tie_count


def run_simulation_coverage_campaign() -> SimulationCoverageArtifact:
    """Run optimizer search, disjoint holdout, and the exact finite oracle."""

    suite = _scenario_suite()
    space = _search_space()
    baseline = _point(space.baseline(), suite=suite)
    selected, transcript = _optimizer_search(space=space, suite=suite)
    oracle, oracle_count, oracle_tie_count = _exhaustive_oracle(suite=suite)

    training_regret = round(
        selected.training_loss - oracle.training_loss,
        12,
    )
    holdout_regret = round(selected.holdout_loss - oracle.holdout_loss, 12)
    improvement_rate = round(
        (baseline.holdout_loss - selected.holdout_loss) / baseline.holdout_loss,
        12,
    )
    scenario_improvements = {
        scenario_type: round(
            (
                baseline.holdout_by_scenario[scenario_type]
                - selected.holdout_by_scenario[scenario_type]
            ),
            8,
        )
        for scenario_type in _SCENARIO_TYPES
    }
    all_scenarios_improved = all(
        value > _LOSS_TOLERANCE for value in scenario_improvements.values()
    )
    training_seeds: dict[str, int] = {
        case.scenario_type: case.seeds[0]
        for case in suite.cases
        if case.enabled and not case.holdout
    }
    holdout_seeds: dict[str, int] = {
        case.scenario_type: case.seeds[0]
        for case in suite.cases
        if case.enabled and case.holdout
    }
    candidate_budget = _INITIAL_DESIGN_SIZE + _GENERATION_COUNT * _BATCH_SIZE
    failed_requirements: list[str] = []
    if set(training_seeds) != set(_SCENARIO_TYPES) or set(holdout_seeds) != set(
        _SCENARIO_TYPES
    ):
        failed_requirements.append("complete_scenario_matrix")
    if set(training_seeds.values()) & set(holdout_seeds.values()):
        failed_requirements.append("disjoint_holdout_seeds")
    if len(transcript) != candidate_budget:
        failed_requirements.append("fixed_optimizer_budget")
    if not selected.training_all_pass or not selected.holdout_all_pass:
        failed_requirements.append("selected_candidate_passes_every_trial")
    if training_regret > _LOSS_TOLERANCE:
        failed_requirements.append("zero_finite_grid_training_regret")
    if holdout_regret > _LOSS_TOLERANCE:
        failed_requirements.append("zero_finite_grid_holdout_regret")
    if improvement_rate < 0.20:
        failed_requirements.append("holdout_improvement_at_least_20_percent")
    if not all_scenarios_improved:
        failed_requirements.append("every_holdout_scenario_improves")

    return SimulationCoverageArtifact(
        schema_version=SIMULATION_COVERAGE_SCHEMA_VERSION,
        simulator_backend="mock",
        mock_landscape_schema=MOCK_LANDSCAPE_SCHEMA_VERSION,
        physical_fidelity=False,
        campaign_spec_sha256=_canonical_sha256(_campaign_spec()),
        optimizer_transcript_sha256=_optimizer_transcript_sha256(transcript),
        optimizer_strategy="optimizer_portfolio",
        optimizer_seed=_OPTIMIZER_SEED,
        scenario_types=_SCENARIO_TYPES,
        training_seeds=training_seeds,
        holdout_seeds=holdout_seeds,
        initial_design_size=_INITIAL_DESIGN_SIZE,
        generation_count=_GENERATION_COUNT,
        batch_size=_BATCH_SIZE,
        candidate_budget=candidate_budget,
        evaluated_candidate_count=len(transcript),
        exhaustive_oracle_candidate_count=oracle_count,
        baseline=baseline,
        selected=selected,
        oracle=oracle,
        oracle_tie_count=oracle_tie_count,
        training_oracle_regret=training_regret,
        holdout_oracle_regret=holdout_regret,
        baseline_to_selected_improvement_rate=improvement_rate,
        holdout_improvement_by_scenario=scenario_improvements,
        all_scenarios_improved=all_scenarios_improved,
        qualified=not failed_requirements,
        failed_requirements=tuple(failed_requirements),
    )


def write_frozen_simulation_coverage_artifact(
    path: Path,
    artifact: SimulationCoverageArtifact,
) -> None:
    """Atomically create a new campaign freeze without replacing one."""

    destination = path.resolve()
    if not destination.parent.is_dir():
        raise FileNotFoundError(
            f"artifact parent directory does not exist: {destination.parent}"
        )
    payload = (
        json.dumps(
            artifact.model_dump(mode="json"),
            indent=2,
            sort_keys=True,
            ensure_ascii=False,
            allow_nan=False,
        )
        + "\n"
    )
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            prefix=f".{destination.name}.",
            suffix=".tmp",
            dir=destination.parent,
            delete=False,
        ) as handle:
            temp_path = Path(handle.name)
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.link(temp_path, destination)
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)


__all__ = [
    "MOCK_LANDSCAPE_SCHEMA_VERSION",
    "SIMULATION_COVERAGE_SCHEMA_VERSION",
    "SimulationCoverageArtifact",
    "SimulationCoveragePoint",
    "run_simulation_coverage_campaign",
    "write_frozen_simulation_coverage_artifact",
]
