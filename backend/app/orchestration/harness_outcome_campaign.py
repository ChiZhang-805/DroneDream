"""Deterministic outcome-level checks for the Harness fallback boundary.

The campaign runs the production Job/Candidate/Trial orchestration against the
deterministic MockSimulatorAdapter.  It compares the direct optimizer
portfolio with the same portfolio reached after two fail-closed Harness
conditions.  This is integration evidence for fallback equivalence only: it
does not measure LLM quality, causal Harness benefit, PX4/Gazebo fidelity, or
real-flight performance.
"""

from __future__ import annotations

import hashlib
import json
import math
import socket
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any
from unittest.mock import patch

from sqlalchemy.orm import Session, sessionmaker

from app import models, schemas
from app.db import Base, _build_engine
from app.optimization.candidate_evidence_ledger import (
    candidate_evidence_chain_matches_current,
)
from app.orchestration import aggregation, job_manager, trial_executor
from app.services import jobs as job_services
from app.simulator.mock import MockSimulatorAdapter

HARNESS_OUTCOME_CAMPAIGN_SCHEMA_VERSION = (
    "dronedream.harness-fallback-outcome-campaign/v1"
)
HARNESS_OUTCOME_CAMPAIGN_EVIDENCE_CLASS = "synthetic_mock_campaign"
HARNESS_OUTCOME_CAMPAIGN_LABEL = "SYNTHETIC_MOCK"
HARNESS_OUTCOME_CAMPAIGN_CLAIM_BOUNDARY = (
    "Outcome-level deterministic integration check on MockSimulatorAdapter. "
    "It verifies that declared fail-closed Harness paths reach the same "
    "optimizer-portfolio candidates and persisted outcomes as a direct "
    "portfolio run under matched seeds and budgets. It does not establish LLM "
    "superiority, causal Harness benefit, PX4/Gazebo performance, physical "
    "fidelity, or real-flight safety."
)
HARNESS_OUTCOME_CAMPAIGN_SEED_BLOCKS = (1100, 2200, 3300, 4400, 5500)
HARNESS_OUTCOME_CAMPAIGN_MAX_ITERATIONS = 2
HARNESS_OUTCOME_CAMPAIGN_MAX_TOTAL_TRIALS = 40
HARNESS_OUTCOME_CAMPAIGN_ARMS = (
    "direct_portfolio",
    "provider_error_fallback",
    "invalid_response_fallback",
)

_TERMINAL_JOBS = {"COMPLETED", "FAILED", "CANCELLED"}
_TERMINAL_TRIALS = {"COMPLETED", "FAILED", "CANCELLED"}
_OUTCOME_COMPONENTS = (
    "candidates",
    "trials",
    "budget",
    "winner",
    "holdout_loss",
    "failure_count",
    "evidence_completeness",
)


class SyntheticProviderError(RuntimeError):
    """Deliberate local exception used by the provider-error campaign arm."""


class SyntheticNetworkConnectBlocked(RuntimeError):
    """Raised before any campaign code can open a network connection."""


class _NetworkConnectMeasurement:
    def __init__(self) -> None:
        self.attempt_count = 0

    def block(self, *_args: object, **_kwargs: object) -> None:
        self.attempt_count += 1
        raise SyntheticNetworkConnectBlocked(
            "network connect blocked by synthetic campaign guard"
        )


class _ProviderErrorClient:
    def __init__(self) -> None:
        self.calls = 0

    def generate(self, *, model: str, system: str, user: str) -> dict[str, Any]:
        del model, system, user
        self.calls += 1
        raise SyntheticProviderError("synthetic provider failure; no network call")


class _InvalidResponseClient:
    def __init__(self) -> None:
        self.calls = 0

    def generate(self, *, model: str, system: str, user: str) -> dict[str, Any]:
        del model, system, user
        self.calls += 1
        return {
            "decision": {
                "tool_id": "__synthetic_invalid_tool__",
                "rationale": "Deliberately invalid local response.",
            }
        }


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


@contextmanager
def _network_connect_guard() -> Iterator[_NetworkConnectMeasurement]:
    """Measure and fail every TCP/Unix socket connection attempt in-process."""

    measurement = _NetworkConnectMeasurement()
    with (
        patch.object(socket.socket, "connect", measurement.block),
        patch.object(socket.socket, "connect_ex", measurement.block),
        patch.object(socket, "create_connection", measurement.block),
    ):
        yield measurement


def _finite(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    numeric = float(value)
    return numeric if math.isfinite(numeric) else None


def _normalized_json(value: object) -> object:
    """Return a canonical JSON value while rejecting non-finite numerics."""

    if value is None or isinstance(value, str | bool | int):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("campaign outcome contains a non-finite number")
        normalized = float(format(value, ".12g"))
        return 0.0 if normalized == 0.0 else normalized
    if isinstance(value, list | tuple):
        return [_normalized_json(item) for item in value]
    if isinstance(value, dict):
        return {
            str(key): _normalized_json(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    raise ValueError(f"campaign outcome contains unsupported {type(value).__name__}")


def _normalized_campaign_json(value: object) -> object:
    """Canonicalize outcomes while omitting declared opaque evidence IDs."""

    if isinstance(value, dict):
        return {
            str(key): _normalized_campaign_json(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
            if str(key) != "evidence_id"
        }
    if isinstance(value, list | tuple):
        return [_normalized_campaign_json(item) for item in value]
    return _normalized_json(value)


def _scenario_suite(seed_block: int) -> schemas.ScenarioSuiteConfig:
    return schemas.ScenarioSuiteConfig(
        common_random_numbers=True,
        cases=[
            schemas.ScenarioCaseConfig(
                id="nominal-training",
                scenario_type="nominal",
                seeds=[seed_block + 1],
            ),
            schemas.ScenarioCaseConfig(
                id="wind-training",
                scenario_type="wind_perturbed",
                seeds=[seed_block + 2],
            ),
            schemas.ScenarioCaseConfig(
                id="noise-training",
                scenario_type="noise_perturbed",
                seeds=[seed_block + 3],
            ),
            schemas.ScenarioCaseConfig(
                id="combined-holdout",
                scenario_type="combined_perturbed",
                seeds=[seed_block + 99],
                holdout=True,
            ),
        ],
    )


def _job_request(
    seed_block: int,
    *,
    arm: str,
) -> schemas.JobCreateRequest:
    strategy = "optimizer_portfolio" if arm == "direct_portfolio" else "llm_harness"
    return schemas.JobCreateRequest(
        display_name=f"synthetic-fallback-equivalence-{seed_block}",
        simulator_backend="mock",
        optimizer_strategy=strategy,  # type: ignore[arg-type]
        max_iterations=HARNESS_OUTCOME_CAMPAIGN_MAX_ITERATIONS,
        max_total_trials=HARNESS_OUTCOME_CAMPAIGN_MAX_TOTAL_TRIALS,
        acceptance_criteria=schemas.AcceptanceCriteria(
            # The deterministic mock landscape cannot reach this value. This
            # forces every arm to consume the same bounded search schedule.
            target_rmse=0.01,
            min_pass_rate=1.0,
        ),
        scenario_suite=_scenario_suite(seed_block),
    )


@contextmanager
def _isolated_session_factory() -> Iterator[sessionmaker[Session]]:
    """Yield a temporary SQLite Session factory with the cancellation fence wired."""

    with TemporaryDirectory(prefix="dronedream-harness-outcome-") as directory:
        database_path = Path(directory) / "campaign.sqlite3"
        engine = _build_engine(f"sqlite:///{database_path.as_posix()}")
        Base.metadata.create_all(engine)
        factory = sessionmaker(bind=engine, expire_on_commit=False)
        previous_fence_factory = aggregation.SessionLocal  # type: ignore[attr-defined]
        aggregation.SessionLocal = factory  # type: ignore[attr-defined]
        try:
            yield factory
        finally:
            aggregation.SessionLocal = previous_fence_factory  # type: ignore[attr-defined]
            engine.dispose()


def _candidate_sort_key(candidate: models.CandidateParameterSet) -> tuple[object, ...]:
    return (
        candidate.generation_index,
        0 if candidate.is_baseline else 1,
        _canonical_json(candidate.parameter_json or {}),
        _canonical_json(candidate.optimizer_metadata_json or {}),
    )


def _aggregate_projection(candidate: models.CandidateParameterSet) -> dict[str, Any] | None:
    aggregate = candidate.aggregated_metric_json
    if not isinstance(aggregate, dict):
        return None
    keys = (
        "objective_values",
        "constraint_values",
        "constraint_violations",
        "feasible",
        "total_constraint_violation",
        "hard_constraint_violation",
        "preference_loss",
        "soft_constraint_penalty",
        "scalar_loss",
        "trial_count",
        "completed_trial_count",
        "failed_trial_count",
        "passing_trial_count",
        "completion_rate",
        "failure_rate",
        "pass_rate",
        "optimizer_learning_failure_rate",
        "holdout",
    )
    return {
        key: _normalized_campaign_json(aggregate[key])
        for key in keys
        if key in aggregate
    }


def _candidate_projection(
    candidate: models.CandidateParameterSet,
    *,
    candidate_key: str,
) -> dict[str, Any]:
    metadata = candidate.optimizer_metadata_json
    metadata_projection = (
        {
            key: _normalized_json(metadata[key])
            for key in (
                "strategy",
                "child_strategy",
                "requested_fidelity",
                "effective_fidelity",
                "fidelity",
                "seed",
                "seed_token",
                "batch_index",
                "restart_index",
            )
            if key in metadata
        }
        if isinstance(metadata, dict)
        else {}
    )
    return {
        "candidate_key": candidate_key,
        "generation_index": candidate.generation_index,
        "source_type": candidate.source_type,
        "is_baseline": candidate.is_baseline,
        "is_best": candidate.is_best,
        "rank_in_job": candidate.rank_in_job,
        "parameters": _normalized_json(candidate.parameter_json or {}),
        "optimizer_metadata": metadata_projection,
        "aggregated_score": _finite(candidate.aggregated_score),
        "trial_count": candidate.trial_count,
        "completed_trial_count": candidate.completed_trial_count,
        "failed_trial_count": candidate.failed_trial_count,
        "aggregate": _aggregate_projection(candidate),
    }


def _trial_projection(
    trial: models.Trial,
    *,
    candidate_key: str,
) -> dict[str, Any]:
    config = trial.scenario_config_json if isinstance(trial.scenario_config_json, dict) else {}
    metric = trial.metric
    metric_projection = (
        {
            "rmse": _finite(metric.rmse),
            "max_error": _finite(metric.max_error),
            "overshoot_count": metric.overshoot_count,
            "completion_time": _finite(metric.completion_time),
            "crash_flag": metric.crash_flag,
            "timeout_flag": metric.timeout_flag,
            "score": _finite(metric.score),
            "final_error": _finite(metric.final_error),
            "pass_flag": metric.pass_flag,
            "instability_flag": metric.instability_flag,
        }
        if metric is not None
        else None
    )
    return {
        "candidate_key": candidate_key,
        "scenario_case_id": config.get("scenario_case_id"),
        "scenario_type": trial.scenario_type,
        "seed": trial.seed,
        "holdout": config.get("holdout") is True,
        "scenario_weight": _finite(config.get("scenario_weight")),
        "optimizer_requested_fidelity": _finite(
            config.get("optimizer_requested_fidelity")
        ),
        "optimizer_fidelity": _finite(config.get("optimizer_fidelity")),
        "status": trial.status,
        "failure_code": trial.failure_code,
        "simulator_backend": trial.simulator_backend,
        "attempt_count": trial.attempt_count,
        "metric": metric_projection,
    }


def _trial_evidence_complete(trial: models.Trial) -> bool:
    attempt = trial.accepted_attempt
    return bool(
        trial.status in _TERMINAL_TRIALS
        and attempt is not None
        and attempt.outcome is not None
        and attempt.outcome.accepted is True
        and attempt.outcome.terminal_status == trial.status
    )


def _candidate_evidence_complete(candidate: models.CandidateParameterSet) -> bool:
    if not candidate.evidence_ledger_required:
        return True
    return candidate_evidence_chain_matches_current(
        candidate,
        candidate.aggregated_metric_json,
    )


def _normalize_outcome(db: Session, job_id: str) -> dict[str, Any]:
    job = db.get(models.Job, job_id)
    if job is None:
        raise RuntimeError("campaign Job disappeared")
    candidates = sorted(list(job.candidates), key=_candidate_sort_key)
    candidate_keys = {
        candidate.id: f"g{candidate.generation_index:02d}-c{index:02d}"
        for index, candidate in enumerate(candidates)
    }
    candidate_rows = [
        _candidate_projection(candidate, candidate_key=candidate_keys[candidate.id])
        for candidate in candidates
    ]
    trial_rows = sorted(
        (
            _trial_projection(
                trial,
                candidate_key=candidate_keys[trial.candidate_id],
            )
            for trial in job.trials
        ),
        key=lambda row: (
            str(row["candidate_key"]),
            bool(row["holdout"]),
            str(row["scenario_case_id"]),
            int(row["seed"]),
        ),
    )
    best = next(
        (candidate for candidate in candidates if candidate.id == job.best_candidate_id),
        None,
    )
    best_aggregate = (
        best.aggregated_metric_json if best is not None and isinstance(
            best.aggregated_metric_json, dict
        )
        else {}
    )
    holdout = best_aggregate.get("holdout")
    holdout_loss = (
        _finite(holdout.get("scalar_loss"))
        if isinstance(holdout, dict)
        else None
    )
    terminal_trial_count = sum(trial.status in _TERMINAL_TRIALS for trial in job.trials)
    complete_trial_evidence_count = sum(
        _trial_evidence_complete(trial) for trial in job.trials
    )
    complete_candidate_evidence_count = sum(
        _candidate_evidence_complete(candidate) for candidate in candidates
    )
    report_complete = bool(job.report is not None and job.report.report_status == "READY")
    winner_freeze_complete = job.winner_freeze is not None
    expected_evidence_units = len(job.trials) + len(candidates) + 2
    complete_evidence_units = (
        complete_trial_evidence_count
        + complete_candidate_evidence_count
        + int(report_complete)
        + int(winner_freeze_complete)
    )
    evidence_completeness = {
        "terminal_trial_count": terminal_trial_count,
        "accepted_trial_outcome_count": complete_trial_evidence_count,
        "candidate_count": len(candidates),
        "complete_candidate_chain_count": complete_candidate_evidence_count,
        "report_ready": report_complete,
        "winner_freeze_present": winner_freeze_complete,
        "expected_evidence_units": expected_evidence_units,
        "complete_evidence_units": complete_evidence_units,
        "completeness_rate": (
            complete_evidence_units / expected_evidence_units
            if expected_evidence_units
            else 0.0
        ),
    }
    winner = (
        {
            "candidate_key": candidate_keys[best.id],
            "parameters": _normalized_json(best.parameter_json or {}),
            "aggregated_score": _finite(best.aggregated_score),
            "rank_in_job": best.rank_in_job,
        }
        if best is not None
        else None
    )
    return {
        "terminal_status": job.status,
        "optimization_outcome": job.optimization_outcome,
        "candidates": candidate_rows,
        "trials": trial_rows,
        "budget": {
            "configured_max_iterations": job.max_iterations,
            "completed_generations": job.current_generation,
            "configured_max_total_trials": job.max_total_trials,
            "dispatched_trials": job.progress_total_trials,
            "completed_trials": job.progress_completed_trials,
            "candidate_count": len(candidates),
            "trial_count": len(job.trials),
        },
        "winner": winner,
        "holdout_loss": holdout_loss,
        "failure_count": sum(trial.status == "FAILED" for trial in job.trials),
        "evidence_completeness": evidence_completeness,
    }


def _fallback_trace(db: Session, job_id: str) -> dict[str, Any]:
    job = db.get(models.Job, job_id)
    if job is None:
        raise RuntimeError("campaign Job disappeared")
    fallback_events: list[dict[str, Any]] = []
    execution_events: list[dict[str, Any]] = []
    for event in sorted(job.events, key=lambda item: (item.created_at, item.id)):
        payload = event.payload_json if isinstance(event.payload_json, dict) else {}
        if event.event_type == "harness_decision_fallback":
            fallback_events.append(
                {
                    "reason": payload.get("reason"),
                    "tool_id": payload.get("tool_id"),
                }
            )
        elif event.event_type == "harness_tool_execution_result":
            execution_events.append(
                {
                    "tool_id": payload.get("tool_id"),
                    "decision_source": payload.get("decision_source"),
                    "status": payload.get("status"),
                    "dispatched_candidates": payload.get("dispatched_candidates"),
                    "fallback_reason": payload.get("fallback_reason"),
                }
            )
    return {
        "fallback_events": fallback_events,
        "execution_events": execution_events,
    }


def _drive_job(
    factory: sessionmaker[Session],
    *,
    job_id: str,
    client: _ProviderErrorClient | _InvalidResponseClient | None,
    max_steps: int | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Run one isolated Job using a process-local, test-only client object.

    ``set_llm_client_override`` is not represented in JobCreateRequest and
    cannot be supplied through the production API. It is an in-process
    evaluation seam used here so no credential or provider transport exists.
    """

    step_limit = (
        HARNESS_OUTCOME_CAMPAIGN_MAX_TOTAL_TRIALS + 20
        if max_steps is None
        else max_steps
    )
    if isinstance(step_limit, bool) or step_limit < 1:
        raise ValueError("campaign orchestration step limit must be positive")

    previous_client = aggregation._llm_client_override
    aggregation.set_llm_client_override(client)
    adapter = MockSimulatorAdapter()
    try:
        with factory() as db:
            started = job_manager.start_queued_jobs(db, limit=1)
        if started != [job_id]:
            raise RuntimeError("campaign Job did not enter RUNNING")
        for _step in range(step_limit):
            ran_trial = False
            with factory() as db:
                trial_id = trial_executor.claim_and_run_one_pending_trial(
                    db,
                    "synthetic-campaign-worker",
                    adapter=adapter,
                )
                ran_trial = trial_id is not None
            if ran_trial:
                continue
            with factory() as db:
                aggregation.finalize_ready_jobs(db, limit=1)
            with factory() as db:
                job = db.get(models.Job, job_id)
                if job is None:
                    raise RuntimeError("campaign Job disappeared")
                if job.status in _TERMINAL_JOBS:
                    return _normalize_outcome(db, job_id), _fallback_trace(db, job_id)
        raise RuntimeError("campaign Job exceeded its bounded orchestration steps")
    finally:
        aggregation.set_llm_client_override(previous_client)


def _run_arm(seed_block: int, arm: str) -> dict[str, Any]:
    if arm not in HARNESS_OUTCOME_CAMPAIGN_ARMS:
        raise ValueError(f"unknown campaign arm: {arm}")
    client: _ProviderErrorClient | _InvalidResponseClient | None
    if arm == "provider_error_fallback":
        client = _ProviderErrorClient()
    elif arm == "invalid_response_fallback":
        client = _InvalidResponseClient()
    else:
        client = None
    with (
        _network_connect_guard() as network_measurement,
        _isolated_session_factory() as factory,
    ):
        with factory() as db:
            user = models.User(
                email=f"synthetic-campaign-{seed_block}@dronedream.invalid",
                display_name="Synthetic campaign",
            )
            db.add(user)
            db.flush()
            request = _job_request(seed_block, arm=arm)
            job = job_services._create_job_from_config(
                db,
                user=user,
                req=request,
            )
            job_id = job.id
            db.commit()
        outcome, trace = _drive_job(
            factory,
            job_id=job_id,
            client=client,
        )
    network_calls = network_measurement.attempt_count
    if network_calls:
        raise ValueError(f"campaign arm attempted {network_calls} network connection(s)")
    provider_calls = client.calls if client is not None else 0
    return {
        "arm": arm,
        "provider_calls": provider_calls,
        "network_calls": network_calls,
        "network_connect_guard_enforced": True,
        "real_credentials_used": False,
        "fallback_trace": trace,
        "outcome_sha256": _sha256(outcome),
        "component_sha256": {
            component: _sha256(outcome[component])
            for component in _OUTCOME_COMPONENTS
        },
        "outcome": outcome,
    }


def _verify_arm_trace(arm: dict[str, Any]) -> None:
    arm_name = arm.get("arm")
    trace = arm.get("fallback_trace")
    if not isinstance(trace, dict):
        raise ValueError("campaign arm fallback trace is invalid")
    fallbacks = trace.get("fallback_events")
    executions = trace.get("execution_events")
    if not isinstance(fallbacks, list) or not isinstance(executions, list):
        raise ValueError("campaign arm fallback trace rows are invalid")
    if arm_name == "direct_portfolio":
        if arm.get("provider_calls") != 0 or fallbacks or executions:
            raise ValueError("direct portfolio arm unexpectedly used the Harness")
        return
    expected_reason = (
        "client_error" if arm_name == "provider_error_fallback" else "invalid_response"
    )
    if (
        not fallbacks
        or arm.get("provider_calls") != len(fallbacks)
        or any(
            row != {"reason": expected_reason, "tool_id": "optimizer_portfolio"}
            for row in fallbacks
        )
        or len(executions) != len(fallbacks)
        or any(
            row.get("tool_id") != "optimizer_portfolio"
            or row.get("decision_source") != "deterministic_fallback"
            or row.get("fallback_reason") != expected_reason
            or row.get("status") != "dispatched"
            for row in executions
        )
    ):
        raise ValueError(f"{arm_name} did not exercise the declared fallback")


def build_harness_outcome_campaign() -> dict[str, Any]:
    """Run all matched arms and return a deterministic signed artifact."""

    block_rows: list[dict[str, Any]] = []
    comparison_rows: list[dict[str, Any]] = []
    for block_index, seed_block in enumerate(
        HARNESS_OUTCOME_CAMPAIGN_SEED_BLOCKS,
        start=1,
    ):
        arms = [_run_arm(seed_block, arm) for arm in HARNESS_OUTCOME_CAMPAIGN_ARMS]
        by_name = {str(arm["arm"]): arm for arm in arms}
        reference = by_name["direct_portfolio"]
        for arm in arms:
            _verify_arm_trace(arm)
            if (
                arm["network_calls"] != 0
                or arm["network_connect_guard_enforced"] is not True
                or arm["real_credentials_used"] is not False
            ):
                raise ValueError("campaign arm violated the offline credential boundary")
        for arm_name in HARNESS_OUTCOME_CAMPAIGN_ARMS[1:]:
            arm = by_name[arm_name]
            component_matches = {
                component: (
                    arm["outcome"][component] == reference["outcome"][component]
                )
                for component in _OUTCOME_COMPONENTS
            }
            exact_match = arm["outcome"] == reference["outcome"]
            if not exact_match or not all(component_matches.values()):
                raise ValueError(
                    f"{arm_name} diverged from direct portfolio in seed block {seed_block}"
                )
            comparison_rows.append(
                {
                    "block_id": block_index,
                    "seed_block": seed_block,
                    "reference_arm": "direct_portfolio",
                    "comparison_arm": arm_name,
                    "exact_outcome_match": exact_match,
                    **{
                        f"{component}_match": component_matches[component]
                        for component in _OUTCOME_COMPONENTS
                    },
                }
            )
        block_rows.append(
            {
                "block_id": block_index,
                "seed_block": seed_block,
                "training_seeds": [
                    seed_block + 1,
                    seed_block + 2,
                    seed_block + 3,
                ],
                "holdout_seeds": [seed_block + 99],
                "arms": arms,
            }
        )
    unsigned: dict[str, Any] = {
        "schema_version": HARNESS_OUTCOME_CAMPAIGN_SCHEMA_VERSION,
        "evidence_class": HARNESS_OUTCOME_CAMPAIGN_EVIDENCE_CLASS,
        "claim_label": HARNESS_OUTCOME_CAMPAIGN_LABEL,
        "claim_boundary": HARNESS_OUTCOME_CAMPAIGN_CLAIM_BOUNDARY,
        "physical_fidelity": False,
        "simulator_backend": "mock",
        "live_model_calls": False,
        "network_calls": sum(
            arm["network_calls"]
            for block in block_rows
            for arm in block["arms"]
        ),
        "real_credentials_used": False,
        "llm_superiority_claim_permitted": False,
        "harness_causal_benefit_claim_permitted": False,
        "px4_or_flight_claim_permitted": False,
        "protocol": {
            "seed_block_count": len(HARNESS_OUTCOME_CAMPAIGN_SEED_BLOCKS),
            "arm_count": len(HARNESS_OUTCOME_CAMPAIGN_ARMS),
            "arms": list(HARNESS_OUTCOME_CAMPAIGN_ARMS),
            "max_iterations_per_arm": HARNESS_OUTCOME_CAMPAIGN_MAX_ITERATIONS,
            "max_total_trials_per_arm": HARNESS_OUTCOME_CAMPAIGN_MAX_TOTAL_TRIALS,
            "training_cases_per_candidate": 3,
            "holdout_cases_per_full_fidelity_candidate": 1,
            "common_random_numbers": True,
            "network_measurement": (
                "socket.connect, socket.connect_ex, and "
                "socket.create_connection are blocked and counted per arm"
            ),
            "client_injection_boundary": (
                "process-local test-only object; absent from JobCreateRequest "
                "and unavailable to the production API"
            ),
            "nondeterministic_fields_excluded": [
                "database_primary_keys",
                "timestamps",
                "worker_ids",
                "filesystem_paths",
                "evidence_ids",
            ],
            "strict_components": list(_OUTCOME_COMPONENTS),
        },
        "summary": {
            "seed_block_count": len(HARNESS_OUTCOME_CAMPAIGN_SEED_BLOCKS),
            "arm_run_count": len(HARNESS_OUTCOME_CAMPAIGN_SEED_BLOCKS)
            * len(HARNESS_OUTCOME_CAMPAIGN_ARMS),
            "total_persisted_trials": sum(
                int(arm["outcome"]["budget"]["trial_count"])
                for block in block_rows
                for arm in block["arms"]
            ),
            "fallback_comparison_count": len(comparison_rows),
            "exact_outcome_match_count": sum(
                row["exact_outcome_match"] is True for row in comparison_rows
            ),
            "all_fallback_outcomes_match_direct_portfolio": all(
                row["exact_outcome_match"] is True for row in comparison_rows
            ),
            "all_evidence_complete": all(
                arm["outcome"]["evidence_completeness"]["completeness_rate"] == 1.0
                for block in block_rows
                for arm in block["arms"]
            ),
        },
        "comparison_rows": comparison_rows,
        "block_rows": block_rows,
    }
    return {
        **unsigned,
        "artifact_sha256": _sha256(unsigned),
    }


def verify_harness_outcome_campaign(payload: object) -> dict[str, Any]:
    """Verify artifact integrity, claim bounds, traces, and outcome equality."""

    if not isinstance(payload, dict):
        raise ValueError("Harness outcome campaign must be an object")
    artifact = dict(payload)
    declared_hash = artifact.pop("artifact_sha256", None)
    if not isinstance(declared_hash, str) or len(declared_hash) != 64:
        raise ValueError("Harness outcome campaign artifact_sha256 is invalid")
    if declared_hash != _sha256(artifact):
        raise ValueError("Harness outcome campaign artifact_sha256 does not recompute")
    if (
        artifact.get("schema_version") != HARNESS_OUTCOME_CAMPAIGN_SCHEMA_VERSION
        or artifact.get("evidence_class") != HARNESS_OUTCOME_CAMPAIGN_EVIDENCE_CLASS
        or artifact.get("claim_label") != HARNESS_OUTCOME_CAMPAIGN_LABEL
        or artifact.get("physical_fidelity") is not False
        or artifact.get("simulator_backend") != "mock"
        or artifact.get("live_model_calls") is not False
        or artifact.get("network_calls") != 0
        or artifact.get("real_credentials_used") is not False
        or artifact.get("llm_superiority_claim_permitted") is not False
        or artifact.get("harness_causal_benefit_claim_permitted") is not False
        or artifact.get("px4_or_flight_claim_permitted") is not False
    ):
        raise ValueError("Harness outcome campaign claim boundary is invalid")
    block_rows = artifact.get("block_rows")
    if not isinstance(block_rows, list) or len(block_rows) != len(
        HARNESS_OUTCOME_CAMPAIGN_SEED_BLOCKS
    ):
        raise ValueError("Harness outcome campaign block rows are invalid")
    recomputed_comparisons: list[dict[str, Any]] = []
    recomputed_network_calls = 0
    for expected_index, (block, seed_block) in enumerate(
        zip(block_rows, HARNESS_OUTCOME_CAMPAIGN_SEED_BLOCKS, strict=True),
        start=1,
    ):
        if (
            not isinstance(block, dict)
            or block.get("block_id") != expected_index
            or block.get("seed_block") != seed_block
        ):
            raise ValueError("Harness outcome campaign seed blocks drifted")
        raw_arms = block.get("arms")
        if not isinstance(raw_arms, list):
            raise ValueError("Harness outcome campaign arms are invalid")
        by_name = {
            arm.get("arm"): arm
            for arm in raw_arms
            if isinstance(arm, dict) and isinstance(arm.get("arm"), str)
        }
        if tuple(by_name) != HARNESS_OUTCOME_CAMPAIGN_ARMS:
            raise ValueError("Harness outcome campaign arm order or set drifted")
        for arm in raw_arms:
            if not isinstance(arm, dict):
                raise ValueError("Harness outcome campaign arm is invalid")
            _verify_arm_trace(arm)
            outcome = arm.get("outcome")
            if (
                not isinstance(outcome, dict)
                or arm.get("outcome_sha256") != _sha256(outcome)
                or arm.get("network_calls") != 0
                or arm.get("network_connect_guard_enforced") is not True
                or arm.get("real_credentials_used") is not False
            ):
                raise ValueError("Harness outcome campaign arm integrity is invalid")
            recomputed_network_calls += int(arm["network_calls"])
            component_hashes = arm.get("component_sha256")
            if not isinstance(component_hashes, dict) or any(
                component_hashes.get(component) != _sha256(outcome.get(component))
                for component in _OUTCOME_COMPONENTS
            ):
                raise ValueError("Harness outcome campaign component hash is invalid")
        reference = by_name["direct_portfolio"]
        for arm_name in HARNESS_OUTCOME_CAMPAIGN_ARMS[1:]:
            arm = by_name[arm_name]
            component_matches = {
                component: (
                    arm["outcome"][component] == reference["outcome"][component]
                )
                for component in _OUTCOME_COMPONENTS
            }
            recomputed_comparisons.append(
                {
                    "block_id": expected_index,
                    "seed_block": seed_block,
                    "reference_arm": "direct_portfolio",
                    "comparison_arm": arm_name,
                    "exact_outcome_match": arm["outcome"] == reference["outcome"],
                    **{
                        f"{component}_match": component_matches[component]
                        for component in _OUTCOME_COMPONENTS
                    },
                }
            )
    if artifact.get("network_calls") != recomputed_network_calls:
        raise ValueError("Harness outcome campaign network count does not recompute")
    if artifact.get("comparison_rows") != recomputed_comparisons or not all(
        row["exact_outcome_match"] is True
        and all(row[f"{component}_match"] is True for component in _OUTCOME_COMPONENTS)
        for row in recomputed_comparisons
    ):
        raise ValueError("Harness fallback outcomes are not strictly equivalent")
    summary = artifact.get("summary")
    expected_summary = {
        "seed_block_count": len(HARNESS_OUTCOME_CAMPAIGN_SEED_BLOCKS),
        "arm_run_count": len(HARNESS_OUTCOME_CAMPAIGN_SEED_BLOCKS)
        * len(HARNESS_OUTCOME_CAMPAIGN_ARMS),
        "total_persisted_trials": sum(
            int(arm["outcome"]["budget"]["trial_count"])
            for block in block_rows
            for arm in block["arms"]
        ),
        "fallback_comparison_count": len(recomputed_comparisons),
        "exact_outcome_match_count": len(recomputed_comparisons),
        "all_fallback_outcomes_match_direct_portfolio": True,
        "all_evidence_complete": all(
            arm["outcome"]["evidence_completeness"]["completeness_rate"] == 1.0
            for block in block_rows
            for arm in block["arms"]
        ),
    }
    if summary != expected_summary:
        raise ValueError("Harness outcome campaign summary does not recompute")
    return payload


def load_harness_outcome_campaign(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("invalid Harness outcome campaign JSON artifact") from exc
    return verify_harness_outcome_campaign(payload)


__all__ = [
    "HARNESS_OUTCOME_CAMPAIGN_ARMS",
    "HARNESS_OUTCOME_CAMPAIGN_CLAIM_BOUNDARY",
    "HARNESS_OUTCOME_CAMPAIGN_EVIDENCE_CLASS",
    "HARNESS_OUTCOME_CAMPAIGN_LABEL",
    "HARNESS_OUTCOME_CAMPAIGN_SCHEMA_VERSION",
    "HARNESS_OUTCOME_CAMPAIGN_SEED_BLOCKS",
    "build_harness_outcome_campaign",
    "load_harness_outcome_campaign",
    "verify_harness_outcome_campaign",
]
