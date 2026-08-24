"""Structured, revocable, user-isolated cross-Job Harness experience memory.

Only verified terminal-Job cohort observations may be materialized. Retrieval
requires exact ownership, task-family, and contract-version matches; expired,
revoked, malformed, drifted, or cross-user rows fail closed. The provider
projection contains no database identifiers, timestamps, seeds, raw text,
parameter values, holdout details, credentials, or simulator output.
"""

from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from app import models
from app.model_harness.domains import (
    MODEL_HARNESS_DOMAIN_VALUES,
    OPTIMIZATION_CONTROL_TUNING_DOMAIN,
    consolidated_verified_outcome_lifecycle,
    validate_long_term_memory_payload,
)
from app.orchestration.harness_context import (
    HARNESS_EVIDENCE_SCHEMA_VERSION,
    HARNESS_PROMPT_TEMPLATE_VERSION,
    HARNESS_TOOL_ELIGIBILITY_POLICY_VERSION,
    HARNESS_TOOL_REGISTRY_VERSION,
    MAX_CROSS_JOB_EXPERIENCE_ITEMS,
    HarnessCrossJobExperience,
    HarnessCrossJobMemory,
    HarnessEvidenceSnapshot,
    HarnessExecutionMemory,
    HarnessObservedDecisionOutcome,
)

HARNESS_EXPERIENCE_MEMORY_SCHEMA_VERSION = "1.0"
HARNESS_EXPERIENCE_RETRIEVAL_POLICY_VERSION = "1.0"
HARNESS_EXPERIENCE_RETENTION_DAYS = 90
HARNESS_EXPERIENCE_RETRIEVAL_SCAN_LIMIT = 64

_TERMINAL_JOB_STATUSES = frozenset({"COMPLETED", "FAILED", "CANCELLED"})
_REVOCATION_REASONS = frozenset(
    {
        "user_requested",
        "source_receipt_drift",
        "contract_retired",
    }
)


def _memory_is_enabled(db: Session, *, user_id: str) -> bool:
    preferences = db.get(models.UserExperiencePreferences, user_id)
    return bool(preferences is not None and preferences.memory_enabled)


def _utc(value: datetime | None = None) -> datetime:
    resolved = value or datetime.now(timezone.utc)
    return resolved if resolved.tzinfo is not None else resolved.replace(tzinfo=timezone.utc)


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    )


def _sha256_json(value: object) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _task_family_payload(
    snapshot: HarnessEvidenceSnapshot,
    *,
    job: models.Job | None = None,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "objective_profile": snapshot.job.objective_profile,
        "track_type": snapshot.job.track_type,
        "parameter_count": snapshot.job.parameter_count,
        "parameter_names": list(snapshot.job.parameter_names),
        "objective_count": snapshot.job.objective_count,
        "constraint_count": snapshot.job.constraint_count,
        "robust_aggregation": snapshot.job.robust_aggregation,
    }
    if job is not None:
        # This binding stays internal. It makes catalog/parameter/objective/
        # vehicle/backend drift a task-family mismatch without exposing raw JSON
        # or user-authored labels to the provider. Scenario/holdout configuration
        # is deliberately excluded and handled only by the safe training profile.
        payload["task_contract_sha256"] = _sha256_json(
            {
                "parameter_catalog_version": job.parameter_catalog_version,
                "parameter_space": job.parameter_space_json,
                "objective_config": job.objective_config_json,
                "vehicle_profile": job.vehicle_profile_json,
                "simulator_backend": job.simulator_backend_requested,
            }
        )
    return payload


def task_family_sha256(
    snapshot: HarnessEvidenceSnapshot,
    *,
    job: models.Job | None = None,
) -> str:
    """Return the exact structural task-family key used by retrieval."""

    return _sha256_json(_task_family_payload(snapshot, job=job))


def _scenario_profile(snapshot: HarnessEvidenceSnapshot) -> dict[str, object]:
    """Project only provider-safe training/environment structure.

    Validation/holdout counts and profiles are intentionally omitted even
    though the current same-Job snapshot includes aggregate cost counts.
    """

    scenarios = snapshot.scenarios
    return {
        "training_case_count": scenarios.training_case_count,
        "training_replicate_count": scenarios.training_replicate_count,
        "training_type_counts": dict(sorted(scenarios.training_type_counts.items())),
        "training_replicate_min": scenarios.training_replicate_min,
        "training_replicate_max": scenarios.training_replicate_max,
        "training_weight_concentration": scenarios.training_weight_concentration,
        "effective_training_case_count": scenarios.effective_training_case_count,
        "environment": scenarios.environment.model_dump(mode="json", exclude_none=True),
        "common_random_numbers": scenarios.common_random_numbers,
    }


def _receipt_payload(
    *,
    source_job_id: str,
    task_family_hash: str,
    scenario_profile: dict[str, object],
    memory: HarnessExecutionMemory,
) -> dict[str, object]:
    return {
        "schema_id": "dronedream.harness-cross-job-source-receipt/v1",
        "source_job_id": source_job_id,
        "source_generation": memory.generation,
        "memory_schema_version": HARNESS_EXPERIENCE_MEMORY_SCHEMA_VERSION,
        "source_evidence_schema_version": HARNESS_EVIDENCE_SCHEMA_VERSION,
        "source_prompt_template_version": HARNESS_PROMPT_TEMPLATE_VERSION,
        "source_tool_registry_version": HARNESS_TOOL_REGISTRY_VERSION,
        "source_eligibility_policy_version": HARNESS_TOOL_ELIGIBILITY_POLICY_VERSION,
        "task_family_sha256": task_family_hash,
        "scenario_profile": scenario_profile,
        "execution": memory.model_dump(mode="json", exclude_none=True),
    }


def _row_memory(row: models.HarnessExperienceMemory) -> HarnessExecutionMemory | None:
    try:
        outcome = HarnessObservedDecisionOutcome.model_validate(row.observed_outcome_json)
        return HarnessExecutionMemory.model_validate(
            {
                "generation": row.source_generation,
                "tool_id": row.tool_id,
                "decision_source": row.decision_source,
                "plan_phase": row.plan_phase,
                "batch_policy": row.batch_policy,
                "status": "dispatched",
                "dispatched_candidates": row.dispatched_candidates,
                "planned_candidates": row.planned_candidates,
                "reflection_status": "verified_complete",
                "observed_outcome": outcome.model_dump(mode="json", exclude_none=True),
            }
        )
    except ValueError:
        return None


def _row_contract_is_current(row: models.HarnessExperienceMemory) -> bool:
    return (
        row.memory_domain in MODEL_HARNESS_DOMAIN_VALUES
        and row.source_kind == "verified_job_outcome"
        and row.evidence_count >= 1
        and row.confidence == 1.0
        and row.lifecycle_status == "consolidated"
        and row.memory_schema_version == HARNESS_EXPERIENCE_MEMORY_SCHEMA_VERSION
        and row.source_evidence_schema_version == HARNESS_EVIDENCE_SCHEMA_VERSION
        and row.source_prompt_template_version == HARNESS_PROMPT_TEMPLATE_VERSION
        and row.source_tool_registry_version == HARNESS_TOOL_REGISTRY_VERSION
        and row.source_eligibility_policy_version == HARNESS_TOOL_ELIGIBILITY_POLICY_VERSION
    )


def _row_receipt_is_valid(row: models.HarnessExperienceMemory) -> bool:
    if not isinstance(row.scenario_profile_json, dict):
        return False
    memory = _row_memory(row)
    if memory is None:
        return False
    expected = _sha256_json(
        _receipt_payload(
            source_job_id=row.source_job_id,
            task_family_hash=row.task_family_sha256,
            scenario_profile=row.scenario_profile_json,
            memory=memory,
        )
    )
    return expected == row.source_receipt_sha256


def materialize_verified_terminal_job_experiences(
    db: Session,
    *,
    source_job: models.Job,
    snapshot: HarnessEvidenceSnapshot,
    now: datetime | None = None,
) -> int:
    """Persist new verified cohort observations from one owned terminal Job.

    Existing rows are never rewritten. If the same source generation compiles
    to different bytes later, the old row is revoked as drift and no replacement
    is silently trusted.
    """

    if (
        not isinstance(source_job.user_id, str)
        or not source_job.user_id
        or not _memory_is_enabled(db, user_id=source_job.user_id)
        or source_job.status not in _TERMINAL_JOB_STATUSES
        or snapshot.schema_version != HARNESS_EVIDENCE_SCHEMA_VERSION
        or source_job.model_harness_domain != OPTIMIZATION_CONTROL_TUNING_DOMAIN
    ):
        return 0

    current_time = _utc(now)
    family_hash = task_family_sha256(snapshot, job=source_job)
    scenario_profile = _scenario_profile(snapshot)
    existing_rows = list(
        db.scalars(
            select(models.HarnessExperienceMemory).where(
                models.HarnessExperienceMemory.source_job_id == source_job.id
            )
        )
    )
    existing_by_generation = {row.source_generation: row for row in existing_rows}
    verified_generations: set[int] = set()
    inserted = 0
    for memory in snapshot.decision_memory:
        if (
            memory.status != "dispatched"
            or memory.reflection_status != "verified_complete"
            or memory.observed_outcome is None
            or memory.decision_source not in {"model", "deterministic_fallback"}
        ):
            continue
        lifecycle = consolidated_verified_outcome_lifecycle(
            evidence_count=memory.observed_outcome.cohort_candidate_count,
            recency_at=current_time,
            ttl_days=HARNESS_EXPERIENCE_RETENTION_DAYS,
        )
        validate_long_term_memory_payload(
            {
                "memory_domain": source_job.model_harness_domain,
                "source_kind": lifecycle.source,
                "evidence_count": lifecycle.evidence_count,
                "confidence": lifecycle.confidence,
                "recency_at": lifecycle.recency_at,
                "ttl_days": lifecycle.ttl_days,
                "lifecycle_status": lifecycle.status,
                "scenario_profile": scenario_profile,
                "execution": memory.model_dump(mode="json", exclude_none=True),
            }
        )
        verified_generations.add(memory.generation)
        receipt_hash = _sha256_json(
            _receipt_payload(
                source_job_id=source_job.id,
                task_family_hash=family_hash,
                scenario_profile=scenario_profile,
                memory=memory,
            )
        )
        existing = existing_by_generation.get(memory.generation)
        if existing is not None:
            if existing.source_receipt_sha256 != receipt_hash and existing.revoked_at is None:
                existing.revoked_at = current_time
                existing.revocation_reason = "source_receipt_drift"
            continue
        db.add(
            models.HarnessExperienceMemory(
                user_id=source_job.user_id,
                source_job_id=source_job.id,
                source_generation=memory.generation,
                memory_domain=source_job.model_harness_domain,
                source_kind=lifecycle.source,
                evidence_count=lifecycle.evidence_count,
                confidence=lifecycle.confidence,
                lifecycle_status=lifecycle.status,
                memory_schema_version=HARNESS_EXPERIENCE_MEMORY_SCHEMA_VERSION,
                source_evidence_schema_version=HARNESS_EVIDENCE_SCHEMA_VERSION,
                source_prompt_template_version=HARNESS_PROMPT_TEMPLATE_VERSION,
                source_tool_registry_version=HARNESS_TOOL_REGISTRY_VERSION,
                source_eligibility_policy_version=(HARNESS_TOOL_ELIGIBILITY_POLICY_VERSION),
                task_family_sha256=family_hash,
                scenario_profile_json=scenario_profile,
                tool_id=memory.tool_id,
                decision_source=memory.decision_source,
                plan_phase=memory.plan_phase,
                batch_policy=memory.batch_policy,
                dispatched_candidates=memory.dispatched_candidates,
                planned_candidates=memory.planned_candidates,
                observed_outcome_json=memory.observed_outcome.model_dump(
                    mode="json",
                    exclude_none=True,
                ),
                source_receipt_sha256=receipt_hash,
                created_at=current_time,
                expires_at=current_time + timedelta(days=HARNESS_EXPERIENCE_RETENTION_DAYS),
            )
        )
        inserted += 1
    for existing in existing_rows:
        if existing.source_generation not in verified_generations and existing.revoked_at is None:
            existing.revoked_at = current_time
            existing.revocation_reason = "source_receipt_drift"
    return inserted


def _bounded_ratio(left: object, right: object) -> float:
    if isinstance(left, bool) or isinstance(right, bool):
        return 0.0
    if not isinstance(left, int | float) or not isinstance(right, int | float):
        return 0.0
    if not math.isfinite(float(left)) or not math.isfinite(float(right)):
        return 0.0
    high = max(abs(float(left)), abs(float(right)))
    if high <= 1e-12:
        return 1.0
    return min(abs(float(left)), abs(float(right))) / high


def _type_count_similarity(
    left: dict[str, object],
    right: dict[str, object],
) -> float:
    left_counts = left.get("training_type_counts")
    right_counts = right.get("training_type_counts")
    if not isinstance(left_counts, dict) or not isinstance(right_counts, dict):
        return 0.0
    keys = set(left_counts) | set(right_counts)
    if not keys:
        return 1.0
    numerator = 0.0
    denominator = 0.0
    for key in keys:
        left_value = left_counts.get(key, 0)
        right_value = right_counts.get(key, 0)
        if (
            isinstance(left_value, bool)
            or isinstance(right_value, bool)
            or not isinstance(left_value, int)
            or not isinstance(right_value, int)
            or left_value < 0
            or right_value < 0
        ):
            return 0.0
        numerator += min(left_value, right_value)
        denominator += max(left_value, right_value)
    return 1.0 if denominator == 0.0 else numerator / denominator


def scenario_profile_similarity(
    left: dict[str, object],
    right: dict[str, object],
) -> float:
    """Return a deterministic retrieval rank, not a physical similarity claim."""

    type_similarity = _type_count_similarity(left, right)
    replicate_similarity = _bounded_ratio(
        left.get("training_replicate_count"),
        right.get("training_replicate_count"),
    )
    left_environment = left.get("environment")
    right_environment = right.get("environment")
    environment_similarity = (
        1.0
        if isinstance(left_environment, dict)
        and isinstance(right_environment, dict)
        and _canonical_json(left_environment) == _canonical_json(right_environment)
        else 0.0
    )
    return round(
        0.6 * type_similarity + 0.2 * replicate_similarity + 0.2 * environment_similarity,
        12,
    )


def retrieve_cross_job_memory(
    db: Session,
    *,
    current_job: models.Job,
    current_snapshot: HarnessEvidenceSnapshot,
    now: datetime | None = None,
) -> HarnessCrossJobMemory:
    """Retrieve bounded current-contract observations for one exact owner."""

    if not isinstance(current_job.user_id, str) or not current_job.user_id:
        return HarnessCrossJobMemory()
    if current_job.model_harness_domain != OPTIMIZATION_CONTROL_TUNING_DOMAIN:
        return HarnessCrossJobMemory()
    if not _memory_is_enabled(db, user_id=current_job.user_id):
        return HarnessCrossJobMemory()
    current_time = _utc(now)
    family_hash = task_family_sha256(current_snapshot, job=current_job)
    current_profile = _scenario_profile(current_snapshot)
    rows = list(
        db.scalars(
            select(models.HarnessExperienceMemory)
            .join(
                models.Job,
                models.Job.id == models.HarnessExperienceMemory.source_job_id,
            )
            .where(
                models.HarnessExperienceMemory.user_id == current_job.user_id,
                models.HarnessExperienceMemory.memory_domain == current_job.model_harness_domain,
                models.HarnessExperienceMemory.source_job_id != current_job.id,
                models.HarnessExperienceMemory.task_family_sha256 == family_hash,
                models.HarnessExperienceMemory.revoked_at.is_(None),
                models.HarnessExperienceMemory.expires_at > current_time,
                models.Job.user_id == current_job.user_id,
                models.Job.model_harness_domain == current_job.model_harness_domain,
                models.Job.status.in_(tuple(_TERMINAL_JOB_STATUSES)),
            )
            .order_by(
                models.HarnessExperienceMemory.created_at.desc(),
                models.HarnessExperienceMemory.id.desc(),
            )
            .limit(HARNESS_EXPERIENCE_RETRIEVAL_SCAN_LIMIT)
        )
    )
    ranked: list[tuple[float, datetime, str, HarnessCrossJobExperience]] = []
    for row in rows:
        if (
            not _row_contract_is_current(row)
            or not _row_receipt_is_valid(row)
            or not isinstance(row.scenario_profile_json, dict)
        ):
            continue
        memory = _row_memory(row)
        if (
            memory is None
            or memory.observed_outcome is None
            or memory.decision_source not in {"model", "deterministic_fallback"}
        ):
            continue
        similarity = scenario_profile_similarity(
            current_profile,
            row.scenario_profile_json,
        )
        experience = HarnessCrossJobExperience(
            scenario_similarity=similarity,
            tool_id=memory.tool_id,
            decision_source=memory.decision_source,
            plan_phase=memory.plan_phase,
            batch_policy=memory.batch_policy,
            dispatched_candidates=memory.dispatched_candidates,
            planned_candidates=memory.planned_candidates,
            observed_outcome=memory.observed_outcome,
        )
        ranked.append(
            (
                similarity,
                _utc(row.created_at),
                row.id,
                experience,
            )
        )
    ranked.sort(key=lambda item: (item[0], item[1], item[2]), reverse=True)
    return HarnessCrossJobMemory(
        experiences=tuple(item[3] for item in ranked[:MAX_CROSS_JOB_EXPERIENCE_ITEMS])
    )


def revoke_cross_job_experiences(
    db: Session,
    *,
    user_id: str,
    source_job_id: str | None = None,
    reason: str = "user_requested",
    now: datetime | None = None,
) -> int:
    """Revoke one user's retrievable experiences without trusting caller IDs."""

    if reason not in _REVOCATION_REASONS:
        raise ValueError("unsupported Harness experience revocation reason")
    predicates = [
        models.HarnessExperienceMemory.user_id == user_id,
        models.HarnessExperienceMemory.revoked_at.is_(None),
    ]
    if source_job_id is not None:
        predicates.append(models.HarnessExperienceMemory.source_job_id == source_job_id)
    result = db.execute(
        update(models.HarnessExperienceMemory)
        .where(*predicates)
        .values(revoked_at=_utc(now), revocation_reason=reason)
        .execution_options(synchronize_session=False)
    )
    return int(getattr(result, "rowcount", 0) or 0)


def purge_expired_cross_job_experiences(
    db: Session,
    *,
    now: datetime | None = None,
) -> int:
    """Delete data after its retention window; retrieval already ignores it."""

    result = db.execute(
        delete(models.HarnessExperienceMemory).where(
            models.HarnessExperienceMemory.expires_at <= _utc(now)
        )
    )
    return int(getattr(result, "rowcount", 0) or 0)


def delete_cross_job_experiences(
    db: Session,
    *,
    user_id: str,
    source_job_id: str | None = None,
) -> int:
    """Physically erase one user's structured memories on explicit request."""

    predicates = [models.HarnessExperienceMemory.user_id == user_id]
    if source_job_id is not None:
        predicates.append(models.HarnessExperienceMemory.source_job_id == source_job_id)
    result = db.execute(delete(models.HarnessExperienceMemory).where(*predicates))
    return int(getattr(result, "rowcount", 0) or 0)


__all__ = [
    "HARNESS_EXPERIENCE_MEMORY_SCHEMA_VERSION",
    "HARNESS_EXPERIENCE_RETENTION_DAYS",
    "HARNESS_EXPERIENCE_RETRIEVAL_POLICY_VERSION",
    "delete_cross_job_experiences",
    "materialize_verified_terminal_job_experiences",
    "purge_expired_cross_job_experiences",
    "retrieve_cross_job_memory",
    "revoke_cross_job_experiences",
    "scenario_profile_similarity",
    "task_family_sha256",
]
