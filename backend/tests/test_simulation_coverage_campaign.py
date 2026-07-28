from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.optimization.generalization_evidence import (
    verify_candidate_generalization_evidence,
)
from app.optimization.simulation_coverage_campaign import (
    SimulationCoverageArtifact,
    _canonical_sha256,
    _optimizer_transcript_sha256,
    run_simulation_coverage_campaign,
    write_frozen_simulation_coverage_artifact,
)

_ARTIFACT_PATH = (
    Path(__file__).resolve().parents[1]
    / "evaluation_artifacts"
    / "simulation-coverage-mock-v3.json"
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
    evidence = verify_candidate_generalization_evidence(campaign.generalization_evidence)
    assert evidence is not None
    assert evidence.role == "validation_report_only_no_adaptive_feedback"
    assert evidence.claim_scope == "seed_robustness"
    assert evidence.shift_axes == ("seed_shift",)
    assert evidence.validation_replicate_count == 10
    assert evidence.qualified is True


def test_campaign_transcript_hash_ignores_cross_runtime_ulp_noise() -> None:
    lower_ulp = [{"metadata": {"mean": 0.5823333333333333}}]
    upper_ulp = [{"metadata": {"mean": 0.5823333333333334}}]
    material_change = [{"metadata": {"mean": 0.5824333333333333}}]

    assert _canonical_sha256(lower_ulp) == _canonical_sha256(upper_ulp)
    assert _canonical_sha256(lower_ulp) != _canonical_sha256(material_change)


def test_campaign_transcript_hash_binds_causal_execution_not_blas_diagnostics() -> None:
    baseline = [
        {
            "candidate_id": "generation-01-00",
            "generation_index": 1,
            "parameters": {"kp": 1.2},
            "training_loss": 0.4,
            "feasible": True,
            "optimizer_strategy": "optimizer_portfolio",
            "optimizer_metadata": {
                "child_strategy": "bipop_cma_es",
                "optimizer_generated_by": "bipop_cma_es",
                "cma_cohort_position": 0,
                "mahalanobis_squared": 2.987321765792121,
                "cma_state": {"covariance": [[1.0, 1e-16], [1e-16, 1.0]]},
            },
        }
    ]
    equivalent_diagnostics = json.loads(json.dumps(baseline))
    equivalent_diagnostics[0]["optimizer_metadata"]["mahalanobis_squared"] = 7.025120301676976
    equivalent_diagnostics[0]["optimizer_metadata"]["cma_state"] = {
        "covariance": [[1.0, -1e-16], [-1e-16, 1.0]]
    }
    changed_candidate = json.loads(json.dumps(baseline))
    changed_candidate[0]["parameters"]["kp"] = 1.3
    changed_route = json.loads(json.dumps(baseline))
    changed_route[0]["optimizer_metadata"]["child_strategy"] = "turbo"

    baseline_hash = _optimizer_transcript_sha256(baseline)
    assert _optimizer_transcript_sha256(equivalent_diagnostics) == baseline_hash
    assert _optimizer_transcript_sha256(changed_candidate) != baseline_hash
    assert _optimizer_transcript_sha256(changed_route) != baseline_hash


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
