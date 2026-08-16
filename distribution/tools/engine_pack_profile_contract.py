"""Versioned, fail-closed Engine Pack payload profile contracts."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

PROFILE_PATH = "distribution/engine-pack-profiles/sim-only.v1.json"
PROFILE_KEYS = {
    "schemaVersion",
    "kind",
    "profileId",
    "profileVersion",
    "includesLargeSimulator",
    "hardwarePayloadAllowed",
    "allowedEditionIds",
    "allowedVehiclePackIds",
    "sourceRoots",
    "excludedSourcePaths",
    "directPayloadPaths",
    "sourceMappings",
    "forbiddenPayloadPaths",
    "forbiddenPayloadPrefixes",
}
MAPPING_KEYS = {"payloadPath", "sourcePath", "sourceSha256"}
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
SEMVER_RE = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")
SAFE_PATH_RE = re.compile(r"^[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)*$")
EXPECTED_SOURCE_ROOTS = (
    "backend/alembic",
    "backend/alembic.ini",
    "backend/app",
    "backend/pyproject.toml",
    "scripts/simulators",
    "worker/drone_dream_worker",
    "worker/pyproject.toml",
)
EXPECTED_EXCLUDED_SOURCE_PATHS = ("backend/app/distribution_safety.py",)
EXPECTED_MAPPING_PATHS = {
    "distribution/runtime-contract-registry.v1.json": (
        "distribution/runtime-contract-registry.sim-only.v1.json"
    ),
    "distribution/vehicle-packs/registry.v1.json": (
        "distribution/vehicle-packs/registry.sim-only.v1.json"
    ),
}
REQUIRED_DIRECT_PATHS = {
    "LICENSE",
    "runtime/THIRD_PARTY_NOTICES.md",
    PROFILE_PATH,
    "distribution/capabilities/core-capabilities.v1.json",
    "distribution/editions/sim.v1.json",
    "distribution/schemas/capability-policy.schema.json",
    "distribution/schemas/edition-manifest.schema.json",
    "distribution/schemas/engine-pack-profile.schema.json",
    "distribution/schemas/upstream-source-inventory.schema.json",
    "distribution/schemas/vehicle-pack-manifest.schema.json",
    "distribution/schemas/vehicle-pack-profile-registry.schema.json",
    "distribution/tools/distribution_contract.py",
    "distribution/tools/engine_pack_profile_contract.py",
    "distribution/upstream-sources.v1.json",
    "distribution/vehicle-packs/px4-gazebo-x500-reference.v1.json",
}
REQUIRED_FORBIDDEN_PATHS = {
    "backend/app/distribution_safety.py",
    "distribution/editions/field.v1.json",
    "distribution/editions/lab.v1.json",
    "distribution/runtime-contract-registry.sim-only.v1.json",
    "distribution/safety/edition-execution-gate.v1.json",
    "distribution/schemas/edition-execution-authorization.schema.json",
    "distribution/schemas/edition-execution-gate-policy.schema.json",
    "distribution/schemas/vehicle-pack-registry.schema.json",
    "distribution/tools/edition_safety_contract.py",
    "distribution/vehicle-packs/amovlab-mfp450-pixhawk6c.v1.json",
    "distribution/vehicle-packs/amovlab-p450-px4.v1.json",
    "distribution/vehicle-packs/bitcraze-crazyflie-2-1-plus.v1.json",
    "distribution/vehicle-packs/holybro-qav250-pixhawk6c-mini.v1.json",
    "distribution/vehicle-packs/holybro-s500-v2-pixhawk6c.v1.json",
    "distribution/vehicle-packs/holybro-x500-v2-pixhawk6.v1.json",
    "distribution/vehicle-packs/holybro-x650-pixhawk6.v1.json",
    "distribution/vehicle-packs/registry.sim-only.v1.json",
}
EXPECTED_FORBIDDEN_PREFIXES = (
    "distribution/build-planning",
    "distribution/build-plans",
    "distribution/tests",
)


class EnginePackProfileError(RuntimeError):
    """Raised when a profile or its payload cannot be trusted."""


def canonical_json(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _exact_keys(value: Mapping[str, Any], expected: set[str], label: str) -> None:
    if set(value) != expected:
        raise EnginePackProfileError(f"{label} fields do not match the contract")


def _path_list(value: Any, label: str) -> tuple[str, ...]:
    if (
        not isinstance(value, list)
        or any(not isinstance(item, str) or not SAFE_PATH_RE.fullmatch(item) for item in value)
        or value != sorted(set(value))
    ):
        raise EnginePackProfileError(f"{label} must be unique, sorted safe paths")
    return tuple(value)


def validate_profile(document: Any) -> dict[str, Any]:
    if not isinstance(document, dict):
        raise EnginePackProfileError("Engine Pack profile must be an object")
    _exact_keys(document, PROFILE_KEYS, "Engine Pack profile")
    if (
        document["schemaVersion"] != 1
        or document["kind"] != "dronedream-engine-pack-profile"
        or document["profileId"] != "sim-only"
        or document["profileVersion"] != "1.0.0"
        or not SEMVER_RE.fullmatch(str(document["profileVersion"]))
    ):
        raise EnginePackProfileError("Engine Pack profile identity is unsupported")
    if document["includesLargeSimulator"] is not True:
        raise EnginePackProfileError("Sim-only profile must retain the simulator closure")
    if document["hardwarePayloadAllowed"] is not False:
        raise EnginePackProfileError("Sim-only profile cannot contain hardware payloads")
    if document["allowedEditionIds"] != ["sim"]:
        raise EnginePackProfileError("Sim-only profile must contain only the Sim edition")
    if document["allowedVehiclePackIds"] != ["px4-gazebo-x500-reference"]:
        raise EnginePackProfileError("Sim-only profile must contain only the X500 reference pack")
    if _path_list(document["sourceRoots"], "sourceRoots") != EXPECTED_SOURCE_ROOTS:
        raise EnginePackProfileError("Sim-only source roots drifted")
    if (
        _path_list(document["excludedSourcePaths"], "excludedSourcePaths")
        != EXPECTED_EXCLUDED_SOURCE_PATHS
    ):
        raise EnginePackProfileError("Sim-only source exclusions drifted")
    direct = set(_path_list(document["directPayloadPaths"], "directPayloadPaths"))
    if direct != REQUIRED_DIRECT_PATHS:
        raise EnginePackProfileError("Sim-only direct payload allowlist drifted")
    mappings = document["sourceMappings"]
    if not isinstance(mappings, list) or len(mappings) != len(EXPECTED_MAPPING_PATHS):
        raise EnginePackProfileError("Sim-only source mappings are incomplete")
    observed_mappings: dict[str, str] = {}
    for index, mapping in enumerate(mappings):
        if not isinstance(mapping, dict):
            raise EnginePackProfileError(f"sourceMappings[{index}] must be an object")
        _exact_keys(mapping, MAPPING_KEYS, f"sourceMappings[{index}]")
        payload_path = mapping["payloadPath"]
        source_path = mapping["sourcePath"]
        digest = mapping["sourceSha256"]
        if (
            not isinstance(payload_path, str)
            or not SAFE_PATH_RE.fullmatch(payload_path)
            or not isinstance(source_path, str)
            or not SAFE_PATH_RE.fullmatch(source_path)
            or not isinstance(digest, str)
            or not SHA256_RE.fullmatch(digest)
            or payload_path in observed_mappings
        ):
            raise EnginePackProfileError(f"sourceMappings[{index}] is invalid")
        observed_mappings[payload_path] = source_path
    if observed_mappings != EXPECTED_MAPPING_PATHS:
        raise EnginePackProfileError("Sim-only source mapping paths drifted")
    forbidden = set(_path_list(document["forbiddenPayloadPaths"], "forbiddenPayloadPaths"))
    if forbidden != REQUIRED_FORBIDDEN_PATHS:
        raise EnginePackProfileError("Sim-only forbidden payload paths drifted")
    if (
        _path_list(document["forbiddenPayloadPrefixes"], "forbiddenPayloadPrefixes")
        != EXPECTED_FORBIDDEN_PREFIXES
    ):
        raise EnginePackProfileError("Sim-only forbidden payload prefixes drifted")
    if direct & forbidden or set(observed_mappings) & forbidden:
        raise EnginePackProfileError("Sim-only allowlist intersects its denylist")
    return document


def load_profile(root: Path) -> dict[str, Any]:
    path = root / PROFILE_PATH
    if path.is_symlink() or not path.is_file():
        raise EnginePackProfileError("Sim-only profile must be an ordinary file")
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise EnginePackProfileError("Sim-only profile could not be read") from error
    return validate_profile(document)


def verify_profile_files(root: Path, profile: Mapping[str, Any], *, active_payload: bool) -> None:
    resolved_root = root.resolve()
    for relative in profile["directPayloadPaths"]:
        candidate = root / relative
        if (
            candidate.is_symlink()
            or not candidate.is_file()
            or not candidate.resolve().is_relative_to(resolved_root)
        ):
            raise EnginePackProfileError(f"required profile file is unavailable: {relative}")
    for mapping in profile["sourceMappings"]:
        relative = mapping["payloadPath"] if active_payload else mapping["sourcePath"]
        candidate = root / relative
        if (
            candidate.is_symlink()
            or not candidate.is_file()
            or not candidate.resolve().is_relative_to(resolved_root)
            or sha256_file(candidate) != mapping["sourceSha256"]
        ):
            raise EnginePackProfileError(f"profile source mapping drifted: {relative}")


def validate_payload_paths(profile: Mapping[str, Any], paths: Sequence[str]) -> None:
    if list(paths) != sorted(set(paths)):
        raise EnginePackProfileError("Engine Pack payload paths must be unique and sorted")
    path_set = set(paths)
    required = set(profile["directPayloadPaths"]) | {
        mapping["payloadPath"] for mapping in profile["sourceMappings"]
    }
    if not required <= path_set:
        raise EnginePackProfileError("Sim-only payload is missing a required contract file")
    if path_set & set(profile["forbiddenPayloadPaths"]):
        raise EnginePackProfileError("Sim-only payload contains a forbidden file")
    for prefix in profile["forbiddenPayloadPrefixes"]:
        if any(path == prefix or path.startswith(f"{prefix}/") for path in path_set):
            raise EnginePackProfileError("Sim-only payload contains a forbidden path family")
    for excluded in profile["excludedSourcePaths"]:
        if any(path == excluded or path.startswith(f"{excluded}/") for path in path_set):
            raise EnginePackProfileError("Sim-only payload contains an excluded source")
    editions = {path for path in path_set if path.startswith("distribution/editions/")}
    if editions != {"distribution/editions/sim.v1.json"}:
        raise EnginePackProfileError("Sim-only payload edition inventory drifted")
    vehicle_metadata = {
        path
        for path in path_set
        if path.startswith("distribution/vehicle-packs/") and path.endswith(".json")
    }
    if vehicle_metadata != {
        "distribution/vehicle-packs/px4-gazebo-x500-reference.v1.json",
        "distribution/vehicle-packs/registry.v1.json",
    }:
        raise EnginePackProfileError("Sim-only Vehicle Pack inventory drifted")
    if not any(path.startswith("backend/app/simulator/") for path in path_set):
        raise EnginePackProfileError("Sim-only payload lost backend simulator support")
    if not any(path.startswith("scripts/simulators/") for path in path_set):
        raise EnginePackProfileError("Sim-only payload lost launcher support")


def profile_manifest_binding(profile: Mapping[str, Any], root: Path) -> dict[str, Any]:
    return {
        "profileId": profile["profileId"],
        "profileVersion": profile["profileVersion"],
        "profileManifestPath": PROFILE_PATH,
        "profileManifestSha256": sha256_file(root / PROFILE_PATH),
        "includesLargeSimulator": profile["includesLargeSimulator"],
        "excludedSourcePaths": list(profile["excludedSourcePaths"]),
    }
