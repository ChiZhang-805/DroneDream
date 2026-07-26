"""Run the frozen Harness routing corpus against an online provider."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Literal

from app.orchestration.harness_evaluation import (
    HarnessRoutingGenerationConfig,
    grade_routing_prediction_artifact,
    load_routing_eval_cases,
)
from app.orchestration.harness_routing_campaign import (
    run_harness_routing_campaign,
    write_frozen_routing_artifact,
)
from app.orchestration.llm_parameter_proposer import OpenAIJsonClient


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
    return parser


def main() -> int:
    args = _parser().parse_args()
    api_key = os.environ.get("HARNESS_ROUTING_API_KEY", "").strip()
    if not api_key:
        raise SystemExit("HARNESS_ROUTING_API_KEY is required")
    base_url = os.environ.get("HARNESS_ROUTING_BASE_URL", "").strip() or None
    if args.timeout_seconds <= 0:
        raise SystemExit("--timeout-seconds must be positive")
    if args.max_retries < 0:
        raise SystemExit("--max-retries cannot be negative")

    cases = load_routing_eval_cases(args.corpus)
    response_format: Literal["json_schema", "json_object"] = (
        "json_object" if base_url else "json_schema"
    )
    generation_config = HarnessRoutingGenerationConfig(
        response_format=response_format,
    )

    def client_factory(schema: dict[str, object]) -> OpenAIJsonClient:
        return OpenAIJsonClient(
            api_key,
            proposal_schema=schema,
            base_url=base_url,
            timeout_seconds=args.timeout_seconds,
            max_retries=args.max_retries,
        )

    artifact = run_harness_routing_campaign(
        cases,
        provider=args.provider,
        model_snapshot=args.model_snapshot,
        generation_config=generation_config,
        client_factory=client_factory,
    )
    report = grade_routing_prediction_artifact(artifact, cases)
    write_frozen_routing_artifact(args.output, artifact)
    print(
        json.dumps(
            {
                "output": str(args.output.resolve()),
                "case_count": len(cases),
                "provider": artifact.provider,
                "model_snapshot": artifact.model_snapshot,
                "pass_rate": report.predictions.pass_rate,
                "qualified": report.qualification.qualified,
                "failed_requirements": list(report.qualification.failed_requirements),
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0 if report.qualification.qualified else 2


if __name__ == "__main__":
    raise SystemExit(main())
