from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError
from sqlalchemy.orm import configure_mappers

from app import models, schemas


def test_job_create_defaults_to_bounded_first_qualified_policy() -> None:
    request = schemas.JobCreateRequest()

    assert request.completion_policy == "first_qualified_stop"
    assert request.provider_turn_cap == 64

    with pytest.raises(ValidationError):
        schemas.JobCreateRequest(provider_turn_cap=129)


def test_first_qualified_and_cognitive_models_have_durable_constraints() -> None:
    configure_mappers()

    job_constraints = {constraint.name for constraint in models.Job.__table__.constraints}
    candidate_constraints = {
        constraint.name for constraint in models.CandidateParameterSet.__table__.constraints
    }
    turn_constraints = {
        constraint.name for constraint in models.HarnessCognitiveTurnReceipt.__table__.constraints
    }

    assert "ck_jobs_provider_turn_cap" in job_constraints
    assert "ck_jobs_provider_turn_counts" in job_constraints
    assert "uq_candidate_job_dispatch_ordinal" in candidate_constraints
    assert "uq_candidate_job_qualification_sequence" in candidate_constraints
    assert "ck_harness_turn_index" in turn_constraints
    assert models.FirstQualifiedFreezeReceipt.__table__.c.job_id.unique
    assert models.HarnessCognitiveTurnOutcome.__table__.c.turn_receipt_id.unique


def test_first_qualified_receipt_keeps_failed_and_indeterminate_work_visible() -> None:
    receipt = schemas.FirstQualifiedFreezeReceipt(
        receipt_schema="dronedream.first-qualified-freeze-receipt/v1",
        definition_version="server-sequence-deterministic-tiebreak/v1",
        id="fqf_example",
        job_id="job_example",
        candidate_id="cand_example",
        evidence_id="sha256:" + "a" * 64,
        holdout_contract_sha256="b" * 64,
        qualification_sequence=2,
        generation_index=1,
        dispatch_ordinal=3,
        time_to_first_qualified_ms=12_345,
        accounting=schemas.FirstQualifiedAccounting(
            simulations_attempted=7,
            trials_attempted=7,
            trials_completed=5,
            trials_passed=3,
            trials_failed=2,
            trials_cancelled=1,
            trials_timed_out=0,
            trials_indeterminate=1,
            generations=2,
            provider_turns_attempted=4,
            provider_turns_succeeded=3,
        ),
        frozen_at=datetime.now(timezone.utc),
    )

    assert receipt.accounting.trials_attempted == 7
    assert receipt.accounting.trials_failed == 2
    assert receipt.accounting.trials_cancelled == 1
    assert receipt.accounting.trials_indeterminate == 1
    assert receipt.accounting.provider_turns_attempted == 4


def test_cognitive_turn_contract_rejects_a_fifth_turn() -> None:
    common = {
        "receipt_schema": "dronedream.harness-cognitive-turn-attempt/v1",
        "id": "htr_example",
        "job_id": "job_example",
        "generation_index": 1,
        "turn_role": "critic",
        "trigger_policy_version": "adaptive-trigger-v1",
        "trigger_reasons": ["near_threshold"],
        "source_commit": "c" * 40,
        "model_snapshot": "fixed-model-snapshot",
        "prompt_sha256": "d" * 64,
        "evidence_sha256": "e" * 64,
        "schema_sha256": "f" * 64,
        "tool_outputs_sha256": "0" * 64,
        "attempted_at": datetime.now(timezone.utc),
    }

    assert schemas.HarnessCognitiveTurnReceipt(turn_index=4, **common).turn_index == 4
    with pytest.raises(ValidationError):
        schemas.HarnessCognitiveTurnReceipt(turn_index=5, **common)
