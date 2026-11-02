from __future__ import annotations

import copy
import math

import numpy as np
import pytest

from app.simulator.px4_actuator_link_evidence import (
    ActuatorLinkEvidenceError,
    actuator_link_evidence_eligibility,
    compile_actuator_link_health_evidence_from_series,
    validate_actuator_link_health_evidence,
)

IDENTITY = {
    "trial_id": "tri-1",
    "job_id": "job-1",
    "candidate_id": "cand-1",
    "seed": 7,
    "attempt_count": 1,
}


def _series(*, physical_vertical_m: float = 0.0, thrust: float = -1.0):
    timestamps = [value * 1_000_000 for value in range(31)]
    return {
        "vehicle_status": {
            "timestamp": [0, 30_000_000],
            "arming_state": [2, 2],
            "nav_state": [14, 4],
        },
        "trajectory_setpoint": {
            "timestamp": timestamps,
            "position[2]": [-min(value / 3, 3.0) for value in range(31)],
        },
        "vehicle_attitude_setpoint": {
            "timestamp": timestamps,
            "thrust_body[2]": [thrust for _ in timestamps],
        },
        "actuator_motors": {
            "timestamp": timestamps,
            **{f"control[{index}]": [0.9 for _ in timestamps] for index in range(4)},
        },
        "vehicle_local_position_groundtruth": {
            "timestamp": timestamps,
            "x": [0.0 for _ in timestamps],
            "y": [0.0 for _ in timestamps],
            "z": [-(physical_vertical_m * value / 30) for value in range(31)],
        },
    }


def _compile(**kwargs):
    return compile_actuator_link_health_evidence_from_series(
        datasets=_series(**kwargs),
        execution_identity=IDENTITY,
        ulog_sha256="a" * 64,
        eligibility={"eligible": True, "reasons": []},
    )


def test_static_groundtruth_under_sustained_actuation_verifies_link_stall() -> None:
    evidence = _compile()

    assert evidence["stall_verified"] is True
    assert evidence["observations"]["active_motor_count"] == 4
    assert evidence["observations"]["commanded_climb_m"] == 3.0
    assert evidence["observations"]["groundtruth_vertical_displacement_m"] == 0.0
    assert evidence["missing_series"] == []

    validated = validate_actuator_link_health_evidence(
        evidence,
        expected_identity=IDENTITY,
        expected_ulog_sha256="a" * 64,
    )
    assert validated == evidence


def test_periodic_status_samples_form_one_continuous_offboard_interval() -> None:
    series = _series()
    series["vehicle_status"] = {
        "timestamp": [value * 1_000_000 for value in range(31)],
        "arming_state": [2] * 31,
        "nav_state": [14] * 30 + [4],
    }

    evidence = compile_actuator_link_health_evidence_from_series(
        datasets=series,
        execution_identity=IDENTITY,
        ulog_sha256="a" * 64,
        eligibility={"eligible": True, "reasons": []},
    )

    assert evidence["observations"]["armed_offboard_duration_s"] == 30.0
    assert evidence["stall_verified"] is True


def test_constant_climb_setpoint_is_measured_from_initial_groundtruth() -> None:
    series = _series()
    series["trajectory_setpoint"]["position[2]"] = [-3.0] * 31

    evidence = compile_actuator_link_health_evidence_from_series(
        datasets=series,
        execution_identity=IDENTITY,
        ulog_sha256="a" * 64,
        eligibility={"eligible": True, "reasons": []},
    )

    assert evidence["observations"]["commanded_climb_m"] == 3.0
    assert evidence["stall_verified"] is True


def test_nonfinite_values_outside_the_offboard_window_do_not_hide_a_stall() -> None:
    series = _series()
    trajectory = series["trajectory_setpoint"]
    trajectory["timestamp"] = [-1_000_000, *trajectory["timestamp"], 31_000_000]
    trajectory["position[2]"] = [math.nan, *trajectory["position[2]"], math.nan]

    evidence = compile_actuator_link_health_evidence_from_series(
        datasets=series,
        execution_identity=IDENTITY,
        ulog_sha256="a" * 64,
        eligibility={"eligible": True, "reasons": []},
    )

    assert evidence["stall_verified"] is True
    assert evidence["missing_series"] == []


def test_pyulog_numpy_series_are_decoded_without_scalar_type_loss() -> None:
    series = _series()
    numpy_series = {
        dataset_name: {
            field_name: np.asarray(values)
            for field_name, values in dataset.items()
        }
        for dataset_name, dataset in series.items()
    }

    evidence = compile_actuator_link_health_evidence_from_series(
        datasets=numpy_series,
        execution_identity=IDENTITY,
        ulog_sha256="a" * 64,
        eligibility={"eligible": True, "reasons": []},
    )

    assert evidence["stall_verified"] is True
    assert evidence["missing_series"] == []


def test_eligibility_is_shared_and_rejects_vertical_or_thrust_effects() -> None:
    eligible = actuator_link_evidence_eligibility(
        vehicle="x500",
        selected_parameters={"MPC_XY_P": 0.95},
        scenario_effect_request={"effects": []},
    )
    assert eligible["eligible"] is True

    vertical = actuator_link_evidence_eligibility(
        vehicle="x500",
        selected_parameters={"MPC_THR_HOVER": 0.5},
        scenario_effect_request={"effects": []},
    )
    assert vertical["eligible"] is False
    assert vertical["unexpected_px4_parameters"] == ["MPC_THR_HOVER"]

    payload = actuator_link_evidence_eligibility(
        vehicle="x500",
        selected_parameters={},
        scenario_effect_request={
            "effects": [{"effect_id": "scenario_type.payload_mass"}]
        },
    )
    assert payload["eligible"] is False
    assert payload["disqualifying_effect_ids"] == ["scenario_type.payload_mass"]


@pytest.mark.parametrize(
    ("change", "expected"),
    [
        ({"physical_vertical_m": 2.0}, False),
        ({"thrust": -0.2}, False),
    ],
)
def test_real_motion_or_low_thrust_does_not_claim_link_stall(change, expected) -> None:
    assert _compile(**change)["stall_verified"] is expected


def test_isolated_motor_command_spikes_do_not_claim_a_sustained_link_stall() -> None:
    series = _series()
    timestamps = series["actuator_motors"]["timestamp"]
    for index in range(4):
        commands = [0.0 for _ in timestamps]
        commands[index + 1] = 0.9
        series["actuator_motors"][f"control[{index}]"] = commands

    evidence = compile_actuator_link_health_evidence_from_series(
        datasets=series,
        execution_identity=IDENTITY,
        ulog_sha256="a" * 64,
        eligibility={"eligible": True, "reasons": []},
    )

    assert evidence["stall_verified"] is False


def test_ineligible_payload_or_actuator_trial_never_claims_link_stall() -> None:
    evidence = compile_actuator_link_health_evidence_from_series(
        datasets=_series(),
        execution_identity=IDENTITY,
        ulog_sha256="a" * 64,
        eligibility={"eligible": False, "reasons": ["payload_effect_requested"]},
    )

    assert evidence["stall_verified"] is False


def test_validation_rejects_identity_digest_and_verdict_tampering() -> None:
    evidence = _compile()
    for key, value in (
        ("execution_identity", {**IDENTITY, "trial_id": "tri-other"}),
        ("ulog_sha256", "b" * 64),
        ("stall_verified", False),
    ):
        tampered = copy.deepcopy(evidence)
        tampered[key] = value
        with pytest.raises(ActuatorLinkEvidenceError):
            validate_actuator_link_health_evidence(
                tampered,
                expected_identity=IDENTITY,
                expected_ulog_sha256="a" * 64,
            )
