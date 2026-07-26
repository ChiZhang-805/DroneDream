"""Run and freeze the deterministic cross-scenario simulation campaign."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.optimization.simulation_coverage_campaign import (
    run_simulation_coverage_campaign,
    write_frozen_simulation_coverage_artifact,
)


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
                "exhaustive_oracle_candidate_count": (
                    artifact.exhaustive_oracle_candidate_count
                ),
                "holdout_improvement_rate": (
                    artifact.baseline_to_selected_improvement_rate
                ),
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
