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


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="DroneDream example real simulator")
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    return parser.parse_args()


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

    telem_path = run_dir / "telemetry.json"
    with telem_path.open("w", encoding="utf-8") as f:
        json.dump(
            {
                "trial_id": trial_id,
                "scenario": scenario,
                "metrics": metrics,
                "parameters": payload.get("parameters", {}),
            },
            f,
            indent=2,
            sort_keys=True,
        )

    traj_path = run_dir / "trajectory.json"
    # Minimal deterministic trajectory — enough to prove the file exists.
    # A real wrapper would write a real trajectory file / PNG.
    samples = [
        {"t": round(i * 0.1, 2), "x": round(i * 0.05, 3), "y": round(i * 0.05, 3)}
        for i in range(0, 20)
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
    params = payload.get("parameters", {}) or {}
    # The canonical grouped object is ``job_config``; top-level aliases
    # (``track_type``, ``altitude_m``, ``wind``, ``start_point``,
    # ``sensor_noise_level``, ``objective_profile``) mirror the same values
    # for wrapper authors who prefer the flat shape. This reference
    # implementation prefers ``job_config`` and falls back to top-level.
    job = payload.get("job_config") or {
        k: payload[k]
        for k in (
            "track_type",
            "altitude_m",
            "wind",
            "start_point",
            "sensor_noise_level",
            "objective_profile",
        )
        if k in payload
    }
    scenario = payload.get("scenario_type", "nominal")
    scenario_config = payload.get("scenario_config") or {}

    # Controlled failure injection for tests.
    inject = scenario_config.get("inject_failure") if isinstance(scenario_config, dict) else None
    if isinstance(params.get("inject_failure"), str):
        inject = params["inject_failure"]
    if isinstance(inject, str):
        inject = inject.strip().lower()
        if inject == "sleep":
            time.sleep(float(scenario_config.get("sleep_seconds", 30)))
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

    kp = float(params.get("kp_xy", 1.0))
    kd = float(params.get("kd_xy", 0.2))
    ki = float(params.get("ki_xy", 0.05))
    disturbance = max(0.0, min(1.0, float(params.get("disturbance_rejection", 0.5))))
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


def main() -> int:
    args = _parse_args()
    try:
        with args.input.open("r", encoding="utf-8") as f:
            payload = json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"[example_real_simulator] cannot read input: {exc}", file=sys.stderr)
        return 2
    result = _compute_metrics(payload)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    # Emit per-trial artifact files for successful trials. Failure paths
    # (``success=False``) intentionally skip this so the adapter's error
    # reporting stays the salient signal.
    if result.get("success") and isinstance(result.get("metrics"), dict):
        result["artifacts"] = _emit_artifacts(
            payload, args.output.parent, result["metrics"]
        )
    with args.output.open("w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, sort_keys=True)
    return 0 if os.environ.get("EXAMPLE_SIM_EXIT_NONZERO") != "1" else 3


if __name__ == "__main__":  # pragma: no cover — CLI entry
    raise SystemExit(main())
