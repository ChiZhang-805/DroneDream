"""Provenance-bound export and verification for real PX4/Gazebo campaigns.

The exporter keeps enough raw material to independently re-evaluate every
successful Trial while avoiding copies of regenerable PX4 root filesystems and
multi-megabyte console streams. Every source file is still inventoried by
exact-byte SHA-256. Retained ULogs use deterministic gzip framing and preserve
the digest and length of the decompressed source.
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

PHYSICAL_CAMPAIGN_SCHEMA_VERSION = "dronedream.px4-physical-campaign-evidence.v1"
PHYSICAL_CAMPAIGN_RECEIPT_SCHEMA_VERSION = (
    "dronedream.px4-physical-campaign-receipt.v1"
)
PHYSICAL_CAMPAIGN_EVIDENCE_CLASS = "real_px4_gazebo_sitl_physical_campaign"
PHYSICAL_CAMPAIGN_CLAIM_LABEL = "REAL_PX4_GAZEBO_SITL"
PHYSICAL_CAMPAIGN_CLAIM_BOUNDARY = (
    "Fixed-version PX4 SITL plus Gazebo evidence for the retained x500 circle-track "
    "Trials only. It proves exact execution, telemetry semantics, PX4 parameter "
    "read-back, constant-wind read-back, and static-obstacle creation for this "
    "matrix. It does not establish real-aircraft transfer, flight safety, signed "
    "installer availability, unsupported advanced effects, or general controller "
    "superiority."
)

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_COMMIT = re.compile(r"^[0-9a-f]{40}$")
_SCENARIOS = ("nominal", "steady_wind", "static_obstacle")
_EXPECTED_SEEDS = (41001, 41002)
_EXPECTED_CANDIDATE = "baseline-mpc-xy-p-0.95"
_EXPECTED_MPC_XY_P = 0.95
_EXPECTED_WIND_VECTOR = {"x": 0.0, "y": 2.0, "z": 0.0}
_EXPECTED_FAILURE_DIRECTORIES = (
    "probe-nominal",
    "probe-nominal-attempt-2",
    "probe-nominal-attempt-3",
    "probe-nominal-attempt-4",
)
_EXPECTED_RUNTIME_OBSERVATION_COMMANDS = (
    "px4_git_head",
    "gazebo_sim_version",
    "python_version",
    "mavsdk_version",
    "pyulog_version",
    "ubuntu_release",
    "gazebo_harmonic_package",
    "kernel",
)

_COMMON_RETAINED = frozenset(
    {
        "controller_params.json",
        "launch_config.json",
        "offboard_executor.log",
        "offboard_timing.json",
        "px4_parameters.applied.json",
        "px4_parameters.before.json",
        "px4_parameters.input.json",
        "px4_parameters.requested.json",
        "reference_track.json",
        "runner.log",
        "scenario_config.json",
        "scenario_effects.applied.json",
        "scenario_effects.request.json",
        "simulator_runtime_manifest.json",
        "stderr.log",
        "telemetry.json",
        "trial_input.json",
        "trial_result.json",
    }
)
_SCENARIO_RETAINED_PREFIXES = (
    "scenario_obstacles/",
    "scenario_runtime/generated_world.sdf",
    "scenario_runtime/models/x500_base/model.sdf",
    "scenario_runtime/px4_rootfs/gz_env.sh",
    "scenario_runtime/worlds/default.sdf",
)
_FAILURE_RETAINED = frozenset(
    {
        "launch_config.json",
        "offboard_executor.log",
        "offboard_timing.json",
        "px4_parameters.applied.json",
        "px4_parameters.before.json",
        "px4_parameters.input.json",
        "px4_parameters.requested.json",
        "runner.log",
        "scenario_effects.request.json",
        "simulator_runtime_manifest.json",
        "stderr.log",
        "telemetry.reprocessed.json",
        "trial_input.json",
        "trial_result.json",
    }
)


@dataclass(frozen=True)
class PhysicalTrialSpec:
    directory: str
    scenario: str
    seed: int


DEFAULT_TRIAL_SPECS = (
    PhysicalTrialSpec("probe-nominal-attempt-5", "nominal", 41001),
    PhysicalTrialSpec("wind-north-2mps-seed-41001", "steady_wind", 41001),
    PhysicalTrialSpec("obstacle-box-seed-41001", "static_obstacle", 41001),
    PhysicalTrialSpec("nominal-seed-41002", "nominal", 41002),
    PhysicalTrialSpec("wind-north-2mps-seed-41002", "steady_wind", 41002),
    PhysicalTrialSpec("obstacle-box-seed-41002", "static_obstacle", 41002),
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
        raise ValueError(f"cannot load JSON object {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def _require_sha256(value: object, *, field: str, prefix_allowed: bool = False) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a SHA-256 string")
    normalized = value[7:] if prefix_allowed and value.startswith("sha256:") else value
    if not _SHA256.fullmatch(normalized):
        raise ValueError(f"{field} must be a lowercase SHA-256 string")
    return normalized


def _require_commit(value: object, *, field: str) -> str:
    if not isinstance(value, str) or not _COMMIT.fullmatch(value):
        raise ValueError(f"{field} must be a lowercase 40-character Git commit")
    return value


def _require_utc_timestamp(value: object, *, field: str) -> str:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ValueError(f"{field} must be an explicit UTC timestamp ending in Z")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise ValueError(f"{field} must be an ISO-8601 UTC timestamp") from exc
    offset = parsed.utcoffset()
    if offset is None or offset.total_seconds() != 0:
        raise ValueError(f"{field} must be UTC")
    return value


def _require_finite(value: object, *, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field} must be numeric")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{field} must be finite")
    return result


def _safe_relative_path(value: object, *, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{field} must be a non-empty relative path")
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or "\\" in value:
        raise ValueError(f"{field} must be a normalized safe POSIX relative path")
    return str(path)


def _same_identity(left: object, right: object, *, field: str) -> dict[str, Any]:
    if not isinstance(left, dict) or not isinstance(right, dict) or left != right:
        raise ValueError(f"{field} execution identity does not match")
    required = {"trial_id", "job_id", "candidate_id", "seed", "attempt_count"}
    if set(left) != required:
        raise ValueError(f"{field} execution identity keys are incomplete")
    return left


def _nested_mapping(value: object, *, field: str) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{field} must be an object")
    return value


def _validate_runtime_release_manifest(
    payload: Mapping[str, Any],
    *,
    expected_firmware_commit: str,
) -> dict[str, Any]:
    if payload.get("schemaVersion") != 1:
        raise ValueError("Runtime release manifest schemaVersion must be 1")
    runtime = _nested_mapping(payload.get("runtime"), field="runtime")
    runtime_id = runtime.get("buildId")
    if not isinstance(runtime_id, str) or not runtime_id:
        raise ValueError("Runtime release manifest buildId is missing")
    if (
        runtime.get("id") != "DroneDreamRuntime"
        or runtime.get("architecture") != "x86_64"
        or runtime.get("wslVersion") != 2
    ):
        raise ValueError("Runtime release identity is invalid")
    source = _nested_mapping(payload.get("source"), field="source")
    if source.get("px4Commit") != expected_firmware_commit:
        raise ValueError("Runtime release PX4 commit does not match campaign")
    gazebo_version = source.get("gazeboVersion")
    if not isinstance(gazebo_version, str) or not gazebo_version.startswith("harmonic@"):
        raise ValueError("Runtime release must identify Gazebo Harmonic")
    smoke = _nested_mapping(payload.get("smoke"), field="smoke")
    if smoke.get("passed") is not True:
        raise ValueError("Runtime release smoke report did not pass")
    _require_utc_timestamp(smoke.get("completedAt"), field="smoke.completedAt")
    _require_sha256(smoke.get("reportSha256"), field="smoke.reportSha256")
    artifact = _nested_mapping(payload.get("artifact"), field="artifact")
    _require_sha256(artifact.get("sha256"), field="artifact.sha256")
    artifact_size = artifact.get("sizeBytes")
    if (
        isinstance(artifact_size, bool)
        or not isinstance(artifact_size, int)
        or artifact_size <= 0
    ):
        raise ValueError("Runtime release artifact size is invalid")
    parts = artifact.get("parts")
    if not isinstance(parts, list) or not parts:
        raise ValueError("Runtime release artifact parts are missing")
    part_size = 0
    for index, raw_part in enumerate(parts):
        part = _nested_mapping(raw_part, field=f"artifact.parts[{index}]")
        if part.get("index") != index:
            raise ValueError("Runtime release artifact part indexes are not contiguous")
        _require_sha256(part.get("sha256"), field=f"artifact.parts[{index}].sha256")
        size = part.get("sizeBytes")
        if isinstance(size, bool) or not isinstance(size, int) or size <= 0:
            raise ValueError("Runtime release artifact part size is invalid")
        part_size += size
    if part_size != artifact_size:
        raise ValueError("Runtime release artifact part sizes do not recompute")
    return {
        "runtime_id": runtime_id,
        "version": runtime.get("version"),
        "px4_commit": source.get("px4Commit"),
        "gazebo_release": "harmonic",
        "gazebo_release_version": gazebo_version,
        "runtime_source_commit": source.get("gitCommit"),
        "runtime_build_timestamp": source.get("buildTimestamp"),
        "smoke_report_completed_at": smoke.get("completedAt"),
        "runtime_artifact_sha256": artifact.get("sha256"),
        "runtime_artifact_bytes": artifact_size,
    }


def _validate_runtime_observation(
    payload: Mapping[str, Any],
    *,
    expected_runtime_id: str,
    expected_firmware_commit: str,
) -> dict[str, Any]:
    if payload.get("schema_version") != "dronedream.runtime-observation.v1":
        raise ValueError("Runtime observation schema is invalid")
    unsigned = {key: value for key, value in payload.items() if key != "observation_sha256"}
    if payload.get("observation_sha256") != _sha256_value(unsigned):
        raise ValueError("Runtime observation hash does not recompute")
    if payload.get("runtime_id") != expected_runtime_id:
        raise ValueError("Runtime observation does not bind the release Runtime")
    if payload.get("px4_commit") != expected_firmware_commit:
        raise ValueError("Runtime observation PX4 commit does not match campaign")
    _require_commit(payload.get("observer_commit"), field="observer_commit")
    _require_utc_timestamp(payload.get("observed_at"), field="observed_at")
    if payload.get("wsl_distribution") != "DroneDreamRuntime":
        raise ValueError("Runtime observation used an unexpected WSL distribution")
    if payload.get("gazebo_sim_version") != "8.14.0":
        raise ValueError("Runtime observation must identify Gazebo Sim 8.14.0")
    if payload.get("gazebo_harmonic_package") != "1.0.0-1~noble":
        raise ValueError("Runtime observation Gazebo Harmonic package drifted")
    if payload.get("mavsdk_version") != "3.15.3":
        raise ValueError("Runtime observation MAVSDK version drifted")
    if payload.get("pyulog_version") != "1.2.3":
        raise ValueError("Runtime observation pyulog version drifted")
    if payload.get("python_version") != "3.12.3":
        raise ValueError("Runtime observation Python version drifted")
    if payload.get("ubuntu_version") != "24.04":
        raise ValueError("Runtime observation Ubuntu version drifted")
    if (
        payload.get("network_calls") != 0
        or payload.get("real_credentials_used") is not False
        or payload.get("observation_role")
        != (
            "post-campaign read-only identity check of the WSL Runtime used by "
            "the retained PX4/Gazebo Trial matrix"
        )
    ):
        raise ValueError("Runtime observation claim boundary drifted")
    commands = payload.get("commands")
    if (
        not isinstance(commands, list)
        or len(commands) != len(_EXPECTED_RUNTIME_OBSERVATION_COMMANDS)
        or [
            item.get("name") if isinstance(item, dict) else None for item in commands
        ]
        != list(_EXPECTED_RUNTIME_OBSERVATION_COMMANDS)
    ):
        raise ValueError("Runtime observation command matrix is incomplete")
    for index, raw_command in enumerate(commands):
        command = _nested_mapping(
            raw_command,
            field=f"runtime observation command {index}",
        )
        argv = command.get("argv")
        stdout = command.get("stdout")
        stderr = command.get("stderr")
        if (
            command.get("exit_code") != 0
            or not isinstance(argv, list)
            or not argv
            or any(not isinstance(item, str) or not item for item in argv)
            or not isinstance(stdout, str)
            or not isinstance(stderr, str)
            or command.get("stdout_sha256")
            != _sha256_bytes(stdout.encode("utf-8"))
            or command.get("stderr_sha256")
            != _sha256_bytes(stderr.encode("utf-8"))
        ):
            raise ValueError("Runtime observation command evidence is invalid")
    return {
        "observer_commit": payload["observer_commit"],
        "observed_at": payload["observed_at"],
        "wsl_distribution": payload["wsl_distribution"],
        "px4_commit_observed": payload["px4_commit"],
        "gazebo_sim_version_observed": payload["gazebo_sim_version"],
        "gazebo_harmonic_package_observed": payload["gazebo_harmonic_package"],
        "mavsdk_version_observed": payload["mavsdk_version"],
        "pyulog_version_observed": payload["pyulog_version"],
        "ubuntu_version_observed": payload["ubuntu_version"],
        "kernel_observed": payload.get("kernel"),
    }


def build_runtime_observation(
    *,
    runtime_id: str,
    observer_commit: str,
    observed_at: str,
    wsl_distribution: str,
    px4_commit: str,
    gazebo_sim_version: str,
    gazebo_harmonic_package: str,
    python_version: str,
    mavsdk_version: str,
    pyulog_version: str,
    ubuntu_version: str,
    kernel: str,
    commands: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Build a hash-bound post-campaign observation from explicit command results."""

    if not isinstance(runtime_id, str) or not runtime_id:
        raise ValueError("runtime_id must be non-empty")
    observer_commit = _require_commit(observer_commit, field="observer_commit")
    observed_at = _require_utc_timestamp(observed_at, field="observed_at")
    px4_commit = _require_commit(px4_commit, field="px4_commit")
    command_rows = [dict(command) for command in commands]
    unsigned: dict[str, Any] = {
        "schema_version": "dronedream.runtime-observation.v1",
        "observation_role": (
            "post-campaign read-only identity check of the WSL Runtime used by "
            "the retained PX4/Gazebo Trial matrix"
        ),
        "runtime_id": runtime_id,
        "observer_commit": observer_commit,
        "observed_at": observed_at,
        "wsl_distribution": wsl_distribution,
        "px4_commit": px4_commit,
        "gazebo_sim_version": gazebo_sim_version,
        "gazebo_harmonic_package": gazebo_harmonic_package,
        "python_version": python_version,
        "mavsdk_version": mavsdk_version,
        "pyulog_version": pyulog_version,
        "ubuntu_version": ubuntu_version,
        "kernel": kernel,
        "commands": command_rows,
        "network_calls": 0,
        "real_credentials_used": False,
    }
    payload = {
        **unsigned,
        "observation_sha256": _sha256_value(unsigned),
    }
    _validate_runtime_observation(
        payload,
        expected_runtime_id=runtime_id,
        expected_firmware_commit=px4_commit,
    )
    return payload


def _validate_telemetry(
    payload: Mapping[str, Any],
    *,
    ulog_sha256: str,
) -> dict[str, Any]:
    if payload.get("schema_version") != "dronedream.telemetry.v2":
        raise ValueError("telemetry schema_version must be dronedream.telemetry.v2")
    contract = _nested_mapping(payload.get("semantic_contract"), field="semantic_contract")
    if contract.get("schema_id") != "dronedream.telemetry-semantic-contract/v1":
        raise ValueError("telemetry semantic contract schema is invalid")
    if contract.get("synthetic") is not False or contract.get("source_kind") != "px4_ulog":
        raise ValueError("telemetry must be non-synthetic PX4 ULog evidence")
    if contract.get("coordinate_frame") != "dronedream_local_cartesian_z_up":
        raise ValueError("telemetry coordinate frame is invalid")
    origin_sha = _require_sha256(
        contract.get("origin_source_sha256"),
        field="semantic_contract.origin_source_sha256",
        prefix_allowed=True,
    )
    if origin_sha != ulog_sha256:
        raise ValueError("telemetry origin ULog SHA-256 does not match retained ULog")
    contract_id = _require_sha256(
        contract.get("contract_id"),
        field="semantic_contract.contract_id",
        prefix_allowed=True,
    )
    unsigned_contract = {
        key: value for key, value in contract.items() if key != "contract_id"
    }
    if contract_id != _sha256_value(unsigned_contract):
        raise ValueError("telemetry semantic contract_id does not recompute")
    samples = payload.get("samples")
    if not isinstance(samples, list) or not samples:
        raise ValueError("telemetry samples must be a non-empty array")
    sampling = _nested_mapping(contract.get("sampling"), field="semantic_contract.sampling")
    if sampling.get("sample_count") != len(samples):
        raise ValueError("telemetry sampling sample_count does not match samples")
    if any(not isinstance(sample, dict) for sample in samples):
        raise ValueError("telemetry samples must contain objects")
    if any(sample.get("crashed") is True for sample in samples):
        raise ValueError("successful campaign telemetry cannot contain crashed=true")
    return {
        "contract_id": f"sha256:{contract_id}",
        "sample_count": len(samples),
        "duration_s": _require_finite(
            sampling.get("duration_s"),
            field="semantic_contract.sampling.duration_s",
        ),
        "sampling_coverage": _require_finite(
            sampling.get("sampling_coverage"),
            field="semantic_contract.sampling.sampling_coverage",
        ),
        "origin_ulog_sha256": f"sha256:{origin_sha}",
    }


def _validate_reprocessed_failure_telemetry(
    payload: Mapping[str, Any],
    *,
    ulog_sha256: str,
    ulog_bytes: int,
) -> dict[str, Any]:
    """Validate the pre-v2 diagnostic produced from attempt 4's exact ULog."""

    meta = _nested_mapping(payload.get("meta"), field="reprocessed telemetry meta")
    origin_sha = _require_sha256(
        meta.get("origin_source_sha256"),
        field="reprocessed telemetry origin_source_sha256",
        prefix_allowed=True,
    )
    if (
        origin_sha != ulog_sha256
        or meta.get("origin_source_byte_count") != ulog_bytes
        or meta.get("source") != "ulog"
        or meta.get("simulator") != "px4_gazebo"
        or meta.get("origin_coordinate_frame") != "PX4_LOCAL_NED"
        or meta.get("origin_extraction_revision") != "pyulog-vehicle-local-position-1.0"
    ):
        raise ValueError("reprocessed failure telemetry does not bind its PX4 ULog")
    samples = payload.get("samples")
    if not isinstance(samples, list) or not samples:
        raise ValueError("reprocessed failure telemetry has no samples")
    previous_time = -math.inf
    required = {
        "t",
        "x",
        "y",
        "z",
        "vx",
        "vy",
        "vz",
        "yaw",
        "armed",
        "mode",
        "crashed",
    }
    for index, raw_sample in enumerate(samples):
        sample = _nested_mapping(
            raw_sample,
            field=f"reprocessed telemetry sample {index}",
        )
        if set(sample) != required:
            raise ValueError("reprocessed failure telemetry sample keys drifted")
        timestamp = _require_finite(
            sample.get("t"),
            field=f"reprocessed telemetry sample {index}.t",
        )
        if timestamp < previous_time:
            raise ValueError("reprocessed failure telemetry time is not monotonic")
        previous_time = timestamp
        if (
            not isinstance(sample.get("armed"), bool)
            or not isinstance(sample.get("crashed"), bool)
            or not isinstance(sample.get("mode"), str)
        ):
            raise ValueError("reprocessed failure telemetry scalar types are invalid")
        for field in ("x", "y", "z", "vx", "vy", "vz", "yaw"):
            _require_finite(
                sample.get(field),
                field=f"reprocessed telemetry sample {index}.{field}",
            )
    return {
        "origin_ulog_sha256": f"sha256:{origin_sha}",
        "origin_ulog_bytes": ulog_bytes,
        "sample_count": len(samples),
        "duration_s": previous_time - float(samples[0]["t"]),
        "extraction_revision": meta["origin_extraction_revision"],
        "evidence_role": "post-fix-parser-diagnostic-not-success-trial",
    }


def _validate_scenario(
    *,
    scenario: str,
    request: Mapping[str, Any],
    applied: Mapping[str, Any] | None,
    launch: Mapping[str, Any],
    trial_dir: Path,
) -> dict[str, Any]:
    contract = _nested_mapping(
        launch.get("scenario_effect_contract"),
        field="launch_config.scenario_effect_contract",
    )
    request_effects = request.get("effects")
    if not isinstance(request_effects, list):
        raise ValueError("scenario request effects must be an array")
    effect_ids = [
        effect.get("effect_id") for effect in request_effects if isinstance(effect, dict)
    ]
    if len(effect_ids) != len(request_effects) or any(
        not isinstance(effect_id, str) for effect_id in effect_ids
    ):
        raise ValueError("scenario request effects are malformed")

    if scenario == "nominal":
        if (
            effect_ids
            or applied is not None
            or contract.get("verification_status") != "not_requested"
            or contract.get("applied_effects") != []
        ):
            raise ValueError("nominal Trial must not request or apply physical effects")
        return {
            "verification_status": "not_requested",
            "requested_effects": [],
            "applied_effects": [],
        }

    if applied is None:
        raise ValueError(f"{scenario} Trial is missing applied scenario evidence")
    if applied.get("schema_version") != "dronedream.scenario_effect_evidence.v1":
        raise ValueError("scenario effect evidence schema is invalid")
    if applied.get("request_sha256") != request.get("request_sha256"):
        raise ValueError("scenario effect evidence does not bind the request")
    applied_effects = applied.get("effects")
    if not isinstance(applied_effects, list) or len(applied_effects) != 1:
        raise ValueError("physical Trial must contain exactly one applied effect")
    effect = _nested_mapping(applied_effects[0], field="scenario applied effect")
    if effect.get("status") != "applied":
        raise ValueError("scenario effect status must be applied")
    if contract.get("verification_status") != "verified_applied":
        raise ValueError("launcher scenario contract must be verified_applied")
    if contract.get("failed_effects") or contract.get("unsupported_effects"):
        raise ValueError("physical Trial contains failed or unsupported effects")
    effect_id = effect.get("effect_id")
    if contract.get("applied_effects") != [effect_id] or effect_ids != [effect_id]:
        raise ValueError("scenario effect IDs are inconsistent")

    if scenario == "steady_wind":
        if effect_id != "job_config.wind":
            raise ValueError("steady-wind Trial must use job_config.wind")
        evidence = _nested_mapping(effect.get("evidence"), field="wind evidence")
        compiled = _nested_mapping(evidence.get("compiled_wind"), field="compiled_wind")
        vector = _nested_mapping(
            compiled.get("linear_velocity_mps"),
            field="compiled_wind.linear_velocity_mps",
        )
        normalized_vector = {
            axis: _require_finite(vector.get(axis), field=f"wind.{axis}")
            for axis in ("x", "y", "z")
        }
        if normalized_vector != _EXPECTED_WIND_VECTOR:
            raise ValueError("steady-wind Trial vector is not the fixed (0, 2, 0) m/s vector")
        verification = _nested_mapping(
            evidence.get("verification"), field="wind verification"
        )
        observations = verification.get("observations")
        if not isinstance(observations, list):
            raise ValueError("wind verification observations must be an array")
        readbacks = [
            item
            for item in observations
            if isinstance(item, dict)
            and item.get("kind") == "readback"
            and item.get("source") == "/world/default/wind_info"
        ]
        if len(readbacks) != 1:
            raise ValueError("wind Trial must retain one /world/default/wind_info read-back")
        readback_value = _nested_mapping(
            readbacks[0].get("value"), field="wind read-back value"
        )
        readback_vector = _nested_mapping(
            readback_value.get("linear_velocity_mps"),
            field="wind read-back vector",
        )
        if readback_value.get("enable_wind") is not True or {
            axis: _require_finite(readback_vector.get(axis), field=f"wind read-back {axis}")
            for axis in ("x", "y", "z")
        } != _EXPECTED_WIND_VECTOR:
            raise ValueError("wind read-back does not match the fixed request")
    elif scenario == "static_obstacle":
        if effect_id != "obstacles":
            raise ValueError("static-obstacle Trial must use obstacles effect")
        evidence = _nested_mapping(effect.get("evidence"), field="obstacle evidence")
        entities = evidence.get("created_entities")
        if not isinstance(entities, list) or len(entities) != 1:
            raise ValueError("static-obstacle Trial must create exactly one entity")
        entity = _nested_mapping(entities[0], field="created obstacle")
        if (
            entity.get("response_data") is not True
            or entity.get("service") != "/world/default/create"
            or entity.get("source_index") != 0
        ):
            raise ValueError("static-obstacle Gazebo acknowledgement is invalid")
        sdf_sha = _require_sha256(entity.get("sdf_sha256"), field="obstacle SDF SHA-256")
        sdf_files = sorted((trial_dir / "scenario_obstacles").glob("*.sdf"))
        if len(sdf_files) != 1 or _sha256_file(sdf_files[0]) != sdf_sha:
            raise ValueError("static-obstacle SDF bytes do not match applied evidence")
    else:
        raise ValueError(f"unsupported campaign scenario {scenario}")

    return {
        "verification_status": "verified_applied",
        "requested_effects": effect_ids,
        "applied_effects": [effect_id],
        "evidence_sha256": f"sha256:{_sha256_file(trial_dir / 'scenario_effects.applied.json')}",
    }


def _validate_success_trial(
    trial_dir: Path,
    spec: PhysicalTrialSpec,
    *,
    firmware_commit: str,
    ulog_sha256: str | None = None,
) -> dict[str, Any]:
    trial_input = _load_json(trial_dir / "trial_input.json")
    result = _load_json(trial_dir / "trial_result.json")
    launch = _load_json(trial_dir / "launch_config.json")
    runtime = _load_json(trial_dir / "simulator_runtime_manifest.json")
    request = _load_json(trial_dir / "scenario_effects.request.json")
    applied_path = trial_dir / "scenario_effects.applied.json"
    applied = _load_json(applied_path) if applied_path.is_file() else None
    parameters = _load_json(trial_dir / "px4_parameters.applied.json")
    telemetry = _load_json(trial_dir / "telemetry.json")
    ulog_path = trial_dir / "px4_source.ulg"
    if ulog_sha256 is None:
        if not ulog_path.is_file():
            raise ValueError(f"{trial_dir} is missing retained PX4 ULog")
        ulog_sha = _sha256_file(ulog_path)
    else:
        ulog_sha = _require_sha256(ulog_sha256, field=f"{spec.directory} ULog SHA-256")

    identity = _same_identity(
        trial_input.get("execution_identity"),
        result.get("execution_identity"),
        field=spec.directory,
    )
    _same_identity(identity, request.get("execution_identity"), field=spec.directory)
    _same_identity(identity, runtime.get("execution_identity"), field=spec.directory)
    if identity.get("seed") != spec.seed:
        raise ValueError(f"{spec.directory} seed does not match fixed matrix")
    if identity.get("candidate_id") != _EXPECTED_CANDIDATE:
        raise ValueError(f"{spec.directory} candidate does not match fixed matrix")
    if result.get("success") is not True:
        raise ValueError(f"{spec.directory} Trial did not succeed")
    metrics = _nested_mapping(result.get("metrics"), field=f"{spec.directory}.metrics")
    if metrics.get("pass_flag") is not True:
        raise ValueError(f"{spec.directory} Trial did not pass the frozen policy")
    if any(metrics.get(flag) is not False for flag in ("crash_flag", "timeout_flag")):
        raise ValueError(f"{spec.directory} Trial has a crash or timeout flag")
    if metrics.get("instability_flag") is not False:
        raise ValueError(f"{spec.directory} Trial has an instability flag")
    raw_metrics = _nested_mapping(
        metrics.get("raw_metric_json"),
        field=f"{spec.directory}.raw_metric_json",
    )
    if raw_metrics.get("mode") != "real" or raw_metrics.get("simulator") != "px4_gazebo":
        raise ValueError(f"{spec.directory} is not real PX4/Gazebo evidence")

    launch_firmware = _nested_mapping(
        launch.get("firmware_identity"), field="launch_config.firmware_identity"
    )
    runtime_firmware = _nested_mapping(
        runtime.get("firmware_identity"), field="runtime.firmware_identity"
    )
    for label, value in (
        ("launch", launch_firmware),
        ("runtime", runtime_firmware),
    ):
        if (
            value.get("status") != "verified"
            or value.get("observed_commit") != firmware_commit
            or value.get("requested_commit") != firmware_commit
        ):
            raise ValueError(f"{spec.directory} {label} firmware identity is not verified")
    if launch.get("world") != "default" or launch.get("simulator_model") != "x500":
        raise ValueError(f"{spec.directory} simulator identity drifted")
    if launch.get("timeout_base_1x_seconds") != 300:
        raise ValueError(f"{spec.directory} timeout budget drifted")

    if parameters.get("status") != "ok":
        raise ValueError(f"{spec.directory} PX4 parameter application failed")
    verification = _nested_mapping(
        parameters.get("verification"), field="PX4 parameter verification"
    )
    if verification.get("verified") is not True or verification.get("mismatches") != {}:
        raise ValueError(f"{spec.directory} PX4 parameter read-back was not verified")
    values = _nested_mapping(parameters.get("values"), field="PX4 parameter values")
    mpc_xy_p = _require_finite(values.get("MPC_XY_P"), field="MPC_XY_P")
    if not math.isclose(mpc_xy_p, _EXPECTED_MPC_XY_P, rel_tol=0.0, abs_tol=1e-6):
        raise ValueError(f"{spec.directory} MPC_XY_P read-back drifted")

    telemetry_summary = _validate_telemetry(telemetry, ulog_sha256=ulog_sha)
    scenario_summary = _validate_scenario(
        scenario=spec.scenario,
        request=request,
        applied=applied,
        launch=launch,
        trial_dir=trial_dir,
    )
    evaluation_sampling = _nested_mapping(
        raw_metrics.get("evaluation_sampling"),
        field=f"{spec.directory}.evaluation_sampling",
    )
    return {
        "trial_id": identity["trial_id"],
        "job_id": identity["job_id"],
        "candidate_id": identity["candidate_id"],
        "seed": spec.seed,
        "attempt_count": identity["attempt_count"],
        "directory": spec.directory,
        "scenario": spec.scenario,
        "success": True,
        "pass_flag": True,
        "metrics": {
            "rmse_m": _require_finite(metrics.get("rmse"), field="metrics.rmse"),
            "max_error_m": _require_finite(
                metrics.get("max_error"), field="metrics.max_error"
            ),
            "completion_time_s": _require_finite(
                metrics.get("completion_time"), field="metrics.completion_time"
            ),
            "score": _require_finite(metrics.get("score"), field="metrics.score"),
            "evaluation_track_coverage": _require_finite(
                raw_metrics.get("evaluation_track_coverage"),
                field="metrics.evaluation_track_coverage",
            ),
            "evaluation_sample_count": evaluation_sampling.get("sample_count"),
        },
        "firmware_commit": firmware_commit,
        "px4_parameter_readback": {"MPC_XY_P": mpc_xy_p, "verified": True},
        "scenario_evidence": scenario_summary,
        "telemetry_evidence": telemetry_summary,
    }


def _retained(relative: str, *, failure: bool) -> bool:
    if relative == "px4_source.ulg":
        return True
    if failure:
        return relative in _FAILURE_RETAINED
    return relative in _COMMON_RETAINED or relative.startswith(
        _SCENARIO_RETAINED_PREFIXES
    )


def _omission_reason(relative: str) -> str:
    if relative == "stdout.log":
        return "verbose_runtime_stream_represented_by_ulog_and_stderr"
    if relative.startswith("scenario_runtime/px4_rootfs/"):
        return "regenerable_trial_local_px4_rootfs_copy"
    if relative.startswith("scenario_runtime/"):
        return "regenerable_trial_local_runtime_overlay"
    if relative in {"trajectory.json", "reference_track.used.json"}:
        return "derived_or_duplicate_of_retained_evidence"
    return "not_required_by_minimum_sufficient_retention_policy"


def _write_exact(path: Path, value: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(value)


def _inventory_and_retain(
    source_dir: Path,
    *,
    output_root: Path,
    retained_prefix: PurePosixPath,
    failure: bool,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    records: list[dict[str, Any]] = []
    retained_bytes = 0
    source_bytes = 0
    source_files = sorted(
        (
            (path.relative_to(source_dir).as_posix(), path)
            for path in source_dir.rglob("*")
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
        if _retained(relative, failure=failure):
            if relative == "px4_source.ulg":
                retained_relative = str(retained_prefix / "px4_source.ulg.gz")
                compressed = gzip.compress(path.read_bytes(), compresslevel=9, mtime=0)
                destination = output_root / PurePosixPath(retained_relative)
                _write_exact(destination, compressed)
                record.update(
                    {
                        "retained": True,
                        "retained_path": retained_relative,
                        "retained_bytes": len(compressed),
                        "retained_sha256": _sha256_bytes(compressed),
                        "compression": "gzip-level-9-mtime-0",
                    }
                )
                retained_bytes += len(compressed)
            else:
                retained_relative = str(retained_prefix / PurePosixPath(relative))
                value = path.read_bytes()
                destination = output_root / PurePosixPath(retained_relative)
                _write_exact(destination, value)
                record.update(
                    {
                        "retained": True,
                        "retained_path": retained_relative,
                        "retained_bytes": len(value),
                        "retained_sha256": digest,
                        "compression": "none",
                    }
                )
                retained_bytes += len(value)
        else:
            record["omission_reason"] = _omission_reason(relative)
        records.append(record)
    return records, {
        "source_file_count": len(records),
        "source_bytes": source_bytes,
        "retained_file_count": sum(1 for item in records if item["retained"]),
        "retained_bytes": retained_bytes,
    }


def _inventory_sha256(inventory: Sequence[Mapping[str, Any]]) -> str:
    rows = [
        {
            "source_path": item["source_path"],
            "source_bytes": item["source_bytes"],
            "source_sha256": item["source_sha256"],
        }
        for item in inventory
    ]
    return _sha256_value(rows)


def _validate_failure_trial(
    trial_dir: Path,
    *,
    expected_source_commit: str,
) -> dict[str, Any]:
    trial_input = _load_json(trial_dir / "trial_input.json")
    result = _load_json(trial_dir / "trial_result.json")
    if result.get("success") is not False:
        raise ValueError(f"{trial_dir.name} failure probe unexpectedly succeeded")
    failure = _nested_mapping(result.get("failure"), field=f"{trial_dir.name}.failure")
    code = failure.get("code")
    reason = failure.get("reason")
    if not isinstance(code, str) or not code or not isinstance(reason, str) or not reason:
        raise ValueError(f"{trial_dir.name} failure probe lacks a structured reason")
    input_identity = _same_identity(
        trial_input.get("execution_identity"),
        trial_input.get("execution_identity"),
        field=trial_dir.name,
    )
    result_identity = result.get("execution_identity")
    if result_identity is None:
        if trial_dir.name != "probe-nominal" or input_identity.get("attempt_count") != 1:
            raise ValueError(
                f"{trial_dir.name} may omit result identity only for pre-dispatch attempt 1"
            )
        identity = input_identity
    else:
        identity = _same_identity(
            input_identity,
            result_identity,
            field=trial_dir.name,
        )
    return {
        "directory": trial_dir.name,
        "trial_id": identity["trial_id"],
        "job_id": identity["job_id"],
        "candidate_id": identity["candidate_id"],
        "seed": identity["seed"],
        "attempt_count": identity["attempt_count"],
        "result_identity_present": result_identity is not None,
        "source_commit": expected_source_commit,
        "success": False,
        "failure_code": code,
        "failure_reason": reason,
    }


def export_physical_campaign_evidence(
    *,
    source_root: Path,
    failure_root: Path,
    output_root: Path,
    runtime_manifest_path: Path,
    runtime_observation_path: Path,
    subject_commit: str,
    exporter_commit: str,
    failure_source_commit: str,
    generated_at: str,
    trial_specs: Sequence[PhysicalTrialSpec] = DEFAULT_TRIAL_SPECS,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Export a deterministic retained evidence subset plus complete source inventory."""

    subject_commit = _require_commit(subject_commit, field="subject_commit")
    exporter_commit = _require_commit(exporter_commit, field="exporter_commit")
    failure_source_commit = _require_commit(
        failure_source_commit, field="failure_source_commit"
    )
    generated_at = _require_utc_timestamp(generated_at, field="generated_at")
    if output_root.exists() and any(output_root.iterdir()):
        raise ValueError(f"output directory must be absent or empty: {output_root}")
    output_root.mkdir(parents=True, exist_ok=True)

    runtime_payload = _load_json(runtime_manifest_path)
    firmware_commit = _require_commit(
        _nested_mapping(runtime_payload.get("source"), field="source").get(
            "px4Commit"
        ),
        field="runtime PX4 commit",
    )
    runtime_summary = _validate_runtime_release_manifest(
        runtime_payload,
        expected_firmware_commit=firmware_commit,
    )
    runtime_bytes = runtime_manifest_path.read_bytes()
    runtime_retained_path = "runtime/runtime-manifest.json"
    _write_exact(output_root / runtime_retained_path, runtime_bytes)
    observation_payload = _load_json(runtime_observation_path)
    observation_summary = _validate_runtime_observation(
        observation_payload,
        expected_runtime_id=str(runtime_summary["runtime_id"]),
        expected_firmware_commit=firmware_commit,
    )
    observation_bytes = runtime_observation_path.read_bytes()
    observation_retained_path = "runtime/runtime-observation.json"
    _write_exact(output_root / observation_retained_path, observation_bytes)

    if len(trial_specs) != 6:
        raise ValueError("fixed physical campaign must contain exactly six Trials")
    matrix = {(spec.seed, spec.scenario) for spec in trial_specs}
    expected_matrix = {
        (seed, scenario) for seed in _EXPECTED_SEEDS for scenario in _SCENARIOS
    }
    if matrix != expected_matrix:
        raise ValueError("physical campaign Trial specs do not form the fixed 2x3 matrix")

    trial_entries: list[dict[str, Any]] = []
    aggregate_inventory: list[dict[str, Any]] = []
    aggregate_counts = {
        "source_file_count": 0,
        "source_bytes": 0,
        "retained_file_count": 0,
        "retained_bytes": 0,
    }
    for spec in trial_specs:
        trial_dir = source_root / spec.directory
        summary = _validate_success_trial(
            trial_dir,
            spec,
            firmware_commit=firmware_commit,
        )
        inventory, counts = _inventory_and_retain(
            trial_dir,
            output_root=output_root,
            retained_prefix=PurePosixPath("trials") / spec.directory,
            failure=False,
        )
        summary["source_inventory"] = inventory
        summary["source_inventory_sha256"] = _inventory_sha256(inventory)
        summary["retention_summary"] = counts
        trial_entries.append(summary)
        aggregate_inventory.extend(
            {
                **item,
                "source_path": f"{spec.directory}/{item['source_path']}",
            }
            for item in inventory
        )
        for key in aggregate_counts:
            aggregate_counts[key] += counts[key]

    failure_entries: list[dict[str, Any]] = []
    for directory in _EXPECTED_FAILURE_DIRECTORIES:
        trial_dir = failure_root / directory
        if not trial_dir.is_dir():
            raise ValueError(f"failure history is missing {directory}")
        summary = _validate_failure_trial(
            trial_dir,
            expected_source_commit=failure_source_commit,
        )
        inventory, counts = _inventory_and_retain(
            trial_dir,
            output_root=output_root,
            retained_prefix=PurePosixPath("failure-history") / trial_dir.name,
            failure=True,
        )
        summary["source_inventory"] = inventory
        summary["source_inventory_sha256"] = _inventory_sha256(inventory)
        summary["retention_summary"] = counts
        if trial_dir.name == "probe-nominal-attempt-4":
            ulog_rows = [
                item for item in inventory if item["source_path"] == "px4_source.ulg"
            ]
            if len(ulog_rows) != 1:
                raise ValueError("attempt 4 must contain exactly one PX4 ULog")
            reprocessed_path = trial_dir / "telemetry.reprocessed.json"
            reprocessed_summary = _validate_reprocessed_failure_telemetry(
                _load_json(reprocessed_path),
                ulog_sha256=str(ulog_rows[0]["source_sha256"]),
                ulog_bytes=int(ulog_rows[0]["source_bytes"]),
            )
            summary["post_fix_reprocessing"] = {
                "processor_commit": subject_commit,
                "path": (
                    "failure-history/probe-nominal-attempt-4/"
                    "telemetry.reprocessed.json"
                ),
                "sha256": _sha256_file(reprocessed_path),
                "bytes": reprocessed_path.stat().st_size,
                **reprocessed_summary,
                "claim": (
                    "The exact retained ULog was successfully parsed after the NumPy "
                    "scalar fix; this diagnostic is not part of the six-Trial matrix."
                ),
            }
        failure_entries.append(summary)
        aggregate_inventory.extend(
            {
                **item,
                "source_path": f"failure-history/{trial_dir.name}/{item['source_path']}",
            }
            for item in inventory
        )
        for key in aggregate_counts:
            aggregate_counts[key] += counts[key]
    if len(failure_entries) != 4:
        raise ValueError("failure history must retain all four diagnostic attempts")

    rmse_values = [float(entry["metrics"]["rmse_m"]) for entry in trial_entries]
    coverage_values = [
        float(entry["metrics"]["evaluation_track_coverage"])
        for entry in trial_entries
    ]
    unsigned_manifest: dict[str, Any] = {
        "schema_version": PHYSICAL_CAMPAIGN_SCHEMA_VERSION,
        "evidence_class": PHYSICAL_CAMPAIGN_EVIDENCE_CLASS,
        "claim_label": PHYSICAL_CAMPAIGN_CLAIM_LABEL,
        "claim_boundary": PHYSICAL_CAMPAIGN_CLAIM_BOUNDARY,
        "generated_at": generated_at,
        "subject_commit": subject_commit,
        "exporter_commit": exporter_commit,
        "physical_fidelity": True,
        "real_aircraft_fidelity": False,
        "network_calls": 0,
        "real_credentials_used": False,
        "protocol": {
            "matrix": {
                "seeds": list(_EXPECTED_SEEDS),
                "scenarios": list(_SCENARIOS),
                "trial_count": 6,
                "paired_by_seed": True,
            },
            "candidate_id": _EXPECTED_CANDIDATE,
            "track_type": "circle",
            "world": "default",
            "vehicle": "x500",
            "px4_parameter_request": {"MPC_XY_P": _EXPECTED_MPC_XY_P},
            "steady_wind_gazebo_enu_mps": _EXPECTED_WIND_VECTOR,
            "static_obstacle": {
                "type": "box",
                "position_m": {"x": 0.0, "y": 8.0, "z": 0.5},
                "size_m": {"x": 1.0, "y": 1.0, "z": 1.0},
                "placement_purpose": (
                    "exercise verified entity injection outside the nominal circle "
                    "track, not deliberate collision avoidance performance"
                ),
            },
            "timeout_base_1x_seconds": 300,
            "unsupported_effects_included": False,
        },
        "runtime_identity": {
            **runtime_summary,
            **observation_summary,
            "runtime_manifest": {
                "path": runtime_retained_path,
                "sha256": _sha256_bytes(runtime_bytes),
                "bytes": len(runtime_bytes),
            },
            "runtime_observation": {
                "path": observation_retained_path,
                "sha256": _sha256_bytes(observation_bytes),
                "bytes": len(observation_bytes),
            },
        },
        "summary": {
            "trial_count": len(trial_entries),
            "success_count": sum(entry["success"] is True for entry in trial_entries),
            "pass_count": sum(entry["pass_flag"] is True for entry in trial_entries),
            "scenario_verified_applied_count": sum(
                entry["scenario_evidence"]["verification_status"]
                == "verified_applied"
                for entry in trial_entries
            ),
            "retained_failure_probe_count": len(failure_entries),
            "rmse_m_min": min(rmse_values),
            "rmse_m_max": max(rmse_values),
            "evaluation_track_coverage_min": min(coverage_values),
            "evaluation_track_coverage_max": max(coverage_values),
            **aggregate_counts,
            "full_source_inventory_sha256": _inventory_sha256(aggregate_inventory),
        },
        "trials": trial_entries,
        "failure_history": {
            "claim": (
                "Four diagnostic failures are retained in chronological order and "
                "are excluded from the preregistered six-Trial success matrix."
            ),
            "source_commit": failure_source_commit,
            "attempts": failure_entries,
        },
        "retention_policy": {
            "policy_id": "dronedream.minimum-sufficient-px4-campaign-retention/v1",
            "all_source_files_inventoried": True,
            "retained_raw_ulog": True,
            "ulog_compression": "gzip-level-9-mtime-0",
            "retained_normalized_telemetry": True,
            "retained_scenario_readback": True,
            "retained_parameter_readback": True,
            "retained_runtime_and_firmware_identity": True,
            "omitted_regenerable_runtime_rootfs_copies": True,
            "omitted_verbose_stdout_streams": True,
        },
    }
    manifest = {
        **unsigned_manifest,
        "manifest_sha256": _sha256_value(unsigned_manifest),
    }
    manifest_bytes = _pretty_bytes(manifest)
    manifest_path = output_root / "px4-physical-campaign-v1.manifest.json"
    _write_exact(manifest_path, manifest_bytes)

    unsigned_receipt: dict[str, Any] = {
        "schema_version": PHYSICAL_CAMPAIGN_RECEIPT_SCHEMA_VERSION,
        "generated_at": generated_at,
        "subject_commit": subject_commit,
        "exporter_commit": exporter_commit,
        "manifest": {
            "path": manifest_path.name,
            "sha256": _sha256_bytes(manifest_bytes),
            "bytes": len(manifest_bytes),
            "manifest_sha256": manifest["manifest_sha256"],
        },
        "result": {
            "status": "passed",
            "trial_count": 6,
            "passed": 6,
            "failed": 0,
            "retained_failure_probes": 4,
        },
        "runtime_id": runtime_summary["runtime_id"],
        "px4_commit": firmware_commit,
    }
    receipt = {
        **unsigned_receipt,
        "receipt_sha256": _sha256_value(unsigned_receipt),
    }
    receipt_bytes = _pretty_bytes(receipt)
    receipt_path = output_root / "px4-physical-campaign-v1.receipt.json"
    _write_exact(receipt_path, receipt_bytes)
    digest_bytes = (
        f"{_sha256_bytes(manifest_bytes)}  {manifest_path.name}\n"
        f"{_sha256_bytes(receipt_bytes)}  {receipt_path.name}\n"
    ).encode("ascii")
    _write_exact(output_root / "px4-physical-campaign-v1.sha256", digest_bytes)
    return manifest, receipt


def _verify_retained_inventory(
    inventory: object,
    *,
    evidence_root: Path,
    source_root: Path | None,
) -> None:
    if not isinstance(inventory, list) or not inventory:
        raise ValueError("source inventory must be a non-empty array")
    previous = ""
    for index, raw in enumerate(inventory):
        item = _nested_mapping(raw, field=f"source_inventory[{index}]")
        source_path = _safe_relative_path(
            item.get("source_path"),
            field=f"source_inventory[{index}].source_path",
        )
        if source_path <= previous:
            raise ValueError("source inventory must be strictly sorted")
        previous = source_path
        source_sha = _require_sha256(
            item.get("source_sha256"),
            field=f"source_inventory[{index}].source_sha256",
        )
        source_bytes = item.get("source_bytes")
        if isinstance(source_bytes, bool) or not isinstance(source_bytes, int) or source_bytes < 0:
            raise ValueError("source inventory byte counts must be non-negative integers")
        if source_root is not None:
            source_file = source_root / PurePosixPath(source_path)
            if (
                not source_file.is_file()
                or source_file.stat().st_size != source_bytes
                or _sha256_file(source_file) != source_sha
            ):
                raise ValueError(f"source inventory file drifted: {source_path}")
        if item.get("retained") is True:
            retained_path = _safe_relative_path(
                item.get("retained_path"),
                field=f"source_inventory[{index}].retained_path",
            )
            retained_file = evidence_root / PurePosixPath(retained_path)
            retained_sha = _require_sha256(
                item.get("retained_sha256"),
                field=f"source_inventory[{index}].retained_sha256",
            )
            retained_bytes = item.get("retained_bytes")
            if (
                not retained_file.is_file()
                or retained_file.stat().st_size != retained_bytes
                or _sha256_file(retained_file) != retained_sha
            ):
                raise ValueError(f"retained evidence file drifted: {retained_path}")
            compression = item.get("compression")
            if compression == "none":
                if retained_sha != source_sha or retained_bytes != source_bytes:
                    raise ValueError(f"exact retained copy does not match source: {source_path}")
            elif compression == "gzip-level-9-mtime-0":
                try:
                    decompressed = gzip.decompress(retained_file.read_bytes())
                except (OSError, EOFError) as exc:
                    raise ValueError(f"retained ULog gzip is invalid: {retained_path}") from exc
                if len(decompressed) != source_bytes or _sha256_bytes(decompressed) != source_sha:
                    raise ValueError(f"retained ULog does not reproduce source: {source_path}")
            else:
                raise ValueError(f"unsupported retained compression: {compression}")
        elif item.get("retained") is False:
            if not isinstance(item.get("omission_reason"), str):
                raise ValueError("omitted source inventory item lacks a reason")
        else:
            raise ValueError("source inventory retained flag must be boolean")


def verify_physical_campaign_evidence(
    evidence_root: Path,
    *,
    source_root: Path | None = None,
    failure_root: Path | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Verify hashes, retained bytes, matrix semantics, and optional source trees."""

    manifest_path = evidence_root / "px4-physical-campaign-v1.manifest.json"
    receipt_path = evidence_root / "px4-physical-campaign-v1.receipt.json"
    digest_path = evidence_root / "px4-physical-campaign-v1.sha256"
    manifest = _load_json(manifest_path)
    receipt = _load_json(receipt_path)
    if manifest.get("schema_version") != PHYSICAL_CAMPAIGN_SCHEMA_VERSION:
        raise ValueError("physical campaign manifest schema is invalid")
    if receipt.get("schema_version") != PHYSICAL_CAMPAIGN_RECEIPT_SCHEMA_VERSION:
        raise ValueError("physical campaign receipt schema is invalid")
    unsigned_manifest = {
        key: value for key, value in manifest.items() if key != "manifest_sha256"
    }
    if manifest.get("manifest_sha256") != _sha256_value(unsigned_manifest):
        raise ValueError("physical campaign manifest hash does not recompute")
    unsigned_receipt = {
        key: value for key, value in receipt.items() if key != "receipt_sha256"
    }
    if receipt.get("receipt_sha256") != _sha256_value(unsigned_receipt):
        raise ValueError("physical campaign receipt hash does not recompute")
    manifest_bytes = manifest_path.read_bytes()
    receipt_bytes = receipt_path.read_bytes()
    manifest_ref = _nested_mapping(receipt.get("manifest"), field="receipt.manifest")
    if (
        manifest_ref.get("path") != manifest_path.name
        or manifest_ref.get("bytes") != len(manifest_bytes)
        or manifest_ref.get("sha256") != _sha256_bytes(manifest_bytes)
        or manifest_ref.get("manifest_sha256") != manifest.get("manifest_sha256")
    ):
        raise ValueError("physical campaign receipt does not bind the manifest")
    expected_digest = (
        f"{_sha256_bytes(manifest_bytes)}  {manifest_path.name}\n"
        f"{_sha256_bytes(receipt_bytes)}  {receipt_path.name}\n"
    ).encode("ascii")
    if digest_path.read_bytes() != expected_digest:
        raise ValueError("physical campaign SHA-256 sidecar drifted")
    if (
        manifest.get("subject_commit") != receipt.get("subject_commit")
        or manifest.get("exporter_commit") != receipt.get("exporter_commit")
        or manifest.get("generated_at") != receipt.get("generated_at")
    ):
        raise ValueError("physical campaign receipt provenance drifted")
    _require_commit(manifest.get("subject_commit"), field="subject_commit")
    _require_commit(manifest.get("exporter_commit"), field="exporter_commit")
    _require_utc_timestamp(manifest.get("generated_at"), field="generated_at")
    if (
        manifest.get("physical_fidelity") is not True
        or manifest.get("real_aircraft_fidelity") is not False
        or manifest.get("claim_boundary") != PHYSICAL_CAMPAIGN_CLAIM_BOUNDARY
        or manifest.get("evidence_class") != PHYSICAL_CAMPAIGN_EVIDENCE_CLASS
        or manifest.get("claim_label") != PHYSICAL_CAMPAIGN_CLAIM_LABEL
        or manifest.get("network_calls") != 0
        or manifest.get("real_credentials_used") is not False
    ):
        raise ValueError("physical campaign claim boundary drifted")
    protocol = _nested_mapping(manifest.get("protocol"), field="protocol")
    matrix = _nested_mapping(protocol.get("matrix"), field="protocol.matrix")
    if (
        matrix.get("seeds") != list(_EXPECTED_SEEDS)
        or matrix.get("scenarios") != list(_SCENARIOS)
        or matrix.get("trial_count") != 6
        or matrix.get("paired_by_seed") is not True
        or protocol.get("candidate_id") != _EXPECTED_CANDIDATE
        or protocol.get("track_type") != "circle"
        or protocol.get("world") != "default"
        or protocol.get("vehicle") != "x500"
        or protocol.get("px4_parameter_request") != {"MPC_XY_P": _EXPECTED_MPC_XY_P}
        or protocol.get("steady_wind_gazebo_enu_mps") != _EXPECTED_WIND_VECTOR
        or protocol.get("timeout_base_1x_seconds") != 300
        or protocol.get("unsupported_effects_included") is not False
    ):
        raise ValueError("physical campaign fixed protocol drifted")
    retention = _nested_mapping(manifest.get("retention_policy"), field="retention_policy")
    if (
        retention.get("policy_id")
        != "dronedream.minimum-sufficient-px4-campaign-retention/v1"
        or any(
            retention.get(field) is not True
            for field in (
                "all_source_files_inventoried",
                "retained_raw_ulog",
                "retained_normalized_telemetry",
                "retained_scenario_readback",
                "retained_parameter_readback",
                "retained_runtime_and_firmware_identity",
                "omitted_regenerable_runtime_rootfs_copies",
                "omitted_verbose_stdout_streams",
            )
        )
        or retention.get("ulog_compression") != "gzip-level-9-mtime-0"
    ):
        raise ValueError("physical campaign retention policy drifted")

    runtime = _nested_mapping(manifest.get("runtime_identity"), field="runtime_identity")
    firmware_commit = _require_commit(
        runtime.get("px4_commit"),
        field="runtime_identity.px4_commit",
    )
    trials = manifest.get("trials")
    if not isinstance(trials, list) or len(trials) != 6:
        raise ValueError("physical campaign must contain six Trials")
    observed_matrix: set[tuple[int, str]] = set()
    job_ids: set[str] = set()
    aggregate_inventory: list[dict[str, Any]] = []
    aggregate_counts = {
        "source_file_count": 0,
        "source_bytes": 0,
        "retained_file_count": 0,
        "retained_bytes": 0,
    }
    rmse_values: list[float] = []
    coverage_values: list[float] = []
    for raw_trial in trials:
        trial = _nested_mapping(raw_trial, field="campaign Trial")
        seed = trial.get("seed")
        scenario = trial.get("scenario")
        if isinstance(seed, bool) or not isinstance(seed, int) or scenario not in _SCENARIOS:
            raise ValueError("campaign Trial matrix identity is invalid")
        observed_matrix.add((seed, str(scenario)))
        if trial.get("candidate_id") != _EXPECTED_CANDIDATE:
            raise ValueError("campaign candidate drifted")
        if trial.get("success") is not True or trial.get("pass_flag") is not True:
            raise ValueError("campaign contains a non-passing Trial")
        if not isinstance(trial.get("job_id"), str):
            raise ValueError("campaign Trial job_id is invalid")
        job_ids.add(str(trial["job_id"]))
        directory = _safe_relative_path(
            trial.get("directory"), field="campaign Trial directory"
        )
        trial_source = source_root / directory if source_root is not None else None
        _verify_retained_inventory(
            trial.get("source_inventory"),
            evidence_root=evidence_root,
            source_root=trial_source,
        )
        if trial.get("source_inventory_sha256") != _inventory_sha256(
            trial["source_inventory"]
        ):
            raise ValueError("campaign Trial source inventory hash drifted")
        inventory = trial["source_inventory"]
        aggregate_inventory.extend(
            {
                **item,
                "source_path": f"{directory}/{item['source_path']}",
            }
            for item in inventory
        )
        aggregate_counts["source_file_count"] += len(inventory)
        aggregate_counts["source_bytes"] += sum(
            int(item["source_bytes"]) for item in inventory
        )
        aggregate_counts["retained_file_count"] += sum(
            item.get("retained") is True for item in inventory
        )
        aggregate_counts["retained_bytes"] += sum(
            int(item["retained_bytes"])
            for item in inventory
            if item.get("retained") is True
        )
        metrics = _nested_mapping(trial.get("metrics"), field=f"{directory}.metrics")
        rmse_values.append(_require_finite(metrics.get("rmse_m"), field="metrics.rmse_m"))
        coverage_values.append(
            _require_finite(
                metrics.get("evaluation_track_coverage"),
                field="metrics.evaluation_track_coverage",
            )
        )
        ulog_rows = [
            item
            for item in inventory
            if isinstance(item, dict) and item.get("source_path") == "px4_source.ulg"
        ]
        if len(ulog_rows) != 1 or ulog_rows[0].get("retained") is not True:
            raise ValueError("campaign Trial does not bind one retained PX4 ULog")
        spec = PhysicalTrialSpec(directory, str(scenario), int(seed))
        retained_projection = _validate_success_trial(
            evidence_root / "trials" / PurePosixPath(directory),
            spec,
            firmware_commit=firmware_commit,
            ulog_sha256=_require_sha256(
                ulog_rows[0].get("source_sha256"),
                field=f"{directory} retained ULog source SHA-256",
            ),
        )
        for key, expected in retained_projection.items():
            if trial.get(key) != expected:
                raise ValueError(f"campaign Trial retained projection drifted: {directory}.{key}")
        if trial_source is not None:
            source_projection = _validate_success_trial(
                trial_source,
                spec,
                firmware_commit=firmware_commit,
            )
            for key, expected in source_projection.items():
                if trial.get(key) != expected:
                    raise ValueError(
                        f"campaign Trial source projection drifted: {directory}.{key}"
                    )
    expected_matrix = {
        (seed, scenario) for seed in _EXPECTED_SEEDS for scenario in _SCENARIOS
    }
    if observed_matrix != expected_matrix or len(job_ids) != 1:
        raise ValueError("physical campaign is not the fixed paired matrix")

    history = _nested_mapping(manifest.get("failure_history"), field="failure_history")
    failure_source_commit = _require_commit(
        history.get("source_commit"),
        field="failure_history.source_commit",
    )
    attempts = history.get("attempts")
    if not isinstance(attempts, list) or len(attempts) != 4:
        raise ValueError("physical campaign failure history is incomplete")
    if [
        attempt.get("directory") if isinstance(attempt, dict) else None
        for attempt in attempts
    ] != list(_EXPECTED_FAILURE_DIRECTORIES):
        raise ValueError("physical campaign failure history order drifted")
    for raw_attempt in attempts:
        attempt = _nested_mapping(raw_attempt, field="failure attempt")
        if attempt.get("success") is not False:
            raise ValueError("failure history contains a successful attempt")
        directory = _safe_relative_path(
            attempt.get("directory"), field="failure attempt directory"
        )
        attempt_source = failure_root / directory if failure_root is not None else None
        _verify_retained_inventory(
            attempt.get("source_inventory"),
            evidence_root=evidence_root,
            source_root=attempt_source,
        )
        if attempt.get("source_inventory_sha256") != _inventory_sha256(
            attempt["source_inventory"]
        ):
            raise ValueError("failure attempt source inventory hash drifted")
        inventory = attempt["source_inventory"]
        aggregate_inventory.extend(
            {
                **item,
                "source_path": f"failure-history/{directory}/{item['source_path']}",
            }
            for item in inventory
        )
        aggregate_counts["source_file_count"] += len(inventory)
        aggregate_counts["source_bytes"] += sum(
            int(item["source_bytes"]) for item in inventory
        )
        aggregate_counts["retained_file_count"] += sum(
            item.get("retained") is True for item in inventory
        )
        aggregate_counts["retained_bytes"] += sum(
            int(item["retained_bytes"])
            for item in inventory
            if item.get("retained") is True
        )
        retained_attempt = evidence_root / "failure-history" / PurePosixPath(directory)
        retained_projection = _validate_failure_trial(
            retained_attempt,
            expected_source_commit=failure_source_commit,
        )
        for key, expected in retained_projection.items():
            if attempt.get(key) != expected:
                raise ValueError(
                    f"failure attempt retained projection drifted: {directory}.{key}"
                )
        if attempt_source is not None:
            source_projection = _validate_failure_trial(
                attempt_source,
                expected_source_commit=failure_source_commit,
            )
            for key, expected in source_projection.items():
                if attempt.get(key) != expected:
                    raise ValueError(
                        f"failure attempt source projection drifted: {directory}.{key}"
                    )
        if directory == "probe-nominal-attempt-4":
            post_fix = _nested_mapping(
                attempt.get("post_fix_reprocessing"),
                field="failure attempt post_fix_reprocessing",
            )
            if post_fix.get("processor_commit") != manifest.get("subject_commit"):
                raise ValueError("post-fix ULog reprocessing commit drifted")
            ulog_rows = [
                item
                for item in attempt["source_inventory"]
                if isinstance(item, dict) and item.get("source_path") == "px4_source.ulg"
            ]
            if len(ulog_rows) != 1:
                raise ValueError("post-fix failure does not bind one PX4 ULog")
            reprocessed_path = (
                evidence_root
                / "failure-history"
                / directory
                / "telemetry.reprocessed.json"
            )
            telemetry_summary = _validate_reprocessed_failure_telemetry(
                _load_json(reprocessed_path),
                ulog_sha256=_require_sha256(
                    ulog_rows[0].get("source_sha256"),
                    field="post-fix ULog source SHA-256",
                ),
                ulog_bytes=int(ulog_rows[0]["source_bytes"]),
            )
            expected_post_fix = {
                "processor_commit": manifest.get("subject_commit"),
                "path": (
                    "failure-history/probe-nominal-attempt-4/"
                    "telemetry.reprocessed.json"
                ),
                "sha256": _sha256_file(reprocessed_path),
                "bytes": reprocessed_path.stat().st_size,
                **telemetry_summary,
                "claim": (
                    "The exact retained ULog was successfully parsed after the NumPy "
                    "scalar fix; this diagnostic is not part of the six-Trial matrix."
                ),
            }
            if dict(post_fix) != expected_post_fix:
                raise ValueError("post-fix telemetry projection drifted")

    summary = _nested_mapping(manifest.get("summary"), field="summary")
    expected_summary = {
        "trial_count": 6,
        "success_count": 6,
        "pass_count": 6,
        "scenario_verified_applied_count": 4,
        "retained_failure_probe_count": 4,
        "rmse_m_min": min(rmse_values),
        "rmse_m_max": max(rmse_values),
        "evaluation_track_coverage_min": min(coverage_values),
        "evaluation_track_coverage_max": max(coverage_values),
        **aggregate_counts,
        "full_source_inventory_sha256": _inventory_sha256(aggregate_inventory),
    }
    if dict(summary) != expected_summary:
        raise ValueError("physical campaign aggregate summary does not recompute")
    receipt_result = _nested_mapping(receipt.get("result"), field="receipt.result")
    if dict(receipt_result) != {
        "status": "passed",
        "trial_count": 6,
        "passed": 6,
        "failed": 0,
        "retained_failure_probes": 4,
    }:
        raise ValueError("physical campaign receipt result drifted")
    if (
        receipt.get("runtime_id") != runtime.get("runtime_id")
        or receipt.get("px4_commit") != firmware_commit
    ):
        raise ValueError("physical campaign receipt Runtime identity drifted")

    for label in ("runtime_manifest", "runtime_observation"):
        artifact = _nested_mapping(runtime.get(label), field=f"runtime_identity.{label}")
        relative = _safe_relative_path(
            artifact.get("path"), field=f"runtime_identity.{label}.path"
        )
        path = evidence_root / relative
        if (
            not path.is_file()
            or path.stat().st_size != artifact.get("bytes")
            or _sha256_file(path) != artifact.get("sha256")
        ):
            raise ValueError(f"retained Runtime artifact drifted: {label}")
    runtime_manifest = _load_json(
        evidence_root
        / _safe_relative_path(
            _nested_mapping(
                runtime.get("runtime_manifest"),
                field="runtime_identity.runtime_manifest",
            ).get("path"),
            field="runtime_identity.runtime_manifest.path",
        )
    )
    release_summary = _validate_runtime_release_manifest(
        runtime_manifest,
        expected_firmware_commit=firmware_commit,
    )
    runtime_observation = _load_json(
        evidence_root
        / _safe_relative_path(
            _nested_mapping(
                runtime.get("runtime_observation"),
                field="runtime_identity.runtime_observation",
            ).get("path"),
            field="runtime_identity.runtime_observation.path",
        )
    )
    observation_summary = _validate_runtime_observation(
        runtime_observation,
        expected_runtime_id=str(release_summary["runtime_id"]),
        expected_firmware_commit=firmware_commit,
    )
    for key, expected in {**release_summary, **observation_summary}.items():
        if runtime.get(key) != expected:
            raise ValueError(f"physical campaign Runtime summary drifted: {key}")
    return manifest, receipt


__all__ = [
    "DEFAULT_TRIAL_SPECS",
    "PHYSICAL_CAMPAIGN_CLAIM_BOUNDARY",
    "PHYSICAL_CAMPAIGN_RECEIPT_SCHEMA_VERSION",
    "PHYSICAL_CAMPAIGN_SCHEMA_VERSION",
    "PhysicalTrialSpec",
    "build_runtime_observation",
    "export_physical_campaign_evidence",
    "verify_physical_campaign_evidence",
]
