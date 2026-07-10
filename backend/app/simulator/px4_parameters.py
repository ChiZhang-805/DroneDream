"""Apply real PX4 parameters and preserve a readback evidence chain.

The module intentionally keeps MAVSDK optional: unit tests and alternate
transports can provide any async client implementing ``PX4ParameterClient``.
SITL launchers may instead inject the environment returned by
``build_px4_parameter_environment`` and then perform readback verification.
"""

from __future__ import annotations

import asyncio
import json
import math
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol

from app.parameters import CATALOG_VERSION, get_parameter, normalize_px4_version
from app.parameters.models import Number
from app.parameters.validation import validate_parameter_values

EVIDENCE_SCHEMA_VERSION = "dronedream.px4_parameter_evidence.v1"
REQUESTED_EVIDENCE_NAME = "px4_parameters.requested.json"
BEFORE_EVIDENCE_NAME = "px4_parameters.before.json"
APPLIED_EVIDENCE_NAME = "px4_parameters.applied.json"


class ParameterApplicationError(RuntimeError):
    """Base class for a PX4 parameter transport or evidence failure."""


class ParameterReadbackError(ParameterApplicationError):
    """Raised when PX4 readback differs from the requested value."""

    def __init__(self, mismatches: Mapping[str, Mapping[str, object]]) -> None:
        self.mismatches = dict(mismatches)
        super().__init__(f"PX4 parameter readback mismatch: {', '.join(self.mismatches)}")


class PX4ParameterClient(Protocol):
    """Small async interface implemented by MAVSDK and deterministic fakes."""

    async def get_parameter(self, name: str, value_type: str) -> Number:
        """Read one PX4 parameter."""

    async def set_parameter(self, name: str, value: Number, value_type: str) -> None:
        """Set one PX4 parameter."""


class MavsdkParameterClient:
    """Adapter over ``mavsdk.System.param`` without a hard package dependency."""

    def __init__(self, parameter_api: Any, *, owner: Any | None = None) -> None:
        self._parameter_api = parameter_api
        # Keep the System object alive for the duration of the transaction.
        self._owner = owner

    async def get_parameter(self, name: str, value_type: str) -> Number:
        if value_type == "int":
            return int(await self._parameter_api.get_param_int(name))
        return float(await self._parameter_api.get_param_float(name))

    async def set_parameter(self, name: str, value: Number, value_type: str) -> None:
        if value_type == "int":
            await self._parameter_api.set_param_int(name, int(value))
            return
        await self._parameter_api.set_param_float(name, float(value))

    def close(self) -> None:
        """Release an embedded MAVSDK server before the Offboard client starts."""

        stop_server = getattr(self._owner, "_stop_mavsdk_server", None)
        if callable(stop_server):
            stop_server()
        self._owner = None


@dataclass(frozen=True)
class ParameterApplicationResult:
    """Verified parameter transaction returned to the wrapper."""

    requested: dict[str, Number]
    before: dict[str, Number | str | None]
    applied: dict[str, Number]
    transport: str
    verified: bool


def build_px4_parameter_environment(
    requested: Mapping[str, object],
    *,
    px4_version: str | None = None,
    enforce_safe_bounds: bool = True,
) -> dict[str, str]:
    """Build official SITL ``PX4_PARAM_<name>`` launch overrides."""

    normalized = validate_parameter_values(
        requested,
        px4_version=px4_version,
        enforce_safe_bounds=enforce_safe_bounds,
    )
    result: dict[str, str] = {}
    for name, value in normalized.items():
        definition = get_parameter(name, px4_version=px4_version)
        assert definition is not None
        rendered = (
            str(int(value)) if definition.value_type == "int" else format(float(value), ".15g")
        )
        result[f"PX4_PARAM_{name}"] = rendered
    return result


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _atomic_json_dump(path: Path, payload: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False),
        encoding="utf-8",
    )
    temporary.replace(path)


def _evidence_payload(
    *,
    kind: str,
    values: Mapping[str, object],
    transport: str,
    px4_version: str,
    context: Mapping[str, object] | None,
    status: str = "ok",
    verification: Mapping[str, object] | None = None,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "schema_version": EVIDENCE_SCHEMA_VERSION,
        "catalog_version": CATALOG_VERSION,
        "px4_version": px4_version,
        "kind": kind,
        "transport": transport,
        "status": status,
        "captured_at": _now_iso(),
        "values": dict(values),
        "context": dict(context or {}),
    }
    if verification is not None:
        payload["verification"] = dict(verification)
    return payload


def _write_evidence(
    evidence_dir: Path,
    *,
    filename: str,
    kind: str,
    values: Mapping[str, object],
    transport: str,
    px4_version: str,
    context: Mapping[str, object] | None,
    status: str = "ok",
    verification: Mapping[str, object] | None = None,
) -> None:
    _atomic_json_dump(
        evidence_dir / filename,
        _evidence_payload(
            kind=kind,
            values=values,
            transport=transport,
            px4_version=px4_version,
            context=context,
            status=status,
            verification=verification,
        ),
    )


async def _read_all(
    client: PX4ParameterClient,
    names: list[str],
    *,
    px4_version: str,
) -> dict[str, Number]:
    values: dict[str, Number] = {}
    for name in names:
        definition = get_parameter(name, px4_version=px4_version)
        assert definition is not None
        value = await client.get_parameter(name, definition.value_type)
        values[name] = int(value) if definition.value_type == "int" else float(value)
    return values


def _readback_mismatches(
    requested: Mapping[str, Number],
    applied: Mapping[str, Number],
    *,
    px4_version: str,
) -> dict[str, dict[str, object]]:
    mismatches: dict[str, dict[str, object]] = {}
    for name, expected in requested.items():
        definition = get_parameter(name, px4_version=px4_version)
        assert definition is not None
        actual = applied.get(name)
        tolerance = (
            0.0 if definition.value_type == "int" else max(float(definition.step) / 10.0, 1e-6)
        )
        matches = actual is not None and math.isclose(
            float(actual),
            float(expected),
            rel_tol=0.0,
            abs_tol=tolerance,
        )
        if not matches:
            mismatches[name] = {
                "requested": expected,
                "applied": actual,
                "absolute_tolerance": tolerance,
            }
    return mismatches


async def apply_and_verify_parameters(
    requested: Mapping[str, object],
    client: PX4ParameterClient,
    evidence_dir: Path,
    *,
    px4_version: str | None = None,
    transport: str = "mavsdk",
    context: Mapping[str, object] | None = None,
    enforce_safe_bounds: bool = True,
) -> ParameterApplicationResult:
    """Read current values, apply a request, read back, and persist evidence."""

    normalized_version = normalize_px4_version(px4_version)
    normalized = validate_parameter_values(
        requested,
        px4_version=normalized_version,
        enforce_safe_bounds=enforce_safe_bounds,
    )
    names = list(normalized)
    _write_evidence(
        evidence_dir,
        filename=REQUESTED_EVIDENCE_NAME,
        kind="requested",
        values=normalized,
        transport=transport,
        px4_version=normalized_version,
        context=context,
    )

    before: dict[str, Number] = {}
    applied: dict[str, Number] = {}
    try:
        before = await _read_all(client, names, px4_version=normalized_version)
        _write_evidence(
            evidence_dir,
            filename=BEFORE_EVIDENCE_NAME,
            kind="before",
            values=before,
            transport=transport,
            px4_version=normalized_version,
            context=context,
        )
        for name, value in normalized.items():
            definition = get_parameter(name, px4_version=normalized_version)
            assert definition is not None
            await client.set_parameter(name, value, definition.value_type)
        applied = await _read_all(client, names, px4_version=normalized_version)
    except Exception as exc:
        if not (evidence_dir / BEFORE_EVIDENCE_NAME).exists():
            _write_evidence(
                evidence_dir,
                filename=BEFORE_EVIDENCE_NAME,
                kind="before",
                values=before,
                transport=transport,
                px4_version=normalized_version,
                context=context,
                status="error",
                verification={"error": str(exc)},
            )
        _write_evidence(
            evidence_dir,
            filename=APPLIED_EVIDENCE_NAME,
            kind="applied",
            values=applied,
            transport=transport,
            px4_version=normalized_version,
            context=context,
            status="error",
            verification={"verified": False, "error": str(exc)},
        )
        raise ParameterApplicationError(f"PX4 parameter transaction failed: {exc}") from exc

    mismatches = _readback_mismatches(normalized, applied, px4_version=normalized_version)
    _write_evidence(
        evidence_dir,
        filename=APPLIED_EVIDENCE_NAME,
        kind="applied",
        values=applied,
        transport=transport,
        px4_version=normalized_version,
        context=context,
        status="mismatch" if mismatches else "ok",
        verification={"verified": not mismatches, "mismatches": mismatches},
    )
    if mismatches:
        raise ParameterReadbackError(mismatches)
    before_result: dict[str, Number | str | None] = dict(before)
    return ParameterApplicationResult(
        normalized,
        before_result,
        applied,
        transport,
        True,
    )


async def verify_environment_parameters(
    requested: Mapping[str, object],
    client: PX4ParameterClient,
    evidence_dir: Path,
    *,
    previous_environment: Mapping[str, str] | None = None,
    px4_version: str | None = None,
    context: Mapping[str, object] | None = None,
    enforce_safe_bounds: bool = True,
) -> ParameterApplicationResult:
    """Verify parameters injected at PX4 process start through environment vars."""

    normalized_version = normalize_px4_version(px4_version)
    normalized = validate_parameter_values(
        requested,
        px4_version=normalized_version,
        enforce_safe_bounds=enforce_safe_bounds,
    )
    previous_environment = previous_environment or {}
    before: dict[str, Number | str | None] = {
        name: previous_environment.get(f"PX4_PARAM_{name}") for name in normalized
    }
    _write_evidence(
        evidence_dir,
        filename=REQUESTED_EVIDENCE_NAME,
        kind="requested",
        values=normalized,
        transport="environment",
        px4_version=normalized_version,
        context=context,
    )
    _write_evidence(
        evidence_dir,
        filename=BEFORE_EVIDENCE_NAME,
        kind="before_environment_override",
        values=before,
        transport="environment",
        px4_version=normalized_version,
        context=context,
    )
    applied: dict[str, Number] = {}
    try:
        applied = await _read_all(client, list(normalized), px4_version=normalized_version)
    except Exception as exc:
        _write_evidence(
            evidence_dir,
            filename=APPLIED_EVIDENCE_NAME,
            kind="applied",
            values=applied,
            transport="environment",
            px4_version=normalized_version,
            context=context,
            status="error",
            verification={"verified": False, "error": str(exc)},
        )
        raise ParameterApplicationError(f"PX4 environment readback failed: {exc}") from exc
    mismatches = _readback_mismatches(normalized, applied, px4_version=normalized_version)
    _write_evidence(
        evidence_dir,
        filename=APPLIED_EVIDENCE_NAME,
        kind="applied",
        values=applied,
        transport="environment",
        px4_version=normalized_version,
        context=context,
        status="mismatch" if mismatches else "ok",
        verification={"verified": not mismatches, "mismatches": mismatches},
    )
    if mismatches:
        raise ParameterReadbackError(mismatches)
    return ParameterApplicationResult(normalized, before, applied, "environment", True)


def write_simulated_parameter_evidence(
    requested: Mapping[str, object],
    evidence_dir: Path,
    *,
    px4_version: str | None = None,
    context: Mapping[str, object] | None = None,
    enforce_safe_bounds: bool = True,
) -> ParameterApplicationResult:
    """Write explicitly simulated evidence for deterministic site dry-runs."""

    normalized_version = normalize_px4_version(px4_version)
    normalized = validate_parameter_values(
        requested,
        px4_version=normalized_version,
        enforce_safe_bounds=enforce_safe_bounds,
    )
    for filename, kind, values in (
        (REQUESTED_EVIDENCE_NAME, "requested", normalized),
        (BEFORE_EVIDENCE_NAME, "before", {name: None for name in normalized}),
        (APPLIED_EVIDENCE_NAME, "applied", normalized),
    ):
        verification = (
            {"verified": True, "simulated": True, "mismatches": {}}
            if filename == APPLIED_EVIDENCE_NAME
            else None
        )
        _write_evidence(
            evidence_dir,
            filename=filename,
            kind=kind,
            values=values,
            transport="site_dry_run",
            px4_version=normalized_version,
            context=context,
            status="simulated",
            verification=verification,
        )
    return ParameterApplicationResult(
        normalized,
        {name: None for name in normalized},
        normalized.copy(),
        "site_dry_run",
        True,
    )


def _write_connection_failure_evidence(
    requested: Mapping[str, object],
    evidence_dir: Path,
    *,
    transport: str,
    error: Exception,
    previous_environment: Mapping[str, str] | None,
    px4_version: str | None,
    context: Mapping[str, object] | None,
    enforce_safe_bounds: bool,
) -> None:
    normalized_version = normalize_px4_version(px4_version)
    normalized = validate_parameter_values(
        requested,
        px4_version=normalized_version,
        enforce_safe_bounds=enforce_safe_bounds,
    )
    before: dict[str, object]
    before_kind = "before"
    if transport == "environment":
        previous_environment = previous_environment or {}
        before = {name: previous_environment.get(f"PX4_PARAM_{name}") for name in normalized}
        before_kind = "before_environment_override"
    else:
        before = {}
    _write_evidence(
        evidence_dir,
        filename=REQUESTED_EVIDENCE_NAME,
        kind="requested",
        values=normalized,
        transport=transport,
        px4_version=normalized_version,
        context=context,
    )
    _write_evidence(
        evidence_dir,
        filename=BEFORE_EVIDENCE_NAME,
        kind=before_kind,
        values=before,
        transport=transport,
        px4_version=normalized_version,
        context=context,
        status="not_captured" if transport == "mavsdk" else "ok",
    )
    _write_evidence(
        evidence_dir,
        filename=APPLIED_EVIDENCE_NAME,
        kind="applied",
        values={},
        transport=transport,
        px4_version=normalized_version,
        context=context,
        status="error",
        verification={"verified": False, "error": str(error), "stage": "connection"},
    )


async def connect_mavsdk_parameter_client(
    connection: str,
    *,
    timeout_seconds: float = 15.0,
) -> MavsdkParameterClient:
    """Connect MAVSDK lazily and return its parameter-only adapter."""

    try:
        from mavsdk import System
    except ModuleNotFoundError as exc:  # pragma: no cover - depends on simulator image
        raise ParameterApplicationError("mavsdk is required for PX4 parameter readback") from exc

    system = System()
    await system.connect(system_address=connection)

    async def _wait_connected() -> None:
        async for state in system.core.connection_state():
            if state.is_connected:
                return

    try:
        await asyncio.wait_for(_wait_connected(), timeout=timeout_seconds)
    except TimeoutError as exc:
        raise ParameterApplicationError(
            f"MAVSDK parameter connection timed out after {timeout_seconds}s"
        ) from exc
    return MavsdkParameterClient(system.param, owner=system)


async def apply_parameters_with_mavsdk(
    requested: Mapping[str, object],
    evidence_dir: Path,
    *,
    connection: str,
    timeout_seconds: float = 15.0,
    px4_version: str | None = None,
    context: Mapping[str, object] | None = None,
    enforce_safe_bounds: bool = True,
) -> ParameterApplicationResult:
    try:
        client = await connect_mavsdk_parameter_client(connection, timeout_seconds=timeout_seconds)
    except Exception as exc:
        _write_connection_failure_evidence(
            requested,
            evidence_dir,
            transport="mavsdk",
            error=exc,
            previous_environment=None,
            px4_version=px4_version,
            context=context,
            enforce_safe_bounds=enforce_safe_bounds,
        )
        raise
    try:
        return await apply_and_verify_parameters(
            requested,
            client,
            evidence_dir,
            px4_version=px4_version,
            context=context,
            enforce_safe_bounds=enforce_safe_bounds,
        )
    finally:
        client.close()


async def verify_environment_parameters_with_mavsdk(
    requested: Mapping[str, object],
    evidence_dir: Path,
    *,
    connection: str,
    previous_environment: Mapping[str, str] | None = None,
    timeout_seconds: float = 15.0,
    px4_version: str | None = None,
    context: Mapping[str, object] | None = None,
    enforce_safe_bounds: bool = True,
) -> ParameterApplicationResult:
    try:
        client = await connect_mavsdk_parameter_client(connection, timeout_seconds=timeout_seconds)
    except Exception as exc:
        _write_connection_failure_evidence(
            requested,
            evidence_dir,
            transport="environment",
            error=exc,
            previous_environment=previous_environment,
            px4_version=px4_version,
            context=context,
            enforce_safe_bounds=enforce_safe_bounds,
        )
        raise
    try:
        return await verify_environment_parameters(
            requested,
            client,
            evidence_dir,
            previous_environment=previous_environment,
            px4_version=px4_version,
            context=context,
            enforce_safe_bounds=enforce_safe_bounds,
        )
    finally:
        client.close()
