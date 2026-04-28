"""Lightweight validators and helpers for real_cli artifact schemas."""

from __future__ import annotations

from typing import Any


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def infer_mime_type(artifact_type: str) -> str | None:
    if artifact_type in {"telemetry_json", "reference_track_json", "trajectory_json"}:
        return "application/json"
    if artifact_type in {"worker_log", "simulator_stdout", "simulator_stderr"}:
        return "text/plain"
    return None


def validate_telemetry_payload(payload: object) -> list[str]:
    """Return a list of schema validation errors for telemetry payloads."""

    errors: list[str] = []
    if not isinstance(payload, dict):
        return ["telemetry payload must be a JSON object"]

    if payload.get("schema_version") != "dronedream.telemetry.v1":
        errors.append("telemetry schema_version must be 'dronedream.telemetry.v1'")

    samples = payload.get("samples")
    if not isinstance(samples, list):
        errors.append("telemetry payload must contain samples[]")
        return errors

    for idx, sample in enumerate(samples):
        if not isinstance(sample, dict):
            errors.append(f"telemetry sample[{idx}] must be an object")
            continue

        for key in ("t", "x", "y", "z"):
            if not _is_number(sample.get(key)):
                errors.append(f"telemetry sample[{idx}] missing numeric '{key}'")

        for key in (
            "vx",
            "vy",
            "vz",
            "roll",
            "pitch",
            "yaw",
            "reference_x",
            "reference_y",
            "reference_z",
        ):
            if key in sample and sample[key] is not None and not _is_number(sample[key]):
                errors.append(f"telemetry sample[{idx}] field '{key}' must be numeric")

    return errors


def validate_reference_track_payload(payload: object) -> list[str]:
    """Return a list of schema validation errors for reference-track payloads."""

    errors: list[str] = []
    if not isinstance(payload, dict):
        return ["reference track payload must be a JSON object"]

    if payload.get("schema_version") != "dronedream.reference_track.v1":
        errors.append("reference track schema_version must be 'dronedream.reference_track.v1'")

    points = payload.get("reference_track")
    if not isinstance(points, list):
        errors.append("reference track payload must contain reference_track[]")
        return errors

    for idx, point in enumerate(points):
        if not isinstance(point, dict):
            errors.append(f"reference_track[{idx}] must be an object")
            continue
        for axis in ("x", "y", "z"):
            if not _is_number(point.get(axis)):
                errors.append(f"reference_track[{idx}] missing numeric '{axis}'")

    return errors
