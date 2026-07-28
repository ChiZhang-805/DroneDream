from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path

import pytest

from scripts.export_technical_report_evidence import (
    build_report_evidence_bundle,
    summarize_scenario_generalization,
    summarize_simulation_coverage,
    write_report_evidence_bundle,
)

_TEST_SOURCE_COMMIT = "a" * 40
_TEST_GENERATED_AT = "2026-07-28T00:00:00Z"
_TEST_RECEIPT = Path(__file__).resolve().parent / "fixtures" / "test_run_receipt_v1.json"


def _build_bundle() -> dict[str, object]:
    return build_report_evidence_bundle(
        source_commit=_TEST_SOURCE_COMMIT,
        generated_at=_TEST_GENERATED_AT,
        backend_test_receipt_path=_TEST_RECEIPT,
    )


def test_report_evidence_bundle_recomputes_frozen_metrics() -> None:
    first = _build_bundle()
    second = _build_bundle()

    assert first == second
    assert first["schema_version"] == "dronedream.technical-report-evidence.v6"
    assert first["source_commit"] == _TEST_SOURCE_COMMIT
    assert first["generated_at"] == _TEST_GENERATED_AT
    assert len(first["bundle_sha256"]) == 64

    routing = first["routing"]
    assert routing["evidence_class"] == "development_routing_corpus"
    assert routing["contract_current"] is False
    assert routing["qualification_scope"] == "archived_evidence_2_4_prompt_1_1"
    assert routing["current_evidence_schema_version"] == "2.7"
    assert routing["current_prompt_template_version"] == "1.5"
    assert routing["case_count"] == 24
    assert routing["passed_count"] == 24
    assert routing["pass_rate"] == 1.0
    assert routing["best_constant_pass_rate"] == pytest.approx(14 / 24)
    assert routing["uniform_random_expected_pass_rate"] == pytest.approx(5.625 / 24)
    assert routing["qualified"] is True
    assert len(routing["category_rows"]) == 8

    coverage = first["simulation_coverage"]
    assert coverage["evidence_class"] == "synthetic_mock_campaign"
    assert coverage["physical_fidelity"] is False
    assert coverage["scenario_count"] == 10
    assert coverage["evaluated_candidate_count"] == 61
    assert coverage["exhaustive_oracle_candidate_count"] == 2430
    assert coverage["baseline_holdout_loss"] == pytest.approx(0.82811)
    assert coverage["selected_holdout_loss"] == pytest.approx(0.58525)
    assert coverage["relative_improvement_rate"] == pytest.approx(0.293270217725)
    generalization = coverage["generalization_evidence"]
    assert generalization["role"] == "validation_report_only_no_adaptive_feedback"
    assert generalization["claim_scope"] == "seed_robustness"
    assert generalization["shift_axes"] == ["seed_shift"]
    assert generalization["validation_replicate_count"] == 10
    assert generalization["validation_trial_count"] == 10
    assert generalization["validation_completed_trial_count"] == 10
    assert generalization["assessment"] == "qualified_improved_or_equal"
    assert generalization["training_scalar_loss"] == pytest.approx(0.58554)
    assert generalization["validation_scalar_loss"] == pytest.approx(0.58525)
    assert generalization["scalar_loss_degradation"] == pytest.approx(-0.00029)
    assert all(
        row["selected_holdout_loss"] < row["baseline_holdout_loss"]
        for row in coverage["scenario_rows"]
    )

    generalization_campaign = first["scenario_generalization"]
    assert generalization_campaign["evidence_class"] == "synthetic_mock_mixed_shift_campaign"
    assert generalization_campaign["physical_fidelity"] is False
    assert generalization_campaign["validation_outcomes_used_for_selection"] is False
    assert generalization_campaign["training_case_count"] == 5
    assert generalization_campaign["validation_case_count"] == 10
    assert generalization_campaign["configuration_shift_case_count"] == 5
    assert generalization_campaign["novel_scenario_type_case_count"] == 5
    assert generalization_campaign["evaluated_candidate_count"] == 61
    assert generalization_campaign["training_scalar_loss"] == pytest.approx(0.8734)
    assert generalization_campaign["validation_scalar_loss"] == pytest.approx(1.03057)
    assert generalization_campaign["scalar_loss_relative_degradation"] == pytest.approx(
        0.17995191206778113
    )
    assert (
        generalization_campaign["generalization_evidence"]["assessment"]
        == "qualified_with_degradation"
    )
    assert generalization_campaign["generalization_evidence"]["shift_axes"] == [
        "configuration_shift",
        "scenario_type_shift",
    ]
    assert len(generalization_campaign["case_rows"]) == 10

    ablations = first["harness_ablations"]
    assert ablations["evidence_class"] == "source_contract_ablation"
    assert ablations["causal_claim_permitted"] is False
    assert ablations["physical_fidelity"] is False
    assert ablations["summary"]["component_count"] == 5
    assert ablations["summary"]["probe_count"] == 25
    assert ablations["summary"]["full_contract_correct_count"] == 25
    assert ablations["summary"]["ablated_contract_correct_count"] == 6

    outcome_campaign = first["harness_outcome_campaign"]
    assert outcome_campaign["evidence_class"] == "synthetic_mock_campaign"
    assert outcome_campaign["claim_label"] == "SYNTHETIC_MOCK"
    assert outcome_campaign["physical_fidelity"] is False
    assert outcome_campaign["simulator_backend"] == "mock"
    assert outcome_campaign["live_model_calls"] is False
    assert outcome_campaign["network_calls"] == 0
    assert outcome_campaign["network_connect_guard_enforced"] is True
    assert outcome_campaign["real_credentials_used"] is False
    assert outcome_campaign["llm_superiority_claim_permitted"] is False
    assert outcome_campaign["harness_causal_benefit_claim_permitted"] is False
    assert outcome_campaign["px4_or_flight_claim_permitted"] is False
    assert outcome_campaign["summary"] == {
        "seed_block_count": 5,
        "arm_run_count": 15,
        "total_persisted_trials": 579,
        "fallback_comparison_count": 10,
        "exact_outcome_match_count": 10,
        "all_fallback_outcomes_match_direct_portfolio": True,
        "all_evidence_complete": True,
    }
    assert len(outcome_campaign["arm_rows"]) == 15
    assert all(
        row["exact_match_to_direct_portfolio"] is True and row["evidence_completeness_rate"] == 1.0
        for row in outcome_campaign["arm_rows"]
    )

    component_ablation = first["harness_component_outcome_ablation"]
    assert component_ablation["evidence_class"] == ("synthetic_mock_component_ablation")
    assert component_ablation["physical_fidelity"] is False
    assert component_ablation["live_model_calls"] is False
    assert component_ablation["network_calls"] == 0
    assert component_ablation["summary"]["total_persisted_trials"] == 554
    assert component_ablation["summary"]["arm_run_count"] == 20
    assert {
        "harness_component_outcome_ablation",
        "harness_component_outcome_ablation_manifest",
        "harness_component_outcome_ablation_csv",
    } <= set(first["sources"])
    for source_name in (
        "harness_component_outcome_ablation",
        "harness_component_outcome_ablation_manifest",
        "harness_component_outcome_ablation_csv",
    ):
        assert len(first["sources"][source_name]["sha256"]) == 64

    backend_tests = first["backend_tests"]
    assert backend_tests["source_commit"] == _TEST_SOURCE_COMMIT
    assert backend_tests["full_suite"]["result"] == {
        "status": "passed",
        "passed": 1139,
        "failed": 0,
    }
    assert backend_tests["validation_bridge"]["focused_rerun_performed"] is True
    assert first["sources"]["backend_test_receipt"]["path"].endswith("test_run_receipt_v1.json")

    holdout = first["routing_policy_holdout"]
    assert holdout["evidence_class"] == "deterministic_router_policy_holdout"
    assert holdout["corpus_role"] == "locked_holdout"
    assert holdout["case_count"] == 16
    assert holdout["passed_count"] == 16
    assert holdout["pass_rate"] == 1.0
    assert holdout["qualified"] is True
    assert holdout["online_calls"] == 0
    assert holdout["simulator_runs"] == 0
    assert holdout["feedback_writebacks"] == 0


def test_report_evidence_refuses_to_upgrade_mock_to_physical() -> None:
    source = (
        Path(__file__).resolve().parents[1]
        / "evaluation_artifacts"
        / "simulation-coverage-mock-v3.json"
    )
    payload = json.loads(source.read_text(encoding="utf-8"))
    payload["physical_fidelity"] = True

    with pytest.raises(ValueError, match="must remain non-physical"):
        summarize_simulation_coverage(payload)


def test_report_evidence_refuses_inconsistent_improvement() -> None:
    source = (
        Path(__file__).resolve().parents[1]
        / "evaluation_artifacts"
        / "simulation-coverage-mock-v3.json"
    )
    payload = json.loads(source.read_text(encoding="utf-8"))
    payload["baseline_to_selected_improvement_rate"] = 0.99

    with pytest.raises(ValueError, match="does not recompute"):
        summarize_simulation_coverage(payload)


def test_report_evidence_refuses_validation_feedback_in_mixed_shift() -> None:
    source = (
        Path(__file__).resolve().parents[1]
        / "evaluation_artifacts"
        / "scenario-generalization-mock-v1.json"
    )
    payload = json.loads(source.read_text(encoding="utf-8"))
    payload["validation_outcomes_used_for_selection"] = True

    with pytest.raises(ValueError, match="must not enter"):
        summarize_scenario_generalization(payload)


def test_report_evidence_writes_chart_ready_csv(tmp_path: Path) -> None:
    bundle = _build_bundle()
    output_path = tmp_path / "evidence.json"
    manifest_path = tmp_path / "evidence.manifest.json"
    sha256_path = tmp_path / "evidence.sha256"
    csv_directory = tmp_path / "csv"

    write_report_evidence_bundle(
        bundle,
        output_path=output_path,
        manifest_path=manifest_path,
        sha256_path=sha256_path,
        csv_directory=csv_directory,
    )

    assert json.loads(output_path.read_text(encoding="utf-8")) == bundle
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["schema_version"] == ("dronedream.technical-report-evidence-manifest.v1")
    assert manifest["source_commit"] == _TEST_SOURCE_COMMIT
    assert manifest["generated_at"] == _TEST_GENERATED_AT
    assert manifest["bundle"]["bundle_sha256"] == bundle["bundle_sha256"]
    assert manifest["bundle"]["file_sha256"] == hashlib.sha256(output_path.read_bytes()).hexdigest()
    checksum_lines = sha256_path.read_text(encoding="utf-8").splitlines()
    assert checksum_lines == [
        f"{hashlib.sha256(output_path.read_bytes()).hexdigest()}  evidence.json",
        (f"{hashlib.sha256(manifest_path.read_bytes()).hexdigest()}  evidence.manifest.json"),
    ]
    with (csv_directory / "synthetic_scenario_holdout.csv").open(
        encoding="utf-8",
        newline="",
    ) as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 10
    assert {row["scenario"] for row in rows} == {
        row["scenario"] for row in bundle["simulation_coverage"]["scenario_rows"]
    }
    with (csv_directory / "synthetic_mixed_shift_generalization.csv").open(
        encoding="utf-8",
        newline="",
    ) as handle:
        generalization_rows = list(csv.DictReader(handle))
    assert len(generalization_rows) == 10
    assert {row["shift_class"] for row in generalization_rows} == {
        "configuration_shift",
        "scenario_type_shift",
    }
    with (csv_directory / "harness_contract_ablations.csv").open(
        encoding="utf-8",
        newline="",
    ) as handle:
        ablation_rows = list(csv.DictReader(handle))
    assert len(ablation_rows) == 5
    assert {row["component"] for row in ablation_rows} == {
        row["component"] for row in bundle["harness_ablations"]["component_rows"]
    }
    with (csv_directory / "harness_fallback_outcomes.csv").open(
        encoding="utf-8",
        newline="",
    ) as handle:
        outcome_rows = list(csv.DictReader(handle))
    assert len(outcome_rows) == 15
    assert all(
        row["exact_match_to_direct_portfolio"] == "True"
        and float(row["evidence_completeness_rate"]) == 1.0
        for row in outcome_rows
    )
    with (csv_directory / "routing_policy_holdout_categories.csv").open(
        encoding="utf-8",
        newline="",
    ) as handle:
        holdout_rows = list(csv.DictReader(handle))
    assert sum(int(row["case_count"]) for row in holdout_rows) == 16
    assert all(float(row["pass_rate"]) == 1.0 for row in holdout_rows)
