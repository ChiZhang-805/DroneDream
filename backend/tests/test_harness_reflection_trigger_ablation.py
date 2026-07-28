from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.orchestration.harness_reflection_trigger_ablation import (
    build_harness_reflection_trigger_artifact,
    build_harness_reflection_trigger_manifest,
    verify_harness_reflection_trigger_artifact,
    verify_harness_reflection_trigger_manifest,
)
from scripts.evaluate_harness_reflection_triggers import (
    write_harness_reflection_trigger_files,
)

ARTIFACT_ROOT = Path(__file__).resolve().parents[1] / "evaluation_artifacts"
JSON_ARTIFACT = ARTIFACT_ROOT / "harness-reflection-trigger-ablation-v1.json"
CSV_ARTIFACT = ARTIFACT_ROOT / "harness-reflection-trigger-ablation-v1.csv"
MANIFEST_ARTIFACT = (
    ARTIFACT_ROOT / "harness-reflection-trigger-ablation-v1.manifest.json"
)
SHA256_ARTIFACT = ARTIFACT_ROOT / "harness-reflection-trigger-ablation-v1.sha256"


def _load(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def test_trigger_ablation_covers_required_states_without_general_benefit_claim() -> None:
    artifact = _load(JSON_ARTIFACT)

    assert artifact["claim_label"] == "SYNTHETIC_CONTRACT"
    assert artifact["general_causal_benefit_claim_permitted"] is False
    assert artifact["optimizer_quality_claim_permitted"] is False
    assert artifact["provider_calls"] == 0
    assert artifact["network_calls"] == 0
    assert artifact["real_credentials_used"] is False
    assert artifact["simulator_runs"] == 0
    assert artifact["physical_fidelity"] is False
    assert artifact["summary"] == {
        "all_six_required_triggers_covered": True,
        "case_count": 6,
        "case_status_counts": {
            "causal_contract_difference": 4,
            "inconclusive_intervention_not_activated": 1,
            "no_observed_contract_difference": 1,
        },
        "phase_difference_step_count": 4,
        "selected_tool_difference_step_count": 4,
        "step_count": 7,
        "step_status_counts": {
            "causal_contract_difference": 4,
            "inconclusive_intervention_not_activated": 1,
            "no_observed_contract_difference": 2,
        },
        "tool_surface_difference_step_count": 4,
        "trigger_count": 6,
    }


def test_trigger_ablation_is_a_direct_reflection_intervention() -> None:
    artifact = _load(JSON_ARTIFACT)
    cases = {row["case_id"]: row for row in artifact["case_rows"]}

    failure = cases["failure_concentration"]["steps"][0]
    full, no_reflection = failure["arms"]
    assert failure["intervention_activated"] is True
    assert full["decision_memory_count"] == 1
    assert no_reflection["decision_memory_count"] == 1
    assert full["verified_reflection_count"] == 1
    assert no_reflection["verified_reflection_count"] == 0
    assert full["observed_outcome_count"] == 1
    assert no_reflection["observed_outcome_count"] == 0
    assert no_reflection["removed_reflection_count"] == 1
    assert full["plan_phase"] == "recovery"
    assert no_reflection["plan_phase"] == "balanced"

    exhaustion = cases["search_space_exhaustion"]["steps"][0]
    assert exhaustion["intervention_activated"] is False
    assert exhaustion["result_status"] == "inconclusive_intervention_not_activated"


def test_recovery_then_reexplore_is_observed_as_a_bounded_transition() -> None:
    artifact = _load(JSON_ARTIFACT)
    case = next(
        row
        for row in artifact["case_rows"]
        if row["case_id"] == "recovery_then_reexplore"
    )
    full_phases = [step["arms"][0]["plan_phase"] for step in case["steps"]]
    no_reflection_phases = [
        step["arms"][1]["plan_phase"] for step in case["steps"]
    ]

    assert full_phases == ["recovery", "exploration"]
    assert no_reflection_phases == ["balanced", "exploration"]


def test_committed_trigger_artifacts_match_current_production_contracts() -> None:
    manifest = _load(MANIFEST_ARTIFACT)
    artifact = _load(JSON_ARTIFACT)

    assert manifest == build_harness_reflection_trigger_manifest()
    assert artifact == build_harness_reflection_trigger_artifact()
    assert verify_harness_reflection_trigger_manifest(manifest) == manifest
    assert (
        verify_harness_reflection_trigger_artifact(artifact, manifest=manifest)
        == artifact
    )


def test_trigger_artifacts_are_byte_reproducible(tmp_path: Path) -> None:
    result = write_harness_reflection_trigger_files(
        json_path=tmp_path / JSON_ARTIFACT.name,
        csv_path=tmp_path / CSV_ARTIFACT.name,
        manifest_path=tmp_path / MANIFEST_ARTIFACT.name,
        sha256_path=tmp_path / SHA256_ARTIFACT.name,
    )
    assert result["summary"]["all_six_required_triggers_covered"] is True
    assert (tmp_path / JSON_ARTIFACT.name).read_bytes() == JSON_ARTIFACT.read_bytes()
    assert (tmp_path / CSV_ARTIFACT.name).read_bytes() == CSV_ARTIFACT.read_bytes()
    assert (
        (tmp_path / MANIFEST_ARTIFACT.name).read_bytes()
        == MANIFEST_ARTIFACT.read_bytes()
    )
    assert (
        (tmp_path / SHA256_ARTIFACT.name).read_bytes()
        == SHA256_ARTIFACT.read_bytes()
    )


def test_trigger_artifact_rejects_tamper() -> None:
    artifact = _load(JSON_ARTIFACT)
    artifact["summary"]["case_count"] += 1
    with pytest.raises(ValueError, match="hash does not recompute"):
        verify_harness_reflection_trigger_artifact(artifact)

    manifest = _load(MANIFEST_ARTIFACT)
    manifest["trigger_coverage"].pop()
    with pytest.raises(ValueError, match="hash does not recompute"):
        verify_harness_reflection_trigger_manifest(manifest)
