"""Evaluate the locked deterministic Harness routing-policy holdout."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
while str(BACKEND) in sys.path:
    sys.path.remove(str(BACKEND))
sys.path.insert(0, str(BACKEND))

import app  # noqa: E402
from app.orchestration.harness_routing_holdout import (  # noqa: E402
    evaluate_locked_routing_policy_holdout,
    load_locked_routing_policy_holdout,
    load_locked_routing_policy_result,
    write_locked_routing_policy_result,
)

FIXTURES = BACKEND / "tests" / "fixtures"


def _assert_local_backend_import() -> None:
    app_path = Path(app.__file__).resolve()
    if not app_path.is_relative_to(BACKEND):
        raise RuntimeError(f"imported app from {app_path}, expected it under {BACKEND}")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run the locked deterministic tool-eligibility holdout. This does "
            "not call a model or simulator and cannot emit training feedback."
        )
    )
    parser.add_argument(
        "--corpus",
        type=Path,
        default=FIXTURES / "harness_routing_policy_holdout_v1.jsonl",
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=FIXTURES / "harness_routing_policy_holdout_v3.manifest.json",
    )
    parser.add_argument(
        "--development-corpus",
        type=Path,
        default=FIXTURES / "harness_routing_eval_v1.jsonl",
    )
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--output", type=Path)
    action.add_argument("--verify-existing", type=Path)
    return parser


def main() -> int:
    _assert_local_backend_import()
    args = _parser().parse_args()
    bundle = load_locked_routing_policy_holdout(
        args.corpus,
        args.manifest,
        args.development_corpus,
    )
    if args.verify_existing is not None:
        result = load_locked_routing_policy_result(args.verify_existing, bundle)
        output = args.verify_existing.resolve()
        action = "verified"
    else:
        result = evaluate_locked_routing_policy_holdout(bundle)
        assert args.output is not None
        write_locked_routing_policy_result(args.output, result)
        output = args.output.resolve()
        action = "created"
    print(
        json.dumps(
            {
                "action": action,
                "output": str(output),
                "evidence_class": result.evidence_class,
                "case_count": result.case_count,
                "passed_count": result.passed_count,
                "pass_rate": result.pass_rate,
                "qualified": result.qualified,
                "online_calls": 0,
                "simulator_runs": 0,
                "feedback_writebacks": 0,
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0 if result.qualified else 2


if __name__ == "__main__":
    raise SystemExit(main())
