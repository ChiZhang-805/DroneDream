"""Safety and lifecycle tests for structured cross-Job Harness experience."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone


class _RoutingClient:
    def __init__(self) -> None:
        self.calls: list[dict[str, str]] = []

    def generate(self, *, model: str, system: str, user: str):
        self.calls.append({"model": model, "system": system, "user": user})
        return {
            "decision": {
                "tool_id": "optimizer_portfolio",
                "rationale": "The bounded portfolio is supported by the measured evidence.",
            }
        }


def _job(models, *, user_id: str, job_id: str, status: str, track_type: str = "circle"):
    return models.Job(
        id=job_id,
        user_id=user_id,
        track_type=track_type,
        altitude_m=5.0,
        sensor_noise_level="low",
        objective_profile="stable",
        status=status,
        optimizer_strategy="llm_harness",
        current_generation=1,
        max_iterations=3,
        max_total_trials=30,
    )


def _verified_memory(harness_context, *, cohort_best: float = 0.7):
    return harness_context.HarnessExecutionMemory(
        generation=1,
        tool_id="turbo",
        decision_source="model",
        plan_phase="refinement",
        batch_policy="balanced",
        status="dispatched",
        dispatched_candidates=2,
        planned_candidates=2,
        reflection_status="verified_complete",
        observed_outcome=harness_context.HarnessObservedDecisionOutcome(
            cohort_candidate_count=2,
            accepted_attempt_count=4,
            optimizer_learning_trial_count=4,
            domain_failure_trial_count=0,
            feasible_candidate_count=2,
            completed_candidate_rate=1.0,
            incumbent_score_before=0.9,
            cohort_best_score=cohort_best,
            incumbent_score_after=cohort_best,
            observed_absolute_improvement=0.9 - cohort_best,
            observed_relative_improvement=(0.9 - cohort_best) / 0.9,
        ),
    )


def _snapshot(harness_context, job, *, memory=()):
    snapshot, _ = harness_context.build_harness_evidence(job)
    return snapshot.model_copy(update={"decision_memory": tuple(memory)})


def test_cross_job_memory_is_user_isolated_closed_and_revocable(client) -> None:
    from app import models
    from app.db import SessionLocal
    from app.orchestration import experience_memory, harness_context
    from app.routers import jobs as jobs_router

    now = datetime(2026, 7, 28, 12, 0, tzinfo=timezone.utc)
    with SessionLocal() as db:
        owner = models.User(id="usr_owner_sentinel", email="owner@example.test")
        other = models.User(id="usr_other_sentinel", email="other@example.test")
        source = _job(
            models,
            user_id=owner.id,
            job_id="job_source_sentinel",
            status="COMPLETED",
        )
        target = _job(
            models,
            user_id=owner.id,
            job_id="job_target_sentinel",
            status="RUNNING",
        )
        other_target = _job(
            models,
            user_id=other.id,
            job_id="job_other_target_sentinel",
            status="RUNNING",
        )
        different_task = _job(
            models,
            user_id=owner.id,
            job_id="job_different_task_sentinel",
            status="RUNNING",
            track_type="u_turn",
        )
        db.add_all([owner, other, source, target, other_target, different_task])
        db.flush()

        source_snapshot = _snapshot(
            harness_context,
            source,
            memory=(_verified_memory(harness_context),),
        )
        assert (
            experience_memory.materialize_verified_terminal_job_experiences(
                db,
                source_job=source,
                snapshot=source_snapshot,
                now=now,
            )
            == 1
        )
        db.flush()
        assert (
            experience_memory.materialize_verified_terminal_job_experiences(
                db,
                source_job=source,
                snapshot=source_snapshot,
                now=now + timedelta(minutes=1),
            )
            == 0
        )

        target_snapshot = _snapshot(harness_context, target)
        memory = experience_memory.retrieve_cross_job_memory(
            db,
            current_job=target,
            current_snapshot=target_snapshot,
            now=now + timedelta(days=1),
        )
        assert len(memory.experiences) == 1
        experience = memory.experiences[0]
        assert experience.tool_id == "turbo"
        assert experience.scenario_similarity == 1.0
        assert experience.observed_outcome.cohort_best_score == 0.7

        provider_payload = memory.model_dump(mode="json", exclude_none=True)
        encoded = json.dumps(provider_payload, sort_keys=True)
        for forbidden in (
            owner.id,
            other.id,
            source.id,
            target.id,
            "owner@example.test",
            "seed",
            "holdout",
            "credential",
        ):
            assert forbidden not in encoded
        assert set(provider_payload) == {
            "schema_id",
            "retrieval_policy_version",
            "retention_days",
            "scope",
            "task_family_policy",
            "claim_boundary",
            "experiences",
        }

        assert not experience_memory.retrieve_cross_job_memory(
            db,
            current_job=other_target,
            current_snapshot=_snapshot(harness_context, other_target),
            now=now + timedelta(days=1),
        ).experiences
        assert not experience_memory.retrieve_cross_job_memory(
            db,
            current_job=different_task,
            current_snapshot=_snapshot(harness_context, different_task),
            now=now + timedelta(days=1),
        ).experiences

        response = jobs_router.revoke_job_harness_experiences(
            source.id,
            db,
            owner,
            idempotency_key=None,
        )
        assert response["data"] == {
            "job_id": source.id,
            "revoked_count": 1,
            "memory_schema_version": "1.0",
            "retrieval_policy_version": "1.0",
            "retention_days": 90,
        }
        db.expire_all()
        target = db.get(models.Job, target.id)
        assert target is not None
        assert not experience_memory.retrieve_cross_job_memory(
            db,
            current_job=target,
            current_snapshot=target_snapshot,
            now=now + timedelta(days=1),
        ).experiences


def test_cross_job_memory_fails_closed_on_expiry_version_or_receipt_drift(client) -> None:
    from app import models
    from app.db import SessionLocal
    from app.orchestration import experience_memory, harness_context

    now = datetime(2026, 7, 28, 12, 0, tzinfo=timezone.utc)
    with SessionLocal() as db:
        owner = models.User(id="usr_memory_owner")
        source = _job(
            models,
            user_id=owner.id,
            job_id="job_memory_source",
            status="FAILED",
        )
        target = _job(
            models,
            user_id=owner.id,
            job_id="job_memory_target",
            status="RUNNING",
        )
        db.add_all([owner, source, target])
        db.flush()
        source_snapshot = _snapshot(
            harness_context,
            source,
            memory=(_verified_memory(harness_context),),
        )
        experience_memory.materialize_verified_terminal_job_experiences(
            db,
            source_job=source,
            snapshot=source_snapshot,
            now=now,
        )
        db.flush()
        row = db.query(models.HarnessExperienceMemory).one()
        target_snapshot = _snapshot(harness_context, target)

        row.source_evidence_schema_version = "retired"
        db.flush()
        assert not experience_memory.retrieve_cross_job_memory(
            db,
            current_job=target,
            current_snapshot=target_snapshot,
            now=now + timedelta(days=1),
        ).experiences

        row.source_evidence_schema_version = (
            harness_context.HARNESS_EVIDENCE_SCHEMA_VERSION
        )
        row.observed_outcome_json = {
            **row.observed_outcome_json,
            "cohort_best_score": 0.6,
        }
        db.flush()
        assert not experience_memory.retrieve_cross_job_memory(
            db,
            current_job=target,
            current_snapshot=target_snapshot,
            now=now + timedelta(days=1),
        ).experiences

        row.observed_outcome_json = _verified_memory(
            harness_context
        ).observed_outcome.model_dump(mode="json", exclude_none=True)
        row.expires_at = now
        db.flush()
        assert not experience_memory.retrieve_cross_job_memory(
            db,
            current_job=target,
            current_snapshot=target_snapshot,
            now=now + timedelta(seconds=1),
        ).experiences
        assert (
            experience_memory.purge_expired_cross_job_experiences(
                db,
                now=now + timedelta(seconds=1),
            )
            == 1
        )
        assert db.query(models.HarnessExperienceMemory).count() == 0


def test_cross_job_memory_rejects_nonterminal_or_incomplete_sources(client) -> None:
    from app import models
    from app.db import SessionLocal
    from app.orchestration import experience_memory, harness_context

    with SessionLocal() as db:
        owner = models.User(id="usr_incomplete_owner")
        running = _job(
            models,
            user_id=owner.id,
            job_id="job_running_source",
            status="RUNNING",
        )
        terminal = _job(
            models,
            user_id=owner.id,
            job_id="job_incomplete_source",
            status="CANCELLED",
        )
        db.add_all([owner, running, terminal])
        db.flush()
        unavailable = _verified_memory(harness_context).model_copy(
            update={"reflection_status": "unavailable", "observed_outcome": None}
        )
        assert (
            experience_memory.materialize_verified_terminal_job_experiences(
                db,
                source_job=running,
                snapshot=_snapshot(
                    harness_context,
                    running,
                    memory=(_verified_memory(harness_context),),
                ),
            )
            == 0
        )
        assert (
            experience_memory.materialize_verified_terminal_job_experiences(
                db,
                source_job=terminal,
                snapshot=_snapshot(
                    harness_context,
                    terminal,
                    memory=(unavailable,),
                ),
            )
            == 0
        )
        assert db.query(models.HarnessExperienceMemory).count() == 0
        assert (
            experience_memory.materialize_verified_terminal_job_experiences(
                db,
                source_job=terminal,
                snapshot=_snapshot(
                    harness_context,
                    terminal,
                    memory=(_verified_memory(harness_context),),
                ),
            )
            == 1
        )
        db.flush()
        assert (
            experience_memory.materialize_verified_terminal_job_experiences(
                db,
                source_job=terminal,
                snapshot=_snapshot(harness_context, terminal),
            )
            == 0
        )
        row = db.query(models.HarnessExperienceMemory).one()
        assert row.revoked_at is not None
        assert row.revocation_reason == "source_receipt_drift"


def test_live_harness_trace_binds_provider_safe_cross_job_memory(client) -> None:
    from app import models
    from app.db import SessionLocal
    from app.orchestration import (
        decision_harness,
        experience_memory,
        harness_context,
    )

    now = datetime.now(timezone.utc)
    with SessionLocal() as db:
        owner = models.User(id="usr_live_memory_owner")
        source = _job(
            models,
            user_id=owner.id,
            job_id="job_live_memory_source",
            status="COMPLETED",
        )
        target = _job(
            models,
            user_id=owner.id,
            job_id="job_live_memory_target",
            status="RUNNING",
        )
        target.current_generation = 0
        target.openai_model = "gpt-test"
        target.llm_provider = "openai"
        db.add_all([owner, source, target])
        db.flush()
        db.add(
            models.CandidateParameterSet(
                job_id=target.id,
                generation_index=0,
                source_type="baseline",
                parameter_json={"kp_xy": 1.0},
                aggregated_score=0.9,
                aggregated_metric_json={
                    "rmse": 0.9,
                    "max_error": 1.3,
                    "scalar_loss": 0.9,
                    "feasible": True,
                },
                trial_count=1,
                completed_trial_count=1,
                is_baseline=True,
            )
        )
        source_snapshot = _snapshot(
            harness_context,
            source,
            memory=(_verified_memory(harness_context),),
        )
        experience_memory.materialize_verified_terminal_job_experiences(
            db,
            source_job=source,
            snapshot=source_snapshot,
            now=now,
        )
        source.updated_at = now - timedelta(days=1)
        db.add_all(
            [
                _job(
                    models,
                    user_id=owner.id,
                    job_id=f"job_newer_terminal_{index:02d}",
                    status="COMPLETED",
                )
                for index in range(12)
            ]
        )
        for index, newer in enumerate(
            db.query(models.Job)
            .filter(models.Job.id.like("job_newer_terminal_%"))
            .all()
        ):
            newer.updated_at = now + timedelta(minutes=index)
        db.flush()

        fake = _RoutingClient()
        decision = decision_harness.select_optimizer_tool(
            db,
            target,
            client=fake,
        )
        db.flush()
        assert decision.tool_id == "optimizer_portfolio"
        assert decision.evidence_schema_version == "2.9"
        assert decision.prompt_template_version == "1.7"
        assert len(fake.calls) == 1
        provider_payload = json.loads(fake.calls[0]["user"])
        experiences = provider_payload["evidence"]["cross_job_memory"][
            "experiences"
        ]
        assert len(experiences) == 1
        encoded = json.dumps(experiences, sort_keys=True)
        assert source.id not in encoded
        assert owner.id not in encoded
        assert experiences[0]["tool_id"] == "turbo"
        started = next(
            event
            for event in target.events
            if event.event_type == "harness_decision_started"
        )
        verification = decision_harness.verify_harness_decision_trace(
            started.payload_json
        )
        assert verification.valid is True
        assert verification.failures == ()
