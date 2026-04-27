#!/usr/bin/env python3
"""Environment-driven PX4/Gazebo runner for DroneDream real_cli protocol.

This script is a drop-in REAL_SIMULATOR_COMMAND target. It reads trial_input.json,
creates run artifacts (controller params, reference track, telemetry, trajectory,
logs), executes a configurable lower-level launcher when available, computes
DroneDream metrics, and writes trial_result.json.

The repository does NOT ship a full PX4/Gazebo workspace. Therefore, the runner
supports:
- DRY RUN mode for deterministic CI/local validation without Gazebo.
- ADAPTER_UNAVAILABLE failures when launch command/binaries are not configured.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import shlex
import shutil
import signal
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

FAILURE_ADAPTER_UNAVAILABLE = "ADAPTER_UNAVAILABLE"
FAILURE_TIMEOUT = "TIMEOUT"
FAILURE_SIMULATION = "SIMULATION_FAILED"

_REQUIRED_PARAM_KEYS = (
    "kp_xy",
    "kd_xy",
    "ki_xy",
    "vel_limit",
    "accel_limit",
    "disturbance_rejection",
)

_TEMPLATE_TOKENS = (
    "run_dir",
    "trial_input",
    "trial_output",
    "params_json",
    "track_json",
    "telemetry_json",
    "trajectory_json",
    "stdout_log",
    "stderr_log",
    "job_id",
    "trial_id",
    "candidate_id",
    "seed",
    "scenario_type",
    "vehicle",
    "world",
    "headless",
    "extra_args",
)


@dataclass(frozen=True)
class RunnerEnv:
    launch_command: str
    workdir: str | None
    timeout_seconds: int
    headless: bool
    keep_raw_logs: bool
    dry_run: bool
    pass_rmse: float
    pass_max_error: float
    min_track_coverage: float
    vehicle: str
    world: str
    extra_args: str
    telemetry_format: str
    allow_csv_telemetry: bool
    eval_altitude_fraction: float
    eval_near_track_threshold_m: float
    eval_consecutive_samples: int
    eval_collapse_altitude_fraction: float


@dataclass(frozen=True)
class EvaluationWindow:
    start_idx: int
    end_idx: int
    source: str
    raw_source: str
    raw_start_t: float | None
    raw_end_t: float | None
    start_reason: str
    trimmed_takeoff_samples: int
    trimmed_landing_samples: int


class RunnerError(Exception):
    """Expected runner-level exception that maps to SIMULATION_FAILED."""


class TimeoutRunnerError(RunnerError):
    """Raised when lower-level simulator exceeds timeout."""


def _parse_bool(raw: str | None, *, default: bool) -> bool:
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _parse_float(raw: str | None, *, default: float) -> float:
    if raw is None or not raw.strip():
        return default
    return float(raw)


def _parse_int(raw: str | None, *, default: int) -> int:
    if raw is None or not raw.strip():
        return default
    return int(raw)


def _load_env() -> RunnerEnv:
    return RunnerEnv(
        launch_command=os.environ.get("PX4_GAZEBO_LAUNCH_COMMAND", "").strip(),
        workdir=os.environ.get("PX4_GAZEBO_WORKDIR") or None,
        timeout_seconds=max(1, _parse_int(os.environ.get("PX4_GAZEBO_TIMEOUT_SECONDS"), default=300)),
        headless=_parse_bool(os.environ.get("PX4_GAZEBO_HEADLESS"), default=True),
        keep_raw_logs=_parse_bool(os.environ.get("PX4_GAZEBO_KEEP_RAW_LOGS"), default=True),
        dry_run=_parse_bool(os.environ.get("PX4_GAZEBO_DRY_RUN"), default=False),
        pass_rmse=_parse_float(os.environ.get("PX4_GAZEBO_PASS_RMSE"), default=0.75),
        pass_max_error=_parse_float(os.environ.get("PX4_GAZEBO_PASS_MAX_ERROR"), default=2.0),
        min_track_coverage=_parse_float(os.environ.get("PX4_GAZEBO_MIN_TRACK_COVERAGE"), default=0.9),
        vehicle=os.environ.get("PX4_GAZEBO_VEHICLE", "").strip() or "x500",
        world=os.environ.get("PX4_GAZEBO_WORLD", "").strip() or "default",
        extra_args=os.environ.get("PX4_GAZEBO_EXTRA_ARGS", "").strip(),
        telemetry_format=os.environ.get("PX4_GAZEBO_TELEMETRY_FORMAT", "json").strip().lower() or "json",
        allow_csv_telemetry=_parse_bool(
            os.environ.get("PX4_GAZEBO_ALLOW_CSV_TELEMETRY"), default=False
        ),
        eval_altitude_fraction=_parse_float(
            os.environ.get("PX4_GAZEBO_EVAL_ALTITUDE_FRACTION"), default=0.9
        ),
        eval_near_track_threshold_m=_parse_float(
            os.environ.get("PX4_GAZEBO_EVAL_NEAR_TRACK_THRESHOLD_M"), default=1.5
        ),
        eval_consecutive_samples=max(
            1, _parse_int(os.environ.get("PX4_GAZEBO_EVAL_CONSECUTIVE_SAMPLES"), default=5)
        ),
        eval_collapse_altitude_fraction=_parse_float(
            os.environ.get("PX4_GAZEBO_EVAL_COLLAPSE_ALTITUDE_FRACTION"), default=0.5
        ),
    )


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="DroneDream PX4/Gazebo real_cli runner")
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    return parser.parse_args()


def _json_dump(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def _safe_excerpt(text: str, *, limit: int = 1800) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n... [truncated from {len(text)} chars]"


def _validate_trial_input(payload: dict[str, Any]) -> tuple[dict[str, Any], dict[str, float], dict[str, Any]]:
    required_ids = ("trial_id", "job_id", "candidate_id", "seed", "scenario_type")
    missing = [key for key in required_ids if key not in payload]
    if missing:
        raise RunnerError(f"trial_input missing required keys: {missing}")

    job_cfg_raw = payload.get("job_config") if isinstance(payload.get("job_config"), dict) else {}

    def _cfg_value(key: str) -> Any:
        if key in job_cfg_raw:
            return job_cfg_raw[key]
        return payload.get(key)

    track_type = _cfg_value("track_type")
    altitude_m = _cfg_value("altitude_m")
    start_point = _cfg_value("start_point")
    wind = _cfg_value("wind")
    sensor_noise_level = _cfg_value("sensor_noise_level")
    objective_profile = _cfg_value("objective_profile")
    reference_track_raw = _cfg_value("reference_track")

    if track_type not in {"circle", "u_turn", "lemniscate", "custom"}:
        raise RunnerError("track_type must be one of: circle, u_turn, lemniscate, custom")
    if not isinstance(start_point, dict):
        raise RunnerError("start_point must be an object with x/y")

    try:
        start_x = float(start_point.get("x"))
        start_y = float(start_point.get("y"))
        altitude = float(altitude_m)
    except (TypeError, ValueError):
        raise RunnerError("start_point.x/y and altitude_m must be numeric") from None

    if not isinstance(wind, dict):
        wind = {"north": 0.0, "east": 0.0, "south": 0.0, "west": 0.0}

    normalized_job_cfg = {
        "track_type": track_type,
        "start_point": {"x": start_x, "y": start_y},
        "altitude_m": altitude,
        "wind": {
            "north": float(wind.get("north", 0.0)),
            "east": float(wind.get("east", 0.0)),
            "south": float(wind.get("south", 0.0)),
            "west": float(wind.get("west", 0.0)),
        },
        "sensor_noise_level": str(sensor_noise_level or "medium"),
        "objective_profile": str(objective_profile or "robust"),
        "reference_track": [],
    }
    if reference_track_raw is not None:
        if not isinstance(reference_track_raw, list):
            raise RunnerError("reference_track must be an array when provided")
        normalized_points: list[dict[str, float]] = []
        for idx, point in enumerate(reference_track_raw):
            if not isinstance(point, dict):
                raise RunnerError(f"reference_track[{idx}] must be an object with x/y")
            try:
                x = float(point.get("x"))
                y = float(point.get("y"))
            except (TypeError, ValueError):
                raise RunnerError(f"reference_track[{idx}].x/y must be numeric") from None
            z_raw = point.get("z")
            try:
                z = float(altitude if z_raw is None else z_raw)
            except (TypeError, ValueError):
                raise RunnerError(f"reference_track[{idx}].z must be numeric when provided") from None
            normalized_points.append({"x": x, "y": y, "z": z})
        normalized_job_cfg["reference_track"] = normalized_points
    if track_type == "custom" and len(normalized_job_cfg["reference_track"]) < 2:
        raise RunnerError("custom track_type requires reference_track with at least 2 points")

    params_raw = payload.get("parameters") if isinstance(payload.get("parameters"), dict) else {}
    params: dict[str, float] = {}
    defaults = {
        "kp_xy": 1.0,
        "kd_xy": 0.2,
        "ki_xy": 0.05,
        "vel_limit": 5.0,
        "accel_limit": 4.0,
        "disturbance_rejection": 0.5,
    }
    for key in _REQUIRED_PARAM_KEYS:
        value = params_raw.get(key, defaults[key])
        try:
            params[key] = float(value)
        except (TypeError, ValueError):
            raise RunnerError(f"parameters.{key} must be numeric") from None
        if not math.isfinite(params[key]):
            raise RunnerError(f"parameters.{key} must be finite")

    meta = {
        "trial_id": str(payload["trial_id"]),
        "job_id": str(payload["job_id"]),
        "candidate_id": str(payload["candidate_id"]),
        "seed": int(payload["seed"]),
        "scenario_type": str(payload["scenario_type"]),
        "scenario_config": payload.get("scenario_config") if isinstance(payload.get("scenario_config"), dict) else {},
    }
    return normalized_job_cfg, params, meta


def _make_reference_track(
    track_type: str,
    start_x: float,
    start_y: float,
    altitude: float,
    reference_track: list[dict[str, float]] | None = None,
) -> list[dict[str, float]]:
    if track_type == "custom":
        return list(reference_track or [])
    points: list[dict[str, float]] = []
    if track_type == "circle":
        radius = 5.0
        n = 180
        for i in range(n + 1):
            theta = 2.0 * math.pi * (i / n)
            points.append({"x": start_x + radius * math.cos(theta), "y": start_y + radius * math.sin(theta), "z": altitude})
    elif track_type == "u_turn":
        lane_half = 5.0
        turn_radius = 3.0
        n_straight = 60
        n_arc = 60
        for i in range(n_straight):
            x = start_x - lane_half + (2 * lane_half) * (i / max(1, n_straight - 1))
            points.append({"x": x, "y": start_y, "z": altitude})
        cx, cy = start_x + lane_half, start_y + turn_radius
        for i in range(n_arc):
            theta = -math.pi / 2 + math.pi * (i / max(1, n_arc - 1))
            points.append({"x": cx + turn_radius * math.cos(theta), "y": cy + turn_radius * math.sin(theta), "z": altitude})
        for i in range(n_straight):
            x = start_x + lane_half - (2 * lane_half) * (i / max(1, n_straight - 1))
            points.append({"x": x, "y": start_y + 2 * turn_radius, "z": altitude})
    else:  # lemniscate
        a = 4.0
        n = 220
        for i in range(n + 1):
            t = 2 * math.pi * (i / n)
            denom = 1 + math.sin(t) ** 2
            x = start_x + (a * math.cos(t)) / denom
            y = start_y + (a * math.sin(t) * math.cos(t)) / denom
            points.append({"x": x, "y": y, "z": altitude})
    return points


def _wind_vec(wind: dict[str, float]) -> tuple[float, float]:
    return (float(wind.get("east", 0.0)) - float(wind.get("west", 0.0)), float(wind.get("north", 0.0)) - float(wind.get("south", 0.0)))


def _make_dry_run_telemetry(
    reference_track: list[dict[str, float]],
    params: dict[str, float],
    job_cfg: dict[str, Any],
    meta: dict[str, Any],
    env: RunnerEnv,
) -> dict[str, Any]:
    scenario_penalty = {
        "nominal": 0.0,
        "noise_perturbed": 0.25,
        "wind_perturbed": 0.35,
        "combined_perturbed": 0.55,
    }.get(meta["scenario_type"], 0.1)
    noise_penalty = {"low": 0.0, "medium": 0.05, "high": 0.12}.get(job_cfg["sensor_noise_level"], 0.06)

    base_err = (
        abs(params["kp_xy"] - 1.1) * 0.15
        + abs(params["kd_xy"] - 0.25) * 0.2
        + abs(params["ki_xy"] - 0.06) * 0.3
        + max(0.0, params["vel_limit"] - 6.0) * 0.04
        + max(0.0, params["accel_limit"] - 5.0) * 0.03
        + (1.0 - min(1.0, max(0.0, params["disturbance_rejection"]))) * 0.12
        + scenario_penalty
        + noise_penalty
    )

    wx, wy = _wind_vec(job_cfg["wind"])
    wobble_mag = min(1.8, 0.15 + base_err + (abs(wx) + abs(wy)) * 0.02)
    samples: list[dict[str, Any]] = []
    dt = 0.1
    for i, ref in enumerate(reference_track):
        theta = 2 * math.pi * i / max(1, len(reference_track) - 1)
        x = ref["x"] + wobble_mag * math.sin(theta * 2 + 0.3) + wx * 0.02
        y = ref["y"] + wobble_mag * math.cos(theta * 2 - 0.2) + wy * 0.02
        z = ref["z"]
        if meta["scenario_type"] == "combined_perturbed" and params["disturbance_rejection"] < 0.1:
            z = max(0.0, z - 0.015 * i)
        vx = (x - samples[-1]["x"]) / dt if samples else 0.0
        vy = (y - samples[-1]["y"]) / dt if samples else 0.0
        vz = (z - samples[-1]["z"]) / dt if samples else 0.0
        samples.append(
            {
                "t": round(i * dt, 4),
                "x": round(x, 6),
                "y": round(y, 6),
                "z": round(z, 6),
                "vx": round(vx, 6),
                "vy": round(vy, 6),
                "vz": round(vz, 6),
                "yaw": round(math.atan2(vy, vx) if i > 0 else 0.0, 6),
                "armed": True,
                "mode": "offboard",
                "crashed": z <= 0.1,
            }
        )

    return {
        "samples": samples,
        "meta": {
            "simulator": "px4_gazebo",
            "vehicle": env.vehicle,
            "world": env.world,
            "mode": "dry_run",
            "seed": meta["seed"],
        },
    }


def _normalize_samples(samples: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for idx, raw in enumerate(samples):
        try:
            s = {
                "t": float(raw["t"]),
                "x": float(raw["x"]),
                "y": float(raw["y"]),
                "z": float(raw["z"]),
                "vx": float(raw.get("vx", 0.0)),
                "vy": float(raw.get("vy", 0.0)),
                "vz": float(raw.get("vz", 0.0)),
                "yaw": float(raw.get("yaw", 0.0)),
                "armed": bool(raw.get("armed", True)),
                "mode": str(raw.get("mode", "unknown")),
                "crashed": bool(raw.get("crashed", False)),
            }
        except (KeyError, TypeError, ValueError):
            raise RunnerError(f"telemetry sample {idx} missing or invalid required fields") from None
        for key in ("t", "x", "y", "z", "vx", "vy", "vz", "yaw"):
            if not math.isfinite(s[key]):
                raise RunnerError(f"telemetry sample {idx} contains non-finite {key}")
        normalized.append(s)

    if not normalized:
        raise RunnerError("telemetry samples are empty")
    return normalized


def _load_telemetry(path: Path, *, allow_csv: bool) -> dict[str, Any]:
    if path.exists():
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise RunnerError(f"telemetry JSON is malformed: {exc}") from None
        if not isinstance(payload, dict) or not isinstance(payload.get("samples"), list):
            raise RunnerError("telemetry.json must contain an object with samples[]")
        payload["samples"] = _normalize_samples(payload["samples"])
        payload.setdefault("meta", {})
        return payload

    csv_path = path.with_suffix(".csv")
    if allow_csv and csv_path.exists():
        rows: list[dict[str, Any]] = []
        with csv_path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                rows.append(row)
        samples: list[dict[str, Any]] = []
        for row in rows:
            samples.append(
                {
                    "t": row.get("t", row.get("timestamp", 0.0)),
                    "x": row.get("x", 0.0),
                    "y": row.get("y", 0.0),
                    "z": row.get("z", 0.0),
                    "vx": row.get("vx", 0.0),
                    "vy": row.get("vy", 0.0),
                    "vz": row.get("vz", 0.0),
                    "yaw": row.get("yaw", 0.0),
                    "armed": row.get("armed", True),
                    "mode": row.get("mode", "unknown"),
                    "crashed": row.get("crashed", False),
                }
            )
        return {"samples": _normalize_samples(samples), "meta": {"format": "csv"}}

    raise RunnerError("telemetry output is missing")


def _nearest_error(sample: dict[str, Any], ref_points: list[dict[str, float]]) -> tuple[float, int]:
    best = float("inf")
    best_idx = 0
    sx, sy = sample["x"], sample["y"]
    for i, rp in enumerate(ref_points):
        d = math.hypot(sx - rp["x"], sy - rp["y"])
        if d < best:
            best, best_idx = d, i
    return best, best_idx


def _sample_meets_track_entry_condition(
    sample: dict[str, Any],
    ref_points: list[dict[str, float]],
    target_altitude: float,
    altitude_fraction: float,
    near_track_threshold: float,
) -> bool:
    if sample["z"] < altitude_fraction * target_altitude:
        return False
    err, _ = _nearest_error(sample, ref_points)
    return err <= near_track_threshold


def _first_consecutive_index(
    samples: list[dict[str, Any]],
    start_idx: int,
    end_idx: int,
    predicate: Callable[[dict[str, Any]], bool],
    consecutive_count: int,
) -> int | None:
    count = 0
    run_start: int | None = None
    for i in range(start_idx, end_idx + 1):
        if predicate(samples[i]):
            if count == 0:
                run_start = i
            count += 1
            if count >= consecutive_count:
                return run_start
        else:
            count = 0
            run_start = None
    return None


def _last_before_landing_index(
    samples: list[dict[str, Any]],
    start_idx: int,
    end_idx: int,
    target_altitude: float,
    altitude_fraction: float,
    consecutive_count: int,
) -> int:
    threshold = altitude_fraction * target_altitude
    count = 0
    run_start: int | None = None
    for i in range(start_idx + 1, end_idx + 1):
        if samples[i]["z"] < threshold:
            if count == 0:
                run_start = i
            count += 1
            if count >= consecutive_count and run_start is not None:
                return max(start_idx, run_start - 1)
        else:
            count = 0
            run_start = None
    return end_idx


def _refine_candidate_window(
    samples: list[dict[str, Any]],
    reference_track: list[dict[str, float]],
    raw_start_idx: int,
    raw_end_idx: int,
    *,
    raw_source: str,
    target_altitude: float,
    altitude_fraction: float,
    near_track_threshold: float,
    consecutive_samples: int,
) -> EvaluationWindow | None:
    raw_start_idx = max(0, raw_start_idx)
    raw_end_idx = min(len(samples) - 1, raw_end_idx)
    if raw_end_idx <= raw_start_idx:
        return None
    refined_start = _first_consecutive_index(
        samples,
        raw_start_idx,
        raw_end_idx,
        lambda sample: _sample_meets_track_entry_condition(
            sample,
            reference_track,
            target_altitude,
            altitude_fraction,
            near_track_threshold,
        ),
        consecutive_samples,
    )
    if refined_start is None:
        return None
    refined_end = _last_before_landing_index(
        samples,
        refined_start,
        raw_end_idx,
        target_altitude,
        altitude_fraction,
        consecutive_samples,
    )
    if refined_end <= refined_start:
        return None
    return EvaluationWindow(
        start_idx=refined_start,
        end_idx=refined_end,
        source=f"{raw_source}_refined",
        raw_source=raw_source,
        raw_start_t=float(samples[raw_start_idx]["t"]),
        raw_end_t=float(samples[raw_end_idx]["t"]),
        start_reason="altitude_and_near_track",
        trimmed_takeoff_samples=refined_start - raw_start_idx,
        trimmed_landing_samples=raw_end_idx - refined_end,
    )


def _find_eval_window_from_timing(
    samples: list[dict[str, Any]],
    reference_track: list[dict[str, float]],
    timing: dict[str, Any],
    *,
    target_altitude: float,
    altitude_fraction: float,
    near_track_threshold: float,
    consecutive_samples: int,
) -> EvaluationWindow | None:
    start_t_raw = timing.get("track_start_t")
    end_t_raw = timing.get("track_end_t")
    if not isinstance(start_t_raw, (int, float)) or not isinstance(end_t_raw, (int, float)):
        return None
    start_t = float(start_t_raw)
    end_t = float(end_t_raw)
    if (not math.isfinite(start_t)) or (not math.isfinite(end_t)) or end_t <= start_t:
        return None

    idx_start = next((i for i, s in enumerate(samples) if s["t"] >= start_t), None)
    idx_end = next((i for i, s in enumerate(samples) if s["t"] >= end_t), None)
    if idx_start is None or idx_end is None:
        return None
    if idx_end <= idx_start:
        return None
    return _refine_candidate_window(
        samples,
        reference_track,
        idx_start,
        idx_end,
        raw_source="offboard_timing",
        target_altitude=target_altitude,
        altitude_fraction=altitude_fraction,
        near_track_threshold=near_track_threshold,
        consecutive_samples=consecutive_samples,
    )


def _find_eval_window_from_telemetry(
    samples: list[dict[str, Any]],
    reference_track: list[dict[str, float]],
    *,
    target_altitude: float,
    altitude_fraction: float,
    near_track_threshold: float,
    consecutive_samples: int,
) -> EvaluationWindow | None:
    raw_start_idx = 0
    raw_end_idx = len(samples) - 1
    start_idx = _first_consecutive_index(
        samples,
        raw_start_idx,
        raw_end_idx,
        lambda sample: _sample_meets_track_entry_condition(
            sample,
            reference_track,
            target_altitude,
            altitude_fraction,
            near_track_threshold,
        ),
        consecutive_samples,
    )
    if start_idx is None:
        return None
    end_idx = _last_before_landing_index(
        samples,
        start_idx,
        raw_end_idx,
        target_altitude,
        altitude_fraction,
        consecutive_samples,
    )
    if end_idx <= start_idx:
        return None
    return EvaluationWindow(
        start_idx=start_idx,
        end_idx=end_idx,
        source="telemetry_derived_refined",
        raw_source="telemetry_derived",
        raw_start_t=None,
        raw_end_t=None,
        start_reason="altitude_and_near_track",
        trimmed_takeoff_samples=start_idx - raw_start_idx,
        trimmed_landing_samples=raw_end_idx - end_idx,
    )


def _find_altitude_only_window(
    samples: list[dict[str, Any]],
    reference_track: list[dict[str, float]],
    *,
    target_altitude: float,
    altitude_fraction: float,
    consecutive_samples: int,
) -> EvaluationWindow | None:
    raw_start_idx = 0
    raw_end_idx = len(samples) - 1
    threshold = altitude_fraction * target_altitude
    start_idx = _first_consecutive_index(
        samples,
        raw_start_idx,
        raw_end_idx,
        lambda sample: sample["z"] >= threshold,
        consecutive_samples,
    )
    if start_idx is None:
        return None
    end_idx = _last_before_landing_index(
        samples,
        start_idx,
        raw_end_idx,
        target_altitude,
        altitude_fraction,
        consecutive_samples,
    )
    if end_idx <= start_idx:
        return None
    return EvaluationWindow(
        start_idx=start_idx,
        end_idx=end_idx,
        source="altitude_only_refined",
        raw_source="altitude_only",
        raw_start_t=None,
        raw_end_t=None,
        start_reason="altitude_only",
        trimmed_takeoff_samples=start_idx - raw_start_idx,
        trimmed_landing_samples=raw_end_idx - end_idx,
    )


def _compute_metrics(
    telemetry: dict[str, Any],
    reference_track: list[dict[str, float]],
    job_cfg: dict[str, Any],
    env: RunnerEnv,
    *,
    timeout_flag: bool,
    dry_run: bool,
) -> dict[str, Any]:
    samples = telemetry["samples"]
    target_altitude = float(reference_track[0]["z"])
    altitude_fraction = env.eval_altitude_fraction
    near_track_threshold = env.eval_near_track_threshold_m
    consecutive_samples = env.eval_consecutive_samples
    total_sample_count = len(samples)

    offboard_timing_path = Path(str(telemetry.get("meta", {}).get("offboard_timing_path", ""))).expanduser()
    offboard_timing: dict[str, Any] | None = None
    if offboard_timing_path and offboard_timing_path.exists():
        try:
            loaded = json.loads(offboard_timing_path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                offboard_timing = loaded
        except Exception:
            offboard_timing = None

    eval_window: EvaluationWindow | None = None
    if offboard_timing is not None:
        eval_window = _find_eval_window_from_timing(
            samples,
            reference_track,
            offboard_timing,
            target_altitude=target_altitude,
            altitude_fraction=altitude_fraction,
            near_track_threshold=near_track_threshold,
            consecutive_samples=consecutive_samples,
        )
    if eval_window is None:
        eval_window = _find_eval_window_from_telemetry(
            samples,
            reference_track,
            target_altitude=target_altitude,
            altitude_fraction=altitude_fraction,
            near_track_threshold=near_track_threshold,
            consecutive_samples=consecutive_samples,
        )
    if eval_window is None:
        eval_window = _find_altitude_only_window(
            samples,
            reference_track,
            target_altitude=target_altitude,
            altitude_fraction=altitude_fraction,
            consecutive_samples=consecutive_samples,
        )
    if eval_window is None:
        eval_window = EvaluationWindow(
            start_idx=0,
            end_idx=len(samples) - 1,
            source="all_samples_fallback",
            raw_source="all_samples_fallback",
            raw_start_t=None,
            raw_end_t=None,
            start_reason="all_samples_fallback",
            trimmed_takeoff_samples=0,
            trimmed_landing_samples=0,
        )

    evaluation_samples = samples[eval_window.start_idx : eval_window.end_idx + 1]

    errors: list[float] = []
    ref_hits: set[int] = set()
    eval_errors: list[float] = []
    eval_ref_hits: set[int] = set()
    radial_errors: list[float] = []
    center_x = job_cfg["start_point"]["x"]
    center_y = job_cfg["start_point"]["y"]

    for s in samples:
        err, idx = _nearest_error(s, reference_track)
        errors.append(err)
        ref_hits.add(idx)
        radial_errors.append(math.hypot(s["x"] - center_x, s["y"] - center_y))
    for s in evaluation_samples:
        err, idx = _nearest_error(s, reference_track)
        eval_errors.append(err)
        eval_ref_hits.add(idx)

    rmse = math.sqrt(sum(e * e for e in eval_errors) / len(eval_errors))
    max_error = max(eval_errors)
    max_error_idx = eval_errors.index(max_error)
    completion_time = max(0.0, evaluation_samples[-1]["t"] - evaluation_samples[0]["t"])
    final_ref = reference_track[-1]
    final_error = math.hypot(evaluation_samples[-1]["x"] - final_ref["x"], evaluation_samples[-1]["y"] - final_ref["y"])

    overshoot_count = 0
    for i in range(2, len(radial_errors)):
        a = radial_errors[i - 2]
        b = radial_errors[i - 1]
        c = radial_errors[i]
        if (b > a and b > c and b - max(a, c) > 0.25) or (b < a and b < c and min(a, c) - b > 0.25):
            overshoot_count += 1

    if eval_window.source == "all_samples_fallback":
        crash_flag = any(bool(s.get("crashed", False)) for s in samples)
        crash_reason = "telemetry_crashed_flag" if crash_flag else "none"
        if not crash_flag and job_cfg["altitude_m"] > 0.5:
            crash_flag = min(s["z"] for s in samples) < 0.2
            crash_reason = "all_samples_fallback_low_altitude" if crash_flag else "none"
    else:
        crash_flag = any(bool(s.get("crashed", False)) for s in evaluation_samples)
        crash_reason = "telemetry_crashed_flag" if crash_flag else "none"
        collapse_threshold = max(0.2, env.eval_collapse_altitude_fraction * target_altitude)
        stable_threshold = altitude_fraction * target_altitude
        stable_altitude_seen = any(s["z"] >= stable_threshold for s in evaluation_samples)
        if not crash_flag and stable_altitude_seen and len(evaluation_samples) > consecutive_samples:
            first_check_idx = consecutive_samples
            run = 0
            for i in range(first_check_idx, len(evaluation_samples)):
                if evaluation_samples[i]["z"] < collapse_threshold:
                    run += 1
                    if run >= consecutive_samples:
                        crash_flag = True
                        crash_reason = "altitude_collapse_in_evaluation_window"
                        break
                else:
                    run = 0

    instability_flag = False
    instability_series = samples if eval_window.source == "all_samples_fallback" else evaluation_samples
    for i in range(1, len(instability_series)):
        dt = max(1e-6, instability_series[i]["t"] - instability_series[i - 1]["t"])
        jump = math.hypot(
            instability_series[i]["x"] - instability_series[i - 1]["x"],
            instability_series[i]["y"] - instability_series[i - 1]["y"],
        )
        if jump / dt > 25.0:
            instability_flag = True
            break
    if max_error > 30.0:
        instability_flag = True

    track_coverage = len(ref_hits) / max(1, len(reference_track))
    evaluation_track_coverage = len(eval_ref_hits) / max(1, len(reference_track))
    pass_flag = (
        (not crash_flag)
        and (not timeout_flag)
        and (not instability_flag)
        and rmse <= env.pass_rmse
        and max_error <= env.pass_max_error
        and evaluation_track_coverage >= env.min_track_coverage
    )

    penalty = 0.0
    if crash_flag:
        penalty += 100.0
    if timeout_flag:
        penalty += 120.0
    if instability_flag:
        penalty += 80.0
    if evaluation_track_coverage < env.min_track_coverage:
        penalty += 20.0
    score = rmse + (0.5 * max_error) + (0.05 * completion_time) + penalty

    return {
        "rmse": round(rmse, 6),
        "max_error": round(max_error, 6),
        "overshoot_count": int(overshoot_count),
        "completion_time": round(completion_time, 6),
        "crash_flag": crash_flag,
        "timeout_flag": timeout_flag,
        "score": round(score, 6),
        "final_error": round(final_error, 6),
        "pass_flag": pass_flag,
        "instability_flag": instability_flag,
        "raw_metric_json": {
            "simulator": "px4_gazebo",
            "track_coverage": round(track_coverage, 6),
            "evaluation_track_coverage": round(evaluation_track_coverage, 6),
            "full_log_rmse": round(math.sqrt(sum(e * e for e in errors) / len(errors)), 6),
            "full_log_max_error": round(max(errors), 6),
            "pass_thresholds": {
                "rmse": env.pass_rmse,
                "max_error": env.pass_max_error,
                "min_track_coverage": env.min_track_coverage,
            },
            "evaluation_window_source": eval_window.source,
            "evaluation_window_raw_source": eval_window.raw_source,
            "raw_track_start_t": (
                round(float(eval_window.raw_start_t), 6) if eval_window.raw_start_t is not None else None
            ),
            "raw_track_end_t": (
                round(float(eval_window.raw_end_t), 6) if eval_window.raw_end_t is not None else None
            ),
            "evaluation_start_t": round(float(evaluation_samples[0]["t"]), 6),
            "evaluation_end_t": round(float(evaluation_samples[-1]["t"]), 6),
            "evaluation_sample_count": len(evaluation_samples),
            "total_sample_count": total_sample_count,
            "evaluation_start_reason": eval_window.start_reason,
            "evaluation_trimmed_takeoff_samples": eval_window.trimmed_takeoff_samples,
            "evaluation_trimmed_landing_samples": eval_window.trimmed_landing_samples,
            "evaluation_min_z": round(min(s["z"] for s in evaluation_samples), 6),
            "evaluation_max_z": round(max(s["z"] for s in evaluation_samples), 6),
            "evaluation_max_error_sample": {
                "t": round(float(evaluation_samples[max_error_idx]["t"]), 6),
                "x": round(float(evaluation_samples[max_error_idx]["x"]), 6),
                "y": round(float(evaluation_samples[max_error_idx]["y"]), 6),
                "z": round(float(evaluation_samples[max_error_idx]["z"]), 6),
                "error": round(float(max_error), 6),
            },
            "crash_reason": crash_reason,
            "mode": "dry_run" if dry_run else "real",
            "vehicle": env.vehicle,
            "world": env.world,
        },
    }


def _write_trajectory_json(telemetry: dict[str, Any], path: Path) -> None:
    samples = telemetry["samples"]
    simplified = [{"t": s["t"], "x": s["x"], "y": s["y"], "z": s["z"]} for s in samples]
    _json_dump(path, {"samples": simplified})


def _artifact_record(path: Path, artifact_type: str, display_name: str, mime_type: str) -> dict[str, Any]:
    if not path.exists():
        return {}
    return {
        "artifact_type": artifact_type,
        "display_name": display_name,
        "storage_path": str(path),
        "mime_type": mime_type,
        "file_size_bytes": path.stat().st_size,
    }


def _command_is_executable(command: str) -> bool:
    argv = shlex.split(command)
    if not argv:
        return False
    first = argv[0]
    if os.path.isabs(first) or first.startswith("."):
        return Path(first).exists() and os.access(first, os.X_OK)
    return shutil.which(first) is not None


def _build_launch_argv(command_template: str, values: dict[str, str]) -> list[str]:
    has_token = any("{" + token + "}" in command_template for token in _TEMPLATE_TOKENS)
    if has_token:
        rendered = command_template
        for token, value in values.items():
            rendered = rendered.replace("{" + token + "}", value)
        return shlex.split(rendered)

    argv = shlex.split(command_template)
    argv.extend(
        [
            "--input",
            values["trial_input"],
            "--output",
            values["trial_output"],
            "--params",
            values["params_json"],
            "--track",
            values["track_json"],
            "--telemetry",
            values["telemetry_json"],
        ]
    )
    return argv


def _run_lower_level_launcher(
    env: RunnerEnv,
    *,
    launch_argv: list[str],
    cwd: Path,
    stdout_log: Path,
    stderr_log: Path,
) -> int:
    with stdout_log.open("w", encoding="utf-8") as out, stderr_log.open("w", encoding="utf-8") as err:
        proc = subprocess.Popen(  # noqa: S603
            launch_argv,
            cwd=str(cwd),
            stdout=out,
            stderr=err,
            text=True,
            start_new_session=True,
        )
        try:
            return proc.wait(timeout=env.timeout_seconds)
        except subprocess.TimeoutExpired as exc:
            try:
                os.killpg(proc.pid, signal.SIGTERM)
            except OSError:
                pass
            time.sleep(0.2)
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except OSError:
                pass
            raise TimeoutRunnerError(f"lower-level launcher timed out after {env.timeout_seconds}s") from exc


def _failure_result(reason: str, code: str, artifacts: list[dict[str, Any]], log_excerpt: str) -> dict[str, Any]:
    return {
        "success": False,
        "failure": {"code": code, "reason": reason},
        "artifacts": artifacts,
        "log_excerpt": _safe_excerpt(log_excerpt),
    }


def _collect_artifacts(run_dir: Path) -> list[dict[str, Any]]:
    records = [
        _artifact_record(run_dir / "telemetry.json", "telemetry_json", "Telemetry", "application/json"),
        _artifact_record(run_dir / "trajectory.json", "trajectory_json", "Trajectory Samples", "application/json"),
        _artifact_record(run_dir / "runner.log", "worker_log", "Runner Log", "text/plain"),
        _artifact_record(run_dir / "stdout.log", "simulator_stdout", "Simulator stdout", "text/plain"),
        _artifact_record(run_dir / "stderr.log", "simulator_stderr", "Simulator stderr", "text/plain"),
        _artifact_record(
            run_dir / "offboard_executor.log",
            "offboard_executor_log",
            "Offboard Executor Log",
            "text/plain",
        ),
        _artifact_record(
            run_dir / "offboard_timing.json",
            "offboard_timing_json",
            "Offboard Timing",
            "application/json",
        ),
        _artifact_record(
            run_dir / "gui_stdout.log",
            "gazebo_gui_stdout_log",
            "Gazebo GUI stdout",
            "text/plain",
        ),
        _artifact_record(
            run_dir / "gui_stderr.log",
            "gazebo_gui_stderr_log",
            "Gazebo GUI stderr",
            "text/plain",
        ),
        _artifact_record(
            run_dir / "track_marker_stdout.log",
            "gazebo_track_marker_stdout_log",
            "Gazebo Track Marker stdout",
            "text/plain",
        ),
        _artifact_record(
            run_dir / "track_marker_stderr.log",
            "gazebo_track_marker_stderr_log",
            "Gazebo Track Marker stderr",
            "text/plain",
        ),
    ]
    return [r for r in records if r]


def run_once(input_path: Path, output_path: Path) -> int:
    env = _load_env()
    run_dir = output_path.parent
    run_dir.mkdir(parents=True, exist_ok=True)

    runner_log = run_dir / "runner.log"
    stdout_log = run_dir / "stdout.log"
    stderr_log = run_dir / "stderr.log"
    telemetry_json = run_dir / "telemetry.json"
    trajectory_json = run_dir / "trajectory.json"
    params_json = run_dir / "controller_params.json"
    track_json = run_dir / "reference_track.json"

    def log(msg: str) -> None:
        with runner_log.open("a", encoding="utf-8") as f:
            f.write(msg + "\n")

    try:
        payload = json.loads(input_path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise RunnerError("trial_input must be a JSON object")

        job_cfg, params, meta = _validate_trial_input(payload)

        reference_track = _make_reference_track(
            job_cfg["track_type"],
            job_cfg["start_point"]["x"],
            job_cfg["start_point"]["y"],
            job_cfg["altitude_m"],
            job_cfg.get("reference_track"),
        )
        _json_dump(
            track_json,
            {
                "track_type": job_cfg["track_type"],
                "points": reference_track,
                "reference_track": reference_track,
            },
        )
        _json_dump(params_json, params)

        timeout_flag = False
        if env.dry_run:
            telemetry = _make_dry_run_telemetry(reference_track, params, job_cfg, meta, env)
            _json_dump(telemetry_json, telemetry)
            stdout_log.write_text("dry-run mode: no external launcher executed\n", encoding="utf-8")
            stderr_log.write_text("", encoding="utf-8")
            log("PX4_GAZEBO_DRY_RUN=true; generated deterministic fixture telemetry")
        else:
            if not env.launch_command:
                result = _failure_result(
                    "PX4_GAZEBO_LAUNCH_COMMAND not configured",
                    FAILURE_ADAPTER_UNAVAILABLE,
                    _collect_artifacts(run_dir),
                    "PX4_GAZEBO_LAUNCH_COMMAND missing in non-dry-run mode",
                )
                _json_dump(output_path, result)
                return 0
            if not _command_is_executable(env.launch_command):
                result = _failure_result(
                    "PX4_GAZEBO_LAUNCH_COMMAND is not executable",
                    FAILURE_ADAPTER_UNAVAILABLE,
                    _collect_artifacts(run_dir),
                    f"command not executable: {env.launch_command}",
                )
                _json_dump(output_path, result)
                return 0

            values = {
                "run_dir": str(run_dir),
                "trial_input": str(input_path),
                "trial_output": str(output_path),
                "params_json": str(params_json),
                "track_json": str(track_json),
                "telemetry_json": str(telemetry_json),
                "trajectory_json": str(trajectory_json),
                "stdout_log": str(stdout_log),
                "stderr_log": str(stderr_log),
                "job_id": meta["job_id"],
                "trial_id": meta["trial_id"],
                "candidate_id": meta["candidate_id"],
                "seed": str(meta["seed"]),
                "scenario_type": meta["scenario_type"],
                "vehicle": env.vehicle,
                "world": env.world,
                "headless": "true" if env.headless else "false",
                "extra_args": env.extra_args,
            }
            argv = _build_launch_argv(env.launch_command, values)
            cwd = Path(env.workdir) if env.workdir else run_dir
            log(f"launch argv: {argv}")
            log(f"launch cwd: {cwd}")
            try:
                exit_code = _run_lower_level_launcher(
                    env,
                    launch_argv=argv,
                    cwd=cwd,
                    stdout_log=stdout_log,
                    stderr_log=stderr_log,
                )
            except TimeoutRunnerError as exc:
                timeout_flag = True
                result = _failure_result(
                    str(exc),
                    FAILURE_TIMEOUT,
                    _collect_artifacts(run_dir),
                    str(exc),
                )
                _json_dump(output_path, result)
                return 0
            log(f"launcher exit code: {exit_code}")

        telemetry = _load_telemetry(telemetry_json, allow_csv=env.allow_csv_telemetry)
        telemetry.setdefault("meta", {})
        telemetry["meta"]["offboard_timing_path"] = str(run_dir / "offboard_timing.json")
        _write_trajectory_json(telemetry, trajectory_json)

        metrics = _compute_metrics(
            telemetry,
            reference_track,
            job_cfg,
            env,
            timeout_flag=timeout_flag,
            dry_run=env.dry_run,
        )

        result = {
            "success": True,
            "metrics": metrics,
            "artifacts": _collect_artifacts(run_dir),
            "log_excerpt": (
                f"px4_gazebo_runner mode={'dry_run' if env.dry_run else 'real'} "
                f"trial={meta['trial_id']} rmse={metrics['rmse']} score={metrics['score']}"
            ),
        }
        _json_dump(output_path, result)
        return 0
    except RunnerError as exc:
        log(f"RunnerError: {exc}")
        result = _failure_result(
            str(exc),
            FAILURE_SIMULATION,
            _collect_artifacts(run_dir),
            f"px4_gazebo_runner simulation failure: {exc}",
        )
        _json_dump(output_path, result)
        return 0
    except Exception as exc:  # pragma: no cover - defensive guardrail
        try:
            log(f"Unexpected exception: {exc!r}")
            result = _failure_result(
                f"Unexpected runner exception: {exc}",
                FAILURE_SIMULATION,
                _collect_artifacts(run_dir),
                f"Unexpected exception: {exc}",
            )
            _json_dump(output_path, result)
            return 0
        except Exception:
            print(f"[px4_gazebo_runner] fatal crash: {exc}", file=sys.stderr)
            return 2


def main() -> int:
    args = _parse_args()
    return run_once(args.input, args.output)


if __name__ == "__main__":
    raise SystemExit(main())
