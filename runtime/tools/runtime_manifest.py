#!/usr/bin/env python3
"""Generate and validate DroneDreamRuntime manifests without third-party packages."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1
REQUIRED_SMOKE_CHECKS = {
    "component_versions",
    "python_imports",
    "valkey_ping",
    "api_worker_heartbeat",
    "real_cli_dry_run",
    "px4_gazebo_headless",
    "parameter_readback",
}
REQUIRED_PINS = {
    "DRONEDREAM_RUNTIME_VERSION",
    "TARGET_ARCH",
    "UBUNTU_VERSION",
    "UBUNTU_CODENAME",
    "UBUNTU_BASE_IMAGE",
    "UBUNTU_INDEX_DIGEST",
    "PX4_VERSION",
    "PX4_GIT_URL",
    "PX4_GIT_COMMIT",
    "GAZEBO_RELEASE",
    "GAZEBO_METAPACKAGE",
    "GAZEBO_METAPACKAGE_VERSION",
    "GAZEBO_APT_KEY_URL",
    "GAZEBO_APT_KEY_SHA256",
    "VALKEY_VERSION",
    "VALKEY_GIT_URL",
    "VALKEY_GIT_COMMIT",
    "PYTHON_VERSION",
    "BACKEND_VERSION",
    "WORKER_VERSION",
    "MAVSDK_VERSION",
    "PYULOG_VERSION",
}
SHA40 = re.compile(r"^[0-9a-f]{40}$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")
SEMVER = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")
EXACT_REQUIREMENT = re.compile(r"^([A-Za-z0-9][A-Za-z0-9._-]*)==([A-Za-z0-9][A-Za-z0-9.!+_-]*)$")


class ManifestError(ValueError):
    pass


def _require_exact_keys(value: dict[str, Any], expected: set[str], label: str) -> None:
    actual = set(value)
    if actual == expected:
        return
    missing = sorted(expected - actual)
    extra = sorted(actual - expected)
    details: list[str] = []
    if missing:
        details.append("missing " + ", ".join(missing))
    if extra:
        details.append("unsupported " + ", ".join(extra))
    raise ManifestError(f"{label} fields are invalid ({'; '.join(details)})")


def _validate_timestamp(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise ManifestError(f"{label} must be an ISO-8601 UTC timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ManifestError(f"{label} must be an ISO-8601 UTC timestamp") from exc
    if parsed.utcoffset() is None or parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        raise ManifestError(f"{label} must use UTC")
    return value


def load_pins(path: Path) -> dict[str, str]:
    pins: dict[str, str] = {}
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if "=" not in stripped:
            raise ManifestError(f"{path}:{number}: expected NAME=value")
        name, value = stripped.split("=", 1)
        if not re.fullmatch(r"[A-Z][A-Z0-9_]*", name) or not value:
            raise ManifestError(f"{path}:{number}: invalid pin")
        if name in pins:
            raise ManifestError(f"{path}:{number}: duplicate pin {name}")
        pins[name] = value
    missing = sorted(REQUIRED_PINS - pins.keys())
    if missing:
        raise ManifestError(f"missing pins: {', '.join(missing)}")
    if pins["TARGET_ARCH"] != "amd64":
        raise ManifestError("TARGET_ARCH must be amd64 for this WSL2 release")
    if not pins["UBUNTU_BASE_IMAGE"].startswith("ubuntu:24.04@sha256:"):
        raise ManifestError("Ubuntu 24.04 base image must be content-addressed")
    base_digest = pins["UBUNTU_BASE_IMAGE"].rsplit("sha256:", 1)[-1]
    index_digest = pins["UBUNTU_INDEX_DIGEST"].removeprefix("sha256:")
    if not SHA256.fullmatch(base_digest) or not SHA256.fullmatch(index_digest):
        raise ManifestError("Ubuntu image digests must be full lowercase SHA-256 values")
    if not SHA256.fullmatch(pins["GAZEBO_APT_KEY_SHA256"]):
        raise ManifestError("GAZEBO_APT_KEY_SHA256 must be a full lowercase SHA-256")
    for key in ("PX4_GIT_URL", "GAZEBO_APT_KEY_URL", "VALKEY_GIT_URL"):
        if not pins[key].startswith("https://") or any(
            character.isspace() for character in pins[key]
        ):
            raise ManifestError(f"{key} must be an absolute whitespace-free HTTPS URL")
    for key in ("PX4_GIT_COMMIT", "VALKEY_GIT_COMMIT"):
        if not SHA40.fullmatch(pins[key]):
            raise ManifestError(f"{key} must be a full lowercase Git SHA")
    for key in ("DRONEDREAM_RUNTIME_VERSION", "BACKEND_VERSION", "WORKER_VERSION"):
        if not SEMVER.fullmatch(pins[key]):
            raise ManifestError(f"{key} must be semantic x.y.z")
    return pins


def validate_python_lock(path: Path) -> dict[str, str]:
    packages: dict[str, str] = {}
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        match = EXACT_REQUIREMENT.fullmatch(stripped)
        if match is None:
            raise ManifestError(f"{path}:{number}: requirement must use one exact == pin")
        name, version = match.groups()
        normalized = name.lower().replace("_", "-")
        if not name or not version or normalized in packages:
            raise ManifestError(f"{path}:{number}: invalid or duplicate requirement")
        packages[normalized] = version
    for required in ("fastapi", "mavsdk", "pyulog"):
        if required not in packages:
            raise ManifestError(f"python lock is missing {required}")
    return packages


def validate_pin_lock_versions(pins: dict[str, str], packages: dict[str, str]) -> None:
    for pin, package in (("MAVSDK_VERSION", "mavsdk"), ("PYULOG_VERSION", "pyulog")):
        if packages.get(package) != pins[pin]:
            raise ManifestError(
                f"{pin}={pins[pin]} does not match {package}=={packages.get(package)}"
            )


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def generate(pins_path: Path, lock_path: Path, source_commit: str, output: Path) -> dict:
    pins = load_pins(pins_path)
    packages = validate_python_lock(lock_path)
    validate_pin_lock_versions(pins, packages)
    if not SHA40.fullmatch(source_commit):
        raise ManifestError("DroneDream source commit must be a full lowercase Git SHA")
    identity = "|".join(
        (
            pins["DRONEDREAM_RUNTIME_VERSION"],
            source_commit,
            pins["UBUNTU_BASE_IMAGE"],
            pins["PX4_GIT_COMMIT"],
            pins["VALKEY_GIT_COMMIT"],
            sha256(lock_path),
        )
    )
    manifest = {
        "schemaVersion": SCHEMA_VERSION,
        "runtimeId": str(uuid.uuid5(uuid.NAMESPACE_URL, "https://dronedream/runtime/" + identity)),
        "version": pins["DRONEDREAM_RUNTIME_VERSION"],
        "target": {
            "os": "ubuntu",
            "version": pins["UBUNTU_VERSION"],
            "codename": pins["UBUNTU_CODENAME"],
            "arch": pins["TARGET_ARCH"],
            "format": "wsl2-rootfs-tar",
        },
        "source": {"droneDreamCommit": source_commit},
        # Stable, flat contract consumed by desktop/src-tauri/src/runtime.rs.
        "components": {
            "backend": pins["BACKEND_VERSION"],
            "px4": f"{pins['PX4_VERSION']}@{pins['PX4_GIT_COMMIT'][:12]}",
            "gazebo": f"{pins['GAZEBO_RELEASE']}@{pins['GAZEBO_METAPACKAGE_VERSION']}",
        },
        "componentDetails": {
            "ubuntu": {
                "image": pins["UBUNTU_BASE_IMAGE"],
                "indexDigest": pins["UBUNTU_INDEX_DIGEST"],
            },
            "px4": {"version": pins["PX4_VERSION"], "commit": pins["PX4_GIT_COMMIT"]},
            "gazebo": {
                "release": pins["GAZEBO_RELEASE"],
                "packageVersion": pins["GAZEBO_METAPACKAGE_VERSION"],
                "aptKeySha256": pins["GAZEBO_APT_KEY_SHA256"],
            },
            "backend": {"version": pins["BACKEND_VERSION"], "commit": source_commit},
            "worker": {"version": pins["WORKER_VERSION"], "commit": source_commit},
            "valkey": {
                "version": pins["VALKEY_VERSION"],
                "commit": pins["VALKEY_GIT_COMMIT"],
            },
            "python": {"version": pins["PYTHON_VERSION"]},
            "mavsdk": {"version": pins["MAVSDK_VERSION"]},
            "pyulog": {"version": pins["PYULOG_VERSION"]},
        },
        "locks": {
            "pinsSha256": sha256(pins_path),
            "pythonRequirementsSha256": sha256(lock_path),
        },
        # These are deliberately false. Only promote_smoke() may change them.
        "smokeTests": {"px4Sitl": False, "gazebo": False, "parameterReadback": False},
        "smokeReport": None,
        "artifact": None,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return manifest


def validate_manifest(manifest: Any, *, require_smoke_passed: bool = False) -> None:
    if not isinstance(manifest, dict):
        raise ManifestError("runtime manifest must be an object")
    _require_exact_keys(
        manifest,
        {
            "schemaVersion",
            "runtimeId",
            "version",
            "target",
            "source",
            "components",
            "componentDetails",
            "locks",
            "smokeTests",
            "smokeReport",
            "artifact",
        },
        "runtime manifest",
    )
    if manifest.get("schemaVersion") != SCHEMA_VERSION:
        raise ManifestError("unsupported runtime manifest schema")
    runtime_id = manifest.get("runtimeId")
    if not isinstance(runtime_id, str):
        raise ManifestError("manifest runtimeId must be a canonical lowercase UUID")
    try:
        parsed_runtime_id = uuid.UUID(runtime_id)
    except ValueError as exc:
        raise ManifestError("manifest runtimeId must be a canonical lowercase UUID") from exc
    if str(parsed_runtime_id) != runtime_id:
        raise ManifestError("manifest runtimeId must be a canonical lowercase UUID")
    version = manifest.get("version")
    if not isinstance(version, str) or not SEMVER.fullmatch(version):
        raise ManifestError("manifest version is invalid")
    target = manifest.get("target")
    if not isinstance(target, dict):
        raise ManifestError("manifest target must be an object")
    _require_exact_keys(target, {"os", "version", "codename", "arch", "format"}, "target")
    if (
        target.get("os") != "ubuntu"
        or not isinstance(target.get("version"), str)
        or not target["version"]
        or not isinstance(target.get("codename"), str)
        or not target["codename"]
        or target.get("arch") != "amd64"
        or target.get("format") != "wsl2-rootfs-tar"
    ):
        raise ManifestError("manifest target is invalid")
    source = manifest.get("source")
    if not isinstance(source, dict):
        raise ManifestError("manifest source must be an object")
    _require_exact_keys(source, {"droneDreamCommit"}, "source")
    source_commit = source.get("droneDreamCommit")
    if not isinstance(source_commit, str) or not SHA40.fullmatch(source_commit):
        raise ManifestError("manifest source commit is invalid")
    components = manifest.get("components")
    if not isinstance(components, dict):
        raise ManifestError("manifest components must be an object")
    for name, value in components.items():
        if (
            not isinstance(name, str)
            or not isinstance(value, str)
            or not value.strip()
            or len(value) > 128
            or any(ord(character) < 32 or 127 <= ord(character) <= 159 for character in value)
        ):
            raise ManifestError("manifest components must be safe string values")
    for component in ("backend", "px4", "gazebo"):
        value = components.get(component)
        if not isinstance(value, str):
            raise ManifestError(f"manifest component {component} is invalid")
    component_details = manifest.get("componentDetails")
    if not isinstance(component_details, dict):
        raise ManifestError("manifest componentDetails must be an object")
    for component in (
        "ubuntu",
        "px4",
        "gazebo",
        "backend",
        "worker",
        "valkey",
        "python",
    ):
        if not isinstance(component_details.get(component), dict):
            raise ManifestError(f"manifest componentDetails.{component} must be an object")
    for component in ("mavsdk", "pyulog"):
        if not isinstance(component_details.get(component), dict):
            raise ManifestError(f"manifest componentDetails.{component} must be an object")
    px4_commit = component_details["px4"].get("commit")
    valkey_commit = component_details["valkey"].get("commit")
    backend_commit = component_details["backend"].get("commit")
    worker_commit = component_details["worker"].get("commit")
    if not isinstance(px4_commit, str) or not SHA40.fullmatch(px4_commit):
        raise ManifestError("manifest PX4 commit is invalid")
    if not isinstance(valkey_commit, str) or not SHA40.fullmatch(valkey_commit):
        raise ManifestError("manifest Valkey commit is invalid")
    if backend_commit != source_commit or worker_commit != source_commit:
        raise ManifestError("manifest backend/worker commits must match the source commit")
    locks = manifest.get("locks")
    if not isinstance(locks, dict):
        raise ManifestError("manifest locks must be an object")
    _require_exact_keys(locks, {"pinsSha256", "pythonRequirementsSha256"}, "locks")
    if any(not isinstance(value, str) or not SHA256.fullmatch(value) for value in locks.values()):
        raise ManifestError("manifest lock hashes are invalid")
    artifact = manifest.get("artifact")
    if artifact is not None and not isinstance(artifact, dict):
        raise ManifestError("manifest artifact must be an object or null")
    smoke = manifest.get("smokeTests")
    smoke_keys = ("px4Sitl", "gazebo", "parameterReadback")
    if not isinstance(smoke, dict) or any(
        not isinstance(smoke.get(key), bool) for key in smoke_keys
    ):
        raise ManifestError("manifest smokeTests is invalid")
    if set(smoke) != set(smoke_keys):
        raise ManifestError("manifest smokeTests contains unsupported fields")
    passed = all(smoke[key] for key in smoke_keys)
    if any(smoke[key] for key in smoke_keys) and not passed:
        raise ManifestError("desktop smoke flags must be promoted atomically")
    report = manifest.get("smokeReport")
    if passed:
        if not isinstance(report, dict) or report.get("passed") is not True:
            raise ManifestError("passed smoke flags require a successful smokeReport")
        checks = report.get("checks")
        if not isinstance(checks, list) or not checks:
            raise ManifestError("manifest smoke report checks must be an array")
        names: list[str] = []
        for item in checks:
            if not isinstance(item, dict) or item.get("passed") is not True:
                raise ManifestError("manifest smoke report contains an unsuccessful check")
            name = item.get("name")
            duration = item.get("durationSeconds")
            if not isinstance(name, str) or not name or len(name) > 128:
                raise ManifestError("manifest smoke report contains an invalid check name")
            if type(duration) is not int or duration < 0:
                raise ManifestError("manifest smoke report contains an invalid check duration")
            names.append(name)
        if len(names) != len(set(names)):
            raise ManifestError("manifest smoke report contains duplicate check names")
        passed_names = set(names)
        missing = REQUIRED_SMOKE_CHECKS - passed_names
        if missing:
            raise ManifestError("passed smoke status is missing successful required checks")
        if report.get("mode") != "runtime-image" or report.get("runtimeId") != runtime_id:
            raise ManifestError("manifest smoke report identity is invalid")
        image_id = report.get("imageId")
        if (
            not isinstance(image_id, str)
            or not image_id
            or len(image_id) > 256
            or any(ord(character) < 32 for character in image_id)
        ):
            raise ManifestError("manifest smoke report imageId is invalid")
        _validate_timestamp(report.get("completedAt"), "manifest smoke completedAt")
    elif report is not None:
        raise ManifestError("unpromoted manifest cannot contain a smokeReport")
    if require_smoke_passed and not passed:
        raise ManifestError("release export requires actual successful smoke tests")


def promote_smoke(manifest_path: Path, report_path: Path, output: Path) -> None:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    validate_manifest(manifest)
    if all(manifest["smokeTests"].values()):
        raise ManifestError("manifest was already promoted")
    report = json.loads(report_path.read_text(encoding="utf-8"))
    if report.get("mode") != "runtime-image":
        raise ManifestError("smoke report must come from the runtime-image harness")
    if report.get("runtimeId") != manifest["runtimeId"]:
        raise ManifestError("smoke report runtimeId does not match the manifest")
    checks = report.get("checks")
    if not isinstance(checks, list) or report.get("passed") is not True:
        raise ManifestError("smoke report did not pass")
    names: list[str] = []
    for item in checks:
        if not isinstance(item, dict) or item.get("passed") is not True:
            raise ManifestError("smoke report contains an unsuccessful check")
        name = item.get("name")
        duration = item.get("durationSeconds")
        if not isinstance(name, str) or not name or len(name) > 128:
            raise ManifestError("smoke report contains an invalid check name")
        if type(duration) is not int or duration < 0:
            raise ManifestError("smoke report contains an invalid check duration")
        names.append(name)
    if len(names) != len(set(names)):
        raise ManifestError("smoke report contains duplicate check names")
    passed_names = set(names)
    missing = REQUIRED_SMOKE_CHECKS - passed_names
    if missing:
        raise ManifestError(f"smoke report is missing passed checks: {', '.join(sorted(missing))}")
    image_id = report.get("imageId")
    if (
        not isinstance(image_id, str)
        or not image_id
        or len(image_id) > 256
        or any(ord(character) < 32 for character in image_id)
    ):
        raise ManifestError("smoke report imageId is invalid")
    completed_at = _validate_timestamp(report.get("completedAt"), "smoke completedAt")
    manifest["smokeTests"] = {
        "px4Sitl": True,
        "gazebo": True,
        "parameterReadback": True,
    }
    manifest["smokeReport"] = {
        **report,
        "passed": True,
        "completedAt": completed_at,
        "checks": checks,
    }
    validate_manifest(manifest, require_smoke_passed=True)
    output.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    config = sub.add_parser("validate-config")
    config.add_argument("--pins", type=Path, required=True)
    config.add_argument("--python-lock", type=Path, required=True)
    make = sub.add_parser("generate")
    make.add_argument("--pins", type=Path, required=True)
    make.add_argument("--python-lock", type=Path, required=True)
    make.add_argument("--source-commit", required=True)
    make.add_argument("--output", type=Path, required=True)
    check = sub.add_parser("validate")
    check.add_argument("--manifest", type=Path, required=True)
    check.add_argument("--require-smoke-passed", action="store_true")
    promote = sub.add_parser("promote-smoke")
    promote.add_argument("--manifest", type=Path, required=True)
    promote.add_argument("--report", type=Path, required=True)
    promote.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.command == "validate-config":
            pins = load_pins(args.pins)
            packages = validate_python_lock(args.python_lock)
            validate_pin_lock_versions(pins, packages)
        elif args.command == "generate":
            generate(args.pins, args.python_lock, args.source_commit, args.output)
        elif args.command == "validate":
            manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
            validate_manifest(manifest, require_smoke_passed=args.require_smoke_passed)
        else:
            promote_smoke(args.manifest, args.report, args.output)
    except (OSError, json.JSONDecodeError, ManifestError, ValueError) as exc:
        print(f"runtime manifest error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
