from __future__ import annotations

import importlib.util
import json
import math
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

WRAPPER = (
    Path(__file__).resolve().parents[2]
    / "scripts"
    / "simulators"
    / "local_px4_launch_wrapper.py"
)
RUNNER = Path(__file__).resolve().parents[2] / "scripts" / "simulators" / "px4_gazebo_runner.py"
WRAPPER_SPEC = importlib.util.spec_from_file_location("local_px4_launch_wrapper", WRAPPER)
assert WRAPPER_SPEC is not None and WRAPPER_SPEC.loader is not None
wrapper = importlib.util.module_from_spec(WRAPPER_SPEC)
WRAPPER_SPEC.loader.exec_module(wrapper)


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


def _fake_dataset(name: str, data: dict[str, list[float] | list[int]]) -> SimpleNamespace:
    return SimpleNamespace(name=name, data=data)


def _fake_ulog_with_groundtruth_yaw() -> SimpleNamespace:
    return SimpleNamespace(
        data_list=[
            _fake_dataset(
                "vehicle_local_position",
                {
                    "timestamp": [1_000_000, 2_000_000],
                    "x": [1.0, 2.0],
                    "y": [3.0, 4.0],
                    "z": [-5.0, -6.0],
                    "vx": [0.2, 0.2],
                    "vy": [0.0, 0.2],
                    "vz": [-0.1, -0.2],
                },
            ),
            _fake_dataset(
                "vehicle_attitude_groundtruth",
                {
                    "q[0]": [1.0, math.cos(math.pi / 4)],
                    "q[1]": [0.0, 0.0],
                    "q[2]": [0.0, 0.0],
                    "q[3]": [0.0, math.sin(math.pi / 4)],
                },
            ),
            _fake_dataset(
                "vehicle_status",
                {
                    "arming_state": [2, 2],
                    "nav_state": [14, 14],
                },
            ),
            _fake_dataset(
                "failure_detector_status",
                {
                    "fd_motor": [0, 1],
                    "fd_roll": [0, 0],
                },
            ),
        ]
    )


def test_find_latest_ulog_recurses_and_selects_newest(tmp_path: Path):
    older = tmp_path / "2026-04-23" / "08_51_47.ulg"
    newer = tmp_path / "2026-04-24" / "08_53_27.ulg"
    older.parent.mkdir(parents=True, exist_ok=True)
    newer.parent.mkdir(parents=True, exist_ok=True)
    older.write_text("old", encoding="utf-8")
    newer.write_text("new", encoding="utf-8")
    os.utime(older, (1_700_000_000, 1_700_000_000))
    os.utime(newer, (1_800_000_000, 1_800_000_000))

    latest = wrapper.find_latest_ulog(tmp_path)
    assert latest == newer


def test_ulog_to_telemetry_json_writes_schema_with_attitude_groundtruth_fallback(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    fake_ulog = _fake_ulog_with_groundtruth_yaw()

    class FakeULog:
        def __init__(self, _path: str):
            self.data_list = fake_ulog.data_list

    monkeypatch.setitem(sys.modules, "pyulog", SimpleNamespace(ULog=FakeULog))
    output_path = tmp_path / "telemetry.json"
    wrapper.ulog_to_telemetry_json(
        tmp_path / "sample.ulg",
        output_path,
        vehicle="x500",
        world="default",
    )

    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert payload["meta"]["source"] == "ulog"
    assert payload["meta"]["vehicle"] == "x500"
    assert payload["samples"][0]["t"] == 0.0
    assert payload["samples"][0]["z"] == 5.0
    assert payload["samples"][0]["vz"] == 0.1
    assert payload["samples"][0]["yaw"] == pytest.approx(0.0)
    assert payload["samples"][1]["yaw"] == pytest.approx(math.pi / 2)
    assert payload["samples"][0]["mode"] == "14"
    assert payload["samples"][1]["crashed"] is True


def test_ulog_to_telemetry_json_fails_when_vehicle_local_position_missing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    class FakeULog:
        def __init__(self, _path: str):
            self.data_list = [_fake_dataset("vehicle_status", {"nav_state": [1]})]

    monkeypatch.setitem(sys.modules, "pyulog", SimpleNamespace(ULog=FakeULog))
    with pytest.raises(ValueError, match="vehicle_local_position"):
        wrapper.ulog_to_telemetry_json(
            tmp_path / "sample.ulg",
            tmp_path / "telemetry.json",
            "x500",
            "default",
        )


def test_wrapper_real_mode_ulog_uses_px4_ulog_path(tmp_path: Path):
    launcher = tmp_path / "launcher.py"
    launcher.write_text("print('ok')\n", encoding="utf-8")
    ulog_path = tmp_path / "specific.ulg"
    ulog_path.write_text("placeholder", encoding="utf-8")

    env = os.environ.copy()
    env["PX4_SITE_DRY_RUN"] = "false"
    env["PX4_AUTOPILOT_DIR"] = str(tmp_path)
    env["PX4_LAUNCH_COMMAND_TEMPLATE"] = f"{sys.executable} {launcher}"
    env["PX4_TELEMETRY_MODE"] = "ulog"
    env["PX4_ULOG_PATH"] = str(ulog_path)
    env["PYTHONPATH"] = str(tmp_path)

    fake_pyulog = tmp_path / "pyulog.py"
    fake_pyulog.write_text(
        "class DS:\n"
        "    def __init__(self, name, data):\n"
        "        self.name=name\n"
        "        self.data=data\n"
        "class ULog:\n"
        "    def __init__(self, _path):\n"
        "        self.data_list=[\n"
        "            DS('vehicle_local_position', {\n"
        "                'timestamp':[1000000], 'x':[0.0], 'y':[0.0],\n"
        "                'z':[-3.0], 'vx':[0.0], 'vy':[0.0], 'vz':[0.0]\n"
        "            }),\n"
        "            DS('vehicle_attitude_groundtruth', {\n"
        "                'q[0]':[1.0], 'q[1]':[0.0], 'q[2]':[0.0], 'q[3]':[0.0]\n"
        "            })\n"
        "        ]\n",
        encoding="utf-8",
    )

    proc = subprocess.run(
        [sys.executable, str(WRAPPER), *_make_args(tmp_path)],
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )
    assert proc.returncode == 0, proc.stderr
    telemetry = json.loads((tmp_path / "run" / "telemetry.json").read_text(encoding="utf-8"))
    assert telemetry["meta"]["ulog_path"] == str(ulog_path)


def test_wrapper_real_mode_ulog_missing_log_fails_with_clear_message(tmp_path: Path):
    launcher = tmp_path / "launcher.py"
    launcher.write_text("print('ok')\n", encoding="utf-8")

    env = os.environ.copy()
    env["PX4_SITE_DRY_RUN"] = "false"
    env["PX4_AUTOPILOT_DIR"] = str(tmp_path)
    env["PX4_LAUNCH_COMMAND_TEMPLATE"] = f"{sys.executable} {launcher}"
    env["PX4_TELEMETRY_MODE"] = "ulog"
    env["PX4_ULOG_ROOT"] = str(tmp_path / "missing_root")

    proc = subprocess.run(
        [sys.executable, str(WRAPPER), *_make_args(tmp_path)],
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )
    assert proc.returncode != 0
    stderr_text = (tmp_path / "run" / "stderr.log").read_text(encoding="utf-8")
    assert "No ULog files found for PX4_TELEMETRY_MODE=ulog under" in stderr_text


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
