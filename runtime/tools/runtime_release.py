#!/usr/bin/env python3
"""Build, sign, verify, and reassemble DroneDreamRuntime release payloads.

The release manifest is deliberately separate from the manifest embedded in
the WSL rootfs.  The embedded manifest records the software composition and
real smoke result; this manifest describes immutable downloadable bytes.
"""

from __future__ import annotations

import argparse
import base64
import binascii
import hashlib
import json
import os
import re
import shutil
import stat
import sys
import tarfile
import tempfile
import uuid
from collections.abc import Iterable
from datetime import datetime
from pathlib import Path
from typing import Any, BinaryIO
from urllib.parse import quote, unquote, urlsplit

try:
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import (
        Ed25519PrivateKey,
        Ed25519PublicKey,
    )
except ImportError:  # pragma: no cover - exercised by the CLI error path.
    InvalidSignature = None  # type: ignore[assignment]
    serialization = None  # type: ignore[assignment]
    Ed25519PrivateKey = None  # type: ignore[assignment,misc]
    Ed25519PublicKey = None  # type: ignore[assignment,misc]


SCHEMA_VERSION = 1
SIGNATURE_SCHEMA_VERSION = 1
KEYRING_SCHEMA_VERSION = 1
RUNTIME_ID = "DroneDreamRuntime"
ARCHITECTURE = "x86_64"
WSL_VERSION = 2
COMPRESSION = "none"
MEDIA_TYPE = "application/vnd.dronedream.wsl-rootfs+tar"
DEFAULT_PART_BYTES = 1_900 * 1024 * 1024
MAX_PART_BYTES_EXCLUSIVE = 2 * 1024 * 1024 * 1024
MAX_ARTIFACT_BYTES = 12 * 1024 * 1024 * 1024
MAX_PARTS = 64
MAX_JSON_BYTES = 4 * 1024 * 1024
DEFAULT_MINIMUM_FREE_BYTES = 52 * 1024 * 1024 * 1024
DEFAULT_TARGET_PATH_HINT = "X:\\DroneDream"
MANIFEST_FILENAME = "runtime-release.json"
SIGNATURE_SUFFIX = ".sig"
PRIVATE_KEY_ENV_DEFAULT = "DRONEDREAM_RUNTIME_ED25519_PRIVATE_KEY"
EMBEDDED_MANIFEST_MEMBER = "opt/dronedream/runtime-manifest.json"

SHA40 = re.compile(r"^[0-9a-f]{40}$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")
SEMVER = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")
SAFE_FILENAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,199}$")
KEY_ID = re.compile(r"^ed25519:[0-9a-f]{64}$")


class ReleaseError(ValueError):
    """A release input or cryptographic verification was invalid."""


def _require_crypto() -> None:
    if Ed25519PrivateKey is None or serialization is None:
        raise ReleaseError(
            "Ed25519 operations require runtime/locks/release-tools-requirements.lock"
        )


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ReleaseError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def load_json(path: Path) -> Any:
    content = read_regular_bytes(path, "JSON file")
    if len(content) > MAX_JSON_BYTES:
        raise ReleaseError(f"JSON file exceeds {MAX_JSON_BYTES} bytes: {path}")
    return load_json_bytes(content, str(path))


def load_json_bytes(content: bytes, label: str) -> Any:
    try:
        return json.loads(
            content.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=lambda value: (_ for _ in ()).throw(
                ReleaseError(f"unsupported JSON constant: {value}")
            ),
        )
    except UnicodeDecodeError as exc:
        raise ReleaseError(f"{label} is not UTF-8") from exc


def _validate_canonical_value(value: Any, location: str = "$") -> None:
    if value is None or isinstance(value, (str, bool)):
        return
    if isinstance(value, int) and not isinstance(value, bool):
        if abs(value) > 9_007_199_254_740_991:
            raise ReleaseError(f"integer outside interoperable range at {location}")
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            _validate_canonical_value(item, f"{location}[{index}]")
        return
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise ReleaseError(f"non-string object key at {location}")
            _validate_canonical_value(item, f"{location}.{key}")
        return
    # Floats are prohibited.  Release manifests have no fractional fields, and
    # excluding them keeps the stdlib canonical encoding unambiguous.
    raise ReleaseError(f"unsupported canonical JSON type at {location}")


def canonical_bytes(payload: Any) -> bytes:
    _validate_canonical_value(payload)
    return json.dumps(
        payload,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _regular_file(path: Path, label: str) -> os.stat_result:
    try:
        details = path.lstat()
    except FileNotFoundError as exc:
        raise ReleaseError(f"{label} does not exist: {path}") from exc
    if not stat.S_ISREG(details.st_mode) or path.is_symlink():
        raise ReleaseError(f"{label} must be a regular non-symlink file: {path}")
    return details


def _sha256_stream(stream: BinaryIO) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    while block := stream.read(1024 * 1024):
        digest.update(block)
        size += len(block)
    return digest.hexdigest(), size


def file_sha256(path: Path) -> tuple[str, int]:
    expected = _regular_file(path, "file")
    with path.open("rb") as stream:
        opened = os.fstat(stream.fileno())
        if (opened.st_dev, opened.st_ino) != (expected.st_dev, expected.st_ino):
            raise ReleaseError(f"file identity changed while opening: {path}")
        result = _sha256_stream(stream)
        finished = os.fstat(stream.fileno())
        if (
            finished.st_size != opened.st_size
            or finished.st_mtime_ns != opened.st_mtime_ns
            or result[1] != finished.st_size
        ):
            raise ReleaseError(f"file changed while hashing: {path}")
        return result


def read_regular_bytes(path: Path, label: str) -> bytes:
    expected = _regular_file(path, label)
    with path.open("rb") as stream:
        opened = os.fstat(stream.fileno())
        if (opened.st_dev, opened.st_ino) != (expected.st_dev, expected.st_ino):
            raise ReleaseError(f"{label} identity changed while opening: {path}")
        content = stream.read()
        finished = os.fstat(stream.fileno())
    if (
        finished.st_size != opened.st_size
        or finished.st_mtime_ns != opened.st_mtime_ns
        or len(content) != finished.st_size
    ):
        raise ReleaseError(f"{label} changed while reading: {path}")
    return content


def _write_new(path: Path, content: bytes, mode: int = 0o644) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor: int | None = None
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
        with os.fdopen(descriptor, "wb") as stream:
            descriptor = None
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
    except FileExistsError as exc:
        raise ReleaseError(f"refusing to overwrite existing file: {path}") from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _write_canonical_new(path: Path, payload: Any, mode: int = 0o644) -> None:
    _write_new(path, canonical_bytes(payload), mode)


def _safe_filename(value: Any, label: str) -> str:
    if not isinstance(value, str) or SAFE_FILENAME.fullmatch(value) is None:
        raise ReleaseError(f"{label} is not a safe release filename")
    if value in {".", ".."}:
        raise ReleaseError(f"{label} is not a safe release filename")
    return value


def _https_url(value: Any, label: str, filename: str | None = None) -> str:
    if not isinstance(value, str) or len(value) > 2048:
        raise ReleaseError(f"{label} must be an HTTPS URL")
    parsed = urlsplit(value)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise ReleaseError(f"{label} must be a credential-free HTTPS URL")
    if filename is not None:
        final_component = unquote(parsed.path.rstrip("/").rsplit("/", 1)[-1])
        if final_component != filename:
            raise ReleaseError(f"{label} URL does not end with its filename")
    return value


def _base_url(value: str) -> str:
    normalized = value.rstrip("/")
    _https_url(normalized, "base URL")
    return normalized


def _asset_url(base_url: str, filename: str) -> str:
    return f"{base_url}/{quote(filename, safe='._-')}"


def _require_keys(value: dict[str, Any], expected: Iterable[str], label: str) -> None:
    actual = set(value)
    required = set(expected)
    if actual != required:
        missing = sorted(required - actual)
        extra = sorted(actual - required)
        details = []
        if missing:
            details.append("missing " + ", ".join(missing))
        if extra:
            details.append("unsupported " + ", ".join(extra))
        raise ReleaseError(f"{label} fields are invalid ({'; '.join(details)})")


def _canonical_uuid(value: Any, label: str) -> str:
    if not isinstance(value, str):
        raise ReleaseError(f"{label} must be a UUID")
    try:
        parsed = uuid.UUID(value)
    except ValueError as exc:
        raise ReleaseError(f"{label} must be a UUID") from exc
    if str(parsed) != value:
        raise ReleaseError(f"{label} must be a canonical lowercase UUID")
    return value


def _rfc3339(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ReleaseError(f"{label} must be an RFC3339 UTC timestamp ending in Z")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise ReleaseError(f"{label} must be an RFC3339 timestamp") from exc
    if parsed.utcoffset() is None or parsed.utcoffset().total_seconds() != 0:
        raise ReleaseError(f"{label} must use UTC")
    return value


def _normalize_rfc3339(value: Any, label: str) -> str:
    if not isinstance(value, str):
        raise ReleaseError(f"{label} must be an RFC3339 timestamp")
    candidate = value
    if candidate.endswith("+00:00"):
        candidate = candidate[:-6] + "Z"
    return _rfc3339(candidate, label)


def validate_release_manifest(manifest: Any) -> dict[str, Any]:
    if not isinstance(manifest, dict):
        raise ReleaseError("release manifest must be an object")
    _require_keys(
        manifest,
        (
            "schemaVersion",
            "runtime",
            "source",
            "artifact",
            "smoke",
            "requirements",
        ),
        "release manifest",
    )
    if type(manifest["schemaVersion"]) is not int or manifest["schemaVersion"] != SCHEMA_VERSION:
        raise ReleaseError("unsupported release manifest schema")

    runtime = manifest["runtime"]
    if not isinstance(runtime, dict):
        raise ReleaseError("runtime must be an object")
    _require_keys(
        runtime,
        ("id", "buildId", "version", "architecture", "wslVersion"),
        "runtime",
    )
    if runtime["id"] != RUNTIME_ID:
        raise ReleaseError("runtime id is invalid")
    _canonical_uuid(runtime["buildId"], "runtime buildId")
    if not isinstance(runtime["version"], str) or not SEMVER.fullmatch(runtime["version"]):
        raise ReleaseError("runtime version is invalid")
    if (
        runtime["architecture"] != ARCHITECTURE
        or type(runtime["wslVersion"]) is not int
        or runtime["wslVersion"] != 2
    ):
        raise ReleaseError("runtime target is unsupported")

    source = manifest["source"]
    if not isinstance(source, dict):
        raise ReleaseError("source must be an object")
    _require_keys(
        source,
        ("gitCommit", "px4Commit", "gazeboVersion", "buildTimestamp"),
        "source",
    )
    if not isinstance(source["gitCommit"], str) or not SHA40.fullmatch(source["gitCommit"]):
        raise ReleaseError("source gitCommit is invalid")
    if not isinstance(source["px4Commit"], str) or not SHA40.fullmatch(source["px4Commit"]):
        raise ReleaseError("source px4Commit is invalid")
    if (
        not isinstance(source["gazeboVersion"], str)
        or not source["gazeboVersion"]
        or len(source["gazeboVersion"]) > 128
    ):
        raise ReleaseError("source gazeboVersion is invalid")
    _rfc3339(source["buildTimestamp"], "source buildTimestamp")

    artifact = manifest["artifact"]
    if not isinstance(artifact, dict):
        raise ReleaseError("artifact must be an object")
    _require_keys(
        artifact,
        (
            "filename",
            "mediaType",
            "compression",
            "sizeBytes",
            "sha256",
            "parts",
        ),
        "artifact",
    )
    filename = _safe_filename(artifact["filename"], "artifact filename")
    reserved_names = {MANIFEST_FILENAME, MANIFEST_FILENAME + SIGNATURE_SUFFIX}
    if filename in reserved_names:
        raise ReleaseError("artifact filename conflicts with release metadata")
    if artifact["mediaType"] != MEDIA_TYPE or artifact["compression"] != COMPRESSION:
        raise ReleaseError("artifact format is unsupported")
    if (
        type(artifact["sizeBytes"]) is not int
        or artifact["sizeBytes"] <= 0
        or artifact["sizeBytes"] > MAX_ARTIFACT_BYTES
    ):
        raise ReleaseError("artifact sizeBytes is invalid")
    if not isinstance(artifact["sha256"], str) or not SHA256.fullmatch(artifact["sha256"]):
        raise ReleaseError("artifact sha256 is invalid")
    parts = artifact["parts"]
    if not isinstance(parts, list) or not parts or len(parts) > MAX_PARTS:
        raise ReleaseError("artifact parts must be a non-empty array")
    part_size_sum = 0
    part_names: set[str] = set()
    part_urls: set[str] = set()
    for expected_index, part in enumerate(parts):
        if not isinstance(part, dict):
            raise ReleaseError("artifact part must be an object")
        _require_keys(part, ("index", "filename", "sizeBytes", "sha256", "url"), "part")
        if type(part["index"]) is not int or part["index"] != expected_index:
            raise ReleaseError("artifact part indexes must be contiguous from zero")
        part_filename = _safe_filename(part["filename"], "part filename")
        if (
            part_filename == filename
            or part_filename in reserved_names
            or part_filename in part_names
        ):
            raise ReleaseError("artifact part filenames must be unique")
        part_names.add(part_filename)
        size = part["sizeBytes"]
        if (
            not isinstance(size, int)
            or isinstance(size, bool)
            or size <= 0
            or size >= MAX_PART_BYTES_EXCLUSIVE
        ):
            raise ReleaseError("every artifact part must be positive and under 2 GiB")
        part_size_sum += size
        if not isinstance(part["sha256"], str) or not SHA256.fullmatch(part["sha256"]):
            raise ReleaseError("artifact part sha256 is invalid")
        url = _https_url(part["url"], "part URL", part_filename)
        if url in part_urls:
            raise ReleaseError("artifact part URLs must be unique")
        part_urls.add(url)
    if part_size_sum != artifact["sizeBytes"]:
        raise ReleaseError("artifact part sizes do not equal whole artifact size")

    smoke = manifest["smoke"]
    if not isinstance(smoke, dict):
        raise ReleaseError("smoke must be an object")
    _require_keys(
        smoke,
        ("passed", "reportFilename", "reportSha256", "reportUrl", "completedAt"),
        "smoke",
    )
    if smoke["passed"] is not True:
        raise ReleaseError("release manifest requires a successful real smoke report")
    report_filename = _safe_filename(smoke["reportFilename"], "smoke report filename")
    if (
        report_filename == filename
        or report_filename in reserved_names
        or report_filename in part_names
    ):
        raise ReleaseError("smoke report filename conflicts with another release asset")
    if not isinstance(smoke["reportSha256"], str) or not SHA256.fullmatch(smoke["reportSha256"]):
        raise ReleaseError("smoke report sha256 is invalid")
    _https_url(smoke["reportUrl"], "smoke report URL", report_filename)
    _rfc3339(smoke["completedAt"], "smoke completedAt")

    requirements = manifest["requirements"]
    if not isinstance(requirements, dict):
        raise ReleaseError("requirements must be an object")
    _require_keys(
        requirements,
        ("minimumFreeBytes", "targetPathHint"),
        "requirements",
    )
    if (
        not isinstance(requirements["minimumFreeBytes"], int)
        or isinstance(requirements["minimumFreeBytes"], bool)
        or requirements["minimumFreeBytes"] < DEFAULT_MINIMUM_FREE_BYTES
        or requirements["minimumFreeBytes"] <= artifact["sizeBytes"]
    ):
        raise ReleaseError("requirements minimumFreeBytes is invalid")
    if requirements["targetPathHint"] != DEFAULT_TARGET_PATH_HINT:
        raise ReleaseError("requirements targetPathHint is invalid")
    return manifest


def validate_signature_envelope(envelope: Any) -> dict[str, Any]:
    if not isinstance(envelope, dict):
        raise ReleaseError("signature envelope must be an object")
    _require_keys(
        envelope,
        ("schemaVersion", "algorithm", "keyId", "manifestSha256", "signature"),
        "signature envelope",
    )
    if (
        type(envelope["schemaVersion"]) is not int
        or envelope["schemaVersion"] != SIGNATURE_SCHEMA_VERSION
    ):
        raise ReleaseError("unsupported signature envelope schema")
    if envelope["algorithm"] != "Ed25519":
        raise ReleaseError("unsupported signature algorithm")
    if not isinstance(envelope["keyId"], str) or not KEY_ID.fullmatch(envelope["keyId"]):
        raise ReleaseError("signature keyId is invalid")
    if not isinstance(envelope["manifestSha256"], str) or not SHA256.fullmatch(
        envelope["manifestSha256"]
    ):
        raise ReleaseError("signature manifestSha256 is invalid")
    try:
        signature = base64.b64decode(envelope["signature"], validate=True)
    except (binascii.Error, TypeError) as exc:
        raise ReleaseError("signature is not canonical base64") from exc
    if len(signature) != 64 or base64.b64encode(signature).decode("ascii") != envelope["signature"]:
        raise ReleaseError("signature must encode exactly 64 bytes")
    return envelope


def validate_keyring(keyring: Any) -> dict[str, bytes]:
    if not isinstance(keyring, dict):
        raise ReleaseError("release keyring must be an object")
    _require_keys(keyring, ("schemaVersion", "keys"), "release keyring")
    if (
        type(keyring["schemaVersion"]) is not int
        or keyring["schemaVersion"] != KEYRING_SCHEMA_VERSION
    ):
        raise ReleaseError("unsupported release keyring schema")
    entries = keyring["keys"]
    if not isinstance(entries, list):
        raise ReleaseError("release keyring keys must be an array")
    # Retired entries remain part of the structurally validated keyring so an
    # operator can retain rotation history, but only active keys are eligible
    # to authorize a newly verified release manifest.
    parsed: dict[str, bytes] = {}
    seen: set[str] = set()
    for entry in entries:
        if not isinstance(entry, dict):
            raise ReleaseError("release key entry must be an object")
        _require_keys(
            entry,
            ("keyId", "algorithm", "publicKeyBase64", "usage", "status"),
            "release key entry",
        )
        if entry["algorithm"] != "Ed25519" or entry["usage"] != "runtime-release":
            raise ReleaseError("release key entry purpose is invalid")
        if entry["status"] not in {"active", "retired"}:
            raise ReleaseError("release key status is invalid")
        try:
            raw = base64.b64decode(entry["publicKeyBase64"], validate=True)
        except (binascii.Error, TypeError) as exc:
            raise ReleaseError("release public key is not base64") from exc
        if len(raw) != 32 or base64.b64encode(raw).decode("ascii") != entry["publicKeyBase64"]:
            raise ReleaseError("release public key must encode exactly 32 bytes")
        expected_id = key_id_for_public_key(raw)
        if entry["keyId"] != expected_id:
            raise ReleaseError("release keyId does not match its public key")
        if expected_id in seen:
            raise ReleaseError("duplicate release keyId")
        seen.add(expected_id)
        if entry["status"] == "active":
            parsed[expected_id] = raw
    return parsed


def key_id_for_public_key(raw_public_key: bytes) -> str:
    return "ed25519:" + hashlib.sha256(raw_public_key).hexdigest()


def _public_entry(private_key: Any) -> dict[str, Any]:
    _require_crypto()
    raw = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    return {
        "keyId": key_id_for_public_key(raw),
        "algorithm": "Ed25519",
        "publicKeyBase64": base64.b64encode(raw).decode("ascii"),
        "usage": "runtime-release",
        "status": "active",
    }


def generate_key(private_output: Path, public_output: Path) -> str:
    _require_crypto()
    private_key = Ed25519PrivateKey.generate()
    raw_private = private_key.private_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PrivateFormat.Raw,
        encryption_algorithm=serialization.NoEncryption(),
    )
    secret = base64.b64encode(raw_private) + b"\n"
    # O_EXCL and 0600 protect POSIX builders.  Windows applies the current
    # user's normal ACL; the command never prints the secret.
    _write_new(private_output, secret, 0o600)
    try:
        os.chmod(private_output, stat.S_IRUSR | stat.S_IWUSR)
        _write_canonical_new(
            public_output,
            {
                "schemaVersion": KEYRING_SCHEMA_VERSION,
                "keys": [_public_entry(private_key)],
            },
        )
    except Exception:
        private_output.unlink(missing_ok=True)
        raise
    return _public_entry(private_key)["keyId"]


def _load_private_key_from_environment(variable: str) -> Any:
    _require_crypto()
    encoded = os.environ.get(variable)
    if not encoded:
        raise ReleaseError(f"private signing key environment variable is empty: {variable}")
    try:
        raw = base64.b64decode(encoded.strip(), validate=True)
    except binascii.Error as exc:
        raise ReleaseError("private signing key must be canonical base64") from exc
    if len(raw) != 32 or base64.b64encode(raw).decode("ascii") != encoded.strip():
        raise ReleaseError("private signing key must encode exactly 32 bytes")
    return Ed25519PrivateKey.from_private_bytes(raw)


def _validate_promoted_runtime_manifest(manifest: Any, smoke_report: Any) -> None:
    if not isinstance(manifest, dict) or not isinstance(smoke_report, dict):
        raise ReleaseError("runtime manifest and smoke report must be objects")
    if manifest.get("schemaVersion") != 1:
        raise ReleaseError("unsupported embedded runtime manifest schema")
    _canonical_uuid(manifest.get("runtimeId"), "embedded runtimeId")
    version = manifest.get("version")
    if not isinstance(version, str) or not SEMVER.fullmatch(version):
        raise ReleaseError("embedded runtime version is invalid")
    smoke_flags = manifest.get("smokeTests")
    if smoke_flags != {
        "px4Sitl": True,
        "gazebo": True,
        "parameterReadback": True,
    }:
        raise ReleaseError("embedded runtime manifest is not smoke-promoted")
    if smoke_report.get("passed") is not True or smoke_report.get("mode") != "runtime-image":
        raise ReleaseError("release requires a passed runtime-image smoke report")
    if smoke_report.get("runtimeId") != manifest["runtimeId"]:
        raise ReleaseError("smoke report does not match embedded runtimeId")
    embedded_report = manifest.get("smokeReport")
    if not isinstance(embedded_report, dict) or embedded_report.get("passed") is not True:
        raise ReleaseError("embedded smoke report is missing or failed")
    for field in ("runtimeId", "imageId", "passed", "mode", "checks"):
        if embedded_report.get(field) != smoke_report.get(field):
            raise ReleaseError(f"smoke report differs from promoted manifest: {field}")
    checks = smoke_report.get("checks")
    if not isinstance(checks, list) or not checks:
        raise ReleaseError("smoke report checks are missing")
    if any(not isinstance(check, dict) or check.get("passed") is not True for check in checks):
        raise ReleaseError("smoke report contains a failed check")
    required = {
        "component_versions",
        "python_imports",
        "valkey_ping",
        "api_worker_heartbeat",
        "real_cli_dry_run",
        "px4_gazebo_headless",
        "parameter_readback",
    }
    names = {check.get("name") for check in checks}
    if not required.issubset(names):
        raise ReleaseError("smoke report is missing required checks")


def extract_embedded_manifest(rootfs: Path, output: Path) -> None:
    """Copy only the validated embedded manifest from a rootfs tar.

    This is a recovery path for an otherwise valid export whose sidecar was
    not retained. It never extracts arbitrary archive paths.
    """

    _regular_file(rootfs, "rootfs")
    content: bytes | None = None
    try:
        with tarfile.open(rootfs, mode="r:") as archive:
            for member in archive:
                normalized = member.name.removeprefix("./")
                if normalized != EMBEDDED_MANIFEST_MEMBER:
                    continue
                if content is not None:
                    raise ReleaseError("rootfs contains duplicate embedded manifests")
                if not member.isfile() or member.size <= 0 or member.size > MAX_JSON_BYTES:
                    raise ReleaseError("embedded runtime manifest member is invalid")
                stream = archive.extractfile(member)
                if stream is None:
                    raise ReleaseError("embedded runtime manifest cannot be read")
                content = stream.read(MAX_JSON_BYTES + 1)
    except (tarfile.TarError, EOFError) as exc:
        raise ReleaseError("rootfs is not a readable uncompressed tar") from exc
    if content is None:
        raise ReleaseError(f"rootfs is missing {EMBEDDED_MANIFEST_MEMBER}")
    manifest = load_json_bytes(content, EMBEDDED_MANIFEST_MEMBER)
    if not isinstance(manifest, dict) or not isinstance(manifest.get("smokeReport"), dict):
        raise ReleaseError("embedded runtime manifest has no smoke evidence")
    _validate_promoted_runtime_manifest(manifest, manifest["smokeReport"])
    _write_new(output, content)


def package_release(
    *,
    rootfs: Path,
    runtime_manifest_path: Path,
    smoke_report_path: Path,
    output_directory: Path,
    base_url: str,
    build_timestamp: str,
    part_bytes: int = DEFAULT_PART_BYTES,
    minimum_free_bytes: int = DEFAULT_MINIMUM_FREE_BYTES,
) -> Path:
    rootfs_stat = _regular_file(rootfs, "rootfs")
    _regular_file(runtime_manifest_path, "promoted runtime manifest")
    _regular_file(smoke_report_path, "smoke report")
    if rootfs_stat.st_size <= 0:
        raise ReleaseError("rootfs must not be empty")
    if rootfs_stat.st_size > MAX_ARTIFACT_BYTES:
        raise ReleaseError("rootfs exceeds the 12 GiB release limit")
    if type(part_bytes) is not int or part_bytes <= 0 or part_bytes >= MAX_PART_BYTES_EXCLUSIVE:
        raise ReleaseError("part size must be positive and strictly below 2 GiB")
    expected_parts = (rootfs_stat.st_size + part_bytes - 1) // part_bytes
    if expected_parts > MAX_PARTS:
        raise ReleaseError(f"release would exceed the {MAX_PARTS}-part safety limit")
    if (
        type(minimum_free_bytes) is not int
        or minimum_free_bytes < DEFAULT_MINIMUM_FREE_BYTES
        or minimum_free_bytes <= rootfs_stat.st_size
    ):
        raise ReleaseError("minimum free bytes must be at least 52 GiB")
    if output_directory.exists() or output_directory.is_symlink():
        raise ReleaseError(f"release output directory must not exist: {output_directory}")

    embedded_manifest_bytes = read_regular_bytes(runtime_manifest_path, "promoted runtime manifest")
    smoke_report_bytes = read_regular_bytes(smoke_report_path, "smoke report")
    embedded_manifest = load_json_bytes(embedded_manifest_bytes, str(runtime_manifest_path))
    smoke_report = load_json_bytes(smoke_report_bytes, str(smoke_report_path))
    _validate_promoted_runtime_manifest(embedded_manifest, smoke_report)
    base = _base_url(base_url)
    build_time = _normalize_rfc3339(build_timestamp, "build timestamp")
    completed_at = _normalize_rfc3339(smoke_report.get("completedAt"), "smoke completedAt")

    source = embedded_manifest.get("source")
    component_details = embedded_manifest.get("componentDetails")
    if not isinstance(source, dict) or not isinstance(component_details, dict):
        raise ReleaseError("embedded source/component details are missing")
    git_commit = source.get("droneDreamCommit")
    px4 = component_details.get("px4")
    gazebo = component_details.get("gazebo")
    if not isinstance(git_commit, str) or not SHA40.fullmatch(git_commit):
        raise ReleaseError("embedded DroneDream source commit is invalid")
    if (
        not isinstance(px4, dict)
        or not isinstance(px4.get("commit"), str)
        or not SHA40.fullmatch(px4["commit"])
    ):
        raise ReleaseError("embedded PX4 commit is invalid")
    if not isinstance(gazebo, dict):
        raise ReleaseError("embedded Gazebo version is missing")
    gazebo_release = gazebo.get("release")
    gazebo_package = gazebo.get("packageVersion")
    if not isinstance(gazebo_release, str) or not isinstance(gazebo_package, str):
        raise ReleaseError("embedded Gazebo version is invalid")
    gazebo_version = f"{gazebo_release}@{gazebo_package}"

    artifact_filename = _safe_filename(rootfs.name, "rootfs filename")
    report_filename = _safe_filename(smoke_report_path.name, "smoke report filename")
    parent = output_directory.parent.resolve()
    parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{output_directory.name}.staging-", dir=parent))
    try:
        whole_digest = hashlib.sha256()
        whole_size = 0
        parts: list[dict[str, Any]] = []
        with rootfs.open("rb") as source_stream:
            opened_rootfs = os.fstat(source_stream.fileno())
            if (opened_rootfs.st_dev, opened_rootfs.st_ino) != (
                rootfs_stat.st_dev,
                rootfs_stat.st_ino,
            ):
                raise ReleaseError("rootfs identity changed while it was being opened")
            index = 0
            while True:
                first = source_stream.read(min(part_bytes, 1024 * 1024))
                if not first:
                    break
                part_filename = f"{artifact_filename}.part{index:04d}"
                part_path = staging / part_filename
                part_digest = hashlib.sha256()
                part_size = 0
                with part_path.open("xb") as part_stream:
                    block = first
                    while block:
                        part_stream.write(block)
                        part_digest.update(block)
                        whole_digest.update(block)
                        part_size += len(block)
                        whole_size += len(block)
                        remaining = part_bytes - part_size
                        if remaining <= 0:
                            break
                        block = source_stream.read(min(remaining, 1024 * 1024))
                    part_stream.flush()
                    os.fsync(part_stream.fileno())
                parts.append(
                    {
                        "index": index,
                        "filename": part_filename,
                        "sizeBytes": part_size,
                        "sha256": part_digest.hexdigest(),
                        "url": _asset_url(base, part_filename),
                    }
                )
                index += 1
            finished_rootfs = os.fstat(source_stream.fileno())
        if (
            whole_size != rootfs_stat.st_size
            or finished_rootfs.st_size != opened_rootfs.st_size
            or finished_rootfs.st_mtime_ns != opened_rootfs.st_mtime_ns
        ):
            raise ReleaseError("rootfs changed while it was being split")

        report_target = staging / report_filename
        _write_new(report_target, smoke_report_bytes)
        report_hash, report_size = file_sha256(report_target)
        if report_size != len(smoke_report_bytes):
            raise ReleaseError("smoke report copy size is invalid")

        release_manifest = {
            "schemaVersion": SCHEMA_VERSION,
            "runtime": {
                "id": RUNTIME_ID,
                "buildId": embedded_manifest["runtimeId"],
                "version": embedded_manifest["version"],
                "architecture": ARCHITECTURE,
                "wslVersion": WSL_VERSION,
            },
            "source": {
                "gitCommit": git_commit,
                "px4Commit": px4["commit"],
                "gazeboVersion": gazebo_version,
                "buildTimestamp": build_time,
            },
            "artifact": {
                "filename": artifact_filename,
                "mediaType": MEDIA_TYPE,
                "compression": COMPRESSION,
                "sizeBytes": whole_size,
                "sha256": whole_digest.hexdigest(),
                "parts": parts,
            },
            "smoke": {
                "passed": True,
                "reportFilename": report_filename,
                "reportSha256": report_hash,
                "reportUrl": _asset_url(base, report_filename),
                "completedAt": completed_at,
            },
            "requirements": {
                "minimumFreeBytes": minimum_free_bytes,
                "targetPathHint": DEFAULT_TARGET_PATH_HINT,
            },
        }
        validate_release_manifest(release_manifest)
        _write_canonical_new(staging / MANIFEST_FILENAME, release_manifest)
        staging.rename(output_directory)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return output_directory / MANIFEST_FILENAME


def sign_manifest(manifest_path: Path, private_key_env: str, public_output: Path | None) -> Path:
    raw_manifest = read_regular_bytes(manifest_path, "release manifest")
    if len(raw_manifest) > MAX_JSON_BYTES:
        raise ReleaseError(f"release manifest exceeds {MAX_JSON_BYTES} bytes")
    payload = load_json_bytes(raw_manifest, str(manifest_path))
    validate_release_manifest(payload)
    if raw_manifest != canonical_bytes(payload):
        raise ReleaseError("release manifest is not canonical JSON")
    private_key = _load_private_key_from_environment(private_key_env)
    entry = _public_entry(private_key)
    signature = private_key.sign(raw_manifest)
    envelope = {
        "schemaVersion": SIGNATURE_SCHEMA_VERSION,
        "algorithm": "Ed25519",
        "keyId": entry["keyId"],
        "manifestSha256": hashlib.sha256(raw_manifest).hexdigest(),
        "signature": base64.b64encode(signature).decode("ascii"),
    }
    validate_signature_envelope(envelope)
    signature_path = Path(str(manifest_path) + SIGNATURE_SUFFIX)
    _write_canonical_new(signature_path, envelope)
    if public_output is not None:
        _write_canonical_new(
            public_output,
            {"schemaVersion": KEYRING_SCHEMA_VERSION, "keys": [entry]},
        )
    return signature_path


def verify_signature(
    manifest_path: Path, signature_path: Path, keyring_path: Path
) -> dict[str, Any]:
    _require_crypto()
    expected_signature_path = Path(str(manifest_path) + SIGNATURE_SUFFIX)
    if signature_path.resolve() != expected_signature_path.resolve():
        raise ReleaseError("signature path must be the manifest path with .sig appended")
    raw_manifest = read_regular_bytes(manifest_path, "release manifest")
    if len(raw_manifest) > MAX_JSON_BYTES:
        raise ReleaseError(f"release manifest exceeds {MAX_JSON_BYTES} bytes")
    manifest = load_json_bytes(raw_manifest, str(manifest_path))
    validate_release_manifest(manifest)
    if raw_manifest != canonical_bytes(manifest):
        raise ReleaseError("release manifest is not canonical JSON")
    raw_envelope = read_regular_bytes(signature_path, "release signature")
    if len(raw_envelope) > MAX_JSON_BYTES:
        raise ReleaseError(f"release signature exceeds {MAX_JSON_BYTES} bytes")
    envelope = load_json_bytes(raw_envelope, str(signature_path))
    validate_signature_envelope(envelope)
    if raw_envelope != canonical_bytes(envelope):
        raise ReleaseError("release signature envelope is not canonical JSON")
    digest = hashlib.sha256(raw_manifest).hexdigest()
    if envelope["manifestSha256"] != digest:
        raise ReleaseError("signature envelope manifest hash does not match")
    raw_keyring = read_regular_bytes(keyring_path, "release keyring")
    if len(raw_keyring) > MAX_JSON_BYTES:
        raise ReleaseError(f"release keyring exceeds {MAX_JSON_BYTES} bytes")
    keys = validate_keyring(load_json_bytes(raw_keyring, str(keyring_path)))
    raw_public_key = keys.get(envelope["keyId"])
    if raw_public_key is None:
        raise ReleaseError("signature keyId is not in the trusted keyring")
    signature = base64.b64decode(envelope["signature"], validate=True)
    try:
        Ed25519PublicKey.from_public_bytes(raw_public_key).verify(signature, raw_manifest)
    except InvalidSignature as exc:
        raise ReleaseError("release manifest Ed25519 signature is invalid") from exc
    return manifest


def _verify_payload(
    manifest: dict[str, Any],
    payload_directory: Path,
    output_stream: BinaryIO | None = None,
) -> None:
    if not payload_directory.is_dir() or payload_directory.is_symlink():
        raise ReleaseError("payload directory must be a non-symlink directory")
    report = payload_directory / manifest["smoke"]["reportFilename"]
    report_bytes = read_regular_bytes(report, "smoke report")
    if len(report_bytes) > MAX_JSON_BYTES:
        raise ReleaseError(f"smoke report exceeds {MAX_JSON_BYTES} bytes")
    report_hash = hashlib.sha256(report_bytes).hexdigest()
    if report_hash != manifest["smoke"]["reportSha256"]:
        raise ReleaseError("smoke report hash does not match release manifest")
    report_payload = load_json_bytes(report_bytes, str(report))
    if report_payload.get("passed") is not True:
        raise ReleaseError("downloaded smoke report is not successful")
    if report_payload.get("runtimeId") != manifest["runtime"]["buildId"]:
        raise ReleaseError("downloaded smoke report buildId does not match")

    whole_digest = hashlib.sha256()
    whole_size = 0
    for part in manifest["artifact"]["parts"]:
        path = payload_directory / part["filename"]
        details = _regular_file(path, "artifact part")
        if details.st_size != part["sizeBytes"]:
            raise ReleaseError(f"artifact part size does not match: {part['filename']}")
        part_digest = hashlib.sha256()
        part_size = 0
        with path.open("rb") as stream:
            while block := stream.read(1024 * 1024):
                part_digest.update(block)
                whole_digest.update(block)
                part_size += len(block)
                whole_size += len(block)
                if output_stream is not None:
                    output_stream.write(block)
        if part_size != part["sizeBytes"] or part_digest.hexdigest() != part["sha256"]:
            raise ReleaseError(f"artifact part hash does not match: {part['filename']}")
    artifact = manifest["artifact"]
    if whole_size != artifact["sizeBytes"] or whole_digest.hexdigest() != artifact["sha256"]:
        raise ReleaseError("reassembled artifact hash or size does not match")


def verify_release(
    manifest_path: Path,
    signature_path: Path,
    keyring_path: Path,
    payload_directory: Path,
) -> None:
    manifest = verify_signature(manifest_path, signature_path, keyring_path)
    _verify_payload(manifest, payload_directory)


def reassemble_release(
    manifest_path: Path,
    signature_path: Path,
    keyring_path: Path,
    payload_directory: Path,
    output: Path,
) -> None:
    if output.exists() or output.is_symlink():
        raise ReleaseError(f"refusing to overwrite reassembled artifact: {output}")
    manifest = verify_signature(manifest_path, signature_path, keyring_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(f".{output.name}.partial-{uuid.uuid4().hex}")
    try:
        with temporary.open("xb") as stream:
            _verify_payload(manifest, payload_directory, stream)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.rename(output)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def _positive_integer(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be positive")
    return parsed


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    keygen = subparsers.add_parser("keygen", help="create an Ed25519 signing key")
    keygen.add_argument("--private-key-output", type=Path, required=True)
    keygen.add_argument("--public-key-output", type=Path, required=True)

    extract = subparsers.add_parser(
        "extract-manifest",
        help="recover a validated manifest sidecar from a rootfs tar",
    )
    extract.add_argument("--rootfs", type=Path, required=True)
    extract.add_argument("--output", type=Path, required=True)

    package = subparsers.add_parser("package", help="split and describe a smoked rootfs")
    package.add_argument("--rootfs", type=Path, required=True)
    package.add_argument("--runtime-manifest", type=Path, required=True)
    package.add_argument("--smoke-report", type=Path, required=True)
    package.add_argument("--output-directory", type=Path, required=True)
    package.add_argument("--base-url", required=True)
    package.add_argument("--build-timestamp", required=True)
    package.add_argument("--part-bytes", type=_positive_integer, default=DEFAULT_PART_BYTES)
    package.add_argument(
        "--minimum-free-bytes",
        type=_positive_integer,
        default=DEFAULT_MINIMUM_FREE_BYTES,
    )

    sign = subparsers.add_parser("sign", help="sign canonical release manifest bytes")
    sign.add_argument("--manifest", type=Path, required=True)
    sign.add_argument("--private-key-env", default=PRIVATE_KEY_ENV_DEFAULT)
    sign.add_argument("--public-key-output", type=Path)

    verify = subparsers.add_parser("verify", help="verify signature and downloaded payload")
    verify.add_argument("--manifest", type=Path, required=True)
    verify.add_argument("--signature", type=Path, required=True)
    verify.add_argument("--keyring", type=Path, required=True)
    verify.add_argument("--payload-directory", type=Path, required=True)

    reassemble = subparsers.add_parser(
        "reassemble", help="verify and atomically reassemble the WSL rootfs"
    )
    reassemble.add_argument("--manifest", type=Path, required=True)
    reassemble.add_argument("--signature", type=Path, required=True)
    reassemble.add_argument("--keyring", type=Path, required=True)
    reassemble.add_argument("--payload-directory", type=Path, required=True)
    reassemble.add_argument("--output", type=Path, required=True)
    return parser


def main() -> int:
    args = _build_parser().parse_args()
    try:
        if args.command == "keygen":
            key_id = generate_key(args.private_key_output, args.public_key_output)
            print(f"created Ed25519 release key {key_id}")
            print(f"private key written securely to {args.private_key_output}")
        elif args.command == "extract-manifest":
            extract_embedded_manifest(args.rootfs, args.output)
            print(f"recovered validated embedded manifest at {args.output}")
        elif args.command == "package":
            manifest = package_release(
                rootfs=args.rootfs,
                runtime_manifest_path=args.runtime_manifest,
                smoke_report_path=args.smoke_report,
                output_directory=args.output_directory,
                base_url=args.base_url,
                build_timestamp=args.build_timestamp,
                part_bytes=args.part_bytes,
                minimum_free_bytes=args.minimum_free_bytes,
            )
            print(f"created unsigned release payload at {manifest.parent}")
        elif args.command == "sign":
            signature = sign_manifest(args.manifest, args.private_key_env, args.public_key_output)
            print(f"created detached signature {signature}")
        elif args.command == "verify":
            verify_release(args.manifest, args.signature, args.keyring, args.payload_directory)
            print("release signature, smoke evidence, parts, and whole artifact verified")
        else:
            reassemble_release(
                args.manifest,
                args.signature,
                args.keyring,
                args.payload_directory,
                args.output,
            )
            print(f"verified and reassembled {args.output}")
    except (OSError, json.JSONDecodeError, ReleaseError, ValueError) as exc:
        print(f"runtime release error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
