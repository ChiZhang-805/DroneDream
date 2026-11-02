#!/usr/bin/env python3
"""Atomically activate a native-verified DroneDream capability or asset pack."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import shutil
import tarfile
import tempfile
import uuid
from pathlib import Path, PurePosixPath
from typing import Any

DEFAULT_PACK_ROOT = Path("/opt/dronedream/component-packs")
DEFAULT_STATE_PATH = Path("/var/lib/dronedream/component-pack-state.json")
DEFAULT_RUNTIME_MANIFEST = Path("/opt/dronedream/runtime-manifest.json")
PACK_TYPES = ("capability", "asset")
PROFILES = ("unified-sim-lab", "sim-only", "field-lightweight", "autonomy-full")


class ComponentPackInstallError(RuntimeError):
    """Raised when a pack cannot be admitted or activated safely."""


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ComponentPackInstallError(f"unable to read JSON contract: {path}") from error
    if not isinstance(value, dict):
        raise ComponentPackInstallError(f"JSON contract is not an object: {path}")
    return value


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as source:
            for block in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(block)
    except OSError as error:
        raise ComponentPackInstallError(f"unable to hash {path}") from error
    return digest.hexdigest()


def canonical_file_list_sha256(files: list[dict[str, Any]]) -> str:
    payload = json.dumps(files, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _exact_keys(value: dict[str, Any], expected: set[str], label: str) -> None:
    if set(value) != expected:
        raise ComponentPackInstallError(f"{label} fields drifted")


def validate_manifest(manifest: dict[str, Any]) -> None:
    _exact_keys(
        manifest,
        {
            "schemaVersion",
            "kind",
            "packType",
            "packName",
            "packId",
            "version",
            "releaseSequence",
            "runtimeCompatibility",
            "editionProfiles",
            "files",
        },
        "component pack manifest",
    )
    if manifest["schemaVersion"] != 1 or manifest["kind"] != "dronedream-component-pack":
        raise ComponentPackInstallError("component pack manifest identity is unsupported")
    if manifest["packType"] not in PACK_TYPES:
        raise ComponentPackInstallError("component pack type is unsupported")
    if (
        not isinstance(manifest["packName"], str)
        or not manifest["packName"].strip()
        or manifest["packName"].strip() != manifest["packName"]
    ):
        raise ComponentPackInstallError("component pack name is invalid")
    parse_version(manifest["version"])
    if not isinstance(manifest["releaseSequence"], int) or manifest["releaseSequence"] <= 0:
        raise ComponentPackInstallError("component pack release sequence is invalid")
    files = manifest["files"]
    if not isinstance(files, list) or not files:
        raise ComponentPackInstallError("component pack has no payload files")
    paths: set[str] = set()
    for record in files:
        if not isinstance(record, dict):
            raise ComponentPackInstallError("component pack file record is invalid")
        _exact_keys(record, {"path", "sizeBytes", "sha256"}, "component pack file")
        path = record["path"]
        pure = PurePosixPath(path) if isinstance(path, str) else PurePosixPath("/")
        if (
            not isinstance(path, str)
            or pure.is_absolute()
            or ".." in pure.parts
            or str(pure) != path
            or path in paths
        ):
            raise ComponentPackInstallError("component pack file path is unsafe or repeated")
        if not isinstance(record["sizeBytes"], int) or not 0 <= record["sizeBytes"] <= 2**32:
            raise ComponentPackInstallError("component pack file size is invalid")
        digest = record["sha256"]
        if (
            not isinstance(digest, str)
            or len(digest) != 64
            or any(character not in "0123456789abcdef" for character in digest)
        ):
            raise ComponentPackInstallError("component pack file digest is invalid")
        paths.add(path)
    expected_id = f"sha256:{canonical_file_list_sha256(files)}"
    if manifest["packId"] != expected_id:
        raise ComponentPackInstallError("component pack ID does not bind its payload records")

    compatibility = manifest["runtimeCompatibility"]
    if not isinstance(compatibility, dict):
        raise ComponentPackInstallError("component pack compatibility is invalid")
    _exact_keys(
        compatibility,
        {"runtimeProductId", "minimumRuntimeVersion", "engineApiVersion"},
        "component pack compatibility",
    )
    if (
        compatibility["runtimeProductId"] != "DroneDreamRuntime"
        or compatibility["engineApiVersion"] != 1
    ):
        raise ComponentPackInstallError("component pack Runtime identity is unsupported")
    parse_version(compatibility["minimumRuntimeVersion"])
    profiles = manifest["editionProfiles"]
    if (
        not isinstance(profiles, list)
        or not profiles
        or len(profiles) != len(set(profiles))
        or any(profile not in PROFILES for profile in profiles)
    ):
        raise ComponentPackInstallError("component pack edition profiles are invalid")


def parse_version(value: Any) -> tuple[int, int, int]:
    if not isinstance(value, str):
        raise ComponentPackInstallError("semantic version is invalid")
    try:
        parts = tuple(int(part) for part in value.split("."))
    except ValueError as error:
        raise ComponentPackInstallError("semantic version is invalid") from error
    if len(parts) != 3 or any(part < 0 for part in parts):
        raise ComponentPackInstallError("semantic version is invalid")
    return parts  # type: ignore[return-value]


def validate_runtime_compatibility(
    manifest: dict[str, Any], runtime: dict[str, Any], profile: str
) -> None:
    compatibility = manifest["runtimeCompatibility"]
    if runtime.get("productId") not in (None, "DroneDreamRuntime"):
        raise ComponentPackInstallError("installed Runtime product is incompatible")
    if parse_version(runtime.get("version")) < parse_version(
        compatibility["minimumRuntimeVersion"]
    ):
        raise ComponentPackInstallError("component pack requires a newer Base Runtime")
    if profile not in manifest["editionProfiles"]:
        raise ComponentPackInstallError("component pack does not support this Runtime profile")


def validate_verified_receipt(
    receipt: dict[str, Any],
    manifest_path: Path,
    archive_path: Path,
    *,
    expected_manifest_sha256: str,
    expected_archive_sha256: str,
    expected_catalog_sequence: int,
    expected_key_id: str,
) -> None:
    _exact_keys(
        receipt,
        {
            "schemaVersion",
            "kind",
            "manifestSha256",
            "archiveSha256",
            "catalogSequence",
            "keyId",
            "verifiedAt",
        },
        "verified component download receipt",
    )
    key_id = receipt["keyId"]
    if (
        receipt["schemaVersion"] != 1
        or receipt["kind"] != "dronedream-verified-component-download"
        or not isinstance(receipt["catalogSequence"], int)
        or receipt["catalogSequence"] <= 0
        or not isinstance(key_id, str)
        or not key_id.startswith("ed25519:")
    ):
        raise ComponentPackInstallError("verified component receipt identity is invalid")
    try:
        verified_at = dt.datetime.fromisoformat(receipt["verifiedAt"].replace("Z", "+00:00"))
    except (AttributeError, TypeError, ValueError) as error:
        raise ComponentPackInstallError("verified component receipt time is invalid") from error
    if verified_at.tzinfo is None:
        raise ComponentPackInstallError("verified component receipt time is not UTC-aware")
    if receipt["manifestSha256"] != sha256_file(manifest_path):
        raise ComponentPackInstallError("component manifest changed after native verification")
    if receipt["archiveSha256"] != sha256_file(archive_path):
        raise ComponentPackInstallError("component archive changed after native verification")
    if (
        receipt["manifestSha256"] != expected_manifest_sha256
        or receipt["archiveSha256"] != expected_archive_sha256
        or receipt["catalogSequence"] != expected_catalog_sequence
        or receipt["keyId"] != expected_key_id
    ):
        raise ComponentPackInstallError(
            "component receipt does not match the native trust decision"
        )


def safe_extract(archive_path: Path, destination: Path, files: list[dict[str, Any]]) -> None:
    expected = {record["path"]: record for record in files}
    try:
        with tarfile.open(archive_path, mode="r:gz") as archive:
            members: dict[str, tarfile.TarInfo] = {}
            for member in archive.getmembers():
                path = PurePosixPath(member.name)
                if path.is_absolute() or ".." in path.parts or not member.isfile():
                    raise ComponentPackInstallError("component archive contains an unsafe member")
                if not member.name.startswith("payload/"):
                    raise ComponentPackInstallError("component archive contains an unscoped member")
                relative = member.name.removeprefix("payload/")
                if relative in members:
                    raise ComponentPackInstallError("component archive contains a duplicate member")
                members[relative] = member
            if set(members) != set(expected):
                raise ComponentPackInstallError("component archive and manifest payloads differ")
            for relative in sorted(members):
                target = destination.joinpath(*PurePosixPath(relative).parts)
                target.parent.mkdir(parents=True, exist_ok=True)
                source = archive.extractfile(members[relative])
                if source is None:
                    raise ComponentPackInstallError("component archive member cannot be read")
                with target.open("xb") as output:
                    shutil.copyfileobj(source, output)
                target.chmod(0o644)
                record = expected[relative]
                if (
                    target.stat().st_size != record["sizeBytes"]
                    or sha256_file(target) != record["sha256"]
                ):
                    raise ComponentPackInstallError(
                        f"component file failed verification: {relative}"
                    )
    except (OSError, tarfile.TarError) as error:
        raise ComponentPackInstallError("component archive could not be extracted") from error


def verify_release_directory(release: Path, manifest_path: Path, manifest: dict[str, Any]) -> None:
    expected_files = {
        "component-pack-manifest.json": {
            "sizeBytes": manifest_path.stat().st_size,
            "sha256": sha256_file(manifest_path),
        },
        **{record["path"]: record for record in manifest["files"]},
    }
    expected_directories: set[str] = set()
    for relative in expected_files:
        for parent in PurePosixPath(relative).parents:
            if str(parent) != ".":
                expected_directories.add(str(parent))
    try:
        for relative, record in expected_files.items():
            path = release.joinpath(*PurePosixPath(relative).parts)
            if path.is_symlink() or not path.is_file():
                raise ComponentPackInstallError(f"component release file is missing: {relative}")
            if path.stat().st_size != record["sizeBytes"] or sha256_file(path) != record["sha256"]:
                raise ComponentPackInstallError(
                    f"component release file failed verification: {relative}"
                )
        for path in release.rglob("*"):
            relative = path.relative_to(release).as_posix()
            if path.is_symlink():
                raise ComponentPackInstallError(f"component release contains a symlink: {relative}")
            if path.is_file() and relative not in expected_files:
                raise ComponentPackInstallError(
                    f"component release contains an unlisted file: {relative}"
                )
            if path.is_dir() and relative not in expected_directories:
                raise ComponentPackInstallError(
                    f"component release contains an unlisted directory: {relative}"
                )
            if not path.is_file() and not path.is_dir():
                raise ComponentPackInstallError(
                    f"component release contains an unsafe path: {relative}"
                )
    except OSError as error:
        raise ComponentPackInstallError("component release directory cannot be verified") from error


def atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.chmod(0o600)
    os.replace(temporary, path)


def managed_current(link: Path) -> Path | None:
    if not link.is_symlink():
        if link.exists():
            raise ComponentPackInstallError("component current path is not a managed symlink")
        return None
    try:
        target = link.resolve(strict=True)
        releases = (link.parent / "releases").resolve(strict=True)
    except OSError as error:
        raise ComponentPackInstallError("component current symlink is invalid") from error
    if target.parent != releases or len(target.name) != 64:
        raise ComponentPackInstallError("component current symlink escapes its release root")
    return target


def replace_symlink(link: Path, target: Path) -> None:
    temporary = link.with_name(f".{link.name}.{uuid.uuid4().hex}.tmp")
    temporary.symlink_to(target)
    os.replace(temporary, link)


def install_pack(
    *,
    manifest_path: Path,
    archive_path: Path,
    verified_receipt_path: Path,
    runtime_manifest_path: Path,
    runtime_profile: str,
    expected_manifest_sha256: str,
    expected_archive_sha256: str,
    expected_catalog_sequence: int,
    expected_key_id: str,
    pack_root: Path = DEFAULT_PACK_ROOT,
    state_path: Path = DEFAULT_STATE_PATH,
) -> dict[str, Any]:
    for path, label in (
        (manifest_path, "manifest"),
        (archive_path, "archive"),
        (verified_receipt_path, "verified receipt"),
        (runtime_manifest_path, "Runtime manifest"),
    ):
        if path.is_symlink() or not path.is_file():
            raise ComponentPackInstallError(f"component {label} path is unsafe")
    manifest = load_json(manifest_path)
    validate_manifest(manifest)
    verified_receipt = load_json(verified_receipt_path)
    validate_verified_receipt(
        verified_receipt,
        manifest_path,
        archive_path,
        expected_manifest_sha256=expected_manifest_sha256,
        expected_archive_sha256=expected_archive_sha256,
        expected_catalog_sequence=expected_catalog_sequence,
        expected_key_id=expected_key_id,
    )
    validate_runtime_compatibility(manifest, load_json(runtime_manifest_path), runtime_profile)
    pack_type = manifest["packType"]
    component_root = pack_root / pack_type
    releases = component_root / "releases"
    staging = component_root / "staging"
    current_link = component_root / "current"
    releases.mkdir(parents=True, exist_ok=True)
    staging.mkdir(parents=True, exist_ok=True)
    previous = managed_current(current_link)
    release_id = manifest["packId"].removeprefix("sha256:")
    target = releases / release_id

    if state_path.is_symlink():
        raise ComponentPackInstallError("component pack state path is unsafe")
    state = (
        load_json(state_path)
        if state_path.is_file()
        else {"schemaVersion": 1, "catalogSequence": 0, "components": {}}
    )
    if (
        set(state) != {"schemaVersion", "catalogSequence", "components"}
        or state.get("schemaVersion") != 1
        or not isinstance(state.get("catalogSequence"), int)
        or state["catalogSequence"] < 0
        or not isinstance(state.get("components"), dict)
    ):
        raise ComponentPackInstallError("component pack state is invalid")
    if verified_receipt["catalogSequence"] < state["catalogSequence"]:
        raise ComponentPackInstallError("component catalog replay or downgrade was rejected")
    previous_state = state["components"].get(pack_type)
    if previous_state is not None:
        if not isinstance(previous_state, dict) or not isinstance(
            previous_state.get("releaseSequence"), int
        ):
            raise ComponentPackInstallError("component pack state entry is invalid")
        if manifest["releaseSequence"] < previous_state["releaseSequence"]:
            raise ComponentPackInstallError("component pack replay or downgrade was rejected")
        if manifest["releaseSequence"] == previous_state["releaseSequence"]:
            if previous_state.get("packId") == manifest["packId"] and current_link.is_symlink():
                return previous_state
            raise ComponentPackInstallError("component pack replay or downgrade was rejected")

    if target.exists():
        if not target.is_dir() or target.is_symlink():
            raise ComponentPackInstallError("component release target is unsafe")
    else:
        temporary = Path(tempfile.mkdtemp(prefix=f"{release_id}.", dir=staging))
        try:
            safe_extract(archive_path, temporary, manifest["files"])
            shutil.copyfile(manifest_path, temporary / "component-pack-manifest.json")
            os.replace(temporary, target)
        except Exception:
            shutil.rmtree(temporary, ignore_errors=True)
            raise

    verify_release_directory(target, manifest_path, manifest)

    replace_symlink(current_link, target)
    receipt = {
        "packId": manifest["packId"],
        "packName": manifest["packName"],
        "packType": pack_type,
        "version": manifest["version"],
        "releaseSequence": manifest["releaseSequence"],
        "previousPackId": f"sha256:{previous.name}" if previous is not None else None,
        "activatedAt": dt.datetime.now(dt.timezone.utc).isoformat(),
        "runtimeProfile": runtime_profile,
    }
    state["components"][pack_type] = receipt
    state["catalogSequence"] = max(state["catalogSequence"], verified_receipt["catalogSequence"])
    try:
        atomic_write_json(state_path, state)
    except Exception:
        if previous is not None:
            replace_symlink(current_link, previous)
        elif current_link.is_symlink():
            current_link.unlink()
        raise
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--verified-receipt", type=Path, required=True)
    parser.add_argument("--runtime-manifest", type=Path, default=DEFAULT_RUNTIME_MANIFEST)
    parser.add_argument("--runtime-profile", choices=PROFILES, required=True)
    parser.add_argument("--expected-manifest-sha256", required=True)
    parser.add_argument("--expected-archive-sha256", required=True)
    parser.add_argument("--expected-catalog-sequence", type=int, required=True)
    parser.add_argument("--expected-key-id", required=True)
    parser.add_argument("--pack-root", type=Path, default=DEFAULT_PACK_ROOT)
    parser.add_argument("--state", type=Path, default=DEFAULT_STATE_PATH)
    arguments = parser.parse_args()
    try:
        receipt = install_pack(
            manifest_path=arguments.manifest,
            archive_path=arguments.archive,
            verified_receipt_path=arguments.verified_receipt,
            runtime_manifest_path=arguments.runtime_manifest,
            runtime_profile=arguments.runtime_profile,
            expected_manifest_sha256=arguments.expected_manifest_sha256,
            expected_archive_sha256=arguments.expected_archive_sha256,
            expected_catalog_sequence=arguments.expected_catalog_sequence,
            expected_key_id=arguments.expected_key_id,
            pack_root=arguments.pack_root,
            state_path=arguments.state,
        )
    except ComponentPackInstallError as error:
        parser.exit(2, f"component pack installation failed: {error}\n")
    print(json.dumps(receipt, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
