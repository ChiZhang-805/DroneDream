from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.benchmarking.statistics import (
    BENCHMARK_STATISTICS_CONTRACT_SHA256,
    BenchmarkStatisticalInputV1,
    BenchmarkStatisticalOutputV1,
    BenchmarkStatisticalPreregistrationV1,
    BenchmarkStatisticalRunV1,
    evaluate_benchmark_statistics,
)
from scripts.evaluate_benchmark_statistics import evaluate_file

ARMS = (
    "dronedream_adaptive_1_4/v1",
    "dronedream_fixed_two_turn/v1",
    "optimizer_portfolio/v1",
    "reference_scbo/v1",
    "hebo/v1",
)
PILOT_SCENARIOS = ("hover-mild", "circle")
FINAL_SCENARIOS = ("hover-mild", "circle", "u-turn-wind", "figure-eight-gust")
CAMPAIGN_SHA = "a" * 64
INVENTORY_SHA = "b" * 64


def _terminal_state(phase: str, arm_id: str, scenario_index: int, block_index: int) -> str:
    if phase == "pilot":
        if block_index == 2 and arm_id == "dronedream_adaptive_1_4/v1":
            return "provider_failure"
        if block_index == 2 and arm_id == "optimizer_portfolio/v1":
            return "process_crash"
        return "first_qualified" if (block_index + scenario_index) % 2 == 0 else "budget_exhausted"
    if arm_id == "dronedream_adaptive_1_4/v1":
        return "first_qualified" if block_index % 3 != 0 else "budget_exhausted"
    if arm_id == "optimizer_portfolio/v1":
        return "first_qualified" if block_index % 4 in {1, 2} else "budget_exhausted"
    if arm_id == "reference_scbo/v1" and block_index == 5:
        return "telemetry_invalid"
    return "first_qualified" if (block_index + scenario_index) % 3 == 0 else "budget_exhausted"


def _run(
    *,
    phase: str,
    arm_id: str,
    arm_index: int,
    scenario_id: str,
    scenario_index: int,
    block_id: str,
    block_index: int,
    ordinal: int,
) -> BenchmarkStatisticalRunV1:
    state = _terminal_state(phase, arm_id, scenario_index, block_index)
    llm = arm_id in {
        "dronedream_adaptive_1_4/v1",
        "dronedream_fixed_two_turn/v1",
    }
    attempted = 5 if state == "first_qualified" else 8
    failed_trial = state not in {"first_qualified", "budget_exhausted"}
    logical_attempted = 2 if llm else 0
    logical_failed = 1 if state == "provider_failure" else 0
    logical_succeeded = logical_attempted - logical_failed
    network_attempted = logical_attempted
    network_failed = logical_failed
    network_succeeded = network_attempted - network_failed
    success = state == "first_qualified"
    error_code = (
        None if state in {"first_qualified", "budget_exhausted"} else state.replace("_", "-")
    )
    return BenchmarkStatisticalRunV1(
        run_key=(f"run/{arm_id.replace('/', '-')}/{scenario_id}/{block_id}"),
        run_ordinal=ordinal,
        benchmark_arm_id=arm_id,
        arm_version="1.0.0",
        scenario_id=scenario_id,
        paired_seed_block=block_id,
        algorithm_seed=10_000 + arm_index * 1_000 + scenario_index * 100 + block_index,
        simulator_seed_block=f"crn/{scenario_id}/{block_id}",
        provider_randomness_policy="fixed_seed" if llm else "not_applicable",
        provider_seed=(20_000 + block_index if llm else None),
        campaign_manifest_sha256=CAMPAIGN_SHA,
        composite_execution_inventory_sha256=INVENTORY_SHA,
        terminal_state=state,
        engineering_failure_code=error_code,
        wall_time_ms=1_000 + scenario_index * 100 + block_index * 20 + arm_index * 5,
        disk_bytes=10_000 + block_index * 100,
        trials_attempted=attempted,
        trials_completed=attempted - int(failed_trial),
        trials_failed=int(failed_trial),
        trials_cancelled=0,
        trials_timed_out=0,
        trials_indeterminate=0,
        logical_turns_attempted=logical_attempted,
        logical_turns_succeeded=logical_succeeded,
        logical_turns_failed=logical_failed,
        logical_turns_indeterminate=0,
        network_requests_attempted=network_attempted,
        network_requests_succeeded=network_succeeded,
        network_requests_failed=network_failed,
        network_requests_indeterminate=0,
        provider_input_tokens=120 if llm else 0,
        provider_output_tokens=30 if llm else 0,
        provider_cost_microusd=350 if llm else 0,
        qualification_candidates_attempted=int(success),
        qualification_candidates_passed=int(success),
        holdout_passed=True if success else None,
        safety_critical_failures=0,
        artifact_complete=success,
        receipt_valid=success,
        first_qualified_receipt_sha256="c" * 64 if success else None,
        time_to_first_qualified_ms=(900 + block_index * 10 if success else None),
        trials_to_first_qualified=attempted if success else None,
        logical_turns_to_first_qualified=logical_attempted if success else None,
        network_requests_to_first_qualified=network_attempted if success else None,
        provider_tokens_to_first_qualified=(150 if llm and success else 0 if success else None),
        provider_cost_to_first_qualified_microusd=(
            350 if llm and success else 0 if success else None
        ),
        budget_endpoint_best_validated_error=0.4 if success else None,
    )


def _input(phase: str) -> BenchmarkStatisticalInputV1:
    scenarios = PILOT_SCENARIOS if phase == "pilot" else FINAL_SCENARIOS
    block_count = 4 if phase == "pilot" else 12
    blocks = tuple(f"block-{index + 1:02d}" for index in range(block_count))
    preregistration = BenchmarkStatisticalPreregistrationV1(
        analysis_id=f"panel-a-{phase}",
        analysis_version="1.0.0",
        protocol_sha256="d" * 64,
        campaign_manifest_sha256=CAMPAIGN_SHA,
        phase=phase,
        bootstrap_replicates=200,
        bootstrap_seed=20260805,
        final_block_count=12 if phase == "final" else None,
    )
    runs: list[BenchmarkStatisticalRunV1] = []
    ordinal = 0
    for arm_index, arm_id in enumerate(ARMS):
        for scenario_index, scenario_id in enumerate(scenarios):
            for block_index, block_id in enumerate(blocks):
                ordinal += 1
                runs.append(
                    _run(
                        phase=phase,
                        arm_id=arm_id,
                        arm_index=arm_index,
                        scenario_id=scenario_id,
                        scenario_index=scenario_index,
                        block_id=block_id,
                        block_index=block_index,
                        ordinal=ordinal,
                    )
                )
    return BenchmarkStatisticalInputV1(
        preregistration=preregistration,
        campaign_manifest_sha256=CAMPAIGN_SHA,
        composite_execution_inventory_sha256=INVENTORY_SHA,
        expected_arm_ids=ARMS,
        expected_scenario_ids=scenarios,
        expected_paired_seed_blocks=blocks,
        runs=tuple(runs),
    )


def test_pilot_is_blinded_and_uses_only_pooled_nuisance_estimates() -> None:
    value = _input("pilot")
    result = evaluate_benchmark_statistics(value)

    assert result.phase == "pilot"
    assert result.blinded is True
    assert result.pilot_summary is not None
    assert result.pilot_summary.runs == len(value.runs)
    assert result.pilot_summary.pooled_qualification.denominator == len(value.runs)
    assert result.pilot_summary.terminal_counts["provider_failure"] == 2
    assert result.pilot_summary.terminal_counts["process_crash"] == 2
    assert result.pilot_summary.recommended_final_block_count == 20
    assert result.arm_summaries == ()
    assert result.primary_comparison is None
    assert result.pareto_frontier == ()
    encoded = json.dumps(result.model_dump(mode="json"), sort_keys=True)
    for arm_id in ARMS:
        assert arm_id not in encoded


def test_final_keeps_failures_in_denominators_and_is_deterministic() -> None:
    value = _input("final")
    result = evaluate_benchmark_statistics(value)
    repeated = evaluate_benchmark_statistics(value)

    assert result == repeated
    assert result.statistics_contract_sha256 == BENCHMARK_STATISTICS_CONTRACT_SHA256
    assert result.blinded is False
    assert len(result.arm_summaries) == len(ARMS)
    by_arm = {summary.benchmark_arm_id: summary for summary in result.arm_summaries}
    expected_runs = len(FINAL_SCENARIOS) * 12
    assert all(summary.qualification.denominator == expected_runs for summary in by_arm.values())
    assert by_arm["reference_scbo/v1"].terminal_counts["telemetry_invalid"] == len(FINAL_SCENARIOS)
    scbo_curve = by_arm["reference_scbo/v1"].trials_event_curve
    assert sum(point.competing_events for point in scbo_curve) == len(FINAL_SCENARIOS)
    assert sum(point.right_censored for point in scbo_curve) > 0
    assert result.primary_comparison is not None
    assert result.primary_comparison.qualification_rate_difference.paired_units == 12
    assert result.primary_comparison.primary_arm_id == "dronedream_adaptive_1_4/v1"
    assert result.primary_comparison.comparator_arm_id == "optimizer_portfolio/v1"
    assert by_arm["dronedream_adaptive_1_4/v1"].median_provider_tokens == 150
    assert by_arm["dronedream_adaptive_1_4/v1"].iqr_provider_tokens == 0


def test_incomplete_grid_and_crn_drift_fail_closed() -> None:
    value = _input("pilot")
    payload = value.model_dump(mode="json")
    payload["runs"].pop()
    with pytest.raises(ValidationError, match="paired run grid is incomplete"):
        BenchmarkStatisticalInputV1.model_validate(payload)

    payload = value.model_dump(mode="json")
    payload["runs"][0]["simulator_seed_block"] = "crn/drifted"
    with pytest.raises(ValidationError, match="same simulator CRN block"):
        BenchmarkStatisticalInputV1.model_validate(payload)

    payload = value.model_dump(mode="json")
    payload["runs"][0]["arm_version"] = "drifted"
    with pytest.raises(ValidationError, match="arm version drifted"):
        BenchmarkStatisticalInputV1.model_validate(payload)

    payload = value.model_dump(mode="json")
    fixed_two_turn = next(
        run for run in payload["runs"] if run["benchmark_arm_id"] == "dronedream_fixed_two_turn/v1"
    )
    fixed_two_turn["provider_seed"] += 1
    with pytest.raises(ValidationError, match="paired provider seed"):
        BenchmarkStatisticalInputV1.model_validate(payload)


def test_accounting_and_terminal_semantics_cannot_be_beautified() -> None:
    run = _input("pilot").runs[0]
    payload = run.model_dump(mode="json")
    payload["trials_failed"] = 1
    with pytest.raises(ValidationError, match="every attempted Trial"):
        BenchmarkStatisticalRunV1.model_validate(payload)

    payload = run.model_dump(mode="json")
    payload["terminal_state"] = "budget_exhausted"
    with pytest.raises(ValidationError, match="non-qualified run"):
        BenchmarkStatisticalRunV1.model_validate(payload)

    traditional = next(
        candidate
        for candidate in _input("pilot").runs
        if candidate.benchmark_arm_id == "optimizer_portfolio/v1"
    )
    parent = _input("pilot").model_dump(mode="json")
    target = next(
        candidate for candidate in parent["runs"] if candidate["run_key"] == traditional.run_key
    )
    target["network_requests_attempted"] = 1
    target["network_requests_succeeded"] = 1
    with pytest.raises(ValidationError, match="traditional arms cannot consume"):
        BenchmarkStatisticalInputV1.model_validate(parent)


def test_cli_writes_once_and_binds_exact_input_bytes(tmp_path: Path) -> None:
    value = _input("pilot")
    input_path = tmp_path / "input.json"
    output_path = tmp_path / "output.json"
    input_path.write_text(
        json.dumps(value.model_dump(mode="json"), indent=2, sort_keys=True),
        encoding="utf-8",
    )

    summary = evaluate_file(input_path, output_path)
    output = json.loads(output_path.read_text(encoding="utf-8"))
    assert summary["blinded"] is True
    assert output["input_file_sha256"] == hashlib.sha256(input_path.read_bytes()).hexdigest()
    assert output["editable_manual_table"] is False
    BenchmarkStatisticalOutputV1.model_validate(output)
    original = output_path.read_bytes()
    with pytest.raises(FileExistsError, match="refusing to overwrite"):
        evaluate_file(input_path, output_path)
    assert output_path.read_bytes() == original
