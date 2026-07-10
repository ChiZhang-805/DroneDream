from __future__ import annotations

from fastapi.testclient import TestClient

from .test_jobs_api import HEURISTIC_JOB_PAYLOAD


def test_create_batch_creates_multiple_jobs(client: TestClient) -> None:
    payload = {
        "name": "sweep-a",
        "description": "benchmark set",
        "jobs": [
            {**HEURISTIC_JOB_PAYLOAD, "altitude_m": 4.0},
            {**HEURISTIC_JOB_PAYLOAD, "altitude_m": 6.0},
        ],
    }
    resp = client.post("/api/v1/batches", json=payload)
    assert resp.status_code == 200, resp.text
    batch = resp.json()["data"]
    assert batch["name"] == "sweep-a"
    assert batch["progress"]["total_jobs"] == 2

    jobs_resp = client.get(f"/api/v1/batches/{batch['id']}/jobs")
    assert jobs_resp.status_code == 200
    jobs = jobs_resp.json()["data"]
    assert len(jobs) == 2
    assert all(job["batch_id"] == batch["id"] for job in jobs)


def test_invalid_child_job_rolls_back_all(client: TestClient) -> None:
    payload = {
        "name": "bad-sweep",
        "jobs": [
            {**HEURISTIC_JOB_PAYLOAD, "altitude_m": 4.0},
            {**HEURISTIC_JOB_PAYLOAD, "altitude_m": 100.0},
        ],
    }
    resp = client.post("/api/v1/batches", json=payload)
    assert resp.status_code == 422

    batches_resp = client.get("/api/v1/batches")
    assert batches_resp.status_code == 200
    assert batches_resp.json()["data"]["total"] == 0

    jobs_resp = client.get("/api/v1/jobs")
    assert jobs_resp.status_code == 200
    assert jobs_resp.json()["data"]["total"] == 0


def test_batch_detail_aggregates_progress(client: TestClient) -> None:
    payload = {
        "name": "agg",
        "jobs": [{**HEURISTIC_JOB_PAYLOAD}, {**HEURISTIC_JOB_PAYLOAD}],
    }
    created = client.post("/api/v1/batches", json=payload).json()["data"]
    jobs = client.get(f"/api/v1/batches/{created['id']}/jobs").json()["data"]

    # terminalize children with one failure to assert batch FAILED semantics.
    from app import models
    from app.db import SessionLocal

    with SessionLocal() as db:
        first = db.get(models.Job, jobs[0]["id"])
        second = db.get(models.Job, jobs[1]["id"])
        assert first is not None
        assert second is not None
        first.status = "COMPLETED"
        second.status = "FAILED"
        db.commit()

    detail = client.get(f"/api/v1/batches/{created['id']}")
    assert detail.status_code == 200
    data = detail.json()["data"]
    assert data["status"] == "FAILED"
    assert data["progress"]["completed_jobs"] == 1
    assert data["progress"]["failed_jobs"] == 1
    assert data["progress"]["terminal_jobs"] == 2


def test_cancel_batch_cancels_non_terminal_children(client: TestClient) -> None:
    payload = {
        "name": "cancel-me",
        "jobs": [{**HEURISTIC_JOB_PAYLOAD}, {**HEURISTIC_JOB_PAYLOAD}],
    }
    created = client.post("/api/v1/batches", json=payload).json()["data"]
    jobs = client.get(f"/api/v1/batches/{created['id']}/jobs").json()["data"]

    # mark one job as already completed, then cancel batch.
    from app import models
    from app.db import SessionLocal

    with SessionLocal() as db:
        first = db.get(models.Job, jobs[0]["id"])
        assert first is not None
        first.status = "COMPLETED"
        db.commit()

    resp = client.post(f"/api/v1/batches/{created['id']}/cancel")
    assert resp.status_code == 200
    assert resp.json()["data"]["cancelled_at"] is not None

    jobs_after = client.get(f"/api/v1/batches/{created['id']}/jobs").json()["data"]
    by_id = {job["id"]: job for job in jobs_after}
    assert by_id[jobs[0]["id"]]["status"] == "COMPLETED"
    assert by_id[jobs[1]["id"]]["status"] == "CANCELLED"


def test_cancel_batch_purges_all_child_gpt_secrets(
    client: TestClient, monkeypatch
) -> None:
    monkeypatch.setenv("APP_SECRET_KEY", "unit-test-secret-material")
    gpt_job = {
        **HEURISTIC_JOB_PAYLOAD,
        "optimizer_strategy": "gpt",
        "max_iterations": 1,
        "openai": {"api_key": "sk-batch-cancel"},
    }
    response = client.post(
        "/api/v1/batches",
        json={"name": "gpt-cancel", "jobs": [gpt_job, gpt_job]},
    )
    assert response.status_code == 200, response.text
    batch_id = response.json()["data"]["id"]

    cancelled = client.post(f"/api/v1/batches/{batch_id}/cancel")
    assert cancelled.status_code == 200, cancelled.text
    assert cancelled.json()["data"]["status"] == "CANCELLED"

    from sqlalchemy import select

    from app import models
    from app.db import SessionLocal

    with SessionLocal() as db:
        batch = db.get(models.BatchJob, batch_id)
        assert batch is not None
        assert batch.status == "CANCELLED"
        child_ids = [job.id for job in batch.jobs]
        secrets = list(
            db.scalars(
                select(models.JobSecret).where(models.JobSecret.job_id.in_(child_ids))
            )
        )
        assert len(secrets) == 2
        assert all(secret.deleted_at is not None for secret in secrets)
        assert all(secret.encrypted_api_key == "" for secret in secrets)


def test_batch_aggregates_aggregating_child_as_running(client: TestClient) -> None:
    payload = {
        "name": "agg-running",
        "jobs": [{**HEURISTIC_JOB_PAYLOAD}, {**HEURISTIC_JOB_PAYLOAD}],
    }
    created = client.post("/api/v1/batches", json=payload).json()["data"]
    jobs = client.get(f"/api/v1/batches/{created['id']}/jobs").json()["data"]

    from app import models
    from app.db import SessionLocal

    with SessionLocal() as db:
        first = db.get(models.Job, jobs[0]["id"])
        second = db.get(models.Job, jobs[1]["id"])
        assert first is not None
        assert second is not None
        first.status = "AGGREGATING"
        second.status = "QUEUED"
        db.commit()

    detail = client.get(f"/api/v1/batches/{created['id']}")
    assert detail.status_code == 200
    assert detail.json()["data"]["status"] == "RUNNING"


def test_batch_aggregates_finalizing_child_as_running(client: TestClient) -> None:
    created = client.post(
        "/api/v1/batches",
        json={"name": "finalizing", "jobs": [{**HEURISTIC_JOB_PAYLOAD}]},
    ).json()["data"]
    jobs = client.get(f"/api/v1/batches/{created['id']}/jobs").json()["data"]

    from app import models
    from app.db import SessionLocal

    with SessionLocal() as db:
        child = db.get(models.Job, jobs[0]["id"])
        assert child is not None
        child.status = "FINALIZING"
        db.commit()

    detail = client.get(f"/api/v1/batches/{created['id']}")
    assert detail.status_code == 200, detail.text
    payload = detail.json()["data"]
    assert payload["status"] == "RUNNING"
    assert payload["progress"]["running_jobs"] == 1


def test_cancel_completed_batch_preserves_terminal_state(client: TestClient) -> None:
    created = client.post(
        "/api/v1/batches",
        json={"name": "already-complete", "jobs": [{**HEURISTIC_JOB_PAYLOAD}]},
    ).json()["data"]
    jobs = client.get(f"/api/v1/batches/{created['id']}/jobs").json()["data"]

    from datetime import datetime, timezone

    from app import models
    from app.db import SessionLocal

    with SessionLocal() as db:
        batch = db.get(models.BatchJob, created["id"])
        child = db.get(models.Job, jobs[0]["id"])
        assert batch is not None and child is not None
        child.status = "COMPLETED"
        child.completed_at = datetime.now(timezone.utc)
        batch.status = "COMPLETED"
        batch.completed_at = child.completed_at
        db.commit()

    response = client.post(f"/api/v1/batches/{created['id']}/cancel")

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "BATCH_ALREADY_TERMINAL"
    detail = client.get(f"/api/v1/batches/{created['id']}").json()["data"]
    assert detail["status"] == "COMPLETED"
    assert detail["cancelled_at"] is None
