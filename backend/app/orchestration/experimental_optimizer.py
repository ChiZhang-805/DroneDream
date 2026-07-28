"""Database-to-numerics adapter for the seven accuracy-first optimizers."""

from __future__ import annotations

import hashlib
import json
import math
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, cast

from app import models, schemas
from app.optimization.bayesian_optimizers import propose_bayesian_candidates
from app.optimization.candidate_evidence_ledger import (
    candidate_evidence_chain_matches_current,
    candidate_evidence_receipt_required,
)
from app.optimization.cma_optimizers import propose_evolutionary_candidates
from app.optimization.domain import ParameterDomain, SearchSpace
from app.optimization.experimental_types import (
    EXPERIMENTAL_OPTIMIZER_STRATEGIES,
    ExperimentalOptimizerStrategy,
    OptimizerObservation,
    OptimizerObservationRole,
    OptimizerRequest,
)
from app.optimization.experimental_types import (
    canonical_optimizer_seed_value as _canonical_seed_value,
)
from app.optimization.outcome_contract import (
    OPTIMIZER_LEARNING_FAILURE_RATE_LIMIT,
)
from app.optimization.outcome_evidence import (
    authoritative_candidate_trial_outcome_projection,
    candidate_outcome_evidence_required,
    candidate_training_trial_evidence_rows,
)
from app.optimization.outcome_taxonomy import (
    TRIAL_OUTCOME_CLASSES,
    TRIAL_OUTCOME_TAXONOMY_SCHEMA,
    TrialOutcomeClass,
    classify_trial_outcome,
)
from app.optimization.proposal_provenance import (
    OPTIMIZER_SOURCE_EVIDENCE_FIELD,
    OPTIMIZER_SOURCE_EVIDENCE_REQUIRED_FIELD,
    compile_optimizer_source_evidence,
    optimizer_search_space_sha256,
    verify_optimizer_source_evidence,
)
from app.optimization.scenarios import (
    scenario_matrix_for_generation,
    training_matrix_for_fidelity,
)
from app.orchestration import constants
from app.orchestration.optimizer import CandidateProposal
from app.orchestration.parameter_constraints import (
    validator_contract_for_job,
    validator_for_job,
)

_BAYESIAN_STRATEGIES = {
    "constrained_mobo",
    "multi_fidelity_mobo",
    "turbo",
    "saasbo",
}


def is_experimental_strategy(value: str) -> bool:
    return value in EXPERIMENTAL_OPTIMIZER_STRATEGIES


def _legacy_parameter_domains(
    baseline_parameters: dict[str, Any],
) -> list[ParameterDomain]:
    """Build the historical mock domain without pretending its keys are PX4 names."""

    domains: list[ParameterDomain] = []
    for name, (minimum, maximum) in constants.PARAMETER_SAFE_RANGES.items():
        baseline = baseline_parameters.get(name, constants.BASELINE_PARAMETERS[name])
        if (
            isinstance(baseline, bool)
            or not isinstance(baseline, int | float)
            or not math.isfinite(float(baseline))
        ):
            raise ValueError(f"baseline parameter {name} must be finite")
        domains.append(
            ParameterDomain(
                name=name,
                baseline=float(baseline),
                minimum=float(minimum),
                maximum=float(maximum),
            )
        )
    return domains


def search_space_for_job(
    job: models.Job,
    *,
    baseline_parameters: dict[str, Any],
) -> SearchSpace:
    if job.parameter_space_json:
        if not isinstance(job.parameter_space_json, list) or any(
            not isinstance(item, dict) for item in job.parameter_space_json
        ):
            raise ValueError("persisted parameter_space_json must be a list of objects")
        selections = [
            schemas.ParameterSelection(**item)
            for item in job.parameter_space_json
            if item.get("enabled", True)
        ]
        return SearchSpace.from_schema(
            selections,
            candidate_validator=validator_for_job(job),
        )
    return SearchSpace(_legacy_parameter_domains(baseline_parameters))


def _objective_directions(job: models.Job) -> dict[str, str]:
    if job.objective_config_json is None:
        return {}
    config = schemas.ObjectiveConfig(**job.objective_config_json)
    return {objective.metric: objective.direction for objective in config.objectives}


def _trial_metric_payload_is_usable(metric: object) -> bool:
    if not isinstance(metric, Mapping):
        return False

    def finite_number(name: str, *, nonnegative: bool = True) -> bool:
        value = metric.get(name)
        return (
            not isinstance(value, bool)
            and isinstance(value, int | float)
            and math.isfinite(float(value))
            and (not nonnegative or float(value) >= 0.0)
        )

    overshoot = metric.get("overshoot_count")
    return (
        finite_number("rmse")
        and finite_number("max_error")
        and finite_number("completion_time")
        and finite_number("score", nonnegative=False)
        and finite_number("final_error")
        and isinstance(overshoot, int)
        and not isinstance(overshoot, bool)
        and overshoot >= 0
        and all(
            isinstance(metric.get(name), bool)
            for name in (
                "crash_flag",
                "timeout_flag",
                "pass_flag",
                "instability_flag",
            )
        )
    )


def _authoritative_training_outcome_counts(
    *,
    trial_evidence_rows: object,
    aggregate: Mapping[str, Any],
) -> dict[TrialOutcomeClass, int] | None:
    """Classify canonical Trial rows and reject divergent aggregate claims."""

    if (
        isinstance(trial_evidence_rows, str | bytes)
        or not isinstance(trial_evidence_rows, Sequence)
        or any(not isinstance(row, Mapping) for row in trial_evidence_rows)
    ):
        return None
    counts: Counter[TrialOutcomeClass] = Counter()
    for raw_row in trial_evidence_rows:
        row = cast(Mapping[str, object], raw_row)
        outcome = classify_trial_outcome(
            status=row.get("status"),
            failure_code=row.get("failure_code"),
            usable_metric=_trial_metric_payload_is_usable(row.get("metric")),
        )
        counts[outcome] += 1
    result = {outcome: counts.get(outcome, 0) for outcome in TRIAL_OUTCOME_CLASSES}

    declared = aggregate.get(
        "training_trial_outcome_counts",
        aggregate.get("trial_outcome_counts"),
    )
    if declared is not None:
        schema = aggregate.get("trial_outcome_taxonomy_schema")
        if schema not in {None, TRIAL_OUTCOME_TAXONOMY_SCHEMA}:
            return None
        if not isinstance(declared, Mapping):
            return None
        normalized: dict[str, int] = {}
        for outcome in TRIAL_OUTCOME_CLASSES:
            value = declared.get(outcome)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                return None
            normalized[outcome] = value
        if set(declared) != set(TRIAL_OUTCOME_CLASSES) or normalized != result:
            return None
    return result


def _authoritative_training_fidelity(
    job: models.Job,
    *,
    generation_index: int,
    trial_evidence_rows: object,
) -> tuple[float, float] | None:
    """Recompute coverage from the configured matrix and canonical Trial rows."""

    if (
        not isinstance(job.scenario_suite_json, Mapping)
        or isinstance(trial_evidence_rows, str | bytes)
        or not isinstance(trial_evidence_rows, Sequence)
        or not trial_evidence_rows
    ):
        return None
    try:
        suite = schemas.ScenarioSuiteConfig(**job.scenario_suite_json)
        configured_runs = scenario_matrix_for_generation(
            suite,
            generation_index=generation_index,
        )
    except (TypeError, ValueError):
        return None
    full_training_runs = [run for run in configured_runs if not run.holdout]
    if not full_training_runs:
        return None

    declared_requested: float | None = None
    declared_effective: float | None = None
    actual_identities: list[tuple[str, str, int]] = []
    for raw_row in trial_evidence_rows:
        if not isinstance(raw_row, Mapping):
            return None
        scenario_config = raw_row.get("scenario_config")
        if not isinstance(scenario_config, Mapping):
            return None
        case_id = scenario_config.get("scenario_case_id")
        holdout = scenario_config.get("holdout")
        row_generation = scenario_config.get("generation_index")
        scenario_type = raw_row.get("scenario_type")
        seed = raw_row.get("seed")
        if (
            not isinstance(case_id, str)
            or not case_id
            or holdout is not False
            or isinstance(row_generation, bool)
            or not isinstance(row_generation, int)
            or row_generation != generation_index
            or not isinstance(scenario_type, str)
            or not scenario_type
            or isinstance(seed, bool)
            or not isinstance(seed, int)
        ):
            return None
        raw_effective = scenario_config.get("optimizer_fidelity")
        raw_requested = scenario_config.get("optimizer_requested_fidelity")
        if (
            isinstance(raw_effective, bool)
            or not isinstance(raw_effective, int | float)
            or not math.isfinite(float(raw_effective))
            or not 0.0 < float(raw_effective) <= 1.0
            or isinstance(raw_requested, bool)
            or not isinstance(raw_requested, int | float)
            or not math.isfinite(float(raw_requested))
            or not 0.0 < float(raw_requested) <= 1.0
        ):
            return None
        current_effective = float(raw_effective)
        current_requested = float(raw_requested)
        if declared_effective is None:
            declared_effective = current_effective
            declared_requested = current_requested
        elif (
            not math.isclose(
                declared_effective,
                current_effective,
                rel_tol=0.0,
                abs_tol=1e-12,
            )
            or declared_requested is None
            or not math.isclose(
                declared_requested,
                current_requested,
                rel_tol=0.0,
                abs_tol=1e-12,
            )
        ):
            return None
        actual_identities.append((case_id, scenario_type, seed))

    if (
        declared_requested is None
        or declared_effective is None
        or len(actual_identities) != len(set(actual_identities))
    ):
        return None
    try:
        expected_runs = training_matrix_for_fidelity(
            configured_runs,
            declared_requested,
        )
    except ValueError:
        return None
    expected_identities = {(run.case_id, run.scenario_type, run.seed) for run in expected_runs}
    if set(actual_identities) != expected_identities:
        return None
    actual_effective = len(actual_identities) / len(full_training_runs)
    if not math.isclose(
        declared_effective,
        actual_effective,
        rel_tol=0.0,
        abs_tol=1e-12,
    ):
        return None
    return actual_effective, declared_requested


def observations_for_job(
    job: models.Job,
    *,
    search_space: SearchSpace,
    candidates: Iterable[models.CandidateParameterSet],
) -> tuple[OptimizerObservation, ...]:
    directions = _objective_directions(job)
    domain_names = {domain.name for domain in search_space.domains}
    observations: list[OptimizerObservation] = []
    ordered_candidates = sorted(
        candidates,
        key=lambda item: (
            item.generation_index,
            json.dumps(item.parameter_json or {}, sort_keys=True, separators=(",", ":")),
            json.dumps(
                item.aggregated_metric_json or {},
                sort_keys=True,
                separators=(",", ":"),
            ),
            json.dumps(
                item.optimizer_metadata_json or {},
                sort_keys=True,
                separators=(",", ":"),
            ),
        ),
    )
    for candidate in ordered_candidates:
        trial_count = candidate.trial_count
        completed_count = candidate.completed_trial_count
        failed_count = candidate.failed_trial_count
        valid_counts = all(
            not isinstance(value, bool) and isinstance(value, int) and value >= 0
            for value in (trial_count, completed_count, failed_count)
        )
        terminal_trials = completed_count + failed_count if valid_counts else -1
        completed = bool(valid_counts and trial_count > 0 and terminal_trials == trial_count)
        # Pending candidates remain visible solely as reservations.  Bayesian
        # and surrogate fits filter ``completed=False`` while CMA reads the
        # persisted cohort position to avoid dispatching it twice.
        parameter_snapshot = (
            candidate.parameter_json if isinstance(candidate.parameter_json, dict) else {}
        )
        raw_parameters = {
            name: float(value)
            for name, value in parameter_snapshot.items()
            if name in domain_names
            and not isinstance(value, bool)
            and isinstance(value, int | float)
            and math.isfinite(float(value))
        }
        try:
            parameters = search_space.project(raw_parameters)
        except ValueError:
            # Historical rows from an older catalog must remain visible to the
            # user, but an invalid point cannot train the current search space.
            continue
        raw_aggregate = candidate.aggregated_metric_json
        ledger_required = candidate_evidence_receipt_required(candidate)
        evidence_required = candidate_outcome_evidence_required(raw_aggregate) or ledger_required
        trial_evidence_rows = candidate_training_trial_evidence_rows(candidate)
        if ledger_required and not candidate_evidence_chain_matches_current(
            candidate,
            raw_aggregate,
        ):
            raw_aggregate = {}
        aggregate = authoritative_candidate_trial_outcome_projection(
            candidate_id=candidate.id,
            generation_index=candidate.generation_index,
            parameter_snapshot=parameter_snapshot,
            trial_evidence_rows=trial_evidence_rows,
            aggregate=raw_aggregate,
        )
        if completed and evidence_required and not aggregate:
            # Evidence-marked rows are all-or-nothing. A stale parameter,
            # Trial, artifact, or attempt binding must not become either an
            # objective or a false constraint observation.
            continue
        outcome_counts = (
            _authoritative_training_outcome_counts(
                trial_evidence_rows=trial_evidence_rows,
                aggregate=aggregate,
            )
            if completed
            else None
        )
        has_canonical_trial_rows = bool(trial_evidence_rows)
        if completed and has_canonical_trial_rows and outcome_counts is None:
            continue
        learning_outcome_count = (
            outcome_counts["success"] + outcome_counts["domain_failure"]
            if outcome_counts is not None
            else 0
        )
        if completed and has_canonical_trial_rows and learning_outcome_count == 0:
            # Infrastructure failures, cancellations, invalid evidence, and
            # unknown-only histories are quarantined. They remain visible in
            # reports but cannot change a model, proposal, CMA state, or seed.
            continue
        raw_objectives = aggregate.get("objective_values", {})
        objectives = {
            str(name): float(value)
            for name, value in (raw_objectives.items() if isinstance(raw_objectives, dict) else [])
            if not isinstance(value, bool)
            and isinstance(value, int | float)
            and math.isfinite(float(value))
        }
        # Optimizers need direction-aware violation margins rather than raw
        # metric values.  A raw value of ``9`` can be a small violation for a
        # ``>= 10`` contract while ``0`` is severe; ranking ``abs(raw)`` would
        # reverse that ordering.  Aggregation already computes non-negative,
        # direction-aware margins for every constraint.
        raw_constraints = aggregate.get("constraint_violations", {})
        constraints = {
            str(name): float(value)
            for name, value in (
                raw_constraints.items() if isinstance(raw_constraints, dict) else []
            )
            if not isinstance(value, bool)
            and isinstance(value, int | float)
            and math.isfinite(float(value))
        }
        # ``aggregated_score`` includes hard-constraint penalties used for the
        # public leaderboard.  Feeding that penalty back into the objective GP
        # double-counts feasibility and can swamp the real control objective.
        # Train objective models on the unpenalized scalar loss and model
        # feasibility/violations separately.
        raw_scalar_loss = aggregate.get("scalar_loss")
        loss = (
            float(raw_scalar_loss)
            if isinstance(raw_scalar_loss, int | float)
            and not isinstance(raw_scalar_loss, bool)
            and math.isfinite(float(raw_scalar_loss))
            else None
            if evidence_required
            else candidate.aggregated_score
        )
        if (
            isinstance(loss, bool)
            or (loss is not None and not isinstance(loss, int | float))
            or (loss is not None and not math.isfinite(float(loss)))
        ):
            loss = None
        if learning_outcome_count > 0 and outcome_counts is not None:
            failure_rate = outcome_counts["domain_failure"] / learning_outcome_count
        else:
            raw_failure_rate = aggregate.get(
                "optimizer_learning_failure_rate",
                aggregate.get(
                    "training_failure_rate",
                    aggregate.get("failure_rate", 0.0),
                ),
            )
            failure_rate = (
                max(0.0, min(1.0, float(raw_failure_rate)))
                if not isinstance(raw_failure_rate, bool)
                and isinstance(raw_failure_rate, int | float)
                and math.isfinite(float(raw_failure_rate))
                else 0.0
            )
        metadata = (
            candidate.optimizer_metadata_json
            if isinstance(candidate.optimizer_metadata_json, dict)
            else {}
        )
        raw_fidelity = metadata.get(
            "effective_fidelity",
            metadata.get("fidelity", 1.0),
        )
        raw_requested_fidelity = metadata.get(
            "requested_fidelity",
            metadata.get("fidelity", 1.0),
        )
        valid_fidelity = (
            not isinstance(raw_fidelity, bool)
            and isinstance(raw_fidelity, int | float)
            and math.isfinite(float(raw_fidelity))
            and 0.0 < float(raw_fidelity) <= 1.0
        )
        valid_requested_fidelity = (
            not isinstance(raw_requested_fidelity, bool)
            and isinstance(raw_requested_fidelity, int | float)
            and math.isfinite(float(raw_requested_fidelity))
            and 0.0 < float(raw_requested_fidelity) <= 1.0
        )
        fidelity = float(cast(int | float, raw_fidelity)) if valid_fidelity else 0.05
        requested_fidelity = (
            float(cast(int | float, raw_requested_fidelity)) if valid_requested_fidelity else 0.05
        )
        source_evidence = None
        raw_source_strategy = metadata.get("strategy")
        if metadata.get(OPTIMIZER_SOURCE_EVIDENCE_REQUIRED_FIELD) is True:
            if (
                raw_source_strategy not in EXPERIMENTAL_OPTIMIZER_STRATEGIES
                or not valid_fidelity
                or not valid_requested_fidelity
            ):
                continue
            trial_fidelity = _authoritative_training_fidelity(
                job,
                generation_index=candidate.generation_index,
                trial_evidence_rows=trial_evidence_rows,
            )
            if trial_fidelity is None or not (
                math.isclose(
                    trial_fidelity[0],
                    fidelity,
                    rel_tol=0.0,
                    abs_tol=1e-12,
                )
                and math.isclose(
                    trial_fidelity[1],
                    requested_fidelity,
                    rel_tol=0.0,
                    abs_tol=1e-12,
                )
            ):
                # Candidate metadata never overrides actual dispatched Trial
                # coverage.  Missing or mixed fidelity rows are not history.
                continue
            source_evidence = verify_optimizer_source_evidence(
                metadata.get(OPTIMIZER_SOURCE_EVIDENCE_FIELD),
                strategy=cast(
                    ExperimentalOptimizerStrategy,
                    raw_source_strategy,
                ),
                generation_index=candidate.generation_index,
                parameters=parameters,
                search_space_sha256=optimizer_search_space_sha256(
                    search_space,
                    validator_contract=validator_contract_for_job(job),
                ),
                requested_fidelity=requested_fidelity,
                effective_fidelity=fidelity,
            )
            if source_evidence is None:
                # A modern Candidate with stale strategy, parameter, source-role,
                # fidelity, or content identity is not optimizer history.
                continue
        if source_evidence is None:
            fidelity = max(0.05, min(1.0, fidelity))
            requested_fidelity = max(
                0.05,
                min(1.0, requested_fidelity),
            )
        has_objective_evidence = loss is not None or bool(objectives)
        role: OptimizerObservationRole
        if not completed:
            role = "pending_reservation"
            failure_rate = 0.0
        elif has_objective_evidence:
            role = "objective"
        elif (
            has_canonical_trial_rows
            and outcome_counts is not None
            and outcome_counts["domain_failure"] > 0
        ):
            # A trusted physical/simulation-domain failure carries useful
            # feasibility evidence even when no objective metric survived.
            role = "constraint_only"
            objectives = {}
            loss = None
        else:
            # Legacy objective aggregates remain readable, but an ambiguous
            # terminal row with no objective and no canonical domain-failure
            # evidence cannot teach the optimizer.
            continue
        aggregate_feasible = aggregate.get("feasible")
        feasible_marker = True if "feasible" not in aggregate else aggregate_feasible is True
        feasible = (
            role == "objective"
            and feasible_marker
            and failure_rate < OPTIMIZER_LEARNING_FAILURE_RATE_LIMIT
        )
        raw_optimizer_strategy = (
            source_evidence.learning_owner or source_evidence.sources[0].child_strategy
            if source_evidence is not None
            else metadata.get("child_strategy") or metadata.get("strategy")
        )
        candidate_id = candidate.id
        if not candidate_id:
            identity_payload = json.dumps(
                {
                    "generation": candidate.generation_index,
                    "parameters": parameters,
                    "metadata": metadata,
                },
                sort_keys=True,
                separators=(",", ":"),
            )
            candidate_id = (
                "unpersisted-" + hashlib.sha256(identity_payload.encode("utf-8")).hexdigest()[:24]
            )
        observations.append(
            OptimizerObservation(
                candidate_id=candidate_id,
                generation_index=candidate.generation_index,
                parameters=parameters,
                unit_vector=search_space.to_unit_vector(parameters),
                loss=float(loss) if loss is not None else None,
                objectives=objectives,
                objective_directions=directions,
                constraints=constraints,
                feasible=feasible,
                failure_rate=failure_rate,
                fidelity=fidelity,
                requested_fidelity=requested_fidelity,
                optimizer_strategy=(
                    raw_optimizer_strategy
                    if isinstance(raw_optimizer_strategy, str) and raw_optimizer_strategy
                    else None
                ),
                optimizer_metadata=dict(metadata),
                completed=completed,
                role=role,
            )
        )
    return tuple(observations)


def _seed_for_request(
    *,
    job: models.Job,
    strategy: str,
    generation_index: int,
    observations: tuple[OptimizerObservation, ...],
) -> int:
    history = [
        cast(
            dict[str, Any],
            _canonical_seed_value(
                {
                    "generation": item.generation_index,
                    "unit_vector": item.unit_vector,
                    "loss": item.loss,
                    "feasible": item.feasible,
                    "failure_rate": item.failure_rate,
                    "fidelity": item.fidelity,
                    "requested_fidelity": item.requested_fidelity,
                    "objectives": item.objectives,
                    "constraints": item.constraints,
                    "optimizer_strategy": item.optimizer_strategy,
                    "optimizer_metadata": _optimizer_seed_metadata(item.optimizer_metadata),
                    "completed": item.completed,
                    # Preserve historical objective-only seeds while making
                    # newly explicit non-objective roles seed-visible.
                    **({"role": item.role} if item.role != "objective" else {}),
                }
            ),
        )
        for item in observations
    ]
    history.sort(key=lambda item: json.dumps(item, sort_keys=True, separators=(",", ":")))
    payload = {
        "strategy": strategy,
        "generation_index": generation_index,
        "parameter_space": job.parameter_space_json,
        "objective_config": job.objective_config_json,
        "scenario_suite": job.scenario_suite_json,
        "vehicle_profile": job.vehicle_profile_json,
        "baseline_parameters": job.baseline_parameter_json,
        "history": history,
    }
    canonical_payload = _canonical_seed_value(payload)
    digest = hashlib.sha256(
        json.dumps(
            canonical_payload,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()
    return int(digest[:16], 16)


def _optimizer_seed_metadata(metadata: Mapping[str, Any]) -> dict[str, Any]:
    """Remove provenance-only schema upgrades from numerical RNG identity."""

    projected = {
        key: value
        for key, value in metadata.items()
        if key
        not in {
            OPTIMIZER_SOURCE_EVIDENCE_FIELD,
            OPTIMIZER_SOURCE_EVIDENCE_REQUIRED_FIELD,
            "optimizer_source_role",
        }
    }
    if projected.get("portfolio_sources_schema") == ("dronedream.portfolio-sources/v2"):
        projected["portfolio_sources_schema"] = "dronedream.portfolio-sources/v1"
    raw_sources = projected.get("portfolio_sources")
    if isinstance(raw_sources, list):
        projected["portfolio_sources"] = [
            {key: value for key, value in source.items() if key != "source_role"}
            if isinstance(source, Mapping)
            else source
            for source in raw_sources
        ]
    return projected


def _public_seed_token(value: object) -> str | None:
    """Encode an optimizer seed without losing uint64 bits in JavaScript."""

    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return f"{value & ((1 << 64) - 1):016x}"
    if isinstance(value, str):
        normalized = value.lower().removeprefix("0x")
        if (
            normalized
            and len(normalized) <= 16
            and all(character in "0123456789abcdef" for character in normalized)
        ):
            return normalized.zfill(16)
    return None


def _proposal_fidelity(value: object, *, field_name: str) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, int | float)
        or not math.isfinite(float(value))
        or not 0.0 < float(value) <= 1.0
    ):
        raise RuntimeError(f"optimizer proposal {field_name} must be inside (0, 1]")
    return float(value)


@dataclass(frozen=True)
class PreparedExperimentalGeneration:
    """Database-free numerical request safe to execute outside the ORM thread."""

    strategy: ExperimentalOptimizerStrategy
    generation_index: int
    batch_size: int
    search_space: SearchSpace
    request: OptimizerRequest
    search_space_sha256: str


def prepare_experimental_generation(
    *,
    job: models.Job,
    candidates: list[models.CandidateParameterSet],
    baseline_parameters: dict[str, Any],
    generation_index: int,
    batch_size: int,
    fidelity_mapping: tuple[tuple[float, float], ...] = (),
    required_fidelity: float | None = None,
    strategy_override: ExperimentalOptimizerStrategy | None = None,
) -> PreparedExperimentalGeneration | None:
    """Compile one immutable numerical request while still on the ORM thread."""

    strategy_value = strategy_override or job.optimizer_strategy
    if not is_experimental_strategy(strategy_value):
        raise ValueError(f"unsupported experimental strategy: {strategy_value}")
    if batch_size < 1:
        return None
    search_space = search_space_for_job(job, baseline_parameters=baseline_parameters)
    observations = observations_for_job(
        job,
        search_space=search_space,
        candidates=candidates,
    )
    strategy = cast(ExperimentalOptimizerStrategy, strategy_value)
    objective_config = schemas.ObjectiveConfig(**(job.objective_config_json or {}))
    request = OptimizerRequest(
        strategy=strategy,
        generation_index=generation_index,
        batch_size=batch_size,
        random_seed=_seed_for_request(
            job=job,
            strategy=strategy,
            generation_index=generation_index,
            observations=observations,
        ),
        observations=observations,
        objective_weights=tuple(
            (objective.metric, objective.weight) for objective in objective_config.objectives
        ),
        objective_normalizations=tuple(
            (objective.metric, objective.normalization) for objective in objective_config.objectives
        ),
        fidelity_mapping=fidelity_mapping,
        required_fidelity=required_fidelity,
    )
    return PreparedExperimentalGeneration(
        strategy=strategy,
        generation_index=generation_index,
        batch_size=batch_size,
        search_space=search_space,
        request=request,
        search_space_sha256=optimizer_search_space_sha256(
            search_space,
            validator_contract=validator_contract_for_job(job),
        ),
    )


def execute_prepared_experimental_generation(
    prepared: PreparedExperimentalGeneration,
) -> list[CandidateProposal]:
    """Run one prepared pure numerical optimizer request."""

    strategy = prepared.strategy
    generation_index = prepared.generation_index
    batch_size = prepared.batch_size
    search_space = prepared.search_space
    request = prepared.request
    fidelity_mapping = request.fidelity_mapping
    required_fidelity = request.required_fidelity
    if strategy in _BAYESIAN_STRATEGIES:
        proposals = propose_bayesian_candidates(search_space, request)
    else:
        proposals = propose_evolutionary_candidates(search_space, request)
    if len(proposals) > batch_size:
        raise RuntimeError(
            f"optimizer {strategy} returned {len(proposals)} proposals for batch {batch_size}"
        )
    converted: list[CandidateProposal] = []
    seen_parameters: set[str] = set()
    expected_parameter_names = {domain.name for domain in search_space.domains}
    for proposal in proposals:
        proposal_metadata = dict(proposal.metadata)
        child_random_seed = proposal_metadata.pop("random_seed", None)
        request_seed = f"{request.random_seed:016x}"
        metadata = dict(proposal_metadata)
        # Proposal diagnostics may never overwrite orchestration identity.
        metadata["strategy"] = strategy
        metadata["generation_index"] = generation_index
        metadata["random_seed"] = request_seed
        metadata["request_random_seed"] = request_seed
        metadata["fidelity"] = _proposal_fidelity(
            proposal_metadata.get("fidelity", 1.0),
            field_name="fidelity",
        )
        for fidelity_field in ("requested_fidelity", "effective_fidelity"):
            if fidelity_field in metadata:
                metadata[fidelity_field] = _proposal_fidelity(
                    metadata[fidelity_field],
                    field_name=fidelity_field,
                )
        if strategy == "optimizer_portfolio":
            metadata["portfolio_random_seed"] = f"{request.random_seed:016x}"
            safe_child_seed = _public_seed_token(
                child_random_seed
                if child_random_seed is not None
                else metadata.get("child_random_seed")
            )
            if safe_child_seed is not None:
                metadata["child_random_seed"] = safe_child_seed
        uses_multi_fidelity = strategy == "multi_fidelity_mobo" or (
            strategy == "optimizer_portfolio"
            and metadata.get("child_strategy") == "multi_fidelity_mobo"
        )
        if uses_multi_fidelity:
            metadata["fidelity_semantics"] = "scenario_and_seed_coverage"
            metadata.setdefault("requested_fidelity", metadata.get("fidelity", 1.0))
            metadata.setdefault("effective_fidelity", metadata.get("fidelity", 1.0))
            requested = _proposal_fidelity(
                metadata["requested_fidelity"],
                field_name="requested_fidelity",
            )
            effective = next(
                (
                    mapped
                    for level, mapped in fidelity_mapping
                    if math.isclose(level, requested, abs_tol=1e-9)
                ),
                requested,
            )
            metadata.update(
                {
                    "requested_fidelity": requested,
                    "effective_fidelity": effective,
                    "fidelity": effective,
                }
            )
            raw_portfolio_sources = metadata.get("portfolio_sources")
            if isinstance(raw_portfolio_sources, list):
                metadata["portfolio_sources"] = [
                    {
                        **source,
                        "effective_fidelity": effective,
                    }
                    if isinstance(source, Mapping) and source.get("materialized") is True
                    else source
                    for source in raw_portfolio_sources
                ]
        if uses_multi_fidelity and required_fidelity is not None:
            requested = _proposal_fidelity(
                metadata.get("requested_fidelity", metadata["fidelity"]),
                field_name="requested_fidelity",
            )
            effective = _proposal_fidelity(
                metadata.get("effective_fidelity", metadata["fidelity"]),
                field_name="effective_fidelity",
            )
            if requested < required_fidelity - 1e-9 or effective < required_fidelity - 1e-9:
                raise RuntimeError(
                    "multi-fidelity optimizer violated the required verification fidelity"
                )
            metadata["forced_full_fidelity_verification"] = True
        if set(proposal.parameters) != expected_parameter_names:
            raise RuntimeError(f"optimizer {strategy} returned an incomplete parameter snapshot")
        try:
            projected_parameters = search_space.project(proposal.parameters)
        except ValueError as exc:
            raise RuntimeError(
                f"optimizer {strategy} returned an invalid parameter proposal"
            ) from exc
        signature = json.dumps(
            projected_parameters,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        if signature in seen_parameters:
            raise RuntimeError(f"optimizer {strategy} returned duplicate proposals")
        seen_parameters.add(signature)
        source_evidence = compile_optimizer_source_evidence(
            strategy=strategy,
            generation_index=generation_index,
            parameters=projected_parameters,
            search_space_sha256=prepared.search_space_sha256,
            metadata=metadata,
        )
        metadata[OPTIMIZER_SOURCE_EVIDENCE_REQUIRED_FIELD] = True
        metadata[OPTIMIZER_SOURCE_EVIDENCE_FIELD] = source_evidence.model_dump(mode="json")
        converted.append(
            CandidateProposal(
                generation_index=generation_index,
                label=proposal.label,
                strategy=proposal.rationale,
                parameters=projected_parameters,
                metadata=metadata,
            )
        )
    return converted


def propose_experimental_generation(
    *,
    job: models.Job,
    candidates: list[models.CandidateParameterSet],
    baseline_parameters: dict[str, Any],
    generation_index: int,
    batch_size: int,
    fidelity_mapping: tuple[tuple[float, float], ...] = (),
    required_fidelity: float | None = None,
    strategy_override: ExperimentalOptimizerStrategy | None = None,
) -> list[CandidateProposal]:
    """Generate a deterministic batch for one of the seven strategies."""

    prepared = prepare_experimental_generation(
        job=job,
        candidates=candidates,
        baseline_parameters=baseline_parameters,
        generation_index=generation_index,
        batch_size=batch_size,
        fidelity_mapping=fidelity_mapping,
        required_fidelity=required_fidelity,
        strategy_override=strategy_override,
    )
    return (
        []
        if prepared is None
        else execute_prepared_experimental_generation(prepared)
    )


__all__ = [
    "PreparedExperimentalGeneration",
    "execute_prepared_experimental_generation",
    "is_experimental_strategy",
    "observations_for_job",
    "prepare_experimental_generation",
    "propose_experimental_generation",
    "search_space_for_job",
]
