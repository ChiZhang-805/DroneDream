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
    "PX4_GIT_COMMIT",
    "GAZEBO_RELEASE",
    "GAZEBO_METAPACKAGE_VERSION",
    "GAZEBO_APT_KEY_SHA256",
    "VALKEY_VERSION",
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
EXACT_REQUIREMENT = re.compile(
    r"^([A-Za-z0-9][A-Za-z0-9._-]*)==([A-Za-z0-9][A-Za-z0-9.!+_-]*)$"
)


class ManifestError(ValueError):
    pass


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
        raise ManifestError(
            "Ubuntu image digests must be full lowercase SHA-256 values"
        )
    if not SHA256.fullmatch(pins["GAZEBO_APT_KEY_SHA256"]):
        raise ManifestError("GAZEBO_APT_KEY_SHA256 must be a full lowercase SHA-256")
    for key in ("PX4_GIT_COMMIT", "VALKEY_GIT_COMMIT"):
        if not SHA40.fullmatch(pins[key]):
            raise ManifestError(f"{key} must be a full lowercase Git SHA")
    for key in ("DRONEDREAM_RUNTIME_VERSION", "BACKEND_VERSION", "WORKER_VERSION"):
        if not SEMVER.fullmatch(pins[key]):
            raise ManifestError(f"{key} must be semantic x.y.z")
    return pins


def validate_python_lock(path: Path) -> None:
    packages: set[str] = set()
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        match = EXACT_REQUIREMENT.fullmatch(stripped)
        if match is None:
            raise ManifestError(
                f"{path}:{number}: requirement must use one exact == pin"
            )
        name, version = match.groups()
        normalized = name.lower().replace("_", "-")
        if not name or not version or normalized in packages:
            raise ManifestError(f"{path}:{number}: invalid or duplicate requirement")
        packages.add(normalized)
    for required in ("fastapi", "drone-dream-backend", "mavsdk"):
        if required == "drone-dream-backend":
            continue  # Installed from the pinned DroneDream source commit with --no-deps.
        if required not in packages:
            raise ManifestError(f"python lock is missing {required}")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def generate(
    pins_path: Path, lock_path: Path, source_commit: str, output: Path
) -> dict:
    pins = load_pins(pins_path)
    validate_python_lock(lock_path)
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
        "runtimeId": str(
            uuid.uuid5(uuid.NAMESPACE_URL, "https://dronedream/runtime/" + identity)
        ),
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
    output.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return manifest


def validate_manifest(manifest: dict, *, require_smoke_passed: bool = False) -> None:
    if manifest.get("schemaVersion") != SCHEMA_VERSION:
        raise ManifestError("unsupported runtime manifest schema")
    runtime_id = str(manifest.get("runtimeId"))
    parsed_runtime_id = uuid.UUID(runtime_id)
    if str(parsed_runtime_id) != runtime_id:
        raise ManifestError("manifest runtimeId must be a canonical lowercase UUID")
    version = manifest.get("version")
    if not isinstance(version, str) or not SEMVER.fullmatch(version):
        raise ManifestError("manifest version is invalid")
    source_commit = manifest.get("source", {}).get("droneDreamCommit")
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
            or any(
                ord(character) < 32 or 127 <= ord(character) <= 159
                for character in value
            )
        ):
            raise ManifestError("manifest components must be safe string values")
    for component in ("backend", "px4", "gazebo"):
        value = components.get(component)
        if not isinstance(value, str):
            raise ManifestError(f"manifest component {component} is invalid")
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
        if not isinstance(checks, list):
            raise ManifestError("manifest smoke report checks must be an array")
        if any(
            not isinstance(item, dict) or item.get("passed") is not True
            for item in checks
        ):
            raise ManifestError("manifest smoke report contains an unsuccessful check")
        passed_names = {
            item.get("name")
            for item in checks
            if isinstance(item, dict) and item.get("passed") is True
        }
        missing = REQUIRED_SMOKE_CHECKS - passed_names
        if missing or not report.get("completedAt"):
            raise ManifestError(
                "passed smoke status is missing successful required checks"
            )
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
    if any(
        not isinstance(item, dict) or item.get("passed") is not True for item in checks
    ):
        raise ManifestError("smoke report contains an unsuccessful check")
    passed_names = {
        item.get("name")
        for item in checks
        if isinstance(item, dict) and item.get("passed") is True
    }
    missing = REQUIRED_SMOKE_CHECKS - passed_names
    if missing:
        raise ManifestError(
            f"smoke report is missing passed checks: {', '.join(sorted(missing))}"
        )
    manifest["smokeTests"] = {
        "px4Sitl": True,
        "gazebo": True,
        "parameterReadback": True,
    }
    manifest["smokeReport"] = {
        **report,
        "passed": True,
        "completedAt": report.get("completedAt")
        or datetime.now(timezone.utc).isoformat(),
        "checks": checks,
    }
    validate_manifest(manifest, require_smoke_passed=True)
    output.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


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
            load_pins(args.pins)
            validate_python_lock(args.python_lock)
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
