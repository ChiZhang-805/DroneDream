"""Smoke tests for the health endpoint and response envelope."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app
from app.response import err, ok


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


def test_readiness_reports_the_configured_desktop_runtime_identity(monkeypatch) -> None:
    from app import config as config_module

    runtime_id = "123e4567-e89b-12d3-a456-426614174000"
    monkeypatch.setenv("DRONEDREAM_RUNTIME_ID", runtime_id)
    config_module.get_settings.cache_clear()
    try:
        response = TestClient(app).get("/health/ready")
        assert response.status_code == 200
        assert response.json()["data"]["runtime_id"] == runtime_id
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
