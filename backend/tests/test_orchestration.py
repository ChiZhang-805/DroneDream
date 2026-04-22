"""Phase 3 orchestration tests: state transitions + worker progression.

These tests exercise the orchestration package directly against an isolated
SQLite DB. They never touch the FastAPI app so they can be run fast and
independently of the HTTP layer.
"""

from __future__ import annotations

import importlib
from collections.abc import Iterator

import pytest
from sqlalchemy.orm import Session


@pytest.fixture()
def orchestration_ctx(tmp_path, monkeypatch) -> Iterator[dict[str, object]]:
    """Yield a reloaded orchestration context bound to a per-test SQLite DB."""

    db_path = tmp_path / "orch.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    monkeypatch.setenv("APP_ENV", "test")

    from app import config as config_module

    config_module.get_settings.cache_clear()

    import app.db as db_module

    importlib.reload(db_module)

    import app.models as models_module

    importlib.reload(models_module)

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
        "aggregation": aggregation_module,
        "runner": runner_module,
    }

    config_module.get_settings.cache_clear()


def _create_queued_job(ctx: dict[str, object]) -> str:
    schemas = ctx["schemas"]
    jobs_service = ctx["jobs_service"]
    db_module = ctx["db_module"]

    req = schemas.JobCreateRequest()
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
        assert job.current_phase == "baseline"
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
            assert len(seeds) == len(
                [t for t in optimizer_trials if t.candidate_id == c.id]
            )

        events = {e.event_type for e in job.events}
        assert "job_started" in events
        assert "baseline_started" in events
        assert "optimizer_started" in events
        assert "optimizer_candidate_created" in events
        assert "trial_dispatched" in events


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

        job = db.get(ctx["models"].Job, job_id)
        assert job.progress_completed_trials == 1
        event_types = [e.event_type for e in job.events]
        assert event_types.count("trial_completed") == 1


def test_claim_returns_none_when_no_pending(orchestration_ctx):
    ctx = orchestration_ctx
    with ctx["db_module"].SessionLocal() as db:
        trial_id = ctx["trial_executor"].claim_and_run_one_pending_trial(db, "test-worker")
    assert trial_id is None


# --- Aggregation / full loop -----------------------------------------------


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


def test_real_stub_backend_marks_job_failed_with_readable_error(
    orchestration_ctx, monkeypatch
):
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


def test_report_for_failed_job_returns_structured_failure(
    orchestration_ctx, monkeypatch
):
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
        cancelled_job = jobs_service.create_job(db, schemas.JobCreateRequest())
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
