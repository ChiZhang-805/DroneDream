"""Phase 6 tests: JobReport generation + mock artifact metadata.

These exercise the report_generator module directly against crafted model
instances so they do not depend on the full worker loop, and also verify
the `/api/v1/jobs/{job_id}/report` endpoint's failure-path behaviour.
"""

from __future__ import annotations

import importlib
from collections.abc import Iterator

import pytest


@pytest.fixture()
def ctx(tmp_path, monkeypatch) -> Iterator[dict[str, object]]:
    """Reload the backend against an isolated SQLite DB."""

    db_path = tmp_path / "report.db"
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

    import app.orchestration.aggregation as aggregation_module
    import app.orchestration.constants as constants_module
    import app.orchestration.events as events_module
    import app.orchestration.job_manager as job_manager_module
    import app.orchestration.metrics as metrics_module  # noqa: F401
    import app.orchestration.optimizer as optimizer_module
    import app.orchestration.report_generator as report_generator_module
    import app.orchestration.runner as runner_module
    import app.orchestration.trial_executor as trial_executor_module

    importlib.reload(constants_module)
    importlib.reload(optimizer_module)
    importlib.reload(events_module)
    importlib.reload(job_manager_module)
    importlib.reload(trial_executor_module)
    importlib.reload(report_generator_module)
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
        "report_generator": report_generator_module,
        "runner": runner_module,
    }

    config_module.get_settings.cache_clear()


def _run_job_to_completion(ctx: dict[str, object]) -> str:
    """Create a job and drain every trial until the runner finalises it."""

    schemas = ctx["schemas"]
    jobs_service = ctx["jobs_service"]
    db_module = ctx["db_module"]
    models = ctx["models"]
    runner = ctx["runner"]

    req = schemas.JobCreateRequest()
    with db_module.SessionLocal() as db:
        job_id = jobs_service.create_job(db, req).id

    for _ in range(60):
        runner.tick("test-worker")
        with db_module.SessionLocal() as db:
            job = db.get(models.Job, job_id)
            if job.status in {"COMPLETED", "FAILED", "CANCELLED"}:
                break
    else:  # pragma: no cover
        pytest.fail("runner did not finalise job within iteration budget")
    return job_id


# --- Summary text --------------------------------------------------------


def test_summary_text_covers_baseline_and_optimized(ctx):
    job_id = _run_job_to_completion(ctx)
    with ctx["db_module"].SessionLocal() as db:
        job = db.get(ctx["models"].Job, job_id)
        assert job.status == "COMPLETED"
        report = job.report
        assert report is not None
        assert report.report_status == "READY"
        text = report.summary_text or ""

    # Must mention baseline and either the optimizer winner or the baseline
    # winner fallback. The "No failure or instability flags" branch is what
    # we expect for a fully successful mock run.
    assert "Baseline achieved aggregated score" in text
    assert (
        "Optimizer candidate" in text
        or "No optimizer candidate beat the baseline" in text
    )
    assert (
        "No failure or instability flags" in text
        or "Watch-outs" in text
    )


def test_summary_text_reports_tradeoff_when_optimized_slower(ctx):
    """Hand-craft a job so the optimized winner is slower than baseline."""

    rg = ctx["report_generator"]
    models = ctx["models"]
    db_module = ctx["db_module"]

    with db_module.SessionLocal() as db:
        job = models.Job(
            track_type="circle",
            altitude_m=3.0,
            sensor_noise_level="medium",
            objective_profile="robust",
            status="COMPLETED",
        )
        db.add(job)
        db.flush()
        baseline = models.CandidateParameterSet(
            job_id=job.id,
            source_type="baseline",
            label="baseline",
            parameter_json={"kp_xy": 1.0},
            is_baseline=True,
        )
        optimizer = models.CandidateParameterSet(
            job_id=job.id,
            generation_index=1,
            source_type="optimizer",
            label="optimizer-1",
            parameter_json={"kp_xy": 1.2},
            is_baseline=False,
        )
        db.add_all([baseline, optimizer])
        db.flush()

        baseline_agg = {
            "rmse": 1.0,
            "max_error": 1.2,
            "overshoot_count": 2,
            "completion_time": 10.0,
            "score": 0.5,
            "aggregated_score": 0.9,
        }
        # Optimized has MUCH better RMSE but is slower.
        best_agg = {
            "rmse": 0.6,
            "max_error": 0.9,
            "overshoot_count": 1,
            "completion_time": 14.0,
            "score": 0.7,
            "aggregated_score": 0.6,
        }

        text = rg.generate_summary_text(
            best=optimizer,
            baseline_agg=baseline_agg,
            best_agg=best_agg,
            baseline_trials=[],
            best_trials=[],
        )

        assert "40.0% lower tracking RMSE" in text
        assert "Tradeoff" in text
        assert "completion time increased" in text


# --- Artifacts ------------------------------------------------------------


def test_completed_job_has_mock_artifacts(ctx):
    job_id = _run_job_to_completion(ctx)
    with ctx["db_module"].SessionLocal() as db:
        artifacts = [
            a
            for a in db.query(ctx["models"].Artifact)
            .filter(ctx["models"].Artifact.owner_type == "job")
            .filter(ctx["models"].Artifact.owner_id == job_id)
            .all()
        ]
        types = {a.artifact_type for a in artifacts}
        assert {
            "comparison_plot",
            "trajectory_plot",
            "worker_log",
            "telemetry_json",
        } <= types
        # storage_path is a mock URI scheme; frontend treats it as metadata.
        for a in artifacts:
            assert a.storage_path.startswith("mock://jobs/")
            assert job_id in a.storage_path


def test_ensure_job_artifacts_is_idempotent(ctx):
    rg = ctx["report_generator"]
    models = ctx["models"]
    db_module = ctx["db_module"]

    with db_module.SessionLocal() as db:
        job = models.Job(
            track_type="circle",
            altitude_m=3.0,
            sensor_noise_level="medium",
            objective_profile="robust",
            status="COMPLETED",
        )
        db.add(job)
        db.flush()

        first = rg.ensure_job_artifacts(db, job)
        db.commit()
        second = rg.ensure_job_artifacts(db, job)
        db.commit()

        assert len(first) == 4
        assert second == []

        rows = (
            db.query(models.Artifact)
            .filter(models.Artifact.owner_id == job.id)
            .all()
        )
        assert len(rows) == 4


# --- API error paths ------------------------------------------------------


def test_report_endpoint_returns_job_failed_when_job_failed(ctx):
    """A FAILED job returns a structured JOB_FAILED error with context."""

    import app.main as main_module
    import app.routers.jobs as jobs_router
    import app.routers.trials as trials_router

    importlib.reload(jobs_router)
    importlib.reload(trials_router)
    importlib.reload(main_module)

    from fastapi.testclient import TestClient

    schemas = ctx["schemas"]
    jobs_service = ctx["jobs_service"]
    db_module = ctx["db_module"]
    models = ctx["models"]

    with db_module.SessionLocal() as db:
        job = jobs_service.create_job(db, schemas.JobCreateRequest())
        job_id = job.id
        job_ref = db.get(models.Job, job_id)
        job_ref.status = "FAILED"
        job_ref.latest_error_code = "ALL_TRIALS_FAILED"
        job_ref.latest_error_message = "All baseline trials failed; cannot produce a report."
        db.commit()

    with TestClient(main_module.app) as client:
        resp = client.get(f"/api/v1/jobs/{job_id}/report")
        assert resp.status_code == 409
        body = resp.json()
        assert body["success"] is False
        assert body["error"]["code"] == "JOB_FAILED"
        assert "All baseline trials failed" in body["error"]["message"]
        details = body["error"]["details"]
        assert details["failure_code"] == "ALL_TRIALS_FAILED"


def test_report_endpoint_returns_job_cancelled_when_cancelled(ctx):
    import app.main as main_module
    import app.routers.jobs as jobs_router
    import app.routers.trials as trials_router

    importlib.reload(jobs_router)
    importlib.reload(trials_router)
    importlib.reload(main_module)

    from fastapi.testclient import TestClient

    schemas = ctx["schemas"]
    jobs_service = ctx["jobs_service"]
    db_module = ctx["db_module"]

    with db_module.SessionLocal() as db:
        job = jobs_service.create_job(db, schemas.JobCreateRequest())
        job_id = job.id
        jobs_service.cancel_job(db, job_id)

    with TestClient(main_module.app) as client:
        resp = client.get(f"/api/v1/jobs/{job_id}/report")
        assert resp.status_code == 409
        body = resp.json()
        assert body["error"]["code"] == "JOB_CANCELLED"


# --- Recent events + artifacts on job detail ------------------------------


def test_job_detail_includes_recent_events(ctx):
    import app.main as main_module
    import app.routers.jobs as jobs_router
    import app.routers.trials as trials_router

    importlib.reload(jobs_router)
    importlib.reload(trials_router)
    importlib.reload(main_module)

    from fastapi.testclient import TestClient

    job_id = _run_job_to_completion(ctx)
    with TestClient(main_module.app) as client:
        body = client.get(f"/api/v1/jobs/{job_id}").json()["data"]

    events = body.get("recent_events")
    assert isinstance(events, list)
    assert len(events) > 0
    # Newest first; at least one of these must be present for a COMPLETED job.
    event_types = {e["event_type"] for e in events}
    assert "job_completed" in event_types
    assert "best_candidate_selected" in event_types
    # Every event exposes the required fields for the frontend diagnostics
    # panel — id, event_type, created_at — payload may be None.
    for e in events:
        assert set(e.keys()) >= {"id", "event_type", "created_at", "payload"}


def test_artifacts_endpoint_exposes_job_artifacts(ctx):
    import app.main as main_module
    import app.routers.jobs as jobs_router
    import app.routers.trials as trials_router

    importlib.reload(jobs_router)
    importlib.reload(trials_router)
    importlib.reload(main_module)

    from fastapi.testclient import TestClient

    job_id = _run_job_to_completion(ctx)

    with TestClient(main_module.app) as client:
        body = client.get(f"/api/v1/jobs/{job_id}/artifacts").json()["data"]

    assert isinstance(body, list)
    # Phase 8: /api/v1/jobs/{id}/artifacts now returns both job-scoped
    # artifacts (the 4 aggregate report artifacts seeded by
    # _run_job_to_completion) AND trial-scoped artifacts (per-trial
    # trajectory_plot / telemetry_json / worker_log). The exact trial count
    # depends on BASELINE_SCENARIOS, so assert the aggregate surface and let
    # the owner_type field distinguish job vs trial rows.
    types = {a["artifact_type"] for a in body}
    assert {
        "comparison_plot",
        "trajectory_plot",
        "worker_log",
        "telemetry_json",
    }.issubset(types)
    owner_types = {a["owner_type"] for a in body}
    assert "job" in owner_types
    job_rows = [a for a in body if a["owner_type"] == "job"]
    assert {a["artifact_type"] for a in job_rows} == {
        "comparison_plot",
        "trajectory_plot",
        "worker_log",
        "telemetry_json",
    }
