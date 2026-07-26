from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.optimization.simulation_coverage_campaign import (
    SimulationCoverageArtifact,
    run_simulation_coverage_campaign,
    write_frozen_simulation_coverage_artifact,
)

_ARTIFACT_PATH = (
    Path(__file__).resolve().parents[1]
    / "evaluation_artifacts"
    / "simulation-coverage-mock-v2.json"
)


@pytest.fixture(scope="module")
def campaign() -> SimulationCoverageArtifact:
    return run_simulation_coverage_campaign()


def test_committed_simulation_coverage_freeze_matches_current_campaign(
    campaign: SimulationCoverageArtifact,
) -> None:
    committed = SimulationCoverageArtifact.model_validate_json(
        _ARTIFACT_PATH.read_text(encoding="utf-8")
    )

    assert committed == campaign
    assert campaign.qualified is True
    assert campaign.failed_requirements == ()
    assert campaign.physical_fidelity is False
    assert len(campaign.scenario_types) == 10
    assert campaign.evaluated_candidate_count == campaign.candidate_budget == 61
    assert campaign.exhaustive_oracle_candidate_count == 2_430
    assert campaign.training_oracle_regret == pytest.approx(0.0, abs=1e-12)
    assert campaign.holdout_oracle_regret == pytest.approx(0.0, abs=1e-12)
    assert campaign.baseline_to_selected_improvement_rate >= 0.20
    assert campaign.all_scenarios_improved is True
    assert campaign.selected.holdout_all_pass is True


def test_simulation_coverage_freeze_refuses_overwrite(
    campaign: SimulationCoverageArtifact,
    tmp_path: Path,
) -> None:
    destination = tmp_path / "freeze.json"
    write_frozen_simulation_coverage_artifact(destination, campaign)
    decoded = json.loads(destination.read_text(encoding="utf-8"))
    assert decoded == campaign.model_dump(mode="json")

    with pytest.raises(FileExistsError):
        write_frozen_simulation_coverage_artifact(destination, campaign)
