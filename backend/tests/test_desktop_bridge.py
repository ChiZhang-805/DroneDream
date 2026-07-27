from __future__ import annotations

import hashlib
import hmac
import time
from uuid import uuid4

from fastapi.testclient import TestClient

from app.config import get_settings

RUNTIME_ID = "123e4567-e89b-12d3-a456-426614174000"
APP_SECRET = "desktop-unit-secret-0123456789-ABCDEFGH"
TOKEN_A = "desktop-token-a-0123456789-ABCDEFGH"
TOKEN_B = "desktop-token-b-0123456789-ABCDEFGH"


def _configure(monkeypatch: object) -> None:
    monkeypatch.setenv("APP_ENV", "desktop")
    monkeypatch.setenv("AUTH_MODE", "oidc_jwt")
    monkeypatch.setenv("OIDC_ISSUER", "https://identity.example.test/auth/v1")
    monkeypatch.setenv("OIDC_AUDIENCE", "authenticated")
    monkeypatch.setenv(
        "OIDC_JWKS_URL",
        "https://identity.example.test/auth/v1/.well-known/jwks.json",
    )
    monkeypatch.setenv("OIDC_ALGORITHMS", "ES256")
    monkeypatch.setenv("DRONEDREAM_RUNTIME_ID", RUNTIME_ID)
    monkeypatch.setenv("DESKTOP_BRIDGE_REQUIRED", "true")
    monkeypatch.setenv("APP_SECRET_KEY", APP_SECRET)
    from app import auth

    def decode(token: str, _settings: object) -> dict[str, str]:
        email = "a@example.com" if token == TOKEN_A else "b@example.com"
        return {
            "iss": "https://identity.example.test/auth/v1",
            "sub": f"subject-{email}",
            "aud": "authenticated",
            "exp": "4102444800",
            "email": email,
            "name": email,
        }

    monkeypatch.setattr(auth, "_decode_oidc_token", decode)
    get_settings.cache_clear()


def _proof(
    method: str,
    path_query: str,
    *,
    token: str = TOKEN_A,
    body: bytes = b"",
    runtime_id: str = RUNTIME_ID,
    nonce: str | None = None,
    session_id: str | None = None,
    timestamp: int | None = None,
) -> dict[str, str]:
    timestamp_text = str(int(time.time()) if timestamp is None else timestamp)
    nonce = nonce or str(uuid4())
    session_id = session_id or str(uuid4())
    authorization = f"Bearer {token}"
    body_sha256 = hashlib.sha256(body).hexdigest()
    authorization_sha256 = hashlib.sha256(authorization.encode()).hexdigest()
    canonical = "\n".join(
        (
            "DD-BRIDGE-V1",
            runtime_id,
            session_id,
            timestamp_text,
            nonce,
            method.upper(),
            path_query,
            body_sha256,
            authorization_sha256,
            "",
        )
    ).encode()
    key = hmac.new(
        APP_SECRET.encode(),
        b"dronedream-desktop-bridge-v1",
        hashlib.sha256,
    ).digest()
    signature = hmac.new(key, canonical, hashlib.sha256).hexdigest()
    return {
        "Authorization": authorization,
        "X-DroneDream-Bridge-Version": "DD-BRIDGE-V1",
        "X-DroneDream-Runtime-Id": runtime_id,
        "X-DroneDream-Session-Id": session_id,
        "X-DroneDream-Timestamp": timestamp_text,
        "X-DroneDream-Nonce": nonce,
        "X-DroneDream-Body-Sha256": body_sha256,
        "X-DroneDream-Signature": signature,
    }


def test_desktop_bridge_accepts_one_proof_and_rejects_replay(
    client: TestClient,
    monkeypatch: object,
) -> None:
    _configure(monkeypatch)
    headers = _proof("GET", "/api/v1/session")

    accepted = client.get("/api/v1/session", headers=headers)
    replay = client.get("/api/v1/session", headers=headers)

    assert accepted.status_code == 200
    assert accepted.json()["data"]["user_id"] == "subject-a@example.com"
    assert replay.status_code == 409
    assert replay.json()["error"]["code"] == "DESKTOP_BRIDGE_REPLAY"


def test_desktop_bridge_rejects_missing_wrong_runtime_expired_and_body_tamper(
    client: TestClient,
    monkeypatch: object,
) -> None:
    _configure(monkeypatch)
    missing = client.get(
        "/api/v1/session",
        headers={"Authorization": f"Bearer {TOKEN_A}"},
    )
    wrong_runtime = client.get(
        "/api/v1/session",
        headers=_proof(
            "GET",
            "/api/v1/session",
            runtime_id="123e4567-e89b-12d3-a456-426614174001",
        ),
    )
    expired = client.get(
        "/api/v1/session",
        headers=_proof(
            "GET",
            "/api/v1/session",
            timestamp=int(time.time()) - 120,
        ),
    )
    body = b'{"display_name":"expected"}'
    tampered = client.patch(
        "/api/v1/jobs/missing",
        headers={
            **_proof(
                "PATCH",
                "/api/v1/jobs/missing",
                body=body,
            ),
            "Content-Type": "application/json",
        },
        content=b'{"display_name":"altered"}',
    )

    assert missing.json()["error"]["code"] == "DESKTOP_BRIDGE_REQUIRED"
    assert wrong_runtime.json()["error"]["code"] == "DESKTOP_BRIDGE_RUNTIME_MISMATCH"
    assert expired.json()["error"]["code"] == "DESKTOP_BRIDGE_EXPIRED"
    assert tampered.json()["error"]["code"] == "DESKTOP_BRIDGE_BODY_MISMATCH"


def test_desktop_bridge_preserves_user_ownership_boundary(
    client: TestClient,
    monkeypatch: object,
) -> None:
    _configure(monkeypatch)
    payload = (
        b'{"track_type":"circle","start_point":{"x":0,"y":0},"altitude_m":5,'
        b'"wind":{"north":0,"east":0,"south":0,"west":0},'
        b'"sensor_noise_level":"medium","objective_profile":"robust",'
        b'"optimizer_strategy":"heuristic","simulator_backend":"mock"}'
    )
    created = client.post(
        "/api/v1/jobs",
        headers={
            **_proof("POST", "/api/v1/jobs", body=payload),
            "Content-Type": "application/json",
        },
        content=payload,
    )
    assert created.status_code == 200
    job_id = created.json()["data"]["id"]

    foreign_path = f"/api/v1/jobs/{job_id}"
    foreign = client.get(
        foreign_path,
        headers=_proof("GET", foreign_path, token=TOKEN_B),
    )
    assert foreign.status_code == 404


def test_desktop_bridge_does_not_wrap_public_health(
    client: TestClient,
    monkeypatch: object,
) -> None:
    _configure(monkeypatch)
    response = client.get("/health/live")
    assert response.status_code == 200
