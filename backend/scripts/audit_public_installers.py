"""Generate or verify a no-write audit of two public Windows installer origins."""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.release.installer_integrity import (  # noqa: E402
    AUTHORITATIVE_WEBSITE_RECEIPT_SHA256,
    build_public_installer_origin_audit,
    canonical_pretty_bytes,
    verify_public_installer_origin_audit,
)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _load_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid public installer audit: {path}") from exc
    if not isinstance(payload, dict):
        raise ValueError("public installer audit must contain a JSON object")
    return payload


def _write_audit(
    payload: dict[str, Any],
    *,
    output_path: Path,
    sha256_output_path: Path,
) -> None:
    output_path = output_path.resolve()
    sha256_output_path = sha256_output_path.resolve()
    if output_path == sha256_output_path:
        raise ValueError("audit and checksum outputs must use different paths")
    existing = [path for path in (output_path, sha256_output_path) if path.exists()]
    if existing:
        raise ValueError(
            "refusing to overwrite frozen installer audit output: "
            + ", ".join(str(path) for path in existing)
        )
    audit_bytes = canonical_pretty_bytes(payload)
    audit_sha256 = hashlib.sha256(audit_bytes).hexdigest()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    sha256_output_path.parent.mkdir(parents=True, exist_ok=True)
    created: list[Path] = []
    try:
        with output_path.open("xb") as handle:
            created.append(output_path)
            handle.write(audit_bytes)
        with sha256_output_path.open("x", encoding="ascii", newline="\n") as handle:
            created.append(sha256_output_path)
            handle.write(f"{audit_sha256}  {output_path.name}\n")
    except FileExistsError as exc:
        for path in reversed(created):
            with contextlib.suppress(FileNotFoundError):
                path.unlink()
        raise ValueError(
            f"refusing to overwrite frozen installer audit output: {exc.filename}"
        ) from exc
    except Exception:
        # Only remove paths that this call opened with exclusive-create mode.
        # A pre-existing frozen output can therefore never be deleted here.
        for path in reversed(created):
            with contextlib.suppress(FileNotFoundError):
                path.unlink()
        raise


def _verify_sidecar(audit_path: Path, sidecar_path: Path) -> None:
    try:
        raw = sidecar_path.read_text(encoding="ascii")
    except (OSError, UnicodeDecodeError) as exc:
        raise ValueError(f"cannot read audit checksum: {sidecar_path}") from exc
    expected = f"{_sha256_file(audit_path)}  {audit_path.name}\n"
    if raw != expected:
        raise ValueError("audit checksum does not bind the exact audit file")


def _add_exact_source_arguments(
    parser: argparse.ArgumentParser,
    *,
    required: bool,
) -> None:
    parser.add_argument("--global-installer", type=Path, required=required)
    parser.add_argument("--global-checksum", type=Path, required=required)
    parser.add_argument("--mirror-installer", type=Path, required=required)
    parser.add_argument("--mirror-checksum", type=Path, required=required)
    parser.add_argument("--website-receipt", type=Path, required=required)


def _build_from_args(args: argparse.Namespace) -> dict[str, Any]:
    return build_public_installer_origin_audit(
        global_installer=args.global_installer.resolve(),
        global_checksum=args.global_checksum.resolve(),
        mirror_installer=args.mirror_installer.resolve(),
        mirror_checksum=args.mirror_checksum.resolve(),
        global_authenticode_status=args.global_authenticode_status,
        mirror_authenticode_status=args.mirror_authenticode_status,
        version=args.version,
        release_tag=args.release_tag,
        release_target_commit=args.release_target_commit,
        release_inventory_source_commit=args.release_inventory_source_commit,
        auditor_commit=args.auditor_commit,
        generated_at=args.generated_at,
        website_receipt_path=args.website_receipt.resolve(),
        website_receipt_expected_sha256=AUTHORITATIVE_WEBSITE_RECEIPT_SHA256,
    )


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    generate = subparsers.add_parser(
        "generate",
        help="Inspect exact local downloads and write a content-addressed audit.",
    )
    _add_exact_source_arguments(generate, required=True)
    generate.add_argument("--global-authenticode-status", required=True)
    generate.add_argument("--mirror-authenticode-status", required=True)
    generate.add_argument("--version", required=True)
    generate.add_argument("--release-tag", required=True)
    generate.add_argument("--release-target-commit", required=True)
    generate.add_argument("--release-inventory-source-commit", required=True)
    generate.add_argument("--auditor-commit", required=True)
    generate.add_argument("--generated-at", required=True)
    generate.add_argument("--output", type=Path, required=True)
    generate.add_argument("--sha256-output", type=Path, required=True)

    verify = subparsers.add_parser(
        "verify",
        help="Recompute the audit contract, checksum, and optionally exact source files.",
    )
    verify.add_argument("--audit", type=Path, required=True)
    verify.add_argument("--sha256", type=Path)
    verify.add_argument(
        "--exact-sources",
        action="store_true",
        help="Reinspect every downloaded file and the authoritative website receipt.",
    )
    _add_exact_source_arguments(verify, required=False)
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    if args.command == "generate":
        payload = _build_from_args(args)
        _write_audit(
            payload,
            output_path=args.output.resolve(),
            sha256_output_path=args.sha256_output.resolve(),
        )
        print(
            json.dumps(
                {
                    "audit": str(args.output.resolve()),
                    "audit_file_sha256": _sha256_file(args.output.resolve()),
                    "audit_sha256": payload["audit_sha256"],
                    "publication_gate_status": payload["conclusion"]["publication_gate_status"],
                },
                sort_keys=True,
            )
        )
        return 0

    audit_path = args.audit.resolve()
    payload = verify_public_installer_origin_audit(_load_json(audit_path))
    if args.sha256 is not None:
        _verify_sidecar(audit_path, args.sha256.resolve())
    if args.exact_sources:
        required_paths = {
            name: getattr(args, name)
            for name in (
                "global_installer",
                "global_checksum",
                "mirror_installer",
                "mirror_checksum",
                "website_receipt",
            )
        }
        missing = sorted(name for name, value in required_paths.items() if value is None)
        if missing:
            raise ValueError(
                "--exact-sources requires: " + ", ".join(name.replace("_", "-") for name in missing)
            )
        exact = build_public_installer_origin_audit(
            global_installer=args.global_installer.resolve(),
            global_checksum=args.global_checksum.resolve(),
            mirror_installer=args.mirror_installer.resolve(),
            mirror_checksum=args.mirror_checksum.resolve(),
            global_authenticode_status=payload["origins"]["global_github_release"][
                "authenticode_status"
            ],
            mirror_authenticode_status=payload["origins"]["alibaba_baota_mirror"][
                "authenticode_status"
            ],
            version=payload["release"]["version"],
            release_tag=payload["release"]["tag"],
            release_target_commit=payload["release"]["release_target_commit"],
            release_inventory_source_commit=payload["release"]["release_inventory_source_commit"],
            auditor_commit=payload["auditor_commit"],
            generated_at=payload["generated_at"],
            website_receipt_path=args.website_receipt.resolve(),
            website_receipt_expected_sha256=AUTHORITATIVE_WEBSITE_RECEIPT_SHA256,
        )
        if exact != payload:
            raise ValueError("public installer audit does not match exact source files")
    print(
        json.dumps(
            {
                "audit": str(audit_path),
                "audit_file_sha256": _sha256_file(audit_path),
                "audit_sha256": payload["audit_sha256"],
                "exact_sources_verified": args.exact_sources,
                "status": "verified",
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
