"""Deterministic contract evaluation for cross-Job Harness experience memory."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from datetime import datetime, timedelta, timezone

from sqlalchemy import create_engine, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app import models
from app.db import Base
from app.orchestration.decision_harness import build_decision_messages
from app.orchestration.experience_memory import (
    HARNESS_EXPERIENCE_MEMORY_SCHEMA_VERSION,
    HARNESS_EXPERIENCE_RETENTION_DAYS,
    HARNESS_EXPERIENCE_RETRIEVAL_POLICY_VERSION,
    materialize_verified_terminal_job_experiences,
    retrieve_cross_job_memory,
    revoke_cross_job_experiences,
)
from app.orchestration.harness_context import (
    HARNESS_DECISION_TRACE_SCHEMA_VERSION,
    HARNESS_EVIDENCE_SCHEMA_VERSION,
    HARNESS_PROMPT_TEMPLATE_VERSION,
    HARNESS_TOOL_ELIGIBILITY_POLICY_VERSION,
    HARNESS_TOOL_REGISTRY_VERSION,
    HarnessEvidenceSnapshot,
    HarnessExecutionMemory,
    HarnessObservedDecisionOutcome,
    build_harness_evidence,
)

HARNESS_CROSS_JOB_EVAL_SCHEMA_VERSION = (
    "dronedream.harness-cross-job-memory-evaluation/v1"
)
HARNESS_CROSS_JOB_EVAL_MANIFEST_SCHEMA_VERSION = (
    "dronedream.harness-cross-job-memory-evaluation-manifest/v1"
)
HARNESS_CROSS_JOB_EVAL_GENERATED_AT = "2026-07-28T17:28:13Z"
HARNESS_CROSS_JOB_EVAL_CLAIM_BOUNDARY = (
    "This deterministic in-memory SQLite evaluation proves the current software "
    "retrieval, isolation, retention, revocation, contract-drift, receipt-binding, "
    "provider-projection, and prompt-binding behavior for the enumerated fixtures. "
    "It makes no claim of optimizer-quality benefit, LLM superiority, physical "
    "fidelity, transfer to other tasks, real-aircraft performance, or flight safety."
)
HARNESS_CROSS_JOB_EVAL_CASES = (
    "same_user_exact_task_exact_scenario",
    "same_user_exact_task_shifted_scenario",
    "cross_user_isolated",
    "anonymous_user_isolated",
    "task_family_mismatch",
    "parameter_catalog_drift",
    "revoked_excluded",
    "expired_excluded",
    "contract_version_drift_excluded",
    "source_receipt_drift_excluded",
)

_NOW = datetime(2026, 7, 28, 16, 0, tzinfo=timezone.utc)


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    )


def _sha256(value: object) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _job(
    *,
    job_id: str,
    user_id: str | None,
    status: str,
    track_type: str = "circle",
    catalog_version: str = "builtin-v1",
    wind_north: float = 0.0,
) -> models.Job:
    return models.Job(
        id=job_id,
        user_id=user_id,
        track_type=track_type,
        altitude_m=5.0,
        wind_north=wind_north,
        sensor_noise_level="low",
        objective_profile="stable",
        status=status,
        optimizer_strategy="llm_harness",
        current_generation=1,
        max_iterations=3,
        max_total_trials=30,
        parameter_catalog_version=catalog_version,
    )


def _verified_memory() -> HarnessExecutionMemory:
    return HarnessExecutionMemory(
        generation=1,
        tool_id="turbo",
        decision_source="model",
        plan_phase="refinement",
        batch_policy="balanced",
        status="dispatched",
        dispatched_candidates=2,
        planned_candidates=2,
        reflection_status="verified_complete",
        observed_outcome=HarnessObservedDecisionOutcome(
            cohort_candidate_count=2,
            accepted_attempt_count=4,
            optimizer_learning_trial_count=4,
            domain_failure_trial_count=0,
            feasible_candidate_count=2,
            completed_candidate_rate=1.0,
            incumbent_score_before=0.9,
            cohort_best_score=0.7,
            incumbent_score_after=0.7,
            observed_absolute_improvement=0.2,
            observed_relative_improvement=0.222222222222,
        ),
    )


def _snapshot(
    job: models.Job,
    *,
    memory: tuple[HarnessExecutionMemory, ...] = (),
) -> HarnessEvidenceSnapshot:
    snapshot, _ = build_harness_evidence(job)
    return snapshot.model_copy(update={"decision_memory": memory})


def _database() -> tuple[Session, models.User, models.User, Engine]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    db = Session(engine)
    owner = models.User(
        id="usr_eval_owner",
        experience_preferences=models.UserExperiencePreferences(
            memory_enabled=True
        ),
    )
    other = models.User(
        id="usr_eval_other",
        experience_preferences=models.UserExperiencePreferences(
            memory_enabled=True
        ),
    )
    db.add_all([owner, other])
    db.flush()
    return db, owner, other, engine


def _evaluate_case(
    case_id: str,
    *,
    target_user: str | None = "owner",
    target_track: str = "circle",
    target_catalog: str = "builtin-v1",
    target_wind_north: float = 0.0,
    mutate: Callable[[Session], None] | None = None,
) -> dict[str, object]:
    db, owner, other, engine = _database()
    try:
        source = _job(
            job_id=f"job_source_{case_id}",
            user_id=owner.id,
            status="COMPLETED",
        )
        target_owner = {
            "owner": owner.id,
            "other": other.id,
            None: None,
        }[target_user]
        target = _job(
            job_id=f"job_target_{case_id}",
            user_id=target_owner,
            status="RUNNING",
            track_type=target_track,
            catalog_version=target_catalog,
            wind_north=target_wind_north,
        )
        db.add_all([source, target])
        db.flush()
        source_snapshot = _snapshot(source, memory=(_verified_memory(),))
        inserted = materialize_verified_terminal_job_experiences(
            db,
            source_job=source,
            snapshot=source_snapshot,
            now=_NOW,
        )
        db.flush()
        if mutate is not None:
            mutate(db)
            db.flush()
        target_snapshot = _snapshot(target)
        memory = retrieve_cross_job_memory(
            db,
            current_job=target,
            current_snapshot=target_snapshot,
            now=_NOW + timedelta(days=1),
        )
        full_snapshot = target_snapshot.model_copy(
            update={"cross_job_memory": memory}
        )
        no_memory_snapshot = target_snapshot
        _, full_prompt = build_decision_messages(full_snapshot)
        _, no_memory_prompt = build_decision_messages(no_memory_snapshot)
        projection = memory.model_dump(mode="json", exclude_none=True)
        encoded_projection = _canonical_json(projection)
        identifiers_absent = all(
            forbidden not in encoded_projection
            for forbidden in (
                source.id,
                target.id,
                owner.id,
                other.id,
                "seed",
                "holdout",
                "credential",
            )
        )
        return {
            "case_id": case_id,
            "inserted_source_experience_count": inserted,
            "retrieved_experience_count": len(memory.experiences),
            "scenario_similarity": (
                memory.experiences[0].scenario_similarity
                if memory.experiences
                else None
            ),
            "provider_identifiers_absent": identifiers_absent,
            "full_prompt_sha256": hashlib.sha256(
                full_prompt.encode("utf-8")
            ).hexdigest(),
            "no_memory_prompt_sha256": hashlib.sha256(
                no_memory_prompt.encode("utf-8")
            ).hexdigest(),
            "prompt_binding_changed": full_prompt != no_memory_prompt,
        }
    finally:
        db.close()
        engine.dispose()


def _revoke(db: Session) -> None:
    row = db.scalar(select(models.HarnessExperienceMemory))
    if row is None:
        raise RuntimeError("missing evaluation experience")
    revoke_cross_job_experiences(
        db,
        user_id=row.user_id,
        source_job_id=row.source_job_id,
        now=_NOW + timedelta(hours=1),
    )


def _expire(db: Session) -> None:
    row = db.scalar(select(models.HarnessExperienceMemory))
    if row is None:
        raise RuntimeError("missing evaluation experience")
    row.expires_at = _NOW


def _version_drift(db: Session) -> None:
    row = db.scalar(select(models.HarnessExperienceMemory))
    if row is None:
        raise RuntimeError("missing evaluation experience")
    row.source_evidence_schema_version = "retired"


def _receipt_drift(db: Session) -> None:
    row = db.scalar(select(models.HarnessExperienceMemory))
    if row is None:
        raise RuntimeError("missing evaluation experience")
    row.observed_outcome_json = {
        **row.observed_outcome_json,
        "cohort_best_score": 0.6,
    }


def build_harness_cross_job_memory_manifest() -> dict[str, object]:
    unsigned: dict[str, object] = {
        "schema_version": HARNESS_CROSS_JOB_EVAL_MANIFEST_SCHEMA_VERSION,
        "generated_at": HARNESS_CROSS_JOB_EVAL_GENERATED_AT,
        "claim_boundary": HARNESS_CROSS_JOB_EVAL_CLAIM_BOUNDARY,
        "cases": list(HARNESS_CROSS_JOB_EVAL_CASES),
        "runtime": {
            "database": "sqlite_in_memory",
            "provider_calls": 0,
            "network_calls": 0,
            "simulator_runs": 0,
            "real_credentials_used": False,
        },
        "contracts": {
            "memory_schema_version": HARNESS_EXPERIENCE_MEMORY_SCHEMA_VERSION,
            "retrieval_policy_version": (
                HARNESS_EXPERIENCE_RETRIEVAL_POLICY_VERSION
            ),
            "retention_days": HARNESS_EXPERIENCE_RETENTION_DAYS,
            "evidence_schema_version": HARNESS_EVIDENCE_SCHEMA_VERSION,
            "prompt_template_version": HARNESS_PROMPT_TEMPLATE_VERSION,
            "trace_schema_version": HARNESS_DECISION_TRACE_SCHEMA_VERSION,
            "tool_registry_version": HARNESS_TOOL_REGISTRY_VERSION,
            "eligibility_policy_version": (
                HARNESS_TOOL_ELIGIBILITY_POLICY_VERSION
            ),
        },
    }
    return {**unsigned, "manifest_sha256": _sha256(unsigned)}


def build_harness_cross_job_memory_artifact() -> dict[str, object]:
    rows = [
        _evaluate_case("same_user_exact_task_exact_scenario"),
        _evaluate_case(
            "same_user_exact_task_shifted_scenario",
            target_wind_north=2.0,
        ),
        _evaluate_case("cross_user_isolated", target_user="other"),
        _evaluate_case("anonymous_user_isolated", target_user=None),
        _evaluate_case("task_family_mismatch", target_track="u_turn"),
        _evaluate_case(
            "parameter_catalog_drift",
            target_catalog="builtin-v2",
        ),
        _evaluate_case("revoked_excluded", mutate=_revoke),
        _evaluate_case("expired_excluded", mutate=_expire),
        _evaluate_case(
            "contract_version_drift_excluded",
            mutate=_version_drift,
        ),
        _evaluate_case(
            "source_receipt_drift_excluded",
            mutate=_receipt_drift,
        ),
    ]
    expected_counts = {
        "same_user_exact_task_exact_scenario": 1,
        "same_user_exact_task_shifted_scenario": 1,
        "cross_user_isolated": 0,
        "anonymous_user_isolated": 0,
        "task_family_mismatch": 0,
        "parameter_catalog_drift": 0,
        "revoked_excluded": 0,
        "expired_excluded": 0,
        "contract_version_drift_excluded": 0,
        "source_receipt_drift_excluded": 0,
    }
    evaluated_rows: list[dict[str, object]] = []
    for row in rows:
        expected = expected_counts[str(row["case_id"])]
        evaluated_rows.append(
            {
                **row,
                "expected_retrieved_experience_count": expected,
                "passed": (
                    row["retrieved_experience_count"] == expected
                    and row["provider_identifiers_absent"] is True
                    and (
                        row["prompt_binding_changed"] is (expected > 0)
                    )
                ),
            }
        )
    def retrieved_count(row: dict[str, object]) -> int:
        value = row["retrieved_experience_count"]
        return value if isinstance(value, int) and not isinstance(value, bool) else 0

    manifest = build_harness_cross_job_memory_manifest()
    unsigned: dict[str, object] = {
        "schema_version": HARNESS_CROSS_JOB_EVAL_SCHEMA_VERSION,
        "generated_at": HARNESS_CROSS_JOB_EVAL_GENERATED_AT,
        "claim_boundary": HARNESS_CROSS_JOB_EVAL_CLAIM_BOUNDARY,
        "manifest_sha256": manifest["manifest_sha256"],
        "case_rows": evaluated_rows,
        "summary": {
            "case_count": len(evaluated_rows),
            "passed_count": sum(row["passed"] is True for row in evaluated_rows),
            "failed_count": sum(row["passed"] is not True for row in evaluated_rows),
            "retrieval_positive_count": sum(
                retrieved_count(row) > 0
                for row in evaluated_rows
            ),
            "retrieval_negative_count": sum(
                retrieved_count(row) == 0
                for row in evaluated_rows
            ),
            "provider_identifier_leak_count": sum(
                row["provider_identifiers_absent"] is not True
                for row in evaluated_rows
            ),
            "provider_calls": 0,
            "network_calls": 0,
            "simulator_runs": 0,
        },
    }
    return {**unsigned, "artifact_sha256": _sha256(unsigned)}


def verify_harness_cross_job_memory_manifest(payload: object) -> dict[str, object]:
    if not isinstance(payload, dict):
        raise ValueError("cross-Job memory manifest must be an object")
    unsigned = {key: value for key, value in payload.items() if key != "manifest_sha256"}
    if payload.get("manifest_sha256") != _sha256(unsigned):
        raise ValueError("cross-Job memory manifest hash does not recompute")
    expected = build_harness_cross_job_memory_manifest()
    if payload != expected:
        raise ValueError("cross-Job memory manifest drifted")
    return payload


def verify_harness_cross_job_memory_artifact(
    payload: object,
    *,
    manifest: object | None = None,
) -> dict[str, object]:
    if not isinstance(payload, dict):
        raise ValueError("cross-Job memory artifact must be an object")
    unsigned = {key: value for key, value in payload.items() if key != "artifact_sha256"}
    if payload.get("artifact_sha256") != _sha256(unsigned):
        raise ValueError("cross-Job memory artifact hash does not recompute")
    verified_manifest = verify_harness_cross_job_memory_manifest(
        build_harness_cross_job_memory_manifest() if manifest is None else manifest
    )
    if payload.get("manifest_sha256") != verified_manifest["manifest_sha256"]:
        raise ValueError("cross-Job memory artifact manifest binding drifted")
    expected = build_harness_cross_job_memory_artifact()
    if payload != expected:
        raise ValueError("cross-Job memory artifact drifted")
    return payload


def cross_job_memory_csv_rows(
    artifact: dict[str, object],
) -> list[dict[str, object]]:
    rows = artifact.get("case_rows")
    if not isinstance(rows, list):
        raise ValueError("cross-Job memory artifact has no case rows")
    return [
        {
            "case_id": row["case_id"],
            "expected_retrieved_experience_count": row[
                "expected_retrieved_experience_count"
            ],
            "retrieved_experience_count": row["retrieved_experience_count"],
            "scenario_similarity": row["scenario_similarity"],
            "provider_identifiers_absent": row["provider_identifiers_absent"],
            "prompt_binding_changed": row["prompt_binding_changed"],
            "passed": row["passed"],
        }
        for row in rows
        if isinstance(row, dict)
    ]


__all__ = [
    "HARNESS_CROSS_JOB_EVAL_CASES",
    "HARNESS_CROSS_JOB_EVAL_CLAIM_BOUNDARY",
    "HARNESS_CROSS_JOB_EVAL_MANIFEST_SCHEMA_VERSION",
    "HARNESS_CROSS_JOB_EVAL_SCHEMA_VERSION",
    "build_harness_cross_job_memory_artifact",
    "build_harness_cross_job_memory_manifest",
    "cross_job_memory_csv_rows",
    "verify_harness_cross_job_memory_artifact",
    "verify_harness_cross_job_memory_manifest",
]
