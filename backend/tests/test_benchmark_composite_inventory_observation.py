from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
import uuid
from pathlib import Path
from types import ModuleType

import pytest
from pydantic import ValidationError

from app.benchmarking.composite_inventory_observation import (
    CompositeObservationBindingsV1,
    CompositeObservationCompilationError,
    DesktopComponentAttestationV1,
    EnginePackManifestAttestationV1,
    RuntimeManifestAttestationV1,
    _validate_engine_edition_profile,
    compile_composite_execution_observation,
)
from app.benchmarking.contracts import CompositeExecutionInventoryV1, canonical_sha256

ROOT = Path(__file__).resolve().parents[2]
_REPOSITORY = "1" * 40
_EVALUATOR = "2" * 40
_COORDINATOR = "3" * 40
_DESKTOP_SOURCE = "4" * 40
_RUNTIME_SOURCE = "5" * 40
_ENGINE_SOURCE = "6" * 40
_SHA = {
    name: f"{index:064x}"
    for index, name in enumerate(
        (
            "desktop_manifest",
            "desktop_artifact",
            "desktop_receipt",
            "runtime_signature",
            "runtime_keyring",
            "runtime_receipt",
            "engine_receipt",
            "prompt",
            "schema",
            "tools",
            "models",
            "machine",
            "concurrency",
            "adapter",
        ),
        start=1,
    )
}


def _load_tool(name: str, relative: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


engine_pack = _load_tool(
    "benchmark_composite_observation_engine_pack",
    "engine-pack/tools/engine_pack.py",
)
runtime_manifest_tool = _load_tool(
    "benchmark_composite_observation_runtime_manifest",
    "runtime/tools/runtime_manifest.py",
)
runtime_release_tool = _load_tool(
    "benchmark_composite_observation_runtime_release",
    "runtime/tools/runtime_release.py",
)


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _runtime_identity(
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


def _canonical_runtime(value: object) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode()


def _canonical_release(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()


def _fixture(*, with_desktop: bool = True) -> dict[str, object]:
    pins = engine_pack.read_pins(ROOT / "runtime/pins.env")
    records = [
        {"path": "backend/app/main.py", "sizeBytes": 4, "sha256": "a" * 64},
        {"path": "worker/drone_dream_worker/main.py", "sizeBytes": 7, "sha256": "b" * 64},
    ]
    engine_manifest = engine_pack.build_manifest(
        ROOT,
        _ENGINE_SOURCE,
        1_722_000_000,
        records,
    )
    engine_manifest_bytes = engine_pack.canonical_json(engine_manifest)
    engine_archive_sha = "c" * 64
    engine_descriptor = {
        "schemaVersion": 1,
        "kind": "dronedream-engine-pack-bundle",
        "packId": engine_manifest["packId"],
        "sourceCommit": _ENGINE_SOURCE,
        "archive": {
            "filename": engine_pack.ARCHIVE_FILENAME,
            "sizeBytes": 4096,
            "sha256": engine_archive_sha,
        },
        "manifest": {
            "filename": engine_pack.MANIFEST_FILENAME,
            "sizeBytes": len(engine_manifest_bytes),
            "sha256": _sha256(engine_manifest_bytes),
        },
    }
    engine_descriptor_bytes = engine_pack.canonical_json(engine_descriptor)

    compatibility = engine_manifest["runtimeCompatibility"]
    python_lock = compatibility["dependencyLockSha256"]
    ubuntu_image = pins["UBUNTU_BASE_IMAGE"]
    runtime_id = _runtime_identity(
        compatibility["runtimeVersion"],
        _RUNTIME_SOURCE,
        ubuntu_image,
        compatibility["px4Commit"],
        pins["VALKEY_GIT_COMMIT"],
        python_lock,
    )
    checks = [
        {"name": name, "passed": True, "durationSeconds": index}
        for index, name in enumerate(
            (
                "component_versions",
                "python_imports",
                "valkey_ping",
                "api_worker_heartbeat",
                "real_cli_dry_run",
                "px4_gazebo_headless",
                "parameter_readback",
            )
        )
    ]
    runtime_manifest = {
        "schemaVersion": 1,
        "runtimeId": runtime_id,
        "version": compatibility["runtimeVersion"],
        "target": {
            "os": "ubuntu",
            "version": pins["UBUNTU_VERSION"],
            "codename": pins["UBUNTU_CODENAME"],
            "arch": "amd64",
            "format": "wsl2-rootfs-tar",
        },
        "source": {"droneDreamCommit": _RUNTIME_SOURCE},
        "components": {
            "backend": pins["BACKEND_VERSION"],
            "px4": f"{pins['PX4_VERSION']}@{pins['PX4_GIT_COMMIT'][:12]}",
            "gazebo": f"{pins['GAZEBO_RELEASE']}@{pins['GAZEBO_METAPACKAGE_VERSION']}",
        },
        "componentDetails": {
            "ubuntu": {
                "image": ubuntu_image,
                "indexDigest": pins["UBUNTU_INDEX_DIGEST"],
            },
            "px4": {"version": pins["PX4_VERSION"], "commit": pins["PX4_GIT_COMMIT"]},
            "gazebo": {
                "release": pins["GAZEBO_RELEASE"],
                "packageVersion": pins["GAZEBO_METAPACKAGE_VERSION"],
                "aptKeySha256": pins["GAZEBO_APT_KEY_SHA256"],
            },
            "backend": {"version": pins["BACKEND_VERSION"], "commit": _RUNTIME_SOURCE},
            "worker": {"version": pins["WORKER_VERSION"], "commit": _RUNTIME_SOURCE},
            "valkey": {
                "version": pins["VALKEY_VERSION"],
                "commit": pins["VALKEY_GIT_COMMIT"],
            },
            "python": {"version": pins["PYTHON_VERSION"]},
            "mavsdk": {"version": pins["MAVSDK_VERSION"]},
            "pyulog": {"version": pins["PYULOG_VERSION"]},
        },
        "locks": {"pinsSha256": "d" * 64, "pythonRequirementsSha256": python_lock},
        "smokeTests": {"px4Sitl": True, "gazebo": True, "parameterReadback": True},
        "smokeReport": {
            "mode": "runtime-image",
            "runtimeId": runtime_id,
            "imageId": "sha256:" + "e" * 64,
            "completedAt": "2026-08-05T00:00:00Z",
            "passed": True,
            "checks": checks,
        },
        "artifact": None,
    }
    runtime_manifest_bytes = _canonical_runtime(runtime_manifest)
    runtime_artifact_sha = "f" * 64
    runtime_release = {
        "schemaVersion": 1,
        "runtime": {
            "id": "DroneDreamRuntime",
            "buildId": runtime_id,
            "version": compatibility["runtimeVersion"],
            "architecture": "x86_64",
            "wslVersion": 2,
        },
        "source": {
            "gitCommit": _RUNTIME_SOURCE,
            "px4Commit": pins["PX4_GIT_COMMIT"],
            "gazeboVersion": compatibility["gazeboVersion"],
            "buildTimestamp": "2026-08-05T00:00:00Z",
        },
        "artifact": {
            "filename": "DroneDreamRuntime.tar",
            "mediaType": "application/vnd.dronedream.wsl-rootfs+tar",
            "compression": "none",
            "sizeBytes": 1024,
            "sha256": runtime_artifact_sha,
            "parts": [
                {
                    "index": 0,
                    "filename": "DroneDreamRuntime.tar.part000",
                    "sizeBytes": 1024,
                    "sha256": "0" * 64,
                    "url": "https://example.test/DroneDreamRuntime.tar.part000",
                }
            ],
        },
        "smoke": {
            "passed": True,
            "reportFilename": "runtime-smoke-report.json",
            "reportSha256": "1" * 64,
            "reportUrl": "https://example.test/runtime-smoke-report.json",
            "completedAt": "2026-08-05T00:00:00Z",
        },
        "requirements": {
            "minimumFreeBytes": 52 * 1024**3,
            "targetPathHint": "X:\\DroneDream",
        },
    }
    runtime_release_bytes = _canonical_release(runtime_release)

    runtime_attestation = RuntimeManifestAttestationV1(
        signed_release_manifest_sha256=_sha256(runtime_release_bytes),
        signed_release_signature_sha256=_SHA["runtime_signature"],
        trusted_keyring_sha256=_SHA["runtime_keyring"],
        installed_runtime_manifest_sha256=_sha256(runtime_manifest_bytes),
        runtime_artifact_sha256=runtime_artifact_sha,
        runtime_artifact_size_bytes=1024,
        verification_receipt_sha256=_SHA["runtime_receipt"],
    )
    engine_attestation = EnginePackManifestAttestationV1(
        descriptor_sha256=_sha256(engine_descriptor_bytes),
        manifest_sha256=_sha256(engine_manifest_bytes),
        archive_sha256=engine_archive_sha,
        archive_size_bytes=4096,
        verification_receipt_sha256=_SHA["engine_receipt"],
    )
    desktop_attestation = (
        DesktopComponentAttestationV1(
            component={
                "component_id": "desktop",
                "version": "1.0.0",
                "source_commit": _DESKTOP_SOURCE,
                "manifest_sha256": _SHA["desktop_manifest"],
                "artifact_sha256": _SHA["desktop_artifact"],
            },
            manifest_bytes_sha256=_SHA["desktop_manifest"],
            artifact_bytes_sha256=_SHA["desktop_artifact"],
            verification_receipt_sha256=_SHA["desktop_receipt"],
        )
        if with_desktop
        else None
    )
    bindings = CompositeObservationBindingsV1(
        repository_subject_commit=_REPOSITORY,
        evaluator_subject_commit=_EVALUATOR,
        campaign_coordinator_subject_commit=_COORDINATOR,
        prompt_registry_sha256=_SHA["prompt"],
        response_schema_sha256=_SHA["schema"],
        tool_registry_sha256=_SHA["tools"],
        model_matrix_sha256=_SHA["models"],
        machine_profile_sha256=_SHA["machine"],
        concurrency_profile_sha256=_SHA["concurrency"],
        observation_adapter_receipt_sha256=_SHA["adapter"],
    )
    runtime_manifest_sha = _sha256(runtime_manifest_bytes)
    inventory = CompositeExecutionInventoryV1(
        repository_subject_commit=_REPOSITORY,
        evaluator_subject_commit=_EVALUATOR,
        campaign_coordinator_subject_commit=_COORDINATOR,
        desktop=desktop_attestation.component if desktop_attestation else None,
        runtime_base={
            "component_id": "runtime-base",
            "version": compatibility["runtimeVersion"],
            "source_commit": _RUNTIME_SOURCE,
            "manifest_sha256": runtime_manifest_sha,
            "artifact_sha256": runtime_artifact_sha,
        },
        engine_pack={
            "component_id": "engine-pack",
            "version": engine_manifest["packId"],
            "source_commit": _ENGINE_SOURCE,
            "manifest_sha256": _sha256(engine_manifest_bytes),
            "artifact_sha256": engine_archive_sha,
        },
        px4={
            "component_id": "px4",
            "version": pins["PX4_VERSION"],
            "source_commit": pins["PX4_GIT_COMMIT"],
            "manifest_sha256": runtime_manifest_sha,
            "artifact_sha256": None,
        },
        gazebo={
            "component_id": "gazebo",
            "version": compatibility["gazeboVersion"],
            "source_commit": None,
            "manifest_sha256": runtime_manifest_sha,
            "artifact_sha256": None,
        },
        prompt_registry_sha256=_SHA["prompt"],
        response_schema_sha256=_SHA["schema"],
        tool_registry_sha256=_SHA["tools"],
        model_matrix_sha256=_SHA["models"],
        machine_profile_sha256=_SHA["machine"],
        concurrency_profile_sha256=_SHA["concurrency"],
    )
    return {
        "inventory": inventory,
        "runtime_release_manifest_bytes": runtime_release_bytes,
        "runtime_installed_manifest_bytes": runtime_manifest_bytes,
        "engine_pack_descriptor_bytes": engine_descriptor_bytes,
        "engine_pack_manifest_bytes": engine_manifest_bytes,
        "runtime_attestation": runtime_attestation,
        "engine_pack_attestation": engine_attestation,
        "desktop_attestation": desktop_attestation,
        "bindings": bindings,
    }


def _compile(values: dict[str, object]):
    return compile_composite_execution_observation(**values)  # type: ignore[arg-type]


def test_compiles_verified_distinct_component_sources_without_authorizing() -> None:
    values = _fixture()
    result = _compile(values)

    assert result.verification.status == "verified"
    assert result.verification.compatible is True
    assert result.execution_authorized is False
    assert result.verification.execution_authorized is False
    assert {
        result.observation.repository_subject_commit,
        result.observation.desktop.component_observation.component.source_commit,
        result.observation.runtime_base.runtime_source_commit,
        result.observation.engine_pack.engine_source_commit,
        result.observation.px4.component.source_commit,
    } == {
        _REPOSITORY,
        _DESKTOP_SOURCE,
        _RUNTIME_SOURCE,
        _ENGINE_SOURCE,
        engine_pack.read_pins(ROOT / "runtime/pins.env")["PX4_GIT_COMMIT"],
    }
    assert result.runtime_attestation_sha256 == canonical_sha256(values["runtime_attestation"])


def test_fixture_bytes_also_pass_authoritative_delivery_validators() -> None:
    values = _fixture()
    release = json.loads(values["runtime_release_manifest_bytes"])
    installed = json.loads(values["runtime_installed_manifest_bytes"])
    engine_manifest = json.loads(values["engine_pack_manifest_bytes"])

    assert runtime_release_tool.validate_release_manifest(release) == release
    runtime_manifest_tool.validate_manifest(installed, require_smoke_passed=True)
    assert engine_pack.validate_manifest(engine_manifest) == engine_manifest


def test_compiles_a_declared_headless_inventory() -> None:
    result = _compile(_fixture(with_desktop=False))
    assert result.verification.status == "verified"
    assert result.observation.desktop is None
    assert result.desktop_attestation_sha256 is None


def test_inventory_drift_is_denied_not_rewritten() -> None:
    values = _fixture()
    inventory = values["inventory"]
    assert isinstance(inventory, CompositeExecutionInventoryV1)
    payload = inventory.model_dump(mode="json")
    payload["runtime_base"]["artifact_sha256"] = "9" * 64
    values["inventory"] = CompositeExecutionInventoryV1.model_validate(payload)

    result = _compile(values)
    assert result.verification.status == "denied"
    assert "runtime-base-identity-mismatch" in result.verification.reason_codes
    assert result.execution_authorized is False


@pytest.mark.parametrize("target", ("runtime_release_manifest_bytes", "engine_pack_manifest_bytes"))
def test_noncanonical_and_duplicate_manifest_bytes_fail_closed(target: str) -> None:
    values = _fixture()
    raw = values[target]
    assert isinstance(raw, bytes)
    values[target] = raw + b" "
    with pytest.raises(CompositeObservationCompilationError, match="not canonical"):
        _compile(values)

    values = _fixture()
    raw = values[target]
    assert isinstance(raw, bytes)
    values[target] = raw.replace(b'{"', b'{"schemaVersion":1,"', 1)
    with pytest.raises(CompositeObservationCompilationError, match="duplicate key"):
        _compile(values)


def test_runtime_release_and_installed_source_drift_fails_closed() -> None:
    values = _fixture()
    release = json.loads(values["runtime_release_manifest_bytes"])
    release["source"]["gitCommit"] = "8" * 40
    raw = _canonical_release(release)
    values["runtime_release_manifest_bytes"] = raw
    attestation = values["runtime_attestation"]
    assert isinstance(attestation, RuntimeManifestAttestationV1)
    values["runtime_attestation"] = attestation.model_copy(
        update={"signed_release_manifest_sha256": _sha256(raw)}
    )

    with pytest.raises(CompositeObservationCompilationError, match="disagree on source"):
        _compile(values)


def test_runtime_identity_and_smoke_tamper_fail_closed() -> None:
    values = _fixture()
    manifest = json.loads(values["runtime_installed_manifest_bytes"])
    manifest["runtimeId"] = str(uuid.uuid4())
    raw = _canonical_runtime(manifest)
    values["runtime_installed_manifest_bytes"] = raw
    attestation = values["runtime_attestation"]
    assert isinstance(attestation, RuntimeManifestAttestationV1)
    values["runtime_attestation"] = attestation.model_copy(
        update={"installed_runtime_manifest_sha256": _sha256(raw)}
    )
    with pytest.raises(CompositeObservationCompilationError, match="immutable identity"):
        _compile(values)

    values = _fixture()
    manifest = json.loads(values["runtime_installed_manifest_bytes"])
    manifest["smokeTests"]["gazebo"] = False
    raw = _canonical_runtime(manifest)
    values["runtime_installed_manifest_bytes"] = raw
    attestation = values["runtime_attestation"]
    assert isinstance(attestation, RuntimeManifestAttestationV1)
    values["runtime_attestation"] = attestation.model_copy(
        update={"installed_runtime_manifest_sha256": _sha256(raw)}
    )
    with pytest.raises(CompositeObservationCompilationError, match="not smoke-promoted"):
        _compile(values)


def test_engine_pack_payload_and_attestation_tamper_fail_closed() -> None:
    values = _fixture()
    manifest = json.loads(values["engine_pack_manifest_bytes"])
    manifest["files"][0]["sha256"] = "9" * 64
    raw = engine_pack.canonical_json(manifest)
    values["engine_pack_manifest_bytes"] = raw
    attestation = values["engine_pack_attestation"]
    assert isinstance(attestation, EnginePackManifestAttestationV1)
    values["engine_pack_attestation"] = attestation.model_copy(
        update={"manifest_sha256": _sha256(raw)}
    )
    with pytest.raises(CompositeObservationCompilationError, match="payload identity"):
        _compile(values)

    values = _fixture()
    attestation = values["engine_pack_attestation"]
    assert isinstance(attestation, EnginePackManifestAttestationV1)
    values["engine_pack_attestation"] = attestation.model_copy(update={"archive_sha256": "8" * 64})
    with pytest.raises(CompositeObservationCompilationError, match="trusted attestation"):
        _compile(values)


@pytest.mark.parametrize(
    ("profile", "message"),
    (
        (
            {
                "profileId": "unified-sim-lab",
                "includesLargeSimulator": False,
                "excludedSourcePaths": [],
            },
            "internally inconsistent",
        ),
        (
            {
                "profileId": "unknown-profile",
                "includesLargeSimulator": True,
                "excludedSourcePaths": [],
            },
            "unsupported",
        ),
        (
            {
                "profileId": "field-lightweight",
                "includesLargeSimulator": False,
                "excludedSourcePaths": ["../backend/app/simulator"],
            },
            "excluded paths",
        ),
    ),
)
def test_engine_pack_edition_profile_drift_fails_closed(
    profile: dict[str, object],
    message: str,
) -> None:
    values = _fixture()
    manifest = json.loads(values["engine_pack_manifest_bytes"])
    manifest["editionProfile"] = profile
    raw = engine_pack.canonical_json(manifest)
    values["engine_pack_manifest_bytes"] = raw
    attestation = values["engine_pack_attestation"]
    assert isinstance(attestation, EnginePackManifestAttestationV1)
    values["engine_pack_attestation"] = attestation.model_copy(
        update={"manifest_sha256": _sha256(raw)}
    )
    with pytest.raises(CompositeObservationCompilationError, match=message):
        _compile(values)


def test_autonomy_full_engine_profile_is_supported() -> None:
    assert _validate_engine_edition_profile(
        {
            "profileId": "autonomy-full",
            "includesLargeSimulator": True,
            "excludedSourcePaths": [],
        }
    ) == {
        "profileId": "autonomy-full",
        "includesLargeSimulator": True,
        "excludedSourcePaths": [],
    }


def test_engine_pack_edition_profile_is_bound_into_pack_identity() -> None:
    values = _fixture()
    manifest = json.loads(values["engine_pack_manifest_bytes"])
    manifest["editionProfile"] = {
        "profileId": "field-lightweight",
        "includesLargeSimulator": False,
        "excludedSourcePaths": ["backend/app/simulator", "scripts/simulators"],
    }
    raw = engine_pack.canonical_json(manifest)
    values["engine_pack_manifest_bytes"] = raw
    attestation = values["engine_pack_attestation"]
    assert isinstance(attestation, EnginePackManifestAttestationV1)
    values["engine_pack_attestation"] = attestation.model_copy(
        update={"manifest_sha256": _sha256(raw)}
    )
    with pytest.raises(CompositeObservationCompilationError, match="payload identity"):
        _compile(values)


def test_sim_only_engine_profile_is_supported_and_hash_bound() -> None:
    profile = {
        "profileId": "sim-only",
        "profileVersion": "1.0.0",
        "profileManifestPath": "distribution/engine-pack-profiles/sim-only.v1.json",
        "profileManifestSha256": "a" * 64,
        "includesLargeSimulator": True,
        "excludedSourcePaths": ["backend/app/distribution_safety.py"],
    }
    assert _validate_engine_edition_profile(profile) == profile
    drifted = dict(profile)
    drifted["profileManifestSha256"] = "not-a-hash"
    with pytest.raises(CompositeObservationCompilationError, match="internally inconsistent"):
        _validate_engine_edition_profile(drifted)


def test_artifact_sizes_and_release_timestamps_are_bound() -> None:
    values = _fixture()
    attestation = values["runtime_attestation"]
    assert isinstance(attestation, RuntimeManifestAttestationV1)
    values["runtime_attestation"] = attestation.model_copy(
        update={"runtime_artifact_size_bytes": 2048}
    )
    with pytest.raises(CompositeObservationCompilationError, match="artifact size"):
        _compile(values)

    values = _fixture()
    descriptor = json.loads(values["engine_pack_descriptor_bytes"])
    descriptor["archive"]["sizeBytes"] = 8192
    descriptor_bytes = engine_pack.canonical_json(descriptor)
    values["engine_pack_descriptor_bytes"] = descriptor_bytes
    attestation = values["engine_pack_attestation"]
    assert isinstance(attestation, EnginePackManifestAttestationV1)
    values["engine_pack_attestation"] = attestation.model_copy(
        update={"descriptor_sha256": _sha256(descriptor_bytes)}
    )
    with pytest.raises(CompositeObservationCompilationError, match="archive size"):
        _compile(values)

    values = _fixture()
    release = json.loads(values["runtime_release_manifest_bytes"])
    release["source"]["buildTimestamp"] = "not-a-timestamp"
    raw = _canonical_release(release)
    values["runtime_release_manifest_bytes"] = raw
    attestation = values["runtime_attestation"]
    assert isinstance(attestation, RuntimeManifestAttestationV1)
    values["runtime_attestation"] = attestation.model_copy(
        update={"signed_release_manifest_sha256": _sha256(raw)}
    )
    with pytest.raises(CompositeObservationCompilationError, match="UTC RFC3339"):
        _compile(values)


def test_desktop_attestation_cannot_cross_manifest_or_artifact_bytes() -> None:
    values = _fixture()
    attestation = values["desktop_attestation"]
    assert isinstance(attestation, DesktopComponentAttestationV1)
    payload = attestation.model_dump(mode="json")
    payload["manifest_bytes_sha256"] = "9" * 64
    with pytest.raises(ValidationError, match="desktop manifest bytes"):
        DesktopComponentAttestationV1.model_validate(payload)


def test_unknown_attestation_fields_are_rejected() -> None:
    values = _fixture()
    attestation = values["runtime_attestation"]
    assert isinstance(attestation, RuntimeManifestAttestationV1)
    payload = attestation.model_dump(mode="json")
    payload["unexpected"] = True
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        RuntimeManifestAttestationV1.model_validate(payload)
