"""Freeze or verify the outcome-blind pre-final PX4/Gazebo scenario registry."""

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

from app.optimization.prefinal_scenario_registry import (  # noqa: E402
    PREFINAL_SCENARIO_REGISTRY_MANIFEST_SCHEMA_VERSION,
    build_prefinal_scenario_registry,
    verify_prefinal_scenario_registry,
)
from scripts.evidence_output import write_new_evidence_files  # noqa: E402

_STEM = "prefinal-realistic-scenario-registry-v1"
DEFAULT_JSON_OUTPUT = BACKEND_ROOT / "evaluation_artifacts" / f"{_STEM}.json"
DEFAULT_CSV_OUTPUT = BACKEND_ROOT / "evaluation_artifacts" / f"{_STEM}.csv"
DEFAULT_MANIFEST_OUTPUT = BACKEND_ROOT / "evaluation_artifacts" / f"{_STEM}.manifest.json"
DEFAULT_SHA256_OUTPUT = BACKEND_ROOT / "evaluation_artifacts" / f"{_STEM}.sha256"


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _json_bytes(value: dict[str, Any]) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, allow_nan=False, indent=2, sort_keys=True)
        + "\n"
    ).encode("utf-8")


def _csv_bytes(registry: dict[str, Any]) -> bytes:
    fields = (
        "registry_ordinal",
        "problem_id",
        "difficulty",
        "task_family",
        "track_type",
        "scenario_type",
        "training_seeds",
        "holdout_seeds",
        "target_rmse",
        "target_max_error",
        "min_pass_rate",
        "physical_effect_contracts_sha256",
    )
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=list(fields), lineterminator="\n")
    writer.writeheader()
    for problem in registry["problems"]:
        template = problem["job_template"]
        cases = template["scenario_suite"]["cases"]
        training = [seed for case in cases if not case["holdout"] for seed in case["seeds"]]
        holdout = [seed for case in cases if case["holdout"] for seed in case["seeds"]]
        acceptance = problem["provisional_acceptance_criteria"]
        writer.writerow(
            {
                "registry_ordinal": problem["registry_ordinal"],
                "problem_id": problem["problem_id"],
                "difficulty": problem["difficulty"],
                "task_family": problem["task_family"],
                "track_type": template["track_type"],
                "scenario_type": cases[0]["scenario_type"],
                "training_seeds": ">".join(str(seed) for seed in training),
                "holdout_seeds": ">".join(str(seed) for seed in holdout),
                "target_rmse": acceptance["target_rmse"],
                "target_max_error": acceptance["target_max_error"],
                "min_pass_rate": acceptance["min_pass_rate"],
                "physical_effect_contracts_sha256": problem[
                    "physical_effect_contracts_sha256"
                ],
            }
        )
    return buffer.getvalue().encode("utf-8")


def render_prefinal_scenario_registry_files(
    registry: dict[str, Any],
    *,
    json_name: str,
    csv_name: str,
    manifest_name: str,
) -> tuple[bytes, bytes, bytes, bytes, dict[str, Any]]:
    if not verify_prefinal_scenario_registry(registry):
        raise ValueError("pre-final scenario registry failed deterministic verification")
    json_payload = _json_bytes(registry)
    csv_payload = _csv_bytes(registry)
    manifest = {
        "schema_version": PREFINAL_SCENARIO_REGISTRY_MANIFEST_SCHEMA_VERSION,
        "registry_version": registry["registry_version"],
        "registry_sha256": registry["registry_sha256"],
        "status": registry["status"],
        "report_eligible": registry["report_eligible"],
        "problem_count": registry["problem_count"],
        "difficulty_distribution": registry["difficulty_distribution"],
        "files": [
            {"path": json_name, "bytes": len(json_payload), "sha256": _sha256(json_payload)},
            {"path": csv_name, "bytes": len(csv_payload), "sha256": _sha256(csv_payload)},
        ],
    }
    unsigned = dict(manifest)
    manifest["manifest_sha256"] = hashlib.sha256(
        json.dumps(
            unsigned,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()
    manifest_payload = _json_bytes(manifest)
    hashes = (
        f"{_sha256(json_payload)}  {json_name}\n"
        f"{_sha256(csv_payload)}  {csv_name}\n"
        f"{_sha256(manifest_payload)}  {manifest_name}\n"
    ).encode("ascii")
    return json_payload, csv_payload, manifest_payload, hashes, manifest


def write_prefinal_scenario_registry_files(
    *,
    json_path: Path,
    csv_path: Path,
    manifest_path: Path,
    sha256_path: Path,
    check: bool = False,
) -> dict[str, Any]:
    registry = build_prefinal_scenario_registry()
    payloads = render_prefinal_scenario_registry_files(
        registry,
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
            raise ValueError("Pre-final scenario registry is stale: " + ", ".join(mismatches))
    else:
        write_new_evidence_files(outputs, label="pre-final scenario registry")
    return {
        "registry_sha256": registry["registry_sha256"],
        "manifest_sha256": payloads[4]["manifest_sha256"],
        "json_file_sha256": _sha256(payloads[0]),
        "csv_file_sha256": _sha256(payloads[1]),
        "manifest_file_sha256": _sha256(payloads[2]),
        "problem_count": registry["problem_count"],
        "difficulty_distribution": registry["difficulty_distribution"],
        "status": registry["status"],
    }


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json-output", type=Path, default=DEFAULT_JSON_OUTPUT)
    parser.add_argument("--csv-output", type=Path, default=DEFAULT_CSV_OUTPUT)
    parser.add_argument("--manifest-output", type=Path, default=DEFAULT_MANIFEST_OUTPUT)
    parser.add_argument("--sha256-output", type=Path, default=DEFAULT_SHA256_OUTPUT)
    parser.add_argument("--check", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    result = write_prefinal_scenario_registry_files(
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
