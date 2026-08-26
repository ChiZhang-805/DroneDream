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
    HarnessRoutingArchivedPredictionArtifact,
    HarnessRoutingPredictionArtifact,
    compile_routing_eval_snapshot,
    grade_routing_prediction_artifact,
    load_archived_routing_prediction_artifact,
    load_routing_eval_cases,
    load_routing_prediction_artifact,
    routing_corpus_sha256,
    routing_prompt_suite_sha256,
    summarize_routing_baselines,
)
from scripts.evidence_output import write_new_evidence_files  # noqa: E402


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
        "--allow-archived-evidence-2-7-prompt-1-6",
        action="store_true",
        help=(
            "Grade the explicitly pinned historical Evidence 2.7 / Prompt 1.6 "
            "freeze instead of requiring the current production prompt."
        ),
    )
    parser.add_argument(
        "--allow-archived-evidence-2-8-prompt-1-7",
        action="store_true",
        help=(
            "Grade the explicitly pinned historical Evidence 2.8 / Prompt 1.7 "
            "freeze instead of requiring the current Evidence 2.9 snapshot."
        ),
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
    if (
        args.allow_archived_evidence_2_7_prompt_1_6
        and args.allow_archived_evidence_2_8_prompt_1_7
    ):
        raise ValueError("select at most one archived routing contract")
    cases = load_routing_eval_cases(args.corpus)
    result: dict[str, object] = {
        "schema_version": "1.1",
        "backend_root": str(BACKEND_ROOT),
        "corpus": str(args.corpus),
        "case_count": len(cases),
        "categories": sorted({case.category for case in cases}),
        "tool_count": len(HARNESS_TOOL_DEFINITIONS),
        "contract_role": "current_software",
        "evidence_schema_version": HARNESS_EVIDENCE_SCHEMA_VERSION,
        "tool_registry_version": HARNESS_TOOL_REGISTRY_VERSION,
        "prompt_template_version": HARNESS_PROMPT_TEMPLATE_VERSION,
        "corpus_sha256": routing_corpus_sha256(cases),
        "prompt_suite_sha256": routing_prompt_suite_sha256(cases),
    }
    result["baselines"] = summarize_routing_baselines(cases).model_dump(mode="json")

    if args.emit_prompts is not None:
        prompt_rows = []
        for case in cases:
            system, user = build_decision_messages(compile_routing_eval_snapshot(case))
            prompt_rows.append(
                json.dumps(
                    {
                        "case_id": case.case_id,
                        "system": system,
                        "user": user,
                    },
                    sort_keys=True,
                    ensure_ascii=False,
                )
            )
        prompt_bytes = (("\n".join(prompt_rows) + "\n").encode("utf-8"))
        write_new_evidence_files(
            [(args.emit_prompts, prompt_bytes)],
            label="Harness routing prompt suite",
        )
        result["prompt_output"] = str(args.emit_prompts)

    if args.predictions is not None:
        artifact: (
            HarnessRoutingPredictionArtifact
            | HarnessRoutingArchivedPredictionArtifact
        )
        if args.allow_archived_evidence_2_7_prompt_1_6:
            artifact = load_archived_routing_prediction_artifact(
                args.predictions,
                cases,
                evidence_schema_version="2.7",
                prompt_template_version="1.6",
                prompt_suite_sha256=(
                    "93ca5fdafe123741821f47296e3e8b23cb5f9d68ff9d78bbf2c10af83642bd77"
                ),
            )
        elif args.allow_archived_evidence_2_8_prompt_1_7:
            artifact = load_archived_routing_prediction_artifact(
                args.predictions,
                cases,
                evidence_schema_version="2.8",
                prompt_template_version="1.7",
                prompt_suite_sha256=(
                    "81b3cae64b16f6b8294ef05acd9792f5d86c36e6d9e2afecf2f60d4d4db41903"
                ),
            )
        else:
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
            "evidence_schema_version": artifact.evidence_schema_version,
            "tool_registry_version": artifact.tool_registry_version,
            "prompt_template_version": artifact.prompt_template_version,
            "prompt_suite_sha256": artifact.prompt_suite_sha256,
            "contract_current": (
                not args.allow_archived_evidence_2_7_prompt_1_6
                and not args.allow_archived_evidence_2_8_prompt_1_7
            ),
            "qualification_scope": (
                "archived_evidence_2_7_prompt_1_6"
                if args.allow_archived_evidence_2_7_prompt_1_6
                else (
                    "archived_evidence_2_8_prompt_1_7"
                    if args.allow_archived_evidence_2_8_prompt_1_7
                    else "current_contract"
                )
            ),
        }

    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
