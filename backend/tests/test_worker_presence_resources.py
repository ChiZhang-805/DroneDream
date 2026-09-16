"""Presence probes must release short-lived Redis clients on every outcome."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from app.orchestration import worker_presence


class _RedisProbe:
    """Track socket-owner lifetime without opening any network connection."""

    def __init__(self, payload: str, *, failure: bool = False) -> None:
        self.payload = payload
        self.failure = failure
        self.closed = False

    def close(self) -> None:
        self.closed = True

    def ping(self) -> bool:
        if self.failure:
            raise RuntimeError("redis://operator:private-value@example.invalid")
        return True

    def getrange(self, _key: str, _start: int, _end: int) -> str:
        return self.payload

    def set(self, _key: str, _payload: str, *, ex: int) -> bool:
        return self.ping()


def _configure(monkeypatch: pytest.MonkeyPatch, client: _RedisProbe) -> None:
    monkeypatch.setattr(
        worker_presence,
        "_settings",
        lambda: SimpleNamespace(
            redis_url="redis://example.invalid/0",
            worker_presence_key="workers:test",
            worker_presence_ttl_seconds=60,
            require_worker_heartbeat=True,
        ),
    )
    monkeypatch.setattr(worker_presence, "_client", lambda: client)


@pytest.mark.parametrize("payload", ("", "[]", "invalid json"))
def test_probe_closes_connection_on_rejected_signal(
    monkeypatch: pytest.MonkeyPatch, payload: str
) -> None:
    client = _RedisProbe(payload)
    _configure(monkeypatch, client)
    assert worker_presence.worker_presence_health()["ok"] is False
    assert client.closed


def test_probe_closes_connection_on_valid_signal(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _RedisProbe(json.dumps({
        "worker_id": "worker",
        "observed_at_epoch": worker_presence._now().timestamp(),
    }))
    _configure(monkeypatch, client)
    assert worker_presence.worker_presence_health()["ok"] is True
    assert client.closed


@pytest.mark.parametrize("failure", (False, True))
def test_publisher_closes_connection_and_redacts_failure(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, failure: bool
) -> None:
    client = _RedisProbe("", failure=failure)
    _configure(monkeypatch, client)
    assert worker_presence.publish_worker_heartbeat("worker") is not failure
    assert client.closed
    assert "private-value" not in caplog.text


def test_connection_failure_still_releases_probe(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _RedisProbe("", failure=True)
    _configure(monkeypatch, client)
    assert worker_presence.worker_presence_health()["status"] == "unavailable"
    assert client.closed


def test_unrepresentable_epoch_is_invalid_signal_not_transport_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _RedisProbe(json.dumps({"worker_id": "worker", "observed_at_epoch": 10**350}))
    _configure(monkeypatch, client)
    assert worker_presence.worker_presence_health()["status"] == "invalid"
