"""Lightweight validators and helpers for real_cli artifact schemas."""

from __future__ import annotations

import math
from typing import Any, cast

from app.simulator.telemetry_evidence import (
    TELEMETRY_SCHEMA_V2,
    verify_telemetry_semantic_contract,
)

_MAX_TELEMETRY_SAMPLES = 200_000
_MAX_REFERENCE_POINTS = 10_000
_MAX_SCHEMA_ERRORS = 100


def _is_number(value: Any) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
    )


def infer_mime_type(artifact_type: str) -> str | None:
    if artifact_type.endswith("_json"):
        return "application/json"
    if artifact_type in {"worker_log", "simulator_stdout", "simulator_stderr"}:
        return "text/plain"
    return None


def validate_telemetry_payload(payload: object) -> list[str]:
    """Return a list of schema validation errors for telemetry payloads."""

    errors: list[str] = []
    if not isinstance(payload, dict):
        return ["telemetry payload must be a JSON object"]

    schema_version = payload.get("schema_version")
    if schema_version not in {
        "dronedream.telemetry.v1",
        TELEMETRY_SCHEMA_V2,
    }:
        errors.append(
            "telemetry schema_version must be "
            "'dronedream.telemetry.v1' or 'dronedream.telemetry.v2'"
        )

    samples = payload.get("samples")
    if not isinstance(samples, list):
        errors.append("telemetry payload must contain samples[]")
        return errors
    if not samples:
        errors.append("telemetry samples[] must not be empty")
        return errors
    if len(samples) > _MAX_TELEMETRY_SAMPLES:
        return [f"telemetry samples[] cannot exceed {_MAX_TELEMETRY_SAMPLES} items"]

    previous_t: float | None = None
    for idx, sample in enumerate(samples):
        if not isinstance(sample, dict):
            errors.append(f"telemetry sample[{idx}] must be an object")
            if len(errors) >= _MAX_SCHEMA_ERRORS:
                errors.append("telemetry validation stopped after too many errors")
                break
            continue

        for key in ("t", "x", "y", "z"):
            if not _is_number(sample.get(key)):
                errors.append(f"telemetry sample[{idx}] missing numeric '{key}'")
        current_t = sample.get("t")
        if _is_number(current_t):
            normalized_t = float(cast(int | float, current_t))
            if previous_t is not None and normalized_t <= previous_t:
                errors.append(f"telemetry sample[{idx}] timestamp must be strictly increasing")
            previous_t = normalized_t

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
        if len(errors) >= _MAX_SCHEMA_ERRORS:
            errors.append("telemetry validation stopped after too many errors")
            break

    if (
        not errors
        and schema_version == TELEMETRY_SCHEMA_V2
        and verify_telemetry_semantic_contract(payload) is None
    ):
        errors.append(
            "telemetry v2 semantic contract is missing or does not match "
            "the samples"
        )

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
    if not points:
        return ["reference_track[] must not be empty"]
    if len(points) > _MAX_REFERENCE_POINTS:
        return [f"reference_track[] cannot exceed {_MAX_REFERENCE_POINTS} items"]

    for idx, point in enumerate(points):
        if not isinstance(point, dict):
            errors.append(f"reference_track[{idx}] must be an object")
            if len(errors) >= _MAX_SCHEMA_ERRORS:
                errors.append("reference track validation stopped after too many errors")
                break
            continue
        for axis in ("x", "y", "z"):
            if not _is_number(point.get(axis)):
                errors.append(f"reference_track[{idx}] missing numeric '{axis}'")
        if len(errors) >= _MAX_SCHEMA_ERRORS:
            errors.append("reference track validation stopped after too many errors")
            break

    return errors
