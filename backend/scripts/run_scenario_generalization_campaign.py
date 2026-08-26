"""Run and freeze the deterministic mixed-shift generalization campaign."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
while str(BACKEND) in sys.path:
    sys.path.remove(str(BACKEND))
sys.path.insert(0, str(BACKEND))

import app  # noqa: E402
from app.optimization.scenario_generalization_campaign import (  # noqa: E402
    run_scenario_generalization_campaign,
    write_frozen_scenario_generalization_artifact,
)


def _assert_local_backend_import() -> None:
    app_path = Path(app.__file__).resolve()
    if not app_path.is_relative_to(BACKEND):
        raise RuntimeError(f"imported app from {app_path}, expected it under {BACKEND}")


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
    _assert_local_backend_import()
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
