"""Compile verified delivery manifests into a benchmark execution observation.

The compatibility verifier deliberately accepts sanitized observations instead
of reading a machine.  This module closes the preceding trust boundary: it
parses exact canonical Runtime Base and Engine Pack manifest bytes, requires
verification receipts from the native/runtime adapters, and only then creates
the observation consumed by :mod:`app.benchmarking.composite_inventory`.

There is intentionally no filesystem, WSL, desktop, provider, simulator, or
network access here and no API request model or route.  The adapter receipts
are produced by privileged platform code; a benchmark caller cannot replace
them with frontend-supplied component identities.
"""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Annotated, Any, Final, Literal
from urllib.parse import unquote, urlsplit

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.benchmarking.composite_inventory import (
    CompositeExecutionObservationV1,
    CompositeExecutionVerificationReceiptV1,
    DesktopCompatibilityObservationV1,
    EnginePackCompatibilityObservationV1,
    RuntimeBaseCompatibilityObservationV1,
    VerifiedExecutionComponentObservationV1,
    verify_composite_execution_inventory,
)
from app.benchmarking.contracts import (
    CompositeExecutionInventoryV1,
    ExecutionComponentV1,
    GitCommit,
    Sha256Hex,
    canonical_sha256,
)

MAX_MANIFEST_BYTES: Final[int] = 1_048_576
MAX_RUNTIME_PARTS: Final[int] = 64
MAX_RUNTIME_ARTIFACT_BYTES: Final[int] = 12 * 1024**3
MAX_RUNTIME_PART_BYTES_EXCLUSIVE: Final[int] = 2 * 1024**3
MINIMUM_RUNTIME_FREE_BYTES: Final[int] = 52 * 1024**3
REQUIRED_RUNTIME_SMOKE_CHECKS: Final[frozenset[str]] = frozenset(
    {
        "component_versions",
        "python_imports",
        "valkey_ping",
        "api_worker_heartbeat",
        "real_cli_dry_run",
        "px4_gazebo_headless",
        "parameter_readback",
    }
)

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_GIT_COMMIT = re.compile(r"^[0-9a-f]{40}$")
_SEMVER = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")
_PYTHON_VERSION = re.compile(r"^[0-9]+\.[0-9]+$")
_SAFE_FILENAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,199}$")
_SAFE_PATH = re.compile(r"^[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)*$")
_FIELD_ENGINE_PROFILE: Final[dict[str, Any]] = {
    "profileId": "field-lightweight",
    "includesLargeSimulator": False,
    "excludedSourcePaths": ["backend/app/simulator", "scripts/simulators"],
}
_UNIFIED_ENGINE_PROFILE: Final[dict[str, Any]] = {
    "profileId": "unified-sim-lab",
    "includesLargeSimulator": True,
    "excludedSourcePaths": [],
}
_SIM_ENGINE_PROFILE_KEYS: Final[set[str]] = {
    "profileId",
    "profileVersion",
    "profileManifestPath",
    "profileManifestSha256",
    "includesLargeSimulator",
    "excludedSourcePaths",
}


class CompositeObservationCompilationError(ValueError):
    """Raised when canonical manifest bytes and trusted attestations disagree."""


class _StrictFrozen(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class RuntimeManifestAttestationV1(_StrictFrozen):
    """Result of native/runtime verification of one installed Runtime artifact."""

    schema_id: Literal["dronedream.runtime-manifest-attestation/v1"] = (
        "dronedream.runtime-manifest-attestation/v1"
    )
    signed_release_manifest_sha256: Sha256Hex
    signed_release_signature_sha256: Sha256Hex
    trusted_keyring_sha256: Sha256Hex
    installed_runtime_manifest_sha256: Sha256Hex
    runtime_artifact_sha256: Sha256Hex
    runtime_artifact_size_bytes: Annotated[int, Field(gt=0, le=MAX_RUNTIME_ARTIFACT_BYTES)]
    signed_release_verified: Literal[True] = True
    artifact_hash_verified: Literal[True] = True
    embedded_manifest_matches_artifact: Literal[True] = True
    installed_runtime_ownership_verified: Literal[True] = True
    verification_receipt_sha256: Sha256Hex


class EnginePackManifestAttestationV1(_StrictFrozen):
    """Result of verifying a bundle descriptor, archive, and active manifest."""

    schema_id: Literal["dronedream.engine-pack-manifest-attestation/v1"] = (
        "dronedream.engine-pack-manifest-attestation/v1"
    )
    descriptor_sha256: Sha256Hex
    manifest_sha256: Sha256Hex
    archive_sha256: Sha256Hex
    archive_size_bytes: Annotated[int, Field(gt=0, le=MAX_RUNTIME_ARTIFACT_BYTES)]
    descriptor_verified: Literal[True] = True
    archive_hash_verified: Literal[True] = True
    embedded_manifest_matches_sidecar: Literal[True] = True
    active_release_matches_manifest: Literal[True] = True
    payload_file_inventory_verified: Literal[True] = True
    verification_receipt_sha256: Sha256Hex


class DesktopComponentAttestationV1(_StrictFrozen):
    """Sanitized native receipt for the optional installed desktop component."""

    schema_id: Literal["dronedream.desktop-component-attestation/v1"] = (
        "dronedream.desktop-component-attestation/v1"
    )
    component: ExecutionComponentV1
    manifest_bytes_sha256: Sha256Hex
    artifact_bytes_sha256: Sha256Hex
    release_manifest_verified: Literal[True] = True
    source_inventory_verified: Literal[True] = True
    updater_signature_verified: Literal[True] = True
    supported_runtime_product_id: Literal["DroneDreamRuntime"] = "DroneDreamRuntime"
    expected_engine_api_version: Literal[1] = 1
    verification_receipt_sha256: Sha256Hex

    @model_validator(mode="after")
    def _bind_component_bytes(self) -> DesktopComponentAttestationV1:
        if self.component.manifest_sha256 != self.manifest_bytes_sha256:
            raise ValueError("desktop manifest bytes do not match its component")
        if self.component.artifact_sha256 != self.artifact_bytes_sha256:
            raise ValueError("desktop artifact bytes do not match its component")
        if self.component.source_commit is None:
            raise ValueError("desktop attestation requires a source commit")
        return self


class CompositeObservationBindingsV1(_StrictFrozen):
    """Frozen non-binary identities supplied by the campaign coordinator."""

    schema_id: Literal["dronedream.composite-observation-bindings/v1"] = (
        "dronedream.composite-observation-bindings/v1"
    )
    repository_subject_commit: GitCommit
    evaluator_subject_commit: GitCommit
    campaign_coordinator_subject_commit: GitCommit
    evidence_head_commit: GitCommit | None = None
    prompt_registry_sha256: Sha256Hex
    response_schema_sha256: Sha256Hex
    tool_registry_sha256: Sha256Hex
    model_matrix_sha256: Sha256Hex
    machine_profile_sha256: Sha256Hex
    concurrency_profile_sha256: Sha256Hex
    observation_adapter_receipt_sha256: Sha256Hex


class CompositeExecutionCompilationV1(_StrictFrozen):
    schema_id: Literal["dronedream.composite-execution-compilation/v1"] = (
        "dronedream.composite-execution-compilation/v1"
    )
    execution_authorized: Literal[False] = False
    observation: CompositeExecutionObservationV1
    verification: CompositeExecutionVerificationReceiptV1
    runtime_release_manifest_sha256: Sha256Hex
    runtime_installed_manifest_sha256: Sha256Hex
    engine_pack_descriptor_sha256: Sha256Hex
    engine_pack_manifest_sha256: Sha256Hex
    runtime_attestation_sha256: Sha256Hex
    engine_pack_attestation_sha256: Sha256Hex
    desktop_attestation_sha256: Sha256Hex | None = None

    @model_validator(mode="after")
    def _bind_verification(self) -> CompositeExecutionCompilationV1:
        if self.verification.observation_sha256 != canonical_sha256(self.observation):
            raise ValueError("compiled verification does not bind its observation")
        return self


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _reject_duplicate_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise CompositeObservationCompilationError(
                f"manifest JSON contains duplicate key: {key}"
            )
        result[key] = value
    return result


def _load_json_bytes(raw: bytes, *, label: str) -> dict[str, Any]:
    if not raw or len(raw) > MAX_MANIFEST_BYTES:
        raise CompositeObservationCompilationError(
            f"{label} must contain 1..{MAX_MANIFEST_BYTES} bytes"
        )
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise CompositeObservationCompilationError(f"{label} is not UTF-8") from exc
    try:
        value = json.loads(text, object_pairs_hook=_reject_duplicate_object)
    except (json.JSONDecodeError, CompositeObservationCompilationError) as exc:
        raise CompositeObservationCompilationError(f"{label} is invalid JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise CompositeObservationCompilationError(f"{label} must be a JSON object")
    return value


def _canonical_compact(value: Mapping[str, Any] | list[dict[str, Any]], *, newline: bool) -> bytes:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return payload + (b"\n" if newline else b"")


def _canonical_runtime(value: Mapping[str, Any]) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _require_exact_keys(value: Mapping[str, Any], keys: set[str], *, label: str) -> None:
    if set(value) != keys:
        raise CompositeObservationCompilationError(f"{label} fields do not match the frozen schema")


def _mapping(value: object, *, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise CompositeObservationCompilationError(f"{label} must be an object")
    return value


def _safe_text(value: object, *, label: str, maximum: int = 256) -> str:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > maximum
        or any(ord(character) < 32 or 127 <= ord(character) <= 159 for character in value)
    ):
        raise CompositeObservationCompilationError(f"{label} is invalid")
    return value


def _sha(value: object, *, label: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise CompositeObservationCompilationError(f"{label} is not a SHA-256 value")
    return value


def _commit(value: object, *, label: str) -> str:
    if not isinstance(value, str) or _GIT_COMMIT.fullmatch(value) is None:
        raise CompositeObservationCompilationError(f"{label} is not a full Git commit")
    return value


def _uuid(value: object, *, label: str) -> str:
    if not isinstance(value, str):
        raise CompositeObservationCompilationError(f"{label} is not a UUID")
    try:
        parsed = uuid.UUID(value)
    except ValueError as exc:
        raise CompositeObservationCompilationError(f"{label} is not a UUID") from exc
    if str(parsed) != value:
        raise CompositeObservationCompilationError(f"{label} is not canonical")
    return value


def _runtime_identity(
    *,
    version: str,
    source_commit: str,
    ubuntu_image: str,
    px4_commit: str,
    valkey_commit: str,
    python_lock_sha256: str,
) -> str:
    identity = "|".join(
        (
            version,
            source_commit,
            ubuntu_image,
            px4_commit,
            valkey_commit,
            python_lock_sha256,
        )
    )
    return str(uuid.uuid5(uuid.NAMESPACE_URL, "https://dronedream/runtime/" + identity))


def _https_url(value: object, *, label: str, filename: str | None = None) -> str:
    text = _safe_text(value, label=label, maximum=2048)
    parsed = urlsplit(text)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise CompositeObservationCompilationError(f"{label} is not credential-free HTTPS")
    if filename is not None:
        final = unquote(parsed.path.rstrip("/").rsplit("/", 1)[-1])
        if final != filename:
            raise CompositeObservationCompilationError(f"{label} does not bind its filename")
    return text


def _safe_filename(value: object, *, label: str) -> str:
    if not isinstance(value, str) or _SAFE_FILENAME.fullmatch(value) is None:
        raise CompositeObservationCompilationError(f"{label} is not a safe filename")
    return value


def _rfc3339_utc(value: object, *, label: str) -> str:
    text = _safe_text(value, label=label, maximum=64)
    if not text.endswith("Z"):
        raise CompositeObservationCompilationError(f"{label} is not UTC RFC3339")
    try:
        parsed = datetime.fromisoformat(text[:-1] + "+00:00")
    except ValueError as exc:
        raise CompositeObservationCompilationError(f"{label} is not UTC RFC3339") from exc
    if parsed.utcoffset() != UTC.utcoffset(parsed):
        raise CompositeObservationCompilationError(f"{label} is not UTC RFC3339")
    return text


def _validate_runtime_manifest(raw: bytes) -> dict[str, Any]:
    manifest = _load_json_bytes(raw, label="installed Runtime manifest")
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
        label="installed Runtime manifest",
    )
    if raw != _canonical_runtime(manifest):
        raise CompositeObservationCompilationError(
            "installed Runtime manifest is not canonical generated JSON"
        )
    if type(manifest["schemaVersion"]) is not int or manifest["schemaVersion"] != 1:
        raise CompositeObservationCompilationError("Runtime manifest schema is unsupported")
    runtime_id = _uuid(manifest["runtimeId"], label="runtimeId")
    version = _safe_text(manifest["version"], label="Runtime version", maximum=64)
    if _SEMVER.fullmatch(version) is None:
        raise CompositeObservationCompilationError("Runtime version is not semantic")

    target = _mapping(manifest["target"], label="Runtime target")
    _require_exact_keys(
        target, {"os", "version", "codename", "arch", "format"}, label="Runtime target"
    )
    if (
        target["os"] != "ubuntu"
        or target["arch"] != "amd64"
        or target["format"] != "wsl2-rootfs-tar"
    ):
        raise CompositeObservationCompilationError("Runtime target is unsupported")
    _safe_text(target["version"], label="Runtime target version")
    _safe_text(target["codename"], label="Runtime target codename")

    source = _mapping(manifest["source"], label="Runtime source")
    _require_exact_keys(source, {"droneDreamCommit"}, label="Runtime source")
    source_commit = _commit(source["droneDreamCommit"], label="Runtime source commit")
    components = _mapping(manifest["components"], label="Runtime components")
    _require_exact_keys(components, {"backend", "px4", "gazebo"}, label="Runtime components")

    details = _mapping(manifest["componentDetails"], label="Runtime componentDetails")
    detail_fields = {
        "ubuntu": {"image", "indexDigest"},
        "px4": {"version", "commit"},
        "gazebo": {"release", "packageVersion", "aptKeySha256"},
        "backend": {"version", "commit"},
        "worker": {"version", "commit"},
        "valkey": {"version", "commit"},
        "python": {"version"},
        "mavsdk": {"version"},
        "pyulog": {"version"},
    }
    _require_exact_keys(details, set(detail_fields), label="Runtime componentDetails")
    normalized_details: dict[str, dict[str, Any]] = {}
    for component, fields in detail_fields.items():
        item = _mapping(details[component], label=f"componentDetails.{component}")
        _require_exact_keys(item, fields, label=f"componentDetails.{component}")
        normalized_details[component] = item

    ubuntu = normalized_details["ubuntu"]
    px4 = normalized_details["px4"]
    gazebo = normalized_details["gazebo"]
    backend = normalized_details["backend"]
    worker = normalized_details["worker"]
    valkey = normalized_details["valkey"]
    ubuntu_image = _safe_text(ubuntu["image"], label="Ubuntu image")
    digest = _safe_text(ubuntu["indexDigest"], label="Ubuntu image digest")
    if not digest.startswith("sha256:"):
        raise CompositeObservationCompilationError("Ubuntu image digest lacks sha256 prefix")
    _sha(digest.removeprefix("sha256:"), label="Ubuntu image digest")
    if re.fullmatch(r"ubuntu:24\.04@sha256:[0-9a-f]{64}", ubuntu_image) is None:
        raise CompositeObservationCompilationError("Ubuntu image identity is unsupported")
    px4_commit = _commit(px4["commit"], label="PX4 commit")
    px4_version = _safe_text(px4["version"], label="PX4 version", maximum=128)
    gazebo_release = _safe_text(gazebo["release"], label="Gazebo release")
    gazebo_package = _safe_text(gazebo["packageVersion"], label="Gazebo package")
    _sha(gazebo["aptKeySha256"], label="Gazebo apt key")
    valkey_commit = _commit(valkey["commit"], label="Valkey commit")
    if backend["commit"] != source_commit or worker["commit"] != source_commit:
        raise CompositeObservationCompilationError(
            "Runtime backend and worker commits do not match its source"
        )
    for name in ("backend", "worker"):
        value = _safe_text(normalized_details[name]["version"], label=f"{name} version")
        if _SEMVER.fullmatch(value) is None:
            raise CompositeObservationCompilationError(f"{name} version is not semantic")
    for name in ("valkey", "mavsdk", "pyulog"):
        _safe_text(normalized_details[name]["version"], label=f"{name} version")
    python_version = _safe_text(
        normalized_details["python"]["version"], label="Python version", maximum=16
    )
    if _PYTHON_VERSION.fullmatch(python_version) is None:
        raise CompositeObservationCompilationError("Python version is invalid")
    gazebo_version = f"{gazebo_release}@{gazebo_package}"
    expected_components = {
        "backend": backend["version"],
        "px4": f"{px4_version}@{px4_commit[:12]}",
        "gazebo": gazebo_version,
    }
    if components != expected_components:
        raise CompositeObservationCompilationError(
            "Runtime component summaries do not match componentDetails"
        )

    locks = _mapping(manifest["locks"], label="Runtime locks")
    _require_exact_keys(locks, {"pinsSha256", "pythonRequirementsSha256"}, label="Runtime locks")
    _sha(locks["pinsSha256"], label="Runtime pins lock")
    python_lock = _sha(locks["pythonRequirementsSha256"], label="Runtime Python dependency lock")
    expected_runtime_id = _runtime_identity(
        version=version,
        source_commit=source_commit,
        ubuntu_image=ubuntu_image,
        px4_commit=px4_commit,
        valkey_commit=valkey_commit,
        python_lock_sha256=python_lock,
    )
    if runtime_id != expected_runtime_id:
        raise CompositeObservationCompilationError(
            "Runtime ID does not match its immutable identity inputs"
        )
    if manifest["artifact"] is not None and not isinstance(manifest["artifact"], dict):
        raise CompositeObservationCompilationError("Runtime artifact is invalid")

    smoke = _mapping(manifest["smokeTests"], label="Runtime smokeTests")
    if smoke != {"px4Sitl": True, "gazebo": True, "parameterReadback": True}:
        raise CompositeObservationCompilationError("Runtime is not smoke-promoted")
    report = _mapping(manifest["smokeReport"], label="Runtime smokeReport")
    if (
        report.get("passed") is not True
        or report.get("mode") != "runtime-image"
        or report.get("runtimeId") != runtime_id
    ):
        raise CompositeObservationCompilationError("Runtime smoke report identity failed")
    _safe_text(report.get("imageId"), label="Runtime smoke image identity")
    _rfc3339_utc(report.get("completedAt"), label="Runtime smoke completion")
    checks = report.get("checks")
    if not isinstance(checks, list) or not checks:
        raise CompositeObservationCompilationError("Runtime smoke checks are missing")
    names: set[str] = set()
    for check in checks:
        if not isinstance(check, dict) or check.get("passed") is not True:
            raise CompositeObservationCompilationError(
                "Runtime smoke report contains a failed check"
            )
        name = _safe_text(check.get("name"), label="Runtime smoke check name")
        duration = check.get("durationSeconds")
        if type(duration) is not int or duration < 0:
            raise CompositeObservationCompilationError("Runtime smoke check duration is invalid")
        if name in names:
            raise CompositeObservationCompilationError(
                "Runtime smoke report contains duplicate checks"
            )
        names.add(name)
    if not REQUIRED_RUNTIME_SMOKE_CHECKS.issubset(names):
        raise CompositeObservationCompilationError(
            "Runtime smoke report is missing required checks"
        )
    return manifest


def _validate_runtime_release(raw: bytes) -> dict[str, Any]:
    manifest = _load_json_bytes(raw, label="signed Runtime release manifest")
    _require_exact_keys(
        manifest,
        {"schemaVersion", "runtime", "source", "artifact", "smoke", "requirements"},
        label="Runtime release manifest",
    )
    if raw != _canonical_compact(manifest, newline=False):
        raise CompositeObservationCompilationError("Runtime release manifest is not canonical JSON")
    if type(manifest["schemaVersion"]) is not int or manifest["schemaVersion"] != 1:
        raise CompositeObservationCompilationError("Runtime release schema is unsupported")
    runtime = _mapping(manifest["runtime"], label="release runtime")
    _require_exact_keys(
        runtime,
        {"id", "buildId", "version", "architecture", "wslVersion"},
        label="release runtime",
    )
    if runtime["id"] != "DroneDreamRuntime" or runtime["architecture"] != "x86_64":
        raise CompositeObservationCompilationError("Runtime release target is unsupported")
    if type(runtime["wslVersion"]) is not int or runtime["wslVersion"] != 2:
        raise CompositeObservationCompilationError("Runtime release requires WSL2")
    _uuid(runtime["buildId"], label="Runtime release build ID")
    version = _safe_text(runtime["version"], label="Runtime release version", maximum=64)
    if _SEMVER.fullmatch(version) is None:
        raise CompositeObservationCompilationError("Runtime release version is invalid")

    source = _mapping(manifest["source"], label="release source")
    _require_exact_keys(
        source,
        {"gitCommit", "px4Commit", "gazeboVersion", "buildTimestamp"},
        label="release source",
    )
    _commit(source["gitCommit"], label="Runtime release source commit")
    _commit(source["px4Commit"], label="Runtime release PX4 commit")
    _safe_text(source["gazeboVersion"], label="Runtime release Gazebo version")
    _rfc3339_utc(source["buildTimestamp"], label="Runtime release build timestamp")

    artifact = _mapping(manifest["artifact"], label="release artifact")
    _require_exact_keys(
        artifact,
        {"filename", "mediaType", "compression", "sizeBytes", "sha256", "parts"},
        label="release artifact",
    )
    artifact_filename = _safe_filename(artifact["filename"], label="Runtime artifact filename")
    if artifact["mediaType"] != "application/vnd.dronedream.wsl-rootfs+tar":
        raise CompositeObservationCompilationError("Runtime artifact media type is invalid")
    if artifact["compression"] != "none":
        raise CompositeObservationCompilationError("Runtime artifact compression is invalid")
    size_bytes = artifact["sizeBytes"]
    if type(size_bytes) is not int or size_bytes <= 0 or size_bytes > MAX_RUNTIME_ARTIFACT_BYTES:
        raise CompositeObservationCompilationError("Runtime artifact size is invalid")
    _sha(artifact["sha256"], label="Runtime artifact hash")
    parts = artifact["parts"]
    if not isinstance(parts, list) or not 1 <= len(parts) <= MAX_RUNTIME_PARTS:
        raise CompositeObservationCompilationError("Runtime release parts are invalid")
    part_names: set[str] = set()
    part_urls: set[str] = set()
    part_size_sum = 0
    for expected_index, part_value in enumerate(parts):
        part = _mapping(part_value, label=f"Runtime release part {expected_index}")
        _require_exact_keys(
            part,
            {"index", "filename", "sizeBytes", "sha256", "url"},
            label="Runtime release part",
        )
        if type(part["index"]) is not int or part["index"] != expected_index:
            raise CompositeObservationCompilationError(
                "Runtime release part indexes are not contiguous"
            )
        filename = _safe_filename(part["filename"], label="Runtime part filename")
        if filename == artifact_filename or filename in part_names:
            raise CompositeObservationCompilationError("Runtime part filename is duplicated")
        part_names.add(filename)
        part_size = part["sizeBytes"]
        if (
            type(part_size) is not int
            or part_size <= 0
            or part_size >= MAX_RUNTIME_PART_BYTES_EXCLUSIVE
        ):
            raise CompositeObservationCompilationError("Runtime part size is invalid")
        part_size_sum += part_size
        _sha(part["sha256"], label="Runtime part hash")
        url = _https_url(part["url"], label="Runtime part URL", filename=filename)
        if url in part_urls:
            raise CompositeObservationCompilationError("Runtime part URL is duplicated")
        part_urls.add(url)
    if part_size_sum != size_bytes:
        raise CompositeObservationCompilationError("Runtime part sizes do not match the artifact")

    smoke = _mapping(manifest["smoke"], label="release smoke")
    _require_exact_keys(
        smoke,
        {"passed", "reportFilename", "reportSha256", "reportUrl", "completedAt"},
        label="release smoke",
    )
    if smoke["passed"] is not True:
        raise CompositeObservationCompilationError("Runtime release smoke did not pass")
    report_filename = _safe_filename(smoke["reportFilename"], label="Runtime smoke report filename")
    _sha(smoke["reportSha256"], label="Runtime smoke report hash")
    _https_url(smoke["reportUrl"], label="Runtime smoke report URL", filename=report_filename)
    _rfc3339_utc(smoke["completedAt"], label="Runtime smoke completedAt")

    requirements = _mapping(manifest["requirements"], label="Runtime requirements")
    _require_exact_keys(
        requirements, {"minimumFreeBytes", "targetPathHint"}, label="Runtime requirements"
    )
    minimum_free = requirements["minimumFreeBytes"]
    if (
        type(minimum_free) is not int
        or minimum_free < MINIMUM_RUNTIME_FREE_BYTES
        or minimum_free <= size_bytes
        or requirements["targetPathHint"] != "X:\\DroneDream"
    ):
        raise CompositeObservationCompilationError("Runtime requirements are invalid")
    return manifest


def _validate_file_records(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, list) or not value:
        raise CompositeObservationCompilationError("Engine Pack file inventory is empty")
    records: list[dict[str, Any]] = []
    paths: list[str] = []
    for record_value in value:
        record = _mapping(record_value, label="Engine Pack file record")
        _require_exact_keys(record, {"path", "sizeBytes", "sha256"}, label="file record")
        path = record["path"]
        if not isinstance(path, str) or _SAFE_PATH.fullmatch(path) is None:
            raise CompositeObservationCompilationError("Engine Pack file path is unsafe")
        size = record["sizeBytes"]
        if type(size) is not int or size < 0:
            raise CompositeObservationCompilationError("Engine Pack file size is invalid")
        _sha(record["sha256"], label="Engine Pack file hash")
        paths.append(path)
        records.append(record)
    if paths != sorted(set(paths)):
        raise CompositeObservationCompilationError(
            "Engine Pack file inventory is not unique and sorted"
        )
    return records


def _engine_payload_identity(records: list[dict[str, Any]]) -> str:
    identity = hashlib.sha256()
    for record in records:
        identity.update(record["path"].encode("utf-8"))
        identity.update(b"\0")
        identity.update(str(record["sizeBytes"]).encode("ascii"))
        identity.update(b"\0")
        identity.update(record["sha256"].encode("ascii"))
        identity.update(b"\n")
    return identity.hexdigest()


def _engine_manifest_identity(
    source: dict[str, Any],
    edition_profile: dict[str, Any],
    compatibility: dict[str, Any],
    records: list[dict[str, Any]],
) -> str:
    return _sha256_bytes(
        _canonical_compact(
            {
                "engineApiVersion": 1,
                "source": source,
                "editionProfile": edition_profile,
                "runtimeCompatibility": compatibility,
                "payloadSha256": _engine_payload_identity(records),
                "files": records,
            },
            newline=True,
        )
    )


def _validate_engine_edition_profile(value: object) -> dict[str, Any]:
    profile = _mapping(value, label="Engine Pack edition profile")
    profile_id = _safe_text(profile.get("profileId"), label="Engine Pack edition profile ID")
    if profile_id == "sim-only":
        _require_exact_keys(
            profile,
            _SIM_ENGINE_PROFILE_KEYS,
            label="Engine Pack edition profile",
        )
        if (
            profile["profileVersion"] != "1.0.0"
            or profile["profileManifestPath"]
            != "distribution/engine-pack-profiles/sim-only.v1.json"
            or not isinstance(profile["profileManifestSha256"], str)
            or _SHA256.fullmatch(profile["profileManifestSha256"]) is None
            or profile["includesLargeSimulator"] is not True
            or profile["excludedSourcePaths"] != ["backend/app/distribution_safety.py"]
        ):
            raise CompositeObservationCompilationError(
                "Engine Pack edition profile is unsupported or internally inconsistent"
            )
        return profile
    _require_exact_keys(
        profile,
        {"profileId", "includesLargeSimulator", "excludedSourcePaths"},
        label="Engine Pack edition profile",
    )
    if type(profile["includesLargeSimulator"]) is not bool:
        raise CompositeObservationCompilationError(
            "Engine Pack edition profile simulator flag is invalid"
        )
    excluded = profile["excludedSourcePaths"]
    if (
        not isinstance(excluded, list)
        or any(
            not isinstance(path, str)
            or _SAFE_PATH.fullmatch(path) is None
            or any(segment in {".", ".."} for segment in path.split("/"))
            for path in excluded
        )
        or len(excluded) != len(set(excluded))
    ):
        raise CompositeObservationCompilationError(
            "Engine Pack edition profile excluded paths are invalid"
        )
    expected = {
        "field-lightweight": _FIELD_ENGINE_PROFILE,
        "unified-sim-lab": _UNIFIED_ENGINE_PROFILE,
    }.get(profile_id)
    if expected is None or profile != expected:
        raise CompositeObservationCompilationError(
            "Engine Pack edition profile is unsupported or internally inconsistent"
        )
    return profile


def _validate_engine_manifest(raw: bytes) -> dict[str, Any]:
    manifest = _load_json_bytes(raw, label="Engine Pack manifest")
    _require_exact_keys(
        manifest,
        {
            "schemaVersion",
            "kind",
            "packId",
            "engineApiVersion",
            "source",
            "editionProfile",
            "runtimeCompatibility",
            "files",
        },
        label="Engine Pack manifest",
    )
    if raw != _canonical_compact(manifest, newline=True):
        raise CompositeObservationCompilationError("Engine Pack manifest is not canonical")
    if (
        type(manifest["schemaVersion"]) is not int
        or manifest["schemaVersion"] != 2
        or manifest["kind"] != "dronedream-engine-pack"
        or type(manifest["engineApiVersion"]) is not int
        or manifest["engineApiVersion"] != 1
    ):
        raise CompositeObservationCompilationError("Engine Pack identity is unsupported")
    source = _mapping(manifest["source"], label="Engine Pack source")
    _require_exact_keys(source, {"gitCommit", "sourceDateEpoch"}, label="Engine Pack source")
    _commit(source["gitCommit"], label="Engine Pack source commit")
    if type(source["sourceDateEpoch"]) is not int or source["sourceDateEpoch"] < 0:
        raise CompositeObservationCompilationError("Engine Pack source epoch is invalid")
    edition_profile = _validate_engine_edition_profile(manifest["editionProfile"])
    compatibility = _mapping(
        manifest["runtimeCompatibility"], label="Engine Pack Runtime compatibility"
    )
    _require_exact_keys(
        compatibility,
        {
            "runtimeProductId",
            "runtimeVersion",
            "pythonVersion",
            "px4Commit",
            "gazeboVersion",
            "dependencyLockSha256",
        },
        label="Engine Pack Runtime compatibility",
    )
    if compatibility["runtimeProductId"] != "DroneDreamRuntime":
        raise CompositeObservationCompilationError("Engine Pack Runtime product is invalid")
    runtime_version = _safe_text(
        compatibility["runtimeVersion"], label="Engine Pack Runtime version"
    )
    if _SEMVER.fullmatch(runtime_version) is None:
        raise CompositeObservationCompilationError("Engine Pack Runtime version is invalid")
    python_version = _safe_text(compatibility["pythonVersion"], label="Engine Pack Python version")
    if _PYTHON_VERSION.fullmatch(python_version) is None:
        raise CompositeObservationCompilationError("Engine Pack Python version is invalid")
    _commit(compatibility["px4Commit"], label="Engine Pack PX4 commit")
    _safe_text(compatibility["gazeboVersion"], label="Engine Pack Gazebo version")
    _sha(compatibility["dependencyLockSha256"], label="Engine Pack dependency lock")
    records = _validate_file_records(manifest["files"])
    expected_pack_id = "sha256:" + _engine_manifest_identity(
        source, edition_profile, compatibility, records
    )
    if manifest["packId"] != expected_pack_id:
        raise CompositeObservationCompilationError(
            "Engine Pack ID does not match its payload identity"
        )
    return manifest


def _validate_engine_descriptor(raw: bytes) -> dict[str, Any]:
    descriptor = _load_json_bytes(raw, label="Engine Pack descriptor")
    _require_exact_keys(
        descriptor,
        {"schemaVersion", "kind", "packId", "sourceCommit", "archive", "manifest"},
        label="Engine Pack descriptor",
    )
    if raw != _canonical_compact(descriptor, newline=True):
        raise CompositeObservationCompilationError("Engine Pack descriptor is not canonical")
    if (
        type(descriptor["schemaVersion"]) is not int
        or descriptor["schemaVersion"] != 1
        or descriptor["kind"] != "dronedream-engine-pack-bundle"
    ):
        raise CompositeObservationCompilationError("Engine Pack descriptor is unsupported")
    pack_id = _safe_text(descriptor["packId"], label="Engine Pack descriptor ID")
    if not pack_id.startswith("sha256:"):
        raise CompositeObservationCompilationError("Engine Pack descriptor ID is invalid")
    _sha(pack_id.removeprefix("sha256:"), label="Engine Pack descriptor ID")
    _commit(descriptor["sourceCommit"], label="Engine Pack descriptor source commit")
    for label, expected_name in (
        ("archive", "DroneDreamEnginePack.tar.gz"),
        ("manifest", "engine-pack-manifest.json"),
    ):
        item = _mapping(descriptor[label], label=f"Engine Pack {label} descriptor")
        _require_exact_keys(item, {"filename", "sizeBytes", "sha256"}, label=f"Engine Pack {label}")
        if item["filename"] != expected_name:
            raise CompositeObservationCompilationError(f"Engine Pack {label} filename is invalid")
        if type(item["sizeBytes"]) is not int or item["sizeBytes"] < 0:
            raise CompositeObservationCompilationError(f"Engine Pack {label} size is invalid")
        _sha(item["sha256"], label=f"Engine Pack {label} hash")
    return descriptor


def _runtime_observations(
    release: dict[str, Any],
    installed: dict[str, Any],
    attestation: RuntimeManifestAttestationV1,
) -> tuple[
    RuntimeBaseCompatibilityObservationV1,
    VerifiedExecutionComponentObservationV1,
    VerifiedExecutionComponentObservationV1,
]:
    runtime_release = release["runtime"]
    release_source = release["source"]
    installed_source = installed["source"]
    details = installed["componentDetails"]
    gazebo_version = f"{details['gazebo']['release']}@{details['gazebo']['packageVersion']}"
    comparisons = (
        (runtime_release["buildId"], installed["runtimeId"], "build ID"),
        (runtime_release["version"], installed["version"], "version"),
        (release_source["gitCommit"], installed_source["droneDreamCommit"], "source"),
        (release_source["px4Commit"], details["px4"]["commit"], "PX4 source"),
        (release_source["gazeboVersion"], gazebo_version, "Gazebo version"),
    )
    for released, active, label in comparisons:
        if released != active:
            raise CompositeObservationCompilationError(
                f"signed Runtime release and installed manifest disagree on {label}"
            )
    runtime_manifest_hash = _sha256_bytes(_canonical_runtime(installed))
    artifact_hash = release["artifact"]["sha256"]
    runtime_component = ExecutionComponentV1(
        component_id="runtime-base",
        version=installed["version"],
        source_commit=installed_source["droneDreamCommit"],
        manifest_sha256=runtime_manifest_hash,
        artifact_sha256=artifact_hash,
    )
    runtime_verified = VerifiedExecutionComponentObservationV1(
        component=runtime_component,
        verification_method="trusted-embedded-manifest",
        manifest_bytes_sha256=runtime_manifest_hash,
        artifact_bytes_sha256=artifact_hash,
        verification_receipt_sha256=attestation.verification_receipt_sha256,
    )
    px4_component = ExecutionComponentV1(
        component_id="px4",
        version=details["px4"]["version"],
        source_commit=details["px4"]["commit"],
        manifest_sha256=runtime_manifest_hash,
        artifact_sha256=None,
    )
    px4_verified = VerifiedExecutionComponentObservationV1(
        component=px4_component,
        verification_method="source-pinned-by-runtime-manifest",
        manifest_bytes_sha256=runtime_manifest_hash,
        artifact_bytes_sha256=None,
        verification_receipt_sha256=attestation.verification_receipt_sha256,
    )
    gazebo_component = ExecutionComponentV1(
        component_id="gazebo",
        version=gazebo_version,
        source_commit=None,
        manifest_sha256=runtime_manifest_hash,
        artifact_sha256=None,
    )
    gazebo_verified = VerifiedExecutionComponentObservationV1(
        component=gazebo_component,
        verification_method="trusted-embedded-manifest",
        manifest_bytes_sha256=runtime_manifest_hash,
        artifact_bytes_sha256=None,
        verification_receipt_sha256=attestation.verification_receipt_sha256,
    )
    runtime_observation = RuntimeBaseCompatibilityObservationV1(
        component_observation=runtime_verified,
        runtime_build_id=installed["runtimeId"],
        runtime_source_commit=installed_source["droneDreamCommit"],
        runtime_version=installed["version"],
        python_version=details["python"]["version"],
        dependency_lock_sha256=installed["locks"]["pythonRequirementsSha256"],
        px4_version=details["px4"]["version"],
        px4_commit=details["px4"]["commit"],
        gazebo_version=gazebo_version,
    )
    return runtime_observation, px4_verified, gazebo_verified


def _engine_observation(
    descriptor: dict[str, Any],
    manifest: dict[str, Any],
    attestation: EnginePackManifestAttestationV1,
) -> EnginePackCompatibilityObservationV1:
    manifest_hash = _sha256_bytes(_canonical_compact(manifest, newline=True))
    comparisons = (
        (descriptor["packId"], manifest["packId"], "pack ID"),
        (descriptor["sourceCommit"], manifest["source"]["gitCommit"], "source"),
        (descriptor["manifest"]["sha256"], manifest_hash, "manifest hash"),
        (
            descriptor["manifest"]["sizeBytes"],
            len(_canonical_compact(manifest, newline=True)),
            "manifest size",
        ),
        (descriptor["archive"]["sha256"], attestation.archive_sha256, "archive hash"),
        (descriptor["archive"]["sizeBytes"], attestation.archive_size_bytes, "archive size"),
    )
    for bundled, observed, label in comparisons:
        if bundled != observed:
            raise CompositeObservationCompilationError(
                f"Engine Pack descriptor and verified payload disagree on {label}"
            )
    compatibility = manifest["runtimeCompatibility"]
    component = ExecutionComponentV1(
        component_id="engine-pack",
        version=manifest["packId"],
        source_commit=manifest["source"]["gitCommit"],
        manifest_sha256=manifest_hash,
        artifact_sha256=attestation.archive_sha256,
    )
    verified = VerifiedExecutionComponentObservationV1(
        component=component,
        verification_method="trusted-embedded-manifest",
        manifest_bytes_sha256=manifest_hash,
        artifact_bytes_sha256=attestation.archive_sha256,
        verification_receipt_sha256=attestation.verification_receipt_sha256,
    )
    return EnginePackCompatibilityObservationV1(
        component_observation=verified,
        pack_id=manifest["packId"],
        engine_source_commit=manifest["source"]["gitCommit"],
        engine_api_version=manifest["engineApiVersion"],
        required_runtime_product_id=compatibility["runtimeProductId"],
        required_runtime_version=compatibility["runtimeVersion"],
        required_python_version=compatibility["pythonVersion"],
        required_dependency_lock_sha256=compatibility["dependencyLockSha256"],
        required_px4_commit=compatibility["px4Commit"],
        required_gazebo_version=compatibility["gazeboVersion"],
    )


def _desktop_observation(
    attestation: DesktopComponentAttestationV1 | None,
) -> DesktopCompatibilityObservationV1 | None:
    if attestation is None:
        return None
    verified = VerifiedExecutionComponentObservationV1(
        component=attestation.component,
        verification_method="signed-release-manifest",
        manifest_bytes_sha256=attestation.manifest_bytes_sha256,
        artifact_bytes_sha256=attestation.artifact_bytes_sha256,
        verification_receipt_sha256=attestation.verification_receipt_sha256,
    )
    return DesktopCompatibilityObservationV1(
        component_observation=verified,
        supported_runtime_product_id=attestation.supported_runtime_product_id,
        expected_engine_api_version=attestation.expected_engine_api_version,
    )


def compile_composite_execution_observation(
    *,
    inventory: CompositeExecutionInventoryV1,
    runtime_release_manifest_bytes: bytes,
    runtime_installed_manifest_bytes: bytes,
    engine_pack_descriptor_bytes: bytes,
    engine_pack_manifest_bytes: bytes,
    runtime_attestation: RuntimeManifestAttestationV1,
    engine_pack_attestation: EnginePackManifestAttestationV1,
    bindings: CompositeObservationBindingsV1,
    desktop_attestation: DesktopComponentAttestationV1 | None = None,
) -> CompositeExecutionCompilationV1:
    """Compile exact verified component bytes; never authorize an execution."""

    release = _validate_runtime_release(runtime_release_manifest_bytes)
    installed = _validate_runtime_manifest(runtime_installed_manifest_bytes)
    descriptor = _validate_engine_descriptor(engine_pack_descriptor_bytes)
    engine_manifest = _validate_engine_manifest(engine_pack_manifest_bytes)
    release_hash = _sha256_bytes(runtime_release_manifest_bytes)
    installed_hash = _sha256_bytes(runtime_installed_manifest_bytes)
    descriptor_hash = _sha256_bytes(engine_pack_descriptor_bytes)
    engine_manifest_hash = _sha256_bytes(engine_pack_manifest_bytes)
    attestation_comparisons = (
        (
            runtime_attestation.signed_release_manifest_sha256,
            release_hash,
            "Runtime signed release manifest",
        ),
        (
            runtime_attestation.installed_runtime_manifest_sha256,
            installed_hash,
            "installed Runtime manifest",
        ),
        (
            runtime_attestation.runtime_artifact_sha256,
            release["artifact"]["sha256"],
            "Runtime artifact",
        ),
        (
            runtime_attestation.runtime_artifact_size_bytes,
            release["artifact"]["sizeBytes"],
            "Runtime artifact size",
        ),
        (engine_pack_attestation.descriptor_sha256, descriptor_hash, "Engine Pack descriptor"),
        (engine_pack_attestation.manifest_sha256, engine_manifest_hash, "Engine Pack manifest"),
        (
            engine_pack_attestation.archive_sha256,
            descriptor["archive"]["sha256"],
            "Engine Pack archive",
        ),
    )
    for attested, observed, label in attestation_comparisons:
        if attested != observed:
            raise CompositeObservationCompilationError(
                f"{label} does not match its trusted attestation"
            )

    runtime_observation, px4_observation, gazebo_observation = _runtime_observations(
        release, installed, runtime_attestation
    )
    engine_observation = _engine_observation(descriptor, engine_manifest, engine_pack_attestation)
    observation = CompositeExecutionObservationV1(
        repository_subject_commit=bindings.repository_subject_commit,
        evaluator_subject_commit=bindings.evaluator_subject_commit,
        campaign_coordinator_subject_commit=bindings.campaign_coordinator_subject_commit,
        evidence_head_commit=bindings.evidence_head_commit,
        desktop=_desktop_observation(desktop_attestation),
        runtime_base=runtime_observation,
        engine_pack=engine_observation,
        px4=px4_observation,
        gazebo=gazebo_observation,
        prompt_registry_sha256=bindings.prompt_registry_sha256,
        response_schema_sha256=bindings.response_schema_sha256,
        tool_registry_sha256=bindings.tool_registry_sha256,
        model_matrix_sha256=bindings.model_matrix_sha256,
        machine_profile_sha256=bindings.machine_profile_sha256,
        concurrency_profile_sha256=bindings.concurrency_profile_sha256,
        observation_adapter_receipt_sha256=(bindings.observation_adapter_receipt_sha256),
    )
    verification = verify_composite_execution_inventory(inventory, observation)
    return CompositeExecutionCompilationV1(
        observation=observation,
        verification=verification,
        runtime_release_manifest_sha256=release_hash,
        runtime_installed_manifest_sha256=installed_hash,
        engine_pack_descriptor_sha256=descriptor_hash,
        engine_pack_manifest_sha256=engine_manifest_hash,
        runtime_attestation_sha256=canonical_sha256(runtime_attestation),
        engine_pack_attestation_sha256=canonical_sha256(engine_pack_attestation),
        desktop_attestation_sha256=(
            canonical_sha256(desktop_attestation) if desktop_attestation is not None else None
        ),
    )


__all__ = [
    "MAX_MANIFEST_BYTES",
    "CompositeExecutionCompilationV1",
    "CompositeObservationBindingsV1",
    "CompositeObservationCompilationError",
    "DesktopComponentAttestationV1",
    "EnginePackManifestAttestationV1",
    "RuntimeManifestAttestationV1",
    "compile_composite_execution_observation",
]
