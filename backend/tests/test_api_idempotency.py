"""Business-effect idempotency across retries, restarts, and conflicts."""

from __future__ import annotations

import hashlib
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from .test_jobs_api import HEURISTIC_JOB_PAYLOAD


def _key() -> str:
    return str(uuid4())


def _headers(key: str) -> dict[str, str]:
    return {"Idempotency-Key": key}


def test_create_job_replays_exact_response_and_persists_one_job(
    client: TestClient,
) -> None:
    key = _key()

    first = client.post(
        "/api/v1/jobs",
        json=HEURISTIC_JOB_PAYLOAD,
        headers=_headers(key),
    )
    replay = client.post(
        "/api/v1/jobs",
        json=HEURISTIC_JOB_PAYLOAD,
        headers=_headers(key),
    )

    assert first.status_code == 200, first.text
    assert replay.status_code == 200, replay.text
    assert replay.json() == first.json()

    from app import models
    from app.db import SessionLocal

    with SessionLocal() as db:
        assert db.scalar(select(func.count(models.Job.id))) == 1
        receipt = db.scalar(
            select(models.ApiIdempotencyRecord).where(
                models.ApiIdempotencyRecord.idempotency_key_hash
                == hashlib.sha256(key.encode("ascii")).hexdigest()
            )
        )
        assert receipt is not None
        assert receipt.status == "COMPLETED"
        assert receipt.operation == "jobs.create"
        assert receipt.resource_id == first.json()["data"]["id"]
        assert receipt.response_json == first.json()


def test_concurrent_same_key_creates_only_one_job(client: TestClient) -> None:
    key = _key()

    def submit() -> tuple[int, dict[str, object]]:
        response = client.post(
            "/api/v1/jobs",
            json=HEURISTIC_JOB_PAYLOAD,
            headers=_headers(key),
        )
        return response.status_code, response.json()

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _index: submit(), range(2)))

    assert [status for status, _body in results] == [200, 200]
    assert results[0][1] == results[1][1]

    from app import models
    from app.db import SessionLocal

    with SessionLocal() as db:
        assert db.scalar(select(func.count(models.Job.id))) == 1
        assert db.scalar(select(func.count(models.ApiIdempotencyRecord.id))) == 1


def test_changed_body_with_same_key_is_a_conflict(client: TestClient) -> None:
    key = _key()
    first = client.post(
        "/api/v1/jobs",
        json=HEURISTIC_JOB_PAYLOAD,
        headers=_headers(key),
    )
    conflict = client.post(
        "/api/v1/jobs",
        json={**HEURISTIC_JOB_PAYLOAD, "altitude_m": 8.0},
        headers=_headers(key),
    )

    assert first.status_code == 200
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "IDEMPOTENCY_CONFLICT"

    from app import models
    from app.db import SessionLocal

    with SessionLocal() as db:
        assert db.scalar(select(func.count(models.Job.id))) == 1


def test_key_cannot_be_reused_for_another_operation(client: TestClient) -> None:
    key = _key()
    created = client.post(
        "/api/v1/jobs",
        json=HEURISTIC_JOB_PAYLOAD,
        headers=_headers(key),
    )
    job_id = created.json()["data"]["id"]

    conflict = client.patch(
        f"/api/v1/jobs/{job_id}",
        json={"display_name": "renamed"},
        headers=_headers(key),
    )

    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "IDEMPOTENCY_CONFLICT"


def test_failed_mutation_rolls_back_key_for_a_corrected_retry(client: TestClient) -> None:
    key = _key()
    missing_credential = {
        **HEURISTIC_JOB_PAYLOAD,
        "optimizer_strategy": "gpt",
    }
    rejected = client.post(
        "/api/v1/jobs",
        json=missing_credential,
        headers=_headers(key),
    )
    corrected = client.post(
        "/api/v1/jobs",
        json=HEURISTIC_JOB_PAYLOAD,
        headers=_headers(key),
    )

    assert rejected.status_code == 422
    assert corrected.status_code == 200, corrected.text


def test_cancel_replay_does_not_repeat_terminal_transition(
    client: TestClient,
) -> None:
    created = client.post("/api/v1/jobs", json=HEURISTIC_JOB_PAYLOAD)
    job_id = created.json()["data"]["id"]
    key = _key()

    first = client.post(
        f"/api/v1/jobs/{job_id}/cancel",
        headers=_headers(key),
    )
    replay = client.post(
        f"/api/v1/jobs/{job_id}/cancel",
        headers=_headers(key),
    )

    assert first.status_code == 200, first.text
    assert replay.status_code == 200, replay.text
    assert replay.json() == first.json()

    from app import models
    from app.db import SessionLocal

    with SessionLocal() as db:
        event_count = db.scalar(
            select(func.count(models.JobEvent.id)).where(
                models.JobEvent.job_id == job_id,
                models.JobEvent.event_type == "job_cancelled",
            )
        )
        assert event_count == 1


def test_delete_replay_survives_resource_removal(client: TestClient) -> None:
    created = client.post("/api/v1/jobs", json=HEURISTIC_JOB_PAYLOAD)
    job_id = created.json()["data"]["id"]

    from app import models
    from app.db import SessionLocal

    with SessionLocal() as db:
        job = db.get(models.Job, job_id)
        assert job is not None
        job.status = "COMPLETED"
        db.commit()

    key = _key()
    first = client.delete(
        f"/api/v1/jobs/{job_id}",
        headers=_headers(key),
    )
    replay = client.delete(
        f"/api/v1/jobs/{job_id}",
        headers=_headers(key),
    )

    assert first.status_code == 200, first.text
    assert replay.status_code == 200, replay.text
    assert replay.json() == first.json()
    with SessionLocal() as db:
        assert db.get(models.Job, job_id) is None


def test_batch_create_replays_without_duplicate_children(client: TestClient) -> None:
    key = _key()
    payload = {
        "name": "idempotent-sweep",
        "jobs": [
            {**HEURISTIC_JOB_PAYLOAD, "altitude_m": 4.0},
            {**HEURISTIC_JOB_PAYLOAD, "altitude_m": 6.0},
        ],
    }

    first = client.post(
        "/api/v1/batches",
        json=payload,
        headers=_headers(key),
    )
    replay = client.post(
        "/api/v1/batches",
        json=payload,
        headers=_headers(key),
    )

    assert first.status_code == 200, first.text
    assert replay.status_code == 200, replay.text
    assert replay.json() == first.json()

    from app import models
    from app.db import SessionLocal

    with SessionLocal() as db:
        assert db.scalar(select(func.count(models.BatchJob.id))) == 1
        assert db.scalar(select(func.count(models.Job.id))) == 2


def test_malformed_key_is_rejected_before_domain_change(client: TestClient) -> None:
    response = client.post(
        "/api/v1/jobs",
        json=HEURISTIC_JOB_PAYLOAD,
        headers=_headers("not-a-uuid"),
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "IDEMPOTENCY_KEY_INVALID"

    from app import models
    from app.db import SessionLocal

    with SessionLocal() as db:
        assert db.scalar(select(func.count(models.Job.id))) == 0
