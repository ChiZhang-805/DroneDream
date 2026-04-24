from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from app.simulator.base import FAILURE_ADAPTER_UNAVAILABLE, FAILURE_TIMEOUT, JobConfig, TrialContext
from app.simulator.real_cli import RealCliSimulatorAdapter

RUNNER = Path(__file__).resolve().parents[2] / "scripts" / "simulators" / "px4_gazebo_runner.py"


def _trial_input(tmp_path: Path) -> Path:
    tmp_path.mkdir(parents=True, exist_ok=True)
    payload = {
        "trial_id": "trial-1",
        "job_id": "job-1",
        "candidate_id": "cand-1",
        "seed": 42,
        "scenario_type": "nominal",
        "scenario_config": {},
        "job_config": {
            "track_type": "circle",
            "start_point": {"x": 0.0, "y": 0.0},
            "altitude_m": 3.0,
            "wind": {"north": 0.0, "east": 0.0, "south": 0.0, "west": 0.0},
            "sensor_noise_level": "medium",
            "objective_profile": "robust",
        },
        "parameters": {
            "kp_xy": 1.0,
            "kd_xy": 0.2,
            "ki_xy": 0.05,
            "vel_limit": 5.0,
            "accel_limit": 4.0,
            "disturbance_rejection": 0.5,
        },
        "output_path": str(tmp_path / "trial_result.json"),
    }
    p = tmp_path / "trial_input.json"
    p.write_text(json.dumps(payload), encoding="utf-8")
    return p


def _run_runner(
    tmp_path: Path, *, env_overrides: dict[str, str]
) -> tuple[subprocess.CompletedProcess[str], dict[str, object]]:
    input_path = _trial_input(tmp_path)
    output_path = tmp_path / "trial_result.json"
    env = os.environ.copy()
    env.update(env_overrides)
    proc = subprocess.run(
        [sys.executable, str(RUNNER), "--input", str(input_path), "--output", str(output_path)],
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )
    assert output_path.exists(), proc.stderr
    payload = json.loads(output_path.read_text(encoding="utf-8"))
    return proc, payload


def test_px4_runner_requires_cli_args():
    proc = subprocess.run(
        [sys.executable, str(RUNNER)],
        text=True,
        capture_output=True,
        check=False,
    )
    assert proc.returncode != 0
    assert "--input" in proc.stderr


def test_px4_runner_returns_adapter_unavailable_when_command_missing(tmp_path: Path):
    proc, result = _run_runner(
        tmp_path,
        env_overrides={
            "PX4_GAZEBO_DRY_RUN": "false",
            "PX4_GAZEBO_LAUNCH_COMMAND": "",
        },
    )
    assert proc.returncode == 0
    assert result["success"] is False
    assert result["failure"]["code"] == FAILURE_ADAPTER_UNAVAILABLE


def test_px4_runner_dry_run_is_deterministic(tmp_path: Path):
    proc1, result1 = _run_runner(tmp_path / "r1", env_overrides={"PX4_GAZEBO_DRY_RUN": "true"})
    proc2, result2 = _run_runner(tmp_path / "r2", env_overrides={"PX4_GAZEBO_DRY_RUN": "true"})
    assert proc1.returncode == 0
    assert proc2.returncode == 0
    assert result1["success"] is True
    assert result2["success"] is True
    assert result1["metrics"] == result2["metrics"]


def test_px4_runner_timeout_maps_to_timeout(tmp_path: Path):
    sleeper = tmp_path / "sleeper.py"
    sleeper.write_text(
        "import time\n"
        "time.sleep(5)\n",
        encoding="utf-8",
    )
    command = f"{sys.executable} {sleeper} --input {{trial_input}} --telemetry {{telemetry_json}}"
    proc, result = _run_runner(
        tmp_path,
        env_overrides={
            "PX4_GAZEBO_DRY_RUN": "false",
            "PX4_GAZEBO_TIMEOUT_SECONDS": "1",
            "PX4_GAZEBO_LAUNCH_COMMAND": command,
        },
    )
    assert proc.returncode == 0
    assert result["success"] is False
    assert result["failure"]["code"] == FAILURE_TIMEOUT


def test_px4_runner_malformed_telemetry_maps_to_simulation_failed(tmp_path: Path):
    launcher = tmp_path / "launcher.py"
    launcher.write_text(
        "import pathlib, sys\n"
        "telemetry = pathlib.Path(sys.argv[sys.argv.index('--telemetry') + 1])\n"
        "telemetry.write_text('{bad json', encoding='utf-8')\n",
        encoding="utf-8",
    )
    command = f"{sys.executable} {launcher} --telemetry {{telemetry_json}}"
    proc, result = _run_runner(
        tmp_path,
        env_overrides={"PX4_GAZEBO_DRY_RUN": "false", "PX4_GAZEBO_LAUNCH_COMMAND": command},
    )
    assert proc.returncode == 0
    assert result["success"] is False
    assert result["failure"]["code"] == "SIMULATION_FAILED"


def test_px4_runner_writes_expected_artifacts_in_dry_run(tmp_path: Path):
    proc, result = _run_runner(tmp_path, env_overrides={"PX4_GAZEBO_DRY_RUN": "true"})
    assert proc.returncode == 0
    assert result["success"] is True
    for name in (
        "controller_params.json",
        "reference_track.json",
        "telemetry.json",
        "trajectory.json",
        "stdout.log",
        "stderr.log",
        "runner.log",
        "trial_result.json",
    ):
        assert (tmp_path / name).exists(), name


def test_px4_runner_template_substitutes_env_tokens(tmp_path: Path):
    launcher = tmp_path / "launcher.py"
    args_dump = tmp_path / "argv.json"
    launcher.write_text(
        "import json, pathlib, sys\n"
        "pathlib.Path(sys.argv[sys.argv.index('--telemetry') + 1]).write_text("
        "'{\"samples\": [{\"t\": 0.0, \"x\": 0.0, \"y\": 0.0, \"z\": 3.0}]}'"
        ", encoding='utf-8')\n"
        f"pathlib.Path({str(args_dump)!r}).write_text(json.dumps(sys.argv), encoding='utf-8')\n",
        encoding="utf-8",
    )
    command = (
        f"{sys.executable} {launcher} "
        "--vehicle {vehicle} --world {world} --headless {headless} --extra {extra_args} "
        "--params {params_json} --track {track_json} --telemetry {telemetry_json}"
    )
    proc, result = _run_runner(
        tmp_path,
        env_overrides={
            "PX4_GAZEBO_DRY_RUN": "false",
            "PX4_GAZEBO_LAUNCH_COMMAND": command,
            "PX4_GAZEBO_VEHICLE": "x500_test",
            "PX4_GAZEBO_WORLD": "warehouse",
            "PX4_GAZEBO_HEADLESS": "false",
            "PX4_GAZEBO_EXTRA_ARGS": "--speed 2 --foo bar",
        },
    )
    assert proc.returncode == 0
    assert result["success"] is True
    argv = json.loads(args_dump.read_text(encoding="utf-8"))
    assert "--vehicle" in argv and "x500_test" in argv
    assert "--world" in argv and "warehouse" in argv
    assert "--headless" in argv and "false" in argv
    assert "--extra" in argv
    extra_idx = argv.index("--extra")
    assert argv[extra_idx + 1 : extra_idx + 5] == ["--speed", "2", "--foo", "bar"]


def test_px4_runner_trajectory_artifact_type_is_json(tmp_path: Path):
    proc, result = _run_runner(tmp_path, env_overrides={"PX4_GAZEBO_DRY_RUN": "true"})
    assert proc.returncode == 0
    assert result["success"] is True
    trajectory = next(
        a for a in result["artifacts"] if Path(a["storage_path"]).name == "trajectory.json"
    )
    assert trajectory["artifact_type"] == "trajectory_json"
    assert trajectory["display_name"] == "Trajectory Samples"
    assert trajectory["mime_type"] == "application/json"


def _ctx() -> TrialContext:
    return TrialContext(
        trial_id="trial-1",
        job_id="job-1",
        candidate_id="cand-1",
        seed=42,
        scenario_type="nominal",
        scenario_config={},
        parameters={
            "kp_xy": 1.0,
            "kd_xy": 0.2,
            "ki_xy": 0.05,
            "vel_limit": 5.0,
            "accel_limit": 4.0,
            "disturbance_rejection": 0.5,
        },
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


def test_real_cli_integration_with_px4_runner_dry_run(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    monkeypatch.setenv("REAL_SIMULATOR_COMMAND", f"{sys.executable} {RUNNER}")
    monkeypatch.setenv("REAL_SIMULATOR_ARTIFACT_ROOT", str(tmp_path))
    monkeypatch.setenv("PX4_GAZEBO_DRY_RUN", "true")
    adapter = RealCliSimulatorAdapter()

    result = adapter.run_trial(_ctx())

    assert result.success is True, result.failure
    assert result.metrics is not None
    assert result.metrics.raw_metric_json.get("mode") == "dry_run"
    run_dir = tmp_path / "jobs" / "job-1" / "trials" / "trial-1"
    assert (run_dir / "telemetry.json").exists()
    assert (run_dir / "trajectory.json").exists()
    assert {a.artifact_type for a in result.artifacts} >= {
        "telemetry_json",
        "trajectory_json",
        "worker_log",
    }
