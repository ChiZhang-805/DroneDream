"""Create a verified deterministic archive of one experiment-evidence directory.

The tool is deliberately fail-closed.  It archives successful, failed, mixed,
or cancelled experiment material without filtering outcomes; rejects obvious
credential material and filesystem indirection; verifies every byte after ZIP
creation; and only removes enumerated source files when the caller explicitly
requests deletion after verification.
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
import re
import stat
import uuid
import zipfile
from pathlib import Path
from typing import Any, Literal

ARCHIVE_SCHEMA_VERSION = "dronedream.experiment-evidence-archive/v1"
RECEIPT_SCHEMA_VERSION = "dronedream.experiment-evidence-archive-receipt/v1"
ARCHIVE_MANIFEST_NAME = "dronedream-archive-manifest.json"
TerminalStatus = Literal["success", "failed", "mixed", "cancelled"]

_FORBIDDEN_BASENAMES = {
    ".env",
    ".env.local",
    ".env.production",
    "credentials.json",
    "id_rsa",
    "id_ed25519",
}
_FORBIDDEN_SUFFIXES = {".key", ".pem", ".p12", ".pfx"}
_SECRET_PATTERNS = (
    re.compile(rb"\bsk-[A-Za-z0-9_-]{20,}\b"),
    re.compile(rb"(?i)\bOPENAI_API_KEY\s*=\s*[^\s\"']{8,}"),
    re.compile(rb"(?i)\bHARNESS_ROUTING_API_KEY\s*=\s*[^\s\"']{8,}"),
    re.compile(
        rb"(?i)\b(password|api[_-]?key|client[_-]?secret)\s*[:=]\s*[\"']?"
        rb"(?!false\b|null\b|none\b|absent\b|redacted\b)[^\s\"',}]{8,}"
    ),
)
_TEXT_SCAN_LIMIT_BYTES = 8 * 1024 * 1024


class EvidenceArchiveError(RuntimeError):
    """Raised when archival or verification cannot safely complete."""


def _canonical_json_bytes(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, allow_nan=False, indent=2, sort_keys=True)
        + "\n"
    ).encode("utf-8")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _is_reparse_point(path: Path) -> bool:
    attributes = getattr(path.lstat(), "st_file_attributes", 0)
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x0400)
    return bool(attributes & reparse_flag)


def _validate_source_root(source: Path) -> Path:
    resolved = source.resolve(strict=True)
    if not resolved.is_dir():
        raise EvidenceArchiveError("source must be an existing directory")
    if resolved.parent == resolved:
        raise EvidenceArchiveError("filesystem root cannot be archived")
    if len(resolved.parts) < 3:
        raise EvidenceArchiveError("source directory is too broad to archive safely")
    if resolved.is_symlink() or _is_reparse_point(resolved):
        raise EvidenceArchiveError("source directory cannot be a symlink or reparse point")
    return resolved


def _validate_output_paths(source: Path, archive: Path, receipt: Path) -> tuple[Path, Path]:
    archive_resolved = archive.resolve(strict=False)
    receipt_resolved = receipt.resolve(strict=False)
    try:
        archive_resolved.relative_to(source)
    except ValueError:
        pass
    else:
        raise EvidenceArchiveError("archive output must be outside the source directory")
    try:
        receipt_resolved.relative_to(source)
    except ValueError:
        pass
    else:
        raise EvidenceArchiveError("receipt output must be outside the source directory")
    if archive_resolved == receipt_resolved:
        raise EvidenceArchiveError("archive and receipt outputs must differ")
    if archive_resolved.suffix.lower() != ".zip":
        raise EvidenceArchiveError("archive output must use the .zip suffix")
    for target in (archive_resolved, receipt_resolved):
        if target.exists():
            raise FileExistsError(f"refusing to overwrite existing output: {target}")
        target.parent.mkdir(parents=True, exist_ok=True)
    return archive_resolved, receipt_resolved


def _scan_secret_content(path: Path, relative_path: str) -> None:
    size = path.stat().st_size
    if size > _TEXT_SCAN_LIMIT_BYTES:
        return
    payload = path.read_bytes()
    if b"\x00" in payload[:4096]:
        return
    for pattern in _SECRET_PATTERNS:
        if pattern.search(payload):
            raise EvidenceArchiveError(
                f"possible credential material detected in {relative_path}"
            )


def _collect_files(source: Path) -> list[tuple[Path, str, int, str]]:
    collected: list[tuple[Path, str, int, str]] = []
    for path in sorted(source.rglob("*"), key=lambda item: item.as_posix().casefold()):
        if path.is_symlink() or _is_reparse_point(path):
            raise EvidenceArchiveError(f"symlink or reparse point is not allowed: {path}")
        if path.is_dir():
            continue
        if not path.is_file():
            raise EvidenceArchiveError(f"unsupported filesystem entry: {path}")
        relative = path.relative_to(source).as_posix()
        if relative == ARCHIVE_MANIFEST_NAME:
            raise EvidenceArchiveError(f"reserved archive path already exists: {relative}")
        lower_name = path.name.casefold()
        if lower_name in _FORBIDDEN_BASENAMES or path.suffix.casefold() in _FORBIDDEN_SUFFIXES:
            raise EvidenceArchiveError(f"credential-like filename is not allowed: {relative}")
        _scan_secret_content(path, relative)
        collected.append((path, relative, path.stat().st_size, _sha256_file(path)))
    if not collected:
        raise EvidenceArchiveError("source directory contains no evidence files")
    return collected


def _manifest(
    *,
    source_label: str,
    terminal_status: TerminalStatus,
    files: list[tuple[Path, str, int, str]],
) -> dict[str, Any]:
    if not source_label.strip() or len(source_label) > 200:
        raise EvidenceArchiveError("source label must contain 1 to 200 characters")
    unsigned: dict[str, Any] = {
        "schema_version": ARCHIVE_SCHEMA_VERSION,
        "source_label": source_label.strip(),
        "terminal_status": terminal_status,
        "outcome_filtering_applied": False,
        "file_count": len(files),
        "original_bytes": sum(item[2] for item in files),
        "files": [
            {"path": relative, "bytes": size, "sha256": digest}
            for _path, relative, size, digest in files
        ],
    }
    compact = json.dumps(
        unsigned,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return {**unsigned, "manifest_sha256": _sha256_bytes(compact)}


def _zip_info(relative_path: str) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(relative_path, date_time=(1980, 1, 1, 0, 0, 0))
    info.compress_type = zipfile.ZIP_DEFLATED
    info.create_system = 3
    info.external_attr = (0o100644 & 0xFFFF) << 16
    return info


def _write_archive(
    archive_path: Path,
    manifest: dict[str, Any],
    files: list[tuple[Path, str, int, str]],
) -> None:
    temporary = archive_path.with_name(f".{archive_path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with zipfile.ZipFile(
            temporary,
            mode="x",
            compression=zipfile.ZIP_DEFLATED,
            compresslevel=9,
            allowZip64=True,
        ) as archive:
            archive.writestr(
                _zip_info(ARCHIVE_MANIFEST_NAME),
                _canonical_json_bytes(manifest),
                compress_type=zipfile.ZIP_DEFLATED,
                compresslevel=9,
            )
            for path, relative, _size, _digest in files:
                archive.writestr(
                    _zip_info(relative),
                    path.read_bytes(),
                    compress_type=zipfile.ZIP_DEFLATED,
                    compresslevel=9,
                )
        os.replace(temporary, archive_path)
    finally:
        if temporary.exists():
            temporary.unlink()


def verify_experiment_evidence_archive(archive_path: Path) -> dict[str, Any]:
    """Verify entry set, canonical manifest hash, sizes, and every file hash."""

    with zipfile.ZipFile(archive_path, "r") as archive:
        names = archive.namelist()
        if len(names) != len(set(names)) or ARCHIVE_MANIFEST_NAME not in names:
            raise EvidenceArchiveError("archive entry set is invalid")
        try:
            manifest = json.loads(archive.read(ARCHIVE_MANIFEST_NAME).decode("utf-8"))
        except (KeyError, UnicodeError, json.JSONDecodeError) as exc:
            raise EvidenceArchiveError("archive manifest is unreadable") from exc
        if (
            not isinstance(manifest, dict)
            or manifest.get("schema_version") != ARCHIVE_SCHEMA_VERSION
        ):
            raise EvidenceArchiveError("archive manifest schema is invalid")
        embedded = manifest.get("manifest_sha256")
        unsigned = {key: value for key, value in manifest.items() if key != "manifest_sha256"}
        compact = json.dumps(
            unsigned,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        if not isinstance(embedded, str) or embedded != _sha256_bytes(compact):
            raise EvidenceArchiveError("archive manifest hash mismatch")
        rows = manifest.get("files")
        if not isinstance(rows, list):
            raise EvidenceArchiveError("archive manifest files list is invalid")
        expected_names = {ARCHIVE_MANIFEST_NAME}
        for row in rows:
            if not isinstance(row, dict):
                raise EvidenceArchiveError("archive manifest file row is invalid")
            relative = row.get("path")
            if (
                not isinstance(relative, str)
                or not relative
                or relative.startswith(("/", "\\"))
                or ".." in Path(relative).parts
            ):
                raise EvidenceArchiveError("archive manifest contains an unsafe path")
            payload = archive.read(relative)
            if len(payload) != row.get("bytes") or _sha256_bytes(payload) != row.get("sha256"):
                raise EvidenceArchiveError(f"archive payload mismatch: {relative}")
            expected_names.add(relative)
        if set(names) != expected_names or len(rows) != manifest.get("file_count"):
            raise EvidenceArchiveError("archive entries do not match the manifest")
        return manifest


def _delete_verified_source(
    source: Path,
    files: list[tuple[Path, str, int, str]],
) -> None:
    """Delete only the exact verified file inventory, then empty directories."""

    for path, relative, size, digest in files:
        resolved = path.resolve(strict=True)
        try:
            resolved.relative_to(source)
        except ValueError as exc:
            raise EvidenceArchiveError(f"refusing to delete out-of-root file: {relative}") from exc
        if resolved.stat().st_size != size or _sha256_file(resolved) != digest:
            raise EvidenceArchiveError(f"source changed before deletion: {relative}")
    for path, _relative, _size, _digest in files:
        path.unlink()
    directories = sorted(
        (path for path in source.rglob("*") if path.is_dir()),
        key=lambda item: len(item.parts),
        reverse=True,
    )
    for directory in directories:
        with contextlib.suppress(OSError):
            directory.rmdir()


def archive_experiment_evidence(
    *,
    source: Path,
    archive_path: Path,
    receipt_path: Path,
    source_label: str,
    terminal_status: TerminalStatus,
    delete_source_after_verify: bool = False,
) -> dict[str, Any]:
    source_root = _validate_source_root(source)
    archive_target, receipt_target = _validate_output_paths(
        source_root,
        archive_path,
        receipt_path,
    )
    files = _collect_files(source_root)
    manifest = _manifest(
        source_label=source_label,
        terminal_status=terminal_status,
        files=files,
    )
    _write_archive(archive_target, manifest, files)
    verified = verify_experiment_evidence_archive(archive_target)
    if verified != manifest:
        raise EvidenceArchiveError("post-write archive verification drifted")
    deletion_performed = False
    if delete_source_after_verify:
        _delete_verified_source(source_root, files)
        deletion_performed = True
    receipt: dict[str, Any] = {
        "schema_version": RECEIPT_SCHEMA_VERSION,
        "source_label": manifest["source_label"],
        "terminal_status": manifest["terminal_status"],
        "archive_path": str(archive_target),
        "archive_bytes": archive_target.stat().st_size,
        "archive_sha256": _sha256_file(archive_target),
        "manifest_sha256": manifest["manifest_sha256"],
        "file_count": manifest["file_count"],
        "original_bytes": manifest["original_bytes"],
        "delete_source_after_verify_requested": delete_source_after_verify,
        "delete_source_after_verify_performed": deletion_performed,
        "verification": "passed",
    }
    receipt_payload = _canonical_json_bytes(receipt)
    with receipt_target.open("xb") as handle:
        handle.write(receipt_payload)
    return receipt


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--source-label", required=True)
    parser.add_argument(
        "--terminal-status",
        choices=("success", "failed", "mixed", "cancelled"),
        required=True,
    )
    parser.add_argument("--delete-source-after-verify", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    receipt = archive_experiment_evidence(
        source=args.source,
        archive_path=args.archive,
        receipt_path=args.receipt,
        source_label=args.source_label,
        terminal_status=args.terminal_status,
        delete_source_after_verify=args.delete_source_after_verify,
    )
    print(json.dumps(receipt, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
