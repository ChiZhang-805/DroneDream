"""Baseline-calibrated successor to the outcome-blind pre-final registry.

Version 1 remains immutable evidence of the preregistered design.  This module
applies only mechanism-based changes justified by baseline-only PX4/Gazebo
calibration; it does not inspect or prune comparative optimizer outcomes.
"""

from __future__ import annotations

import copy
import hashlib
import json
from typing import Any

from app.optimization.prefinal_scenario_registry import build_prefinal_scenario_registry
from app.optimization.scenarios import scenario_matrix
from app.schemas import JobCreateRequest
from app.simulator.scenario_effects import build_scenario_effect_request

PREFINAL_CALIBRATED_REGISTRY_SCHEMA_VERSION = (
    "dronedream.prefinal-scenario-registry/v2"
)
PREFINAL_CALIBRATED_REGISTRY_VERSION = "prefinal-realistic-px4-gazebo-v2"
PREFINAL_CALIBRATED_MANIFEST_SCHEMA_VERSION = (
    "dronedream.prefinal-scenario-registry-manifest/v1"
)

_CALIBRATION_MANIFEST = {
    "path": "artifacts/test-runs/prefinal-physical-calibration-9db5df2-smoke3/"
    "campaign-manifest.json",
    "execution_source": "9db5df212ef14927e0ba47a30304b026d3c0bc4c",
    "engine_pack_id": (
        "sha256:28347545e0160d459513e432bfa83af3c36a8497a800933bfe0982bc68095674"
    ),
    "repository_evidence_head": "9c4004961b2079cef2a7f84e1fb39d23f33ff460",
    "provider_calls_attempted": 0,
    "provider_calls_succeeded": 0,
}

_GNSS_PREARM_REVISIONS = {
    "representative-hover-sensor-noise": 0.25,
    "representative-lemniscate-sensor-noise": 0.35,
    "representative-circle-wind-noise": 0.20,
    "hard-lemniscate-gust-noise": 0.40,
    "hard-hover-wind-dropout": 0.45,
}

_CALIBRATED_PROBLEMS = {
    "easy-hover-calm": {
        "status": "baseline_calibrated_easy_tail",
        "job_id": "job_ce55e4c02f7a",
        "receipt_sha256": "c12292447368d32b6c6869f1fca42bf35d12c2a6ee3bbbadd83e1bef60e75b89",
        "outcome": "qualified_4_of_4",
    },
    "representative-circle-crosswind": {
        "status": "baseline_calibrated_discriminative_candidate",
        "job_id": "job_8c1175cb474e",
        "receipt_sha256": "f1f5c7fab2756d461c0b4be3e4f713227671b23e40ceb14c93ac63565834cc36",
        "outcome": "completed_4_of_4_baseline_not_qualified",
    },
    "hard-hover-wind-dropout": {
        "status": "v1_prearm_invalid_revised_recalibration_required",
        "job_id": "job_52b4e29f4dc5",
        "receipt_sha256": "d631e8173b6a9104d98e4e678e490237d36dc36de9d227e7f49f3ee47312d9e5",
        "outcome": "failed_4_of_4_before_flight_global_position_unhealthy",
    },
}


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def _sha256(value: object) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _rebuild_effect_contracts(problem: dict[str, Any]) -> list[dict[str, Any]]:
    job = JobCreateRequest.model_validate(problem["job_template"])
    job_payload = job.model_dump(mode="json", exclude_none=True)
    contracts: list[dict[str, Any]] = []
    for run in scenario_matrix(job.scenario_suite):
        request = build_scenario_effect_request(
            execution_identity={
                "registry_version": PREFINAL_CALIBRATED_REGISTRY_VERSION,
                "problem_id": problem["problem_id"],
                "case_id": run.case_id,
                "seed": run.seed,
            },
            scenario_type=run.scenario_type,
            scenario_config=run.config,
            job_config={
                "wind": job_payload["wind"],
                "sensor_noise_level": job.sensor_noise_level,
            },
            advanced_config=job_payload.get("advanced_scenario_config"),
        )
        unavailable = [
            effect["effect_id"]
            for effect in request["effects"]
            if effect["capability"]["status"] != "available"
        ]
        if unavailable:
            raise ValueError(
                f"{problem['problem_id']} requires unavailable effects: {sorted(unavailable)}"
            )
        contracts.append(
            {
                "case_id": run.case_id,
                "seed": run.seed,
                "holdout": run.holdout,
                "effect_ids": [effect["effect_id"] for effect in request["effects"]],
                "request_sha256": _sha256(request),
            }
        )
    return contracts


def build_prefinal_calibrated_scenario_registry() -> dict[str, Any]:
    """Build the deterministic v2 baseline-calibration revision."""

    base = build_prefinal_scenario_registry()
    registry = copy.deepcopy(base)
    base_sha = str(registry.pop("registry_sha256"))
    registry["schema_version"] = PREFINAL_CALIBRATED_REGISTRY_SCHEMA_VERSION
    registry["registry_version"] = PREFINAL_CALIBRATED_REGISTRY_VERSION
    registry["status"] = "baseline_calibration_in_progress"
    registry["report_eligible"] = False
    registry["claim_boundary"] = (
        "Baseline-only calibration revision. It makes no provider calls, compares no "
        "optimizer arms, selects no comparative winner, and supports no superiority, "
        "real-aircraft safety, or global-optimum claim."
    )
    registry["supersedes_registry"] = {
        "registry_version": base["registry_version"],
        "registry_sha256": base_sha,
        "preserved_as_immutable_input": True,
    }
    registry["calibration_protocol"] = {
        **registry["calibration_protocol"],
        "status": "partial_3_of_18",
        "calibration_manifest": _CALIBRATION_MANIFEST,
        "uses_comparative_arm_outcomes": False,
        "uses_provider": False,
        "uses_optimizer": False,
        "successor_required": "locked-realistic-px4-gazebo-v3-after-full-calibration",
    }
    registry["calibration_audit_log"] = []

    for problem in registry["problems"]:
        problem_id = str(problem["problem_id"])
        observed = _CALIBRATED_PROBLEMS.get(problem_id)
        if observed is not None:
            problem["threshold_status"] = observed["status"]
            problem["baseline_calibration_observation"] = observed

        previous_gps_noise = _GNSS_PREARM_REVISIONS.get(problem_id)
        if previous_gps_noise is not None:
            advanced = problem["job_template"].get("advanced_scenario_config")
            if not isinstance(advanced, dict):
                raise ValueError(f"{problem_id} is missing advanced scenario configuration")
            sensor = advanced.get("sensor_degradation")
            if not isinstance(sensor, dict):
                raise ValueError(f"{problem_id} is missing sensor degradation")
            if float(sensor.get("gps_noise_m", -1.0)) != previous_gps_noise:
                raise ValueError(f"{problem_id} GNSS calibration input drifted")
            sensor["gps_noise_m"] = 0.0
            adjustment = {
                "field": "advanced_scenario_config.sensor_degradation.gps_noise_m",
                "before": previous_gps_noise,
                "after": 0.0,
                "reason": (
                    "Continuous Gazebo NavSat noise is active before arming and can make "
                    "PX4 global_position_ok=false before any optimizer candidate flies. "
                    "Keep GNSS healthy for prearm; retain high barometer/IMU noise and any "
                    "post-takeoff deterministic dropout, wind, gust, payload, or battery stress."
                ),
                "comparative_outcome_used": False,
            }
            problem.setdefault("calibration_adjustments", []).append(adjustment)
            registry["calibration_audit_log"].append(
                {"problem_id": problem_id, **adjustment}
            )

        contracts = _rebuild_effect_contracts(problem)
        problem["physical_effect_contracts"] = contracts
        problem["physical_effect_contracts_sha256"] = _sha256(contracts)

    unsigned = dict(registry)
    return {**unsigned, "registry_sha256": _sha256(unsigned)}


def verify_prefinal_calibrated_scenario_registry(registry: dict[str, Any]) -> bool:
    expected = registry.get("registry_sha256")
    unsigned = {key: value for key, value in registry.items() if key != "registry_sha256"}
    return (
        isinstance(expected, str)
        and expected == _sha256(unsigned)
        and registry == build_prefinal_calibrated_scenario_registry()
    )


__all__ = [
    "PREFINAL_CALIBRATED_MANIFEST_SCHEMA_VERSION",
    "PREFINAL_CALIBRATED_REGISTRY_SCHEMA_VERSION",
    "PREFINAL_CALIBRATED_REGISTRY_VERSION",
    "build_prefinal_calibrated_scenario_registry",
    "verify_prefinal_calibrated_scenario_registry",
]
