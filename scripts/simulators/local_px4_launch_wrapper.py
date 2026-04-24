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
import time
from pathlib import Path
from typing import Any

DEFAULT_MAKE_TARGET = "gz_x500"
DEFAULT_RUN_SECONDS = 30
DEFAULT_READY_TIMEOUT_SECONDS = 30
DEFAULT_SITE_DRY_RUN = False
DEFAULT_TELEMETRY_MODE = "json"

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


def _render_launch_command(template: str, values: dict[str, str]) -> str:
    rendered = template
    for key, value in values.items():
        rendered = rendered.replace("{" + key + "}", value)
    return rendered


def _terminate_process_group(proc: subprocess.Popen[str], stderr_log: Path) -> None:
    try:
        os.killpg(proc.pid, signal.SIGTERM)
        _append_log(stderr_log, "[local_px4_launch_wrapper] Sent SIGTERM to process group")
    except OSError:
        return

    deadline = time.time() + 2.0
    while time.time() < deadline:
        if proc.poll() is not None:
            return
        time.sleep(0.1)

    try:
        os.killpg(proc.pid, signal.SIGKILL)
        _append_log(stderr_log, "[local_px4_launch_wrapper] Sent SIGKILL to process group")
    except OSError:
        return


def _run_real_process(command: str, *, run_seconds: int, stdout_log: Path, stderr_log: Path) -> int:
    with stdout_log.open("a", encoding="utf-8") as out_handle, stderr_log.open("a", encoding="utf-8") as err_handle:
        proc = subprocess.Popen(  # noqa: S603
            ["bash", "-lc", command],
            stdout=out_handle,
            stderr=err_handle,
            text=True,
            start_new_session=True,
        )
        timed_out = False
        try:
            proc.wait(timeout=run_seconds)
        except subprocess.TimeoutExpired:
            timed_out = True
            _append_log(stderr_log, f"[local_px4_launch_wrapper] Timeout after {run_seconds}s")

        _terminate_process_group(proc, stderr_log)
        if timed_out:
            return 124
        return proc.returncode or 0


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


def _write_launch_config(args: argparse.Namespace, *, autopilot_dir: str | None, setup_commands: str, make_target: str) -> None:
    payload = {
        "vehicle": args.vehicle,
        "world": args.world,
        "headless": _parse_bool(args.headless, default=True),
        "make_target": make_target,
        "PX4_AUTOPILOT_DIR": autopilot_dir,
        "PX4_SETUP_COMMANDS": setup_commands,
        "paths": {
            "run_dir": str(args.run_dir),
            "input": str(args.input),
            "params": str(args.params),
            "track": str(args.track),
            "telemetry": str(args.telemetry),
            "stdout_log": str(args.stdout_log),
            "stderr_log": str(args.stderr_log),
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

    raise ValueError(f"Unsupported PX4_TELEMETRY_MODE: {telemetry_mode}")


def main() -> int:
    args = _parse_args()
    args.run_dir.mkdir(parents=True, exist_ok=True)

    make_target = os.environ.get("PX4_MAKE_TARGET", DEFAULT_MAKE_TARGET).strip() or DEFAULT_MAKE_TARGET
    setup_commands = os.environ.get("PX4_SETUP_COMMANDS", "").strip()
    run_seconds = max(1, _parse_int(os.environ.get("PX4_RUN_SECONDS"), default=DEFAULT_RUN_SECONDS))
    _ = max(1, _parse_int(os.environ.get("PX4_READY_TIMEOUT_SECONDS"), default=DEFAULT_READY_TIMEOUT_SECONDS))
    site_dry_run = _parse_bool(os.environ.get("PX4_SITE_DRY_RUN"), default=DEFAULT_SITE_DRY_RUN)

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

    try:
        command, resolved_autopilot_dir = _resolve_real_launch_command(args)
        _write_launch_config(
            args,
            autopilot_dir=resolved_autopilot_dir,
            setup_commands=setup_commands,
            make_target=make_target,
        )
        _append_log(args.stdout_log, f"[local_px4_launch_wrapper] Launch command: {command}")
        exit_code = _run_real_process(
            command,
            run_seconds=run_seconds,
            stdout_log=args.stdout_log,
            stderr_log=args.stderr_log,
        )
        _append_log(args.stdout_log, f"[local_px4_launch_wrapper] Launcher exit code: {exit_code}")
        _finalize_real_telemetry(args)
        return 0
    except Exception as exc:
        _append_log(args.stderr_log, f"[local_px4_launch_wrapper] Real mode failure: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
