"""Run the frozen Harness routing corpus against an online provider."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Literal

BACKEND_ROOT = Path(__file__).resolve().parents[1]
_backend_root_text = str(BACKEND_ROOT)
if _backend_root_text in sys.path:
    sys.path.remove(_backend_root_text)
sys.path.insert(0, _backend_root_text)

import app  # noqa: E402
from app.orchestration.harness_context import (  # noqa: E402
    HARNESS_EVIDENCE_SCHEMA_VERSION,
    HARNESS_PROMPT_TEMPLATE_VERSION,
    HARNESS_TOOL_REGISTRY_VERSION,
)
from app.orchestration.harness_evaluation import (  # noqa: E402
    HarnessRoutingGenerationConfig,
    grade_routing_prediction_artifact,
    load_routing_eval_cases,
    routing_corpus_sha256,
    routing_prompt_suite_sha256,
)
from app.orchestration.harness_routing_campaign import (  # noqa: E402
    run_harness_routing_campaign,
    write_frozen_routing_artifact,
)
from app.orchestration.llm_parameter_proposer import OpenAIJsonClient  # noqa: E402


def _assert_local_backend_import() -> None:
    imported_backend_root = Path(app.__file__).resolve().parent.parent
    if imported_backend_root != BACKEND_ROOT:
        raise SystemExit(
            "Harness routing campaign imported app from an unexpected backend: "
            f"{imported_backend_root}"
        )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run every secretless Harness routing case and atomically publish "
            "one provenance-bound prediction artifact."
        )
    )
    parser.add_argument(
        "--corpus",
        type=Path,
        default=Path(__file__).resolve().parents[1]
        / "tests"
        / "fixtures"
        / "harness_routing_eval_v1.jsonl",
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--model-snapshot", required=True)
    parser.add_argument("--provider", default="openai")
    parser.add_argument("--timeout-seconds", type=float, default=60.0)
    parser.add_argument("--max-retries", type=int, default=1)
    parser.add_argument("--temperature", type=float)
    parser.add_argument("--top-p", type=float)
    parser.add_argument("--seed", type=int)
    parser.add_argument(
        "--preflight-only",
        action="store_true",
        help="Print the bound source, corpus, prompt, and output facts without a provider call.",
    )
    return parser


def main() -> int:
    args = _parser().parse_args()
    _assert_local_backend_import()
    base_url = os.environ.get("HARNESS_ROUTING_BASE_URL", "").strip() or None
    if args.timeout_seconds <= 0:
        raise SystemExit("--timeout-seconds must be positive")
    if args.max_retries < 0:
        raise SystemExit("--max-retries cannot be negative")

    corpus_path = args.corpus.resolve()
    output_path = args.output.resolve()
    cases = load_routing_eval_cases(corpus_path)
    response_format: Literal["json_schema", "json_object"] = (
        "json_object" if base_url else "json_schema"
    )
    generation_config = HarnessRoutingGenerationConfig(
        temperature=args.temperature,
        top_p=args.top_p,
        seed=args.seed,
        response_format=response_format,
    )
    preflight = {
        "backend_root": str(BACKEND_ROOT),
        "case_count": len(cases),
        "corpus": str(corpus_path),
        "corpus_sha256": routing_corpus_sha256(cases),
        "evidence_schema_version": HARNESS_EVIDENCE_SCHEMA_VERSION,
        "generation_config": generation_config.model_dump(mode="json"),
        "model_snapshot": args.model_snapshot.strip(),
        "output": str(output_path),
        "output_exists": output_path.exists(),
        "prompt_suite_sha256": routing_prompt_suite_sha256(cases),
        "prompt_template_version": HARNESS_PROMPT_TEMPLATE_VERSION,
        "provider": args.provider.strip(),
        "tool_registry_version": HARNESS_TOOL_REGISTRY_VERSION,
    }
    if args.preflight_only:
        print(json.dumps(preflight, indent=2, sort_keys=True))
        return 0
    if output_path.exists():
        raise SystemExit(f"refusing to replace existing artifact: {output_path}")
    if not output_path.parent.is_dir():
        raise SystemExit(f"artifact parent directory does not exist: {output_path.parent}")

    api_key = os.environ.get("HARNESS_ROUTING_API_KEY", "").strip()
    if not api_key:
        raise SystemExit("HARNESS_ROUTING_API_KEY is required")

    def client_factory(schema: dict[str, object]) -> OpenAIJsonClient:
        return OpenAIJsonClient(
            api_key,
            proposal_schema=schema,
            base_url=base_url,
            timeout_seconds=args.timeout_seconds,
            max_retries=args.max_retries,
            temperature=generation_config.temperature,
            top_p=generation_config.top_p,
            seed=generation_config.seed,
        )

    artifact = run_harness_routing_campaign(
        cases,
        provider=args.provider,
        model_snapshot=args.model_snapshot,
        generation_config=generation_config,
        client_factory=client_factory,
    )
    report = grade_routing_prediction_artifact(artifact, cases)
    write_frozen_routing_artifact(output_path, artifact)
    print(
        json.dumps(
            {
                "corpus_sha256": artifact.corpus_sha256,
                "evidence_schema_version": artifact.evidence_schema_version,
                "output": str(output_path),
                "case_count": len(cases),
                "provider": artifact.provider,
                "model_snapshot": artifact.model_snapshot,
                "pass_rate": report.predictions.pass_rate,
                "prompt_suite_sha256": artifact.prompt_suite_sha256,
                "prompt_template_version": artifact.prompt_template_version,
                "qualified": report.qualification.qualified,
                "failed_requirements": list(report.qualification.failed_requirements),
                "tool_registry_version": artifact.tool_registry_version,
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0 if report.qualification.qualified else 2


if __name__ == "__main__":
    raise SystemExit(main())
