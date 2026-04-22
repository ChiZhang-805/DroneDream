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
