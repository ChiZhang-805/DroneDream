"""Validate or grade the replayable Harness routing development corpus."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import cast

from app.orchestration.decision_harness import build_decision_messages
from app.orchestration.harness_context import HARNESS_TOOL_DEFINITIONS, HarnessToolId
from app.orchestration.harness_evaluation import (
    build_routing_eval_report,
    compile_routing_eval_snapshot,
    load_routing_eval_cases,
    summarize_routing_baselines,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--corpus",
        type=Path,
        default=Path(__file__).resolve().parents[1]
        / "tests"
        / "fixtures"
        / "harness_routing_eval_v1.jsonl",
    )
    parser.add_argument(
        "--predictions",
        type=Path,
        help="Optional JSON object mapping every case_id to one registered tool_id.",
    )
    parser.add_argument(
        "--emit-prompts",
        type=Path,
        help="Optional output JSONL containing the exact secretless production messages.",
    )
    return parser


def main() -> int:
    args = _parser().parse_args()
    cases = load_routing_eval_cases(args.corpus)
    result: dict[str, object] = {
        "schema_version": "1.0",
        "corpus": str(args.corpus),
        "case_count": len(cases),
        "categories": sorted({case.category for case in cases}),
        "tool_count": len(HARNESS_TOOL_DEFINITIONS),
    }
    result["baselines"] = summarize_routing_baselines(cases).model_dump(mode="json")

    if args.emit_prompts is not None:
        with args.emit_prompts.open("w", encoding="utf-8", newline="\n") as handle:
            for case in cases:
                system, user = build_decision_messages(compile_routing_eval_snapshot(case))
                handle.write(
                    json.dumps(
                        {
                            "case_id": case.case_id,
                            "system": system,
                            "user": user,
                        },
                        sort_keys=True,
                        ensure_ascii=False,
                    )
                    + "\n"
                )
        result["prompt_output"] = str(args.emit_prompts)

    if args.predictions is not None:
        raw_predictions = json.loads(args.predictions.read_text(encoding="utf-8"))
        if not isinstance(raw_predictions, dict):
            raise ValueError("predictions must be a JSON object")
        predictions: dict[str, HarnessToolId] = {}
        for case_id, tool_id in raw_predictions.items():
            if not isinstance(case_id, str) or tool_id not in HARNESS_TOOL_DEFINITIONS:
                raise ValueError("predictions contain an invalid case or tool ID")
            predictions[case_id] = cast(HarnessToolId, tool_id)
        report = build_routing_eval_report(
            cases,
            predictions,
        )
        result["grade"] = report.predictions.model_dump(mode="json")
        result["comparison"] = {
            "absolute_lift_over_uniform_random": (
                report.absolute_lift_over_uniform_random
            ),
            "absolute_lift_over_best_constant": (
                report.absolute_lift_over_best_constant
            ),
            "beats_best_constant": report.beats_best_constant,
        }

    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
