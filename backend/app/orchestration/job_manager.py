"""Job-level orchestration: claim QUEUED jobs, create baseline + optimizer
candidates, and dispatch their trials.

The job manager only mutates Job/CandidateParameterSet/Trial rows. It never
executes a trial directly — trial-level work is done by the trial executor
from a separate transaction.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import models
from app.orchestration import constants
from app.orchestration.cma_es_optimizer import propose_next_generation
from app.orchestration.events import record_event
from app.orchestration.llm_parameter_proposer import (
    LlmProposal,
    OpenAIClientLike,
    propose_candidates,
)
from app.orchestration.optimizer import CandidateProposal, generate_candidates


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
    return datetime.now(UTC)


def _create_baseline_candidate(db: Session, job: models.Job) -> models.CandidateParameterSet:
    """Persist the baseline CandidateParameterSet for a job."""

    candidate = models.CandidateParameterSet(
        job_id=job.id,
        generation_index=0,
        source_type="baseline",
        label="baseline",
        parameter_json=dict(constants.BASELINE_PARAMETERS),
        is_baseline=True,
        trial_count=len(constants.BASELINE_SCENARIOS),
    )
    db.add(candidate)
    db.flush()
    job.baseline_candidate_id = candidate.id
    record_event(
        db,
        job.id,
        "baseline_started",
        {"candidate_id": candidate.id, "scenario_count": len(constants.BASELINE_SCENARIOS)},
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
            scenario_config_json=constants.optimizer_scenario_config(
                scenario,
                candidate_index=candidate.generation_index,
                seed=seed,
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
    for scenario in constants.BASELINE_SCENARIOS:
        seed = constants.SCENARIO_SEEDS[scenario]
        trial = models.Trial(
            job_id=job.id,
            candidate_id=candidate.id,
            seed=seed,
            scenario_type=scenario,
            scenario_config_json=constants.baseline_scenario_config(scenario),
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
            scenario_config_json=constants.optimizer_scenario_config(
                scenario, candidate_index=candidate.generation_index, seed=seed
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


def start_job(db: Session, job: models.Job) -> models.Job:
    """Move a QUEUED job to RUNNING and dispatch the first generation of work.

    For heuristic jobs this dispatches the baseline plus all heuristic
    optimizer candidates up front (same behaviour as Phase 7). For GPT jobs
    only the baseline is dispatched initially; subsequent generations are
    created by :func:`dispatch_next_llm_generation` as the iterative loop
    decides more candidates are needed.
    """

    if job.status != "QUEUED":
        return job

    now = _now()
    job.status = "RUNNING"
    job.started_at = now
    job.current_phase = "baseline"
    job.current_generation = 0

    record_event(db, job.id, "job_started", None)

    baseline = _create_baseline_candidate(db, job)
    _dispatch_baseline_trials(db, job, baseline)

    total_trials = len(constants.BASELINE_SCENARIOS)

    if job.optimizer_strategy == "heuristic":
        proposals = generate_candidates(dict(constants.BASELINE_PARAMETERS))
        record_event(
            db,
            job.id,
            "optimizer_started",
            {"candidate_count": len(proposals), "strategy": "heuristic"},
        )
        for proposal in proposals:
            opt_candidate = _create_optimizer_candidate(
                db,
                job,
                proposal,
                trial_count=len(constants.OPTIMIZER_SCENARIOS),
            )
            _dispatch_optimizer_trials(
                db,
                job,
                opt_candidate,
                trials_per_candidate=len(constants.OPTIMIZER_SCENARIOS),
            )
        total_trials += len(proposals) * len(constants.OPTIMIZER_SCENARIOS)

    job.progress_completed_trials = 0
    job.progress_total_trials = total_trials
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

    criteria = criteria_for_job(job)
    result = propose_candidates(db, job, criteria, client=client)
    if result.error:
        return LlmDispatchResult(status="llm_error", error=result.error)
    if not result.proposals:
        return LlmDispatchResult(status="no_usable_proposal")

    generation_index = job.current_generation + 1
    trials_per_candidate = max(1, job.trials_per_candidate)
    if generation_index > job.max_iterations:
        return LlmDispatchResult(status="max_iterations_reached")
    if job.progress_total_trials + trials_per_candidate > job.max_total_trials:
        return LlmDispatchResult(status="budget_exhausted")
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
    trials_per_candidate = max(1, job.trials_per_candidate)
    if generation_index > job.max_iterations:
        return AdaptiveDispatchResult(status="max_iterations_reached")
    if job.progress_total_trials + trials_per_candidate > job.max_total_trials:
        return AdaptiveDispatchResult(status="budget_exhausted")

    proposal = propose_next_generation(
        job=job,
        candidates=list(job.candidates),
        safe_ranges=constants.PARAMETER_SAFE_RANGES,
        baseline_parameters=constants.BASELINE_PARAMETERS,
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
        start_job(db, job)
        db.commit()
        started.append(job.id)
    return started
