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
import subprocess
import tarfile
import tempfile
from pathlib import Path, PurePosixPath
from typing import Any, Iterable

ARCHIVE_FILENAME = "DroneDreamEnginePack.tar.gz"
DESCRIPTOR_FILENAME = "engine-pack-bundle.json"
MANIFEST_FILENAME = "engine-pack-manifest.json"
KIND = "dronedream-engine-pack"
SCHEMA_VERSION = 1
ENGINE_API_VERSION = 1
SOURCE_PATHS = (
    "backend/app",
    "backend/alembic",
    "backend/alembic.ini",
    "backend/pyproject.toml",
    "worker/drone_dream_worker",
    "worker/pyproject.toml",
    "scripts/simulators",
)
IGNORED_PARTS = {"__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache"}
IGNORED_SUFFIXES = {".pyc", ".pyo"}
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")


class EnginePackError(RuntimeError):
    """Raised when an Engine Pack cannot be trusted."""


def canonical_json(payload: Any) -> bytes:
    return (json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n").encode()


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
    configured = os.environ.get("SOURCE_DATE_EPOCH")
    if configured:
        try:
            value = int(configured)
        except ValueError as error:
            raise EnginePackError("SOURCE_DATE_EPOCH must be an integer") from error
        if value < 0:
            raise EnginePackError("SOURCE_DATE_EPOCH must not be negative")
        return value
    result = subprocess.run(
        ["git", "show", "-s", "--format=%ct", source_commit],
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


def production_files(repository_root: Path) -> list[tuple[str, Path]]:
    collected: dict[str, Path] = {}
    for relative in SOURCE_PATHS:
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
    compatibility: dict[str, Any],
    records: list[dict[str, Any]],
) -> str:
    return sha256_bytes(
        canonical_json(
            {
                "engineApiVersion": ENGINE_API_VERSION,
                "source": source,
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
) -> dict[str, Any]:
    if not COMMIT_RE.fullmatch(source_commit):
        raise EnginePackError("source commit must be a full lowercase Git SHA")
    pins = read_pins(repository_root / "runtime" / "pins.env")
    lock = repository_root / "runtime" / "locks" / "python-requirements.lock"
    source = {"gitCommit": source_commit, "sourceDateEpoch": epoch}
    compatibility = {
        "runtimeId": "DroneDreamRuntime",
        "runtimeVersion": pins["DRONEDREAM_RUNTIME_VERSION"],
        "pythonVersion": pins["PYTHON_VERSION"],
        "px4Commit": pins["PX4_GIT_COMMIT"],
        "gazeboVersion": f"{pins['GAZEBO_RELEASE']}@{pins['GAZEBO_METAPACKAGE_VERSION']}",
        "dependencyLockSha256": sha256_file(lock),
    }
    return {
        "schemaVersion": SCHEMA_VERSION,
        "kind": KIND,
        "packId": f"sha256:{manifest_identity(source, compatibility, records)}",
        "engineApiVersion": ENGINE_API_VERSION,
        "source": source,
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
    temporary = archive_path.with_suffix(archive_path.suffix + ".tmp")
    temporary.unlink(missing_ok=True)
    try:
        with temporary.open("wb") as raw:
            with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as compressed:
                with tarfile.open(fileobj=compressed, mode="w", format=tarfile.PAX_FORMAT) as archive:
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
        os.replace(temporary, archive_path)
    finally:
        temporary.unlink(missing_ok=True)


def build(args: argparse.Namespace) -> int:
    root = Path(args.repository_root).resolve()
    output = Path(args.output_directory).resolve()
    if not root.is_dir():
        raise EnginePackError("repository root does not exist")
    output.mkdir(parents=True, exist_ok=True)
    files = production_files(root)
    records = file_records(files)
    epoch = source_date_epoch(root, args.source_commit)
    manifest = build_manifest(root, args.source_commit, epoch, records)
    manifest_bytes = canonical_json(manifest)
    manifest_path = output / MANIFEST_FILENAME
    archive_path = output / ARCHIVE_FILENAME
    manifest_path.write_bytes(manifest_bytes)
    write_archive(archive_path, manifest_bytes, files, epoch)
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
    (output / DESCRIPTOR_FILENAME).write_bytes(canonical_json(descriptor))
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
        "runtimeCompatibility",
        "files",
    }:
        raise EnginePackError("Engine Pack manifest fields do not match schema v1")
    if manifest["schemaVersion"] != 1 or manifest["kind"] != KIND:
        raise EnginePackError("Engine Pack manifest identity is invalid")
    if manifest["engineApiVersion"] != ENGINE_API_VERSION:
        raise EnginePackError("Engine Pack API version is unsupported")
    if not isinstance(manifest["files"], list) or not manifest["files"]:
        raise EnginePackError("Engine Pack file list is empty")
    paths: list[str] = []
    for record in manifest["files"]:
        if not isinstance(record, dict) or set(record) != {"path", "sizeBytes", "sha256"}:
            raise EnginePackError("Engine Pack file record is invalid")
        path = _safe_member_path(record["path"])
        if str(path) != record["path"] or not SHA256_RE.fullmatch(record["sha256"]):
            raise EnginePackError("Engine Pack file identity is invalid")
        if not isinstance(record["sizeBytes"], int) or record["sizeBytes"] < 0:
            raise EnginePackError("Engine Pack file size is invalid")
        paths.append(record["path"])
    if paths != sorted(set(paths)):
        raise EnginePackError("Engine Pack files are not unique and sorted")
    expected_pack_id = "sha256:" + manifest_identity(
        manifest["source"], manifest["runtimeCompatibility"], manifest["files"]
    )
    if manifest["packId"] != expected_pack_id:
        raise EnginePackError("Engine Pack payload identity does not match its file list")
    return manifest


def verified_bundle(descriptor_path: Path, archive_path: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    descriptor = json.loads(descriptor_path.read_text(encoding="utf-8"))
    if descriptor.get("schemaVersion") != 1 or descriptor.get("kind") != "dronedream-engine-pack-bundle":
        raise EnginePackError("Engine Pack descriptor identity is invalid")
    expected_archive = descriptor.get("archive")
    if not isinstance(expected_archive, dict):
        raise EnginePackError("Engine Pack archive descriptor is missing")
    if expected_archive.get("filename") != archive_path.name:
        raise EnginePackError("Engine Pack archive filename does not match")
    if expected_archive.get("sizeBytes") != archive_path.stat().st_size:
        raise EnginePackError("Engine Pack archive size does not match")
    if expected_archive.get("sha256") != sha256_file(archive_path):
        raise EnginePackError("Engine Pack archive hash does not match")
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
        expected_manifest = descriptor.get("manifest")
        if not isinstance(expected_manifest, dict):
            raise EnginePackError("Engine Pack manifest descriptor is missing")
        if expected_manifest.get("sha256") != sha256_bytes(manifest_bytes):
            raise EnginePackError("Engine Pack manifest hash does not match")
        records = {record["path"]: record for record in manifest["files"]}
        payload_names = [name.removeprefix("payload/") for name in names if name.startswith("payload/")]
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
    if descriptor.get("packId") != manifest["packId"]:
        raise EnginePackError("Engine Pack descriptor and manifest disagree")
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
        print(f"engine pack error: {error}", file=os.sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
