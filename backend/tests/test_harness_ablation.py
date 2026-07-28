from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from app.orchestration.harness_ablation import (
    build_harness_ablation_artifact,
    load_harness_ablation_artifact,
    verify_harness_ablation_artifact,
)
from scripts.evaluate_harness_ablations import write_harness_ablation_files

ARTIFACT_ROOT = Path(__file__).resolve().parents[1] / "evaluation_artifacts"
JSON_ARTIFACT = ARTIFACT_ROOT / "harness-contract-ablation-v2.json"
CSV_ARTIFACT = ARTIFACT_ROOT / "harness-contract-ablation-v2.csv"
SHA256_ARTIFACT = ARTIFACT_ROOT / "harness-contract-ablation-v2.sha256"


def test_harness_ablation_is_deterministic_and_claim_bounded() -> None:
    first = build_harness_ablation_artifact()
    second = build_harness_ablation_artifact()

    assert first == second
    assert first["evidence_class"] == "source_contract_ablation"
    assert first["causal_claim_permitted"] is False
    assert first["physical_fidelity"] is False
    assert first["live_model_calls"] is False
    assert first["simulator_runs"] is False
    assert "do not measure optimizer quality" in first["claim_boundary"]

    summary = first["summary"]
    assert summary == {
        "component_count": 5,
        "probe_count": 25,
        "full_contract_correct_count": 25,
        "ablated_contract_correct_count": 6,
        "full_contract_correct_rate": 1.0,
        "ablated_contract_correct_rate": 0.24,
        "absolute_contract_delta": 0.76,
    }
    by_component = {row["component"]: row for row in first["component_rows"]}
    assert by_component["provider_trust_filter"]["ablated_contract_correct_count"] == 2
    assert by_component["tool_eligibility_gate"]["ablated_contract_correct_count"] == 1
    assert by_component["deterministic_fallback"]["ablated_contract_correct_count"] == 1
    assert by_component["scenario_and_outcome_isolation"]["ablated_contract_correct_count"] == 2
    assert by_component["scenario_profile_context"]["probe_count"] == 5
    assert by_component["scenario_profile_context"]["full_contract_correct_rate"] == 1.0
    assert by_component["scenario_profile_context"]["ablated_contract_correct_rate"] == 0.0


def test_harness_ablation_rejects_hash_or_claim_upgrade() -> None:
    artifact = build_harness_ablation_artifact()
    artifact["summary"]["full_contract_correct_count"] = 19
    with pytest.raises(ValueError, match="does not recompute"):
        verify_harness_ablation_artifact(artifact)

    artifact = build_harness_ablation_artifact()
    unsigned = {key: value for key, value in artifact.items() if key != "artifact_sha256"}
    unsigned["physical_fidelity"] = True
    artifact = {
        **unsigned,
        "artifact_sha256": hashlib.sha256(
            json.dumps(
                unsigned,
                ensure_ascii=False,
                allow_nan=False,
                separators=(",", ":"),
                sort_keys=True,
            ).encode("utf-8")
        ).hexdigest(),
    }
    with pytest.raises(ValueError, match="claim boundary"):
        verify_harness_ablation_artifact(artifact)


def test_committed_harness_ablation_remains_a_verified_legacy_freeze() -> None:
    artifact = load_harness_ablation_artifact(JSON_ARTIFACT)

    current = build_harness_ablation_artifact()
    assert artifact != current
    assert artifact["contract_versions"]["harness_evidence_schema"] == "2.7"
    assert artifact["contract_versions"]["prompt_template"] == "1.6"
    assert artifact["artifact_sha256"] == (
        "f91a848c84d1766fd728968f4d82d49a9bc3af7fc2cc036da5b99efed62bb8f2"
    )
    assert current["contract_versions"]["harness_evidence_schema"] == "2.8"
    assert current["contract_versions"]["prompt_template"] == "1.7"
    manifest = SHA256_ARTIFACT.read_text(encoding="ascii").splitlines()
    assert manifest == [
        f"{hashlib.sha256(JSON_ARTIFACT.read_bytes()).hexdigest()}  {JSON_ARTIFACT.name}",
        f"{hashlib.sha256(CSV_ARTIFACT.read_bytes()).hexdigest()}  {CSV_ARTIFACT.name}",
    ]


def test_harness_ablation_writer_supports_reproducible_check_mode(
    tmp_path: Path,
) -> None:
    json_path = tmp_path / JSON_ARTIFACT.name
    csv_path = tmp_path / CSV_ARTIFACT.name
    sha256_path = tmp_path / SHA256_ARTIFACT.name

    first = write_harness_ablation_files(
        json_path=json_path,
        csv_path=csv_path,
        sha256_path=sha256_path,
    )
    second = write_harness_ablation_files(
        json_path=json_path,
        csv_path=csv_path,
        sha256_path=sha256_path,
        check=True,
    )

    assert first == second
    csv_lines = csv_path.read_text(encoding="utf-8").splitlines()
    assert len(csv_lines) == 26

    csv_path.write_text("stale\n", encoding="utf-8")
    with pytest.raises(ValueError, match="stale"):
        write_harness_ablation_files(
            json_path=json_path,
            csv_path=csv_path,
            sha256_path=sha256_path,
            check=True,
        )
