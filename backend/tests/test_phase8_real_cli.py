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
from app.simulator.real_cli import RealCliSimulatorAdapter, _trial_input_payload

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
    # job_config is the canonical grouped object.
    assert payload["job_config"]["track_type"] == "circle"
    assert payload["job_config"]["altitude_m"] == 3.0
    assert payload["job_config"]["start_point"] == {"x": 0.0, "y": 0.0}
    # Top-level aliases mirror the same values for wrapper authors who
    # prefer to read them without reaching into job_config.
    assert payload["track_type"] == payload["job_config"]["track_type"]
    assert payload["altitude_m"] == payload["job_config"]["altitude_m"]
    assert payload["start_point"] == payload["job_config"]["start_point"]
    assert payload["reference_track"] == payload["job_config"]["reference_track"]
    assert payload["wind"] == payload["job_config"]["wind"]
    assert payload["sensor_noise_level"] == payload["job_config"]["sensor_noise_level"]
    assert payload["objective_profile"] == payload["job_config"]["objective_profile"]
    # Phase 8 polish: the example simulator emits real per-trial artifact
    # files alongside trial_result.json, so the adapter must surface them in
    # TrialResult.artifacts. The trial_executor persists these with
    # owner_type="trial" so the UI can show real artifact metadata instead
    # of mock-only placeholders.
    assert (run_dir / "trajectory.json").exists()
    assert (run_dir / "telemetry.json").exists()
    assert (run_dir / "worker.log").exists()
    assert {a.artifact_type for a in result.artifacts} == {
        "trajectory_plot",
        "telemetry_json",
        "worker_log",
    }
    for a in result.artifacts:
        assert Path(a.storage_path).exists()
        assert a.file_size_bytes is None or a.file_size_bytes > 0


def test_trial_input_payload_includes_custom_reference_track() -> None:
    ctx = _ctx()
    ctx = TrialContext(
        trial_id=ctx.trial_id,
        job_id=ctx.job_id,
        candidate_id=ctx.candidate_id,
        seed=ctx.seed,
        scenario_type=ctx.scenario_type,
        scenario_config=ctx.scenario_config,
        parameters=ctx.parameters,
        job_config=JobConfig(
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
            reference_track=[
                {"x": 0.0, "y": 0.0, "z": 3.0},
                {"x": 5.0, "y": 0.0, "z": 3.0},
            ],
        ),
    )
    payload = _trial_input_payload(ctx, Path("/tmp/out.json"))
    assert payload["track_type"] == "custom"
    assert payload["job_config"]["reference_track"] == payload["reference_track"]
    assert len(payload["reference_track"]) == 2


def test_trial_input_payload_includes_advanced_scenario_config() -> None:
    ctx = _ctx(
        scenario_config={
            "scenario": "nominal",
            "advanced_scenario_config": {
                "wind_gusts": {
                    "enabled": True,
                    "magnitude_mps": 1.2,
                    "direction_deg": 90,
                    "period_s": 5,
                },
            },
        }
    )
    payload = _trial_input_payload(ctx, Path("/tmp/out.json"))
    assert payload["advanced_scenario_config"]["wind_gusts"]["enabled"] is True


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


def test_real_cli_parses_v1_artifacts_and_infers_mime(monkeypatch, tmp_path):
    fake = tmp_path / "fake_sim_v1.py"
    fake.write_text(
        """
import json, pathlib, sys
out = pathlib.Path(sys.argv[sys.argv.index('--output') + 1])
run_dir = out.parent
telemetry = run_dir / 'telemetry.json'
ref = run_dir / 'reference_track.json'
telemetry.write_text(json.dumps({
    'schema_version': 'dronedream.telemetry.v1',
    'samples': [{'t': 0, 'x': 0, 'y': 0, 'z': 3}],
}))
ref.write_text(json.dumps({
    'schema_version': 'dronedream.reference_track.v1',
    'reference_track': [{'x': 0, 'y': 0, 'z': 3}],
}))
payload = {
    'success': True,
    'metrics': {
        'rmse': 1.0, 'max_error': 1.0, 'overshoot_count': 0,
        'completion_time': 1.0, 'score': 1.0,
    },
    'artifacts': [
        {'artifact_type': 'telemetry_json', 'storage_path': str(telemetry)},
        {'artifact_type': 'reference_track_json', 'storage_path': str(ref)},
    ],
}
out.write_text(json.dumps(payload))
""".strip()
    )
    monkeypatch.setenv("REAL_SIMULATOR_COMMAND", f"{sys.executable} {fake}")
    monkeypatch.setenv("REAL_SIMULATOR_ARTIFACT_ROOT", str(tmp_path))
    result = RealCliSimulatorAdapter().run_trial(_ctx())
    assert result.success is True
    types = {a.artifact_type: a for a in result.artifacts}
    assert types["telemetry_json"].mime_type == "application/json"
    assert types["reference_track_json"].mime_type == "application/json"


def test_real_cli_malformed_telemetry_does_not_fail_success_trial(monkeypatch, tmp_path):
    fake = tmp_path / "fake_sim_bad_telemetry.py"
    fake.write_text(
        """
import json, pathlib, sys
out = pathlib.Path(sys.argv[sys.argv.index('--output') + 1])
run_dir = out.parent
telemetry = run_dir / 'telemetry.json'
telemetry.write_text(json.dumps({
    'schema_version': 'dronedream.telemetry.v1',
    'samples': [{'x': 0, 'y': 0, 'z': 3}],
}))
payload = {
    'success': True,
    'metrics': {
        'rmse': 1.0, 'max_error': 1.0, 'overshoot_count': 0,
        'completion_time': 1.0, 'score': 1.0,
    },
    'artifacts': [
        {
            'artifact_type': 'telemetry_json',
            'storage_path': str(telemetry),
            'mime_type': 'application/json',
        },
    ],
}
out.write_text(json.dumps(payload))
""".strip()
    )
    monkeypatch.setenv("REAL_SIMULATOR_COMMAND", f"{sys.executable} {fake}")
    monkeypatch.setenv("REAL_SIMULATOR_ARTIFACT_ROOT", str(tmp_path))
    result = RealCliSimulatorAdapter().run_trial(_ctx())
    assert result.success is True
    assert {a.artifact_type for a in result.artifacts} == {"telemetry_json"}


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-v"]))
