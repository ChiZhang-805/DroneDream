"""Freeze or independently check AURORA reflection-trigger contract ablations."""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import sys
from pathlib import Path
from typing import Any

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.orchestration.harness_reflection_trigger_ablation import (  # noqa: E402
    build_harness_reflection_trigger_artifact,
    build_harness_reflection_trigger_manifest,
    verify_harness_reflection_trigger_artifact,
    verify_harness_reflection_trigger_manifest,
)

_STEM = "harness-reflection-trigger-ablation-v1"
DEFAULT_JSON_OUTPUT = BACKEND_ROOT / "evaluation_artifacts" / f"{_STEM}.json"
DEFAULT_CSV_OUTPUT = BACKEND_ROOT / "evaluation_artifacts" / f"{_STEM}.csv"
DEFAULT_MANIFEST_OUTPUT = BACKEND_ROOT / "evaluation_artifacts" / f"{_STEM}.manifest.json"
DEFAULT_SHA256_OUTPUT = BACKEND_ROOT / "evaluation_artifacts" / f"{_STEM}.sha256"

CSV_FIELDS = (
    "case_id",
    "trigger",
    "step_id",
    "arm",
    "intervention_activated",
    "result_status",
    "plan_phase",
    "batch_policy",
    "reason_codes",
    "eligible_tools",
    "selectable_tools",
    "selected_tool",
    "decision_memory_count",
    "verified_reflection_count",
    "observed_outcome_count",
    "removed_reflection_count",
    "snapshot_sha256",
)


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _json_bytes(value: dict[str, Any]) -> bytes:
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


def _csv_bytes(artifact: dict[str, Any]) -> bytes:
    rows: list[dict[str, Any]] = []
    for case in artifact["case_rows"]:
        for step in case["steps"]:
            for arm in step["arms"]:
                rows.append(
                    {
                        "case_id": case["case_id"],
                        "trigger": case["trigger"],
                        "step_id": step["step_id"],
                        "arm": arm["arm"],
                        "intervention_activated": step["intervention_activated"],
                        "result_status": step["result_status"],
                        "plan_phase": arm["plan_phase"],
                        "batch_policy": arm["batch_policy"],
                        "reason_codes": ">".join(arm["reason_codes"]),
                        "eligible_tools": ">".join(arm["eligible_tools"]),
                        "selectable_tools": ">".join(arm["selectable_tools"]),
                        "selected_tool": arm["selected_tool"],
                        "decision_memory_count": arm["decision_memory_count"],
                        "verified_reflection_count": arm[
                            "verified_reflection_count"
                        ],
                        "observed_outcome_count": arm["observed_outcome_count"],
                        "removed_reflection_count": arm[
                            "removed_reflection_count"
                        ],
                        "snapshot_sha256": arm["snapshot_sha256"],
                    }
                )
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(
        buffer,
        fieldnames=list(CSV_FIELDS),
        lineterminator="\n",
    )
    writer.writeheader()
    writer.writerows(rows)
    return buffer.getvalue().encode("utf-8")


def render_harness_reflection_trigger_files(
    artifact: dict[str, Any],
    manifest: dict[str, Any],
    *,
    json_name: str,
    csv_name: str,
    manifest_name: str,
) -> tuple[bytes, bytes, bytes, bytes]:
    verify_harness_reflection_trigger_manifest(manifest)
    verify_harness_reflection_trigger_artifact(artifact, manifest=manifest)
    json_payload = _json_bytes(artifact)
    csv_payload = _csv_bytes(artifact)
    manifest_payload = _json_bytes(manifest)
    hashes = (
        f"{_sha256(json_payload)}  {json_name}\n"
        f"{_sha256(csv_payload)}  {csv_name}\n"
        f"{_sha256(manifest_payload)}  {manifest_name}\n"
    ).encode("ascii")
    return json_payload, csv_payload, manifest_payload, hashes


def write_harness_reflection_trigger_files(
    *,
    json_path: Path,
    csv_path: Path,
    manifest_path: Path,
    sha256_path: Path,
    check: bool = False,
) -> dict[str, Any]:
    manifest = build_harness_reflection_trigger_manifest()
    artifact = build_harness_reflection_trigger_artifact()
    payloads = render_harness_reflection_trigger_files(
        artifact,
        manifest,
        json_name=json_path.name,
        csv_name=csv_path.name,
        manifest_name=manifest_path.name,
    )
    outputs = (
        (json_path, payloads[0]),
        (csv_path, payloads[1]),
        (manifest_path, payloads[2]),
        (sha256_path, payloads[3]),
    )
    if check:
        mismatches = [
            str(path)
            for path, expected in outputs
            if not path.is_file() or path.read_bytes() != expected
        ]
        if mismatches:
            raise ValueError(
                "Harness reflection-trigger artifacts are stale: "
                + ", ".join(mismatches)
            )
    else:
        for path, payload in outputs:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(payload)
    return {
        "artifact_sha256": artifact["artifact_sha256"],
        "manifest_sha256": manifest["manifest_sha256"],
        "json_file_sha256": _sha256(payloads[0]),
        "csv_file_sha256": _sha256(payloads[1]),
        "manifest_file_sha256": _sha256(payloads[2]),
        "summary": artifact["summary"],
    }


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json-output", type=Path, default=DEFAULT_JSON_OUTPUT)
    parser.add_argument("--csv-output", type=Path, default=DEFAULT_CSV_OUTPUT)
    parser.add_argument(
        "--manifest-output",
        type=Path,
        default=DEFAULT_MANIFEST_OUTPUT,
    )
    parser.add_argument(
        "--sha256-output",
        type=Path,
        default=DEFAULT_SHA256_OUTPUT,
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Recompute the suite and require byte-identical frozen files.",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    result = write_harness_reflection_trigger_files(
        json_path=args.json_output.resolve(),
        csv_path=args.csv_output.resolve(),
        manifest_path=args.manifest_output.resolve(),
        sha256_path=args.sha256_output.resolve(),
        check=args.check,
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
