from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize(
    "script",
    (
        "backend/scripts/run_locked_harness_routing_policy_holdout.py",
        "backend/scripts/run_scenario_generalization_campaign.py",
        "backend/scripts/run_simulation_coverage_campaign.py",
    ),
)
def test_campaign_help_imports_current_backend_from_repository_root(script: str) -> None:
    environment = dict(os.environ)
    environment.pop("PYTHONPATH", None)
    environment["OPENAI_API_KEY"] = ""
    environment["HARNESS_ROUTING_API_KEY"] = ""

    completed = subprocess.run(
        [sys.executable, script, "--help"],
        cwd=REPOSITORY_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert "usage:" in completed.stdout
