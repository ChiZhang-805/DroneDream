"""Job-level orchestration: claim QUEUED jobs, create baseline + optimizer
candidates, and dispatch their trials.

The job manager only mutates Job/CandidateParameterSet/Trial rows. It never
executes a trial directly — trial-level work is done by the trial executor
from a separate transaction.
"""

from __future__ import annotations

import logging
import math
import time
from collections.abc import Callable, Mapping
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, cast

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app import models, schemas
from app.benchmarking.adapters import BenchmarkAdapterError
from app.benchmarking.contracts import BenchmarkProposalContextV1, canonical_sha256
from app.benchmarking.job_runtime import (
    BenchmarkJobRuntimeBlocked,
    benchmark_run_binding,
    build_benchmark_job_observation,
    require_benchmark_job_runtime_context,
)
from app.benchmarking.llm_durable_runtime import (
    BenchmarkDurableLLMBlocked,
    execute_durable_direct_arm,
    execute_durable_react_arm,
)
from app.benchmarking.method_inventory import require_execution_ready_method
from app.benchmarking.provider_transport import build_job_secret_benchmark_transport
from app.benchmarking.registry import create_benchmark_adapter, require_registered_adapter
from app.optimization.experimental_types import ExperimentalOptimizerStrategy
from app.optimization.scenarios import (
    ScenarioRun,
    optimizer_fidelity,
    optimizer_requested_fidelity,
    scenario_execution_payload,
    scenario_matrix_for_generation,
    training_matrix_for_fidelity,
)
from app.orchestration import constants
from app.orchestration.aggregation import candidate_is_publishable
from app.orchestration.cma_es_optimizer import propose_next_generation
from app.orchestration.events import record_event
from app.orchestration.experimental_optimizer import (
    PreparedExperimentalGeneration,
    execute_prepared_experimental_generation,
    is_experimental_strategy,
    prepare_experimental_generation,
    propose_experimental_generation,
    search_space_for_job,
)
from app.orchestration.harness_budget_planner import (
    HarnessBudgetOpportunity,
    HarnessCompiledGenerationPlan,
    HarnessCompiledToolCall,
    HarnessProposalSummary,
    HarnessStopReason,
    build_budget_opportunity,
    proposal_summary,
)
from app.orchestration.harness_context import (
    HarnessBatchPolicy,
    HarnessPlanPhase,
    build_harness_evidence,
    selectable_harness_tools,
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
from app.orchestration.outcome_contract_guard import (
    OutcomeContractDriftError,
    check_job_outcome_contract,
)
from app.orchestration.parameter_constraints import validator_for_job
from app.orchestration.qualification_dispatch import (
    ensure_candidate_screening_qualification,
    qualification_trial_binding,
    screening_runs,
)
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
    planned_candidates: int = 0


@dataclass(frozen=True)
class BenchmarkDispatchResult:
    """Outcome of one server-bound benchmark proposal attempt."""

    status: str
    dispatched_candidates: int = 0
    error_code: str | None = None
    error: str | None = None


@dataclass(frozen=True)
class _PreparedHarnessToolCall:
    call: HarnessCompiledToolCall
    prepared: PreparedExperimentalGeneration


@dataclass(frozen=True)
class _HarnessToolCallResult:
    call: HarnessCompiledToolCall
    proposals: tuple[CandidateProposal, ...]
    status: str
    elapsed_ms: float
    cpu_ms: float
    error_type: str | None = None


def _now() -> datetime:
    return datetime.now(timezone.utc)


class CandidateDispatchStopped(RuntimeError):
    """Raised when a frozen first-qualified Job rejects new candidate work."""


def _claim_candidate_dispatch_ordinal(db: Session, job: models.Job) -> int:
    """Atomically reserve the next server-authoritative candidate ordinal.

    The conditional Job-row update is part of the caller's transaction.  A
    concurrent first-qualified freeze therefore either wins before this claim
    (and rejects it) or waits for the candidate transaction to finish.  UUIDs
    and client arrival order never define candidate ordering.
    """

    with db.no_autoflush:
        next_value = db.scalar(
            update(models.Job)
            .where(
                models.Job.id == job.id,
                models.Job.first_qualified_candidate_id.is_(None),
            )
            .values(
                next_candidate_dispatch_ordinal=(models.Job.next_candidate_dispatch_ordinal + 1)
            )
            .returning(models.Job.next_candidate_dispatch_ordinal)
            .execution_options(synchronize_session=False)
        )
    if next_value is None:
        raise CandidateDispatchStopped(f"Job {job.id} already froze a first-qualified candidate")
    db.expire(
        job,
        ["next_candidate_dispatch_ordinal", "first_qualified_candidate_id"],
    )
    return int(next_value) - 1


def _configured_scenario_runs(
    job: models.Job,
    *,
    generation_index: int,
) -> list[ScenarioRun] | None:
    """Return the explicit fair matrix, or None for the legacy scenario policy."""

    if not job.scenario_suite_json:
        return None
    suite = schemas.ScenarioSuiteConfig(**job.scenario_suite_json)
    return scenario_matrix_for_generation(
        suite,
        generation_index=generation_index,
    )


def _candidate_dispatch_runs(
    db: Session,
    job: models.Job,
    candidate: models.CandidateParameterSet,
) -> tuple[list[ScenarioRun] | None, models.CandidateQualification | None]:
    """Select legacy matrix or the exact four-run sealed screening matrix."""

    qualification, contract = ensure_candidate_screening_qualification(
        db,
        job=job,
        candidate=candidate,
    )
    if qualification is not None:
        if contract is None:  # pragma: no cover - guarded by dispatch contract
            raise RuntimeError("sealed qualification is missing its contract")
        return list(screening_runs(contract)), qualification
    return (
        _configured_scenario_runs(
            job,
            generation_index=candidate.generation_index,
        ),
        None,
    )


def _qualification_trial_fields(
    qualification: models.CandidateQualification | None,
    *,
    ordinal: int,
) -> dict[str, Any]:
    if qualification is None:
        return {}
    return qualification_trial_binding(
        qualification=qualification,
        phase="screening",
        ordinal=ordinal,
    )


def _scenario_payload(
    job: models.Job,
    run: ScenarioRun,
    *,
    source: str,
    generation_index: int,
    optimizer_fidelity_value: float | None = None,
    optimizer_requested_fidelity_value: float | None = None,
) -> dict[str, Any]:
    if source == "optimizer":
        optimizer_fidelity_value = (
            1.0 if optimizer_fidelity_value is None else optimizer_fidelity_value
        )
        optimizer_requested_fidelity_value = (
            1.0
            if optimizer_requested_fidelity_value is None
            else optimizer_requested_fidelity_value
        )
    return scenario_execution_payload(
        run,
        source=source,
        generation_index=generation_index,
        advanced_scenario_config=job.advanced_scenario_config_json,
        optimizer_fidelity_value=optimizer_fidelity_value,
        optimizer_requested_fidelity_value=(optimizer_requested_fidelity_value),
    )


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


def _complete_candidate_parameters(job: models.Job, proposed: dict[str, float]) -> dict[str, float]:
    """Overlay tuned values onto the invariant job-level controller inputs.

    Schedule/controller values that are not selected for tuning must remain
    identical across baseline and every candidate; otherwise candidates would
    fly different commands and the comparison would not be causal.
    """

    if not isinstance(proposed, dict):
        raise ValueError("proposed parameters must be an object")
    completed = _baseline_parameters_for_job(job)
    parameter_space = job.parameter_space_json or []
    allowed_names = (
        {
            str(item.get("name", "")).strip().upper()
            for item in parameter_space
            if isinstance(item, dict)
            and item.get("enabled", True) is True
            and str(item.get("name", "")).strip()
        }
        if parameter_space
        else set(constants.BASELINE_PARAMETERS)
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

    return optimizer_fidelity(metadata)


def _optimizer_requested_fidelity(metadata: object) -> float:
    """Return the nominal level, preserving whether holdouts were verified."""

    return optimizer_requested_fidelity(metadata)


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
        _optimizer_requested_fidelity(candidate.optimizer_metadata_json) < 1.0 - 1e-9
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
        trial.failure_code in _TRANSIENT_FULL_VERIFICATION_FAILURES for trial in failed_trials
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
        identity[2] and len(matches) == 1 and _allows_transient_full_verification_retry(matches[0])
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
        dispatch_ordinal=_claim_candidate_dispatch_ordinal(db, job),
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
        dispatch_ordinal=_claim_candidate_dispatch_ordinal(db, job),
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
    configured_runs, qualification = _candidate_dispatch_runs(db, job, candidate)
    if configured_runs is not None:
        for ordinal, run in enumerate(configured_runs, start=1):
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
                **_qualification_trial_fields(qualification, ordinal=ordinal),
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
                    "evaluation_phase": trial.evaluation_phase,
                    "qualification_ordinal": trial.qualification_ordinal,
                },
            )
        candidate.trial_count = len(trials)
        return trials
    scenarios = constants.OPTIMIZER_SCENARIOS
    for idx in range(trials_per_candidate):
        scenario = scenarios[idx % len(scenarios)]
        seed = constants.optimizer_seed_for(candidate.generation_index * 10 + idx, scenario)
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
    configured_runs, qualification = _candidate_dispatch_runs(db, job, candidate)
    if configured_runs is not None:
        for ordinal, run in enumerate(configured_runs, start=1):
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
                **_qualification_trial_fields(qualification, ordinal=ordinal),
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
                    "evaluation_phase": trial.evaluation_phase,
                    "qualification_ordinal": trial.qualification_ordinal,
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
        dispatch_ordinal=_claim_candidate_dispatch_ordinal(db, job),
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
    """Compatibility wrapper for the shared deterministic coverage selector."""

    return training_matrix_for_fidelity(configured_runs, fidelity)


def _effective_fidelity_mapping(
    configured_runs: list[ScenarioRun] | None,
    *,
    full_trials_per_candidate: int,
) -> tuple[tuple[float, float], ...]:
    if configured_runs is not None:
        training_runs = [run for run in configured_runs if not run.holdout]
        matrix_size = len(training_runs)
        minimum_coverage = len({run.case_id for run in training_runs})
    else:
        matrix_size = max(1, full_trials_per_candidate)
        minimum_coverage = 1
    if matrix_size <= 0:
        return ((0.25, 0.25), (0.5, 0.5), (1.0, 1.0))
    return tuple(
        (
            level,
            min(
                1.0,
                max(minimum_coverage, math.ceil(matrix_size * level)) / matrix_size,
            ),
        )
        for level in (0.25, 0.5, 1.0)
    )


def _resolve_proposal_fidelity(
    proposal: CandidateProposal,
    fidelity_mapping: tuple[tuple[float, float], ...],
) -> CandidateProposal:
    """Verify that the proposal was sealed after final fidelity resolution."""

    if not _uses_multi_fidelity(proposal.metadata):
        return proposal
    requested = _optimizer_requested_fidelity(proposal.metadata)
    expected_effective = next(
        (
            mapped
            for level, mapped in fidelity_mapping
            if math.isclose(level, requested, abs_tol=1e-9)
        ),
        requested,
    )
    sealed_effective = _optimizer_fidelity(proposal.metadata)
    if not math.isclose(
        sealed_effective,
        expected_effective,
        rel_tol=0.0,
        abs_tol=1e-12,
    ):
        raise RuntimeError("optimizer proposal fidelity changed after source evidence sealing")
    return proposal


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
    configured_runs, qualification = _candidate_dispatch_runs(db, job, candidate)
    if configured_runs is not None:
        full_training_count = sum(1 for run in configured_runs if not run.holdout)
        fidelity = _optimizer_fidelity(candidate.optimizer_metadata_json)
        requested_fidelity = _optimizer_requested_fidelity(candidate.optimizer_metadata_json)
        if qualification is not None and (
            not math.isclose(fidelity, 1.0, rel_tol=0.0, abs_tol=1e-12)
            or not math.isclose(
                requested_fidelity,
                1.0,
                rel_tol=0.0,
                abs_tol=1e-12,
            )
        ):
            raise RuntimeError("sealed qualification screening requires full fidelity")
        if requested_fidelity < 1.0:
            configured_runs = _low_fidelity_scenario_runs(
                configured_runs,
                requested_fidelity,
            )
            if full_training_count > 0:
                actual_fidelity = len(configured_runs) / full_training_count
                if not math.isclose(
                    fidelity,
                    actual_fidelity,
                    rel_tol=0.0,
                    abs_tol=1e-12,
                ):
                    raise RuntimeError(
                        "dispatched Trial coverage diverged from sealed optimizer fidelity"
                    )
        for ordinal, run in enumerate(configured_runs, start=1):
            payload = _scenario_payload(
                job,
                run,
                source="optimizer",
                generation_index=candidate.generation_index,
                optimizer_fidelity_value=fidelity,
                optimizer_requested_fidelity_value=requested_fidelity,
            )
            trial = models.Trial(
                job_id=job.id,
                candidate_id=candidate.id,
                seed=run.seed,
                scenario_type=run.scenario_type,
                scenario_config_json=payload,
                status="PENDING",
                queued_at=now,
                **_qualification_trial_fields(qualification, ordinal=ordinal),
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
                    "evaluation_phase": trial.evaluation_phase,
                    "qualification_ordinal": trial.qualification_ordinal,
                },
            )
        candidate.trial_count = len(trials)
        return trials
    scenario_count = len(constants.OPTIMIZER_SCENARIOS)
    dispatch_count = (
        scenario_count if trials_per_candidate is None else max(1, trials_per_candidate)
    )
    fidelity = _optimizer_fidelity(candidate.optimizer_metadata_json)
    requested_fidelity = _optimizer_requested_fidelity(candidate.optimizer_metadata_json)
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
    if not check_job_outcome_contract(db, job).valid:
        raise OutcomeContractDriftError(
            "the persisted optimization outcome contract no longer matches "
            "the queued Job configuration"
        )
    run_binding = benchmark_run_binding(db, job)
    if run_binding is not None:
        # Validate the complete immutable graph before claiming the Job.  A
        # benchmark label can never fall through to ``optimizer_strategy``.
        require_benchmark_job_runtime_context(db, job)

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

    if run_binding is not None:
        logger.debug(
            "job %s is bound to benchmark run %s; baseline-only initialization",
            job.id,
            run_binding.id,
        )
        record_event(
            db,
            job.id,
            "benchmark_baseline_dispatched",
            {
                "run_binding_id": run_binding.id,
                "benchmark_arm_record_id": run_binding.benchmark_arm_id,
            },
        )
    elif job.optimizer_strategy == "none":
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
                generate_candidates(_baseline_parameters_for_job(job), count=budgeted_count)
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


def _require_current_outcome_contract(
    db: Session,
    job: models.Job,
) -> None:
    """Refuse generation dispatch after the frozen semantics have drifted."""

    if not check_job_outcome_contract(db, job).valid:
        raise OutcomeContractDriftError(
            "the persisted optimization outcome contract no longer matches the Job configuration"
        )


def dispatch_next_benchmark_generation(
    db: Session,
    job: models.Job,
) -> BenchmarkDispatchResult:
    """Dispatch exactly one proposal from the immutable benchmark arm.

    This path intentionally ignores ``job.optimizer_strategy``.  Local
    numerical adapters consume the same holdout-free observation, while LLM
    provider arms use their separately durable, JobSecret-bound transport.
    """

    if _first_qualified_dispatch_stopped(job):
        return BenchmarkDispatchResult(status="first_qualified_stop")
    _require_current_outcome_contract(db, job)
    try:
        context, observation = build_benchmark_job_observation(db, job)
        adapter_id = context.arm.proposal_adapter_id
        require_registered_adapter(adapter_id)
        require_execution_ready_method(adapter_id)
        adapter = (
            None
            if adapter_id in {"llm_direct/v1", "llm_react/v1"}
            else create_benchmark_adapter(adapter_id)
        )
    except BenchmarkJobRuntimeBlocked as exc:
        return BenchmarkDispatchResult(
            status="benchmark_blocked",
            error_code=exc.code,
            error=str(exc),
        )
    except ValueError as exc:
        return BenchmarkDispatchResult(
            status="benchmark_blocked",
            error_code="benchmark_adapter_unavailable",
            error=str(exc),
        )
    if observation.generation_index > job.max_iterations:
        return BenchmarkDispatchResult(status="max_iterations_reached")
    if observation.simulator_budget_remaining < 1:
        return BenchmarkDispatchResult(status="budget_exhausted")
    if observation.wall_time_remaining_ms < 1:
        return BenchmarkDispatchResult(status="wall_time_exhausted")
    try:
        if adapter_id == "llm_direct/v1":
            direct = execute_durable_direct_arm(
                db,
                job,
                observation,
                transport_factory=lambda provider: build_job_secret_benchmark_transport(
                    db, job, provider
                ),
            )
            if direct.status == "first_qualified_stop":
                return BenchmarkDispatchResult(status="first_qualified_stop")
            if direct.proposal is None:  # pragma: no cover - strict result contract.
                raise RuntimeError("durable direct execution returned no proposal")
            proposal = direct.proposal
        elif adapter_id == "llm_react/v1":
            react = execute_durable_react_arm(
                db,
                job,
                observation,
                transport_factory=lambda provider: build_job_secret_benchmark_transport(
                    db, job, provider
                ),
            )
            if react.status == "first_qualified_stop":
                return BenchmarkDispatchResult(status="first_qualified_stop")
            if react.status.startswith("abandoned"):
                return BenchmarkDispatchResult(
                    status="proposal_failed",
                    error_code="benchmark_react_abandoned",
                    error="The bounded ReAct arm abandoned this generation.",
                )
            if react.proposal is None:  # pragma: no cover - strict result contract.
                raise RuntimeError("durable ReAct execution returned no proposal")
            proposal = react.proposal
        else:
            if adapter is None:  # pragma: no cover - exhaustive registry routing.
                raise RuntimeError("benchmark adapter routing is incomplete")
            proposal = adapter.propose(observation)
    except BenchmarkDurableLLMBlocked as exc:
        return BenchmarkDispatchResult(
            status="benchmark_blocked",
            error_code=exc.code,
            error=str(exc),
        )
    except BenchmarkAdapterError as exc:
        message = str(exc)
        return BenchmarkDispatchResult(
            status=("search_space_exhausted" if "exhausted" in message else "proposal_failed"),
            error_code="benchmark_proposal_failed",
            error=message,
        )
    proposal_context = BenchmarkProposalContextV1(
        proposal_adapter_id=adapter_id,
        reason_code=proposal.reason_code,
        proposal_receipt_sha256=canonical_sha256(proposal.proposal_receipt),
        optimizer_metadata={"proposal_receipt": proposal.proposal_receipt},
    )
    metadata: dict[str, Any] = {
        "schema_id": "dronedream.benchmark-candidate-metadata/v1",
        "benchmark_proposal_context": proposal_context.model_dump(mode="json"),
        "effective_fidelity": 1.0,
        "requested_fidelity": 1.0,
    }
    if _is_duplicate_proposal(job, proposal.parameters, optimizer_metadata=metadata):
        return BenchmarkDispatchResult(status="search_space_exhausted")
    candidate_proposal = CandidateProposal(
        generation_index=observation.generation_index,
        label=proposal.candidate_ref,
        strategy=f"benchmark:{adapter_id}",
        parameters=proposal.parameters,
        metadata=metadata,
    )
    candidate = _create_optimizer_candidate(
        db,
        job,
        candidate_proposal,
        trial_count=0,
    )
    trials = _dispatch_optimizer_trials(db, job, candidate)
    if not trials:
        raise RuntimeError("benchmark proposal dispatched no screening Trials")
    job.current_generation = observation.generation_index
    job.current_phase = f"benchmark_generation_{observation.generation_index}"
    job.progress_total_trials += len(trials)
    record_event(
        db,
        job.id,
        "benchmark_generation_dispatched",
        {
            "benchmark_arm_id": context.arm.benchmark_arm_id,
            "proposal_adapter_id": adapter_id,
            "run_binding_id": context.binding.id,
            "generation_index": observation.generation_index,
            "candidate_id": candidate.id,
            "candidate_dispatch_ordinal": candidate.dispatch_ordinal,
            "trial_count": len(trials),
            "observation_sha256": canonical_sha256(observation),
            "proposal_receipt_sha256": proposal_context.proposal_receipt_sha256,
        },
    )
    return BenchmarkDispatchResult(status="dispatched", dispatched_candidates=1)


def _first_qualified_dispatch_stopped(job: models.Job) -> bool:
    return (
        job.completion_policy == "first_qualified_stop"
        and job.first_qualified_candidate_id is not None
    )


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

    if _first_qualified_dispatch_stopped(job):
        return LlmDispatchResult(status="first_qualified_stop")
    _require_current_outcome_contract(db, job)
    generation_index = job.current_generation + 1
    configured_runs = _configured_scenario_runs(job, generation_index=generation_index)
    trials_per_candidate = (
        len(configured_runs) if configured_runs is not None else max(1, job.trials_per_candidate)
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

    if _first_qualified_dispatch_stopped(job):
        return AdaptiveDispatchResult(status="first_qualified_stop")
    _require_current_outcome_contract(db, job)
    generation_index = job.current_generation + 1
    configured_runs = _configured_scenario_runs(job, generation_index=generation_index)
    trials_per_candidate = (
        len(configured_runs) if configured_runs is not None else max(1, job.trials_per_candidate)
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
        return AdaptiveDispatchResult(
            status="search_space_exhausted",
            planned_candidates=1,
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
    return AdaptiveDispatchResult(
        status="dispatched",
        dispatched_candidates=1,
        planned_candidates=1,
    )


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


def _batch_size_for_policy(
    safe_maximum: int,
    policy: HarnessBatchPolicy,
) -> int:
    """Translate a closed planning policy into a locally bounded batch size."""

    if safe_maximum < 1:
        raise ValueError("safe batch maximum must be positive")
    if policy == "conservative":
        return 1
    if policy == "balanced":
        return max(1, (safe_maximum + 1) // 2)
    if policy == "broad":
        return safe_maximum
    raise ValueError("unsupported Harness batch policy")


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


def _required_fidelity_for_plan(
    *,
    can_schedule_reduced_fidelity: bool,
    plan_phase: HarnessPlanPhase,
    has_full_optimizer_evidence: bool,
    generation_index: int,
    max_iterations: int,
    full_candidate_capacity: int,
) -> float | None:
    """Compile the non-negotiable fidelity floor for one planned cohort."""

    if not can_schedule_reduced_fidelity:
        return None
    if plan_phase == "verification":
        return 1.0
    if not has_full_optimizer_evidence and (
        generation_index >= max_iterations or full_candidate_capacity <= 1
    ):
        return 1.0
    return None


def dispatch_next_experimental_generation(
    db: Session,
    job: models.Job,
    *,
    strategy_override: ExperimentalOptimizerStrategy | None = None,
    batch_policy: HarnessBatchPolicy = "broad",
    plan_phase: HarnessPlanPhase = "balanced",
) -> AdaptiveDispatchResult:
    """Generate and dispatch one batch from an accuracy-first optimizer."""

    if _first_qualified_dispatch_stopped(job):
        return AdaptiveDispatchResult(status="first_qualified_stop")
    _require_current_outcome_contract(db, job)
    strategy_value = strategy_override or job.optimizer_strategy
    if not is_experimental_strategy(strategy_value):
        raise ValueError(f"unsupported experimental strategy: {strategy_value}")
    strategy = cast(ExperimentalOptimizerStrategy, strategy_value)
    generation_index = job.current_generation + 1
    if generation_index > job.max_iterations:
        return AdaptiveDispatchResult(status="max_iterations_reached")

    configured_runs = _configured_scenario_runs(job, generation_index=generation_index)
    full_trials_per_candidate = (
        len(configured_runs) if configured_runs is not None else max(1, job.trials_per_candidate)
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
    required_fidelity = _required_fidelity_for_plan(
        can_schedule_reduced_fidelity=can_schedule_reduced_fidelity,
        plan_phase=plan_phase,
        has_full_optimizer_evidence=has_full_optimizer_evidence,
        generation_index=generation_index,
        max_iterations=job.max_iterations,
        full_candidate_capacity=capacity,
    )
    force_full_fidelity = required_fidelity == 1.0
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
    safe_batch_maximum = min(
        allocatable_capacity,
        _experimental_batch_target(job, strategy),
    )
    batch_size = _batch_size_for_policy(safe_batch_maximum, batch_policy)
    proposals = propose_experimental_generation(
        job=job,
        candidates=list(job.candidates),
        baseline_parameters=_baseline_parameters_for_job(job),
        generation_index=generation_index,
        batch_size=batch_size,
        fidelity_mapping=fidelity_mapping,
        required_fidelity=required_fidelity,
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
        return AdaptiveDispatchResult(
            status="search_space_exhausted",
            planned_candidates=batch_size,
        )

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
        planned_candidates=batch_size,
    )


def _harness_budget_context(
    job: models.Job,
    *,
    generation_index: int,
    remaining_trials: int,
    full_trials_per_candidate: int,
) -> tuple[HarnessBudgetOpportunity, HarnessPlanPhase]:
    """Compile the trusted per-generation budget and deterministic stop gate."""

    snapshot, _ = build_harness_evidence(job, execution_events=job.events)
    selectable = tuple(
        tool_id for tool_id in selectable_harness_tools(snapshot) if tool_id != "cma_es"
    )
    if not selectable:
        raise RuntimeError("multi-tool Harness requires an experimental fallback")
    full_capacity = remaining_trials // full_trials_per_candidate
    has_full_optimizer_evidence = _has_successful_full_fidelity_optimizer_evidence(job)
    candidate_capacity = min(4, full_capacity)
    if (
        not has_full_optimizer_evidence
        and generation_index < job.max_iterations
        and candidate_capacity > 1
    ):
        # Preserve one complete matrix for a later verification generation.
        candidate_capacity -= 1
    stop_reasons: tuple[HarnessStopReason, ...] = ()
    if (
        has_full_optimizer_evidence
        and job.current_generation >= 3
        and snapshot.search.trailing_stagnant_generations >= 3
    ):
        stop_reasons = ("budget_efficiency_stalled",)
    opportunity = build_budget_opportunity(
        generation=generation_index,
        remaining_trials=remaining_trials,
        full_trials_per_candidate=full_trials_per_candidate,
        candidate_capacity=candidate_capacity,
        allowed_tools=selectable,
        stop_reasons=stop_reasons,
        maximum_tool_calls=min(4, len(selectable)),
    )
    return opportunity, snapshot.plan.phase


def _prepare_harness_tool_calls(
    *,
    job: models.Job,
    plan: HarnessCompiledGenerationPlan,
    configured_runs: list[ScenarioRun] | None,
    full_trials_per_candidate: int,
    plan_phase: HarnessPlanPhase,
) -> tuple[_PreparedHarnessToolCall, ...]:
    """Prepare every numerical request before any worker thread is created."""

    fidelity_mapping = _effective_fidelity_mapping(
        configured_runs,
        full_trials_per_candidate=full_trials_per_candidate,
    )
    candidates = list(job.candidates)
    baseline_parameters = _baseline_parameters_for_job(job)
    has_full_optimizer_evidence = _has_successful_full_fidelity_optimizer_evidence(job)
    prepared_calls: list[_PreparedHarnessToolCall] = []
    for call in plan.calls:
        strategy = cast(ExperimentalOptimizerStrategy, call.tool_id)
        can_schedule_reduced_fidelity = strategy in {
            "multi_fidelity_mobo",
            "optimizer_portfolio",
        }
        required_fidelity = (
            1.0
            if call.fidelity_mode == "force_full"
            else _required_fidelity_for_plan(
                can_schedule_reduced_fidelity=can_schedule_reduced_fidelity,
                plan_phase=plan_phase,
                has_full_optimizer_evidence=has_full_optimizer_evidence,
                generation_index=plan.generation,
                max_iterations=job.max_iterations,
                full_candidate_capacity=plan.projected_candidate_count,
            )
        )
        prepared = prepare_experimental_generation(
            job=job,
            candidates=candidates,
            baseline_parameters=baseline_parameters,
            generation_index=plan.generation,
            batch_size=call.allocation,
            fidelity_mapping=fidelity_mapping,
            required_fidelity=required_fidelity,
            strategy_override=strategy,
        )
        if prepared is None:
            raise RuntimeError("compiled Harness tool call produced no numerical request")
        prepared_calls.append(_PreparedHarnessToolCall(call=call, prepared=prepared))
    return tuple(prepared_calls)


def _run_harness_tool_call(
    prepared_call: _PreparedHarnessToolCall,
) -> _HarnessToolCallResult:
    """Execute one pure numerical request and enforce its local cost envelope."""

    wall_started = time.perf_counter_ns()
    thread_clock = getattr(time, "thread_time_ns", time.process_time_ns)
    cpu_started = thread_clock()
    error_type: str | None = None
    proposals: tuple[CandidateProposal, ...] = ()
    try:
        proposals = tuple(execute_prepared_experimental_generation(prepared_call.prepared))
        if len(proposals) > prepared_call.call.allocation:
            error_type = "ProposalCountExceeded"
            proposals = ()
            logger.warning(
                "Harness tool call exceeded its compiled allocation "
                "(call_id=%s, tool_id=%s, allocation=%s)",
                prepared_call.call.call_id,
                prepared_call.call.tool_id,
                prepared_call.call.allocation,
            )
    except Exception as exc:
        error_type = type(exc).__name__[:128]
        logger.warning(
            "Harness tool call failed (call_id=%s, tool_id=%s, error_type=%s)",
            prepared_call.call.call_id,
            prepared_call.call.tool_id,
            error_type,
        )
    elapsed_ms = (time.perf_counter_ns() - wall_started) / 1_000_000
    cpu_ms = (thread_clock() - cpu_started) / 1_000_000
    if error_type is not None:
        status = "tool_error"
    elif (
        elapsed_ms > prepared_call.call.latency_budget_ms
        or cpu_ms > prepared_call.call.cpu_budget_ms
    ):
        status = "cost_budget_exceeded"
        proposals = ()
    else:
        status = "completed"
    return _HarnessToolCallResult(
        call=prepared_call.call,
        proposals=proposals,
        status=status,
        elapsed_ms=elapsed_ms,
        cpu_ms=cpu_ms,
        error_type=error_type,
    )


def _execute_harness_tool_calls(
    prepared_calls: tuple[_PreparedHarnessToolCall, ...],
) -> tuple[_HarnessToolCallResult, ...]:
    """Execute parallel-safe requests concurrently and serial-lane calls in order."""

    results: dict[int, _HarnessToolCallResult] = {}
    parallel_calls = tuple(item for item in prepared_calls if item.call.parallel_safe)
    serial_calls = tuple(item for item in prepared_calls if not item.call.parallel_safe)
    if parallel_calls:
        with ThreadPoolExecutor(
            max_workers=len(parallel_calls),
            thread_name_prefix="harness-tool",
        ) as executor:
            future_calls = {
                executor.submit(_run_harness_tool_call, item): item for item in parallel_calls
            }
            for future in as_completed(future_calls):
                item = future_calls[future]
                results[item.call.ordinal] = future.result()
    for item in serial_calls:
        results[item.call.ordinal] = _run_harness_tool_call(item)
    return tuple(results[index] for index in sorted(results))


def _harness_incumbent_parameters(job: models.Job) -> dict[str, float]:
    scored = [
        candidate
        for candidate in job.candidates
        if candidate_is_publishable(candidate)
        and not isinstance(candidate.aggregated_score, bool)
        and isinstance(candidate.aggregated_score, int | float)
        and math.isfinite(float(candidate.aggregated_score))
        and isinstance(candidate.parameter_json, dict)
    ]
    if scored:
        incumbent = min(
            scored,
            key=lambda item: (
                float(cast(int | float, item.aggregated_score)),
                item.generation_index,
                item.id,
            ),
        )
        return {
            str(name): float(value)
            for name, value in incumbent.parameter_json.items()
            if not isinstance(value, bool)
            and isinstance(value, int | float)
            and math.isfinite(float(value))
        }
    return _baseline_parameters_for_job(job)


def _summarize_harness_proposals(
    db: Session,
    job: models.Job,
    *,
    tool_results: tuple[_HarnessToolCallResult, ...],
) -> tuple[
    tuple[HarnessProposalSummary, ...],
    dict[str, tuple[CandidateProposal, _HarnessToolCallResult]],
]:
    """Deduplicate and anonymize tool outputs for the sole post-tool model turn."""

    search_space = search_space_for_job(
        job,
        baseline_parameters=_baseline_parameters_for_job(job),
    )
    incumbent = _harness_incumbent_parameters(job)
    summaries: list[HarnessProposalSummary] = []
    proposal_by_ref: dict[str, tuple[CandidateProposal, _HarnessToolCallResult]] = {}
    seen_batch_identities: set[ProposalIdentity] = set()
    for tool_result in tool_results:
        if tool_result.status != "completed":
            continue
        for tool_candidate_ordinal, proposal in enumerate(tool_result.proposals):
            resolved = proposal
            identity = _proposal_identity(
                job,
                resolved.parameters,
                resolved.metadata,
            )
            reason: str | None = None
            if identity is None:
                reason = "invalid_parameter_fingerprint"
            elif identity in seen_batch_identities:
                reason = "duplicate_in_generation"
            elif _is_duplicate_proposal(
                job,
                resolved.parameters,
                optimizer_metadata=resolved.metadata,
            ):
                reason = "duplicate_parameters_and_fidelity"
            if reason is not None:
                record_event(
                    db,
                    job.id,
                    "optimizer_candidate_skipped",
                    {
                        "reason": reason,
                        "strategy": tool_result.call.tool_id,
                        "generation_index": resolved.generation_index,
                        "label": resolved.label,
                        "harness_call_id": tool_result.call.call_id,
                    },
                )
                continue
            if identity is None:
                raise RuntimeError("validated Harness proposal lost its identity")
            seen_batch_identities.add(identity)
            proposal_ref = f"proposal_{len(summaries)}"
            requested_fidelity = _optimizer_requested_fidelity(resolved.metadata)
            effective_fidelity = _optimizer_fidelity(resolved.metadata)
            distance = search_space.normalized_distance(
                resolved.parameters,
                incumbent,
            )
            summary = proposal_summary(
                proposal_ref=proposal_ref,
                tool_id=tool_result.call.tool_id,
                tool_candidate_ordinal=tool_candidate_ordinal,
                requested_fidelity=requested_fidelity,
                effective_fidelity=effective_fidelity,
                normalized_distance_from_incumbent=max(0.0, min(1.0, distance)),
            )
            summaries.append(summary)
            proposal_by_ref[proposal_ref] = (resolved, tool_result)
    return tuple(summaries), proposal_by_ref


def _harness_candidate_proposal(
    proposal: CandidateProposal,
    *,
    summary: HarnessProposalSummary,
    tool_result: _HarnessToolCallResult,
    plan_decision_id: str,
    plan: HarnessCompiledGenerationPlan,
    revision_id: str,
    revision_source: str,
) -> CandidateProposal:
    metadata = dict(proposal.metadata)
    metadata["harness_orchestration"] = {
        "schema_id": "dronedream.harness-candidate-orchestration/v1",
        "decision_id": plan_decision_id,
        "revision_id": revision_id,
        "revision_source": revision_source,
        "plan_sha256": plan.plan_sha256,
        "call_id": tool_result.call.call_id,
        "call_ordinal": tool_result.call.ordinal,
        "tool_id": tool_result.call.tool_id,
        "allocation": tool_result.call.allocation,
        "allocation_authority": tool_result.call.allocation_authority,
        "fidelity_mode": tool_result.call.fidelity_mode,
        "proposal_ref": summary.proposal_ref,
        "tool_candidate_ordinal": summary.tool_candidate_ordinal,
        "tool_elapsed_ms": round(tool_result.elapsed_ms, 3),
        "tool_cpu_ms": round(tool_result.cpu_ms, 3),
    }
    return CandidateProposal(
        generation_index=proposal.generation_index,
        label=proposal.label,
        strategy=proposal.strategy,
        parameters=dict(proposal.parameters),
        metadata=metadata,
    )


def _cognitive_review_inputs(
    job: models.Job,
    *,
    summaries: tuple[HarnessProposalSummary, ...],
    proposal_by_ref: Mapping[
        str,
        tuple[CandidateProposal, _HarnessToolCallResult],
    ],
    selected_refs: tuple[str, ...],
) -> tuple[
    dict[str, dict[str, object]],
    list[dict[str, object]],
    bool,
    bool,
]:
    """Build bounded proposal/boundary evidence and deterministic risk flags."""

    search_space = search_space_for_job(
        job,
        baseline_parameters=_baseline_parameters_for_job(job),
    )
    incumbent = _harness_incumbent_parameters(job)
    summary_by_ref = {item.proposal_ref: item for item in summaries}
    proposal_details: dict[str, dict[str, object]] = {}
    tool_directions: dict[str, dict[str, list[float]]] = {}
    hard_boundary_candidate = False
    selected_set = frozenset(selected_refs)
    for ref in sorted(proposal_by_ref):
        proposal, tool_result = proposal_by_ref[ref]
        summary = summary_by_ref[ref]
        normalized_parameters: dict[str, float] = {}
        boundary_parameters: list[str] = []
        for domain in search_space.tunable:
            value = float(proposal.parameters.get(domain.name, domain.baseline))
            span = domain.maximum - domain.minimum
            unit = 0.0 if span <= 0 else (value - domain.minimum) / span
            normalized_parameters[domain.name] = round(max(0.0, min(1.0, unit)), 6)
            if ref in selected_set and span > 0 and (unit <= 0.02 or unit >= 0.98):
                boundary_parameters.append(domain.name)
            if ref in selected_set and span > 0:
                delta = (value - float(incumbent.get(domain.name, domain.baseline))) / span
                if abs(delta) >= 0.02:
                    tool_directions.setdefault(domain.name, {}).setdefault(
                        tool_result.call.tool_id,
                        [],
                    ).append(delta)
        if boundary_parameters:
            hard_boundary_candidate = True
        proposal_details[ref] = {
            "proposal_ref": ref,
            "tool_id": summary.tool_id,
            "tool_candidate_ordinal": summary.tool_candidate_ordinal,
            "requested_fidelity": summary.requested_fidelity,
            "effective_fidelity": summary.effective_fidelity,
            "normalized_distance_from_incumbent": (summary.normalized_distance_from_incumbent),
            "normalized_parameters": normalized_parameters,
            "near_hard_bound_parameters": sorted(boundary_parameters),
        }
    tool_direction_conflict = False
    for directions_by_tool in tool_directions.values():
        if len(directions_by_tool) < 2:
            continue
        tool_means = [sum(values) / len(values) for values in directions_by_tool.values() if values]
        if tool_means and min(tool_means) < -0.02 and max(tool_means) > 0.02:
            tool_direction_conflict = True
            break
    hard_bounds = [
        {
            "parameter": domain.name,
            "minimum": domain.minimum,
            "maximum": domain.maximum,
            "baseline": domain.baseline,
            "scale": domain.scale,
            "value_type": domain.value_type,
        }
        for domain in search_space.tunable
    ]
    return (
        proposal_details,
        hard_bounds,
        tool_direction_conflict,
        hard_boundary_candidate,
    )


def dispatch_next_harness_generation(
    db: Session,
    job: models.Job,
    *,
    client: OpenAIClientLike | None = None,
    before_dispatch: Callable[[], None] | None = None,
) -> AdaptiveDispatchResult:
    """Plan, execute, revise, and dispatch one bounded multi-tool generation."""

    if _first_qualified_dispatch_stopped(job):
        return AdaptiveDispatchResult(status="first_qualified_stop")
    _require_current_outcome_contract(db, job)
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

    from app.orchestration.cognitive_budget import cognitive_turn_counts, evaluate_adaptive_triggers
    from app.orchestration.cognitive_review import run_adaptive_cognitive_review
    from app.orchestration.decision_harness import (
        current_harness_evidence_snapshot,
        select_optimizer_budget_plan,
        select_plan_revision,
    )

    opportunity, plan_phase = _harness_budget_context(
        job,
        generation_index=generation_index,
        remaining_trials=remaining_trials,
        full_trials_per_candidate=full_trials_per_candidate,
    )
    plan_decision_started = time.perf_counter_ns()
    decision = select_optimizer_budget_plan(
        db,
        job,
        opportunity=opportunity,
        client=client,
    )
    plan_decision_wall_ms = (time.perf_counter_ns() - plan_decision_started) / 1_000_000
    if decision.generation != generation_index:
        raise RuntimeError("Harness budget decision generation drifted")
    if decision.compiled_plan is None:
        provider_call_count, provider_success_count = cognitive_turn_counts(
            db,
            job,
            generation_index=generation_index,
        )
        record_event(
            db,
            job.id,
            "harness_multi_tool_execution_result",
            {
                "decision_id": decision.decision_id,
                "generation": generation_index,
                "status": "stop_accepted",
                "stop_reason": decision.stop_reason,
                "decision_source": decision.source,
                "plan_decision_wall_ms": round(plan_decision_wall_ms, 3),
                "provider_call_count": provider_call_count,
                "provider_success_count": provider_success_count,
                "evidence_sha256": decision.evidence_sha256,
                "prompt_sha256": decision.prompt_sha256,
                "evidence_schema_version": decision.evidence_schema_version,
                "tool_registry_version": decision.tool_registry_version,
                "budget_policy_version": decision.budget_policy_version,
                "plan_prompt_version": decision.plan_prompt_version,
            },
        )
        return AdaptiveDispatchResult(status="stop_accepted")

    plan = decision.compiled_plan
    # Renew/fence immediately after the first external turn. A finalizer whose
    # lease was reclaimed while the provider was responding must not spend CPU
    # on tools or issue the optional second provider request.
    if before_dispatch is not None:
        before_dispatch()
    prepared_calls = _prepare_harness_tool_calls(
        job=job,
        plan=plan,
        configured_runs=configured_runs,
        full_trials_per_candidate=full_trials_per_candidate,
        plan_phase=plan_phase,
    )
    execution_started = time.perf_counter_ns()
    tool_results = _execute_harness_tool_calls(prepared_calls)
    tool_execution_wall_ms = (time.perf_counter_ns() - execution_started) / 1_000_000
    summaries, proposal_by_ref = _summarize_harness_proposals(
        db,
        job,
        tool_results=tool_results,
    )
    revision_started = time.perf_counter_ns()
    revision = select_plan_revision(
        db,
        job,
        plan_decision=decision,
        proposals=summaries,
        maximum_dispatch_candidates=min(
            opportunity.candidate_capacity,
            len(summaries),
        )
        if summaries
        else 1,
        client=client,
    )
    revision_wall_ms = (time.perf_counter_ns() - revision_started) / 1_000_000
    selected_refs = revision.selected_proposal_refs
    revision_selected_refs = selected_refs
    cognitive_review = None
    if (
        summaries
        and selected_refs
        and not revision.abandoned
        and decision.source == "model"
        and revision.source == "model"
    ):
        (
            proposal_details,
            hard_bounds,
            tool_direction_conflict,
            hard_boundary_candidate,
        ) = _cognitive_review_inputs(
            job,
            summaries=summaries,
            proposal_by_ref=proposal_by_ref,
            selected_refs=selected_refs,
        )
        trigger_snapshot, _ = current_harness_evidence_snapshot(db, job)
        trigger = evaluate_adaptive_triggers(
            job,
            generation_index=generation_index,
            snapshot=trigger_snapshot,
            proposal_tools={item.proposal_ref: item.tool_id for item in summaries},
            selected_proposal_refs=selected_refs,
            tool_direction_conflict=tool_direction_conflict,
            hard_boundary_candidate=hard_boundary_candidate,
        )
        cognitive_review = run_adaptive_cognitive_review(
            db,
            job,
            generation_index=generation_index,
            trigger=trigger,
            proposals=summaries,
            selected_proposal_refs=selected_refs,
            proposal_details=proposal_details,
            hard_bounds=hard_bounds,
            client=client,
        )
        selected_refs = cognitive_review.selected_proposal_refs
        record_event(
            db,
            job.id,
            "harness_cognitive_review_result",
            {
                "decision_id": decision.decision_id,
                "revision_id": revision.revision_id,
                "generation": generation_index,
                "trigger_policy_version": trigger.policy_version,
                "diagnosis_trigger_reasons": list(trigger.diagnosis_reasons),
                "critic_trigger_reasons": list(trigger.critic_reasons),
                "suppressed_by_cooldown": list(trigger.suppressed_by_cooldown),
                "available_proposal_refs": [item.proposal_ref for item in summaries],
                "input_selected_proposal_refs": list(revision_selected_refs),
                "diagnosis_decision": cognitive_review.diagnosis_decision,
                "critic_decision": cognitive_review.critic_decision,
                "fail_closed_reason": cognitive_review.fail_closed_reason,
                "selected_proposal_refs": list(selected_refs),
                "holdout_outcomes_visible": False,
            },
        )
    provider_call_count, provider_success_count = cognitive_turn_counts(
        db,
        job,
        generation_index=generation_index,
    )
    actual_tool_cpu_ms = round(
        sum(result.cpu_ms for result in tool_results),
        3,
    )
    tool_call_ledger = [
        {
            "call_id": result.call.call_id,
            "tool_id": result.call.tool_id,
            "status": result.status,
            "allocation": result.call.allocation,
            "parallel_safe": result.call.parallel_safe,
            "proposal_count": len(result.proposals),
            "elapsed_ms": round(result.elapsed_ms, 3),
            "cpu_ms": round(result.cpu_ms, 3),
            "latency_budget_ms": result.call.latency_budget_ms,
            "cpu_budget_ms": result.call.cpu_budget_ms,
            "error_type": result.error_type,
        }
        for result in tool_results
    ]
    if not summaries or not selected_refs or revision.abandoned:
        status = "search_space_exhausted"
        record_event(
            db,
            job.id,
            "harness_multi_tool_execution_result",
            {
                "decision_id": decision.decision_id,
                "revision_id": revision.revision_id,
                "generation": generation_index,
                "plan_sha256": plan.plan_sha256,
                "status": status,
                "decision_source": decision.source,
                "revision_source": revision.source,
                "plan_decision_wall_ms": round(plan_decision_wall_ms, 3),
                "revision_wall_ms": round(revision_wall_ms, 3),
                "provider_call_count": provider_call_count,
                "provider_success_count": provider_success_count,
                "selected_proposal_refs": list(selected_refs),
                "dispatched_candidates": 0,
                "dispatched_trials": 0,
                "planned_candidates": plan.projected_candidate_count,
                "usable_proposal_count": len(summaries),
                "projected_trial_upper_bound": plan.projected_trial_upper_bound,
                "projected_critical_path_latency_budget_ms": (
                    plan.projected_critical_path_latency_budget_ms
                ),
                "projected_cpu_budget_ms": plan.projected_cpu_budget_ms,
                "tool_execution_wall_ms": round(tool_execution_wall_ms, 3),
                "actual_tool_cpu_ms": actual_tool_cpu_ms,
                "tool_calls": tool_call_ledger,
                "evidence_sha256": decision.evidence_sha256,
                "prompt_sha256": decision.prompt_sha256,
                "fallback_reason": decision.fallback_reason,
                "revision_fallback_reason": revision.fallback_reason,
                "cognitive_review_fail_closed_reason": (
                    cognitive_review.fail_closed_reason if cognitive_review else None
                ),
                "evidence_schema_version": decision.evidence_schema_version,
                "tool_registry_version": decision.tool_registry_version,
                "budget_policy_version": decision.budget_policy_version,
                "plan_prompt_version": decision.plan_prompt_version,
                "revision_prompt_version": revision.revision_prompt_version,
            },
        )
        return AdaptiveDispatchResult(
            status=status,
            planned_candidates=plan.projected_candidate_count,
        )

    # Both provider turns and every pure numerical call are complete. The
    # caller's compare-and-swap hook now converts the still-live finalization
    # claim into a commit fence before Candidate/Trial rows are created.
    if before_dispatch is not None:
        before_dispatch()
    if job.current_generation + 1 != generation_index:
        raise RuntimeError("Harness generation drifted before trusted dispatch")

    summary_by_ref = {summary.proposal_ref: summary for summary in summaries}
    dispatched_candidates = 0
    dispatched_trials = 0
    for proposal_ref in selected_refs:
        proposal, tool_result = proposal_by_ref[proposal_ref]
        compiled_proposal = _harness_candidate_proposal(
            proposal,
            summary=summary_by_ref[proposal_ref],
            tool_result=tool_result,
            plan_decision_id=decision.decision_id,
            plan=plan,
            revision_id=revision.revision_id,
            revision_source=revision.source,
        )
        candidate = _create_optimizer_candidate(
            db,
            job,
            compiled_proposal,
            trial_count=0,
        )
        trials = _dispatch_optimizer_trials(
            db,
            job,
            candidate,
            trials_per_candidate=full_trials_per_candidate,
        )
        if dispatched_trials + len(trials) > remaining_trials:
            raise RuntimeError("Harness dispatch exceeded the remaining Trial budget")
        dispatched_candidates += 1
        dispatched_trials += len(trials)
    if dispatched_candidates == 0:
        return AdaptiveDispatchResult(
            status="search_space_exhausted",
            planned_candidates=plan.projected_candidate_count,
        )

    job.current_generation = generation_index
    job.current_phase = f"candidate_generation_{generation_index}"
    job.progress_total_trials += dispatched_trials
    record_event(
        db,
        job.id,
        "harness_multi_tool_execution_result",
        {
            "decision_id": decision.decision_id,
            "revision_id": revision.revision_id,
            "generation": generation_index,
            "plan_sha256": plan.plan_sha256,
            "status": "dispatched",
            "decision_source": decision.source,
            "revision_source": revision.source,
            "plan_decision_wall_ms": round(plan_decision_wall_ms, 3),
            "revision_wall_ms": round(revision_wall_ms, 3),
            "provider_call_count": provider_call_count,
            "provider_success_count": provider_success_count,
            "selected_proposal_refs": list(selected_refs),
            "dispatched_candidates": dispatched_candidates,
            "dispatched_trials": dispatched_trials,
            "planned_candidates": plan.projected_candidate_count,
            "usable_proposal_count": len(summaries),
            "projected_trial_upper_bound": plan.projected_trial_upper_bound,
            "projected_critical_path_latency_budget_ms": (
                plan.projected_critical_path_latency_budget_ms
            ),
            "projected_cpu_budget_ms": plan.projected_cpu_budget_ms,
            "tool_execution_wall_ms": round(tool_execution_wall_ms, 3),
            "actual_tool_cpu_ms": actual_tool_cpu_ms,
            "tool_calls": tool_call_ledger,
            "evidence_sha256": decision.evidence_sha256,
            "prompt_sha256": decision.prompt_sha256,
            "fallback_reason": decision.fallback_reason,
            "revision_fallback_reason": revision.fallback_reason,
            "cognitive_review_fail_closed_reason": (
                cognitive_review.fail_closed_reason if cognitive_review else None
            ),
            "evidence_schema_version": decision.evidence_schema_version,
            "tool_registry_version": decision.tool_registry_version,
            "budget_policy_version": decision.budget_policy_version,
            "plan_prompt_version": decision.plan_prompt_version,
            "revision_prompt_version": revision.revision_prompt_version,
        },
    )
    record_event(
        db,
        job.id,
        "generation_dispatched",
        {
            "generation_index": generation_index,
            "candidate_count": dispatched_candidates,
            "trial_count": dispatched_trials,
            "strategy": "llm_harness",
            "plan_sha256": plan.plan_sha256,
            "decision_id": decision.decision_id,
            "revision_id": revision.revision_id,
        },
    )
    return AdaptiveDispatchResult(
        status="dispatched",
        dispatched_candidates=dispatched_candidates,
        planned_candidates=plan.projected_candidate_count,
    )


def _fail_job_initialization(
    db: Session,
    job_id: str,
    exc: ValueError,
    *,
    code: str = "JOB_INITIALIZATION_FAILED",
) -> None:
    """Terminally quarantine one invalid persisted job without blocking the queue."""

    db.rollback()
    job = db.get(models.Job, job_id)
    if job is None or job.status != "QUEUED":
        return
    now = _now()
    job.status = "FAILED"
    job.current_phase = "failed"
    job.failed_at = now
    job.completed_at = None
    job.latest_error_code = code
    job.latest_error_message = (
        "The saved optimization outcome contract changed after Job creation."
        if code == "OUTCOME_CONTRACT_DRIFT"
        else "The saved job configuration is invalid and could not be initialized."
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
            "code": code,
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
        except OutcomeContractDriftError as exc:
            logger.error("job %s outcome contract drifted before dispatch", job_id)
            _fail_job_initialization(
                db,
                job_id,
                exc,
                code="OUTCOME_CONTRACT_DRIFT",
            )
        except ValueError as exc:
            logger.exception("job %s failed initialization validation", job_id)
            _fail_job_initialization(db, job_id, exc)
    return started
