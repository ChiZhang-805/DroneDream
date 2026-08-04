"""Insert-once first-qualified candidate freeze and honest work accounting."""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Iterable, Sequence
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import models
from app.optimization.outcome_contract import selection_order_key
from app.orchestration.acceptance import AcceptanceResult
from app.orchestration.events import record_event
from app.orchestration.qualification import SEALED_QUALIFICATION_POLICY_VERSION
from app.orchestration.qualification_coordinator import (
    QualificationCoordinatorError,
    qualified_candidate_evidence_projection,
)
from app.simulator.base import (
    FAILURE_CANCELLED,
    FAILURE_EXECUTION_TIMEOUT,
    FAILURE_TIMEOUT,
)

FIRST_QUALIFIED_RECEIPT_SCHEMA_V1 = (
    "dronedream.first-qualified-freeze-receipt/v1"
)
FIRST_QUALIFIED_RECEIPT_SCHEMA = (
    "dronedream.first-qualified-freeze-receipt/v2"
)
FIRST_QUALIFIED_DEFINITION_VERSION_V1 = (
    "server-sequence-deterministic-tiebreak/v1"
)
FIRST_QUALIFIED_DEFINITION_VERSION = (
    "server-sequence-deterministic-tiebreak/v2"
)
_SUPPORTED_RECEIPT_VERSIONS = {
    FIRST_QUALIFIED_RECEIPT_SCHEMA_V1: FIRST_QUALIFIED_DEFINITION_VERSION_V1,
    FIRST_QUALIFIED_RECEIPT_SCHEMA: FIRST_QUALIFIED_DEFINITION_VERSION,
}
_TERMINAL_TRIAL_STATUSES = frozenset({"COMPLETED", "FAILED", "CANCELLED"})
_TIMEOUT_CODES = frozenset({FAILURE_TIMEOUT, FAILURE_EXECUTION_TIMEOUT})


class FirstQualifiedFreezeError(ValueError):
    """Raised when first-qualified ordering or evidence is not trustworthy."""


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def _sha256(value: object) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _iso(value: datetime) -> str:
    return _utc(value).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _holdout_contract_binding(job: models.Job) -> dict[str, object]:
    """Bind the receipt to the exact persisted holdout inputs.

    ``legacy-visible-v0`` is intentionally preserved when that is what the Job
    used.  A later sealed-holdout layer can change the version and contract,
    but this receipt never upgrades old evidence by assertion.
    """

    return {
        "holdout_policy_version": job.holdout_policy_version,
        "holdout_contract": job.holdout_contract_json,
        "scenario_suite": job.scenario_suite_json,
    }


def _candidate_order_key(candidate: models.CandidateParameterSet) -> tuple[float, ...]:
    """Deterministic same-window first-qualified tie-break.

    Earlier generation, then fewer dispatched trials within that generation,
    and the server dispatch ordinal define "first" before the preregistered
    objective order.  Candidate UUIDs are deliberately absent.
    """

    job = candidate.job
    if job.holdout_policy_version == SEALED_QUALIFICATION_POLICY_VERSION:
        try:
            projection = qualified_candidate_evidence_projection(candidate)
        except QualificationCoordinatorError as exc:
            raise FirstQualifiedFreezeError(
                "sealed first-qualified evidence failed revalidation"
            ) from exc
        if (
            projection is None
            or candidate.qualification_sequence is None
            or candidate.qualified_at is None
        ):
            raise FirstQualifiedFreezeError(
                "sealed first-qualified candidate lacks a frozen verdict"
            )
        return (
            _utc(candidate.qualified_at).timestamp(),
            float(candidate.qualification_sequence),
        )

    ordinal = candidate.dispatch_ordinal
    if ordinal is None or ordinal < 1:
        raise FirstQualifiedFreezeError(
            "first-qualified freeze requires a server dispatch ordinal"
        )
    if candidate.generation_index < 0 or candidate.trial_count < 0:
        raise FirstQualifiedFreezeError(
            "first-qualified freeze requires nonnegative generation/trial counts"
        )
    objective_order = selection_order_key(
        candidate.aggregated_metric_json,
        candidate.aggregated_score,
    )
    if not all(math.isfinite(float(value)) for value in objective_order):
        raise FirstQualifiedFreezeError(
            "first-qualified freeze requires a finite preregistered selection key"
        )
    return (
        float(candidate.generation_index),
        float(candidate.trial_count),
        float(ordinal),
        *(float(value) for value in objective_order),
    )


def _attempt_rows(trials: Iterable[models.Trial]) -> list[models.TrialExecutionAttempt]:
    return [attempt for trial in trials for attempt in trial.execution_attempts]


def _accounting(
    job: models.Job,
) -> dict[str, int]:
    trials = list(job.trials)
    attempts = _attempt_rows(trials)
    # Legacy rows may carry attempt_count without the immutable attempt ledger.
    # Preserve the larger observed value instead of beautifying old failures.
    simulation_attempts = max(
        len(attempts),
        sum(max(0, int(trial.attempt_count or 0)) for trial in trials),
    )
    trial_attempts = sum(
        1
        for trial in trials
        if trial.execution_attempts or int(trial.attempt_count or 0) > 0
    )
    return {
        "simulations_attempted": simulation_attempts,
        "trials_attempted": trial_attempts,
        "trials_completed": sum(trial.status == "COMPLETED" for trial in trials),
        "trials_passed": sum(
            trial.status == "COMPLETED"
            and trial.metric is not None
            and trial.metric.pass_flag is True
            for trial in trials
        ),
        "trials_failed": sum(trial.status == "FAILED" for trial in trials),
        "trials_cancelled": sum(trial.status == "CANCELLED" for trial in trials),
        "trials_timed_out": sum(
            trial.status == "FAILED" and trial.failure_code in _TIMEOUT_CODES
            for trial in trials
        ),
        "trials_indeterminate": sum(attempt.outcome is None for attempt in attempts),
        "generations": max(
            max(
                (candidate.generation_index for candidate in job.candidates),
                default=0,
            ),
            max(0, int(job.current_generation or 0)),
        ),
        "provider_turns_attempted": max(0, job.provider_turns_attempted),
        "provider_turns_succeeded": max(0, job.provider_turns_succeeded),
        "provider_requests_attempted": max(0, job.provider_requests_attempted),
        "provider_requests_succeeded": max(0, job.provider_requests_succeeded),
    }


def _receipt_evidence(
    *,
    job: models.Job,
    candidate: models.CandidateParameterSet,
    acceptance: AcceptanceResult,
    qualification_sequence: int,
    accounting: dict[str, int],
    frozen_at: datetime,
    holdout_contract_sha256: str,
) -> dict[str, object]:
    aggregate = candidate.aggregated_metric_json or {}
    candidate_outcome = aggregate.get("candidate_outcome_evidence")
    candidate_report = aggregate.get("candidate_report_evidence")
    start = job.started_at or job.queued_at or job.created_at
    elapsed_ms = max(0, int((_utc(frozen_at) - _utc(start)).total_seconds() * 1000))
    return {
        "receipt_schema": FIRST_QUALIFIED_RECEIPT_SCHEMA,
        "definition_version": FIRST_QUALIFIED_DEFINITION_VERSION,
        "job_id": job.id,
        "candidate_id": candidate.id,
        "completion_policy": job.completion_policy,
        "qualification_sequence": qualification_sequence,
        "generation_index": candidate.generation_index,
        "dispatch_ordinal": candidate.dispatch_ordinal,
        "qualified_at": _iso(frozen_at),
        "time_to_first_qualified_ms": elapsed_ms,
        "holdout_contract_sha256": holdout_contract_sha256,
        "candidate_parameter_sha256": _sha256(candidate.parameter_json),
        "candidate_aggregate_sha256": _sha256(aggregate),
        "candidate_outcome_evidence_id": (
            candidate_outcome.get("evidence_id")
            if isinstance(candidate_outcome, dict)
            else None
        ),
        "candidate_report_evidence_id": (
            candidate_report.get("evidence_id")
            if isinstance(candidate_report, dict)
            else None
        ),
        "acceptance": {
            "passed": acceptance.passed,
            "reason": acceptance.reason,
            "pass_rate": acceptance.pass_rate,
            "completion_rate": acceptance.completion_rate,
            "rmse": acceptance.rmse,
            "max_error": acceptance.max_error,
        },
        "accounting": accounting,
    }


def require_first_qualified_freeze_receipt(
    receipt: models.FirstQualifiedFreezeReceipt,
    *,
    job: models.Job | None = None,
) -> dict[str, object]:
    """Return evidence only when the immutable receipt is internally exact."""

    evidence = receipt.evidence_json
    if not isinstance(evidence, dict):
        raise FirstQualifiedFreezeError("first-qualified evidence is malformed")
    expected_id = "sha256:" + _sha256(evidence)
    accounting = evidence.get("accounting")
    expected_accounting = {
        "simulations_attempted": receipt.simulations_to_first_qualified,
        "trials_attempted": receipt.trials_to_first_qualified,
        "trials_completed": receipt.trials_completed_to_first_qualified,
        "trials_passed": receipt.trials_passed_to_first_qualified,
        "trials_failed": receipt.trials_failed_to_first_qualified,
        "trials_cancelled": receipt.trials_cancelled_to_first_qualified,
        "trials_timed_out": receipt.trials_timed_out_to_first_qualified,
        "trials_indeterminate": receipt.trials_indeterminate_to_first_qualified,
        "generations": receipt.generations_to_first_qualified,
        "provider_turns_attempted": (
            receipt.provider_turns_attempted_to_first_qualified
        ),
        "provider_turns_succeeded": (
            receipt.provider_turns_succeeded_to_first_qualified
        ),
    }
    if receipt.receipt_schema == FIRST_QUALIFIED_RECEIPT_SCHEMA:
        expected_accounting.update(
            {
                "provider_requests_attempted": (
                    receipt.provider_requests_attempted_to_first_qualified
                ),
                "provider_requests_succeeded": (
                    receipt.provider_requests_succeeded_to_first_qualified
                ),
            }
        )
    expected_definition = _SUPPORTED_RECEIPT_VERSIONS.get(receipt.receipt_schema)
    scalar_match = (
        expected_definition is not None
        and receipt.definition_version == expected_definition
        and receipt.evidence_id == expected_id
        and evidence.get("receipt_schema") == receipt.receipt_schema
        and evidence.get("definition_version") == receipt.definition_version
        and evidence.get("job_id") == receipt.job_id
        and evidence.get("candidate_id") == receipt.candidate_id
        and evidence.get("qualification_sequence") == receipt.qualification_sequence
        and evidence.get("generation_index") == receipt.generation_index
        and evidence.get("dispatch_ordinal") == receipt.dispatch_ordinal
        and evidence.get("time_to_first_qualified_ms")
        == receipt.time_to_first_qualified_ms
        and evidence.get("holdout_contract_sha256")
        == receipt.holdout_contract_sha256
        and evidence.get("qualified_at") == _iso(receipt.frozen_at)
        and accounting == expected_accounting
    )
    if not scalar_match:
        raise FirstQualifiedFreezeError(
            "first-qualified receipt is internally inconsistent"
        )
    if job is not None:
        candidate = next(
            (
                item
                for item in job.candidates
                if item.id == receipt.candidate_id
            ),
            None,
        )
        job_match = (
            receipt.job_id == job.id
            and receipt.candidate_id == job.first_qualified_candidate_id
            and job.first_qualified_at is not None
            and _utc(receipt.frozen_at) == _utc(job.first_qualified_at)
            and evidence.get("completion_policy") == job.completion_policy
            and receipt.holdout_contract_sha256
            == _sha256(_holdout_contract_binding(job))
            and candidate is not None
            and candidate.qualification_sequence == receipt.qualification_sequence
            and candidate.qualified_at is not None
            and _utc(candidate.qualified_at) == _utc(receipt.frozen_at)
            and candidate.generation_index == receipt.generation_index
            and candidate.dispatch_ordinal == receipt.dispatch_ordinal
            and evidence.get("candidate_parameter_sha256")
            == _sha256(candidate.parameter_json)
            and evidence.get("candidate_aggregate_sha256")
            == _sha256(candidate.aggregated_metric_json or {})
        )
        if not job_match:
            raise FirstQualifiedFreezeError(
                "first-qualified receipt does not match the current Job freeze"
            )
    return evidence


def freeze_first_qualified_candidate(
    db: Session,
    *,
    job: models.Job,
    qualified: Sequence[tuple[models.CandidateParameterSet, AcceptanceResult]],
    frozen_at: datetime | None = None,
) -> models.FirstQualifiedFreezeReceipt | None:
    """Freeze the deterministic first candidate from one aggregation window."""

    existing = db.scalars(
        select(models.FirstQualifiedFreezeReceipt).where(
            models.FirstQualifiedFreezeReceipt.job_id == job.id
        )
    ).first()
    if existing is not None:
        require_first_qualified_freeze_receipt(existing, job=job)
        return existing
    if job.first_qualified_candidate_id is not None:
        raise FirstQualifiedFreezeError(
            "Job points to a first-qualified candidate without a freeze receipt"
        )
    if job.status != "FINALIZING":
        raise FirstQualifiedFreezeError(
            "a first-qualified candidate may be frozen only during FINALIZING"
        )
    if not qualified:
        return None
    if any(not result.passed for _, result in qualified):
        raise FirstQualifiedFreezeError(
            "first-qualified input contains a candidate that failed acceptance"
        )

    ordered = sorted(qualified, key=lambda item: _candidate_order_key(item[0]))
    now = _utc(frozen_at or datetime.now(timezone.utc))
    sealed_job = job.holdout_policy_version == SEALED_QUALIFICATION_POLICY_VERSION
    if sealed_job:
        for candidate, _ in ordered:
            if (
                candidate.job_id != job.id
                or candidate.qualification_sequence is None
                or candidate.qualified_at is None
            ):
                raise FirstQualifiedFreezeError(
                    "sealed qualified candidate lacks server ordering state"
                )
        first_sequence = int(ordered[0][0].qualification_sequence or 0)
    else:
        next_sequence = job.next_qualification_sequence
        if next_sequence < 1:
            raise FirstQualifiedFreezeError("invalid next qualification sequence")
        for offset, (candidate, _) in enumerate(ordered):
            if candidate.job_id != job.id:
                raise FirstQualifiedFreezeError(
                    "qualified candidate belongs to a different Job"
                )
            if candidate.qualification_sequence is not None or candidate.qualified_at is not None:
                raise FirstQualifiedFreezeError(
                    "qualified candidate already carries partial ordering state"
                )
            candidate.qualification_sequence = next_sequence + offset
            candidate.qualified_at = now
        job.next_qualification_sequence = next_sequence + len(ordered)
        first_sequence = next_sequence

    first, acceptance = ordered[0]
    if sealed_job:
        qualified_at = first.qualified_at
        if qualified_at is None:  # pragma: no cover - guarded above
            raise FirstQualifiedFreezeError(
                "sealed first-qualified candidate has no decision time"
            )
        now = _utc(qualified_at)
        if frozen_at is not None and _utc(frozen_at) != now:
            raise FirstQualifiedFreezeError(
                "sealed first-qualified freeze cannot rewrite its decision time"
            )
    job.first_qualified_candidate_id = first.id
    job.first_qualified_at = now
    holdout_contract_sha256 = _sha256(_holdout_contract_binding(job))
    accounting = _accounting(job)
    evidence = _receipt_evidence(
        job=job,
        candidate=first,
        acceptance=acceptance,
        qualification_sequence=first_sequence,
        accounting=accounting,
        frozen_at=now,
        holdout_contract_sha256=holdout_contract_sha256,
    )
    elapsed_ms = evidence.get("time_to_first_qualified_ms")
    if isinstance(elapsed_ms, bool) or not isinstance(elapsed_ms, int):
        raise FirstQualifiedFreezeError(
            "first-qualified elapsed time must be an integer millisecond count"
        )
    evidence_id = "sha256:" + _sha256(evidence)
    receipt = models.FirstQualifiedFreezeReceipt(
        id=f"fqf_{uuid4().hex[:12]}",
        job_id=job.id,
        candidate_id=first.id,
        receipt_schema=FIRST_QUALIFIED_RECEIPT_SCHEMA,
        definition_version=FIRST_QUALIFIED_DEFINITION_VERSION,
        evidence_id=evidence_id,
        holdout_contract_sha256=holdout_contract_sha256,
        qualification_sequence=first_sequence,
        generation_index=first.generation_index,
        dispatch_ordinal=int(first.dispatch_ordinal or 0),
        time_to_first_qualified_ms=elapsed_ms,
        simulations_to_first_qualified=accounting["simulations_attempted"],
        trials_to_first_qualified=accounting["trials_attempted"],
        trials_completed_to_first_qualified=accounting["trials_completed"],
        trials_passed_to_first_qualified=accounting["trials_passed"],
        trials_failed_to_first_qualified=accounting["trials_failed"],
        trials_cancelled_to_first_qualified=accounting["trials_cancelled"],
        trials_timed_out_to_first_qualified=accounting["trials_timed_out"],
        trials_indeterminate_to_first_qualified=accounting["trials_indeterminate"],
        generations_to_first_qualified=accounting["generations"],
        provider_turns_attempted_to_first_qualified=accounting[
            "provider_turns_attempted"
        ],
        provider_turns_succeeded_to_first_qualified=accounting[
            "provider_turns_succeeded"
        ],
        provider_requests_attempted_to_first_qualified=accounting[
            "provider_requests_attempted"
        ],
        provider_requests_succeeded_to_first_qualified=accounting[
            "provider_requests_succeeded"
        ],
        evidence_json=evidence,
        frozen_at=now,
    )
    receipt.job = job
    db.add(receipt)
    record_event(
        db,
        job.id,
        "first_qualified_candidate_frozen",
        {
            "candidate_id": first.id,
            "qualification_sequence": first_sequence,
            "generation_index": first.generation_index,
            "dispatch_ordinal": first.dispatch_ordinal,
            "definition_version": FIRST_QUALIFIED_DEFINITION_VERSION,
            "evidence_id": evidence_id,
            "time_to_first_qualified_ms": evidence[
                "time_to_first_qualified_ms"
            ],
            "accounting": accounting,
        },
    )
    return receipt


def stage_first_qualified_dispatch_stop(
    db: Session,
    *,
    job: models.Job,
    stopped_at: datetime | None = None,
) -> dict[str, int]:
    """Cancel unclaimed work while leaving running physical Trials untouched."""

    if job.first_qualified_candidate_id is None:
        raise FirstQualifiedFreezeError(
            "cannot stop dispatch before first-qualified freeze"
        )
    now = _utc(stopped_at or datetime.now(timezone.utc))
    queued_cancelled = 0
    running_preserved = 0
    for trial in job.trials:
        if trial.status == "PENDING":
            trial.status = "CANCELLED"
            trial.finished_at = now
            trial.failure_code = FAILURE_CANCELLED
            trial.failure_reason = (
                "Cancelled before claim because the Job froze its first "
                "fully-qualified candidate."
            )
            trial.lease_owner = None
            trial.lease_expires_at = None
            queued_cancelled += 1
        elif trial.status == "RUNNING":
            # The adapter retains responsibility for safe landing/cleanup and
            # terminal evidence.  Never rewrite an in-flight Trial here.
            running_preserved += 1
    job.progress_completed_trials = sum(
        trial.status in _TERMINAL_TRIAL_STATUSES for trial in job.trials
    )
    if queued_cancelled or running_preserved:
        record_event(
            db,
            job.id,
            "first_qualified_dispatch_stopped",
            {
                "queued_trials_cancelled": queued_cancelled,
                "running_trials_preserved_for_safe_finalization": running_preserved,
            },
        )
    return {
        "queued_trials_cancelled": queued_cancelled,
        "running_trials_preserved": running_preserved,
    }


__all__ = [
    "FIRST_QUALIFIED_DEFINITION_VERSION",
    "FIRST_QUALIFIED_DEFINITION_VERSION_V1",
    "FIRST_QUALIFIED_RECEIPT_SCHEMA",
    "FIRST_QUALIFIED_RECEIPT_SCHEMA_V1",
    "FirstQualifiedFreezeError",
    "freeze_first_qualified_candidate",
    "require_first_qualified_freeze_receipt",
    "stage_first_qualified_dispatch_stop",
]
