from __future__ import annotations

import json
import math
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


def _write_launcher_with_payloads(
    path: Path,
    telemetry_payload: dict[str, object],
    *,
    offboard_timing_payload: dict[str, object] | None = None,
) -> Path:
    script = [
        "import json, pathlib, sys",
        "telemetry = pathlib.Path(sys.argv[sys.argv.index('--telemetry') + 1])",
        f"telemetry.write_text({json.dumps(json.dumps(telemetry_payload))}, encoding='utf-8')",
    ]
    if offboard_timing_payload is not None:
        script.extend(
            [
                "run_dir = telemetry.parent",
                (
                    "(run_dir / 'offboard_timing.json').write_text("
                    f"{json.dumps(json.dumps(offboard_timing_payload))}, encoding='utf-8')"
                ),
            ]
        )
    path.write_text("\n".join(script) + "\n", encoding="utf-8")
    return path


def _track_following_telemetry() -> dict[str, object]:
    samples: list[dict[str, object]] = []
    t = 0.0
    for _ in range(20):
        samples.append(
            {
                "t": round(t, 2),
                "x": 0.0,
                "y": 0.0,
                "z": 0.0,
                "mode": "takeoff",
                "crashed": False,
            }
        )
        t += 0.1
    for i in range(10):
        samples.append(
            {
                "t": round(t, 2),
                "x": 0.5 * i,
                "y": 0.0,
                "z": 3.0,
                "mode": "transition",
                "crashed": False,
            }
        )
        t += 0.1
    for i in range(180):
        theta = 2.0 * 3.141592653589793 * (i / 179)
        samples.append(
            {
                "t": round(t, 2),
                "x": 5.0 * math.cos(theta),
                "y": 5.0 * math.sin(theta),
                "z": 3.0,
                "mode": "offboard",
                "crashed": False,
            }
        )
        t += 0.1
    for _ in range(10):
        samples.append(
            {
                "t": round(t, 2),
                "x": 5.0,
                "y": 0.0,
                "z": 0.0,
                "mode": "land",
                "crashed": False,
            }
        )
        t += 0.1
    return {"samples": samples, "meta": {"source": "test_fixture"}}


def _find_sample_time(samples: list[dict[str, object]], idx: int) -> float:
    value = samples[idx]["t"]
    assert isinstance(value, (int, float))
    return float(value)


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


def test_px4_runner_collects_track_marker_logs_when_present(tmp_path: Path):
    launcher = tmp_path / "launcher.py"
    launcher.write_text(
        "import pathlib, sys\n"
        "telemetry = pathlib.Path(sys.argv[sys.argv.index('--telemetry') + 1])\n"
        "run_dir = telemetry.parent\n"
        "telemetry.write_text("
        "'{\"samples\": [{\"t\": 0.0, \"x\": 0.0, \"y\": 0.0, \"z\": 3.0}]}'"
        ", encoding='utf-8')\n"
        "(run_dir / 'track_marker_stdout.log').write_text('marker ok\\n', encoding='utf-8')\n"
        "(run_dir / 'track_marker_stderr.log').write_text('', encoding='utf-8')\n",
        encoding="utf-8",
    )
    proc, result = _run_runner(
        tmp_path,
        env_overrides={
            "PX4_GAZEBO_DRY_RUN": "false",
            "PX4_GAZEBO_LAUNCH_COMMAND": (
                f"{sys.executable} {launcher} --telemetry {{telemetry_json}}"
            ),
        },
    )
    assert proc.returncode == 0
    assert result["success"] is True
    artifact_types = {artifact["artifact_type"] for artifact in result["artifacts"]}
    assert "gazebo_track_marker_stdout_log" in artifact_types
    assert "gazebo_track_marker_stderr_log" in artifact_types


def test_evaluation_window_ignores_takeoff_transition_and_landing(tmp_path: Path):
    telemetry = _track_following_telemetry()
    launcher = _write_launcher_with_payloads(tmp_path / "launcher.py", telemetry)
    proc, result = _run_runner(
        tmp_path,
        env_overrides={
            "PX4_GAZEBO_DRY_RUN": "false",
            "PX4_GAZEBO_PASS_RMSE": "1.5",
            "PX4_GAZEBO_PASS_MAX_ERROR": "3.0",
            "PX4_GAZEBO_LAUNCH_COMMAND": (
                f"{sys.executable} {launcher} --telemetry {{telemetry_json}}"
            ),
        },
    )
    assert proc.returncode == 0
    assert result["success"] is True
    assert result["metrics"]["raw_metric_json"]["full_log_max_error"] > 4.5
    assert result["metrics"]["rmse"] < 0.2
    assert result["metrics"]["pass_flag"] is True


def test_preflight_and_post_track_ground_samples_do_not_trigger_crash(tmp_path: Path):
    telemetry = _track_following_telemetry()
    launcher = _write_launcher_with_payloads(tmp_path / "launcher.py", telemetry)
    proc, result = _run_runner(
        tmp_path,
        env_overrides={
            "PX4_GAZEBO_DRY_RUN": "false",
            "PX4_GAZEBO_LAUNCH_COMMAND": (
                f"{sys.executable} {launcher} --telemetry {{telemetry_json}}"
            ),
        },
    )
    assert proc.returncode == 0
    assert result["success"] is True
    assert result["metrics"]["crash_flag"] is False
    assert result["metrics"]["raw_metric_json"]["crash_reason"] == "none"


def test_crash_inside_evaluation_window_sets_crash_flag(tmp_path: Path):
    telemetry = _track_following_telemetry()
    samples = telemetry["samples"]
    assert isinstance(samples, list)
    for idx in range(80, 90):
        samples[idx]["crashed"] = True
    launcher = _write_launcher_with_payloads(tmp_path / "launcher.py", telemetry)
    proc, result = _run_runner(
        tmp_path,
        env_overrides={
            "PX4_GAZEBO_DRY_RUN": "false",
            "PX4_GAZEBO_LAUNCH_COMMAND": (
                f"{sys.executable} {launcher} --telemetry {{telemetry_json}}"
            ),
        },
    )
    assert proc.returncode == 0
    assert result["success"] is True
    assert result["metrics"]["crash_flag"] is True
    assert result["metrics"]["raw_metric_json"]["crash_reason"] == "telemetry_crashed_flag"
    assert result["metrics"]["pass_flag"] is False


def test_altitude_collapse_inside_evaluation_window_sets_crash(tmp_path: Path):
    telemetry = _track_following_telemetry()
    samples = telemetry["samples"]
    assert isinstance(samples, list)
    for idx in range(120, 130):
        samples[idx]["z"] = 1.0
    launcher = _write_launcher_with_payloads(tmp_path / "launcher.py", telemetry)
    proc, result = _run_runner(
        tmp_path,
        env_overrides={
            "PX4_GAZEBO_DRY_RUN": "false",
            "PX4_GAZEBO_EVAL_CONSECUTIVE_SAMPLES": "5",
            "PX4_GAZEBO_EVAL_ALTITUDE_FRACTION": "0.3",
            "PX4_GAZEBO_EVAL_COLLAPSE_ALTITUDE_FRACTION": "0.5",
            "PX4_GAZEBO_LAUNCH_COMMAND": (
                f"{sys.executable} {launcher} --telemetry {{telemetry_json}}"
            ),
        },
    )
    assert proc.returncode == 0
    assert result["success"] is True
    assert result["metrics"]["crash_flag"] is True
    assert (
        result["metrics"]["raw_metric_json"]["crash_reason"]
        == "altitude_collapse_in_evaluation_window"
    )


def test_offboard_timing_window_source_is_used_when_present(tmp_path: Path):
    telemetry = _track_following_telemetry()
    samples = telemetry["samples"]
    assert isinstance(samples, list)
    launcher = _write_launcher_with_payloads(
        tmp_path / "launcher.py",
        telemetry,
        offboard_timing_payload={
            "track_start_t": _find_sample_time(samples, 10),
            "track_end_t": _find_sample_time(samples, 210),
            "time_base": "executor_relative_seconds",
        },
    )
    proc, result = _run_runner(
        tmp_path,
        env_overrides={
            "PX4_GAZEBO_DRY_RUN": "false",
            "PX4_GAZEBO_LAUNCH_COMMAND": (
                f"{sys.executable} {launcher} --telemetry {{telemetry_json}}"
            ),
        },
    )
    assert proc.returncode == 0
    assert result["success"] is True
    raw = result["metrics"]["raw_metric_json"]
    assert raw["evaluation_window_source"] == "offboard_timing_refined"
    assert raw["evaluation_window_raw_source"] == "offboard_timing"
    assert raw["evaluation_start_t"] > raw["raw_track_start_t"]
    assert raw["evaluation_trimmed_takeoff_samples"] > 0
    assert raw["crash_reason"] == "none"
    assert result["metrics"]["crash_flag"] is False
    assert raw["evaluation_sample_count"] < raw["total_sample_count"]
    assert result["metrics"]["max_error"] < 3.5


def test_telemetry_derived_window_source_used_when_timing_missing(tmp_path: Path):
    telemetry = _track_following_telemetry()
    launcher = _write_launcher_with_payloads(tmp_path / "launcher.py", telemetry)
    proc, result = _run_runner(
        tmp_path,
        env_overrides={
            "PX4_GAZEBO_DRY_RUN": "false",
            "PX4_GAZEBO_LAUNCH_COMMAND": (
                f"{sys.executable} {launcher} --telemetry {{telemetry_json}}"
            ),
        },
    )
    assert proc.returncode == 0
    assert result["success"] is True
    raw = result["metrics"]["raw_metric_json"]
    assert raw["evaluation_window_source"] == "telemetry_derived_refined"
    for key in (
        "evaluation_window_source",
        "evaluation_window_raw_source",
        "raw_track_start_t",
        "raw_track_end_t",
        "evaluation_start_t",
        "evaluation_end_t",
        "evaluation_sample_count",
        "total_sample_count",
        "evaluation_start_reason",
        "evaluation_trimmed_takeoff_samples",
        "evaluation_trimmed_landing_samples",
        "evaluation_min_z",
        "evaluation_max_z",
        "evaluation_max_error_sample",
        "crash_reason",
    ):
        assert key in raw


def test_entry_requires_consecutive_samples(tmp_path: Path):
    telemetry = _track_following_telemetry()
    samples = telemetry["samples"]
    assert isinstance(samples, list)
    for i in range(20, 40):
        samples[i]["z"] = 0.0
    samples[30]["x"] = 5.0
    samples[30]["y"] = 0.0
    samples[30]["z"] = 3.0
    launcher = _write_launcher_with_payloads(tmp_path / "launcher.py", telemetry)
    proc, result = _run_runner(
        tmp_path,
        env_overrides={
            "PX4_GAZEBO_DRY_RUN": "false",
            "PX4_GAZEBO_EVAL_CONSECUTIVE_SAMPLES": "5",
            "PX4_GAZEBO_LAUNCH_COMMAND": (
                f"{sys.executable} {launcher} --telemetry {{telemetry_json}}"
            ),
        },
    )
    assert proc.returncode == 0
    assert result["success"] is True
    raw = result["metrics"]["raw_metric_json"]
    assert raw["evaluation_start_t"] > float(samples[30]["t"])


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
