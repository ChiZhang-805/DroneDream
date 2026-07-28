"""Validate or grade the replayable Harness routing development corpus."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
while str(BACKEND_ROOT) in sys.path:
    sys.path.remove(str(BACKEND_ROOT))
sys.path.insert(0, str(BACKEND_ROOT))

import app  # noqa: E402
from app.orchestration.decision_harness import build_decision_messages  # noqa: E402
from app.orchestration.harness_context import (  # noqa: E402
    HARNESS_EVIDENCE_SCHEMA_VERSION,
    HARNESS_PROMPT_TEMPLATE_VERSION,
    HARNESS_TOOL_DEFINITIONS,
    HARNESS_TOOL_REGISTRY_VERSION,
)
from app.orchestration.harness_evaluation import (  # noqa: E402
    compile_routing_eval_snapshot,
    grade_routing_prediction_artifact,
    load_routing_eval_cases,
    load_routing_prediction_artifact,
    routing_corpus_sha256,
    routing_prompt_suite_sha256,
    summarize_routing_baselines,
)


def _assert_local_backend_import() -> None:
    app_path = Path(app.__file__).resolve()
    try:
        app_path.relative_to(BACKEND_ROOT)
    except ValueError as exc:
        raise RuntimeError(
            f"evaluate_harness_router imported app from {app_path}, "
            f"expected it under {BACKEND_ROOT}"
        ) from exc


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
    _assert_local_backend_import()
    args = _parser().parse_args()
    cases = load_routing_eval_cases(args.corpus)
    result: dict[str, object] = {
        "schema_version": "1.1",
        "backend_root": str(BACKEND_ROOT),
        "corpus": str(args.corpus),
        "case_count": len(cases),
        "categories": sorted({case.category for case in cases}),
        "tool_count": len(HARNESS_TOOL_DEFINITIONS),
        "evidence_schema_version": HARNESS_EVIDENCE_SCHEMA_VERSION,
        "tool_registry_version": HARNESS_TOOL_REGISTRY_VERSION,
        "prompt_template_version": HARNESS_PROMPT_TEMPLATE_VERSION,
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
            "absolute_lift_over_uniform_random": (report.absolute_lift_over_uniform_random),
            "absolute_lift_over_best_constant": (report.absolute_lift_over_best_constant),
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
