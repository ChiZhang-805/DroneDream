"""Phase 8 tests for the real_cli simulator adapter."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from app.simulator.base import (
    FAILURE_ADAPTER_UNAVAILABLE,
    FAILURE_SIMULATION,
    FAILURE_TIMEOUT,
    JobConfig,
    TrialContext,
)
from app.simulator.real_cli import RealCliSimulatorAdapter

_EXAMPLE_SIM = (
    Path(__file__).resolve().parents[2] / "scripts" / "simulators" / "example_real_simulator.py"
)


def _ctx(
    *,
    trial_id: str = "trial-1",
    job_id: str = "job-1",
    parameters: dict[str, float] | None = None,
    scenario: str = "nominal",
    scenario_config: dict[str, object] | None = None,
) -> TrialContext:
    return TrialContext(
        trial_id=trial_id,
        job_id=job_id,
        candidate_id="cand-1",
        seed=42,
        scenario_type=scenario,
        scenario_config=dict(scenario_config or {}),
        parameters=parameters or {"kp_xy": 1.0, "kd_xy": 0.2, "ki_xy": 0.05},
        job_config=JobConfig(
            track_type="circle",
            start_point_x=0.0,
            start_point_y=0.0,
            altitude_m=3.0,
            wind_north=0.0,
            wind_east=0.0,
            wind_south=0.0,
            wind_west=0.0,
            sensor_noise_level="medium",
            objective_profile="robust",
        ),
    )


def test_real_cli_fails_when_command_unset(monkeypatch):
    monkeypatch.delenv("REAL_SIMULATOR_COMMAND", raising=False)
    adapter = RealCliSimulatorAdapter()
    result = adapter.run_trial(_ctx())
    assert result.success is False
    assert result.failure is not None
    assert result.failure.code == FAILURE_ADAPTER_UNAVAILABLE


def test_real_cli_succeeds_against_example_simulator(monkeypatch, tmp_path):
    monkeypatch.setenv(
        "REAL_SIMULATOR_COMMAND",
        f"{sys.executable} {_EXAMPLE_SIM}",
    )
    monkeypatch.setenv("REAL_SIMULATOR_ARTIFACT_ROOT", str(tmp_path))
    monkeypatch.setenv("REAL_SIMULATOR_TIMEOUT_SECONDS", "60")

    adapter = RealCliSimulatorAdapter()
    result = adapter.run_trial(_ctx())

    assert result.success is True, result.failure
    assert result.metrics is not None
    assert result.metrics.rmse > 0
    assert result.metrics.raw_metric_json.get("simulator") == "example_real_simulator"
    run_dir = tmp_path / "jobs" / "job-1" / "trials" / "trial-1"
    assert (run_dir / "trial_input.json").exists()
    assert (run_dir / "trial_result.json").exists()
    payload = json.loads((run_dir / "trial_input.json").read_text())
    assert payload["parameters"]["kp_xy"] == 1.0
    assert payload["scenario_type"] == "nominal"


def test_real_cli_maps_timeout(monkeypatch, tmp_path):
    monkeypatch.setenv(
        "REAL_SIMULATOR_COMMAND",
        f"{sys.executable} {_EXAMPLE_SIM}",
    )
    monkeypatch.setenv("REAL_SIMULATOR_ARTIFACT_ROOT", str(tmp_path))
    monkeypatch.setenv("REAL_SIMULATOR_TIMEOUT_SECONDS", "1")

    adapter = RealCliSimulatorAdapter()
    result = adapter.run_trial(
        _ctx(
            scenario_config={"inject_failure": "sleep", "sleep_seconds": 5},
        )
    )
    assert result.success is False
    assert result.failure is not None
    assert result.failure.code == FAILURE_TIMEOUT


def test_real_cli_malformed_output_is_simulation_failed(monkeypatch, tmp_path):
    # A tiny script that writes a non-object into trial_result.json.
    fake = tmp_path / "fake_sim.py"
    fake.write_text(
        "import json, sys\n"
        "i = sys.argv[sys.argv.index('--input') + 1]\n"
        "o = sys.argv[sys.argv.index('--output') + 1]\n"
        "json.load(open(i))\n"
        "open(o, 'w').write('not json')\n"
    )
    monkeypatch.setenv("REAL_SIMULATOR_COMMAND", f"{sys.executable} {fake}")
    monkeypatch.setenv("REAL_SIMULATOR_ARTIFACT_ROOT", str(tmp_path))

    adapter = RealCliSimulatorAdapter()
    result = adapter.run_trial(_ctx())
    assert result.success is False
    assert result.failure is not None
    assert result.failure.code == FAILURE_SIMULATION


def test_real_cli_adapter_unavailable_when_command_missing_binary(monkeypatch, tmp_path):
    monkeypatch.setenv("REAL_SIMULATOR_COMMAND", "/path/does/not/exist/binary_x")
    monkeypatch.setenv("REAL_SIMULATOR_ARTIFACT_ROOT", str(tmp_path))
    adapter = RealCliSimulatorAdapter()
    result = adapter.run_trial(_ctx())
    assert result.success is False
    assert result.failure is not None
    assert result.failure.code == FAILURE_ADAPTER_UNAVAILABLE


def test_real_cli_parses_structured_failure(monkeypatch, tmp_path):
    monkeypatch.setenv(
        "REAL_SIMULATOR_COMMAND",
        f"{sys.executable} {_EXAMPLE_SIM}",
    )
    monkeypatch.setenv("REAL_SIMULATOR_ARTIFACT_ROOT", str(tmp_path))

    adapter = RealCliSimulatorAdapter()
    result = adapter.run_trial(
        _ctx(
            parameters={
                "kp_xy": 1.0,
                "kd_xy": 0.2,
                "ki_xy": 0.05,
                "inject_failure": "simulation_failed",
            },
        )
    )
    assert result.success is False
    assert result.failure is not None
    assert result.failure.code == FAILURE_SIMULATION
    assert "injected simulation_failed" in result.failure.reason


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-v"]))
