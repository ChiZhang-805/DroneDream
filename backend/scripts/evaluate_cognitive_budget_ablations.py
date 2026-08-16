"""Generate or check the fixed-budget adaptive-cognition offline ablation."""

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

from app.orchestration.cognitive_budget_ablation import (  # noqa: E402
    build_cognitive_budget_ablation_artifact,
    build_cognitive_budget_ablation_manifest,
    verify_cognitive_budget_ablation_artifact,
    verify_cognitive_budget_ablation_manifest,
)
from scripts.evidence_output import write_new_evidence_files  # noqa: E402

_STEM = "cognitive-budget-ablation-v1"
DEFAULT_JSON_OUTPUT = BACKEND_ROOT / "evaluation_artifacts" / f"{_STEM}.json"
DEFAULT_CSV_OUTPUT = BACKEND_ROOT / "evaluation_artifacts" / f"{_STEM}.csv"
DEFAULT_MANIFEST_OUTPUT = BACKEND_ROOT / "evaluation_artifacts" / f"{_STEM}.manifest.json"
DEFAULT_SHA256_OUTPUT = BACKEND_ROOT / "evaluation_artifacts" / f"{_STEM}.sha256"

CSV_FIELDS = (
    "case_id",
    "category",
    "arm",
    "expected_optional_turn",
    "optional_turn_triggered",
    "diagnosis_reasons",
    "critic_reasons",
    "suppressed_by_cooldown",
    "qualified",
    "terminal_result",
    "generations_to_first_qualified",
    "simulations_to_first_qualified",
    "provider_turns_to_first_qualified",
    "consumed_simulations",
    "simulated_provider_turns_attempted",
    "time_to_first_qualified_ms",
)


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _json_bytes(value: dict[str, Any]) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, allow_nan=False, indent=2, sort_keys=True)
        + "\n"
    ).encode("utf-8")


def _csv_bytes(artifact: dict[str, Any]) -> bytes:
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=list(CSV_FIELDS), lineterminator="\n")
    writer.writeheader()
    for case in artifact["case_rows"]:
        trigger = case["trigger"]
        for arm in case["arms"]:
            writer.writerow(
                {
                    "case_id": case["case_id"],
                    "category": case["category"],
                    "arm": arm["arm"],
                    "expected_optional_turn": trigger["expected_optional_turn"],
                    "optional_turn_triggered": trigger["optional_turn_triggered"],
                    "diagnosis_reasons": ">".join(trigger["diagnosis_reasons"]),
                    "critic_reasons": ">".join(trigger["critic_reasons"]),
                    "suppressed_by_cooldown": ">".join(
                        trigger["suppressed_by_cooldown"]
                    ),
                    "qualified": arm["qualified"],
                    "terminal_result": arm["terminal_result"],
                    "generations_to_first_qualified": (
                        arm["generations_to_first_qualified"]
                    ),
                    "simulations_to_first_qualified": (
                        arm["simulations_to_first_qualified"]
                    ),
                    "provider_turns_to_first_qualified": (
                        arm["provider_turns_to_first_qualified"]
                    ),
                    "consumed_simulations": arm["consumed_simulations"],
                    "simulated_provider_turns_attempted": (
                        arm["simulated_provider_turns_attempted"]
                    ),
                    "time_to_first_qualified_ms": arm["time_to_first_qualified_ms"],
                }
            )
    return buffer.getvalue().encode("utf-8")


def render_cognitive_budget_ablation_files(
    artifact: dict[str, Any],
    manifest: dict[str, Any],
    *,
    json_name: str,
    csv_name: str,
    manifest_name: str,
) -> tuple[bytes, bytes, bytes, bytes]:
    verify_cognitive_budget_ablation_manifest(manifest)
    verify_cognitive_budget_ablation_artifact(artifact, manifest=manifest)
    json_payload = _json_bytes(artifact)
    csv_payload = _csv_bytes(artifact)
    manifest_payload = _json_bytes(manifest)
    hashes = (
        f"{_sha256(json_payload)}  {json_name}\n"
        f"{_sha256(csv_payload)}  {csv_name}\n"
        f"{_sha256(manifest_payload)}  {manifest_name}\n"
    ).encode("ascii")
    return json_payload, csv_payload, manifest_payload, hashes


def write_cognitive_budget_ablation_files(
    *,
    json_path: Path,
    csv_path: Path,
    manifest_path: Path,
    sha256_path: Path,
    check: bool = False,
) -> dict[str, Any]:
    manifest = build_cognitive_budget_ablation_manifest()
    artifact = build_cognitive_budget_ablation_artifact()
    payloads = render_cognitive_budget_ablation_files(
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
                "Cognitive-budget ablation artifacts are stale: " + ", ".join(mismatches)
            )
    else:
        write_new_evidence_files(outputs, label="cognitive-budget ablation evidence")
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
    parser.add_argument("--manifest-output", type=Path, default=DEFAULT_MANIFEST_OUTPUT)
    parser.add_argument("--sha256-output", type=Path, default=DEFAULT_SHA256_OUTPUT)
    parser.add_argument(
        "--check",
        action="store_true",
        help="Recompute and require byte-identical frozen files.",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    result = write_cognitive_budget_ablation_files(
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
