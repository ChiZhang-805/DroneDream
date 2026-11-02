from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from app.orchestration.cognitive_budget_ablation import (
    ARMS,
    build_cognitive_budget_ablation_artifact,
    build_cognitive_budget_ablation_manifest,
    verify_cognitive_budget_ablation_artifact,
    verify_cognitive_budget_ablation_manifest,
)
from scripts.evaluate_cognitive_budget_ablations import (
    render_cognitive_budget_ablation_files,
    write_cognitive_budget_ablation_files,
)

BACKEND_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = BACKEND_ROOT / "scripts" / "evaluate_cognitive_budget_ablations.py"


def test_fixed_budget_ablation_exercises_production_triggers_without_online_claims() -> None:
    artifact = build_cognitive_budget_ablation_artifact()

    assert artifact["claim_label"] == "SYNTHETIC_FIXED_BUDGET"
    assert artifact["real_provider_calls"] == 0
    assert artifact["network_calls"] == 0
    assert artifact["simulator_runs"] == 0
    assert artifact["real_credentials_used"] is False
    assert artifact["optimizer_quality_claim_permitted"] is False
    assert artifact["general_model_benefit_claim_permitted"] is False
    assert artifact["summary"]["fixed_budget_equal_across_arms"] is True
    assert artifact["summary"]["trigger_confusion"] == {
        "tp": 7,
        "fp": 0,
        "tn": 4,
        "fn": 0,
    }
    assert artifact["summary"]["trigger_precision"] == 1.0
    assert artifact["summary"]["trigger_false_positive_rate"] == 0.0
    assert all(
        case["trigger"]["holdout_outcomes_visible"] is False
        for case in artifact["case_rows"]
    )


def test_all_arms_share_maximum_simulation_budget_and_report_pareto_coordinates() -> None:
    manifest = build_cognitive_budget_ablation_manifest()
    artifact = build_cognitive_budget_ablation_artifact()

    assert manifest["arms"] == list(ARMS)
    assert manifest["fixed_budget"] == {
        "generation_cap": 4,
        "provider_retries": 0,
        "simulation_cap": 24,
        "trial_cap": 24,
        "trials_per_generation": 6,
    }
    summaries = artifact["summary"]["arm_summaries"]
    assert [row["arm"] for row in summaries] == list(ARMS)
    assert all(row["case_count"] == 11 for row in summaries)
    assert all(row["total_consumed_simulations"] <= 11 * 24 for row in summaries)
    assert all(row["median_time_to_first_qualified_ms"] is not None for row in summaries)
    assert all(row["median_simulations_to_first_qualified"] is not None for row in summaries)
    assert all(row["median_provider_turns_to_first_qualified"] is not None for row in summaries)


def test_default_stop_and_negative_result_semantics_are_preserved() -> None:
    artifact = build_cognitive_budget_ablation_artifact()
    cases = {row["case_id"]: row for row in artifact["case_rows"]}

    direct = cases["direct_first_turn_stop"]
    adaptive = next(
        row for row in direct["arms"] if row["arm"] == "adaptive_two_to_four_turn"
    )
    assert adaptive["qualified"] is True
    assert adaptive["simulated_provider_turns_attempted"] == 1

    negative = cases["no_validated_winner_under_frozen_budget"]
    assert all(row["qualified"] is False for row in negative["arms"])
    assert all(row["terminal_result"] == "no_validated_winner" for row in negative["arms"])
    assert all(row["time_to_first_qualified_ms"] is None for row in negative["arms"])


def test_cooldown_and_severity_escalation_are_both_frozen() -> None:
    artifact = build_cognitive_budget_ablation_artifact()
    cases = {row["case_id"]: row for row in artifact["case_rows"]}

    cooled = cases["cooldown_suppresses_duplicate_stagnation"]["trigger"]
    assert cooled["optional_turn_triggered"] is False
    assert cooled["suppressed_by_cooldown"] == ["trailing_stagnation"]
    escalated = cases["severity_escalation_over_cooldown"]["trigger"]
    assert escalated["optional_turn_triggered"] is True
    assert escalated["critic_reasons"] == ["hard_boundary_candidate"]


def test_manifest_and_artifact_reject_tamper() -> None:
    manifest = build_cognitive_budget_ablation_manifest()
    artifact = build_cognitive_budget_ablation_artifact()
    assert verify_cognitive_budget_ablation_manifest(manifest) == manifest
    assert verify_cognitive_budget_ablation_artifact(artifact, manifest=manifest) == artifact

    artifact["summary"]["case_count"] += 1
    with pytest.raises(ValueError, match="hash does not recompute"):
        verify_cognitive_budget_ablation_artifact(artifact)


def test_render_and_cli_outputs_are_byte_reproducible(tmp_path: Path) -> None:
    manifest = build_cognitive_budget_ablation_manifest()
    artifact = build_cognitive_budget_ablation_artifact()
    rendered = render_cognitive_budget_ablation_files(
        artifact,
        manifest,
        json_name="artifact.json",
        csv_name="artifact.csv",
        manifest_name="manifest.json",
    )
    outputs = {
        "--json-output": tmp_path / "artifact.json",
        "--csv-output": tmp_path / "artifact.csv",
        "--manifest-output": tmp_path / "manifest.json",
        "--sha256-output": tmp_path / "artifact.sha256",
    }
    command = [sys.executable, str(SCRIPT)]
    for option, path in outputs.items():
        command.extend((option, str(path)))
    result = subprocess.run(
        command,
        cwd=BACKEND_ROOT.parent,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["artifact_sha256"] == artifact["artifact_sha256"]
    assert outputs["--json-output"].read_bytes() == rendered[0]
    assert outputs["--csv-output"].read_bytes() == rendered[1]
    assert outputs["--manifest-output"].read_bytes() == rendered[2]
    assert outputs["--sha256-output"].read_bytes() == rendered[3]

    with pytest.raises(FileExistsError):
        write_cognitive_budget_ablation_files(
            json_path=outputs["--json-output"],
            csv_path=outputs["--csv-output"],
            manifest_path=outputs["--manifest-output"],
            sha256_path=outputs["--sha256-output"],
        )
