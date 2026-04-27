"""Lightweight validators for real_cli artifact payload schemas."""

from __future__ import annotations

from typing import Any


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _validate_sample(sample: Any, idx: int) -> None:
    if not isinstance(sample, dict):
        raise ValueError(f"telemetry sample[{idx}] must be an object")
    required = ("t", "x", "y", "z")
    for key in required:
        if not _is_number(sample.get(key)):
            raise ValueError(f"telemetry sample[{idx}] missing numeric '{key}'")
    optional_numeric = (
        "vx",
        "vy",
        "vz",
        "roll",
        "pitch",
        "yaw",
        "reference_x",
        "reference_y",
        "reference_z",
    )
    for key in optional_numeric:
        if key in sample and sample[key] is not None and not _is_number(sample[key]):
            raise ValueError(f"telemetry sample[{idx}] field '{key}' must be numeric")


def validate_telemetry_payload(payload: Any) -> None:
    """Validate dronedream.telemetry.v1 payload shape.

    Raises ``ValueError`` when the payload is malformed.
    """

    if not isinstance(payload, dict):
        raise ValueError("telemetry payload must be a JSON object")
    if payload.get("schema_version") != "dronedream.telemetry.v1":
        raise ValueError("telemetry schema_version must be 'dronedream.telemetry.v1'")
    samples = payload.get("samples")
    if not isinstance(samples, list):
        raise ValueError("telemetry payload must contain samples[]")
    for idx, sample in enumerate(samples):
        _validate_sample(sample, idx)


def validate_reference_track_payload(payload: Any) -> None:
    """Validate dronedream.reference_track.v1 payload shape.

    Raises ``ValueError`` when the payload is malformed.
    """

    if not isinstance(payload, dict):
        raise ValueError("reference track payload must be a JSON object")
    if payload.get("schema_version") != "dronedream.reference_track.v1":
        raise ValueError(
            "reference track schema_version must be 'dronedream.reference_track.v1'"
        )
    points = payload.get("reference_track")
    if not isinstance(points, list):
        raise ValueError("reference track payload must contain reference_track[]")
    for idx, point in enumerate(points):
        if not isinstance(point, dict):
            raise ValueError(f"reference_track[{idx}] must be an object")
        for axis in ("x", "y", "z"):
            if not _is_number(point.get(axis)):
                raise ValueError(f"reference_track[{idx}] missing numeric '{axis}'")

