"""Run, freeze, or independently check AURORA component outcome ablations."""

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

from app.orchestration.harness_component_ablation import (  # noqa: E402
    build_harness_component_ablation_artifact,
    build_harness_component_ablation_manifest,
    verify_harness_component_ablation_artifact,
    verify_harness_component_ablation_manifest,
)

_STEM = "harness-component-outcome-ablation-v2"
DEFAULT_JSON_OUTPUT = BACKEND_ROOT / "evaluation_artifacts" / f"{_STEM}.json"
DEFAULT_CSV_OUTPUT = BACKEND_ROOT / "evaluation_artifacts" / f"{_STEM}.csv"
DEFAULT_MANIFEST_OUTPUT = BACKEND_ROOT / "evaluation_artifacts" / f"{_STEM}.manifest.json"
DEFAULT_SHA256_OUTPUT = BACKEND_ROOT / "evaluation_artifacts" / f"{_STEM}.sha256"

CSV_FIELDS = (
    "block_id",
    "seed_block",
    "arm",
    "tool_sequence",
    "provider_calls",
    "network_calls",
    "intervention_component",
    "intervention_activated",
    "holdout_loss",
    "optimizer_candidate_count",
    "feasible_optimizer_candidate_count",
    "optimizer_feasible_rate",
    "target_reached",
    "target_generation",
    "trials_to_target",
    "right_censor_trials",
    "total_trials",
    "completed_trials",
    "terminal_failure_trials",
    "recovered_trials",
    "failure_rate",
    "recovery_rate",
    "evidence_completeness_rate",
    "result_metrics_sha256",
    "outcome_sha256",
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


def _csv_rows(artifact: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for block in artifact["block_rows"]:
        for arm in block["arms"]:
            metrics = arm["result_metrics"]
            activation = arm["component_activation"]
            rows.append(
                {
                    "block_id": block["block_id"],
                    "seed_block": block["seed_block"],
                    "arm": arm["arm"],
                    "tool_sequence": ">".join(arm["tool_sequence"]),
                    "provider_calls": arm["provider_calls"],
                    "network_calls": arm["network_calls"],
                    "intervention_component": activation["component"],
                    "intervention_activated": activation["provider_visible_intervention_activated"],
                    "holdout_loss": metrics["holdout_loss"],
                    "optimizer_candidate_count": metrics["optimizer_candidate_count"],
                    "feasible_optimizer_candidate_count": metrics[
                        "feasible_optimizer_candidate_count"
                    ],
                    "optimizer_feasible_rate": metrics["optimizer_feasible_rate"],
                    "target_reached": metrics["target_reached"],
                    "target_generation": metrics["target_generation"],
                    "trials_to_target": metrics["trials_to_target"],
                    "right_censor_trials": metrics["right_censor_trials"],
                    "total_trials": metrics["total_trials"],
                    "completed_trials": metrics["completed_trials"],
                    "terminal_failure_trials": metrics["terminal_failure_trials"],
                    "recovered_trials": metrics["recovered_trials"],
                    "failure_rate": metrics["failure_rate"],
                    "recovery_rate": metrics["recovery_rate"],
                    "evidence_completeness_rate": metrics["evidence_completeness_rate"],
                    "result_metrics_sha256": arm["result_metrics_sha256"],
                    "outcome_sha256": arm["outcome_sha256"],
                }
            )
    return rows


def _csv_bytes(artifact: dict[str, Any]) -> bytes:
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(
        buffer,
        fieldnames=list(CSV_FIELDS),
        lineterminator="\n",
    )
    writer.writeheader()
    writer.writerows(_csv_rows(artifact))
    return buffer.getvalue().encode("utf-8")


def render_harness_component_ablation_files(
    artifact: dict[str, Any],
    manifest: dict[str, Any],
    *,
    json_name: str,
    csv_name: str,
    manifest_name: str,
) -> tuple[bytes, bytes, bytes, bytes]:
    """Render canonical result, flat CSV, preregistration, and file hashes."""

    verify_harness_component_ablation_manifest(manifest)
    verify_harness_component_ablation_artifact(
        artifact,
        manifest=manifest,
    )
    json_payload = _json_bytes(artifact)
    csv_payload = _csv_bytes(artifact)
    manifest_payload = _json_bytes(manifest)
    hashes = (
        f"{_sha256(json_payload)}  {json_name}\n"
        f"{_sha256(csv_payload)}  {csv_name}\n"
        f"{_sha256(manifest_payload)}  {manifest_name}\n"
    ).encode("ascii")
    return json_payload, csv_payload, manifest_payload, hashes


def write_harness_component_ablation_files(
    *,
    json_path: Path,
    csv_path: Path,
    manifest_path: Path,
    sha256_path: Path,
    check: bool = False,
    artifact: dict[str, Any] | None = None,
    manifest: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Write files or rerun and require exact byte-for-byte equality."""

    current_manifest = build_harness_component_ablation_manifest() if manifest is None else manifest
    current_artifact = build_harness_component_ablation_artifact() if artifact is None else artifact
    payloads = render_harness_component_ablation_files(
        current_artifact,
        current_manifest,
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
                "Harness component-ablation artifacts are stale: " + ", ".join(mismatches)
            )
    else:
        for path, payload in outputs:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(payload)
    return {
        "artifact_sha256": current_artifact["artifact_sha256"],
        "manifest_sha256": current_manifest["manifest_sha256"],
        "json_file_sha256": _sha256(payloads[0]),
        "csv_file_sha256": _sha256(payloads[1]),
        "manifest_file_sha256": _sha256(payloads[2]),
        "summary": current_artifact["summary"],
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
        help=(
            "Rerun all four arms for every seed block, independently recompute "
            "metrics/comparisons/hashes, and require byte-identical frozen files."
        ),
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    result = write_harness_component_ablation_files(
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
