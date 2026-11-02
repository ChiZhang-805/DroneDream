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

    oversized = client.post(
        "/api/v1/jobs",
        headers={"Authorization": "Bearer " + "x" * 16_385},
        json=PAYLOAD,
    )
    assert oversized.status_code == 401
    assert "x" * 100 not in oversized.text


def test_authenticated_session_requires_and_returns_current_identity(
    client: TestClient,
    monkeypatch,
) -> None:
    monkeypatch.setenv("AUTH_MODE", "demo_token")
    monkeypatch.setenv("DEMO_AUTH_TOKENS", "a@example.com:token-a")
    get_settings.cache_clear()

    denied = client.get("/api/v1/session")
    assert denied.status_code == 401

    accepted = client.get(
        "/api/v1/session",
        headers={"Authorization": "Bearer token-a"},
    )
    assert accepted.status_code == 200
    assert accepted.json()["data"] == {
        "status": "ready",
        "user_id": "a@example.com",
    }


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

    with db.SessionLocal() as session:
        local_user = session.query(models.User).filter_by(
            email="default@drone-dream.local"
        ).one()
        assert local_user.identity_provider == "urn:dronedream:local"
        assert local_user.external_subject == "default@drone-dream.local"


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


def test_oidc_subjects_are_isolated_even_when_email_matches(
    client: TestClient, monkeypatch
) -> None:
    monkeypatch.setenv("AUTH_MODE", "oidc_jwt")
    monkeypatch.setenv("OIDC_ISSUER", "https://identity.example.test/")
    monkeypatch.setenv("OIDC_AUDIENCE", "dronedream-api")
    monkeypatch.setenv("OIDC_JWKS_URL", "https://identity.example.test/jwks.json")
    get_settings.cache_clear()

    def fake_decode(token: str, _settings) -> dict[str, object]:
        return {
            "sub": "subject-a" if token == "token-a" else "subject-b",
            "email": "shared@example.com",
            "name": "OIDC User",
        }

    monkeypatch.setattr("app.auth._decode_oidc_token", fake_decode)
    created = client.post(
        "/api/v1/jobs",
        headers={"Authorization": "Bearer token-a"},
        json=PAYLOAD,
    )
    assert created.status_code == 200, created.text
    job_id = created.json()["data"]["id"]
    denied = client.get(
        f"/api/v1/jobs/{job_id}", headers={"Authorization": "Bearer token-b"}
    )
    assert denied.status_code == 404


def test_demo_identity_does_not_adopt_oidc_user_with_same_email(
    client: TestClient, monkeypatch
) -> None:
    monkeypatch.setenv("AUTH_MODE", "oidc_jwt")
    monkeypatch.setenv("OIDC_ISSUER", "https://identity.example.test/")
    monkeypatch.setenv("OIDC_AUDIENCE", "dronedream-api")
    monkeypatch.setenv("OIDC_JWKS_URL", "https://identity.example.test/jwks.json")
    get_settings.cache_clear()

    monkeypatch.setattr(
        "app.auth._decode_oidc_token",
        lambda _token, _settings: {
            "sub": "oidc-subject",
            "email": "shared@example.com",
            "name": "OIDC User",
        },
    )
    oidc_job = client.post(
        "/api/v1/jobs",
        headers={"Authorization": "Bearer oidc-token"},
        json=PAYLOAD,
    )
    assert oidc_job.status_code == 200, oidc_job.text
    oidc_job_id = oidc_job.json()["data"]["id"]

    monkeypatch.setenv("AUTH_MODE", "demo_token")
    monkeypatch.setenv("DEMO_AUTH_TOKENS", "shared@example.com:demo-token")
    get_settings.cache_clear()
    demo_job = client.post(
        "/api/v1/jobs",
        headers={"Authorization": "Bearer demo-token"},
        json=PAYLOAD,
    )
    assert demo_job.status_code == 200, demo_job.text

    denied = client.get(
        f"/api/v1/jobs/{oidc_job_id}",
        headers={"Authorization": "Bearer demo-token"},
    )
    assert denied.status_code == 404

    with db.SessionLocal() as session:
        users = list(
            session.query(models.User)
            .filter(models.User.email == "shared@example.com")
            .all()
        )
        assert len(users) == 2
        assert {user.identity_provider for user in users} == {
            "https://identity.example.test/",
            "urn:dronedream:local",
        }


def test_demo_token_hides_other_and_legacy_unowned_batches(
    client: TestClient, monkeypatch
) -> None:
    monkeypatch.setenv("AUTH_MODE", "demo_token")
    monkeypatch.setenv("DEMO_AUTH_TOKENS", "a@example.com:token-a,b@example.com:token-b")
    get_settings.cache_clear()

    created = client.post(
        "/api/v1/batches",
        headers={"Authorization": "Bearer token-a"},
        json={"name": "owned-by-a", "jobs": [PAYLOAD]},
    )
    assert created.status_code == 200, created.text
    owned_id = created.json()["data"]["id"]

    with db.SessionLocal() as session:
        legacy = models.BatchJob(user_id=None, name="legacy-unowned", status="QUEUED")
        session.add(legacy)
        session.commit()
        legacy_id = legacy.id

    listing = client.get(
        "/api/v1/batches", headers={"Authorization": "Bearer token-b"}
    )
    assert listing.status_code == 200
    assert listing.json()["data"]["items"] == []
    assert (
        client.get(
            f"/api/v1/batches/{owned_id}",
            headers={"Authorization": "Bearer token-b"},
        ).status_code
        == 404
    )
    assert (
        client.get(
            f"/api/v1/batches/{legacy_id}",
            headers={"Authorization": "Bearer token-b"},
        ).status_code
        == 404
    )


def test_oidc_invalid_token_returns_bearer_challenge(
    client: TestClient, monkeypatch
) -> None:
    monkeypatch.setenv("AUTH_MODE", "oidc_jwt")
    monkeypatch.setenv("OIDC_ISSUER", "https://identity.example.test/")
    monkeypatch.setenv("OIDC_AUDIENCE", "dronedream-api")
    monkeypatch.setenv("OIDC_JWKS_URL", "https://identity.example.test/jwks.json")
    get_settings.cache_clear()

    def reject_token(_token: str, _settings) -> dict[str, object]:
        raise ValueError("bad signature")

    monkeypatch.setattr("app.auth._decode_oidc_token", reject_token)
    response = client.get(
        "/api/v1/jobs", headers={"Authorization": "Bearer invalid"}
    )
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
