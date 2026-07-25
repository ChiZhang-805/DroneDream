"""Validate or grade the replayable Harness routing development corpus."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.orchestration.decision_harness import build_decision_messages
from app.orchestration.harness_context import HARNESS_TOOL_DEFINITIONS
from app.orchestration.harness_evaluation import (
    compile_routing_eval_snapshot,
    grade_routing_prediction_artifact,
    load_routing_eval_cases,
    load_routing_prediction_artifact,
    routing_corpus_sha256,
    routing_prompt_suite_sha256,
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
        help=(
            "Optional strict prediction artifact bound to corpus, prompt, "
            "schema, provider, and model versions."
        ),
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
        "schema_version": "1.1",
        "corpus": str(args.corpus),
        "case_count": len(cases),
        "categories": sorted({case.category for case in cases}),
        "tool_count": len(HARNESS_TOOL_DEFINITIONS),
        "corpus_sha256": routing_corpus_sha256(cases),
        "prompt_suite_sha256": routing_prompt_suite_sha256(cases),
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
        artifact = load_routing_prediction_artifact(
            args.predictions,
            cases,
        )
        report = grade_routing_prediction_artifact(artifact, cases)
        result["grade"] = report.predictions.model_dump(mode="json")
        result["comparison"] = {
            "absolute_lift_over_uniform_random": (
                report.absolute_lift_over_uniform_random
            ),
            "absolute_lift_over_best_constant": (
                report.absolute_lift_over_best_constant
            ),
            "beats_best_constant": report.beats_best_constant,
            "qualification": report.qualification.model_dump(mode="json"),
        }
        result["prediction_provenance"] = {
            "provider": artifact.provider,
            "model_snapshot": artifact.model_snapshot,
            "generation_config": artifact.generation_config.model_dump(mode="json"),
        }

    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
