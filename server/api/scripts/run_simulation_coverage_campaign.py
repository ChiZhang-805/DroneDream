"""Run and freeze the deterministic cross-scenario simulation campaign."""

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
from app.optimization.simulation_coverage_campaign import (  # noqa: E402
    run_simulation_coverage_campaign,
    write_frozen_simulation_coverage_artifact,
)


def _assert_local_backend_import() -> None:
    app_path = Path(app.__file__).resolve()
    if not app_path.is_relative_to(BACKEND):
        raise RuntimeError(f"imported app from {app_path}, expected it under {BACKEND}")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run the finite synthetic optimizer campaign across all supported "
            "mock scenarios and disjoint holdout seeds."
        )
    )
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main() -> int:
    _assert_local_backend_import()
    args = _parser().parse_args()
    artifact = run_simulation_coverage_campaign()
    write_frozen_simulation_coverage_artifact(args.output, artifact)
    print(
        json.dumps(
            {
                "output": str(args.output.resolve()),
                "qualified": artifact.qualified,
                "failed_requirements": list(artifact.failed_requirements),
                "scenario_count": len(artifact.scenario_types),
                "evaluated_candidate_count": artifact.evaluated_candidate_count,
                "exhaustive_oracle_candidate_count": (artifact.exhaustive_oracle_candidate_count),
                "holdout_improvement_rate": (artifact.baseline_to_selected_improvement_rate),
                "training_oracle_regret": artifact.training_oracle_regret,
                "physical_fidelity": artifact.physical_fidelity,
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0 if artifact.qualified else 2


if __name__ == "__main__":
    raise SystemExit(main())
