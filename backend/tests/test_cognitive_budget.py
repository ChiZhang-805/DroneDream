from __future__ import annotations

from collections.abc import Iterator
from types import SimpleNamespace

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session


class SequenceClient:
    def __init__(self, responses: list[dict[str, object]]) -> None:
        self.responses = list(responses)
        self.calls: list[dict[str, str]] = []

    def generate(self, *, model: str, system: str, user: str):
        self.calls.append({"model": model, "system": system, "user": user})
        return self.responses.pop(0)


@pytest.fixture()
def cognitive_db(tmp_path) -> Iterator[SimpleNamespace]:
    from app import models, schemas
    from app.db import _build_engine

    engine = _build_engine(f"sqlite:///{tmp_path / 'cognitive.db'}")
    models.Base.metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                CREATE TRIGGER trg_harness_cognitive_turn_receipts_no_update
                BEFORE UPDATE ON harness_cognitive_turn_receipts
                BEGIN
                    SELECT RAISE(ABORT, 'cognitive turn receipts are append-only');
                END
                """
            )
        )
        connection.execute(
            text(
                """
                CREATE TRIGGER trg_harness_cognitive_turn_receipts_no_delete
                BEFORE DELETE ON harness_cognitive_turn_receipts
                WHEN NOT EXISTS (
                    SELECT 1
                    FROM harness_cognitive_turn_delete_authorizations
                    WHERE receipt_id = OLD.id
                )
                BEGIN
                    SELECT RAISE(ABORT, 'cognitive turn receipts are append-only');
                END
                """
            )
        )
        connection.execute(
            text(
                """
                CREATE TRIGGER trg_harness_cognitive_turn_outcomes_no_update
                BEFORE UPDATE ON harness_cognitive_turn_outcomes
                BEGIN
                    SELECT RAISE(ABORT, 'cognitive turn outcomes are append-only');
                END
                """
            )
        )
        connection.execute(
            text(
                """
                CREATE TRIGGER trg_harness_cognitive_turn_outcomes_no_delete
                BEFORE DELETE ON harness_cognitive_turn_outcomes
                WHEN NOT EXISTS (
                    SELECT 1
                    FROM harness_cognitive_turn_delete_authorizations
                    WHERE receipt_id = OLD.turn_receipt_id
                )
                BEGIN
                    SELECT RAISE(ABORT, 'cognitive turn outcomes are append-only');
                END
                """
            )
        )
    try:
        yield SimpleNamespace(engine=engine, models=models, schemas=schemas)
    finally:
        engine.dispose()


def _create_harness_job(
    db: Session,
    models,
    schemas,
    *,
    provider_turn_cap: int = 8,
):
    scenario_suite = schemas.ScenarioSuiteConfig()
    job = models.Job(
        track_type="circle",
        altitude_m=3.0,
        sensor_noise_level="medium",
        objective_profile="robust",
        status="RUNNING",
        simulator_backend_requested="mock",
        optimizer_strategy="llm_harness",
        max_iterations=3,
        max_total_trials=64,
        provider_turn_cap=provider_turn_cap,
        scenario_suite_json=scenario_suite.model_dump(mode="json"),
        vehicle_profile_json=schemas.VehicleProfileConfig().model_dump(mode="json"),
        parameter_space_json=[],
        objective_config_json=schemas.ObjectiveConfig().model_dump(mode="json"),
        openai_model="gpt-4.1-2025-04-14",
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


def _attempt(module, db, job, *, turn_index: int, suffix: str = "a"):
    return module.begin_cognitive_turn(
        db,
        job,
        generation_index=job.current_generation + 1,
        turn_index=turn_index,
        turn_role={1: "plan", 2: "revision", 3: "diagnosis", 4: "critic"}[turn_index],
        trigger_reasons=("test_reason",),
        model_snapshot="gpt-4.1-2025-04-14",
        prompt_sha256=suffix * 64,
        evidence_sha256="b" * 64,
        schema_sha256="c" * 64,
        tool_outputs_sha256="d" * 64,
    )


def test_attempt_is_durable_before_network_and_cannot_be_replayed(
    cognitive_db,
    monkeypatch,
) -> None:
    monkeypatch.setenv("DRONEDREAM_SOURCE_COMMIT", "1" * 40)
    models = cognitive_db.models
    from app.orchestration import cognitive_budget

    with Session(cognitive_db.engine) as db:
        job = _create_harness_job(db, models, cognitive_db.schemas)
        job_id = job.id
        attempt = _attempt(cognitive_budget, db, job, turn_index=1)
        assert job.provider_turns_attempted == 1
        receipt = db.get(models.HarnessCognitiveTurnReceipt, attempt.receipt_id)
        assert receipt is not None
        assert receipt.outcome is None

    with Session(cognitive_db.engine) as db:
        job = db.get(models.Job, job_id)
        assert job is not None
        with pytest.raises(cognitive_budget.CognitiveTurnBlocked) as replay:
            _attempt(cognitive_budget, db, job, turn_index=1)
        assert replay.value.code == "turn_already_attempted"

        status = cognitive_budget.finish_cognitive_turn(
            db,
            job,
            attempt,
            status="succeeded",
            response={"decision": "continue"},
        )
        assert status == "succeeded"
        assert job.provider_turns_attempted == 1
        assert job.provider_turns_succeeded == 1

        with pytest.raises(DBAPIError):
            db.execute(
                text(
                    "UPDATE harness_cognitive_turn_receipts "
                    "SET turn_role='critic' WHERE id=:receipt_id"
                ),
                {"receipt_id": attempt.receipt_id},
            )
            db.commit()
        db.rollback()

        job = db.get(models.Job, job_id)
        assert job is not None
        receipt = db.get(models.HarnessCognitiveTurnReceipt, attempt.receipt_id)
        assert receipt is not None
        db.add(
            models.HarnessCognitiveTurnDeleteAuthorization(
                receipt_id=receipt.id,
                reason="job_delete",
            )
        )
        db.delete(job)
        db.commit()
        assert db.get(models.Job, job_id) is None


def test_source_drift_is_recorded_and_not_counted_as_success(
    cognitive_db,
    monkeypatch,
) -> None:
    monkeypatch.setenv("DRONEDREAM_SOURCE_COMMIT", "2" * 40)
    models = cognitive_db.models
    from app.orchestration import cognitive_budget

    with Session(cognitive_db.engine) as db:
        job = _create_harness_job(db, models, cognitive_db.schemas)
        attempt = _attempt(cognitive_budget, db, job, turn_index=1)
        monkeypatch.setenv("DRONEDREAM_SOURCE_COMMIT", "3" * 40)
        status = cognitive_budget.finish_cognitive_turn(
            db,
            job,
            attempt,
            status="succeeded",
            response={"decision": "continue"},
        )
        assert status == "source_drift"
        assert job.provider_turns_attempted == 1
        assert job.provider_turns_succeeded == 0
        receipt = db.get(models.HarnessCognitiveTurnReceipt, attempt.receipt_id)
        assert receipt is not None and receipt.outcome is not None
        assert receipt.outcome.error_code == "source_drift"


def test_job_provider_turn_cap_is_atomic_and_fail_closed(
    cognitive_db,
    monkeypatch,
) -> None:
    monkeypatch.setenv("DRONEDREAM_SOURCE_COMMIT", "4" * 40)
    models = cognitive_db.models
    from app.orchestration import cognitive_budget

    with Session(cognitive_db.engine) as db:
        job = _create_harness_job(
            db,
            models,
            cognitive_db.schemas,
            provider_turn_cap=1,
        )
        _attempt(cognitive_budget, db, job, turn_index=1)
        with pytest.raises(cognitive_budget.CognitiveTurnBlocked) as exhausted:
            _attempt(cognitive_budget, db, job, turn_index=2, suffix="e")
        assert exhausted.value.code == "provider_turn_cap_exhausted"
        assert job.provider_turns_attempted == 1


def test_training_only_failure_triggers_and_cooldown(
    cognitive_db,
    monkeypatch,
) -> None:
    monkeypatch.setenv("DRONEDREAM_SOURCE_COMMIT", "5" * 40)
    models = cognitive_db.models
    schemas = cognitive_db.schemas
    from app.optimization.scenarios import scenario_matrix_for_generation
    from app.orchestration import cognitive_budget
    from app.orchestration.harness_context import build_harness_evidence
    from app.simulator.base import FAILURE_UNSTABLE

    with Session(cognitive_db.engine) as db:
        job = _create_harness_job(db, models, schemas)
        suite = schemas.ScenarioSuiteConfig(**job.scenario_suite_json)
        training_run = next(
            run
            for run in scenario_matrix_for_generation(suite, generation_index=0)
            if not run.holdout
        )
        candidate = models.CandidateParameterSet(
            job_id=job.id,
            generation_index=0,
            source_type="baseline",
            label="unsafe baseline",
            parameter_json={"kp_xy": 1.0},
            is_baseline=True,
            trial_count=1,
            completed_trial_count=0,
            aggregated_metric_json={"feasible": False},
            aggregated_score=20.0,
        )
        db.add(candidate)
        db.flush()
        db.add(
            models.Trial(
                job_id=job.id,
                candidate_id=candidate.id,
                seed=training_run.seed,
                scenario_type=training_run.scenario_type,
                scenario_config_json=training_run.persistence_config(),
                status="FAILED",
                failure_code=FAILURE_UNSTABLE,
            )
        )
        job.current_generation = 1
        db.commit()
        db.refresh(job)

        snapshot, _ = build_harness_evidence(job)
        evaluation = cognitive_budget.evaluate_adaptive_triggers(
            job,
            generation_index=2,
            snapshot=snapshot,
            proposal_tools={"proposal-a": "cma_es"},
            selected_proposal_refs=("proposal-a",),
            tool_direction_conflict=False,
            hard_boundary_candidate=False,
        )
        assert "domain_failure_spike" in evaluation.diagnosis_reasons
        assert "ood_no_transfer_memory" in evaluation.diagnosis_reasons
        assert "crash_or_instability" in evaluation.critic_reasons
        assert evaluation.evidence["holdout_outcomes_visible"] is False
        assert evaluation.evidence["training_failure_summary"] == {
            "unstable_or_simulation_failure_count": 1,
            "timeout_count": 0,
            "sensor_case_domain_failure_count": 0,
        }

        db.add(
            models.HarnessCognitiveTurnReceipt(
                job_id=job.id,
                receipt_schema=cognitive_budget.COGNITIVE_ATTEMPT_SCHEMA,
                generation_index=1,
                turn_index=3,
                turn_role="diagnosis",
                trigger_policy_version=(cognitive_budget.COGNITIVE_TRIGGER_POLICY_VERSION),
                trigger_reasons_json=["domain_failure_spike"],
                source_commit="5" * 40,
                model_snapshot="gpt-4.1-2025-04-14",
                prompt_sha256="6" * 64,
                evidence_sha256="7" * 64,
                schema_sha256="8" * 64,
                tool_outputs_sha256="9" * 64,
            )
        )
        db.commit()
        db.refresh(job)
        cooled = cognitive_budget.evaluate_adaptive_triggers(
            job,
            generation_index=2,
            snapshot=snapshot,
            proposal_tools={"proposal-a": "cma_es"},
            selected_proposal_refs=("proposal-a",),
            tool_direction_conflict=False,
            hard_boundary_candidate=False,
        )
        assert "domain_failure_spike" in cooled.suppressed_by_cooldown
        assert "domain_failure_spike" not in cooled.diagnosis_reasons
        assert "crash_or_instability" in cooled.critic_reasons


def test_adaptive_review_uses_bounded_t3_and_t4_without_expansion(
    cognitive_db,
    monkeypatch,
) -> None:
    monkeypatch.setenv("DRONEDREAM_SOURCE_COMMIT", "a" * 40)
    from app.orchestration import cognitive_budget, cognitive_review
    from app.orchestration.harness_budget_planner import HarnessProposalSummary

    with Session(cognitive_db.engine) as db:
        job = _create_harness_job(
            db,
            cognitive_db.models,
            cognitive_db.schemas,
        )
        for turn_index, suffix in ((1, "1"), (2, "2")):
            attempt = _attempt(
                cognitive_budget,
                db,
                job,
                turn_index=turn_index,
                suffix=suffix,
            )
            cognitive_budget.finish_cognitive_turn(
                db,
                job,
                attempt,
                status="succeeded",
                response={"turn": turn_index},
            )
        proposals = (
            HarnessProposalSummary(
                proposal_ref="proposal_0",
                tool_id="cma_es",
                tool_candidate_ordinal=0,
                requested_fidelity=1.0,
                effective_fidelity=1.0,
                normalized_distance_from_incumbent=0.2,
            ),
            HarnessProposalSummary(
                proposal_ref="proposal_1",
                tool_id="turbo",
                tool_candidate_ordinal=0,
                requested_fidelity=1.0,
                effective_fidelity=1.0,
                normalized_distance_from_incumbent=0.3,
            ),
        )
        trigger = cognitive_budget.CognitiveTriggerEvaluation(
            policy_version=cognitive_budget.COGNITIVE_TRIGGER_POLICY_VERSION,
            diagnosis_reasons=("tool_direction_conflict",),
            critic_reasons=("hard_boundary_candidate",),
            suppressed_by_cooldown=(),
            evidence={"holdout_outcomes_visible": False},
        )
        client = SequenceClient(
            [
                {
                    "schema_version": "1.0",
                    "decision": "replace",
                    "selected_proposal_refs": ["proposal_1"],
                    "diagnosis_codes": ["tool_direction_conflict"],
                },
                {
                    "schema_version": "1.0",
                    "decision": "approve",
                    "approved_proposal_refs": ["proposal_1"],
                    "risk_codes": ["hard_boundary_candidate"],
                },
            ]
        )
        result = cognitive_review.run_adaptive_cognitive_review(
            db,
            job,
            generation_index=1,
            trigger=trigger,
            proposals=proposals,
            selected_proposal_refs=("proposal_0",),
            proposal_details={
                "proposal_0": {"proposal_ref": "proposal_0"},
                "proposal_1": {"proposal_ref": "proposal_1"},
            },
            hard_bounds=[{"parameter": "MPC_XY_P", "minimum": 0.1, "maximum": 1.0}],
            client=client,
        )
        assert result.selected_proposal_refs == ("proposal_1",)
        assert result.diagnosis_decision == "replace"
        assert result.critic_decision == "approve"
        assert result.fail_closed_reason is None
        assert len(client.calls) == 2
        assert job.provider_turns_attempted == 4
        assert job.provider_turns_succeeded == 4
        assert all("holdout_outcomes_visible" in call["user"] for call in client.calls)


def test_adaptive_review_invalid_diagnosis_fails_closed_without_t4(
    cognitive_db,
    monkeypatch,
) -> None:
    monkeypatch.setenv("DRONEDREAM_SOURCE_COMMIT", "b" * 40)
    from app.orchestration import cognitive_budget, cognitive_review
    from app.orchestration.harness_budget_planner import HarnessProposalSummary

    with Session(cognitive_db.engine) as db:
        job = _create_harness_job(
            db,
            cognitive_db.models,
            cognitive_db.schemas,
        )
        for turn_index, suffix in ((1, "3"), (2, "4")):
            attempt = _attempt(
                cognitive_budget,
                db,
                job,
                turn_index=turn_index,
                suffix=suffix,
            )
            cognitive_budget.finish_cognitive_turn(
                db,
                job,
                attempt,
                status="succeeded",
                response={"turn": turn_index},
            )
        proposal = HarnessProposalSummary(
            proposal_ref="proposal_0",
            tool_id="cma_es",
            tool_candidate_ordinal=0,
            requested_fidelity=1.0,
            effective_fidelity=1.0,
            normalized_distance_from_incumbent=0.2,
        )
        trigger = cognitive_budget.CognitiveTriggerEvaluation(
            policy_version=cognitive_budget.COGNITIVE_TRIGGER_POLICY_VERSION,
            diagnosis_reasons=("trailing_stagnation",),
            critic_reasons=("near_threshold_uncertain",),
            suppressed_by_cooldown=(),
            evidence={"holdout_outcomes_visible": False},
        )
        client = SequenceClient(
            [
                {
                    "schema_version": "1.0",
                    "decision": "replace",
                    "selected_proposal_refs": ["unknown"],
                    "diagnosis_codes": ["trailing_stagnation"],
                },
                {
                    "schema_version": "1.0",
                    "decision": "approve",
                    "approved_proposal_refs": ["proposal_0"],
                    "risk_codes": ["near_threshold_uncertain"],
                },
            ]
        )
        result = cognitive_review.run_adaptive_cognitive_review(
            db,
            job,
            generation_index=1,
            trigger=trigger,
            proposals=(proposal,),
            selected_proposal_refs=("proposal_0",),
            proposal_details={"proposal_0": {"proposal_ref": "proposal_0"}},
            hard_bounds=[],
            client=client,
        )
        assert result.selected_proposal_refs == ()
        assert result.fail_closed_reason == "diagnosis_invalid_schema"
        assert len(client.calls) == 1
        assert job.provider_turns_attempted == 3
        assert job.provider_turns_succeeded == 2
        receipt = next(item for item in job.cognitive_turn_receipts if item.turn_index == 3)
        assert receipt.outcome is not None
        assert receipt.outcome.status == "invalid_schema"


def test_adaptive_review_can_stop_at_three_turns_when_only_diagnosis_is_triggered(
    cognitive_db,
    monkeypatch,
) -> None:
    monkeypatch.setenv("DRONEDREAM_SOURCE_COMMIT", "c" * 40)
    from app.orchestration import cognitive_budget, cognitive_review
    from app.orchestration.harness_budget_planner import HarnessProposalSummary

    with Session(cognitive_db.engine) as db:
        job = _create_harness_job(
            db,
            cognitive_db.models,
            cognitive_db.schemas,
        )
        for turn_index, suffix in ((1, "5"), (2, "6")):
            attempt = _attempt(
                cognitive_budget,
                db,
                job,
                turn_index=turn_index,
                suffix=suffix,
            )
            cognitive_budget.finish_cognitive_turn(
                db,
                job,
                attempt,
                status="succeeded",
                response={"turn": turn_index},
            )
        proposal = HarnessProposalSummary(
            proposal_ref="proposal_0",
            tool_id="cma_es",
            tool_candidate_ordinal=0,
            requested_fidelity=1.0,
            effective_fidelity=1.0,
            normalized_distance_from_incumbent=0.2,
        )
        trigger = cognitive_budget.CognitiveTriggerEvaluation(
            policy_version=cognitive_budget.COGNITIVE_TRIGGER_POLICY_VERSION,
            diagnosis_reasons=("trailing_stagnation",),
            critic_reasons=(),
            suppressed_by_cooldown=(),
            evidence={"holdout_outcomes_visible": False},
        )
        client = SequenceClient(
            [
                {
                    "schema_version": "1.0",
                    "decision": "keep",
                    "selected_proposal_refs": ["proposal_0"],
                    "diagnosis_codes": ["trailing_stagnation"],
                }
            ]
        )
        result = cognitive_review.run_adaptive_cognitive_review(
            db,
            job,
            generation_index=1,
            trigger=trigger,
            proposals=(proposal,),
            selected_proposal_refs=("proposal_0",),
            proposal_details={"proposal_0": {"proposal_ref": "proposal_0"}},
            hard_bounds=[],
            client=client,
        )
        assert result.selected_proposal_refs == ("proposal_0",)
        assert result.diagnosis_decision == "keep"
        assert result.critic_decision is None
        assert result.fail_closed_reason is None
        assert len(client.calls) == 1
        assert job.provider_turns_attempted == 3
        assert job.provider_turns_succeeded == 3
        assert {item.turn_index for item in job.cognitive_turn_receipts} == {1, 2, 3}


def test_adaptive_review_can_run_t4_directly_after_t2_for_high_risk_evidence(
    cognitive_db,
    monkeypatch,
) -> None:
    monkeypatch.setenv("DRONEDREAM_SOURCE_COMMIT", "d" * 40)
    from app.orchestration import cognitive_budget, cognitive_review
    from app.orchestration.harness_budget_planner import HarnessProposalSummary

    with Session(cognitive_db.engine) as db:
        job = _create_harness_job(
            db,
            cognitive_db.models,
            cognitive_db.schemas,
        )
        for turn_index, suffix in ((1, "7"), (2, "8")):
            attempt = _attempt(
                cognitive_budget,
                db,
                job,
                turn_index=turn_index,
                suffix=suffix,
            )
            cognitive_budget.finish_cognitive_turn(
                db,
                job,
                attempt,
                status="succeeded",
                response={"turn": turn_index},
            )
        proposal = HarnessProposalSummary(
            proposal_ref="proposal_0",
            tool_id="cma_es",
            tool_candidate_ordinal=0,
            requested_fidelity=1.0,
            effective_fidelity=1.0,
            normalized_distance_from_incumbent=0.98,
        )
        trigger = cognitive_budget.CognitiveTriggerEvaluation(
            policy_version=cognitive_budget.COGNITIVE_TRIGGER_POLICY_VERSION,
            diagnosis_reasons=(),
            critic_reasons=("hard_boundary_candidate",),
            suppressed_by_cooldown=(),
            evidence={"holdout_outcomes_visible": False},
        )
        client = SequenceClient(
            [
                {
                    "schema_version": "1.0",
                    "decision": "approve",
                    "approved_proposal_refs": ["proposal_0"],
                    "risk_codes": ["hard_boundary_candidate"],
                }
            ]
        )
        result = cognitive_review.run_adaptive_cognitive_review(
            db,
            job,
            generation_index=1,
            trigger=trigger,
            proposals=(proposal,),
            selected_proposal_refs=("proposal_0",),
            proposal_details={"proposal_0": {"proposal_ref": "proposal_0"}},
            hard_bounds=[],
            client=client,
        )
        assert result.selected_proposal_refs == ("proposal_0",)
        assert result.diagnosis_decision is None
        assert result.critic_decision == "approve"
        assert result.fail_closed_reason is None
        assert len(client.calls) == 1
        assert job.provider_turns_attempted == 3
        assert job.provider_turns_succeeded == 3
        assert {item.turn_index for item in job.cognitive_turn_receipts} == {1, 2, 4}
