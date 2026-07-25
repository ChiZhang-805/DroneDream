"""Job-level orchestration: claim QUEUED jobs, create baseline + optimizer
candidates, and dispatch their trials.

The job manager only mutates Job/CandidateParameterSet/Trial rows. It never
executes a trial directly — trial-level work is done by the trial executor
from a separate transaction.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from typing import Any, cast

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app import models, schemas
from app.optimization.experimental_types import ExperimentalOptimizerStrategy
from app.optimization.scenarios import ScenarioRun, scenario_matrix
from app.orchestration import constants
from app.orchestration.aggregation import candidate_is_publishable
from app.orchestration.cma_es_optimizer import propose_next_generation
from app.orchestration.events import record_event
from app.orchestration.experimental_optimizer import (
    is_experimental_strategy,
    propose_experimental_generation,
)
from app.orchestration.llm_parameter_proposer import (
    LlmProposal,
    OpenAIClientLike,
    propose_candidates,
)
from app.orchestration.optimizer import (
    CandidateProposal,
    generate_candidates,
    generate_selected_parameter_candidates,
)
from app.orchestration.parameter_constraints import validator_for_job
from app.simulator.base import (
    FAILURE_ADAPTER_UNAVAILABLE,
    FAILURE_ARTIFACT_PERSISTENCE,
    FAILURE_RESULT_PERSISTENCE,
)

logger = logging.getLogger("drone_dream.orchestration.job_manager")


@dataclass(frozen=True)
class LlmDispatchResult:
    """Outcome of one attempt to dispatch the next GPT generation."""

    status: str
    dispatched_candidates: int = 0
    error: str | None = None


@dataclass(frozen=True)
class AdaptiveDispatchResult:
    """Outcome of one attempt to dispatch next adaptive-optimizer generation."""

    status: str
    dispatched_candidates: int = 0


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _configured_scenario_runs(
    job: models.Job,
    *,
    generation_index: int,
) -> list[ScenarioRun] | None:
    """Return the explicit fair matrix, or None for the legacy scenario policy."""

    if not job.scenario_suite_json:
        return None
    suite = schemas.ScenarioSuiteConfig(**job.scenario_suite_json)
    runs = scenario_matrix(suite)
    if suite.common_random_numbers or generation_index == 0:
        return runs
    # Users may explicitly disable common random numbers. Keep that mode
    # deterministic while giving each generation a disjoint seed range.
    offset = generation_index * 1_000_003
    # Keep derived seeds inside the portable signed 32-bit range accepted by
    # the request schema and common simulator/SDK interfaces.
    seed_modulus = 2_147_483_648
    return [
        ScenarioRun(
            case_id=run.case_id,
            scenario_type=run.scenario_type,
            seed=(run.seed + offset) % seed_modulus,
            weight=run.weight,
            holdout=run.holdout,
            config=run.config,
        )
        for run in runs
    ]


def _scenario_payload(
    job: models.Job,
    run: ScenarioRun,
    *,
    source: str,
    generation_index: int,
) -> dict[str, Any]:
    base = {
        "scenario": run.scenario_type,
        "source": source,
        "generation_index": generation_index,
        **run.persistence_config(),
    }
    return constants.with_advanced_scenario(base, job.advanced_scenario_config_json)


def _baseline_parameters_for_job(job: models.Job) -> dict[str, float]:
    params = dict(constants.BASELINE_PARAMETERS)
    if job.baseline_parameter_json:
        if not isinstance(job.baseline_parameter_json, dict):
            raise ValueError("baseline_parameter_json must be an object")
        for key in constants.BASELINE_PARAMETERS:
            value = job.baseline_parameter_json.get(key)
            if value is None:
                continue
            if isinstance(value, bool) or not isinstance(value, int | float):
                raise ValueError(f"baseline parameter {key} must be numeric")
            numeric = float(value)
            if not math.isfinite(numeric):
                raise ValueError(f"baseline parameter {key} must be finite")
            lo, hi = constants.PARAMETER_SAFE_RANGES[key]
            params[key] = round(max(lo, min(hi, numeric)), 6)
    # The extensible parameter space is authoritative for enabled selections.
    # Legacy six-parameter defaults remain in the dict for the existing mock
    # simulator and heuristic optimizer until those consumers are fully
    # catalog-driven.
    parameter_space = job.parameter_space_json or []
    if not isinstance(parameter_space, list):
        raise ValueError("parameter_space_json must be an array")
    seen_names: set[str] = set()
    for selection in parameter_space:
        if not isinstance(selection, dict):
            raise ValueError("parameter_space_json entries must be objects")
        enabled = selection.get("enabled", True)
        if not isinstance(enabled, bool):
            raise ValueError("parameter enabled flags must be boolean")
        if not enabled:
            continue
        name = selection.get("name")
        baseline = selection.get("baseline")
        if not isinstance(name, str) or not name.strip():
            raise ValueError("enabled parameters require a non-empty name")
        name = name.strip().upper()
        if name in seen_names:
            raise ValueError(f"duplicate selected parameter {name}")
        seen_names.add(name)
        if isinstance(baseline, bool) or not isinstance(baseline, int | float):
            raise ValueError(f"baseline parameter {name} must be numeric")
        value = float(baseline)
        if not math.isfinite(value):
            raise ValueError(f"baseline parameter {name} must be finite")
        params[name] = value
    return params


def _complete_candidate_parameters(
    job: models.Job, proposed: dict[str, float]
) -> dict[str, float]:
    """Overlay tuned values onto the invariant job-level controller inputs.

    Schedule/controller values that are not selected for tuning must remain
    identical across baseline and every candidate; otherwise candidates would
    fly different commands and the comparison would not be causal.
    """

    if not isinstance(proposed, dict):
        raise ValueError("proposed parameters must be an object")
    completed = _baseline_parameters_for_job(job)
    allowed_names = set(constants.BASELINE_PARAMETERS)
    allowed_names.update(
        str(item.get("name", "")).strip().upper()
        for item in (job.parameter_space_json or [])
        if isinstance(item, dict) and item.get("enabled", True) is True
    )
    normalized: dict[str, float] = {}
    for raw_name, raw_value in proposed.items():
        if not isinstance(raw_name, str) or not raw_name.strip():
            raise ValueError("proposed parameter names must be non-empty strings")
        name = raw_name.strip()
        canonical_name = name if name in constants.BASELINE_PARAMETERS else name.upper()
        if canonical_name not in allowed_names:
            raise ValueError(f"proposal contains unselected parameter {name}")
        if isinstance(raw_value, bool) or not isinstance(raw_value, int | float):
            raise ValueError(f"proposed parameter {name} must be numeric")
        value = float(raw_value)
        if not math.isfinite(value):
            raise ValueError(f"proposed parameter {name} must be finite")
        normalized[canonical_name] = value
    completed.update(normalized)
    return completed


def _proposal_fingerprint(
    job: models.Job, parameters: dict[str, Any]
) -> tuple[tuple[str, float], ...] | None:
    selected_names = {
        str(item.get("name", "")).strip().upper()
        for item in (job.parameter_space_json or [])
        if isinstance(item, dict)
        and item.get("enabled", True)
        and str(item.get("name", "")).strip()
    }
    keys = selected_names or set(constants.BASELINE_PARAMETERS)
    values: list[tuple[str, float]] = []
    for key in sorted(keys):
        value = parameters.get(key)
        if isinstance(value, bool) or not isinstance(value, int | float):
            return None
        numeric = float(value)
        if not math.isfinite(numeric):
            return None
        values.append((key, round(numeric, 12)))
    return tuple(values)


def _optimizer_fidelity(metadata: object) -> float:
    """Return a validated optimizer fidelity for persisted or proposed metadata."""

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


def _optimizer_requested_fidelity(metadata: object) -> float:
    """Return the nominal level, preserving whether holdouts were verified."""

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


def _uses_multi_fidelity(metadata: object) -> bool:
    if not isinstance(metadata, dict):
        return False
    return (
        metadata.get("strategy") == "multi_fidelity_mobo"
        or metadata.get("child_strategy") == "multi_fidelity_mobo"
    )


ProposalIdentity = tuple[tuple[tuple[str, float], ...], float, bool]


def _proposal_identity(
    job: models.Job,
    parameters: dict[str, Any],
    optimizer_metadata: object = None,
) -> ProposalIdentity | None:
    """Return the persisted identity used for cross- and within-batch deduplication.

    A multi-fidelity observation at reduced coverage is intentionally distinct
    from a full verification of the same controller parameters.  Nominal
    verification class is retained separately because an effective coverage
    may be rounded to the same fraction for a very small scenario matrix.
    """

    fingerprint = _proposal_fingerprint(job, parameters)
    if fingerprint is None:
        return None
    return (
        fingerprint,
        round(_optimizer_fidelity(optimizer_metadata), 12),
        _optimizer_requested_fidelity(optimizer_metadata) >= 1.0 - 1e-9,
    )


_TRANSIENT_FULL_VERIFICATION_FAILURES = {
    FAILURE_ADAPTER_UNAVAILABLE,
    FAILURE_ARTIFACT_PERSISTENCE,
    FAILURE_RESULT_PERSISTENCE,
}


def _allows_transient_full_verification_retry(
    candidate: models.CandidateParameterSet,
) -> bool:
    """Allow one conservative retry after an unambiguous infrastructure failure.

    Simulation errors, timeouts, instability, invalid parameters, cancelled
    trials, and failed holdout criteria are evidence about the candidate rather
    than a safe reason to repeat it.  Only terminal, nominally full-fidelity
    optimizer candidates whose failures are all persistence/adapter failures
    qualify.
    """

    if candidate.is_baseline or candidate.source_type not in {
        "optimizer",
        "llm_optimizer",
    }:
        return False
    if (
        _optimizer_requested_fidelity(candidate.optimizer_metadata_json)
        < 1.0 - 1e-9
        or int(candidate.trial_count or 0) <= 0
        or int(candidate.failed_trial_count or 0) <= 0
    ):
        return False
    trials = list(candidate.trials)
    if len(trials) != int(candidate.trial_count or 0):
        return False
    failed_trials = [trial for trial in trials if trial.status == "FAILED"]
    if len(failed_trials) != int(candidate.failed_trial_count or 0):
        return False
    if any(trial.status not in {"COMPLETED", "FAILED"} for trial in trials):
        return False
    return bool(failed_trials) and all(
        trial.failure_code in _TRANSIENT_FULL_VERIFICATION_FAILURES
        for trial in failed_trials
    )


def _is_duplicate_proposal(
    job: models.Job,
    proposed: dict[str, float],
    *,
    optimizer_metadata: dict[str, Any] | None = None,
) -> bool:
    identity = _proposal_identity(job, proposed, optimizer_metadata)
    if identity is None:
        return True
    matches = [
        candidate
        for candidate in job.candidates
        if _proposal_identity(
            job,
            candidate.parameter_json or {},
            candidate.optimizer_metadata_json,
        )
        == identity
    ]
    if not matches:
        return False
    # One full-fidelity infrastructure failure may be retried once.  Once a
    # second identical row exists, or if the first row failed for any other
    # reason, the proposal remains a duplicate.
    return not (
        identity[2]
        and len(matches) == 1
        and _allows_transient_full_verification_retry(matches[0])
    )


def _create_baseline_candidate(db: Session, job: models.Job) -> models.CandidateParameterSet:
    """Persist the baseline CandidateParameterSet for a job."""

    configured_runs = _configured_scenario_runs(job, generation_index=0)
    scenario_count = (
        len(configured_runs) if configured_runs is not None else len(constants.BASELINE_SCENARIOS)
    )
    candidate = models.CandidateParameterSet(
        job_id=job.id,
        generation_index=0,
        source_type="baseline",
        label="baseline",
        parameter_json=_baseline_parameters_for_job(job),
        is_baseline=True,
        trial_count=scenario_count,
    )
    db.add(candidate)
    db.flush()
    job.baseline_candidate_id = candidate.id
    record_event(
        db,
        job.id,
        "baseline_started",
        {"candidate_id": candidate.id, "scenario_count": scenario_count},
    )
    return candidate


def _create_llm_candidate(
    db: Session,
    job: models.Job,
    proposal: LlmProposal,
    *,
    generation_index: int,
    trials_per_candidate: int,
    raw_response: dict[str, Any] | None,
) -> models.CandidateParameterSet:
    candidate = models.CandidateParameterSet(
        job_id=job.id,
        generation_index=generation_index,
        source_type="llm_optimizer",
        label=proposal.label,
        parameter_json=_complete_candidate_parameters(job, proposal.parameters),
        is_baseline=False,
        trial_count=trials_per_candidate,
        proposal_reason=proposal.rationale,
        llm_response_json=raw_response,
    )
    db.add(candidate)
    db.flush()
    record_event(
        db,
        job.id,
        "candidate_generated_from_llm",
        {
            "candidate_id": candidate.id,
            "label": proposal.label,
            "generation_index": generation_index,
            "parameters": proposal.parameters,
        },
    )
    return candidate


def _dispatch_llm_candidate_trials(
    db: Session,
    job: models.Job,
    candidate: models.CandidateParameterSet,
    trials_per_candidate: int,
) -> list[models.Trial]:
    trials: list[models.Trial] = []
    now = _now()
    configured_runs = _configured_scenario_runs(
        job, generation_index=candidate.generation_index
    )
    if configured_runs is not None:
        for run in configured_runs:
            trial = models.Trial(
                job_id=job.id,
                candidate_id=candidate.id,
                seed=run.seed,
                scenario_type=run.scenario_type,
                scenario_config_json=_scenario_payload(
                    job,
                    run,
                    source="llm_optimizer",
                    generation_index=candidate.generation_index,
                ),
                status="PENDING",
                queued_at=now,
            )
            db.add(trial)
            db.flush()
            trials.append(trial)
            record_event(
                db,
                job.id,
                "trial_dispatched",
                {
                    "trial_id": trial.id,
                    "candidate_id": candidate.id,
                    "candidate_source": "llm_optimizer",
                    "scenario": run.scenario_type,
                    "scenario_case_id": run.case_id,
                    "seed": run.seed,
                    "generation_index": candidate.generation_index,
                },
            )
        candidate.trial_count = len(trials)
        return trials
    scenarios = constants.OPTIMIZER_SCENARIOS
    for idx in range(trials_per_candidate):
        scenario = scenarios[idx % len(scenarios)]
        seed = constants.optimizer_seed_for(
            candidate.generation_index * 10 + idx, scenario
        )
        trial = models.Trial(
            job_id=job.id,
            candidate_id=candidate.id,
            seed=seed,
            scenario_type=scenario,
            scenario_config_json=constants.with_advanced_scenario(
                constants.optimizer_scenario_config(
                    scenario,
                    candidate_index=candidate.generation_index,
                    seed=seed,
                ),
                job.advanced_scenario_config_json,
            ),
            status="PENDING",
            queued_at=now,
        )
        db.add(trial)
        db.flush()
        trials.append(trial)
        record_event(
            db,
            job.id,
            "trial_dispatched",
            {
                "trial_id": trial.id,
                "candidate_id": candidate.id,
                "candidate_source": "llm_optimizer",
                "scenario": scenario,
                "generation_index": candidate.generation_index,
            },
        )
    return trials


def _dispatch_baseline_trials(
    db: Session,
    job: models.Job,
    candidate: models.CandidateParameterSet,
) -> list[models.Trial]:
    """Create PENDING Trial rows for every baseline scenario."""

    trials: list[models.Trial] = []
    now = _now()
    configured_runs = _configured_scenario_runs(job, generation_index=0)
    if configured_runs is not None:
        for run in configured_runs:
            trial = models.Trial(
                job_id=job.id,
                candidate_id=candidate.id,
                seed=run.seed,
                scenario_type=run.scenario_type,
                scenario_config_json=_scenario_payload(
                    job, run, source="baseline", generation_index=0
                ),
                status="PENDING",
                queued_at=now,
            )
            db.add(trial)
            db.flush()
            trials.append(trial)
            record_event(
                db,
                job.id,
                "trial_dispatched",
                {
                    "trial_id": trial.id,
                    "candidate_id": candidate.id,
                    "candidate_source": "baseline",
                    "scenario": run.scenario_type,
                    "scenario_case_id": run.case_id,
                    "seed": run.seed,
                },
            )
        candidate.trial_count = len(trials)
        return trials
    for scenario in constants.BASELINE_SCENARIOS:
        seed = constants.SCENARIO_SEEDS[scenario]
        trial = models.Trial(
            job_id=job.id,
            candidate_id=candidate.id,
            seed=seed,
            scenario_type=scenario,
            scenario_config_json=constants.with_advanced_scenario(
                constants.baseline_scenario_config(scenario),
                job.advanced_scenario_config_json,
            ),
            status="PENDING",
            queued_at=now,
        )
        db.add(trial)
        db.flush()
        trials.append(trial)
        record_event(
            db,
            job.id,
            "trial_dispatched",
            {
                "trial_id": trial.id,
                "candidate_id": candidate.id,
                "candidate_source": "baseline",
                "scenario": scenario,
            },
        )
    return trials


def _create_optimizer_candidate(
    db: Session,
    job: models.Job,
    proposal: CandidateProposal,
    *,
    trial_count: int,
) -> models.CandidateParameterSet:
    """Persist one optimizer-generated CandidateParameterSet."""

    candidate = models.CandidateParameterSet(
        job_id=job.id,
        generation_index=proposal.generation_index,
        source_type="optimizer",
        label=proposal.label,
        parameter_json=_complete_candidate_parameters(job, proposal.parameters),
        is_baseline=False,
        trial_count=trial_count,
        proposal_reason=proposal.strategy,
        optimizer_metadata_json=dict(proposal.metadata),
    )
    db.add(candidate)
    db.flush()
    record_event(
        db,
        job.id,
        "optimizer_candidate_created",
        {
            "candidate_id": candidate.id,
            "label": proposal.label,
            "strategy": proposal.strategy,
            "generation_index": proposal.generation_index,
            "optimizer_metadata": proposal.metadata,
        },
    )
    return candidate


def _low_fidelity_scenario_runs(
    configured_runs: list[ScenarioRun], fidelity: float
) -> list[ScenarioRun]:
    """Choose a deterministic, case-stratified fraction of training runs.

    Fidelity represents executed scenario/seed coverage. Holdout cases remain
    reserved for full-fidelity verification. Round-robin selection prevents a
    case with many seeds from consuming the entire reduced budget.
    """

    training_runs = [run for run in configured_runs if not run.holdout]
    if not training_runs:
        return []
    target = max(1, math.ceil(len(training_runs) * fidelity))
    grouped: dict[str, list[ScenarioRun]] = {}
    for run in training_runs:
        grouped.setdefault(run.case_id, []).append(run)
    reduced: list[ScenarioRun] = []
    seed_index = 0
    while len(reduced) < target:
        added = False
        for case_runs in grouped.values():
            if seed_index < len(case_runs):
                reduced.append(case_runs[seed_index])
                added = True
                if len(reduced) >= target:
                    break
        if not added:
            break
        seed_index += 1
    return reduced


def _effective_fidelity_mapping(
    configured_runs: list[ScenarioRun] | None,
    *,
    full_trials_per_candidate: int,
) -> tuple[tuple[float, float], ...]:
    if configured_runs is not None:
        matrix_size = len([run for run in configured_runs if not run.holdout])
    else:
        matrix_size = max(1, full_trials_per_candidate)
    if matrix_size <= 0:
        return ((0.25, 0.25), (0.5, 0.5), (1.0, 1.0))
    return tuple(
        (
            level,
            min(1.0, max(1, math.ceil(matrix_size * level)) / matrix_size),
        )
        for level in (0.25, 0.5, 1.0)
    )


def _resolve_proposal_fidelity(
    proposal: CandidateProposal,
    fidelity_mapping: tuple[tuple[float, float], ...],
) -> CandidateProposal:
    if not _uses_multi_fidelity(proposal.metadata):
        return proposal
    metadata = dict(proposal.metadata)
    requested = _optimizer_requested_fidelity(metadata)
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
            # Numerical optimizers consume the actual training coverage.
            "fidelity": effective,
        }
    )
    return replace(proposal, metadata=metadata)


def _dispatch_optimizer_trials(
    db: Session,
    job: models.Job,
    candidate: models.CandidateParameterSet,
    *,
    trials_per_candidate: int | None = None,
) -> list[models.Trial]:
    """Create PENDING Trial rows for one optimizer candidate."""

    trials: list[models.Trial] = []
    now = _now()
    configured_runs = _configured_scenario_runs(
        job, generation_index=candidate.generation_index
    )
    if configured_runs is not None:
        fidelity = _optimizer_fidelity(candidate.optimizer_metadata_json)
        requested_fidelity = _optimizer_requested_fidelity(
            candidate.optimizer_metadata_json
        )
        if requested_fidelity < 1.0:
            configured_runs = _low_fidelity_scenario_runs(
                configured_runs,
                requested_fidelity,
            )
        for run in configured_runs:
            payload = _scenario_payload(
                job,
                run,
                source="optimizer",
                generation_index=candidate.generation_index,
            )
            payload["optimizer_fidelity"] = fidelity
            payload["optimizer_requested_fidelity"] = requested_fidelity
            trial = models.Trial(
                job_id=job.id,
                candidate_id=candidate.id,
                seed=run.seed,
                scenario_type=run.scenario_type,
                scenario_config_json=payload,
                status="PENDING",
                queued_at=now,
            )
            db.add(trial)
            db.flush()
            trials.append(trial)
            record_event(
                db,
                job.id,
                "trial_dispatched",
                {
                    "trial_id": trial.id,
                    "candidate_id": candidate.id,
                    "candidate_source": "optimizer",
                    "scenario": run.scenario_type,
                    "scenario_case_id": run.case_id,
                    "seed": run.seed,
                },
            )
        candidate.trial_count = len(trials)
        return trials
    scenario_count = len(constants.OPTIMIZER_SCENARIOS)
    dispatch_count = (
        scenario_count if trials_per_candidate is None else max(1, trials_per_candidate)
    )
    fidelity = _optimizer_fidelity(candidate.optimizer_metadata_json)
    requested_fidelity = _optimizer_requested_fidelity(
        candidate.optimizer_metadata_json
    )
    if requested_fidelity < 1.0:
        dispatch_count = max(
            1,
            math.ceil(dispatch_count * max(0.05, requested_fidelity)),
        )
    for idx in range(dispatch_count):
        scenario = constants.OPTIMIZER_SCENARIOS[idx % scenario_count]
        seed = constants.optimizer_seed_for(candidate.generation_index * 10 + idx, scenario)
        scenario_payload = constants.with_advanced_scenario(
            constants.optimizer_scenario_config(
                scenario, candidate_index=candidate.generation_index, seed=seed
            ),
            job.advanced_scenario_config_json,
        )
        scenario_payload["optimizer_fidelity"] = fidelity
        scenario_payload["optimizer_requested_fidelity"] = requested_fidelity
        trial = models.Trial(
            job_id=job.id,
            candidate_id=candidate.id,
            seed=seed,
            scenario_type=scenario,
            scenario_config_json=scenario_payload,
            status="PENDING",
            queued_at=now,
        )
        db.add(trial)
        db.flush()
        trials.append(trial)
        record_event(
            db,
            job.id,
            "trial_dispatched",
            {
                "trial_id": trial.id,
                "candidate_id": candidate.id,
                "candidate_source": "optimizer",
                "scenario": scenario,
            },
        )
    return trials


def _claim_and_initialize_job(db: Session, job: models.Job) -> bool:
    """Atomically claim a QUEUED job and dispatch its first generation.

    For heuristic jobs this dispatches the baseline plus all heuristic
    optimizer candidates up front (same behaviour as Phase 7). For GPT jobs
    only the baseline is dispatched initially; subsequent generations are
    created by :func:`dispatch_next_llm_generation` as the iterative loop
    decides more candidates are needed.

    The conditional status update and all generated candidate/trial rows live
    in the caller's transaction. A worker crash therefore rolls the whole
    claim back to QUEUED, while concurrent workers get ``rowcount == 0`` and
    cannot create duplicate work.
    """

    if job.status != "QUEUED":
        return False

    now = _now()
    claimed = db.execute(
        update(models.Job)
        .where(models.Job.id == job.id, models.Job.status == "QUEUED")
        .values(
            status="RUNNING",
            started_at=now,
            current_phase="baseline",
            current_generation=0,
        )
        .execution_options(synchronize_session=False)
    )
    if claimed.rowcount != 1:  # type: ignore[attr-defined]
        db.expire(job)
        db.refresh(job)
        return False

    db.expire(job)
    db.refresh(job)

    record_event(db, job.id, "job_started", None)

    baseline = _create_baseline_candidate(db, job)
    baseline_trials = _dispatch_baseline_trials(db, job, baseline)

    total_trials = len(baseline_trials)

    if job.optimizer_strategy == "none":
        logger.debug("job %s requested baseline-only execution", job.id)
    elif job.optimizer_strategy == "heuristic":
        configured_runs = _configured_scenario_runs(job, generation_index=1)
        trials_per_optimizer = (
            len(configured_runs)
            if configured_runs is not None
            else len(constants.OPTIMIZER_SCENARIOS)
        )
        requested_count = (
            job.max_iterations
            if job.parameter_space_json
            else min(job.max_iterations, constants.OPTIMIZER_CANDIDATE_COUNT)
        )
        budgeted_count = min(
            requested_count,
            max(0, (job.max_total_trials - total_trials) // trials_per_optimizer),
        )
        if job.parameter_space_json:
            proposals = (
                generate_selected_parameter_candidates(
                    job.parameter_space_json,
                    count=budgeted_count,
                    candidate_validator=validator_for_job(job),
                )
                if budgeted_count > 0
                else []
            )
        else:
            proposals = (
                generate_candidates(
                    _baseline_parameters_for_job(job), count=budgeted_count
                )
                if budgeted_count > 0
                else []
            )
        record_event(
            db,
            job.id,
            "optimizer_started",
            {
                "candidate_count": len(proposals),
                "strategy": "heuristic",
                "requested_candidate_count": requested_count,
                "budget_limited": budgeted_count < requested_count,
                "design_limited": len(proposals) < budgeted_count,
            },
        )
        for proposal in proposals:
            opt_candidate = _create_optimizer_candidate(
                db,
                job,
                proposal,
                trial_count=trials_per_optimizer,
            )
            _dispatch_optimizer_trials(
                db,
                job,
                opt_candidate,
                trials_per_candidate=trials_per_optimizer,
            )
        total_trials += len(proposals) * trials_per_optimizer
        job.current_generation = max(
            (proposal.generation_index for proposal in proposals), default=0
        )
        job.current_phase = "trial_execution"

    job.progress_completed_trials = 0
    job.progress_total_trials = total_trials
    return True


def start_job(db: Session, job: models.Job) -> models.Job:
    """Compatibility wrapper around the atomic QUEUED-job claim."""

    _claim_and_initialize_job(db, job)
    return job


def dispatch_next_llm_generation(
    db: Session,
    job: models.Job,
    *,
    client: OpenAIClientLike | None = None,
) -> LlmDispatchResult:
    """Ask the LLM proposer for the next generation and dispatch its trials.

    Returns a structured status so callers can distinguish proposer/system
    failures from clean budget exhaustion and "no usable proposal" outcomes.
    Caller is responsible for the DB commit lifecycle.
    """

    from app.orchestration.acceptance import criteria_for_job

    generation_index = job.current_generation + 1
    configured_runs = _configured_scenario_runs(job, generation_index=generation_index)
    trials_per_candidate = (
        len(configured_runs)
        if configured_runs is not None
        else max(1, job.trials_per_candidate)
    )
    if generation_index > job.max_iterations:
        return LlmDispatchResult(status="max_iterations_reached")
    if job.progress_total_trials + trials_per_candidate > job.max_total_trials:
        return LlmDispatchResult(status="budget_exhausted")

    criteria = criteria_for_job(job)
    result = propose_candidates(db, job, criteria, client=client)
    if result.error:
        return LlmDispatchResult(status="llm_error", error=result.error)
    if not result.proposals:
        return LlmDispatchResult(status="no_usable_proposal")

    proposal = result.proposals[0]
    if _is_duplicate_proposal(job, proposal.parameters):
        record_event(
            db,
            job.id,
            "optimizer_candidate_skipped",
            {
                "reason": "duplicate_parameters",
                "strategy": "gpt",
                "generation_index": generation_index,
            },
        )
        return LlmDispatchResult(status="no_usable_proposal")
    candidate = _create_llm_candidate(
        db,
        job,
        proposal,
        generation_index=generation_index,
        trials_per_candidate=trials_per_candidate,
        raw_response=result.raw_response,
    )
    _dispatch_llm_candidate_trials(db, job, candidate, trials_per_candidate)

    job.current_generation = generation_index
    job.current_phase = f"candidate_generation_{generation_index}"
    job.progress_total_trials += trials_per_candidate
    record_event(
        db,
        job.id,
        "generation_dispatched",
        {
            "generation_index": generation_index,
            "candidate_count": 1,
            "trials_per_candidate": trials_per_candidate,
            "model": result.model,
        },
    )
    return LlmDispatchResult(status="dispatched", dispatched_candidates=1)


def dispatch_next_cma_es_generation(
    db: Session,
    job: models.Job,
) -> AdaptiveDispatchResult:
    """Generate and dispatch the next dependency-free CMA-ES-style candidate."""

    generation_index = job.current_generation + 1
    configured_runs = _configured_scenario_runs(job, generation_index=generation_index)
    trials_per_candidate = (
        len(configured_runs)
        if configured_runs is not None
        else max(1, job.trials_per_candidate)
    )
    if generation_index > job.max_iterations:
        return AdaptiveDispatchResult(status="max_iterations_reached")
    if job.progress_total_trials + trials_per_candidate > job.max_total_trials:
        return AdaptiveDispatchResult(status="budget_exhausted")

    proposal = propose_next_generation(
        job=job,
        candidates=list(job.candidates),
        safe_ranges=constants.PARAMETER_SAFE_RANGES,
        baseline_parameters=_baseline_parameters_for_job(job),
        generation_index=generation_index,
    )
    if _is_duplicate_proposal(job, proposal.parameters):
        record_event(
            db,
            job.id,
            "optimizer_candidate_skipped",
            {
                "reason": "search_space_exhausted",
                "strategy": "cma_es",
                "generation_index": generation_index,
            },
        )
        return AdaptiveDispatchResult(status="search_space_exhausted")
    candidate = _create_optimizer_candidate(
        db,
        job,
        proposal,
        trial_count=trials_per_candidate,
    )
    _dispatch_optimizer_trials(
        db,
        job,
        candidate,
        trials_per_candidate=trials_per_candidate,
    )
    job.current_generation = generation_index
    job.current_phase = f"candidate_generation_{generation_index}"
    job.progress_total_trials += trials_per_candidate
    record_event(
        db,
        job.id,
        "generation_dispatched",
        {
            "generation_index": generation_index,
            "candidate_count": 1,
            "trials_per_candidate": trials_per_candidate,
            "strategy": "cma_es",
        },
    )
    return AdaptiveDispatchResult(status="dispatched", dispatched_candidates=1)


def _experimental_batch_target(
    job: models.Job,
    strategy: ExperimentalOptimizerStrategy,
) -> int:
    dimensions = 0
    parameter_space = job.parameter_space_json or []
    if not isinstance(parameter_space, list):
        raise ValueError("parameter_space_json must be an array")
    for item in parameter_space:
        if not isinstance(item, dict):
            raise ValueError("parameter_space_json entries must be objects")
        enabled = item.get("enabled", True)
        locked = item.get("locked", False)
        if not isinstance(enabled, bool) or not isinstance(locked, bool):
            raise ValueError("parameter enabled/locked flags must be boolean")
        if not enabled or locked:
            continue
        minimum = item.get("minimum")
        maximum = item.get("maximum")
        if (
            isinstance(minimum, bool)
            or isinstance(maximum, bool)
            or not isinstance(minimum, int | float)
            or not isinstance(maximum, int | float)
            or not math.isfinite(float(minimum))
            or not math.isfinite(float(maximum))
        ):
            raise ValueError("parameter bounds must be finite numbers")
        if float(maximum) > float(minimum):
            dimensions += 1
    if dimensions == 0:
        dimensions = len(constants.BASELINE_PARAMETERS)
    if strategy in {
        "surrogate_cma_es",
        "bipop_cma_es",
        "optimizer_portfolio",
    }:
        return max(4, min(12, 4 + math.floor(3 * math.log(dimensions))))
    return max(2, min(4, dimensions))


def _has_successful_full_fidelity_optimizer_evidence(job: models.Job) -> bool:
    """Return whether at least one optimizer point passed a complete full matrix.

    Merely dispatching a nominally full-fidelity row is not verification.  A
    cancelled, pending, failed, or entirely infeasible/crashed candidate must
    not consume the one full-matrix reserve forever; a later generation needs
    another chance to produce usable verification evidence.
    """

    return any(
        candidate.source_type == "optimizer" and candidate_is_publishable(candidate)
        for candidate in job.candidates
    )


def dispatch_next_experimental_generation(
    db: Session,
    job: models.Job,
    *,
    strategy_override: ExperimentalOptimizerStrategy | None = None,
) -> AdaptiveDispatchResult:
    """Generate and dispatch one batch from an accuracy-first optimizer."""

    strategy_value = strategy_override or job.optimizer_strategy
    if not is_experimental_strategy(strategy_value):
        raise ValueError(f"unsupported experimental strategy: {strategy_value}")
    strategy = cast(ExperimentalOptimizerStrategy, strategy_value)
    generation_index = job.current_generation + 1
    if generation_index > job.max_iterations:
        return AdaptiveDispatchResult(status="max_iterations_reached")

    configured_runs = _configured_scenario_runs(job, generation_index=generation_index)
    full_trials_per_candidate = (
        len(configured_runs)
        if configured_runs is not None
        else max(1, job.trials_per_candidate)
    )
    remaining_trials = max(0, job.max_total_trials - job.progress_total_trials)
    capacity = remaining_trials // full_trials_per_candidate
    if capacity < 1:
        return AdaptiveDispatchResult(status="budget_exhausted")
    fidelity_mapping = _effective_fidelity_mapping(
        configured_runs,
        full_trials_per_candidate=full_trials_per_candidate,
    )
    can_schedule_reduced_fidelity = strategy in {
        "multi_fidelity_mobo",
        "optimizer_portfolio",
    }
    has_full_optimizer_evidence = _has_successful_full_fidelity_optimizer_evidence(job)
    force_full_fidelity = can_schedule_reduced_fidelity and not has_full_optimizer_evidence and (
        generation_index >= job.max_iterations or capacity <= 1
    )
    allocatable_capacity = capacity
    if (
        can_schedule_reduced_fidelity
        and not has_full_optimizer_evidence
        and not force_full_fidelity
    ):
        # Preserve the budget of one complete scenario matrix. If every early
        # point is screened cheaply, a later generation can still verify at
        # least one optimizer candidate instead of ending with low-fidelity
        # evidence only.
        allocatable_capacity = max(1, capacity - 1)
    batch_size = min(
        allocatable_capacity,
        _experimental_batch_target(job, strategy),
    )
    proposals = propose_experimental_generation(
        job=job,
        candidates=list(job.candidates),
        baseline_parameters=_baseline_parameters_for_job(job),
        generation_index=generation_index,
        batch_size=batch_size,
        fidelity_mapping=fidelity_mapping,
        required_fidelity=1.0 if force_full_fidelity else None,
        strategy_override=strategy,
    )
    dispatched_candidates = 0
    dispatched_trials = 0
    seen_batch_identities: set[ProposalIdentity] = set()
    for raw_proposal in proposals:
        proposal = _resolve_proposal_fidelity(raw_proposal, fidelity_mapping)
        effective_fidelity = _optimizer_fidelity(proposal.metadata)
        requested_fidelity = _optimizer_requested_fidelity(proposal.metadata)
        if effective_fidelity <= 0.0 or requested_fidelity <= 0.0:
            record_event(
                db,
                job.id,
                "optimizer_candidate_skipped",
                {
                    "reason": "invalid_fidelity",
                    "strategy": strategy,
                    "generation_index": generation_index,
                    "label": proposal.label,
                },
            )
            continue
        proposal_identity = _proposal_identity(
            job,
            proposal.parameters,
            proposal.metadata,
        )
        if proposal_identity is None:
            record_event(
                db,
                job.id,
                "optimizer_candidate_skipped",
                {
                    "reason": "invalid_parameter_fingerprint",
                    "strategy": strategy,
                    "generation_index": generation_index,
                    "label": proposal.label,
                },
            )
            continue
        if proposal_identity in seen_batch_identities:
            record_event(
                db,
                job.id,
                "optimizer_candidate_skipped",
                {
                    "reason": "duplicate_in_generation",
                    "strategy": strategy,
                    "generation_index": generation_index,
                    "label": proposal.label,
                },
            )
            continue
        if _is_duplicate_proposal(
            job,
            proposal.parameters,
            optimizer_metadata=proposal.metadata,
        ):
            record_event(
                db,
                job.id,
                "optimizer_candidate_skipped",
                {
                    "reason": "duplicate_parameters_and_fidelity",
                    "strategy": strategy,
                    "generation_index": generation_index,
                    "label": proposal.label,
                },
            )
            continue
        # SQLAlchemy does not guarantee that adding a Candidate row by job_id
        # mutates an already-loaded job.candidates collection.  Keep an
        # explicit batch-local set so later proposals cannot repeat it.
        seen_batch_identities.add(proposal_identity)
        candidate = _create_optimizer_candidate(
            db,
            job,
            proposal,
            trial_count=0,
        )
        trials = _dispatch_optimizer_trials(
            db,
            job,
            candidate,
            trials_per_candidate=full_trials_per_candidate,
        )
        if dispatched_trials + len(trials) > remaining_trials:
            raise RuntimeError("optimizer dispatch exceeded the remaining trial budget")
        dispatched_candidates += 1
        dispatched_trials += len(trials)
    if dispatched_candidates == 0:
        return AdaptiveDispatchResult(status="search_space_exhausted")

    job.current_generation = generation_index
    job.current_phase = f"candidate_generation_{generation_index}"
    job.progress_total_trials += dispatched_trials
    record_event(
        db,
        job.id,
        "generation_dispatched",
        {
            "generation_index": generation_index,
            "candidate_count": dispatched_candidates,
            "trial_count": dispatched_trials,
            "strategy": strategy,
            "batch_target": batch_size,
        },
    )
    return AdaptiveDispatchResult(
        status="dispatched",
        dispatched_candidates=dispatched_candidates,
    )


def dispatch_next_harness_generation(
    db: Session,
    job: models.Job,
    *,
    client: OpenAIClientLike | None = None,
) -> AdaptiveDispatchResult:
    """Let the bounded planner select and dispatch one registered optimizer.

    The planner can only return a registry identifier. This function remains
    the authority boundary: it maps that identifier to trusted in-process
    optimizer code without mutating the job's persisted ``llm_harness`` mode.
    """

    generation_index = job.current_generation + 1
    if generation_index > job.max_iterations:
        record_event(
            db,
            job.id,
            "harness_decision_skipped",
            {
                "reason": "max_iterations_reached",
                "generation": generation_index,
                "remaining_trials": max(
                    0,
                    job.max_total_trials - job.progress_total_trials,
                ),
            },
        )
        return AdaptiveDispatchResult(status="max_iterations_reached")

    configured_runs = _configured_scenario_runs(
        job,
        generation_index=generation_index,
    )
    full_trials_per_candidate = (
        len(configured_runs) if configured_runs is not None else max(1, job.trials_per_candidate)
    )
    remaining_trials = max(
        0,
        job.max_total_trials - job.progress_total_trials,
    )
    if remaining_trials < full_trials_per_candidate:
        record_event(
            db,
            job.id,
            "harness_decision_skipped",
            {
                "reason": "budget_exhausted",
                "generation": generation_index,
                "remaining_trials": remaining_trials,
                "minimum_dispatch_trials": full_trials_per_candidate,
            },
        )
        return AdaptiveDispatchResult(status="budget_exhausted")

    from app.orchestration.decision_harness import (
        as_experimental_strategy,
        select_optimizer_tool,
    )

    decision = select_optimizer_tool(db, job, client=client)
    if decision.tool_id == "cma_es":
        result = dispatch_next_cma_es_generation(db, job)
    else:
        result = dispatch_next_experimental_generation(
            db,
            job,
            strategy_override=as_experimental_strategy(decision.tool_id),
        )
    record_event(
        db,
        job.id,
        "harness_tool_execution_result",
        {
            "generation": job.current_generation,
            "tool_id": decision.tool_id,
            "decision_source": decision.source,
            "status": result.status,
            "dispatched_candidates": result.dispatched_candidates,
            "evidence_sha256": decision.evidence_sha256,
            "prompt_sha256": decision.prompt_sha256,
            "fallback_reason": decision.fallback_reason,
            "evidence_schema_version": decision.evidence_schema_version,
            "tool_registry_version": decision.tool_registry_version,
        },
    )
    return result


def _fail_job_initialization(db: Session, job_id: str, exc: ValueError) -> None:
    """Terminally quarantine one invalid persisted job without blocking the queue."""

    db.rollback()
    job = db.get(models.Job, job_id)
    if job is None or job.status != "QUEUED":
        return
    now = _now()
    job.status = "FAILED"
    job.current_phase = "failed"
    job.completed_at = now
    job.latest_error_code = "JOB_INITIALIZATION_FAILED"
    job.latest_error_message = (
        "The saved job configuration is invalid and could not be initialized."
    )
    purged = 0
    for stored_secret in job.secrets:
        if stored_secret.deleted_at is None:
            stored_secret.deleted_at = now
            stored_secret.encrypted_api_key = ""
            purged += 1
    record_event(
        db,
        job.id,
        "job_failed",
        {
            "code": "JOB_INITIALIZATION_FAILED",
            "error_type": type(exc).__name__,
            "secrets_purged": purged,
        },
    )
    db.commit()


def start_queued_jobs(db: Session, *, limit: int = 10) -> list[str]:
    """Process up to ``limit`` QUEUED jobs, moving each to RUNNING.

    Returns the list of job ids that were started. Each job is advanced in its
    own commit so a failure on one job does not roll back others.
    """

    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 100:
        raise ValueError("limit must be an integer in [1, 100]")
    stmt = (
        select(models.Job)
        .where(models.Job.status == "QUEUED")
        .order_by(models.Job.queued_at.asc().nullsfirst(), models.Job.created_at.asc())
        .limit(limit)
    )
    started: list[str] = []
    for job in list(db.scalars(stmt)):
        job_id = job.id
        try:
            if _claim_and_initialize_job(db, job):
                db.commit()
                started.append(job_id)
            else:
                db.rollback()
        except ValueError as exc:
            logger.exception("job %s failed initialization validation", job_id)
            _fail_job_initialization(db, job_id, exc)
    return started
