from __future__ import annotations

import copy
import hashlib
import json
import struct
from pathlib import Path
from typing import Any

import pytest

from app.release import installer_integrity
from app.release.installer_integrity import (
    AUTHORITATIVE_MIRROR_CHECKSUM_SHA256,
    AUTHORITATIVE_WEBSITE_RECEIPT_SHA256,
    IMMUTABLE_INSTALLER_RELEASE_CONTRACT_VERSION,
    build_public_installer_origin_audit,
    inspect_pe_certificate_table,
    verify_checksum_file,
    verify_new_immutable_installer_release,
    verify_public_installer_origin_audit,
)
from scripts.audit_public_installers import _write_audit

_FIXTURE_ROOT = Path(__file__).resolve().parent / "fixtures"
_WEBSITE_RECEIPT = _FIXTURE_ROOT / "installer_public_recheck_20260728.json"
_TARGET_COMMIT = "41a7d8560d67f5380a34d03226326dd3041bf923"
_INVENTORY_COMMIT = "92444a2354d6e0b199eba4e50bdf1c49af7aa21f"
_AUDITOR_COMMIT = "8" * 40
_GLOBAL_SHA = "3be26b78aa1ec3383dd67c04b9d762b6ac2a481c2befc6880f43e2b59b6ee368"
_MIRROR_SHA = "aad5a7fdb1196059ce2e15b33e2495830f77ed5f1070e56e5423796b9ca96b86"


def _write_pe(path: Path, *, certificate_size: int = 0, marker: int = 0) -> None:
    pe_offset = 0x80
    optional_size = 224
    optional_offset = pe_offset + 24
    certificate_offset = 512 if certificate_size else 0
    total_size = certificate_offset + certificate_size if certificate_size else 512
    raw = bytearray(total_size)
    raw[0:2] = b"MZ"
    struct.pack_into("<I", raw, 0x3C, pe_offset)
    raw[pe_offset : pe_offset + 4] = b"PE\0\0"
    struct.pack_into("<H", raw, pe_offset + 4 + 16, optional_size)
    struct.pack_into("<H", raw, optional_offset, 0x10B)
    struct.pack_into("<I", raw, optional_offset + 92, 16)
    struct.pack_into(
        "<II",
        raw,
        optional_offset + 96 + (4 * 8),
        certificate_offset,
        certificate_size,
    )
    raw[0x40] = marker
    if certificate_size:
        raw[certificate_offset : certificate_offset + certificate_size] = (
            bytes([marker or 1]) * certificate_size
        )
    path.write_bytes(raw)


def _origin(
    *,
    local_name: str,
    size: int,
    sha256: str,
    checksum_sha256: str,
) -> dict[str, Any]:
    public_name = "DroneDream_1.0.0_x64-setup.exe"
    return {
        "file_name": public_name,
        "local_file_name": local_name,
        "bytes": size,
        "sha256": sha256,
        "checksum": {
            "path": f"{local_name}.sha256",
            "bytes": 98,
            "sha256": checksum_sha256,
            "declared_installer_sha256": sha256,
            "declared_installer_name": public_name,
            "verified": True,
        },
        "authenticode_status": "NotSigned",
        "authenticode_valid": False,
        "pe": {
            "pe_format": "PE32",
            "pe_header_offset": 280,
            "certificate_table_file_offset": 0,
            "certificate_table_size": 0,
            "has_certificate_table": False,
        },
    }


def _build_frozen_audit(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    global_origin = _origin(
        local_name="DroneDream_1.0.0_x64-setup.exe",
        size=5_526_509,
        sha256=_GLOBAL_SHA,
        checksum_sha256="7aaa61a1c536829554c24d78165ee23134bddf7671960f323a8d24606456b32e",
    )
    mirror_origin = _origin(
        local_name="mirror-DroneDream_1.0.0_x64-setup.exe",
        size=9_881_226,
        sha256=_MIRROR_SHA,
        checksum_sha256=AUTHORITATIVE_MIRROR_CHECKSUM_SHA256,
    )
    observations = iter((global_origin, mirror_origin))
    monkeypatch.setattr(
        installer_integrity,
        "inspect_installer",
        lambda *_args, **_kwargs: next(observations),
    )
    return build_public_installer_origin_audit(
        global_installer=Path(global_origin["local_file_name"]),
        global_checksum=Path(f"{global_origin['local_file_name']}.sha256"),
        mirror_installer=Path(mirror_origin["local_file_name"]),
        mirror_checksum=Path(f"{mirror_origin['local_file_name']}.sha256"),
        global_authenticode_status="NotSigned",
        mirror_authenticode_status="NotSigned",
        version="1.0.0",
        release_tag="signpath-candidate-v1.0.0",
        release_target_commit=_TARGET_COMMIT,
        release_inventory_source_commit=_INVENTORY_COMMIT,
        auditor_commit=_AUDITOR_COMMIT,
        generated_at="2026-07-28T14:00:00Z",
        website_receipt_path=_WEBSITE_RECEIPT,
        website_receipt_expected_sha256=AUTHORITATIVE_WEBSITE_RECEIPT_SHA256,
    )


def _candidate() -> dict[str, Any]:
    version = "1.0.1"
    filename = f"DroneDream_{version}_x64-setup.exe"
    sha256 = "c" * 64
    global_url = (
        "https://github.com/ChiZhang-805/DroneDream/releases/download/"
        f"desktop-v{version}/{filename}"
    )
    mirror_url = f"https://downloads.example.invalid/{filename}"
    metadata = {
        "version": version,
        "release_tag": f"desktop-v{version}",
        "file_name": filename,
        "sha256": sha256,
        "size_bytes": 12_345,
    }
    return {
        "contract_version": IMMUTABLE_INSTALLER_RELEASE_CONTRACT_VERSION,
        "version": version,
        "version_owner_approved": True,
        "version_approval_reference": "owner-approved-release-ticket",
        "file_name": filename,
        "release_tag": f"desktop-v{version}",
        "bytes": 12_345,
        "sha256": sha256,
        "checksum_verified": True,
        "authenticode_status": "Valid",
        "has_pe_certificate_table": True,
        "updater_signature_present": True,
        "source_commit": "d" * 40,
        "source_inventory_commit": "d" * 40,
        "single_installer_for_both_origins": True,
        "updater_manifest": {
            "version": version,
            "signature": "tauri-minisign-signature",
            "download_url": global_url,
        },
        "origin_metadata": {
            "global_github_release": {
                **metadata,
                "download_url": global_url,
                "checksum_url": f"{global_url}.sha256",
            },
            "alibaba_baota_mirror": {
                **metadata,
                "download_url": mirror_url,
                "checksum_url": f"{mirror_url}.sha256",
            },
        },
    }


def test_corrected_website_receipt_fixture_is_exact_authority() -> None:
    assert _WEBSITE_RECEIPT.stat().st_size == 2320
    assert hashlib.sha256(_WEBSITE_RECEIPT.read_bytes()).hexdigest() == (
        AUTHORITATIVE_WEBSITE_RECEIPT_SHA256
    )
    payload = json.loads(_WEBSITE_RECEIPT.read_text(encoding="utf-8"))
    assert payload["baotaMirror"]["checksumAssetSha256"] == (AUTHORITATIVE_MIRROR_CHECKSUM_SHA256)


def test_pe_certificate_table_inspection_distinguishes_unsigned_and_present(
    tmp_path: Path,
) -> None:
    unsigned = tmp_path / "unsigned.exe"
    signed_container = tmp_path / "signed-container.exe"
    _write_pe(unsigned)
    _write_pe(signed_container, certificate_size=16, marker=3)

    unsigned_result = inspect_pe_certificate_table(unsigned)
    signed_result = inspect_pe_certificate_table(signed_container)

    assert unsigned_result["has_certificate_table"] is False
    assert unsigned_result["certificate_table_file_offset"] == 0
    assert unsigned_result["certificate_table_size"] == 0
    assert signed_result["has_certificate_table"] is True
    assert signed_result["certificate_table_file_offset"] == 512
    assert signed_result["certificate_table_size"] == 16


def test_checksum_file_binds_public_name_even_for_prefixed_cache_file(
    tmp_path: Path,
) -> None:
    installer = tmp_path / "mirror-DroneDream_1.0.0_x64-setup.exe"
    checksum = tmp_path / "mirror-DroneDream_1.0.0_x64-setup.exe.sha256"
    _write_pe(installer, marker=4)
    digest = hashlib.sha256(installer.read_bytes()).hexdigest()
    checksum.write_text(
        f"{digest}  DroneDream_1.0.0_x64-setup.exe\n",
        encoding="ascii",
        newline="\n",
    )

    result = verify_checksum_file(
        installer,
        checksum,
        public_file_name="DroneDream_1.0.0_x64-setup.exe",
    )

    assert result["verified"] is True
    assert result["declared_installer_sha256"] == digest
    with pytest.raises(ValueError, match="names a different file"):
        verify_checksum_file(installer, checksum)


def test_frozen_public_audit_preserves_failures_and_recomputes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    audit = _build_frozen_audit(monkeypatch)

    assert verify_public_installer_origin_audit(audit) == audit
    assert audit["authoritative_receipt_sha256"] == AUTHORITATIVE_WEBSITE_RECEIPT_SHA256
    assert audit["conclusion"] == {
        "global_internal_integrity": True,
        "mirror_internal_integrity": True,
        "dual_origin_byte_parity": False,
        "authenticode_valid_on_both_origins": False,
        "release_source_bound_to_tag_commit": False,
        "publication_gate_status": "fail",
        "deployment_performed": False,
        "release_modified": False,
        "server_modified": False,
    }


def test_public_audit_writer_refuses_colliding_or_frozen_outputs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    audit = _build_frozen_audit(monkeypatch)
    output = tmp_path / "audit.json"
    sidecar = tmp_path / "audit.json.sha256"

    with pytest.raises(ValueError, match="different paths"):
        _write_audit(audit, output_path=output, sha256_output_path=output)

    _write_audit(audit, output_path=output, sha256_output_path=sidecar)
    original_audit = output.read_bytes()
    original_sidecar = sidecar.read_bytes()
    with pytest.raises(ValueError, match="refusing to overwrite"):
        _write_audit(audit, output_path=output, sha256_output_path=sidecar)

    assert output.read_bytes() == original_audit
    assert sidecar.read_bytes() == original_sidecar
    assert sidecar.read_text(encoding="ascii") == (
        f"{hashlib.sha256(original_audit).hexdigest()}  {output.name}\n"
    )


def test_frozen_public_audit_rejects_tampered_authority(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    audit = _build_frozen_audit(monkeypatch)
    audit["authoritative_receipt_sha256"] = "0" * 64
    unsigned = {key: value for key, value in audit.items() if key != "audit_sha256"}
    audit["audit_sha256"] = hashlib.sha256(
        json.dumps(
            unsigned,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()

    with pytest.raises(ValueError, match="authority binding"):
        verify_public_installer_origin_audit(audit)


def test_future_immutable_release_contract_accepts_only_new_exact_signed_bytes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    previous = _build_frozen_audit(monkeypatch)

    result = verify_new_immutable_installer_release(
        previous_audit=previous,
        candidate=_candidate(),
    )

    assert result == {
        "status": "passed",
        "version": "1.0.1",
        "file_name": "DroneDream_1.0.1_x64-setup.exe",
        "sha256": "c" * 64,
        "source_commit": "d" * 40,
        "publication_authorized": False,
    }


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda value: value.update(version="1.0.0"), "new approved version"),
        (
            lambda value: value.update(version_owner_approved=False),
            "explicit owner approval",
        ),
        (lambda value: value.update(authenticode_status="NotSigned"), "must be Valid"),
        (lambda value: value.update(has_pe_certificate_table=False), "certificate table"),
        (lambda value: value.update(source_inventory_commit="e" * 40), "inventory"),
        (lambda value: value.update(single_installer_for_both_origins=False), "same exact"),
        (
            lambda value: value["origin_metadata"]["alibaba_baota_mirror"].update(sha256="f" * 64),
            "metadata does not bind",
        ),
    ],
)
def test_future_immutable_release_contract_rejects_gate_failures(
    monkeypatch: pytest.MonkeyPatch,
    mutation: Any,
    message: str,
) -> None:
    previous = _build_frozen_audit(monkeypatch)
    candidate = copy.deepcopy(_candidate())
    mutation(candidate)

    with pytest.raises(ValueError, match=message):
        verify_new_immutable_installer_release(
            previous_audit=previous,
            candidate=candidate,
        )


def test_windows_audit_wrapper_observes_authenticode_without_status_override() -> None:
    repository_root = Path(__file__).resolve().parents[2]
    wrapper = (repository_root / "desktop" / "scripts" / "audit-public-installers.ps1").read_text(
        encoding="utf-8"
    )

    assert wrapper.count("Get-AuthenticodeSignature -LiteralPath") == 2
    assert "GlobalAuthenticodeStatus" not in wrapper
    assert "MirrorAuthenticodeStatus" not in wrapper
    assert "--global-authenticode-status ([string]$globalSignature.Status)" in wrapper
    assert "--mirror-authenticode-status ([string]$mirrorSignature.Status)" in wrapper


def test_formal_release_workflow_fails_closed_on_signing_and_source_binding() -> None:
    repository_root = Path(__file__).resolve().parents[2]
    workflow = (repository_root / ".github" / "workflows" / "desktop-installer.yml").read_text(
        encoding="utf-8"
    )

    assert workflow.count("signpath/github-action-submit-signing-request@") == 2
    assert workflow.count('if ($signature.Status -ne "Valid")') == 2
    assert ".sourceCommit == env.GITHUB_SHA" in workflow
    assert "release already exists and will never be overwritten" in workflow


def test_desktop_workflow_bounds_pr_concurrency_and_artifact_retention() -> None:
    repository_root = Path(__file__).resolve().parents[2]
    workflow = (repository_root / ".github" / "workflows" / "desktop-installer.yml").read_text(
        encoding="utf-8"
    )

    assert (
        "group: desktop-installer-${{ github.event.pull_request.number || github.ref }}"
        in workflow
    )
    assert "cancel-in-progress: ${{ github.event_name == 'pull_request' }}" in workflow
    retention = (
        "retention-days: ${{ github.event_name == 'pull_request' && 3 || "
        "(github.event_name == 'workflow_dispatch' && 14 || 30) }}"
    )
    assert workflow.count(retention) == 1
    assert 'name: DroneDream-Windows-x64' in workflow
    assert 'tags:\n      - "desktop-v*"' in workflow
    assert "workflow_dispatch:" in workflow
    assert "pull_request:" in workflow
