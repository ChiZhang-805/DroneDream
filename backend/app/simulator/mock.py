"""Deterministic mock simulator adapter (Phase 4).

Computes TrialMetric-compatible values from
``(job_config, candidate parameters, seed, scenario, scenario_config)``.

Design goals:

* **Deterministic**: same inputs always produce the same metrics so tests
  (and, in Phase 5, the optimizer) can rely on a stable fitness landscape.
* **Scenario-aware**: the scenario_type and job-level wind/sensor noise
  values shape the error, so ``wind_perturbed`` + high wind is worse than
  ``nominal`` + zero wind.
* **Controlled failure injection**: a trial can be asked to fail with a
  specific code via ``scenario_config['inject_failure']`` or via a reserved
  key inside the candidate's ``parameters``. No random chaos.
* **Artifact metadata**: every COMPLETED trial returns metadata rows for a
  trajectory plot, telemetry JSON, and worker log. The mock does not write
  real bytes — the Artifact table stores metadata only in the MVP.
"""

from __future__ import annotations

import random
from typing import Any

from app.simulator.base import (
    FAILURE_SIMULATION,
    FAILURE_TIMEOUT,
    FAILURE_UNSTABLE,
    ArtifactMetadata,
    SimulatorAdapter,
    TrialContext,
    TrialFailure,
    TrialMetricsPayload,
    TrialResult,
)

# Multiplier applied to the base error for each scenario. Keep this in sync
# with Phase 3 behavior so existing metrics tests remain stable.
_SCENARIO_FACTOR: dict[str, float] = {
    "nominal": 1.00,
    "noise_perturbed": 1.30,
    "wind_perturbed": 1.45,
    "combined_perturbed": 1.80,
}

# Sensor-noise contribution to rmse. Higher noise -> larger rmse.
_NOISE_FACTOR: dict[str, float] = {
    "low": 0.98,
    "medium": 1.00,
    "high": 1.08,
}

# Recognised failure injection codes. Anything else is ignored.
_INJECTABLE_FAILURES = {
    "timeout": (FAILURE_TIMEOUT, "Mock simulator injected timeout."),
    "simulation_failed": (FAILURE_SIMULATION, "Mock simulator injected simulation failure."),
    "unstable_candidate": (FAILURE_UNSTABLE, "Mock simulator injected unstable candidate."),
}


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def _resolve_injected_failure(ctx: TrialContext) -> tuple[str, str] | None:
    """Return the injected (code, reason) pair, or None if not injected."""

    inject_key = None
    if ctx.scenario_config and isinstance(ctx.scenario_config, dict):
        inject_key = ctx.scenario_config.get("inject_failure")
    if inject_key is None and isinstance(ctx.parameters, dict):
        inject_key = ctx.parameters.get("inject_failure")
    if not isinstance(inject_key, str):
        return None
    return _INJECTABLE_FAILURES.get(inject_key.strip().lower())


class MockSimulatorAdapter(SimulatorAdapter):
    """Deterministic mock backend used by the MVP worker."""

    backend_name = "mock"

    def run_trial(self, ctx: TrialContext) -> TrialResult:
        injected = _resolve_injected_failure(ctx)
        if injected is not None:
            code, reason = injected
            return TrialResult(
                success=False,
                backend=self.backend_name,
                failure=TrialFailure(code=code, reason=reason),
                log_excerpt=f"[mock] scenario={ctx.scenario_type} seed={ctx.seed} FAILED {code}",
            )

        payload = self._compute_metrics(ctx)
        artifacts = self._build_artifacts(ctx, payload)
        log_excerpt = (
            f"[mock] scenario={ctx.scenario_type} seed={ctx.seed} "
            f"rmse={payload.rmse} score={payload.score}"
        )
        return TrialResult(
            success=True,
            backend=self.backend_name,
            metrics=payload,
            artifacts=artifacts,
            log_excerpt=log_excerpt,
        )

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _compute_metrics(self, ctx: TrialContext) -> TrialMetricsPayload:
        params = ctx.parameters or {}
        kp = float(params.get("kp_xy", 1.0))
        kd = float(params.get("kd_xy", 0.2))
        ki = float(params.get("ki_xy", 0.05))
        accel_limit = float(params.get("accel_limit", 4.0))
        disturbance = float(params.get("disturbance_rejection", 0.5))

        # Distance from a synthetic optimum. Abs so the landscape is a simple bowl.
        base_err = (
            abs(kp - 1.2) * 0.30
            + abs(kd - 0.30) * 0.20
            + abs(ki - 0.05) * 0.50
            + max(0.0, 3.5 - accel_limit) * 0.05
            + (1.0 - _clamp(disturbance, 0.0, 1.0)) * 0.10
            + 0.35
        )

        scenario_factor = _SCENARIO_FACTOR.get(ctx.scenario_type, 1.0)
        noise_factor = _NOISE_FACTOR.get(ctx.job_config.sensor_noise_level, 1.0)

        # Wind magnitude softly penalises wind-perturbed scenarios; nominal
        # and noise_perturbed trials barely feel it. This keeps Phase 3's
        # baseline numbers stable while making job config actually matter.
        wind_mag = (
            abs(ctx.job_config.wind_north)
            + abs(ctx.job_config.wind_east)
            + abs(ctx.job_config.wind_south)
            + abs(ctx.job_config.wind_west)
        )
        wind_penalty = 0.0
        if ctx.scenario_type in {"wind_perturbed", "combined_perturbed"}:
            wind_penalty = wind_mag * 0.01

        rng = random.Random(ctx.seed * 31 + sum(ord(c) for c in ctx.scenario_type))
        jitter = rng.uniform(-0.04, 0.04)

        rmse = max(0.05, base_err * scenario_factor * noise_factor + wind_penalty + jitter)
        max_error = rmse * 2.1 + rng.uniform(0.0, 0.15)
        overshoot_count = max(0, int(rmse * 3.0))
        completion_time = 12.0 + rng.uniform(-0.4, 0.6)
        final_error = rmse * 0.55
        score = 1.0 / (1.0 + rmse)

        crash_flag = False
        timeout_flag = False
        instability_flag = rmse > 1.1
        pass_flag = (not instability_flag) and (not crash_flag) and (not timeout_flag)

        raw: dict[str, Any] = {
            "rmse": round(rmse, 4),
            "max_error": round(max_error, 4),
            "overshoot_count": overshoot_count,
            "completion_time": round(completion_time, 3),
            "crash_flag": crash_flag,
            "timeout_flag": timeout_flag,
            "score": round(score, 4),
            "final_error": round(final_error, 4),
            "pass_flag": pass_flag,
            "instability_flag": instability_flag,
            "scenario_factor": scenario_factor,
            "noise_factor": noise_factor,
            "wind_penalty": round(wind_penalty, 4),
            "backend": self.backend_name,
        }

        return TrialMetricsPayload(
            rmse=round(rmse, 4),
            max_error=round(max_error, 4),
            overshoot_count=overshoot_count,
            completion_time=round(completion_time, 3),
            crash_flag=crash_flag,
            timeout_flag=timeout_flag,
            score=round(score, 4),
            final_error=round(final_error, 4),
            pass_flag=pass_flag,
            instability_flag=instability_flag,
            raw_metric_json=raw,
        )

    def _build_artifacts(
        self, ctx: TrialContext, payload: TrialMetricsPayload
    ) -> list[ArtifactMetadata]:
        base = f"mock://trials/{ctx.trial_id}"
        return [
            ArtifactMetadata(
                artifact_type="trajectory_plot",
                display_name=f"Trajectory ({ctx.scenario_type})",
                storage_path=f"{base}/trajectory.png",
                mime_type="image/png",
                file_size_bytes=None,
            ),
            ArtifactMetadata(
                artifact_type="telemetry_json",
                display_name=f"Telemetry ({ctx.scenario_type})",
                storage_path=f"{base}/telemetry.json",
                mime_type="application/json",
                file_size_bytes=None,
            ),
            ArtifactMetadata(
                artifact_type="worker_log",
                display_name=f"Worker log ({ctx.scenario_type})",
                storage_path=f"{base}/worker.log",
                mime_type="text/plain",
                file_size_bytes=None,
            ),
        ]


__all__ = ["MockSimulatorAdapter"]
