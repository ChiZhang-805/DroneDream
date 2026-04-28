"""Integration tests for /api/v1 job and trial endpoints."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

VALID_JOB_PAYLOAD: dict = {
    "track_type": "circle",
    "start_point": {"x": 0, "y": 0},
    "altitude_m": 5.0,
    "wind": {"north": 0, "east": 0, "south": 0, "west": 0},
    "sensor_noise_level": "medium",
    "objective_profile": "robust",
}
HEURISTIC_JOB_PAYLOAD: dict = {
    **VALID_JOB_PAYLOAD,
    "optimizer_strategy": "heuristic",
    "simulator_backend": "mock",
}


# --- Create ----------------------------------------------------------------


def test_create_job_returns_queued(client: TestClient) -> None:
    resp = client.post("/api/v1/jobs", json=HEURISTIC_JOB_PAYLOAD)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["success"] is True
    assert body["error"] is None
    job = body["data"]
    assert job["status"] == "QUEUED"
    assert job["id"].startswith("job_")
    # Backward-compatible alias for clients that expected the original
    # ``{job_id, status}`` wording in ``docs/04_API_SPEC.md``.
    assert job["job_id"] == job["id"]
    assert job["queued_at"] is not None
    assert job["started_at"] is None
    assert job["progress"]["completed_trials"] == 0
    assert job["track_type"] == "circle"
    assert job["sensor_noise_level"] == "medium"
    assert job["objective_profile"] == "robust"
    assert job["source_job_id"] is None


def test_create_job_exposes_job_id_alias(client: TestClient) -> None:
    """The create response must include ``job_id`` (alias of ``id``)."""

    body = client.post("/api/v1/jobs", json=HEURISTIC_JOB_PAYLOAD).json()
    job = body["data"]
    assert body["success"] is True
    assert "id" in job
    assert "job_id" in job
    assert job["id"] == job["job_id"]
    assert job["status"] == "QUEUED"


def test_list_and_detail_do_not_add_job_id_alias(client: TestClient) -> None:
    """Only create/rerun advertise ``job_id``; list/detail stick to ``id``.

    This keeps the canonical ``id`` schema unchanged on the read endpoints
    while preserving the alias where the original spec promised it.
    """

    created = client.post("/api/v1/jobs", json=HEURISTIC_JOB_PAYLOAD).json()["data"]
    detail = client.get(f"/api/v1/jobs/{created['id']}").json()["data"]
    assert detail["id"] == created["id"]
    assert "job_id" not in detail
    listing = client.get("/api/v1/jobs").json()["data"]
    for row in listing["items"]:
        assert "id" in row
        assert "job_id" not in row


def test_create_job_rejects_invalid_altitude(client: TestClient) -> None:
    bad = {**VALID_JOB_PAYLOAD, "altitude_m": 25.0}
    resp = client.post("/api/v1/jobs", json=bad)
    assert resp.status_code == 422
    body = resp.json()
    assert body["success"] is False
    assert body["error"]["code"] == "INVALID_INPUT"


def test_create_job_rejects_invalid_wind(client: TestClient) -> None:
    bad = {**VALID_JOB_PAYLOAD, "wind": {"north": 20, "east": 0, "south": 0, "west": 0}}
    resp = client.post("/api/v1/jobs", json=bad)
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "INVALID_INPUT"


def test_create_job_rejects_invalid_track_type(client: TestClient) -> None:
    bad = {**VALID_JOB_PAYLOAD, "track_type": "zigzag"}
    resp = client.post("/api/v1/jobs", json=bad)
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "INVALID_INPUT"


def test_create_job_rejects_custom_track_without_reference_track(client: TestClient) -> None:
    bad = {**HEURISTIC_JOB_PAYLOAD, "track_type": "custom", "reference_track": None}
    resp = client.post("/api/v1/jobs", json=bad)
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "INVALID_INPUT"


def test_create_job_rejects_custom_track_with_short_reference_track(client: TestClient) -> None:
    bad = {
        **HEURISTIC_JOB_PAYLOAD,
        "track_type": "custom",
        "reference_track": [{"x": 0, "y": 0, "z": 3}],
    }
    resp = client.post("/api/v1/jobs", json=bad)
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "INVALID_INPUT"


def test_create_job_accepts_and_persists_custom_reference_track(client: TestClient) -> None:
    payload = {
        **HEURISTIC_JOB_PAYLOAD,
        "track_type": "custom",
        "reference_track": [{"x": 0, "y": 0, "z": 3}, {"x": 5, "y": 0}, {"x": 5, "y": 5, "z": 3}],
    }
    created = client.post("/api/v1/jobs", json=payload)
    assert created.status_code == 200, created.text
    data = created.json()["data"]
    assert data["track_type"] == "custom"
    assert len(data["reference_track"]) == 3
    assert data["reference_track"][1]["z"] is None

    fetched = client.get(f"/api/v1/jobs/{data['id']}")
    assert fetched.status_code == 200
    assert fetched.json()["data"]["reference_track"] == data["reference_track"]


def test_create_job_rejects_non_finite_custom_reference_track_values(client: TestClient) -> None:
    body = {
        **HEURISTIC_JOB_PAYLOAD,
        "track_type": "custom",
        # 1e309 decodes to +inf in Python's float parser.
        "reference_track": [{"x": 0, "y": 0, "z": 3}, {"x": 1e309, "y": 1}],
    }
    resp = client.post("/api/v1/jobs", content=json.dumps(body))
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "INVALID_INPUT"


def test_create_job_accepts_advanced_scenario_config(client: TestClient) -> None:
    payload = {
        **HEURISTIC_JOB_PAYLOAD,
        "advanced_scenario_config": {
            "wind_gusts": {
                "enabled": True,
                "magnitude_mps": 2.5,
                "direction_deg": 45,
                "period_s": 8,
            },
            "sensor_degradation": {
                "gps_noise_m": 1.0,
                "baro_noise_m": 0.5,
                "imu_noise_scale": 1.2,
                "dropout_rate": 0.2,
            },
            "battery": {"initial_percent": 70, "voltage_sag": True},
            "obstacles": [{"type": "cylinder", "x": 1, "y": 2, "z": 0, "radius": 0.5, "height": 2}],
        },
    }
    resp = client.post("/api/v1/jobs", json=payload)
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["advanced_scenario_config"]["battery"]["initial_percent"] == 70


def test_create_job_rejects_invalid_advanced_dropout_rate(client: TestClient) -> None:
    payload = {
        **HEURISTIC_JOB_PAYLOAD,
        "advanced_scenario_config": {
            "sensor_degradation": {
                "gps_noise_m": 0.0,
                "baro_noise_m": 0.0,
                "imu_noise_scale": 1.0,
                "dropout_rate": 1.5,
            }
        },
    }
    resp = client.post("/api/v1/jobs", json=payload)
    assert resp.status_code == 422


def test_create_job_rejects_invalid_battery_percent(client: TestClient) -> None:
    payload = {
        **HEURISTIC_JOB_PAYLOAD,
        "advanced_scenario_config": {"battery": {"initial_percent": 120, "voltage_sag": False}},
    }
    resp = client.post("/api/v1/jobs", json=payload)
    assert resp.status_code == 422


@pytest.mark.parametrize("track_type", ["circle", "u_turn", "lemniscate"])
def test_non_custom_track_creation_unchanged(client: TestClient, track_type: str) -> None:
    payload = {**HEURISTIC_JOB_PAYLOAD, "track_type": track_type}
    resp = client.post("/api/v1/jobs", json=payload)
    assert resp.status_code == 200, resp.text
    body = resp.json()["data"]
    assert body["track_type"] == track_type
    assert body["reference_track"] is None


def test_create_job_rejects_invalid_sensor_noise(client: TestClient) -> None:
    bad = {**VALID_JOB_PAYLOAD, "sensor_noise_level": "extreme"}
    resp = client.post("/api/v1/jobs", json=bad)
    assert resp.status_code == 422


def test_create_job_rejects_invalid_objective(client: TestClient) -> None:
    bad = {**VALID_JOB_PAYLOAD, "objective_profile": "fun"}
    resp = client.post("/api/v1/jobs", json=bad)
    assert resp.status_code == 422


def test_create_job_rejects_unknown_fields(client: TestClient) -> None:
    bad = {**VALID_JOB_PAYLOAD, "rogue_field": 1}
    resp = client.post("/api/v1/jobs", json=bad)
    assert resp.status_code == 422


# --- List / Detail ---------------------------------------------------------


def test_list_jobs_paginates(client: TestClient) -> None:
    for _ in range(3):
        r = client.post("/api/v1/jobs", json=HEURISTIC_JOB_PAYLOAD)
        assert r.status_code == 200

    resp = client.get("/api/v1/jobs")
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    data = body["data"]
    assert data["total"] == 3
    assert data["page"] == 1
    assert data["page_size"] == 20
    assert len(data["items"]) == 3
    assert all(item["status"] == "QUEUED" for item in data["items"])


def test_get_job_detail(client: TestClient) -> None:
    created = client.post("/api/v1/jobs", json=HEURISTIC_JOB_PAYLOAD).json()["data"]
    resp = client.get(f"/api/v1/jobs/{created['id']}")
    assert resp.status_code == 200
    fetched = resp.json()["data"]
    assert fetched["id"] == created["id"]
    assert fetched["status"] == "QUEUED"


def test_get_job_not_found(client: TestClient) -> None:
    resp = client.get("/api/v1/jobs/job_does_not_exist")
    assert resp.status_code == 404
    body = resp.json()
    assert body["success"] is False
    assert body["error"]["code"] == "JOB_NOT_FOUND"


# --- Trials ----------------------------------------------------------------


def test_list_trials_for_job_is_empty(client: TestClient) -> None:
    job = client.post("/api/v1/jobs", json=HEURISTIC_JOB_PAYLOAD).json()["data"]
    resp = client.get(f"/api/v1/jobs/{job['id']}/trials")
    assert resp.status_code == 200
    assert resp.json() == {"success": True, "data": [], "error": None}


def test_trial_not_found(client: TestClient) -> None:
    resp = client.get("/api/v1/trials/tri_missing")
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "TRIAL_NOT_FOUND"


# --- Rerun -----------------------------------------------------------------


def test_rerun_creates_new_job_preserving_original(client: TestClient) -> None:
    original = client.post("/api/v1/jobs", json=HEURISTIC_JOB_PAYLOAD).json()["data"]
    resp = client.post(f"/api/v1/jobs/{original['id']}/rerun")
    assert resp.status_code == 200
    new_job = resp.json()["data"]
    assert new_job["id"] != original["id"]
    # Rerun response also advertises the ``job_id`` alias (see
    # docs/04_API_SPEC.md §7.4).
    assert new_job["job_id"] == new_job["id"]
    assert new_job["status"] == "QUEUED"
    assert new_job["source_job_id"] == original["id"]
    assert new_job["track_type"] == original["track_type"]
    assert new_job["altitude_m"] == original["altitude_m"]

    # Original still exists unchanged.
    again = client.get(f"/api/v1/jobs/{original['id']}").json()["data"]
    assert again["id"] == original["id"]
    assert again["source_job_id"] is None


def test_rerun_preserves_custom_reference_track(client: TestClient) -> None:
    created = client.post(
        "/api/v1/jobs",
        json={
            **HEURISTIC_JOB_PAYLOAD,
            "track_type": "custom",
            "reference_track": [{"x": 0, "y": 0, "z": 3}, {"x": 4, "y": 2, "z": 3}],
        },
    )
    assert created.status_code == 200, created.text
    source = created.json()["data"]
    rerun = client.post(f"/api/v1/jobs/{source['id']}/rerun")
    assert rerun.status_code == 200, rerun.text
    child = rerun.json()["data"]
    assert child["track_type"] == "custom"
    assert child["reference_track"] == source["reference_track"]


def test_rerun_not_found(client: TestClient) -> None:
    resp = client.post("/api/v1/jobs/job_missing/rerun")
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "JOB_NOT_FOUND"


def test_compare_jobs_returns_completed_metrics(client: TestClient) -> None:
    from app import models
    from app.db import SessionLocal

    job_a = client.post("/api/v1/jobs", json=HEURISTIC_JOB_PAYLOAD).json()["data"]["id"]
    job_b = client.post("/api/v1/jobs", json=HEURISTIC_JOB_PAYLOAD).json()["data"]["id"]
    with SessionLocal() as db:
        for job_id in (job_a, job_b):
            job = db.get(models.Job, job_id)
            assert job is not None
            job.status = "COMPLETED"
            job.report = models.JobReport(
                job_id=job.id,
                report_status="READY",
                baseline_metric_json={"rmse": 1.0},
                optimized_metric_json={"rmse": 0.8},
            )
        db.commit()
    resp = client.post("/api/v1/jobs/compare", json={"job_ids": [job_a, job_b]})
    assert resp.status_code == 200, resp.text
    items = resp.json()["data"]["items"]
    assert len(items) == 2
    assert items[0]["optimized_metrics"]["rmse"] == 0.8


def test_compare_jobs_active_job_metrics_are_null(client: TestClient) -> None:
    job_a = client.post("/api/v1/jobs", json=HEURISTIC_JOB_PAYLOAD).json()["data"]["id"]
    job_b = client.post("/api/v1/jobs", json=HEURISTIC_JOB_PAYLOAD).json()["data"]["id"]
    resp = client.post("/api/v1/jobs/compare", json={"job_ids": [job_a, job_b]})
    assert resp.status_code == 200
    for item in resp.json()["data"]["items"]:
        assert item["baseline_metrics"] is None
        assert item["optimized_metrics"] is None


def test_compare_jobs_unknown_job_returns_404(client: TestClient) -> None:
    job = client.post("/api/v1/jobs", json=HEURISTIC_JOB_PAYLOAD).json()["data"]["id"]
    resp = client.post("/api/v1/jobs/compare", json={"job_ids": [job, "job_missing"]})
    assert resp.status_code == 404


def test_rerun_gpt_requires_fresh_openai_api_key(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("APP_SECRET_KEY", "dev-unit-test-key")
    monkeypatch.delenv("DRONEDREAM_SECRET_KEY", raising=False)
    payload = {
        **VALID_JOB_PAYLOAD,
        "optimizer_strategy": "gpt",
        "openai": {"api_key": "sk-source"},
    }
    original = client.post("/api/v1/jobs", json=payload).json()["data"]
    resp = client.post(f"/api/v1/jobs/{original['id']}/rerun")
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "INVALID_INPUT"


def test_rerun_gpt_stays_gpt_with_new_openai_key(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("APP_SECRET_KEY", "dev-unit-test-key")
    monkeypatch.delenv("DRONEDREAM_SECRET_KEY", raising=False)
    payload = {
        **VALID_JOB_PAYLOAD,
        "optimizer_strategy": "gpt",
        "openai": {"api_key": "sk-source", "model": "gpt-4.1"},
    }
    original = client.post("/api/v1/jobs", json=payload).json()["data"]
    resp = client.post(
        f"/api/v1/jobs/{original['id']}/rerun",
        json={"openai": {"api_key": "sk-rerun"}},
    )
    assert resp.status_code == 200
    rerun = resp.json()["data"]
    assert rerun["optimizer_strategy"] == "gpt"


# --- Cancel ----------------------------------------------------------------


def test_cancel_queued_job(client: TestClient) -> None:
    job = client.post("/api/v1/jobs", json=HEURISTIC_JOB_PAYLOAD).json()["data"]
    resp = client.post(f"/api/v1/jobs/{job['id']}/cancel")
    assert resp.status_code == 200
    cancelled = resp.json()["data"]
    assert cancelled["status"] == "CANCELLED"
    assert cancelled["cancelled_at"] is not None


def test_cancel_twice_rejects(client: TestClient) -> None:
    job = client.post("/api/v1/jobs", json=HEURISTIC_JOB_PAYLOAD).json()["data"]
    assert client.post(f"/api/v1/jobs/{job['id']}/cancel").status_code == 200
    resp = client.post(f"/api/v1/jobs/{job['id']}/cancel")
    assert resp.status_code == 409
    body = resp.json()
    assert body["success"] is False
    assert body["error"]["code"] == "JOB_ALREADY_CANCELLED"


def test_cancel_not_found(client: TestClient) -> None:
    resp = client.post("/api/v1/jobs/job_missing/cancel")
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "JOB_NOT_FOUND"


# --- Report ----------------------------------------------------------------


def test_report_not_ready(client: TestClient) -> None:
    job = client.post("/api/v1/jobs", json=HEURISTIC_JOB_PAYLOAD).json()["data"]
    resp = client.get(f"/api/v1/jobs/{job['id']}/report")
    assert resp.status_code == 409
    body = resp.json()
    assert body["success"] is False
    assert body["error"]["code"] == "REPORT_NOT_READY"


def test_report_for_missing_job_returns_job_not_found(client: TestClient) -> None:
    resp = client.get("/api/v1/jobs/job_missing/report")
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "JOB_NOT_FOUND"


def _seed_job_with_report(
    *,
    status: str,
    report_status: str,
    latest_error_code: str | None = None,
) -> str:
    """Seed a job row (optionally with a JobReport) via a direct DB session.

    Returns the job_id. Requires that the shared test ``client`` fixture has
    already initialised the database.
    """

    from app import db as db_module
    from app import models

    baseline = {
        "rmse": 1.2, "max_error": 2.0, "overshoot_count": 3,
        "completion_time": 9.0, "score": 4.2,
    }
    optimized = {
        "rmse": 0.9, "max_error": 1.5, "overshoot_count": 2,
        "completion_time": 8.0, "score": 3.0,
    }
    comparison = [
        {"metric": "rmse", "label": "RMSE", "baseline": 1.2,
         "optimized": 0.9, "lower_is_better": True, "unit": "m"}
    ]
    best_params = {
        "kp_xy": 1.1, "kd_xy": 0.21, "ki_xy": 0.05,
        "vel_limit": 5.0, "accel_limit": 4.0, "disturbance_rejection": 0.5,
    }

    with db_module.SessionLocal() as db:
        job = models.Job(
            user_id=None,
            track_type="circle",
            start_point_x=0.0,
            start_point_y=0.0,
            altitude_m=3.0,
            wind_north=0.0, wind_east=0.0, wind_south=0.0, wind_west=0.0,
            sensor_noise_level="medium",
            objective_profile="robust",
            status=status,
            current_phase="failed" if status == "FAILED" else "completed",
            latest_error_code=latest_error_code,
            latest_error_message="seeded",
        )
        db.add(job)
        db.flush()
        db.add(
            models.JobReport(
                job_id=job.id,
                best_candidate_id="cand_seed",
                summary_text="best-so-far seeded",
                baseline_metric_json=baseline,
                optimized_metric_json=optimized,
                comparison_metric_json=comparison,
                best_parameter_json=best_params,
                report_status=report_status,
            )
        )
        db.commit()
        return str(job.id)


def test_failed_job_with_ready_report_returns_report(client: TestClient) -> None:
    """Phase 8: a FAILED GPT job with a best-so-far READY report returns it."""

    job_id = _seed_job_with_report(
        status="FAILED",
        report_status="READY",
        latest_error_code="MAX_ITERATIONS_REACHED",
    )
    resp = client.get(f"/api/v1/jobs/{job_id}/report")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["success"] is True
    assert body["data"]["best_candidate_id"] == "cand_seed"
    assert body["data"]["summary_text"] == "best-so-far seeded"
    assert body["data"]["optimized_metrics"]["rmse"] == 0.9


def test_failed_job_without_ready_report_still_returns_job_failed(
    client: TestClient,
) -> None:
    job_id = _seed_job_with_report(
        status="FAILED",
        report_status="FAILED",
        latest_error_code="ALL_TRIALS_FAILED",
    )
    resp = client.get(f"/api/v1/jobs/{job_id}/report")
    assert resp.status_code == 409
    body = resp.json()
    assert body["error"]["code"] == "JOB_FAILED"
    assert body["error"]["details"]["failure_code"] == "ALL_TRIALS_FAILED"


# --- Artifacts -------------------------------------------------------------


def test_artifacts_empty(client: TestClient) -> None:
    job = client.post("/api/v1/jobs", json=HEURISTIC_JOB_PAYLOAD).json()["data"]
    resp = client.get(f"/api/v1/jobs/{job['id']}/artifacts")
    assert resp.status_code == 200
    assert resp.json() == {"success": True, "data": [], "error": None}


def test_artifacts_includes_trial_scoped_artifacts(client: TestClient) -> None:
    """Phase 8: trial-level artifacts (e.g. real_cli trajectory plots) are
    returned from the job artifacts endpoint alongside job-level artifacts."""

    job = client.post("/api/v1/jobs", json=HEURISTIC_JOB_PAYLOAD).json()["data"]
    job_id = job["id"]

    from app import db as db_module
    from app import models

    with db_module.SessionLocal() as db:
        # Seed a trial row bound to this job.
        trial = models.Trial(
            job_id=job_id,
            candidate_id="cand_seed",
            seed=7,
            scenario_type="nominal",
            status="COMPLETED",
            attempt_count=1,
        )
        db.add(trial)
        db.flush()
        # Trial-scoped artifact (what real_cli writes).
        db.add(
            models.Artifact(
                owner_type="trial",
                owner_id=trial.id,
                artifact_type="trajectory_plot",
                display_name="Trajectory",
                storage_path="/tmp/trajectory.png",
                mime_type="image/png",
                file_size_bytes=1234,
            )
        )
        # Job-scoped artifact (what the report writer produces).
        db.add(
            models.Artifact(
                owner_type="job",
                owner_id=job_id,
                artifact_type="report_summary",
                display_name="Report",
                storage_path="/tmp/report.json",
                mime_type="application/json",
                file_size_bytes=56,
            )
        )
        db.commit()

    resp = client.get(f"/api/v1/jobs/{job_id}/artifacts")
    assert resp.status_code == 200, resp.text
    items = resp.json()["data"]
    owner_types = {a["owner_type"] for a in items}
    kinds = {a["artifact_type"] for a in items}
    assert "trial" in owner_types and "job" in owner_types
    assert "trajectory_plot" in kinds and "report_summary" in kinds
