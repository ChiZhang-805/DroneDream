from __future__ import annotations

import copy
from pathlib import Path

import pytest

from app.optimization.prefinal_calibrated_scenario_registry import (
    build_prefinal_calibrated_scenario_registry,
    verify_prefinal_calibrated_scenario_registry,
)
from app.optimization.prefinal_scenario_registry import build_prefinal_scenario_registry
from app.schemas import JobCreateRequest
from scripts.freeze_prefinal_calibrated_scenario_registry import (
    write_prefinal_calibrated_scenario_registry_files,
)


def _by_id(registry: dict) -> dict[str, dict]:
    return {problem["problem_id"]: problem for problem in registry["problems"]}


def test_v2_preserves_v1_problem_order_budgets_seeds_and_arms() -> None:
    before = build_prefinal_scenario_registry()
    after = build_prefinal_calibrated_scenario_registry()

    assert after["status"] == "baseline_calibration_in_progress"
    assert after["report_eligible"] is False
    assert after["problem_count"] == before["problem_count"] == 18
    assert after["budget"] == before["budget"]
    assert after["arms"] == before["arms"]
    assert [item["problem_id"] for item in after["problems"]] == [
        item["problem_id"] for item in before["problems"]
    ]
    for prior, revised in zip(before["problems"], after["problems"], strict=True):
        assert (
            revised["job_template"]["scenario_suite"]
            == prior["job_template"]["scenario_suite"]
        )


def test_v2_removes_only_prearm_gnss_noise_and_retains_other_stressors() -> None:
    registry = build_prefinal_calibrated_scenario_registry()
    problems = _by_id(registry)
    revised_ids = {
        "representative-hover-sensor-noise",
        "representative-lemniscate-sensor-noise",
        "representative-circle-wind-noise",
        "hard-lemniscate-gust-noise",
        "hard-hover-wind-dropout",
    }

    assert {entry["problem_id"] for entry in registry["calibration_audit_log"]} == revised_ids
    for problem_id in revised_ids:
        problem = problems[problem_id]
        sensor = problem["job_template"]["advanced_scenario_config"][
            "sensor_degradation"
        ]
        assert sensor["gps_noise_m"] == 0.0
        assert sensor["baro_noise_m"] > 0.0
        assert sensor["imu_noise_scale"] > 1.0
        JobCreateRequest.model_validate(problem["job_template"])
        effect_ids = {
            effect_id
            for contract in problem["physical_effect_contracts"]
            for effect_id in contract["effect_ids"]
        }
        assert "sensor_degradation.gps_noise_m" not in effect_ids
        assert "job_config.sensor_noise_level" in effect_ids

    hard = problems["hard-hover-wind-dropout"]["job_template"]
    assert hard["wind"]["north"] == 3.5
    assert hard["advanced_scenario_config"]["sensor_degradation"]["dropout_rate"] == 0.04


def test_v2_hash_and_non_overwriting_writer_are_deterministic(tmp_path: Path) -> None:
    registry = build_prefinal_calibrated_scenario_registry()
    assert verify_prefinal_calibrated_scenario_registry(registry)
    tampered = copy.deepcopy(registry)
    tampered["calibration_audit_log"][0]["after"] = 0.1
    assert not verify_prefinal_calibrated_scenario_registry(tampered)

    paths = {
        "json_path": tmp_path / "registry-v2.json",
        "csv_path": tmp_path / "registry-v2.csv",
        "manifest_path": tmp_path / "registry-v2.manifest.json",
        "sha256_path": tmp_path / "registry-v2.sha256",
    }
    write_prefinal_calibrated_scenario_registry_files(**paths)
    write_prefinal_calibrated_scenario_registry_files(**paths, check=True)
    with pytest.raises(FileExistsError):
        write_prefinal_calibrated_scenario_registry_files(**paths)
