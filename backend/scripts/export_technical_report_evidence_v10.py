"""Export or verify the software-owned technical-report evidence v10 bundle."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = BACKEND_ROOT.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.orchestration.technical_report_evidence_v10 import (  # noqa: E402
    export_technical_report_evidence_v10,
    verify_technical_report_evidence_v10,
)

DEFAULT_OUTPUT = REPOSITORY_ROOT / "artifacts" / "technical-report" / "evidence-v10.json"
DEFAULT_MANIFEST = REPOSITORY_ROOT / "artifacts" / "technical-report" / "evidence-v10.manifest.json"
DEFAULT_CHECKSUMS = REPOSITORY_ROOT / "artifacts" / "technical-report" / "evidence-v10.sha256"
DEFAULT_CSV_DIRECTORY = REPOSITORY_ROOT / "artifacts" / "technical-report" / "csv-v10"


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-commit")
    parser.add_argument("--generated-at")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--checksums", type=Path, default=DEFAULT_CHECKSUMS)
    parser.add_argument("--csv-directory", type=Path, default=DEFAULT_CSV_DIRECTORY)
    parser.add_argument(
        "--check",
        action="store_true",
        help="Recompute and verify existing output without rewriting it.",
    )
    args = parser.parse_args()
    if not args.check and (args.source_commit is None or args.generated_at is None):
        parser.error("--source-commit and --generated-at are required when exporting")
    return args


def main() -> int:
    args = _parse_args()
    if args.check:
        bundle = verify_technical_report_evidence_v10(
            repository_root=REPOSITORY_ROOT,
            output_path=args.output,
            manifest_path=args.manifest,
            checksum_path=args.checksums,
            csv_directory=args.csv_directory,
        )
        action = "verified"
    else:
        bundle = export_technical_report_evidence_v10(
            repository_root=REPOSITORY_ROOT,
            output_path=args.output,
            manifest_path=args.manifest,
            checksum_path=args.checksums,
            csv_directory=args.csv_directory,
            source_commit=args.source_commit,
            generated_at=args.generated_at,
        )
        action = "exported"
    print(
        json.dumps(
            {
                "action": action,
                "schema_version": bundle["schema_version"],
                "source_commit": bundle["source_commit"],
                "generated_at": bundle["generated_at"],
                "bundle_sha256": bundle["bundle_sha256"],
                "online_routing_current_for_evidence_2_9": bundle["release_readiness"][
                    "online_routing_current_for_evidence_2_9"
                ],
                "release_ready": bundle["release_readiness"]["release_ready"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
