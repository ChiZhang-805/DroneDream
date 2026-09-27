#!/usr/bin/env python3
"""Example external simulator driver for the ``real_cli`` adapter.

This is deliberately NOT the mock backend. Its job is to exercise the
subprocess path end-to-end: read ``trial_input.json``, compute a simple
deterministic pseudo-trajectory based on the candidate's parameters +
scenario, and write ``trial_result.json`` in the schema the adapter expects.

Usage::

    python scripts/simulators/example_real_simulator.py \\
        --input /path/to/trial_input.json \\
        --output /path/to/trial_result.json

Exit code 0 on success, non-zero on invocation errors. Structured
simulation failures are written to the output file with ``"success": false``.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

_SCENARIO_PENALTY = {
    "nominal": 0.00,
    "noise_perturbed": 0.18,
    "wind_perturbed": 0.25,
    "combined_perturbed": 0.42,
}

_NOISE_PENALTY = {"low": 0.00, "medium": 0.05, "high": 0.12}
_MAX_INPUT_BYTES = 16 * 1024 * 1024
_MAX_INJECTED_SLEEP_SECONDS = 3600.0


class ExampleSimulatorError(ValueError):
    """Invalid invocation or trial payload supplied to the example simulator."""


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="DroneDream example real simulator")
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    return parser.parse_args()


def _require_object(value: object, *, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ExampleSimulatorError(f"{label} must be a JSON object")
    return value


def _finite_float(value: Any, *, label: str) -> float:
    if isinstance(value, bool):
        raise ExampleSimulatorError(f"{label} must be a finite number")
    try:
        normalized = float(value)
    except (TypeError, ValueError):
        raise ExampleSimulatorError(f"{label} must be a finite number") from None
    if not math.isfinite(normalized):
        raise ExampleSimulatorError(f"{label} must be a finite number")
    return normalized


def _emit_artifacts(
    payload: dict[str, Any],
    run_dir: Path,
    metrics: dict[str, Any],
) -> list[dict[str, Any]]:
    """Write per-trial artifact files next to ``trial_result.json``.

    These are the files the DroneDream UI surfaces on Trial Detail as real
    trial-level artifacts (owner_type="trial"). Writing them here proves the
    subprocess path persists real files, not mock placeholders.
    """

    run_dir.mkdir(parents=True, exist_ok=True)
    trial_id = str(payload.get("trial_id", "unknown_trial"))
    scenario = payload.get("scenario_type", "nominal")
    job_config = payload.get("job_config")
    altitude = (
        _finite_float(job_config.get("altitude_m", 3.0), label="job_config.altitude_m")
        if isinstance(job_config, dict)
        else 3.0
    )
    telemetry_samples = [
        {
            "t": round(i * 0.1, 2),
            "x": round(i * 0.05, 3),
            "y": round(i * 0.05, 3),
            "z": altitude,
        }
        for i in range(0, 20)
    ]

    telem_path = run_dir / "telemetry.json"
    with telem_path.open("w", encoding="utf-8") as f:
        json.dump(
            {
                "schema_version": "dronedream.telemetry.v1",
                "trial_id": trial_id,
                "samples": telemetry_samples,
                "meta": {
                    "scenario": scenario,
                    "parameters": payload.get("parameters", {}),
                },
            },
            f,
            indent=2,
            sort_keys=True,
        )

    traj_path = run_dir / "trajectory.json"
    # Minimal deterministic trajectory — enough to prove the file exists.
    # A real wrapper would write a real trajectory file / PNG.
    samples = [
        {"t": sample["t"], "x": sample["x"], "y": sample["y"]} for sample in telemetry_samples
    ]
    with traj_path.open("w", encoding="utf-8") as f:
        json.dump({"trial_id": trial_id, "samples": samples}, f, indent=2, sort_keys=True)

    log_path = run_dir / "worker.log"
    with log_path.open("w", encoding="utf-8") as f:
        f.write(
            f"[example_real_simulator] trial={trial_id} scenario={scenario}\n"
            f"rmse={metrics.get('rmse')} score={metrics.get('score')} "
            f"pass_flag={metrics.get('pass_flag')}\n"
        )

    return [
        {
            "artifact_type": "trajectory_plot",
            "display_name": "Trajectory (samples)",
            "storage_path": str(traj_path),
            "mime_type": "application/json",
            "file_size_bytes": traj_path.stat().st_size,
        },
        {
            "artifact_type": "telemetry_json",
            "display_name": "Telemetry",
            "storage_path": str(telem_path),
            "mime_type": "application/json",
            "file_size_bytes": telem_path.stat().st_size,
        },
        {
            "artifact_type": "worker_log",
            "display_name": "Worker log",
            "storage_path": str(log_path),
            "mime_type": "text/plain",
            "file_size_bytes": log_path.stat().st_size,
        },
    ]


def _compute_metrics(payload: dict[str, Any]) -> dict[str, Any]:
    params = _require_object(payload.get("parameters", {}), label="parameters")
    # The canonical grouped object is ``job_config``; top-level aliases
    # (``track_type``, ``altitude_m``, ``wind``, ``start_point``,
    # ``sensor_noise_level``, ``objective_profile``) mirror the same values
    # for wrapper authors who prefer the flat shape. This reference
    # implementation prefers ``job_config`` and falls back to top-level.
    raw_job = payload.get("job_config")
    job: dict[str, Any]
    if raw_job is None:
        job = {
            k: payload[k]
            for k in (
                "track_type",
                "altitude_m",
                "reference_track",
                "wind",
                "start_point",
                "sensor_noise_level",
                "objective_profile",
            )
            if k in payload
        }
    else:
        job = _require_object(raw_job, label="job_config")
    scenario = payload.get("scenario_type", "nominal")
    if not isinstance(scenario, str):
        raise ExampleSimulatorError("scenario_type must be a string")
    scenario_config = _require_object(payload.get("scenario_config", {}), label="scenario_config")

    # Controlled failure injection for tests.
    inject = scenario_config.get("inject_failure") if isinstance(scenario_config, dict) else None
    if isinstance(params.get("inject_failure"), str):
        inject = params["inject_failure"]
    if isinstance(inject, str):
        inject = inject.strip().lower()
        if inject == "sleep":
            sleep_seconds = _finite_float(
                scenario_config.get("sleep_seconds", 30),
                label="scenario_config.sleep_seconds",
            )
            if not 0.0 <= sleep_seconds <= _MAX_INJECTED_SLEEP_SECONDS:
                raise ExampleSimulatorError(
                    "scenario_config.sleep_seconds must be between "
                    f"0 and {_MAX_INJECTED_SLEEP_SECONDS:g}"
                )
            time.sleep(sleep_seconds)
        if inject in {"timeout", "simulation_failed", "unstable"}:
            return {
                "success": False,
                "failure": {
                    "code": (
                        "TIMEOUT"
                        if inject == "timeout"
                        else "SIMULATION_FAILED"
                        if inject == "simulation_failed"
                        else "UNSTABLE_CANDIDATE"
                    ),
                    "reason": f"example_real_simulator injected {inject}",
                },
                "artifacts": [],
                "log_excerpt": f"[example_real_simulator] injected {inject}",
            }
        if inject == "malformed":
            return {"success": True, "garbage": True}

    kp = _finite_float(params.get("kp_xy", 1.0), label="parameters.kp_xy")
    kd = _finite_float(params.get("kd_xy", 0.2), label="parameters.kd_xy")
    ki = _finite_float(params.get("ki_xy", 0.05), label="parameters.ki_xy")
    disturbance = max(
        0.0,
        min(
            1.0,
            _finite_float(
                params.get("disturbance_rejection", 0.5),
                label="parameters.disturbance_rejection",
            ),
        ),
    )
    noise_level = str(job.get("sensor_noise_level", "medium"))

    base = (
        abs(kp - 1.2) * 0.30
        + abs(kd - 0.30) * 0.20
        + abs(ki - 0.05) * 0.50
        + (1.0 - disturbance) * 0.10
        + 0.30
    )
    scenario_factor = 1.0 + _SCENARIO_PENALTY.get(scenario, 0.0)
    noise_factor = 1.0 + _NOISE_PENALTY.get(noise_level, 0.0)

    rmse = round(base * scenario_factor * noise_factor, 4)
    max_error = round(rmse * 1.6, 4)
    completion_time = round(10.0 + rmse * 2.0, 3)
    overshoot_count = int(math.floor(rmse * 2.0))
    score = round(rmse * 1.0 + max_error * 0.5 + completion_time * 0.05, 4)

    return {
        "success": True,
        "metrics": {
            "rmse": rmse,
            "max_error": max_error,
            "overshoot_count": overshoot_count,
            "completion_time": completion_time,
            "crash_flag": False,
            "timeout_flag": False,
            "score": score,
            "final_error": round(rmse * 0.6, 4),
            "pass_flag": rmse < 0.5,
            "instability_flag": False,
            "raw_metric_json": {
                "simulator": "example_real_simulator",
                "scenario": scenario,
                "seed": payload.get("seed"),
            },
        },
        "artifacts": [],
        "log_excerpt": (
            f"[example_real_simulator] scenario={scenario} kp={kp} kd={kd} ki={ki} "
            f"rmse={rmse} score={score}"
        ),
    }


def _read_input(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise ExampleSimulatorError(f"input file does not exist: {path}")
    try:
        if path.stat().st_size > _MAX_INPUT_BYTES:
            raise ExampleSimulatorError(f"input file exceeds {_MAX_INPUT_BYTES} bytes")
        with path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except ExampleSimulatorError:
        raise
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ExampleSimulatorError(f"cannot read input: {exc}") from exc
    return _require_object(payload, label="trial input")


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".partial",
            delete=False,
        ) as handle:
            temporary_path = Path(handle.name)
            json.dump(payload, handle, indent=2, sort_keys=True, allow_nan=False)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
        temporary_path = None
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def main() -> int:
    args = _parse_args()
    try:
        if args.input.resolve(strict=False) == args.output.resolve(strict=False):
            raise ExampleSimulatorError("input and output paths must be different")
        payload = _read_input(args.input)
        result = _compute_metrics(payload)
    except ExampleSimulatorError as exc:
        print(f"[example_real_simulator] invalid input: {exc}", file=sys.stderr)
        return 2
    identity = payload.get("execution_identity")
    if isinstance(identity, dict):
        result["schema_version"] = "dronedream.trial_result.v2"
        result["execution_identity"] = dict(identity)
    # Emit per-trial artifact files for successful trials. Failure paths
    # (``success=False``) intentionally skip this so the adapter's error
    # reporting stays the salient signal.
    if result.get("success") and isinstance(result.get("metrics"), dict):
        try:
            result["artifacts"] = _emit_artifacts(payload, args.output.parent, result["metrics"])
        except (OSError, ExampleSimulatorError) as exc:
            print(
                f"[example_real_simulator] cannot write artifacts: {exc}",
                file=sys.stderr,
            )
            return 2
    try:
        _atomic_write_json(args.output, result)
    except (OSError, TypeError, ValueError) as exc:
        print(f"[example_real_simulator] cannot write output: {exc}", file=sys.stderr)
        return 2
    return 0 if os.environ.get("EXAMPLE_SIM_EXIT_NONZERO") != "1" else 3


if __name__ == "__main__":  # pragma: no cover — CLI entry
    raise SystemExit(main())
