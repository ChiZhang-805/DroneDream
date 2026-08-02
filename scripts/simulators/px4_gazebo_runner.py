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
import contextlib
import csv
import hashlib
import io
import json
import math
import os
import random
import re
import shlex
import shutil
import signal
import stat
import subprocess
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# The runner is intentionally executable as a standalone REAL_SIMULATOR_COMMAND.
# When Python is given a script path, it places the script's directory (rather
# than the repository root) on sys.path, so the sibling backend package would
# otherwise be invisible unless callers manually set PYTHONPATH.  Resolve the
# checkout/runtime layout here to keep local, CI, and bundled WSL launches
# identical.
_BACKEND_ROOT = Path(__file__).resolve().parents[2] / "backend"
if _BACKEND_ROOT.is_dir() and str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

from app.parameters import (  # noqa: E402 - path bootstrap must precede backend imports
    ParameterValueValidationError,
    get_parameter,
    normalize_px4_version,
    validate_parameter_values,
)
from app.simulator.px4_metric_evidence import (  # noqa: E402 - see path bootstrap above
    Px4CoreMetricEvidenceError,
    compile_px4_core_metric_evidence,
    compile_px4_evaluation_policy,
    compile_px4_evaluation_window_evidence,
    compile_px4_outcome_evidence,
    require_px4_core_metric_binding,
    require_px4_evaluation_window_binding,
    require_px4_outcome_binding,
)
from app.simulator.px4_parameters import (  # noqa: E402 - see path bootstrap above
    APPLIED_EVIDENCE_NAME,
    BEFORE_EVIDENCE_NAME,
    REQUESTED_EVIDENCE_NAME,
    write_simulated_parameter_evidence,
)
from app.simulator.scenario_effects import (  # noqa: E402 - see path bootstrap above
    EVIDENCE_ARTIFACT_NAME,
    MAX_EFFECT_CONTRACT_BYTES,
    REQUEST_ARTIFACT_NAME,
    ScenarioEffectContractError,
    build_scenario_effect_request,
    load_scenario_effect_evidence,
    validate_scenario_effect_request,
)
from app.simulator.scenario_effects import (  # noqa: E402 - see path bootstrap above
    write_json_atomic as write_effect_json_atomic,
)
from app.simulator.telemetry_evidence import (  # noqa: E402 - see path bootstrap above
    TELEMETRY_SCHEMA_V2,
    TelemetrySemanticContractError,
    compile_sampling_evidence,
    compile_telemetry_semantic_contract,
    require_sampling_quality,
    verify_telemetry_semantic_contract,
)

FAILURE_ADAPTER_UNAVAILABLE = "ADAPTER_UNAVAILABLE"
FAILURE_TIMEOUT = "TIMEOUT"
FAILURE_SIMULATION = "SIMULATION_FAILED"
FAILURE_UNSUPPORTED_SCENARIO_EFFECT = "UNSUPPORTED_SCENARIO_EFFECT"
_MAX_SLOW_SIMULATION_TIMEOUT_MULTIPLIER = 10.0
_MAX_TELEMETRY_BYTES = 16 * 1024 * 1024
_MAX_TELEMETRY_SAMPLES = 50_000
_MAX_TRIAL_INPUT_BYTES = 8 * 1024 * 1024
_MAX_OFFBOARD_TIMING_BYTES = 1024 * 1024
_MAX_LAUNCHER_FAILURE_BYTES = 64 * 1024
_MAX_ENGINE_PACK_MANIFEST_BYTES = 8 * 1024 * 1024
_MAX_ENGINE_PACK_STATE_BYTES = 64 * 1024
_MAX_REFERENCE_TRACK_POINTS = 10_000
_HOVER_DURATION_SECONDS = 10.0
_HOVER_REFERENCE_SAMPLE_COUNT = 101
_HOVER_MIN_EVALUATION_DURATION_SECONDS = 10.0
_MAX_ID_LENGTH = 256
_PROJECTION_BACKTRACK_SEGMENTS = 16
_PROJECTION_FORWARD_SEGMENTS = 64
_PROJECTION_GLOBAL_RESCAN_INTERVAL = 256
_PROJECTION_GLOBAL_RESCAN_DISTANCE_M = 2.0
_PROJECTION_LOCAL_ERROR_FALLBACK_M = 5.0
_MAX_PROJECTION_SEGMENT_COMPARISONS = 10_000_000
_MAX_COVERAGE_PROGRESS_STEP_FRACTION = 0.2

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
    "px4_params_json",
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
    "airframe",
    "simulator_model",
    "world",
    "px4_version",
    "headless",
    "extra_args",
    "scenario_config_json",
    "scenario_effect_request_json",
    "scenario_effect_evidence_json",
    "instance_id",
    "simulation_speed_factor",
    "px4_executable",
    "gazebo_executable",
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
    px4_version: str
    enforce_safe_parameter_bounds: bool
    allow_unverified_advanced_effects: bool


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


@dataclass(frozen=True)
class TrackSegment:
    start: tuple[float, float, float]
    delta: tuple[float, float, float]
    length: float
    start_progress: float


@dataclass(frozen=True)
class TrackGeometry:
    segments: tuple[TrackSegment, ...]
    total_length: float
    closed: bool
    stationary: bool = False


@dataclass(frozen=True)
class TrackProjection:
    error: float
    segment_index: int
    segment_fraction: float
    progress: float
    reference_x: float
    reference_y: float
    reference_z: float


@dataclass(frozen=True)
class TrackProgressEvaluation:
    coverage: float
    directed_progress_fraction: float
    backward_distance: float
    discontinuity_count: int
    start_progress: float | None
    end_progress: float | None


class RunnerError(Exception):
    """Expected runner-level exception that maps to SIMULATION_FAILED."""


class TimeoutRunnerError(RunnerError):
    """Raised when lower-level simulator exceeds timeout."""


class ConfigurationRunnerError(RunnerError):
    """Raised when worker-level PX4/Gazebo configuration is invalid."""


class UnsupportedScenarioEffectRunnerError(RunnerError):
    """Raised before launch when requested physics are not implemented."""


_SAFE_PROFILE_TOKEN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
_REQUESTED_FIRMWARE_SHA = re.compile(r"^[0-9a-fA-F]{7,40}$")
_OBSERVED_FIRMWARE_SHA = re.compile(r"^[0-9a-fA-F]{40}$")
_SHA256_HEX = re.compile(r"^[0-9a-f]{64}$")
_ENGINE_PACK_ID = re.compile(r"^sha256:[0-9a-f]{64}$")
_ENGINE_PACK_STATE_PATH = Path("/var/lib/dronedream/engine-pack-state.json")
_ENGINE_PACK_ACTIVE_PATH = Path("/opt/dronedream/engine/current")


def _profile_token(name: str, value: Any, *, default: str) -> str:
    """Normalize a profile value before it is exposed as a launcher token."""

    normalized = str(value or default).strip()
    if not _SAFE_PROFILE_TOKEN.fullmatch(normalized):
        raise RunnerError(
            f"vehicle_profile.{name} must contain only letters, numbers, '.', '_' or '-'"
        )
    return normalized


def _profile_bool(name: str, value: Any, *, default: bool) -> bool:
    if value is None:
        return default
    if not isinstance(value, bool):
        raise RunnerError(f"vehicle_profile.{name} must be a boolean")
    return value


def _profile_positive_float(name: str, value: Any, *, default: float) -> float:
    if value is None:
        return default
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise RunnerError(f"vehicle_profile.{name} must be numeric")
    normalized = float(value)
    if not math.isfinite(normalized) or not 0.1 <= normalized <= 100:
        raise RunnerError(f"vehicle_profile.{name} must be finite and in [0.1, 100]")
    return normalized


def _profile_instance_id(value: Any) -> int:
    if value is None:
        return 0
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 255:
        raise RunnerError("vehicle_profile.instance_id must be an integer from 0 to 255")
    return value


def _effective_timeout_seconds(
    baseline_seconds: float,
    simulation_speed_factor: float,
) -> float:
    """Scale a 1x simulation wall budget for slower-than-real-time execution."""

    if not math.isfinite(baseline_seconds) or baseline_seconds <= 0:
        raise ConfigurationRunnerError("timeout baseline must be finite and greater than zero")
    if not math.isfinite(simulation_speed_factor) or simulation_speed_factor <= 0:
        raise RunnerError("simulation speed factor must be finite and greater than zero")
    multiplier = min(
        max(1.0, 1.0 / simulation_speed_factor),
        _MAX_SLOW_SIMULATION_TIMEOUT_MULTIPLIER,
    )
    return baseline_seconds * multiplier


def _firmware_identity(requested_commit: str | None) -> dict[str, Any]:
    """Observe PX4 source HEAD and compare it with the requested identity.

    A site-specific launcher that does not expose a local checkout may provide
    the full observed SHA through ``PX4_FIRMWARE_COMMIT_OBSERVED``. When both
    sources are present they must agree; this variable is evidence, never an
    instruction to checkout or mutate the PX4 repository.
    """

    explicit_raw = os.environ.get("PX4_FIRMWARE_COMMIT_OBSERVED", "").strip()
    explicit = explicit_raw.lower() or None
    observation_error: str | None = None
    if explicit is not None and not _OBSERVED_FIRMWARE_SHA.fullmatch(explicit):
        observation_error = "PX4_FIRMWARE_COMMIT_OBSERVED must be a full 40-character Git SHA"
        explicit = None

    checkout_raw = os.environ.get("PX4_AUTOPILOT_DIR", "").strip()
    checkout = Path(checkout_raw).expanduser().resolve() if checkout_raw else None
    observed_from_git: str | None = None
    if checkout is not None:
        if not checkout.is_dir():
            observation_error = f"PX4_AUTOPILOT_DIR is not a directory: {checkout}"
        else:
            try:
                completed = subprocess.run(  # noqa: S603, S607 - fixed git argv, no shell.
                    ["git", "-C", str(checkout), "rev-parse", "HEAD"],  # noqa: S607
                    capture_output=True,
                    check=False,
                    text=True,
                    timeout=10,
                )
            except (OSError, subprocess.SubprocessError) as exc:
                observation_error = f"could not inspect PX4_AUTOPILOT_DIR Git HEAD: {exc}"
            else:
                candidate = completed.stdout.strip().lower()
                if completed.returncode != 0 or not _OBSERVED_FIRMWARE_SHA.fullmatch(candidate):
                    detail = completed.stderr.strip() or "git rev-parse HEAD returned no full SHA"
                    observation_error = f"could not inspect PX4_AUTOPILOT_DIR Git HEAD: {detail}"
                else:
                    observed_from_git = candidate

    if explicit is not None and observed_from_git is not None and explicit != observed_from_git:
        observation_error = "PX4_FIRMWARE_COMMIT_OBSERVED does not match PX4_AUTOPILOT_DIR Git HEAD"
    observed = observed_from_git or explicit
    source = "git_head" if observed_from_git is not None else ("environment" if explicit else None)
    if requested_commit is None:
        status = "not_requested"
    elif observed is None:
        status = "unavailable"
    elif observed.startswith(requested_commit.lower()):
        status = "verified"
    else:
        status = "mismatch"
    return {
        "requested_commit": requested_commit,
        "observed_commit": observed,
        "observed_source": source,
        "px4_autopilot_dir": str(checkout) if checkout is not None else None,
        "status": status,
        "error": observation_error,
    }


def _load_engine_identity_json(
    path: Path,
    *,
    label: str,
    max_bytes: int,
) -> tuple[bytes, dict[str, Any]]:
    size = _regular_file_size(path, label=label, required=True)
    if size is None or size > max_bytes:
        raise RunnerError(f"{label} exceeds the {max_bytes}-byte contract limit")
    try:
        with path.open("rb") as stream:
            encoded = stream.read(max_bytes + 1)
    except OSError as exc:
        raise RunnerError(f"{label} could not be read") from exc
    if len(encoded) > max_bytes:
        raise RunnerError(f"{label} exceeds the {max_bytes}-byte contract limit")
    try:
        payload = json.loads(
            encoded.decode("utf-8"),
            parse_constant=_reject_nonfinite_json,
        )
    except (UnicodeError, json.JSONDecodeError, RecursionError, ValueError) as exc:
        raise RunnerError(f"{label} is not valid bounded JSON") from exc
    if not isinstance(payload, dict):
        raise RunnerError(f"{label} must contain a JSON object")
    return encoded, payload


def _engine_pack_identity(
    *,
    manifest_path: Path | None = None,
    state_path: Path = _ENGINE_PACK_STATE_PATH,
    active_path: Path | None = None,
) -> dict[str, Any]:
    """Bind a trial to the immutable Engine Pack and its activation receipt.

    Repository and CI runs legitimately have neither file and report an
    explicit unmanaged identity. A managed Runtime must expose both files;
    partial or mismatched state fails closed before PX4/Gazebo is launched.
    """

    if manifest_path is None:
        payload_root = Path(__file__).resolve().parents[2]
        manifest_path = payload_root / "engine-pack-manifest.json"
        active_path = active_path or _ENGINE_PACK_ACTIVE_PATH

    manifest_exists = manifest_path.exists()
    state_exists = state_path.exists()
    if not manifest_exists and not state_exists:
        return {
            "status": "unavailable",
            "reason": "runner is not executing from a managed Engine Pack",
        }
    if manifest_exists != state_exists:
        missing = "activation state" if manifest_exists else "Engine Pack manifest"
        raise RunnerError(f"managed Engine Pack identity is incomplete: missing {missing}")

    manifest_bytes, manifest = _load_engine_identity_json(
        manifest_path,
        label="Engine Pack manifest",
        max_bytes=_MAX_ENGINE_PACK_MANIFEST_BYTES,
    )
    pack_id = manifest.get("packId")
    source = manifest.get("source")
    compatibility = manifest.get("runtimeCompatibility")
    source_commit = source.get("gitCommit") if isinstance(source, dict) else None
    source_date_epoch = source.get("sourceDateEpoch") if isinstance(source, dict) else None
    if manifest.get("schemaVersion") != 1 or manifest.get("kind") != "dronedream-engine-pack":
        raise RunnerError("Engine Pack manifest kind or schemaVersion is unsupported")
    if manifest.get("engineApiVersion") != 1:
        raise RunnerError("Engine Pack manifest engineApiVersion is unsupported")
    if not isinstance(pack_id, str) or not _ENGINE_PACK_ID.fullmatch(pack_id):
        raise RunnerError("Engine Pack manifest packId is invalid")
    if not isinstance(source_commit, str) or not _OBSERVED_FIRMWARE_SHA.fullmatch(source_commit):
        raise RunnerError("Engine Pack manifest source.gitCommit is invalid")
    if (
        isinstance(source_date_epoch, bool)
        or not isinstance(source_date_epoch, int)
        or source_date_epoch < 0
    ):
        raise RunnerError("Engine Pack manifest source.sourceDateEpoch is invalid")
    if not isinstance(compatibility, dict):
        raise RunnerError("Engine Pack manifest runtimeCompatibility is invalid")

    px4_commit = compatibility.get("px4Commit")
    dependency_lock = compatibility.get("dependencyLockSha256")
    runtime_version = compatibility.get("runtimeVersion")
    if not isinstance(px4_commit, str) or not _OBSERVED_FIRMWARE_SHA.fullmatch(px4_commit):
        raise RunnerError("Engine Pack runtimeCompatibility.px4Commit is invalid")
    if not isinstance(dependency_lock, str) or not _SHA256_HEX.fullmatch(dependency_lock):
        raise RunnerError("Engine Pack runtimeCompatibility.dependencyLockSha256 is invalid")
    if not isinstance(runtime_version, str) or not runtime_version.strip():
        raise RunnerError("Engine Pack runtimeCompatibility.runtimeVersion is invalid")

    try:
        _, state = _load_engine_identity_json(
            state_path,
            label="Engine Pack activation state",
            max_bytes=_MAX_ENGINE_PACK_STATE_BYTES,
        )
    except RunnerError as exc:
        if not isinstance(exc.__cause__, PermissionError) or active_path is None:
            raise
        manager_state_binding = _active_engine_pack_binding(
            active_path=active_path,
            manifest_path=manifest_path,
            pack_id=pack_id,
        )
    else:
        archive_sha256 = state.get("archiveSha256")
        state_runtime_version = state.get("runtimeVersion")
        if state.get("schemaVersion") != 1:
            raise RunnerError("Engine Pack activation state schemaVersion is unsupported")
        if state.get("currentPackId") != pack_id:
            raise RunnerError(
                "Engine Pack activation state currentPackId does not match the manifest"
            )
        if state.get("sourceCommit") != source_commit:
            raise RunnerError(
                "Engine Pack activation state sourceCommit does not match the manifest"
            )
        if not isinstance(archive_sha256, str) or not _SHA256_HEX.fullmatch(archive_sha256):
            raise RunnerError("Engine Pack activation state archiveSha256 is invalid")
        if state_runtime_version != runtime_version:
            raise RunnerError(
                "Engine Pack activation state runtimeVersion does not match the manifest"
            )
        manager_state_binding = {
            "status": "verified",
            "activation_method": "manager_state",
            "archive_sha256": archive_sha256,
            "runtime_id": state.get("runtimeId"),
            "runtime_version": state_runtime_version,
        }

    return {
        "status": "verified",
        "pack_id": pack_id,
        "source_commit": source_commit,
        "source_date_epoch": source_date_epoch,
        "manifest_file": "engine-pack-manifest.json",
        "manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
        "engine_api_version": 1,
        "runtime_compatibility": {
            "runtime_product_id": compatibility.get("runtimeProductId"),
            "runtime_version": runtime_version,
            "python_version": compatibility.get("pythonVersion"),
            "px4_commit": px4_commit,
            "gazebo_version": compatibility.get("gazeboVersion"),
            "dependency_lock_sha256": dependency_lock,
        },
        "manager_state_binding": manager_state_binding,
    }


def _active_engine_pack_binding(
    *,
    active_path: Path,
    manifest_path: Path,
    pack_id: str,
) -> dict[str, Any]:
    """Verify the manager-owned active symlink without weakening state-file permissions."""

    try:
        if not active_path.is_symlink():
            raise RunnerError("Engine Pack active path is not a manager-owned symbolic link")
        active_release = active_path.resolve(strict=True)
        manifest_release = manifest_path.resolve(strict=True).parent
    except OSError as exc:
        raise RunnerError("Engine Pack active symbolic link could not be resolved") from exc
    expected_release_id = pack_id.removeprefix("sha256:")
    if active_release != manifest_release or active_release.name != expected_release_id:
        raise RunnerError("Engine Pack active symbolic link does not match the manifest packId")
    return {
        "status": "permission_restricted",
        "activation_method": "active_symlink",
        "active_release_id": expected_release_id,
    }


def _enforce_engine_pack_firmware_binding(
    engine_pack_identity: dict[str, Any],
    firmware_identity: dict[str, Any],
) -> None:
    if engine_pack_identity.get("status") != "verified":
        return
    compatibility = engine_pack_identity.get("runtime_compatibility")
    expected = compatibility.get("px4_commit") if isinstance(compatibility, dict) else None
    observed = firmware_identity.get("observed_commit")
    if observed is None:
        raise RunnerError(
            "managed Engine Pack PX4 identity could not be bound to an observed firmware checkout"
        )
    if observed != expected:
        raise RunnerError(
            f"managed Engine Pack PX4 commit {expected} does not match observed firmware {observed}"
        )


def _enforce_firmware_identity(identity: dict[str, Any]) -> None:
    requested = identity.get("requested_commit")
    if requested is None:
        return
    status = identity.get("status")
    if status == "verified" and identity.get("error") is None:
        return
    observed = identity.get("observed_commit")
    error = identity.get("error")
    if status == "mismatch":
        raise RunnerError(
            f"requested PX4 firmware commit {requested} does not match observed HEAD {observed}"
        )
    raise RunnerError(
        "vehicle_profile.firmware_commit was requested but PX4 firmware identity "
        f"could not be verified: {error or 'no PX4_AUTOPILOT_DIR or observed SHA was provided'}"
    )


def _advanced_number(
    section: dict[str, Any],
    name: str,
    *,
    default: float,
) -> float:
    value = section.get(name, default)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise RunnerError(f"advanced_scenario_config.{name} must be numeric")
    normalized = float(value)
    if not math.isfinite(normalized):
        raise RunnerError(f"advanced_scenario_config.{name} must be finite")
    return normalized


def _scenario_effect_contract(
    advanced_config: object,
    *,
    scenario_type: str,
    scenario_config: object,
    job_config: dict[str, Any],
    effect_request: dict[str, Any] | None = None,
    dry_run: bool,
    allow_unverified_passthrough: bool,
) -> dict[str, Any]:
    """Build the pre-launch view of the scenario-effect evidence contract.

    Real launches are no longer rejected merely because fields are present.
    Instead, the normalized request is handed to the launcher, which must
    return per-effect applied/unsupported evidence. Dry-run retains explicit
    surrogate semantics and never claims a physical effect.
    """

    if effect_request is None:
        effect_request = build_scenario_effect_request(
            execution_identity={},
            scenario_type=scenario_type,
            scenario_config=scenario_config if isinstance(scenario_config, dict) else {},
            job_config=job_config,
            advanced_config=advanced_config if isinstance(advanced_config, dict) else {},
        )
    validate_scenario_effect_request(effect_request)
    requested_details = list(effect_request["effects"])
    requested = sorted(str(item["effect_id"]) for item in requested_details)
    advanced_sources = ("advanced_scenario_config.",)
    dry_run_applied = sorted(
        str(item["effect_id"])
        for item in requested_details
        if not str(item.get("source", "")).startswith(advanced_sources)
    )
    dry_run_unsupported = sorted(set(requested) - set(dry_run_applied))
    if dry_run:
        applied = dry_run_applied
        unsupported = dry_run_unsupported
        pending: list[str] = []
        verification_status = (
            "not_requested"
            if not requested
            else (
                "unverified_passthrough"
                if unsupported and allow_unverified_passthrough
                else ("unsupported" if unsupported else "dry_run_surrogate_applied")
            )
        )
    else:
        applied = []
        unsupported = []
        pending = list(requested)
        verification_status = "not_requested" if not requested else "awaiting_launcher_evidence"
    return {
        "request_schema_version": effect_request["schema_version"],
        "request_sha256": effect_request["request_sha256"],
        "requested_effects": requested,
        "requested_effect_details": requested_details,
        "applied_effects": applied,
        "unsupported_effects": unsupported,
        "failed_effects": [],
        "pending_effects": pending,
        "capabilities": [
            {
                "effect_id": item["effect_id"],
                "mechanism": item["mechanism"],
                "status": item["capability"]["status"],
                "reason": item["capability"]["reason"],
            }
            for item in requested_details
        ],
        "unverified_passthrough_enabled": allow_unverified_passthrough,
        "application_mode": "dry_run_surrogate" if dry_run else "real_physics",
        "verification_status": verification_status,
    }


def _enforce_scenario_effect_contract(contract: dict[str, Any]) -> None:
    unsupported = contract.get("unsupported_effects")
    if not unsupported or contract.get("unverified_passthrough_enabled") is True:
        return
    rendered = ", ".join(str(item) for item in unsupported)
    evidence_error = str(contract.get("evidence_error") or "").strip()
    evidence_detail = f" Launcher evidence error: {evidence_error}." if evidence_error else ""
    raise UnsupportedScenarioEffectRunnerError(
        "bundled PX4/Gazebo runner cannot verify requested advanced scenario effects: "
        f"{rendered}.{evidence_detail} Configure a launcher that applies them, or explicitly set "
        "PX4_GAZEBO_ALLOW_UNVERIFIED_ADVANCED_EFFECTS=true for metadata-only "
        "passthrough (pass_flag will remain false)."
    )


def _parse_bool(raw: str | None, *, default: bool) -> bool:
    if raw is None:
        return default
    normalized = raw.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"invalid boolean value: {raw!r}")


def _telemetry_bool(value: Any, *, field: str, sample_index: int) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, int) and value in {0, 1}:
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
    raise RunnerError(f"telemetry sample {sample_index} field {field!r} must be boolean")


def _parse_float(raw: str | None, *, default: float) -> float:
    if raw is None or not raw.strip():
        return default
    return float(raw)


def _parse_int(raw: str | None, *, default: int) -> int:
    if raw is None or not raw.strip():
        return default
    return int(raw)


def _load_env() -> RunnerEnv:
    timeout_seconds = _parse_int(os.environ.get("PX4_GAZEBO_TIMEOUT_SECONDS"), default=300)
    if timeout_seconds <= 0:
        raise ConfigurationRunnerError("PX4_GAZEBO_TIMEOUT_SECONDS must be greater than zero")
    eval_consecutive_samples = _parse_int(
        os.environ.get("PX4_GAZEBO_EVAL_CONSECUTIVE_SAMPLES"),
        default=5,
    )
    if eval_consecutive_samples <= 0:
        raise ConfigurationRunnerError(
            "PX4_GAZEBO_EVAL_CONSECUTIVE_SAMPLES must be greater than zero"
        )
    telemetry_format = (
        os.environ.get("PX4_GAZEBO_TELEMETRY_FORMAT", "json").strip().lower() or "json"
    )
    if telemetry_format not in {"json", "csv"}:
        raise ConfigurationRunnerError("PX4_GAZEBO_TELEMETRY_FORMAT must be either json or csv")
    allow_csv = _parse_bool(os.environ.get("PX4_GAZEBO_ALLOW_CSV_TELEMETRY"), default=False)
    result = RunnerEnv(
        launch_command=os.environ.get("PX4_GAZEBO_LAUNCH_COMMAND", "").strip(),
        workdir=os.environ.get("PX4_GAZEBO_WORKDIR") or None,
        timeout_seconds=timeout_seconds,
        headless=_parse_bool(os.environ.get("PX4_GAZEBO_HEADLESS"), default=True),
        keep_raw_logs=_parse_bool(os.environ.get("PX4_GAZEBO_KEEP_RAW_LOGS"), default=True),
        dry_run=_parse_bool(os.environ.get("PX4_GAZEBO_DRY_RUN"), default=False),
        pass_rmse=_parse_float(os.environ.get("PX4_GAZEBO_PASS_RMSE"), default=0.75),
        pass_max_error=_parse_float(os.environ.get("PX4_GAZEBO_PASS_MAX_ERROR"), default=2.0),
        min_track_coverage=_parse_float(
            os.environ.get("PX4_GAZEBO_MIN_TRACK_COVERAGE"), default=0.9
        ),
        vehicle=os.environ.get("PX4_GAZEBO_VEHICLE", "").strip() or "x500",
        world=os.environ.get("PX4_GAZEBO_WORLD", "").strip() or "default",
        extra_args=os.environ.get("PX4_GAZEBO_EXTRA_ARGS", "").strip(),
        telemetry_format=telemetry_format,
        allow_csv_telemetry=allow_csv or telemetry_format == "csv",
        eval_altitude_fraction=_parse_float(
            os.environ.get("PX4_GAZEBO_EVAL_ALTITUDE_FRACTION"), default=0.9
        ),
        eval_near_track_threshold_m=_parse_float(
            os.environ.get("PX4_GAZEBO_EVAL_NEAR_TRACK_THRESHOLD_M"), default=1.5
        ),
        eval_consecutive_samples=eval_consecutive_samples,
        eval_collapse_altitude_fraction=_parse_float(
            os.environ.get("PX4_GAZEBO_EVAL_COLLAPSE_ALTITUDE_FRACTION"), default=0.5
        ),
        px4_version=os.environ.get("PX4_VERSION", "main").strip() or "main",
        enforce_safe_parameter_bounds=_parse_bool(
            os.environ.get("PX4_PARAMETER_ENFORCE_SAFE_BOUNDS"), default=True
        ),
        allow_unverified_advanced_effects=_parse_bool(
            os.environ.get("PX4_GAZEBO_ALLOW_UNVERIFIED_ADVANCED_EFFECTS"),
            default=False,
        ),
    )
    finite_fields = {
        "PX4_GAZEBO_PASS_RMSE": result.pass_rmse,
        "PX4_GAZEBO_PASS_MAX_ERROR": result.pass_max_error,
        "PX4_GAZEBO_MIN_TRACK_COVERAGE": result.min_track_coverage,
        "PX4_GAZEBO_EVAL_ALTITUDE_FRACTION": result.eval_altitude_fraction,
        "PX4_GAZEBO_EVAL_NEAR_TRACK_THRESHOLD_M": result.eval_near_track_threshold_m,
        "PX4_GAZEBO_EVAL_COLLAPSE_ALTITUDE_FRACTION": result.eval_collapse_altitude_fraction,
    }
    for name, value in finite_fields.items():
        if not math.isfinite(value):
            raise ConfigurationRunnerError(f"{name} must be finite")
    if result.pass_rmse < 0 or result.pass_max_error < 0:
        raise ConfigurationRunnerError("PX4/Gazebo pass thresholds must be non-negative")
    if not 0 <= result.min_track_coverage <= 1:
        raise ConfigurationRunnerError("PX4_GAZEBO_MIN_TRACK_COVERAGE must be between 0 and 1")
    if not 0 < result.eval_altitude_fraction <= 1:
        raise ConfigurationRunnerError("PX4_GAZEBO_EVAL_ALTITUDE_FRACTION must be in (0, 1]")
    if result.eval_near_track_threshold_m <= 0:
        raise ConfigurationRunnerError("PX4_GAZEBO_EVAL_NEAR_TRACK_THRESHOLD_M must be positive")
    if not 0 < result.eval_collapse_altitude_fraction <= 1:
        raise ConfigurationRunnerError(
            "PX4_GAZEBO_EVAL_COLLAPSE_ALTITUDE_FRACTION must be in (0, 1]"
        )
    return result


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="DroneDream PX4/Gazebo real_cli runner")
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    return parser.parse_args()


def _json_dump(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        temporary.write_text(
            json.dumps(payload, indent=2, sort_keys=True, allow_nan=False),
            encoding="utf-8",
        )
        temporary.replace(path)
    finally:
        with contextlib.suppress(OSError):
            temporary.unlink()


def _merge_json_object(path: Path, authoritative: dict[str, Any]) -> None:
    """Preserve lower-wrapper details while restoring runner-owned evidence."""

    existing: dict[str, Any] = {}
    if path.is_file():
        with contextlib.suppress(OSError, UnicodeError, json.JSONDecodeError, ValueError):
            loaded = json.loads(
                path.read_text(encoding="utf-8"),
                parse_constant=_reject_nonfinite_json,
            )
            if isinstance(loaded, dict):
                existing = loaded
    existing.update(authoritative)
    _json_dump(path, existing)


def _reject_nonfinite_json(value: str) -> None:
    raise ValueError(f"non-standard JSON numeric constant is forbidden: {value}")


def _load_bounded_json(path: Path, *, label: str, max_bytes: int) -> object:
    try:
        with path.open("rb") as stream:
            encoded = stream.read(max_bytes + 1)
    except OSError as exc:
        raise RunnerError(f"{label} could not be read") from exc
    if len(encoded) > max_bytes:
        raise RunnerError(f"{label} exceeds the JSON evidence limit")
    try:
        return json.loads(
            encoded.decode("utf-8"),
            parse_constant=_reject_nonfinite_json,
        )
    except (UnicodeError, json.JSONDecodeError, RecursionError, ValueError) as exc:
        raise RunnerError(f"{label} is not valid bounded JSON") from exc


def _safe_excerpt(text: str, *, limit: int = 1800) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n... [truncated from {len(text)} chars]"


def _regular_file_size(
    path: Path,
    *,
    label: str,
    required: bool,
) -> int | None:
    """Return a regular file's size without following a launcher-created link."""

    try:
        file_stat = path.lstat()
    except FileNotFoundError:
        if required:
            raise RunnerError(f"{label} is missing") from None
        return None
    except OSError as exc:
        raise RunnerError(f"could not inspect {label}: {exc}") from exc
    if not stat.S_ISREG(file_stat.st_mode):
        raise RunnerError(f"{label} must be a regular, non-symlink file")
    return file_stat.st_size


def _lower_level_failure_reason(run_dir: Path, exit_code: int) -> str:
    """Prefer the launcher's bounded structured failure over a bare exit code."""

    generic_reason = f"lower-level launcher exited with code {exit_code}"
    evidence_sources = (
        (
            run_dir / "offboard_timing.json",
            "offboard timing failure evidence",
            _MAX_OFFBOARD_TIMING_BYTES,
        ),
        (
            run_dir / "launcher_failure.json",
            "launcher failure evidence",
            _MAX_LAUNCHER_FAILURE_BYTES,
        ),
    )
    for evidence_path, label, byte_limit in evidence_sources:
        try:
            evidence_size = _regular_file_size(
                evidence_path,
                label=label,
                required=False,
            )
            if evidence_size is None:
                continue
            loaded = _load_bounded_json(
                evidence_path,
                label=label,
                max_bytes=byte_limit,
            )
        except RunnerError:
            continue
        if not isinstance(loaded, dict) or loaded.get("status") != "failed":
            continue
        failure = loaded.get("failure")
        if not isinstance(failure, str) or not failure.strip():
            continue
        normalized_failure = " ".join(failure.split())
        return f"{generic_reason}: {_safe_excerpt(normalized_failure, limit=1200)}"
    return generic_reason


def _load_trial_payload(path: Path) -> dict[str, Any]:
    size = _regular_file_size(path, label="trial_input", required=True)
    if size is None or size > _MAX_TRIAL_INPUT_BYTES:
        raise RunnerError(f"trial_input exceeds the {_MAX_TRIAL_INPUT_BYTES}-byte contract limit")
    try:
        with path.open("rb") as stream:
            encoded = stream.read(_MAX_TRIAL_INPUT_BYTES + 1)
        if len(encoded) > _MAX_TRIAL_INPUT_BYTES:
            raise RunnerError(
                f"trial_input exceeds the {_MAX_TRIAL_INPUT_BYTES}-byte contract limit"
            )
        payload = json.loads(
            encoded.decode("utf-8"),
            parse_constant=_reject_nonfinite_json,
        )
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise RunnerError(f"trial_input JSON is malformed: {exc}") from None
    if not isinstance(payload, dict):
        raise RunnerError("trial_input must be a JSON object")
    return payload


def _require_effect_evidence_file(path: Path) -> None:
    try:
        size = _regular_file_size(
            path,
            label="scenario effect evidence",
            required=True,
        )
    except RunnerError as exc:
        raise ScenarioEffectContractError(str(exc)) from exc
    if size is None or size > MAX_EFFECT_CONTRACT_BYTES:
        raise ScenarioEffectContractError("scenario effect evidence file is missing or too large")


def _validate_trial_input(
    payload: dict[str, Any],
    *,
    default_px4_version: str = "main",
    default_vehicle: str = "x500",
    default_world: str = "default",
    default_headless: bool = True,
    enforce_safe_parameter_bounds: bool = True,
) -> tuple[dict[str, Any], dict[str, float], dict[str, int | float], dict[str, Any]]:
    required_ids = ("trial_id", "job_id", "candidate_id", "seed", "scenario_type")
    missing = [key for key in required_ids if key not in payload]
    if missing:
        raise RunnerError(f"trial_input missing required keys: {missing}")
    schema_version = payload.get("schema_version")
    if schema_version is not None and schema_version not in {
        "dronedream.trial_input.v1",
        "dronedream.trial_input.v2",
    }:
        raise RunnerError(f"unsupported trial_input.schema_version: {schema_version!r}")
    for key in ("trial_id", "job_id", "candidate_id", "scenario_type"):
        if not isinstance(payload[key], str) or not payload[key].strip():
            raise RunnerError(f"trial_input.{key} must be a non-empty string")
        if len(payload[key]) > _MAX_ID_LENGTH or any(
            ord(character) < 32 or ord(character) == 127 for character in payload[key]
        ):
            raise RunnerError(
                f"trial_input.{key} exceeds {_MAX_ID_LENGTH} characters or contains controls"
            )
    scenario_type = str(payload["scenario_type"]).strip()
    supported_scenarios = {
        "nominal",
        "noise_perturbed",
        "wind_perturbed",
        "combined_perturbed",
        "turbulence",
        "gps_dropout",
        "payload_changed",
        "battery_degraded",
        "actuator_delay",
        "actuator_failure",
        "custom",
    }
    if scenario_type not in supported_scenarios:
        raise RunnerError(
            "trial_input.scenario_type is unsupported; expected one of: "
            + ", ".join(sorted(supported_scenarios))
        )
    seed_raw = payload["seed"]
    if isinstance(seed_raw, bool) or not isinstance(seed_raw, int):
        raise RunnerError("trial_input.seed must be an integer")
    if not -(2**63) <= seed_raw < 2**63:
        raise RunnerError("trial_input.seed must fit in a signed 64-bit integer")
    attempt_raw = payload.get("attempt_count", 1)
    if isinstance(attempt_raw, bool) or not isinstance(attempt_raw, int) or attempt_raw < 1:
        raise RunnerError("trial_input.attempt_count must be a positive integer")
    identity_raw = payload.get("execution_identity")
    expected_identity = {
        "trial_id": payload["trial_id"],
        "job_id": payload["job_id"],
        "candidate_id": payload["candidate_id"],
        "seed": seed_raw,
        "attempt_count": attempt_raw,
    }
    if identity_raw is not None:
        if not isinstance(identity_raw, dict):
            raise RunnerError("trial_input.execution_identity must be an object")
        if identity_raw != expected_identity:
            raise RunnerError("trial_input.execution_identity does not match top-level fields")

    job_cfg_value = payload.get("job_config")
    if job_cfg_value is not None and not isinstance(job_cfg_value, dict):
        raise RunnerError("trial_input.job_config must be an object when provided")
    job_cfg_raw = job_cfg_value or {}

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

    if track_type not in {"hover", "circle", "u_turn", "lemniscate", "custom"}:
        raise RunnerError("track_type must be one of: hover, circle, u_turn, lemniscate, custom")
    if not isinstance(start_point, dict):
        raise RunnerError("start_point must be an object with x/y")

    try:
        start_x = float(start_point.get("x"))
        start_y = float(start_point.get("y"))
        altitude = float(altitude_m)
    except (TypeError, ValueError):
        raise RunnerError("start_point.x/y and altitude_m must be numeric") from None
    if not all(math.isfinite(value) for value in (start_x, start_y, altitude)):
        raise RunnerError("start_point.x/y and altitude_m must be finite")
    if not 1.0 <= altitude <= 20.0:
        raise RunnerError("altitude_m must be between 1 and 20 meters")
    if track_type == "hover" and (abs(start_x) > 1e-9 or abs(start_y) > 1e-9):
        raise RunnerError("hover track requires start_point x=0 and y=0")

    if wind is not None and not isinstance(wind, dict):
        raise RunnerError("wind must be an object when provided")
    if wind is None:
        wind = {"north": 0.0, "east": 0.0, "south": 0.0, "west": 0.0}
    try:
        normalized_wind = {
            direction: float(wind.get(direction, 0.0))
            for direction in ("north", "east", "south", "west")
        }
    except (TypeError, ValueError):
        raise RunnerError("wind components must be numeric") from None
    if not all(math.isfinite(value) for value in normalized_wind.values()):
        raise RunnerError("wind components must be finite")
    if any(not -10.0 <= value <= 10.0 for value in normalized_wind.values()):
        raise RunnerError("wind components must be between -10 and 10 m/s")
    normalized_noise = str(sensor_noise_level or "medium").strip().lower()
    if normalized_noise not in {"low", "medium", "high"}:
        raise RunnerError("sensor_noise_level must be one of: low, medium, high")
    normalized_objective = str(objective_profile or "robust").strip().lower()
    if normalized_objective not in {"stable", "fast", "smooth", "robust", "custom"}:
        raise RunnerError("objective_profile must be one of: stable, fast, smooth, robust, custom")

    normalized_job_cfg = {
        "track_type": track_type,
        "start_point": {"x": start_x, "y": start_y},
        "altitude_m": altitude,
        "wind": normalized_wind,
        "sensor_noise_level": normalized_noise,
        "objective_profile": normalized_objective,
        "reference_track": [],
    }
    if reference_track_raw is not None:
        if not isinstance(reference_track_raw, list):
            raise RunnerError("reference_track must be an array when provided")
        if len(reference_track_raw) > _MAX_REFERENCE_TRACK_POINTS:
            raise RunnerError(
                f"reference_track exceeds the {_MAX_REFERENCE_TRACK_POINTS}-point limit"
            )
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
                raise RunnerError(
                    f"reference_track[{idx}].z must be numeric when provided"
                ) from None
            if not all(math.isfinite(value) for value in (x, y, z)):
                raise RunnerError(f"reference_track[{idx}] coordinates must be finite")
            normalized_points.append({"x": x, "y": y, "z": z})
        normalized_job_cfg["reference_track"] = normalized_points
    if track_type == "custom" and len(normalized_job_cfg["reference_track"]) < 2:
        raise RunnerError("custom track_type requires reference_track with at least 2 points")
    if (
        track_type == "hover"
        and normalized_job_cfg["reference_track"]
        and any(
            abs(point["x"]) > 1e-9 or abs(point["y"]) > 1e-9 or abs(point["z"] - altitude) > 1e-9
            for point in normalized_job_cfg["reference_track"]
        )
    ):
        raise RunnerError("hover reference_track must remain at x=0, y=0 and altitude_m")

    params_value = payload.get("parameters")
    if params_value is not None and not isinstance(params_value, dict):
        raise RunnerError("trial_input.parameters must be an object when provided")
    params_raw = params_value or {}
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
    if min(params["kp_xy"], params["kd_xy"], params["ki_xy"]) < 0:
        raise RunnerError("controller gains must be non-negative")
    if params["vel_limit"] <= 0 or params["accel_limit"] <= 0:
        raise RunnerError(
            "parameters.vel_limit and parameters.accel_limit must be greater than zero"
        )
    if not 0.0 <= params["disturbance_rejection"] <= 1.0:
        raise RunnerError("parameters.disturbance_rejection must be between 0 and 1")

    profile_raw = payload.get("vehicle_profile")
    if profile_raw is not None and not isinstance(profile_raw, dict):
        raise RunnerError("trial_input.vehicle_profile must be an object when provided")
    if profile_raw is None:
        nested_profile = job_cfg_raw.get("vehicle_profile")
        if nested_profile is not None and not isinstance(nested_profile, dict):
            raise RunnerError("trial_input.job_config.vehicle_profile must be an object")
        profile_raw = nested_profile or {}
    airframe = _profile_token("airframe", profile_raw.get("airframe"), default=default_vehicle)
    simulator_model = _profile_token(
        "simulator_model",
        profile_raw.get("simulator_model"),
        default=default_vehicle,
    )
    world = _profile_token("world", profile_raw.get("world"), default=default_world)
    vehicle_type = _profile_token(
        "vehicle_type", profile_raw.get("vehicle_type"), default="multicopter"
    )
    headless = _profile_bool("headless", profile_raw.get("headless"), default=default_headless)
    simulation_speed_factor = _profile_positive_float(
        "simulation_speed_factor",
        profile_raw.get("simulation_speed_factor"),
        default=1.0,
    )
    instance_id = _profile_instance_id(profile_raw.get("instance_id"))
    firmware_commit_raw = profile_raw.get("firmware_commit")
    if firmware_commit_raw is None or firmware_commit_raw == "":
        firmware_commit = None
    elif not isinstance(firmware_commit_raw, str) or not _REQUESTED_FIRMWARE_SHA.fullmatch(
        firmware_commit_raw.strip()
    ):
        raise RunnerError(
            "vehicle_profile.firmware_commit must be a 7-40 character Git SHA when provided"
        )
    else:
        firmware_commit = firmware_commit_raw.strip().lower()

    raw_px4_version = str(
        payload.get("px4_version")
        or profile_raw.get("px4_version")
        or job_cfg_raw.get("px4_version")
        or default_px4_version
    )
    try:
        px4_version = normalize_px4_version(raw_px4_version)
    except ValueError as exc:
        raise RunnerError(f"vehicle_profile.px4_version is invalid: {exc}") from exc
    catalog_version_raw = payload.get("parameter_catalog_version")
    if catalog_version_raw is None:
        catalog_version_raw = job_cfg_raw.get("parameter_catalog_version")
    if catalog_version_raw is not None and not isinstance(catalog_version_raw, str):
        raise RunnerError("parameter_catalog_version must be a string when provided")
    parameter_catalog_version = (
        catalog_version_raw.strip() if isinstance(catalog_version_raw, str) else None
    )
    explicit_px4_params = payload.get("px4_parameters")
    if explicit_px4_params is None:
        explicit_px4_params = job_cfg_raw.get("px4_parameters")
    if explicit_px4_params is None:
        # Forward-compatible bridge for candidates that place real PX4 names in
        # the existing parameters object while the legacy six fields still exist.
        explicit_px4_params = {
            str(key): value
            for key, value in params_raw.items()
            if get_parameter(str(key), px4_version=px4_version) is not None
            or get_parameter(str(key), px4_version="main") is not None
        }
    if not isinstance(explicit_px4_params, dict):
        raise RunnerError("px4_parameters must be an object when provided")
    try:
        px4_params = validate_parameter_values(
            explicit_px4_params,
            px4_version=px4_version,
            catalog_version=parameter_catalog_version,
            vehicle_type=vehicle_type,
            airframe=airframe,
            enforce_safe_bounds=enforce_safe_parameter_bounds,
        )
    except (ParameterValueValidationError, ValueError) as exc:
        raise RunnerError(f"invalid px4_parameters: {exc}") from exc

    normalized_job_cfg["vehicle_profile"] = {
        "px4_version": px4_version,
        "firmware_commit": firmware_commit,
        "vehicle_type": vehicle_type,
        "airframe": airframe,
        "simulator_model": simulator_model,
        "world": world,
        "headless": headless,
        "simulation_speed_factor": simulation_speed_factor,
        "instance_id": instance_id,
    }
    normalized_job_cfg["parameter_catalog_version"] = parameter_catalog_version

    scenario_config_raw = payload.get("scenario_config")
    if scenario_config_raw is not None and not isinstance(scenario_config_raw, dict):
        raise RunnerError("trial_input.scenario_config must be an object when provided")
    scenario_config = scenario_config_raw or {}
    advanced = payload.get("advanced_scenario_config")
    if advanced is not None and not isinstance(advanced, dict):
        raise RunnerError("trial_input.advanced_scenario_config must be an object when provided")
    if advanced is None:
        nested_advanced = scenario_config.get("advanced_scenario_config")
        if nested_advanced is not None and not isinstance(nested_advanced, dict):
            raise RunnerError(
                "trial_input.scenario_config.advanced_scenario_config must be an object"
            )
        advanced = nested_advanced or {}
    try:
        expected_effect_request = build_scenario_effect_request(
            execution_identity=expected_identity,
            scenario_type=scenario_type,
            scenario_config=scenario_config,
            job_config=normalized_job_cfg,
            advanced_config=advanced,
        )
        supplied_effect_request = payload.get("scenario_effect_request")
        if supplied_effect_request is not None:
            validate_scenario_effect_request(supplied_effect_request)
            if supplied_effect_request != expected_effect_request:
                raise ScenarioEffectContractError(
                    "scenario_effect_request does not match normalized trial inputs"
                )
        else:
            supplied_effect_request = expected_effect_request
    except ScenarioEffectContractError as exc:
        raise RunnerError(f"invalid scenario effect request: {exc}") from exc
    meta = {
        "trial_id": str(payload["trial_id"]),
        "job_id": str(payload["job_id"]),
        "candidate_id": str(payload["candidate_id"]),
        "seed": seed_raw,
        "attempt_count": attempt_raw,
        "scenario_type": scenario_type,
        "scenario_config": scenario_config,
        "advanced_scenario_config": advanced,
        "scenario_effect_request": supplied_effect_request,
        "px4_version": px4_version,
        "firmware_commit": firmware_commit,
        "parameter_catalog_version": parameter_catalog_version,
        "airframe": airframe,
        "simulator_model": simulator_model,
        # ``vehicle`` is the backwards-compatible launcher alias. PX4/Gazebo
        # launchers historically interpreted it as the simulator model.
        "vehicle": simulator_model,
        "world": world,
        "headless": headless,
        "simulation_speed_factor": simulation_speed_factor,
        "instance_id": instance_id,
    }
    return normalized_job_cfg, params, px4_params, meta


def _make_reference_track(
    track_type: str,
    start_x: float,
    start_y: float,
    altitude: float,
    reference_track: list[dict[str, float]] | None = None,
) -> list[dict[str, float]]:
    if reference_track:
        return list(reference_track)
    if track_type == "custom":
        return list(reference_track or [])
    points: list[dict[str, float]] = []
    if track_type == "hover":
        for _ in range(_HOVER_REFERENCE_SAMPLE_COUNT):
            points.append({"x": 0.0, "y": 0.0, "z": altitude})
    elif track_type == "circle":
        radius = 5.0
        n = 180
        for i in range(n + 1):
            theta = 2.0 * math.pi * (i / n)
            points.append(
                {
                    "x": start_x + radius * math.cos(theta),
                    "y": start_y + radius * math.sin(theta),
                    "z": altitude,
                }
            )
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
            points.append(
                {
                    "x": cx + turn_radius * math.cos(theta),
                    "y": cy + turn_radius * math.sin(theta),
                    "z": altitude,
                }
            )
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
    return (
        float(wind.get("east", 0.0)) - float(wind.get("west", 0.0)),
        float(wind.get("north", 0.0)) - float(wind.get("south", 0.0)),
    )


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
        "turbulence": 0.45,
        "gps_dropout": 0.4,
        "payload_changed": 0.3,
        "battery_degraded": 0.35,
        "actuator_delay": 0.3,
        "actuator_failure": 0.9,
        "custom": 0.2,
    }.get(meta["scenario_type"], 0.1)
    noise_penalty = {"low": 0.0, "medium": 0.05, "high": 0.12}.get(
        job_cfg["sensor_noise_level"], 0.06
    )
    scenario_config = meta.get("scenario_config", {})
    scenario_wind_mps = 0.0
    if isinstance(scenario_config, dict) and "wind_mps" in scenario_config:
        value = scenario_config["wind_mps"]
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise RunnerError("scenario_config.wind_mps must be numeric")
        scenario_wind_mps = float(value)
        if not math.isfinite(scenario_wind_mps) or scenario_wind_mps < 0:
            raise RunnerError("scenario_config.wind_mps must be finite and non-negative")

    base_err = (
        abs(params["kp_xy"] - 1.1) * 0.15
        + abs(params["kd_xy"] - 0.25) * 0.2
        + abs(params["ki_xy"] - 0.06) * 0.3
        + max(0.0, params["vel_limit"] - 6.0) * 0.04
        + max(0.0, params["accel_limit"] - 5.0) * 0.03
        + (1.0 - min(1.0, max(0.0, params["disturbance_rejection"]))) * 0.12
        + scenario_penalty
        + noise_penalty
        + min(20.0, scenario_wind_mps) * 0.03
    )

    wx, wy = _wind_vec(job_cfg["wind"])
    wobble_mag = min(1.8, 0.15 + base_err + (abs(wx) + abs(wy)) * 0.02)
    rng = random.Random(int(meta["seed"]))  # noqa: S311 - deterministic simulation.
    x_phase = rng.uniform(-math.pi, math.pi)
    y_phase = rng.uniform(-math.pi, math.pi)
    noise_std = 0.01 + 0.04 * noise_penalty + 0.01 * scenario_penalty
    samples: list[dict[str, Any]] = []
    dt = 0.1
    for i, ref in enumerate(reference_track):
        theta = 2 * math.pi * i / max(1, len(reference_track) - 1)
        x = (
            ref["x"]
            + wobble_mag * math.sin(theta * 2 + x_phase)
            + wx * 0.02
            + rng.gauss(0.0, noise_std)
        )
        y = (
            ref["y"]
            + wobble_mag * math.cos(theta * 2 + y_phase)
            + wy * 0.02
            + rng.gauss(0.0, noise_std)
        )
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
            "vehicle": meta["vehicle"],
            "airframe": meta["airframe"],
            "simulator_model": meta["simulator_model"],
            "world": meta["world"],
            "px4_version": meta["px4_version"],
            "mode": "dry_run",
            "seed": meta["seed"],
        },
    }


def _normalize_samples(samples: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if len(samples) > _MAX_TELEMETRY_SAMPLES:
        raise RunnerError(f"telemetry exceeds the {_MAX_TELEMETRY_SAMPLES}-sample contract limit")
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
                "armed": _telemetry_bool(raw.get("armed", True), field="armed", sample_index=idx),
                "mode": str(raw.get("mode", "unknown")),
                "crashed": _telemetry_bool(
                    raw.get("crashed", False), field="crashed", sample_index=idx
                ),
            }
        except (KeyError, TypeError, ValueError):
            raise RunnerError(
                f"telemetry sample {idx} missing or invalid required fields"
            ) from None
        for key in ("t", "x", "y", "z", "vx", "vy", "vz", "yaw"):
            if not math.isfinite(s[key]):
                raise RunnerError(f"telemetry sample {idx} contains non-finite {key}")
        if len(s["mode"]) > 128 or any(ord(char) < 32 for char in s["mode"]):
            raise RunnerError(f"telemetry sample {idx} mode is too long or contains controls")
        normalized.append(s)

    if not normalized:
        raise RunnerError("telemetry samples are empty")
    for idx in range(1, len(normalized)):
        if normalized[idx]["t"] <= normalized[idx - 1]["t"]:
            raise RunnerError(f"telemetry sample {idx} timestamp must be strictly increasing")
    return normalized


def _load_telemetry(path: Path, *, allow_csv: bool) -> dict[str, Any]:
    size = _regular_file_size(path, label="telemetry JSON", required=False)
    if size is not None:
        if size > _MAX_TELEMETRY_BYTES:
            raise RunnerError(
                f"telemetry JSON exceeds the {_MAX_TELEMETRY_BYTES}-byte contract limit"
            )
        try:
            with path.open("rb") as stream:
                encoded = stream.read(_MAX_TELEMETRY_BYTES + 1)
            if len(encoded) > _MAX_TELEMETRY_BYTES:
                raise RunnerError(
                    f"telemetry JSON exceeds the {_MAX_TELEMETRY_BYTES}-byte contract limit"
                )
            payload = json.loads(
                encoded.decode("utf-8"),
                parse_constant=_reject_nonfinite_json,
            )
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise RunnerError(f"telemetry JSON is malformed: {exc}") from None
        if not isinstance(payload, dict) or not isinstance(payload.get("samples"), list):
            raise RunnerError("telemetry.json must contain an object with samples[]")
        samples = _normalize_samples(payload["samples"])
        if payload.get("meta") is None:
            meta: dict[str, Any] = {}
        elif not isinstance(payload.get("meta"), dict):
            raise RunnerError("telemetry.meta must be an object when present")
        else:
            meta = dict(payload["meta"])
        source = str(meta.get("source", "")).strip().lower()
        mode = str(meta.get("mode", "")).strip().lower()
        source_kind = (
            "px4_ulog"
            if source == "ulog"
            else "runner_dry_run"
            if mode in {"dry_run", "site_dry_run"}
            else "launcher_json"
        )
        origin_provenance = {
            key: meta.get(key)
            for key in (
                "origin_source_sha256",
                "origin_source_byte_count",
                "origin_extraction_revision",
                "origin_coordinate_frame",
                "coordinate_transform",
            )
            if meta.get(key) is not None
        }
        try:
            contract = compile_telemetry_semantic_contract(
                samples=samples,
                source_bytes=encoded,
                source_kind=source_kind,
                extraction_revision=("px4-gazebo-runner-json-normalization-1.0"),
                synthetic=source_kind == "runner_dry_run",
                origin_provenance=origin_provenance,
            )
        except (TelemetrySemanticContractError, ValueError) as exc:
            raise RunnerError(f"telemetry semantic contract failed: {exc}") from exc
        return {
            "schema_version": TELEMETRY_SCHEMA_V2,
            "samples": samples,
            "meta": meta,
            "semantic_contract": contract.model_dump(mode="json"),
        }

    csv_path = path.with_suffix(".csv")
    csv_size = (
        _regular_file_size(csv_path, label="telemetry CSV", required=False) if allow_csv else None
    )
    if csv_size is not None:
        if csv_size > _MAX_TELEMETRY_BYTES:
            raise RunnerError(
                f"telemetry CSV exceeds the {_MAX_TELEMETRY_BYTES}-byte contract limit"
            )
        with csv_path.open("rb") as stream:
            encoded = stream.read(_MAX_TELEMETRY_BYTES + 1)
        if len(encoded) > _MAX_TELEMETRY_BYTES:
            raise RunnerError(
                f"telemetry CSV exceeds the {_MAX_TELEMETRY_BYTES}-byte contract limit"
            )
        try:
            decoded = encoded.decode("utf-8")
        except UnicodeError as exc:
            raise RunnerError(f"telemetry CSV is not UTF-8: {exc}") from None
        samples_raw: list[dict[str, Any]] = []
        reader = csv.DictReader(io.StringIO(decoded, newline=""))
        for row_index, row in enumerate(reader):
            if row_index >= _MAX_TELEMETRY_SAMPLES:
                raise RunnerError(
                    f"telemetry exceeds the {_MAX_TELEMETRY_SAMPLES}-sample contract limit"
                )
            samples_raw.append(
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
        samples = _normalize_samples(samples_raw)
        try:
            contract = compile_telemetry_semantic_contract(
                samples=samples,
                source_bytes=encoded,
                source_kind="launcher_csv",
                extraction_revision=("px4-gazebo-runner-csv-normalization-1.0"),
                synthetic=False,
            )
        except (TelemetrySemanticContractError, ValueError) as exc:
            raise RunnerError(f"telemetry semantic contract failed: {exc}") from exc
        return {
            "schema_version": TELEMETRY_SCHEMA_V2,
            "samples": samples,
            "meta": {"format": "csv"},
            "semantic_contract": contract.model_dump(mode="json"),
        }

    raise RunnerError("telemetry output is missing")


def _build_track_geometry(
    ref_points: list[dict[str, float]],
    *,
    allow_stationary: bool = False,
) -> TrackGeometry:
    if len(ref_points) < 2:
        raise RunnerError("reference track must contain at least two points")
    segments: list[TrackSegment] = []
    progress = 0.0
    for start, end in zip(ref_points, ref_points[1:], strict=False):
        start_xyz = (float(start["x"]), float(start["y"]), float(start["z"]))
        delta = (
            float(end["x"]) - start_xyz[0],
            float(end["y"]) - start_xyz[1],
            float(end["z"]) - start_xyz[2],
        )
        length = math.sqrt(sum(component * component for component in delta))
        if length <= 1e-12:
            continue
        segments.append(
            TrackSegment(
                start=start_xyz,
                delta=delta,
                length=length,
                start_progress=progress,
            )
        )
        progress += length
    if not segments or progress <= 1e-12:
        if allow_stationary and ref_points:
            anchor = ref_points[0]
            anchor_start = (
                float(anchor["x"]),
                float(anchor["y"]),
                float(anchor["z"]),
            )
            return TrackGeometry(
                segments=(
                    TrackSegment(
                        start=anchor_start,
                        delta=(0.0, 0.0, 0.0),
                        length=0.0,
                        start_progress=0.0,
                    ),
                ),
                total_length=0.0,
                closed=True,
                stationary=True,
            )
        raise RunnerError("reference track must have non-zero three-dimensional length")
    first = ref_points[0]
    last = ref_points[-1]
    endpoint_distance = math.sqrt(
        (float(first["x"]) - float(last["x"])) ** 2
        + (float(first["y"]) - float(last["y"])) ** 2
        + (float(first["z"]) - float(last["z"])) ** 2
    )
    return TrackGeometry(
        segments=tuple(segments),
        total_length=progress,
        closed=endpoint_distance <= max(1e-6, progress * 1e-6),
        stationary=False,
    )


def _project_sample_to_segment(
    sample: dict[str, Any],
    segment: TrackSegment,
    segment_index: int,
) -> TrackProjection:
    offset = (
        float(sample["x"]) - segment.start[0],
        float(sample["y"]) - segment.start[1],
        float(sample["z"]) - segment.start[2],
    )
    length_squared = segment.length * segment.length
    fraction = (
        0.0
        if length_squared <= 1e-24
        else min(
            1.0,
            max(
                0.0,
                sum(offset[i] * segment.delta[i] for i in range(3)) / length_squared,
            ),
        )
    )
    reference = tuple(segment.start[i] + fraction * segment.delta[i] for i in range(3))
    error = math.sqrt(
        (float(sample["x"]) - reference[0]) ** 2
        + (float(sample["y"]) - reference[1]) ** 2
        + (float(sample["z"]) - reference[2]) ** 2
    )
    return TrackProjection(
        error=error,
        segment_index=segment_index,
        segment_fraction=fraction,
        progress=segment.start_progress + fraction * segment.length,
        reference_x=reference[0],
        reference_y=reference[1],
        reference_z=reference[2],
    )


def _best_track_projection(
    sample: dict[str, Any],
    geometry: TrackGeometry,
    candidate_indices: list[int] | range,
    comparison_budget: list[int],
) -> TrackProjection:
    candidate_count = len(candidate_indices)
    if candidate_count > comparison_budget[0]:
        raise RunnerError(
            "track projection exceeds the bounded comparison budget; "
            "downsample telemetry/reference points or remove discontinuous jumps"
        )
    comparison_budget[0] -= candidate_count
    best: TrackProjection | None = None
    for segment_index in candidate_indices:
        projection = _project_sample_to_segment(
            sample,
            geometry.segments[segment_index],
            segment_index,
        )
        if best is None or projection.error < best.error:
            best = projection
    if best is None:
        raise RunnerError("track projection requires at least one candidate segment")
    return best


def _local_segment_indices(
    previous_index: int,
    segment_count: int,
    *,
    closed: bool,
) -> list[int]:
    if segment_count <= _PROJECTION_BACKTRACK_SEGMENTS + _PROJECTION_FORWARD_SEGMENTS + 1:
        return list(range(segment_count))
    lower = previous_index - _PROJECTION_BACKTRACK_SEGMENTS
    upper = previous_index + _PROJECTION_FORWARD_SEGMENTS
    # Closed tracks wrap around their seam. Open tracks clamp to their ends.
    if closed and (lower < 0 or upper >= segment_count):
        wrapped = [index % segment_count for index in range(lower, upper + 1)]
        return list(dict.fromkeys(wrapped))
    return list(range(max(0, lower), min(segment_count - 1, upper) + 1))


def _project_samples_to_track(
    samples: list[dict[str, Any]],
    geometry: TrackGeometry,
) -> list[TrackProjection]:
    """Project an ordered telemetry stream with bounded local search.

    A full scan establishes the first match. Subsequent samples search near the
    previous segment, with periodic/global recovery when the aircraft has moved
    far while the local match is poor. This makes normal work proportional to
    telemetry size rather than telemetry multiplied by reference density while
    retaining recovery from resets and large jumps.
    """

    segment_count = len(geometry.segments)
    all_indices = range(segment_count)
    comparison_budget = [_MAX_PROJECTION_SEGMENT_COMPARISONS]
    projections: list[TrackProjection] = []
    previous_index = 0
    last_global_position: tuple[float, float, float] | None = None
    for sample_index, sample in enumerate(samples):
        position = (float(sample["x"]), float(sample["y"]), float(sample["z"]))
        if sample_index == 0:
            best = _best_track_projection(
                sample,
                geometry,
                all_indices,
                comparison_budget,
            )
            last_global_position = position
        else:
            local_indices = _local_segment_indices(
                previous_index,
                segment_count,
                closed=geometry.closed,
            )
            best = _best_track_projection(
                sample,
                geometry,
                local_indices,
                comparison_budget,
            )
            moved_since_global = (
                float("inf")
                if last_global_position is None
                else math.dist(position, last_global_position)
            )
            local_boundary_hit = len(local_indices) < segment_count and (
                (geometry.closed and best.segment_index in {local_indices[0], local_indices[-1]})
                or (
                    not geometry.closed
                    and (
                        (local_indices[0] > 0 and best.segment_index == local_indices[0])
                        or (
                            local_indices[-1] < segment_count - 1
                            and best.segment_index == local_indices[-1]
                        )
                    )
                )
            )
            needs_global = (
                sample_index % _PROJECTION_GLOBAL_RESCAN_INTERVAL == 0
                or local_boundary_hit
                or (
                    best.error > _PROJECTION_LOCAL_ERROR_FALLBACK_M
                    and moved_since_global >= _PROJECTION_GLOBAL_RESCAN_DISTANCE_M
                )
            )
            if needs_global:
                global_best = _best_track_projection(
                    sample,
                    geometry,
                    all_indices,
                    comparison_budget,
                )
                # Preserve ordered continuity at exactly equidistant
                # self-intersections; otherwise accept the globally closer arc.
                if global_best.error + 1e-9 < best.error:
                    best = global_best
                last_global_position = position
        projections.append(best)
        previous_index = best.segment_index
    return projections


def _merged_interval_length(intervals: list[tuple[float, float]]) -> float:
    if not intervals:
        return 0.0
    ordered = sorted(intervals)
    total = 0.0
    start, end = ordered[0]
    for next_start, next_end in ordered[1:]:
        if next_start <= end:
            end = max(end, next_end)
        else:
            total += end - start
            start, end = next_start, next_end
    return total + (end - start)


def _evaluate_track_progress(
    samples: list[dict[str, Any]],
    projections: list[TrackProjection],
    geometry: TrackGeometry,
    *,
    max_track_error: float,
) -> TrackProgressEvaluation:
    """Evaluate directed, continuous progress independent of waypoint density."""

    if geometry.stationary:
        in_tolerance = [projection.error <= max_track_error for projection in projections]
        duration_seconds = (
            max(0.0, float(samples[-1]["t"]) - float(samples[0]["t"])) if len(samples) >= 2 else 0.0
        )
        duration_fraction = min(
            1.0,
            duration_seconds / _HOVER_MIN_EVALUATION_DURATION_SECONDS,
        )
        in_tolerance_duration = 0.0
        for index in range(1, len(samples)):
            interval_seconds = float(samples[index]["t"]) - float(samples[index - 1]["t"])
            if interval_seconds <= 0:
                raise RunnerError("stationary hover coverage requires increasing timestamps")
            in_tolerance_duration += (
                0.5
                * (float(in_tolerance[index - 1]) + float(in_tolerance[index]))
                * interval_seconds
            )
        in_tolerance_fraction = (
            min(1.0, in_tolerance_duration / duration_seconds)
            if duration_seconds > 0
            else float(bool(in_tolerance and in_tolerance[0]))
        )
        coverage = in_tolerance_fraction * duration_fraction
        reached = 0.0 if any(in_tolerance) else None
        return TrackProgressEvaluation(
            coverage=coverage,
            directed_progress_fraction=coverage,
            backward_distance=0.0,
            discontinuity_count=0,
            start_progress=reached,
            end_progress=reached,
        )

    intervals: list[tuple[float, float]] = []
    previous: tuple[dict[str, Any], TrackProjection] | None = None
    first_progress: float | None = None
    last_progress: float | None = None
    forward_distance = 0.0
    backward_distance = 0.0
    discontinuity_count = 0
    for sample, projection in zip(samples, projections, strict=True):
        if projection.error > max_track_error:
            previous = None
            continue
        if first_progress is None:
            first_progress = projection.progress
        last_progress = projection.progress
        if previous is not None:
            previous_sample, previous_projection = previous
            delta = projection.progress - previous_projection.progress
            if geometry.closed:
                half_length = geometry.total_length / 2.0
                if delta > half_length:
                    delta -= geometry.total_length
                elif delta < -half_length:
                    delta += geometry.total_length
            sample_distance = math.dist(
                (sample["x"], sample["y"], sample["z"]),
                (
                    previous_sample["x"],
                    previous_sample["y"],
                    previous_sample["z"],
                ),
            )
            maximum_continuous_step = min(
                geometry.total_length * _MAX_COVERAGE_PROGRESS_STEP_FRACTION,
                max(0.25, sample_distance * 4.0 + 0.1),
            )
            if abs(delta) > maximum_continuous_step + 1e-9:
                discontinuity_count += 1
                previous = (sample, projection)
                continue
            if delta < -1e-12:
                backward_distance += -delta
                previous = (sample, projection)
                continue
            if delta > 1e-12:
                forward_distance += delta
                if geometry.closed:
                    start = previous_projection.progress
                    normalized_start = start % geometry.total_length
                    normalized_end = normalized_start + delta
                    if normalized_end <= geometry.total_length:
                        intervals.append((normalized_start, normalized_end))
                    else:
                        intervals.append((normalized_start, geometry.total_length))
                        intervals.append((0.0, normalized_end - geometry.total_length))
                else:
                    intervals.append((previous_projection.progress, projection.progress))
        previous = (sample, projection)
    return TrackProgressEvaluation(
        coverage=min(1.0, _merged_interval_length(intervals) / geometry.total_length),
        directed_progress_fraction=min(
            1.0,
            max(0.0, (forward_distance - backward_distance) / geometry.total_length),
        ),
        backward_distance=backward_distance,
        discontinuity_count=discontinuity_count,
        start_progress=first_progress,
        end_progress=last_progress,
    )


def _sample_meets_track_entry_condition(
    sample: dict[str, Any],
    projection: TrackProjection,
    altitude_fraction: float,
    near_track_threshold: float,
) -> bool:
    target_altitude = max(0.0, projection.reference_z)
    if target_altitude > 0.0 and sample["z"] < altitude_fraction * target_altitude:
        return False
    return projection.error <= near_track_threshold


def _first_consecutive_index(
    samples: list[dict[str, Any]],
    start_idx: int,
    end_idx: int,
    predicate: Callable[[int, dict[str, Any]], bool],
    consecutive_count: int,
) -> int | None:
    count = 0
    run_start: int | None = None
    for i in range(start_idx, end_idx + 1):
        if predicate(i, samples[i]):
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
    projections: list[TrackProjection],
    start_idx: int,
    end_idx: int,
    altitude_fraction: float,
    consecutive_count: int,
) -> int:
    count = 0
    run_start: int | None = None
    for i in range(start_idx + 1, end_idx + 1):
        target_altitude = max(0.0, projections[i].reference_z)
        threshold = altitude_fraction * target_altitude
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
    projections: list[TrackProjection],
    raw_start_idx: int,
    raw_end_idx: int,
    *,
    raw_source: str,
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
        lambda index, sample: _sample_meets_track_entry_condition(
            sample,
            projections[index],
            altitude_fraction,
            near_track_threshold,
        ),
        consecutive_samples,
    )
    if refined_start is None:
        return None
    refined_end = _last_before_landing_index(
        samples,
        projections,
        refined_start,
        raw_end_idx,
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
    projections: list[TrackProjection],
    timing: dict[str, Any],
    *,
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
        projections,
        idx_start,
        idx_end,
        raw_source="offboard_timing",
        altitude_fraction=altitude_fraction,
        near_track_threshold=near_track_threshold,
        consecutive_samples=consecutive_samples,
    )


def _find_eval_window_from_telemetry(
    samples: list[dict[str, Any]],
    projections: list[TrackProjection],
    *,
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
        lambda index, sample: _sample_meets_track_entry_condition(
            sample,
            projections[index],
            altitude_fraction,
            near_track_threshold,
        ),
        consecutive_samples,
    )
    if start_idx is None:
        return None
    end_idx = _last_before_landing_index(
        samples,
        projections,
        start_idx,
        raw_end_idx,
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
    projections: list[TrackProjection],
    *,
    altitude_fraction: float,
    consecutive_samples: int,
) -> EvaluationWindow | None:
    raw_start_idx = 0
    raw_end_idx = len(samples) - 1
    start_idx = _first_consecutive_index(
        samples,
        raw_start_idx,
        raw_end_idx,
        lambda index, sample: (
            sample["z"] >= altitude_fraction * max(0.0, projections[index].reference_z)
        ),
        consecutive_samples,
    )
    if start_idx is None:
        return None
    end_idx = _last_before_landing_index(
        samples,
        projections,
        start_idx,
        raw_end_idx,
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


def _time_weighted_rms(
    values: list[float],
    samples: list[dict[str, Any]],
) -> float:
    if not values or len(values) != len(samples):
        raise RunnerError("time-weighted RMS requires one value per telemetry sample")
    if len(values) == 1:
        return abs(values[0])
    duration = float(samples[-1]["t"]) - float(samples[0]["t"])
    if duration <= 0:
        raise RunnerError("time-weighted RMS requires a positive time interval")
    integral = 0.0
    for index in range(1, len(values)):
        dt = float(samples[index]["t"]) - float(samples[index - 1]["t"])
        if dt <= 0:
            raise RunnerError("time-weighted RMS requires strictly increasing timestamps")
        integral += 0.5 * (values[index - 1] ** 2 + values[index] ** 2) * dt
    return math.sqrt(integral / duration)


def _compute_metrics(
    telemetry: dict[str, Any],
    reference_track: list[dict[str, float]],
    job_cfg: dict[str, Any],
    env: RunnerEnv,
    *,
    timeout_flag: bool,
    dry_run: bool,
    advanced_scenario_config: dict[str, Any] | None = None,
    scenario_effect_contract: dict[str, Any] | None = None,
) -> dict[str, Any]:
    samples = telemetry["samples"]
    telemetry_contract = verify_telemetry_semantic_contract(telemetry)
    if telemetry_contract is None:
        raise RunnerError("telemetry semantic contract is missing or does not match samples")
    synthetic_telemetry = dry_run or telemetry_contract.synthetic
    stationary_hover = job_cfg.get("track_type") == "hover"
    track_geometry = _build_track_geometry(
        reference_track,
        allow_stationary=stationary_hover,
    )
    projections = _project_samples_to_track(samples, track_geometry)
    altitude_fraction = env.eval_altitude_fraction
    near_track_threshold = env.eval_near_track_threshold_m
    consecutive_samples = env.eval_consecutive_samples
    total_sample_count = len(samples)

    offboard_timing_raw = str(telemetry.get("meta", {}).get("offboard_timing_path", "")).strip()
    offboard_timing_path = Path(offboard_timing_raw).expanduser()
    offboard_timing: dict[str, Any] | None = None
    if offboard_timing_raw:
        try:
            timing_size = _regular_file_size(
                offboard_timing_path,
                label="offboard timing evidence",
                required=False,
            )
            if timing_size is None:
                raise RunnerError("offboard timing evidence is missing or too large")
            loaded = _load_bounded_json(
                offboard_timing_path,
                label="offboard timing evidence",
                max_bytes=_MAX_OFFBOARD_TIMING_BYTES,
            )
            if isinstance(loaded, dict):
                offboard_timing = loaded
        except (OSError, UnicodeError, json.JSONDecodeError, ValueError, RunnerError):
            offboard_timing = None

    eval_window: EvaluationWindow | None = None
    if offboard_timing is not None:
        eval_window = _find_eval_window_from_timing(
            samples,
            projections,
            offboard_timing,
            altitude_fraction=altitude_fraction,
            near_track_threshold=near_track_threshold,
            consecutive_samples=consecutive_samples,
        )
    if eval_window is None:
        eval_window = _find_eval_window_from_telemetry(
            samples,
            projections,
            altitude_fraction=altitude_fraction,
            near_track_threshold=near_track_threshold,
            consecutive_samples=consecutive_samples,
        )
    if eval_window is None:
        eval_window = _find_altitude_only_window(
            samples,
            projections,
            altitude_fraction=altitude_fraction,
            consecutive_samples=consecutive_samples,
        )
    if eval_window is None:
        if not synthetic_telemetry:
            raise RunnerError(
                "trusted evaluation window could not be established from "
                "offboard timing or telemetry"
            )
        eval_window = EvaluationWindow(
            start_idx=0,
            end_idx=len(samples) - 1,
            source="synthetic_all_samples",
            raw_source="synthetic_all_samples",
            raw_start_t=None,
            raw_end_t=None,
            start_reason="synthetic_all_samples",
            trimmed_takeoff_samples=0,
            trimmed_landing_samples=0,
        )

    evaluation_samples = samples[eval_window.start_idx : eval_window.end_idx + 1]
    evaluation_projections = projections[eval_window.start_idx : eval_window.end_idx + 1]
    evaluation_sampling = compile_sampling_evidence(evaluation_samples)
    try:
        require_sampling_quality(
            evaluation_sampling,
            synthetic=synthetic_telemetry,
        )
    except TelemetrySemanticContractError as exc:
        raise RunnerError(f"evaluation-window sampling failed: {exc}") from exc

    errors = [projection.error for projection in projections]
    eval_errors = [projection.error for projection in evaluation_projections]

    rmse = _time_weighted_rms(eval_errors, evaluation_samples)
    max_error = max(eval_errors)
    max_error_idx = eval_errors.index(max_error)
    completion_time = evaluation_sampling.duration_s
    final_ref = reference_track[-1]
    final_error = math.sqrt(
        (evaluation_samples[-1]["x"] - final_ref["x"]) ** 2
        + (evaluation_samples[-1]["y"] - final_ref["y"]) ** 2
        + (evaluation_samples[-1]["z"] - final_ref["z"]) ** 2
    )

    overshoot_count = 0
    for i in range(2, len(eval_errors)):
        a = eval_errors[i - 2]
        b = eval_errors[i - 1]
        c = eval_errors[i]
        if b > a and b > c and b - max(a, c) > 0.25:
            overshoot_count += 1

    if eval_window.source == "all_samples_fallback":
        crash_flag = any(bool(s.get("crashed", False)) for s in samples)
        crash_reason = "telemetry_crashed_flag" if crash_flag else "none"
        if not crash_flag:
            crash_flag = any(
                projection.reference_z > 0.5 and sample["z"] < 0.2
                for sample, projection in zip(samples, projections, strict=True)
            )
            crash_reason = "all_samples_fallback_low_altitude" if crash_flag else "none"
    else:
        crash_flag = any(bool(s.get("crashed", False)) for s in evaluation_samples)
        crash_reason = "telemetry_crashed_flag" if crash_flag else "none"
        stable_altitude_seen = any(
            projection.reference_z > 0.5
            and sample["z"] >= altitude_fraction * projection.reference_z
            for sample, projection in zip(
                evaluation_samples,
                evaluation_projections,
                strict=True,
            )
        )
        if (
            not crash_flag
            and stable_altitude_seen
            and len(evaluation_samples) > consecutive_samples
        ):
            first_check_idx = consecutive_samples
            run = 0
            for i in range(first_check_idx, len(evaluation_samples)):
                reference_z = evaluation_projections[i].reference_z
                collapse_threshold = max(
                    0.2,
                    env.eval_collapse_altitude_fraction * reference_z,
                )
                if reference_z > 0.5 and evaluation_samples[i]["z"] < collapse_threshold:
                    run += 1
                    if run >= consecutive_samples:
                        crash_flag = True
                        crash_reason = "altitude_collapse_in_evaluation_window"
                        break
                else:
                    run = 0

    instability_flag = False
    instability_series = (
        samples if eval_window.source == "all_samples_fallback" else evaluation_samples
    )
    for i in range(1, len(instability_series)):
        dt = max(1e-6, instability_series[i]["t"] - instability_series[i - 1]["t"])
        jump = math.hypot(
            math.hypot(
                instability_series[i]["x"] - instability_series[i - 1]["x"],
                instability_series[i]["y"] - instability_series[i - 1]["y"],
            ),
            instability_series[i]["z"] - instability_series[i - 1]["z"],
        )
        if jump / dt > 25.0:
            instability_flag = True
            break
    if max_error > 30.0:
        instability_flag = True

    full_progress = _evaluate_track_progress(
        samples,
        projections,
        track_geometry,
        max_track_error=near_track_threshold,
    )
    evaluation_progress = _evaluate_track_progress(
        evaluation_samples,
        evaluation_projections,
        track_geometry,
        max_track_error=near_track_threshold,
    )
    track_coverage = full_progress.coverage
    evaluation_track_coverage = evaluation_progress.coverage
    backward_tolerance = max(0.1, track_geometry.total_length * 0.02)
    endpoint_tolerance = max(0.25, track_geometry.total_length * 0.01)
    start_progress = evaluation_progress.start_progress
    end_progress = evaluation_progress.end_progress
    if track_geometry.closed:
        start_reached = (
            start_progress is not None
            and min(
                start_progress,
                abs(track_geometry.total_length - start_progress),
            )
            <= endpoint_tolerance
        )
        endpoint_reached = final_error <= env.pass_max_error
    else:
        start_reached = start_progress is not None and start_progress <= endpoint_tolerance
        endpoint_reached = (
            end_progress is not None
            and end_progress >= track_geometry.total_length - endpoint_tolerance
            and final_error <= env.pass_max_error
        )
    direction_valid = evaluation_progress.backward_distance <= backward_tolerance
    progress_contract_ok = (
        direction_valid
        and evaluation_progress.discontinuity_count == 0
        and evaluation_progress.directed_progress_fraction >= env.min_track_coverage
        and start_reached
        and endpoint_reached
    )
    effect_contract = dict(scenario_effect_contract or {})
    unsupported_effects = list(effect_contract.get("unsupported_effects") or [])
    failed_effects = list(effect_contract.get("failed_effects") or [])
    pending_effects = list(effect_contract.get("pending_effects") or [])
    pass_flag = (
        (not crash_flag)
        and (not timeout_flag)
        and (not instability_flag)
        and rmse <= env.pass_rmse
        and max_error <= env.pass_max_error
        and evaluation_track_coverage >= env.min_track_coverage
        and progress_contract_ok
        and not unsupported_effects
        and not failed_effects
        and not pending_effects
    )

    penalty = 0.0
    if crash_flag:
        penalty += 100.0
    if timeout_flag:
        penalty += 120.0
    if instability_flag:
        penalty += 80.0
    if evaluation_track_coverage < env.min_track_coverage or not progress_contract_ok:
        penalty += 20.0
    score = rmse + (0.5 * max_error) + (0.05 * completion_time) + penalty

    advanced = dict(advanced_scenario_config or {})
    sensor_deg = (
        advanced.get("sensor_degradation")
        if isinstance(advanced.get("sensor_degradation"), dict)
        else {}
    )
    obstacle_count = (
        len(advanced.get("obstacles", [])) if isinstance(advanced.get("obstacles"), list) else 0
    )
    wind_gusts = advanced.get("wind_gusts") if isinstance(advanced.get("wind_gusts"), dict) else {}
    wind_gust_enabled_raw = wind_gusts.get("enabled", False)
    if not isinstance(wind_gust_enabled_raw, bool):
        raise RunnerError("advanced_scenario_config.wind_gusts.enabled must be boolean")
    wind_gust_enabled = wind_gust_enabled_raw
    dropout_rate_raw = sensor_deg.get("dropout_rate", 0.0) if sensor_deg else 0.0
    if isinstance(dropout_rate_raw, bool) or not isinstance(dropout_rate_raw, (int, float)):
        raise RunnerError(
            "advanced_scenario_config.sensor_degradation.dropout_rate must be numeric"
        )
    dropout_rate = float(dropout_rate_raw)
    if not math.isfinite(dropout_rate) or not 0 <= dropout_rate <= 1:
        raise RunnerError(
            "advanced_scenario_config.sensor_degradation.dropout_rate must be in [0, 1]"
        )
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
            "evaluation_directed_progress_fraction": round(
                evaluation_progress.directed_progress_fraction, 6
            ),
            "evaluation_backward_distance_m": round(evaluation_progress.backward_distance, 6),
            "evaluation_progress_discontinuity_count": (evaluation_progress.discontinuity_count),
            "evaluation_direction_valid": direction_valid,
            "evaluation_start_reached": start_reached,
            "evaluation_endpoint_reached": endpoint_reached,
            "evaluation_progress_contract_ok": progress_contract_ok,
            "track_length_3d_m": round(track_geometry.total_length, 6),
            "track_is_closed": track_geometry.closed,
            "track_projection": (
                "stationary_point_3d_projection"
                if track_geometry.stationary
                else "ordered_local_3d_segment_projection"
            ),
            "track_projection_comparison_limit": _MAX_PROJECTION_SEGMENT_COMPARISONS,
            "coverage_basis": (
                "stationary_hover_time_weighted_trapezoidal_in_tolerance"
                if track_geometry.stationary
                else "union_of_traversed_polyline_arc_length"
            ),
            "track_mode": "stationary_hover" if track_geometry.stationary else "trajectory",
            "hover_minimum_evaluation_duration_s": (
                _HOVER_MIN_EVALUATION_DURATION_SECONDS if track_geometry.stationary else None
            ),
            "full_log_rmse": round(
                _time_weighted_rms(errors, samples),
                6,
            ),
            "full_log_max_error": round(max(errors), 6),
            "pass_thresholds": {
                "rmse": env.pass_rmse,
                "max_error": env.pass_max_error,
                "min_track_coverage": env.min_track_coverage,
            },
            "evaluation_window_source": eval_window.source,
            "evaluation_window_raw_source": eval_window.raw_source,
            "raw_track_start_t": (
                round(float(eval_window.raw_start_t), 6)
                if eval_window.raw_start_t is not None
                else None
            ),
            "raw_track_end_t": (
                round(float(eval_window.raw_end_t), 6)
                if eval_window.raw_end_t is not None
                else None
            ),
            "evaluation_start_t": round(float(evaluation_samples[0]["t"]), 6),
            "evaluation_end_t": round(float(evaluation_samples[-1]["t"]), 6),
            "evaluation_start_index": eval_window.start_idx,
            "evaluation_end_index": eval_window.end_idx,
            "evaluation_sample_count": len(evaluation_samples),
            "total_sample_count": total_sample_count,
            "rmse_integration": "time_weighted_trapezoidal",
            "telemetry_semantic_contract_id": (telemetry_contract.contract_id),
            "telemetry_verifier_revision": (telemetry_contract.verifier_revision),
            "telemetry_coordinate_frame": (telemetry_contract.coordinate_frame),
            "telemetry_position_unit": telemetry_contract.position_unit,
            "telemetry_time_unit": telemetry_contract.time_unit,
            "telemetry_source_sha256": telemetry_contract.source_sha256,
            "telemetry_sampling": (telemetry_contract.sampling.model_dump(mode="json")),
            "evaluation_sampling": evaluation_sampling.model_dump(mode="json"),
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
                "reference_x": round(float(evaluation_projections[max_error_idx].reference_x), 6),
                "reference_y": round(float(evaluation_projections[max_error_idx].reference_y), 6),
                "reference_z": round(float(evaluation_projections[max_error_idx].reference_z), 6),
                "track_progress_m": round(float(evaluation_projections[max_error_idx].progress), 6),
                "error": round(float(max_error), 6),
            },
            "crash_reason": crash_reason,
            "mode": "dry_run" if dry_run else "real",
            "vehicle": job_cfg["vehicle_profile"]["simulator_model"],
            "airframe": job_cfg["vehicle_profile"]["airframe"],
            "simulator_model": job_cfg["vehicle_profile"]["simulator_model"],
            "world": job_cfg["vehicle_profile"]["world"],
            "px4_version": job_cfg["vehicle_profile"]["px4_version"],
            "advanced_scenario_summary": {
                "enabled": bool(effect_contract.get("requested_effects")),
                "obstacle_count": obstacle_count,
                "dropout_rate": dropout_rate,
                "wind_gust_enabled": wind_gust_enabled,
                "requested_effects": list(effect_contract.get("requested_effects") or []),
                "applied_effects": list(effect_contract.get("applied_effects") or []),
                "unsupported_effects": unsupported_effects,
                "failed_effects": failed_effects,
                "pending_effects": pending_effects,
                "capabilities": list(effect_contract.get("capabilities") or []),
                "verification_status": effect_contract.get("verification_status", "not_requested"),
                "unverified_passthrough_enabled": bool(
                    effect_contract.get("unverified_passthrough_enabled", False)
                ),
            },
        },
    }


def _write_trajectory_json(telemetry: dict[str, Any], path: Path) -> None:
    samples = telemetry["samples"]
    simplified = [{"t": s["t"], "x": s["x"], "y": s["y"], "z": s["z"]} for s in samples]
    _json_dump(path, {"schema_version": "dronedream.telemetry.v1", "samples": simplified})


def _artifact_record(
    path: Path, artifact_type: str, display_name: str, mime_type: str
) -> dict[str, Any]:
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
    argv = _split_command(command)
    if not argv:
        return False
    first = argv[0]
    executable_tokens = {
        "{px4_executable}": "DRONEDREAM_PX4_EXECUTABLE",
        "{gazebo_executable}": "DRONEDREAM_GAZEBO_EXECUTABLE",
    }
    if first in executable_tokens:
        first = os.environ.get(executable_tokens[first], "").strip()
        if not first:
            return False
    if os.path.isabs(first) or first.startswith("."):
        return Path(first).exists() and os.access(first, os.X_OK)
    return shutil.which(first) is not None


def _split_command(command: str) -> list[str]:
    """Split a configured command without eating Windows path separators."""

    argv = shlex.split(command, posix=os.name != "nt")
    if os.name == "nt":
        return [
            item[1:-1] if len(item) >= 2 and item[0] == item[-1] and item[0] in {'"', "'"} else item
            for item in argv
        ]
    return argv


def _build_launch_argv(command_template: str, values: dict[str, str]) -> list[str]:
    has_token = any("{" + token + "}" in command_template for token in _TEMPLATE_TOKENS)
    if has_token:
        template_argv = _split_command(command_template)
        rendered_argv: list[str] = []
        for item in template_argv:
            # ``extra_args`` is the only intentionally multi-argument token.
            # Every path/value token is substituted *after* splitting so a
            # workspace path containing spaces remains exactly one argv item.
            if item == "{extra_args}":
                rendered_argv.extend(_split_command(values.get("extra_args", "")))
                continue
            rendered = item
            for token, value in values.items():
                rendered = rendered.replace("{" + token + "}", value)
            rendered_argv.append(rendered)
        return rendered_argv

    argv = _split_command(command_template)
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
    *,
    launch_argv: list[str],
    cwd: Path,
    stdout_log: Path,
    stderr_log: Path,
    timeout_seconds: float,
    launch_env: dict[str, str] | None = None,
) -> int:
    with (
        stdout_log.open("w", encoding="utf-8") as out,
        stderr_log.open("w", encoding="utf-8") as err,
    ):
        creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) if os.name == "nt" else 0
        proc = subprocess.Popen(  # noqa: S603
            launch_argv,
            cwd=str(cwd),
            stdout=out,
            stderr=err,
            text=True,
            start_new_session=os.name != "nt",
            creationflags=creationflags,
            env=launch_env,
        )
        previous_signal_handlers: dict[int, Any] = {}

        def _forward_shutdown(signum: int, _frame: Any) -> None:
            _terminate_subprocess_tree(proc, force=True)
            raise SystemExit(128 + signum)

        if os.name != "nt":
            for shutdown_signal in (signal.SIGINT, signal.SIGTERM):
                previous_signal_handlers[int(shutdown_signal)] = signal.getsignal(shutdown_signal)
                signal.signal(shutdown_signal, _forward_shutdown)
        try:
            return proc.wait(timeout=timeout_seconds)
        except subprocess.TimeoutExpired as exc:
            _terminate_subprocess_tree(proc, force=False)
            time.sleep(0.2)
            _terminate_subprocess_tree(proc, force=True)
            raise TimeoutRunnerError(
                f"lower-level launcher timed out after {timeout_seconds:g}s"
            ) from exc
        finally:
            for shutdown_signal, previous_handler in previous_signal_handlers.items():
                signal.signal(shutdown_signal, previous_handler)


def _terminate_subprocess_tree(proc: subprocess.Popen[str], *, force: bool) -> None:
    """Terminate a launcher safely on both POSIX and native Windows."""

    if proc.poll() is not None:
        return
    if os.name == "nt":
        taskkill = ["taskkill", "/PID", str(proc.pid), "/T"]
        if force:
            taskkill.append("/F")
        with contextlib.suppress(OSError, subprocess.SubprocessError):
            subprocess.run(  # noqa: S603, S607 - fixed system utility.
                taskkill,
                capture_output=True,
                check=False,
                timeout=10,
            )
        if proc.poll() is None:
            with contextlib.suppress(OSError):
                proc.kill() if force else proc.terminate()
        return
    with contextlib.suppress(OSError):
        os.killpg(proc.pid, signal.SIGKILL if force else signal.SIGTERM)


def _failure_result(
    reason: str, code: str, artifacts: list[dict[str, Any]], log_excerpt: str
) -> dict[str, Any]:
    return {
        "success": False,
        "failure": {"code": code, "reason": reason},
        "artifacts": artifacts,
        "log_excerpt": _safe_excerpt(log_excerpt),
    }


def _collect_artifacts(run_dir: Path) -> list[dict[str, Any]]:
    records = [
        _artifact_record(
            run_dir / "telemetry.json",
            "telemetry_json",
            "Telemetry",
            "application/json",
        ),
        _artifact_record(
            run_dir / "reference_track.json",
            "reference_track_json",
            "Reference Track",
            "application/json",
        ),
        _artifact_record(
            run_dir / "scenario_config.json",
            "scenario_config_json",
            "Scenario Configuration",
            "application/json",
        ),
        _artifact_record(
            run_dir / REQUEST_ARTIFACT_NAME,
            "scenario_effect_request_json",
            "Scenario Effect Request",
            "application/json",
        ),
        _artifact_record(
            run_dir / EVIDENCE_ARTIFACT_NAME,
            "scenario_effect_evidence_json",
            "Scenario Effect Evidence",
            "application/json",
        ),
        _artifact_record(
            run_dir / "controller_params.json",
            "controller_parameters_json",
            "Controller Parameters",
            "application/json",
        ),
        _artifact_record(
            run_dir / "px4_parameters.input.json",
            "px4_parameters_input_json",
            "PX4 Parameter Input",
            "application/json",
        ),
        _artifact_record(
            run_dir / "launch_config.json",
            "simulator_launch_config_json",
            "Simulator Launch Configuration",
            "application/json",
        ),
        _artifact_record(
            run_dir / "simulator_runtime_manifest.json",
            "simulator_runtime_manifest_json",
            "Simulator Runtime Manifest",
            "application/json",
        ),
        _artifact_record(
            run_dir / "trajectory.json",
            "trajectory_json",
            "Trajectory Samples",
            "application/json",
        ),
        _artifact_record(
            run_dir / "px4_source.ulg",
            "px4_ulog",
            "Retained PX4 ULog",
            "application/octet-stream",
        ),
        _artifact_record(run_dir / "runner.log", "worker_log", "Runner Log", "text/plain"),
        _artifact_record(
            run_dir / "stdout.log", "simulator_stdout", "Simulator stdout", "text/plain"
        ),
        _artifact_record(
            run_dir / "stderr.log", "simulator_stderr", "Simulator stderr", "text/plain"
        ),
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
            run_dir / "launcher_failure.json",
            "launcher_failure_json",
            "Launcher Failure",
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
        _artifact_record(
            run_dir / REQUESTED_EVIDENCE_NAME,
            "px4_parameter_evidence_json",
            "PX4 Parameters Requested",
            "application/json",
        ),
        _artifact_record(
            run_dir / BEFORE_EVIDENCE_NAME,
            "px4_parameter_evidence_json",
            "PX4 Parameters Before",
            "application/json",
        ),
        _artifact_record(
            run_dir / APPLIED_EVIDENCE_NAME,
            "px4_parameter_evidence_json",
            "PX4 Parameters Applied",
            "application/json",
        ),
    ]
    return [r for r in records if r]


def _remove_success_raw_logs(run_dir: Path) -> None:
    """Honor KEEP_RAW_LOGS only after successful metric computation."""

    for name in (
        "stdout.log",
        "stderr.log",
        "gui_stdout.log",
        "gui_stderr.log",
        "track_marker_stdout.log",
        "track_marker_stderr.log",
    ):
        with contextlib.suppress(OSError):
            (run_dir / name).unlink(missing_ok=True)


def _require_verified_px4_parameter_evidence(
    run_dir: Path,
    requested: dict[str, int | float],
    *,
    expected_px4_version: str,
) -> None:
    """Reject a trial before metrics if its requested parameters lack proof."""

    if not requested:
        return
    evidence: dict[str, dict[str, Any]] = {}
    for filename in (
        REQUESTED_EVIDENCE_NAME,
        BEFORE_EVIDENCE_NAME,
        APPLIED_EVIDENCE_NAME,
    ):
        path = run_dir / filename
        if not path.is_file():
            raise RunnerError(f"PX4 parameter evidence missing: {filename}")
        payload = json.loads(
            path.read_text(encoding="utf-8"),
            parse_constant=_reject_nonfinite_json,
        )
        if not isinstance(payload, dict):
            raise RunnerError(f"PX4 parameter evidence must be an object: {filename}")
        try:
            evidence_version = normalize_px4_version(str(payload.get("px4_version")))
        except ValueError as exc:
            raise RunnerError(f"PX4 parameter evidence has invalid version: {filename}") from exc
        if evidence_version != expected_px4_version:
            raise RunnerError(f"PX4 parameter evidence version mismatch: {filename}")
        evidence[filename] = payload

    requested_values = evidence[REQUESTED_EVIDENCE_NAME].get("values")
    if not isinstance(requested_values, dict) or requested_values != requested:
        raise RunnerError("PX4 requested-parameter evidence does not match the trial request")
    applied_values = evidence[APPLIED_EVIDENCE_NAME].get("values")
    verification = evidence[APPLIED_EVIDENCE_NAME].get("verification")
    if not isinstance(applied_values, dict) or not isinstance(verification, dict):
        raise RunnerError("PX4 applied-parameter evidence is malformed")
    if verification.get("verified") is not True:
        raise RunnerError("PX4 parameter readback was not verified")
    if set(applied_values) != set(requested):
        raise RunnerError("PX4 applied-parameter evidence has missing or unexpected names")
    for name, expected in requested.items():
        actual = applied_values.get(name)
        if isinstance(actual, bool) or not isinstance(actual, (int, float)):
            raise RunnerError(f"PX4 applied-parameter evidence has invalid value for {name}")
        definition = get_parameter(name, px4_version=expected_px4_version)
        if definition is None:
            raise RunnerError(f"PX4 applied-parameter evidence contains unknown parameter: {name}")
        tolerance = (
            0.0 if definition.value_type == "int" else max(float(definition.step) / 10.0, 1e-6)
        )
        if not math.isfinite(float(actual)) or not math.isclose(
            float(actual),
            float(expected),
            rel_tol=0.0,
            abs_tol=tolerance,
        ):
            raise RunnerError(f"PX4 applied-parameter evidence does not match request for {name}")


def run_once(input_path: Path, output_path: Path) -> int:
    run_dir = output_path.parent
    run_dir.mkdir(parents=True, exist_ok=True)

    runner_log = run_dir / "runner.log"
    stdout_log = run_dir / "stdout.log"
    stderr_log = run_dir / "stderr.log"
    telemetry_json = run_dir / "telemetry.json"
    trajectory_json = run_dir / "trajectory.json"
    params_json = run_dir / "controller_params.json"
    px4_params_json = run_dir / "px4_parameters.input.json"
    track_json = run_dir / "reference_track.json"
    scenario_config_json = run_dir / "scenario_config.json"
    scenario_effect_request_json = run_dir / REQUEST_ARTIFACT_NAME
    scenario_effect_evidence_json = run_dir / EVIDENCE_ARTIFACT_NAME
    meta: dict[str, Any] | None = None

    def log(msg: str) -> None:
        with runner_log.open("a", encoding="utf-8") as f:
            f.write(msg + "\n")

    def write_result(result: dict[str, Any]) -> None:
        payload = dict(result)
        if meta is not None:
            payload["schema_version"] = "dronedream.trial_result.v2"
            payload["execution_identity"] = {
                "trial_id": meta["trial_id"],
                "job_id": meta["job_id"],
                "candidate_id": meta["candidate_id"],
                "seed": meta["seed"],
                "attempt_count": meta["attempt_count"],
            }
        _json_dump(output_path, payload)

    try:
        try:
            env = _load_env()
        except (ConfigurationRunnerError, ValueError) as exc:
            result = _failure_result(
                f"Invalid PX4/Gazebo runner configuration: {exc}",
                FAILURE_ADAPTER_UNAVAILABLE,
                _collect_artifacts(run_dir),
                f"runner configuration error: {exc}",
            )
            write_result(result)
            return 0
        payload = _load_trial_payload(input_path)

        job_cfg, params, px4_params, meta = _validate_trial_input(
            payload,
            default_px4_version=env.px4_version,
            default_vehicle=env.vehicle,
            default_world=env.world,
            default_headless=env.headless,
            enforce_safe_parameter_bounds=env.enforce_safe_parameter_bounds,
        )
        effective_launcher_timeout = _effective_timeout_seconds(
            float(env.timeout_seconds),
            float(meta["simulation_speed_factor"]),
        )
        firmware_identity = _firmware_identity(meta.get("firmware_commit"))
        engine_pack_identity = _engine_pack_identity()
        scenario_effect_request = meta["scenario_effect_request"]
        scenario_effect_contract = _scenario_effect_contract(
            meta.get("advanced_scenario_config"),
            scenario_type=str(meta["scenario_type"]),
            scenario_config=meta.get("scenario_config"),
            job_config=job_cfg,
            effect_request=scenario_effect_request,
            dry_run=env.dry_run,
            allow_unverified_passthrough=env.allow_unverified_advanced_effects,
        )
        runner_launch_config = {
            "vehicle": meta["vehicle"],
            "airframe": meta["airframe"],
            "simulator_model": meta["simulator_model"],
            "world": meta["world"],
            "headless": meta["headless"],
            "simulation_speed_factor": meta["simulation_speed_factor"],
            "instance_id": meta["instance_id"],
            "instance_management": "operator_managed",
            "timeout_base_1x_seconds": env.timeout_seconds,
            "timeout_effective_seconds": effective_launcher_timeout,
            "timeout_slow_simulation_multiplier_cap": (_MAX_SLOW_SIMULATION_TIMEOUT_MULTIPLIER),
            "extra_args": env.extra_args,
            "scenario_type": meta["scenario_type"],
            "advanced_scenario_config": meta.get("advanced_scenario_config", {}),
            "px4_version": meta["px4_version"],
            "firmware_identity": firmware_identity,
            "engine_pack_identity": engine_pack_identity,
            "scenario_effect_contract": scenario_effect_contract,
            "scenario_effect_request": {
                "path": str(scenario_effect_request_json),
                "schema_version": scenario_effect_request["schema_version"],
                "request_sha256": scenario_effect_request["request_sha256"],
            },
            "scenario_effect_evidence": {
                "path": str(scenario_effect_evidence_json),
                "required": bool(scenario_effect_request["effects"]),
            },
            "parameter_catalog_version": meta["parameter_catalog_version"],
            "px4_parameter_names": sorted(px4_params),
        }
        write_effect_json_atomic(scenario_effect_request_json, scenario_effect_request)
        _json_dump(run_dir / "launch_config.json", runner_launch_config)
        _json_dump(
            run_dir / "simulator_runtime_manifest.json",
            {
                "schema_version": "dronedream.simulator_runtime_manifest.v1",
                "execution_identity": {
                    "trial_id": meta["trial_id"],
                    "job_id": meta["job_id"],
                    "candidate_id": meta["candidate_id"],
                    "seed": meta["seed"],
                    "attempt_count": meta["attempt_count"],
                },
                "px4_version": meta["px4_version"],
                "firmware_identity": firmware_identity,
                "engine_pack_identity": engine_pack_identity,
                "scenario_effect_contract": scenario_effect_contract,
                "scenario_effect_request": {
                    "path": str(scenario_effect_request_json),
                    "schema_version": scenario_effect_request["schema_version"],
                    "request_sha256": scenario_effect_request["request_sha256"],
                },
                "scenario_effect_evidence": {
                    "path": str(scenario_effect_evidence_json),
                    "required": bool(scenario_effect_request["effects"]),
                },
                "simulator": {
                    "airframe": meta["airframe"],
                    "simulator_model": meta["simulator_model"],
                    "world": meta["world"],
                    "headless": meta["headless"],
                    "simulation_speed_factor": meta["simulation_speed_factor"],
                    "instance_id": meta["instance_id"],
                },
                "timeout": {
                    "base_1x_seconds": env.timeout_seconds,
                    "effective_seconds": effective_launcher_timeout,
                    "slow_simulation_multiplier_cap": (_MAX_SLOW_SIMULATION_TIMEOUT_MULTIPLIER),
                },
            },
        )
        _enforce_firmware_identity(firmware_identity)
        _enforce_engine_pack_firmware_binding(engine_pack_identity, firmware_identity)
        _enforce_scenario_effect_contract(scenario_effect_contract)

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
                "schema_version": "dronedream.reference_track.v1",
                "track_type": job_cfg["track_type"],
                "hover_duration_s": (
                    _HOVER_DURATION_SECONDS if job_cfg["track_type"] == "hover" else None
                ),
                "points": reference_track,
                "reference_track": reference_track,
            },
        )
        _json_dump(params_json, params)
        _json_dump(px4_params_json, px4_params)
        _json_dump(
            scenario_config_json,
            {
                "schema_version": "dronedream.scenario_config.v1",
                "scenario_type": meta["scenario_type"],
                "seed": meta["seed"],
                "wind": job_cfg["wind"],
                "sensor_noise_level": job_cfg["sensor_noise_level"],
                "scenario_config": meta.get("scenario_config", {}),
                "advanced_scenario_config": meta.get("advanced_scenario_config", {}),
            },
        )

        timeout_flag = False
        if env.dry_run:
            if px4_params:
                write_simulated_parameter_evidence(
                    px4_params,
                    run_dir,
                    px4_version=str(meta["px4_version"]),
                    context={
                        "trial_id": meta["trial_id"],
                        "job_id": meta["job_id"],
                        "candidate_id": meta["candidate_id"],
                    },
                    enforce_safe_bounds=env.enforce_safe_parameter_bounds,
                )
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
                write_result(result)
                return 0
            if not _command_is_executable(env.launch_command):
                result = _failure_result(
                    "PX4_GAZEBO_LAUNCH_COMMAND is not executable",
                    FAILURE_ADAPTER_UNAVAILABLE,
                    _collect_artifacts(run_dir),
                    f"command not executable: {env.launch_command}",
                )
                write_result(result)
                return 0

            configured_executables: dict[str, str] = {}
            for token, environment_name in (
                ("px4_executable", "DRONEDREAM_PX4_EXECUTABLE"),
                ("gazebo_executable", "DRONEDREAM_GAZEBO_EXECUTABLE"),
            ):
                configured = os.environ.get(environment_name, "").strip()
                configured_executables[token] = configured
                if "{" + token + "}" not in env.launch_command:
                    continue
                executable_path = Path(configured).expanduser() if configured else None
                if (
                    executable_path is None
                    or not executable_path.is_file()
                    or not os.access(executable_path, os.X_OK)
                ):
                    result = _failure_result(
                        f"{environment_name} must point to an executable file when "
                        f"{{{token}}} is used",
                        FAILURE_ADAPTER_UNAVAILABLE,
                        _collect_artifacts(run_dir),
                        f"invalid configured executable: {environment_name}",
                    )
                    write_result(result)
                    return 0

            values = {
                "run_dir": str(run_dir),
                "trial_input": str(input_path),
                "trial_output": str(output_path),
                "params_json": str(params_json),
                "px4_params_json": str(px4_params_json),
                "scenario_config_json": str(scenario_config_json),
                "scenario_effect_request_json": str(scenario_effect_request_json),
                "scenario_effect_evidence_json": str(scenario_effect_evidence_json),
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
                "vehicle": meta["vehicle"],
                "airframe": meta["airframe"],
                "simulator_model": meta["simulator_model"],
                "world": meta["world"],
                "px4_version": meta["px4_version"],
                "headless": "true" if meta["headless"] else "false",
                "extra_args": env.extra_args,
                "instance_id": str(meta["instance_id"]),
                "simulation_speed_factor": str(meta["simulation_speed_factor"]),
                **configured_executables,
            }
            argv = _build_launch_argv(env.launch_command, values)
            cwd = Path(env.workdir).expanduser().resolve() if env.workdir else run_dir
            if not cwd.is_dir():
                result = _failure_result(
                    f"PX4_GAZEBO_WORKDIR is not a directory: {cwd}",
                    FAILURE_ADAPTER_UNAVAILABLE,
                    _collect_artifacts(run_dir),
                    "invalid PX4_GAZEBO_WORKDIR",
                )
                write_result(result)
                return 0
            launch_env = os.environ.copy()
            launch_env.update(
                {
                    "PX4_TRIAL_AIRFRAME": str(meta["airframe"]),
                    "PX4_TRIAL_SIMULATOR_MODEL": str(meta["simulator_model"]),
                    "PX4_TRIAL_WORLD": str(meta["world"]),
                    "PX4_TRIAL_PX4_VERSION": str(meta["px4_version"]),
                    "PX4_TRIAL_SEED": str(meta["seed"]),
                    "PX4_TRIAL_ATTEMPT": str(meta["attempt_count"]),
                    "PX4_TRIAL_SCENARIO_TYPE": str(meta["scenario_type"]),
                    "PX4_TRIAL_SCENARIO_CONFIG_PATH": str(scenario_config_json),
                    "PX4_TRIAL_SCENARIO_EFFECT_REQUEST_PATH": str(scenario_effect_request_json),
                    "PX4_TRIAL_SCENARIO_EFFECT_EVIDENCE_PATH": str(scenario_effect_evidence_json),
                    "PX4_TRIAL_WIND_JSON": json.dumps(job_cfg["wind"], sort_keys=True),
                    "PX4_TRIAL_SENSOR_NOISE_LEVEL": str(job_cfg["sensor_noise_level"]),
                    "PX4_TRIAL_HEADLESS": "true" if meta["headless"] else "false",
                    "PX4_INSTANCE": str(meta["instance_id"]),
                    # Official PX4 SITL speed-factor environment variable.
                    "PX4_SIM_SPEED_FACTOR": str(meta["simulation_speed_factor"]),
                    "PX4_GAZEBO_TIMEOUT_BASE_1X_SECONDS": str(env.timeout_seconds),
                    "PX4_GAZEBO_TIMEOUT_EFFECTIVE_SECONDS": str(effective_launcher_timeout),
                    "PX4_FIRMWARE_COMMIT_REQUESTED": str(
                        firmware_identity.get("requested_commit") or ""
                    ),
                    "PX4_FIRMWARE_COMMIT_OBSERVED": str(
                        firmware_identity.get("observed_commit") or ""
                    ),
                    "PX4_FIRMWARE_VERIFICATION_STATUS": str(firmware_identity.get("status") or ""),
                }
            )
            if px4_params:
                launch_env["PX4_PARAMETER_REQUEST_PATH"] = str(px4_params_json)
                launch_env["PX4_PARAMETER_PX4_VERSION"] = str(meta["px4_version"])
                launch_env["PX4_PARAMETER_CONTEXT_JSON"] = json.dumps(
                    {
                        "trial_id": meta["trial_id"],
                        "job_id": meta["job_id"],
                        "candidate_id": meta["candidate_id"],
                    }
                )
                launch_env["PX4_PARAMETER_ENFORCE_SAFE_BOUNDS"] = (
                    "true" if env.enforce_safe_parameter_bounds else "false"
                )
            log(f"launch executable: {argv[0]} (argc={len(argv)})")
            log(f"launch cwd: {cwd}")
            log(
                "launch timeout: "
                f"base_1x={env.timeout_seconds}s "
                f"speed_factor={meta['simulation_speed_factor']} "
                f"effective={effective_launcher_timeout:g}s"
            )
            try:
                exit_code = _run_lower_level_launcher(
                    launch_argv=argv,
                    cwd=cwd,
                    stdout_log=stdout_log,
                    stderr_log=stderr_log,
                    timeout_seconds=effective_launcher_timeout,
                    launch_env=launch_env,
                )
            except TimeoutRunnerError as exc:
                _merge_json_object(run_dir / "launch_config.json", runner_launch_config)
                timeout_flag = True
                result = _failure_result(
                    str(exc),
                    FAILURE_TIMEOUT,
                    _collect_artifacts(run_dir),
                    str(exc),
                )
                write_result(result)
                return 0
            _merge_json_object(run_dir / "launch_config.json", runner_launch_config)
            log(f"launcher exit code: {exit_code}")
            if scenario_effect_request["effects"]:
                try:
                    _require_effect_evidence_file(scenario_effect_evidence_json)
                    verified_effects = load_scenario_effect_evidence(
                        scenario_effect_evidence_json,
                        scenario_effect_request,
                    )
                except ScenarioEffectContractError as exc:
                    requested_effect_ids = list(scenario_effect_contract["requested_effects"])
                    verified_effects = {
                        "applied_effects": [],
                        "unsupported_effects": requested_effect_ids,
                        "failed_effects": [],
                        "pending_effects": [],
                        "verification_status": (
                            "unverified_passthrough"
                            if env.allow_unverified_advanced_effects
                            else "invalid_launcher_evidence"
                        ),
                        "evidence_error": str(exc),
                        "capabilities": [
                            {
                                "effect_id": effect_id,
                                "status": "unsupported",
                                "reason": (
                                    "launcher evidence was missing or invalid while "
                                    "unverified passthrough was enabled: " + str(exc)
                                ),
                            }
                            for effect_id in requested_effect_ids
                        ],
                    }
                scenario_effect_contract.update(verified_effects)
                scenario_effect_contract["pending_effects"] = []
                evidence_manifest = {
                    "path": str(scenario_effect_evidence_json),
                    "required": True,
                    "verification_status": scenario_effect_contract["verification_status"],
                    "schema_version": verified_effects.get("evidence_schema_version"),
                }
                runner_launch_config["scenario_effect_contract"] = scenario_effect_contract
                runner_launch_config["scenario_effect_evidence"] = evidence_manifest
                _merge_json_object(run_dir / "launch_config.json", runner_launch_config)
                _merge_json_object(
                    run_dir / "simulator_runtime_manifest.json",
                    {
                        "scenario_effect_contract": scenario_effect_contract,
                        "scenario_effect_evidence": evidence_manifest,
                    },
                )
                if scenario_effect_contract.get("failed_effects"):
                    raise RunnerError(
                        "launcher failed to apply scenario effects: "
                        + ", ".join(scenario_effect_contract["failed_effects"])
                    )
                _enforce_scenario_effect_contract(scenario_effect_contract)
            if exit_code != 0:
                failure_reason = _lower_level_failure_reason(run_dir, exit_code)
                result = _failure_result(
                    failure_reason,
                    FAILURE_SIMULATION,
                    _collect_artifacts(run_dir),
                    failure_reason,
                )
                write_result(result)
                return 0

        _require_verified_px4_parameter_evidence(
            run_dir,
            px4_params,
            expected_px4_version=str(meta["px4_version"]),
        )

        telemetry = _load_telemetry(telemetry_json, allow_csv=env.allow_csv_telemetry)
        if telemetry.get("schema_version") != TELEMETRY_SCHEMA_V2:
            raise RunnerError("normalized telemetry did not produce the v2 semantic contract")
        telemetry.setdefault("meta", {})
        telemetry["meta"]["offboard_timing_path"] = str(run_dir / "offboard_timing.json")
        # Persist the normalized contract, not the launcher's potentially
        # legacy shape, because this exact file is exposed as telemetry_json.
        _json_dump(telemetry_json, telemetry)
        if telemetry_json.stat().st_size > _MAX_TELEMETRY_BYTES:
            raise RunnerError(
                f"normalized telemetry JSON exceeds the {_MAX_TELEMETRY_BYTES}-byte contract limit"
            )
        _write_trajectory_json(telemetry, trajectory_json)

        metrics = _compute_metrics(
            telemetry,
            reference_track,
            job_cfg,
            env,
            timeout_flag=timeout_flag,
            dry_run=env.dry_run,
            advanced_scenario_config=(
                meta.get("advanced_scenario_config")
                if isinstance(meta.get("advanced_scenario_config"), dict)
                else {}
            ),
            scenario_effect_contract=scenario_effect_contract,
        )
        try:
            reference_track_payload = {
                "schema_version": "dronedream.reference_track.v1",
                "track_type": job_cfg["track_type"],
                "hover_duration_s": (
                    _HOVER_DURATION_SECONDS if job_cfg["track_type"] == "hover" else None
                ),
                "reference_track": reference_track,
            }
            evaluation_policy = compile_px4_evaluation_policy(
                pass_rmse_m=env.pass_rmse,
                pass_max_error_m=env.pass_max_error,
                minimum_track_coverage=env.min_track_coverage,
                altitude_entry_fraction=env.eval_altitude_fraction,
                near_track_threshold_m=(env.eval_near_track_threshold_m),
                consecutive_samples=env.eval_consecutive_samples,
                collapse_altitude_fraction=(env.eval_collapse_altitude_fraction),
            )
            offboard_timing_payload: object | None = None
            offboard_timing_path = run_dir / "offboard_timing.json"
            if offboard_timing_path.is_file():
                try:
                    loaded_timing = _load_bounded_json(
                        offboard_timing_path,
                        label="offboard timing evidence",
                        max_bytes=_MAX_OFFBOARD_TIMING_BYTES,
                    )
                    if isinstance(loaded_timing, dict):
                        offboard_timing_payload = loaded_timing
                except RunnerError:
                    offboard_timing_payload = None
            evaluation_window_evidence = compile_px4_evaluation_window_evidence(
                telemetry_payload=telemetry,
                reference_track_payload=reference_track_payload,
                offboard_timing_payload=offboard_timing_payload,
                policy=evaluation_policy,
            )
            metrics["raw_metric_json"]["evaluation_policy"] = evaluation_policy.model_dump(
                mode="json"
            )
            metrics["raw_metric_json"]["evaluation_window_evidence"] = (
                evaluation_window_evidence.model_dump(mode="json")
            )
            require_px4_evaluation_window_binding(
                metrics["raw_metric_json"],
                policy=evaluation_policy,
                evidence=evaluation_window_evidence,
            )
            core_metric_evidence = compile_px4_core_metric_evidence(
                telemetry_payload=telemetry,
                reference_track_payload=reference_track_payload,
                evaluation_start_index=(evaluation_window_evidence.start_index),
                evaluation_end_index=(evaluation_window_evidence.end_index),
            )
            metrics["raw_metric_json"]["px4_core_metric_evidence"] = (
                core_metric_evidence.model_dump(mode="json")
            )
            require_px4_core_metric_binding(
                metrics,
                core_metric_evidence,
            )
            scenario_effect_evidence_payload: object | None = None
            if scenario_effect_evidence_json.is_file():
                try:
                    scenario_effect_evidence_payload = _load_bounded_json(
                        scenario_effect_evidence_json,
                        label="scenario-effect evidence",
                        max_bytes=MAX_EFFECT_CONTRACT_BYTES,
                    )
                except RunnerError:
                    scenario_effect_evidence_payload = None
            outcome_policy, outcome_evidence = compile_px4_outcome_evidence(
                telemetry_payload=telemetry,
                reference_track_payload=reference_track_payload,
                evaluation_policy=evaluation_policy,
                evaluation_window_evidence=(evaluation_window_evidence),
                core_metric_evidence=core_metric_evidence,
                scenario_effect_request_payload=(scenario_effect_request),
                scenario_effect_evidence_payload=(scenario_effect_evidence_payload),
            )
            metrics["raw_metric_json"].update(
                {
                    "scenario_effects_ready": (outcome_evidence.scenario_effects_ready),
                    "scenario_effect_status": (outcome_evidence.scenario_effect_status),
                    "scenario_effect_request_sha256": (
                        outcome_evidence.scenario_effect_request_sha256
                    ),
                    "scenario_effect_evidence_sha256": (
                        outcome_evidence.scenario_effect_evidence_sha256
                    ),
                    "px4_outcome_policy": outcome_policy.model_dump(mode="json"),
                    "px4_outcome_evidence": (outcome_evidence.model_dump(mode="json")),
                }
            )
            require_px4_outcome_binding(
                metrics,
                policy=outcome_policy,
                evidence=outcome_evidence,
            )
        except Px4CoreMetricEvidenceError as exc:
            raise RunnerError(f"independent PX4 core-metric verification failed: {exc}") from exc
        if not env.keep_raw_logs:
            _remove_success_raw_logs(run_dir)

        result = {
            "success": True,
            "backend": "px4_gazebo",
            "metrics": metrics,
            "artifacts": _collect_artifacts(run_dir),
            "log_excerpt": (
                f"px4_gazebo_runner mode={'dry_run' if env.dry_run else 'real'} "
                f"trial={meta['trial_id']} rmse={metrics['rmse']} score={metrics['score']}"
            ),
        }
        write_result(result)
        return 0
    except UnsupportedScenarioEffectRunnerError as exc:
        log(f"UnsupportedScenarioEffectRunnerError: {exc}")
        result = _failure_result(
            str(exc),
            FAILURE_UNSUPPORTED_SCENARIO_EFFECT,
            _collect_artifacts(run_dir),
            f"px4_gazebo_runner unsupported scenario effect: {exc}",
        )
        write_result(result)
        return 0
    except RunnerError as exc:
        log(f"RunnerError: {exc}")
        result = _failure_result(
            str(exc),
            FAILURE_SIMULATION,
            _collect_artifacts(run_dir),
            f"px4_gazebo_runner simulation failure: {exc}",
        )
        write_result(result)
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
            write_result(result)
            return 0
        except Exception:
            print(f"[px4_gazebo_runner] fatal crash: {exc}", file=sys.stderr)
            return 2


def main() -> int:
    args = _parse_args()
    return run_once(args.input, args.output)


if __name__ == "__main__":
    raise SystemExit(main())
