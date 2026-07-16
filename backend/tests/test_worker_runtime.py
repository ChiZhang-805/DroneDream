from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from app import models
from app.orchestration import events, runner, trial_executor, worker_presence


@pytest.mark.parametrize("value", (-1.0, float("nan"), True))
def test_worker_loop_rejects_invalid_poll_intervals(value: object) -> None:
    with pytest.raises(ValueError, match="poll_interval_seconds"):
        runner.run_forever(poll_interval_seconds=value)  # type: ignore[arg-type]


@pytest.mark.parametrize("value", (-1, True))
def test_worker_loop_rejects_invalid_iteration_limits(value: object) -> None:
    with pytest.raises(ValueError, match="max_iterations"):
        runner.run_forever(max_iterations=value)  # type: ignore[arg-type]


def test_zero_iteration_worker_does_not_start_presence_thread(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        runner.WorkerPresenceHeartbeat,
        "start",
        lambda _self: pytest.fail("presence thread should not start"),
    )
    assert runner.run_forever(max_iterations=0) == 0


@pytest.mark.parametrize(
    "observed_epoch",
    (float("nan"), 9_999_999_999.0, True),
)
def test_worker_presence_rejects_invalid_or_future_timestamps(
    monkeypatch: pytest.MonkeyPatch,
    observed_epoch: float,
) -> None:
    settings = SimpleNamespace(
        redis_url="redis://example.invalid/0",
        worker_presence_key="workers:test",
        worker_presence_ttl_seconds=60,
        require_worker_heartbeat=True,
    )
    client = SimpleNamespace(
        ping=lambda: True,
        get=lambda _key: json.dumps(
            {"worker_id": "worker", "observed_at_epoch": observed_epoch}
        ),
    )
    monkeypatch.setattr(worker_presence, "_settings", lambda: settings)
    monkeypatch.setattr(worker_presence, "_client", lambda: client)

    health = worker_presence.worker_presence_health()

    assert health["ok"] is False
    assert health["status"] == "invalid"


@pytest.mark.parametrize("worker_id", ("", "   ", "bad\nworker", "x" * 129))
def test_worker_presence_rejects_invalid_worker_ids(worker_id: str) -> None:
    with pytest.raises(ValueError, match="worker_id"):
        worker_presence.WorkerPresenceHeartbeat(worker_id)


def test_event_writer_rejects_nonfinite_json_payload() -> None:
    db = SimpleNamespace(add=lambda _row: None)
    with pytest.raises(ValueError, match="finite JSON"):
        events.record_event(  # type: ignore[arg-type]
            db,
            "job_test",
            "test_event",
            {"metric": float("nan")},
        )


def test_trial_executor_rejects_invalid_worker_id_before_database_access() -> None:
    with pytest.raises(ValueError, match="worker_id"):
        trial_executor.claim_and_run_one_pending_trial(  # type: ignore[arg-type]
            SimpleNamespace(),
            "\n",
        )


def test_trial_executor_rejects_nonfinite_reference_track() -> None:
    job = models.Job(
        track_type="custom",
        start_point_x=0.0,
        start_point_y=0.0,
        altitude_m=3.0,
        wind_north=0.0,
        wind_east=0.0,
        wind_south=0.0,
        wind_west=0.0,
        sensor_noise_level="medium",
        objective_profile="robust",
        reference_track_json=[{"x": float("nan"), "y": 0.0, "z": 3.0}],
    )

    with pytest.raises(ValueError, match=r"track\[0\]\.x must be finite"):
        trial_executor._job_config_from(job)  # noqa: SLF001
