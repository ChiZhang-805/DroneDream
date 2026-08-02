"""Aggregate the complete bundled PX4/Gazebo effect-coverage evidence.

The individual campaigns remain immutable and authoritative.  This module only
verifies their receipts/manifests by exact bytes, validates the semantic claim
boundaries, snapshots the current launcher capability contract, and emits a
small provenance-bound closure manifest.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Any

from app.simulator.scenario_effects import bundled_launcher_capabilities

MANIFEST_SCHEMA_VERSION = "dronedream.advanced-physics-closure-manifest.v2"
RECEIPT_SCHEMA_VERSION = "dronedream.advanced-physics-closure-receipt.v2"
EVIDENCE_CLASS = "REAL_PX4_GAZEBO_BUNDLED_EFFECT_CLOSURE"
CLAIM_BOUNDARY = (
    "Exact-byte aggregation of real PX4 SITL and Gazebo evidence for every "
    "bundled DroneDream physical-effect category. It proves request-bound "
    "injection and readback within the retained x500/default-world protocols. "
    "It does not claim that every perturbed flight passed its performance "
    "policy, real-aircraft transfer, flight safety, or general controller "
    "superiority."
)

_COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_EXPECTED_PX4_COMMIT = "6ea3539157ca358c70a515878b77077af7d4611d"
_CAPABILITY_CATEGORIES = (
    "actuator_first_order_delay",
    "actuator_hard_failure",
    "battery_initial_state_and_voltage_sag",
    "deterministic_seeded_gps_dropout",
    "gust_and_turbulence",
    "obstacles",
    "payload_mass_and_inertia",
    "sensor_noise",
    "steady_wind",
)


@dataclass(frozen=True)
class EvidenceSource:
    role: str
    receipt_path: str
    receipt_schema: str
    subject_commit: str
    manifest_path: str | None = None
    manifest_schema: str | None = None


EVIDENCE_SOURCES = (
    EvidenceSource(
        role="constant_wind_and_obstacles",
        receipt_path=(
            "artifacts/technical-report/px4-physical-campaign-v1-5f0f62c/"
            "px4-physical-campaign-v1.receipt.json"
        ),
        receipt_schema="dronedream.px4-physical-campaign-receipt.v1",
        subject_commit="86273db6d827a790cb0a8b1472256b23e0a629d2",
        manifest_path=(
            "artifacts/technical-report/px4-physical-campaign-v1-5f0f62c/"
            "px4-physical-campaign-v1.manifest.json"
        ),
        manifest_schema="dronedream.px4-physical-campaign-evidence.v1",
    ),
    EvidenceSource(
        role="gust_noise_payload_and_actuator_delay",
        receipt_path=(
            "artifacts/technical-report/advanced-physics-real-px4-v1-26b957e/"
            "advanced-physics-real-px4-v1.receipt.json"
        ),
        receipt_schema="dronedream.advanced-physics-real-px4-receipt.v1",
        subject_commit="26b957efd985d0ac37702a8d2518e87ab65347c3",
        manifest_path=(
            "artifacts/technical-report/advanced-physics-real-px4-v1-26b957e/"
            "advanced-physics-real-px4-v1.manifest.json"
        ),
        manifest_schema="dronedream.advanced-physics-real-px4-manifest.v1",
    ),
    EvidenceSource(
        role="gps_dropout_and_battery",
        receipt_path=(
            "artifacts/test-runs/advanced-physics-runtime-working-tree-probe/"
            "attempt-18/receipt.json"
        ),
        receipt_schema="dronedream.advanced-physics-runtime-receipt/v1",
        subject_commit="fdf1250398567c6658ad5148efc1c302dede4a17",
    ),
    EvidenceSource(
        role="hard_actuator_failure",
        receipt_path=(
            "artifacts/test-runs/"
            "advanced-physics-actuator-failure-working-tree-probe/"
            "attempt-1/receipt.json"
        ),
        receipt_schema="dronedream.advanced-physics-actuator-failure-receipt/v1",
        subject_commit="793f02089413f2baa8ea78387cd1e9e078f02b83",
    ),
)

_COVERAGE = (
    {
        "category": "steady_wind",
        "effect_ids": ["job_config.wind"],
        "source_role": "constant_wind_and_obstacles",
        "evidence_strength": "two_seed_successful_flight_and_runtime_readback",
        "performance_success_for_all_retained_trials": True,
    },
    {
        "category": "obstacles",
        "effect_ids": ["scenario_config.obstacles"],
        "source_role": "constant_wind_and_obstacles",
        "evidence_strength": "two_seed_successful_flight_and_entity_creation_readback",
        "performance_success_for_all_retained_trials": True,
    },
    {
        "category": "gust_and_turbulence",
        "effect_ids": ["wind_gusts"],
        "source_role": "gust_noise_payload_and_actuator_delay",
        "evidence_strength": "three_successful_flights_and_generated_sdf_readback",
        "performance_success_for_all_retained_trials": True,
    },
    {
        "category": "sensor_noise",
        "effect_ids": [
            "sensor_degradation.baro_noise_m",
            "sensor_degradation.gps_noise_m",
            "sensor_degradation.imu_noise_scale",
        ],
        "source_role": "gust_noise_payload_and_actuator_delay",
        "evidence_strength": ("barometer_and_imu_successful_flight_plus_gps_readiness_boundary"),
        "performance_success_for_all_retained_trials": False,
    },
    {
        "category": "payload_mass_and_inertia",
        "effect_ids": ["battery.mass_payload_kg"],
        "source_role": "gust_noise_payload_and_actuator_delay",
        "evidence_strength": "three_successful_flights_and_generated_sdf_readback",
        "performance_success_for_all_retained_trials": True,
    },
    {
        "category": "actuator_first_order_delay",
        "effect_ids": ["scenario_type.actuator_delay"],
        "source_role": "gust_noise_payload_and_actuator_delay",
        "evidence_strength": "three_successful_flights_and_generated_sdf_readback",
        "performance_success_for_all_retained_trials": True,
    },
    {
        "category": "deterministic_seeded_gps_dropout",
        "effect_ids": ["sensor_degradation.dropout_rate"],
        "source_role": "gps_dropout_and_battery",
        "evidence_strength": ("flight_timed_parameter_readback_gps_telemetry_and_ulog_transition"),
        "performance_success_for_all_retained_trials": False,
    },
    {
        "category": "battery_initial_state_and_voltage_sag",
        "effect_ids": ["battery.initial_percent", "battery.voltage_sag"],
        "source_role": "gps_dropout_and_battery",
        "evidence_strength": "flight_timed_parameter_readback_and_battery_telemetry",
        "performance_success_for_all_retained_trials": False,
    },
    {
        "category": "actuator_hard_failure",
        "effect_ids": ["scenario_type.actuator_failure"],
        "source_role": "hard_actuator_failure",
        "evidence_strength": ("generated_sdf_plus_failed_and_healthy_rotor_joint_state_readback"),
        "performance_success_for_all_retained_trials": False,
    },
)


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _pretty_bytes(value: object) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _self_hash(payload: Mapping[str, Any], field: str) -> str:
    return _sha256_bytes(
        _canonical_bytes({key: value for key, value in payload.items() if key != field})
    )


def _require_commit(value: object, *, field: str) -> str:
    if not isinstance(value, str) or _COMMIT_RE.fullmatch(value) is None:
        raise ValueError(f"{field} must be a full lowercase Git commit")
    return value


def _require_sha256(value: object, *, field: str) -> str:
    if not isinstance(value, str) or _SHA256_RE.fullmatch(value) is None:
        raise ValueError(f"{field} must be a lowercase SHA-256")
    return value


def _require_timestamp(value: object, *, field: str) -> str:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ValueError(f"{field} must be an explicit UTC timestamp")
    try:
        datetime.fromisoformat(value.removesuffix("Z") + "+00:00")
    except ValueError as exc:
        raise ValueError(f"{field} must be an explicit UTC timestamp") from exc
    return value


def _safe_path(value: str, *, field: str) -> PurePosixPath:
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or not path.parts:
        raise ValueError(f"{field} must be a safe repository-relative path")
    return path


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"could not read JSON evidence: {path}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"JSON evidence must be an object: {path}")
    return value


def _file_record(repository_root: Path, relative: str) -> dict[str, Any]:
    path = repository_root.joinpath(*_safe_path(relative, field="source path").parts)
    if not path.is_file():
        raise ValueError(f"evidence source is missing: {relative}")
    raw = path.read_bytes()
    return {
        "path": relative,
        "bytes": len(raw),
        "sha256": _sha256_bytes(raw),
    }


def _mapping(value: object, *, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{field} must be an object")
    return value


def _verify_manifest_binding(
    *,
    source: EvidenceSource,
    receipt: Mapping[str, Any],
    manifest: Mapping[str, Any],
    manifest_record: Mapping[str, Any],
) -> None:
    if manifest.get("schema_version") != source.manifest_schema:
        raise ValueError(f"{source.role} manifest schema drifted")
    if manifest.get("subject_commit") != source.subject_commit:
        raise ValueError(f"{source.role} manifest subject commit drifted")
    binding = _mapping(receipt.get("manifest"), field=f"{source.role}.manifest")
    manifest_path = PurePosixPath(source.manifest_path or "")
    if binding.get("path") != manifest_path.name:
        raise ValueError(f"{source.role} receipt manifest path drifted")
    if binding.get("bytes") != manifest_record["bytes"]:
        raise ValueError(f"{source.role} receipt manifest byte length drifted")
    if binding.get("sha256") != manifest_record["sha256"]:
        raise ValueError(f"{source.role} receipt manifest SHA-256 drifted")
    internal = manifest.get("manifest_sha256")
    if "manifest_sha256" in binding and binding.get("manifest_sha256") != internal:
        raise ValueError(f"{source.role} receipt internal manifest hash drifted")
    if internal is not None:
        _require_sha256(internal, field=f"{source.role}.manifest_sha256")
        if internal != _self_hash(manifest, "manifest_sha256"):
            raise ValueError(f"{source.role} internal manifest hash drifted")


def _validate_physical_campaign(
    receipt: Mapping[str, Any],
    manifest: Mapping[str, Any],
) -> None:
    result = _mapping(receipt.get("result"), field="physical campaign result")
    if result != {
        "failed": 0,
        "passed": 6,
        "retained_failure_probes": 4,
        "status": "passed",
        "trial_count": 6,
    }:
        raise ValueError("constant-wind/obstacle campaign result drifted")
    if receipt.get("px4_commit") != _EXPECTED_PX4_COMMIT:
        raise ValueError("constant-wind/obstacle PX4 identity drifted")
    if manifest.get("network_calls") != 0 or manifest.get("real_credentials_used") is not False:
        raise ValueError("constant-wind/obstacle campaign provenance drifted")
    protocol = _mapping(manifest.get("protocol"), field="physical protocol")
    matrix = _mapping(protocol.get("matrix"), field="physical protocol matrix")
    if (
        matrix.get("scenarios") != ["nominal", "steady_wind", "static_obstacle"]
        or matrix.get("seeds") != [41001, 41002]
        or matrix.get("trial_count") != 6
        or matrix.get("paired_by_seed") is not True
    ):
        raise ValueError("constant-wind/obstacle scenario matrix drifted")
    trials = manifest.get("trials")
    if not isinstance(trials, list) or len(trials) != 6:
        raise ValueError("constant-wind/obstacle trial matrix drifted")
    scenarios: list[str] = [
        (
            item["scenario"]
            if isinstance(item, Mapping) and isinstance(item.get("scenario"), str)
            else ""
        )
        for item in trials
    ]
    if sorted(scenarios) != [
        "nominal",
        "nominal",
        "static_obstacle",
        "static_obstacle",
        "steady_wind",
        "steady_wind",
    ] or any(
        not isinstance(item, Mapping)
        or item.get("success") is not True
        or item.get("pass_flag") is not True
        for item in trials
    ):
        raise ValueError("constant-wind/obstacle trial outcomes drifted")


def _validate_advanced_campaign(
    receipt: Mapping[str, Any],
    manifest: Mapping[str, Any],
) -> None:
    result = _mapping(receipt.get("result"), field="advanced campaign result")
    if (
        result.get("status") != "passed"
        or result.get("successful_flights") != 3
        or result.get("passing_flights") != 3
        or result.get("gps_readiness_boundaries") != 2
    ):
        raise ValueError("advanced SDF campaign result drifted")
    if (
        receipt.get("px4_commit") != _EXPECTED_PX4_COMMIT
        or receipt.get("network_calls") != 0
        or receipt.get("real_credentials_used") is not False
    ):
        raise ValueError("advanced SDF campaign provenance drifted")
    protocol = _mapping(manifest.get("protocol"), field="advanced protocol")
    if set(protocol.get("successful_flight_effects", [])) != {
        "battery.mass_payload_kg",
        "scenario_type.actuator_delay",
        "sensor_degradation.baro_noise_m",
        "sensor_degradation.imu_noise_scale",
        "wind_gusts",
    }:
        raise ValueError("advanced successful-flight effects drifted")
    if "sensor_degradation.gps_noise_m" not in set(
        protocol.get("gps_readiness_boundary_effects", [])
    ):
        raise ValueError("GPS-noise readiness boundary is missing")
    if manifest.get("remaining_runtime_extensions") != [
        "probabilistic GPS dropout",
        "battery initial state and voltage sag",
        "hard actuator failure beyond the bounded first-order delay profile",
    ]:
        raise ValueError("advanced campaign predecessor gaps drifted")


def _validate_dropout_battery(receipt: Mapping[str, Any]) -> None:
    run = _mapping(receipt.get("physical_run"), field="dropout physical_run")
    result = _mapping(receipt.get("effect_result"), field="dropout effect_result")
    review = _mapping(
        receipt.get("independent_ulog_review"),
        field="dropout independent_ulog_review",
    )
    outcome = _mapping(receipt.get("outcome"), field="dropout outcome")
    if (
        run.get("runner_exit_code") != 0
        or run.get("acceptance_exit_code") != 0
        or run.get("trial_success") is not True
        or run.get("residual_process_count") != 0
        or run.get("openai_api_key_used") is not False
        or result.get("verification_status") != "verified_applied"
        or set(result.get("applied_effects", []))
        != {
            "battery.initial_percent",
            "battery.voltage_sag",
            "sensor_degradation.dropout_rate",
        }
        or result.get("gps_restore_verified") is not True
        or result.get("battery_nonincrease_verified") is not True
        or review.get("physical_transition_verified") is not True
        or outcome.get("pass_flag") is not False
    ):
        raise ValueError("GPS-dropout/battery evidence drifted")
    environment = _mapping(run.get("environment"), field="dropout environment")
    if environment.get("px4_firmware_commit") != _EXPECTED_PX4_COMMIT:
        raise ValueError("GPS-dropout/battery PX4 identity drifted")


def _validate_hard_failure(receipt: Mapping[str, Any]) -> None:
    run = _mapping(receipt.get("physical_run"), field="actuator physical_run")
    effect = _mapping(receipt.get("effect_result"), field="actuator effect_result")
    joint = _mapping(
        effect.get("gazebo_joint_state"),
        field="actuator gazebo_joint_state",
    )
    outcome = _mapping(receipt.get("trial_outcome"), field="actuator trial_outcome")
    if (
        run.get("runner_exit_code") != 0
        or run.get("acceptance_exit_code") != 0
        or run.get("trial_success") is not False
        or run.get("physical_effect_verified") is not True
        or run.get("residual_process_count") != 0
        or run.get("openai_api_key_used") is not False
        or effect.get("verification_status") != "verified_applied"
        or joint.get("hard_stop_verified") is not True
        or joint.get("healthy_motion_verified") is not True
        or outcome.get("success") is not False
    ):
        raise ValueError("hard actuator-failure evidence drifted")
    target = joint.get("target_max_abs_velocity_rad_s")
    limit = joint.get("max_failed_motor_abs_velocity_rad_s")
    if (
        isinstance(target, bool)
        or not isinstance(target, (int, float))
        or isinstance(limit, bool)
        or not isinstance(limit, (int, float))
        or float(target) > float(limit)
    ):
        raise ValueError("hard actuator-failure velocity boundary drifted")
    environment = _mapping(run.get("environment"), field="actuator environment")
    if environment.get("px4_firmware_commit") != _EXPECTED_PX4_COMMIT:
        raise ValueError("hard actuator-failure PX4 identity drifted")


def _validate_capabilities(payload: Mapping[str, Any]) -> dict[str, Any]:
    physically_applied = payload.get("physically_applied")
    extensions = payload.get("requires_runtime_extension")
    if physically_applied != list(_CAPABILITY_CATEGORIES):
        raise ValueError("bundled physical capability categories drifted")
    if extensions != []:
        raise ValueError("bundled Runtime extensions remain open")
    return {
        "schema_version": payload.get("schema_version"),
        "physically_applied": list(physically_applied),
        "requires_runtime_extension": [],
        "contract_sha256": _sha256_bytes(_canonical_bytes(payload)),
    }


def _source_records(repository_root: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for source in EVIDENCE_SOURCES:
        receipt_record = _file_record(repository_root, source.receipt_path)
        receipt = _load_json(repository_root / source.receipt_path)
        if receipt.get("schema_version") != source.receipt_schema:
            raise ValueError(f"{source.role} receipt schema drifted")
        if receipt.get("subject_commit") != source.subject_commit:
            raise ValueError(f"{source.role} receipt subject commit drifted")
        internal_receipt_hash = receipt.get("receipt_sha256")
        if internal_receipt_hash is not None:
            _require_sha256(
                internal_receipt_hash,
                field=f"{source.role}.receipt_sha256",
            )
            if internal_receipt_hash != _self_hash(receipt, "receipt_sha256"):
                raise ValueError(f"{source.role} internal receipt hash drifted")
        record: dict[str, Any] = {
            "role": source.role,
            "subject_commit": source.subject_commit,
            "receipt": receipt_record,
        }
        manifest: dict[str, Any] | None = None
        if source.manifest_path is not None:
            manifest_record = _file_record(repository_root, source.manifest_path)
            manifest = _load_json(repository_root / source.manifest_path)
            _verify_manifest_binding(
                source=source,
                receipt=receipt,
                manifest=manifest,
                manifest_record=manifest_record,
            )
            record["manifest"] = manifest_record
        if source.role == "constant_wind_and_obstacles":
            _validate_physical_campaign(receipt, manifest or {})
        elif source.role == "gust_noise_payload_and_actuator_delay":
            _validate_advanced_campaign(receipt, manifest or {})
        elif source.role == "gps_dropout_and_battery":
            _validate_dropout_battery(receipt)
        elif source.role == "hard_actuator_failure":
            _validate_hard_failure(receipt)
        else:  # pragma: no cover - closed constant registry.
            raise AssertionError(source.role)
        records.append(record)
    return records


def _build_manifest(
    *,
    repository_root: Path,
    subject_commit: str,
    generated_at: str,
    capabilities: Mapping[str, Any],
) -> dict[str, Any]:
    source_records = _source_records(repository_root)
    capability_snapshot = _validate_capabilities(capabilities)
    coverage: list[dict[str, Any]] = [dict(row) for row in _COVERAGE]
    covered = sorted(str(row["category"]) for row in coverage)
    if covered != sorted(_CAPABILITY_CATEGORIES):
        raise ValueError("evidence coverage does not match the capability contract")
    manifest: dict[str, Any] = {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "evidence_class": EVIDENCE_CLASS,
        "claim_boundary": CLAIM_BOUNDARY,
        "generated_at": _require_timestamp(generated_at, field="generated_at"),
        "subject_commit": _require_commit(subject_commit, field="subject_commit"),
        "runtime_identity": {
            "px4_commit": _EXPECTED_PX4_COMMIT,
            "px4_version": "v1.16",
            "gazebo_sim_version_observed_in_latest_closure": "8.14.0",
            "gazebo_transport_version_observed_in_latest_closure": "13.5.0",
            "vehicle": "x500",
            "world": "default",
            "real_aircraft": False,
        },
        "capability_contract": capability_snapshot,
        "source_evidence": source_records,
        "coverage": coverage,
        "remaining_runtime_extensions": [],
        "summary": {
            "capability_category_count": len(_CAPABILITY_CATEGORIES),
            "verified_category_count": len(coverage),
            "source_receipt_count": len(EVIDENCE_SOURCES),
            "source_manifest_count": sum(
                source.manifest_path is not None for source in EVIDENCE_SOURCES
            ),
            "categories_with_all_retained_performance_success": sum(
                row["performance_success_for_all_retained_trials"] is True for row in coverage
            ),
            "all_runtime_effect_categories_verified": True,
            "all_effects_performance_successful": False,
            "real_aircraft_claim_permitted": False,
        },
    }
    manifest["manifest_sha256"] = _self_hash(manifest, "manifest_sha256")
    return manifest


def _build_receipt(
    *,
    manifest: Mapping[str, Any],
    manifest_bytes: bytes,
) -> dict[str, Any]:
    summary = _mapping(manifest.get("summary"), field="manifest summary")
    receipt: dict[str, Any] = {
        "schema_version": RECEIPT_SCHEMA_VERSION,
        "evidence_class": EVIDENCE_CLASS,
        "claim_boundary": CLAIM_BOUNDARY,
        "generated_at": manifest["generated_at"],
        "subject_commit": manifest["subject_commit"],
        "manifest": {
            "path": "advanced-physics-closure-v2.manifest.json",
            "bytes": len(manifest_bytes),
            "sha256": _sha256_bytes(manifest_bytes),
            "manifest_sha256": manifest["manifest_sha256"],
        },
        "result": {
            "status": "complete_for_bundled_runtime_effect_contract",
            "verified_categories": summary["verified_category_count"],
            "remaining_runtime_extensions": 0,
            "all_effects_performance_successful": False,
            "real_aircraft_claim_permitted": False,
        },
        "network_calls": 0,
        "real_credentials_used": False,
        "openai_api_key_used": False,
    }
    receipt["receipt_sha256"] = _self_hash(receipt, "receipt_sha256")
    return receipt


def _write_exact(path: Path, value: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    created = False
    try:
        with path.open("xb") as handle:
            created = True
            handle.write(value)
    except FileExistsError as exc:
        raise ValueError(f"refusing to replace frozen evidence file: {path}") from exc
    except Exception:
        if created:
            path.unlink(missing_ok=True)
        raise


def export_advanced_physics_closure(
    *,
    repository_root: Path,
    output_root: Path,
    subject_commit: str,
    generated_at: str,
    capabilities: Mapping[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Verify all source evidence and export the deterministic closure bundle."""

    if output_root.exists() and any(output_root.iterdir()):
        raise ValueError(f"output directory must be absent or empty: {output_root}")
    output_root.mkdir(parents=True, exist_ok=True)
    manifest = _build_manifest(
        repository_root=repository_root,
        subject_commit=subject_commit,
        generated_at=generated_at,
        capabilities=capabilities or bundled_launcher_capabilities(),
    )
    manifest_bytes = _pretty_bytes(manifest)
    receipt = _build_receipt(manifest=manifest, manifest_bytes=manifest_bytes)
    receipt_bytes = _pretty_bytes(receipt)
    checksum_bytes = (
        f"{_sha256_bytes(manifest_bytes)}  advanced-physics-closure-v2.manifest.json\n"
        f"{_sha256_bytes(receipt_bytes)}  advanced-physics-closure-v2.receipt.json\n"
    ).encode("ascii")
    _write_exact(
        output_root / "advanced-physics-closure-v2.manifest.json",
        manifest_bytes,
    )
    _write_exact(
        output_root / "advanced-physics-closure-v2.receipt.json",
        receipt_bytes,
    )
    _write_exact(output_root / "advanced-physics-closure-v2.sha256", checksum_bytes)
    return manifest, receipt


def verify_advanced_physics_closure(
    *,
    repository_root: Path,
    evidence_root: Path,
    capabilities: Mapping[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Recompute every source binding and verify an exported closure bundle."""

    manifest_path = evidence_root / "advanced-physics-closure-v2.manifest.json"
    receipt_path = evidence_root / "advanced-physics-closure-v2.receipt.json"
    checksum_path = evidence_root / "advanced-physics-closure-v2.sha256"
    manifest = _load_json(manifest_path)
    receipt = _load_json(receipt_path)
    if manifest.get("schema_version") != MANIFEST_SCHEMA_VERSION:
        raise ValueError("advanced-physics closure manifest schema drifted")
    if receipt.get("schema_version") != RECEIPT_SCHEMA_VERSION:
        raise ValueError("advanced-physics closure receipt schema drifted")
    if manifest.get("manifest_sha256") != _self_hash(
        manifest,
        "manifest_sha256",
    ):
        raise ValueError("advanced-physics closure internal manifest hash drifted")
    if receipt.get("receipt_sha256") != _self_hash(receipt, "receipt_sha256"):
        raise ValueError("advanced-physics closure internal receipt hash drifted")
    expected_manifest = _build_manifest(
        repository_root=repository_root,
        subject_commit=_require_commit(
            manifest.get("subject_commit"),
            field="subject_commit",
        ),
        generated_at=_require_timestamp(
            manifest.get("generated_at"),
            field="generated_at",
        ),
        capabilities=capabilities or bundled_launcher_capabilities(),
    )
    if manifest != expected_manifest:
        raise ValueError("advanced-physics closure manifest does not recompute")
    manifest_bytes = manifest_path.read_bytes()
    expected_receipt = _build_receipt(
        manifest=manifest,
        manifest_bytes=manifest_bytes,
    )
    if receipt != expected_receipt:
        raise ValueError("advanced-physics closure receipt does not recompute")
    receipt_bytes = receipt_path.read_bytes()
    expected_checksums = (
        f"{_sha256_bytes(manifest_bytes)}  {manifest_path.name}\n"
        f"{_sha256_bytes(receipt_bytes)}  {receipt_path.name}\n"
    ).encode("ascii")
    if checksum_path.read_bytes() != expected_checksums:
        raise ValueError("advanced-physics closure checksum file drifted")
    return manifest, receipt


__all__ = [
    "CLAIM_BOUNDARY",
    "EVIDENCE_CLASS",
    "EVIDENCE_SOURCES",
    "MANIFEST_SCHEMA_VERSION",
    "RECEIPT_SCHEMA_VERSION",
    "export_advanced_physics_closure",
    "verify_advanced_physics_closure",
]
