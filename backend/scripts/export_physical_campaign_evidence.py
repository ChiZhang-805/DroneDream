"""Export or verify the fixed six-Trial real PX4/Gazebo evidence campaign."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = BACKEND_ROOT.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.simulator.physical_campaign_evidence import (  # noqa: E402
    export_physical_campaign_evidence,
    verify_physical_campaign_evidence,
)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    generate = subparsers.add_parser("generate")
    generate.add_argument("--source-root", type=Path, required=True)
    generate.add_argument("--failure-root", type=Path, required=True)
    generate.add_argument("--output-root", type=Path, required=True)
    generate.add_argument(
        "--runtime-release",
        type=Path,
        default=REPOSITORY_ROOT / "runtime" / "tests" / "fixtures" / "runtime-release.json",
    )
    generate.add_argument("--runtime-observation", type=Path, required=True)
    generate.add_argument("--subject-commit", required=True)
    generate.add_argument("--exporter-commit", required=True)
    generate.add_argument("--failure-source-commit", required=True)
    generate.add_argument("--generated-at", required=True)

    verify = subparsers.add_parser("verify")
    verify.add_argument("--evidence-root", type=Path, required=True)
    verify.add_argument("--source-root", type=Path)
    verify.add_argument("--failure-root", type=Path)
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    if args.command == "generate":
        output_root = args.output_root.resolve()
        manifest, receipt = export_physical_campaign_evidence(
            source_root=args.source_root.resolve(),
            failure_root=args.failure_root.resolve(),
            output_root=output_root,
            runtime_manifest_path=args.runtime_release.resolve(),
            runtime_observation_path=args.runtime_observation.resolve(),
            subject_commit=args.subject_commit,
            exporter_commit=args.exporter_commit,
            failure_source_commit=args.failure_source_commit,
            generated_at=args.generated_at,
        )
        verify_physical_campaign_evidence(
            output_root,
            source_root=args.source_root.resolve(),
            failure_root=args.failure_root.resolve(),
        )
        print(
            json.dumps(
                {
                    "evidence_root": str(output_root),
                    "manifest_sha256": manifest["manifest_sha256"],
                    "receipt_sha256": receipt["receipt_sha256"],
                    "trial_count": manifest["summary"]["trial_count"],
                    "retained_failure_probes": manifest["summary"][
                        "retained_failure_probe_count"
                    ],
                    "exact_sources_verified": True,
                },
                sort_keys=True,
            )
        )
        return 0

    if (args.source_root is None) != (args.failure_root is None):
        raise ValueError(
            "--source-root and --failure-root must be supplied together for exact verification"
        )
    manifest, receipt = verify_physical_campaign_evidence(
        args.evidence_root.resolve(),
        source_root=args.source_root.resolve() if args.source_root is not None else None,
        failure_root=args.failure_root.resolve() if args.failure_root is not None else None,
    )
    print(
        json.dumps(
            {
                "evidence_root": str(args.evidence_root.resolve()),
                "manifest_sha256": manifest["manifest_sha256"],
                "receipt_sha256": receipt["receipt_sha256"],
                "exact_sources_verified": args.source_root is not None,
                "status": "verified",
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
