"""Phase 3 orchestration tests: state transitions + worker progression.

These tests exercise the orchestration package directly against an isolated
SQLite DB. They never touch the FastAPI app so they can be run fast and
independently of the HTTP layer.
"""

from __future__ import annotations

import importlib
import sys
import threading
import time
from collections.abc import Iterator
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import event, select, update
from sqlalchemy.exc import DatabaseError
from sqlalchemy.orm import Session

from app.simulator import (
    ArtifactMetadata,
    MockSimulatorAdapter,
    RealCliSimulatorAdapter,
    TrialContext,
    TrialFailure,
    TrialResult,
)

_EXAMPLE_SIM = (
    Path(__file__).resolve().parents[2] / "scripts" / "simulators" / "example_real_simulator.py"
)


@pytest.fixture()
def orchestration_ctx(tmp_path, monkeypatch) -> Iterator[dict[str, object]]:
    """Yield a reloaded orchestration context bound to a per-test SQLite DB."""

    db_path = tmp_path / "orch.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    monkeypatch.setenv("APP_ENV", "test")

    from app import config as config_module

    config_module.get_settings.cache_clear()

    models_was_loaded = "app.models" in sys.modules

    import app.db as db_module

    importlib.reload(db_module)

    if models_was_loaded:
        models_module = importlib.reload(sys.modules["app.models"])
    else:
        models_module = importlib.import_module("app.models")

    import app.orchestration.attempt_evidence as attempt_evidence_module

    importlib.reload(attempt_evidence_module)

    import app.services.jobs as jobs_service_module

    importlib.reload(jobs_service_module)

    # Reload orchestration submodules so they pick up the freshly-reloaded
    # models/db (they otherwise cache Base/metadata from the previous import).
    import app.orchestration.aggregation as aggregation_module
    import app.orchestration.constants as constants_module
    import app.orchestration.events as events_module
    import app.orchestration.job_manager as job_manager_module
    import app.orchestration.metrics as metrics_module  # noqa: F401
    import app.orchestration.optimizer as optimizer_module
    import app.orchestration.runner as runner_module
    import app.orchestration.trial_executor as trial_executor_module

    importlib.reload(constants_module)
    importlib.reload(optimizer_module)
    importlib.reload(events_module)
    importlib.reload(job_manager_module)
    importlib.reload(trial_executor_module)
    importlib.reload(aggregation_module)
    importlib.reload(runner_module)

    db_module.init_db()

    yield {
        "db_module": db_module,
        "models": models_module,
        "schemas": __import__("app.schemas", fromlist=["*"]),
        "jobs_service": jobs_service_module,
        "job_manager": job_manager_module,
        "trial_executor": trial_executor_module,
        "attempt_evidence": attempt_evidence_module,
        "aggregation": aggregation_module,
        "runner": runner_module,
    }

    config_module.get_settings.cache_clear()


def _create_queued_job(ctx: dict[str, object]) -> str:
    schemas = ctx["schemas"]
    jobs_service = ctx["jobs_service"]
    db_module = ctx["db_module"]

    req = schemas.JobCreateRequest(
        simulator_backend="mock",
        optimizer_strategy="heuristic",
    )
    with db_module.SessionLocal() as db:
        job = jobs_service.create_job(db, req)
        return job.id


# --- Job manager -----------------------------------------------------------


def test_start_queued_jobs_creates_baseline_and_trials(orchestration_ctx):
    ctx = orchestration_ctx
    job_id = _create_queued_job(ctx)

    with ctx["db_module"].SessionLocal() as db:
        started = ctx["job_manager"].start_queued_jobs(db)
    assert started == [job_id]

    with ctx["db_module"].SessionLocal() as db:
        db_session: Session = db
        job = db_session.get(ctx["models"].Job, job_id)
        assert job is not None
        assert job.status == "RUNNING"
        assert job.started_at is not None
        assert job.current_phase == "trial_execution"
        assert job.baseline_candidate_id is not None
        # Phase 5: baseline (4 scenarios) + 3 optimizer candidates × 3 scenarios.
        assert job.progress_total_trials == 4 + 3 * 3
        assert job.progress_completed_trials == 0

        candidates = list(job.candidates)
        # Phase 5: one baseline plus the optimizer proposals.
        assert len(candidates) == 1 + 3
        baseline = next(c for c in candidates if c.is_baseline)
        assert baseline.source_type == "baseline"
        assert baseline.is_baseline is True
        assert set(baseline.parameter_json.keys()) >= {
            "kp_xy",
            "kd_xy",
            "ki_xy",
            "vel_limit",
            "accel_limit",
            "disturbance_rejection",
        }

        optimizer_candidates = [c for c in candidates if not c.is_baseline]
        assert len(optimizer_candidates) == 3
        assert all(c.source_type == "optimizer" for c in optimizer_candidates)
        assert {c.generation_index for c in optimizer_candidates} == {1, 2, 3}

        trials = list(job.trials)
        assert len(trials) == job.progress_total_trials
        baseline_trials = [t for t in trials if t.candidate_id == baseline.id]
        assert {t.scenario_type for t in baseline_trials} == {
            "nominal",
            "noise_perturbed",
            "wind_perturbed",
            "combined_perturbed",
        }
        optimizer_trials = [t for t in trials if t.candidate_id != baseline.id]
        assert len(optimizer_trials) == 3 * 3
        assert all(t.status == "PENDING" for t in trials)

        # Seeds must actually vary within each optimizer candidate and between
        # candidates — the spec requires trials to vary seed and scenario.
        for c in optimizer_candidates:
            seeds = {t.seed for t in optimizer_trials if t.candidate_id == c.id}
            assert len(seeds) == len([t for t in optimizer_trials if t.candidate_id == c.id])

        events = {e.event_type for e in job.events}
        assert "job_started" in events
        assert "baseline_started" in events
        assert "optimizer_started" in events
        assert "optimizer_candidate_created" in events
        assert "trial_dispatched" in events


def test_outcome_contract_drift_is_rejected_before_candidate_dispatch(
    orchestration_ctx,
):
    ctx = orchestration_ctx
    job_id = _create_queued_job(ctx)
    with ctx["db_module"].SessionLocal() as db:
        job = db.get(ctx["models"].Job, job_id)
        assert job is not None
        job.min_pass_rate = 0.7
        db.commit()

    with ctx["db_module"].SessionLocal() as db:
        started = ctx["job_manager"].start_queued_jobs(db)

    assert started == []
    with ctx["db_module"].SessionLocal() as db:
        job = db.get(ctx["models"].Job, job_id)
        assert job is not None
        assert job.status == "FAILED"
        assert job.latest_error_code == "OUTCOME_CONTRACT_DRIFT"
        assert list(job.candidates) == []
        assert list(job.trials) == []
        failure = next(
            event for event in job.events if event.event_type == "job_failed"
        )
        assert failure.payload_json["code"] == "OUTCOME_CONTRACT_DRIFT"


def test_invalid_queued_job_is_quarantined_without_blocking_following_job(
    orchestration_ctx,
):
    ctx = orchestration_ctx
    invalid_job_id = _create_queued_job(ctx)
    valid_job_id = _create_queued_job(ctx)
    with ctx["db_module"].SessionLocal() as db:
        invalid_job = db.get(ctx["models"].Job, invalid_job_id)
        assert invalid_job is not None
        invalid_job.baseline_parameter_json = {"kp_xy": True}
        db.commit()

    with ctx["db_module"].SessionLocal() as db:
        started = ctx["job_manager"].start_queued_jobs(db)

    assert started == [valid_job_id]
    with ctx["db_module"].SessionLocal() as db:
        invalid_job = db.get(ctx["models"].Job, invalid_job_id)
        valid_job = db.get(ctx["models"].Job, valid_job_id)
        assert invalid_job is not None and valid_job is not None
        assert invalid_job.status == "FAILED"
        assert invalid_job.latest_error_code == "JOB_INITIALIZATION_FAILED"
        assert valid_job.status == "RUNNING"


@pytest.mark.parametrize("limit", [0, -1, True, 101])
def test_start_queued_jobs_rejects_invalid_limits(orchestration_ctx, limit: object):
    with (
        orchestration_ctx["db_module"].SessionLocal() as db,
        pytest.raises(ValueError, match="limit"),
    ):
        orchestration_ctx["job_manager"].start_queued_jobs(
            db,
            limit=limit,  # type: ignore[arg-type]
        )


def test_budget_limited_legacy_heuristic_still_dispatches_one_candidate(
    orchestration_ctx,
):
    ctx = orchestration_ctx
    schemas = ctx["schemas"]
    with ctx["db_module"].SessionLocal() as db:
        job = ctx["jobs_service"].create_job(
            db,
            schemas.JobCreateRequest(
                simulator_backend="mock",
                optimizer_strategy="heuristic",
                # Legacy scheduling uses four baseline and three optimizer
                # trials. Eight is accepted by the request-level conservative
                # budget check and leaves room for exactly one candidate.
                max_total_trials=8,
            ),
        )
        job_id = job.id

    with ctx["db_module"].SessionLocal() as db:
        assert ctx["job_manager"].start_queued_jobs(db) == [job_id]

    with ctx["db_module"].SessionLocal() as db:
        job = db.get(ctx["models"].Job, job_id)
        assert job is not None
        assert len(job.candidates) == 2
        assert len([candidate for candidate in job.candidates if not candidate.is_baseline]) == 1
        assert job.progress_total_trials == 7
        assert job.progress_total_trials <= job.max_total_trials


def test_explicit_scenario_suite_uses_common_random_numbers_for_every_candidate(
    orchestration_ctx,
):
    ctx = orchestration_ctx
    schemas = ctx["schemas"]
    with ctx["db_module"].SessionLocal() as db:
        job = ctx["jobs_service"].create_job(
            db,
            schemas.JobCreateRequest(
                optimizer_strategy="heuristic",
                max_iterations=3,
                parameter_catalog_version="builtin-v1",
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
                            id="nominal", scenario_type="nominal", seeds=[11, 12]
                        ),
                        schemas.ScenarioCaseConfig(
                            id="wind-validation",
                            scenario_type="wind_perturbed",
                            seeds=[91],
                            holdout=True,
                            config={"wind_mps": 8},
                        ),
                    ],
                    common_random_numbers=True,
                ),
            ),
        )
        job_id = job.id
    with ctx["db_module"].SessionLocal() as db:
        assert ctx["job_manager"].start_queued_jobs(db) == [job_id]
    with ctx["db_module"].SessionLocal() as db:
        job = db.get(ctx["models"].Job, job_id)
        assert len(job.candidates) == 4
        assert job.progress_total_trials == 4 * 3
        baseline = next(candidate for candidate in job.candidates if candidate.is_baseline)
        invariant_keys = {
            "kp_xy",
            "kd_xy",
            "ki_xy",
            "vel_limit",
            "accel_limit",
            "disturbance_rejection",
        }
        assert all(
            {key: candidate.parameter_json[key] for key in invariant_keys}
            == {key: baseline.parameter_json[key] for key in invariant_keys}
            for candidate in job.candidates
        )
        scenario_keys_by_candidate = {
            candidate.id: {
                (
                    trial.scenario_config_json["scenario_case_id"],
                    trial.seed,
                    trial.scenario_type,
                )
                for trial in candidate.trials
            }
            for candidate in job.candidates
        }
        expected = {
            ("nominal", 11, "nominal"),
            ("nominal", 12, "nominal"),
            ("wind-validation", 91, "wind_perturbed"),
        }
        assert all(keys == expected for keys in scenario_keys_by_candidate.values())
        assert all(
            trial.scenario_config_json["holdout"] is True
            for trial in job.trials
            if trial.scenario_config_json["scenario_case_id"] == "wind-validation"
        )


def test_selected_parameter_heuristic_honors_iteration_limit(orchestration_ctx):
    ctx = orchestration_ctx
    schemas = ctx["schemas"]
    with ctx["db_module"].SessionLocal() as db:
        job = ctx["jobs_service"].create_job(
            db,
            schemas.JobCreateRequest(
                optimizer_strategy="heuristic",
                max_iterations=5,
                max_total_trials=20,
                parameter_catalog_version="builtin-v1",
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
                            id="nominal", scenario_type="nominal", seeds=[11]
                        )
                    ]
                ),
            ),
        )
        job_id = job.id

    with ctx["db_module"].SessionLocal() as db:
        assert ctx["job_manager"].start_queued_jobs(db) == [job_id]

    with ctx["db_module"].SessionLocal() as db:
        job = db.get(ctx["models"].Job, job_id)
        assert job is not None
        assert len(job.candidates) == 6
        assert job.current_generation == 5
        assert job.progress_total_trials == 6
        optimizer_event = next(
            event for event in job.events if event.event_type == "optimizer_started"
        )
        assert optimizer_event.payload_json["requested_candidate_count"] == 5
        assert optimizer_event.payload_json["budget_limited"] is False
        assert optimizer_event.payload_json["design_limited"] is False


def test_non_common_random_number_seed_offsets_stay_portable(orchestration_ctx):
    ctx = orchestration_ctx
    job = ctx["models"].Job(
        scenario_suite_json={
            "common_random_numbers": False,
            "cases": [
                {
                    "id": "nominal",
                    "scenario_type": "nominal",
                    "seeds": [2_147_483_647],
                }
            ],
        }
    )

    runs = ctx["job_manager"]._configured_scenario_runs(job, generation_index=100)

    assert runs is not None
    assert len(runs) == 1
    assert 0 <= runs[0].seed <= 2_147_483_647
    assert runs[0].seed != 2_147_483_647


def test_holdout_results_never_influence_candidate_selection(orchestration_ctx):
    """A validation scenario may be reported, but cannot steer optimization."""

    ctx = orchestration_ctx
    schemas = ctx["schemas"]
    objective = schemas.ObjectiveConfig(
        objectives=[schemas.ObjectiveSpec(metric="rmse", direction="minimize", weight=1.0)],
        constraints=[schemas.ConstraintSpec(metric="pass_rate", operator="gte", threshold=0.5)],
    )
    suite = schemas.ScenarioSuiteConfig(
        cases=[
            schemas.ScenarioCaseConfig(id="training", seeds=[1]),
            schemas.ScenarioCaseConfig(id="validation", seeds=[2], holdout=True),
        ]
    )

    def metric(rmse: float, *, passed: bool) -> SimpleNamespace:
        return SimpleNamespace(
            rmse=rmse,
            max_error=rmse * 2,
            overshoot_count=0,
            completion_time=10.0,
            crash_flag=False,
            timeout_flag=False,
            score=rmse,
            final_error=rmse,
            pass_flag=passed,
            instability_flag=False,
            raw_metric_json={},
        )

    def aggregate(holdout_rmse: float) -> tuple[SimpleNamespace, dict]:
        candidate = SimpleNamespace(
            is_baseline=False,
            trial_count=0,
            completed_trial_count=0,
            failed_trial_count=0,
            aggregated_metric_json=None,
            aggregated_score=None,
        )
        trials = [
            SimpleNamespace(
                status="COMPLETED",
                metric=metric(2.0, passed=True),
                scenario_config_json={"scenario_case_id": "training", "holdout": False},
                scenario_type="nominal",
                seed=1,
            ),
            SimpleNamespace(
                status="COMPLETED",
                metric=metric(holdout_rmse, passed=holdout_rmse < 1.0),
                scenario_config_json={"scenario_case_id": "validation", "holdout": True},
                scenario_type="nominal",
                seed=2,
            ),
        ]
        result = ctx["aggregation"]._aggregate_candidate(
            candidate,
            trials,
            objective_config=objective,
            scenario_suite=suite,
        )
        assert result is not None
        return candidate, result

    excellent_holdout, excellent_metrics = aggregate(0.01)
    failed_holdout, failed_metrics = aggregate(100.0)

    assert excellent_holdout.aggregated_score == failed_holdout.aggregated_score
    assert excellent_metrics["objective_values"] == failed_metrics["objective_values"]
    assert excellent_metrics["rmse"] == failed_metrics["rmse"] == 2.0
    assert excellent_metrics["training_trial_count"] == 1
    assert excellent_metrics["training_completed_trial_count"] == 1
    assert excellent_metrics["holdout"]["objective_values"]["rmse"] == 0.01
    assert failed_metrics["holdout"]["objective_values"]["rmse"] == 100.0
    assert ctx["aggregation"]._is_eligible(excellent_holdout) is True


def test_start_queued_jobs_skips_non_queued(orchestration_ctx):
    ctx = orchestration_ctx
    job_id = _create_queued_job(ctx)

    # First call moves it to RUNNING. Second call must be a no-op.
    with ctx["db_module"].SessionLocal() as db:
        ctx["job_manager"].start_queued_jobs(db)
    with ctx["db_module"].SessionLocal() as db:
        started = ctx["job_manager"].start_queued_jobs(db)
    assert started == []

    with ctx["db_module"].SessionLocal() as db:
        job = db.get(ctx["models"].Job, job_id)
        assert job.status == "RUNNING"
        # Still exactly one baseline + optimizer candidates and all trials.
        assert len(list(job.candidates)) == 1 + 3
        assert len(list(job.trials)) == 4 + 3 * 3


# --- Trial executor --------------------------------------------------------


def test_claim_and_run_one_pending_trial_completes(orchestration_ctx):
    ctx = orchestration_ctx
    job_id = _create_queued_job(ctx)
    with ctx["db_module"].SessionLocal() as db:
        ctx["job_manager"].start_queued_jobs(db)

    with ctx["db_module"].SessionLocal() as db:
        trial_id = ctx["trial_executor"].claim_and_run_one_pending_trial(db, "test-worker")
    assert trial_id is not None

    with ctx["db_module"].SessionLocal() as db:
        trial = db.get(ctx["models"].Trial, trial_id)
        assert trial.status == "COMPLETED"
        assert trial.worker_id == "test-worker"
        assert trial.simulator_backend == "mock"
        assert trial.started_at is not None
        assert trial.finished_at is not None
        assert trial.attempt_count == 1
        assert trial.metric is not None
        assert trial.metric.score is not None
        assert trial.metric.rmse is not None
        assert trial.log_excerpt is not None
        assert trial.accepted_attempt_id is not None
        assert len(trial.execution_attempts) == 1
        attempt = trial.execution_attempts[0]
        assert attempt.id == trial.accepted_attempt_id
        assert attempt.attempt_count == 1
        assert attempt.outcome is not None
        assert attempt.outcome.accepted is True
        assert attempt.outcome.terminal_status == "COMPLETED"
        assert attempt.outcome.outcome_class == "success"
        assert "test-worker" not in str(attempt.claim_evidence_json)

        from app.storage.evidence import candidate_trial_artifact_evidence

        artifact_evidence = candidate_trial_artifact_evidence(
            trial.candidate,
            [trial],
            verify_bytes=True,
        )
        assert artifact_evidence is not None
        accepted = ctx["attempt_evidence"].accepted_trial_attempt_evidence(
            trial,
            artifact_evidence=artifact_evidence[trial.id],
        )
        assert accepted is not None
        assert accepted.attempt_id == attempt.id
        assert accepted.outcome_evidence_id == attempt.outcome.evidence_id

        job = db.get(ctx["models"].Job, job_id)
        assert job.progress_completed_trials == 1
        event_types = [e.event_type for e in job.events]
        assert event_types.count("trial_completed") == 1


def test_claim_time_input_snapshot_fails_closed_before_simulator_on_drift(
    orchestration_ctx,
    monkeypatch,
) -> None:
    """A post-claim row change cannot alter or launch the frozen execution."""

    ctx = orchestration_ctx
    trial_id = _seed_single_pending_trial(ctx)
    models = ctx["models"]
    original_record_event = ctx["trial_executor"].record_event
    mutated = False

    def mutate_after_claim(db, job_id, event_type, payload):
        nonlocal mutated
        if event_type == "trial_claimed" and not mutated:
            mutated = True
            with ctx["db_module"].SessionLocal() as other_db:
                other_trial = other_db.get(models.Trial, trial_id)
                assert other_trial is not None
                other_trial.scenario_config_json = {
                    "scenario_case_id": "mutated-after-claim",
                    "scenario_weight": 9.0,
                    "advanced": {"gust_m_s": 40.0},
                }
                other_trial.candidate.parameter_json = {
                    "kp_xy": 9.0,
                    "nested": {"mutated": True},
                }
                other_trial.job.vehicle_profile_json = {
                    "vehicle_type": "mutated-after-claim"
                }
                other_db.commit()
        return original_record_event(db, job_id, event_type, payload)

    class NeverStartedAdapter:
        backend_name = "claim-drift-probe"

        def __init__(self) -> None:
            self.prepare_calls = 0
            self.run_calls = 0
            self.cleanup_calls = 0

        def prepare(self, _ctx) -> None:
            self.prepare_calls += 1

        def run_trial(self, _ctx):
            self.run_calls += 1
            raise AssertionError("drifted claim must not reach the simulator")

        def cleanup(self, _ctx) -> None:
            self.cleanup_calls += 1

    adapter = NeverStartedAdapter()
    monkeypatch.setattr(
        ctx["trial_executor"],
        "record_event",
        mutate_after_claim,
    )
    with ctx["db_module"].SessionLocal() as db:
        assert (
            ctx["trial_executor"].claim_and_run_one_pending_trial(
                db,
                "worker-input-receipt",
                adapter=adapter,
            )
            == trial_id
        )

    assert mutated is True
    assert adapter.prepare_calls == 0
    assert adapter.run_calls == 0
    assert adapter.cleanup_calls == 0
    with ctx["db_module"].SessionLocal() as db:
        trial = db.get(models.Trial, trial_id)
        assert trial is not None
        assert trial.status == "FAILED"
        assert trial.failure_code == "INPUT_EVIDENCE_DRIFT"
        assert trial.metric is None
        attempt = trial.accepted_attempt
        assert attempt is not None
        claim = ctx["attempt_evidence"].verify_trial_attempt_claim(
            attempt.claim_evidence_json
        )
        assert claim is not None
        assert claim.schema_id == (
            "dronedream.trial-execution-attempt-claim/v3"
        )
        assert claim.execution_input_sha256 is not None
        assert claim.candidate_contract_sha256 is not None
        assert claim.scenario_contract_sha256 is not None
        assert attempt.outcome is not None
        assert attempt.outcome.outcome_class == "invalid_evidence"
        assert adapter.backend_name == attempt.simulator_backend


def test_frozen_trial_context_detaches_nested_json(orchestration_ctx) -> None:
    """Nested ORM JSON mutations cannot rewrite an already-frozen context."""

    ctx = orchestration_ctx
    trial_id = _seed_single_pending_trial(ctx)
    models = ctx["models"]
    with ctx["db_module"].SessionLocal() as db:
        trial = db.get(models.Trial, trial_id)
        assert trial is not None
        trial.scenario_config_json = {
            "advanced": {"gust": [1.0, 2.0]},
            "scenario_weight": 2.0,
        }
        trial.candidate.parameter_json = {
            "kp_xy": 1.0,
            "schedule": {"points": [0.1, 0.2]},
        }
        trial.job.vehicle_profile_json = {
            "vehicle_type": "multicopter",
            "nested": {"motors": [1, 2, 3, 4]},
        }
        trial.attempt_count = 1
        db.flush()
        snapshot = ctx["attempt_evidence"].snapshot_trial_attempt_inputs(
            trial=trial,
            job=trial.job,
            candidate=trial.candidate,
        )
        frozen = ctx["trial_executor"]._build_trial_context(
            trial,
            trial.job,
            trial.candidate,
            input_snapshot=snapshot,
        )

        trial.scenario_config_json["advanced"]["gust"][0] = 99.0
        trial.candidate.parameter_json["schedule"]["points"][0] = 99.0
        trial.job.vehicle_profile_json["nested"]["motors"][0] = 99

        assert frozen.scenario_config == {
            "advanced": {"gust": [1.0, 2.0]},
            "scenario_weight": 2.0,
        }
        assert frozen.parameters["schedule"]["points"] == [0.1, 0.2]
        assert frozen.job_config.vehicle_profile["nested"]["motors"] == [
            1,
            2,
            3,
            4,
        ]


def test_simulator_result_is_rejected_when_inputs_drift_during_run(
    orchestration_ctx,
) -> None:
    """The terminal transaction re-locks claim inputs after external work."""

    ctx = orchestration_ctx
    trial_id = _seed_single_pending_trial(ctx)
    models = ctx["models"]

    class MidRunMutationAdapter(MockSimulatorAdapter):
        backend_name = "mid-run-input-drift"

        def run_trial(self, trial_ctx):
            with ctx["db_module"].SessionLocal() as other_db:
                other_trial = other_db.get(models.Trial, trial_id)
                assert other_trial is not None
                other_trial.job.wind_north = 12.5
                other_db.commit()
            return super().run_trial(trial_ctx)

    with ctx["db_module"].SessionLocal() as db:
        assert (
            ctx["trial_executor"].claim_and_run_one_pending_trial(
                db,
                "worker-mid-run-drift",
                adapter=MidRunMutationAdapter(),
            )
            == trial_id
        )

    with ctx["db_module"].SessionLocal() as db:
        trial = db.get(models.Trial, trial_id)
        assert trial is not None
        assert trial.status == "FAILED"
        assert trial.failure_code == "INPUT_EVIDENCE_DRIFT"
        assert trial.metric is None
        assert trial.accepted_attempt is not None
        assert trial.accepted_attempt.outcome is not None
        assert trial.accepted_attempt.outcome.outcome_class == "invalid_evidence"


def test_legacy_attempt_claim_without_combined_input_hash_still_verifies(
    orchestration_ctx,
) -> None:
    """The additive claim field preserves existing v1 content addresses."""

    module = orchestration_ctx["attempt_evidence"]
    payload = {
        "schema_id": "dronedream.trial-execution-attempt-claim/v1",
        "trial_id": "trial_legacy",
        "job_id": "job_legacy",
        "candidate_id": "candidate_legacy",
        "attempt_count": 1,
        "claim_kind": "initial",
        "worker_id_sha256": "1" * 64,
        "lease_token_sha256": "sha256:" + "2" * 64,
        "simulator_backend": "mock",
        "parameter_sha256": "sha256:" + "3" * 64,
        "scenario_sha256": "sha256:" + "4" * 64,
        "job_config_sha256": "sha256:" + "5" * 64,
        "claimed_at": "2026-07-27T00:00:00Z",
    }
    evidence = {
        "evidence_id": module._sha256_id(payload),
        **payload,
    }
    verified = module.verify_trial_attempt_claim(evidence)
    assert verified is not None
    assert verified.schema_id == (
        "dronedream.trial-execution-attempt-claim/v1"
    )
    assert not hasattr(verified, "execution_input_sha256")


def test_legacy_v1_claim_remains_accepted_end_to_end(
    orchestration_ctx,
) -> None:
    """A historical v1 receipt still authorizes its accepted Trial evidence."""

    ctx = orchestration_ctx
    trial_id = _seed_single_pending_trial(ctx)
    with ctx["db_module"].SessionLocal() as db:
        assert (
            ctx["trial_executor"].claim_and_run_one_pending_trial(
                db,
                "worker-v1-compatibility",
            )
            == trial_id
        )

    from app.storage.evidence import candidate_trial_artifact_evidence

    module = ctx["attempt_evidence"]
    with ctx["db_module"].SessionLocal() as db:
        trial = db.get(ctx["models"].Trial, trial_id)
        assert trial is not None
        assert trial.finished_at is not None
        attempt = trial.accepted_attempt
        assert attempt is not None
        outcome = attempt.outcome
        assert outcome is not None
        current_claim = module.verify_trial_attempt_claim(
            attempt.claim_evidence_json
        )
        assert current_claim is not None
        claim_payload = current_claim.model_dump(mode="json")
        claim_payload.pop("evidence_id")
        claim_payload.pop("execution_input_sha256")
        claim_payload.pop("candidate_contract_sha256")
        claim_payload.pop("scenario_contract_sha256")
        legacy_inputs = module._snapshot_trial_attempt_inputs_v2(
            trial=trial,
            job=trial.job,
            candidate=trial.candidate,
        )
        claim_payload["parameter_sha256"] = module._sha256_id(
            legacy_inputs["candidate_parameters"]
        )
        claim_payload["scenario_sha256"] = module._sha256_id(
            {
                "seed": legacy_inputs["trial"]["seed"],
                "scenario_type": legacy_inputs["trial"]["scenario_type"],
                "scenario_config": legacy_inputs["trial"][
                    "scenario_config"
                ],
            }
        )
        claim_payload["job_config_sha256"] = module._sha256_id(
            legacy_inputs["job_config"]
        )
        claim_payload["schema_id"] = (
            "dronedream.trial-execution-attempt-claim/v1"
        )
        legacy_claim_id = module._sha256_id(claim_payload)
        attempt.claim_evidence_id = legacy_claim_id
        attempt.claim_evidence_json = {
            "evidence_id": legacy_claim_id,
            **claim_payload,
        }

        artifact_mapping = candidate_trial_artifact_evidence(
            trial.candidate,
            [trial],
            verify_bytes=True,
        )
        assert artifact_mapping is not None
        artifact_evidence = artifact_mapping[trial.id]
        legacy_outcome = module._compile_attempt_outcome(
            attempt=attempt,
            terminal_status=trial.status,
            outcome_class=outcome.outcome_class,
            accepted=True,
            failure_code=trial.failure_code,
            metric_snapshot=module._metric_snapshot(trial),
            artifact_evidence=artifact_evidence,
            finished_at=trial.finished_at,
            superseded_by_attempt_count=None,
        )
        outcome.evidence_id = legacy_outcome.evidence_id
        outcome.evidence_json = legacy_outcome.model_dump(mode="json")

        assert module.trial_attempt_claim_matches_current_inputs(
            trial,
            attempt=attempt,
        )
        accepted = module.accepted_trial_attempt_evidence(
            trial,
            artifact_evidence=artifact_evidence,
        )
        assert accepted is not None
        assert accepted.claim_evidence_id == legacy_claim_id
        assert accepted.outcome_evidence_id == legacy_outcome.evidence_id


def test_legacy_v2_claim_remains_accepted_end_to_end(
    orchestration_ctx,
) -> None:
    """A historical v2 combined snapshot remains verifiable and admissible."""

    ctx = orchestration_ctx
    trial_id = _seed_single_pending_trial(ctx)
    with ctx["db_module"].SessionLocal() as db:
        assert (
            ctx["trial_executor"].claim_and_run_one_pending_trial(
                db,
                "worker-v2-compatibility",
            )
            == trial_id
        )

    from app.storage.evidence import candidate_trial_artifact_evidence

    module = ctx["attempt_evidence"]
    with ctx["db_module"].SessionLocal() as db:
        trial = db.get(ctx["models"].Trial, trial_id)
        assert trial is not None
        assert trial.finished_at is not None
        attempt = trial.accepted_attempt
        assert attempt is not None
        outcome = attempt.outcome
        assert outcome is not None
        current_claim = module.verify_trial_attempt_claim(
            attempt.claim_evidence_json
        )
        assert current_claim is not None
        legacy_inputs = module._snapshot_trial_attempt_inputs_v2(
            trial=trial,
            job=trial.job,
            candidate=trial.candidate,
        )
        claim_payload = current_claim.model_dump(mode="json")
        claim_payload.pop("evidence_id")
        claim_payload.pop("candidate_contract_sha256")
        claim_payload.pop("scenario_contract_sha256")
        claim_payload["schema_id"] = (
            "dronedream.trial-execution-attempt-claim/v2"
        )
        claim_payload["parameter_sha256"] = module._sha256_id(
            legacy_inputs["candidate_parameters"]
        )
        claim_payload["scenario_sha256"] = module._sha256_id(
            {
                "seed": legacy_inputs["trial"]["seed"],
                "scenario_type": legacy_inputs["trial"]["scenario_type"],
                "scenario_config": legacy_inputs["trial"][
                    "scenario_config"
                ],
            }
        )
        claim_payload["job_config_sha256"] = module._sha256_id(
            legacy_inputs["job_config"]
        )
        claim_payload["execution_input_sha256"] = module._sha256_id(
            legacy_inputs
        )
        legacy_claim_id = module._sha256_id(claim_payload)
        attempt.claim_evidence_id = legacy_claim_id
        attempt.claim_evidence_json = {
            "evidence_id": legacy_claim_id,
            **claim_payload,
        }

        artifact_mapping = candidate_trial_artifact_evidence(
            trial.candidate,
            [trial],
            verify_bytes=True,
        )
        assert artifact_mapping is not None
        artifact_evidence = artifact_mapping[trial.id]
        legacy_outcome = module._compile_attempt_outcome(
            attempt=attempt,
            terminal_status=trial.status,
            outcome_class=outcome.outcome_class,
            accepted=True,
            failure_code=trial.failure_code,
            metric_snapshot=module._metric_snapshot(trial),
            artifact_evidence=artifact_evidence,
            finished_at=trial.finished_at,
            superseded_by_attempt_count=None,
        )
        outcome.evidence_id = legacy_outcome.evidence_id
        outcome.evidence_json = legacy_outcome.model_dump(mode="json")

        assert module.trial_attempt_claim_matches_current_inputs(
            trial,
            attempt=attempt,
        )
        accepted = module.accepted_trial_attempt_evidence(
            trial,
            artifact_evidence=artifact_evidence,
        )
        assert accepted is not None
        assert accepted.claim_evidence_id == legacy_claim_id


def test_configured_scenario_contract_is_checked_before_simulator(
    orchestration_ctx,
) -> None:
    """A pre-claim payload mutation is quarantined without simulator I/O."""

    ctx = orchestration_ctx
    schemas = ctx["schemas"]
    models = ctx["models"]
    with ctx["db_module"].SessionLocal() as db:
        job = ctx["jobs_service"].create_job(
            db,
            schemas.JobCreateRequest(
                simulator_backend="mock",
                optimizer_strategy="none",
                scenario_suite=schemas.ScenarioSuiteConfig(
                    cases=[
                        schemas.ScenarioCaseConfig(
                            id="nominal",
                            seeds=[101],
                            config={"wind_mps": 0},
                        )
                    ]
                ),
            ),
        )
        job_id = job.id
    with ctx["db_module"].SessionLocal() as db:
        assert ctx["job_manager"].start_queued_jobs(db) == [job_id]
        trial = db.scalar(
            select(models.Trial).where(models.Trial.job_id == job_id)
        )
        assert trial is not None
        payload = dict(trial.scenario_config_json or {})
        payload["scenario_weight"] = 99.0
        trial.scenario_config_json = payload
        db.commit()
        trial_id = trial.id

    class NeverStartedAdapter:
        backend_name = "scenario-contract-probe"

        def __init__(self) -> None:
            self.prepare_calls = 0
            self.run_calls = 0
            self.cleanup_calls = 0

        def prepare(self, _ctx) -> None:
            self.prepare_calls += 1

        def run_trial(self, _ctx):
            self.run_calls += 1
            raise AssertionError("invalid scenario must not run")

        def cleanup(self, _ctx) -> None:
            self.cleanup_calls += 1

    adapter = NeverStartedAdapter()
    with ctx["db_module"].SessionLocal() as db:
        assert (
            ctx["trial_executor"].claim_and_run_one_pending_trial(
                db,
                "worker-scenario-contract",
                adapter=adapter,
            )
            == trial_id
        )

    assert adapter.prepare_calls == 0
    assert adapter.run_calls == 0
    assert adapter.cleanup_calls == 0
    with ctx["db_module"].SessionLocal() as db:
        trial = db.get(models.Trial, trial_id)
        assert trial is not None
        assert trial.status == "FAILED"
        assert trial.failure_code == "SCENARIO_CONTRACT_DRIFT"
        assert trial.accepted_attempt is not None
        assert trial.accepted_attempt.outcome is not None
        assert (
            trial.accepted_attempt.outcome.outcome_class
            == "invalid_evidence"
        )


def test_valid_configured_scenario_contract_executes_normally(
    orchestration_ctx,
) -> None:
    """The strict gate admits an untouched authoritative dispatch."""

    ctx = orchestration_ctx
    schemas = ctx["schemas"]
    models = ctx["models"]
    with ctx["db_module"].SessionLocal() as db:
        job = ctx["jobs_service"].create_job(
            db,
            schemas.JobCreateRequest(
                simulator_backend="mock",
                optimizer_strategy="none",
                advanced_scenario_config={
                    "wind_gusts": {
                        "enabled": True,
                        "magnitude_mps": 2.0,
                    }
                },
                scenario_suite=schemas.ScenarioSuiteConfig(
                    cases=[
                        schemas.ScenarioCaseConfig(
                            id="wind",
                            scenario_type="wind_perturbed",
                            seeds=[202],
                            weight=2.0,
                            config={"wind_mps": 6},
                        )
                    ]
                ),
            ),
        )
        job_id = job.id
    with ctx["db_module"].SessionLocal() as db:
        assert ctx["job_manager"].start_queued_jobs(db) == [job_id]
        trial = db.scalar(
            select(models.Trial).where(models.Trial.job_id == job_id)
        )
        assert trial is not None
        trial_id = trial.id
    with ctx["db_module"].SessionLocal() as db:
        assert (
            ctx["trial_executor"].claim_and_run_one_pending_trial(
                db,
                "worker-valid-scenario-contract",
            )
            == trial_id
        )
    with ctx["db_module"].SessionLocal() as db:
        trial = db.get(models.Trial, trial_id)
        assert trial is not None
        assert trial.status == "COMPLETED"
        assert trial.failure_code is None
        assert trial.metric is not None
        assert trial.accepted_attempt is not None
        claim = ctx["attempt_evidence"].verify_trial_attempt_claim(
            trial.accepted_attempt.claim_evidence_json
        )
        assert claim is not None
        assert claim.schema_id == (
            "dronedream.trial-execution-attempt-claim/v3"
        )


def test_trial_gate_rejects_coordinated_job_and_scenario_rewrite(
    orchestration_ctx,
) -> None:
    """Matching rewritten rows still cannot replace the creation-time contract."""

    ctx = orchestration_ctx
    schemas = ctx["schemas"]
    models = ctx["models"]
    with ctx["db_module"].SessionLocal() as db:
        job = ctx["jobs_service"].create_job(
            db,
            schemas.JobCreateRequest(
                simulator_backend="mock",
                optimizer_strategy="none",
                scenario_suite=schemas.ScenarioSuiteConfig(
                    cases=[
                        schemas.ScenarioCaseConfig(
                            id="nominal",
                            seeds=[303],
                            weight=1.0,
                        )
                    ]
                ),
            ),
        )
        job_id = job.id
    with ctx["db_module"].SessionLocal() as db:
        assert ctx["job_manager"].start_queued_jobs(db) == [job_id]
        job = db.get(models.Job, job_id)
        assert job is not None
        trial = db.scalar(
            select(models.Trial).where(models.Trial.job_id == job_id)
        )
        assert trial is not None
        rewritten_suite = dict(job.scenario_suite_json or {})
        rewritten_cases = [
            dict(case) for case in rewritten_suite.get("cases", [])
        ]
        rewritten_cases[0]["weight"] = 3.0
        rewritten_suite["cases"] = rewritten_cases
        job.scenario_suite_json = rewritten_suite
        rewritten_trial = dict(trial.scenario_config_json or {})
        rewritten_trial["scenario_weight"] = 3.0
        trial.scenario_config_json = rewritten_trial
        db.commit()
        trial_id = trial.id

    class NeverStartedAdapter:
        backend_name = "coordinated-contract-rewrite-probe"

        def prepare(self, _ctx) -> None:
            raise AssertionError("rewritten contract must not prepare")

        def run_trial(self, _ctx):
            raise AssertionError("rewritten contract must not run")

        def cleanup(self, _ctx) -> None:
            raise AssertionError("rewritten contract must not clean up")

    with ctx["db_module"].SessionLocal() as db:
        assert (
            ctx["trial_executor"].claim_and_run_one_pending_trial(
                db,
                "worker-coordinated-contract-rewrite",
                adapter=NeverStartedAdapter(),
            )
            == trial_id
        )
    with ctx["db_module"].SessionLocal() as db:
        trial = db.get(models.Trial, trial_id)
        assert trial is not None
        assert trial.status == "FAILED"
        assert trial.failure_code == "OUTCOME_CONTRACT_DRIFT"
        assert trial.accepted_attempt is not None
        assert trial.accepted_attempt.outcome is not None
        assert (
            trial.accepted_attempt.outcome.outcome_class
            == "invalid_evidence"
        )


def test_claim_v3_detects_candidate_contract_drift(
    orchestration_ctx,
    monkeypatch,
) -> None:
    """Candidate generation/source metadata cannot change after claim."""

    ctx = orchestration_ctx
    trial_id = _seed_single_pending_trial(ctx)
    models = ctx["models"]
    original_record_event = ctx["trial_executor"].record_event

    def mutate_candidate_contract(db, job_id, event_type, payload):
        if event_type == "trial_claimed":
            with ctx["db_module"].SessionLocal() as other_db:
                trial = other_db.get(models.Trial, trial_id)
                assert trial is not None
                trial.candidate.generation_index = 12
                trial.candidate.source_type = "optimizer"
                trial.candidate.optimizer_metadata_json = {
                    "fidelity": 0.5
                }
                other_db.commit()
        return original_record_event(db, job_id, event_type, payload)

    monkeypatch.setattr(
        ctx["trial_executor"],
        "record_event",
        mutate_candidate_contract,
    )
    with ctx["db_module"].SessionLocal() as db:
        assert (
            ctx["trial_executor"].claim_and_run_one_pending_trial(
                db,
                "worker-candidate-contract",
            )
            == trial_id
        )

    with ctx["db_module"].SessionLocal() as db:
        trial = db.get(models.Trial, trial_id)
        assert trial is not None
        assert trial.status == "FAILED"
        assert trial.failure_code == "INPUT_EVIDENCE_DRIFT"
        attempt = trial.accepted_attempt
        assert attempt is not None
        claim = ctx["attempt_evidence"].verify_trial_attempt_claim(
            attempt.claim_evidence_json
        )
        assert claim is not None
        assert claim.schema_id == (
            "dronedream.trial-execution-attempt-claim/v3"
        )


def test_completion_fence_locks_job_before_updating_trial(
    orchestration_ctx,
) -> None:
    """Completion follows cancellation's Job-before-Trial lock order."""

    ctx = orchestration_ctx
    trial_id = _seed_single_pending_trial(ctx)
    with ctx["db_module"].SessionLocal() as db:
        trial = db.get(ctx["models"].Trial, trial_id)
        assert trial is not None
        trial.status = "RUNNING"
        trial.worker_id = "worker-lock-order"
        trial.lease_owner = "worker-lock-order"
        trial.lease_expires_at = datetime.now(timezone.utc) + timedelta(
            minutes=5
        )
        trial.attempt_count = 1
        db.commit()

        statements: list[str] = []

        def capture_statement(
            _connection,
            _cursor,
            statement,
            _parameters,
            _context,
            _executemany,
        ) -> None:
            statements.append(" ".join(statement.lower().split()))

        event.listen(
            db.get_bind(),
            "before_cursor_execute",
            capture_statement,
        )
        try:
            acquired = ctx[
                "trial_executor"
            ]._acquire_completion_fence(
                db,
                ctx["trial_executor"]._TrialLeaseToken(
                    trial_id=trial_id,
                    worker_id="worker-lock-order",
                    attempt_count=1,
                ),
                lease_seconds=300,
            )
        finally:
            event.remove(
                db.get_bind(),
                "before_cursor_execute",
                capture_statement,
            )

        assert acquired is True
        job_lock_index = next(
            index
            for index, statement in enumerate(statements)
            if statement.startswith("select")
            and " from jobs " in f" {statement} "
        )
        trial_update_index = next(
            index
            for index, statement in enumerate(statements)
            if statement.startswith("update trials ")
        )
        assert job_lock_index < trial_update_index


def test_claim_returns_none_when_no_pending(orchestration_ctx):
    ctx = orchestration_ctx
    with ctx["db_module"].SessionLocal() as db:
        trial_id = ctx["trial_executor"].claim_and_run_one_pending_trial(db, "test-worker")
    assert trial_id is None


def _seed_single_pending_trial(ctx: dict[str, object]) -> str:
    models = ctx["models"]
    with ctx["db_module"].SessionLocal() as db:
        user = models.User(display_name="u")
        db.add(user)
        db.flush()
        job = models.Job(
            user_id=user.id,
            track_type="circle",
            altitude_m=3.0,
            sensor_noise_level="medium",
            objective_profile="robust",
            status="RUNNING",
            simulator_backend_requested="mock",
        )
        db.add(job)
        db.flush()
        cand = models.CandidateParameterSet(job_id=job.id, parameter_json={"kp_xy": 1.0})
        db.add(cand)
        db.flush()
        trial = models.Trial(job_id=job.id, candidate_id=cand.id, status="PENDING")
        db.add(trial)
        db.commit()
        return trial.id


def _seed_pending_trial_pool(ctx: dict[str, object], *, count: int) -> list[str]:
    first_trial_id = _seed_single_pending_trial(ctx)
    models = ctx["models"]
    trial_ids = [first_trial_id]
    with ctx["db_module"].SessionLocal() as db:
        first_trial = db.get(models.Trial, first_trial_id)
        assert first_trial is not None
        for seed in range(1, count):
            trial = models.Trial(
                job_id=first_trial.job_id,
                candidate_id=first_trial.candidate_id,
                seed=seed,
                status="PENDING",
            )
            db.add(trial)
            db.flush()
            trial_ids.append(trial.id)
        db.commit()
    return trial_ids


def test_pending_trial_claim_is_single_winner(orchestration_ctx):
    ctx = orchestration_ctx
    trial_id = _seed_single_pending_trial(ctx)
    with ctx["db_module"].SessionLocal() as db1:
        claimed1 = ctx["trial_executor"].claim_and_run_one_pending_trial(db1, "worker-a")
    with ctx["db_module"].SessionLocal() as db2:
        claimed2 = ctx["trial_executor"].claim_and_run_one_pending_trial(db2, "worker-b")
    assert {claimed1, claimed2} == {trial_id, None}
    with ctx["db_module"].SessionLocal() as db:
        trial = db.get(ctx["models"].Trial, trial_id)
        assert trial is not None
        assert trial.claimed_at is not None
        event_types = [e.event_type for e in trial.job.events]
        assert "trial_claimed" in event_types


def test_pending_trial_claims_are_fair_across_jobs(orchestration_ctx):
    """A large experiment must not monopolize a sequential worker queue."""

    ctx = orchestration_ctx
    first_job_trials = _seed_pending_trial_pool(ctx, count=3)
    second_job_trials = _seed_pending_trial_pool(ctx, count=3)
    all_trial_ids = first_job_trials + second_job_trials
    claimed_trial_ids: list[str] = []

    for worker_number in range(len(all_trial_ids)):
        with ctx["db_module"].SessionLocal() as db:
            claimed = ctx["trial_executor"].claim_and_run_one_pending_trial(
                db,
                f"fair-worker-{worker_number}",
            )
        assert claimed is not None
        claimed_trial_ids.append(claimed)

    models = ctx["models"]
    with ctx["db_module"].SessionLocal() as db:
        job_by_trial = {
            trial.id: trial.job_id
            for trial in db.scalars(
                select(models.Trial).where(models.Trial.id.in_(all_trial_ids))
            )
        }

    claimed_job_ids = [job_by_trial[trial_id] for trial_id in claimed_trial_ids]
    assert len(set(claimed_job_ids)) == 2
    assert claimed_job_ids[0] != claimed_job_ids[1]
    assert claimed_job_ids[0::2] == [claimed_job_ids[0]] * 3
    assert claimed_job_ids[1::2] == [claimed_job_ids[1]] * 3


def test_simultaneous_workers_create_one_physical_attempt(orchestration_ctx):
    """A concurrent claim race must execute and accept exactly one attempt."""

    ctx = orchestration_ctx
    trial_id = _seed_single_pending_trial(ctx)
    worker_count = 8
    start_barrier = threading.Barrier(worker_count + 1)
    simulator_entered = threading.Event()
    release_simulator = threading.Event()
    competitors_finished = threading.Event()
    result_lock = threading.Lock()
    adapter_lock = threading.Lock()
    results: list[str | None] = []
    errors: list[BaseException] = []
    simulator_calls = 0

    class CoordinatedAdapter(MockSimulatorAdapter):
        backend_name = "concurrent-claim-mock"

        def run_trial(self, trial_ctx: TrialContext) -> TrialResult:
            nonlocal simulator_calls
            with adapter_lock:
                simulator_calls += 1
            simulator_entered.set()
            release_simulator.wait(timeout=10)
            return super().run_trial(trial_ctx)

    adapter = CoordinatedAdapter()

    def compete(worker_number: int) -> None:
        try:
            start_barrier.wait()
            with ctx["db_module"].SessionLocal() as worker_db:
                claimed = ctx["trial_executor"].claim_and_run_one_pending_trial(
                    worker_db,
                    f"simultaneous-worker-{worker_number}",
                    adapter=adapter,
                )
            with result_lock:
                results.append(claimed)
                if len(results) + len(errors) >= worker_count - 1:
                    competitors_finished.set()
        except BaseException as exc:
            with result_lock:
                errors.append(exc)
                if len(results) + len(errors) >= worker_count - 1:
                    competitors_finished.set()

    workers = [
        threading.Thread(target=compete, args=(index,), daemon=True)
        for index in range(worker_count)
    ]
    for worker in workers:
        worker.start()

    start_barrier.wait()
    try:
        assert simulator_entered.wait(timeout=10), "no worker reached the simulator"
        assert competitors_finished.wait(timeout=10), (
            "competing workers did not settle while the winning execution was fenced"
        )
    finally:
        release_simulator.set()
        for worker in workers:
            worker.join(timeout=10)

    assert all(not worker.is_alive() for worker in workers)
    assert errors == []
    assert results.count(trial_id) == 1
    assert results.count(None) == worker_count - 1
    assert simulator_calls == 1

    models = ctx["models"]
    with ctx["db_module"].SessionLocal() as db:
        trial = db.get(models.Trial, trial_id)
        assert trial is not None
        assert trial.status == "COMPLETED"
        assert trial.attempt_count == 1
        assert trial.metric is not None
        assert trial.accepted_attempt_id is not None
        assert len(trial.execution_attempts) == 1
        attempt = trial.execution_attempts[0]
        assert attempt.id == trial.accepted_attempt_id
        assert attempt.attempt_count == 1
        assert attempt.claim_evidence_json["schema_id"] == (
            "dronedream.trial-execution-attempt-claim/v3"
        )
        assert attempt.outcome is not None
        assert attempt.outcome.accepted is True
        assert attempt.outcome.terminal_status == "COMPLETED"
        assert attempt.outcome.outcome_class == "success"
        claim_events = [
            event for event in trial.job.events if event.event_type == "trial_claimed"
        ]
        assert len(claim_events) == 1


def test_simultaneous_workers_drain_distinct_pending_pool(orchestration_ctx):
    """Claim collisions must not strand workers while other Trials are pending."""

    ctx = orchestration_ctx
    worker_count = 8
    trial_ids = _seed_pending_trial_pool(ctx, count=worker_count)
    start_barrier = threading.Barrier(worker_count + 1)
    all_simulators_entered = threading.Event()
    release_simulators = threading.Event()
    result_lock = threading.Lock()
    adapter_lock = threading.Lock()
    results: list[str | None] = []
    errors: list[BaseException] = []
    simulator_calls = 0

    class PoolAdapter(MockSimulatorAdapter):
        backend_name = "concurrent-pool-mock"

        def run_trial(self, trial_ctx: TrialContext) -> TrialResult:
            nonlocal simulator_calls
            with adapter_lock:
                simulator_calls += 1
                if simulator_calls == worker_count:
                    all_simulators_entered.set()
            release_simulators.wait(timeout=10)
            return super().run_trial(trial_ctx)

    adapter = PoolAdapter()

    def compete(worker_number: int) -> None:
        try:
            start_barrier.wait()
            with ctx["db_module"].SessionLocal() as worker_db:
                claimed = ctx["trial_executor"].claim_and_run_one_pending_trial(
                    worker_db,
                    f"pool-worker-{worker_number}",
                    adapter=adapter,
                )
            with result_lock:
                results.append(claimed)
        except BaseException as exc:
            with result_lock:
                errors.append(exc)

    workers = [
        threading.Thread(target=compete, args=(index,), daemon=True)
        for index in range(worker_count)
    ]
    for worker in workers:
        worker.start()

    start_barrier.wait()
    try:
        assert all_simulators_entered.wait(timeout=10), (
            "claim collisions left runnable Trials in the pending pool"
        )
    finally:
        release_simulators.set()
        for worker in workers:
            worker.join(timeout=10)

    assert all(not worker.is_alive() for worker in workers)
    assert errors == []
    assert simulator_calls == worker_count
    assert None not in results
    assert len(results) == worker_count
    assert set(results) == set(trial_ids)

    models = ctx["models"]
    with ctx["db_module"].SessionLocal() as db:
        trials = list(
            db.scalars(select(models.Trial).where(models.Trial.id.in_(trial_ids)))
        )
        assert len(trials) == worker_count
        assert all(trial.status == "COMPLETED" for trial in trials)
        assert all(trial.attempt_count == 1 for trial in trials)
        assert all(trial.metric is not None for trial in trials)
        attempts = [trial.execution_attempts[0] for trial in trials]
        assert len({attempt.id for attempt in attempts}) == worker_count
        assert len({attempt.claim_evidence_id for attempt in attempts}) == worker_count
        assert all(attempt.outcome is not None for attempt in attempts)
        assert all(attempt.outcome.accepted is True for attempt in attempts)
        assert len({attempt.outcome.evidence_id for attempt in attempts}) == worker_count


def test_running_trial_reclaimed_after_lease_expiry(orchestration_ctx):
    ctx = orchestration_ctx
    trial_id = _seed_single_pending_trial(ctx)
    models = ctx["models"]
    with ctx["db_module"].SessionLocal() as db:
        trial = db.get(models.Trial, trial_id)
        assert trial is not None
        trial.status = "RUNNING"
        trial.worker_id = "worker-a"
        trial.lease_owner = "worker-a"
        trial.lease_expires_at = datetime.now(timezone.utc) - timedelta(seconds=5)
        db.commit()
    with ctx["db_module"].SessionLocal() as db:
        claimed = ctx["trial_executor"].claim_and_run_one_pending_trial(db, "worker-b")
        assert claimed == trial_id
    with ctx["db_module"].SessionLocal() as db:
        trial = db.get(models.Trial, trial_id)
        assert trial is not None
        assert trial.lease_owner is None
        assert trial.lease_expires_at is None
        event_types = [e.event_type for e in trial.job.events]
        assert "trial_reclaimed_from_stale_worker" in event_types


def test_unexpired_lease_blocks_second_worker(orchestration_ctx):
    ctx = orchestration_ctx
    trial_id = _seed_single_pending_trial(ctx)
    models = ctx["models"]
    with ctx["db_module"].SessionLocal() as db:
        trial = db.get(models.Trial, trial_id)
        assert trial is not None
        trial.lease_owner = "worker-a"
        trial.lease_expires_at = datetime.now(timezone.utc) + timedelta(minutes=5)
        db.commit()
    with ctx["db_module"].SessionLocal() as db:
        claimed = ctx["trial_executor"].claim_and_run_one_pending_trial(db, "worker-b")
    assert claimed is None


def test_long_trial_renews_lease_while_simulator_runs(orchestration_ctx, monkeypatch):
    ctx = orchestration_ctx
    trial_id = _seed_single_pending_trial(ctx)
    monkeypatch.setenv("WORKER_LEASE_SECONDS", "1")
    monkeypatch.setenv("WORKER_LEASE_HEARTBEAT_SECONDS", "0.05")

    from app.config import get_settings

    get_settings.cache_clear()

    class SlowAdapter(MockSimulatorAdapter):
        backend_name = "slow-mock"

        def __init__(self) -> None:
            self.before = None
            self.after = None

        def prepare(self, trial_ctx: TrialContext) -> None:
            with ctx["db_module"].SessionLocal() as heartbeat_db:
                row = heartbeat_db.get(ctx["models"].Trial, trial_ctx.trial_id)
                self.before = row.lease_expires_at

        def run_trial(self, trial_ctx: TrialContext) -> TrialResult:
            time.sleep(0.35)
            with ctx["db_module"].SessionLocal() as heartbeat_db:
                row = heartbeat_db.get(ctx["models"].Trial, trial_ctx.trial_id)
                self.after = row.lease_expires_at
            return super().run_trial(trial_ctx)

    adapter = SlowAdapter()
    try:
        with ctx["db_module"].SessionLocal() as db:
            claimed = ctx["trial_executor"].claim_and_run_one_pending_trial(
                db, "worker-heartbeat", adapter=adapter
            )
        assert claimed == trial_id
        assert adapter.before is not None
        assert adapter.after is not None
        assert adapter.after > adapter.before
    finally:
        get_settings.cache_clear()


def test_process_control_exception_from_cleanup_stops_lease_heartbeat(
    orchestration_ctx, monkeypatch: pytest.MonkeyPatch
) -> None:
    ctx = orchestration_ctx
    trial_id = _seed_single_pending_trial(ctx)
    heartbeat_state = SimpleNamespace(started=False, stopped=False)

    class FakeHeartbeat:
        def __init__(self, *_args, **_kwargs) -> None:
            self.lost = SimpleNamespace(is_set=lambda: False)

        def start(self) -> None:
            heartbeat_state.started = True

        def stop(self) -> None:
            heartbeat_state.stopped = True

    class InterruptingCleanupAdapter(MockSimulatorAdapter):
        def cleanup(self, _trial_ctx: TrialContext) -> None:
            raise SystemExit(23)

    monkeypatch.setattr(ctx["trial_executor"], "_TrialLeaseHeartbeat", FakeHeartbeat)

    with ctx["db_module"].SessionLocal() as db, pytest.raises(SystemExit, match="23"):
        ctx["trial_executor"].claim_and_run_one_pending_trial(
            db,
            "worker-interrupted-cleanup",
            adapter=InterruptingCleanupAdapter(),
        )

    assert heartbeat_state.started is True
    assert heartbeat_state.stopped is True
    with ctx["db_module"].SessionLocal() as db:
        trial = db.get(ctx["models"].Trial, trial_id)
        assert trial is not None
        assert trial.status == "RUNNING"
        assert trial.failure_code is None


def test_reclaimed_attempt_fences_stale_result_persistence(orchestration_ctx):
    ctx = orchestration_ctx
    trial_id = _seed_single_pending_trial(ctx)

    class ReclaimingAdapter(MockSimulatorAdapter):
        backend_name = "reclaiming-mock"

        def run_trial(self, trial_ctx: TrialContext) -> TrialResult:
            with ctx["db_module"].SessionLocal() as reclaim_db:
                row = reclaim_db.get(ctx["models"].Trial, trial_ctx.trial_id)
                row.worker_id = "worker-new"
                row.lease_owner = "worker-new"
                row.attempt_count += 1
                row.lease_expires_at = datetime.now(timezone.utc) + timedelta(minutes=5)
                reclaim_db.commit()
            return super().run_trial(trial_ctx)

    with ctx["db_module"].SessionLocal() as db:
        claimed = ctx["trial_executor"].claim_and_run_one_pending_trial(
            db, "worker-old", adapter=ReclaimingAdapter()
        )
    assert claimed == trial_id

    with ctx["db_module"].SessionLocal() as db:
        trial = db.get(ctx["models"].Trial, trial_id)
        assert trial.status == "RUNNING"
        assert trial.lease_owner == "worker-new"
        assert trial.attempt_count == 2
        assert trial.metric is None
        assert trial.accepted_attempt_id is None
        assert len(trial.execution_attempts) == 1
        stale_attempt = trial.execution_attempts[0]
        assert stale_attempt.outcome is not None
        assert stale_attempt.outcome.accepted is False
        assert stale_attempt.outcome.terminal_status == "SUPERSEDED"
        assert (
            stale_attempt.outcome.evidence_json["superseded_by_attempt_count"]
            == 2
        )


def test_interrupted_attempt_is_superseded_and_reclaim_is_accepted(
    orchestration_ctx,
) -> None:
    ctx = orchestration_ctx
    trial_id = _seed_single_pending_trial(ctx)

    class InterruptingCleanupAdapter(MockSimulatorAdapter):
        def cleanup(self, _trial_ctx: TrialContext) -> None:
            raise SystemExit(41)

    with ctx["db_module"].SessionLocal() as db, pytest.raises(
        SystemExit,
        match="41",
    ):
        ctx["trial_executor"].claim_and_run_one_pending_trial(
            db,
            "worker-interrupted",
            adapter=InterruptingCleanupAdapter(),
        )

    with ctx["db_module"].SessionLocal() as db:
        trial = db.get(ctx["models"].Trial, trial_id)
        assert trial is not None
        assert len(trial.execution_attempts) == 1
        assert trial.execution_attempts[0].outcome is None
        trial.lease_expires_at = datetime.now(timezone.utc) - timedelta(
            seconds=1
        )
        db.commit()

    with ctx["db_module"].SessionLocal() as db:
        assert (
            ctx["trial_executor"].claim_and_run_one_pending_trial(
                db,
                "worker-reclaim",
                adapter=MockSimulatorAdapter(),
            )
            == trial_id
        )

    with ctx["db_module"].SessionLocal() as db:
        trial = db.get(ctx["models"].Trial, trial_id)
        assert trial is not None
        assert trial.status == "COMPLETED"
        assert trial.accepted_attempt_id is not None
        attempts = sorted(
            trial.execution_attempts,
            key=lambda item: item.attempt_count,
        )
        assert [item.attempt_count for item in attempts] == [1, 2]
        assert attempts[0].outcome is not None
        assert attempts[0].outcome.accepted is False
        assert attempts[0].outcome.outcome_class == "superseded"
        assert attempts[1].outcome is not None
        assert attempts[1].outcome.accepted is True
        assert attempts[1].id == trial.accepted_attempt_id


def test_accepted_attempt_evidence_fails_after_input_or_metric_mutation(
    orchestration_ctx,
) -> None:
    ctx = orchestration_ctx
    trial_id = _seed_single_pending_trial(ctx)
    with ctx["db_module"].SessionLocal() as db:
        assert (
            ctx["trial_executor"].claim_and_run_one_pending_trial(
                db,
                "worker-evidence",
            )
            == trial_id
        )

    from app.storage.evidence import candidate_trial_artifact_evidence

    with ctx["db_module"].SessionLocal() as db:
        trial = db.get(ctx["models"].Trial, trial_id)
        assert trial is not None
        artifact_evidence = candidate_trial_artifact_evidence(
            trial.candidate,
            [trial],
            verify_bytes=True,
        )
        assert artifact_evidence is not None
        current_artifacts = artifact_evidence[trial.id]
        assert (
            ctx["attempt_evidence"].accepted_trial_attempt_evidence(
                trial,
                artifact_evidence=current_artifacts,
            )
            is not None
        )

        trial.candidate.parameter_json = {"kp_xy": 1.25}
        assert (
            ctx["attempt_evidence"].accepted_trial_attempt_evidence(
                trial,
                artifact_evidence=current_artifacts,
            )
            is None
        )
        trial.candidate.parameter_json = {"kp_xy": 1.0}
        assert trial.metric is not None
        trial.metric.score = float(trial.metric.score or 0.0) + 1.0
        assert (
            ctx["attempt_evidence"].accepted_trial_attempt_evidence(
                trial,
                artifact_evidence=current_artifacts,
            )
            is None
        )


def test_attempt_ledger_rows_and_accepted_pointer_are_append_only(
    orchestration_ctx,
) -> None:
    ctx = orchestration_ctx
    trial_id = _seed_single_pending_trial(ctx)
    with ctx["db_module"].SessionLocal() as db:
        assert (
            ctx["trial_executor"].claim_and_run_one_pending_trial(
                db,
                "worker-immutable",
            )
            == trial_id
        )

    models = ctx["models"]
    with ctx["db_module"].SessionLocal() as db:
        trial = db.get(models.Trial, trial_id)
        assert trial is not None
        attempt = trial.accepted_attempt
        assert attempt is not None
        assert attempt.outcome is not None

        with pytest.raises(DatabaseError):
            db.execute(
                update(models.TrialExecutionAttempt)
                .where(models.TrialExecutionAttempt.id == attempt.id)
                .values(simulator_backend="tampered")
            )
            db.commit()
        db.rollback()

        with pytest.raises(DatabaseError):
            db.execute(
                update(models.TrialExecutionAttemptOutcome)
                .where(
                    models.TrialExecutionAttemptOutcome.id
                    == attempt.outcome.id
                )
                .values(outcome_class="tampered")
            )
            db.commit()
        db.rollback()

        with pytest.raises(DatabaseError):
            db.execute(
                update(models.Trial)
                .where(models.Trial.id == trial_id)
                .values(accepted_attempt_id=None)
            )
            db.commit()
        db.rollback()

        other_trial = models.Trial(
            job_id=trial.job_id,
            candidate_id=trial.candidate_id,
            status="PENDING",
        )
        db.add(other_trial)
        db.commit()
        with pytest.raises(DatabaseError):
            db.execute(
                update(models.Trial)
                .where(models.Trial.id == other_trial.id)
                .values(accepted_attempt_id=attempt.id)
            )
            db.commit()
        db.rollback()


def test_authorized_job_delete_removes_attempt_ledger(orchestration_ctx) -> None:
    ctx = orchestration_ctx
    trial_id = _seed_single_pending_trial(ctx)
    with ctx["db_module"].SessionLocal() as db:
        assert (
            ctx["trial_executor"].claim_and_run_one_pending_trial(
                db,
                "worker-delete",
            )
            == trial_id
        )

    models = ctx["models"]
    with ctx["db_module"].SessionLocal() as db:
        trial = db.get(models.Trial, trial_id)
        assert trial is not None
        job_id = trial.job_id
        trial.job.status = "COMPLETED"
        db.commit()
        assert ctx["jobs_service"].delete_job(db, job_id) == {
            "id": job_id,
            "deleted": True,
        }

    with ctx["db_module"].SessionLocal() as db:
        assert (
            db.scalar(
                select(models.TrialExecutionAttempt).where(
                    models.TrialExecutionAttempt.trial_id == trial_id
                )
            )
            is None
        )


def test_cancel_job_seals_an_open_physical_attempt(orchestration_ctx) -> None:
    ctx = orchestration_ctx
    trial_id = _seed_single_pending_trial(ctx)

    class InterruptingCleanupAdapter(MockSimulatorAdapter):
        def cleanup(self, _trial_ctx: TrialContext) -> None:
            raise SystemExit(52)

    with ctx["db_module"].SessionLocal() as db, pytest.raises(
        SystemExit,
        match="52",
    ):
        ctx["trial_executor"].claim_and_run_one_pending_trial(
            db,
            "worker-cancel",
            adapter=InterruptingCleanupAdapter(),
        )

    with ctx["db_module"].SessionLocal() as db:
        trial = db.get(ctx["models"].Trial, trial_id)
        assert trial is not None
        ctx["jobs_service"].cancel_job(db, trial.job_id)

    with ctx["db_module"].SessionLocal() as db:
        trial = db.get(ctx["models"].Trial, trial_id)
        assert trial is not None
        assert trial.status == "CANCELLED"
        assert trial.accepted_attempt_id is not None
        attempt = trial.accepted_attempt
        assert attempt is not None
        assert attempt.outcome is not None
        assert attempt.outcome.accepted is True
        assert attempt.outcome.terminal_status == "CANCELLED"
        assert attempt.outcome.outcome_class == "cancelled"


def test_real_cli_artifacts_are_persisted_before_transient_run_cleanup(
    orchestration_ctx, monkeypatch, tmp_path
):
    ctx = orchestration_ctx
    trial_id = _seed_single_pending_trial(ctx)
    run_root = tmp_path / "transient-runs"
    durable_root = tmp_path / "durable-artifacts"
    monkeypatch.setenv("REAL_SIMULATOR_COMMAND", f'"{sys.executable}" "{_EXAMPLE_SIM}"')
    monkeypatch.setenv("REAL_SIMULATOR_ARTIFACT_ROOT", str(run_root))
    monkeypatch.setenv("REAL_SIMULATOR_KEEP_RUN_DIRS", "false")
    monkeypatch.setenv("ARTIFACT_ROOT", str(durable_root))

    from app.config import get_settings

    get_settings.cache_clear()
    try:
        with ctx["db_module"].SessionLocal() as db:
            claimed = ctx["trial_executor"].claim_and_run_one_pending_trial(
                db,
                "worker-real-cli",
                adapter=RealCliSimulatorAdapter(),
            )
        assert claimed == trial_id

        with ctx["db_module"].SessionLocal() as db:
            models = ctx["models"]
            trial = db.get(models.Trial, trial_id)
            assert trial is not None
            assert trial.status == "COMPLETED"
            artifacts = (
                db.query(models.Artifact)
                .filter(
                    models.Artifact.owner_type == "trial",
                    models.Artifact.owner_id == trial_id,
                )
                .all()
            )
            assert artifacts
            for artifact in artifacts:
                stored = Path(artifact.storage_path)
                assert stored.is_file()
                assert stored.resolve().is_relative_to(durable_root.resolve())
                assert "attempts" in stored.parts
                assert str(trial.attempt_count) in stored.parts
                assert artifact.integrity_policy == "sha256-v1"
                assert artifact.digest_receipt is not None
                assert (
                    artifact.digest_receipt.content_size_bytes
                    == stored.stat().st_size
                )

        transient_dir = run_root / "jobs" / trial.job_id / "trials" / trial_id
        assert not transient_dir.exists()
    finally:
        get_settings.cache_clear()


@pytest.mark.parametrize("simulation_success", [True, False])
def test_artifact_copy_failure_is_terminal_and_retains_transient_run(
    orchestration_ctx,
    monkeypatch,
    tmp_path,
    simulation_success: bool,
) -> None:
    ctx = orchestration_ctx
    trial_id = _seed_single_pending_trial(ctx)
    source = tmp_path / "transient" / "telemetry.json"
    source.parent.mkdir()
    source.write_text('{"samples": []}', encoding="utf-8")
    durable_root = tmp_path / "durable"
    monkeypatch.setenv("ARTIFACT_ROOT", str(durable_root))

    from app.config import get_settings

    get_settings.cache_clear()

    class ArtifactAdapter(MockSimulatorAdapter):
        backend_name = "artifact-failure-test"

        def __init__(self) -> None:
            self.finalized_with: TrialResult | None | object = object()

        def run_trial(self, trial_ctx: TrialContext) -> TrialResult:
            if simulation_success:
                result = super().run_trial(trial_ctx)
            else:
                result = TrialResult(
                    success=False,
                    backend=self.backend_name,
                    failure=TrialFailure(
                        code="SIMULATION_FAILED",
                        reason="fixture simulation failure",
                    ),
                )
            result.artifacts = [
                ArtifactMetadata(
                    artifact_type="telemetry_json",
                    display_name="Telemetry.json",
                    storage_path=str(source),
                    mime_type="application/json",
                )
            ]
            return result

        def finalize_trial(self, trial_ctx: TrialContext, result: TrialResult | None) -> None:
            self.finalized_with = result

    def fail_after_creating_temporary(_source: Path, destination: Path) -> None:
        Path(destination).write_text("partial", encoding="utf-8")
        raise OSError("injected artifact copy failure")

    adapter = ArtifactAdapter()
    monkeypatch.setattr(
        ctx["trial_executor"].shutil,
        "copy2",
        fail_after_creating_temporary,
    )
    try:
        with ctx["db_module"].SessionLocal() as db:
            claimed = ctx["trial_executor"].claim_and_run_one_pending_trial(
                db,
                "worker-storage-failure",
                adapter=adapter,
            )
        assert claimed == trial_id
        with ctx["db_module"].SessionLocal() as db:
            models = ctx["models"]
            trial = db.get(models.Trial, trial_id)
            assert trial is not None
            assert trial.status == "FAILED"
            assert trial.failure_code == "ARTIFACT_PERSISTENCE_FAILED"
            assert trial.lease_owner is None
            assert trial.lease_expires_at is None
            assert trial.metric is None
        assert source.is_file(), "transient diagnostic input must be retained"
        assert adapter.finalized_with is None
        assert not list(durable_root.rglob("*.tmp"))
    finally:
        get_settings.cache_clear()


def test_invalid_px4_candidate_is_rejected_before_simulator_start(
    orchestration_ctx,
) -> None:
    ctx = orchestration_ctx
    trial_id = _seed_single_pending_trial(ctx)
    models = ctx["models"]
    with ctx["db_module"].SessionLocal() as db:
        trial = db.get(models.Trial, trial_id)
        assert trial is not None
        trial.job.parameter_space_json = [{"name": "MPC_XY_P"}]
        trial.job.vehicle_profile_json = {
            "px4_version": "main",
            "vehicle_type": "multicopter",
            "airframe": "x500",
        }
        trial.candidate.parameter_json = {"MPC_XY_P": 99.0}
        db.commit()

    class NeverStartedAdapter(MockSimulatorAdapter):
        backend_name = "must-not-start"

        def __init__(self) -> None:
            self.prepared = False
            self.ran = False

        def prepare(self, trial_ctx: TrialContext) -> None:
            self.prepared = True

        def run_trial(self, trial_ctx: TrialContext) -> TrialResult:
            self.ran = True
            return super().run_trial(trial_ctx)

    adapter = NeverStartedAdapter()
    with ctx["db_module"].SessionLocal() as db:
        claimed = ctx["trial_executor"].claim_and_run_one_pending_trial(
            db,
            "worker-parameter-fence",
            adapter=adapter,
        )
    assert claimed == trial_id
    assert adapter.prepared is False
    assert adapter.ran is False
    with ctx["db_module"].SessionLocal() as db:
        trial = db.get(models.Trial, trial_id)
        assert trial is not None
        assert trial.status == "FAILED"
        assert trial.failure_code == "INVALID_CANDIDATE_PARAMETERS"
        assert "OUTSIDE_SAFE_BOUNDS" in (trial.failure_reason or "")
        assert trial.metric is None


def test_disabled_parameter_is_not_required_but_enabled_locked_parameter_is(
    orchestration_ctx,
) -> None:
    ctx = orchestration_ctx
    trial_id = _seed_single_pending_trial(ctx)
    models = ctx["models"]
    with ctx["db_module"].SessionLocal() as db:
        trial = db.get(models.Trial, trial_id)
        assert trial is not None
        trial.job.parameter_space_json = [
            {"name": "MPC_XY_P", "enabled": True, "locked": True},
            {"name": "MPC_Z_P", "enabled": False, "locked": False},
        ]
        trial.job.vehicle_profile_json = {
            "px4_version": "main",
            "vehicle_type": "multicopter",
            "airframe": "x500",
        }
        trial.candidate.parameter_json = {"MPC_XY_P": 0.95}
        db.commit()

    adapter = MockSimulatorAdapter()
    with ctx["db_module"].SessionLocal() as db:
        claimed = ctx["trial_executor"].claim_and_run_one_pending_trial(
            db,
            "worker-enabled-filter",
            adapter=adapter,
        )
    assert claimed == trial_id
    with ctx["db_module"].SessionLocal() as db:
        trial = db.get(models.Trial, trial_id)
        assert trial is not None
        assert trial.status == "COMPLETED"
        assert trial.failure_code is None
        assert trial.metric is not None


def test_cancel_job_clears_trial_lease(orchestration_ctx):
    ctx = orchestration_ctx
    trial_id = _seed_single_pending_trial(ctx)
    models = ctx["models"]
    jobs_service = ctx["jobs_service"]
    with ctx["db_module"].SessionLocal() as db:
        trial = db.get(models.Trial, trial_id)
        assert trial is not None
        trial.status = "RUNNING"
        trial.lease_owner = "worker-a"
        trial.lease_expires_at = datetime.now(timezone.utc) + timedelta(minutes=5)
        trial.worker_id = "worker-a"
        db.commit()
        jobs_service.cancel_job(db, trial.job_id)
    with ctx["db_module"].SessionLocal() as db:
        trial = db.get(models.Trial, trial_id)
        assert trial is not None
        assert trial.status == "CANCELLED"
        assert trial.lease_owner is None
        assert trial.lease_expires_at is None


# --- Aggregation / full loop -----------------------------------------------


def test_finalization_failure_isolated_to_one_ready_job(orchestration_ctx, monkeypatch) -> None:
    ctx = orchestration_ctx
    failing_job_id = _create_queued_job(ctx)
    healthy_job_id = _create_queued_job(ctx)

    with ctx["db_module"].SessionLocal() as db:
        assert set(ctx["job_manager"].start_queued_jobs(db)) == {
            failing_job_id,
            healthy_job_id,
        }

    while True:
        with ctx["db_module"].SessionLocal() as db:
            trial_id = ctx["trial_executor"].claim_and_run_one_pending_trial(
                db, "worker-finalization-isolation"
            )
        if trial_id is None:
            break

    original_generate = ctx["aggregation"].report_generator.generate_and_persist_report

    def fail_one_report(db, *, job, **kwargs):
        if job.id == failing_job_id:
            raise OSError("simulated report storage outage")
        return original_generate(db, job=job, **kwargs)

    monkeypatch.setattr(
        ctx["aggregation"].report_generator,
        "generate_and_persist_report",
        fail_one_report,
    )

    with ctx["db_module"].SessionLocal() as db:
        finalized = ctx["aggregation"].finalize_ready_jobs(db)
    assert set(finalized) == {failing_job_id, healthy_job_id}

    with ctx["db_module"].SessionLocal() as db:
        failing = db.get(ctx["models"].Job, failing_job_id)
        healthy = db.get(ctx["models"].Job, healthy_job_id)
        assert failing is not None
        assert healthy is not None
        assert failing.status == "FAILED"
        assert failing.latest_error_code == "FINALIZATION_FAILED"
        assert "report storage outage" in (failing.latest_error_message or "")
        assert healthy.status == "COMPLETED"
        assert healthy.report is not None


def test_runner_drives_job_to_completed(orchestration_ctx):
    ctx = orchestration_ctx
    job_id = _create_queued_job(ctx)

    # Drive the runner synchronously until the job is terminal. Phase 5
    # dispatches 13 trials per job (4 baseline + 3×3 optimizer), so the
    # iteration budget has to accommodate all of them.
    runner = ctx["runner"]
    for _ in range(60):
        runner.tick("test-worker")
        with ctx["db_module"].SessionLocal() as db:
            job = db.get(ctx["models"].Job, job_id)
            if job.status in {"COMPLETED", "FAILED", "CANCELLED"}:
                break
    else:  # pragma: no cover
        pytest.fail("worker loop did not finalize job within iteration budget")

    with ctx["db_module"].SessionLocal() as db:
        job = db.get(ctx["models"].Job, job_id)
        assert job.status == "COMPLETED"
        assert job.completed_at is not None
        assert job.best_candidate_id is not None
        # Phase 5: all 13 trials must have completed for the job to finalise.
        assert job.progress_completed_trials == job.progress_total_trials == 4 + 3 * 3
        assert job.current_phase == "completed"
        assert job.latest_error_code is None

        baseline = db.get(ctx["models"].CandidateParameterSet, job.baseline_candidate_id)
        assert baseline is not None
        assert baseline.aggregated_score is not None
        assert baseline.aggregated_metric_json is not None
        assert baseline.completed_trial_count == 4
        assert baseline.failed_trial_count == 0
        assert baseline.rank_in_job is not None
        # Phase 8 polish: aggregation must surface the per-trial pass_flag
        # count so the acceptance evaluator can judge "did the candidate
        # actually pass" separately from "did the candidate's trials run".
        assert "passing_trial_count" in baseline.aggregated_metric_json
        assert isinstance(baseline.aggregated_metric_json["passing_trial_count"], int)

        # Every optimizer candidate must have its own aggregate + rank.
        optimizer_candidates = [c for c in job.candidates if not c.is_baseline]
        assert len(optimizer_candidates) == 3
        for c in optimizer_candidates:
            assert c.aggregated_score is not None
            assert c.aggregated_metric_json is not None
            assert c.completed_trial_count == 3
            assert c.rank_in_job is not None

        # Exactly one winner.
        winners = [c for c in job.candidates if c.is_best]
        assert len(winners) == 1
        assert winners[0].id == job.best_candidate_id

        # Ranks are 1..N and distinct.
        ranks = sorted(c.rank_in_job for c in job.candidates)
        assert ranks == list(range(1, len(job.candidates) + 1))

        report = job.report
        assert report is not None
        assert report.report_status == "READY"
        assert report.best_candidate_id == job.best_candidate_id
        assert report.baseline_metric_json is not None
        assert report.optimized_metric_json is not None
        assert report.best_parameter_json is not None
        assert len(report.comparison_metric_json or []) == 5

        event_types = [e.event_type for e in job.events]
        assert "aggregation_started" in event_types
        assert "best_candidate_selected" in event_types
        assert "job_completed" in event_types


def test_api_report_endpoint_returns_ready_after_worker_runs(
    orchestration_ctx, tmp_path, monkeypatch
):
    """End-to-end: POST /api/v1/jobs -> run worker -> GET /api/v1/jobs/{id}/report."""

    ctx = orchestration_ctx

    # Reload main so the FastAPI app picks up the patched DB URL.
    import app.main as main_module
    import app.routers.jobs as jobs_router
    import app.routers.trials as trials_router

    importlib.reload(jobs_router)
    importlib.reload(trials_router)
    importlib.reload(main_module)

    from fastapi.testclient import TestClient

    with TestClient(main_module.app) as client:
        created = client.post(
            "/api/v1/jobs",
            json={
                "track_type": "circle",
                "start_point": {"x": 0, "y": 0},
                "altitude_m": 5.0,
                "wind": {"north": 0, "east": 0, "south": 0, "west": 0},
                "sensor_noise_level": "medium",
                "objective_profile": "robust",
                "optimizer_strategy": "heuristic",
                "simulator_backend": "mock",
            },
        ).json()["data"]
        job_id = created["id"]

        # Job should not be ready yet.
        resp = client.get(f"/api/v1/jobs/{job_id}/report")
        assert resp.status_code == 409
        assert resp.json()["error"]["code"] == "REPORT_NOT_READY"

        runner = ctx["runner"]
        for _ in range(60):
            runner.tick("test-worker")
            body = client.get(f"/api/v1/jobs/{job_id}").json()["data"]
            if body["status"] == "COMPLETED":
                break
        assert body["status"] == "COMPLETED"

        report = client.get(f"/api/v1/jobs/{job_id}/report")
        assert report.status_code == 200
        rep_data = report.json()["data"]
        assert rep_data["report_status"] == "READY"
        assert rep_data["best_candidate_id"] == body["best_candidate_id"]
        assert len(rep_data["comparison"]) == 5
        assert isinstance(rep_data["optimized_metrics"]["max_error_worst"], float)
        assert any(point["metric"] == "max_error_worst" for point in rep_data["comparison"])
        assert set(rep_data["best_parameters"].keys()) >= {"kp_xy", "kd_xy"}


def test_cancelled_queued_job_is_not_started(orchestration_ctx):
    ctx = orchestration_ctx
    job_id = _create_queued_job(ctx)

    # Cancel via the service helper.
    with ctx["db_module"].SessionLocal() as db:
        ctx["jobs_service"].cancel_job(db, job_id)

    with ctx["db_module"].SessionLocal() as db:
        started = ctx["job_manager"].start_queued_jobs(db)
    assert started == []

    with ctx["db_module"].SessionLocal() as db:
        job = db.get(ctx["models"].Job, job_id)
        assert job.status == "CANCELLED"
        assert len(list(job.trials)) == 0
        assert job.baseline_candidate_id is None


# --- Phase 7 acceptance coverage ------------------------------------------


def test_real_stub_backend_marks_job_failed_with_readable_error(orchestration_ctx, monkeypatch):
    """Phase 7 acceptance: the failed-flow demo must surface a user-readable
    failure summary on the job. Driving the worker with ``SIMULATOR_BACKEND=
    real_stub`` fails every trial with ``ADAPTER_UNAVAILABLE`` and the job
    manager must then mark the job ``FAILED`` with ``ALL_TRIALS_FAILED``.
    """

    ctx = orchestration_ctx
    monkeypatch.setenv("SIMULATOR_BACKEND", "real_stub")
    job_id = _create_queued_job(ctx)

    runner = ctx["runner"]
    for _ in range(60):
        runner.tick("test-worker")
        with ctx["db_module"].SessionLocal() as db:
            job = db.get(ctx["models"].Job, job_id)
            if job.status in {"COMPLETED", "FAILED", "CANCELLED"}:
                break
    else:  # pragma: no cover
        pytest.fail("worker loop did not finalize job within iteration budget")

    with ctx["db_module"].SessionLocal() as db:
        job = db.get(ctx["models"].Job, job_id)
        assert job.status == "FAILED"
        assert job.latest_error_code == "ALL_TRIALS_FAILED"
        assert job.latest_error_message
        # Every trial must be terminal and failed with ADAPTER_UNAVAILABLE.
        assert len(job.trials) == job.progress_total_trials
        assert all(t.status == "FAILED" for t in job.trials)
        assert all(t.failure_code == "ADAPTER_UNAVAILABLE" for t in job.trials)
        # No report should be produced for an all-failed job.
        assert job.report is None


def test_terminal_job_rejects_further_cancellation(orchestration_ctx):
    """Phase 7 acceptance: terminal jobs must not be cancellable again.

    Drive a job to COMPLETED and verify the job service raises a structured
    ``JOB_ALREADY_COMPLETED`` error rather than toggling state back.
    """

    ctx = orchestration_ctx
    job_id = _create_queued_job(ctx)

    runner = ctx["runner"]
    for _ in range(60):
        runner.tick("test-worker")
        with ctx["db_module"].SessionLocal() as db:
            job = db.get(ctx["models"].Job, job_id)
            if job.status == "COMPLETED":
                break
    else:  # pragma: no cover
        pytest.fail("worker loop did not complete job within iteration budget")

    jobs_service = ctx["jobs_service"]
    with (
        ctx["db_module"].SessionLocal() as db,
        pytest.raises(jobs_service.JobServiceError) as excinfo,
    ):
        jobs_service.cancel_job(db, job_id)
    assert excinfo.value.code == "JOB_ALREADY_COMPLETED"
    assert excinfo.value.http_status == 409


def test_report_for_failed_job_returns_structured_failure(orchestration_ctx, monkeypatch):
    """Phase 7 acceptance: when a job fails, ``GET /jobs/{id}/report`` must
    return a structured error with ``code=JOB_FAILED`` (not 200, not 500).
    """

    ctx = orchestration_ctx
    monkeypatch.setenv("SIMULATOR_BACKEND", "real_stub")
    job_id = _create_queued_job(ctx)

    runner = ctx["runner"]
    for _ in range(60):
        runner.tick("test-worker")
        with ctx["db_module"].SessionLocal() as db:
            job = db.get(ctx["models"].Job, job_id)
            if job.status in {"FAILED", "COMPLETED"}:
                break

    # Drive the HTTP layer directly so we cover the router error envelope.
    import app.main as main_module
    import app.routers.jobs as jobs_router
    import app.routers.trials as trials_router

    importlib.reload(jobs_router)
    importlib.reload(trials_router)
    importlib.reload(main_module)

    from fastapi.testclient import TestClient

    with TestClient(main_module.app) as client:
        resp = client.get(f"/api/v1/jobs/{job_id}/report")
        assert resp.status_code == 409
        body = resp.json()
        assert body["success"] is False
        assert body["error"]["code"] == "JOB_FAILED"
        assert body["error"]["message"]
        # Details must carry the failure code so the UI can render it.
        assert body["error"]["details"]["failure_code"] == "ALL_TRIALS_FAILED"


def test_list_jobs_filters_by_status(orchestration_ctx):
    """Phase 7 acceptance: the ``?status=`` query param must filter results."""

    ctx = orchestration_ctx
    queued_id = _create_queued_job(ctx)

    # Create a second job and cancel it so we have two distinct statuses.
    schemas = ctx["schemas"]
    jobs_service = ctx["jobs_service"]
    with ctx["db_module"].SessionLocal() as db:
        cancelled_job = jobs_service.create_job(
            db,
            schemas.JobCreateRequest(
                simulator_backend="mock",
                optimizer_strategy="heuristic",
            ),
        )
        cancelled_id = cancelled_job.id
    with ctx["db_module"].SessionLocal() as db:
        jobs_service.cancel_job(db, cancelled_id)

    import app.main as main_module
    import app.routers.jobs as jobs_router
    import app.routers.trials as trials_router

    importlib.reload(jobs_router)
    importlib.reload(trials_router)
    importlib.reload(main_module)

    from fastapi.testclient import TestClient

    with TestClient(main_module.app) as client:
        queued = client.get("/api/v1/jobs?status=QUEUED").json()["data"]
        cancelled = client.get("/api/v1/jobs?status=CANCELLED").json()["data"]

    assert [j["id"] for j in queued["items"]] == [queued_id]
    assert queued["total"] == 1
    assert [j["id"] for j in cancelled["items"]] == [cancelled_id]
    assert cancelled["total"] == 1
