#!/usr/bin/env python3
"""Site-specific PX4/Gazebo launch wrapper used by px4_gazebo_runner.py.

This script is intentionally a thin, configurable launcher layer:
- CI/dev dry-run mode emits deterministic fixture telemetry.
- Real mode launches a local PX4/Gazebo command configured by env vars.
- Telemetry validation/normalization guarantees telemetry JSON exists on success.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import shlex
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

DEFAULT_MAKE_TARGET = "gz_x500"
DEFAULT_RUN_SECONDS = 30
DEFAULT_READY_TIMEOUT_SECONDS = 30
DEFAULT_SITE_DRY_RUN = False
DEFAULT_TELEMETRY_MODE = "json"
DEFAULT_ENABLE_OFFBOARD_EXECUTOR = True
DEFAULT_OFFBOARD_CONNECTION = "udp://:14540"
DEFAULT_OFFBOARD_SETPOINT_RATE_HZ = 10.0
DEFAULT_OFFBOARD_TAKEOFF_TIMEOUT_SECONDS = 30.0
DEFAULT_OFFBOARD_TRACK_TIMEOUT_SECONDS = 120.0
DEFAULT_LAUNCH_GUI_CLIENT = False
DEFAULT_GUI_COMMAND = "gz sim -g"
DEFAULT_GUI_START_DELAY_SECONDS = 5.0
DEFAULT_GUI_WAIT_TIMEOUT_SECONDS = 15.0
DEFAULT_REQUIRE_GUI_CLIENT = False
DEFAULT_DRAW_TRACK_MARKER = False
DEFAULT_TRACK_MARKER_START_DELAY_SECONDS = 2.0
DEFAULT_REQUIRE_TRACK_MARKER = False
DEFAULT_TRACK_MARKER_Z_OFFSET = 0.03
DEFAULT_TRACK_MARKER_COLOR = "0 0.8 1 1"
DEFAULT_TRACK_MARKER_LINE_WIDTH = 0.08
DEFAULT_TRACK_MARKER_MODE = "line_strip"

REQUIRED_SAMPLE_KEYS = (
    "t",
    "x",
    "y",
    "z",
    "vx",
    "vy",
    "vz",
    "yaw",
    "armed",
    "mode",
    "crashed",
)


def _parse_bool(raw: str | None, *, default: bool) -> bool:
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _parse_int(raw: str | None, *, default: int) -> int:
    if raw is None or not raw.strip():
        return default
    return int(raw)


def _parse_float(raw: str | None, *, default: float) -> float:
    if raw is None or not raw.strip():
        return default
    return float(raw)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Local PX4/Gazebo launch wrapper")
    parser.add_argument("--run-dir", required=True, type=Path)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--params", required=True, type=Path)
    parser.add_argument("--track", required=True, type=Path)
    parser.add_argument("--telemetry", required=True, type=Path)
    parser.add_argument("--stdout-log", required=True, type=Path)
    parser.add_argument("--stderr-log", required=True, type=Path)
    parser.add_argument("--vehicle", required=True)
    parser.add_argument("--world", required=True)
    parser.add_argument("--headless", required=True)
    parser.add_argument("--extra-args", default="")
    return parser.parse_args()


def _json_load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _json_dump(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def _append_log(path: Path, message: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(message.rstrip("\n") + "\n")


def _copy_used_inputs(run_dir: Path, params: Path, track: Path) -> tuple[Any, Any]:
    params_payload = _json_load(params)
    track_payload = _json_load(track)
    _json_dump(run_dir / "controller_params.used.json", params_payload)
    _json_dump(run_dir / "reference_track.used.json", track_payload)
    return params_payload, track_payload


def _normalize_telemetry_payload(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict) or not isinstance(payload.get("samples"), list):
        raise ValueError("telemetry must be an object containing samples[]")
    samples = payload["samples"]
    if not samples:
        raise ValueError("telemetry samples[] cannot be empty")

    normalized: list[dict[str, Any]] = []
    for idx, sample in enumerate(samples):
        if not isinstance(sample, dict):
            raise ValueError(f"telemetry sample {idx} must be an object")
        for key in REQUIRED_SAMPLE_KEYS:
            if key not in sample:
                raise ValueError(f"telemetry sample {idx} missing required key: {key}")
        cleaned = {
            "t": float(sample["t"]),
            "x": float(sample["x"]),
            "y": float(sample["y"]),
            "z": float(sample["z"]),
            "vx": float(sample["vx"]),
            "vy": float(sample["vy"]),
            "vz": float(sample["vz"]),
            "yaw": float(sample["yaw"]),
            "armed": bool(sample["armed"]),
            "mode": str(sample["mode"]),
            "crashed": bool(sample["crashed"]),
        }
        for numeric_key in ("t", "x", "y", "z", "vx", "vy", "vz", "yaw"):
            if not math.isfinite(cleaned[numeric_key]):
                raise ValueError(f"telemetry sample {idx} contains non-finite {numeric_key}")
        normalized.append(cleaned)

    meta = payload.get("meta") if isinstance(payload.get("meta"), dict) else {}
    return {"samples": normalized, "meta": meta}


def _write_dry_run_telemetry(path: Path, *, vehicle: str, world: str) -> None:
    payload = {
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
        ],
        "meta": {
            "simulator": "px4_gazebo",
            "vehicle": vehicle,
            "world": world,
            "mode": "site_dry_run",
        },
    }
    _json_dump(path, payload)


def find_latest_ulog(root: Path) -> Path:
    candidates = [path for path in root.rglob("*.ulg") if path.is_file()]
    if not candidates:
        raise FileNotFoundError(f"No ULog files found under {root}")
    return max(candidates, key=lambda path: path.stat().st_mtime)


def _dataset_map(ulog: Any) -> dict[str, Any]:
    return {dataset.name: dataset for dataset in getattr(ulog, "data_list", [])}


def _to_float_list(values: Any, length: int, *, default: float = 0.0) -> list[float]:
    if values is None:
        return [default] * length
    return [float(values[idx]) for idx in range(length)]


def _bool_from_value(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    try:
        return bool(int(value))
    except Exception:
        return bool(value)


def _extract_vehicle_status(dataset_map: dict[str, Any], sample_count: int) -> tuple[list[bool], list[str]]:
    status = dataset_map.get("vehicle_status")
    if status is None:
        return [True] * sample_count, ["unknown"] * sample_count

    data = status.data
    armed_values = data.get("arming_state")
    if armed_values is None:
        armed_values = data.get("armed")
    armed = (
        [_bool_from_value(value) for value in armed_values[:sample_count]]
        if armed_values is not None
        else [True] * sample_count
    )
    if len(armed) < sample_count:
        armed.extend([armed[-1] if armed else True] * (sample_count - len(armed)))

    nav_state_values = data.get("nav_state")
    if nav_state_values is None:
        mode = ["unknown"] * sample_count
    else:
        mode = [str(nav_state_values[idx]) for idx in range(min(sample_count, len(nav_state_values)))]
        if len(mode) < sample_count:
            mode.extend([mode[-1] if mode else "unknown"] * (sample_count - len(mode)))
    return armed, mode


def _extract_crash_flags(dataset_map: dict[str, Any], sample_count: int) -> list[bool]:
    failure = dataset_map.get("failure_detector_status")
    if failure is None:
        return [False] * sample_count

    fields = (
        "fd_alt",
        "fd_arm_escs",
        "fd_battery",
        "fd_ext",
        "fd_imbalanced_prop",
        "fd_motor",
        "fd_pitch",
        "fd_roll",
    )
    flags_by_field: list[Any] = [failure.data.get(field) for field in fields if failure.data.get(field) is not None]
    if not flags_by_field:
        return [False] * sample_count

    crashed: list[bool] = []
    for idx in range(sample_count):
        crashed.append(any(_bool_from_value(field_values[idx]) for field_values in flags_by_field if idx < len(field_values)))
    return crashed


def _quat_to_yaw(q0: float, q1: float, q2: float, q3: float) -> float:
    siny_cosp = 2.0 * (q0 * q3 + q1 * q2)
    cosy_cosp = 1.0 - 2.0 * (q2 * q2 + q3 * q3)
    return math.atan2(siny_cosp, cosy_cosp)


def _extract_yaw_values(
    dataset_map: dict[str, Any], vx_values: list[float], vy_values: list[float], sample_count: int
) -> list[float]:
    for attitude_name in ("vehicle_attitude", "vehicle_attitude_groundtruth", "vehicle_attitude_setpoint"):
        attitude_dataset = dataset_map.get(attitude_name)
        if attitude_dataset is None:
            continue
        q0 = attitude_dataset.data.get("q[0]")
        q1 = attitude_dataset.data.get("q[1]")
        q2 = attitude_dataset.data.get("q[2]")
        q3 = attitude_dataset.data.get("q[3]")
        if any(component is None for component in (q0, q1, q2, q3)):
            continue
        size = min(sample_count, len(q0), len(q1), len(q2), len(q3))
        if size <= 0:
            continue
        yaw_values = [_quat_to_yaw(float(q0[idx]), float(q1[idx]), float(q2[idx]), float(q3[idx])) for idx in range(size)]
        if size < sample_count:
            yaw_values.extend([yaw_values[-1]] * (sample_count - size))
        return yaw_values

    yaw_values: list[float] = []
    for idx in range(sample_count):
        vx = vx_values[idx]
        vy = vy_values[idx]
        if abs(vx) > 1e-6 or abs(vy) > 1e-6:
            yaw_values.append(math.atan2(vy, vx))
        else:
            yaw_values.append(0.0)
    return yaw_values


def ulog_to_telemetry_json(ulog_path: Path, output_path: Path, vehicle: str, world: str) -> None:
    try:
        from pyulog import ULog
    except ModuleNotFoundError as exc:  # pragma: no cover - exercised via wrapper integration
        raise RuntimeError("pyulog is required for PX4_TELEMETRY_MODE=ulog") from exc

    ulog = ULog(str(ulog_path))
    datasets = _dataset_map(ulog)
    local_position = datasets.get("vehicle_local_position")
    if local_position is None:
        raise ValueError("vehicle_local_position dataset is required in ULog")

    data = local_position.data
    timestamps = data.get("timestamp")
    if timestamps is None or len(timestamps) == 0:
        raise ValueError("vehicle_local_position.timestamp is required and cannot be empty")

    sample_count = len(timestamps)
    t0 = float(timestamps[0])
    x_values = _to_float_list(data.get("x"), sample_count)
    y_values = _to_float_list(data.get("y"), sample_count)
    z_values = _to_float_list(data.get("z"), sample_count)
    vx_values = _to_float_list(data.get("vx"), sample_count)
    vy_values = _to_float_list(data.get("vy"), sample_count)
    vz_values = _to_float_list(data.get("vz"), sample_count)
    yaw_values = _extract_yaw_values(datasets, vx_values, vy_values, sample_count)
    armed_values, mode_values = _extract_vehicle_status(datasets, sample_count)
    crashed_values = _extract_crash_flags(datasets, sample_count)

    samples = []
    for idx in range(sample_count):
        samples.append(
            {
                "t": (float(timestamps[idx]) - t0) / 1_000_000.0,
                "x": x_values[idx],
                "y": y_values[idx],
                "z": -z_values[idx],
                "vx": vx_values[idx],
                "vy": vy_values[idx],
                "vz": -vz_values[idx],
                "yaw": yaw_values[idx],
                "armed": armed_values[idx],
                "mode": mode_values[idx],
                "crashed": crashed_values[idx],
            }
        )

    if not samples:
        raise ValueError("Converted telemetry samples cannot be empty")

    payload = {
        "samples": samples,
        "meta": {
            "simulator": "px4_gazebo",
            "source": "ulog",
            "ulog_path": str(ulog_path),
            "vehicle": vehicle,
            "world": world,
        },
    }
    _json_dump(output_path, payload)


def _render_launch_command(template: str, values: dict[str, str]) -> str:
    rendered = template
    for key, value in values.items():
        rendered = rendered.replace("{" + key + "}", value)
    return rendered


def _terminate_process_group(proc: subprocess.Popen[str], stderr_log: Path, *, label: str) -> None:
    try:
        os.killpg(proc.pid, signal.SIGTERM)
        _append_log(stderr_log, f"[local_px4_launch_wrapper] Sent SIGTERM to {label} process group")
    except OSError:
        return

    deadline = time.time() + 2.0
    while time.time() < deadline:
        if proc.poll() is not None:
            return
        time.sleep(0.1)

    try:
        os.killpg(proc.pid, signal.SIGKILL)
        _append_log(stderr_log, f"[local_px4_launch_wrapper] Sent SIGKILL to {label} process group")
    except OSError:
        return


def _launch_process(
    command: str,
    *,
    stdout_log: Path,
    stderr_log: Path,
    launch_env: dict[str, str] | None = None,
) -> subprocess.Popen[str]:
    out_handle = stdout_log.open("a", encoding="utf-8")
    err_handle = stderr_log.open("a", encoding="utf-8")
    proc = subprocess.Popen(  # noqa: S603
        ["bash", "-lc", command],
        stdout=out_handle,
        stderr=err_handle,
        text=True,
        start_new_session=True,
        env=launch_env,
    )
    proc._stdout_handle = out_handle  # type: ignore[attr-defined]
    proc._stderr_handle = err_handle  # type: ignore[attr-defined]
    return proc


def _close_launch_handles(proc: subprocess.Popen[str]) -> None:
    out_handle = getattr(proc, "_stdout_handle", None)
    err_handle = getattr(proc, "_stderr_handle", None)
    if out_handle is not None:
        out_handle.close()
    if err_handle is not None:
        err_handle.close()


def _cleanup_process(proc: subprocess.Popen[str] | None, stderr_log: Path, *, label: str) -> None:
    if proc is None:
        return
    _terminate_process_group(proc, stderr_log, label=label)
    _close_launch_handles(proc)


def _default_offboard_executor_command() -> str:
    script_path = Path(__file__).resolve().parent / "px4_offboard_track_executor.py"
    return f"python3 {shlex.quote(str(script_path))}"


def _default_track_marker_command(args: argparse.Namespace) -> str:
    script_path = Path(__file__).resolve().parent / "gazebo_track_marker.py"
    return (
        f"{shlex.quote(sys.executable)} {shlex.quote(str(script_path))} "
        f"--track {shlex.quote(str(args.track))} "
        f"--world {shlex.quote(args.world)} "
        f"--z-offset {shlex.quote(str(_parse_float(os.environ.get('PX4_GAZEBO_TRACK_MARKER_Z_OFFSET'), default=DEFAULT_TRACK_MARKER_Z_OFFSET)))} "
        f"--color {shlex.quote(os.environ.get('PX4_GAZEBO_TRACK_MARKER_COLOR', DEFAULT_TRACK_MARKER_COLOR).strip() or DEFAULT_TRACK_MARKER_COLOR)} "
        f"--line-width {shlex.quote(str(_parse_float(os.environ.get('PX4_GAZEBO_TRACK_MARKER_LINE_WIDTH'), default=DEFAULT_TRACK_MARKER_LINE_WIDTH)))} "
        f"--mode {shlex.quote((os.environ.get('PX4_GAZEBO_TRACK_MARKER_MODE', DEFAULT_TRACK_MARKER_MODE).strip() or DEFAULT_TRACK_MARKER_MODE).lower())}"
    )


def _build_track_marker_command(args: argparse.Namespace) -> str:
    override = os.environ.get("PX4_GAZEBO_TRACK_MARKER_COMMAND", "").strip()
    if override:
        return override
    return _default_track_marker_command(args)


def _run_track_marker(args: argparse.Namespace, stderr_log: Path) -> int:
    command = _build_track_marker_command(args)
    stdout_log = args.run_dir / "track_marker_stdout.log"
    stderr_marker_log = args.run_dir / "track_marker_stderr.log"
    _append_log(args.stdout_log, f"[local_px4_launch_wrapper] Track marker command: {command}")
    proc = subprocess.run(  # noqa: S603
        ["bash", "-lc", command],
        text=True,
        capture_output=True,
        check=False,
    )
    stdout_log.write_text(proc.stdout or "", encoding="utf-8")
    stderr_marker_log.write_text(proc.stderr or "", encoding="utf-8")
    _append_log(args.stdout_log, f"[local_px4_launch_wrapper] Track marker exit code: {proc.returncode}")
    if proc.returncode != 0:
        _append_log(
            stderr_log,
            "[local_px4_launch_wrapper] WARNING: track marker failed "
            f"with code {proc.returncode}; see {stderr_marker_log}",
        )
    return proc.returncode


def _build_offboard_executor_argv(args: argparse.Namespace) -> list[str]:
    command = os.environ.get("PX4_OFFBOARD_EXECUTOR_COMMAND", "").strip() or _default_offboard_executor_command()
    setpoint_rate_hz = _parse_float(
        os.environ.get("PX4_OFFBOARD_SETPOINT_RATE_HZ"), default=DEFAULT_OFFBOARD_SETPOINT_RATE_HZ
    )
    takeoff_timeout = _parse_float(
        os.environ.get("PX4_OFFBOARD_TAKEOFF_TIMEOUT_SECONDS"), default=DEFAULT_OFFBOARD_TAKEOFF_TIMEOUT_SECONDS
    )
    track_timeout = _parse_float(
        os.environ.get("PX4_OFFBOARD_TRACK_TIMEOUT_SECONDS"), default=DEFAULT_OFFBOARD_TRACK_TIMEOUT_SECONDS
    )
    connection = os.environ.get("PX4_OFFBOARD_CONNECTION", DEFAULT_OFFBOARD_CONNECTION).strip() or DEFAULT_OFFBOARD_CONNECTION
    offboard_log = args.run_dir / "offboard_executor.log"

    argv = shlex.split(command)
    argv.extend(
        [
            "--run-dir",
            str(args.run_dir),
            "--track",
            str(args.track),
            "--params",
            str(args.params),
            "--vehicle",
            args.vehicle,
            "--world",
            args.world,
            "--connection",
            connection,
            "--setpoint-rate-hz",
            str(setpoint_rate_hz),
            "--takeoff-timeout-seconds",
            str(takeoff_timeout),
            "--track-timeout-seconds",
            str(track_timeout),
            "--log",
            str(offboard_log),
        ]
    )
    return argv


def _run_offboard_executor(args: argparse.Namespace, stderr_log: Path) -> int:
    argv = _build_offboard_executor_argv(args)
    _append_log(args.stdout_log, f"[local_px4_launch_wrapper] Offboard executor command: {shlex.join(argv)}")
    proc = subprocess.run(  # noqa: S603
        argv,
        text=True,
        capture_output=True,
        check=False,
    )
    if proc.stdout:
        _append_log(args.stdout_log, proc.stdout)
    if proc.stderr:
        _append_log(stderr_log, proc.stderr)
    return proc.returncode


def _resolve_real_launch_command(args: argparse.Namespace) -> tuple[str, str | None]:
    setup_commands = os.environ.get("PX4_SETUP_COMMANDS", "").strip()
    make_target = os.environ.get("PX4_MAKE_TARGET", DEFAULT_MAKE_TARGET).strip() or DEFAULT_MAKE_TARGET
    launch_template = os.environ.get("PX4_LAUNCH_COMMAND_TEMPLATE", "").strip()
    autopilot_dir = os.environ.get("PX4_AUTOPILOT_DIR", "").strip()

    values = {
        "run_dir": shlex.quote(str(args.run_dir)),
        "input": shlex.quote(str(args.input)),
        "params": shlex.quote(str(args.params)),
        "track": shlex.quote(str(args.track)),
        "telemetry": shlex.quote(str(args.telemetry)),
        "stdout_log": shlex.quote(str(args.stdout_log)),
        "stderr_log": shlex.quote(str(args.stderr_log)),
        "vehicle": shlex.quote(args.vehicle),
        "world": shlex.quote(args.world),
        "headless": "1" if _parse_bool(args.headless, default=True) else "0",
        "extra_args": args.extra_args,
        "make_target": shlex.quote(make_target),
        "px4_autopilot_dir": shlex.quote(autopilot_dir),
    }

    if launch_template:
        return _render_launch_command(launch_template, values), autopilot_dir or None

    if not autopilot_dir:
        raise ValueError("PX4_AUTOPILOT_DIR is required in real mode when PX4_LAUNCH_COMMAND_TEMPLATE is unset")

    autopilot_path = Path(autopilot_dir)
    if not autopilot_path.exists() or not autopilot_path.is_dir():
        raise ValueError(f"PX4_AUTOPILOT_DIR does not exist or is not a directory: {autopilot_dir}")

    components: list[str] = []
    if setup_commands:
        components.append(setup_commands)
    components.append(f"cd {shlex.quote(str(autopilot_path))}")
    components.append(f"HEADLESS={values['headless']} make px4_sitl {shlex.quote(make_target)}")
    return "; ".join(components), str(autopilot_path)


def _write_launch_config(
    args: argparse.Namespace,
    *,
    autopilot_dir: str | None,
    setup_commands: str,
    make_target: str,
) -> None:
    gui_command = os.environ.get("PX4_GAZEBO_GUI_COMMAND", DEFAULT_GUI_COMMAND).strip() or DEFAULT_GUI_COMMAND
    track_marker_command = _build_track_marker_command(args)
    track_marker_stdout_log = args.run_dir / "track_marker_stdout.log"
    track_marker_stderr_log = args.run_dir / "track_marker_stderr.log"
    gui_stdout_log = args.run_dir / "gui_stdout.log"
    gui_stderr_log = args.run_dir / "gui_stderr.log"
    payload = {
        "vehicle": args.vehicle,
        "world": args.world,
        "headless": _parse_bool(args.headless, default=True),
        "make_target": make_target,
        "PX4_AUTOPILOT_DIR": autopilot_dir,
        "PX4_SETUP_COMMANDS": setup_commands,
        "PX4_ENABLE_OFFBOARD_EXECUTOR": _parse_bool(
            os.environ.get("PX4_ENABLE_OFFBOARD_EXECUTOR"), default=DEFAULT_ENABLE_OFFBOARD_EXECUTOR
        ),
        "PX4_OFFBOARD_CONNECTION": os.environ.get("PX4_OFFBOARD_CONNECTION", DEFAULT_OFFBOARD_CONNECTION),
        "gui_client_enabled": _parse_bool(
            os.environ.get("PX4_GAZEBO_LAUNCH_GUI_CLIENT"), default=DEFAULT_LAUNCH_GUI_CLIENT
        ),
        "gui_command": gui_command,
        "gui_require_client": _parse_bool(
            os.environ.get("PX4_GAZEBO_REQUIRE_GUI_CLIENT"), default=DEFAULT_REQUIRE_GUI_CLIENT
        ),
        "gui_start_delay_seconds": _parse_float(
            os.environ.get("PX4_GAZEBO_GUI_START_DELAY_SECONDS"), default=DEFAULT_GUI_START_DELAY_SECONDS
        ),
        "gui_wait_timeout_seconds": _parse_float(
            os.environ.get("PX4_GAZEBO_GUI_WAIT_TIMEOUT_SECONDS"), default=DEFAULT_GUI_WAIT_TIMEOUT_SECONDS
        ),
        "track_marker_enabled": _parse_bool(
            os.environ.get("PX4_GAZEBO_DRAW_TRACK_MARKER"), default=DEFAULT_DRAW_TRACK_MARKER
        ),
        "track_marker_command": track_marker_command,
        "track_marker_start_delay_seconds": _parse_float(
            os.environ.get("PX4_GAZEBO_TRACK_MARKER_START_DELAY_SECONDS"),
            default=DEFAULT_TRACK_MARKER_START_DELAY_SECONDS,
        ),
        "track_marker_require": _parse_bool(
            os.environ.get("PX4_GAZEBO_REQUIRE_TRACK_MARKER"), default=DEFAULT_REQUIRE_TRACK_MARKER
        ),
        "track_marker_z_offset": _parse_float(
            os.environ.get("PX4_GAZEBO_TRACK_MARKER_Z_OFFSET"), default=DEFAULT_TRACK_MARKER_Z_OFFSET
        ),
        "track_marker_color": os.environ.get(
            "PX4_GAZEBO_TRACK_MARKER_COLOR", DEFAULT_TRACK_MARKER_COLOR
        ).strip()
        or DEFAULT_TRACK_MARKER_COLOR,
        "track_marker_line_width": _parse_float(
            os.environ.get("PX4_GAZEBO_TRACK_MARKER_LINE_WIDTH"), default=DEFAULT_TRACK_MARKER_LINE_WIDTH
        ),
        "track_marker_mode": os.environ.get(
            "PX4_GAZEBO_TRACK_MARKER_MODE", DEFAULT_TRACK_MARKER_MODE
        ).strip()
        or DEFAULT_TRACK_MARKER_MODE,
        "paths": {
            "run_dir": str(args.run_dir),
            "input": str(args.input),
            "params": str(args.params),
            "track": str(args.track),
            "telemetry": str(args.telemetry),
            "stdout_log": str(args.stdout_log),
            "stderr_log": str(args.stderr_log),
            "gui_stdout_log": str(gui_stdout_log),
            "gui_stderr_log": str(gui_stderr_log),
            "track_marker_stdout_log": str(track_marker_stdout_log),
            "track_marker_stderr_log": str(track_marker_stderr_log),
        },
    }
    _json_dump(args.run_dir / "launch_config.json", payload)


def _finalize_real_telemetry(args: argparse.Namespace) -> None:
    telemetry_source = os.environ.get("PX4_TELEMETRY_SOURCE_JSON", "").strip()
    telemetry_mode = os.environ.get("PX4_TELEMETRY_MODE", DEFAULT_TELEMETRY_MODE).strip().lower() or DEFAULT_TELEMETRY_MODE

    if telemetry_source:
        source_path = Path(telemetry_source)
        if not source_path.exists():
            raise ValueError(f"PX4_TELEMETRY_SOURCE_JSON does not exist: {telemetry_source}")
        shutil.copyfile(source_path, args.telemetry)

    if telemetry_mode == "json":
        if not args.telemetry.exists():
            raise ValueError("Telemetry JSON missing after launcher exit")
        payload = _json_load(args.telemetry)
        normalized = _normalize_telemetry_payload(payload)
        _json_dump(args.telemetry, normalized)
        return

    if telemetry_mode == "ulog":
        ulog_path_raw = os.environ.get("PX4_ULOG_PATH", "").strip()
        if ulog_path_raw:
            ulog_path = Path(ulog_path_raw)
            if not ulog_path.is_file():
                raise FileNotFoundError(f"PX4_ULOG_PATH does not exist or is not a file: {ulog_path_raw}")
        else:
            ulog_root_raw = os.environ.get("PX4_ULOG_ROOT", "").strip()
            if ulog_root_raw:
                ulog_root = Path(ulog_root_raw)
            else:
                autopilot_dir = os.environ.get("PX4_AUTOPILOT_DIR", "").strip()
                if not autopilot_dir:
                    raise ValueError("PX4_AUTOPILOT_DIR is required to locate default PX4 ULog root")
                ulog_root = Path(autopilot_dir) / "build" / "px4_sitl_default" / "rootfs" / "log"
            try:
                ulog_path = find_latest_ulog(ulog_root)
            except FileNotFoundError as exc:
                raise FileNotFoundError(f"No ULog files found for PX4_TELEMETRY_MODE=ulog under: {ulog_root}") from exc

        ulog_to_telemetry_json(
            ulog_path,
            args.telemetry,
            vehicle=args.vehicle,
            world=args.world,
        )
        payload = _json_load(args.telemetry)
        normalized = _normalize_telemetry_payload(payload)
        _json_dump(args.telemetry, normalized)
        return

    raise ValueError(f"Unsupported PX4_TELEMETRY_MODE: {telemetry_mode}")


def main() -> int:
    args = _parse_args()
    args.run_dir.mkdir(parents=True, exist_ok=True)

    make_target = os.environ.get("PX4_MAKE_TARGET", DEFAULT_MAKE_TARGET).strip() or DEFAULT_MAKE_TARGET
    setup_commands = os.environ.get("PX4_SETUP_COMMANDS", "").strip()
    run_seconds = max(1, _parse_int(os.environ.get("PX4_RUN_SECONDS"), default=DEFAULT_RUN_SECONDS))
    ready_timeout_seconds = max(
        1, _parse_int(os.environ.get("PX4_READY_TIMEOUT_SECONDS"), default=DEFAULT_READY_TIMEOUT_SECONDS)
    )
    site_dry_run = _parse_bool(os.environ.get("PX4_SITE_DRY_RUN"), default=DEFAULT_SITE_DRY_RUN)
    enable_offboard_executor = _parse_bool(
        os.environ.get("PX4_ENABLE_OFFBOARD_EXECUTOR"), default=DEFAULT_ENABLE_OFFBOARD_EXECUTOR
    )
    headless = _parse_bool(args.headless, default=True)
    gui_launch_enabled = _parse_bool(
        os.environ.get("PX4_GAZEBO_LAUNCH_GUI_CLIENT"), default=DEFAULT_LAUNCH_GUI_CLIENT
    )
    require_gui_client = _parse_bool(
        os.environ.get("PX4_GAZEBO_REQUIRE_GUI_CLIENT"), default=DEFAULT_REQUIRE_GUI_CLIENT
    )
    gui_command = os.environ.get("PX4_GAZEBO_GUI_COMMAND", DEFAULT_GUI_COMMAND).strip() or DEFAULT_GUI_COMMAND
    gui_start_delay_seconds = max(
        0.0,
        _parse_float(
            os.environ.get("PX4_GAZEBO_GUI_START_DELAY_SECONDS"),
            default=DEFAULT_GUI_START_DELAY_SECONDS,
        ),
    )
    gui_wait_timeout_seconds = max(
        0.0,
        _parse_float(
            os.environ.get("PX4_GAZEBO_GUI_WAIT_TIMEOUT_SECONDS"),
            default=DEFAULT_GUI_WAIT_TIMEOUT_SECONDS,
        ),
    )
    display = os.environ.get("DISPLAY", "").strip()
    draw_track_marker = _parse_bool(
        os.environ.get("PX4_GAZEBO_DRAW_TRACK_MARKER"), default=DEFAULT_DRAW_TRACK_MARKER
    )
    track_marker_start_delay_seconds = max(
        0.0,
        _parse_float(
            os.environ.get("PX4_GAZEBO_TRACK_MARKER_START_DELAY_SECONDS"),
            default=DEFAULT_TRACK_MARKER_START_DELAY_SECONDS,
        ),
    )
    require_track_marker = _parse_bool(
        os.environ.get("PX4_GAZEBO_REQUIRE_TRACK_MARKER"), default=DEFAULT_REQUIRE_TRACK_MARKER
    )
    gui_stdout_log = args.run_dir / "gui_stdout.log"
    gui_stderr_log = args.run_dir / "gui_stderr.log"

    try:
        _copy_used_inputs(args.run_dir, args.params, args.track)
    except Exception as exc:
        _append_log(args.stderr_log, f"[local_px4_launch_wrapper] Failed reading params/track: {exc}")
        return 2

    if site_dry_run:
        _write_launch_config(
            args,
            autopilot_dir=os.environ.get("PX4_AUTOPILOT_DIR", "").strip() or None,
            setup_commands=setup_commands,
            make_target=make_target,
        )
        _write_dry_run_telemetry(args.telemetry, vehicle=args.vehicle, world=args.world)
        _append_log(args.stdout_log, "[local_px4_launch_wrapper] site dry-run enabled; no PX4 process launched")
        _append_log(args.stderr_log, "")
        return 0

    px4_proc: subprocess.Popen[str] | None = None
    gui_proc: subprocess.Popen[str] | None = None
    try:
        command, resolved_autopilot_dir = _resolve_real_launch_command(args)
        _write_launch_config(
            args,
            autopilot_dir=resolved_autopilot_dir,
            setup_commands=setup_commands,
            make_target=make_target,
        )
        _append_log(args.stdout_log, f"[local_px4_launch_wrapper] Launch command: {command}")
        px4_proc = _launch_process(
            command,
            stdout_log=args.stdout_log,
            stderr_log=args.stderr_log,
        )
        _append_log(
            args.stdout_log,
            f"[local_px4_launch_wrapper] Waiting {ready_timeout_seconds}s for PX4 readiness (simple fixed wait)",
        )
        time.sleep(float(ready_timeout_seconds))

        should_launch_gui = (not headless) and gui_launch_enabled and bool(display)
        if should_launch_gui:
            if gui_start_delay_seconds > 0:
                _append_log(
                    args.stdout_log,
                    f"[local_px4_launch_wrapper] Waiting {gui_start_delay_seconds}s before launching GUI client",
                )
                time.sleep(gui_start_delay_seconds)

            gui_proc = _launch_process(
                gui_command,
                stdout_log=gui_stdout_log,
                stderr_log=gui_stderr_log,
                launch_env=os.environ.copy(),
            )
            _append_log(args.stdout_log, f"[local_px4_launch_wrapper] GUI client launch command: {gui_command}")

            startup_deadline = time.time() + gui_wait_timeout_seconds
            while time.time() < startup_deadline:
                if gui_proc.poll() is not None:
                    break
                time.sleep(0.1)
            if gui_proc.poll() is not None:
                gui_error = (
                    "[local_px4_launch_wrapper] GUI client exited early "
                    f"with code {gui_proc.returncode}; command={gui_command}"
                )
                _append_log(gui_stderr_log, gui_error)
                _append_log(args.stderr_log, gui_error)
                _close_launch_handles(gui_proc)
                gui_proc = None
                if require_gui_client:
                    raise RuntimeError("GUI client failed to start and PX4_GAZEBO_REQUIRE_GUI_CLIENT=true")
            else:
                _append_log(
                    args.stdout_log,
                    f"[local_px4_launch_wrapper] GUI client running after {gui_wait_timeout_seconds}s startup window",
                )
        else:
            reason_bits: list[str] = []
            if headless:
                reason_bits.append("headless=true")
            if not gui_launch_enabled:
                reason_bits.append("PX4_GAZEBO_LAUNCH_GUI_CLIENT=false")
            if not display:
                reason_bits.append("DISPLAY is empty")
            _append_log(
                args.stdout_log,
                "[local_px4_launch_wrapper] GUI client not launched: " + ", ".join(reason_bits),
            )

        if px4_proc.poll() is not None and enable_offboard_executor:
            raise RuntimeError(f"PX4 process exited before offboard execution with code {px4_proc.returncode}")

        should_draw_track_marker = (not headless) and bool(display) and draw_track_marker
        if should_draw_track_marker:
            if track_marker_start_delay_seconds > 0:
                _append_log(
                    args.stdout_log,
                    (
                        "[local_px4_launch_wrapper] Waiting "
                        f"{track_marker_start_delay_seconds}s before drawing track marker"
                    ),
                )
                time.sleep(track_marker_start_delay_seconds)
            marker_exit = _run_track_marker(args, args.stderr_log)
            if marker_exit != 0 and require_track_marker:
                raise RuntimeError(
                    "track marker failed and PX4_GAZEBO_REQUIRE_TRACK_MARKER=true "
                    f"(exit={marker_exit})"
                )
        else:
            reason_bits = []
            if headless:
                reason_bits.append("headless=true")
            if not display:
                reason_bits.append("DISPLAY empty")
            if not draw_track_marker:
                reason_bits.append("PX4_GAZEBO_DRAW_TRACK_MARKER=false")
            _append_log(
                args.stdout_log,
                "[local_px4_launch_wrapper] Track marker not launched: " + " / ".join(reason_bits),
            )

        if enable_offboard_executor:
            executor_exit = _run_offboard_executor(args, args.stderr_log)
            _append_log(args.stdout_log, f"[local_px4_launch_wrapper] Offboard executor exit code: {executor_exit}")
            if executor_exit != 0:
                raise RuntimeError(f"offboard executor failed with code {executor_exit}")
        else:
            _append_log(
                args.stdout_log,
                "[local_px4_launch_wrapper] PX4_ENABLE_OFFBOARD_EXECUTOR=false; preserving launcher-only behavior",
            )
            time.sleep(float(run_seconds))

        _cleanup_process(gui_proc, args.stderr_log, label="GUI")
        gui_proc = None
        _cleanup_process(px4_proc, args.stderr_log, label="PX4")
        px4_proc = None
        _append_log(args.stdout_log, "[local_px4_launch_wrapper] PX4 process terminated after execution window")
        _finalize_real_telemetry(args)
        return 0
    except Exception as exc:
        _cleanup_process(gui_proc, args.stderr_log, label="GUI")
        _cleanup_process(px4_proc, args.stderr_log, label="PX4")
        _append_log(args.stderr_log, f"[local_px4_launch_wrapper] Real mode failure: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
