from __future__ import annotations


def test_parameter_catalog_lists_versioned_bilingual_entries(client) -> None:
    response = client.get("/api/v1/parameter-catalog", params={"px4_version": "v1.17"})

    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["catalog_version"].startswith("dronedream.px4.multicopter.")
    assert payload["px4_version"] == "v1.17"
    assert payload["parameter_count"] == 28
    assert {group["id"] for group in payload["groups"]} == {
        "xy_position_velocity",
        "z_position_velocity",
        "attitude",
        "angular_rate",
        "filters",
        "motion_limits",
    }
    xy_p = next(item for item in payload["parameters"] if item["name"] == "MPC_XY_P")
    assert xy_p["type"] == "float"
    assert xy_p["hard_bounds"] == {"min": 0.0, "max": 2.0}
    assert xy_p["safe_bounds"] == {"min": 0.6, "max": 1.3}
    assert xy_p["label"]["en"]
    assert xy_p["label"]["zh-CN"]
    assert xy_p["description"]["en"]
    assert xy_p["description"]["zh-CN"]
    assert xy_p["dependencies"][0]["parameter"] == "MPC_XY_VEL_P_ACC"


def test_parameter_catalog_can_filter_group_and_read_one_entry(client) -> None:
    response = client.get(
        "/api/v1/parameter-catalog",
        params={"group": "angular_rate", "px4_version": "1.16.2"},
    )
    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["px4_version"] == "v1.16"
    assert payload["parameter_count"] == 8
    assert {item["group"] for item in payload["parameters"]} == {"angular_rate"}

    detail = client.get("/api/v1/parameter-catalog/MC_ROLLRATE_P")
    assert detail.status_code == 200
    assert detail.json()["data"]["parameter"]["name"] == "MC_ROLLRATE_P"


def test_parameter_catalog_rejects_unknown_version_group_and_parameter(client) -> None:
    version = client.get("/api/v1/parameter-catalog", params={"px4_version": "v1.15"})
    assert version.status_code == 400
    assert version.json()["error"]["code"] == "INVALID_PARAMETER_CATALOG_REQUEST"

    group = client.get("/api/v1/parameter-catalog", params={"group": "not-real"})
    assert group.status_code == 400

    parameter = client.get("/api/v1/parameter-catalog/NOT_A_PX4_PARAMETER")
    assert parameter.status_code == 404
    assert parameter.json()["error"]["code"] == "PARAMETER_NOT_FOUND"


def test_validate_endpoint_accepts_job_parameter_space_contract(client) -> None:
    response = client.post(
        "/api/v1/parameter-catalog/validate",
        json={
            "px4_version": "main",
            "selections": [
                {
                    "name": "MC_ROLL_P",
                    "baseline": 4.0,
                    "minimum": 2.0,
                    "maximum": 6.0,
                    "step": 0.1,
                    "scale": "linear",
                    "value_type": "float",
                    "choices": None,
                    "enabled": True,
                    "locked": False,
                },
                {
                    "name": "MC_PITCH_P",
                    "baseline": 4.0,
                    "minimum": 2.0,
                    "maximum": 6.0,
                    "step": 0.1,
                    "scale": "linear",
                    "value_type": "float",
                    "choices": None,
                    "enabled": False,
                    "locked": False,
                },
            ],
        },
    )

    assert response.status_code == 200
    result = response.json()["data"]
    assert result["valid"] is True
    assert result["normalized"] == [
        {
            "name": "MC_ROLL_P",
            "search_min": 2.0,
            "search_max": 6.0,
            "initial_value": 4.0,
        }
    ]
    assert result["ignored"] == [{"name": "MC_PITCH_P", "reason": "disabled"}]
    assert any(
        warning["code"] == "RECOMMENDED_PARAMETER_NOT_SELECTED" for warning in result["warnings"]
    )


def test_validate_endpoint_reports_safe_hard_and_duplicate_errors(client) -> None:
    outside_safe = client.post(
        "/api/v1/parameter-catalog/validate",
        json={
            "selections": [
                {
                    "name": "MPC_XY_VEL_I_ACC",
                    "search_min": 0.2,
                    "search_max": 5.0,
                    "initial_value": 0.4,
                }
            ]
        },
    ).json()["data"]
    assert outside_safe["valid"] is False
    assert outside_safe["errors"][0]["code"] == "OUTSIDE_SAFE_BOUNDS"

    warning_only = client.post(
        "/api/v1/parameter-catalog/validate",
        json={
            "enforce_safe_bounds": False,
            "selections": [
                {
                    "name": "MPC_XY_VEL_I_ACC",
                    "search_min": 0.2,
                    "search_max": 5.0,
                    "initial_value": 0.4,
                }
            ],
        },
    ).json()["data"]
    assert warning_only["valid"] is True
    assert warning_only["warnings"][0]["code"] == "OUTSIDE_SAFE_BOUNDS"

    bad = client.post(
        "/api/v1/parameter-catalog/validate",
        json={
            "enforce_safe_bounds": False,
            "selections": [
                {"name": "MPC_XY_P", "search_min": -1.0, "search_max": 1.0},
                {"name": "MPC_XY_P", "search_min": 0.7, "search_max": 1.2},
            ],
        },
    ).json()["data"]
    assert bad["valid"] is False
    assert {error["code"] for error in bad["errors"]} == {
        "OUTSIDE_HARD_BOUNDS",
        "DUPLICATE_PARAMETER",
    }

    bad_step = client.post(
        "/api/v1/parameter-catalog/validate",
        json={
            "selections": [
                {
                    "name": "MPC_XY_P",
                    "minimum": 0.7,
                    "maximum": 1.2,
                    "baseline": 0.95,
                    "step": 1.0,
                    "value_type": "float",
                }
            ]
        },
    ).json()["data"]
    assert bad_step["valid"] is False
    assert bad_step["errors"][0]["code"] == "STEP_EXCEEDS_RANGE"
