"""Optimistic fences for user-authored Job and Batch control commands."""

from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

from fastapi.testclient import TestClient

from .test_jobs_api import HEURISTIC_JOB_PAYLOAD


def _idempotency_headers() -> dict[str, str]:
    return {"Idempotency-Key": str(uuid4())}


def test_job_control_version_advances_and_rejects_a_stale_command(
    client: TestClient,
) -> None:
    created = client.post("/api/v1/jobs", json=HEURISTIC_JOB_PAYLOAD).json()["data"]
    assert created["control_version"] == 1

    renamed = client.patch(
        f"/api/v1/jobs/{created['id']}?control_version=1",
        json={"display_name": "first accepted name"},
        headers=_idempotency_headers(),
    )
    assert renamed.status_code == 200, renamed.text
    assert renamed.json()["data"]["control_version"] == 2

    stale = client.post(
        f"/api/v1/jobs/{created['id']}/cancel?control_version=1",
        headers=_idempotency_headers(),
    )
    assert stale.status_code == 409, stale.text
    assert stale.json()["error"]["code"] == "CONTROL_VERSION_CONFLICT"

    current = client.get(f"/api/v1/jobs/{created['id']}").json()["data"]
    assert current["display_name"] == "first accepted name"
    assert current["status"] == "QUEUED"
    assert current["control_version"] == 2


def test_exact_idempotent_replay_precedes_control_version_validation(
    client: TestClient,
) -> None:
    created = client.post("/api/v1/jobs", json=HEURISTIC_JOB_PAYLOAD).json()["data"]
    headers = _idempotency_headers()
    path = f"/api/v1/jobs/{created['id']}?control_version={created['control_version']}"
    payload = {"display_name": "stable replay"}

    first = client.patch(path, json=payload, headers=headers)
    replay = client.patch(path, json=payload, headers=headers)

    assert first.status_code == 200, first.text
    assert replay.status_code == 200, replay.text
    assert replay.json() == first.json()
    assert replay.json()["data"]["control_version"] == 2


def test_protected_runtime_requires_an_explicit_control_version(
    client: TestClient,
    monkeypatch,
) -> None:
    created = client.post("/api/v1/jobs", json=HEURISTIC_JOB_PAYLOAD).json()["data"]

    import app.services.jobs as jobs_service

    monkeypatch.setattr(
        jobs_service,
        "get_settings",
        lambda: SimpleNamespace(app_env="production", auth_mode="disabled"),
    )
    response = client.patch(
        f"/api/v1/jobs/{created['id']}",
        json={"display_name": "must not be applied"},
        headers=_idempotency_headers(),
    )

    assert response.status_code == 428, response.text
    assert response.json()["error"]["code"] == "CONTROL_VERSION_REQUIRED"
    current = client.get(f"/api/v1/jobs/{created['id']}").json()["data"]
    assert current["display_name"] is None
    assert current["control_version"] == 1


def test_batch_control_version_advances_and_rejects_a_stale_view(
    client: TestClient,
) -> None:
    created = client.post(
        "/api/v1/batches",
        json={
            "name": "versioned-batch",
            "jobs": [{**HEURISTIC_JOB_PAYLOAD}],
        },
    ).json()["data"]
    assert created["control_version"] == 1

    from app import models
    from app.db import SessionLocal

    with SessionLocal() as db:
        batch = db.get(models.BatchJob, created["id"])
        assert batch is not None
        batch.control_version = 2
        db.commit()

    stale = client.post(
        f"/api/v1/batches/{created['id']}/cancel?control_version=1",
        headers=_idempotency_headers(),
    )

    assert stale.status_code == 409, stale.text
    assert stale.json()["error"]["code"] == "CONTROL_VERSION_CONFLICT"
    current = client.get(f"/api/v1/batches/{created['id']}").json()["data"]
    assert current["control_version"] == 2
    assert current["status"] != "CANCELLED"


def test_batch_cancel_rolls_back_if_a_child_never_stabilizes(
    client: TestClient,
    monkeypatch,
) -> None:
    created = client.post(
        "/api/v1/batches",
        json={
            "name": "racing-child",
            "jobs": [{**HEURISTIC_JOB_PAYLOAD}],
        },
    ).json()["data"]

    import app.services.jobs as jobs_service

    monkeypatch.setattr(
        jobs_service,
        "_claim_job_cancellation",
        lambda *_args, **_kwargs: False,
    )
    response = client.post(
        (
            f"/api/v1/batches/{created['id']}/cancel"
            f"?control_version={created['control_version']}"
        ),
        headers=_idempotency_headers(),
    )

    assert response.status_code == 409, response.text
    assert response.json()["error"]["code"] == "BATCH_CHILD_CONTROL_CONFLICT"
    current = client.get(f"/api/v1/batches/{created['id']}").json()["data"]
    assert current["control_version"] == 1
    assert current["status"] != "CANCELLED"
