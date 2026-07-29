#!/usr/bin/env python3
"""Generate or verify the Evidence 2.9 equal-budget multi-tool receipt."""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
import sys
from pathlib import Path
from typing import Any, cast

BACKEND_ROOT = Path(__file__).resolve().parents[1]
while str(BACKEND_ROOT) in sys.path:
    sys.path.remove(str(BACKEND_ROOT))
sys.path.insert(0, str(BACKEND_ROOT))

from app.orchestration.harness_context import HarnessGenerationPlanMemory  # noqa: E402
from app.orchestration.harness_multi_tool_budget_evaluation import (  # noqa: E402
    HARNESS_MULTI_TOOL_BUDGET_EVAL_CLAIM_BOUNDARY,
    HARNESS_MULTI_TOOL_BUDGET_EVAL_MANIFEST_SCHEMA_VERSION,
    HARNESS_MULTI_TOOL_BUDGET_EVAL_SCHEMA_VERSION,
    build_harness_multi_tool_budget_evaluation,
    build_harness_multi_tool_budget_manifest,
)

DEFAULT_ROOT = BACKEND_ROOT / "evaluation_artifacts"
DEFAULT_STEM = "harness-multi-tool-budget-evaluation-v1"
_TIMING_FIELDS = frozenset(
    {
        "actual_tool_cpu_ms",
        "cpu_ms",
        "elapsed_ms",
        "plan_decision_wall_ms",
        "revision_wall_ms",
        "scripted_actual_tool_cpu_ms",
        "scripted_plan_decision_wall_ms",
        "scripted_revision_wall_ms",
        "scripted_tool_execution_wall_ms",
        "tool_execution_wall_ms",
    }
)
_HASH_FIELDS = frozenset({"artifact_sha256", "manifest_sha256"})


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
                    "configured_max_total_trials": arm["configured_max_total_trials"],
                    "realized_dispatched_trials": arm["realized_dispatched_trials"],
                    "realized_completed_trials": arm["realized_completed_trials"],
                    "realized_candidate_count": arm["realized_candidate_count"],
                    "terminal_status": arm["terminal_status"],
                    "holdout_loss": arm["holdout_loss"],
                    "failure_count": arm["failure_count"],
                    "verified_generation_count": arm["plan_trace"]["verified_generation_count"],
                    "multi_tool_generation_count": arm["plan_trace"]["multi_tool_generation_count"],
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
    if manifest.get("schema_version") != HARNESS_MULTI_TOOL_BUDGET_EVAL_MANIFEST_SCHEMA_VERSION:
        raise ValueError("multi-tool evaluation manifest schema drifted")
    if (
        artifact.get("source_commit") != source_commit
        or manifest.get("source_commit") != source_commit
    ):
        raise ValueError("multi-tool evaluation source_commit drifted")
    if artifact.get("generated_at") != generated_at or manifest.get("generated_at") != generated_at:
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


def _semantic_projection(value: object, *, field: str | None = None) -> object:
    """Remove hashes and normalize only irreproducible clock observations."""

    if field in _TIMING_FIELDS:
        return 0.0
    if isinstance(value, dict):
        return {
            key: _semantic_projection(item, field=key)
            for key, item in value.items()
            if key not in _HASH_FIELDS
        }
    if isinstance(value, list):
        return [_semantic_projection(item) for item in value]
    return value


def _finite_timing(value: object, *, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field} must be a finite timing number")
    resolved = float(value)
    if not math.isfinite(resolved) or not 0.0 <= resolved <= 600_000.0:
        raise ValueError(f"{field} must be between 0 and 600000 milliseconds")
    return resolved


def _validate_timing_accounting(artifact: dict[str, object]) -> None:
    raw_blocks = artifact.get("block_rows")
    if not isinstance(raw_blocks, list):
        raise ValueError("multi-tool evaluation has no block rows")
    scripted_accounting: list[dict[str, object]] = []
    for block_index, raw_block in enumerate(raw_blocks):
        if not isinstance(raw_block, dict) or not isinstance(raw_block.get("arms"), list):
            raise ValueError(f"multi-tool evaluation block {block_index} is invalid")
        for arm_index, raw_arm in enumerate(raw_block["arms"]):
            if not isinstance(raw_arm, dict):
                raise ValueError(f"multi-tool evaluation arm {block_index}/{arm_index} is invalid")
            trace = raw_arm.get("plan_trace")
            if not isinstance(trace, dict):
                raise ValueError(
                    f"multi-tool evaluation arm {block_index}/{arm_index} has no trace"
                )
            raw_history = trace.get("provider_visible_history")
            accounting = trace.get("accounting")
            if not isinstance(raw_history, list) or not isinstance(accounting, dict):
                raise ValueError(
                    f"multi-tool evaluation arm {block_index}/{arm_index} has invalid accounting"
                )
            history = [HarnessGenerationPlanMemory.model_validate(row) for row in raw_history]
            integer_fields = (
                "provider_call_count",
                "planned_candidates",
                "dispatched_candidates",
                "dispatched_trials",
            )
            for name in integer_fields:
                observed = accounting.get(name)
                expected = sum(int(getattr(row, name)) for row in history)
                if (
                    isinstance(observed, bool)
                    or not isinstance(observed, int)
                    or observed != expected
                ):
                    raise ValueError(
                        f"multi-tool evaluation {name} accounting does not match generation rows"
                    )
            for name in (
                "plan_decision_wall_ms",
                "revision_wall_ms",
                "tool_execution_wall_ms",
                "actual_tool_cpu_ms",
            ):
                observed = _finite_timing(
                    accounting.get(name),
                    field=f"block_rows[{block_index}].arms[{arm_index}].accounting.{name}",
                )
                expected = round(sum(float(getattr(row, name)) for row in history), 3)
                if not math.isclose(observed, expected, abs_tol=0.001):
                    raise ValueError(
                        f"multi-tool evaluation {name} accounting does not match generation rows"
                    )
            if raw_arm.get("arm") == "scripted_multi_tool":
                scripted_accounting.append(accounting)

    summary = artifact.get("summary")
    if not isinstance(summary, dict):
        raise ValueError("multi-tool evaluation summary is invalid")
    summary_fields = {
        "scripted_plan_decision_wall_ms": "plan_decision_wall_ms",
        "scripted_revision_wall_ms": "revision_wall_ms",
        "scripted_tool_execution_wall_ms": "tool_execution_wall_ms",
        "scripted_actual_tool_cpu_ms": "actual_tool_cpu_ms",
    }
    for summary_name, accounting_name in summary_fields.items():
        observed = _finite_timing(summary.get(summary_name), field=f"summary.{summary_name}")
        expected = round(
            sum(float(accounting[accounting_name]) for accounting in scripted_accounting),
            3,
        )
        if not math.isclose(observed, expected, abs_tol=0.001):
            raise ValueError(
                f"multi-tool evaluation {summary_name} does not match block accounting"
            )


def _build_verified(
    *,
    source_commit: str,
    generated_at: str,
) -> tuple[dict[str, object], dict[str, object]]:
    artifact = build_harness_multi_tool_budget_evaluation(
        source_commit=source_commit,
        generated_at=generated_at,
    )
    manifest = build_harness_multi_tool_budget_manifest(
        source_commit=source_commit,
        generated_at=generated_at,
        artifact=artifact,
    )
    artifact, manifest = _verify_loaded(
        artifact,
        manifest,
        source_commit=source_commit,
        generated_at=generated_at,
    )
    _validate_timing_accounting(artifact)
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
        artifact = json.loads((root / f"{DEFAULT_STEM}.json").read_text(encoding="utf-8"))
        manifest = json.loads((root / f"{DEFAULT_STEM}.manifest.json").read_text(encoding="utf-8"))
        artifact, manifest = _verify_loaded(
            artifact,
            manifest,
            source_commit=args.source_commit,
            generated_at=args.generated_at,
        )
        _validate_timing_accounting(artifact)
        rebuilt_artifact, rebuilt_manifest = _build_verified(
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
            raise ValueError("multi-tool evaluation files drifted: " + ", ".join(mismatches))
        if _semantic_projection(artifact) != _semantic_projection(
            rebuilt_artifact
        ) or _semantic_projection(manifest) != _semantic_projection(rebuilt_manifest):
            raise ValueError(
                "multi-tool evaluation deterministic semantics drifted on re-execution"
            )
    else:
        artifact, manifest = _build_verified(
            source_commit=args.source_commit,
            generated_at=args.generated_at,
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
