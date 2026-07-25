from __future__ import annotations

from fastapi.testclient import TestClient

from app.parameters import CATALOG_VERSION


def _advanced_job_payload() -> dict[str, object]:
    return {
        "display_name": "PX4 x500 robust tune",
        "optimizer_strategy": "cma_es",
        "vehicle_profile": {
            "px4_version": "v1.16",
            "firmware_commit": "a1b2c3d4",
            "vehicle_type": "multicopter",
            "airframe": "x500",
            "simulator_model": "gz_x500",
            "world": "windy_test_world",
            "headless": False,
            "simulation_speed_factor": 2.5,
            "instance_id": 7,
        },
        "parameter_catalog_version": "px4-v1.16",
        "parameter_space": [
            {
                "name": "MPC_XY_P",
                "baseline": 0.95,
                "minimum": 0.6,
                "maximum": 1.3,
                "step": 0.1,
            },
            {
                "name": "MPC_TILTMAX_AIR",
                "baseline": 45,
                "minimum": 25,
                "maximum": 60,
                "step": 1,
                "value_type": "integer",
            },
        ],
        "objective_config": {
            "objectives": [
                {
                    "metric": "rmse",
                    "direction": "minimize",
                    "weight": 0.7,
                    "normalization": 1.0,
                },
                {
                    "metric": "completion_time",
                    "direction": "minimize",
                    "weight": 0.3,
                    "normalization": 30.0,
                },
            ],
            "constraints": [
                {
                    "metric": "crash_flag",
                    "operator": "lte",
                    "threshold": 0,
                    "hard": True,
                }
            ],
            "robust_aggregation": "cvar",
            "cvar_alpha": 0.25,
        },
        "scenario_suite": {
            "common_random_numbers": True,
            "cases": [
                {
                    "id": "nominal-a",
                    "scenario_type": "nominal",
                    "seeds": [101, 102],
                    "weight": 1,
                },
                {
                    "id": "wind-holdout",
                    "scenario_type": "wind_perturbed",
                    "seeds": [901],
                    "weight": 2,
                    "holdout": True,
                    "config": {"wind_mps": 8},
                },
            ],
        },
    }


def test_advanced_experiment_round_trips_and_reruns(client: TestClient) -> None:
    created_response = client.post("/api/v1/jobs", json=_advanced_job_payload())
    assert created_response.status_code == 200, created_response.text
    created = created_response.json()["data"]
    assert created["parameter_catalog_version"] == CATALOG_VERSION
    assert [item["name"] for item in created["parameter_space"]] == [
        "MPC_XY_P",
        "MPC_TILTMAX_AIR",
    ]
    assert created["objective_config"]["robust_aggregation"] == "cvar"
    assert created["scenario_suite"]["cases"][1]["holdout"] is True
    assert created["vehicle_profile"]["firmware_commit"] == "a1b2c3d4"
    assert created["vehicle_profile"]["headless"] is False
    assert created["vehicle_profile"]["simulation_speed_factor"] == 2.5
    assert created["vehicle_profile"]["instance_id"] == 7

    detail = client.get(f"/api/v1/jobs/{created['id']}").json()["data"]
    assert detail["parameter_space"] == created["parameter_space"]
    assert detail["scenario_suite"] == created["scenario_suite"]
    contract_event = next(
        event
        for event in detail["recent_events"]
        if event["event_type"] == "optimization_outcome_contract_compiled"
    )
    contract = contract_event["payload"]
    assert contract["schema_id"] == "dronedream.optimization-outcome/v1"
    assert contract["contract_id"].startswith("sha256:")
    assert contract["domain_failure_policy"] == {
        "failed_trial_treatment": "separate_rate_penalty",
        "failed_trial_weight_decimal": "1.5",
        "optimizer_learning_failure_rate_operator": "lt",
        "optimizer_learning_failure_rate_limit_decimal": "0.5",
        "hard_constraint_penalty_in_scalar_loss": False,
        "soft_constraint_penalty_in_scalar_loss": True,
    }

    history_response = client.get(f"/api/v1/jobs/{created['id']}/candidates")
    assert history_response.status_code == 200, history_response.text
    assert history_response.json()["data"] == {
        "items": [],
        "pareto_candidate_ids": [],
        "recommendations": {},
        "objective_directions": {"rmse": "minimize", "completion_time": "minimize"},
    }

    rerun_response = client.post(f"/api/v1/jobs/{created['id']}/rerun", json={})
    assert rerun_response.status_code == 200, rerun_response.text
    rerun = rerun_response.json()["data"]
    assert rerun["source_job_id"] == created["id"]
    assert rerun["parameter_space"] == created["parameter_space"]
    assert rerun["objective_config"] == created["objective_config"]
    assert rerun["scenario_suite"] == created["scenario_suite"]
    assert rerun["vehicle_profile"] == created["vehicle_profile"]
    rerun_detail = client.get(f"/api/v1/jobs/{rerun['id']}").json()["data"]
    rerun_contract = next(
        event["payload"]
        for event in rerun_detail["recent_events"]
        if event["event_type"] == "optimization_outcome_contract_compiled"
    )
    assert rerun_contract["contract_id"] == contract["contract_id"]


def test_legacy_job_receives_safe_advanced_defaults(client: TestClient) -> None:
    response = client.post(
        "/api/v1/jobs",
        json={"optimizer_strategy": "heuristic", "simulator_backend": "mock"},
    )
    assert response.status_code == 200, response.text
    job = response.json()["data"]
    assert job["parameter_space"] == []
    assert job["parameter_catalog_version"] == CATALOG_VERSION
    assert job["vehicle_profile"]["airframe"] == "x500"
    assert [case["scenario_type"] for case in job["scenario_suite"]["cases"]] == [
        "nominal",
        "noise_perturbed",
        "wind_perturbed",
        "combined_perturbed",
    ]


def test_job_create_revalidates_parameter_catalog_server_side(client: TestClient) -> None:
    payload = _advanced_job_payload()
    payload["parameter_space"] = [
        {
            "name": "MPC_XY_P",
            "baseline": 0.5,
            "minimum": 0.2,
            "maximum": 1.3,
            "step": 0.1,
        }
    ]
    response = client.post("/api/v1/jobs", json=payload)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "INVALID_PARAMETER_SPACE"
