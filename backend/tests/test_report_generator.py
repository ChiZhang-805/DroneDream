"""Phase 6 tests: JobReport generation + mock artifact metadata.

These exercise the report_generator module directly against crafted model
instances so they do not depend on the full worker loop, and also verify
the `/api/v1/jobs/{job_id}/report` endpoint's failure-path behaviour.
"""

from __future__ import annotations

import importlib
from collections.abc import Iterator
from datetime import datetime, timedelta, timezone
from pathlib import Path

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

    req = schemas.JobCreateRequest(
        optimizer_strategy="heuristic",
        simulator_backend="mock",
    )
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


def test_score_comparison_point_is_lower_is_better(ctx):
    rg = ctx["report_generator"]
    points = rg._comparison_points(  # noqa: SLF001
        {
            "rmse": 1.0,
            "max_error": 1.0,
            "overshoot_count": 1,
            "completion_time": 10.0,
            "score": 5.0,
        },
        {
            "rmse": 0.8,
            "max_error": 0.9,
            "overshoot_count": 0,
            "completion_time": 9.0,
            "score": 4.0,
        },
    )
    score_point = next(p for p in points if p["metric"] == "score")
    assert score_point["lower_is_better"] is True


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
            if a.artifact_type == "pdf_report":
                assert a.storage_path.endswith(f"{job_id} report.pdf")
                assert not a.storage_path.startswith("mock://")
            else:
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
        best = models.CandidateParameterSet(
            job_id=job.id,
            source_type="baseline",
            label="baseline",
            parameter_json={"kp_xy": 1.0},
            is_baseline=True,
            is_best=True,
        )
        db.add(best)
        db.flush()
        report_body = {
            "summary_text": "summary",
            "baseline_metric_json": {
                "rmse": 1.0,
                "max_error": 1.0,
                "overshoot_count": 0,
                "completion_time": 10.0,
                "score": 1.0,
            },
            "optimized_metric_json": {
                "rmse": 1.0,
                "max_error": 1.0,
                "overshoot_count": 0,
                "completion_time": 10.0,
                "score": 1.0,
            },
            "comparison_metric_json": [],
            "best_parameter_json": {"kp_xy": 1.0},
        }

        first = rg.ensure_job_artifacts(db, job=job, report_body=report_body, best=best)
        db.commit()
        second = rg.ensure_job_artifacts(db, job=job, report_body=report_body, best=best)
        db.commit()

        assert len(first) == 4
        assert second == []

        rows = (
            db.query(models.Artifact)
            .filter(models.Artifact.owner_id == job.id)
            .all()
        )
        assert len(rows) == 4


def test_real_cli_job_artifacts_are_real_files_and_idempotent(ctx, tmp_path, monkeypatch):
    rg = ctx["report_generator"]
    models = ctx["models"]
    db_module = ctx["db_module"]
    monkeypatch.setenv("REAL_SIMULATOR_ARTIFACT_ROOT", str(tmp_path))

    with db_module.SessionLocal() as db:
        job = models.Job(
            track_type="circle",
            altitude_m=3.0,
            sensor_noise_level="medium",
            objective_profile="robust",
            status="COMPLETED",
            simulator_backend_requested="real_cli",
        )
        db.add(job)
        db.flush()
        best = models.CandidateParameterSet(
            job_id=job.id,
            source_type="baseline",
            label="baseline",
            parameter_json={"kp_xy": 1.0},
            is_baseline=True,
            is_best=True,
        )
        db.add(best)
        db.flush()
        report_body = {
            "summary_text": "summary",
            "baseline_metric_json": {
                "rmse": 1.0,
                "max_error": 1.0,
                "overshoot_count": 0,
                "completion_time": 10.0,
                "score": 1.0,
            },
            "optimized_metric_json": {
                "rmse": 0.9,
                "max_error": 0.9,
                "overshoot_count": 0,
                "completion_time": 9.0,
                "score": 0.9,
            },
            "comparison_metric_json": [],
            "best_parameter_json": {"kp_xy": 1.0},
        }

        first = rg.ensure_job_artifacts(db, job=job, report_body=report_body, best=best)
        db.commit()
        second = rg.ensure_job_artifacts(db, job=job, report_body=report_body, best=best)
        db.commit()

        assert len(first) == 5
        assert second == []

        rows = (
            db.query(models.Artifact)
            .filter(models.Artifact.owner_type == "job")
            .filter(models.Artifact.owner_id == job.id)
            .all()
        )
        assert len(rows) == 5
        assert all(not a.storage_path.startswith("mock://") for a in rows)
        assert {a.artifact_type for a in rows} == {
            "report_json",
            "candidate_summary_json",
            "trial_summary_json",
            "comparison_json",
            "job_events_log",
        }
        for row in rows:
            path = tmp_path / "jobs" / job.id / "job_artifacts" / Path(row.storage_path).name
            assert path.exists()


def test_real_cli_pdf_artifact_upsert_is_idempotent(ctx, tmp_path, monkeypatch):
    rg = ctx["report_generator"]
    models = ctx["models"]
    db_module = ctx["db_module"]
    monkeypatch.setenv("REAL_SIMULATOR_ARTIFACT_ROOT", str(tmp_path))

    with db_module.SessionLocal() as db:
        job = models.Job(
            track_type="circle",
            altitude_m=3.0,
            sensor_noise_level="medium",
            objective_profile="robust",
            status="COMPLETED",
            simulator_backend_requested="real_cli",
        )
        db.add(job)
        db.flush()
        best = models.CandidateParameterSet(
            job_id=job.id,
            source_type="baseline",
            label="baseline",
            parameter_json={"kp_xy": 1.0},
            aggregated_metric_json={
                "rmse": 1.0,
                "max_error": 1.1,
                "completion_time": 10.0,
                "aggregated_score": 1.1,
                "trial_count": 1,
                "passing_trial_count": 1,
            },
            is_baseline=True,
            is_best=True,
        )
        db.add(best)
        db.flush()
        job.baseline_candidate_id = best.id
        job.best_candidate_id = best.id
        db.add(
            models.JobReport(
                job_id=job.id,
                best_candidate_id=best.id,
                summary_text="summary",
                baseline_metric_json={
                    "rmse": 1.0,
                    "max_error": 1.1,
                    "overshoot_count": 0,
                    "completion_time": 10.0,
                    "score": 1.1,
                },
                optimized_metric_json={
                    "rmse": 1.0,
                    "max_error": 1.1,
                    "overshoot_count": 0,
                    "completion_time": 10.0,
                    "score": 1.1,
                },
                comparison_metric_json=[],
                best_parameter_json={"kp_xy": 1.0},
                report_status="READY",
            )
        )
        db.commit()
        db.refresh(job)

        first = rg.ensure_job_pdf_artifact(db, job=job)
        db.commit()
        second = rg.ensure_job_pdf_artifact(db, job=job)
        db.commit()
        assert first.id == second.id
        assert first.mime_type == "application/pdf"
        assert first.display_name == f"{job.id} report.pdf"
        assert first.file_size_bytes is not None and first.file_size_bytes > 0
        assert not first.storage_path.startswith("mock://")
        assert Path(first.storage_path).exists()

        rows = (
            db.query(models.Artifact)
            .filter(models.Artifact.owner_type == "job")
            .filter(models.Artifact.owner_id == job.id)
            .filter(models.Artifact.artifact_type == "pdf_report")
            .all()
        )
        assert len(rows) == 1


def test_generate_job_pdf_report_creates_expected_file(ctx, tmp_path):
    models = ctx["models"]
    db_module = ctx["db_module"]
    pdf_service = __import__("app.services.pdf_report", fromlist=["*"])

    with db_module.SessionLocal() as db:
        job = models.Job(
            track_type="circle",
            altitude_m=3.0,
            sensor_noise_level="medium",
            objective_profile="robust",
            status="COMPLETED",
            simulator_backend_requested="real_cli",
        )
        db.add(job)
        db.flush()

        baseline = models.CandidateParameterSet(
            job_id=job.id,
            source_type="baseline",
            label="baseline",
            parameter_json={"kp_xy": 1.0, "kd_xy": 0.2},
            aggregated_score=1.0,
            aggregated_metric_json={
                "rmse": 1.1,
                "max_error": 1.4,
                "completion_time": 9.2,
                "aggregated_score": 1.0,
                "trial_count": 1,
                "passing_trial_count": 1,
            },
            trial_count=1,
            completed_trial_count=1,
            is_baseline=True,
            is_best=True,
        )
        db.add(baseline)
        db.flush()
        job.baseline_candidate_id = baseline.id
        job.best_candidate_id = baseline.id
        report = models.JobReport(
            job_id=job.id,
            best_candidate_id=baseline.id,
            summary_text="A deterministic summary.",
            report_status="READY",
            best_parameter_json={"kp_xy": 1.0, "kd_xy": 0.2},
            baseline_metric_json={
                "rmse": 1.1,
                "max_error": 1.4,
                "overshoot_count": 0,
                "completion_time": 9.2,
                "score": 1.0,
            },
            optimized_metric_json={
                "rmse": 1.1,
                "max_error": 1.4,
                "overshoot_count": 0,
                "completion_time": 9.2,
                "score": 1.0,
            },
            comparison_metric_json=[],
        )
        db.add(report)
        db.commit()
        db.refresh(job)

        path = pdf_service.generate_job_pdf_report(
            db=db,
            job=job,
            output_dir=tmp_path / "jobs" / job.id / "reports",
        )
        assert path.exists()
        assert path.name == f"{job.id} report.pdf"
        assert path.stat().st_size > 0
        assert path.read_bytes().startswith(b"%PDF")


def test_generate_job_pdf_report_paginates_and_includes_all_candidates_trials(ctx, tmp_path):
    models = ctx["models"]
    db_module = ctx["db_module"]
    pdf_service = __import__("app.services.pdf_report", fromlist=["*"])

    with db_module.SessionLocal() as db:
        job = models.Job(
            track_type="circle",
            altitude_m=3.0,
            sensor_noise_level="medium",
            objective_profile="robust",
            status="COMPLETED",
            simulator_backend_requested="real_cli",
            optimizer_strategy="gpt",
            max_iterations=20,
            trials_per_candidate=3,
        )
        db.add(job)
        db.flush()

        base_time = datetime.now(timezone.utc)
        candidates: list[object] = []
        for idx in range(21):
            is_baseline = idx == 0
            candidate = models.CandidateParameterSet(
                id=f"cand_large_{idx:03d}",
                job_id=job.id,
                generation_index=idx,
                source_type="baseline" if is_baseline else "llm_optimizer",
                label="baseline" if is_baseline else f"gpt-gen-{idx}",
                parameter_json={
                    "kp_xy": 1.0 + idx * 0.01,
                    "kd_xy": 0.2 + idx * 0.01,
                    "ki_xy": 0.05 + idx * 0.001,
                    "vel_limit": 5.0,
                    "accel_limit": 4.0,
                    "disturbance_rejection": 0.5,
                },
                aggregated_score=1.0 + idx * 0.01,
                aggregated_metric_json={
                    "rmse": 1.0 + idx * 0.01,
                    "max_error": 1.2 + idx * 0.01,
                    "completion_time": 9.0 + idx * 0.05,
                    "aggregated_score": 1.0 + idx * 0.01,
                    "trial_count": 3,
                    "completed_trial_count": 3,
                },
                trial_count=3,
                completed_trial_count=3,
                is_baseline=is_baseline,
                is_best=idx == 20,
                proposal_reason=(
                    "Candidate rationale " * 15 if not is_baseline else "Baseline"
                ),
                created_at=base_time + timedelta(seconds=idx),
                updated_at=base_time + timedelta(seconds=idx),
            )
            candidates.append(candidate)
            db.add(candidate)
        db.flush()

        job.baseline_candidate_id = "cand_large_000"
        job.best_candidate_id = "cand_large_020"
        db.add(
            models.JobReport(
                job_id=job.id,
                best_candidate_id=job.best_candidate_id,
                summary_text="Large-job summary",
                report_status="READY",
                baseline_metric_json={},
                optimized_metric_json={},
                comparison_metric_json=[],
                best_parameter_json={"kp_xy": 1.2},
            )
        )
        db.flush()

        trials_per_candidate = [4] + [3] * 20
        trial_index = 0
        for candidate, trial_count in zip(candidates, trials_per_candidate, strict=True):
            for seed in range(trial_count):
                trial_id = f"tri_large_{trial_index:03d}"
                trial = models.Trial(
                    id=trial_id,
                    job_id=job.id,
                    candidate_id=candidate.id,
                    seed=seed,
                    scenario_type="nominal",
                    status="COMPLETED",
                    created_at=base_time + timedelta(minutes=1, seconds=trial_index),
                    updated_at=base_time + timedelta(minutes=1, seconds=trial_index),
                )
                db.add(trial)
                db.flush()
                db.add(
                    models.TrialMetric(
                        trial_id=trial.id,
                        rmse=0.3 + trial_index * 0.01,
                        max_error=0.5 + trial_index * 0.01,
                        completion_time=10.0 + trial_index * 0.01,
                        score=0.9 + trial_index * 0.001,
                        final_error=0.2 + trial_index * 0.001,
                        pass_flag=True,
                        instability_flag=False,
                    )
                )
                trial_index += 1
        assert trial_index == 64
        db.commit()
        db.refresh(job)

        path = pdf_service.generate_job_pdf_report(
            db=db,
            job=job,
            output_dir=tmp_path / "jobs" / job.id / "reports",
        )
        body = path.read_bytes()
        assert path.exists()
        assert path.name == f"{job.id} report.pdf"
        assert body.startswith(b"%PDF")
        assert b"cand_large_000" in body
        assert b"cand_large_020" in body
        assert b"tri_large_000" in body
        assert b"tri_large_063" in body
        assert b"Page 1 /" in body
        assert b"Page 2 /" in body


def test_generate_job_pdf_report_excludes_secret_values(ctx, tmp_path):
    models = ctx["models"]
    db_module = ctx["db_module"]
    pdf_service = __import__("app.services.pdf_report", fromlist=["*"])

    with db_module.SessionLocal() as db:
        job = models.Job(
            track_type="circle",
            altitude_m=3.0,
            sensor_noise_level="medium",
            objective_profile="robust",
            status="COMPLETED",
            simulator_backend_requested="real_cli",
        )
        db.add(job)
        db.flush()

        secret_value = "sk-secret-should-not-appear"
        baseline = models.CandidateParameterSet(
            job_id=job.id,
            source_type="baseline",
            label="baseline",
            parameter_json={
                "kp_xy": 1.0,
                "kd_xy": 0.2,
                "openai_api_key": secret_value,
                "APP_SECRET_KEY": "app-secret-never-print",
                "password": "p@ss",
                "token": "tok-123",
                "nested": {"access_token": "nested-secret", "kp_xy": 9.9},
            },
            aggregated_score=1.0,
            aggregated_metric_json={
                "rmse": 1.1,
                "max_error": 1.4,
                "completion_time": 9.2,
                "aggregated_score": 1.0,
                "trial_count": 1,
                "completed_trial_count": 1,
            },
            trial_count=1,
            completed_trial_count=1,
            is_baseline=True,
            is_best=True,
        )
        db.add(baseline)
        db.flush()
        job.baseline_candidate_id = baseline.id
        job.best_candidate_id = baseline.id
        db.add(
            models.JobReport(
                job_id=job.id,
                best_candidate_id=baseline.id,
                summary_text="Summary",
                report_status="READY",
                best_parameter_json={"kp_xy": 1.0},
                baseline_metric_json={},
                optimized_metric_json={},
                comparison_metric_json=[],
            )
        )
        db.commit()
        db.refresh(job)

        lines = pdf_service.build_job_report_lines(job)
        joined_lines = "\n".join(lines)
        path = pdf_service.generate_job_pdf_report(
            db=db,
            job=job,
            output_dir=tmp_path / "jobs" / job.id / "reports",
        )
        body = path.read_bytes().decode("latin-1", errors="ignore")

        assert "kp_xy" in joined_lines
        assert "kd_xy" in joined_lines
        assert secret_value not in joined_lines
        assert "app-secret-never-print" not in joined_lines
        assert "tok-123" not in joined_lines
        assert "nested-secret" not in joined_lines
        assert secret_value not in body
        assert "app-secret-never-print" not in body
        assert "tok-123" not in body
        assert "nested-secret" not in body


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
        job = jobs_service.create_job(
            db,
            schemas.JobCreateRequest(
                optimizer_strategy="heuristic",
                simulator_backend="mock",
            ),
        )
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
        job = jobs_service.create_job(
            db,
            schemas.JobCreateRequest(
                optimizer_strategy="heuristic",
                simulator_backend="mock",
            ),
        )
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
    assert {a["artifact_type"] for a in job_rows} >= {
        "comparison_plot",
        "trajectory_plot",
        "worker_log",
        "telemetry_json",
    }
