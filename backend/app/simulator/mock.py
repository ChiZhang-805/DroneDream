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

import hashlib
import random
from typing import Any

from app.parameters import get_parameter
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
    "turbulence": 1.65,
    "gps_dropout": 1.55,
    "payload_changed": 1.30,
    "battery_degraded": 1.25,
    "actuator_delay": 1.55,
    "custom": 1.15,
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


def _catalog_landscape_penalty(
    parameters: dict[str, Any], *, px4_version: str
) -> tuple[float, dict[str, float]]:
    """Return a deterministic synthetic loss for every recognized PX4 value.

    The mock backend cannot model flight physics. This normalized landscape is
    intentionally explicit and versioned so catalog-driven workflow tests do
    not silently ignore parameters or claim physical fidelity.
    """

    weighted_error = 0.0
    total_weight = 0.0
    contributions: dict[str, float] = {}
    risk_weights = {"low": 0.8, "medium": 1.0, "high": 1.2}
    for name, raw_value in parameters.items():
        if isinstance(raw_value, bool) or not isinstance(raw_value, int | float):
            continue
        definition = get_parameter(str(name), px4_version=px4_version)
        if definition is None:
            continue
        low = float(definition.safe_bounds.minimum)
        high = float(definition.safe_bounds.maximum)
        if high <= low:
            continue
        normalized = _clamp((float(raw_value) - low) / (high - low), 0.0, 1.0)
        default_normalized = _clamp((float(definition.default) - low) / (high - low), 0.0, 1.0)
        digest = hashlib.sha256(f"mock-landscape-v1:{name}".encode()).digest()
        deterministic_offset = (int.from_bytes(digest[:2], "big") / 65535.0 - 0.5) * 0.30
        synthetic_optimum = _clamp(default_normalized + deterministic_offset, 0.05, 0.95)
        distance = abs(normalized - synthetic_optimum)
        weight = risk_weights[definition.risk]
        contributions[str(name)] = round(distance, 6)
        weighted_error += distance * weight
        total_weight += weight
    if total_weight == 0:
        return 0.0, {}
    return 0.60 * weighted_error / total_weight, contributions


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

        if ctx.scenario_type not in _SCENARIO_FACTOR:
            return TrialResult(
                success=False,
                backend=self.backend_name,
                failure=TrialFailure(
                    code=FAILURE_SIMULATION,
                    reason=f"Mock backend does not support scenario {ctx.scenario_type!r}.",
                ),
                log_excerpt=f"[mock] unsupported scenario={ctx.scenario_type}",
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
        vehicle_profile = dict(ctx.job_config.vehicle_profile or {})
        px4_version = str(vehicle_profile.get("px4_version") or "main")
        catalog_penalty, catalog_contributions = _catalog_landscape_penalty(
            params,
            px4_version=px4_version,
        )

        # Distance from a synthetic optimum. Abs so the landscape is a simple bowl.
        base_err = (
            abs(kp - 1.2) * 0.30
            + abs(kd - 0.30) * 0.20
            + abs(ki - 0.05) * 0.50
            + max(0.0, 3.5 - accel_limit) * 0.05
            + (1.0 - _clamp(disturbance, 0.0, 1.0)) * 0.10
            + catalog_penalty
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
        scenario_cfg = dict(ctx.scenario_config or {})
        advanced = scenario_cfg.get("advanced_scenario_config")
        advanced_cfg = advanced if isinstance(advanced, dict) else {}
        gusts = advanced_cfg.get("wind_gusts")
        gust_penalty = 0.0
        if isinstance(gusts, dict) and bool(gusts.get("enabled", False)):
            try:
                gust_penalty = max(0.0, float(gusts.get("magnitude_mps", 0.0)) * 0.015)
            except (TypeError, ValueError):
                gust_penalty = 0.0
        sensor_degradation = advanced_cfg.get("sensor_degradation")
        dropout_rate = 0.0
        if isinstance(sensor_degradation, dict):
            try:
                dropout_rate = _clamp(float(sensor_degradation.get("dropout_rate", 0.0)), 0.0, 1.0)
            except (TypeError, ValueError):
                dropout_rate = 0.0
        if ctx.scenario_type == "gps_dropout":
            try:
                dropout_rate = max(
                    dropout_rate,
                    _clamp(float(scenario_cfg.get("dropout_rate", 0.20)), 0.0, 1.0),
                )
            except (TypeError, ValueError):
                dropout_rate = max(dropout_rate, 0.20)
        battery = advanced_cfg.get("battery")
        battery_initial_percent = 100.0
        payload_kg = 0.0
        if isinstance(battery, dict):
            try:
                battery_initial_percent = _clamp(
                    float(battery.get("initial_percent", 100.0)),
                    0.0,
                    100.0,
                )
            except (TypeError, ValueError):
                battery_initial_percent = 100.0
            try:
                payload_kg = _clamp(float(battery.get("mass_payload_kg", 0.0) or 0.0), 0.0, 20.0)
            except (TypeError, ValueError):
                payload_kg = 0.0
        if ctx.scenario_type == "battery_degraded" and not isinstance(battery, dict):
            battery_initial_percent = 45.0
        if ctx.scenario_type == "payload_changed" and payload_kg == 0.0:
            try:
                payload_kg = _clamp(float(scenario_cfg.get("mass_payload_kg", 1.0)), 0.0, 20.0)
            except (TypeError, ValueError):
                payload_kg = 1.0
        obstacle_count = (
            len(advanced_cfg.get("obstacles", []))
            if isinstance(advanced_cfg.get("obstacles"), list)
            else 0
        )
        actuator_delay_penalty = 0.0
        if ctx.scenario_type == "actuator_delay":
            try:
                actuator_delay_penalty = _clamp(
                    float(scenario_cfg.get("delay_ms", 50.0)) / 500.0,
                    0.0,
                    0.5,
                )
            except (TypeError, ValueError):
                actuator_delay_penalty = 0.1
        turbulence_penalty = 0.0
        if ctx.scenario_type == "turbulence":
            try:
                turbulence_penalty = _clamp(
                    float(scenario_cfg.get("intensity", 0.5)) * 0.15,
                    0.0,
                    0.3,
                )
            except (TypeError, ValueError):
                turbulence_penalty = 0.075

        rng = random.Random(ctx.seed * 31 + sum(ord(c) for c in ctx.scenario_type))
        jitter = rng.uniform(-0.04, 0.04)

        rmse = max(
            0.05,
            base_err * scenario_factor * noise_factor
            + wind_penalty
            + gust_penalty
            + dropout_rate * 0.20
            + obstacle_count * 0.005
            + actuator_delay_penalty
            + turbulence_penalty
            + jitter,
        )
        max_error = rmse * 2.1 + rng.uniform(0.0, 0.15)
        overshoot_count = max(0, int(rmse * 3.0))
        completion_time = (
            12.0
            + rng.uniform(-0.4, 0.6)
            + payload_kg * 0.04
            + max(0.0, (100.0 - battery_initial_percent) * 0.006)
        )
        final_error = rmse * 0.55
        # Global contract: lower score is better, matching real_cli/aggregation.
        score = rmse + 0.20 * max_error + 0.01 * completion_time

        crash_flag = False
        timeout_flag = False
        instability_flag = rmse > 1.1 or (dropout_rate >= 0.5 and (ctx.seed % 2 == 0))
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
            "gust_penalty": round(gust_penalty, 4),
            "dropout_rate": round(dropout_rate, 4),
            "battery_initial_percent": round(battery_initial_percent, 2),
            "payload_kg": round(payload_kg, 3),
            "mock_landscape_schema": "dronedream.mock.synthetic.v1",
            "physical_fidelity": False,
            "catalog_parameter_count": len(catalog_contributions),
            "catalog_parameter_penalty": round(catalog_penalty, 6),
            "catalog_parameter_contributions": catalog_contributions,
            "actuator_delay_penalty": round(actuator_delay_penalty, 4),
            "turbulence_penalty": round(turbulence_penalty, 4),
            "advanced_scenario_summary": {
                "has_advanced": bool(advanced_cfg),
                "gust_enabled": bool(isinstance(gusts, dict) and gusts.get("enabled")),
                "obstacle_count": obstacle_count,
                "dropout_rate": round(dropout_rate, 4),
                "dropout_instability_risk": "high" if dropout_rate >= 0.5 else "normal",
                "battery_initial_percent": round(battery_initial_percent, 2),
                "payload_kg": round(payload_kg, 3),
            },
            "backend": self.backend_name,
            "track_type": ctx.job_config.track_type,
            "reference_track_point_count": len(ctx.job_config.reference_track or []),
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
