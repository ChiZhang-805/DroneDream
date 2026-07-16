"""Boundary validation for experiment inputs passed to optimizers and runners."""

from __future__ import annotations

import math

import pytest
from app.schemas import (
    JobCreateRequest,
    JobsCompareRequest,
    OpenAIConfig,
    ParameterSelection,
)
from pydantic import ValidationError


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("altitude_m", True),
        ("max_iterations", 2.5),
        ("trials_per_candidate", "3"),
    ],
)
def test_job_request_rejects_coerced_numeric_types(field, value) -> None:
    with pytest.raises(ValidationError):
        JobCreateRequest(**{field: value})


def test_request_rejects_non_finite_numeric_inputs() -> None:
    with pytest.raises(ValidationError):
        JobCreateRequest(start_point={"x": math.nan, "y": 0.0})

    with pytest.raises(ValidationError):
        JobCreateRequest(
            objective_config={
                "objectives": [
                    {"metric": "rmse", "direction": "minimize", "target": math.inf}
                ]
            }
        )

    with pytest.raises(ValidationError):
        JobCreateRequest(
            advanced_scenario_config={
                "obstacles": [
                    {
                        "type": "cylinder",
                        "x": math.nan,
                        "y": 0,
                        "z": 0,
                        "radius": 1,
                        "height": 2,
                    }
                ]
            }
        )


def test_legacy_openai_config_rejects_blank_key_and_normalizes_model() -> None:
    with pytest.raises(ValidationError):
        OpenAIConfig(api_key="   ")

    config = OpenAIConfig(api_key="  sk-test  ", model="   ")
    assert config.api_key == "sk-test"
    assert config.model is None


def test_vehicle_profile_normalizes_and_validates_firmware_identity() -> None:
    request = JobCreateRequest(
        display_name="  Trial A  ",
        vehicle_profile={
            "px4_version": " v1.16 ",
            "firmware_commit": " a1b2c3d4 ",
            "vehicle_type": " multicopter ",
            "airframe": " x500 ",
            "simulator_model": " gz_x500 ",
            "world": " default ",
        },
    )
    assert request.display_name == "Trial A"
    assert request.vehicle_profile.px4_version == "v1.16"
    assert request.vehicle_profile.firmware_commit == "a1b2c3d4"
    assert request.vehicle_profile.simulator_model == "gz_x500"

    with pytest.raises(ValidationError):
        JobCreateRequest(vehicle_profile={"firmware_commit": "main"})

    with pytest.raises(ValidationError):
        JobCreateRequest(vehicle_profile={"simulation_speed_factor": 0})
    with pytest.raises(ValidationError):
        JobCreateRequest(vehicle_profile={"simulation_speed_factor": 0.09})
    with pytest.raises(ValidationError):
        JobCreateRequest(vehicle_profile={"instance_id": 256})


@pytest.mark.parametrize("seed", [-1, 2_147_483_648])
def test_scenario_seed_stays_in_portable_process_range(seed: int) -> None:
    with pytest.raises(ValidationError):
        JobCreateRequest(
            scenario_suite={
                "cases": [
                    {
                        "id": "nominal",
                        "scenario_type": "nominal",
                        "seeds": [seed],
                    }
                ]
            }
        )


def test_scenario_case_config_rejects_nested_non_finite_values() -> None:
    with pytest.raises(ValidationError):
        JobCreateRequest(
            scenario_suite={
                "cases": [
                    {
                        "id": "wind",
                        "scenario_type": "wind_perturbed",
                        "seeds": [1],
                        "config": {"wind": {"gusts": [1.0, math.nan]}},
                    }
                ]
            }
        )


def test_obstacle_shape_fields_are_unambiguous() -> None:
    with pytest.raises(ValidationError):
        JobCreateRequest(
            advanced_scenario_config={
                "obstacles": [
                    {
                        "type": "box",
                        "x": 0,
                        "y": 0,
                        "z": 0,
                        "size_x": 1,
                        "size_y": 1,
                        "size_z": 1,
                        "radius": 0.5,
                    }
                ]
            }
        )


def test_unlocked_discrete_dimension_requires_two_choices() -> None:
    with pytest.raises(ValidationError):
        JobCreateRequest(
            parameter_space=[
                {
                    "name": "MC_AIRMODE",
                    "baseline": 1,
                    "minimum": 0,
                    "maximum": 2,
                    "value_type": "enum",
                    "choices": [1],
                }
            ]
        )


def test_discrete_parameter_rejects_fractional_step() -> None:
    with pytest.raises(ValidationError, match="values must be integers"):
        ParameterSelection(
            name="TEST_INT",
            baseline=1.0,
            minimum=0.0,
            maximum=2.0,
            step=0.5,
            value_type="integer",
        )


def test_job_compare_rejects_duplicate_job_ids() -> None:
    with pytest.raises(ValidationError, match="job_ids must be unique"):
        JobsCompareRequest(job_ids=["job_same", "job_same"])
    with pytest.raises(ValidationError):
        JobsCompareRequest(job_ids=["job_ok", "x" * 65])
