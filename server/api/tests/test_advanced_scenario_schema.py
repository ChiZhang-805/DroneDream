from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.schemas import JobCreateRequest


def _base_payload() -> dict:
    return {
        "track_type": "circle",
        "start_point": {"x": 0, "y": 0},
        "altitude_m": 3.0,
        "wind": {"north": 0, "east": 0, "south": 0, "west": 0},
        "sensor_noise_level": "medium",
        "objective_profile": "robust",
        "simulator_backend": "mock",
        "optimizer_strategy": "heuristic",
        "max_iterations": 2,
        "trials_per_candidate": 1,
        "max_total_trials": 10,
    }


def test_advanced_schema_accepts_valid_payload() -> None:
    payload = _base_payload()
    payload["advanced_scenario_config"] = {
        "wind_gusts": {
            "enabled": True,
            "magnitude_mps": 3.0,
            "direction_deg": 45.0,
            "period_s": 15.0,
        },
        "obstacles": [
            {
                "type": "cylinder",
                "x": 1.0,
                "y": 2.0,
                "z": 0.0,
                "radius": 0.6,
                "height": 2.0,
            },
            {
                "type": "box",
                "x": 5.0,
                "y": 1.0,
                "z": 0.0,
                "size_x": 1.0,
                "size_y": 2.0,
                "size_z": 3.0,
            },
        ],
        "sensor_degradation": {
            "gps_noise_m": 1.0,
            "baro_noise_m": 0.5,
            "imu_noise_scale": 5.0,
            "dropout_rate": 0.2,
        },
        "battery": {
            "initial_percent": 90.0,
            "voltage_sag": True,
            "mass_payload_kg": 4.0,
        },
    }
    req = JobCreateRequest(**payload)
    assert req.advanced_scenario_config is not None
    assert req.advanced_scenario_config.wind_gusts.direction_deg == 45.0


@pytest.mark.parametrize(
    "field,value",
    [
        ("magnitude_mps", 31.0),
        ("direction_deg", 360.0),
        ("period_s", 0.0),
    ],
)
def test_advanced_schema_rejects_invalid_wind_gusts(field: str, value: float) -> None:
    payload = _base_payload()
    payload["advanced_scenario_config"] = {
        "wind_gusts": {
            "enabled": True,
            "magnitude_mps": 2.0,
            "direction_deg": 30.0,
            "period_s": 10.0,
            field: value,
        }
    }
    with pytest.raises(ValidationError):
        JobCreateRequest(**payload)


def test_advanced_schema_rejects_invalid_payload_mass() -> None:
    payload = _base_payload()
    payload["advanced_scenario_config"] = {
        "battery": {"initial_percent": 80.0, "voltage_sag": False, "mass_payload_kg": 21.0}
    }
    with pytest.raises(ValidationError):
        JobCreateRequest(**payload)
