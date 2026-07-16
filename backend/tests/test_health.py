"""Smoke tests for the health endpoint and response envelope."""

from __future__ import annotations

import sys

from app.main import app, create_app
from app.response import err, ok
from fastapi.testclient import TestClient
from pydantic import BaseModel, Field


def test_health_returns_ok_envelope() -> None:
    client = TestClient(app)
    response = client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["error"] is None
    assert body["data"]["status"] == "ok"
    assert body["data"]["service"] == "drone-dream-backend"
    assert body["data"]["runtime_id"] is None


def test_liveness_alias_returns_ok() -> None:
    response = TestClient(app).get("/health/live")
    assert response.status_code == 200
    assert response.json()["data"]["status"] == "ok"


def test_readiness_checks_database_storage_and_optional_worker() -> None:
    response = TestClient(app).get("/health/ready")
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["status"] == "ready"
    assert data["components"]["database"]["ok"] is True
    assert data["components"]["storage"]["ok"] is True
    assert data["components"]["worker"]["status"] == "not_required"
    assert data["runtime_id"] is None


def test_packaged_runtime_requires_worker_and_simulator_executables(monkeypatch) -> None:
    from app import config as config_module

    runtime_id = "123e4567-e89b-12d3-a456-426614174000"
    monkeypatch.setenv("DRONEDREAM_RUNTIME_ID", runtime_id)
    monkeypatch.delenv("REDIS_URL", raising=False)
    monkeypatch.delenv("DRONEDREAM_PX4_EXECUTABLE", raising=False)
    monkeypatch.delenv("DRONEDREAM_GAZEBO_EXECUTABLE", raising=False)
    config_module.get_settings.cache_clear()
    try:
        response = TestClient(app).get("/health/ready")
        assert response.status_code == 503
        data = response.json()["data"]
        assert data["runtime_id"] == runtime_id
        assert data["components"]["worker"]["status"] == "not_configured"
        assert data["components"]["px4"]["status"] == "not_configured"
        assert data["components"]["gazebo"]["status"] == "not_configured"
    finally:
        config_module.get_settings.cache_clear()


def test_packaged_runtime_is_ready_with_live_worker_and_executables(monkeypatch) -> None:
    from app import config as config_module
    from app.orchestration import worker_presence as worker_presence_module

    runtime_id = "123e4567-e89b-12d3-a456-426614174000"
    monkeypatch.setenv("DRONEDREAM_RUNTIME_ID", runtime_id)
    monkeypatch.setenv("DRONEDREAM_PX4_EXECUTABLE", sys.executable)
    monkeypatch.setenv("DRONEDREAM_GAZEBO_EXECUTABLE", sys.executable)
    monkeypatch.setattr(
        worker_presence_module,
        "worker_presence_health",
        lambda: {"ok": True, "status": "available", "worker_id": "test-worker"},
    )
    config_module.get_settings.cache_clear()
    try:
        response = TestClient(app).get("/health/ready")
        assert response.status_code == 200
        data = response.json()["data"]
        assert data["runtime_id"] == runtime_id
        assert data["components"]["worker"]["status"] == "available"
        assert data["components"]["px4"]["status"] == "available"
        assert data["components"]["gazebo"]["status"] == "available"
        assert "path" not in data["components"]["px4"]
        assert sys.executable not in response.text
    finally:
        config_module.get_settings.cache_clear()


def test_readiness_fails_when_required_worker_signal_is_not_configured(monkeypatch) -> None:
    from app import config as config_module

    monkeypatch.setenv("REQUIRE_WORKER_HEARTBEAT", "true")
    monkeypatch.delenv("REDIS_URL", raising=False)
    config_module.get_settings.cache_clear()
    try:
        response = TestClient(app).get("/health/ready")
        assert response.status_code == 503
        data = response.json()["data"]
        assert data["status"] == "not_ready"
        assert data["components"]["worker"]["status"] == "not_configured"
    finally:
        config_module.get_settings.cache_clear()


def test_envelope_helpers_shape() -> None:
    success = ok({"foo": 1})
    assert success == {"success": True, "data": {"foo": 1}, "error": None}

    error = err("INVALID_INPUT", "bad")
    assert error == {
        "success": False,
        "data": None,
        "error": {"code": "INVALID_INPUT", "message": "bad", "details": None},
    }


def test_unknown_route_returns_error_envelope() -> None:
    client = TestClient(app)
    response = client.get("/does-not-exist")
    assert response.status_code == 404
    body = response.json()
    assert body["success"] is False
    assert body["data"] is None
    assert body["error"]["code"] == "NOT_FOUND"


def test_unhandled_exception_uses_sanitized_error_envelope(caplog) -> None:
    local_app = create_app()
    caplog.set_level("ERROR", logger="drone_dream.backend")

    def explode() -> None:
        raise RuntimeError("private database detail")

    local_app.add_api_route("/explode", explode)
    response = TestClient(local_app, raise_server_exceptions=False).get("/explode")
    assert response.status_code == 500
    assert response.json() == {
        "success": False,
        "data": None,
        "error": {
            "code": "INTERNAL_ERROR",
            "message": "An unexpected internal error occurred.",
            "details": None,
        },
    }
    assert "private database detail" not in response.text
    assert "private database detail" not in caplog.text
    assert "exception_type=RuntimeError" in caplog.text


def test_validation_error_never_echoes_rejected_secret_input() -> None:
    class SecretRequest(BaseModel):
        api_key: str = Field(max_length=4)

    local_app = create_app()

    def receive_secret(_request: SecretRequest) -> dict[str, bool]:
        return {"ok": True}

    local_app.add_api_route("/secret", receive_secret, methods=["POST"])
    response = TestClient(local_app).post("/secret", json={"api_key": "do-not-echo"})
    assert response.status_code == 422
    assert "do-not-echo" not in response.text
