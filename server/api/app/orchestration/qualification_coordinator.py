"""Fenced progression for the two-stage sealed qualification protocol."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from app import models
from app.optimization.scenarios import ScenarioRun, scenario_execution_payload
from app.orchestration.events import record_event
from app.orchestration.qualification import (
    QUALIFICATION_CONTRACT_SCHEMA,
    QUALIFICATION_RULE_SHA256,
    QUALIFICATION_RULE_VERSION,
    SEALED_QUALIFICATION_POLICY_VERSION,
    QualificationContractError,
    QualificationProgress,
    QualificationTrialObservation,
    evaluate_qualification_progress,
    sealed_qualification_contract_sha256,
)
from app.orchestration.qualification_dispatch import (
    QualificationDispatchError,
    qualification_runs,
    qualification_trial_binding,
    sealed_contract_for_job,
)
from app.orchestration.qualification_receipts import (
    QualificationReceiptError,
    require_qualification_trial_receipt,
)

_TERMINAL_STATES = frozenset(
    {
        "screening_failed",
        "qualification_failed",
        "indeterminate",
        "cancelled",
        "qualified",
    }
)
_TERMINAL_TRIAL_STATUSES = frozenset({"COMPLETED", "FAILED", "CANCELLED"})


class QualificationCoordinatorError(QualificationDispatchError):
    """Raised when persisted qualification state cannot advance exactly."""


@dataclass(frozen=True)
class QualificationAdvanceResult:
    dispatched_trials: int
    state_changes: int
    qualified_candidates: tuple[str, ...]


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _iso_utc(value: datetime) -> str:
    return _utc(value).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def _candidate_order_key(
    qualification: models.CandidateQualification,
) -> tuple[int, int]:
    candidate = qualification.candidate
    ordinal = candidate.dispatch_ordinal
    generation = candidate.generation_index
    if (
        isinstance(generation, bool)
        or not isinstance(generation, int)
        or generation < 0
        or isinstance(ordinal, bool)
        or not isinstance(ordinal, int)
        or ordinal < 1
    ):
        raise QualificationCoordinatorError(
            "qualification ordering requires server generation and dispatch ordinals"
        )
    return generation, ordinal


def _observations(
    qualification: models.CandidateQualification,
) -> tuple[QualificationTrialObservation, ...]:
    trials = list(qualification.trials)
    receipts = list(qualification.trial_receipts)
    if len(trials) != len(receipts):
        raise QualificationCoordinatorError(
            "terminal qualification Trial set is missing an immutable receipt"
        )
    trial_by_id = {trial.id: trial for trial in trials}
    if len(trial_by_id) != len(trials):
        raise QualificationCoordinatorError("qualification Trial identity is duplicated")
    observations: list[QualificationTrialObservation] = []
    for receipt in receipts:
        trial = trial_by_id.get(receipt.trial_id)
        if trial is None:
            raise QualificationCoordinatorError(
                "qualification receipt belongs to an unknown Trial"
            )
        try:
            evidence = require_qualification_trial_receipt(receipt, trial=trial)
        except QualificationReceiptError as exc:
            raise QualificationCoordinatorError(
                "qualification Trial receipt failed revalidation"
            ) from exc
        observations.append(
            QualificationTrialObservation(
                phase=evidence.phase,
                ordinal=evidence.ordinal,
                terminal_status=evidence.terminal_status,
                passed=evidence.passed,
                safety_critical_failure=evidence.safety_critical_failure,
                effect_readback_complete=evidence.effect_readback_complete,
                evidence_complete=evidence.evidence_complete,
                evidence_id=evidence.evidence_id,
            )
        )
    return tuple(observations)


def _source_for_candidate(candidate: models.CandidateParameterSet) -> str:
    if candidate.is_baseline:
        return "baseline"
    if candidate.source_type == "optimizer":
        return "optimizer"
    return "llm"


def _scenario_payload(
    job: models.Job,
    candidate: models.CandidateParameterSet,
    run: ScenarioRun,
) -> dict[str, Any]:
    source = _source_for_candidate(candidate)
    return scenario_execution_payload(
        run,
        source=source,
        generation_index=candidate.generation_index,
        advanced_scenario_config=job.advanced_scenario_config_json,
        optimizer_fidelity_value=(1.0 if source == "optimizer" else None),
        optimizer_requested_fidelity_value=(1.0 if source == "optimizer" else None),
    )


def _dispatch_qualification_trials(
    db: Session,
    *,
    job: models.Job,
    qualification: models.CandidateQualification,
    runs: tuple[ScenarioRun, ...],
    start_ordinal: int,
    now: datetime,
) -> int:
    candidate = qualification.candidate
    existing = {
        trial.qualification_ordinal: trial
        for trial in qualification.trials
        if trial.evaluation_phase == "qualification"
    }
    if len(existing) != sum(
        trial.evaluation_phase == "qualification" for trial in qualification.trials
    ):
        raise QualificationCoordinatorError("qualification Trial ordinals are duplicated")
    planned: list[tuple[int, ScenarioRun, dict[str, Any]]] = []
    for offset, run in enumerate(runs):
        ordinal = start_ordinal + offset
        payload = _scenario_payload(job, candidate, run)
        current = existing.get(ordinal)
        if current is not None:
            if (
                current.seed != run.seed
                or current.scenario_type != run.scenario_type
                or current.scenario_config_json != payload
            ):
                raise QualificationCoordinatorError(
                    "existing qualification Trial diverges from sealed holdout"
                )
            continue
        planned.append((ordinal, run, payload))
    if job.progress_total_trials + len(planned) > job.max_total_trials:
        raise QualificationCoordinatorError(
            "sealed qualification would exceed the Job Trial cap"
        )
    for ordinal, run, payload in planned:
        trial = models.Trial(
            job_id=job.id,
            candidate_id=candidate.id,
            worker_id=None,
            seed=run.seed,
            scenario_type=run.scenario_type,
            scenario_config_json=payload,
            status="PENDING",
            queued_at=now,
            **qualification_trial_binding(
                qualification=qualification,
                phase="qualification",
                ordinal=ordinal,
            ),
        )
        trial.qualification = qualification
        trial.candidate = candidate
        trial.job = job
        db.add(trial)
    new_trials = len(planned)
    if new_trials:
        candidate.trial_count += new_trials
        job.progress_total_trials += new_trials
    return new_trials


def _apply_terminal_progress(
    qualification: models.CandidateQualification,
    progress: QualificationProgress,
    *,
    now: datetime,
) -> bool:
    changed = qualification.state != progress.state
    qualification.state = progress.state
    if progress.sealed and qualification.sealed_at is None:
        qualification.sealed_at = now
        changed = True
    if progress.terminal and qualification.decided_at is None:
        qualification.decided_at = now
        changed = True
    if changed:
        qualification.state_revision += 1
    return changed


def _bind_qualified_candidate(
    qualification: models.CandidateQualification,
) -> None:
    sequence = qualification.qualification_sequence
    decided_at = qualification.decided_at
    candidate = qualification.candidate
    if sequence is None or sequence < 1 or decided_at is None:
        raise QualificationCoordinatorError(
            "qualified candidate is missing its server sequence or decision time"
        )
    if candidate.qualification_sequence not in {None, sequence}:
        raise QualificationCoordinatorError(
            "candidate qualification sequence diverges from sealed state"
        )
    if (
        candidate.qualified_at is not None
        and _utc(candidate.qualified_at) != _utc(decided_at)
    ):
        raise QualificationCoordinatorError(
            "candidate qualification time diverges from sealed state"
        )
    candidate.qualification_sequence = sequence
    candidate.qualified_at = decided_at


def qualified_candidate_evidence_projection(
    candidate: models.CandidateParameterSet,
) -> dict[str, Any] | None:
    """Return a revalidated, content-addressed sealed qualification verdict."""

    try:
        job = getattr(candidate, "job", None)
    except Exception as exc:  # pragma: no cover - detached sealed rows fail closed
        raise QualificationCoordinatorError(
            "candidate Job binding is unavailable for qualification revalidation"
        ) from exc
    try:
        qualification = getattr(candidate, "qualification", None)
    except Exception as exc:  # pragma: no cover - detached sealed rows fail closed
        raise QualificationCoordinatorError(
            "candidate qualification binding is unavailable for revalidation"
        ) from exc
    if job is None:
        if qualification is not None:
            raise QualificationCoordinatorError(
                "qualification row is orphaned from its Job binding"
            )
        return None
    if (
        getattr(job, "holdout_policy_version", None)
        != SEALED_QUALIFICATION_POLICY_VERSION
    ):
        if qualification is not None:
            raise QualificationCoordinatorError(
                "qualification row is bound to an incompatible Job policy"
            )
        return None
    if qualification is None or qualification.state != "qualified":
        return None
    contract = sealed_contract_for_job(job)
    if contract is None:
        raise QualificationCoordinatorError(
            "sealed qualification Job has no revalidatable holdout contract"
        )
    expected_contract_sha256 = sealed_qualification_contract_sha256(contract)
    if (
        qualification.job_id != job.id
        or qualification.candidate_id != candidate.id
        or qualification.contract_schema != QUALIFICATION_CONTRACT_SCHEMA
        or qualification.rule_version != QUALIFICATION_RULE_VERSION
        or qualification.rule_sha256 != QUALIFICATION_RULE_SHA256
        or qualification.holdout_contract_sha256 != expected_contract_sha256
    ):
        raise QualificationCoordinatorError(
            "qualified state diverges from the frozen rule or holdout contract"
        )
    progress = evaluate_qualification_progress(_observations(qualification))
    if not progress.qualified or not progress.terminal or not progress.sealed:
        raise QualificationCoordinatorError(
            "persisted qualified state diverges from immutable Trial receipts"
        )
    if (
        qualification.qualification_sequence is None
        or qualification.qualification_sequence < 1
        or qualification.decided_at is None
    ):
        raise QualificationCoordinatorError(
            "qualified state is missing its deterministic sequence or timestamp"
        )
    payload: dict[str, Any] = {
        "schema_id": "dronedream.sealed-candidate-qualification/v1",
        "job_id": job.id,
        "candidate_id": candidate.id,
        "qualification_id": qualification.id,
        "qualification_sequence": qualification.qualification_sequence,
        "rule_version": qualification.rule_version,
        "rule_sha256": qualification.rule_sha256,
        "holdout_contract_sha256": qualification.holdout_contract_sha256,
        "state_revision": qualification.state_revision,
        "screening_attempted": progress.screening_attempted,
        "screening_passed": progress.screening_passed,
        "qualification_attempted": progress.qualification_attempted,
        "qualification_passed": progress.qualification_passed,
        "qualification_target": progress.qualification_target,
        "decision_reason": progress.reason,
        "decided_at": _iso_utc(qualification.decided_at),
        "receipt_evidence_ids": sorted(
            receipt.evidence_id for receipt in qualification.trial_receipts
        ),
    }
    return {
        "evidence_id": "sha256:"
        + hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest(),
        **payload,
    }


def advance_sealed_qualifications(
    db: Session,
    *,
    job: models.Job,
) -> QualificationAdvanceResult:
    """Advance all sealed candidates under the caller's Job finalization fence."""

    contract = sealed_contract_for_job(job)
    if contract is None:
        return QualificationAdvanceResult(0, 0, ())
    if job.first_qualified_candidate_id is not None:
        return QualificationAdvanceResult(0, 0, (job.first_qualified_candidate_id,))

    now = _now()
    qualifications = list(job.candidate_qualifications)
    if len(qualifications) != len(job.candidates):
        raise QualificationCoordinatorError(
            "sealed Job candidates are missing qualification bindings"
        )
    selected = [item for item in qualifications if item.qualification_sequence is not None]
    if len(selected) > 2:
        raise QualificationCoordinatorError("sealed Job exceeds its qualification candidate cap")

    progress_by_id: dict[str, QualificationProgress] = {}
    qualified_ids = [
        item.candidate_id for item in qualifications if item.state == "qualified"
    ]
    for qualification in qualifications:
        if qualification.state in _TERMINAL_STATES:
            continue
        # Trial execution is parallel and receipts may arrive out of ordinal
        # order. Evaluate one Candidate only after its complete currently
        # dispatched matrix is terminal; this still allows candidate A to stop
        # the Job while candidate B remains in flight.
        if not qualification.trials or any(
            trial.status not in _TERMINAL_TRIAL_STATUSES
            for trial in qualification.trials
        ):
            continue
        try:
            progress_by_id[qualification.id] = evaluate_qualification_progress(
                _observations(qualification)
            )
        except QualificationContractError as exc:
            raise QualificationCoordinatorError(
                "qualification Trial sequence violates the frozen rule"
            ) from exc
        if progress_by_id[qualification.id].qualified:
            qualified_ids.append(qualification.candidate_id)

    dispatched = 0
    state_changes = 0
    if qualified_ids:
        for qualification in qualifications:
            progress = progress_by_id.get(qualification.id)
            if qualification.state == "qualified":
                if qualified_candidate_evidence_projection(qualification.candidate) is None:
                    raise QualificationCoordinatorError(
                        "persisted qualified state has no sealed evidence projection"
                    )
                _bind_qualified_candidate(qualification)
                continue
            if progress is not None and progress.qualified:
                if _apply_terminal_progress(qualification, progress, now=now):
                    state_changes += 1
                _bind_qualified_candidate(qualification)
                continue
            if progress is not None and progress.terminal:
                if _apply_terminal_progress(qualification, progress, now=now):
                    state_changes += 1
                continue
            if qualification.state not in _TERMINAL_STATES:
                qualification.state = "cancelled"
                qualification.decided_at = now
                qualification.state_revision += 1
                state_changes += 1
        return QualificationAdvanceResult(
            dispatched_trials=0,
            state_changes=state_changes,
            qualified_candidates=tuple(qualified_ids),
        )

    eligible: list[models.CandidateQualification] = []
    for qualification in qualifications:
        if qualification.state in _TERMINAL_STATES:
            continue
        progress = progress_by_id.get(qualification.id)
        if progress is None:
            continue
        if progress.action == "seal_and_dispatch_qualification":
            if qualification.qualification_sequence is None:
                eligible.append(qualification)
                continue
            runs = qualification_runs(contract, start_ordinal=1, end_ordinal=10)
            dispatched += _dispatch_qualification_trials(
                db,
                job=job,
                qualification=qualification,
                runs=runs,
                start_ordinal=1,
                now=now,
            )
            if qualification.state != "qualification_10":
                qualification.state = "qualification_10"
                qualification.state_revision += 1
                state_changes += 1
            continue
        if progress.action == "dispatch_qualification_extension":
            runs = qualification_runs(contract, start_ordinal=11, end_ordinal=20)
            dispatched += _dispatch_qualification_trials(
                db,
                job=job,
                qualification=qualification,
                runs=runs,
                start_ordinal=11,
                now=now,
            )
        if _apply_terminal_progress(qualification, progress, now=now):
            state_changes += 1
        if progress.qualified:
            _bind_qualified_candidate(qualification)
            qualified_ids.append(qualification.candidate_id)

    unselected_nonterminal = [
        qualification
        for qualification in qualifications
        if qualification.state not in _TERMINAL_STATES
        and qualification.qualification_sequence is None
    ]
    selection_window_closed = all(
        qualification.id in progress_by_id
        for qualification in unselected_nonterminal
    )
    if not selection_window_closed:
        return QualificationAdvanceResult(
            dispatched_trials=dispatched,
            state_changes=state_changes,
            qualified_candidates=tuple(qualified_ids),
        )

    available = 2 - len(selected)
    ordered_eligible = sorted(eligible, key=_candidate_order_key)
    entrants = ordered_eligible[:available]
    rejected = ordered_eligible[available:]
    for qualification in entrants:
        sequence = job.next_qualification_sequence
        if sequence < 1:
            raise QualificationCoordinatorError("invalid next qualification sequence")
        qualification.qualification_sequence = sequence
        qualification.state = "qualification_10"
        qualification.sealed_at = qualification.sealed_at or now
        qualification.state_revision += 1
        job.next_qualification_sequence = sequence + 1
        runs = qualification_runs(contract, start_ordinal=1, end_ordinal=10)
        dispatched += _dispatch_qualification_trials(
            db,
            job=job,
            qualification=qualification,
            runs=runs,
            start_ordinal=1,
            now=now,
        )
        state_changes += 1
        record_event(
            db,
            job.id,
            "candidate_sealed_qualification_started",
            {
                "candidate_id": qualification.candidate_id,
                "qualification_sequence": sequence,
                "rule_version": qualification.rule_version,
                "holdout_contract_sha256": qualification.holdout_contract_sha256,
                "trial_count": 10,
            },
        )
    for qualification in rejected:
        qualification.state = "cancelled"
        qualification.decided_at = now
        qualification.state_revision += 1
        state_changes += 1
        record_event(
            db,
            job.id,
            "candidate_qualification_cap_reached",
            {
                "candidate_id": qualification.candidate_id,
                "max_candidates_per_run": 2,
            },
        )
    return QualificationAdvanceResult(
        dispatched_trials=dispatched,
        state_changes=state_changes,
        qualified_candidates=tuple(qualified_ids),
    )


__all__ = [
    "QualificationAdvanceResult",
    "QualificationCoordinatorError",
    "advance_sealed_qualifications",
    "qualified_candidate_evidence_projection",
]
