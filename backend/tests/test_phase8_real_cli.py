"""Phase 8 tests for the real_cli simulator adapter."""

from __future__ import annotations

import json
import logging
import sys
import threading
import time
from pathlib import Path

import pytest
from app.simulator.artifact_schema import (
    _MAX_REFERENCE_POINTS,
    _MAX_TELEMETRY_SAMPLES,
    validate_reference_track_payload,
    validate_telemetry_payload,
)
from app.simulator.base import (
    FAILURE_ADAPTER_UNAVAILABLE,
    FAILURE_CANCELLED,
    FAILURE_SIMULATION,
    FAILURE_TIMEOUT,
    JobConfig,
    TrialContext,
)
from app.simulator.real_cli import (
    _MAX_KNOWN_JSON_ARTIFACT_BYTES,
    _MAX_RESULT_ARTIFACTS,
    _MAX_RESULT_BYTES,
    RealCliSimulatorAdapter,
    _build_command,
    _effective_timeout_seconds,
    _load_result_payload,
    _parse_artifacts,
    _parse_metrics,
    _read_log_tail,
    _trial_input_payload,
)

_EXAMPLE_SIM = (
    Path(__file__).resolve().parents[2] / "scripts" / "simulators" / "example_real_simulator.py"
)


def _valid_result(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "success": True,
        "metrics": {
            "rmse": 1.0,
            "max_error": 2.0,
            "overshoot_count": 0,
            "completion_time": 3.0,
            "score": 4.0,
        },
    }
    payload.update(overrides)
    return payload


def _write_result_simulator(script: Path, result: dict[str, object], *, exit_code: int = 0) -> None:
    encoded = json.dumps(result)
    script.write_text(
        "import json, pathlib, sys\n"
        "out = pathlib.Path(sys.argv[sys.argv.index('--output') + 1])\n"
        f"out.write_text({encoded!r}, encoding='utf-8')\n"
        f"raise SystemExit({exit_code})\n",
        encoding="utf-8",
    )


def _ctx(
    *,
    trial_id: str = "trial-1",
    job_id: str = "job-1",
    parameters: dict[str, float] | None = None,
    scenario: str = "nominal",
    scenario_config: dict[str, object] | None = None,
    vehicle_profile: dict[str, object] | None = None,
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
            vehicle_profile=vehicle_profile,
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


def test_real_cli_child_environment_excludes_control_plane_credentials(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    simulator = tmp_path / "inspect_environment.py"
    simulator.write_text(
        """
import json, os, pathlib, sys
out = pathlib.Path(sys.argv[sys.argv.index('--output') + 1])
names = [
    'APP_SECRET_KEY', 'DATABASE_URL', 'S3_SECRET_ACCESS_KEY',
    'PX4_GAZEBO_DRY_RUN', 'DRONEDREAM_PX4_EXECUTABLE', 'PATH',
]
payload = {
    'success': True,
    'metrics': {
        'rmse': 1.0, 'max_error': 1.0, 'overshoot_count': 0,
        'completion_time': 1.0, 'score': 1.0,
        'raw_metric_json': {'child_environment': {name: os.environ.get(name) for name in names}},
    },
}
out.write_text(json.dumps(payload), encoding='utf-8')
""".strip(),
        encoding="utf-8",
    )
    monkeypatch.setenv("APP_SECRET_KEY", "must-not-leak")
    monkeypatch.setenv("DATABASE_URL", "postgresql://secret")
    monkeypatch.setenv("S3_SECRET_ACCESS_KEY", "must-not-leak")
    monkeypatch.setenv("PX4_GAZEBO_DRY_RUN", "true")
    monkeypatch.setenv("DRONEDREAM_PX4_EXECUTABLE", str(tmp_path / "px4"))
    monkeypatch.setenv("REAL_SIMULATOR_COMMAND", f'"{sys.executable}" "{simulator}"')
    monkeypatch.setenv("REAL_SIMULATOR_ARTIFACT_ROOT", str(tmp_path / "runs"))

    result = RealCliSimulatorAdapter().run_trial(_ctx())

    assert result.success is True
    assert result.metrics is not None
    child_environment = result.metrics.raw_metric_json["child_environment"]
    assert child_environment["APP_SECRET_KEY"] is None
    assert child_environment["DATABASE_URL"] is None
    assert child_environment["S3_SECRET_ACCESS_KEY"] is None
    assert child_environment["PX4_GAZEBO_DRY_RUN"] == "true"
    assert child_environment["DRONEDREAM_PX4_EXECUTABLE"] == str(tmp_path / "px4")
    assert child_environment["PATH"]


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
    effect_request = payload["scenario_effect_request"]
    assert effect_request["schema_version"] == "dronedream.scenario_effect_request.v1"
    assert effect_request["execution_identity"] == payload["execution_identity"]
    assert [item["effect_id"] for item in effect_request["effects"]] == [
        "wind_gusts"
    ]
    assert effect_request["effects"][0]["requested_value"] == {
        "enabled": True,
        "magnitude_mps": 1.2,
        "direction_deg": 90.0,
        "period_s": 5.0,
    }


def test_trial_input_payload_carries_vehicle_profile_and_real_px4_parameters() -> None:
    base = _ctx(
        parameters={
            "MPC_XY_P": 1.0,
            "MC_ROLL_P": 4.5,
            "IMU_GYRO_CUTOFF": 40.0,
            "kp_xy": 1.0,
        }
    )
    ctx = TrialContext(
        trial_id=base.trial_id,
        job_id=base.job_id,
        candidate_id=base.candidate_id,
        seed=base.seed,
        scenario_type=base.scenario_type,
        scenario_config=base.scenario_config,
        parameters=base.parameters,
        job_config=JobConfig(
            track_type="circle",
            start_point_x=0,
            start_point_y=0,
            altitude_m=3,
            wind_north=0,
            wind_east=0,
            wind_south=0,
            wind_west=0,
            sensor_noise_level="medium",
            objective_profile="robust",
            vehicle_profile={
                "px4_version": "v1.16",
                "airframe": "x500",
                "simulator_model": "gz_x500",
                "world": "windy",
            },
        ),
    )
    payload = _trial_input_payload(ctx, Path("/tmp/out.json"))
    assert payload["px4_version"] == "v1.16"
    assert payload["vehicle_profile"]["world"] == "windy"
    assert payload["px4_parameters"] == {
        "MPC_XY_P": 1.0,
        "MC_ROLL_P": 4.5,
        "IMU_GYRO_CUTOFF": 40.0,
    }
    assert payload["job_config"]["px4_parameters"] == payload["px4_parameters"]


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


def test_real_cli_drops_malformed_telemetry_without_failing_metrics(monkeypatch, tmp_path, caplog):
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
    with caplog.at_level(logging.WARNING, logger="drone_dream.simulator.real_cli"):
        result = RealCliSimulatorAdapter().run_trial(_ctx())
    assert result.success is True
    assert result.artifacts == []
    assert "dropped invalid artifact" in caplog.text


def test_real_cli_drops_oversized_known_json_artifact(monkeypatch, tmp_path, caplog):
    fake = tmp_path / "fake_sim_large_telemetry.py"
    fake.write_text(
        f"""
import json, pathlib, sys
out = pathlib.Path(sys.argv[sys.argv.index('--output') + 1])
telemetry = out.parent / 'telemetry.json'
with telemetry.open('wb') as stream:
    stream.truncate({_MAX_KNOWN_JSON_ARTIFACT_BYTES + 1})
out.write_text(json.dumps({{
    'success': True,
    'metrics': {{
        'rmse': 1.0, 'max_error': 1.0, 'overshoot_count': 0,
        'completion_time': 1.0, 'score': 1.0,
    }},
    'artifacts': [{{
        'artifact_type': 'telemetry_json',
        'storage_path': str(telemetry),
        'mime_type': 'application/json',
    }}],
}}))
""".strip(),
        encoding="utf-8",
    )
    monkeypatch.setenv("REAL_SIMULATOR_COMMAND", f'"{sys.executable}" "{fake}"')
    monkeypatch.setenv("REAL_SIMULATOR_ARTIFACT_ROOT", str(tmp_path))

    with caplog.at_level(logging.WARNING, logger="drone_dream.simulator.real_cli"):
        result = RealCliSimulatorAdapter().run_trial(_ctx())

    assert result.success is True
    assert result.artifacts == []
    assert "exceeds" in caplog.text
    assert "validation limit" in caplog.text


def test_build_command_substitutes_paths_after_tokenization() -> None:
    argv = _build_command(
        f'"{sys.executable}" --literal={{"key":1}} --input={{input}}',
        Path("C:/workspace with spaces/input.json"),
        Path("C:/workspace with spaces/output.json"),
    )
    assert argv[1].startswith("--literal={")
    assert argv[2] == f"--input={Path('C:/workspace with spaces/input.json')}"
    assert argv[-2:] == ["--output", str(Path("C:/workspace with spaces/output.json"))]


def test_real_cli_timeout_scales_for_slow_simulation_with_bounded_multiplier() -> None:
    assert _effective_timeout_seconds(300.0, 1.0) == 300.0
    assert _effective_timeout_seconds(300.0, 2.0) == 300.0
    assert _effective_timeout_seconds(300.0, 0.5) == 600.0
    assert _effective_timeout_seconds(300.0, 0.1) == 3_000.0
    assert _effective_timeout_seconds(50_000.0, 0.1) == 86_400.0
    with pytest.raises(ValueError, match=r"\[0\.1, 100\]"):
        _effective_timeout_seconds(300.0, 0.01)


def test_real_cli_adapter_applies_slow_simulation_timeout(monkeypatch, tmp_path) -> None:
    simulator = tmp_path / "slow_but_valid.py"
    simulator.write_text(
        """
import json, pathlib, sys, time
time.sleep(1.2)
out = pathlib.Path(sys.argv[sys.argv.index('--output') + 1])
out.write_text(json.dumps({
    'success': True,
    'metrics': {
        'rmse': 1.0, 'max_error': 1.0, 'overshoot_count': 0,
        'completion_time': 1.0, 'score': 1.0,
    },
}), encoding='utf-8')
""".strip(),
        encoding="utf-8",
    )
    monkeypatch.setenv("REAL_SIMULATOR_COMMAND", f'"{sys.executable}" "{simulator}"')
    monkeypatch.setenv("REAL_SIMULATOR_ARTIFACT_ROOT", str(tmp_path / "runs"))
    monkeypatch.setenv("REAL_SIMULATOR_TIMEOUT_SECONDS", "1")

    result = RealCliSimulatorAdapter().run_trial(
        _ctx(vehicle_profile={"simulation_speed_factor": 0.25})
    )

    assert result.success is True, result.failure


def test_real_cli_deletes_stale_output_before_launch(monkeypatch, tmp_path) -> None:
    stale_dir = tmp_path / "jobs" / "job-1" / "trials" / "trial-1"
    stale_dir.mkdir(parents=True)
    stale_output = stale_dir / "trial_result.json"
    stale_output.write_text(json.dumps(_valid_result()), encoding="utf-8")
    exits_without_output = tmp_path / "exits_without_output.py"
    exits_without_output.write_text("raise SystemExit(9)\n", encoding="utf-8")
    monkeypatch.setenv("REAL_SIMULATOR_COMMAND", f'"{sys.executable}" "{exits_without_output}"')
    monkeypatch.setenv("REAL_SIMULATOR_ARTIFACT_ROOT", str(tmp_path))

    result = RealCliSimulatorAdapter().run_trial(_ctx())

    assert result.success is False
    assert result.failure is not None
    assert "without producing trial_result.json" in result.failure.reason
    assert not stale_output.exists()


def test_real_cli_uses_attempt_specific_run_directory(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("REAL_SIMULATOR_COMMAND", f'"{sys.executable}" "{_EXAMPLE_SIM}"')
    monkeypatch.setenv("REAL_SIMULATOR_ARTIFACT_ROOT", str(tmp_path))
    base = _ctx()
    retry = TrialContext(
        trial_id=base.trial_id,
        job_id=base.job_id,
        candidate_id=base.candidate_id,
        seed=base.seed,
        scenario_type=base.scenario_type,
        scenario_config=base.scenario_config,
        parameters=base.parameters,
        job_config=base.job_config,
        attempt_count=2,
    )

    result = RealCliSimulatorAdapter().run_trial(retry)

    assert result.success is True
    attempt_dir = tmp_path / "jobs" / "job-1" / "trials" / "trial-1" / "attempts" / "0002"
    payload = json.loads((attempt_dir / "trial_input.json").read_text(encoding="utf-8"))
    assert payload["attempt_count"] == 2
    assert payload["execution_identity"]["attempt_count"] == 2


def test_real_cli_rejects_success_from_nonzero_process(monkeypatch, tmp_path) -> None:
    simulator = tmp_path / "nonzero_success.py"
    _write_result_simulator(simulator, _valid_result(), exit_code=7)
    monkeypatch.setenv("REAL_SIMULATOR_COMMAND", f'"{sys.executable}" "{simulator}"')
    monkeypatch.setenv("REAL_SIMULATOR_ARTIFACT_ROOT", str(tmp_path))

    result = RealCliSimulatorAdapter().run_trial(_ctx())

    assert result.success is False
    assert result.failure is not None
    assert "reported success" in result.failure.reason
    assert "exit=7" in result.failure.reason


def test_real_cli_rejects_string_success_flag(monkeypatch, tmp_path) -> None:
    simulator = tmp_path / "string_success.py"
    _write_result_simulator(simulator, _valid_result(success="false"))
    monkeypatch.setenv("REAL_SIMULATOR_COMMAND", f'"{sys.executable}" "{simulator}"')
    monkeypatch.setenv("REAL_SIMULATOR_ARTIFACT_ROOT", str(tmp_path))

    result = RealCliSimulatorAdapter().run_trial(_ctx())

    assert result.success is False
    assert result.failure is not None
    assert "'success' must be a boolean" in result.failure.reason


def test_real_cli_rejects_result_identity_mismatch(monkeypatch, tmp_path) -> None:
    simulator = tmp_path / "wrong_identity.py"
    payload = _valid_result(
        execution_identity={
            "trial_id": "another-trial",
            "job_id": "job-1",
            "candidate_id": "cand-1",
            "seed": 42,
            "attempt_count": 1,
        }
    )
    _write_result_simulator(simulator, payload)
    monkeypatch.setenv("REAL_SIMULATOR_COMMAND", f'"{sys.executable}" "{simulator}"')
    monkeypatch.setenv("REAL_SIMULATOR_ARTIFACT_ROOT", str(tmp_path))

    result = RealCliSimulatorAdapter().run_trial(_ctx())

    assert result.success is False
    assert result.failure is not None
    assert "identity mismatch for trial_id" in result.failure.reason


def test_real_cli_requires_identity_for_v2_result(monkeypatch, tmp_path) -> None:
    simulator = tmp_path / "v2_without_identity.py"
    _write_result_simulator(
        simulator,
        _valid_result(schema_version="dronedream.trial_result.v2"),
    )
    monkeypatch.setenv("REAL_SIMULATOR_COMMAND", f'"{sys.executable}" "{simulator}"')
    monkeypatch.setenv("REAL_SIMULATOR_ARTIFACT_ROOT", str(tmp_path))

    result = RealCliSimulatorAdapter().run_trial(_ctx())

    assert result.success is False
    assert result.failure is not None
    assert "v2 requires execution_identity" in result.failure.reason


def test_log_excerpt_reads_only_bounded_tail(tmp_path) -> None:
    log_path = tmp_path / "large.log"
    log_path.write_bytes(b"prefix-secret\n" + b"x" * 2_000_000 + b"\nTAIL-MARKER")

    excerpt = _read_log_tail(log_path, limit=128)

    assert len(excerpt) < 256
    assert "TAIL-MARKER" in excerpt
    assert "prefix-secret" not in excerpt


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("rmse", True),
        ("max_error", float("inf")),
        ("score", float("nan")),
        ("overshoot_count", 1.5),
        ("crash_flag", "false"),
    ],
)
def test_parse_metrics_rejects_ambiguous_or_nonfinite_values(field: str, value: object) -> None:
    raw = _valid_result()
    metrics = dict(raw["metrics"])  # type: ignore[arg-type]
    metrics[field] = value
    with pytest.raises(ValueError):
        _parse_metrics({"metrics": metrics})


def test_parse_metrics_rejects_nonfinite_number_nested_in_raw_metric_json(
    tmp_path: Path,
) -> None:
    result_path = tmp_path / "trial_result.json"
    result_path.write_text(
        """{
          "metrics": {
            "rmse": 1, "max_error": 1, "overshoot_count": 0,
            "completion_time": 1, "score": 1,
            "raw_metric_json": {"nested": {"value": 1e999}}
          }
        }""",
        encoding="utf-8",
    )
    decoded = _load_result_payload(result_path)
    assert isinstance(decoded, dict)

    with pytest.raises(ValueError, match="raw_metric_json numbers must be finite"):
        _parse_metrics(decoded)


def test_parse_metrics_bounds_raw_metric_json_depth_and_node_count() -> None:
    raw = _valid_result()
    metrics = dict(raw["metrics"])  # type: ignore[arg-type]
    nested: dict[str, object] = {}
    cursor = nested
    for _ in range(25):
        child: dict[str, object] = {}
        cursor["next"] = child
        cursor = child
    metrics["raw_metric_json"] = nested
    with pytest.raises(ValueError, match="nesting contract limit"):
        _parse_metrics({"metrics": metrics})

    metrics["raw_metric_json"] = {"values": [0] * 10_000}
    with pytest.raises(ValueError, match="node contract limit"):
        _parse_metrics({"metrics": metrics})


def test_result_loader_reports_decoder_recursion_as_contract_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    result_path = tmp_path / "trial_result.json"
    result_path.write_text("{}", encoding="utf-8")

    def fail_deep_json(*_args: object, **_kwargs: object) -> object:
        raise RecursionError("decoder depth")

    monkeypatch.setattr(json, "loads", fail_deep_json)

    with pytest.raises(ValueError, match="nesting is too deep"):
        _load_result_payload(result_path)


def test_result_loader_bounds_actual_bytes_read(tmp_path: Path) -> None:
    result_path = tmp_path / "trial_result.json"
    result_path.write_bytes(b"{" + b" " * _MAX_RESULT_BYTES + b"}")
    with pytest.raises(ValueError, match="byte contract limit"):
        _load_result_payload(result_path)


def test_result_contract_bounds_artifact_count_and_metadata_lengths() -> None:
    artifact = {
        "artifact_type": "worker_log",
        "storage_path": "worker.log",
    }
    with pytest.raises(ValueError, match="cannot contain more"):
        _parse_artifacts({"artifacts": [artifact] * (_MAX_RESULT_ARTIFACTS + 1)})
    with pytest.raises(ValueError, match="artifact requires"):
        _parse_artifacts(
            {
                "artifacts": [
                    {
                        "artifact_type": "x" * 33,
                        "storage_path": "worker.log",
                    }
                ]
            }
        )
    oversized_file = dict(artifact, file_size_bytes=2**63)
    with pytest.raises(ValueError, match="signed 64-bit"):
        _parse_artifacts({"artifacts": [oversized_file]})
    with pytest.raises(ValueError, match="must be an array"):
        _parse_artifacts({"artifacts": 0})
    with pytest.raises(ValueError, match="display_name must be a string"):
        _parse_artifacts({"artifacts": [dict(artifact, display_name=7)]})
    with pytest.raises(ValueError, match="mime_type must be a string"):
        _parse_artifacts({"artifacts": [dict(artifact, mime_type={})]})


def test_known_artifact_schemas_bound_array_sizes_and_error_counts() -> None:
    telemetry_errors = validate_telemetry_payload(
        {
            "schema_version": "dronedream.telemetry.v1",
            "samples": [{}] * (_MAX_TELEMETRY_SAMPLES + 1),
        }
    )
    assert telemetry_errors == [
        f"telemetry samples[] cannot exceed {_MAX_TELEMETRY_SAMPLES} items"
    ]
    assert len(
        validate_telemetry_payload(
            {
                "schema_version": "dronedream.telemetry.v1",
                "samples": [None] * 1_000,
            }
        )
    ) <= 101
    assert validate_reference_track_payload(
        {
            "schema_version": "dronedream.reference_track.v1",
            "reference_track": [],
        }
    ) == ["reference_track[] must not be empty"]
    reference_errors = validate_reference_track_payload(
        {
            "schema_version": "dronedream.reference_track.v1",
            "reference_track": [{}] * (_MAX_REFERENCE_POINTS + 1),
        }
    )
    assert reference_errors == [
        f"reference_track[] cannot exceed {_MAX_REFERENCE_POINTS} items"
    ]


@pytest.mark.parametrize("timeout", ["0", "-1", "nan", "invalid", "86401"])
def test_real_cli_rejects_nonpositive_or_invalid_timeout(
    monkeypatch, tmp_path, timeout: str
) -> None:
    monkeypatch.setenv("REAL_SIMULATOR_COMMAND", f'"{sys.executable}" "{_EXAMPLE_SIM}"')
    monkeypatch.setenv("REAL_SIMULATOR_ARTIFACT_ROOT", str(tmp_path))
    monkeypatch.setenv("REAL_SIMULATOR_TIMEOUT_SECONDS", timeout)
    result = RealCliSimulatorAdapter().run_trial(_ctx())
    assert result.success is False
    assert result.failure is not None
    assert result.failure.code == FAILURE_ADAPTER_UNAVAILABLE


def _write_process_tree_fixture(tmp_path: Path) -> tuple[Path, Path, Path]:
    sentinel = tmp_path / "child-survived.txt"
    child = tmp_path / "child.py"
    child.write_text(
        "import pathlib, sys, time\n"
        "time.sleep(0.8)\n"
        "pathlib.Path(sys.argv[1]).write_text('survived', encoding='utf-8')\n",
        encoding="utf-8",
    )
    parent = tmp_path / "parent.py"
    parent.write_text(
        "import subprocess, sys, time\n"
        "subprocess.Popen([sys.executable, sys.argv[1], sys.argv[2]])\n"
        "time.sleep(30)\n",
        encoding="utf-8",
    )
    return parent, child, sentinel


def test_real_cli_timeout_terminates_descendant_processes(monkeypatch, tmp_path) -> None:
    parent, child, sentinel = _write_process_tree_fixture(tmp_path)
    monkeypatch.setenv(
        "REAL_SIMULATOR_COMMAND",
        f'"{sys.executable}" "{parent}" "{child}" "{sentinel}"',
    )
    monkeypatch.setenv("REAL_SIMULATOR_ARTIFACT_ROOT", str(tmp_path / "runs"))
    monkeypatch.setenv("REAL_SIMULATOR_TIMEOUT_SECONDS", "0.2")

    result = RealCliSimulatorAdapter().run_trial(_ctx())
    time.sleep(1.0)

    assert result.success is False
    assert result.failure is not None
    assert result.failure.code == FAILURE_TIMEOUT
    assert not sentinel.exists(), "timed-out simulator descendant was left running"


def test_real_cli_cancellation_terminates_descendant_processes(monkeypatch, tmp_path) -> None:
    parent, child, sentinel = _write_process_tree_fixture(tmp_path)
    monkeypatch.setenv(
        "REAL_SIMULATOR_COMMAND",
        f'"{sys.executable}" "{parent}" "{child}" "{sentinel}"',
    )
    monkeypatch.setenv("REAL_SIMULATOR_ARTIFACT_ROOT", str(tmp_path / "runs"))
    monkeypatch.setenv("REAL_SIMULATOR_TIMEOUT_SECONDS", "10")
    event = threading.Event()
    timer = threading.Timer(0.2, event.set)
    timer.start()
    base = _ctx()
    ctx = TrialContext(
        trial_id=base.trial_id,
        job_id=base.job_id,
        candidate_id=base.candidate_id,
        seed=base.seed,
        scenario_type=base.scenario_type,
        scenario_config=base.scenario_config,
        parameters=base.parameters,
        job_config=base.job_config,
        cancellation_event=event,
    )
    try:
        result = RealCliSimulatorAdapter().run_trial(ctx)
    finally:
        timer.cancel()
    time.sleep(1.0)

    assert result.success is False
    assert result.failure is not None
    assert result.failure.code == FAILURE_CANCELLED
    assert not sentinel.exists(), "cancelled simulator descendant was left running"


def test_keep_run_dirs_false_defers_cleanup_until_finalize(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("REAL_SIMULATOR_COMMAND", f'"{sys.executable}" "{_EXAMPLE_SIM}"')
    monkeypatch.setenv("REAL_SIMULATOR_ARTIFACT_ROOT", str(tmp_path))
    monkeypatch.setenv("REAL_SIMULATOR_KEEP_RUN_DIRS", "false")
    adapter = RealCliSimulatorAdapter()
    ctx = _ctx()

    result = adapter.run_trial(ctx)
    run_dir = tmp_path / "jobs" / "job-1" / "trials" / "trial-1"

    assert result.success is True
    assert run_dir.is_dir()
    assert all(Path(artifact.storage_path).is_file() for artifact in result.artifacts)
    adapter.finalize_trial(ctx, result)
    assert not run_dir.exists()


def test_real_cli_artifact_schema_doc_exists() -> None:
    doc = Path(__file__).resolve().parents[2] / "docs" / "REAL_CLI_ARTIFACT_SCHEMA.md"
    assert doc.exists()


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-v"]))
