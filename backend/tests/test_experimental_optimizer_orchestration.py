"""End-to-end orchestration coverage for the seven experimental optimizers."""

from __future__ import annotations

import sys
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy import select, update
from sqlalchemy.exc import DatabaseError

STRATEGIES = (
    "constrained_mobo",
    "multi_fidelity_mobo",
    "turbo",
    "saasbo",
    "surrogate_cma_es",
    "bipop_cma_es",
    "optimizer_portfolio",
)

CHILD_STRATEGIES = {
    "constrained_mobo",
    "multi_fidelity_mobo",
    "turbo",
    "saasbo",
    "surrogate_cma_es",
    "bipop_cma_es",
}


@pytest.fixture()
def experimental_ctx(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[dict[str, Any]]:
    db_path = tmp_path / "experimental-optimizers.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("APP_SECRET_KEY", "experimental-optimizer-test-key")

    from app import config as config_module

    config_module.get_settings.cache_clear()
    for name in list(sys.modules):
        if name == "app" or name.startswith("app."):
            del sys.modules[name]

    import app.db as db_module
    import app.models as models_module
    import app.orchestration.runner as runner
    import app.schemas as schemas_module
    import app.services.jobs as jobs_service

    db_module.init_db()
    yield {
        "db": db_module,
        "models": models_module,
        "runner": runner,
        "schemas": schemas_module,
        "jobs": jobs_service,
    }
    config_module.get_settings.cache_clear()


def _create_job(
    ctx: dict[str, Any], strategy: str, *, use_selected_px4_parameter: bool = True
) -> str:
    schemas = ctx["schemas"]
    parameter_space = (
        [
            schemas.ParameterSelection(
                name="MPC_XY_P",
                baseline=0.95,
                minimum=0.6,
                maximum=1.3,
                step=0.1,
            )
        ]
        if use_selected_px4_parameter
        else []
    )
    request = schemas.JobCreateRequest(
        display_name=f"integration-{strategy}",
        simulator_backend="mock",
        optimizer_strategy=strategy,
        parameter_space=parameter_space,
        max_iterations=2,
        trials_per_candidate=1,
        max_total_trials=17,
        # These deliberately impossible mock thresholds force generation two,
        # which is important for final full-fidelity verification.
        acceptance_criteria=schemas.AcceptanceCriteria(
            target_rmse=1e-12,
            target_max_error=1e-12,
            min_pass_rate=1.0,
        ),
    )
    with ctx["db"].SessionLocal() as db:
        job = ctx["jobs"].create_job(db, request)
        return str(job.id)


def _drive_to_terminal(ctx: dict[str, Any], job_id: str, *, max_ticks: int = 240) -> str:
    for _ in range(max_ticks):
        ctx["runner"].tick("experimental-integration-worker")
        with ctx["db"].SessionLocal() as db:
            job = db.get(ctx["models"].Job, job_id)
            assert job is not None
            if job.status in {"COMPLETED", "FAILED", "CANCELLED"}:
                return str(job.status)
    raise AssertionError(f"job {job_id} did not become terminal after {max_ticks} ticks")


def test_source_evidence_schema_upgrade_preserves_numerical_seed_projection() -> None:
    from app.orchestration.experimental_optimizer import (
        _optimizer_seed_metadata,
    )

    legacy = {
        "strategy": "optimizer_portfolio",
        "child_strategy": "multi_fidelity_mobo",
        "optimizer_generated_by": "multi_fidelity_mobo",
        "portfolio_sources_schema": "dronedream.portfolio-sources/v1",
        "portfolio_sources": [
            {
                "child_strategy": "multi_fidelity_mobo",
                "generated_by": "multi_fidelity_mobo",
                "planned_slot_role": "exploration",
                "effective_fidelity": 1.0,
                "requested_fidelity": 0.25,
                "materialized": True,
                "reward_eligible": True,
                "exclusion_reason": None,
            }
        ],
    }
    modern = {
        **legacy,
        "harness_orchestration": {
            "schema_id": "dronedream.harness-candidate-orchestration/v1",
            "decision_id": "a" * 32,
            "revision_id": "b" * 32,
            "call_id": "call_" + "c" * 24,
            "tool_elapsed_ms": 12.5,
            "tool_cpu_ms": 7.25,
        },
        "optimizer_source_role": "native_optimizer",
        "optimizer_source_evidence_required": True,
        "optimizer_source_evidence": {
            "schema_id": "dronedream.optimizer-source-evidence/v2",
            "evidence_id": "sha256:" + "a" * 64,
        },
        "portfolio_sources_schema": "dronedream.portfolio-sources/v2",
        "portfolio_sources": [
            {
                **legacy["portfolio_sources"][0],
                "source_role": "native_optimizer",
            }
        ],
    }

    assert _optimizer_seed_metadata(modern) == legacy


@pytest.mark.parametrize(
    ("field_name", "invalid_value"),
    (
        ("score", -0.1),
        ("crash_flag", True),
        ("timeout_flag", True),
        ("instability_flag", True),
    ),
)
def test_experimental_history_rejects_invalid_or_contradictory_trial_metric(
    field_name: str,
    invalid_value: float | bool,
) -> None:
    from app.orchestration.experimental_optimizer import (
        _authoritative_training_outcome_counts,
    )

    metric: dict[str, float | int | bool] = {
        "rmse": 0.5,
        "max_error": 0.75,
        "completion_time": 8.0,
        "score": 0.5,
        "final_error": 0.1,
        "overshoot_count": 0,
        "crash_flag": False,
        "timeout_flag": False,
        "pass_flag": True,
        "instability_flag": False,
    }
    metric[field_name] = invalid_value

    counts = _authoritative_training_outcome_counts(
        trial_evidence_rows=(
            {
                "status": "COMPLETED",
                "failure_code": None,
                "metric": metric,
            },
        ),
        aggregate={},
    )

    assert counts is not None
    assert counts["success"] == 0
    assert counts["invalid_evidence"] == 1


@pytest.mark.parametrize("strategy", STRATEGIES)
def test_experimental_strategy_dispatches_candidates_with_budgeted_metadata(
    experimental_ctx: dict[str, Any], strategy: str
) -> None:
    ctx = experimental_ctx
    job_id = _create_job(ctx, strategy)
    from app.optimization.candidate_evidence_ledger import (
        CandidateEvidenceReceiptV1,
        CandidateEvidenceReceiptV2,
        _sha256_id,
        candidate_evidence_chain_matches_current,
        candidate_optimizer_metadata_receipt_matches_current,
        current_candidate_evidence_receipt,
        verify_candidate_evidence_receipt,
    )
    from app.optimization.outcome_evidence import (
        CandidateOutcomeEvidenceV3,
        CandidateReportEvidenceV3,
        candidate_report_trial_evidence_rows,
        candidate_training_trial_evidence_rows,
        verify_candidate_outcome_evidence,
        verify_candidate_report_evidence,
    )
    from app.optimization.proposal_provenance import (
        OPTIMIZER_SOURCE_EVIDENCE_FIELD,
        OPTIMIZER_SOURCE_EVIDENCE_REQUIRED_FIELD,
        optimizer_search_space_sha256,
        verify_optimizer_source_evidence,
    )
    from app.optimization.winner_evidence import (
        verify_winner_selection_evidence,
    )
    from app.orchestration.experimental_optimizer import (
        search_space_for_job,
    )
    from app.orchestration.parameter_constraints import validator_contract_for_job

    assert _drive_to_terminal(ctx, job_id) == "COMPLETED"

    models = ctx["models"]
    with ctx["db"].SessionLocal() as db:
        job = db.get(models.Job, job_id)
        assert job is not None
        assert isinstance(job.objective_config_json, dict)
        assert isinstance(job.scenario_suite_json, dict)
        candidates = list(job.candidates)
        trials = list(job.trials)
        optimizer_candidates = [
            candidate
            for candidate in candidates
            if candidate.source_type == "optimizer" and not candidate.is_baseline
        ]
        search_space = search_space_for_job(
            job,
            baseline_parameters=dict(job.baseline_parameter_json or {}),
        )
        search_space_sha256 = optimizer_search_space_sha256(
            search_space,
            validator_contract=validator_contract_for_job(job),
        )

        assert any(candidate.is_baseline for candidate in candidates)
        assert optimizer_candidates, "the optimizer must dispatch at least one real candidate"
        assert all(candidate.generation_index >= 1 for candidate in optimizer_candidates)
        assert len(trials) == job.progress_total_trials
        assert len(trials) <= job.max_total_trials == 17

        for candidate in optimizer_candidates:
            metadata = candidate.optimizer_metadata_json
            assert isinstance(metadata, dict)
            assert metadata["strategy"] == strategy
            assert metadata["generation_index"] == candidate.generation_index
            assert metadata[OPTIMIZER_SOURCE_EVIDENCE_REQUIRED_FIELD] is True
            assert (
                verify_optimizer_source_evidence(
                    metadata[OPTIMIZER_SOURCE_EVIDENCE_FIELD],
                    strategy=strategy,  # type: ignore[arg-type]
                    generation_index=candidate.generation_index,
                    parameters={"MPC_XY_P": float(candidate.parameter_json["MPC_XY_P"])},
                    search_space_sha256=search_space_sha256,
                    requested_fidelity=float(
                        metadata.get(
                            "requested_fidelity",
                            metadata["fidelity"],
                        )
                    ),
                    effective_fidelity=float(
                        metadata.get(
                            "effective_fidelity",
                            metadata["fidelity"],
                        )
                    ),
                )
                is not None
            )
            assert isinstance(metadata["random_seed"], str)
            assert len(metadata["random_seed"]) == 16
            assert int(metadata["random_seed"], 16) >= 0
            fidelity = float(metadata["fidelity"])
            assert 0.05 <= fidelity <= 1.0

            candidate_trials = list(
                db.scalars(select(models.Trial).where(models.Trial.candidate_id == candidate.id))
            )
            assert candidate_trials, "persisted candidates must own executable trials"
            assert all(
                float(trial.scenario_config_json["optimizer_fidelity"]) == pytest.approx(fidelity)
                for trial in candidate_trials
            )
            trial_summary = ctx["jobs"].to_trial_summary(candidate_trials[0])
            trial_detail = ctx["jobs"].to_trial_schema(candidate_trials[0])
            for field_name in ctx["schemas"].TrialSummary.model_fields:
                assert getattr(trial_detail, field_name) == getattr(trial_summary, field_name)

            if strategy in {"surrogate_cma_es", "bipop_cma_es"}:
                assert metadata["child_strategy"] == strategy
            elif strategy == "optimizer_portfolio":
                assert metadata["child_strategy"] in CHILD_STRATEGIES
                for seed_key in ("portfolio_random_seed", "child_random_seed"):
                    seed_value = metadata[seed_key]
                    assert isinstance(seed_value, str)
                    assert len(seed_value) == 16
                    int(seed_value, 16)
                assert trial_summary.candidate_optimizer_strategy == metadata["child_strategy"]

        generation_events = [
            event for event in job.events if event.event_type == "generation_dispatched"
        ]
        assert generation_events
        assert all(event.payload_json["strategy"] == strategy for event in generation_events)
        assert job.report is not None
        assert job.winner_freeze is not None
        winner_evidence = verify_winner_selection_evidence(job.report.winner_evidence_json)
        assert winner_evidence is not None
        assert winner_evidence.winner_candidate_id == job.best_candidate_id
        assert winner_evidence.baseline_candidate_id == job.baseline_candidate_id
        assert winner_evidence.candidate_count == len(candidates)
        assert job.winner_freeze.evidence_id == winner_evidence.evidence_id
        assert job.report.winner_freeze_receipt_id == job.winner_freeze.id
        assert {decision.candidate_id for decision in winner_evidence.candidates} == {
            candidate.id for candidate in candidates
        }
        selected_event = next(
            event for event in job.events if event.event_type == "best_candidate_selected"
        )
        assert selected_event.payload_json["winner_evidence_id"] == winner_evidence.evidence_id
        assert selected_event.payload_json["winner_freeze_receipt_id"] == job.winner_freeze.id

        history = ctx["jobs"].optimization_history(job)
        history_by_id = {item.id: item for item in history.items}
        for candidate in candidates:
            aggregate = candidate.aggregated_metric_json or {}
            if "objective_values" in aggregate:
                assert history_by_id[candidate.id].objective_values == aggregate["objective_values"]
                evidence = verify_candidate_outcome_evidence(
                    aggregate.get("candidate_outcome_evidence")
                )
                assert evidence is not None
                assert isinstance(evidence, CandidateOutcomeEvidenceV3)
                assert evidence.candidate_id == candidate.id
                assert evidence.outcome_contract_id == aggregate["outcome_contract_id"]
                assert evidence.accepted_attempt_count == evidence.trial_count
                assert (
                    evidence.trial_attempt_evidence_schema
                    == "dronedream.trial-accepted-attempt-evidence/v1"
                )
                report_evidence = verify_candidate_report_evidence(
                    aggregate.get("candidate_report_evidence")
                )
                assert report_evidence is not None
                assert isinstance(report_evidence, CandidateReportEvidenceV3)
                assert report_evidence.candidate_outcome_evidence_id == evidence.evidence_id
                assert report_evidence.accepted_attempt_count == len(candidate.trials)
                training_rows = candidate_training_trial_evidence_rows(
                    candidate,
                    verify_artifact_bytes=True,
                )
                report_rows = candidate_report_trial_evidence_rows(
                    candidate,
                    verify_artifact_bytes=True,
                )
                assert training_rows is not None
                assert report_rows is not None
                assert len(training_rows) == evidence.trial_count
                assert len(report_rows) == len(candidate.trials)
                assert all(
                    row["evidence_schema"] == "dronedream.trial-outcome-evidence/v3"
                    and "accepted_attempt_evidence" in row
                    for row in report_rows
                )
                receipt = current_candidate_evidence_receipt(candidate)
                assert isinstance(receipt, CandidateEvidenceReceiptV2)
                assert receipt.candidate_id == candidate.id
                assert receipt.outcome_evidence_id == evidence.evidence_id
                assert receipt.report_evidence_id == report_evidence.evidence_id
                assert candidate_evidence_chain_matches_current(candidate)
                assert candidate_optimizer_metadata_receipt_matches_current(candidate)
                if strategy == "constrained_mobo":
                    legacy_payload = receipt.model_dump(mode="json")
                    legacy_payload.pop("evidence_id")
                    legacy_payload.pop("optimizer_metadata_sha256")
                    legacy_payload.pop("source_type")
                    legacy_payload.pop("optimizer_source_evidence_required")
                    legacy_payload["schema_id"] = "dronedream.candidate-evidence-receipt/v1"
                    legacy_payload["evidence_id"] = _sha256_id(legacy_payload)
                    assert isinstance(
                        verify_candidate_evidence_receipt(legacy_payload),
                        CandidateEvidenceReceiptV1,
                    )
                    current_row = candidate.evidence_receipts[-1]
                    legacy_row = SimpleNamespace(
                        id=current_row.id,
                        candidate_id=current_row.candidate_id,
                        job_id=current_row.job_id,
                        receipt_schema=legacy_payload["schema_id"],
                        evidence_id=legacy_payload["evidence_id"],
                        revision=current_row.revision,
                        previous_evidence_id=current_row.previous_evidence_id,
                        aggregate_sha256=legacy_payload["aggregate_sha256"],
                        outcome_evidence_id=current_row.outcome_evidence_id,
                        report_evidence_id=current_row.report_evidence_id,
                        outcome_evidence_json=current_row.outcome_evidence_json,
                        report_evidence_json=current_row.report_evidence_json,
                        evidence_json=legacy_payload,
                    )
                    legacy_optimizer_candidate = SimpleNamespace(
                        id=candidate.id,
                        job_id=candidate.job_id,
                        generation_index=candidate.generation_index,
                        parameter_json=candidate.parameter_json,
                        optimizer_metadata_json=candidate.optimizer_metadata_json,
                        aggregated_metric_json=candidate.aggregated_metric_json,
                        evidence_receipts=[legacy_row],
                        evidence_ledger_required=True,
                        source_type="optimizer",
                    )
                    assert not candidate_evidence_chain_matches_current(legacy_optimizer_candidate)

        if strategy == "multi_fidelity_mobo":
            earlier_candidates = [
                candidate
                for candidate in optimizer_candidates
                if candidate.generation_index < job.max_iterations
            ]
            assert any(
                float(candidate.optimizer_metadata_json["requested_fidelity"]) < 1.0
                for candidate in earlier_candidates
            ), "multi-fidelity search must exercise a screening request before verification"
            assert all(
                float(candidate.optimizer_metadata_json["effective_fidelity"])
                >= float(candidate.optimizer_metadata_json["requested_fidelity"])
                for candidate in earlier_candidates
            )
            final_candidates = [
                candidate
                for candidate in optimizer_candidates
                if candidate.generation_index == job.max_iterations
            ]
            assert final_candidates, "the final verification generation must be dispatched"
            assert all(
                float(candidate.optimizer_metadata_json["requested_fidelity"]) == pytest.approx(1.0)
                and float(candidate.optimizer_metadata_json["effective_fidelity"])
                == pytest.approx(1.0)
                for candidate in final_candidates
            )
            assert all(
                candidate.optimizer_metadata_json["forced_full_fidelity_verification"] is True
                for candidate in final_candidates
            )
            reduced_candidates = [
                candidate
                for candidate in earlier_candidates
                if float(candidate.optimizer_metadata_json["requested_fidelity"]) < 1.0
            ]
            assert reduced_candidates
            assert all(candidate.rank_in_job is None for candidate in reduced_candidates)
            assert all(not candidate.is_best for candidate in reduced_candidates)
            excluded_ids = {candidate.id for candidate in reduced_candidates}
            assert excluded_ids.isdisjoint(history.pareto_candidate_ids)
            assert excluded_ids.isdisjoint(history.recommendations.values())


def test_candidate_evidence_ledger_blocks_legacy_fallback_and_allows_job_delete(
    experimental_ctx: dict[str, Any],
) -> None:
    ctx = experimental_ctx
    job_id = _create_job(ctx, "constrained_mobo")
    assert _drive_to_terminal(ctx, job_id) == "COMPLETED"

    from app.optimization.candidate_evidence_ledger import (
        candidate_evidence_chain_matches_current,
        candidate_evidence_receipt_required,
    )
    from app.optimization.outcome_evidence import (
        CandidateReportEvidenceError,
        require_authoritative_candidate_report_projection,
    )
    from app.orchestration.aggregation import candidate_is_publishable

    models = ctx["models"]
    with ctx["db"].SessionLocal() as db:
        job = db.get(models.Job, job_id)
        assert job is not None
        candidate = next(
            item
            for item in job.candidates
            if item.aggregated_metric_json and item.evidence_receipts
        )
        assert candidate_evidence_receipt_required(candidate)
        assert candidate_evidence_chain_matches_current(candidate)
        assert candidate_is_publishable(candidate)
        aggregate = dict(candidate.aggregated_metric_json or {})
        aggregate.pop("candidate_outcome_evidence", None)
        aggregate.pop("candidate_outcome_evidence_required", None)
        aggregate.pop("candidate_report_evidence", None)
        aggregate.pop("candidate_report_evidence_required", None)
        candidate.aggregated_metric_json = aggregate
        db.commit()
        candidate_id = candidate.id
        receipt_id = candidate.evidence_receipts[-1].id

    with ctx["db"].SessionLocal() as db:
        candidate = db.get(models.CandidateParameterSet, candidate_id)
        assert candidate is not None
        assert candidate.evidence_ledger_required is True
        assert candidate_evidence_receipt_required(candidate)
        assert not candidate_evidence_chain_matches_current(candidate)
        assert not candidate_is_publishable(candidate)
        with pytest.raises(
            CandidateReportEvidenceError,
            match="relational Candidate evidence",
        ):
            require_authoritative_candidate_report_projection(candidate)

        with pytest.raises(DatabaseError):
            db.execute(
                update(models.CandidateEvidenceReceipt)
                .where(models.CandidateEvidenceReceipt.id == receipt_id)
                .values(aggregate_sha256="sha256:" + "0" * 64)
            )
            db.commit()
        db.rollback()

        with pytest.raises(DatabaseError):
            db.execute(
                update(models.CandidateParameterSet)
                .where(models.CandidateParameterSet.id == candidate_id)
                .values(evidence_ledger_required=False)
            )
            db.commit()
        db.rollback()

        assert ctx["jobs"].delete_job(db, job_id) == {
            "id": job_id,
            "deleted": True,
        }

    with ctx["db"].SessionLocal() as db:
        assert db.get(models.CandidateEvidenceReceipt, receipt_id) is None


def test_candidate_metadata_tamper_quarantines_optimizer_history_and_publication(
    experimental_ctx: dict[str, Any],
) -> None:
    ctx = experimental_ctx
    job_id = _create_job(ctx, "turbo")
    assert _drive_to_terminal(ctx, job_id) == "COMPLETED"

    from app.optimization.candidate_evidence_ledger import (
        CandidateEvidenceLedgerError,
        candidate_evidence_chain_matches_current,
        candidate_optimizer_metadata_receipt_matches_current,
        record_candidate_evidence_receipt,
    )
    from app.orchestration.aggregation import candidate_is_publishable
    from app.orchestration.experimental_optimizer import (
        observations_for_job,
        search_space_for_job,
    )

    models = ctx["models"]
    with ctx["db"].SessionLocal() as db:
        job = db.get(models.Job, job_id)
        assert job is not None
        candidate = next(
            item
            for item in job.candidates
            if item.source_type == "optimizer"
            and item.aggregated_metric_json
            and item.evidence_receipts
        )
        candidate_id = candidate.id
        assert candidate_evidence_chain_matches_current(candidate)
        assert candidate_optimizer_metadata_receipt_matches_current(candidate)
        assert candidate_is_publishable(candidate)

        tampered_metadata = dict(candidate.optimizer_metadata_json)
        tampered_metadata["portfolio_reward_eligible"] = not bool(
            tampered_metadata.get("portfolio_reward_eligible", False)
        )
        candidate.optimizer_metadata_json = tampered_metadata
        with pytest.raises(
            DatabaseError,
            match="Candidate provenance is immutable after evidence sealing",
        ):
            db.commit()
        db.rollback()

    with ctx["db"].SessionLocal() as db:
        job = db.get(models.Job, job_id)
        candidate = db.get(models.CandidateParameterSet, candidate_id)
        assert job is not None
        assert candidate is not None
        candidate.optimizer_metadata_json = tampered_metadata
        assert not candidate_evidence_chain_matches_current(candidate)
        assert not candidate_optimizer_metadata_receipt_matches_current(candidate)
        assert not candidate_is_publishable(candidate)
        with pytest.raises(
            CandidateEvidenceLedgerError,
            match="source identity or optimizer metadata diverged",
        ):
            record_candidate_evidence_receipt(
                candidate=candidate,
                aggregate=dict(candidate.aggregated_metric_json or {}),
            )
        search_space = search_space_for_job(
            job,
            baseline_parameters={"MPC_XY_P": 0.95},
        )
        assert (
            observations_for_job(
                job,
                search_space=search_space,
                candidates=[candidate],
            )
            == ()
        )


def test_candidate_source_type_downgrade_cannot_wash_optimizer_metadata(
    experimental_ctx: dict[str, Any],
) -> None:
    ctx = experimental_ctx
    job_id = _create_job(ctx, "turbo")
    assert _drive_to_terminal(ctx, job_id) == "COMPLETED"

    from app.optimization.candidate_evidence_ledger import (
        CandidateEvidenceLedgerError,
        candidate_evidence_chain_matches_current,
        record_candidate_evidence_receipt,
    )

    models = ctx["models"]
    with ctx["db"].SessionLocal() as db:
        job = db.get(models.Job, job_id)
        assert job is not None
        candidate = next(
            item
            for item in job.candidates
            if item.source_type == "optimizer"
            and item.aggregated_metric_json
            and item.evidence_receipts
        )
        candidate_id = candidate.id
        downgraded_metadata = dict(candidate.optimizer_metadata_json or {})
        downgraded_metadata.pop("optimizer_source_evidence_required", None)
        downgraded_metadata.pop("optimizer_source_evidence", None)
        with pytest.raises(
            DatabaseError,
            match="Candidate provenance is immutable after evidence sealing",
        ):
            db.execute(
                update(models.CandidateParameterSet)
                .where(models.CandidateParameterSet.id == candidate_id)
                .values(
                    source_type="baseline",
                    optimizer_metadata_json=downgraded_metadata,
                )
            )
            db.commit()
        db.rollback()

    with ctx["db"].SessionLocal() as db:
        candidate = db.get(models.CandidateParameterSet, candidate_id)
        assert candidate is not None
        candidate.source_type = "baseline"
        candidate.optimizer_metadata_json = downgraded_metadata
        assert not candidate_evidence_chain_matches_current(candidate)
        with pytest.raises(
            CandidateEvidenceLedgerError,
            match="source identity or optimizer metadata diverged",
        ):
            record_candidate_evidence_receipt(
                candidate=candidate,
                aggregate=dict(candidate.aggregated_metric_json or {}),
            )
        candidate.source_type = "optimizer"
        assert not candidate_evidence_chain_matches_current(candidate)


def test_real_orm_v1_optimizer_receipt_fails_closed_everywhere(
    experimental_ctx: dict[str, Any],
) -> None:
    ctx = experimental_ctx
    job_id = _create_job(ctx, "turbo")
    assert _drive_to_terminal(ctx, job_id) == "COMPLETED"

    from app.optimization.candidate_evidence_ledger import (
        CandidateEvidenceLedgerError,
        _sha256_id,
        candidate_evidence_chain_matches_current,
        current_candidate_evidence_receipt,
        record_candidate_evidence_receipt,
    )
    from app.orchestration.aggregation import candidate_is_publishable
    from app.orchestration.experimental_optimizer import (
        observations_for_job,
        search_space_for_job,
    )

    models = ctx["models"]
    with ctx["db"].SessionLocal() as db:
        job = db.get(models.Job, job_id)
        assert job is not None
        candidate = next(
            item
            for item in job.candidates
            if item.source_type == "optimizer"
            and item.aggregated_metric_json
            and item.evidence_receipts
        )
        current = current_candidate_evidence_receipt(candidate)
        assert current is not None
        current_row = candidate.evidence_receipts[-1]
        legacy_payload = current.model_dump(mode="json")
        legacy_payload.pop("evidence_id")
        legacy_payload.pop("optimizer_metadata_sha256")
        legacy_payload.pop("source_type")
        legacy_payload.pop("optimizer_source_evidence_required")
        legacy_payload.update(
            {
                "schema_id": "dronedream.candidate-evidence-receipt/v1",
                "revision": current.revision + 1,
                "previous_evidence_id": current.evidence_id,
            }
        )
        legacy_payload["evidence_id"] = _sha256_id(legacy_payload)
        candidate.evidence_receipts.append(
            models.CandidateEvidenceReceipt(
                id="cer_legacy_optimizer_v1",
                candidate_id=candidate.id,
                job_id=candidate.job_id,
                revision=legacy_payload["revision"],
                previous_evidence_id=legacy_payload["previous_evidence_id"],
                receipt_schema=legacy_payload["schema_id"],
                evidence_id=legacy_payload["evidence_id"],
                aggregate_sha256=legacy_payload["aggregate_sha256"],
                outcome_evidence_id=legacy_payload["outcome_evidence_id"],
                report_evidence_id=legacy_payload["report_evidence_id"],
                outcome_evidence_json=dict(current_row.outcome_evidence_json),
                report_evidence_json=dict(current_row.report_evidence_json),
                evidence_json=legacy_payload,
            )
        )
        db.flush()

        assert not candidate_evidence_chain_matches_current(candidate)
        assert not candidate_is_publishable(candidate)
        search_space = search_space_for_job(
            job,
            baseline_parameters={"MPC_XY_P": 0.95},
        )
        assert (
            observations_for_job(
                job,
                search_space=search_space,
                candidates=[candidate],
            )
            == ()
        )
        with pytest.raises(
            CandidateEvidenceLedgerError,
            match="controlled v2 migration",
        ):
            record_candidate_evidence_receipt(
                candidate=candidate,
                aggregate=dict(candidate.aggregated_metric_json or {}),
            )


def test_search_space_contract_drift_quarantines_optimizer_history(
    experimental_ctx: dict[str, Any],
) -> None:
    ctx = experimental_ctx
    job_id = _create_job(ctx, "turbo")
    assert _drive_to_terminal(ctx, job_id) == "COMPLETED"

    from app.optimization.candidate_evidence_ledger import (
        candidate_evidence_chain_matches_current,
    )
    from app.orchestration.experimental_optimizer import (
        observations_for_job,
        search_space_for_job,
    )

    models = ctx["models"]
    with ctx["db"].SessionLocal() as db:
        job = db.get(models.Job, job_id)
        assert job is not None
        candidate = next(
            item
            for item in job.candidates
            if item.source_type == "optimizer"
            and item.aggregated_metric_json
            and item.evidence_receipts
        )
        candidate_id = candidate.id
        assert candidate_evidence_chain_matches_current(candidate)

        parameter_space = [dict(item) for item in (job.parameter_space_json or [])]
        assert parameter_space
        assert parameter_space[0]["maximum"] == pytest.approx(1.3)
        parameter_space[0]["maximum"] = 1.4
        job.parameter_space_json = parameter_space
        db.commit()

    with ctx["db"].SessionLocal() as db:
        job = db.get(models.Job, job_id)
        candidate = db.get(models.CandidateParameterSet, candidate_id)
        assert job is not None
        assert candidate is not None
        # The Candidate receipt remains an authentic record of the original
        # contract.  Reusing it under a different search space must still fail
        # closed at the optimizer-history boundary.
        assert candidate_evidence_chain_matches_current(candidate)
        changed_search_space = search_space_for_job(
            job,
            baseline_parameters={"MPC_XY_P": 0.95},
        )
        assert (
            observations_for_job(
                job,
                search_space=changed_search_space,
                candidates=[candidate],
            )
            == ()
        )


@pytest.mark.parametrize(
    ("context_field", "changed_value"),
    (
        ("parameter_catalog_version", "px4-catalog-drift"),
        ("px4_version", "v1.15"),
        ("vehicle_type", "fixedwing"),
        ("airframe", "plane"),
    ),
)
def test_validator_context_drift_quarantines_optimizer_history(
    experimental_ctx: dict[str, Any],
    context_field: str,
    changed_value: str,
) -> None:
    ctx = experimental_ctx
    job_id = _create_job(ctx, "turbo")
    assert _drive_to_terminal(ctx, job_id) == "COMPLETED"

    from app.optimization.candidate_evidence_ledger import (
        candidate_evidence_chain_matches_current,
    )
    from app.orchestration.experimental_optimizer import (
        observations_for_job,
        search_space_for_job,
    )

    models = ctx["models"]
    with ctx["db"].SessionLocal() as db:
        job = db.get(models.Job, job_id)
        assert job is not None
        candidate = next(
            item
            for item in job.candidates
            if item.source_type == "optimizer"
            and item.aggregated_metric_json
            and item.evidence_receipts
        )
        assert candidate_evidence_chain_matches_current(candidate)
        original_parameter_space = [dict(item) for item in (job.parameter_space_json or [])]
        if context_field == "parameter_catalog_version":
            job.parameter_catalog_version = changed_value
        else:
            profile = dict(job.vehicle_profile_json or {})
            profile[context_field] = changed_value
            job.vehicle_profile_json = profile
        assert [dict(item) for item in (job.parameter_space_json or [])] == (
            original_parameter_space
        )
        changed_search_space = search_space_for_job(
            job,
            baseline_parameters={"MPC_XY_P": 0.95},
        )
        assert (
            observations_for_job(
                job,
                search_space=changed_search_space,
                candidates=[candidate],
            )
            == ()
        )


def test_dispatched_trial_fidelity_drift_quarantines_pending_optimizer_history(
    experimental_ctx: dict[str, Any],
) -> None:
    ctx = experimental_ctx
    job_id = _create_job(ctx, "turbo")

    from app.orchestration.experimental_optimizer import (
        observations_for_job,
        search_space_for_job,
    )

    models = ctx["models"]
    candidate_id: str | None = None
    for _ in range(20):
        ctx["runner"].tick("fidelity-drift-worker")
        with ctx["db"].SessionLocal() as db:
            job = db.get(models.Job, job_id)
            assert job is not None
            pending = next(
                (
                    item
                    for item in job.candidates
                    if item.source_type == "optimizer"
                    and item.trials
                    and item.completed_trial_count + item.failed_trial_count < item.trial_count
                ),
                None,
            )
            if pending is not None:
                candidate_id = pending.id
                break
    assert candidate_id is not None

    with ctx["db"].SessionLocal() as db:
        job = db.get(models.Job, job_id)
        assert job is not None
        candidate = db.get(models.CandidateParameterSet, candidate_id)
        assert candidate is not None
        search_space = search_space_for_job(
            job,
            baseline_parameters={"MPC_XY_P": 0.95},
        )
        observations = observations_for_job(
            job,
            search_space=search_space,
            candidates=[candidate],
        )
        assert len(observations) == 1
        assert observations[0].role == "pending_reservation"

        trial = candidate.trials[0]
        scenario_config = dict(trial.scenario_config_json or {})
        effective_fidelity = float(scenario_config["optimizer_fidelity"])
        scenario_config["optimizer_fidelity"] = (
            0.5 if abs(effective_fidelity - 0.5) > 1e-12 else 0.75
        )
        trial.scenario_config_json = scenario_config
        db.flush()

        assert (
            observations_for_job(
                job,
                search_space=search_space,
                candidates=[candidate],
            )
            == ()
        )


def test_actual_trial_coverage_mismatch_is_not_hidden_by_consistent_labels(
    experimental_ctx: dict[str, Any],
) -> None:
    ctx = experimental_ctx
    job_id = _create_job(ctx, "turbo")

    from app.orchestration.experimental_optimizer import (
        observations_for_job,
        search_space_for_job,
    )

    models = ctx["models"]
    candidate_id: str | None = None
    for _ in range(20):
        ctx["runner"].tick("coverage-mismatch-worker")
        with ctx["db"].SessionLocal() as db:
            job = db.get(models.Job, job_id)
            assert job is not None
            pending = next(
                (
                    item
                    for item in job.candidates
                    if item.source_type == "optimizer"
                    and len(item.trials) >= 2
                    and item.completed_trial_count + item.failed_trial_count < item.trial_count
                ),
                None,
            )
            if pending is not None:
                candidate_id = pending.id
                break
    assert candidate_id is not None

    with ctx["db"].SessionLocal() as db:
        job = db.get(models.Job, job_id)
        candidate = db.get(models.CandidateParameterSet, candidate_id)
        assert job is not None
        assert candidate is not None
        search_space = search_space_for_job(
            job,
            baseline_parameters={"MPC_XY_P": 0.95},
        )
        observations = observations_for_job(
            job,
            search_space=search_space,
            candidates=[candidate],
        )
        assert len(observations) == 1
        assert observations[0].role == "pending_reservation"

        first, second = candidate.trials[:2]
        first.seed = second.seed
        first.scenario_type = second.scenario_type
        first.scenario_config_json = dict(second.scenario_config_json or {})
        # Every copied fidelity label is still internally consistent.  Only an
        # independent reconstruction of the configured case/seed subset can
        # detect that one run disappeared and another was duplicated.
        assert (
            observations_for_job(
                job,
                search_space=search_space,
                candidates=[candidate],
            )
            == ()
        )


def test_real_scenario_matrix_controls_iterative_budget_not_legacy_trial_count(
    experimental_ctx: dict[str, Any],
) -> None:
    """A one-run matrix must fit even when the legacy hint says ten trials."""

    ctx = experimental_ctx
    schemas = ctx["schemas"]
    request = schemas.JobCreateRequest(
        display_name="matrix-budget-regression",
        simulator_backend="mock",
        optimizer_strategy="turbo",
        parameter_space=[
            schemas.ParameterSelection(
                name="MPC_XY_P",
                baseline=0.95,
                minimum=0.6,
                maximum=1.3,
                step=0.1,
            )
        ],
        scenario_suite=schemas.ScenarioSuiteConfig(
            cases=[
                schemas.ScenarioCaseConfig(
                    id="single-run",
                    scenario_type="nominal",
                    seeds=[805],
                )
            ]
        ),
        max_iterations=1,
        trials_per_candidate=10,
        max_total_trials=2,
        acceptance_criteria=schemas.AcceptanceCriteria(target_rmse=1e-12),
    )
    with ctx["db"].SessionLocal() as db:
        job = ctx["jobs"].create_job(db, request)
        job_id = str(job.id)

    assert _drive_to_terminal(ctx, job_id) == "COMPLETED"
    with ctx["db"].SessionLocal() as db:
        job = db.get(ctx["models"].Job, job_id)
        assert job is not None
        assert job.progress_total_trials == 2
        assert len(job.trials) == 2
        assert any(not candidate.is_baseline for candidate in job.candidates)


def test_post_proposal_fidelity_resolver_cannot_mutate_a_sealed_envelope() -> None:
    from app.orchestration.job_manager import _resolve_proposal_fidelity
    from app.orchestration.optimizer import CandidateProposal

    proposal = CandidateProposal(
        generation_index=1,
        label="sealed-quarter-fidelity",
        strategy="multi-fidelity regression",
        parameters={"MPC_XY_P": 0.9},
        metadata={
            "strategy": "multi_fidelity_mobo",
            "requested_fidelity": 0.25,
            "effective_fidelity": 0.25,
            "fidelity": 0.25,
            "optimizer_source_evidence_required": True,
        },
    )

    with pytest.raises(
        RuntimeError,
        match="changed after source evidence sealing",
    ):
        _resolve_proposal_fidelity(
            proposal,
            ((0.25, 0.5), (0.5, 0.75), (1.0, 1.0)),
        )


def test_reduced_fidelity_covers_every_training_case_before_more_replicates(
    experimental_ctx: dict[str, Any],
) -> None:
    _ = experimental_ctx
    from app.optimization.scenarios import scenario_matrix
    from app.orchestration.job_manager import (
        _effective_fidelity_mapping,
        _low_fidelity_scenario_runs,
    )
    from app.schemas import ScenarioCaseConfig, ScenarioSuiteConfig

    suite = ScenarioSuiteConfig(
        cases=[
            ScenarioCaseConfig(
                id=f"training-{case_index}",
                scenario_type=("nominal" if case_index == 0 else "wind_perturbed"),
                seeds=[case_index * 10 + seed_index for seed_index in (1, 2, 3)],
            )
            for case_index in range(4)
        ]
        + [
            ScenarioCaseConfig(
                id="sealed-holdout",
                seeds=[901, 902],
                holdout=True,
            )
        ]
    )
    runs = scenario_matrix(suite)

    quarter = _low_fidelity_scenario_runs(runs, 0.25)
    half = _low_fidelity_scenario_runs(runs, 0.5)
    mapping = dict(
        _effective_fidelity_mapping(
            runs,
            full_trials_per_candidate=999,
        )
    )

    assert len(quarter) == 4
    assert {run.case_id for run in quarter} == {
        "training-0",
        "training-1",
        "training-2",
        "training-3",
    }
    assert all(not run.holdout for run in quarter)
    assert len(half) == 6
    assert {run.case_id for run in half} == {
        "training-0",
        "training-1",
        "training-2",
        "training-3",
    }
    assert set(mapping) == {0.25, 0.5, 1.0}
    assert mapping[0.25] == pytest.approx(4 / 12)
    assert mapping[0.5] == pytest.approx(6 / 12)
    assert mapping[1.0] == pytest.approx(1.0)


def test_experimental_dispatch_deduplicates_identical_proposals_within_batch(
    experimental_ctx: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    ctx = experimental_ctx
    schemas = ctx["schemas"]
    from app.orchestration import job_manager
    from app.orchestration.optimizer import CandidateProposal

    request = schemas.JobCreateRequest(
        display_name="batch-dedup-regression",
        simulator_backend="mock",
        optimizer_strategy="turbo",
        parameter_space=[
            schemas.ParameterSelection(
                name="MPC_XY_P",
                baseline=0.95,
                minimum=0.6,
                maximum=1.3,
                step=0.1,
            )
        ],
        scenario_suite=schemas.ScenarioSuiteConfig(
            cases=[
                schemas.ScenarioCaseConfig(
                    id="single-run",
                    scenario_type="nominal",
                    seeds=[805],
                )
            ]
        ),
        max_iterations=1,
        max_total_trials=4,
    )
    duplicate = CandidateProposal(
        generation_index=1,
        label="duplicate",
        strategy="turbo",
        parameters={"MPC_XY_P": 1.0},
        metadata={"strategy": "turbo", "fidelity": 1.0},
    )
    monkeypatch.setattr(
        job_manager,
        "propose_experimental_generation",
        lambda **_kwargs: [duplicate, duplicate],
    )

    with ctx["db"].SessionLocal() as db:
        job = ctx["jobs"].create_job(db, request)
        job_manager.start_job(db, job)
        result = job_manager.dispatch_next_experimental_generation(db, job)
        db.flush()

        assert result.status == "dispatched"
        assert result.dispatched_candidates == 1
        optimizer_candidates = [
            candidate for candidate in job.candidates if not candidate.is_baseline
        ]
        # The relationship may have been loaded before inserts; query the DB to
        # assert the persisted batch rather than relying on identity-map refresh.
        persisted = list(
            db.scalars(
                select(ctx["models"].CandidateParameterSet).where(
                    ctx["models"].CandidateParameterSet.job_id == job.id,
                    ctx["models"].CandidateParameterSet.is_baseline.is_(False),
                )
            )
        )
        assert len(persisted) == 1
        assert len(optimizer_candidates) <= 1
        assert any(
            event.event_type == "optimizer_candidate_skipped"
            and event.payload_json.get("reason") == "duplicate_in_generation"
            for event in job.events
        )


def test_direct_experimental_dispatch_rejects_outcome_contract_drift_before_writes(
    experimental_ctx: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    ctx = experimental_ctx
    schemas = ctx["schemas"]
    from app.orchestration import job_manager
    from app.orchestration.outcome_contract_guard import OutcomeContractDriftError

    request = schemas.JobCreateRequest(
        display_name="direct-dispatch-contract-guard",
        simulator_backend="mock",
        optimizer_strategy="turbo",
        parameter_space=[
            schemas.ParameterSelection(
                name="MPC_XY_P",
                baseline=0.95,
                minimum=0.6,
                maximum=1.3,
                step=0.1,
            )
        ],
        max_iterations=2,
        trials_per_candidate=1,
        max_total_trials=8,
    )

    with ctx["db"].SessionLocal() as db:
        job = ctx["jobs"].create_job(db, request)
        job_manager.start_job(db, job)
        db.flush()
        candidate_count = len(
            list(
                db.scalars(
                    select(ctx["models"].CandidateParameterSet).where(
                        ctx["models"].CandidateParameterSet.job_id == job.id
                    )
                )
            )
        )
        trial_count = len(
            list(
                db.scalars(
                    select(ctx["models"].Trial).where(
                        ctx["models"].Trial.job_id == job.id
                    )
                )
            )
        )
        job.min_pass_rate = 0.731
        monkeypatch.setattr(
            job_manager,
            "propose_experimental_generation",
            lambda **_kwargs: pytest.fail(
                "proposal generation ran after outcome-contract drift"
            ),
        )

        with pytest.raises(OutcomeContractDriftError, match="no longer matches"):
            job_manager.dispatch_next_experimental_generation(db, job)

        assert (
            len(
                list(
                    db.scalars(
                        select(ctx["models"].CandidateParameterSet).where(
                            ctx["models"].CandidateParameterSet.job_id == job.id
                        )
                    )
                )
            )
            == candidate_count
        )
        assert (
            len(
                list(
                    db.scalars(
                        select(ctx["models"].Trial).where(
                            ctx["models"].Trial.job_id == job.id
                        )
                    )
                )
            )
            == trial_count
        )


def test_full_fidelity_infrastructure_failure_allows_exactly_one_retry(
    experimental_ctx: dict[str, Any],
) -> None:
    ctx = experimental_ctx
    from app.orchestration.job_manager import _is_duplicate_proposal
    from app.simulator.base import FAILURE_ADAPTER_UNAVAILABLE, FAILURE_SIM_ERROR

    with ctx["db"].SessionLocal() as db:
        job_id = _create_job(ctx, "turbo")
        job = db.get(ctx["models"].Job, job_id)
        assert job is not None
        first = ctx["models"].CandidateParameterSet(
            job_id=job.id,
            generation_index=1,
            source_type="optimizer",
            label="failed-full",
            parameter_json={"MPC_XY_P": 1.0},
            optimizer_metadata_json={"strategy": "turbo", "fidelity": 1.0},
            trial_count=1,
            completed_trial_count=0,
            failed_trial_count=1,
        )
        first.trials.append(
            ctx["models"].Trial(
                job_id=job.id,
                seed=805,
                scenario_type="nominal",
                status="FAILED",
                failure_code=FAILURE_ADAPTER_UNAVAILABLE,
            )
        )
        job.candidates.append(first)
        db.flush()

        metadata = {"strategy": "turbo", "fidelity": 1.0}
        assert not _is_duplicate_proposal(job, {"MPC_XY_P": 1.0}, optimizer_metadata=metadata)

        first.trials[0].failure_code = FAILURE_SIM_ERROR
        assert _is_duplicate_proposal(job, {"MPC_XY_P": 1.0}, optimizer_metadata=metadata)
        first.trials[0].failure_code = FAILURE_ADAPTER_UNAVAILABLE

        retry = ctx["models"].CandidateParameterSet(
            job_id=job.id,
            generation_index=2,
            source_type="optimizer",
            label="one-retry-used",
            parameter_json={"MPC_XY_P": 1.0},
            optimizer_metadata_json=metadata,
        )
        job.candidates.append(retry)
        assert _is_duplicate_proposal(job, {"MPC_XY_P": 1.0}, optimizer_metadata=metadata)


def test_pending_candidate_is_visible_but_excluded_from_bayesian_training(
    experimental_ctx: dict[str, Any],
) -> None:
    """Persisted in-flight points reserve space without becoming fake failures."""

    ctx = experimental_ctx
    job_id = _create_job(ctx, "turbo")
    from app.orchestration.experimental_optimizer import (
        observations_for_job,
        propose_experimental_generation,
        search_space_for_job,
    )

    with ctx["db"].SessionLocal() as db:
        job = db.get(ctx["models"].Job, job_id)
        assert job is not None
        for index, (parameter, loss) in enumerate(
            ((0.7, 0.5), (0.9, 0.4), (1.1, 0.3)),
            start=1,
        ):
            job.candidates.append(
                ctx["models"].CandidateParameterSet(
                    job_id=job.id,
                    generation_index=index,
                    source_type="optimizer",
                    label=f"completed-{index}",
                    parameter_json={"MPC_XY_P": parameter},
                    aggregated_score=loss,
                    aggregated_metric_json={
                        "objective_values": {"rmse": loss},
                        "constraint_violations": {},
                        "scalar_loss": loss,
                        "feasible": True,
                    },
                    optimizer_metadata_json={"strategy": "turbo", "fidelity": 1.0},
                    trial_count=1,
                    completed_trial_count=1,
                    failed_trial_count=0,
                )
            )
        pending = ctx["models"].CandidateParameterSet(
            job_id=job.id,
            generation_index=4,
            source_type="optimizer",
            label="pending-point",
            parameter_json={"MPC_XY_P": 1.2},
            optimizer_metadata_json={"strategy": "turbo", "fidelity": 1.0},
            trial_count=1,
            completed_trial_count=0,
            failed_trial_count=0,
        )
        pending.trials.append(
            ctx["models"].Trial(
                job_id=job.id,
                seed=805,
                scenario_type="nominal",
                status="PENDING",
            )
        )
        job.candidates.append(pending)
        db.flush()

        search_space = search_space_for_job(
            job,
            baseline_parameters={"MPC_XY_P": 0.95},
        )
        observations = observations_for_job(
            job,
            search_space=search_space,
            candidates=list(job.candidates),
        )
        pending_observation = next(item for item in observations if item.candidate_id == pending.id)

        assert pending_observation.completed is False
        assert pending_observation.role == "pending_reservation"
        assert pending_observation.loss is None
        assert pending_observation.failure_rate == pytest.approx(0.0)
        assert pending_observation.objectives == {}
        assert pending_observation.constraints == {}

        proposals = propose_experimental_generation(
            job=job,
            candidates=list(job.candidates),
            baseline_parameters={"MPC_XY_P": 0.95},
            generation_index=5,
            batch_size=1,
        )
        assert proposals
        diagnostics = proposals[0].metadata["gp_training_set"]
        assert diagnostics["feasibility"] == {"source": 3, "active": 3}
        assert diagnostics["metrics"]["__loss__"] == {"source": 3, "active": 3}
        assert "rmse" not in diagnostics["metrics"]
        assert proposals[0].metadata["acquisition_representation"] == "scalar_loss"
        assert proposals[0].metadata["uses_scalar_loss"] is True
        assert proposals[0].parameters != pending.parameter_json


def test_optimizer_history_rejects_candidate_missing_a_selected_parameter(
    experimental_ctx: dict[str, Any],
) -> None:
    ctx = experimental_ctx
    job_id = _create_job(ctx, "turbo")
    from app.orchestration.experimental_optimizer import (
        observations_for_job,
        search_space_for_job,
    )

    with ctx["db"].SessionLocal() as db:
        job = db.get(ctx["models"].Job, job_id)
        assert job is not None
        incomplete = ctx["models"].CandidateParameterSet(
            job_id=job.id,
            generation_index=1,
            source_type="optimizer",
            label="incomplete-history",
            # This invariant controller value is valid extra context, but the
            # selected MPC_XY_P coordinate is absent and must not be invented
            # from the current baseline by the history adapter.
            parameter_json={"MC_PITCHRATE_P": 0.15},
            aggregated_score=0.2,
            aggregated_metric_json={
                "objective_values": {"rmse": 0.2},
                "constraint_violations": {},
                "scalar_loss": 0.2,
                "feasible": True,
            },
            optimizer_metadata_json={"strategy": "turbo", "fidelity": 1.0},
            trial_count=1,
            completed_trial_count=1,
            failed_trial_count=0,
        )
        search_space = search_space_for_job(
            job,
            baseline_parameters={"MPC_XY_P": 0.95},
        )

        assert (
            observations_for_job(
                job,
                search_space=search_space,
                candidates=[incomplete],
            )
            == ()
        )


def test_job_objective_preferences_reach_bayesian_vector_acquisition(
    experimental_ctx: dict[str, Any],
) -> None:
    ctx = experimental_ctx
    job_id = _create_job(ctx, "constrained_mobo")
    from app.orchestration.experimental_optimizer import (
        propose_experimental_generation,
    )

    with ctx["db"].SessionLocal() as db:
        job = db.get(ctx["models"].Job, job_id)
        assert job is not None
        for index, (parameter, rmse) in enumerate(
            ((0.6, 0.8), (0.8, 0.5), (1.0, 0.3), (1.2, 0.6)),
            start=1,
        ):
            job.candidates.append(
                ctx["models"].CandidateParameterSet(
                    job_id=job.id,
                    generation_index=index,
                    source_type="optimizer",
                    label=f"preference-evidence-{index}",
                    parameter_json={"MPC_XY_P": parameter},
                    aggregated_score=rmse,
                    aggregated_metric_json={
                        "objective_values": {"rmse": rmse},
                        "constraint_violations": {},
                        "scalar_loss": rmse,
                        "feasible": True,
                    },
                    optimizer_metadata_json={
                        "strategy": "constrained_mobo",
                        "fidelity": 1.0,
                    },
                    trial_count=1,
                    completed_trial_count=1,
                    failed_trial_count=0,
                )
            )
        db.flush()

        proposals = propose_experimental_generation(
            job=job,
            candidates=list(job.candidates),
            baseline_parameters={"MPC_XY_P": 0.95},
            generation_index=5,
            batch_size=1,
        )

        assert proposals
        metadata = proposals[0].metadata
        assert metadata["acquisition_representation"] == "objective_vector"
        assert metadata["scalarization_policy"] == "fixed_configured_objective_weights"
        assert metadata["objective_weights"] == {"rmse": 1.0}
        assert metadata["objective_normalizations"] == {"rmse": 1.0}


def test_optimizer_learning_excludes_infrastructure_failure_rate(
    experimental_ctx: dict[str, Any],
) -> None:
    ctx = experimental_ctx
    job_id = _create_job(ctx, "constrained_mobo")
    from app.orchestration.experimental_optimizer import (
        observations_for_job,
        search_space_for_job,
    )

    with ctx["db"].SessionLocal() as db:
        job = db.get(ctx["models"].Job, job_id)
        assert job is not None
        candidate = ctx["models"].CandidateParameterSet(
            job_id=job.id,
            generation_index=1,
            source_type="optimizer",
            label="infrastructure-exclusion",
            parameter_json={"MPC_XY_P": 1.0},
            aggregated_score=0.2,
            aggregated_metric_json={
                "objective_values": {"rmse": 0.2},
                "constraint_violations": {},
                "scalar_loss": 0.2,
                "feasible": True,
                "training_failure_rate": 0.5,
                "optimizer_learning_failure_rate": 0.0,
            },
            optimizer_metadata_json={
                "strategy": "constrained_mobo",
                "fidelity": 1.0,
            },
            trial_count=2,
            completed_trial_count=1,
            failed_trial_count=1,
        )
        search_space = search_space_for_job(
            job,
            baseline_parameters={"MPC_XY_P": 0.95},
        )

        observations = observations_for_job(
            job,
            search_space=search_space,
            candidates=[candidate],
        )

        assert len(observations) == 1
        assert observations[0].completed is True
        assert observations[0].failure_rate == pytest.approx(0.0)
        assert observations[0].feasible is True


@pytest.mark.parametrize("strategy", ("constrained_mobo", "surrogate_cma_es"))
@pytest.mark.parametrize(
    ("status", "failure_code"),
    (
        ("FAILED", "SIM_ERROR"),
        ("CANCELLED", None),
        ("FAILED", "INVALID_SIMULATOR_RESULT"),
        ("FAILED", "UNREGISTERED_FAILURE"),
    ),
)
def test_non_learning_history_is_quarantined_from_seed_and_proposal(
    experimental_ctx: dict[str, Any],
    strategy: str,
    status: str,
    failure_code: str | None,
) -> None:
    ctx = experimental_ctx
    job_id = _create_job(ctx, strategy)
    from app.orchestration.experimental_optimizer import (
        observations_for_job,
        propose_experimental_generation,
        search_space_for_job,
    )

    with ctx["db"].SessionLocal() as db:
        job = db.get(ctx["models"].Job, job_id)
        assert job is not None
        candidate = ctx["models"].CandidateParameterSet(
            job_id=job.id,
            generation_index=1,
            source_type="optimizer",
            label="quarantined-infrastructure",
            parameter_json={"MPC_XY_P": 1.0},
            aggregated_score=0.2,
            aggregated_metric_json={
                "objective_values": {"rmse": 0.2},
                "constraint_violations": {},
                "scalar_loss": 0.2,
                "feasible": True,
                "optimizer_learning_failure_rate": 0.0,
            },
            optimizer_metadata_json={"strategy": strategy, "fidelity": 1.0},
            trial_count=1,
            completed_trial_count=0,
            failed_trial_count=1,
        )
        candidate.trials.append(
            ctx["models"].Trial(
                job_id=job.id,
                seed=805,
                scenario_type="nominal",
                scenario_config_json={},
                status=status,
                failure_code=failure_code,
            )
        )
        job.candidates.append(candidate)
        db.flush()
        search_space = search_space_for_job(
            job,
            baseline_parameters={"MPC_XY_P": 0.95},
        )

        assert (
            observations_for_job(
                job,
                search_space=search_space,
                candidates=[candidate],
            )
            == ()
        )
        without_failure = propose_experimental_generation(
            job=job,
            candidates=[],
            baseline_parameters={"MPC_XY_P": 0.95},
            generation_index=2,
            batch_size=1,
        )
        with_failure = propose_experimental_generation(
            job=job,
            candidates=[candidate],
            baseline_parameters={"MPC_XY_P": 0.95},
            generation_index=2,
            batch_size=1,
        )

        assert with_failure == without_failure


@pytest.mark.parametrize("strategy", ("constrained_mobo", "surrogate_cma_es"))
def test_domain_failure_becomes_constraint_only_learning_evidence(
    experimental_ctx: dict[str, Any],
    strategy: str,
) -> None:
    ctx = experimental_ctx
    job_id = _create_job(ctx, strategy)
    from app.orchestration.experimental_optimizer import (
        observations_for_job,
        propose_experimental_generation,
        search_space_for_job,
    )
    from app.simulator.base import FAILURE_TIMEOUT

    with ctx["db"].SessionLocal() as db:
        job = db.get(ctx["models"].Job, job_id)
        assert job is not None
        candidate = ctx["models"].CandidateParameterSet(
            job_id=job.id,
            generation_index=1,
            source_type="optimizer",
            label="trusted-domain-failure",
            parameter_json={"MPC_XY_P": 1.0},
            optimizer_metadata_json={"strategy": strategy, "fidelity": 1.0},
            trial_count=1,
            completed_trial_count=0,
            failed_trial_count=1,
        )
        candidate.trials.append(
            ctx["models"].Trial(
                job_id=job.id,
                seed=805,
                scenario_type="nominal",
                scenario_config_json={},
                status="FAILED",
                failure_code=FAILURE_TIMEOUT,
            )
        )
        job.candidates.append(candidate)
        db.flush()
        search_space = search_space_for_job(
            job,
            baseline_parameters={"MPC_XY_P": 0.95},
        )

        observations = observations_for_job(
            job,
            search_space=search_space,
            candidates=[candidate],
        )
        assert len(observations) == 1
        assert observations[0].role == "constraint_only"
        assert observations[0].completed is True
        assert observations[0].loss is None
        assert observations[0].objectives == {}
        assert observations[0].failure_rate == pytest.approx(1.0)
        assert observations[0].feasible is False

        proposals = propose_experimental_generation(
            job=job,
            candidates=[candidate],
            baseline_parameters={"MPC_XY_P": 0.95},
            generation_index=2,
            batch_size=1,
        )
        assert proposals
        metadata = proposals[0].metadata
        if strategy == "constrained_mobo":
            assert metadata["gp_training_set"]["feasibility"] == {
                "source": 1,
                "active": 1,
            }
            assert metadata["gp_training_set"]["metrics"] == {}
        else:
            assert metadata["rbf_training_set"]["feasibility_source"] == 1
            assert metadata["rbf_training_set"]["objective_source"] == 0


@pytest.mark.parametrize("strategy", ("surrogate_cma_es", "bipop_cma_es"))
def test_pending_cma_offspring_reserves_its_cohort_position_without_training(
    experimental_ctx: dict[str, Any], strategy: str
) -> None:
    """A second ask must fill a missing position, not repeat an in-flight one."""

    ctx = experimental_ctx
    job_id = _create_job(ctx, strategy)
    from app.optimization.scenarios import (
        scenario_matrix_for_generation,
        training_matrix_for_fidelity,
    )
    from app.orchestration.experimental_optimizer import (
        observations_for_job,
        propose_experimental_generation,
        search_space_for_job,
    )

    with ctx["db"].SessionLocal() as db:
        job = db.get(ctx["models"].Job, job_id)
        assert job is not None
        first_batch = propose_experimental_generation(
            job=job,
            candidates=[],
            baseline_parameters={"MPC_XY_P": 0.95},
            generation_index=1,
            batch_size=1,
        )
        assert len(first_batch) == 1
        first = first_batch[0]
        assert isinstance(job.scenario_suite_json, dict)
        suite = ctx["schemas"].ScenarioSuiteConfig(**job.scenario_suite_json)
        configured_runs = scenario_matrix_for_generation(
            suite,
            generation_index=1,
        )
        requested_fidelity = float(
            first.metadata.get(
                "requested_fidelity",
                first.metadata.get("fidelity", 1.0),
            )
        )
        effective_fidelity = float(
            first.metadata.get(
                "effective_fidelity",
                first.metadata.get("fidelity", 1.0),
            )
        )
        selected_runs = training_matrix_for_fidelity(
            configured_runs,
            requested_fidelity,
        )
        pending = ctx["models"].CandidateParameterSet(
            job_id=job.id,
            generation_index=1,
            source_type="optimizer",
            label=first.label,
            parameter_json=dict(first.parameters),
            optimizer_metadata_json=dict(first.metadata),
            trial_count=len(selected_runs),
            completed_trial_count=0,
            failed_trial_count=0,
        )
        for run in selected_runs:
            pending.trials.append(
                ctx["models"].Trial(
                    job_id=job.id,
                    seed=run.seed,
                    scenario_type=run.scenario_type,
                    scenario_config_json={
                        **run.persistence_config(),
                        "scenario": run.scenario_type,
                        "source": "optimizer",
                        "generation_index": 1,
                        "optimizer_fidelity": effective_fidelity,
                        "optimizer_requested_fidelity": requested_fidelity,
                    },
                    status="PENDING",
                )
            )
        job.candidates.append(pending)
        db.flush()

        search_space = search_space_for_job(
            job,
            baseline_parameters={"MPC_XY_P": 0.95},
        )
        observations = observations_for_job(
            job,
            search_space=search_space,
            candidates=[pending],
        )
        assert len(observations) == 1
        assert observations[0].completed is False
        assert observations[0].loss is None
        assert observations[0].failure_rate == pytest.approx(0.0)

        second_batch = propose_experimental_generation(
            job=job,
            candidates=[pending],
            baseline_parameters={"MPC_XY_P": 0.95},
            generation_index=2,
            batch_size=1,
        )
        assert len(second_batch) == 1
        second = second_batch[0]
        first_metadata = first.metadata
        second_metadata = second.metadata

        assert second_metadata["cma_cohort_id"] == first_metadata["cma_cohort_id"]
        assert second_metadata["cma_cohort_index"] == first_metadata["cma_cohort_index"]
        assert second_metadata["cma_cohort_position"] != first_metadata["cma_cohort_position"]
        assert second_metadata["cma_state"]["updates"] == 0
        assert second_metadata["cma_state"]["pending_offspring"] == 1
        assert second_metadata["rbf_training_set"]["objective_source"] == 0
        assert second_metadata["rbf_training_set"]["feasibility_source"] == 0
        assert second.parameters != first.parameters


def test_legacy_mock_parameter_domain_can_reach_the_experimental_optimizer(
    experimental_ctx: dict[str, Any],
) -> None:
    """The backward-compatible lowercase mock domain must not use PX4-name validation."""

    ctx = experimental_ctx
    job_id = _create_job(ctx, "turbo", use_selected_px4_parameter=False)

    assert _drive_to_terminal(ctx, job_id) == "COMPLETED"
    with ctx["db"].SessionLocal() as db:
        job = db.get(ctx["models"].Job, job_id)
        assert job is not None
        generated = [candidate for candidate in job.candidates if not candidate.is_baseline]
        assert generated
        assert all("kp_xy" in candidate.parameter_json for candidate in generated)


@pytest.mark.parametrize(
    "optimizer_strategy",
    [
        "heuristic",
        "gpt",
        "llm_harness",
        "cma_es",
        "constrained_mobo",
        "multi_fidelity_mobo",
        "turbo",
        "saasbo",
        "surrogate_cma_es",
        "bipop_cma_es",
        "optimizer_portfolio",
    ],
)
def test_real_cli_optimizer_requires_explicit_px4_parameters(
    experimental_ctx: dict[str, Any],
    optimizer_strategy: str,
) -> None:
    schemas = experimental_ctx["schemas"]

    with pytest.raises(
        ValueError,
        match="requires an explicit PX4 parameter_space",
    ):
        schemas.JobCreateRequest(
            simulator_backend="real_cli",
            optimizer_strategy=optimizer_strategy,
            parameter_space=[],
            max_total_trials=100,
        )


def test_full_fidelity_guard_requires_completed_feasible_evidence(
    experimental_ctx: dict[str, Any],
) -> None:
    ctx = experimental_ctx
    job_id = _create_job(ctx, "multi_fidelity_mobo")
    models = ctx["models"]
    from app.orchestration.job_manager import (
        _has_successful_full_fidelity_optimizer_evidence,
    )

    with ctx["db"].SessionLocal() as db:
        job = db.get(models.Job, job_id)
        assert job is not None
        job.scenario_suite_json = {
            "cases": [{"id": "nominal", "scenario_type": "nominal", "seeds": [101]}]
        }
        candidate = models.CandidateParameterSet(
            job_id=job.id,
            generation_index=1,
            source_type="optimizer",
            label="failed-full-verification",
            parameter_json={"MPC_XY_P": 1.0},
            optimizer_metadata_json={
                "requested_fidelity": 1.0,
                "effective_fidelity": 1.0,
            },
            trial_count=1,
            completed_trial_count=0,
            failed_trial_count=1,
        )
        job.candidates.append(candidate)
        candidate.trials.append(
            models.Trial(
                job_id=job.id,
                seed=101,
                scenario_type="nominal",
                scenario_config_json={
                    "scenario_case_id": "nominal",
                    "holdout": False,
                },
                status="FAILED",
            )
        )
        db.flush()

        assert not _has_successful_full_fidelity_optimizer_evidence(job)

        candidate.completed_trial_count = 1
        candidate.failed_trial_count = 0
        candidate.trials[0].status = "COMPLETED"
        candidate.trials[0].metric = models.TrialMetric(
            rmse=0.5,
            max_error=0.75,
            overshoot_count=0,
            completion_time=8.0,
            crash_flag=False,
            timeout_flag=False,
            score=0.5,
            final_error=0.1,
            pass_flag=True,
            instability_flag=False,
            raw_metric_json={},
        )
        candidate.aggregated_score = 0.5
        candidate.aggregated_metric_json = {"scalar_loss": 0.5, "feasible": False}
        assert not _has_successful_full_fidelity_optimizer_evidence(job)

        candidate.aggregated_metric_json = {"scalar_loss": 0.5, "feasible": True}
        assert _has_successful_full_fidelity_optimizer_evidence(job)

        job.scenario_suite_json = {
            "cases": [
                {"id": "nominal", "scenario_type": "nominal", "seeds": [101]},
                {
                    "id": "verification",
                    "scenario_type": "nominal",
                    "seeds": [805],
                    "holdout": True,
                },
            ]
        }
        holdout_trial = models.Trial(
            job_id=job.id,
            candidate_id=candidate.id,
            seed=805,
            scenario_type="nominal",
            scenario_config_json={
                "scenario_case_id": "verification",
                "holdout": True,
            },
            status="COMPLETED",
        )
        holdout_trial.metric = models.TrialMetric(
            rmse=0.6,
            max_error=0.8,
            overshoot_count=0,
            completion_time=8.5,
            crash_flag=False,
            timeout_flag=False,
            score=0.6,
            final_error=0.1,
            pass_flag=True,
            instability_flag=False,
            raw_metric_json={},
        )
        candidate.trials.append(holdout_trial)
        candidate.trial_count = 2
        candidate.completed_trial_count = 2
        assert not _has_successful_full_fidelity_optimizer_evidence(job)

        candidate.aggregated_metric_json = {
            "scalar_loss": 0.5,
            "feasible": True,
            "holdout": {"validation_status": "failed", "feasible": False},
        }
        assert not _has_successful_full_fidelity_optimizer_evidence(job)

        candidate.aggregated_metric_json["holdout"] = {
            "validation_status": "passed",
            "feasible": True,
        }
        assert _has_successful_full_fidelity_optimizer_evidence(job)


def test_optimizer_adapter_separates_objective_loss_from_constraint_penalty(
    experimental_ctx: dict[str, Any],
) -> None:
    ctx = experimental_ctx
    job_id = _create_job(ctx, "surrogate_cma_es")
    models = ctx["models"]
    from app.orchestration.experimental_optimizer import (
        observations_for_job,
        search_space_for_job,
    )

    with ctx["db"].SessionLocal() as db:
        job = db.get(models.Job, job_id)
        assert job is not None
        candidate = models.CandidateParameterSet(
            job_id=job.id,
            generation_index=1,
            source_type="optimizer",
            parameter_json={"MPC_XY_P": 1.0},
            aggregated_score=1_000_002.5,
            aggregated_metric_json={
                "scalar_loss": 2.5,
                "feasible": False,
                "constraint_values": {"minimum_margin": 9.0},
                "constraint_violations": {"minimum_margin": 1.0},
            },
            optimizer_metadata_json={"requested_fidelity": 1.0},
            trial_count=1,
            completed_trial_count=1,
        )
        search_space = search_space_for_job(
            job,
            baseline_parameters={"MPC_XY_P": 0.95},
        )

        observation = observations_for_job(
            job,
            search_space=search_space,
            candidates=[candidate],
        )[0]

        assert observation.loss == pytest.approx(2.5)
        assert observation.constraints == {"minimum_margin": pytest.approx(1.0)}
        assert observation.feasible is False


def test_history_evaluation_reuses_persisted_aggregate_objectives(
    experimental_ctx: dict[str, Any],
) -> None:
    ctx = experimental_ctx
    schemas = ctx["schemas"]
    candidate = ctx["models"].CandidateParameterSet(
        job_id="job-evaluation",
        source_type="optimizer",
        parameter_json={"MPC_XY_P": 1.0},
        aggregated_score=99.0,
        aggregated_metric_json={
            "objective_values": {"rmse": 99.0},
            "constraint_values": {},
            "constraint_violations": {},
            "feasible": True,
            "total_constraint_violation": 0.0,
            "scalar_loss": 99.0,
            "training_completed_trial_count": 1,
        },
        trial_count=1,
        completed_trial_count=1,
    )
    trial = ctx["models"].Trial(
        job_id="job-evaluation",
        seed=101,
        scenario_type="nominal",
        scenario_config_json={
            "scenario_case_id": "nominal",
            "holdout": False,
        },
        status="COMPLETED",
    )
    trial.metric = ctx["models"].TrialMetric(
        rmse=1.0,
        max_error=1.0,
        completion_time=1.0,
        score=1.0,
    )
    candidate.trials.append(trial)

    evaluation = ctx["jobs"]._candidate_evaluation(
        candidate,
        schemas.ObjectiveConfig(),
        schemas.ScenarioSuiteConfig(),
    )

    assert evaluation is not None
    assert evaluation.objectives == {"rmse": pytest.approx(99.0)}


def test_legacy_history_evaluation_shares_case_weight_across_seeds(
    experimental_ctx: dict[str, Any],
) -> None:
    ctx = experimental_ctx
    schemas = ctx["schemas"]
    candidate = ctx["models"].CandidateParameterSet(
        job_id="job-legacy-evaluation",
        source_type="optimizer",
        parameter_json={"MPC_XY_P": 1.0},
    )
    for case_id, seed, rmse in (
        ("many-seeds", 1, 0.0),
        ("many-seeds", 2, 10.0),
        ("one-seed", 3, 20.0),
    ):
        trial = ctx["models"].Trial(
            job_id="job-legacy-evaluation",
            seed=seed,
            scenario_type="nominal",
            scenario_config_json={"scenario_case_id": case_id},
            status="COMPLETED",
        )
        trial.metric = ctx["models"].TrialMetric(
            rmse=rmse,
            max_error=rmse,
            completion_time=1.0,
            score=rmse,
            crash_flag=False,
            timeout_flag=False,
            pass_flag=True,
            instability_flag=False,
        )
        candidate.trials.append(trial)
    suite = schemas.ScenarioSuiteConfig(
        cases=[
            schemas.ScenarioCaseConfig(
                id="many-seeds", scenario_type="nominal", seeds=[1, 2], weight=1.0
            ),
            schemas.ScenarioCaseConfig(
                id="one-seed", scenario_type="nominal", seeds=[3], weight=1.0
            ),
        ]
    )

    evaluation = ctx["jobs"]._candidate_evaluation(
        candidate,
        schemas.ObjectiveConfig(),
        suite,
    )

    assert evaluation is not None
    assert evaluation.objectives["rmse"] == pytest.approx(12.5)


def test_identical_experiments_do_not_derive_seed_from_random_database_ids(
    experimental_ctx: dict[str, Any],
) -> None:
    ctx = experimental_ctx
    first_id = _create_job(ctx, "turbo")
    second_id = _create_job(ctx, "turbo")
    from app.orchestration.experimental_optimizer import propose_experimental_generation

    with ctx["db"].SessionLocal() as db:
        first = db.get(ctx["models"].Job, first_id)
        second = db.get(ctx["models"].Job, second_id)
        assert first is not None and second is not None and first.id != second.id

        common = {
            "candidates": [],
            "baseline_parameters": {"MPC_XY_P": 0.95},
            "generation_index": 1,
            "batch_size": 2,
        }
        first_proposals = propose_experimental_generation(job=first, **common)
        second_proposals = propose_experimental_generation(job=second, **common)

        assert first_proposals == second_proposals


def test_optimizer_seed_state_ignores_cross_runtime_ulp_noise() -> None:
    from app.orchestration.experimental_optimizer import _canonical_seed_value

    lower_ulp = {
        "loss": 0.5823333333333333,
        "objectives": {"rmse": 0.5823333333333333},
        "unit_vector": (0.1, 0.2),
    }
    upper_ulp = {
        "loss": 0.5823333333333334,
        "objectives": {"rmse": 0.5823333333333334},
        "unit_vector": (0.1, 0.2),
    }
    materially_different = {
        **lower_ulp,
        "loss": 0.5824333333333333,
    }

    assert _canonical_seed_value(lower_ulp) == _canonical_seed_value(upper_ulp)
    assert _canonical_seed_value(lower_ulp) != _canonical_seed_value(materially_different)
    assert _canonical_seed_value(-0.0) == 0.0


def test_experimental_adapter_protects_identity_and_validates_output(
    experimental_ctx: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    ctx = experimental_ctx
    job_id = _create_job(ctx, "turbo")
    import app.orchestration.experimental_optimizer as adapter
    from app.optimization.experimental_types import ExperimentalProposal

    poisoned = ExperimentalProposal(
        label="poisoned-metadata",
        parameters={"MPC_XY_P": 1.0},
        rationale="exercise the adapter boundary",
        metadata={
            "strategy": "not-the-job-strategy",
            "generation_index": 999,
            "random_seed": 1,
            "fidelity": 1.0,
        },
    )
    monkeypatch.setattr(
        adapter,
        "propose_bayesian_candidates",
        lambda *_args, **_kwargs: [poisoned],
    )

    with ctx["db"].SessionLocal() as db:
        job = db.get(ctx["models"].Job, job_id)
        assert job is not None
        proposal = adapter.propose_experimental_generation(
            job=job,
            candidates=[],
            baseline_parameters={"MPC_XY_P": 0.95},
            generation_index=2,
            batch_size=1,
        )[0]

        assert proposal.metadata["strategy"] == "turbo"
        assert proposal.metadata["generation_index"] == 2
        assert proposal.metadata["random_seed"] != 1
        assert isinstance(proposal.metadata["random_seed"], str)

        invalid_fidelity = ExperimentalProposal(
            label="invalid-fidelity",
            parameters={"MPC_XY_P": 1.0},
            rationale="exercise invalid child metadata",
            metadata={"fidelity": True},
        )
        monkeypatch.setattr(
            adapter,
            "propose_bayesian_candidates",
            lambda *_args, **_kwargs: [invalid_fidelity],
        )
        with pytest.raises(RuntimeError, match="fidelity"):
            adapter.propose_experimental_generation(
                job=job,
                candidates=[],
                baseline_parameters={"MPC_XY_P": 0.95},
                generation_index=2,
                batch_size=1,
            )

        monkeypatch.setattr(
            adapter,
            "propose_bayesian_candidates",
            lambda *_args, **_kwargs: [poisoned, poisoned],
        )
        with pytest.raises(RuntimeError, match="duplicate proposals"):
            adapter.propose_experimental_generation(
                job=job,
                candidates=[],
                baseline_parameters={"MPC_XY_P": 0.95},
                generation_index=2,
                batch_size=2,
            )
