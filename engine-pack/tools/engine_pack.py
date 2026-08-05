#!/usr/bin/env python3
"""Build and verify deterministic DroneDream Engine Pack archives."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
from collections.abc import Iterable
from pathlib import Path, PurePosixPath
from typing import Any

ARCHIVE_FILENAME = "DroneDreamEnginePack.tar.gz"
DESCRIPTOR_FILENAME = "engine-pack-bundle.json"
MANIFEST_FILENAME = "engine-pack-manifest.json"
KIND = "dronedream-engine-pack"
SCHEMA_VERSION = 1
ENGINE_API_VERSION = 1
DEFAULT_EDITION_PROFILE = "unified-sim-lab"
FIELD_EDITION_PROFILE = "field-lightweight"
EDITION_PROFILES = {DEFAULT_EDITION_PROFILE, FIELD_EDITION_PROFILE}
RUNTIME_DISTRIBUTION_PATHS = (
    "LICENSE",
    "runtime/THIRD_PARTY_NOTICES.md",
    "distribution/capabilities/core-capabilities.v1.json",
    "distribution/editions/field.v1.json",
    "distribution/editions/lab.v1.json",
    "distribution/editions/sim.v1.json",
    "distribution/safety/edition-execution-gate.v1.json",
    "distribution/schemas/edition-execution-authorization.schema.json",
    "distribution/schemas/edition-execution-gate-policy.schema.json",
    "distribution/schemas/field-lifecycle-contract.schema.json",
    "distribution/schemas/field-prerelease-audit.schema.json",
    "distribution/tools/distribution_contract.py",
    "distribution/tools/edition_safety_contract.py",
    "distribution/tools/field_lifecycle_contract.py",
    "distribution/tools/field_prerelease_audit.py",
    "distribution/upstream-sources.v1.json",
    "distribution/vehicle-packs/amovlab-mfp450-pixhawk6c.v1.json",
    "distribution/vehicle-packs/amovlab-p450-px4.v1.json",
    "distribution/vehicle-packs/bitcraze-crazyflie-2-1-plus.v1.json",
    "distribution/vehicle-packs/holybro-qav250-pixhawk6c-mini.v1.json",
    "distribution/vehicle-packs/holybro-s500-v2-pixhawk6c.v1.json",
    "distribution/vehicle-packs/holybro-x500-v2-pixhawk6.v1.json",
    "distribution/vehicle-packs/holybro-x650-pixhawk6.v1.json",
    "distribution/vehicle-packs/px4-gazebo-x500-reference.v1.json",
    "distribution/vehicle-packs/registry.v1.json",
)
SOURCE_PATHS = (
    "backend/app",
    "backend/alembic",
    "backend/alembic.ini",
    "backend/pyproject.toml",
    "worker/drone_dream_worker",
    "worker/pyproject.toml",
    "scripts/simulators",
    *RUNTIME_DISTRIBUTION_PATHS,
)
FIELD_EXCLUDED_SOURCE_PATHS = ("backend/app/simulator", "scripts/simulators")
IGNORED_PARTS = {"__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache"}
IGNORED_SUFFIXES = {".pyc", ".pyo"}
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")


class EnginePackError(RuntimeError):
    """Raised when an Engine Pack cannot be trusted."""


def canonical_json(payload: Any) -> bytes:
    return (json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n").encode()


def write_new_file(path: Path, payload: bytes) -> None:
    """Create one delivery file without replacing an earlier build."""

    path.parent.mkdir(parents=True, exist_ok=True)
    created = False
    try:
        with path.open("xb") as handle:
            created = True
            handle.write(payload)
    except FileExistsError as exc:
        raise EnginePackError(f"refusing to replace Engine Pack output: {path}") from exc
    except Exception:
        if created:
            path.unlink(missing_ok=True)
        raise


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_pins(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise EnginePackError(f"invalid pins line: {raw!r}")
        key, value = line.split("=", 1)
        values[key] = value
    required = {
        "DRONEDREAM_RUNTIME_VERSION",
        "PYTHON_VERSION",
        "PX4_GIT_COMMIT",
        "GAZEBO_RELEASE",
        "GAZEBO_METAPACKAGE_VERSION",
    }
    missing = sorted(required - values.keys())
    if missing:
        raise EnginePackError(f"runtime pins are missing: {', '.join(missing)}")
    return values


def source_date_epoch(repository_root: Path, source_commit: str) -> int:
    if not COMMIT_RE.fullmatch(source_commit):
        raise EnginePackError("source commit must be a full lowercase Git SHA")
    configured = os.environ.get("SOURCE_DATE_EPOCH")
    if configured:
        try:
            value = int(configured)
        except ValueError as error:
            raise EnginePackError("SOURCE_DATE_EPOCH must be an integer") from error
        if value < 0:
            raise EnginePackError("SOURCE_DATE_EPOCH must not be negative")
        return value
    git = shutil.which("git")
    if git is None:
        raise EnginePackError("git is required to derive the source commit timestamp")
    result = subprocess.run(  # noqa: S603 - resolved executable and validated SHA argument.
        [git, "show", "-s", "--format=%ct", source_commit],
        cwd=repository_root,
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode:
        raise EnginePackError("unable to derive the source commit timestamp")
    try:
        return int(result.stdout.strip())
    except ValueError as error:
        raise EnginePackError("source commit timestamp was invalid") from error


def source_paths_for_profile(edition_profile: str) -> tuple[str, ...]:
    if edition_profile not in EDITION_PROFILES:
        raise EnginePackError(f"unsupported Engine Pack edition profile: {edition_profile}")
    if edition_profile == FIELD_EDITION_PROFILE:
        return tuple(
            path for path in SOURCE_PATHS if path not in FIELD_EXCLUDED_SOURCE_PATHS
        )
    return SOURCE_PATHS


def is_excluded_for_profile(path: str, edition_profile: str) -> bool:
    if edition_profile != FIELD_EDITION_PROFILE:
        return False
    return any(
        path == excluded or path.startswith(f"{excluded}/")
        for excluded in FIELD_EXCLUDED_SOURCE_PATHS
    )


def production_files(
    repository_root: Path,
    *,
    edition_profile: str = DEFAULT_EDITION_PROFILE,
) -> list[tuple[str, Path]]:
    collected: dict[str, Path] = {}
    for relative in source_paths_for_profile(edition_profile):
        candidate = repository_root / relative
        if not candidate.exists():
            raise EnginePackError(f"required Engine Pack source is missing: {relative}")
        paths: Iterable[Path] = candidate.rglob("*") if candidate.is_dir() else (candidate,)
        for path in paths:
            if path.is_dir():
                continue
            if path.is_symlink() or not path.is_file():
                raise EnginePackError(f"Engine Pack source is not an ordinary file: {path}")
            inner = path.relative_to(repository_root)
            if any(part in IGNORED_PARTS for part in inner.parts):
                continue
            if path.suffix.lower() in IGNORED_SUFFIXES:
                continue
            posix = inner.as_posix()
            if is_excluded_for_profile(posix, edition_profile):
                continue
            if posix in collected:
                raise EnginePackError(f"duplicate Engine Pack path: {posix}")
            collected[posix] = path
    return sorted(collected.items())


def file_records(files: list[tuple[str, Path]]) -> list[dict[str, Any]]:
    return [
        {"path": path, "sizeBytes": source.stat().st_size, "sha256": sha256_file(source)}
        for path, source in files
    ]


def payload_identity(records: list[dict[str, Any]]) -> str:
    identity = hashlib.sha256()
    for record in records:
        identity.update(record["path"].encode())
        identity.update(b"\0")
        identity.update(str(record["sizeBytes"]).encode())
        identity.update(b"\0")
        identity.update(record["sha256"].encode())
        identity.update(b"\n")
    return identity.hexdigest()


def manifest_identity(
    source: dict[str, Any],
    edition_profile: dict[str, Any],
    compatibility: dict[str, Any],
    records: list[dict[str, Any]],
) -> str:
    return sha256_bytes(
        canonical_json(
            {
                "engineApiVersion": ENGINE_API_VERSION,
                "source": source,
                "editionProfile": edition_profile,
                "runtimeCompatibility": compatibility,
                "payloadSha256": payload_identity(records),
                "files": records,
            }
        )
    )


def build_manifest(
    repository_root: Path,
    source_commit: str,
    epoch: int,
    records: list[dict[str, Any]],
    *,
    edition_profile_id: str = DEFAULT_EDITION_PROFILE,
) -> dict[str, Any]:
    if not COMMIT_RE.fullmatch(source_commit):
        raise EnginePackError("source commit must be a full lowercase Git SHA")
    pins = read_pins(repository_root / "runtime" / "pins.env")
    lock = repository_root / "runtime" / "locks" / "python-requirements.lock"
    source = {"gitCommit": source_commit, "sourceDateEpoch": epoch}
    edition_profile = {
        "profileId": edition_profile_id,
        "includesLargeSimulator": edition_profile_id != FIELD_EDITION_PROFILE,
        "excludedSourcePaths": list(FIELD_EXCLUDED_SOURCE_PATHS)
        if edition_profile_id == FIELD_EDITION_PROFILE
        else [],
    }
    compatibility = {
        # This is the stable product/distribution identity. The Runtime
        # manifest's `runtimeId` is a build-specific UUID and must not be used
        # as an Engine Pack compatibility key.
        "runtimeProductId": "DroneDreamRuntime",
        "runtimeVersion": pins["DRONEDREAM_RUNTIME_VERSION"],
        "pythonVersion": pins["PYTHON_VERSION"],
        "px4Commit": pins["PX4_GIT_COMMIT"],
        "gazeboVersion": f"{pins['GAZEBO_RELEASE']}@{pins['GAZEBO_METAPACKAGE_VERSION']}",
        "dependencyLockSha256": sha256_file(lock),
    }
    return {
        "schemaVersion": SCHEMA_VERSION,
        "kind": KIND,
        "packId": f"sha256:{manifest_identity(source, edition_profile, compatibility, records)}",
        "engineApiVersion": ENGINE_API_VERSION,
        "source": source,
        "editionProfile": edition_profile,
        "runtimeCompatibility": compatibility,
        "files": records,
    }


def _tar_info(name: str, payload: bytes, epoch: int) -> tarfile.TarInfo:
    info = tarfile.TarInfo(name)
    info.size = len(payload)
    info.mode = 0o644
    info.uid = 0
    info.gid = 0
    info.uname = ""
    info.gname = ""
    info.mtime = epoch
    return info


def write_archive(
    archive_path: Path,
    manifest_bytes: bytes,
    files: list[tuple[str, Path]],
    epoch: int,
) -> None:
    archive_path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{archive_path.name}.",
        suffix=".tmp",
        dir=archive_path.parent,
    )
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        with (
            temporary.open("wb") as raw,
            gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as compressed,
            tarfile.open(
                fileobj=compressed, mode="w", format=tarfile.PAX_FORMAT
            ) as archive,
        ):
            archive.addfile(
                _tar_info(MANIFEST_FILENAME, manifest_bytes, epoch),
                io.BytesIO(manifest_bytes),
            )
            for relative, source in files:
                payload = source.read_bytes()
                archive.addfile(
                    _tar_info(f"payload/{relative}", payload, epoch),
                    io.BytesIO(payload),
                )
        try:
            os.link(temporary, archive_path)
        except FileExistsError as exc:
            raise EnginePackError(
                f"refusing to replace Engine Pack output: {archive_path}"
            ) from exc
    finally:
        temporary.unlink(missing_ok=True)


def build(args: argparse.Namespace) -> int:
    root = Path(args.repository_root).resolve()
    output = Path(args.output_directory).resolve()
    edition_profile = args.edition_profile
    if edition_profile not in EDITION_PROFILES:
        raise EnginePackError(f"unsupported Engine Pack edition profile: {edition_profile}")
    if not root.is_dir():
        raise EnginePackError("repository root does not exist")
    if output.exists() and any(output.iterdir()):
        raise EnginePackError(f"output directory must be absent or empty: {output}")
    output.mkdir(parents=True, exist_ok=True)
    files = production_files(root, edition_profile=edition_profile)
    records = file_records(files)
    epoch = source_date_epoch(root, args.source_commit)
    manifest = build_manifest(
        root,
        args.source_commit,
        epoch,
        records,
        edition_profile_id=edition_profile,
    )
    manifest_bytes = canonical_json(manifest)
    manifest_path = output / MANIFEST_FILENAME
    archive_path = output / ARCHIVE_FILENAME
    created: list[Path] = []
    try:
        write_new_file(manifest_path, manifest_bytes)
        created.append(manifest_path)
        write_archive(archive_path, manifest_bytes, files, epoch)
        created.append(archive_path)
        descriptor = {
            "schemaVersion": 1,
            "kind": "dronedream-engine-pack-bundle",
            "packId": manifest["packId"],
            "sourceCommit": args.source_commit,
            "archive": {
                "filename": ARCHIVE_FILENAME,
                "sizeBytes": archive_path.stat().st_size,
                "sha256": sha256_file(archive_path),
            },
            "manifest": {
                "filename": MANIFEST_FILENAME,
                "sizeBytes": len(manifest_bytes),
                "sha256": sha256_bytes(manifest_bytes),
            },
        }
        descriptor_path = output / DESCRIPTOR_FILENAME
        write_new_file(descriptor_path, canonical_json(descriptor))
        created.append(descriptor_path)
    except Exception:
        for created_path in reversed(created):
            created_path.unlink(missing_ok=True)
        raise
    print(json.dumps(descriptor, sort_keys=True))
    return 0


def _safe_member_path(name: str) -> PurePosixPath:
    path = PurePosixPath(name)
    if path.is_absolute() or ".." in path.parts or not path.parts:
        raise EnginePackError(f"unsafe archive member: {name}")
    return path


def validate_manifest(manifest: Any) -> dict[str, Any]:
    if not isinstance(manifest, dict):
        raise EnginePackError("Engine Pack manifest is not an object")
    if set(manifest) != {
        "schemaVersion",
        "kind",
        "packId",
        "engineApiVersion",
        "source",
        "editionProfile",
        "runtimeCompatibility",
        "files",
    }:
        raise EnginePackError("Engine Pack manifest fields do not match schema v1")
    if manifest["schemaVersion"] != 1 or manifest["kind"] != KIND:
        raise EnginePackError("Engine Pack manifest identity is invalid")
    if manifest["engineApiVersion"] != ENGINE_API_VERSION:
        raise EnginePackError("Engine Pack API version is unsupported")
    source = manifest["source"]
    if not isinstance(source, dict) or set(source) != {"gitCommit", "sourceDateEpoch"}:
        raise EnginePackError("Engine Pack source identity is invalid")
    if not isinstance(source["gitCommit"], str) or not COMMIT_RE.fullmatch(source["gitCommit"]):
        raise EnginePackError("Engine Pack source commit is invalid")
    if type(source["sourceDateEpoch"]) is not int or source["sourceDateEpoch"] < 0:
        raise EnginePackError("Engine Pack source timestamp is invalid")
    edition_profile = manifest["editionProfile"]
    if not isinstance(edition_profile, dict) or set(edition_profile) != {
        "profileId",
        "includesLargeSimulator",
        "excludedSourcePaths",
    }:
        raise EnginePackError("Engine Pack edition profile identity is invalid")
    profile_id = edition_profile["profileId"]
    if profile_id not in EDITION_PROFILES:
        raise EnginePackError("Engine Pack edition profile is unsupported")
    if type(edition_profile["includesLargeSimulator"]) is not bool:
        raise EnginePackError("Engine Pack simulator inclusion flag is invalid")
    excluded_paths = edition_profile["excludedSourcePaths"]
    if (
        not isinstance(excluded_paths, list)
        or any(not isinstance(path, str) for path in excluded_paths)
        or len(excluded_paths) != len(set(excluded_paths))
    ):
        raise EnginePackError("Engine Pack excluded source paths are invalid")
    if profile_id == FIELD_EDITION_PROFILE:
        if edition_profile["includesLargeSimulator"] is not False or tuple(
            excluded_paths
        ) != FIELD_EXCLUDED_SOURCE_PATHS:
            raise EnginePackError("Field Engine Pack profile does not exclude simulator payloads")
    elif edition_profile["includesLargeSimulator"] is not True or excluded_paths:
        raise EnginePackError("default Engine Pack profile drifted")
    compatibility = manifest["runtimeCompatibility"]
    compatibility_keys = {
        "runtimeProductId",
        "runtimeVersion",
        "pythonVersion",
        "px4Commit",
        "gazeboVersion",
        "dependencyLockSha256",
    }
    if not isinstance(compatibility, dict) or set(compatibility) != compatibility_keys:
        raise EnginePackError("Engine Pack Runtime compatibility identity is invalid")
    if any(
        not isinstance(compatibility[key], str) or not compatibility[key]
        for key in compatibility_keys
    ):
        raise EnginePackError("Engine Pack Runtime compatibility values are invalid")
    if not COMMIT_RE.fullmatch(compatibility["px4Commit"]):
        raise EnginePackError("Engine Pack PX4 compatibility commit is invalid")
    if not SHA256_RE.fullmatch(compatibility["dependencyLockSha256"]):
        raise EnginePackError("Engine Pack dependency lock identity is invalid")
    if not isinstance(manifest["files"], list) or not manifest["files"]:
        raise EnginePackError("Engine Pack file list is empty")
    paths: list[str] = []
    for record in manifest["files"]:
        if not isinstance(record, dict) or set(record) != {"path", "sizeBytes", "sha256"}:
            raise EnginePackError("Engine Pack file record is invalid")
        if not isinstance(record["path"], str) or not isinstance(record["sha256"], str):
            raise EnginePackError("Engine Pack file identity is invalid")
        path = _safe_member_path(record["path"])
        if str(path) != record["path"] or not SHA256_RE.fullmatch(record["sha256"]):
            raise EnginePackError("Engine Pack file identity is invalid")
        if not isinstance(record["sizeBytes"], int) or record["sizeBytes"] < 0:
            raise EnginePackError("Engine Pack file size is invalid")
        paths.append(record["path"])
    if paths != sorted(set(paths)):
        raise EnginePackError("Engine Pack files are not unique and sorted")
    expected_pack_id = "sha256:" + manifest_identity(
        manifest["source"],
        manifest["editionProfile"],
        manifest["runtimeCompatibility"],
        manifest["files"],
    )
    if manifest["packId"] != expected_pack_id:
        raise EnginePackError("Engine Pack payload identity does not match its file list")
    return manifest


def verified_bundle(
    descriptor_path: Path, archive_path: Path
) -> tuple[dict[str, Any], dict[str, Any]]:
    if descriptor_path.is_symlink() or not descriptor_path.is_file():
        raise EnginePackError("Engine Pack descriptor must be a regular non-symlink file")
    if archive_path.is_symlink() or not archive_path.is_file():
        raise EnginePackError("Engine Pack archive must be a regular non-symlink file")
    descriptor_bytes = descriptor_path.read_bytes()
    descriptor = json.loads(descriptor_bytes)
    if not isinstance(descriptor, dict) or set(descriptor) != {
        "schemaVersion",
        "kind",
        "packId",
        "sourceCommit",
        "archive",
        "manifest",
    }:
        raise EnginePackError("Engine Pack descriptor fields do not match schema v1")
    if (
        descriptor.get("schemaVersion") != 1
        or descriptor.get("kind") != "dronedream-engine-pack-bundle"
    ):
        raise EnginePackError("Engine Pack descriptor identity is invalid")
    if descriptor_bytes != canonical_json(descriptor):
        raise EnginePackError("Engine Pack descriptor is not canonical JSON")
    if (
        not isinstance(descriptor.get("packId"), str)
        or not descriptor["packId"].startswith("sha256:")
        or not SHA256_RE.fullmatch(descriptor["packId"].removeprefix("sha256:"))
    ):
        raise EnginePackError("Engine Pack descriptor pack ID is invalid")
    if not isinstance(descriptor.get("sourceCommit"), str) or not COMMIT_RE.fullmatch(
        descriptor["sourceCommit"]
    ):
        raise EnginePackError("Engine Pack descriptor source commit is invalid")
    expected_archive = descriptor.get("archive")
    if not isinstance(expected_archive, dict) or set(expected_archive) != {
        "filename",
        "sizeBytes",
        "sha256",
    }:
        raise EnginePackError("Engine Pack archive descriptor is missing")
    if (
        expected_archive.get("filename") != ARCHIVE_FILENAME
        or archive_path.name != ARCHIVE_FILENAME
    ):
        raise EnginePackError("Engine Pack archive filename does not match")
    if type(expected_archive.get("sizeBytes")) is not int or expected_archive["sizeBytes"] < 0:
        raise EnginePackError("Engine Pack archive size is invalid")
    if expected_archive["sizeBytes"] != archive_path.stat().st_size:
        raise EnginePackError("Engine Pack archive size does not match")
    if not isinstance(expected_archive.get("sha256"), str) or not SHA256_RE.fullmatch(
        expected_archive["sha256"]
    ):
        raise EnginePackError("Engine Pack archive hash is invalid")
    if expected_archive["sha256"] != sha256_file(archive_path):
        raise EnginePackError("Engine Pack archive hash does not match")
    expected_manifest = descriptor.get("manifest")
    if not isinstance(expected_manifest, dict) or set(expected_manifest) != {
        "filename",
        "sizeBytes",
        "sha256",
    }:
        raise EnginePackError("Engine Pack manifest descriptor is missing")
    if expected_manifest.get("filename") != MANIFEST_FILENAME:
        raise EnginePackError("Engine Pack manifest filename does not match")
    if type(expected_manifest.get("sizeBytes")) is not int or expected_manifest["sizeBytes"] < 0:
        raise EnginePackError("Engine Pack manifest size is invalid")
    if not isinstance(expected_manifest.get("sha256"), str) or not SHA256_RE.fullmatch(
        expected_manifest["sha256"]
    ):
        raise EnginePackError("Engine Pack manifest hash is invalid")
    manifest_path = descriptor_path.parent / MANIFEST_FILENAME
    if manifest_path.is_symlink() or not manifest_path.is_file():
        raise EnginePackError("Engine Pack manifest must be a regular non-symlink file")
    manifest_sidecar = manifest_path.read_bytes()
    if len(manifest_sidecar) != expected_manifest["sizeBytes"]:
        raise EnginePackError("Engine Pack manifest size does not match")
    if sha256_bytes(manifest_sidecar) != expected_manifest["sha256"]:
        raise EnginePackError("Engine Pack manifest hash does not match")
    with tarfile.open(archive_path, mode="r:gz") as archive:
        members = archive.getmembers()
        names = [str(_safe_member_path(member.name)) for member in members]
        if names != sorted(names) or len(names) != len(set(names)):
            raise EnginePackError("Engine Pack archive members are not unique and sorted")
        if any(not member.isfile() for member in members):
            raise EnginePackError("Engine Pack archive contains a non-file member")
        manifest_member = archive.getmember(MANIFEST_FILENAME)
        extracted = archive.extractfile(manifest_member)
        if extracted is None:
            raise EnginePackError("Engine Pack manifest cannot be read")
        manifest_bytes = extracted.read()
        manifest = validate_manifest(json.loads(manifest_bytes))
        if manifest_bytes != canonical_json(manifest):
            raise EnginePackError("Engine Pack manifest is not canonical JSON")
        if manifest_bytes != manifest_sidecar:
            raise EnginePackError("Engine Pack embedded and sidecar manifests disagree")
        if expected_manifest["sha256"] != sha256_bytes(manifest_bytes):
            raise EnginePackError("Engine Pack manifest hash does not match")
        records = {record["path"]: record for record in manifest["files"]}
        payload_names = [
            name.removeprefix("payload/") for name in names if name.startswith("payload/")
        ]
        if payload_names != list(records):
            raise EnginePackError("Engine Pack archive payload does not match its manifest")
        for inner_path, record in records.items():
            member = archive.getmember(f"payload/{inner_path}")
            source = archive.extractfile(member)
            if source is None:
                raise EnginePackError(f"Engine Pack payload is unreadable: {inner_path}")
            payload = source.read()
            if len(payload) != record["sizeBytes"] or sha256_bytes(payload) != record["sha256"]:
                raise EnginePackError(f"Engine Pack payload failed verification: {inner_path}")
    if descriptor["packId"] != manifest["packId"]:
        raise EnginePackError("Engine Pack descriptor and manifest disagree")
    if descriptor["sourceCommit"] != manifest["source"]["gitCommit"]:
        raise EnginePackError("Engine Pack descriptor and source commit disagree")
    return descriptor, manifest


def verify(args: argparse.Namespace) -> int:
    descriptor_path = Path(args.descriptor).resolve()
    archive_path = Path(args.archive).resolve()
    _descriptor, manifest = verified_bundle(descriptor_path, archive_path)
    print(json.dumps({"packId": manifest["packId"], "verified": True}, sort_keys=True))
    return 0


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description=__doc__)
    commands = root.add_subparsers(dest="command", required=True)
    build_parser = commands.add_parser("build")
    build_parser.add_argument("--repository-root", required=True)
    build_parser.add_argument("--output-directory", required=True)
    build_parser.add_argument("--source-commit", required=True)
    build_parser.add_argument(
        "--edition-profile",
        choices=sorted(EDITION_PROFILES),
        default=DEFAULT_EDITION_PROFILE,
    )
    build_parser.set_defaults(handler=build)
    verify_parser = commands.add_parser("verify")
    verify_parser.add_argument("--descriptor", required=True)
    verify_parser.add_argument("--archive", required=True)
    verify_parser.set_defaults(handler=verify)
    return root


def main() -> int:
    args = parser().parse_args()
    try:
        return args.handler(args)
    except (EnginePackError, OSError, json.JSONDecodeError, tarfile.TarError) as error:
        print(f"engine pack error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
