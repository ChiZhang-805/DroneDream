from __future__ import annotations

import pytest

from app.parameters import (
    CATALOG_VERSION,
    ParameterValueValidationError,
    get_parameter,
    list_presets,
    validate_parameter_values,
    validate_search_selections,
)


def test_parameter_catalog_lists_versioned_bilingual_entries(client) -> None:
    response = client.get("/api/v1/parameter-catalog", params={"px4_version": "v1.17"})

    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["catalog_version"].startswith("dronedream.px4.multicopter.")
    assert payload["px4_version"] == "v1.17"
    assert payload["parameter_count"] == 45
    assert payload["total_parameter_count"] == 45
    assert {group["id"] for group in payload["groups"]} == {
        "xy_position_velocity",
        "z_position_velocity",
        "attitude",
        "angular_rate",
        "filters",
        "thrust_and_authority",
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
    assert xy_p["control_loop"] == "horizontal_position"
    assert xy_p["axes"] == ["x", "y"]
    assert xy_p["compatibility"]["px4_versions"] == ["v1.16", "v1.17", "main"]
    assert xy_p["application_interfaces"] == ["mavsdk", "px4_startup_env"]
    assert set(xy_p["recommended_metrics"]) <= set(payload["supported_trial_metrics"])
    assert xy_p["evidence_signals"]
    assert xy_p["apply_policy"] == "live"
    assert payload["presets"]
    assert payload["catalog_version"] == CATALOG_VERSION


def test_parameter_catalog_can_filter_group_and_read_one_entry(client) -> None:
    response = client.get(
        "/api/v1/parameter-catalog",
        params={"group": "angular_rate", "px4_version": "1.16.2"},
    )
    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["px4_version"] == "v1.16"
    assert payload["parameter_count"] == 18
    assert {item["group"] for item in payload["parameters"]} == {"angular_rate"}

    detail = client.get("/api/v1/parameter-catalog/MC_ROLLRATE_P")
    assert detail.status_code == 200
    assert detail.json()["data"]["parameter"]["name"] == "MC_ROLLRATE_P"
    assert detail.json()["data"]["parameter"]["apply_policy"] == "disarmed"

    release_filter = client.get(
        "/api/v1/parameter-catalog/IMU_DGYRO_CUTOFF",
        params={"px4_version": "v1.16"},
    ).json()["data"]["parameter"]
    main_filter = client.get(
        "/api/v1/parameter-catalog/IMU_DGYRO_CUTOFF",
        params={"px4_version": "main"},
    ).json()["data"]["parameter"]
    assert release_filter["default"] == 30.0
    assert main_filter["default"] == 20.0
    assert release_filter["apply_policy"] == "reboot"
    assert "/v1.16/" in release_filter["source_url"]
    assert "/main/" in main_filter["source_url"]

    release_yaw_k = client.get(
        "/api/v1/parameter-catalog/MC_YAWRATE_K",
        params={"px4_version": "v1.16"},
    ).json()["data"]["parameter"]
    main_yaw_k = client.get(
        "/api/v1/parameter-catalog/MC_YAWRATE_K",
        params={"px4_version": "main"},
    ).json()["data"]["parameter"]
    assert release_yaw_k["hard_bounds"]["min"] == 0.0
    assert main_yaw_k["hard_bounds"]["min"] == 0.01

    release_yaw_d = client.get(
        "/api/v1/parameter-catalog/MC_YAWRATE_D",
        params={"px4_version": "v1.16"},
    ).json()["data"]["parameter"]
    main_yaw_d = client.get(
        "/api/v1/parameter-catalog/MC_YAWRATE_D",
        params={"px4_version": "main"},
    ).json()["data"]["parameter"]
    assert release_yaw_d["step"] == 0.01
    assert main_yaw_d["step"] == 0.0005


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


def test_catalog_filters_by_control_loop_axis_risk_and_vehicle_context(client) -> None:
    response = client.get(
        "/api/v1/parameter-catalog",
        params={
            "px4_version": "v1.17.3",
            "vehicle_type": "multirotor",
            "airframe": "gz_x500_depth",
            "control_loop": "angular_rate",
            "axis": "roll",
            "risk": "high",
        },
    )
    assert response.status_code == 200, response.text
    payload = response.json()["data"]
    assert payload["vehicle_type"] == "multicopter"
    assert payload["airframe_family"] == "quadrotor"
    assert {item["name"] for item in payload["parameters"]} == {
        "MC_ROLLRATE_P",
        "MC_ROLLRATE_I",
        "MC_ROLLRATE_D",
        "MC_ROLLRATE_K",
        "MC_ROLLRATE_FF",
    }

    incompatible = client.get(
        "/api/v1/parameter-catalog",
        params={"vehicle_type": "fixed_wing"},
    )
    assert incompatible.status_code == 400
    assert incompatible.json()["error"]["code"] == "INVALID_PARAMETER_CATALOG_REQUEST"


def test_catalog_exposes_ordered_integral_workflow_presets(client) -> None:
    catalog = client.get("/api/v1/parameter-catalog").json()["data"]
    response = client.get(
        "/api/v1/parameter-catalog/presets",
        params={"px4_version": "v1.16", "airframe": "quad_x"},
    )
    assert response.status_code == 200, response.text
    payload = response.json()["data"]
    assert payload["preset_count"] == 8
    presets = payload["presets"]
    assert [item["order"] for item in presets] == sorted(item["order"] for item in presets)
    assert presets[0]["id"] == "rate_roll_pitch"
    assert presets[0]["locked_parameters"] == ["MC_ROLLRATE_K", "MC_PITCHRATE_K"]
    available = {item["name"] for item in catalog["parameters"]}
    assert all(set(item["parameter_names"]) <= available for item in presets)
    assert all(set(item["metrics"]) <= set(payload["supported_trial_metrics"]) for item in presets)
    assert all(item["evidence_signals"] for item in presets)
    assert {item["id"] for item in payload["preconditions"]} >= {
        "rate_loop_validated",
        "attitude_loop_validated",
    }


def test_every_preset_has_a_constraint_safe_default_search_space() -> None:
    for preset in list_presets(px4_version="main", airframe="x500"):
        selections = []
        for name in preset.parameter_names:
            parameter = get_parameter(name, px4_version="main", airframe="x500")
            assert parameter is not None
            selections.append(
                {
                    "name": name,
                    "search_min": parameter.safe_bounds.minimum,
                    "search_max": parameter.safe_bounds.maximum,
                    "initial_value": parameter.default,
                    "step": parameter.step,
                }
            )
        result = validate_search_selections(selections, px4_version="main", airframe="x500")
        assert result.valid, (preset.id, result.errors)
        assert "DEPENDENCY_RANGE_MAY_VIOLATE" not in {
            warning.code for warning in result.warnings
        }, preset.id


def test_catalog_version_is_explicit_and_px4_specific_aliases_cannot_drift(client) -> None:
    accepted = client.post(
        "/api/v1/parameter-catalog/validate",
        json={
            "catalog_version": "builtin-v1",
            "px4_version": "v1.17",
            "selections": [
                {
                    "name": "MPC_XY_P",
                    "search_min": 0.7,
                    "search_max": 1.2,
                    "initial_value": 0.95,
                }
            ],
        },
    )
    assert accepted.status_code == 200
    accepted_data = accepted.json()["data"]
    assert accepted_data["valid"] is True
    assert accepted_data["requested_catalog_version"] == "builtin-v1"
    assert accepted_data["catalog_version"] == CATALOG_VERSION

    unknown = client.post(
        "/api/v1/parameter-catalog/validate",
        json={
            "catalog_version": "latest-whatever-is-installed",
            "selections": [{"name": "MPC_XY_P", "search_min": 0.7, "search_max": 1.2}],
        },
    )
    assert unknown.status_code == 400

    mismatch = client.post(
        "/api/v1/parameter-catalog/validate",
        json={
            "catalog_version": "px4-v1.16",
            "px4_version": "v1.17",
            "selections": [{"name": "MPC_XY_P", "search_min": 0.7, "search_max": 1.2}],
        },
    )
    assert mismatch.status_code == 400
    assert "targets v1.16" in mismatch.json()["error"]["message"]


def test_job_create_rejects_unknown_catalog_mismatch_and_incompatible_vehicle(client) -> None:
    unknown = client.post(
        "/api/v1/jobs",
        json={"parameter_catalog_version": "user-supplied-catalog"},
    )
    assert unknown.status_code == 422
    assert unknown.json()["error"]["code"] == "UNSUPPORTED_PARAMETER_CATALOG"

    mismatch = client.post(
        "/api/v1/jobs",
        json={
            "parameter_catalog_version": "px4-v1.16",
            "vehicle_profile": {"px4_version": "v1.17"},
        },
    )
    assert mismatch.status_code == 422
    assert mismatch.json()["error"]["code"] == "UNSUPPORTED_PARAMETER_CATALOG"

    vehicle = client.post(
        "/api/v1/jobs",
        json={"vehicle_profile": {"vehicle_type": "fixed_wing"}},
    )
    assert vehicle.status_code == 422
    assert vehicle.json()["error"]["code"] == "UNSUPPORTED_VEHICLE_TYPE"

    disabled_unknown = client.post(
        "/api/v1/jobs",
        json={
            "parameter_space": [
                {
                    "name": "MPC_XY_P",
                    "baseline": 0.95,
                    "minimum": 0.7,
                    "maximum": 1.2,
                },
                {
                    "name": "NOT_A_REAL_PX4_PARAM",
                    "baseline": 1.0,
                    "minimum": 0.0,
                    "maximum": 2.0,
                    "enabled": False,
                },
            ]
        },
    )
    assert disabled_unknown.status_code == 422
    assert disabled_unknown.json()["error"]["code"] == "INVALID_PARAMETER_SPACE"


def test_cross_parameter_constraints_are_executable_not_only_metadata(client) -> None:
    with pytest.raises(ParameterValueValidationError) as exc_info:
        validate_parameter_values(
            {"MPC_THR_MIN": 0.4, "MPC_THR_HOVER": 0.3},
            enforce_safe_bounds=False,
        )
    assert {issue.code for issue in exc_info.value.issues} == {"DEPENDENCY_VIOLATION"}

    impossible = client.post(
        "/api/v1/parameter-catalog/validate",
        json={
            "enforce_safe_bounds": False,
            "selections": [
                {
                    "name": "MPC_THR_MIN",
                    "search_min": 0.4,
                    "search_max": 0.5,
                    "initial_value": 0.45,
                },
                {
                    "name": "MPC_THR_HOVER",
                    "search_min": 0.1,
                    "search_max": 0.3,
                    "initial_value": 0.2,
                },
            ],
        },
    ).json()["data"]
    assert impossible["valid"] is False
    assert "DEPENDENCY_RANGE_VIOLATION" in {issue["code"] for issue in impossible["errors"]}

    overlap = client.post(
        "/api/v1/parameter-catalog/validate",
        json={
            "selections": [
                {
                    "name": "MPC_THR_MIN",
                    "search_min": 0.1,
                    "search_max": 0.2,
                    "initial_value": 0.12,
                },
                {
                    "name": "MPC_THR_HOVER",
                    "search_min": 0.25,
                    "search_max": 0.5,
                    "initial_value": 0.4,
                },
                {
                    "name": "MPC_THR_MAX",
                    "search_min": 0.8,
                    "search_max": 0.8,
                    "initial_value": 0.8,
                    "locked": True,
                },
            ],
        },
    ).json()["data"]
    assert overlap["valid"] is True
    assert "DEPENDENCY_RANGE_MAY_VIOLATE" not in {issue["code"] for issue in overlap["warnings"]}

    incomplete_range = client.post(
        "/api/v1/parameter-catalog/validate",
        json={
            "selections": [
                {
                    "name": "MPC_THR_MIN",
                    "search_max": 0.3,
                    "initial_value": 0.2,
                },
                {
                    "name": "MPC_THR_HOVER",
                    "initial_value": 0.5,
                    "locked": True,
                },
            ]
        },
    )
    assert incomplete_range.status_code == 422
    assert incomplete_range.json()["error"]["code"] == "INVALID_INPUT"

    missing_for_preview = client.post(
        "/api/v1/parameter-catalog/validate",
        json={
            "selections": [
                {
                    "name": "MPC_ACC_HOR",
                    "search_min": 2,
                    "search_max": 5,
                    "initial_value": 3,
                    "step": 1,
                }
            ]
        },
    ).json()["data"]
    assert missing_for_preview["valid"] is False
    missing_issue = next(
        issue
        for issue in missing_for_preview["errors"]
        if issue["code"] == "CONSTRAINT_PARAMETER_NOT_SELECTED"
    )
    assert missing_issue["related_parameter"] == "MPC_ACC_HOR_MAX"

    locked_companion = client.post(
        "/api/v1/parameter-catalog/validate",
        json={
            "selections": [
                {
                    "name": "MPC_ACC_HOR",
                    "search_min": 2,
                    "search_max": 5,
                    "initial_value": 3,
                    "step": 1,
                },
                {
                    "name": "MPC_ACC_HOR_MAX",
                    "search_min": 5,
                    "search_max": 5,
                    "initial_value": 5,
                    "locked": True,
                },
            ]
        },
    ).json()["data"]
    assert locked_companion["valid"] is True
    assert locked_companion["ignored"] == [{"name": "MPC_ACC_HOR_MAX", "reason": "locked"}]
    assert "CONSTRAINT_PARAMETER_NOT_SELECTED" not in {
        issue["code"] for issue in locked_companion["warnings"]
    }

    missing_companion = client.post(
        "/api/v1/jobs",
        json={
            "vehicle_profile": {"px4_version": "v1.16"},
            "parameter_catalog_version": "px4-v1.16",
            "parameter_space": [
                {
                    "name": "MPC_ACC_HOR",
                    "baseline": 3,
                    "minimum": 2,
                    "maximum": 8,
                    "step": 1,
                }
            ],
        },
    )
    assert missing_companion.status_code == 422
    assert "MPC_ACC_HOR_MAX" in missing_companion.json()["error"]["message"]


def test_normalized_duplicates_integer_steps_and_empty_active_space_are_rejected(client) -> None:
    with pytest.raises(ParameterValueValidationError) as exc_info:
        validate_parameter_values({"MPC_XY_P": 0.9, " mpc_xy_p ": 1.0})
    assert {issue.code for issue in exc_info.value.issues} == {"DUPLICATE_PARAMETER"}
    with pytest.raises(ParameterValueValidationError, match="JSON number"):
        validate_parameter_values({"MPC_XY_P": "0.9"})

    bad_step = client.post(
        "/api/v1/parameter-catalog/validate",
        json={
            "selections": [
                {
                    "name": "MC_AIRMODE",
                    "search_min": 0,
                    "search_max": 2,
                    "initial_value": 0,
                    "step": 0.5,
                    "value_type": "integer",
                }
            ]
        },
    ).json()["data"]
    assert bad_step["valid"] is False
    assert bad_step["errors"][0]["code"] == "INVALID_STEP_INCREMENT"

    empty = client.post(
        "/api/v1/parameter-catalog/validate",
        json={
            "selections": [
                {
                    "name": "MPC_XY_P",
                    "search_min": 0.7,
                    "search_max": 1.2,
                    "enabled": False,
                }
            ]
        },
    ).json()["data"]
    assert empty["valid"] is False
    assert empty["errors"][0]["code"] == "NO_TUNABLE_PARAMETERS"


def test_discrete_catalog_choices_are_labelled_and_persisted_for_jobs(client) -> None:
    detail = client.get("/api/v1/parameter-catalog/MC_AIRMODE")
    assert detail.status_code == 200
    parameter = detail.json()["data"]["parameter"]
    assert parameter["type"] == "int"
    assert [choice["value"] for choice in parameter["choices"]] == [0, 1, 2]
    assert all(
        choice["label"]["en"] and choice["label"]["zh-CN"] for choice in parameter["choices"]
    )

    response = client.post(
        "/api/v1/jobs",
        json={
            "parameter_space": [
                {
                    "name": "MC_AIRMODE",
                    "baseline": 0,
                    "minimum": 0,
                    "maximum": 2,
                    "step": 1,
                }
            ]
        },
    )
    assert response.status_code == 200, response.text
    selection = response.json()["data"]["parameter_space"][0]
    assert response.json()["data"]["parameter_catalog_version"] == CATALOG_VERSION
    assert selection["value_type"] == "integer"
    assert selection["choices"] == [0.0, 1.0, 2.0]


def test_parameter_catalog_http_inputs_are_bounded(client) -> None:
    query = client.get("/api/v1/parameter-catalog", params={"px4_version": "x" * 65})
    assert query.status_code == 422

    oversized_choices = client.post(
        "/api/v1/parameter-catalog/validate",
        json={
            "selections": [
                {
                    "name": "MC_AIRMODE",
                    "search_min": 0,
                    "search_max": 2,
                    "choices": list(range(129)),
                }
            ]
        },
    )
    assert oversized_choices.status_code == 422

    invalid_scale = client.post(
        "/api/v1/parameter-catalog/validate",
        json={
            "selections": [
                {
                    "name": "MPC_XY_P",
                    "search_min": 0.7,
                    "search_max": 1.2,
                    "scale": "unsupported",
                }
            ]
        },
    )
    assert invalid_scale.status_code == 422
