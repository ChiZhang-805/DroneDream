"""Durable, bounded cognitive-turn accounting and adaptive trigger policy.

Provider calls are side effects.  A worker must therefore commit an immutable
attempt receipt *before* network I/O, and it must never repeat a turn whose
outcome is missing after a crash.  This module owns that boundary as well as
the deterministic policy that can authorize the optional diagnosis and critic
turns.  It never receives credentials, raw chat history, or a callable tool.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import shutil
import subprocess
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Literal

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app import models, schemas
from app.optimization.outcome_taxonomy import (
    classify_trial_outcome,
    is_optimizer_learning_failure,
)
from app.optimization.scenarios import resolve_scenario_case
from app.orchestration.harness_context import HarnessEvidenceSnapshot
from app.orchestration.provider_feedback import compile_candidate_feedback
from app.orchestration.provider_request_accounting import (
    provider_request_outcome_pending,
    recover_abandoned_provider_requests,
)
from app.simulator.base import (
    FAILURE_SIMULATION,
    FAILURE_TIMEOUT,
    FAILURE_UNSTABLE,
)

COGNITIVE_ATTEMPT_SCHEMA = "dronedream.harness-cognitive-turn-attempt/v1"
COGNITIVE_OUTCOME_SCHEMA = "dronedream.harness-cognitive-turn-outcome/v1"
COGNITIVE_TRIGGER_POLICY_VERSION = "adaptive-trigger-v1"
COGNITIVE_POLICY_VERSION = "adaptive-2-4-v1"
MAX_PROVIDER_TURNS_PER_GENERATION = 4
MAX_PROVIDER_TURNS_PER_JOB = 128

TurnRole = Literal["plan", "revision", "diagnosis", "critic"]
BenchmarkTurnRole = Literal["direct_proposal"]
TurnOutcomeStatus = Literal[
    "succeeded",
    "provider_failed",
    "invalid_schema",
    "source_drift",
    "cancelled",
    "indeterminate",
]

_EMPTY_SHA256 = hashlib.sha256(b"[]").hexdigest()
_HEX = frozenset("0123456789abcdef")
_ROLE_BY_INDEX: dict[int, TurnRole] = {
    1: "plan",
    2: "revision",
    3: "diagnosis",
    4: "critic",
}
_TRIGGER_FAMILY = {
    "trailing_stagnation": "progress",
    "tool_direction_conflict": "conflict",
    "prediction_outcome_mismatch": "mismatch",
    "domain_failure_spike": "physical_failure",
    "ood_no_transfer_memory": "ood",
    "crash_or_instability": "physical_failure",
    "timeout_or_sensor_anomaly": "physical_failure",
    "near_threshold_uncertain": "threshold",
    "hard_boundary_candidate": "boundary",
}
_SEVERITY_ESCALATION = frozenset(
    {
        "crash_or_instability",
        "timeout_or_sensor_anomaly",
        "hard_boundary_candidate",
    }
)


class CognitiveTurnBlocked(RuntimeError):
    """A provider turn was rejected before network I/O."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class CognitiveTurnPending(CognitiveTurnBlocked):
    """Another worker still owns an attempted provider turn."""

    def __init__(self) -> None:
        super().__init__(
            "turn_outcome_pending",
            "This cognitive turn is already in flight; finalization must be deferred.",
        )


@dataclass(frozen=True)
class CognitiveTurnAttempt:
    receipt_id: str
    source_commit: str


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def recover_existing_cognitive_turn(
    db: Session,
    job: models.Job,
    *,
    generation_index: int,
    turn_index: int,
) -> Literal["new", "pending", "consumed"]:
    """Classify a durable turn without ever replaying provider network I/O.

    A receipt without an outcome is normally an in-flight call, so a reclaimed
    finalizer must defer. Once the configured request/retry window plus its
    safety margin has elapsed, a missing outcome is frozen as indeterminate and
    remains charged to the Job cap. A later finalizer may then use an explicit
    deterministic fallback, but it must not call the provider again.
    """

    receipt = db.scalar(
        select(models.HarnessCognitiveTurnReceipt).where(
            models.HarnessCognitiveTurnReceipt.job_id == job.id,
            models.HarnessCognitiveTurnReceipt.generation_index == generation_index,
            models.HarnessCognitiveTurnReceipt.turn_index == turn_index,
        )
    )
    if receipt is None:
        return "new"
    if receipt.outcome is not None:
        return "consumed"

    from app.config import get_settings

    settings = get_settings()
    recover_abandoned_provider_requests(
        db,
        job,
        cognitive_turn_receipt_id=receipt.id,
        request_timeout_seconds=settings.llm_request_timeout_seconds,
    )
    if provider_request_outcome_pending(
        db,
        cognitive_turn_receipt_id=receipt.id,
    ):
        return "pending"
    outcome_deadline = _as_utc(receipt.attempted_at) + timedelta(
        seconds=(
            settings.llm_request_timeout_seconds * (job.provider_max_retries + 2)
            + 60
        )
    )
    if datetime.now(timezone.utc) < outcome_deadline:
        return "pending"

    finish_cognitive_turn(
        db,
        job,
        CognitiveTurnAttempt(
            receipt_id=receipt.id,
            source_commit=receipt.source_commit,
        ),
        status="indeterminate",
        error_code="provider_outcome_indeterminate",
    )
    return "consumed"


@dataclass(frozen=True)
class CognitiveTriggerEvaluation:
    """Provider-safe decision for the optional T3/T4 turns."""

    policy_version: str
    diagnosis_reasons: tuple[str, ...]
    critic_reasons: tuple[str, ...]
    suppressed_by_cooldown: tuple[str, ...]
    evidence: dict[str, Any]

    @property
    def diagnosis_required(self) -> bool:
        return bool(self.diagnosis_reasons)

    @property
    def critic_required(self) -> bool:
        return bool(self.critic_reasons)


def canonical_json(value: object) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def sha256_json(value: object) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def empty_tool_outputs_sha256() -> str:
    return _EMPTY_SHA256


def _valid_commit(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip().lower()
    if len(normalized) != 40 or any(char not in _HEX for char in normalized):
        return None
    return normalized


def _manifest_source_commit(path: Path) -> str:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise CognitiveTurnBlocked(
            "source_manifest_invalid",
            f"Active Engine Pack manifest cannot be verified: {path}",
        ) from exc
    source = payload.get("source") if isinstance(payload, dict) else None
    commit = _valid_commit(source.get("gitCommit")) if isinstance(source, dict) else None
    if commit is None:
        raise CognitiveTurnBlocked(
            "source_manifest_invalid",
            f"Active Engine Pack manifest lacks a valid source commit: {path}",
        )
    return commit


def _repository_source_commit() -> str | None:
    git = shutil.which("git")
    if git is None:
        return None
    current = Path(__file__).resolve()
    for parent in current.parents:
        if not (parent / ".git").exists():
            continue
        try:
            completed = subprocess.run(  # noqa: S603 - resolved binary, fixed argv.
                [git, "rev-parse", "HEAD"],
                cwd=parent,
                check=True,
                capture_output=True,
                text=True,
                timeout=5,
            )
        except (OSError, subprocess.SubprocessError, UnicodeError):
            return None
        return _valid_commit(completed.stdout)
    return None


def resolve_source_commit() -> str:
    """Resolve the exact active Engine Pack source, failing closed on drift."""

    configured_raw = os.environ.get("DRONEDREAM_SOURCE_COMMIT")
    configured = _valid_commit(configured_raw)
    if configured_raw is not None and configured is None:
        raise CognitiveTurnBlocked(
            "source_configuration_invalid",
            "DRONEDREAM_SOURCE_COMMIT is not a full Git commit.",
        )
    manifest_paths = (
        Path("/opt/dronedream/engine/current/engine-pack-manifest.json"),
        Path(os.environ["DRONEDREAM_ENGINE_PACK_MANIFEST"])
        if os.environ.get("DRONEDREAM_ENGINE_PACK_MANIFEST")
        else None,
    )
    manifest_commits = {
        _manifest_source_commit(path)
        for path in manifest_paths
        if path is not None and path.is_file()
    }
    if len(manifest_commits) > 1:
        raise CognitiveTurnBlocked(
            "source_drift",
            "Active Engine Pack manifests disagree on the software source commit.",
        )
    manifest = next(iter(manifest_commits), None)
    if configured is not None and manifest is not None and configured != manifest:
        raise CognitiveTurnBlocked(
            "source_drift",
            "Configured and active Engine Pack source commits disagree.",
        )
    resolved = configured or manifest or _repository_source_commit()
    if resolved is None:
        raise CognitiveTurnBlocked(
            "source_unavailable",
            "The active software source commit cannot be verified.",
        )
    return resolved


def _strict_sha256(value: str, *, field: str) -> str:
    normalized = value.strip().lower()
    if len(normalized) != 64 or any(char not in _HEX for char in normalized):
        raise CognitiveTurnBlocked("invalid_receipt_hash", f"{field} is not a SHA-256 digest")
    return normalized


def _commit_cognitive_turn(
    db: Session,
    job: models.Job,
    *,
    generation_index: int,
    turn_index: int,
    turn_role: str,
    trigger_policy_version: str,
    trigger_reasons: Sequence[str],
    model_snapshot: str,
    prompt_sha256: str,
    evidence_sha256: str,
    schema_sha256: str,
    tool_outputs_sha256: str,
) -> CognitiveTurnAttempt:
    """Commit an already-authorized turn without relaxing its caller's policy."""

    if not turn_role or len(turn_role) > 32:
        raise CognitiveTurnBlocked("turn_role_invalid", "Cognitive turn role is invalid.")
    if not trigger_policy_version or len(trigger_policy_version) > 32:
        raise CognitiveTurnBlocked(
            "trigger_policy_invalid",
            "Cognitive trigger policy version is invalid.",
        )
    if not model_snapshot or len(model_snapshot) > 128:
        raise CognitiveTurnBlocked(
            "invalid_model_snapshot",
            "Model snapshot is missing or too long.",
        )
    prompt_hash = _strict_sha256(prompt_sha256, field="prompt_sha256")
    evidence_hash = _strict_sha256(evidence_sha256, field="evidence_sha256")
    schema_hash = _strict_sha256(schema_sha256, field="schema_sha256")
    tool_hash = _strict_sha256(tool_outputs_sha256, field="tool_outputs_sha256")
    reasons = tuple(dict.fromkeys(str(reason) for reason in trigger_reasons if str(reason)))
    if len(reasons) > 16:
        raise CognitiveTurnBlocked("too_many_trigger_reasons", "Trigger reason count exceeds 16.")

    existing_turn = db.scalar(
        select(models.HarnessCognitiveTurnReceipt).where(
            models.HarnessCognitiveTurnReceipt.job_id == job.id,
            models.HarnessCognitiveTurnReceipt.generation_index == generation_index,
            models.HarnessCognitiveTurnReceipt.turn_index == turn_index,
        )
    )
    if existing_turn is not None:
        if existing_turn.outcome is None:
            raise CognitiveTurnPending()
        raise CognitiveTurnBlocked(
            "turn_result_not_replayable",
            "This cognitive turn was consumed and cannot be replayed.",
        )
    source_commit = resolve_source_commit()
    duplicate = db.scalar(
        select(models.HarnessCognitiveTurnReceipt.id).where(
            models.HarnessCognitiveTurnReceipt.job_id == job.id,
            models.HarnessCognitiveTurnReceipt.turn_role == turn_role,
            models.HarnessCognitiveTurnReceipt.source_commit == source_commit,
            models.HarnessCognitiveTurnReceipt.model_snapshot == model_snapshot,
            models.HarnessCognitiveTurnReceipt.prompt_sha256 == prompt_hash,
            models.HarnessCognitiveTurnReceipt.evidence_sha256 == evidence_hash,
            models.HarnessCognitiveTurnReceipt.schema_sha256 == schema_hash,
            models.HarnessCognitiveTurnReceipt.tool_outputs_sha256 == tool_hash,
        )
    )
    if duplicate is not None:
        raise CognitiveTurnBlocked(
            "duplicate_cognitive_content",
            "Identical cognitive content was already charged to this Job.",
        )
    absolute_cap = min(MAX_PROVIDER_TURNS_PER_JOB, max(0, int(job.provider_turn_cap)))
    claimed = db.execute(
        update(models.Job)
        .where(
            models.Job.id == job.id,
            models.Job.provider_turns_attempted < absolute_cap,
        )
        .values(
            provider_turns_attempted=models.Job.provider_turns_attempted + 1,
        )
        .execution_options(synchronize_session=False)
    )
    if getattr(claimed, "rowcount", None) != 1:
        raise CognitiveTurnBlocked(
            "provider_turn_cap_exhausted",
            "Job provider-turn cap exhausted.",
        )
    receipt = models.HarnessCognitiveTurnReceipt(
        job_id=job.id,
        receipt_schema=COGNITIVE_ATTEMPT_SCHEMA,
        generation_index=generation_index,
        turn_index=turn_index,
        turn_role=turn_role,
        trigger_policy_version=trigger_policy_version,
        trigger_reasons_json=list(reasons),
        source_commit=source_commit,
        model_snapshot=model_snapshot,
        prompt_sha256=prompt_hash,
        evidence_sha256=evidence_hash,
        schema_sha256=schema_hash,
        tool_outputs_sha256=tool_hash,
    )
    db.add(receipt)
    db.commit()
    db.refresh(job)
    db.refresh(receipt)
    return CognitiveTurnAttempt(receipt_id=receipt.id, source_commit=source_commit)


def begin_cognitive_turn(
    db: Session,
    job: models.Job,
    *,
    generation_index: int,
    turn_index: int,
    turn_role: TurnRole,
    trigger_reasons: Sequence[str],
    model_snapshot: str,
    prompt_sha256: str,
    evidence_sha256: str,
    schema_sha256: str,
    tool_outputs_sha256: str,
) -> CognitiveTurnAttempt:
    """Commit one product-Harness turn before the caller performs network I/O."""

    if job.cognitive_policy_version != COGNITIVE_POLICY_VERSION:
        raise CognitiveTurnBlocked(
            "unsupported_cognitive_policy",
            "The Job cognitive policy is not supported by this Engine Pack.",
        )
    if job.first_qualified_candidate_id is not None:
        raise CognitiveTurnBlocked(
            "first_qualified_stop",
            "A first-qualified parent never resumes provider turns; exploration uses a child Job.",
        )
    if generation_index != job.current_generation + 1:
        raise CognitiveTurnBlocked(
            "generation_drift",
            "Cognitive generation no longer matches Job state.",
        )
    if _ROLE_BY_INDEX.get(turn_index) != turn_role:
        raise CognitiveTurnBlocked("turn_role_mismatch", "Cognitive turn index and role disagree.")
    if not 1 <= turn_index <= MAX_PROVIDER_TURNS_PER_GENERATION:
        raise CognitiveTurnBlocked(
            "turn_limit_exceeded",
            "Per-generation cognitive turn cap exceeded.",
        )
    required_prior_index = {2: 1, 3: 2, 4: 2}.get(turn_index)
    if required_prior_index is not None:
        prior_turn = db.scalar(
            select(models.HarnessCognitiveTurnReceipt.id).where(
                models.HarnessCognitiveTurnReceipt.job_id == job.id,
                models.HarnessCognitiveTurnReceipt.generation_index == generation_index,
                models.HarnessCognitiveTurnReceipt.turn_index == required_prior_index,
            )
        )
        if prior_turn is None:
            raise CognitiveTurnBlocked(
                "cognitive_predecessor_missing",
                "The required earlier cognitive turn was not attempted.",
            )
    return _commit_cognitive_turn(
        db,
        job,
        generation_index=generation_index,
        turn_index=turn_index,
        turn_role=turn_role,
        trigger_policy_version=COGNITIVE_TRIGGER_POLICY_VERSION,
        trigger_reasons=trigger_reasons,
        model_snapshot=model_snapshot,
        prompt_sha256=prompt_sha256,
        evidence_sha256=evidence_sha256,
        schema_sha256=schema_sha256,
        tool_outputs_sha256=tool_outputs_sha256,
    )


def begin_benchmark_direct_turn(
    db: Session,
    job: models.Job,
    *,
    generation_index: int,
    turn_role: BenchmarkTurnRole,
    model_snapshot: str,
    prompt_sha256: str,
    evidence_sha256: str,
    schema_sha256: str,
    tool_outputs_sha256: str,
) -> CognitiveTurnAttempt:
    """Persist one preregistered benchmark-direct turn without changing Job policy."""

    if job.first_qualified_candidate_id is not None:
        raise CognitiveTurnBlocked(
            "first_qualified_stop",
            "A first-qualified benchmark run cannot spend another provider turn.",
        )
    if generation_index != job.current_generation + 1:
        raise CognitiveTurnBlocked(
            "generation_drift",
            "Benchmark generation no longer matches Job state.",
        )
    if turn_role != "direct_proposal":
        raise CognitiveTurnBlocked(
            "turn_role_mismatch",
            "The direct benchmark adapter permits only direct_proposal.",
        )
    if job.provider_max_retries != 0:
        raise CognitiveTurnBlocked(
            "benchmark_retry_policy_drift",
            "Formal benchmark provider retries must be zero.",
        )
    return _commit_cognitive_turn(
        db,
        job,
        generation_index=generation_index,
        turn_index=1,
        turn_role=turn_role,
        trigger_policy_version="benchmark-llm-direct-v1",
        trigger_reasons=("preregistered-direct-turn",),
        model_snapshot=model_snapshot,
        prompt_sha256=prompt_sha256,
        evidence_sha256=evidence_sha256,
        schema_sha256=schema_sha256,
        tool_outputs_sha256=tool_outputs_sha256,
    )


def finish_cognitive_turn(
    db: Session,
    job: models.Job,
    attempt: CognitiveTurnAttempt,
    *,
    status: TurnOutcomeStatus,
    response: Mapping[str, Any] | None = None,
    error_code: str | None = None,
) -> TurnOutcomeStatus:
    """Append and commit the terminal outcome for one attempted turn."""

    receipt = db.get(models.HarnessCognitiveTurnReceipt, attempt.receipt_id)
    if receipt is None or receipt.job_id != job.id:
        raise CognitiveTurnBlocked("turn_receipt_missing", "Cognitive attempt receipt is missing.")
    if receipt.outcome is not None:
        raise CognitiveTurnBlocked("turn_outcome_exists", "Cognitive turn outcome is append-only.")
    try:
        current_source = resolve_source_commit()
    except CognitiveTurnBlocked:
        current_source = None
    final_status: TurnOutcomeStatus = status
    if current_source != attempt.source_commit:
        final_status = "source_drift"
        error_code = "source_drift"
    response_hash = sha256_json(dict(response)) if response is not None else None
    if final_status == "succeeded" and response_hash is None:
        raise CognitiveTurnBlocked(
            "successful_response_missing",
            "Successful turn lacks a response hash.",
        )
    outcome = models.HarnessCognitiveTurnOutcome(
        turn_receipt_id=receipt.id,
        outcome_schema=COGNITIVE_OUTCOME_SCHEMA,
        status=final_status,
        response_sha256=response_hash,
        error_code=error_code[:64] if error_code else None,
    )
    db.add(outcome)
    if final_status == "succeeded":
        updated = db.execute(
            update(models.Job)
            .where(
                models.Job.id == job.id,
                models.Job.provider_turns_succeeded < models.Job.provider_turns_attempted,
            )
            .values(
                provider_turns_succeeded=(models.Job.provider_turns_succeeded + 1),
            )
            .execution_options(synchronize_session=False)
        )
        if getattr(updated, "rowcount", None) != 1:
            raise CognitiveTurnBlocked(
                "provider_turn_accounting_invalid",
                "Succeeded provider-turn accounting would exceed attempts.",
            )
    db.commit()
    db.refresh(job)
    return final_status


def cancel_cognitive_turn_if_job_terminal(
    db: Session,
    job: models.Job,
    attempt: CognitiveTurnAttempt,
) -> str | None:
    """Re-read server state after provider I/O and seal a stale result safely."""

    db.refresh(job)
    if job.status not in schemas.JOB_TERMINAL_STATUSES:
        return None
    finish_cognitive_turn(
        db,
        job,
        attempt,
        status="cancelled",
        error_code=f"job_{job.status.lower()}_during_provider_turn",
    )
    return job.status


def cognitive_turn_counts(
    db: Session,
    job: models.Job,
    *,
    generation_index: int,
) -> tuple[int, int]:
    """Return durable attempted/succeeded counts for one generation."""

    attempted = int(
        db.scalar(
            select(func.count(models.HarnessCognitiveTurnReceipt.id)).where(
                models.HarnessCognitiveTurnReceipt.job_id == job.id,
                models.HarnessCognitiveTurnReceipt.generation_index == generation_index,
            )
        )
        or 0
    )
    succeeded = int(
        db.scalar(
            select(func.count(models.HarnessCognitiveTurnOutcome.id))
            .join(
                models.HarnessCognitiveTurnReceipt,
                models.HarnessCognitiveTurnOutcome.turn_receipt_id
                == models.HarnessCognitiveTurnReceipt.id,
            )
            .where(
                models.HarnessCognitiveTurnReceipt.job_id == job.id,
                models.HarnessCognitiveTurnReceipt.generation_index == generation_index,
                models.HarnessCognitiveTurnOutcome.status == "succeeded",
            )
        )
        or 0
    )
    if attempted > MAX_PROVIDER_TURNS_PER_GENERATION or succeeded > attempted:
        raise CognitiveTurnBlocked(
            "provider_turn_accounting_invalid",
            "Generation provider-turn accounting violates the cognitive cap.",
        )
    return attempted, succeeded


def _number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    numeric = float(value)
    return numeric if math.isfinite(numeric) else None


def _near_threshold(job: models.Job, snapshot: HarnessEvidenceSnapshot) -> bool:
    for candidate in snapshot.candidates:
        rmse = _number(candidate.metrics.get("rmse"))
        max_error = _number(candidate.metrics.get("max_error"))
        if (
            job.target_rmse is not None
            and rmse is not None
            and job.target_rmse < rmse <= job.target_rmse * 1.15
        ):
            return True
        if (
            job.target_max_error is not None
            and max_error is not None
            and job.target_max_error < max_error <= job.target_max_error * 1.15
        ):
            return True
    return False


def _latest_outcome(snapshot: HarnessEvidenceSnapshot) -> Any | None:
    for memory in reversed(snapshot.decision_memory):
        if memory.reflection_status == "verified_complete" and memory.observed_outcome is not None:
            return memory.observed_outcome
    return None


def _usable_metric(trial: models.Trial) -> bool:
    metric = trial.metric
    return bool(
        trial.status == "COMPLETED"
        and metric is not None
        and _number(metric.rmse) is not None
        and _number(metric.max_error) is not None
        and _number(metric.completion_time) is not None
    )


def _training_failure_summary(job: models.Job) -> dict[str, int]:
    """Return fixed training-only failure classes with no raw Trial content."""

    if not isinstance(job.scenario_suite_json, dict) or not job.scenario_suite_json:
        return {
            "unstable_or_simulation_failure_count": 0,
            "timeout_count": 0,
            "sensor_case_domain_failure_count": 0,
        }
    try:
        suite = schemas.ScenarioSuiteConfig(**job.scenario_suite_json)
    except (TypeError, ValueError):
        return {
            "unstable_or_simulation_failure_count": 0,
            "timeout_count": 0,
            "sensor_case_domain_failure_count": 0,
        }
    unstable = 0
    timeout = 0
    sensor = 0
    sensor_scenarios = frozenset({"noise_perturbed", "gps_dropout"})
    for candidate in job.candidates:
        feedback = compile_candidate_feedback(candidate, scenario_suite=suite)
        if not feedback.usable:
            continue
        for trial in candidate.trials:
            resolution = resolve_scenario_case(
                suite,
                scenario_type=trial.scenario_type,
                scenario_config=trial.scenario_config_json,
                seed=trial.seed,
            )
            if not resolution.matched or resolution.case is None or resolution.case.holdout:
                continue
            outcome = classify_trial_outcome(
                status=trial.status,
                failure_code=trial.failure_code,
                usable_metric=_usable_metric(trial),
            )
            if not is_optimizer_learning_failure(outcome):
                continue
            if trial.failure_code in {FAILURE_SIMULATION, FAILURE_UNSTABLE}:
                unstable += 1
            if trial.failure_code == FAILURE_TIMEOUT:
                timeout += 1
            if resolution.case.scenario_type in sensor_scenarios:
                sensor += 1
    return {
        "unstable_or_simulation_failure_count": unstable,
        "timeout_count": timeout,
        "sensor_case_domain_failure_count": sensor,
    }


def _cooldown_families(job: models.Job, generation_index: int) -> set[str]:
    families: set[str] = set()
    for receipt in job.cognitive_turn_receipts:
        if receipt.generation_index != generation_index - 1:
            continue
        for reason in receipt.trigger_reasons_json:
            family = _TRIGGER_FAMILY.get(str(reason))
            if family is not None:
                families.add(family)
    return families


def evaluate_adaptive_triggers(
    job: models.Job,
    *,
    generation_index: int,
    snapshot: HarnessEvidenceSnapshot,
    proposal_tools: Mapping[str, str],
    selected_proposal_refs: Sequence[str],
    tool_direction_conflict: bool,
    hard_boundary_candidate: bool,
) -> CognitiveTriggerEvaluation:
    """Evaluate versioned T3/T4 triggers without holdout outcomes."""

    diagnosis: list[str] = []
    critic: list[str] = []
    latest = _latest_outcome(snapshot)
    failures = _training_failure_summary(job)
    if snapshot.search.trailing_stagnant_generations >= 2:
        diagnosis.append("trailing_stagnation")
    if tool_direction_conflict:
        diagnosis.append("tool_direction_conflict")
    if (
        latest is not None
        and latest.incumbent_score_before is not None
        and latest.cohort_best_score
        > latest.incumbent_score_before + max(abs(latest.incumbent_score_before) * 0.15, 1e-9)
    ):
        diagnosis.append("prediction_outcome_mismatch")
    latest_domain_failure_spike = bool(
        latest is not None
        and latest.optimizer_learning_trial_count > 0
        and latest.domain_failure_trial_count / latest.optimizer_learning_trial_count >= 0.25
    )
    if latest_domain_failure_spike or (
        snapshot.search.total_trial_count > 0 and snapshot.search.observed_failure_rate >= 0.25
    ):
        diagnosis.append("domain_failure_spike")
    if (
        generation_index >= 2
        and snapshot.scenarios.training_case_count > 1
        and not snapshot.cross_job_memory.experiences
        and snapshot.search.failed_trial_count > 0
    ):
        diagnosis.append("ood_no_transfer_memory")

    # These counts are derived only from verified, configured training Trials.
    # Holdout outcomes and raw failure text are unavailable downstream.
    if failures["unstable_or_simulation_failure_count"] > 0:
        critic.append("crash_or_instability")
    if failures["timeout_count"] > 0 or failures["sensor_case_domain_failure_count"] > 0:
        critic.append("timeout_or_sensor_anomaly")
    if _near_threshold(job, snapshot):
        critic.append("near_threshold_uncertain")
    if hard_boundary_candidate:
        critic.append("hard_boundary_candidate")

    cooldown = _cooldown_families(job, generation_index)
    suppressed: list[str] = []

    def apply_cooldown(reasons: list[str]) -> tuple[str, ...]:
        accepted: list[str] = []
        for reason in reasons:
            family = _TRIGGER_FAMILY[reason]
            if family in cooldown and reason not in _SEVERITY_ESCALATION:
                suppressed.append(reason)
            else:
                accepted.append(reason)
        return tuple(accepted)

    selected_tools = sorted(
        {proposal_tools[ref] for ref in selected_proposal_refs if ref in proposal_tools}
    )
    evidence = {
        "schema_id": "dronedream.adaptive-cognitive-trigger-evidence/v1",
        "generation": generation_index,
        "search": snapshot.search.model_dump(mode="json", exclude_none=True),
        "plan": snapshot.plan.model_dump(mode="json", exclude_none=True),
        "scenarios": snapshot.scenarios.model_dump(mode="json", exclude_none=True),
        "selected_proposal_refs": list(selected_proposal_refs),
        "selected_tools": selected_tools,
        "training_failure_summary": failures,
        "holdout_outcomes_visible": False,
    }
    return CognitiveTriggerEvaluation(
        policy_version=COGNITIVE_TRIGGER_POLICY_VERSION,
        diagnosis_reasons=apply_cooldown(diagnosis),
        critic_reasons=apply_cooldown(critic),
        suppressed_by_cooldown=tuple(dict.fromkeys(suppressed)),
        evidence=evidence,
    )


__all__ = [
    "COGNITIVE_ATTEMPT_SCHEMA",
    "COGNITIVE_OUTCOME_SCHEMA",
    "COGNITIVE_POLICY_VERSION",
    "COGNITIVE_TRIGGER_POLICY_VERSION",
    "CognitiveTriggerEvaluation",
    "CognitiveTurnAttempt",
    "CognitiveTurnBlocked",
    "CognitiveTurnPending",
    "begin_benchmark_direct_turn",
    "begin_cognitive_turn",
    "cancel_cognitive_turn_if_job_terminal",
    "canonical_json",
    "cognitive_turn_counts",
    "empty_tool_outputs_sha256",
    "evaluate_adaptive_triggers",
    "finish_cognitive_turn",
    "recover_existing_cognitive_turn",
    "resolve_source_commit",
    "sha256_json",
    "sha256_text",
]
