"""Export or verify the Harness handoff 6.1-6.6 exact-byte closure index."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = BACKEND_ROOT.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.orchestration.harness_handoff_closure import (  # noqa: E402
    export_harness_handoff_closure,
    verify_harness_handoff_closure,
)

DEFAULT_DIRECTORY = REPOSITORY_ROOT / "artifacts" / "test-runs" / "harness-handoff-closure-v1"
DEFAULT_OUTPUT = DEFAULT_DIRECTORY / "handoff-closure.json"
DEFAULT_CHECKSUM = DEFAULT_DIRECTORY / "handoff-closure.json.sha256"


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-commit")
    parser.add_argument("--generated-at")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--checksum", type=Path, default=DEFAULT_CHECKSUM)
    parser.add_argument(
        "--check",
        action="store_true",
        help="Recompute and verify the existing output without rewriting it.",
    )
    args = parser.parse_args()
    if not args.check and (args.source_commit is None or args.generated_at is None):
        parser.error("--source-commit and --generated-at are required when exporting")
    return args


def main() -> int:
    args = _parse_args()
    if args.check:
        closure = verify_harness_handoff_closure(
            repository_root=REPOSITORY_ROOT,
            output_path=args.output,
            checksum_path=args.checksum,
        )
        action = "verified"
    else:
        closure = export_harness_handoff_closure(
            repository_root=REPOSITORY_ROOT,
            subject_commit=args.source_commit,
            generated_at=args.generated_at,
            output_path=args.output,
            checksum_path=args.checksum,
        )
        action = "exported"
    print(
        json.dumps(
            {
                "action": action,
                "schema_version": closure["schema_version"],
                "subject_commit": closure["subject_commit"],
                "generated_at": closure["generated_at"],
                "manifest_sha256": closure["manifest_sha256"],
                "gap_count": closure["summary"]["gap_count"],
                "technical_report_release_ready": closure["summary"][
                    "technical_report_release_ready"
                ],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
