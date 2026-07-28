"""Contracts for the frozen offline AURORA component outcome ablation."""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path

import pytest

from app.orchestration.harness_component_ablation import (
    HARNESS_COMPONENT_ABLATION_ARMS,
    HARNESS_COMPONENT_ABLATION_SEED_BLOCKS,
    build_harness_component_ablation_artifact,
    build_harness_component_ablation_manifest,
    verify_harness_component_ablation_artifact,
    verify_harness_component_ablation_manifest,
)
from scripts.evaluate_harness_component_ablations import (
    write_harness_component_ablation_files,
)

ARTIFACT_ROOT = Path(__file__).resolve().parents[1] / "evaluation_artifacts"
STEM = "harness-component-outcome-ablation-v2"
JSON_ARTIFACT = ARTIFACT_ROOT / f"{STEM}.json"
CSV_ARTIFACT = ARTIFACT_ROOT / f"{STEM}.csv"
MANIFEST_ARTIFACT = ARTIFACT_ROOT / f"{STEM}.manifest.json"
SHA256_ARTIFACT = ARTIFACT_ROOT / f"{STEM}.sha256"


def _load_manifest() -> dict[str, object]:
    return verify_harness_component_ablation_manifest(
        json.loads(MANIFEST_ARTIFACT.read_text(encoding="utf-8"))
    )


def _load_artifact() -> dict[str, object]:
    return verify_harness_component_ablation_artifact(
        json.loads(JSON_ARTIFACT.read_text(encoding="utf-8")),
        manifest=_load_manifest(),
    )


def test_committed_component_ablation_is_offline_matched_and_claim_bounded() -> None:
    artifact = _load_artifact()

    assert artifact["claim_label"] == "SYNTHETIC_MOCK"
    assert artifact["physical_fidelity"] is False
    assert artifact["simulator_backend"] == "mock"
    assert artifact["live_model_calls"] is False
    assert artifact["network_calls"] == 0
    assert artifact["real_credentials_used"] is False
    assert artifact["general_causal_claim_permitted"] is False
    assert artifact["llm_superiority_claim_permitted"] is False
    assert artifact["px4_or_flight_claim_permitted"] is False
    assert artifact["summary"] == {
        "seed_block_count": 5,
        "arm_count": 4,
        "arm_run_count": 20,
        "total_persisted_trials": 554,
        "comparison_count": 15,
        "component_isolation_count": 5,
        "inconclusive_component_isolation_count": 5,
        "interpretation_status_counts": {
            "observed_protocol_difference": 5,
            "no_observed_protocol_difference": 10,
            "inconclusive_intervention_not_activated": 0,
        },
        "all_network_calls_blocked": True,
        "all_evidence_complete": True,
    }
    assert [block["seed_block"] for block in artifact["block_rows"]] == list(
        HARNESS_COMPONENT_ABLATION_SEED_BLOCKS
    )
    for block in artifact["block_rows"]:
        assert [arm["arm"] for arm in block["arms"]] == list(HARNESS_COMPONENT_ABLATION_ARMS)
        assert len({tuple(arm["tool_sequence"]) for arm in block["arms"]}) >= 3
        assert all(
            arm["result_metrics"]["evidence_completeness_rate"] == 1.0 for arm in block["arms"]
        )
        assert all(
            arm["result_metrics"]["terminal_failure_trials"]
            + arm["result_metrics"]["recovered_trials"]
            >= 0
            for arm in block["arms"]
        )
    assert all(
        row["result_status"] == "inconclusive_component_not_decision_relevant_under_policy"
        for row in artifact["component_isolation_rows"]
    )


def test_ablation_really_removes_memory_and_reflection_before_routing() -> None:
    artifact = _load_artifact()

    for block in artifact["block_rows"]:
        by_name = {arm["arm"]: arm for arm in block["arms"]}
        full = by_name["full_aurora"]
        no_memory = by_name["no_decision_memory"]
        no_reflection = by_name["no_observed_outcome_reflection"]
        fixed = by_name["fixed_deterministic_portfolio"]

        assert full["tool_sequence"] == ["constrained_mobo", "turbo"]
        assert no_memory["tool_sequence"] == [
            "constrained_mobo",
            "optimizer_portfolio",
        ]
        assert no_reflection["tool_sequence"] == [
            "constrained_mobo",
            "optimizer_portfolio",
        ]
        assert fixed["tool_sequence"] == [
            "optimizer_portfolio",
            "optimizer_portfolio",
        ]
        assert no_memory["component_activation"]["removed_memory_count"] == 1
        assert no_memory["component_activation"]["provider_visible_intervention_activated"] is True
        assert no_reflection["component_activation"]["removed_reflection_count"] == 1
        assert (
            no_reflection["component_activation"]["provider_visible_intervention_activated"] is True
        )


def test_committed_component_ablation_remains_a_verified_legacy_freeze() -> None:
    manifest = _load_manifest()
    artifact = _load_artifact()
    assert manifest["runtime_contract"]["evidence_schema_version"] == "2.7"
    assert manifest["runtime_contract"]["prompt_template_version"] == "1.6"
    assert manifest != build_harness_component_ablation_manifest()
    assert artifact != build_harness_component_ablation_artifact()


def test_component_ablation_rejects_claim_or_metric_tamper() -> None:
    artifact = json.loads(JSON_ARTIFACT.read_text(encoding="utf-8"))
    artifact["physical_fidelity"] = True
    unsigned = {key: value for key, value in artifact.items() if key != "artifact_sha256"}
    artifact["artifact_sha256"] = hashlib.sha256(
        json.dumps(
            unsigned,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()
    with pytest.raises(ValueError, match="claim boundary"):
        verify_harness_component_ablation_artifact(
            artifact,
            manifest=_load_manifest(),
        )

    artifact = json.loads(JSON_ARTIFACT.read_text(encoding="utf-8"))
    artifact["block_rows"][0]["arms"][0]["result_metrics"]["total_trials"] += 1
    with pytest.raises(ValueError, match="does not recompute"):
        verify_harness_component_ablation_artifact(
            artifact,
            manifest=_load_manifest(),
        )

    artifact = json.loads(JSON_ARTIFACT.read_text(encoding="utf-8"))
    arm = artifact["block_rows"][0]["arms"][0]
    arm["decision_trace"][1]["tool_id"] = "optimizer_portfolio"
    arm["tool_sequence"][1] = "optimizer_portfolio"
    arm["scripted_router_trace"][1]["selected_tool"] = "optimizer_portfolio"
    unsigned = {key: value for key, value in artifact.items() if key != "artifact_sha256"}
    artifact["artifact_sha256"] = hashlib.sha256(
        json.dumps(
            unsigned,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()
    with pytest.raises(ValueError, match="decision trace"):
        verify_harness_component_ablation_artifact(
            artifact,
            manifest=_load_manifest(),
        )


def test_component_ablation_files_and_check_mode_are_reproducible(
    tmp_path: Path,
) -> None:
    artifact = _load_artifact()
    manifest = _load_manifest()
    json_path = tmp_path / JSON_ARTIFACT.name
    csv_path = tmp_path / CSV_ARTIFACT.name
    manifest_path = tmp_path / MANIFEST_ARTIFACT.name
    sha256_path = tmp_path / SHA256_ARTIFACT.name

    first = write_harness_component_ablation_files(
        json_path=json_path,
        csv_path=csv_path,
        manifest_path=manifest_path,
        sha256_path=sha256_path,
        artifact=artifact,
        manifest=manifest,
    )
    second = write_harness_component_ablation_files(
        json_path=json_path,
        csv_path=csv_path,
        manifest_path=manifest_path,
        sha256_path=sha256_path,
        check=True,
        artifact=artifact,
        manifest=manifest,
    )

    assert first == second
    with csv_path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 20
    assert {row["arm"] for row in rows} == set(HARNESS_COMPONENT_ABLATION_ARMS)
    assert all(row["evidence_completeness_rate"] == "1.0" for row in rows)
    assert sha256_path.read_text(encoding="ascii").splitlines() == [
        f"{hashlib.sha256(json_path.read_bytes()).hexdigest()}  {json_path.name}",
        f"{hashlib.sha256(csv_path.read_bytes()).hexdigest()}  {csv_path.name}",
        (f"{hashlib.sha256(manifest_path.read_bytes()).hexdigest()}  {manifest_path.name}"),
    ]


def test_manifest_rejects_hash_tamper() -> None:
    manifest = json.loads(MANIFEST_ARTIFACT.read_text(encoding="utf-8"))
    manifest["budget"]["max_total_trials"] += 1
    with pytest.raises(ValueError, match="does not recompute"):
        verify_harness_component_ablation_manifest(manifest)
