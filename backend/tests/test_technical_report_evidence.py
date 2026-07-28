from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path

import pytest

from scripts.export_technical_report_evidence import (
    _read_test_log_text,
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
    assert first["schema_version"] == "dronedream.technical-report-evidence.v8"
    assert first["source_commit"] == _TEST_SOURCE_COMMIT
    assert first["generated_at"] == _TEST_GENERATED_AT
    assert len(first["bundle_sha256"]) == 64

    routing = first["routing"]
    assert routing["evidence_class"] == "development_routing_corpus"
    assert routing["contract_current"] is True
    assert routing["qualification_scope"] == "current_evidence_2_7_prompt_1_6"
    assert routing["current_evidence_schema_version"] == "2.7"
    assert routing["current_prompt_template_version"] == "1.6"
    assert routing["evidence_schema_version"] == "2.7"
    assert routing["tool_registry_version"] == "2.1"
    assert routing["prompt_template_version"] == "1.6"
    assert routing["corpus_sha256"] == (
        "98b94ae1e32f3df7f5d119cefebe0f949fea5f17c537f8688c7d4c05b1d92f89"
    )
    assert routing["prompt_suite_sha256"] == (
        "93ca5fdafe123741821f47296e3e8b23cb5f9d68ff9d78bbf2c10af83642bd77"
    )
    assert routing["generation_config"] == {
        "temperature": None,
        "top_p": None,
        "seed": None,
        "response_format": "json_schema",
    }
    assert routing["case_count"] == 24
    assert routing["passed_count"] == 24
    assert routing["pass_rate"] == 1.0
    assert routing["best_constant_pass_rate"] == pytest.approx(14 / 24)
    assert routing["uniform_random_expected_pass_rate"] == pytest.approx(5.625 / 24)
    assert routing["qualified"] is True
    assert len(routing["category_rows"]) == 8
    assert first["sources"]["routing_predictions"]["path"].endswith(
        "harness-routing-gpt-4.1-2025-04-14-evidence-2.7-prompt-1.6-20260728.json"
    )
    assert first["sources"]["routing_predictions"]["sha256"] == (
        "2cd125346b10bc914c90d889ef43db97714dbbce9f20bbe47b5e0365e39c76e4"
    )

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

    trigger_ablation = first["harness_reflection_trigger_ablation"]
    assert trigger_ablation["evidence_class"] == (
        "deterministic_reflection_trigger_contract_ablation"
    )
    assert trigger_ablation["general_causal_benefit_claim_permitted"] is False
    assert trigger_ablation["optimizer_quality_claim_permitted"] is False
    assert trigger_ablation["artifact_sha256"] == (
        "cb7cc30bac7f63df4ddda84d81f881e111b6bac229eacc0b5ec5a228df3b0c38"
    )
    assert trigger_ablation["summary"]["case_count"] == 6
    assert trigger_ablation["summary"]["step_count"] == 7
    assert trigger_ablation["summary"]["phase_difference_step_count"] == 4
    assert trigger_ablation["summary"]["all_six_required_triggers_covered"] is True

    outcome_stress = first["harness_reflection_outcome_stress"]
    assert outcome_stress["evidence_class"] == ("synthetic_mock_long_horizon_component_stress")
    assert outcome_stress["claim_label"] == "SYNTHETIC_MOCK_PILOT_INFORMED"
    assert outcome_stress["physical_fidelity"] is False
    assert outcome_stress["general_causal_benefit_claim_permitted"] is False
    assert outcome_stress["consistent_holdout_benefit_observed"] is False
    assert outcome_stress["causal_synthetic_protocol_effect_observed"] is True
    assert outcome_stress["artifact_sha256"] == (
        "6da3544651ee56428b6e78f1613fd520c46b789dc3e7f9d44fc8be153dd9f5b3"
    )
    assert outcome_stress["summary"]["total_persisted_trials"] == 1588
    primary = outcome_stress["contrast_summaries"]["no_observed_outcome_reflection"]
    assert primary["holdout_paired_signs"] == {
        "comparison_better": 4,
        "full_better": 1,
        "tie": 0,
    }
    assert primary["realized_trial_paired_signs"] == {
        "comparison_better": 2,
        "full_better": 3,
        "tie": 0,
    }
    assert primary["trial_delta_comparison_minus_full_total"] == 44

    assert {
        "harness_reflection_trigger_ablation",
        "harness_reflection_trigger_ablation_manifest",
        "harness_reflection_trigger_ablation_csv",
        "harness_reflection_trigger_ablation_sha256",
        "harness_reflection_outcome_stress",
        "harness_reflection_outcome_stress_manifest",
        "harness_reflection_outcome_stress_csv",
        "harness_reflection_outcome_stress_sha256",
    } <= set(first["sources"])

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


def test_report_evidence_rejects_reflection_sidecar_tamper(
    tmp_path: Path,
) -> None:
    sidecar_path = (
        Path(__file__).resolve().parents[1]
        / "evaluation_artifacts"
        / "harness-reflection-trigger-ablation-v1.sha256"
    )
    tampered_path = tmp_path / sidecar_path.name
    tampered_path.write_text(
        sidecar_path.read_text(encoding="ascii").replace(
            "d1c7c752",
            "00000000",
            1,
        ),
        encoding="ascii",
    )

    with pytest.raises(ValueError, match="does not bind expected files"):
        build_report_evidence_bundle(
            source_commit=_TEST_SOURCE_COMMIT,
            generated_at=_TEST_GENERATED_AT,
            backend_test_receipt_path=_TEST_RECEIPT,
            harness_reflection_trigger_ablation_sha256_path=tampered_path,
        )


def test_report_evidence_rejects_receipt_log_count_mismatch(tmp_path: Path) -> None:
    receipt = json.loads(_TEST_RECEIPT.read_text(encoding="utf-8"))
    receipt["full_suite"]["result"]["passed"] = 1142
    unsigned = dict(receipt)
    unsigned.pop("receipt_sha256")
    receipt["receipt_sha256"] = hashlib.sha256(
        json.dumps(
            unsigned,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()
    receipt_path = tmp_path / "receipt.json"
    receipt_path.write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="does not contain the declared result"):
        build_report_evidence_bundle(
            source_commit=_TEST_SOURCE_COMMIT,
            generated_at=_TEST_GENERATED_AT,
            backend_test_receipt_path=receipt_path,
        )


def test_report_evidence_decodes_powershell_utf16le_pytest_logs(tmp_path: Path) -> None:
    log_path = tmp_path / "pytest.log"
    log_path.write_bytes("1147 passed in 788.78s (0:13:08)\r\n".encode("utf-16-le"))

    assert "1147 passed in 788.78s" in _read_test_log_text(log_path)


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
    with (csv_directory / "harness_reflection_trigger_steps.csv").open(
        encoding="utf-8",
        newline="",
    ) as handle:
        trigger_rows = list(csv.DictReader(handle))
    assert len(trigger_rows) == 7
    assert sum(row["result_status"] == "causal_contract_difference" for row in trigger_rows) == 4
    with (csv_directory / "harness_reflection_outcome_comparisons.csv").open(
        encoding="utf-8",
        newline="",
    ) as handle:
        stress_rows = list(csv.DictReader(handle))
    assert len(stress_rows) == 15
    assert (
        sum(row["comparison_arm"] == "no_observed_outcome_reflection" for row in stress_rows) == 5
    )
    with (csv_directory / "routing_policy_holdout_categories.csv").open(
        encoding="utf-8",
        newline="",
    ) as handle:
        holdout_rows = list(csv.DictReader(handle))
    assert sum(int(row["case_count"]) for row in holdout_rows) == 16
    assert all(float(row["pass_rate"]) == 1.0 for row in holdout_rows)
