"""Freeze and verify the real-PX4 advanced-physics evidence campaign.

The raw campaign is intentionally left untouched.  Every raw file is inventoried
by exact byte length and SHA-256, while the bundle retains only the material
needed to audit the claims.  The authoritative success ULog is stored with a
deterministic gzip frame (level 9, mtime 0).
"""

from __future__ import annotations

import gzip
import hashlib
import json
import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Any

from app.simulator.scenario_effects import scenario_effect_request_sha256

MANIFEST_SCHEMA_VERSION = "dronedream.advanced-physics-real-px4-manifest.v1"
RECEIPT_SCHEMA_VERSION = "dronedream.advanced-physics-real-px4-receipt.v1"
EXECUTION_WINDOW_SCHEMA_VERSION = "dronedream.advanced-physics-execution-window/v1"
CLAIM_LABEL = "PHYSICAL_SIMULATION"
EVIDENCE_CLASS = "REAL_PX4_GAZEBO_ADVANCED_PHYSICS"
CLAIM_BOUNDARY = (
    "Real PX4 SITL and Gazebo evidence for request-bound Trial-local effect "
    "injection and readback. It is not real-aircraft evidence. The GPS-noise "
    "boundary proves injection/readback before a PX4 readiness timeout; it does "
    "not claim a successful GPS-noise flight."
)
RETENTION_POLICY_ID = "dronedream.minimum-sufficient-advanced-physics-retention/v1"

_COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_UTC_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")

_EXPECTED_JOB_ID = "advanced-physics-real-px4-26b957e"
_EXPECTED_CANDIDATE_ID = "baseline-mpc-xy-p-0.95"
_EXPECTED_SEED = 42001
_EXPECTED_PX4_COMMIT = "6ea3539157ca358c70a515878b77077af7d4611d"
_EXPECTED_PX4_VERSION = "v1.16"
_SUCCESS_EFFECTS = (
    "battery.mass_payload_kg",
    "scenario_type.actuator_delay",
    "sensor_degradation.baro_noise_m",
    "sensor_degradation.imu_noise_scale",
    "wind_gusts",
)
_GPS_BOUNDARY_EFFECTS = (
    "battery.mass_payload_kg",
    "scenario_type.actuator_delay",
    "sensor_degradation.baro_noise_m",
    "sensor_degradation.gps_noise_m",
    "sensor_degradation.imu_noise_scale",
    "wind_gusts",
)
_REQUIRES_RUNTIME_EXTENSION = (
    "probabilistic GPS dropout",
    "battery initial state and voltage sag",
    "hard actuator failure beyond the bounded first-order delay profile",
)

_RETAINED_COMMON = frozenset(
    {
        "execution-window.json",
        "execution-window.log",
        "launch_config.json",
        "runner.log",
        "scenario_config.json",
        "scenario_effects.applied.json",
        "scenario_effects.request.json",
        "simulator_runtime_manifest.json",
        "stderr.log",
        "stdout.log",
        "trial-input.json",
        "trial-result.json",
    }
)
_RETAINED_AUTHORITY = frozenset(
    {
        "controller_params.json",
        "controller_params.used.json",
        "offboard_executor.log",
        "offboard_timing.json",
        "px4_parameters.applied.json",
        "px4_parameters.before.json",
        "px4_parameters.input.json",
        "px4_parameters.requested.json",
        "reference_track.json",
    }
)
_RETAINED_RUNTIME_READBACK = frozenset(
    {
        "scenario_runtime/generated_world.last_attempt.sdf",
        "scenario_runtime/generated_world.sdf",
        "scenario_runtime/models/x500/model.sdf",
        "scenario_runtime/models/x500_base/model.sdf",
        "scenario_runtime/px4_rootfs/gz_env.sh",
        "scenario_runtime/worlds/default.sdf",
    }
)


@dataclass(frozen=True)
class AdvancedPhysicsAttemptSpec:
    """Expected semantic role and outcome for one raw campaign directory."""

    directory: str
    role: str
    expected_success: bool
    expected_effects: tuple[str, ...]
    authoritative: bool = False


ATTEMPT_SPECS = (
    AdvancedPhysicsAttemptSpec(
        "success-five-effects",
        "file_backed_preflight_failure",
        False,
        (),
    ),
    AdvancedPhysicsAttemptSpec(
        "success-five-effects-attempt-2",
        "repeat_success",
        True,
        _SUCCESS_EFFECTS,
    ),
    AdvancedPhysicsAttemptSpec(
        "success-five-effects-attempt-3",
        "repeat_success",
        True,
        _SUCCESS_EFFECTS,
    ),
    AdvancedPhysicsAttemptSpec(
        "success-five-effects-attempt-4",
        "authoritative_success",
        True,
        _SUCCESS_EFFECTS,
        authoritative=True,
    ),
    AdvancedPhysicsAttemptSpec(
        "gps-readiness-boundary",
        "repeat_gps_readiness_boundary",
        False,
        _GPS_BOUNDARY_EFFECTS,
    ),
    AdvancedPhysicsAttemptSpec(
        "gps-readiness-boundary-attempt-2",
        "authoritative_gps_readiness_boundary",
        False,
        _GPS_BOUNDARY_EFFECTS,
        authoritative=True,
    ),
)

_TERMINAL_ONLY_PREFLIGHTS = (
    {
        "sequence": 1,
        "failure": "windows_to_wsl_command_marshalling",
        "recorded_at": "2026-07-28T20:09:24Z",
        "raw_artifact_available": False,
        "machine_verified": False,
    },
    {
        "sequence": 2,
        "failure": "wsl_git_could_not_parse_windows_worktree_pointer",
        "recorded_at": None,
        "raw_artifact_available": False,
        "machine_verified": False,
    },
    {
        "sequence": 3,
        "failure": "process_probe_false_positive_from_path_text",
        "recorded_at": None,
        "raw_artifact_available": False,
        "machine_verified": False,
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


def _sha256_value(value: object) -> str:
    return _sha256_bytes(_canonical_bytes(value))


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"could not load JSON evidence {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"JSON evidence must be an object: {path}")
    return value


def _mapping(value: object, *, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{field} must be an object")
    return value


def _list_of_strings(value: object, *, field: str) -> list[str]:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise ValueError(f"{field} must be a string list")
    return value


def _require_commit(value: object, *, field: str) -> str:
    if not isinstance(value, str) or _COMMIT_RE.fullmatch(value) is None:
        raise ValueError(f"{field} must be a full lowercase Git commit")
    return value


def _require_sha256(value: object, *, field: str) -> str:
    if not isinstance(value, str) or _SHA256_RE.fullmatch(value) is None:
        raise ValueError(f"{field} must be a lowercase SHA-256")
    return value


def _require_utc(value: object, *, field: str) -> str:
    if not isinstance(value, str) or _UTC_RE.fullmatch(value) is None:
        raise ValueError(f"{field} must be a whole-second UTC timestamp")
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{field} is not a valid UTC timestamp") from exc
    return value


def _finite(value: object, *, field: str) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, int | float)
        or not math.isfinite(float(value))
    ):
        raise ValueError(f"{field} must be finite")
    return float(value)


def _safe_relative_path(value: object, *, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{field} must be a non-empty relative path")
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or "\\" in value:
        raise ValueError(f"{field} is unsafe")
    return str(path)


def _identity(
    payload: Mapping[str, Any],
    *,
    field: str,
) -> dict[str, Any]:
    identity = _mapping(payload.get("execution_identity"), field=f"{field}.identity")
    if (
        identity.get("job_id") != _EXPECTED_JOB_ID
        or identity.get("candidate_id") != _EXPECTED_CANDIDATE_ID
        or identity.get("seed") != _EXPECTED_SEED
        or isinstance(identity.get("attempt_count"), bool)
        or not isinstance(identity.get("attempt_count"), int)
        or not isinstance(identity.get("trial_id"), str)
        or not identity.get("trial_id")
    ):
        raise ValueError(f"{field} execution identity is invalid")
    return dict(identity)


def _validate_execution_window(
    trial_dir: Path,
    *,
    spec: AdvancedPhysicsAttemptSpec,
    subject_commit: str,
) -> dict[str, Any]:
    path = trial_dir / "execution-window.json"
    if not spec.authoritative:
        if path.exists():
            raise ValueError(f"{spec.directory} unexpectedly has an authority window")
        return {"present": False}
    window = _load_json(path)
    if (
        window.get("schema_version") != EXECUTION_WINDOW_SCHEMA_VERSION
        or window.get("subject_commit") != subject_commit
        or window.get("source_preflight") != "windows_git_head_and_tracked_diff"
        or window.get("runtime_user") != "dronedream"
        or window.get("run_name") != spec.directory
        or window.get("runner_exit_code") != 0
        or window.get("preexisting_process_count") != 0
        or window.get("residual_process_count") != 0
        or isinstance(window.get("duration_seconds"), bool)
        or not isinstance(window.get("duration_seconds"), int)
        or int(window["duration_seconds"]) <= 0
    ):
        raise ValueError(f"{spec.directory} execution window is invalid")
    started_at = _require_utc(
        window.get("started_at"),
        field=f"{spec.directory}.started_at",
    )
    ended_at = _require_utc(
        window.get("ended_at"),
        field=f"{spec.directory}.ended_at",
    )
    if ended_at <= started_at:
        raise ValueError(f"{spec.directory} execution window is not chronological")
    elapsed_seconds = int(
        (
            datetime.fromisoformat(ended_at.replace("Z", "+00:00"))
            - datetime.fromisoformat(started_at.replace("Z", "+00:00"))
        ).total_seconds()
    )
    if int(window["duration_seconds"]) != elapsed_seconds:
        raise ValueError(
            f"{spec.directory} execution window duration does not match timestamps"
        )
    return {
        "present": True,
        "started_at": started_at,
        "ended_at": ended_at,
        "duration_seconds": int(window["duration_seconds"]),
        "runner_exit_code": 0,
        "preexisting_process_count": 0,
        "residual_process_count": 0,
        "runtime_user": "dronedream",
        "source_preflight": "windows_git_head_and_tracked_diff",
    }


def _validate_effect_contract(
    trial_dir: Path,
    *,
    spec: AdvancedPhysicsAttemptSpec,
) -> tuple[dict[str, Any], dict[str, Any]]:
    request = _load_json(trial_dir / "scenario_effects.request.json")
    evidence = _load_json(trial_dir / "scenario_effects.applied.json")
    runtime = _load_json(trial_dir / "simulator_runtime_manifest.json")
    if request.get("schema_version") != "dronedream.scenario_effect_request.v1":
        raise ValueError(f"{spec.directory} request schema is invalid")
    if evidence.get("schema_version") != "dronedream.scenario_effect_evidence.v1":
        raise ValueError(f"{spec.directory} evidence schema is invalid")
    if runtime.get("schema_version") != "dronedream.simulator_runtime_manifest.v1":
        raise ValueError(f"{spec.directory} runtime manifest schema is invalid")

    request_identity = _identity(request, field=f"{spec.directory}.request")
    evidence_identity = _identity(evidence, field=f"{spec.directory}.evidence")
    runtime_identity = _identity(runtime, field=f"{spec.directory}.runtime")
    if request_identity != evidence_identity or request_identity != runtime_identity:
        raise ValueError(f"{spec.directory} effect identities drifted")

    request_rows = request.get("effects")
    evidence_rows = evidence.get("effects")
    if not isinstance(request_rows, list) or not isinstance(evidence_rows, list):
        raise ValueError(f"{spec.directory} effect rows are invalid")
    request_effects = [
        str(_mapping(row, field="request effect").get("effect_id")) for row in request_rows
    ]
    applied_effects = [
        str(_mapping(row, field="applied effect").get("effect_id")) for row in evidence_rows
    ]
    if sorted(request_effects) != list(spec.expected_effects):
        raise ValueError(f"{spec.directory} requested effects drifted")
    if sorted(applied_effects) != list(spec.expected_effects):
        raise ValueError(f"{spec.directory} applied effects drifted")
    if len(set(request_effects)) != len(request_effects):
        raise ValueError(f"{spec.directory} request repeats an effect")
    if len(set(applied_effects)) != len(applied_effects):
        raise ValueError(f"{spec.directory} evidence repeats an effect")
    for row in request_rows:
        item = _mapping(row, field="request effect")
        capability = _mapping(item.get("capability"), field="request capability")
        if capability.get("status") != "available":
            raise ValueError(f"{spec.directory} request capability is unavailable")
    for row in evidence_rows:
        item = _mapping(row, field="applied effect")
        capability = _mapping(item.get("capability"), field="evidence capability")
        verification = _mapping(item.get("evidence"), field="effect evidence").get("verification")
        if (
            item.get("status") != "applied"
            or capability.get("status") != "available"
            or not isinstance(verification, Mapping)
            or verification.get("status") != "verified"
        ):
            raise ValueError(f"{spec.directory} effect is not verified applied")

    request_sha = _require_sha256(
        request.get("request_sha256"),
        field=f"{spec.directory}.request_sha256",
    )
    if request_sha != scenario_effect_request_sha256(dict(request)):
        raise ValueError(f"{spec.directory} request hash does not recompute")
    if evidence.get("request_sha256") != request_sha:
        raise ValueError(f"{spec.directory} evidence request hash drifted")
    contract = _mapping(
        runtime.get("scenario_effect_contract"),
        field=f"{spec.directory}.scenario_effect_contract",
    )
    if (
        contract.get("verification_status") != "verified_applied"
        or sorted(
            _list_of_strings(
                contract.get("requested_effects"),
                field="contract.requested_effects",
            )
        )
        != list(spec.expected_effects)
        or sorted(
            _list_of_strings(
                contract.get("applied_effects"),
                field="contract.applied_effects",
            )
        )
        != list(spec.expected_effects)
        or contract.get("unsupported_effects") != []
        or contract.get("failed_effects") != []
        or contract.get("pending_effects") != []
        or contract.get("request_sha256") != request_sha
    ):
        raise ValueError(f"{spec.directory} runtime effect contract drifted")
    runtime_request = _mapping(
        runtime.get("scenario_effect_request"),
        field="runtime.scenario_effect_request",
    )
    runtime_evidence = _mapping(
        runtime.get("scenario_effect_evidence"),
        field="runtime.scenario_effect_evidence",
    )
    if (
        runtime_request.get("request_sha256") != request_sha
        or runtime_evidence.get("verification_status") != "verified_applied"
        or runtime_evidence.get("required") is not True
    ):
        raise ValueError(f"{spec.directory} runtime references drifted")
    firmware = _mapping(
        runtime.get("firmware_identity"),
        field=f"{spec.directory}.firmware_identity",
    )
    if (
        firmware.get("status") != "verified"
        or firmware.get("observed_source") != "git_head"
        or firmware.get("observed_commit") != _EXPECTED_PX4_COMMIT
        or firmware.get("requested_commit") != _EXPECTED_PX4_COMMIT
        or runtime.get("px4_version") != _EXPECTED_PX4_VERSION
    ):
        raise ValueError(f"{spec.directory} PX4 identity is invalid")
    return request_identity, {
        "request_sha256": request_sha,
        "requested_effects": list(spec.expected_effects),
        "applied_effects": list(spec.expected_effects),
        "verification_status": "verified_applied",
        "unsupported_effects": [],
        "failed_effects": [],
        "pending_effects": [],
    }


def _validate_attempt(
    trial_dir: Path,
    *,
    spec: AdvancedPhysicsAttemptSpec,
    subject_commit: str,
    require_large_raw: bool = True,
) -> dict[str, Any]:
    if not trial_dir.is_dir():
        raise ValueError(f"campaign attempt is missing: {spec.directory}")
    trial_input = _load_json(trial_dir / "trial-input.json")
    result = _load_json(trial_dir / "trial-result.json")
    input_identity = _identity(trial_input, field=f"{spec.directory}.input")
    result_identity = _identity(result, field=f"{spec.directory}.result")
    if input_identity != result_identity:
        raise ValueError(f"{spec.directory} Trial identities drifted")
    if result.get("schema_version") != "dronedream.trial_result.v2":
        raise ValueError(f"{spec.directory} result schema is invalid")
    if result.get("success") is not spec.expected_success:
        raise ValueError(f"{spec.directory} outcome drifted")

    execution_window = _validate_execution_window(
        trial_dir,
        spec=spec,
        subject_commit=subject_commit,
    )
    if spec.role == "file_backed_preflight_failure":
        failure = _mapping(result.get("failure"), field=f"{spec.directory}.failure")
        reason = failure.get("reason")
        if (
            failure.get("code") != "SIMULATION_FAILED"
            or not isinstance(reason, str)
            or "dubious ownership" not in reason
            or "safe.directory" not in reason
            or (trial_dir / "scenario_effects.applied.json").exists()
        ):
            raise ValueError(f"{spec.directory} preflight failure drifted")
        return {
            "directory": spec.directory,
            "role": spec.role,
            "authoritative": False,
            "execution_identity": result_identity,
            "success": False,
            "failure_code": "SIMULATION_FAILED",
            "failure_reason": reason,
            "execution_window": execution_window,
        }

    effect_identity, effect_summary = _validate_effect_contract(
        trial_dir,
        spec=spec,
    )
    if effect_identity != result_identity:
        raise ValueError(f"{spec.directory} Trial/effect identity drifted")
    summary: dict[str, Any] = {
        "directory": spec.directory,
        "role": spec.role,
        "authoritative": spec.authoritative,
        "execution_identity": result_identity,
        "success": spec.expected_success,
        "effect_evidence": effect_summary,
        "execution_window": execution_window,
    }
    if spec.expected_success:
        metrics = _mapping(result.get("metrics"), field=f"{spec.directory}.metrics")
        raw_metrics = _mapping(
            metrics.get("raw_metric_json"),
            field=f"{spec.directory}.raw_metrics",
        )
        if metrics.get("pass_flag") is not True:
            raise ValueError(f"{spec.directory} did not pass")
        summary["pass_flag"] = True
        summary["metrics"] = {
            "rmse_m": _finite(metrics.get("rmse"), field="metrics.rmse"),
            "max_error_m": _finite(
                metrics.get("max_error"),
                field="metrics.max_error",
            ),
            "completion_time_s": _finite(
                metrics.get("completion_time"),
                field="metrics.completion_time",
            ),
            "score": _finite(metrics.get("score"), field="metrics.score"),
            "evaluation_track_coverage": _finite(
                raw_metrics.get("evaluation_track_coverage"),
                field="raw_metrics.evaluation_track_coverage",
            ),
        }
        if spec.authoritative and require_large_raw:
            for required in ("px4_source.ulg", "telemetry.json"):
                if not (trial_dir / required).is_file():
                    raise ValueError(f"{spec.directory} lacks authoritative {required}")
    else:
        failure = _mapping(result.get("failure"), field=f"{spec.directory}.failure")
        stderr = (trial_dir / "stderr.log").read_text(encoding="utf-8")
        if (
            failure.get("code") != "SIMULATION_FAILED"
            or failure.get("reason") != "lower-level launcher exited with code 1"
            or "PX4 readiness timeout after 30.0s" not in stderr
            or result.get("metrics") is not None
        ):
            raise ValueError(f"{spec.directory} readiness boundary drifted")
        summary.update(
            {
                "pass_flag": None,
                "metrics": None,
                "failure_code": "SIMULATION_FAILED",
                "failure_reason": "lower-level launcher exited with code 1",
                "boundary": (
                    "All requested effects were verified applied in generated "
                    "runtime SDF before PX4 readiness timed out; no successful "
                    "GPS-noise flight is claimed."
                ),
            }
        )
    return summary


def _should_retain(relative: str, spec: AdvancedPhysicsAttemptSpec) -> bool:
    if spec.role == "file_backed_preflight_failure":
        return True
    if relative in _RETAINED_COMMON or relative in _RETAINED_RUNTIME_READBACK:
        return True
    if spec.authoritative and relative in _RETAINED_AUTHORITY:
        return True
    return spec.role == "authoritative_success" and relative in {
        "px4_source.ulg",
        "telemetry.json",
    }


def _omission_reason(relative: str) -> str:
    if relative.startswith("scenario_runtime/px4_rootfs/"):
        return "regenerable_trial_local_px4_rootfs_copy"
    if relative.startswith("scenario_runtime/models/"):
        return "regenerable_model_asset_not_needed_beyond_retained_sdf_readback"
    if relative.startswith("scenario_runtime/"):
        return "regenerable_trial_local_runtime_overlay"
    if relative == "px4_source.ulg":
        return "repeat_or_boundary_ulog_not_needed_for_authoritative_flight_claim"
    if relative == "telemetry.json":
        return "repeat_success_telemetry_summarized_by_retained_trial_result"
    if relative in {"trajectory.json", "reference_track.used.json"}:
        return "derived_or_duplicate_of_retained_evidence"
    return "not_required_by_minimum_sufficient_retention_policy"


def _write_exact(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    created = False
    try:
        with path.open("xb") as handle:
            created = True
            handle.write(payload)
    except FileExistsError as exc:
        raise ValueError(f"refusing to replace frozen evidence file: {path}") from exc
    except Exception:
        if created:
            path.unlink(missing_ok=True)
        raise


def _inventory_and_retain(
    trial_dir: Path,
    *,
    spec: AdvancedPhysicsAttemptSpec,
    output_root: Path,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    records: list[dict[str, Any]] = []
    source_bytes = 0
    retained_bytes = 0
    source_entries = list(trial_dir.rglob("*"))
    linked_entries = sorted(
        path.relative_to(trial_dir).as_posix() for path in source_entries if path.is_symlink()
    )
    if linked_entries:
        raise ValueError(
            "advanced-physics evidence source must not contain symbolic links: "
            + ", ".join(linked_entries)
        )
    source_files = sorted(
        (
            (path.relative_to(trial_dir).as_posix(), path)
            for path in source_entries
            if path.is_file()
        ),
        key=lambda item: item[0],
    )
    for relative, path in source_files:
        size = path.stat().st_size
        digest = _sha256_file(path)
        source_bytes += size
        record: dict[str, Any] = {
            "source_path": relative,
            "source_bytes": size,
            "source_sha256": digest,
            "retained": False,
        }
        if _should_retain(relative, spec):
            retained_base = PurePosixPath("attempts") / spec.directory / PurePosixPath(relative)
            if relative == "px4_source.ulg":
                retained_path = f"{retained_base}.gz"
                raw = path.read_bytes()
                retained = gzip.compress(raw, compresslevel=9, mtime=0)
                compression = "gzip-level-9-mtime-0"
            else:
                retained_path = str(retained_base)
                retained = path.read_bytes()
                compression = "none"
            _write_exact(output_root / PurePosixPath(retained_path), retained)
            record.update(
                {
                    "retained": True,
                    "retained_path": retained_path,
                    "retained_bytes": len(retained),
                    "retained_sha256": _sha256_bytes(retained),
                    "compression": compression,
                }
            )
            retained_bytes += len(retained)
        else:
            record["omission_reason"] = _omission_reason(relative)
        records.append(record)
    return records, {
        "source_file_count": len(records),
        "source_bytes": source_bytes,
        "retained_file_count": sum(item["retained"] is True for item in records),
        "retained_bytes": retained_bytes,
    }


def _inventory_sha256(inventory: Sequence[Mapping[str, Any]]) -> str:
    return _sha256_value(
        [
            {
                "source_path": row["source_path"],
                "source_bytes": row["source_bytes"],
                "source_sha256": row["source_sha256"],
            }
            for row in inventory
        ]
    )


def export_advanced_physics_evidence(
    *,
    source_root: Path,
    output_root: Path,
    subject_commit: str,
    exporter_commit: str,
    generated_at: str,
    attempt_specs: Sequence[AdvancedPhysicsAttemptSpec] = ATTEMPT_SPECS,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Export a deterministic retained bundle plus complete raw inventory."""

    subject_commit = _require_commit(subject_commit, field="subject_commit")
    exporter_commit = _require_commit(exporter_commit, field="exporter_commit")
    generated_at = _require_utc(generated_at, field="generated_at")
    if tuple(attempt_specs) != ATTEMPT_SPECS:
        raise ValueError("advanced-physics campaign attempt matrix drifted")
    if output_root.exists() and any(output_root.iterdir()):
        raise ValueError(f"output directory must be absent or empty: {output_root}")
    output_root.mkdir(parents=True, exist_ok=True)

    attempts: list[dict[str, Any]] = []
    full_inventory: list[dict[str, Any]] = []
    aggregate = {
        "source_file_count": 0,
        "source_bytes": 0,
        "retained_file_count": 0,
        "retained_bytes": 0,
    }
    for spec in attempt_specs:
        trial_dir = source_root / spec.directory
        summary = _validate_attempt(
            trial_dir,
            spec=spec,
            subject_commit=subject_commit,
        )
        inventory, counts = _inventory_and_retain(
            trial_dir,
            spec=spec,
            output_root=output_root,
        )
        summary["source_inventory"] = inventory
        summary["source_inventory_sha256"] = _inventory_sha256(inventory)
        summary["retention_summary"] = counts
        attempts.append(summary)
        full_inventory.extend(
            {
                **row,
                "source_path": f"{spec.directory}/{row['source_path']}",
            }
            for row in inventory
        )
        for key in aggregate:
            aggregate[key] += counts[key]

    successful = [item for item in attempts if item["success"] is True]
    boundaries = [item for item in attempts if "gps_readiness_boundary" in str(item["role"])]
    unsigned_manifest: dict[str, Any] = {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "evidence_class": EVIDENCE_CLASS,
        "claim_label": CLAIM_LABEL,
        "claim_boundary": CLAIM_BOUNDARY,
        "generated_at": generated_at,
        "subject_commit": subject_commit,
        "exporter_commit": exporter_commit,
        "physical_fidelity": True,
        "real_aircraft_fidelity": False,
        "network_calls": 0,
        "real_credentials_used": False,
        "protocol": {
            "campaign_seed": _EXPECTED_SEED,
            "candidate_id": _EXPECTED_CANDIDATE_ID,
            "job_id": _EXPECTED_JOB_ID,
            "simulator": "px4_gazebo",
            "vehicle": "x500",
            "world": "default",
            "successful_flight_effects": list(_SUCCESS_EFFECTS),
            "gps_readiness_boundary_effects": list(_GPS_BOUNDARY_EFFECTS),
            "unsupported_effects_included": False,
        },
        "runtime_identity": {
            "px4_commit": _EXPECTED_PX4_COMMIT,
            "px4_version": _EXPECTED_PX4_VERSION,
            "runtime_user": "dronedream",
            "identity_source": (
                "per-Trial firmware Git readback plus authoritative execution windows"
            ),
            "gazebo_version_claimed": False,
            "wsl_runtime_id_claimed": False,
        },
        "summary": {
            "attempt_count": len(attempts),
            "successful_flight_count": len(successful),
            "passing_flight_count": sum(item.get("pass_flag") is True for item in attempts),
            "gps_readiness_boundary_count": len(boundaries),
            "file_backed_preflight_failure_count": sum(
                item["role"] == "file_backed_preflight_failure" for item in attempts
            ),
            "terminal_only_preflight_count": len(_TERMINAL_ONLY_PREFLIGHTS),
            "authoritative_success_directory": "success-five-effects-attempt-4",
            "authoritative_boundary_directory": ("gps-readiness-boundary-attempt-2"),
            **aggregate,
            "full_source_inventory_sha256": _inventory_sha256(full_inventory),
        },
        "attempts": attempts,
        "terminal_only_preflights": {
            "claim": (
                "These operator-observed preflight failures produced no raw files. "
                "They are retained as an honest narrative timeline only, excluded "
                "from machine-verified counts, and have no invented hashes."
            ),
            "attempts": list(_TERMINAL_ONLY_PREFLIGHTS),
        },
        "remaining_runtime_extensions": list(_REQUIRES_RUNTIME_EXTENSION),
        "retention_policy": {
            "policy_id": RETENTION_POLICY_ID,
            "all_source_files_inventoried": True,
            "raw_source_deleted": False,
            "authoritative_ulog_retained": True,
            "ulog_compression": "gzip-level-9-mtime-0",
            "authoritative_telemetry_retained": True,
            "effect_request_and_readback_retained": True,
            "runtime_sdf_readback_retained": True,
            "failure_logs_retained": True,
            "omitted_regenerable_runtime_rootfs_copies": True,
        },
    }
    manifest = {
        **unsigned_manifest,
        "manifest_sha256": _sha256_value(unsigned_manifest),
    }
    manifest_bytes = _pretty_bytes(manifest)
    manifest_path = output_root / "advanced-physics-real-px4-v1.manifest.json"
    _write_exact(manifest_path, manifest_bytes)

    unsigned_receipt: dict[str, Any] = {
        "schema_version": RECEIPT_SCHEMA_VERSION,
        "generated_at": generated_at,
        "subject_commit": subject_commit,
        "exporter_commit": exporter_commit,
        "claim_boundary": CLAIM_BOUNDARY,
        "manifest": {
            "path": manifest_path.name,
            "bytes": len(manifest_bytes),
            "sha256": _sha256_bytes(manifest_bytes),
            "manifest_sha256": manifest["manifest_sha256"],
        },
        "result": {
            "status": "passed",
            "attempt_count": 6,
            "successful_flights": 3,
            "passing_flights": 3,
            "gps_readiness_boundaries": 2,
            "file_backed_preflight_failures": 1,
            "terminal_only_preflights": 3,
        },
        "px4_commit": _EXPECTED_PX4_COMMIT,
        "network_calls": 0,
        "real_credentials_used": False,
    }
    receipt = {
        **unsigned_receipt,
        "receipt_sha256": _sha256_value(unsigned_receipt),
    }
    receipt_bytes = _pretty_bytes(receipt)
    receipt_path = output_root / "advanced-physics-real-px4-v1.receipt.json"
    _write_exact(receipt_path, receipt_bytes)
    digest_path = output_root / "advanced-physics-real-px4-v1.sha256"
    _write_exact(
        digest_path,
        (
            f"{_sha256_bytes(manifest_bytes)}  {manifest_path.name}\n"
            f"{_sha256_bytes(receipt_bytes)}  {receipt_path.name}\n"
        ).encode("ascii"),
    )
    return manifest, receipt


def _verify_retained_inventory(
    *,
    evidence_root: Path,
    attempt: Mapping[str, Any],
    source_root: Path | None,
) -> None:
    directory = _safe_relative_path(attempt.get("directory"), field="attempt.directory")
    inventory = attempt.get("source_inventory")
    if not isinstance(inventory, list):
        raise ValueError(f"{directory} source inventory is invalid")
    if attempt.get("source_inventory_sha256") != _inventory_sha256(inventory):
        raise ValueError(f"{directory} source inventory hash drifted")
    seen_source: set[str] = set()
    for raw_row in inventory:
        row = _mapping(raw_row, field=f"{directory} inventory row")
        source_path = _safe_relative_path(
            row.get("source_path"),
            field=f"{directory}.source_path",
        )
        if source_path in seen_source:
            raise ValueError(f"{directory} source inventory repeats {source_path}")
        seen_source.add(source_path)
        source_bytes = row.get("source_bytes")
        if isinstance(source_bytes, bool) or not isinstance(source_bytes, int) or source_bytes < 0:
            raise ValueError(f"{directory} source byte count is invalid")
        source_sha = _require_sha256(
            row.get("source_sha256"),
            field=f"{directory}.{source_path}.source_sha256",
        )
        if row.get("retained") is True:
            retained_path = _safe_relative_path(
                row.get("retained_path"),
                field=f"{directory}.{source_path}.retained_path",
            )
            retained_file = evidence_root / PurePosixPath(retained_path)
            if (
                not retained_file.is_file()
                or retained_file.stat().st_size != row.get("retained_bytes")
                or _sha256_file(retained_file) != row.get("retained_sha256")
            ):
                raise ValueError(f"retained evidence drifted: {retained_path}")
            compression = row.get("compression")
            if compression == "none":
                if (
                    retained_file.stat().st_size != source_bytes
                    or _sha256_file(retained_file) != source_sha
                ):
                    raise ValueError(f"retained source drifted: {retained_path}")
            elif compression == "gzip-level-9-mtime-0":
                compressed = retained_file.read_bytes()
                if len(compressed) < 10 or int.from_bytes(compressed[4:8], "little") != 0:
                    raise ValueError(f"retained gzip framing drifted: {retained_path}")
                try:
                    raw = gzip.decompress(compressed)
                except OSError as exc:
                    raise ValueError(f"retained gzip is invalid: {retained_path}") from exc
                if len(raw) != source_bytes or _sha256_bytes(raw) != source_sha:
                    raise ValueError(f"retained gzip source drifted: {retained_path}")
                if gzip.compress(raw, compresslevel=9, mtime=0) != compressed:
                    raise ValueError(f"retained gzip is not deterministic: {retained_path}")
            else:
                raise ValueError(f"unknown compression for {retained_path}")
        elif (
            row.get("retained") is not False
            or not isinstance(row.get("omission_reason"), str)
            or not row.get("omission_reason")
        ):
            raise ValueError(f"{directory} omission record is invalid")
        if source_root is not None:
            source_file = source_root / directory / PurePosixPath(source_path)
            if (
                not source_file.is_file()
                or source_file.stat().st_size != source_bytes
                or _sha256_file(source_file) != source_sha
            ):
                raise ValueError(
                    f"raw source no longer matches inventory: {directory}/{source_path}"
                )
    if source_root is not None:
        observed = {
            path.relative_to(source_root / directory).as_posix()
            for path in (source_root / directory).rglob("*")
            if path.is_file()
        }
        if observed != seen_source:
            raise ValueError(f"{directory} raw source file set drifted")


def verify_advanced_physics_evidence(
    *,
    evidence_root: Path,
    source_root: Path | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Verify bundle integrity and, optionally, every raw source byte."""

    manifest_path = evidence_root / "advanced-physics-real-px4-v1.manifest.json"
    receipt_path = evidence_root / "advanced-physics-real-px4-v1.receipt.json"
    digest_path = evidence_root / "advanced-physics-real-px4-v1.sha256"
    manifest = _load_json(manifest_path)
    receipt = _load_json(receipt_path)
    if manifest.get("schema_version") != MANIFEST_SCHEMA_VERSION:
        raise ValueError("advanced-physics manifest schema is invalid")
    if receipt.get("schema_version") != RECEIPT_SCHEMA_VERSION:
        raise ValueError("advanced-physics receipt schema is invalid")
    unsigned_manifest = {key: value for key, value in manifest.items() if key != "manifest_sha256"}
    unsigned_receipt = {key: value for key, value in receipt.items() if key != "receipt_sha256"}
    if manifest.get("manifest_sha256") != _sha256_value(unsigned_manifest):
        raise ValueError("advanced-physics manifest hash does not recompute")
    if receipt.get("receipt_sha256") != _sha256_value(unsigned_receipt):
        raise ValueError("advanced-physics receipt hash does not recompute")
    manifest_bytes = manifest_path.read_bytes()
    receipt_bytes = receipt_path.read_bytes()
    manifest_ref = _mapping(receipt.get("manifest"), field="receipt.manifest")
    if dict(manifest_ref) != {
        "path": manifest_path.name,
        "bytes": len(manifest_bytes),
        "sha256": _sha256_bytes(manifest_bytes),
        "manifest_sha256": manifest["manifest_sha256"],
    }:
        raise ValueError("advanced-physics receipt does not bind manifest")
    expected_digest = (
        f"{_sha256_bytes(manifest_bytes)}  {manifest_path.name}\n"
        f"{_sha256_bytes(receipt_bytes)}  {receipt_path.name}\n"
    ).encode("ascii")
    if digest_path.read_bytes() != expected_digest:
        raise ValueError("advanced-physics SHA-256 sidecar drifted")

    if (
        manifest.get("subject_commit") != receipt.get("subject_commit")
        or manifest.get("exporter_commit") != receipt.get("exporter_commit")
        or manifest.get("generated_at") != receipt.get("generated_at")
        or manifest.get("claim_boundary") != CLAIM_BOUNDARY
        or receipt.get("claim_boundary") != CLAIM_BOUNDARY
        or manifest.get("evidence_class") != EVIDENCE_CLASS
        or manifest.get("claim_label") != CLAIM_LABEL
        or manifest.get("physical_fidelity") is not True
        or manifest.get("real_aircraft_fidelity") is not False
        or manifest.get("network_calls") != 0
        or manifest.get("real_credentials_used") is not False
        or receipt.get("network_calls") != 0
        or receipt.get("real_credentials_used") is not False
    ):
        raise ValueError("advanced-physics claim boundary drifted")
    subject_commit = _require_commit(
        manifest.get("subject_commit"),
        field="subject_commit",
    )
    _require_commit(manifest.get("exporter_commit"), field="exporter_commit")
    _require_utc(manifest.get("generated_at"), field="generated_at")
    runtime = _mapping(manifest.get("runtime_identity"), field="runtime_identity")
    if (
        runtime.get("px4_commit") != _EXPECTED_PX4_COMMIT
        or runtime.get("px4_version") != _EXPECTED_PX4_VERSION
        or runtime.get("runtime_user") != "dronedream"
        or runtime.get("gazebo_version_claimed") is not False
        or runtime.get("wsl_runtime_id_claimed") is not False
        or receipt.get("px4_commit") != _EXPECTED_PX4_COMMIT
    ):
        raise ValueError("advanced-physics runtime identity drifted")
    protocol = _mapping(manifest.get("protocol"), field="protocol")
    if (
        protocol.get("campaign_seed") != _EXPECTED_SEED
        or protocol.get("candidate_id") != _EXPECTED_CANDIDATE_ID
        or protocol.get("job_id") != _EXPECTED_JOB_ID
        or protocol.get("successful_flight_effects") != list(_SUCCESS_EFFECTS)
        or protocol.get("gps_readiness_boundary_effects") != list(_GPS_BOUNDARY_EFFECTS)
        or protocol.get("unsupported_effects_included") is not False
    ):
        raise ValueError("advanced-physics protocol drifted")
    if manifest.get("remaining_runtime_extensions") != list(_REQUIRES_RUNTIME_EXTENSION):
        raise ValueError("advanced-physics remaining extensions drifted")
    retention = _mapping(manifest.get("retention_policy"), field="retention_policy")
    if (
        retention.get("policy_id") != RETENTION_POLICY_ID
        or retention.get("all_source_files_inventoried") is not True
        or retention.get("raw_source_deleted") is not False
        or retention.get("authoritative_ulog_retained") is not True
        or retention.get("ulog_compression") != "gzip-level-9-mtime-0"
        or retention.get("authoritative_telemetry_retained") is not True
        or retention.get("effect_request_and_readback_retained") is not True
        or retention.get("runtime_sdf_readback_retained") is not True
        or retention.get("failure_logs_retained") is not True
    ):
        raise ValueError("advanced-physics retention policy drifted")

    attempts = manifest.get("attempts")
    if not isinstance(attempts, list) or len(attempts) != len(ATTEMPT_SPECS):
        raise ValueError("advanced-physics attempt matrix is invalid")
    aggregate = {
        "source_file_count": 0,
        "source_bytes": 0,
        "retained_file_count": 0,
        "retained_bytes": 0,
    }
    full_inventory: list[dict[str, Any]] = []
    for attempt, spec in zip(attempts, ATTEMPT_SPECS, strict=True):
        item = _mapping(attempt, field="attempt")
        if (
            item.get("directory") != spec.directory
            or item.get("role") != spec.role
            or item.get("authoritative") is not spec.authoritative
            or item.get("success") is not spec.expected_success
        ):
            raise ValueError("advanced-physics attempt identity drifted")
        _verify_retained_inventory(
            evidence_root=evidence_root,
            attempt=item,
            source_root=source_root,
        )
        retained_dir = evidence_root / "attempts" / spec.directory
        semantic = _validate_attempt(
            retained_dir,
            spec=spec,
            subject_commit=subject_commit,
            require_large_raw=False,
        )
        for key in (
            "directory",
            "role",
            "authoritative",
            "execution_identity",
            "success",
            "effect_evidence",
            "execution_window",
            "pass_flag",
            "metrics",
            "failure_code",
            "failure_reason",
            "boundary",
        ):
            if key in semantic and item.get(key) != semantic[key]:
                raise ValueError(f"{spec.directory} retained semantic summary drifted: {key}")
        counts = _mapping(
            item.get("retention_summary"),
            field=f"{spec.directory}.retention_summary",
        )
        for key in aggregate:
            value = counts.get(key)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"{spec.directory} retention count is invalid")
            aggregate[key] += value
        inventory = item["source_inventory"]
        full_inventory.extend(
            {
                **row,
                "source_path": f"{spec.directory}/{row['source_path']}",
            }
            for row in inventory
        )

    terminal = _mapping(
        manifest.get("terminal_only_preflights"),
        field="terminal_only_preflights",
    )
    if terminal.get("attempts") != list(_TERMINAL_ONLY_PREFLIGHTS):
        raise ValueError("terminal-only preflight history drifted")
    summary = _mapping(manifest.get("summary"), field="summary")
    expected_summary = {
        "attempt_count": 6,
        "successful_flight_count": 3,
        "passing_flight_count": 3,
        "gps_readiness_boundary_count": 2,
        "file_backed_preflight_failure_count": 1,
        "terminal_only_preflight_count": 3,
        "authoritative_success_directory": "success-five-effects-attempt-4",
        "authoritative_boundary_directory": "gps-readiness-boundary-attempt-2",
        **aggregate,
        "full_source_inventory_sha256": _inventory_sha256(full_inventory),
    }
    if dict(summary) != expected_summary:
        raise ValueError("advanced-physics summary does not recompute")
    if receipt.get("result") != {
        "status": "passed",
        "attempt_count": 6,
        "successful_flights": 3,
        "passing_flights": 3,
        "gps_readiness_boundaries": 2,
        "file_backed_preflight_failures": 1,
        "terminal_only_preflights": 3,
    }:
        raise ValueError("advanced-physics receipt result drifted")
    return manifest, receipt


__all__ = [
    "ATTEMPT_SPECS",
    "AdvancedPhysicsAttemptSpec",
    "CLAIM_BOUNDARY",
    "EVIDENCE_CLASS",
    "MANIFEST_SCHEMA_VERSION",
    "RECEIPT_SCHEMA_VERSION",
    "export_advanced_physics_evidence",
    "verify_advanced_physics_evidence",
]
