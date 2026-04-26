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


def _set_headless_arg(args: list[str], value: str) -> list[str]:
    updated = list(args)
    headless_idx = updated.index("--headless")
    updated[headless_idx + 1] = value
    return updated


def _basic_telemetry() -> dict:
    return {
        "samples": [
            {
                "t": 0.0,
                "x": 0.0,
                "y": 0.0,
                "z": 3.0,
                "vx": 0.0,
                "vy": 0.0,
                "vz": 0.0,
                "yaw": 0.0,
                "armed": True,
                "mode": "offboard",
                "crashed": False,
            }
        ]
    }


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
    env["PX4_ENABLE_OFFBOARD_EXECUTOR"] = "false"

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
    env["PX4_ENABLE_OFFBOARD_EXECUTOR"] = "false"

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


def test_wrapper_real_mode_without_offboard_executor_preserves_behavior(tmp_path: Path):
    launcher = tmp_path / "launcher.py"
    launcher.write_text("import time\nprint('launched')\ntime.sleep(0.2)\n", encoding="utf-8")
    telemetry_src = _write_json(
        tmp_path / "source_telemetry.json",
        {
            "samples": [
                {
                    "t": 0.0,
                    "x": 0.0,
                    "y": 0.0,
                    "z": 3.0,
                    "vx": 0.0,
                    "vy": 0.0,
                    "vz": 0.0,
                    "yaw": 0.0,
                    "armed": True,
                    "mode": "offboard",
                    "crashed": False,
                }
            ]
        },
    )

    env = os.environ.copy()
    env["PX4_SITE_DRY_RUN"] = "false"
    env["PX4_AUTOPILOT_DIR"] = str(tmp_path)
    env["PX4_LAUNCH_COMMAND_TEMPLATE"] = f"{sys.executable} {launcher}"
    env["PX4_ENABLE_OFFBOARD_EXECUTOR"] = "false"
    env["PX4_RUN_SECONDS"] = "1"
    env["PX4_READY_TIMEOUT_SECONDS"] = "1"
    env["PX4_TELEMETRY_MODE"] = "json"
    env["PX4_TELEMETRY_SOURCE_JSON"] = str(telemetry_src)

    proc = subprocess.run(
        [sys.executable, str(WRAPPER), *_make_args(tmp_path)],
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )

    assert proc.returncode == 0, proc.stderr
    assert (tmp_path / "run" / "telemetry.json").exists()


def test_wrapper_offboard_executor_invoked_while_px4_running(tmp_path: Path):
    pid_file = tmp_path / "px4.pid"
    marker_file = tmp_path / "run" / "executor_ok.txt"
    launcher = tmp_path / "launcher.py"
    launcher.write_text(
        "import pathlib,time,os\n"
        f"pathlib.Path({str(pid_file)!r}).write_text(str(os.getpid()), encoding='utf-8')\n"
        "time.sleep(30)\n",
        encoding="utf-8",
    )
    executor_script = tmp_path / "executor.py"
    executor_script.write_text(
        "import os,sys,pathlib,time\n"
        f"pid_path=pathlib.Path({str(pid_file)!r})\n"
        "for _ in range(50):\n"
        "    if pid_path.exists():\n"
        "        break\n"
        "    time.sleep(0.05)\n"
        "if not pid_path.exists():\n"
        "    sys.exit(4)\n"
        "pid=int(pid_path.read_text(encoding='utf-8').strip())\n"
        "alive=True\n"
        "try:\n"
        "    os.kill(pid, 0)\n"
        "except OSError:\n"
        "    alive=False\n"
        "marker=pathlib.Path(sys.argv[sys.argv.index('--log')+1]).with_name('executor_ok.txt')\n"
        "marker.write_text('alive' if alive else 'dead', encoding='utf-8')\n"
        "log_path = pathlib.Path(sys.argv[sys.argv.index('--log')+1])\n"
        "log_path.write_text('executor ran\\n', encoding='utf-8')\n"
        "sys.exit(0 if alive else 3)\n",
        encoding="utf-8",
    )
    telemetry_src = _write_json(
        tmp_path / "source_telemetry.json",
        {
            "samples": [
                {
                    "t": 0.0,
                    "x": 0.0,
                    "y": 0.0,
                    "z": 3.0,
                    "vx": 0.0,
                    "vy": 0.0,
                    "vz": 0.0,
                    "yaw": 0.0,
                    "armed": True,
                    "mode": "offboard",
                    "crashed": False,
                }
            ]
        },
    )

    env = os.environ.copy()
    env["PX4_SITE_DRY_RUN"] = "false"
    env["PX4_AUTOPILOT_DIR"] = str(tmp_path)
    env["PX4_LAUNCH_COMMAND_TEMPLATE"] = f"{sys.executable} {launcher}"
    env["PX4_ENABLE_OFFBOARD_EXECUTOR"] = "true"
    env["PX4_OFFBOARD_EXECUTOR_COMMAND"] = f"{sys.executable} {executor_script}"
    env["PX4_READY_TIMEOUT_SECONDS"] = "1"
    env["PX4_TELEMETRY_MODE"] = "json"
    env["PX4_TELEMETRY_SOURCE_JSON"] = str(telemetry_src)

    proc = subprocess.run(
        [sys.executable, str(WRAPPER), *_make_args(tmp_path)],
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )

    assert proc.returncode == 0, proc.stderr
    assert marker_file.read_text(encoding="utf-8") == "alive"
    assert (tmp_path / "run" / "offboard_executor.log").exists()


def test_wrapper_offboard_executor_failure_exits_non_zero(tmp_path: Path):
    launcher = tmp_path / "launcher.py"
    launcher.write_text("import time\nprint('launched')\ntime.sleep(30)\n", encoding="utf-8")
    bad_executor = tmp_path / "bad_executor.py"
    bad_executor.write_text(
        "import sys\nprint('boom', file=sys.stderr)\nsys.exit(9)\n",
        encoding="utf-8",
    )
    telemetry_src = _write_json(
        tmp_path / "source_telemetry.json",
        {
            "samples": [
                {
                    "t": 0.0,
                    "x": 0.0,
                    "y": 0.0,
                    "z": 3.0,
                    "vx": 0.0,
                    "vy": 0.0,
                    "vz": 0.0,
                    "yaw": 0.0,
                    "armed": True,
                    "mode": "offboard",
                    "crashed": False,
                }
            ]
        },
    )

    env = os.environ.copy()
    env["PX4_SITE_DRY_RUN"] = "false"
    env["PX4_AUTOPILOT_DIR"] = str(tmp_path)
    env["PX4_LAUNCH_COMMAND_TEMPLATE"] = f"{sys.executable} {launcher}"
    env["PX4_ENABLE_OFFBOARD_EXECUTOR"] = "true"
    env["PX4_OFFBOARD_EXECUTOR_COMMAND"] = f"{sys.executable} {bad_executor}"
    env["PX4_READY_TIMEOUT_SECONDS"] = "1"
    env["PX4_TELEMETRY_MODE"] = "json"
    env["PX4_TELEMETRY_SOURCE_JSON"] = str(telemetry_src)

    proc = subprocess.run(
        [sys.executable, str(WRAPPER), *_make_args(tmp_path)],
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )

    assert proc.returncode != 0
    stderr_text = (tmp_path / "run" / "stderr.log").read_text(encoding="utf-8")
    assert "offboard executor failed" in stderr_text


def test_wrapper_headless_true_does_not_launch_gui_client(tmp_path: Path):
    launcher = tmp_path / "launcher.py"
    launcher.write_text("import time\ntime.sleep(0.4)\n", encoding="utf-8")
    gui_marker = tmp_path / "run" / "gui_invoked.txt"
    gui_script = tmp_path / "gui.py"
    gui_script.write_text(
        "import pathlib\n"
        f"pathlib.Path({str(gui_marker)!r}).write_text('yes', encoding='utf-8')\n",
        encoding="utf-8",
    )
    telemetry_src = _write_json(tmp_path / "source_telemetry.json", _basic_telemetry())
    args = _set_headless_arg(_make_args(tmp_path), "true")

    env = os.environ.copy()
    env["PX4_SITE_DRY_RUN"] = "false"
    env["PX4_AUTOPILOT_DIR"] = str(tmp_path)
    env["PX4_LAUNCH_COMMAND_TEMPLATE"] = f"{sys.executable} {launcher}"
    env["PX4_ENABLE_OFFBOARD_EXECUTOR"] = "false"
    env["PX4_RUN_SECONDS"] = "1"
    env["PX4_READY_TIMEOUT_SECONDS"] = "0"
    env["PX4_TELEMETRY_MODE"] = "json"
    env["PX4_TELEMETRY_SOURCE_JSON"] = str(telemetry_src)
    env["PX4_GAZEBO_LAUNCH_GUI_CLIENT"] = "true"
    env["PX4_GAZEBO_GUI_COMMAND"] = f"{sys.executable} {gui_script}"
    env["PX4_GAZEBO_DRAW_TRACK_MARKER"] = "true"
    env["PX4_GAZEBO_TRACK_MARKER_COMMAND"] = f"{sys.executable} {gui_script}"
    env["DISPLAY"] = ":99"

    proc = subprocess.run(
        [sys.executable, str(WRAPPER), *args],
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )
    assert proc.returncode == 0, proc.stderr
    assert not gui_marker.exists()
    wrapper_stdout = (tmp_path / "run" / "stdout.log").read_text(encoding="utf-8")
    assert "Track marker not launched: headless=true" in wrapper_stdout


def test_wrapper_non_headless_launches_gui_client_and_writes_logs_and_launch_config(tmp_path: Path):
    launcher = tmp_path / "launcher.py"
    launcher.write_text("import time\ntime.sleep(2)\n", encoding="utf-8")
    gui_script = tmp_path / "gui.py"
    gui_script.write_text(
        "import pathlib,time\n"
        "run_dir=pathlib.Path(__file__).resolve().parent / 'run'\n"
        "(run_dir / 'gui_started.txt').write_text('started', encoding='utf-8')\n"
        "print('gui-stdout-line')\n"
        "print('gui-stderr-line', file=__import__('sys').stderr)\n"
        "time.sleep(5)\n",
        encoding="utf-8",
    )
    telemetry_src = _write_json(tmp_path / "source_telemetry.json", _basic_telemetry())
    args = _set_headless_arg(_make_args(tmp_path), "false")

    env = os.environ.copy()
    env["PX4_SITE_DRY_RUN"] = "false"
    env["PX4_AUTOPILOT_DIR"] = str(tmp_path)
    env["PX4_LAUNCH_COMMAND_TEMPLATE"] = f"{sys.executable} {launcher}"
    env["PX4_ENABLE_OFFBOARD_EXECUTOR"] = "false"
    env["PX4_RUN_SECONDS"] = "1"
    env["PX4_READY_TIMEOUT_SECONDS"] = "0"
    env["PX4_TELEMETRY_MODE"] = "json"
    env["PX4_TELEMETRY_SOURCE_JSON"] = str(telemetry_src)
    env["PX4_GAZEBO_LAUNCH_GUI_CLIENT"] = "true"
    env["PX4_GAZEBO_GUI_COMMAND"] = f"{sys.executable} {gui_script}"
    env["PX4_GAZEBO_GUI_START_DELAY_SECONDS"] = "0"
    env["PX4_GAZEBO_GUI_WAIT_TIMEOUT_SECONDS"] = "0.2"
    env["DISPLAY"] = ":99"

    proc = subprocess.run(
        [sys.executable, str(WRAPPER), *args],
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )
    assert proc.returncode == 0, proc.stderr
    assert (tmp_path / "run" / "gui_stdout.log").exists()
    assert (tmp_path / "run" / "gui_stderr.log").exists()
    launch_config = json.loads(
        (tmp_path / "run" / "launch_config.json").read_text(encoding="utf-8")
    )
    assert launch_config["gui_client_enabled"] is True
    assert launch_config["gui_command"] == f"{sys.executable} {gui_script}"
    assert "gui_stdout_log" in launch_config["paths"]
    assert "gui_stderr_log" in launch_config["paths"]


def test_wrapper_gui_failure_is_non_fatal_by_default(tmp_path: Path):
    launcher = tmp_path / "launcher.py"
    launcher.write_text("import time\ntime.sleep(0.4)\n", encoding="utf-8")
    telemetry_src = _write_json(tmp_path / "source_telemetry.json", _basic_telemetry())
    args = _set_headless_arg(_make_args(tmp_path), "false")
    env = os.environ.copy()
    env["PX4_SITE_DRY_RUN"] = "false"
    env["PX4_AUTOPILOT_DIR"] = str(tmp_path)
    env["PX4_LAUNCH_COMMAND_TEMPLATE"] = f"{sys.executable} {launcher}"
    env["PX4_ENABLE_OFFBOARD_EXECUTOR"] = "false"
    env["PX4_RUN_SECONDS"] = "1"
    env["PX4_READY_TIMEOUT_SECONDS"] = "0"
    env["PX4_TELEMETRY_MODE"] = "json"
    env["PX4_TELEMETRY_SOURCE_JSON"] = str(telemetry_src)
    env["PX4_GAZEBO_LAUNCH_GUI_CLIENT"] = "true"
    env["PX4_GAZEBO_GUI_COMMAND"] = "command_that_does_not_exist_12345"
    env["PX4_GAZEBO_GUI_START_DELAY_SECONDS"] = "0"
    env["PX4_GAZEBO_GUI_WAIT_TIMEOUT_SECONDS"] = "2"
    env["DISPLAY"] = ":99"

    proc = subprocess.run(
        [sys.executable, str(WRAPPER), *args],
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )
    assert proc.returncode == 0, proc.stderr
    assert (tmp_path / "run" / "gui_stderr.log").exists()


def test_wrapper_terminates_gui_process_on_exit(tmp_path: Path):
    launcher = tmp_path / "launcher.py"
    launcher.write_text("import time\ntime.sleep(2)\n", encoding="utf-8")
    gui_script = tmp_path / "gui.py"
    gui_script.write_text(
        "import time\n"
        "print('gui-started')\n"
        "time.sleep(30)\n",
        encoding="utf-8",
    )
    telemetry_src = _write_json(tmp_path / "source_telemetry.json", _basic_telemetry())
    args = _set_headless_arg(_make_args(tmp_path), "false")
    env = os.environ.copy()
    env["PX4_SITE_DRY_RUN"] = "false"
    env["PX4_AUTOPILOT_DIR"] = str(tmp_path)
    env["PX4_LAUNCH_COMMAND_TEMPLATE"] = f"{sys.executable} {launcher}"
    env["PX4_ENABLE_OFFBOARD_EXECUTOR"] = "false"
    env["PX4_RUN_SECONDS"] = "1"
    env["PX4_READY_TIMEOUT_SECONDS"] = "0"
    env["PX4_TELEMETRY_MODE"] = "json"
    env["PX4_TELEMETRY_SOURCE_JSON"] = str(telemetry_src)
    env["PX4_GAZEBO_LAUNCH_GUI_CLIENT"] = "true"
    env["PX4_GAZEBO_GUI_COMMAND"] = f"{sys.executable} {gui_script}"
    env["PX4_GAZEBO_GUI_START_DELAY_SECONDS"] = "0"
    env["PX4_GAZEBO_GUI_WAIT_TIMEOUT_SECONDS"] = "0.2"
    env["DISPLAY"] = ":99"

    proc = subprocess.run(
        [sys.executable, str(WRAPPER), *args],
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )
    assert proc.returncode == 0, proc.stderr
    wrapper_stderr = (tmp_path / "run" / "stderr.log").read_text(encoding="utf-8")
    wrapper_stdout = (tmp_path / "run" / "stdout.log").read_text(encoding="utf-8")
    assert "GUI client launch command" in wrapper_stdout
    assert "Sent SIGTERM to GUI process group" in wrapper_stderr


def test_wrapper_non_headless_track_marker_disabled_by_default(tmp_path: Path):
    launcher = tmp_path / "launcher.py"
    launcher.write_text("import time\ntime.sleep(0.2)\n", encoding="utf-8")
    telemetry_src = _write_json(tmp_path / "source_telemetry.json", _basic_telemetry())
    args = _set_headless_arg(_make_args(tmp_path), "false")

    env = os.environ.copy()
    env["PX4_SITE_DRY_RUN"] = "false"
    env["PX4_AUTOPILOT_DIR"] = str(tmp_path)
    env["PX4_LAUNCH_COMMAND_TEMPLATE"] = f"{sys.executable} {launcher}"
    env["PX4_ENABLE_OFFBOARD_EXECUTOR"] = "false"
    env["PX4_RUN_SECONDS"] = "1"
    env["PX4_READY_TIMEOUT_SECONDS"] = "0"
    env["PX4_TELEMETRY_MODE"] = "json"
    env["PX4_TELEMETRY_SOURCE_JSON"] = str(telemetry_src)
    env["DISPLAY"] = ":99"
    env["PX4_GAZEBO_DRAW_TRACK_MARKER"] = "false"

    proc = subprocess.run(
        [sys.executable, str(WRAPPER), *args],
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )
    assert proc.returncode == 0, proc.stderr
    wrapper_stdout = (tmp_path / "run" / "stdout.log").read_text(encoding="utf-8")
    assert "Track marker not launched" in wrapper_stdout
    assert "PX4_GAZEBO_DRAW_TRACK_MARKER=false" in wrapper_stdout
    assert not (tmp_path / "run" / "track_marker_stdout.log").exists()


def test_wrapper_non_headless_track_marker_runs_and_writes_logs(tmp_path: Path):
    launcher = tmp_path / "launcher.py"
    launcher.write_text("import time\ntime.sleep(0.2)\n", encoding="utf-8")
    marker = tmp_path / "marker.py"
    marker.write_text("print('marker-ok')\n", encoding="utf-8")
    telemetry_src = _write_json(tmp_path / "source_telemetry.json", _basic_telemetry())
    args = _set_headless_arg(_make_args(tmp_path), "false")

    env = os.environ.copy()
    env["PX4_SITE_DRY_RUN"] = "false"
    env["PX4_AUTOPILOT_DIR"] = str(tmp_path)
    env["PX4_LAUNCH_COMMAND_TEMPLATE"] = f"{sys.executable} {launcher}"
    env["PX4_ENABLE_OFFBOARD_EXECUTOR"] = "false"
    env["PX4_RUN_SECONDS"] = "1"
    env["PX4_READY_TIMEOUT_SECONDS"] = "0"
    env["PX4_TELEMETRY_MODE"] = "json"
    env["PX4_TELEMETRY_SOURCE_JSON"] = str(telemetry_src)
    env["DISPLAY"] = ":99"
    env["PX4_GAZEBO_DRAW_TRACK_MARKER"] = "true"
    env["PX4_GAZEBO_TRACK_MARKER_START_DELAY_SECONDS"] = "0"
    env["PX4_GAZEBO_TRACK_MARKER_COMMAND"] = f"{sys.executable} {marker}"

    proc = subprocess.run(
        [sys.executable, str(WRAPPER), *args],
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )
    assert proc.returncode == 0, proc.stderr
    assert (tmp_path / "run" / "track_marker_stdout.log").exists()
    assert (tmp_path / "run" / "track_marker_stderr.log").exists()
    marker_stdout = (tmp_path / "run" / "track_marker_stdout.log").read_text(encoding="utf-8")
    wrapper_stdout = (tmp_path / "run" / "stdout.log").read_text(encoding="utf-8")
    assert "marker-ok" in marker_stdout
    assert "Track marker command" in wrapper_stdout
    assert "Track marker exit code: 0" in wrapper_stdout
    launch_config = json.loads(
        (tmp_path / "run" / "launch_config.json").read_text(encoding="utf-8")
    )
    assert launch_config["track_marker_enabled"] is True
    assert launch_config["track_marker_command"] == f"{sys.executable} {marker}"
    assert launch_config["track_marker_require"] is False
    assert "track_marker_stdout_log" in launch_config["paths"]
    assert "track_marker_stderr_log" in launch_config["paths"]


def test_wrapper_track_marker_failure_non_fatal_by_default(tmp_path: Path):
    launcher = tmp_path / "launcher.py"
    launcher.write_text("import time\ntime.sleep(0.2)\n", encoding="utf-8")
    telemetry_src = _write_json(tmp_path / "source_telemetry.json", _basic_telemetry())
    args = _set_headless_arg(_make_args(tmp_path), "false")
    env = os.environ.copy()
    env["PX4_SITE_DRY_RUN"] = "false"
    env["PX4_AUTOPILOT_DIR"] = str(tmp_path)
    env["PX4_LAUNCH_COMMAND_TEMPLATE"] = f"{sys.executable} {launcher}"
    env["PX4_ENABLE_OFFBOARD_EXECUTOR"] = "false"
    env["PX4_RUN_SECONDS"] = "1"
    env["PX4_READY_TIMEOUT_SECONDS"] = "0"
    env["PX4_TELEMETRY_MODE"] = "json"
    env["PX4_TELEMETRY_SOURCE_JSON"] = str(telemetry_src)
    env["DISPLAY"] = ":99"
    env["PX4_GAZEBO_DRAW_TRACK_MARKER"] = "true"
    env["PX4_GAZEBO_TRACK_MARKER_START_DELAY_SECONDS"] = "0"
    env["PX4_GAZEBO_TRACK_MARKER_COMMAND"] = f"{sys.executable} -c \"import sys; sys.exit(9)\""

    proc = subprocess.run(
        [sys.executable, str(WRAPPER), *args],
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )
    assert proc.returncode == 0, proc.stderr
    wrapper_stderr = (tmp_path / "run" / "stderr.log").read_text(encoding="utf-8")
    assert "WARNING: track marker failed" in wrapper_stderr


def test_wrapper_track_marker_failure_fatal_when_required(tmp_path: Path):
    launcher = tmp_path / "launcher.py"
    launcher.write_text("import time\ntime.sleep(0.2)\n", encoding="utf-8")
    telemetry_src = _write_json(tmp_path / "source_telemetry.json", _basic_telemetry())
    args = _set_headless_arg(_make_args(tmp_path), "false")
    env = os.environ.copy()
    env["PX4_SITE_DRY_RUN"] = "false"
    env["PX4_AUTOPILOT_DIR"] = str(tmp_path)
    env["PX4_LAUNCH_COMMAND_TEMPLATE"] = f"{sys.executable} {launcher}"
    env["PX4_ENABLE_OFFBOARD_EXECUTOR"] = "false"
    env["PX4_RUN_SECONDS"] = "1"
    env["PX4_READY_TIMEOUT_SECONDS"] = "0"
    env["PX4_TELEMETRY_MODE"] = "json"
    env["PX4_TELEMETRY_SOURCE_JSON"] = str(telemetry_src)
    env["DISPLAY"] = ":99"
    env["PX4_GAZEBO_DRAW_TRACK_MARKER"] = "true"
    env["PX4_GAZEBO_TRACK_MARKER_START_DELAY_SECONDS"] = "0"
    env["PX4_GAZEBO_REQUIRE_TRACK_MARKER"] = "true"
    env["PX4_GAZEBO_TRACK_MARKER_COMMAND"] = f"{sys.executable} -c \"import sys; sys.exit(6)\""

    proc = subprocess.run(
        [sys.executable, str(WRAPPER), *args],
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )
    assert proc.returncode != 0
    wrapper_stderr = (tmp_path / "run" / "stderr.log").read_text(encoding="utf-8")
    assert "PX4_GAZEBO_REQUIRE_TRACK_MARKER=true" in wrapper_stderr
