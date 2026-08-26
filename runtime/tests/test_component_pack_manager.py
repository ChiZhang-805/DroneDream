from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import sys
import tarfile
from copy import deepcopy
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
TOOL_PATH = ROOT / "runtime/scripts/component-pack-manager.py"
SPEC = importlib.util.spec_from_file_location("component_pack_manager", TOOL_PATH)
assert SPEC and SPEC.loader
tool = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = tool
SPEC.loader.exec_module(tool)


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _contracts(tmp_path: Path, sequence: int = 1) -> tuple[Path, Path, Path, Path]:
    payload = b'{"workflows":["autonomous-mission"]}\n'
    records = [
        {"path": "capabilities/index.json", "sizeBytes": len(payload), "sha256": _sha(payload)}
    ]
    manifest = {
        "schemaVersion": 1,
        "kind": "dronedream-component-pack",
        "packType": "capability",
        "packName": "DroneDream Workflow Capability Pack",
        "packId": f"sha256:{tool.canonical_file_list_sha256(records)}",
        "version": f"1.0.{sequence - 1}",
        "releaseSequence": sequence,
        "runtimeCompatibility": {
            "runtimeProductId": "DroneDreamRuntime",
            "minimumRuntimeVersion": "0.1.0",
            "engineApiVersion": 1,
        },
        "editionProfiles": ["unified-sim-lab", "sim-only"],
        "files": records,
    }
    manifest_path = tmp_path / f"manifest-{sequence}.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    archive_path = tmp_path / f"pack-{sequence}.tar.gz"
    with tarfile.open(archive_path, "w:gz") as archive:
        info = tarfile.TarInfo("payload/capabilities/index.json")
        info.size = len(payload)
        archive.addfile(info, io.BytesIO(payload))
    receipt_path = tmp_path / f"receipt-{sequence}.json"
    receipt_path.write_text(
        json.dumps(
            {
                "schemaVersion": 1,
                "kind": "dronedream-verified-component-download",
                "manifestSha256": tool.sha256_file(manifest_path),
                "archiveSha256": tool.sha256_file(archive_path),
                "catalogSequence": sequence,
                "keyId": "ed25519:" + "a" * 64,
                "verifiedAt": "2026-08-16T00:00:00Z",
            }
        ),
        encoding="utf-8",
    )
    runtime_path = tmp_path / "runtime.json"
    runtime_path.write_text(
        json.dumps({"productId": "DroneDreamRuntime", "version": "0.1.0"}),
        encoding="utf-8",
    )
    return manifest_path, archive_path, receipt_path, runtime_path


def _install(tmp_path: Path, sequence: int = 1) -> dict[str, object]:
    manifest, archive, receipt, runtime = _contracts(tmp_path, sequence)
    verified = json.loads(receipt.read_text(encoding="utf-8"))
    return tool.install_pack(
        manifest_path=manifest,
        archive_path=archive,
        verified_receipt_path=receipt,
        runtime_manifest_path=runtime,
        runtime_profile="sim-only",
        expected_manifest_sha256=verified["manifestSha256"],
        expected_archive_sha256=verified["archiveSha256"],
        expected_catalog_sequence=verified["catalogSequence"],
        expected_key_id=verified["keyId"],
        pack_root=tmp_path / "packs",
        state_path=tmp_path / "state.json",
    )


def test_installs_verified_pack_into_versioned_release_and_switches_atomically(
    tmp_path: Path,
) -> None:
    result = _install(tmp_path)
    current = tmp_path / "packs/capability/current"
    assert current.is_symlink()
    assert (current / "capabilities/index.json").is_file()
    assert result["releaseSequence"] == 1
    state = json.loads((tmp_path / "state.json").read_text(encoding="utf-8"))
    assert state["catalogSequence"] == 1


def test_modified_archive_after_native_verification_is_rejected(tmp_path: Path) -> None:
    manifest, archive, receipt, runtime = _contracts(tmp_path)
    verified = json.loads(receipt.read_text(encoding="utf-8"))
    archive.write_bytes(archive.read_bytes() + b"tamper")
    with pytest.raises(tool.ComponentPackInstallError, match="changed after native verification"):
        tool.install_pack(
            manifest_path=manifest,
            archive_path=archive,
            verified_receipt_path=receipt,
            runtime_manifest_path=runtime,
            runtime_profile="sim-only",
            expected_manifest_sha256=verified["manifestSha256"],
            expected_archive_sha256=verified["archiveSha256"],
            expected_catalog_sequence=verified["catalogSequence"],
            expected_key_id=verified["keyId"],
            pack_root=tmp_path / "packs",
            state_path=tmp_path / "state.json",
        )


def test_downgrade_and_equal_sequence_with_different_payload_are_rejected(tmp_path: Path) -> None:
    _install(tmp_path, 2)
    manifest, archive, receipt, runtime = _contracts(tmp_path, 1)
    verified = json.loads(receipt.read_text(encoding="utf-8"))
    with pytest.raises(tool.ComponentPackInstallError, match="replay or downgrade"):
        tool.install_pack(
            manifest_path=manifest,
            archive_path=archive,
            verified_receipt_path=receipt,
            runtime_manifest_path=runtime,
            runtime_profile="sim-only",
            expected_manifest_sha256=verified["manifestSha256"],
            expected_archive_sha256=verified["archiveSha256"],
            expected_catalog_sequence=verified["catalogSequence"],
            expected_key_id=verified["keyId"],
            pack_root=tmp_path / "packs",
            state_path=tmp_path / "state.json",
        )


def test_profile_and_runtime_version_mismatch_fail_closed(tmp_path: Path) -> None:
    manifest_path, archive, receipt, runtime_path = _contracts(tmp_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    changed = deepcopy(manifest)
    changed["runtimeCompatibility"]["minimumRuntimeVersion"] = "9.0.0"
    manifest_path.write_text(json.dumps(changed), encoding="utf-8")
    verified = json.loads(receipt.read_text(encoding="utf-8"))
    verified["manifestSha256"] = tool.sha256_file(manifest_path)
    receipt.write_text(json.dumps(verified), encoding="utf-8")
    with pytest.raises(tool.ComponentPackInstallError, match="newer Base Runtime"):
        tool.install_pack(
            manifest_path=manifest_path,
            archive_path=archive,
            verified_receipt_path=receipt,
            runtime_manifest_path=runtime_path,
            runtime_profile="sim-only",
            expected_manifest_sha256=verified["manifestSha256"],
            expected_archive_sha256=verified["archiveSha256"],
            expected_catalog_sequence=verified["catalogSequence"],
            expected_key_id=verified["keyId"],
            pack_root=tmp_path / "packs",
            state_path=tmp_path / "state.json",
        )


def test_manifest_pack_id_binds_exact_ordered_file_records(tmp_path: Path) -> None:
    manifest_path, _, _, _ = _contracts(tmp_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["files"][0]["sizeBytes"] += 1
    with pytest.raises(tool.ComponentPackInstallError, match="does not bind"):
        tool.validate_manifest(manifest)


def test_autonomy_full_component_pack_profile_is_admitted(tmp_path: Path) -> None:
    manifest_path, _, _, _ = _contracts(tmp_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["editionProfiles"].append("autonomy-full")

    tool.validate_manifest(manifest)


def test_existing_release_is_reverified_before_reactivation(tmp_path: Path) -> None:
    first = _install(tmp_path, 1)
    current = tmp_path / "packs/capability/current"
    (current / "capabilities/index.json").write_text("tampered", encoding="utf-8")
    with pytest.raises(tool.ComponentPackInstallError, match="failed verification"):
        _install(tmp_path, 2)
    assert (
        first["packId"]
        == json.loads((tmp_path / "state.json").read_text())["components"]["capability"]["packId"]
    )


def test_older_verified_catalog_sequence_is_rejected(tmp_path: Path) -> None:
    _install(tmp_path, 2)
    manifest, archive, receipt, runtime = _contracts(tmp_path, 3)
    verified = json.loads(receipt.read_text(encoding="utf-8"))
    verified["catalogSequence"] = 1
    receipt.write_text(json.dumps(verified), encoding="utf-8")
    with pytest.raises(tool.ComponentPackInstallError, match="catalog replay"):
        tool.install_pack(
            manifest_path=manifest,
            archive_path=archive,
            verified_receipt_path=receipt,
            runtime_manifest_path=runtime,
            runtime_profile="sim-only",
            expected_manifest_sha256=verified["manifestSha256"],
            expected_archive_sha256=verified["archiveSha256"],
            expected_catalog_sequence=verified["catalogSequence"],
            expected_key_id=verified["keyId"],
            pack_root=tmp_path / "packs",
            state_path=tmp_path / "state.json",
        )


def test_forged_receipt_cannot_replace_the_native_trust_decision(tmp_path: Path) -> None:
    manifest, archive, receipt, runtime = _contracts(tmp_path)
    trusted = json.loads(receipt.read_text(encoding="utf-8"))
    forged = dict(trusted)
    forged["catalogSequence"] += 100
    receipt.write_text(json.dumps(forged), encoding="utf-8")
    with pytest.raises(tool.ComponentPackInstallError, match="native trust decision"):
        tool.install_pack(
            manifest_path=manifest,
            archive_path=archive,
            verified_receipt_path=receipt,
            runtime_manifest_path=runtime,
            runtime_profile="sim-only",
            expected_manifest_sha256=trusted["manifestSha256"],
            expected_archive_sha256=trusted["archiveSha256"],
            expected_catalog_sequence=trusted["catalogSequence"],
            expected_key_id=trusted["keyId"],
            pack_root=tmp_path / "packs",
            state_path=tmp_path / "state.json",
        )


def test_runtime_image_contains_both_pack_managers() -> None:
    dockerfile = (ROOT / "runtime/Dockerfile").read_text(encoding="utf-8")
    for path in (
        "/usr/lib/dronedream/engine-pack-manager.py",
        "/usr/lib/dronedream/component-pack-manager.py",
        "/usr/lib/dronedream/engine_pack.py",
    ):
        assert path in dockerfile
