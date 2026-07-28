#!/usr/bin/env python3
"""Generate or verify the Evidence 2.9 equal-budget multi-tool receipt."""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import sys
from pathlib import Path
from typing import Any, cast

BACKEND_ROOT = Path(__file__).resolve().parents[1]
while str(BACKEND_ROOT) in sys.path:
    sys.path.remove(str(BACKEND_ROOT))
sys.path.insert(0, str(BACKEND_ROOT))

from app.orchestration.harness_multi_tool_budget_evaluation import (  # noqa: E402
    HARNESS_MULTI_TOOL_BUDGET_EVAL_CLAIM_BOUNDARY,
    HARNESS_MULTI_TOOL_BUDGET_EVAL_MANIFEST_SCHEMA_VERSION,
    HARNESS_MULTI_TOOL_BUDGET_EVAL_SCHEMA_VERSION,
    build_harness_multi_tool_budget_evaluation,
    build_harness_multi_tool_budget_manifest,
)

DEFAULT_ROOT = BACKEND_ROOT / "evaluation_artifacts"
DEFAULT_STEM = "harness-multi-tool-budget-evaluation-v1"


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _internal_sha(payload: dict[str, object], field: str) -> str:
    unsigned = {key: value for key, value in payload.items() if key != field}
    return hashlib.sha256(_canonical_json(unsigned).encode("utf-8")).hexdigest()


def _json_bytes(value: object) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _csv_bytes(artifact: dict[str, object]) -> bytes:
    output = io.StringIO(newline="")
    fields = (
        "block_id",
        "seed_block",
        "arm",
        "configured_max_iterations",
        "configured_max_total_trials",
        "realized_dispatched_trials",
        "realized_completed_trials",
        "realized_candidate_count",
        "terminal_status",
        "holdout_loss",
        "failure_count",
        "verified_generation_count",
        "multi_tool_generation_count",
        "scripted_decision_calls",
        "plan_decision_wall_ms",
        "revision_wall_ms",
        "tool_execution_wall_ms",
        "actual_tool_cpu_ms",
    )
    writer = csv.DictWriter(output, fieldnames=fields, lineterminator="\n")
    writer.writeheader()
    raw_blocks = artifact.get("block_rows")
    if not isinstance(raw_blocks, list):
        raise ValueError("multi-tool evaluation has no block rows")
    for raw_block in raw_blocks:
        if not isinstance(raw_block, dict):
            raise ValueError("multi-tool evaluation block row is invalid")
        block = cast(dict[str, Any], raw_block)
        raw_arms = block.get("arms")
        if not isinstance(raw_arms, list):
            raise ValueError("multi-tool evaluation block has no arm rows")
        for raw_arm in raw_arms:
            if not isinstance(raw_arm, dict):
                raise ValueError("multi-tool evaluation arm row is invalid")
            arm = cast(dict[str, Any], raw_arm)
            accounting = arm["plan_trace"]["accounting"]
            writer.writerow(
                {
                    "block_id": block["block_id"],
                    "seed_block": block["seed_block"],
                    "arm": arm["arm"],
                    "configured_max_iterations": arm["configured_max_iterations"],
                    "configured_max_total_trials": arm[
                        "configured_max_total_trials"
                    ],
                    "realized_dispatched_trials": arm["realized_dispatched_trials"],
                    "realized_completed_trials": arm["realized_completed_trials"],
                    "realized_candidate_count": arm["realized_candidate_count"],
                    "terminal_status": arm["terminal_status"],
                    "holdout_loss": arm["holdout_loss"],
                    "failure_count": arm["failure_count"],
                    "verified_generation_count": arm["plan_trace"][
                        "verified_generation_count"
                    ],
                    "multi_tool_generation_count": arm["plan_trace"][
                        "multi_tool_generation_count"
                    ],
                    "scripted_decision_calls": arm["scripted_decision_calls"],
                    "plan_decision_wall_ms": accounting["plan_decision_wall_ms"],
                    "revision_wall_ms": accounting["revision_wall_ms"],
                    "tool_execution_wall_ms": accounting["tool_execution_wall_ms"],
                    "actual_tool_cpu_ms": accounting["actual_tool_cpu_ms"],
                }
            )
    return output.getvalue().encode("utf-8")


def _payloads(
    artifact: dict[str, object],
    manifest: dict[str, object],
) -> dict[str, bytes]:
    json_bytes = _json_bytes(artifact)
    csv_bytes = _csv_bytes(artifact)
    manifest_bytes = _json_bytes(manifest)
    checksums = (
        f"{_sha256_bytes(json_bytes)}  {DEFAULT_STEM}.json\n"
        f"{_sha256_bytes(csv_bytes)}  {DEFAULT_STEM}.csv\n"
        f"{_sha256_bytes(manifest_bytes)}  {DEFAULT_STEM}.manifest.json\n"
    ).encode("ascii")
    return {
        f"{DEFAULT_STEM}.json": json_bytes,
        f"{DEFAULT_STEM}.csv": csv_bytes,
        f"{DEFAULT_STEM}.manifest.json": manifest_bytes,
        f"{DEFAULT_STEM}.sha256": checksums,
    }


def _verify_loaded(
    artifact: object,
    manifest: object,
    *,
    source_commit: str,
    generated_at: str,
) -> tuple[dict[str, object], dict[str, object]]:
    if not isinstance(artifact, dict) or not isinstance(manifest, dict):
        raise ValueError("multi-tool evaluation files must contain JSON objects")
    if artifact.get("schema_version") != HARNESS_MULTI_TOOL_BUDGET_EVAL_SCHEMA_VERSION:
        raise ValueError("multi-tool evaluation schema drifted")
    if (
        manifest.get("schema_version")
        != HARNESS_MULTI_TOOL_BUDGET_EVAL_MANIFEST_SCHEMA_VERSION
    ):
        raise ValueError("multi-tool evaluation manifest schema drifted")
    if artifact.get("source_commit") != source_commit or manifest.get(
        "source_commit"
    ) != source_commit:
        raise ValueError("multi-tool evaluation source_commit drifted")
    if artifact.get("generated_at") != generated_at or manifest.get(
        "generated_at"
    ) != generated_at:
        raise ValueError("multi-tool evaluation generated_at drifted")
    if artifact.get("claim_boundary") != HARNESS_MULTI_TOOL_BUDGET_EVAL_CLAIM_BOUNDARY:
        raise ValueError("multi-tool evaluation claim boundary drifted")
    if artifact.get("artifact_sha256") != _internal_sha(artifact, "artifact_sha256"):
        raise ValueError("multi-tool evaluation artifact hash does not recompute")
    if manifest.get("manifest_sha256") != _internal_sha(
        manifest,
        "manifest_sha256",
    ):
        raise ValueError("multi-tool evaluation manifest hash does not recompute")
    if manifest.get("artifact_sha256") != artifact.get("artifact_sha256"):
        raise ValueError("multi-tool evaluation manifest binding drifted")
    summary = artifact.get("summary")
    if (
        not isinstance(summary, dict)
        or summary.get("block_count") != 3
        or summary.get("configured_budget_parity_count") != 3
        or not isinstance(summary.get("scripted_multi_tool_generation_count"), int)
        or summary["scripted_multi_tool_generation_count"] < 3
        or summary.get("scripted_decision_call_count")
        != summary.get("scripted_accounted_provider_call_count")
    ):
        raise ValueError("multi-tool evaluation summary is incomplete")
    return artifact, manifest


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--generated-at", required=True)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    root = args.output_dir
    if args.check:
        artifact = json.loads(
            (root / f"{DEFAULT_STEM}.json").read_text(encoding="utf-8")
        )
        manifest = json.loads(
            (root / f"{DEFAULT_STEM}.manifest.json").read_text(encoding="utf-8")
        )
        artifact, manifest = _verify_loaded(
            artifact,
            manifest,
            source_commit=args.source_commit,
            generated_at=args.generated_at,
        )
        expected = _payloads(artifact, manifest)
        mismatches = [
            name
            for name, payload in expected.items()
            if not (root / name).is_file() or (root / name).read_bytes() != payload
        ]
        if mismatches:
            raise ValueError(
                "multi-tool evaluation files drifted: " + ", ".join(mismatches)
            )
    else:
        artifact = build_harness_multi_tool_budget_evaluation(
            source_commit=args.source_commit,
            generated_at=args.generated_at,
        )
        manifest = build_harness_multi_tool_budget_manifest(
            source_commit=args.source_commit,
            generated_at=args.generated_at,
            artifact=artifact,
        )
        root.mkdir(parents=True, exist_ok=True)
        for name, payload in _payloads(artifact, manifest).items():
            (root / name).write_bytes(payload)
    print(
        json.dumps(
            {
                "artifact_sha256": artifact["artifact_sha256"],
                "manifest_sha256": manifest["manifest_sha256"],
                "summary": artifact["summary"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
