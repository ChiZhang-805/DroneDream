from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

WRAPPER = (
    Path(__file__).resolve().parents[2]
    / "scripts"
    / "simulators"
    / "local_px4_launch_wrapper.py"
)
RUNNER = Path(__file__).resolve().parents[2] / "scripts" / "simulators" / "px4_gazebo_runner.py"


def _write_json(path: Path, payload: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _make_args(tmp_path: Path) -> list[str]:
    run_dir = tmp_path / "run"
    input_path = _write_json(tmp_path / "trial_input.json", {"trial_id": "t"})
    params = _write_json(tmp_path / "params.json", {"kp_xy": 1.0})
    track = _write_json(tmp_path / "track.json", {"points": [{"x": 0.0, "y": 0.0, "z": 3.0}]})
    telemetry = run_dir / "telemetry.json"
    stdout_log = run_dir / "stdout.log"
    stderr_log = run_dir / "stderr.log"
    return [
        "--run-dir",
        str(run_dir),
        "--input",
        str(input_path),
        "--params",
        str(params),
        "--track",
        str(track),
        "--telemetry",
        str(telemetry),
        "--stdout-log",
        str(stdout_log),
        "--stderr-log",
        str(stderr_log),
        "--vehicle",
        "x500",
        "--world",
        "default",
        "--headless",
        "true",
    ]


def test_wrapper_requires_required_args():
    proc = subprocess.run(
        [sys.executable, str(WRAPPER)],
        text=True,
        capture_output=True,
        check=False,
    )
    assert proc.returncode != 0
    assert "--run-dir" in proc.stderr


def test_wrapper_site_dry_run_writes_valid_telemetry(tmp_path: Path):
    args = _make_args(tmp_path)
    env = os.environ.copy()
    env["PX4_SITE_DRY_RUN"] = "true"
    proc = subprocess.run(
        [sys.executable, str(WRAPPER), *args],
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )

    assert proc.returncode == 0, proc.stderr
    telemetry = json.loads((tmp_path / "run" / "telemetry.json").read_text(encoding="utf-8"))
    assert "samples" in telemetry and len(telemetry["samples"]) == 1
    sample = telemetry["samples"][0]
    assert sample["z"] == 3.0
    assert sample["mode"] == "offboard"
    assert telemetry["meta"]["mode"] == "site_dry_run"
    assert (tmp_path / "run" / "controller_params.used.json").exists()
    assert (tmp_path / "run" / "reference_track.used.json").exists()
    assert (tmp_path / "run" / "launch_config.json").exists()


def test_wrapper_site_dry_run_is_deterministic(tmp_path: Path):
    env = os.environ.copy()
    env["PX4_SITE_DRY_RUN"] = "true"

    run_a = tmp_path / "a"
    run_b = tmp_path / "b"
    proc_a = subprocess.run(
        [sys.executable, str(WRAPPER), *_make_args(run_a)],
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )
    proc_b = subprocess.run(
        [sys.executable, str(WRAPPER), *_make_args(run_b)],
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )

    assert proc_a.returncode == 0
    assert proc_b.returncode == 0
    telemetry_a = json.loads((run_a / "run" / "telemetry.json").read_text(encoding="utf-8"))
    telemetry_b = json.loads((run_b / "run" / "telemetry.json").read_text(encoding="utf-8"))
    assert telemetry_a == telemetry_b


def test_wrapper_real_mode_requires_px4_autopilot_dir(tmp_path: Path):
    env = os.environ.copy()
    env["PX4_SITE_DRY_RUN"] = "false"
    env.pop("PX4_AUTOPILOT_DIR", None)

    proc = subprocess.run(
        [sys.executable, str(WRAPPER), *_make_args(tmp_path)],
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )

    assert proc.returncode != 0
    stderr_text = (tmp_path / "run" / "stderr.log").read_text(encoding="utf-8")
    assert "PX4_AUTOPILOT_DIR is required" in stderr_text


def test_px4_runner_can_call_local_wrapper_in_site_dry_run(tmp_path: Path):
    trial_input = {
        "trial_id": "trial-1",
        "job_id": "job-1",
        "candidate_id": "cand-1",
        "seed": 1,
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
    input_path = _write_json(tmp_path / "trial_input.json", trial_input)
    output_path = tmp_path / "trial_result.json"

    launch_command = (
        f"{sys.executable} {WRAPPER} "
        "--run-dir {run_dir} --input {trial_input} --params {params_json} --track {track_json} "
        "--telemetry {telemetry_json} --stdout-log {stdout_log} --stderr-log {stderr_log} "
        "--vehicle {vehicle} --world {world} --headless {headless}"
    )

    env = os.environ.copy()
    env["PX4_GAZEBO_DRY_RUN"] = "false"
    env["PX4_GAZEBO_LAUNCH_COMMAND"] = launch_command
    env["PX4_SITE_DRY_RUN"] = "true"

    proc = subprocess.run(
        [sys.executable, str(RUNNER), "--input", str(input_path), "--output", str(output_path)],
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )

    assert proc.returncode == 0, proc.stderr
    result = json.loads(output_path.read_text(encoding="utf-8"))
    assert result["success"] is True
    assert result["metrics"]["raw_metric_json"]["mode"] == "real"
