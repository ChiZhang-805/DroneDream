"""Evidence for a PX4-to-Gazebo actuator-link stall.

The diagnostic is intentionally conservative.  It is only allowed when the
trial contract excludes payload/thrust/actuator effects and the selected
parameters cannot legitimately prevent vertical lift.  ULog then has to show
an armed Offboard interval, a material climb request, sustained high thrust,
active motor commands, and a Gazebo ground-truth pose that remains stationary.

This evidence classifies a simulator transport/runtime failure.  It never
turns a failed flight into a passing metric and never teaches the optimizer
that a parameter region is unsafe.
"""

from __future__ import annotations

import hashlib
import math
from collections.abc import Mapping, Sequence
from numbers import Real
from pathlib import Path
from typing import Any

SCHEMA_ID = "dronedream.px4-actuator-link-health/v1"
DIAGNOSTIC_FAILURE_CODE = "SIMULATOR_ACTUATOR_LINK_STALLED"
ARTIFACT_NAME = "actuator_link_health.json"
TRANSIENT_RETRY_RECEIPT_NAME = "actuator_link_transient_retry.json"

_ARMED_STATE = 2
_OFFBOARD_NAV_STATE = 14
_MIN_OFFBOARD_SECONDS = 10.0
_MIN_CLIMB_REQUEST_M = 1.0
_MIN_THRUST_MAGNITUDE = 0.8
_MIN_HIGH_THRUST_FRACTION = 0.8
_MIN_ACTIVE_MOTOR_COMMAND = 0.3
_MIN_ACTIVE_MOTOR_FRACTION = 0.8
_MIN_ACTIVE_MOTOR_COUNT = 4
_MAX_GROUNDTRUTH_VERTICAL_DISPLACEMENT_M = 0.05
_MAX_GROUNDTRUTH_HORIZONTAL_DISPLACEMENT_M = 0.05
_SAFE_HORIZONTAL_PARAMETERS = frozenset(
    {
        "MPC_XY_P",
        "MPC_XY_VEL_P_ACC",
        "MPC_XY_VEL_I_ACC",
        "MPC_XY_VEL_D_ACC",
        "MPC_XY_VEL_MAX",
        "MPC_ACC_HOR",
        "MPC_ACC_HOR_MAX",
        "MPC_JERK_AUTO",
    }
)
_DISQUALIFYING_EFFECT_PREFIXES = (
    "battery.",
    "scenario_type.payload_",
    "scenario_type.actuator_",
)


class ActuatorLinkEvidenceError(ValueError):
    """Raised when actuator-link evidence is malformed or mismatched."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def actuator_link_evidence_eligibility(
    *,
    vehicle: object,
    selected_parameters: Mapping[str, object] | Sequence[object],
    scenario_effect_request: object,
) -> dict[str, Any]:
    """Derive the narrow, reproducible boundary for link-stall diagnosis."""

    parameter_names = sorted(
        str(name)
        for name in (
            selected_parameters
            if not isinstance(selected_parameters, Mapping)
            else selected_parameters.keys()
        )
    )
    raw_effects = (
        scenario_effect_request.get("effects", [])
        if isinstance(scenario_effect_request, Mapping)
        else []
    )
    effect_ids = sorted(
        str(effect.get("effect_id"))
        for effect in raw_effects
        if isinstance(effect, Mapping) and isinstance(effect.get("effect_id"), str)
    )
    normalized_vehicle = str(vehicle)
    reasons: list[str] = []
    if normalized_vehicle not in {"x500", "gz_x500"}:
        reasons.append("vehicle_is_not_bundled_x500")
    unexpected_parameters = sorted(set(parameter_names) - _SAFE_HORIZONTAL_PARAMETERS)
    if unexpected_parameters:
        reasons.append("selected_parameters_can_affect_vertical_lift_or_unknown_contract")
    disqualifying_effects = [
        effect_id
        for effect_id in effect_ids
        if effect_id.startswith(_DISQUALIFYING_EFFECT_PREFIXES)
    ]
    if disqualifying_effects:
        reasons.append("payload_battery_or_actuator_effect_requested")
    return {
        "eligible": not reasons,
        "reasons": reasons,
        "vehicle": normalized_vehicle,
        "selected_px4_parameters": parameter_names,
        "unexpected_px4_parameters": unexpected_parameters,
        "scenario_effect_ids": effect_ids,
        "disqualifying_effect_ids": disqualifying_effects,
    }


def _finite(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, Real):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def _column(dataset: Mapping[str, Sequence[object]], name: str) -> list[float]:
    raw = dataset.get(name)
    if raw is None:
        return []
    values: list[float] = []
    for value in raw:
        number = _finite(value)
        if number is None:
            return []
        values.append(number)
    return values


def _offboard_interval(
    status: Mapping[str, Sequence[object]],
) -> tuple[float, float] | None:
    timestamps = _column(status, "timestamp")
    armed = _column(status, "arming_state")
    nav_states = _column(status, "nav_state")
    if not timestamps or not (len(timestamps) == len(armed) == len(nav_states)):
        return None
    timestamps = [value / 1_000_000.0 for value in timestamps]
    intervals: list[tuple[float, float]] = []
    active_start: float | None = None
    active_end: float | None = None
    for index, start in enumerate(timestamps[:-1]):
        end = timestamps[index + 1]
        is_active = (
            int(armed[index]) == _ARMED_STATE
            and int(nav_states[index]) == _OFFBOARD_NAV_STATE
            and end > start
        )
        if is_active:
            if active_start is None:
                active_start = start
            active_end = end
        elif active_start is not None and active_end is not None:
            intervals.append((active_start, active_end))
            active_start = active_end = None
    if active_start is not None and active_end is not None:
        intervals.append((active_start, active_end))
    if not intervals:
        return None
    return max(intervals, key=lambda item: item[1] - item[0])


def _window_values(
    dataset: Mapping[str, Sequence[object]],
    field: str,
    *,
    start_s: float,
    end_s: float,
) -> list[float]:
    raw_timestamps = dataset.get("timestamp")
    raw_values = dataset.get(field)
    if (
        raw_timestamps is None
        or raw_values is None
        or len(raw_timestamps) == 0
        or len(raw_timestamps) != len(raw_values)
    ):
        return []
    selected: list[float] = []
    for raw_timestamp, raw_value in zip(raw_timestamps, raw_values, strict=True):
        timestamp = _finite(raw_timestamp)
        if timestamp is None:
            return []
        timestamp_s = timestamp / 1_000_000.0
        if not start_s <= timestamp_s <= end_s:
            continue
        value = _finite(raw_value)
        if value is None:
            return []
        selected.append(value)
    return selected


def compile_actuator_link_health_evidence_from_series(
    *,
    datasets: Mapping[str, Mapping[str, Sequence[object]]],
    execution_identity: Mapping[str, object],
    ulog_sha256: str,
    eligibility: Mapping[str, object],
) -> dict[str, Any]:
    """Compile bounded stall evidence from already-decoded ULog series."""

    status = datasets.get("vehicle_status", {})
    interval = _offboard_interval(status)
    missing: list[str] = []
    if interval is None:
        missing.append("armed_offboard_interval")
        start_s = end_s = 0.0
    else:
        start_s, end_s = interval

    trajectory = datasets.get("trajectory_setpoint", {})
    attitude_setpoint = datasets.get("vehicle_attitude_setpoint", {})
    motors = datasets.get("actuator_motors", {})
    groundtruth = datasets.get("vehicle_local_position_groundtruth", {})

    commanded_z = _window_values(
        trajectory, "position[2]", start_s=start_s, end_s=end_s
    )
    thrust_z = _window_values(
        attitude_setpoint, "thrust_body[2]", start_s=start_s, end_s=end_s
    )
    groundtruth_x = _window_values(groundtruth, "x", start_s=start_s, end_s=end_s)
    groundtruth_y = _window_values(groundtruth, "y", start_s=start_s, end_s=end_s)
    groundtruth_z = _window_values(groundtruth, "z", start_s=start_s, end_s=end_s)
    motor_columns = [
        _window_values(motors, f"control[{index}]", start_s=start_s, end_s=end_s)
        for index in range(4)
    ]

    for name, values in (
        ("trajectory_setpoint.position[2]", commanded_z),
        ("vehicle_attitude_setpoint.thrust_body[2]", thrust_z),
        ("vehicle_local_position_groundtruth.x", groundtruth_x),
        ("vehicle_local_position_groundtruth.y", groundtruth_y),
        ("vehicle_local_position_groundtruth.z", groundtruth_z),
    ):
        if not values:
            missing.append(name)
    for index, values in enumerate(motor_columns):
        if not values:
            missing.append(f"actuator_motors.control[{index}]")

    duration_s = max(0.0, end_s - start_s)
    climb_request_m = max(commanded_z) - min(commanded_z) if commanded_z else 0.0
    if commanded_z and groundtruth_z:
        climb_request_m = max(
            climb_request_m,
            max(abs(value - groundtruth_z[0]) for value in commanded_z),
        )
    max_thrust_magnitude = max((abs(value) for value in thrust_z), default=0.0)
    high_thrust_fraction = (
        sum(abs(value) >= _MIN_THRUST_MAGNITUDE for value in thrust_z) / len(thrust_z)
        if thrust_z
        else 0.0
    )
    motor_maxima = [max((abs(value) for value in values), default=0.0) for values in motor_columns]
    motor_active_fractions = [
        (
            sum(abs(value) >= _MIN_ACTIVE_MOTOR_COMMAND for value in values) / len(values)
            if values
            else 0.0
        )
        for values in motor_columns
    ]
    active_motor_count = sum(
        fraction >= _MIN_ACTIVE_MOTOR_FRACTION for fraction in motor_active_fractions
    )

    if groundtruth_x and groundtruth_y and groundtruth_z:
        x0, y0, z0 = groundtruth_x[0], groundtruth_y[0], groundtruth_z[0]
        horizontal_displacement_m = max(
            math.hypot(x - x0, y - y0)
            for x, y in zip(groundtruth_x, groundtruth_y, strict=True)
        )
        vertical_displacement_m = max(abs(z - z0) for z in groundtruth_z)
    else:
        horizontal_displacement_m = math.inf
        vertical_displacement_m = math.inf

    eligible = eligibility.get("eligible") is True
    stall_verified = bool(
        eligible
        and not missing
        and duration_s >= _MIN_OFFBOARD_SECONDS
        and climb_request_m >= _MIN_CLIMB_REQUEST_M
        and max_thrust_magnitude >= _MIN_THRUST_MAGNITUDE
        and high_thrust_fraction >= _MIN_HIGH_THRUST_FRACTION
        and active_motor_count >= _MIN_ACTIVE_MOTOR_COUNT
        and vertical_displacement_m <= _MAX_GROUNDTRUTH_VERTICAL_DISPLACEMENT_M
        and horizontal_displacement_m <= _MAX_GROUNDTRUTH_HORIZONTAL_DISPLACEMENT_M
    )
    observations = {
        "armed_offboard_duration_s": round(duration_s, 6),
        "commanded_climb_m": round(climb_request_m, 6),
        "max_thrust_magnitude": round(max_thrust_magnitude, 6),
        "high_thrust_sample_fraction": round(high_thrust_fraction, 6),
        "motor_max_abs_commands": [round(value, 6) for value in motor_maxima],
        "motor_active_sample_fractions": [
            round(value, 6) for value in motor_active_fractions
        ],
        "active_motor_count": active_motor_count,
        "groundtruth_vertical_displacement_m": (
            round(vertical_displacement_m, 6) if math.isfinite(vertical_displacement_m) else None
        ),
        "groundtruth_horizontal_displacement_m": (
            round(horizontal_displacement_m, 6)
            if math.isfinite(horizontal_displacement_m)
            else None
        ),
    }
    return {
        "schema_id": SCHEMA_ID,
        "diagnostic_failure_code": DIAGNOSTIC_FAILURE_CODE,
        "execution_identity": dict(execution_identity),
        "ulog_sha256": ulog_sha256,
        "eligibility": dict(eligibility),
        "thresholds": {
            "minimum_armed_offboard_seconds": _MIN_OFFBOARD_SECONDS,
            "minimum_commanded_climb_m": _MIN_CLIMB_REQUEST_M,
            "minimum_thrust_magnitude": _MIN_THRUST_MAGNITUDE,
            "minimum_high_thrust_sample_fraction": _MIN_HIGH_THRUST_FRACTION,
            "minimum_active_motor_command": _MIN_ACTIVE_MOTOR_COMMAND,
            "minimum_active_motor_sample_fraction": _MIN_ACTIVE_MOTOR_FRACTION,
            "minimum_active_motor_count": _MIN_ACTIVE_MOTOR_COUNT,
            "maximum_groundtruth_vertical_displacement_m": (
                _MAX_GROUNDTRUTH_VERTICAL_DISPLACEMENT_M
            ),
            "maximum_groundtruth_horizontal_displacement_m": (
                _MAX_GROUNDTRUTH_HORIZONTAL_DISPLACEMENT_M
            ),
        },
        "observations": observations,
        "missing_series": sorted(missing),
        "stall_verified": stall_verified,
    }


def compile_actuator_link_health_evidence(
    *,
    ulog_path: Path,
    execution_identity: Mapping[str, object],
    eligibility: Mapping[str, object],
) -> dict[str, Any]:
    """Decode a PX4 ULog and compile actuator-link stall evidence."""

    try:
        from pyulog import ULog
    except ImportError as exc:  # pragma: no cover - pinned Runtime owns pyulog.
        raise ActuatorLinkEvidenceError("pyulog is required for actuator-link evidence") from exc
    try:
        log = ULog(str(ulog_path))
        required = {
            "vehicle_status",
            "trajectory_setpoint",
            "vehicle_attitude_setpoint",
            "actuator_motors",
            "vehicle_local_position_groundtruth",
        }
        datasets: dict[str, Mapping[str, Sequence[object]]] = {}
        for dataset in log.data_list:
            if dataset.multi_id == 0 and dataset.name in required:
                datasets[dataset.name] = dataset.data
    except Exception as exc:
        raise ActuatorLinkEvidenceError(
            "PX4 ULog could not be decoded for actuator-link evidence"
        ) from exc
    return compile_actuator_link_health_evidence_from_series(
        datasets=datasets,
        execution_identity=execution_identity,
        ulog_sha256=sha256_file(ulog_path),
        eligibility=eligibility,
    )


def validate_actuator_link_health_evidence(
    payload: object,
    *,
    expected_identity: Mapping[str, object],
    expected_ulog_sha256: str,
) -> dict[str, Any]:
    """Validate a producer receipt before admitting infrastructure taxonomy."""

    if not isinstance(payload, dict) or payload.get("schema_id") != SCHEMA_ID:
        raise ActuatorLinkEvidenceError("actuator-link evidence schema mismatch")
    if payload.get("diagnostic_failure_code") != DIAGNOSTIC_FAILURE_CODE:
        raise ActuatorLinkEvidenceError("actuator-link diagnostic code mismatch")
    if payload.get("execution_identity") != dict(expected_identity):
        raise ActuatorLinkEvidenceError("actuator-link execution identity mismatch")
    if payload.get("ulog_sha256") != expected_ulog_sha256:
        raise ActuatorLinkEvidenceError("actuator-link ULog digest mismatch")
    if payload.get("stall_verified") is not True:
        raise ActuatorLinkEvidenceError("actuator-link stall was not verified")
    eligibility = payload.get("eligibility")
    if not isinstance(eligibility, dict) or eligibility.get("eligible") is not True:
        raise ActuatorLinkEvidenceError("actuator-link trial was not eligible")
    if payload.get("missing_series") != []:
        raise ActuatorLinkEvidenceError("actuator-link evidence has missing ULog series")
    thresholds = payload.get("thresholds")
    observations = payload.get("observations")
    if not isinstance(thresholds, dict) or not isinstance(observations, dict):
        raise ActuatorLinkEvidenceError("actuator-link observations are malformed")
    return payload


__all__ = [
    "ARTIFACT_NAME",
    "ActuatorLinkEvidenceError",
    "DIAGNOSTIC_FAILURE_CODE",
    "SCHEMA_ID",
    "TRANSIENT_RETRY_RECEIPT_NAME",
    "actuator_link_evidence_eligibility",
    "compile_actuator_link_health_evidence",
    "compile_actuator_link_health_evidence_from_series",
    "sha256_file",
    "validate_actuator_link_health_evidence",
]
