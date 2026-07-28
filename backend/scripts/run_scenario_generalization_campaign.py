"""Run and freeze the deterministic mixed-shift generalization campaign."""

from __future__ import annotations

import argparse
from pathlib import Path

from app.optimization.scenario_generalization_campaign import (
    run_scenario_generalization_campaign,
    write_frozen_scenario_generalization_artifact,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        type=Path,
        required=True,
        help="New JSON path; existing files are never overwritten.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    artifact = run_scenario_generalization_campaign()
    write_frozen_scenario_generalization_artifact(args.output, artifact)
    print(
        "scenario generalization campaign "
        f"qualified={artifact.qualified} "
        f"training_loss={artifact.selected.training_loss:.8f} "
        f"validation_loss={artifact.selected.validation_loss:.8f} "
        f"evidence_id={artifact.generalization_evidence.evidence_id}"
    )
    return 0 if artifact.qualified else 1


if __name__ == "__main__":
    raise SystemExit(main())
