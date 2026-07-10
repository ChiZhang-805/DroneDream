"""Job-level orchestration: claim QUEUED jobs, create baseline + optimizer
candidates, and dispatch their trials.

The job manager only mutates Job/CandidateParameterSet/Trial rows. It never
executes a trial directly — trial-level work is done by the trial executor
from a separate transaction.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app import models, schemas
from app.optimization.scenarios import ScenarioRun, scenario_matrix
from app.orchestration import constants
from app.orchestration.cma_es_optimizer import propose_next_generation
from app.orchestration.events import record_event
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
    return [
        ScenarioRun(
            case_id=run.case_id,
            scenario_type=run.scenario_type,
            seed=run.seed + offset,
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
        for key in constants.BASELINE_PARAMETERS:
            value = job.baseline_parameter_json.get(key)
            if isinstance(value, (int, float)):
                lo, hi = constants.PARAMETER_SAFE_RANGES[key]
                params[key] = round(max(lo, min(hi, float(value))), 6)
    # The extensible parameter space is authoritative for enabled selections.
    # Legacy six-parameter defaults remain in the dict for the existing mock
    # simulator and heuristic optimizer until those consumers are fully
    # catalog-driven.
    for selection in job.parameter_space_json or []:
        if not isinstance(selection, dict) or selection.get("enabled") is False:
            continue
        name = selection.get("name")
        baseline = selection.get("baseline")
        if not isinstance(name, str) or not isinstance(baseline, int | float):
            continue
        value = float(baseline)
        if math.isfinite(value):
            params[name] = value
    return params


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
    parameter_json = {**proposal.parameters, "_rationale": proposal.rationale}
    candidate = models.CandidateParameterSet(
        job_id=job.id,
        generation_index=generation_index,
        source_type="llm_optimizer",
        label=proposal.label,
        parameter_json=parameter_json,
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
        parameter_json=dict(proposal.parameters),
        is_baseline=False,
        trial_count=trial_count,
        proposal_reason=proposal.strategy,
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
        },
    )
    return candidate


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
        for run in configured_runs:
            trial = models.Trial(
                job_id=job.id,
                candidate_id=candidate.id,
                seed=run.seed,
                scenario_type=run.scenario_type,
                scenario_config_json=_scenario_payload(
                    job,
                    run,
                    source="optimizer",
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
    for idx in range(dispatch_count):
        scenario = constants.OPTIMIZER_SCENARIOS[idx % scenario_count]
        seed = constants.optimizer_seed_for(candidate.generation_index * 10 + idx, scenario)
        trial = models.Trial(
            job_id=job.id,
            candidate_id=candidate.id,
            seed=seed,
            scenario_type=scenario,
            scenario_config_json=constants.with_advanced_scenario(
                constants.optimizer_scenario_config(
                    scenario, candidate_index=candidate.generation_index, seed=seed
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
        pass
    elif job.optimizer_strategy == "heuristic":
        configured_runs = _configured_scenario_runs(job, generation_index=1)
        trials_per_optimizer = (
            len(configured_runs)
            if configured_runs is not None
            else len(constants.OPTIMIZER_SCENARIOS)
        )
        budgeted_count = min(
            constants.OPTIMIZER_CANDIDATE_COUNT,
            max(0, (job.max_total_trials - total_trials) // trials_per_optimizer),
        )
        if job.parameter_space_json:
            proposals = (
                generate_selected_parameter_candidates(
                    job.parameter_space_json, count=budgeted_count
                )
                if budgeted_count > 0
                else []
            )
        else:
            proposals = (
                generate_candidates(
                    _baseline_parameters_for_job(job), count=budgeted_count
                )
                if budgeted_count >= 2
                else []
            )
        record_event(
            db,
            job.id,
            "optimizer_started",
            {
                "candidate_count": len(proposals),
                "strategy": "heuristic",
                "budget_limited": len(proposals) < constants.OPTIMIZER_CANDIDATE_COUNT,
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


def start_queued_jobs(db: Session, *, limit: int = 10) -> list[str]:
    """Process up to ``limit`` QUEUED jobs, moving each to RUNNING.

    Returns the list of job ids that were started. Each job is advanced in its
    own commit so a failure on one job does not roll back others.
    """

    stmt = (
        select(models.Job)
        .where(models.Job.status == "QUEUED")
        .order_by(models.Job.queued_at.asc().nullsfirst(), models.Job.created_at.asc())
        .limit(limit)
    )
    started: list[str] = []
    for job in list(db.scalars(stmt)):
        if _claim_and_initialize_job(db, job):
            db.commit()
            started.append(job.id)
        else:
            db.rollback()
    return started
