"""Export, check, or verify the real-PX4 advanced-physics evidence bundle."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.simulator.advanced_physics_evidence import (  # noqa: E402
    export_advanced_physics_evidence,
    verify_advanced_physics_evidence,
)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    export = subparsers.add_parser("export")
    export.add_argument("--source-root", type=Path, required=True)
    export.add_argument("--output-root", type=Path, required=True)
    export.add_argument("--subject-commit", required=True)
    export.add_argument("--exporter-commit", required=True)
    export.add_argument("--generated-at", required=True)
    export.add_argument("--check", action="store_true")

    verify = subparsers.add_parser("verify")
    verify.add_argument("--evidence-root", type=Path, required=True)
    verify.add_argument("--source-root", type=Path)
    return parser.parse_args()


def _file_map(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def _check_export(args: argparse.Namespace) -> tuple[dict[str, Any], dict[str, Any]]:
    output_root = args.output_root.resolve()
    if not output_root.is_dir():
        raise ValueError(f"evidence output does not exist: {output_root}")
    with tempfile.TemporaryDirectory(prefix="dronedream-advanced-physics-check-") as raw:
        check_root = Path(raw) / "bundle"
        manifest, receipt = export_advanced_physics_evidence(
            source_root=args.source_root.resolve(),
            output_root=check_root,
            subject_commit=args.subject_commit,
            exporter_commit=args.exporter_commit,
            generated_at=args.generated_at,
        )
        expected = _file_map(check_root)
        observed = _file_map(output_root)
        if observed != expected:
            missing = sorted(set(expected) - set(observed))
            extra = sorted(set(observed) - set(expected))
            changed = sorted(
                path
                for path in set(expected) & set(observed)
                if expected[path] != observed[path]
            )
            raise ValueError(
                "advanced-physics evidence is stale: "
                f"missing={missing}, extra={extra}, changed={changed}"
            )
    return manifest, receipt


def main() -> int:
    args = _parse_args()
    if args.command == "export":
        if args.check:
            manifest, receipt = _check_export(args)
        else:
            output_root = args.output_root.resolve()
            if output_root.exists():
                if any(output_root.iterdir()):
                    raise ValueError(
                        f"output directory must be absent or empty: {output_root}"
                    )
            else:
                output_root.mkdir(parents=True)
            manifest, receipt = export_advanced_physics_evidence(
                source_root=args.source_root.resolve(),
                output_root=output_root,
                subject_commit=args.subject_commit,
                exporter_commit=args.exporter_commit,
                generated_at=args.generated_at,
            )
        result = {
            "status": "passed",
            "mode": "check" if args.check else "export",
            "manifest_sha256": manifest["manifest_sha256"],
            "receipt_sha256": receipt["receipt_sha256"],
            "attempt_count": manifest["summary"]["attempt_count"],
            "successful_flights": manifest["summary"]["successful_flight_count"],
            "gps_readiness_boundaries": manifest["summary"][
                "gps_readiness_boundary_count"
            ],
        }
    else:
        manifest, receipt = verify_advanced_physics_evidence(
            evidence_root=args.evidence_root.resolve(),
            source_root=(
                args.source_root.resolve() if args.source_root is not None else None
            ),
        )
        result = {
            "status": "passed",
            "mode": "verify",
            "manifest_sha256": manifest["manifest_sha256"],
            "receipt_sha256": receipt["receipt_sha256"],
            "raw_source_verified": args.source_root is not None,
        }
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, shutil.Error) as error:
        print(f"advanced-physics evidence error: {error}", file=sys.stderr)
        raise SystemExit(1) from error
