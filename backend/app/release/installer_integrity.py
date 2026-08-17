"""Fail-closed installer integrity, origin-parity, and immutability contracts."""

from __future__ import annotations

import hashlib
import json
import re
import struct
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from typing import Any

PUBLIC_INSTALLER_AUDIT_SCHEMA_VERSION = (
    "dronedream.public-installer-origin-audit.v1"
)
PUBLIC_INSTALLER_AUDIT_CLAIM_BOUNDARY = (
    "Exact-byte audit of the two named public Windows installer artifacts. "
    "It reports each origin's internal checksum consistency, cross-origin byte "
    "parity, PE certificate-table presence, and Windows Authenticode status. "
    "It does not sign, publish, deploy, overwrite, or authorize any artifact."
)
IMMUTABLE_INSTALLER_RELEASE_CONTRACT_VERSION = (
    "dronedream.immutable-installer-publication-contract.v1"
)
AUTHORITATIVE_WEBSITE_RECEIPT_SHA256 = (
    "cd53a1de257f6bafe9c05afcd381b5852f31f9381946d1a49038bc039ca6916a"
)
AUTHORITATIVE_WEBSITE_RECEIPT_BYTES = 2320
SUPERSEDED_WEBSITE_RECEIPT_SHA256 = (
    "a3d21ca26270d5de398f9468c3c52df452f13d09c1a708151ba6356b68bbfcbe"
)
AUTHORITATIVE_MIRROR_CHECKSUM_SHA256 = (
    "e7cd2b624cfedab6ef974b41ddfa28b5d263a2292ed8f551c57cb516ef30cd08"
)
FROZEN_GLOBAL_INSTALLER_SHA256 = (
    "3be26b78aa1ec3383dd67c04b9d762b6ac2a481c2befc6880f43e2b59b6ee368"
)
FROZEN_GLOBAL_INSTALLER_BYTES = 5_526_509
FROZEN_GLOBAL_CHECKSUM_SHA256 = (
    "7aaa61a1c536829554c24d78165ee23134bddf7671960f323a8d24606456b32e"
)
FROZEN_MIRROR_INSTALLER_SHA256 = (
    "aad5a7fdb1196059ce2e15b33e2495830f77ed5f1070e56e5423796b9ca96b86"
)
FROZEN_MIRROR_INSTALLER_BYTES = 9_881_226

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_COMMIT = re.compile(r"^[0-9a-f]{40}$")
_SEMVER = re.compile(
    r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)"
    r"(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?$"
)
_AUTHENTICODE_STATUSES = {
    "Valid",
    "NotSigned",
    "HashMismatch",
    "NotTrusted",
    "UnknownError",
}
_DESKTOP_EDITION_PRODUCTS = {
    "universal": "DroneDream-Universal",
    "sim": "DroneDream-Sim",
    "lab": "DroneDream-Lab",
    "field": "DroneDream-Field",
}


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def canonical_pretty_bytes(value: object) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _sha256_value(value: object) -> str:
    return _sha256_bytes(_canonical_bytes(value))


def _require_sha256(value: object, *, field: str) -> str:
    if not isinstance(value, str) or not _SHA256.fullmatch(value):
        raise ValueError(f"{field} must be a lowercase SHA-256 string")
    return value


def _require_commit(value: object, *, field: str) -> str:
    if not isinstance(value, str) or not _COMMIT.fullmatch(value):
        raise ValueError(f"{field} must be a lowercase 40-character Git commit")
    return value


def _require_timestamp(value: object, *, field: str) -> str:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ValueError(f"{field} must be an explicit UTC timestamp ending in Z")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise ValueError(f"{field} must be ISO-8601 UTC") from exc
    offset = parsed.utcoffset()
    if offset is None or offset.total_seconds() != 0:
        raise ValueError(f"{field} must be UTC")
    return value


def _require_mapping(value: object, *, field: str) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{field} must be an object")
    return value


def _require_semver(value: object, *, field: str) -> str:
    if not isinstance(value, str) or not _SEMVER.fullmatch(value):
        raise ValueError(f"{field} must be a supported semantic version")
    return value


def _compare_semver_precedence(left: str, right: str) -> int:
    def parts(value: str) -> tuple[tuple[int, int, int], list[str] | None]:
        without_build = value.split("+", 1)[0]
        core, separator, prerelease = without_build.partition("-")
        major, minor, patch = core.split(".")
        return (int(major), int(minor), int(patch)), (
            prerelease.split(".") if separator else None
        )

    left_core, left_prerelease = parts(left)
    right_core, right_prerelease = parts(right)
    if left_core != right_core:
        return 1 if left_core > right_core else -1
    if left_prerelease is None or right_prerelease is None:
        if left_prerelease is right_prerelease:
            return 0
        return 1 if left_prerelease is None else -1
    for left_identifier, right_identifier in zip(
        left_prerelease,
        right_prerelease,
        strict=False,
    ):
        if left_identifier == right_identifier:
            continue
        left_numeric = left_identifier.isdigit()
        right_numeric = right_identifier.isdigit()
        if left_numeric and right_numeric:
            return 1 if int(left_identifier) > int(right_identifier) else -1
        if left_numeric != right_numeric:
            return -1 if left_numeric else 1
        return 1 if left_identifier > right_identifier else -1
    if len(left_prerelease) == len(right_prerelease):
        return 0
    return 1 if len(left_prerelease) > len(right_prerelease) else -1


def _require_positive_int(value: object, *, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{field} must be a positive integer")
    return value


def inspect_pe_certificate_table(path: Path) -> dict[str, Any]:
    """Inspect the PE security data directory without treating it as trust proof."""

    try:
        file_size = path.stat().st_size
    except OSError as exc:
        raise ValueError(f"cannot stat installer {path}: {exc}") from exc
    if file_size < 256:
        raise ValueError(f"installer is too small to be a PE image: {path}")
    try:
        with path.open("rb") as handle:
            if handle.read(2) != b"MZ":
                raise ValueError(f"installer lacks DOS MZ header: {path}")
            handle.seek(0x3C)
            pe_offset_raw = handle.read(4)
            if len(pe_offset_raw) != 4:
                raise ValueError(f"installer lacks PE header offset: {path}")
            pe_offset = struct.unpack("<I", pe_offset_raw)[0]
            if pe_offset < 0x40 or pe_offset > file_size - 24:
                raise ValueError(f"installer PE header offset is out of range: {path}")
            handle.seek(pe_offset)
            if handle.read(4) != b"PE\0\0":
                raise ValueError(f"installer lacks PE signature: {path}")
            coff = handle.read(20)
            if len(coff) != 20:
                raise ValueError(f"installer COFF header is truncated: {path}")
            optional_size = struct.unpack_from("<H", coff, 16)[0]
            optional_offset = pe_offset + 24
            if optional_size < 128 or optional_offset + optional_size > file_size:
                raise ValueError(f"installer optional header is invalid: {path}")
            handle.seek(optional_offset)
            optional = handle.read(optional_size)
    except OSError as exc:
        raise ValueError(f"cannot inspect installer {path}: {exc}") from exc

    magic = struct.unpack_from("<H", optional, 0)[0]
    if magic == 0x10B:
        directory_count_offset = 92
        directory_offset = 96
        pe_format = "PE32"
    elif magic == 0x20B:
        directory_count_offset = 108
        directory_offset = 112
        pe_format = "PE32+"
    else:
        raise ValueError(f"installer optional header has unknown magic 0x{magic:04x}")
    if len(optional) < directory_count_offset + 4:
        raise ValueError("installer optional header lacks data-directory count")
    directory_count = struct.unpack_from("<I", optional, directory_count_offset)[0]
    if directory_count <= 4 or len(optional) < directory_offset + (5 * 8):
        raise ValueError("installer optional header lacks certificate-table directory")
    certificate_offset, certificate_size = struct.unpack_from(
        "<II",
        optional,
        directory_offset + (4 * 8),
    )
    has_table = certificate_offset != 0 or certificate_size != 0
    if (certificate_offset == 0) != (certificate_size == 0):
        raise ValueError("installer certificate-table offset/size pair is inconsistent")
    if has_table:
        if certificate_size < 8:
            raise ValueError("installer certificate table is too small")
        if certificate_offset % 8 != 0:
            raise ValueError("installer certificate table is not 8-byte aligned")
        if certificate_offset + certificate_size > file_size:
            raise ValueError("installer certificate table extends beyond end of file")
    return {
        "pe_format": pe_format,
        "pe_header_offset": pe_offset,
        "certificate_table_file_offset": certificate_offset,
        "certificate_table_size": certificate_size,
        "has_certificate_table": has_table,
    }


def verify_checksum_file(
    installer_path: Path,
    checksum_path: Path,
    *,
    public_file_name: str | None = None,
) -> dict[str, Any]:
    """Verify strict lowercase GNU-style SHA-256 metadata for one installer."""

    try:
        text = checksum_path.read_text(encoding="ascii")
    except (OSError, UnicodeDecodeError) as exc:
        raise ValueError(f"cannot read installer checksum {checksum_path}: {exc}") from exc
    match = re.fullmatch(
        r"([0-9a-f]{64})  ([^/\\\r\n]+)(?:\r?\n)?",
        text,
    )
    if match is None:
        raise ValueError("installer checksum must be lowercase SHA-256, two spaces, filename")
    declared_sha, declared_name = match.groups()
    expected_name = public_file_name or installer_path.name
    if declared_name != expected_name:
        raise ValueError("installer checksum names a different file")
    actual_sha = _sha256_file(installer_path)
    if declared_sha != actual_sha:
        raise ValueError("installer checksum does not match exact installer bytes")
    return {
        "path": checksum_path.name,
        "bytes": checksum_path.stat().st_size,
        "sha256": _sha256_file(checksum_path),
        "declared_installer_sha256": declared_sha,
        "declared_installer_name": declared_name,
        "verified": True,
    }


def inspect_installer(
    installer_path: Path,
    checksum_path: Path,
    *,
    authenticode_status: str,
    public_file_name: str | None = None,
) -> dict[str, Any]:
    """Inspect one exact installer and bind an externally observed Windows status."""

    if authenticode_status not in _AUTHENTICODE_STATUSES:
        raise ValueError("authenticode_status is not a recognized Windows result")
    checksum = verify_checksum_file(
        installer_path,
        checksum_path,
        public_file_name=public_file_name,
    )
    pe = inspect_pe_certificate_table(installer_path)
    return {
        "file_name": public_file_name or installer_path.name,
        "local_file_name": installer_path.name,
        "bytes": installer_path.stat().st_size,
        "sha256": _sha256_file(installer_path),
        "checksum": checksum,
        "authenticode_status": authenticode_status,
        "authenticode_valid": authenticode_status == "Valid",
        "pe": pe,
    }


def build_public_installer_origin_audit(
    *,
    global_installer: Path,
    global_checksum: Path,
    mirror_installer: Path,
    mirror_checksum: Path,
    global_authenticode_status: str,
    mirror_authenticode_status: str,
    version: str,
    release_tag: str,
    release_target_commit: str,
    release_inventory_source_commit: str,
    auditor_commit: str,
    generated_at: str,
    website_receipt_path: Path,
    website_receipt_expected_sha256: str,
) -> dict[str, Any]:
    """Build the exact two-origin audit without changing either origin."""

    version = _require_semver(version, field="version")
    release_target_commit = _require_commit(
        release_target_commit,
        field="release_target_commit",
    )
    release_inventory_source_commit = _require_commit(
        release_inventory_source_commit,
        field="release_inventory_source_commit",
    )
    auditor_commit = _require_commit(auditor_commit, field="auditor_commit")
    generated_at = _require_timestamp(generated_at, field="generated_at")
    website_receipt_expected_sha256 = _require_sha256(
        website_receipt_expected_sha256,
        field="website_receipt_expected_sha256",
    )
    if website_receipt_expected_sha256 != AUTHORITATIVE_WEBSITE_RECEIPT_SHA256:
        raise ValueError("website installer receipt is not the corrected authority")
    if release_tag != f"signpath-candidate-v{version}":
        raise ValueError("audited prerelease tag does not match the audited version")
    website_receipt_bytes = website_receipt_path.read_bytes()
    website_receipt_sha = _sha256_bytes(website_receipt_bytes)
    if website_receipt_sha != website_receipt_expected_sha256:
        raise ValueError("website installer receipt SHA-256 does not match authority")
    if len(website_receipt_bytes) != AUTHORITATIVE_WEBSITE_RECEIPT_BYTES:
        raise ValueError("website installer receipt byte count does not match authority")
    website_receipt = json.loads(website_receipt_bytes)
    if not isinstance(website_receipt, dict):
        raise ValueError("website installer receipt must be an object")
    if website_receipt.get("auditKind") != "public-installer-byte-and-signature-recheck":
        raise ValueError("website installer receipt has the wrong audit kind")

    global_origin = inspect_installer(
        global_installer,
        global_checksum,
        authenticode_status=global_authenticode_status,
    )
    mirror_origin = inspect_installer(
        mirror_installer,
        mirror_checksum,
        authenticode_status=mirror_authenticode_status,
        public_file_name=global_origin["file_name"],
    )
    if global_origin["file_name"] != f"DroneDream_{version}_x64-setup.exe":
        raise ValueError("global installer filename does not match version")
    mirror_declared_name = mirror_origin["checksum"]["declared_installer_name"]
    if mirror_declared_name != global_origin["file_name"]:
        raise ValueError("mirror checksum does not name the common installer filename")
    global_receipt = _require_mapping(
        website_receipt.get("githubRelease"),
        field="website receipt githubRelease",
    )
    mirror_receipt = _require_mapping(
        website_receipt.get("baotaMirror"),
        field="website receipt baotaMirror",
    )
    receipt_release = _require_mapping(
        website_receipt.get("release"),
        field="website receipt release",
    )
    if (
        receipt_release.get("tag") != release_tag
        or receipt_release.get("fileName") != global_origin["file_name"]
        or receipt_release.get("checksumFileName")
        != f"{global_origin['file_name']}.sha256"
    ):
        raise ValueError("website installer receipt release identity drifted")
    for label, observed, frozen in (
        ("global", global_origin, global_receipt),
        ("mirror", mirror_origin, mirror_receipt),
    ):
        if (
            observed["bytes"] != frozen.get("bytes")
            or observed["sha256"] != frozen.get("sha256")
            or observed["authenticode_status"] != frozen.get("authenticodeStatus")
            or observed["pe"]["certificate_table_file_offset"]
            != frozen.get("peCertificateTableFileOffset")
            or observed["pe"]["certificate_table_size"]
            != frozen.get("peCertificateTableSize")
            or observed["pe"]["has_certificate_table"]
            is not frozen.get("hasPeCertificateTable")
        ):
            raise ValueError(f"{label} installer does not match website frozen receipt")
    if mirror_origin["checksum"]["sha256"] != AUTHORITATIVE_MIRROR_CHECKSUM_SHA256:
        raise ValueError("mirror checksum file does not match corrected authority")
    frozen_conclusion = _require_mapping(
        website_receipt.get("conclusion"),
        field="website receipt conclusion",
    )
    if (
        frozen_conclusion.get("publicGithubAssetIntegrity") != "pass"
        or frozen_conclusion.get("dualOriginInstallerParity") != "fail"
        or frozen_conclusion.get("authenticodeSigning") != "fail"
        or frozen_conclusion.get("deploymentPerformed") is not False
    ):
        raise ValueError("website installer receipt conclusion drifted")

    parity = (
        global_origin["sha256"] == mirror_origin["sha256"]
        and global_origin["bytes"] == mirror_origin["bytes"]
    )
    signatures_valid = (
        global_origin["authenticode_valid"]
        and mirror_origin["authenticode_valid"]
        and global_origin["pe"]["has_certificate_table"]
        and mirror_origin["pe"]["has_certificate_table"]
    )
    source_binding_matches_tag = release_target_commit == release_inventory_source_commit
    unsigned: dict[str, Any] = {
        "schema_version": PUBLIC_INSTALLER_AUDIT_SCHEMA_VERSION,
        "claim_boundary": PUBLIC_INSTALLER_AUDIT_CLAIM_BOUNDARY,
        "generated_at": generated_at,
        "auditor_commit": auditor_commit,
        "release": {
            "version": version,
            "tag": release_tag,
            "file_name": global_origin["file_name"],
            "release_target_commit": release_target_commit,
            "release_inventory_source_commit": release_inventory_source_commit,
            "source_binding_matches_tag": source_binding_matches_tag,
        },
        "website_receipt": {
            "path": website_receipt_path.name,
            "bytes": len(website_receipt_bytes),
            "sha256": website_receipt_sha,
        },
        "origins": {
            "global_github_release": global_origin,
            "alibaba_baota_mirror": {
                **mirror_origin,
                "public_file_name": global_origin["file_name"],
            },
        },
        "conclusion": {
            "global_internal_integrity": True,
            "mirror_internal_integrity": True,
            "dual_origin_byte_parity": parity,
            "authenticode_valid_on_both_origins": signatures_valid,
            "release_source_bound_to_tag_commit": source_binding_matches_tag,
            "publication_gate_status": (
                "pass"
                if parity and signatures_valid and source_binding_matches_tag
                else "fail"
            ),
            "deployment_performed": False,
            "release_modified": False,
            "server_modified": False,
        },
        "superseded_receipt_sha256": SUPERSEDED_WEBSITE_RECEIPT_SHA256,
        "authoritative_receipt_sha256": website_receipt_sha,
    }
    return {
        **unsigned,
        "audit_sha256": _sha256_value(unsigned),
    }


def verify_public_installer_origin_audit(payload: object) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("public installer origin audit must be an object")
    if payload.get("schema_version") != PUBLIC_INSTALLER_AUDIT_SCHEMA_VERSION:
        raise ValueError("public installer origin audit schema is invalid")
    unsigned = {key: value for key, value in payload.items() if key != "audit_sha256"}
    if payload.get("audit_sha256") != _sha256_value(unsigned):
        raise ValueError("public installer origin audit hash does not recompute")
    if payload.get("claim_boundary") != PUBLIC_INSTALLER_AUDIT_CLAIM_BOUNDARY:
        raise ValueError("public installer origin audit claim boundary drifted")
    if (
        payload.get("authoritative_receipt_sha256")
        != AUTHORITATIVE_WEBSITE_RECEIPT_SHA256
        or payload.get("superseded_receipt_sha256")
        != SUPERSEDED_WEBSITE_RECEIPT_SHA256
    ):
        raise ValueError("public installer receipt authority binding drifted")
    _require_timestamp(payload.get("generated_at"), field="generated_at")
    _require_commit(payload.get("auditor_commit"), field="auditor_commit")
    release = _require_mapping(payload.get("release"), field="release")
    version = _require_semver(release.get("version"), field="release.version")
    if (
        release.get("tag") != f"signpath-candidate-v{version}"
        or release.get("file_name") != f"DroneDream_{version}_x64-setup.exe"
    ):
        raise ValueError("public installer release identity is invalid")
    _require_commit(
        release.get("release_target_commit"),
        field="release.release_target_commit",
    )
    _require_commit(
        release.get("release_inventory_source_commit"),
        field="release.release_inventory_source_commit",
    )
    origins = _require_mapping(payload.get("origins"), field="origins")
    for name in ("global_github_release", "alibaba_baota_mirror"):
        origin = _require_mapping(origins.get(name), field=f"origins.{name}")
        _require_sha256(origin.get("sha256"), field=f"origins.{name}.sha256")
        _require_positive_int(origin.get("bytes"), field=f"origins.{name}.bytes")
        if origin.get("file_name") != release["file_name"]:
            raise ValueError(f"{name} file identity is invalid")
        checksum = _require_mapping(
            origin.get("checksum"),
            field=f"origins.{name}.checksum",
        )
        if checksum.get("verified") is not True:
            raise ValueError(f"{name} checksum is not verified")
        _require_positive_int(
            checksum.get("bytes"),
            field=f"origins.{name}.checksum.bytes",
        )
        if (
            checksum.get("declared_installer_name") != release["file_name"]
            or checksum.get("declared_installer_sha256") != origin["sha256"]
        ):
            raise ValueError(f"{name} checksum binding is invalid")
        _require_sha256(checksum.get("sha256"), field=f"origins.{name}.checksum.sha256")
        pe = _require_mapping(origin.get("pe"), field=f"origins.{name}.pe")
        if not isinstance(pe.get("has_certificate_table"), bool):
            raise ValueError(f"{name} PE certificate-table flag is invalid")
        if origin.get("authenticode_status") not in _AUTHENTICODE_STATUSES:
            raise ValueError(f"{name} Authenticode status is invalid")
        if origin.get("authenticode_valid") is not (
            origin["authenticode_status"] == "Valid"
        ):
            raise ValueError(f"{name} Authenticode validity flag is invalid")
        certificate_offset = pe.get("certificate_table_file_offset")
        certificate_size = pe.get("certificate_table_size")
        if (
            isinstance(certificate_offset, bool)
            or not isinstance(certificate_offset, int)
            or certificate_offset < 0
            or isinstance(certificate_size, bool)
            or not isinstance(certificate_size, int)
            or certificate_size < 0
        ):
            raise ValueError(f"{name} PE certificate-table coordinates are invalid")
        if pe["has_certificate_table"]:
            if (
                certificate_offset == 0
                or certificate_size < 8
                or certificate_offset % 8 != 0
            ):
                raise ValueError(f"{name} PE certificate-table binding is invalid")
        elif certificate_offset != 0 or certificate_size != 0:
            raise ValueError(f"{name} unsigned PE coordinates are invalid")
    conclusion = _require_mapping(payload.get("conclusion"), field="conclusion")
    global_origin = origins["global_github_release"]
    mirror_origin = origins["alibaba_baota_mirror"]
    if (
        global_origin["sha256"] != FROZEN_GLOBAL_INSTALLER_SHA256
        or global_origin["bytes"] != FROZEN_GLOBAL_INSTALLER_BYTES
        or global_origin["checksum"]["sha256"] != FROZEN_GLOBAL_CHECKSUM_SHA256
        or mirror_origin["sha256"] != FROZEN_MIRROR_INSTALLER_SHA256
        or mirror_origin["bytes"] != FROZEN_MIRROR_INSTALLER_BYTES
        or mirror_origin["checksum"]["sha256"]
        != AUTHORITATIVE_MIRROR_CHECKSUM_SHA256
    ):
        raise ValueError("public installer frozen origin bytes drifted")
    for origin in (global_origin, mirror_origin):
        pe = origin["pe"]
        if (
            origin["authenticode_status"] != "NotSigned"
            or origin["authenticode_valid"] is not False
            or pe["has_certificate_table"] is not False
            or pe["certificate_table_file_offset"] != 0
            or pe["certificate_table_size"] != 0
        ):
            raise ValueError("public installer known unsigned origin facts drifted")
    parity = (
        global_origin["sha256"] == mirror_origin["sha256"]
        and global_origin["bytes"] == mirror_origin["bytes"]
    )
    signatures_valid = all(
        origin["authenticode_status"] == "Valid"
        and origin["pe"]["has_certificate_table"] is True
        for origin in (global_origin, mirror_origin)
    )
    source_bound = (
        release["release_target_commit"] == release["release_inventory_source_commit"]
    )
    if release.get("source_binding_matches_tag") is not source_bound:
        raise ValueError("release source-binding conclusion does not recompute")
    website_receipt = _require_mapping(
        payload.get("website_receipt"),
        field="website_receipt",
    )
    if (
        website_receipt.get("sha256") != AUTHORITATIVE_WEBSITE_RECEIPT_SHA256
        or website_receipt.get("bytes") != AUTHORITATIVE_WEBSITE_RECEIPT_BYTES
    ):
        raise ValueError("website receipt byte binding is invalid")
    if (
        conclusion.get("dual_origin_byte_parity") is not parity
        or conclusion.get("authenticode_valid_on_both_origins") is not signatures_valid
        or conclusion.get("release_source_bound_to_tag_commit") is not source_bound
    ):
        raise ValueError("public installer origin audit conclusion does not recompute")
    if (
        conclusion.get("global_internal_integrity") is not True
        or conclusion.get("mirror_internal_integrity") is not True
    ):
        raise ValueError("public installer internal-integrity conclusion is invalid")
    expected_gate = "pass" if parity and signatures_valid and source_bound else "fail"
    if conclusion.get("publication_gate_status") != expected_gate:
        raise ValueError("public installer publication gate status does not recompute")
    if any(
        conclusion.get(field) is not False
        for field in ("deployment_performed", "release_modified", "server_modified")
    ):
        raise ValueError("public installer audit cannot claim external changes")
    return payload


def verify_new_immutable_installer_release(
    *,
    previous_audit: Mapping[str, Any],
    candidate: Mapping[str, Any],
) -> dict[str, Any]:
    """Verify a future signed candidate without authorizing its publication."""

    verify_public_installer_origin_audit(dict(previous_audit))
    if candidate.get("contract_version") != IMMUTABLE_INSTALLER_RELEASE_CONTRACT_VERSION:
        raise ValueError("immutable installer publication contract version is invalid")
    previous_release = _require_mapping(previous_audit.get("release"), field="previous release")
    version = _require_semver(candidate.get("version"), field="candidate.version")
    previous_version = _require_semver(
        previous_release.get("version"),
        field="previous release.version",
    )
    # Edition-scoped releases use a monotonically increasing build number, so
    # independently signed builds may intentionally share the display version.
    # The historical generic installer remains the previous-origin authority;
    # it must not force all four first edition releases to invent a new SemVer.
    if _compare_semver_precedence(version, previous_version) < 0:
        raise ValueError("candidate.version cannot downgrade the audited release")
    if (
        candidate.get("version_owner_approved") is not True
        or not isinstance(candidate.get("version_approval_reference"), str)
        or not candidate["version_approval_reference"].strip()
    ):
        raise ValueError("new installer version requires explicit owner approval")
    edition_id = candidate.get("edition_id")
    if edition_id not in _DESKTOP_EDITION_PRODUCTS:
        raise ValueError("candidate.edition_id is not a supported desktop edition")
    build_number = _require_positive_int(
        candidate.get("build_number"),
        field="candidate.build_number",
    )
    product_name = _DESKTOP_EDITION_PRODUCTS[edition_id]
    filename = candidate.get("file_name")
    expected_filename = f"{product_name}-{version}.exe"
    if filename != expected_filename or filename == previous_release.get("file_name"):
        raise ValueError("new installer bytes require the edition product filename")
    release_tag = f"desktop-{edition_id}-v{version}-build-{build_number}"
    channel_tag = f"desktop-{edition_id}-channel"
    metadata_file = f"latest-{edition_id}.json"
    if candidate.get("release_tag") != release_tag:
        raise ValueError("candidate release tag does not match edition and build")
    sha256 = _require_sha256(candidate.get("sha256"), field="candidate.sha256")
    _require_positive_int(candidate.get("bytes"), field="candidate.bytes")
    previous_origins = _require_mapping(previous_audit.get("origins"), field="previous origins")
    previous_hashes = {
        _require_mapping(value, field="previous origin").get("sha256")
        for value in previous_origins.values()
    }
    if sha256 in previous_hashes:
        raise ValueError("new version unexpectedly reuses old installer bytes")
    if candidate.get("checksum_verified") is not True:
        raise ValueError("candidate checksum is not verified")
    if candidate.get("authenticode_status") != "Valid":
        raise ValueError("candidate Authenticode status must be Valid")
    if candidate.get("has_pe_certificate_table") is not True:
        raise ValueError("candidate lacks a PE certificate table")
    if candidate.get("updater_signature_present") is not True:
        raise ValueError("candidate lacks the independent Tauri updater signature")
    if candidate.get("source_inventory_commit") != candidate.get("source_commit"):
        raise ValueError("candidate release inventory does not bind the source commit")
    _require_commit(candidate.get("source_commit"), field="candidate.source_commit")
    if candidate.get("single_installer_for_both_origins") is not True:
        raise ValueError("both origins must consume the same exact installer bytes")
    updater = _require_mapping(
        candidate.get("updater_manifest"),
        field="candidate.updater_manifest",
    )
    expected_url_suffix = f"/{release_tag}/{filename}"
    if (
        updater.get("version") != version
        or updater.get("edition_id") != edition_id
        or updater.get("build_number") != build_number
        or updater.get("source_commit") != candidate.get("source_commit")
        or updater.get("metadata_file") != metadata_file
        or updater.get("channel_tag") != channel_tag
        or not isinstance(updater.get("signature"), str)
        or not updater["signature"].strip()
        or not isinstance(updater.get("download_url"), str)
        or not str(updater["download_url"]).endswith(expected_url_suffix)
    ):
        raise ValueError("candidate updater latest.json does not bind exact new bytes")
    origin_metadata = _require_mapping(
        candidate.get("origin_metadata"),
        field="candidate.origin_metadata",
    )
    for name in ("global_github_release", "alibaba_baota_mirror"):
        metadata = _require_mapping(
            origin_metadata.get(name),
            field=f"candidate.origin_metadata.{name}",
        )
        if (
            metadata.get("version") != version
            or metadata.get("edition_id") != edition_id
            or metadata.get("build_number") != build_number
            or metadata.get("release_tag") != release_tag
            or metadata.get("file_name") != filename
            or metadata.get("sha256") != sha256
            or metadata.get("size_bytes") != candidate.get("bytes")
            or not isinstance(metadata.get("download_url"), str)
            or not metadata["download_url"].endswith(filename)
            or metadata.get("checksum_url") != f"{metadata['download_url']}.sha256"
        ):
            raise ValueError(f"{name} metadata does not bind exact new bytes")
    return {
        "status": "passed",
        "edition_id": edition_id,
        "version": version,
        "build_number": build_number,
        "file_name": filename,
        "sha256": sha256,
        "source_commit": candidate["source_commit"],
        "publication_authorized": False,
    }


__all__ = [
    "AUTHORITATIVE_MIRROR_CHECKSUM_SHA256",
    "AUTHORITATIVE_WEBSITE_RECEIPT_BYTES",
    "AUTHORITATIVE_WEBSITE_RECEIPT_SHA256",
    "FROZEN_GLOBAL_CHECKSUM_SHA256",
    "FROZEN_GLOBAL_INSTALLER_BYTES",
    "FROZEN_GLOBAL_INSTALLER_SHA256",
    "FROZEN_MIRROR_INSTALLER_BYTES",
    "FROZEN_MIRROR_INSTALLER_SHA256",
    "IMMUTABLE_INSTALLER_RELEASE_CONTRACT_VERSION",
    "PUBLIC_INSTALLER_AUDIT_CLAIM_BOUNDARY",
    "PUBLIC_INSTALLER_AUDIT_SCHEMA_VERSION",
    "SUPERSEDED_WEBSITE_RECEIPT_SHA256",
    "build_public_installer_origin_audit",
    "canonical_pretty_bytes",
    "inspect_installer",
    "inspect_pe_certificate_table",
    "verify_checksum_file",
    "verify_new_immutable_installer_release",
    "verify_public_installer_origin_audit",
]
