from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from scripts.export_technical_report_evidence import (
    build_report_evidence_bundle,
    summarize_simulation_coverage,
    write_report_evidence_bundle,
)


def test_report_evidence_bundle_recomputes_frozen_metrics() -> None:
    first = build_report_evidence_bundle()
    second = build_report_evidence_bundle()

    assert first == second
    assert len(first["bundle_sha256"]) == 64

    routing = first["routing"]
    assert routing["evidence_class"] == "development_routing_corpus"
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
    assert all(
        row["selected_holdout_loss"] < row["baseline_holdout_loss"]
        for row in coverage["scenario_rows"]
    )


def test_report_evidence_refuses_to_upgrade_mock_to_physical() -> None:
    source = (
        Path(__file__).resolve().parents[1]
        / "evaluation_artifacts"
        / "simulation-coverage-mock-v2.json"
    )
    payload = json.loads(source.read_text(encoding="utf-8"))
    payload["physical_fidelity"] = True

    with pytest.raises(ValueError, match="must remain non-physical"):
        summarize_simulation_coverage(payload)


def test_report_evidence_refuses_inconsistent_improvement() -> None:
    source = (
        Path(__file__).resolve().parents[1]
        / "evaluation_artifacts"
        / "simulation-coverage-mock-v2.json"
    )
    payload = json.loads(source.read_text(encoding="utf-8"))
    payload["baseline_to_selected_improvement_rate"] = 0.99

    with pytest.raises(ValueError, match="does not recompute"):
        summarize_simulation_coverage(payload)


def test_report_evidence_writes_chart_ready_csv(tmp_path: Path) -> None:
    bundle = build_report_evidence_bundle()
    output_path = tmp_path / "evidence.json"
    csv_directory = tmp_path / "csv"

    write_report_evidence_bundle(
        bundle,
        output_path=output_path,
        csv_directory=csv_directory,
    )

    assert json.loads(output_path.read_text(encoding="utf-8")) == bundle
    with (csv_directory / "synthetic_scenario_holdout.csv").open(
        encoding="utf-8",
        newline="",
    ) as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 10
    assert {row["scenario"] for row in rows} == {
        row["scenario"] for row in bundle["simulation_coverage"]["scenario_rows"]
    }
