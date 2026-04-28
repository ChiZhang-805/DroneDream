from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from app import db, models
from app.config import get_settings

PAYLOAD = {
    "track_type": "circle",
    "start_point": {"x": 0, "y": 0},
    "altitude_m": 5.0,
    "wind": {"north": 0, "east": 0, "south": 0, "west": 0},
    "sensor_noise_level": "medium",
    "objective_profile": "robust",
    "optimizer_strategy": "heuristic",
    "simulator_backend": "mock",
}


def test_demo_token_requires_auth(client: TestClient, monkeypatch) -> None:
    monkeypatch.setenv("AUTH_MODE", "demo_token")
    monkeypatch.setenv("DEMO_AUTH_TOKENS", "a@example.com:token-a")
    get_settings.cache_clear()
    resp = client.post("/api/v1/jobs", json=PAYLOAD)
    assert resp.status_code == 401


def test_demo_token_isolates_jobs_by_user(client: TestClient, monkeypatch) -> None:
    monkeypatch.setenv("AUTH_MODE", "demo_token")
    monkeypatch.setenv("DEMO_AUTH_TOKENS", "a@example.com:token-a,b@example.com:token-b")
    get_settings.cache_clear()

    created = client.post(
        "/api/v1/jobs",
        headers={"Authorization": "Bearer token-a"},
        json=PAYLOAD,
    )
    assert created.status_code == 200
    job_id = created.json()["data"]["id"]

    denied = client.get(f"/api/v1/jobs/{job_id}", headers={"Authorization": "Bearer token-b"})
    assert denied.status_code == 404


def test_artifact_download_enforces_user_isolation(
    client: TestClient, monkeypatch: object, tmp_path: Path
) -> None:
    monkeypatch.setenv("AUTH_MODE", "demo_token")
    monkeypatch.setenv("DEMO_AUTH_TOKENS", "a@example.com:token-a,b@example.com:token-b")
    get_settings.cache_clear()

    created = client.post(
        "/api/v1/jobs",
        headers={"Authorization": "Bearer token-a"},
        json=PAYLOAD,
    )
    job_id = created.json()["data"]["id"]

    f = tmp_path / "artifact.txt"
    f.write_text("hello", encoding="utf-8")
    with db.SessionLocal() as session:
        artifact = models.Artifact(
            owner_type="job",
            owner_id=job_id,
            artifact_type="job_events_log",
            display_name="artifact.txt",
            storage_path=str(f),
            mime_type="text/plain",
            file_size_bytes=f.stat().st_size,
        )
        session.add(artifact)
        session.commit()
        artifact_id = artifact.id

    resp = client.get(
        f"/api/v1/artifacts/{artifact_id}/download",
        headers={"Authorization": "Bearer token-b"},
    )
    assert resp.status_code == 404


def test_auth_mode_disabled_allows_requests_without_token(client: TestClient, monkeypatch) -> None:
    monkeypatch.setenv("AUTH_MODE", "disabled")
    monkeypatch.delenv("DEMO_AUTH_TOKENS", raising=False)
    get_settings.cache_clear()

    created = client.post("/api/v1/jobs", json=PAYLOAD)
    assert created.status_code == 200


def test_demo_token_artifact_isolation_for_trial_owner(
    client: TestClient, monkeypatch: object, tmp_path: Path
) -> None:
    monkeypatch.setenv("AUTH_MODE", "demo_token")
    monkeypatch.setenv("DEMO_AUTH_TOKENS", "a@example.com:token-a,b@example.com:token-b")
    get_settings.cache_clear()

    created = client.post(
        "/api/v1/jobs",
        headers={"Authorization": "Bearer token-a"},
        json=PAYLOAD,
    )
    job_id = created.json()["data"]["id"]

    with db.SessionLocal() as session:
        candidate = models.CandidateParameterSet(
            job_id=job_id,
            generation_index=0,
            source_type="baseline",
            parameter_json={},
        )
        session.add(candidate)
        session.flush()
        trial = models.Trial(
            job_id=job_id,
            candidate_id=candidate.id,
            seed=1,
            scenario_type="nominal",
            status="COMPLETED",
        )
        session.add(trial)
        session.commit()
        trial_id = trial.id

    f = tmp_path / "trial-artifact.txt"
    f.write_text("hello", encoding="utf-8")
    with db.SessionLocal() as session:
        artifact = models.Artifact(
            owner_type="trial",
            owner_id=trial_id,
            artifact_type="worker_log",
            display_name="trial-artifact.txt",
            storage_path=str(f),
            mime_type="text/plain",
            file_size_bytes=f.stat().st_size,
        )
        session.add(artifact)
        session.commit()
        artifact_id = artifact.id

    resp = client.get(
        f"/api/v1/artifacts/{artifact_id}/download",
        headers={"Authorization": "Bearer token-b"},
    )
    assert resp.status_code == 404


def test_demo_token_never_leaks_into_job_endpoints(client: TestClient, monkeypatch) -> None:
    monkeypatch.setenv("AUTH_MODE", "demo_token")
    monkeypatch.setenv("DEMO_AUTH_TOKENS", "a@example.com:token-a,b@example.com:token-b")
    get_settings.cache_clear()

    created = client.post(
        "/api/v1/jobs",
        headers={"Authorization": "Bearer token-a"},
        json=PAYLOAD,
    )
    job_id = created.json()["data"]["id"]

    for url in (
        f"/api/v1/jobs/{job_id}",
        f"/api/v1/jobs/{job_id}/report",
        f"/api/v1/jobs/{job_id}/artifacts",
    ):
        resp = client.get(url, headers={"Authorization": "Bearer token-a"})
        blob = json.dumps(resp.json())
        assert "token-a" not in blob
        assert "token-b" not in blob
