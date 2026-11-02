from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.orchestration import harness_reflection_outcome_stress as stress_module
from app.orchestration.harness_reflection_outcome_stress import (
    build_harness_reflection_outcome_stress_artifact,
    build_harness_reflection_outcome_stress_manifest,
    verify_harness_reflection_outcome_stress_artifact,
    verify_harness_reflection_outcome_stress_manifest,
)
from scripts.evaluate_harness_reflection_outcome_stress import (
    render_harness_reflection_outcome_stress_files,
)

ARTIFACT_ROOT = Path(__file__).resolve().parents[1] / "evaluation_artifacts"
JSON_ARTIFACT = ARTIFACT_ROOT / "harness-reflection-outcome-stress-v1.json"
CSV_ARTIFACT = ARTIFACT_ROOT / "harness-reflection-outcome-stress-v1.csv"
MANIFEST_ARTIFACT = (
    ARTIFACT_ROOT / "harness-reflection-outcome-stress-v1.manifest.json"
)
SHA256_ARTIFACT = ARTIFACT_ROOT / "harness-reflection-outcome-stress-v1.sha256"


def _load(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def test_outcome_stress_reports_mixed_quality_without_general_benefit_claim() -> None:
    artifact = _load(JSON_ARTIFACT)
    primary = artifact["contrast_summaries"][
        "no_observed_outcome_reflection"
    ]

    assert artifact["claim_label"] == "SYNTHETIC_MOCK_PILOT_INFORMED"
    assert artifact["general_causal_benefit_claim_permitted"] is False
    assert artifact["consistent_holdout_benefit_observed"] is False
    assert artifact["causal_synthetic_protocol_effect_observed"] is True
    assert artifact["network_calls"] == 0
    assert artifact["real_credentials_used"] is False
    assert artifact["physical_fidelity"] is False
    assert artifact["summary"]["primary_holdout_direction_mixed"] is True
    assert artifact["summary"]["primary_full_lower_realized_trials_every_block"] is False
    assert primary["holdout_paired_signs"]["full_better"] > 0
    assert primary["holdout_paired_signs"]["comparison_better"] > 0
    assert primary["consistent_full_holdout_benefit"] is False
    assert primary["consistent_full_realized_trial_reduction"] is False
    assert primary["realized_trial_paired_signs"] == {
        "comparison_better": 2,
        "full_better": 3,
        "tie": 0,
    }
    assert primary["trial_delta_comparison_minus_full_total"] == 44


def test_outcome_stress_activates_reflection_intervention_in_every_block() -> None:
    artifact = _load(JSON_ARTIFACT)
    primary_rows = [
        row
        for row in artifact["comparison_rows"]
        if row["comparison_arm"] == "no_observed_outcome_reflection"
    ]

    assert len(primary_rows) == 5
    assert all(row["intervention_activated"] for row in primary_rows)
    assert all(row["tool_sequence_changed"] for row in primary_rows)
    assert all(row["outcome_changed"] for row in primary_rows)
    assert all(
        row["result_status"] == "causal_protocol_difference"
        for row in primary_rows
    )


def test_committed_outcome_stress_remains_a_verified_legacy_freeze() -> None:
    manifest = _load(MANIFEST_ARTIFACT)
    artifact = _load(JSON_ARTIFACT)

    current_manifest = build_harness_reflection_outcome_stress_manifest()
    current_artifact = build_harness_reflection_outcome_stress_artifact()
    assert manifest != current_manifest
    assert artifact != current_artifact
    assert manifest["runtime_contract"]["evidence_schema_version"] == "2.7"
    assert manifest["runtime_contract"]["prompt_template_version"] == "1.6"
    assert manifest["manifest_sha256"] == (
        "bbf3d39405fd9092d59cf5d0557d14616f8d4a8739e1865f7e2cf6fda811e1b2"
    )
    assert current_manifest["runtime_contract"]["evidence_schema_version"] == "2.9"
    assert current_manifest["runtime_contract"]["prompt_template_version"] == "1.7"
    assert verify_harness_reflection_outcome_stress_manifest(manifest) == manifest
    assert (
        verify_harness_reflection_outcome_stress_artifact(
            artifact,
            manifest=manifest,
        )
        == artifact
    )


def test_outcome_stress_files_are_canonical() -> None:
    artifact = _load(JSON_ARTIFACT)
    manifest = _load(MANIFEST_ARTIFACT)
    payloads = render_harness_reflection_outcome_stress_files(
        artifact,
        manifest,
        json_name=JSON_ARTIFACT.name,
        csv_name=CSV_ARTIFACT.name,
        manifest_name=MANIFEST_ARTIFACT.name,
    )

    assert payloads[0] == JSON_ARTIFACT.read_bytes()
    assert payloads[1] == CSV_ARTIFACT.read_bytes()
    assert payloads[2] == MANIFEST_ARTIFACT.read_bytes()
    assert payloads[3] == SHA256_ARTIFACT.read_bytes()


def test_outcome_stress_rejects_tamper() -> None:
    artifact = _load(JSON_ARTIFACT)
    artifact["consistent_holdout_benefit_observed"] = True
    with pytest.raises(ValueError, match="hash does not recompute"):
        verify_harness_reflection_outcome_stress_artifact(artifact)

    manifest = _load(MANIFEST_ARTIFACT)
    manifest["budget"]["max_total_trials"] += 1
    with pytest.raises(ValueError, match="hash does not recompute"):
        verify_harness_reflection_outcome_stress_manifest(manifest)


def test_outcome_stress_rejects_self_consistent_forged_arm_metrics() -> None:
    manifest = _load(MANIFEST_ARTIFACT)
    artifact = _load(JSON_ARTIFACT)
    first_arm = artifact["block_rows"][0]["arms"][0]
    first_arm["result_metrics"]["total_trials"] += 1
    first_arm["result_metrics_sha256"] = stress_module._sha256(
        first_arm["result_metrics"]
    )
    forged = stress_module._build_from_blocks(
        manifest=manifest,
        block_rows=artifact["block_rows"],
    )

    with pytest.raises(ValueError, match="arm integrity"):
        verify_harness_reflection_outcome_stress_artifact(
            forged,
            manifest=manifest,
        )
