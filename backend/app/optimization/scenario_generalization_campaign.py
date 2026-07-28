"""Frozen mixed-shift campaign for the deterministic mock simulator.

The optimizer sees only the training cases.  After candidate selection is
frozen, the selected parameters are evaluated against stronger configurations
of known scenario types and scenario types absent from training.  Validation
outcomes are report-only and never enter the optimizer transcript.

This campaign proves a software and evaluation contract on a deterministic
synthetic landscape.  It does not claim PX4/Gazebo or real-flight fidelity.
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
from app.optimization.generalization_evidence import (
    CandidateGeneralizationEvidence,
    compile_candidate_generalization_evidence,
)
from app.optimization.simulation_coverage_campaign import (
    MOCK_LANDSCAPE_SCHEMA_VERSION,
)
from app.schemas import (
    ObjectiveConfig,
    ObjectiveSpec,
    ScenarioCaseConfig,
    ScenarioSuiteConfig,
)
from app.simulator import JobConfig, MockSimulatorAdapter, TrialContext

SCENARIO_GENERALIZATION_SCHEMA_VERSION: Literal[
    "dronedream.scenario-generalization-campaign.v1"
] = "dronedream.scenario-generalization-campaign.v1"

_OPTIMIZER_SEED = 27_071
_INITIAL_DESIGN_SIZE = 13
_GENERATION_COUNT = 8
_BATCH_SIZE = 6
_LOSS_TOLERANCE = 1e-12
_SHA256_PATTERN = r"^[0-9a-f]{64}$"
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


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ScenarioGeneralizationPoint(_FrozenModel):
    parameters: dict[str, float]
    training_loss: float
    validation_loss: float
    training_by_case: dict[str, float]
    validation_by_case: dict[str, float]
    training_all_pass: bool
    validation_all_pass: bool


class ScenarioGeneralizationArtifact(_FrozenModel):
    schema_version: Literal["dronedream.scenario-generalization-campaign.v1"]
    simulator_backend: Literal["mock"]
    mock_landscape_schema: Literal["dronedream.mock.synthetic.v2"]
    physical_fidelity: Literal[False]
    validation_role: Literal["report_only_no_adaptive_feedback"]
    validation_outcomes_used_for_selection: Literal[False]
    campaign_spec_sha256: str = Field(pattern=_SHA256_PATTERN)
    optimizer_transcript_sha256: str = Field(pattern=_SHA256_PATTERN)
    optimizer_strategy: Literal["optimizer_portfolio"]
    optimizer_seed: int
    training_case_ids: tuple[str, ...]
    validation_case_ids: tuple[str, ...]
    training_scenario_types: tuple[str, ...]
    validation_scenario_types: tuple[str, ...]
    training_seeds: dict[str, int]
    validation_seeds: dict[str, int]
    configuration_shift_case_ids: tuple[str, ...]
    novel_scenario_type_case_ids: tuple[str, ...]
    initial_design_size: int
    generation_count: int
    batch_size: int
    candidate_budget: int
    evaluated_candidate_count: int
    exhaustive_training_oracle_candidate_count: int
    exhaustive_validation_oracle_candidate_count: int
    baseline: ScenarioGeneralizationPoint
    selected: ScenarioGeneralizationPoint
    training_oracle: ScenarioGeneralizationPoint
    validation_oracle: ScenarioGeneralizationPoint
    training_oracle_tie_count: int
    validation_oracle_tie_count: int
    training_oracle_regret: float
    validation_oracle_regret: float
    baseline_to_selected_training_improvement_rate: float
    baseline_to_selected_validation_improvement_rate: float
    validation_change_by_case: dict[str, float]
    generalization_evidence: CandidateGeneralizationEvidence
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


def _parameter_key(parameters: dict[str, float]) -> str:
    return json.dumps(parameters, sort_keys=True, separators=(",", ":"))


def _optimizer_transcript_sha256(transcript: list[dict[str, object]]) -> str:
    causal_payload: list[dict[str, object]] = []
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
        causal_payload.append(causal)
    return _canonical_sha256(causal_payload)


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
    training = (
        ScenarioCaseConfig(
            id="training-nominal",
            scenario_type="nominal",
            seeds=[111],
            config={},
        ),
        ScenarioCaseConfig(
            id="training-noise",
            scenario_type="noise_perturbed",
            seeds=[112],
            config={"advanced_scenario_config": {"sensor_degradation": {"dropout_rate": 0.05}}},
        ),
        ScenarioCaseConfig(
            id="training-wind",
            scenario_type="wind_perturbed",
            seeds=[113],
            config={
                "advanced_scenario_config": {"wind_gusts": {"enabled": True, "magnitude_mps": 2.0}}
            },
        ),
        ScenarioCaseConfig(
            id="training-turbulence",
            scenario_type="turbulence",
            seeds=[114],
            config={"intensity": 0.35},
        ),
        ScenarioCaseConfig(
            id="training-payload",
            scenario_type="payload_changed",
            seeds=[115],
            config={"mass_payload_kg": 0.75},
        ),
    )
    validation = (
        ScenarioCaseConfig(
            id="validation-nominal-obstacles",
            scenario_type="nominal",
            seeds=[911],
            holdout=True,
            config={
                "advanced_scenario_config": {
                    "obstacles": [
                        {"x": 2.0, "y": 1.0},
                        {"x": -1.0, "y": 3.0},
                        {"x": 4.0, "y": -2.0},
                    ]
                }
            },
        ),
        ScenarioCaseConfig(
            id="validation-noise-heavy",
            scenario_type="noise_perturbed",
            seeds=[912],
            holdout=True,
            config={"advanced_scenario_config": {"sensor_degradation": {"dropout_rate": 0.30}}},
        ),
        ScenarioCaseConfig(
            id="validation-wind-gust",
            scenario_type="wind_perturbed",
            seeds=[913],
            holdout=True,
            config={
                "advanced_scenario_config": {"wind_gusts": {"enabled": True, "magnitude_mps": 7.0}}
            },
        ),
        ScenarioCaseConfig(
            id="validation-turbulence-high",
            scenario_type="turbulence",
            seeds=[914],
            holdout=True,
            config={"intensity": 1.20},
        ),
        ScenarioCaseConfig(
            id="validation-payload-heavy",
            scenario_type="payload_changed",
            seeds=[915],
            holdout=True,
            config={"mass_payload_kg": 2.50},
        ),
        ScenarioCaseConfig(
            id="validation-combined-novel",
            scenario_type="combined_perturbed",
            seeds=[916],
            holdout=True,
            config={},
        ),
        ScenarioCaseConfig(
            id="validation-gps-dropout-novel",
            scenario_type="gps_dropout",
            seeds=[917],
            holdout=True,
            config={"dropout_rate": 0.42},
        ),
        ScenarioCaseConfig(
            id="validation-battery-novel",
            scenario_type="battery_degraded",
            seeds=[918],
            holdout=True,
            config={"advanced_scenario_config": {"battery": {"initial_percent": 35.0}}},
        ),
        ScenarioCaseConfig(
            id="validation-actuator-delay-novel",
            scenario_type="actuator_delay",
            seeds=[919],
            holdout=True,
            config={"delay_ms": 110.0},
        ),
        ScenarioCaseConfig(
            id="validation-custom-novel",
            scenario_type="custom",
            seeds=[920],
            holdout=True,
            config={
                "profile": "synthetic-mixed-shift",
                "advanced_scenario_config": {
                    "wind_gusts": {"enabled": True, "magnitude_mps": 4.0},
                    "obstacles": [{"x": 1.0, "y": 1.0}],
                },
            },
        ),
    )
    return ScenarioSuiteConfig(cases=[*training, *validation])


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


def _enabled_cases(suite: ScenarioSuiteConfig, *, holdout: bool) -> tuple[ScenarioCaseConfig, ...]:
    return tuple(case for case in suite.cases if case.enabled and case.holdout is holdout)


def _evaluate_case_set(
    parameters: dict[str, float],
    *,
    cases: tuple[ScenarioCaseConfig, ...],
    phase: Literal["training", "validation"],
) -> tuple[float, dict[str, float], bool]:
    adapter = MockSimulatorAdapter()
    job = _job_config()
    by_case: dict[str, float] = {}
    all_pass = True
    for case in cases:
        values: list[float] = []
        for seed in case.seeds:
            result = adapter.run_trial(
                TrialContext(
                    trial_id=(
                        f"scenario-generalization:{phase}:{case.id}:{seed}:"
                        f"{_parameter_key(parameters)}"
                    ),
                    job_id="scenario-generalization-campaign",
                    job_config=job,
                    candidate_id=_parameter_key(parameters),
                    parameters=parameters,
                    seed=seed,
                    scenario_type=case.scenario_type,
                    scenario_config=dict(case.config),
                )
            )
            if not result.success or result.metrics is None:
                raise RuntimeError(f"mock mixed-shift campaign failed for {case.id} seed {seed}")
            raw = result.metrics.raw_metric_json
            if (
                raw.get("mock_landscape_schema") != MOCK_LANDSCAPE_SCHEMA_VERSION
                or raw.get("physical_fidelity") is not False
            ):
                raise RuntimeError("mock simulator returned an unexpected fidelity contract")
            values.append(float(result.metrics.score))
            all_pass = all_pass and result.metrics.pass_flag
        by_case[case.id] = round(sum(values) / len(values), 8)
    if set(by_case) != {case.id for case in cases}:
        raise RuntimeError("mixed-shift campaign did not evaluate every declared case")
    return round(sum(by_case.values()) / len(by_case), 8), by_case, all_pass


def _point(
    parameters: dict[str, float],
    *,
    training_cases: tuple[ScenarioCaseConfig, ...],
    validation_cases: tuple[ScenarioCaseConfig, ...],
) -> ScenarioGeneralizationPoint:
    training_loss, training_by_case, training_all_pass = _evaluate_case_set(
        parameters,
        cases=training_cases,
        phase="training",
    )
    validation_loss, validation_by_case, validation_all_pass = _evaluate_case_set(
        parameters,
        cases=validation_cases,
        phase="validation",
    )
    return ScenarioGeneralizationPoint(
        parameters=parameters,
        training_loss=training_loss,
        validation_loss=validation_loss,
        training_by_case=training_by_case,
        validation_by_case=validation_by_case,
        training_all_pass=training_all_pass,
        validation_all_pass=validation_all_pass,
    )


def _optimizer_search(
    *,
    space: SearchSpace,
    training_cases: tuple[ScenarioCaseConfig, ...],
) -> tuple[dict[str, float], list[dict[str, object]]]:
    """Select a candidate from training outcomes only."""

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
            raise RuntimeError("optimizer proposed a duplicate mixed-shift candidate")
        seen.add(key)
        training_loss, _by_case, all_pass = _evaluate_case_set(
            parameters,
            cases=training_cases,
            phase="training",
        )
        observations.append(
            OptimizerObservation(
                candidate_id=candidate_id,
                generation_index=generation_index,
                parameters=parameters,
                unit_vector=space.to_unit_vector(parameters),
                loss=training_loss,
                objectives={"score": training_loss},
                objective_directions={"score": "minimize"},
                feasible=all_pass,
                optimizer_strategy=strategy,
                optimizer_metadata=metadata,
                completed=True,
            )
        )
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
        halton_design(space, _INITIAL_DESIGN_SIZE, include_baseline=True)
    ):
        record(
            candidate_id=f"initial-{index:03d}",
            generation_index=0,
            parameters=parameters,
            strategy="initial_halton",
            metadata={"design": "halton", "design_index": index},
        )

    for generation_index in range(1, _GENERATION_COUNT + 1):
        proposals = propose_evolutionary_candidates(
            space,
            OptimizerRequest(
                strategy="optimizer_portfolio",
                generation_index=generation_index,
                batch_size=_BATCH_SIZE,
                random_seed=_OPTIMIZER_SEED,
                observations=tuple(observations),
                objective_weights=(("score", 1.0),),
                objective_normalizations=(("score", 1.0),),
            ),
        )
        if len(proposals) != _BATCH_SIZE:
            raise RuntimeError("optimizer portfolio did not fill the fixed batch")
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
    return dict(selected.parameters), transcript


def _exhaustive_oracle_parameters(
    *,
    cases: tuple[ScenarioCaseConfig, ...],
    phase: Literal["training", "validation"],
) -> tuple[dict[str, float], int, int]:
    best_loss = math.inf
    best_parameters: dict[str, float] | None = None
    tie_count = 0
    candidate_count = 0
    names = tuple(_PARAMETER_CHOICES)
    for values in itertools.product(*(_PARAMETER_CHOICES[name] for name in names)):
        parameters = dict(zip(names, values, strict=True))
        candidate_count += 1
        loss, _by_case, _all_pass = _evaluate_case_set(
            parameters,
            cases=cases,
            phase=phase,
        )
        if loss < best_loss - _LOSS_TOLERANCE:
            best_loss = loss
            best_parameters = parameters
            tie_count = 1
        elif math.isclose(loss, best_loss, rel_tol=0.0, abs_tol=_LOSS_TOLERANCE):
            tie_count += 1
    if best_parameters is None:
        raise RuntimeError("mixed-shift oracle did not evaluate a candidate")
    return best_parameters, candidate_count, tie_count


def _campaign_spec() -> dict[str, object]:
    return {
        "schema_version": SCENARIO_GENERALIZATION_SCHEMA_VERSION,
        "simulator_backend": "mock",
        "mock_landscape_schema": MOCK_LANDSCAPE_SCHEMA_VERSION,
        "physical_fidelity": False,
        "validation_role": "report_only_no_adaptive_feedback",
        "validation_outcomes_used_for_selection": False,
        "optimizer_strategy": "optimizer_portfolio",
        "optimizer_seed": _OPTIMIZER_SEED,
        "initial_design_size": _INITIAL_DESIGN_SIZE,
        "generation_count": _GENERATION_COUNT,
        "batch_size": _BATCH_SIZE,
        "parameter_choices": {name: list(values) for name, values in _PARAMETER_CHOICES.items()},
        "baseline_parameters": _BASELINE_PARAMETERS,
        "scenario_suite": _scenario_suite().model_dump(mode="json"),
        "job_config": {
            "track_type": "circle",
            "altitude_m": 3.0,
            "wind": [4.0, 1.0, 0.0, 0.0],
            "sensor_noise_level": "high",
            "objective_profile": "robust",
        },
        "objective": {
            "metric": "score",
            "direction": "minimize",
            "aggregation": "equal_case_mean",
        },
    }


def run_scenario_generalization_campaign() -> ScenarioGeneralizationArtifact:
    """Run training-only search followed by report-only mixed-shift validation."""

    suite = _scenario_suite()
    training_cases = _enabled_cases(suite, holdout=False)
    validation_cases = _enabled_cases(suite, holdout=True)
    space = _search_space()

    selected_parameters, transcript = _optimizer_search(
        space=space,
        training_cases=training_cases,
    )
    training_oracle_parameters, training_oracle_count, training_oracle_ties = (
        _exhaustive_oracle_parameters(cases=training_cases, phase="training")
    )
    validation_oracle_parameters, validation_oracle_count, validation_oracle_ties = (
        _exhaustive_oracle_parameters(cases=validation_cases, phase="validation")
    )

    baseline = _point(
        space.baseline(),
        training_cases=training_cases,
        validation_cases=validation_cases,
    )
    selected = _point(
        selected_parameters,
        training_cases=training_cases,
        validation_cases=validation_cases,
    )
    training_oracle = _point(
        training_oracle_parameters,
        training_cases=training_cases,
        validation_cases=validation_cases,
    )
    validation_oracle = _point(
        validation_oracle_parameters,
        training_cases=training_cases,
        validation_cases=validation_cases,
    )
    validation_trial_count = sum(len(case.seeds) for case in validation_cases)
    generalization_evidence = compile_candidate_generalization_evidence(
        objective_config=ObjectiveConfig(
            objectives=[ObjectiveSpec(metric="score", direction="minimize")]
        ),
        scenario_suite=suite,
        validation_status="passed" if selected.validation_all_pass else "failed",
        validation_trial_count=validation_trial_count,
        validation_completed_trial_count=validation_trial_count,
        training_objectives={"score": selected.training_loss},
        validation_objectives={"score": selected.validation_loss},
        training_scalar_loss=selected.training_loss,
        validation_scalar_loss=selected.validation_loss,
    )

    training_types = tuple(dict.fromkeys(case.scenario_type for case in training_cases))
    validation_types = tuple(dict.fromkeys(case.scenario_type for case in validation_cases))
    training_type_set = set(training_types)
    training_config_pairs = {
        (case.scenario_type, _canonical_sha256(case.config)) for case in training_cases
    }
    configuration_shift_ids = tuple(
        case.id
        for case in validation_cases
        if case.scenario_type in training_type_set
        and (case.scenario_type, _canonical_sha256(case.config)) not in training_config_pairs
    )
    novel_type_ids = tuple(
        case.id for case in validation_cases if case.scenario_type not in training_type_set
    )
    training_seeds = {case.id: case.seeds[0] for case in training_cases}
    validation_seeds = {case.id: case.seeds[0] for case in validation_cases}
    candidate_budget = _INITIAL_DESIGN_SIZE + _GENERATION_COUNT * _BATCH_SIZE
    failed_requirements: list[str] = []
    if len(transcript) != candidate_budget:
        failed_requirements.append("fixed_optimizer_budget")
    if set(training_seeds.values()) & set(validation_seeds.values()):
        failed_requirements.append("disjoint_training_validation_seeds")
    if len(configuration_shift_ids) != 5:
        failed_requirements.append("five_configuration_shift_cases")
    if len(novel_type_ids) != 5:
        failed_requirements.append("five_novel_scenario_type_cases")
    if not selected.training_all_pass or not selected.validation_all_pass:
        failed_requirements.append("selected_candidate_passes_every_trial")
    if selected.training_loss - training_oracle.training_loss > _LOSS_TOLERANCE:
        failed_requirements.append("zero_finite_grid_training_regret")
    if (
        generalization_evidence.role != "validation_report_only_no_adaptive_feedback"
        or not generalization_evidence.qualified
        or generalization_evidence.claim_scope != "mixed_shift_robustness"
        or generalization_evidence.shift_axes != ("configuration_shift", "scenario_type_shift")
    ):
        failed_requirements.append("content_addressed_mixed_shift_evidence")

    validation_change_by_case = {
        case_id: round(
            selected.validation_by_case[case_id] - baseline.validation_by_case[case_id],
            8,
        )
        for case_id in selected.validation_by_case
    }
    return ScenarioGeneralizationArtifact(
        schema_version=SCENARIO_GENERALIZATION_SCHEMA_VERSION,
        simulator_backend="mock",
        mock_landscape_schema=MOCK_LANDSCAPE_SCHEMA_VERSION,
        physical_fidelity=False,
        validation_role="report_only_no_adaptive_feedback",
        validation_outcomes_used_for_selection=False,
        campaign_spec_sha256=_canonical_sha256(_campaign_spec()),
        optimizer_transcript_sha256=_optimizer_transcript_sha256(transcript),
        optimizer_strategy="optimizer_portfolio",
        optimizer_seed=_OPTIMIZER_SEED,
        training_case_ids=tuple(case.id for case in training_cases),
        validation_case_ids=tuple(case.id for case in validation_cases),
        training_scenario_types=training_types,
        validation_scenario_types=validation_types,
        training_seeds=training_seeds,
        validation_seeds=validation_seeds,
        configuration_shift_case_ids=configuration_shift_ids,
        novel_scenario_type_case_ids=novel_type_ids,
        initial_design_size=_INITIAL_DESIGN_SIZE,
        generation_count=_GENERATION_COUNT,
        batch_size=_BATCH_SIZE,
        candidate_budget=candidate_budget,
        evaluated_candidate_count=len(transcript),
        exhaustive_training_oracle_candidate_count=training_oracle_count,
        exhaustive_validation_oracle_candidate_count=validation_oracle_count,
        baseline=baseline,
        selected=selected,
        training_oracle=training_oracle,
        validation_oracle=validation_oracle,
        training_oracle_tie_count=training_oracle_ties,
        validation_oracle_tie_count=validation_oracle_ties,
        training_oracle_regret=round(selected.training_loss - training_oracle.training_loss, 12),
        validation_oracle_regret=round(
            selected.validation_loss - validation_oracle.validation_loss, 12
        ),
        baseline_to_selected_training_improvement_rate=round(
            (baseline.training_loss - selected.training_loss) / baseline.training_loss,
            12,
        ),
        baseline_to_selected_validation_improvement_rate=round(
            (baseline.validation_loss - selected.validation_loss) / baseline.validation_loss,
            12,
        ),
        validation_change_by_case=validation_change_by_case,
        generalization_evidence=generalization_evidence,
        qualified=not failed_requirements,
        failed_requirements=tuple(failed_requirements),
    )


def write_frozen_scenario_generalization_artifact(
    path: Path,
    artifact: ScenarioGeneralizationArtifact,
) -> None:
    """Atomically create a new campaign freeze without replacing one."""

    destination = path.resolve()
    if not destination.parent.is_dir():
        raise FileNotFoundError(f"artifact parent directory does not exist: {destination.parent}")
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
    "SCENARIO_GENERALIZATION_SCHEMA_VERSION",
    "ScenarioGeneralizationArtifact",
    "ScenarioGeneralizationPoint",
    "run_scenario_generalization_campaign",
    "write_frozen_scenario_generalization_artifact",
]
