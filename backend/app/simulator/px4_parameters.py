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
from app.parameters.models import Number, ParameterDefinition
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


def _require_parameter_definition(
    name: str,
    *,
    px4_version: str | None,
) -> ParameterDefinition:
    definition = get_parameter(name, px4_version=px4_version)
    if definition is None:
        raise ParameterApplicationError(
            f"Validated PX4 parameter {name!r} is missing from catalog version "
            f"{px4_version or 'default'}"
        )
    return definition


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

        owner = self._owner
        self._owner = None
        stop_server = getattr(owner, "_stop_mavsdk_server", None)
        if callable(stop_server):
            stop_server()


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
        definition = _require_parameter_definition(name, px4_version=px4_version)
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
        definition = _require_parameter_definition(name, px4_version=px4_version)
        raw_value = await client.get_parameter(name, definition.value_type)
        if (
            isinstance(raw_value, bool)
            or not isinstance(raw_value, int | float)
            or not math.isfinite(float(raw_value))
        ):
            raise ParameterApplicationError(
                f"invalid PX4 parameter readback for {name}: expected a finite "
                f"{definition.value_type} value"
            )
        if definition.value_type == "int":
            if not float(raw_value).is_integer():
                raise ParameterApplicationError(
                    f"invalid PX4 parameter readback for {name}: expected an integer value"
                )
            values[name] = int(raw_value)
        else:
            values[name] = float(raw_value)
    return values


def _readback_mismatches(
    requested: Mapping[str, Number],
    applied: Mapping[str, Number],
    *,
    px4_version: str,
) -> dict[str, dict[str, object]]:
    mismatches: dict[str, dict[str, object]] = {}
    for name, expected in requested.items():
        definition = _require_parameter_definition(name, px4_version=px4_version)
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


def _reject_reboot_required_live_parameters(
    requested: Mapping[str, Number],
    *,
    px4_version: str,
) -> None:
    """Prevent a live write from masquerading as an applied reboot parameter.

    ``PX4ParameterClient`` intentionally exposes only get/set operations.  It
    cannot restart PX4 and re-establish the vehicle connection, so accepting a
    reboot-policy parameter here would let the same flight continue with an
    unverified old value.  Startup-environment injection remains supported by
    :func:`build_px4_parameter_environment` and is verified separately after
    the new SITL process connects.
    """

    requires_restart: list[str] = []
    for name in requested:
        definition = _require_parameter_definition(name, px4_version=px4_version)
        if definition.requires_reboot or definition.apply_policy == "reboot":
            requires_restart.append(name)
    if not requires_restart:
        return
    rendered = ", ".join(sorted(requires_restart))
    raise ParameterApplicationError(
        "PX4 live parameter application cannot safely apply reboot-required "
        f"parameters: {rendered}. Start a fresh SITL process with PX4_PARAM_* "
        "startup overrides, then perform readback verification before flight."
    )


async def _restore_parameters(
    client: PX4ParameterClient,
    before: Mapping[str, Number],
    written_names: list[str],
    *,
    px4_version: str,
) -> dict[str, str]:
    """Best-effort rollback with readback verification."""

    errors: dict[str, str] = {}
    for name in reversed(written_names):
        definition = _require_parameter_definition(name, px4_version=px4_version)
        try:
            await client.set_parameter(name, before[name], definition.value_type)
        except Exception as exc:  # pragma: no cover - transport-specific failure
            errors[name] = str(exc)
    for name in reversed(written_names):
        if name in errors:
            continue
        definition = _require_parameter_definition(name, px4_version=px4_version)
        try:
            actual = await client.get_parameter(name, definition.value_type)
            mismatch = _readback_mismatches(
                {name: before[name]},
                {name: actual},
                px4_version=px4_version,
            )
            if mismatch:
                errors[name] = "rollback readback did not match the original value"
        except Exception as exc:  # pragma: no cover - transport-specific failure
            errors[name] = f"rollback readback failed: {exc}"
    return errors


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
    written_names: list[str] = []
    try:
        _reject_reboot_required_live_parameters(
            normalized,
            px4_version=normalized_version,
        )
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
            definition = _require_parameter_definition(
                name,
                px4_version=normalized_version,
            )
            # Track before awaiting: an acknowledgement can be lost after PX4
            # has already committed the value. Restoring the old value is safe
            # even when the failed write never reached the vehicle.
            written_names.append(name)
            await client.set_parameter(name, value, definition.value_type)
        applied = await _read_all(client, names, px4_version=normalized_version)
    except Exception as exc:
        transaction_rollback_errors = await _restore_parameters(
            client,
            before,
            written_names,
            px4_version=normalized_version,
        )
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
            verification={
                "verified": False,
                "error": str(exc),
                "rollback_attempted": bool(written_names),
                "rollback_succeeded": bool(written_names) and not transaction_rollback_errors,
                "rollback_errors": transaction_rollback_errors,
            },
        )
        raise ParameterApplicationError(f"PX4 parameter transaction failed: {exc}") from exc

    mismatches = _readback_mismatches(normalized, applied, px4_version=normalized_version)
    mismatch_rollback_errors: dict[str, str] = {}
    if mismatches:
        mismatch_rollback_errors = await _restore_parameters(
            client,
            before,
            written_names,
            px4_version=normalized_version,
        )
    _write_evidence(
        evidence_dir,
        filename=APPLIED_EVIDENCE_NAME,
        kind="applied",
        values=applied,
        transport=transport,
        px4_version=normalized_version,
        context=context,
        status="mismatch" if mismatches else "ok",
        verification={
            "verified": not mismatches,
            "mismatches": mismatches,
            **(
                {
                    "rollback_attempted": True,
                    "rollback_succeeded": not mismatch_rollback_errors,
                    "rollback_errors": mismatch_rollback_errors,
                }
                if mismatches
                else {}
            ),
        },
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
    reconcile_live_mismatches: bool = False,
) -> ParameterApplicationResult:
    """Verify parameters injected at PX4 process start through environment vars.

    Some airframe startup scripts apply vehicle defaults after PX4 consumes the
    ``PX4_PARAM_*`` overrides. A real launcher may therefore opt into a narrow
    post-start reconciliation pass for live-settable values. Reboot-required
    parameters are never written live: a mismatch for one of those remains a
    fail-closed startup error.
    """

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
    initial_applied = dict(applied)
    initial_mismatches = _readback_mismatches(
        normalized,
        initial_applied,
        px4_version=normalized_version,
    )
    reconciled_names: list[str] = []
    reconciliation_rollback_errors: dict[str, str] = {}
    if initial_mismatches and reconcile_live_mismatches:
        reboot_mismatches: list[str] = []
        for name in initial_mismatches:
            definition = _require_parameter_definition(
                name,
                px4_version=normalized_version,
            )
            if definition.requires_reboot or definition.apply_policy == "reboot":
                reboot_mismatches.append(name)
        if not reboot_mismatches:
            try:
                for name in initial_mismatches:
                    definition = _require_parameter_definition(
                        name,
                        px4_version=normalized_version,
                    )
                    # Track before awaiting: PX4 may commit a write even if the
                    # acknowledgement is lost, so rollback must remain possible.
                    reconciled_names.append(name)
                    await client.set_parameter(name, normalized[name], definition.value_type)
                applied = await _read_all(client, list(normalized), px4_version=normalized_version)
            except Exception as exc:
                reconciliation_rollback_errors = await _restore_parameters(
                    client,
                    initial_applied,
                    reconciled_names,
                    px4_version=normalized_version,
                )
                _write_evidence(
                    evidence_dir,
                    filename=APPLIED_EVIDENCE_NAME,
                    kind="applied",
                    values=applied,
                    transport="environment",
                    px4_version=normalized_version,
                    context=context,
                    status="error",
                    verification={
                        "verified": False,
                        "error": str(exc),
                        "stage": "post_airframe_live_reconciliation",
                        "initial_readback": initial_applied,
                        "initial_mismatches": initial_mismatches,
                        "reconciled_parameters": reconciled_names,
                        "rollback_attempted": bool(reconciled_names),
                        "rollback_succeeded": bool(reconciled_names)
                        and not reconciliation_rollback_errors,
                        "rollback_errors": reconciliation_rollback_errors,
                    },
                )
                raise ParameterApplicationError(
                    f"PX4 post-airframe parameter reconciliation failed: {exc}"
                ) from exc
    mismatches = _readback_mismatches(normalized, applied, px4_version=normalized_version)
    if mismatches and reconciled_names:
        reconciliation_rollback_errors = await _restore_parameters(
            client,
            initial_applied,
            reconciled_names,
            px4_version=normalized_version,
        )
    _write_evidence(
        evidence_dir,
        filename=APPLIED_EVIDENCE_NAME,
        kind="applied",
        values=applied,
        transport="environment",
        px4_version=normalized_version,
        context=context,
        status="mismatch" if mismatches else "ok",
        verification={
            "verified": not mismatches,
            "mismatches": mismatches,
            "initial_readback": initial_applied,
            "initial_mismatches": initial_mismatches,
            "reconciliation_transport": "mavsdk" if reconciled_names else "none",
            "reconciled_parameters": reconciled_names,
            **(
                {
                    "rollback_attempted": True,
                    "rollback_succeeded": not reconciliation_rollback_errors,
                    "rollback_errors": reconciliation_rollback_errors,
                }
                if mismatches and reconciled_names
                else {}
            ),
        },
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

    if (
        isinstance(timeout_seconds, bool)
        or not isinstance(timeout_seconds, (int, float))
        or not math.isfinite(timeout_seconds)
        or timeout_seconds <= 0
    ):
        raise ParameterApplicationError(
            "MAVSDK parameter timeout must be a finite number greater than zero"
        )

    try:
        from mavsdk import System
    except ModuleNotFoundError as exc:  # pragma: no cover - depends on simulator image
        raise ParameterApplicationError("mavsdk is required for PX4 parameter readback") from exc

    system = System()
    try:
        await system.connect(system_address=connection)

        async def _wait_connected() -> None:
            async for state in system.core.connection_state():
                if state.is_connected:
                    return

        await asyncio.wait_for(_wait_connected(), timeout=timeout_seconds)
    except BaseException as exc:
        # ``mavsdk.System`` may have spawned an embedded mavsdk_server before
        # connection succeeds. A timeout/cancellation must release it even
        # though no MavsdkParameterClient is returned to the caller's finally.
        stop_server = getattr(system, "_stop_mavsdk_server", None)
        if callable(stop_server):
            stop_server()
        if isinstance(exc, TimeoutError):
            raise ParameterApplicationError(
                f"MAVSDK parameter connection timed out after {timeout_seconds}s"
            ) from exc
        raise
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
    reconcile_live_mismatches: bool = False,
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
            reconcile_live_mismatches=reconcile_live_mismatches,
        )
    finally:
        client.close()
