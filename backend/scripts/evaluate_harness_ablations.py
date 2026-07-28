"""Export deterministic offline Harness source-contract ablations."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.orchestration.harness_ablation import (  # noqa: E402
    build_harness_ablation_artifact,
)

DEFAULT_JSON_OUTPUT = BACKEND_ROOT / "evaluation_artifacts" / "harness-contract-ablation-v2.json"
DEFAULT_CSV_OUTPUT = BACKEND_ROOT / "evaluation_artifacts" / "harness-contract-ablation-v2.csv"
DEFAULT_SHA256_OUTPUT = (
    BACKEND_ROOT / "evaluation_artifacts" / "harness-contract-ablation-v2.sha256"
)

CSV_FIELDS = (
    "component",
    "case_id",
    "expectation",
    "full_observation",
    "ablated_observation",
    "full_contract_correct",
    "ablated_contract_correct",
)


def _json_bytes(artifact: dict[str, Any]) -> bytes:
    return (
        json.dumps(
            artifact,
            ensure_ascii=False,
            allow_nan=False,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")


def _csv_bytes(artifact: dict[str, Any]) -> bytes:
    import io

    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(
        buffer,
        fieldnames=list(CSV_FIELDS),
        lineterminator="\n",
    )
    writer.writeheader()
    writer.writerows(artifact["probe_rows"])
    return buffer.getvalue().encode("utf-8")


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def render_harness_ablation_files(
    artifact: dict[str, Any],
    *,
    json_name: str,
    csv_name: str,
) -> tuple[bytes, bytes, bytes]:
    json_payload = _json_bytes(artifact)
    csv_payload = _csv_bytes(artifact)
    manifest = (
        f"{_sha256(json_payload)}  {json_name}\n{_sha256(csv_payload)}  {csv_name}\n"
    ).encode("ascii")
    return json_payload, csv_payload, manifest


def write_harness_ablation_files(
    *,
    json_path: Path,
    csv_path: Path,
    sha256_path: Path,
    check: bool = False,
) -> dict[str, str]:
    artifact = build_harness_ablation_artifact()
    json_payload, csv_payload, manifest = render_harness_ablation_files(
        artifact,
        json_name=json_path.name,
        csv_name=csv_path.name,
    )
    outputs = (
        (json_path, json_payload),
        (csv_path, csv_payload),
        (sha256_path, manifest),
    )
    if check:
        mismatches = [
            str(path)
            for path, expected in outputs
            if not path.is_file() or path.read_bytes() != expected
        ]
        if mismatches:
            raise ValueError("Harness ablation artifacts are stale: " + ", ".join(mismatches))
    else:
        for path, payload in outputs:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(payload)
    return {
        "artifact_sha256": str(artifact["artifact_sha256"]),
        "json_file_sha256": _sha256(json_payload),
        "csv_file_sha256": _sha256(csv_payload),
    }


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json-output", type=Path, default=DEFAULT_JSON_OUTPUT)
    parser.add_argument("--csv-output", type=Path, default=DEFAULT_CSV_OUTPUT)
    parser.add_argument("--sha256-output", type=Path, default=DEFAULT_SHA256_OUTPUT)
    parser.add_argument(
        "--check",
        action="store_true",
        help="Fail unless all destination files exactly match current contracts.",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    result = write_harness_ablation_files(
        json_path=args.json_output.resolve(),
        csv_path=args.csv_output.resolve(),
        sha256_path=args.sha256_output.resolve(),
        check=args.check,
    )
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
