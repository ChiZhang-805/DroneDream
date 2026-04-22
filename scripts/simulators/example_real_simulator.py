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


def _compute_metrics(payload: dict[str, Any]) -> dict[str, Any]:
    params = payload.get("parameters", {}) or {}
    job = payload.get("job_config", {}) or {}
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
    with args.output.open("w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, sort_keys=True)
    return 0 if os.environ.get("EXAMPLE_SIM_EXIT_NONZERO") != "1" else 3


if __name__ == "__main__":  # pragma: no cover — CLI entry
    raise SystemExit(main())
