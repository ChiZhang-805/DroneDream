"""Lightweight validators and helpers for real_cli artifact schemas."""

from __future__ import annotations

import hashlib
import math
import re
from typing import Any, cast

from app.simulator.bounded_log_capture import LOG_CAPTURE_SCHEMA_VERSION
from app.simulator.telemetry_evidence import (
    TELEMETRY_SCHEMA_V2,
    verify_telemetry_semantic_contract,
)

_MAX_TELEMETRY_SAMPLES = 200_000
_MAX_REFERENCE_POINTS = 10_000
_MAX_SCHEMA_ERRORS = 100
_SHA256_HEX = re.compile(r"^[0-9a-f]{64}$")


def _is_number(value: Any) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
    )


def infer_mime_type(artifact_type: str) -> str | None:
    if artifact_type.endswith("_json"):
        return "application/json"
    if artifact_type == "px4_ulog":
        return "application/octet-stream"
    if artifact_type in {"worker_log", "simulator_stdout", "simulator_stderr"}:
        return "text/plain"
    return None


def validate_log_capture_receipt_payload(payload: object) -> list[str]:
    """Validate the durable contract for a bounded simulator log receipt."""

    if not isinstance(payload, dict):
        return ["log capture receipt must be a JSON object"]
    errors: list[str] = []
    if payload.get("schema_version") != LOG_CAPTURE_SCHEMA_VERSION:
        errors.append(f"schema_version must be {LOG_CAPTURE_SCHEMA_VERSION!r}")
    for field in ("stream", "captured_file_name"):
        value = payload.get(field)
        if (
            not isinstance(value, str)
            or not value.strip()
            or len(value) > 255
            or any(ord(char) < 32 for char in value)
        ):
            errors.append(f"{field} must be a bounded non-empty string")
    integer_fields = (
        "cap_bytes",
        "raw_observed_bytes",
        "normalized_observed_bytes",
        "retained_bytes",
        "dropped_bytes_due_to_cap",
        "ansi_sequence_count",
        "ansi_control_bytes_removed",
        "prompt_redraws_collapsed",
        "utf8_replacement_count",
    )
    numbers: dict[str, int] = {}
    for field in integer_fields:
        value = payload.get(field)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            errors.append(f"{field} must be a non-negative integer")
        else:
            numbers[field] = value
    if numbers.get("cap_bytes", 0) <= 0:
        errors.append("cap_bytes must be positive")
    if numbers.get("retained_bytes", 0) > numbers.get("cap_bytes", 0):
        errors.append("retained_bytes cannot exceed cap_bytes")
    if numbers.get("normalized_observed_bytes", 0) != numbers.get(
        "retained_bytes", 0
    ) + numbers.get("dropped_bytes_due_to_cap", 0):
        errors.append("normalized bytes must equal retained plus cap-dropped bytes")
    for field in (
        "truncated",
        "observation_complete",
        "prior_observation_exact",
        "incomplete_ansi_sequence",
    ):
        if not isinstance(payload.get(field), bool):
            errors.append(f"{field} must be boolean")
    dropped = numbers.get("dropped_bytes_due_to_cap", 0)
    if payload.get("truncated") != (dropped > 0):
        errors.append("truncated must match dropped_bytes_due_to_cap")
    expected_reason = "normalized_output_exceeded_cap" if dropped else None
    if payload.get("truncation_reason") != expected_reason:
        errors.append("truncation_reason does not match the cap outcome")
    observation_error = payload.get("observation_error")
    if observation_error is not None and (
        not isinstance(observation_error, str)
        or not observation_error
        or len(observation_error) > 128
    ):
        errors.append("observation_error must be null or a bounded string")
    retained_sha256 = payload.get("retained_sha256")
    if not isinstance(retained_sha256, str) or _SHA256_HEX.fullmatch(retained_sha256) is None:
        errors.append("retained_sha256 must be lowercase SHA-256 hex")
    critical_lines = payload.get("critical_lines")
    if not isinstance(critical_lines, list) or len(critical_lines) > 32:
        errors.append("critical_lines must be an array with at most 32 items")
    else:
        for index, item in enumerate(critical_lines):
            if not isinstance(item, dict):
                errors.append(f"critical_lines[{index}] must be an object")
                continue
            line = item.get("line")
            digest = item.get("sha256")
            if not isinstance(line, str) or not line or len(line) > 1024:
                errors.append(f"critical_lines[{index}].line is invalid")
                continue
            expected_digest = hashlib.sha256(line.encode("utf-8")).hexdigest()
            if digest != expected_digest:
                errors.append(f"critical_lines[{index}].sha256 does not match line")
    return errors[:_MAX_SCHEMA_ERRORS]


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
        if "crashed" in sample and not isinstance(
            sample["crashed"],
            bool,
        ):
            errors.append(f"telemetry sample[{idx}] field 'crashed' must be boolean")
        if len(errors) >= _MAX_SCHEMA_ERRORS:
            errors.append("telemetry validation stopped after too many errors")
            break

    if (
        not errors
        and schema_version == TELEMETRY_SCHEMA_V2
        and verify_telemetry_semantic_contract(payload) is None
    ):
        errors.append("telemetry v2 semantic contract is missing or does not match the samples")

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
