#!/usr/bin/env python3
"""Site-specific PX4/Gazebo launch wrapper used by px4_gazebo_runner.py.

This script is intentionally a thin, configurable launcher layer:
- CI/dev dry-run mode emits deterministic fixture telemetry.
- Real mode launches a local PX4/Gazebo command configured by env vars.
- Telemetry validation/normalization guarantees telemetry JSON exists on success.
"""

from __future__ import annotations

import argparse
import ast
import asyncio
import contextlib
import copy
import hashlib
import ipaddress
import json
import math
import numbers
import os
import re
import shlex
import shutil
import signal
import socket
import stat
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

# This wrapper is launched as a standalone script. Python consequently places
# ``scripts/simulators`` (not the repository root) first on ``sys.path``. A
# bundled Runtime can also have an older ``app`` distribution installed in its
# virtual environment, so a fallback-only insertion is insufficient: that
# installed package may import successfully while missing the checkout's newer
# simulator contracts. Prefer the backend adjacent to this exact wrapper before
# importing any ``app`` module, matching px4_gazebo_runner.py's source binding.
_BACKEND_ROOT = Path(__file__).resolve().parents[2] / "backend"
if _BACKEND_ROOT.is_dir():
    _backend_root_text = str(_BACKEND_ROOT)
    while _backend_root_text in sys.path:
        sys.path.remove(_backend_root_text)
    sys.path.insert(0, _backend_root_text)

DEFAULT_MAKE_TARGET = "gz_x500"
DEFAULT_RUN_SECONDS = 30
DEFAULT_READY_TIMEOUT_SECONDS = 30
DEFAULT_SITE_DRY_RUN = False
DEFAULT_TELEMETRY_MODE = "json"
DEFAULT_ENABLE_OFFBOARD_EXECUTOR = True
DEFAULT_OFFBOARD_CONNECTION = "udp://:14540"
DEFAULT_OFFBOARD_SETPOINT_RATE_HZ = 10.0
DEFAULT_OFFBOARD_TAKEOFF_TIMEOUT_SECONDS = 30.0
DEFAULT_OFFBOARD_TRACK_TIMEOUT_SECONDS = 120.0
DEFAULT_LAUNCH_GUI_CLIENT = False
DEFAULT_GUI_COMMAND = (
    f"{shlex.quote(str(Path(__file__).resolve().parent / 'gazebo_gui_client.sh'))}"
)
DEFAULT_GUI_START_DELAY_SECONDS = 5.0
DEFAULT_GUI_WAIT_TIMEOUT_SECONDS = 15.0
DEFAULT_REQUIRE_GUI_CLIENT = False
DEFAULT_DRAW_TRACK_MARKER = False
DEFAULT_TRACK_MARKER_START_DELAY_SECONDS = 2.0
DEFAULT_REQUIRE_TRACK_MARKER = False
DEFAULT_TRACK_MARKER_Z_OFFSET = 0.03
DEFAULT_TRACK_MARKER_COLOR = "0 0.8 1 1"
DEFAULT_TRACK_MARKER_LINE_WIDTH = 0.08
DEFAULT_TRACK_MARKER_MODE = "line_strip"
WINDOWS_PROCESS_TREE_TERMINATION_TIMEOUT_SECONDS = 30.0
MAX_JSON_BYTES = 16 * 1024 * 1024
MAX_TELEMETRY_SAMPLES = 50_000
MAX_ULOG_BYTES = 1024 * 1024 * 1024
MAX_GENERATED_WORLD_SDF_BYTES = 16 * 1024 * 1024
MAX_TRUSTED_LOCAL_XML_BYTES = 16 * 1024 * 1024
RETAINED_ULOG_NAME = "px4_source.ulg"
WIND_EFFECTS_PLUGIN_FILENAME = "gz-sim-wind-effects-system"
WIND_EFFECTS_PLUGIN_NAME = "gz::sim::systems::WindEffects"
JOINT_STATE_PUBLISHER_PLUGIN_FILENAME = "gz-sim-joint-state-publisher-system"
JOINT_STATE_PUBLISHER_PLUGIN_NAME = "gz::sim::systems::JointStatePublisher"
_FORBIDDEN_XML_DECLARATION = re.compile(rb"<!\s*(?:DOCTYPE|ENTITY)\b", re.IGNORECASE)


def _running_under_wsl() -> bool:
    """Return whether this process is running inside Windows Subsystem for Linux."""

    if os.environ.get("WSL_INTEROP", "").strip() or os.environ.get("WSL_DISTRO_NAME", "").strip():
        return True
    try:
        release = Path("/proc/sys/kernel/osrelease").read_text(encoding="utf-8").lower()
    except OSError:
        return False
    return "microsoft" in release or "wsl" in release


def _gazebo_transport_ip() -> str:
    """Choose one Gazebo Transport interface shared by every Trial child.

    An explicit site setting remains authoritative.  Otherwise only WSL uses
    its default-route source address: Gazebo Transport discovery can
    intermittently omit cross-process subscribers when every process is bound
    to loopback.  Native Linux and Windows retain the conservative loopback
    default.  The UDP connect selects a route but sends no packet.
    """

    configured = os.environ.get("GZ_IP", "").strip()
    if configured:
        try:
            address = ipaddress.ip_address(configured)
        except ValueError as exc:
            raise ValueError("GZ_IP must be a valid IPv4 address") from exc
        if address.version != 4 or address.is_unspecified or address.is_multicast:
            raise ValueError("GZ_IP must be a usable unicast IPv4 address")
        return configured
    if not _running_under_wsl():
        return "127.0.0.1"

    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        probe.connect(("192.0.2.1", 9))
        candidate = str(probe.getsockname()[0]).strip()
        address = ipaddress.ip_address(candidate)
        if address.version == 4 and not address.is_unspecified and not address.is_multicast:
            return candidate
    except (OSError, ValueError, IndexError):
        pass
    finally:
        probe.close()
    return "127.0.0.1"


REQUIRED_SAMPLE_KEYS = (
    "t",
    "x",
    "y",
    "z",
    "vx",
    "vy",
    "vz",
    "yaw",
    "armed",
    "mode",
    "crashed",
)


class ScenarioEffectUnsupportedError(RuntimeError):
    """The running Gazebo instance cannot provide a requested capability."""


def _checked_xml_bytes(raw: bytes, *, byte_limit: int, context: str) -> bytes:
    if len(raw) > byte_limit:
        raise RuntimeError(f"{context} exceeds the XML evidence limit")
    if _FORBIDDEN_XML_DECLARATION.search(raw):
        raise RuntimeError(f"{context} contains a forbidden DTD or entity declaration")
    return raw


def _parse_trusted_local_xml(
    path: Path,
    *,
    trusted_root: Path,
    context: str,
) -> ET.ElementTree:
    """Parse bounded XML only after proving it remains inside a trusted local root."""

    try:
        resolved_root = trusted_root.resolve(strict=True)
        resolved_path = path.resolve(strict=True)
        resolved_path.relative_to(resolved_root)
    except (OSError, ValueError) as exc:
        raise RuntimeError(f"{context} is outside its trusted local root") from exc
    if not resolved_path.is_file() or resolved_path.is_symlink():
        raise RuntimeError(f"{context} is not a trusted regular file")
    try:
        raw = resolved_path.read_bytes()
    except OSError as exc:
        raise RuntimeError(f"{context} could not be read") from exc
    checked = _checked_xml_bytes(
        raw,
        byte_limit=MAX_TRUSTED_LOCAL_XML_BYTES,
        context=context,
    )
    try:
        # ElementTree is safe here because DTD/entity declarations are rejected,
        # bytes are bounded, and the resolved file is confined to a trusted root.
        return ET.ElementTree(ET.fromstring(checked))  # noqa: S314
    except ET.ParseError as exc:
        raise RuntimeError(f"{context} is invalid XML") from exc


def _parse_bounded_xml_text(
    value: str,
    *,
    byte_limit: int,
    context: str,
) -> ET.Element:
    raw = _checked_xml_bytes(
        value.encode("utf-8"),
        byte_limit=byte_limit,
        context=context,
    )
    try:
        # The encoded payload is bounded and DTD/entity declarations are rejected
        # before the standard-library parser sees it.
        return ET.fromstring(raw)  # noqa: S314
    except ET.ParseError as exc:
        raise RuntimeError(f"{context} is invalid XML") from exc


def _parse_bool(raw: str | None, *, default: bool) -> bool:
    if raw is None:
        return default
    normalized = raw.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"invalid boolean value: {raw!r}")


def _make_target_for_vehicle(vehicle: str) -> str:
    """Resolve a per-trial Gazebo target with an explicit force escape hatch."""

    configured = os.environ.get("PX4_MAKE_TARGET", "").strip()
    if configured and _parse_bool(os.environ.get("PX4_FORCE_MAKE_TARGET"), default=False):
        return configured
    model = vehicle.strip()
    if model.startswith("gz_"):
        return model
    if model in {"x500", "x500_depth", "x500_vision"}:
        return f"gz_{model}"
    return configured or DEFAULT_MAKE_TARGET


def _parse_int(raw: str | None, *, default: int) -> int:
    if raw is None or not raw.strip():
        return default
    return int(raw)


def _parse_float(raw: str | None, *, default: float) -> float:
    if raw is None or not raw.strip():
        return default
    value = float(raw)
    if not math.isfinite(value):
        raise ValueError("numeric environment values must be finite")
    return value


def _subprocess_text(value: str | bytes | None) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value or ""


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Local PX4/Gazebo launch wrapper")
    parser.add_argument("--run-dir", required=True, type=Path)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--params", required=True, type=Path)
    parameter_request_path = os.environ.get("PX4_PARAMETER_REQUEST_PATH", "").strip()
    parser.add_argument(
        "--px4-params",
        type=Path,
        default=Path(parameter_request_path) if parameter_request_path else None,
    )
    parser.add_argument("--track", required=True, type=Path)
    parser.add_argument("--telemetry", required=True, type=Path)
    parser.add_argument("--stdout-log", required=True, type=Path)
    parser.add_argument("--stderr-log", required=True, type=Path)
    parser.add_argument("--vehicle", required=True)
    parser.add_argument(
        "--airframe",
        default=os.environ.get("PX4_TRIAL_AIRFRAME", "").strip(),
    )
    parser.add_argument(
        "--simulator-model",
        default=os.environ.get("PX4_TRIAL_SIMULATOR_MODEL", "").strip(),
    )
    parser.add_argument("--world", required=True)
    parser.add_argument(
        "--px4-version",
        default=os.environ.get("PX4_TRIAL_PX4_VERSION", "main").strip() or "main",
    )
    parser.add_argument("--headless", required=True)
    parser.add_argument("--extra-args", default="")
    return parser.parse_args()


def _json_load(path: Path) -> Any:
    try:
        size = path.stat().st_size
    except OSError as exc:
        raise ValueError(f"could not inspect JSON file {path}: {exc}") from exc
    if size > MAX_JSON_BYTES:
        raise ValueError(f"JSON file exceeds {MAX_JSON_BYTES} bytes: {path}")
    with path.open("rb") as stream:
        content = stream.read(MAX_JSON_BYTES + 1)
    if len(content) > MAX_JSON_BYTES:
        raise ValueError(f"JSON file exceeds {MAX_JSON_BYTES} bytes: {path}")
    try:
        return json.loads(content.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"JSON file is malformed: {path}: {exc}") from exc


def _json_dump(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def _append_log(path: Path, message: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(message.rstrip("\n") + "\n")


def _copy_used_inputs(run_dir: Path, params: Path, track: Path) -> tuple[Any, Any]:
    params_payload = _json_load(params)
    track_payload = _json_load(track)
    _json_dump(run_dir / "controller_params.used.json", params_payload)
    _json_dump(run_dir / "reference_track.used.json", track_payload)
    return params_payload, track_payload


def _load_parameter_engine() -> Any:
    """Import the backend engine when installed or from this repository checkout."""

    try:
        from app.simulator import px4_parameters as engine
    except ModuleNotFoundError:
        backend_root = Path(__file__).resolve().parents[2] / "backend"
        if not backend_root.is_dir():
            raise RuntimeError(
                "DroneDream backend package is required for PX4 parameter application"
            ) from None
        sys.path.insert(0, str(backend_root))
        from app.simulator import px4_parameters as engine
    return engine


def _load_scenario_effect_engine() -> Any:
    """Import the shared request/evidence contract implementation."""

    try:
        from app.simulator import scenario_effects as engine
    except ModuleNotFoundError:
        backend_root = Path(__file__).resolve().parents[2] / "backend"
        if not backend_root.is_dir():
            raise RuntimeError(
                "DroneDream backend package is required for scenario-effect evidence"
            ) from None
        if str(backend_root) not in sys.path:
            sys.path.insert(0, str(backend_root))
        from app.simulator import scenario_effects as engine
    return engine


def _load_scenario_effect_request(
    run_dir: Path,
) -> tuple[Any, dict[str, Any] | None, Path]:
    engine = _load_scenario_effect_engine()
    request_raw = os.environ.get("PX4_TRIAL_SCENARIO_EFFECT_REQUEST_PATH", "").strip()
    evidence_raw = os.environ.get("PX4_TRIAL_SCENARIO_EFFECT_EVIDENCE_PATH", "").strip()
    evidence_path = Path(evidence_raw) if evidence_raw else run_dir / engine.EVIDENCE_ARTIFACT_NAME
    if not request_raw:
        return engine, None, evidence_path
    return engine, engine.load_scenario_effect_request(Path(request_raw)), evidence_path


def _scenario_effect_record(
    effect: dict[str, Any],
    *,
    status: str,
    capability_status: str,
    reason: str,
    evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    record: dict[str, Any] = {
        "effect_id": effect["effect_id"],
        "mechanism": effect["mechanism"],
        "status": status,
        "capability": {
            "status": capability_status,
            "reason": reason,
        },
    }
    if status != "applied":
        record["reason"] = reason
    if evidence is not None:
        record["evidence"] = evidence
    return record


def _write_scenario_effect_evidence(
    engine: Any,
    request: dict[str, Any],
    evidence_path: Path,
    *,
    world: str,
    effects: list[dict[str, Any]],
) -> None:
    payload = engine.build_scenario_effect_evidence(
        request,
        launcher="local_px4_launch_wrapper",
        world=world,
        effects=effects,
    )
    engine.validate_scenario_effect_evidence(request, payload)
    engine.write_json_atomic(evidence_path, payload)


def _load_runtime_effect_records(
    engine: Any,
    request: dict[str, Any],
    *,
    run_dir: Path,
) -> dict[str, dict[str, Any]]:
    profile = engine.compile_bundled_runtime_profile(request)
    if profile is None:
        return {}
    path = run_dir / engine.RUNTIME_EVIDENCE_ARTIFACT_NAME
    if not path.is_file() or path.stat().st_size > engine.MAX_EFFECT_CONTRACT_BYTES:
        raise RuntimeError("flight-timed scenario-effect evidence is missing or too large")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"could not read flight-timed scenario-effect evidence: {exc}") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("flight-timed scenario-effect evidence must be an object")
    if payload.get("schema_version") != "dronedream.scenario_runtime_effects.v1":
        raise RuntimeError("unsupported flight-timed scenario-effect evidence schema")
    if payload.get("request_sha256") != request["request_sha256"]:
        raise RuntimeError("flight-timed scenario-effect evidence request hash mismatch")
    if payload.get("compiled_runtime_profile") != profile:
        raise RuntimeError("flight-timed scenario-effect profile does not match the request")
    status = payload.get("status")
    if status not in {"complete", "failed"}:
        raise RuntimeError("flight-timed scenario-effect evidence status is invalid")
    if status == "failed" and not str(payload.get("error") or "").strip():
        raise RuntimeError("failed flight-timed scenario-effect evidence requires an error")
    records = payload.get("records")
    if not isinstance(records, list):
        raise RuntimeError("flight-timed scenario-effect records must be an array")
    by_id: dict[str, dict[str, Any]] = {}
    for record in records:
        if not isinstance(record, dict) or not isinstance(record.get("effect_id"), str):
            raise RuntimeError("flight-timed scenario-effect record is malformed")
        effect_id = record["effect_id"]
        if effect_id in by_id:
            raise RuntimeError("flight-timed scenario-effect records contain duplicate ids")
        by_id[effect_id] = record
    expected = set(profile["requested_effect_ids"])
    if set(by_id) != expected:
        raise RuntimeError("flight-timed scenario-effect records do not cover the compiled profile")
    expected_record_status = "applied" if status == "complete" else "failed"
    if any(record.get("status") != expected_record_status for record in by_id.values()):
        raise RuntimeError(
            "flight-timed scenario-effect record statuses do not match the evidence status"
        )
    return by_id


def _merge_staged_wind_effect_records(
    engine: Any,
    preliminary_by_id: dict[str, dict[str, Any]],
    runtime_by_id: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    merged = dict(runtime_by_id)
    for effect_id in engine.BUNDLED_WIND_ACTIVATION_EFFECT_IDS:
        preliminary = preliminary_by_id.get(effect_id)
        runtime = runtime_by_id.get(effect_id)
        if preliminary is None or runtime is None or runtime.get("status") != "applied":
            continue
        preliminary_details = preliminary.get("evidence")
        runtime_details = runtime.get("evidence")
        if not isinstance(preliminary_details, dict) or not isinstance(runtime_details, dict):
            raise RuntimeError(f"staged wind evidence for {effect_id} is malformed")
        preliminary_verification = preliminary_details.get("verification")
        runtime_verification = runtime_details.get("verification")
        if not isinstance(preliminary_verification, dict) or not isinstance(
            runtime_verification, dict
        ):
            raise RuntimeError(f"staged wind verification for {effect_id} is malformed")
        structural_observations = [
            item
            for item in preliminary_verification.get("observations", [])
            if not (
                isinstance(item, dict)
                and item.get("kind") == "readback"
                and isinstance(item.get("source"), str)
                and item["source"].endswith("/wind_info")
            )
        ]
        activation_observations = runtime_verification.get("observations")
        if not isinstance(activation_observations, list) or not structural_observations:
            raise RuntimeError(f"staged wind observations for {effect_id} are incomplete")
        combined = copy.deepcopy(runtime)
        combined_details = combined["evidence"]
        for field in ("compiled_wind", "compiled_sdf_profile"):
            if field in preliminary_details:
                combined_details[field] = copy.deepcopy(preliminary_details[field])
        combined_details["verification"] = {
            "status": "verified",
            "method": "gazebo_zero_wind_takeoff_then_post_hover_activation_and_sdf_readback",
            "observations": copy.deepcopy(activation_observations)
            + copy.deepcopy(structural_observations),
        }
        combined["capability"] = {
            "status": "available",
            "reason": (
                "Gazebo started at zero wind, stable hover was verified, then the requested "
                "wind was activated and read back before track entry"
            ),
        }
        merged[effect_id] = combined
    return merged


def _validate_pre_executor_effect_records(
    engine: Any,
    applied_by_id: dict[str, dict[str, Any]],
    *,
    expected_preflight_ids: set[str],
    runtime_effect_ids: set[str],
) -> None:
    """Require every pre-executor record, including staged wind prerequisites.

    Wind is a flight-timed effect, but its zero-wind takeoff and generated-SDF
    proof is collected before the executor starts.  Those preliminary records
    must remain available for the post-hover merge instead of being mistaken
    for unexpected fully-applied runtime effects.
    """

    staged_wind_ids = runtime_effect_ids & set(engine.BUNDLED_WIND_ACTIVATION_EFFECT_IDS)
    expected_ids = expected_preflight_ids | staged_wind_ids
    observed_ids = set(applied_by_id)
    if observed_ids == expected_ids:
        return
    missing = sorted(expected_ids - observed_ids)
    unexpected = sorted(observed_ids - expected_ids)
    details: list[str] = []
    if missing:
        details.append("missing=" + ", ".join(missing))
    if unexpected:
        details.append("unexpected=" + ", ".join(unexpected))
    raise RuntimeError(
        "scenario-effect dispatcher record mismatch before flight: " + "; ".join(details)
    )


def _scenario_effect_failure_records(
    request: dict[str, Any],
    *,
    applied_by_id: dict[str, dict[str, Any]],
    failing_ids: set[str],
    reason: str,
    unsupported: bool,
) -> list[dict[str, Any]]:
    blocked_reason = (
        "another requested scenario effect failed; the bundled launcher does not "
        "continue a partially applied physical scenario"
    )
    records: list[dict[str, Any]] = []
    for effect in request["effects"]:
        effect_id = effect["effect_id"]
        if effect_id in applied_by_id and not applied_by_id[effect_id].get("_activation_pending"):
            records.append(applied_by_id[effect_id])
        elif effect_id in failing_ids:
            records.append(
                _scenario_effect_record(
                    effect,
                    status="unsupported" if unsupported else "failed",
                    capability_status="unsupported" if unsupported else "available",
                    reason=reason,
                )
            )
        else:
            records.append(
                _scenario_effect_record(
                    effect,
                    status="skipped",
                    capability_status=(
                        "available"
                        if effect.get("capability", {}).get("status") == "available"
                        else "unsupported"
                    ),
                    reason=blocked_reason,
                )
            )
    return records


def _preflight_scenario_effects(
    request: dict[str, Any] | None,
    *,
    site_dry_run: bool,
) -> list[dict[str, Any]] | None:
    """Return conclusive unsupported evidence, or None when launch can proceed."""

    if request is None or not request["effects"]:
        return None
    if site_dry_run:
        reason = (
            "PX4_SITE_DRY_RUN produces fixture telemetry and cannot verify physical Gazebo effects"
        )
        return [
            _scenario_effect_record(
                effect,
                status="unsupported",
                capability_status="unsupported",
                reason=reason,
            )
            for effect in request["effects"]
        ]

    engine = _load_scenario_effect_engine()
    bundled_ids = {
        "obstacles",
        *engine.BUNDLED_STEADY_WIND_EFFECT_IDS,
        *engine.BUNDLED_SDF_PROFILE_EFFECT_IDS,
        *engine.BUNDLED_RUNTIME_EFFECT_IDS,
    }
    unavailable = [
        effect
        for effect in request["effects"]
        if effect["effect_id"] not in bundled_ids
        or effect.get("capability", {}).get("status") != "available"
    ]
    if not unavailable:
        return None
    unavailable_ids = {effect["effect_id"] for effect in unavailable}
    blocked_reason = (
        "another requested scenario effect is unsupported; the bundled launcher "
        "does not partially execute a physical scenario"
    )
    return [
        _scenario_effect_record(
            effect,
            status=("unsupported" if effect["effect_id"] in unavailable_ids else "skipped"),
            capability_status=(
                "unsupported" if effect["effect_id"] in unavailable_ids else "available"
            ),
            reason=(
                str(effect.get("capability", {}).get("reason") or "unsupported")
                if effect["effect_id"] in unavailable_ids
                else blocked_reason
            ),
        )
        for effect in request["effects"]
    ]


def _obstacle_sdf(
    obstacle: dict[str, Any],
    *,
    source_index: int,
    run_dir: Path,
) -> tuple[str, Path, str]:
    """Create deterministic SDF for one validated static obstacle."""

    entity_name = f"dronedream_obstacle_{source_index:03d}"
    root = ET.Element("sdf", {"version": "1.9"})
    model = ET.SubElement(root, "model", {"name": entity_name})
    ET.SubElement(model, "static").text = "true"
    ET.SubElement(
        model, "pose"
    ).text = f"{obstacle['x']:g} {obstacle['y']:g} {obstacle['z']:g} 0 0 0"
    link = ET.SubElement(model, "link", {"name": "body"})
    for role in ("collision", "visual"):
        element = ET.SubElement(link, role, {"name": role})
        geometry = ET.SubElement(element, "geometry")
        if obstacle["type"] == "cylinder":
            shape = ET.SubElement(geometry, "cylinder")
            ET.SubElement(shape, "radius").text = f"{obstacle['radius']:g}"
            ET.SubElement(shape, "length").text = f"{obstacle['height']:g}"
        else:
            shape = ET.SubElement(geometry, "box")
            ET.SubElement(
                shape, "size"
            ).text = f"{obstacle['size_x']:g} {obstacle['size_y']:g} {obstacle['size_z']:g}"
    ET.indent(root, space="  ")
    sdf_bytes = ET.tostring(root, encoding="utf-8", xml_declaration=True)
    sdf_dir = run_dir / "scenario_obstacles"
    sdf_dir.mkdir(parents=True, exist_ok=True)
    sdf_path = sdf_dir / f"{entity_name}.sdf"
    sdf_path.write_bytes(sdf_bytes)
    return entity_name, sdf_path, hashlib.sha256(sdf_bytes).hexdigest()


def _protobuf_quote(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _sha256_hex(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _validated_world_name(world: str) -> str:
    if (
        not world
        or len(world) > 128
        or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", world)
        or Path(world).name != world
    ):
        raise ScenarioEffectUnsupportedError(
            "bundled steady wind requires a simple Gazebo world name"
        )
    return world


def _ensure_xml_path(parent: ET.Element, *tags: str) -> ET.Element:
    current = parent
    for tag in tags:
        child = current.find(tag)
        if child is None:
            child = ET.SubElement(current, tag)
        current = child
    return current


def _set_gaussian_stddev(container: ET.Element, value: float) -> None:
    noise = _ensure_xml_path(container, "noise")
    noise.set("type", "gaussian")
    _ensure_xml_path(noise, "mean").text = "0"
    _ensure_xml_path(noise, "stddev").text = f"{value:.17g}"


def _apply_sensor_noise_sdf(
    base_link: ET.Element,
    profile: dict[str, Any],
) -> dict[str, Any]:
    gps = base_link.find("./sensor[@name='navsat_sensor']")
    barometer = base_link.find("./sensor[@name='air_pressure_sensor']")
    imu = base_link.find("./sensor[@name='imu_sensor']")
    if gps is None or barometer is None or imu is None:
        raise RuntimeError("pinned x500_base model is missing a required physical sensor")

    gps_stddev_m = float(profile["gps_position_stddev_m"])
    gps_horizontal_stddev_deg = float(profile["gazebo_navsat_horizontal_stddev_deg"])
    gps_vertical_stddev_m = float(profile["gazebo_navsat_vertical_stddev_m"])
    navsat = _ensure_xml_path(gps, "navsat", "position_sensing")
    _set_gaussian_stddev(_ensure_xml_path(navsat, "horizontal"), gps_horizontal_stddev_deg)
    _set_gaussian_stddev(_ensure_xml_path(navsat, "vertical"), gps_vertical_stddev_m)

    barometer_stddev = float(profile["barometer_pressure_stddev_pa"])
    pressure = _ensure_xml_path(barometer, "air_pressure", "pressure")
    _set_gaussian_stddev(pressure, barometer_stddev)

    imu_scale = float(profile["imu_noise_scale"])
    expected_imu: dict[str, float] = {}
    for group in ("angular_velocity", "linear_acceleration"):
        for axis in ("x", "y", "z"):
            axis_element = imu.find(f"./imu/{group}/{axis}")
            noise = axis_element.find("noise") if axis_element is not None else None
            if axis_element is None or noise is None:
                raise RuntimeError(f"pinned x500_base IMU is missing {group}/{axis}/noise")
            raw_stddev = noise.findtext("stddev")
            try:
                base_stddev = float(raw_stddev or "")
            except ValueError as exc:
                raise RuntimeError(
                    f"pinned x500_base IMU {group}/{axis} stddev is invalid"
                ) from exc
            scaled = base_stddev * imu_scale
            _set_gaussian_stddev(axis_element, scaled)
            expected_imu[f"{group}.{axis}"] = scaled
    return {
        "gps_position_stddev_m": gps_stddev_m,
        "gazebo_navsat_horizontal_stddev_deg": gps_horizontal_stddev_deg,
        "gazebo_navsat_vertical_stddev_m": gps_vertical_stddev_m,
        "gazebo_navsat_meters_per_degree_reference": float(
            profile["gazebo_navsat_meters_per_degree_reference"]
        ),
        "gazebo_navsat_unit_policy": str(profile["gazebo_navsat_unit_policy"]),
        "barometer_pressure_stddev_pa": barometer_stddev,
        "imu_stddev": expected_imu,
    }


def _apply_payload_sdf(
    base_link: ET.Element,
    profile: dict[str, Any],
) -> dict[str, Any]:
    inertial = base_link.find("inertial")
    if inertial is None:
        raise RuntimeError("pinned x500_base model has no base_link inertial")
    mass_node = inertial.find("mass")
    inertia = inertial.find("inertia")
    if mass_node is None or inertia is None:
        raise RuntimeError("pinned x500_base inertial is incomplete")
    try:
        original_mass = float(mass_node.text or "")
        original_inertia = {
            name: float(inertia.findtext(name, default=""))
            for name in ("ixx", "ixy", "ixz", "iyy", "iyz", "izz")
        }
    except ValueError as exc:
        raise RuntimeError("pinned x500_base mass/inertia is invalid") from exc
    increment = profile["inertia_increment_kg_m2"]
    final_mass = original_mass + float(profile["mass_kg"])
    final_inertia = dict(original_inertia)
    for name in ("ixx", "iyy", "izz"):
        final_inertia[name] = original_inertia[name] + float(increment[name])
    mass_node.text = f"{final_mass:.17g}"
    for name, value in final_inertia.items():
        node = inertia.find(name)
        if node is None:
            raise RuntimeError(f"pinned x500_base inertia is missing {name}")
        node.text = f"{value:.17g}"
    return {
        "original_mass_kg": original_mass,
        "payload_mass_kg": float(profile["mass_kg"]),
        "final_mass_kg": final_mass,
        "original_inertia_kg_m2": original_inertia,
        "final_inertia_kg_m2": final_inertia,
        "payload_assumption": profile["assumption"],
        "payload_dimensions_m": profile["dimensions_m"],
        "payload_center_m": profile["center_m"],
    }


def _apply_actuator_dynamics_sdf(
    model_root: ET.Element,
    profile: dict[str, Any],
) -> dict[str, Any]:
    model = model_root.find("./model[@name='x500']")
    if model is None:
        raise RuntimeError("pinned x500 model SDF has no x500 model")
    expected_numbers = set(profile["motor_numbers"])
    observed: dict[int, dict[str, float]] = {}
    for plugin in model.findall("plugin"):
        if plugin.get("name") != "gz::sim::systems::MulticopterMotorModel":
            continue
        try:
            motor_number = int(plugin.findtext("motorNumber", default=""))
        except ValueError as exc:
            raise RuntimeError("pinned x500 motor plugin has invalid motorNumber") from exc
        if motor_number not in expected_numbers or motor_number in observed:
            raise RuntimeError("pinned x500 motor plugin set is invalid")
        up = float(profile["time_constant_up_s"])
        down = float(profile["time_constant_down_s"])
        _ensure_xml_path(plugin, "timeConstantUp").text = f"{up:.17g}"
        _ensure_xml_path(plugin, "timeConstantDown").text = f"{down:.17g}"
        observed[motor_number] = {
            "time_constant_up_s": up,
            "time_constant_down_s": down,
        }
    if set(observed) != expected_numbers:
        raise RuntimeError("pinned x500 model does not expose all four motor plugins")
    return {
        "model": profile["model"],
        "requested_delay_ms": float(profile["requested_delay_ms"]),
        "motors": [{"motor_number": number, **observed[number]} for number in sorted(observed)],
    }


def _apply_actuator_failure_sdf(
    model_root: ET.Element,
    profile: dict[str, Any],
) -> dict[str, Any]:
    model = model_root.find("./model[@name='x500']")
    if model is None:
        raise RuntimeError("pinned x500 model SDF has no x500 model")
    target_motor = int(profile["target_motor_number"])
    observed: dict[int, dict[str, Any]] = {}
    for plugin in model.findall("plugin"):
        if plugin.get("name") != "gz::sim::systems::MulticopterMotorModel":
            continue
        try:
            motor_number = int(plugin.findtext("motorNumber", default=""))
            original_max = float(plugin.findtext("maxRotVelocity", default=""))
        except ValueError as exc:
            raise RuntimeError("pinned x500 motor plugin has invalid hard-stop fields") from exc
        if (
            motor_number not in {0, 1, 2, 3}
            or motor_number in observed
            or not math.isfinite(original_max)
            or original_max <= 0
        ):
            raise RuntimeError("pinned x500 motor plugin set is invalid")
        final_max = (
            float(profile["max_rot_velocity_rad_s"])
            if motor_number == target_motor
            else original_max
        )
        _ensure_xml_path(plugin, "maxRotVelocity").text = f"{final_max:.17g}"
        observed[motor_number] = {
            "joint_name": plugin.findtext("jointName", default=""),
            "original_max_rot_velocity_rad_s": original_max,
            "final_max_rot_velocity_rad_s": final_max,
            "failed": motor_number == target_motor,
        }
    if set(observed) != {0, 1, 2, 3}:
        raise RuntimeError("pinned x500 model does not expose all four motor plugins")
    if observed[target_motor]["joint_name"] != profile["target_joint_name"]:
        raise RuntimeError("pinned x500 target motor joint does not match the failure profile")

    publishers = [
        plugin
        for plugin in model.findall("plugin")
        if plugin.get("name") == JOINT_STATE_PUBLISHER_PLUGIN_NAME
        or plugin.get("filename") == JOINT_STATE_PUBLISHER_PLUGIN_FILENAME
    ]
    if publishers:
        raise RuntimeError("pinned x500 model unexpectedly already has a joint-state publisher")
    publisher = ET.SubElement(
        model,
        "plugin",
        {
            "filename": JOINT_STATE_PUBLISHER_PLUGIN_FILENAME,
            "name": JOINT_STATE_PUBLISHER_PLUGIN_NAME,
        },
    )
    _ensure_xml_path(publisher, "topic").text = str(profile["joint_state_topic"])
    _ensure_xml_path(
        publisher, "update_rate"
    ).text = f"{float(profile['joint_state_update_rate_hz']):.17g}"
    for motor_number in range(4):
        joint_name = str(observed[motor_number]["joint_name"])
        if not re.fullmatch(r"rotor_[0-3]_joint", joint_name):
            raise RuntimeError("pinned x500 motor plugin has an unexpected joint name")
        ET.SubElement(publisher, "joint_name").text = joint_name

    return {
        "failure_mode": profile["failure_mode"],
        "failure_start": profile["failure_start"],
        "target_motor_number": target_motor,
        "target_joint_name": profile["target_joint_name"],
        "max_failed_motor_abs_velocity_rad_s": float(
            profile["max_failed_motor_abs_velocity_rad_s"]
        ),
        "min_healthy_motor_abs_velocity_rad_s": float(
            profile["min_healthy_motor_abs_velocity_rad_s"]
        ),
        "joint_state_publisher": {
            "filename": JOINT_STATE_PUBLISHER_PLUGIN_FILENAME,
            "name": JOINT_STATE_PUBLISHER_PLUGIN_NAME,
            "topic": profile["joint_state_topic"],
            "update_rate_hz": float(profile["joint_state_update_rate_hz"]),
            "joint_names": [str(observed[number]["joint_name"]) for number in range(4)],
        },
        "motors": [{"motor_number": number, **observed[number]} for number in sorted(observed)],
    }


def _configure_wind_effects_plugin(
    plugin: ET.Element,
    gust_profile: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if gust_profile is None:
        return None
    _ensure_xml_path(plugin, "force_approximation_scaling_factor").text = "1"
    magnitude = _ensure_xml_path(plugin, "horizontal", "magnitude")
    rise_time = float(gust_profile["time_for_rise_s"])
    if not math.isfinite(rise_time) or rise_time <= 0:
        raise RuntimeError("WindEffects gust time_for_rise must be finite and greater than zero")
    _ensure_xml_path(magnitude, "time_for_rise").text = f"{rise_time:.17g}"
    magnitude_sin = _ensure_xml_path(magnitude, "sin")
    _ensure_xml_path(
        magnitude_sin, "amplitude_percent"
    ).text = f"{float(gust_profile['horizontal_magnitude_sine_amplitude_percent']):.17g}"
    _ensure_xml_path(magnitude_sin, "period").text = f"{float(gust_profile['period_s']):.17g}"
    _set_gaussian_stddev(magnitude, 0.0)
    direction = _ensure_xml_path(plugin, "horizontal", "direction")
    _ensure_xml_path(direction, "time_for_rise").text = f"{rise_time:.17g}"
    direction_sin = _ensure_xml_path(direction, "sin")
    _ensure_xml_path(direction_sin, "amplitude").text = "0"
    _ensure_xml_path(direction_sin, "period").text = f"{float(gust_profile['period_s']):.17g}"
    _set_gaussian_stddev(direction, 0.0)
    _set_gaussian_stddev(_ensure_xml_path(plugin, "vertical"), 0.0)
    return {
        "mean_linear_velocity_mps": gust_profile["mean_linear_velocity_mps"],
        "peak_magnitude_mps": float(gust_profile["peak_magnitude_mps"]),
        "period_s": float(gust_profile["period_s"]),
        "time_for_rise_s": rise_time,
        "amplitude_percent": float(gust_profile["horizontal_magnitude_sine_amplitude_percent"]),
        "range_mps": gust_profile["range_mps"],
    }


def _prepare_steady_wind_overlay(
    request: dict[str, Any],
    engine: Any,
    *,
    run_dir: Path,
    autopilot_dir: str | None,
    simulator_model: str,
    world: str,
    launch_env: dict[str, str],
) -> dict[str, Any] | None:
    """Create an isolated world/model overlay before Gazebo starts."""

    compiled = engine.compile_bundled_steady_wind(request)
    compiled_sdf_profile = engine.compile_bundled_sdf_profile(request)
    if compiled is None and compiled_sdf_profile is None:
        return None
    normalized_model = simulator_model.removeprefix("gz_")
    if normalized_model not in {"x500", "x500_depth", "x500_vision"}:
        raise ScenarioEffectUnsupportedError(
            "bundled steady wind currently supports PX4 x500, x500_depth, and "
            "x500_vision simulator models"
        )
    if compiled_sdf_profile is not None and normalized_model != "x500":
        raise ScenarioEffectUnsupportedError(
            "bundled Trial-local sensor, gust, payload, and actuator profiles "
            "currently require the PX4 x500 simulator model"
        )
    if not autopilot_dir:
        raise ScenarioEffectUnsupportedError(
            "PX4_AUTOPILOT_DIR is required to build the trusted Trial-local wind overlay"
        )

    world_name = _validated_world_name(world)
    px4_root = Path(autopilot_dir).resolve()
    if not px4_root.is_dir():
        raise ScenarioEffectUnsupportedError("PX4_AUTOPILOT_DIR is unavailable")
    gazebo_root = px4_root / "Tools" / "simulation" / "gz"
    source_model_dir = gazebo_root / "models" / "x500_base"
    source_model_sdf = source_model_dir / "model.sdf"
    source_vehicle_model_dir = gazebo_root / "models" / normalized_model
    source_vehicle_model_sdf = source_vehicle_model_dir / "model.sdf"
    source_world_sdf = gazebo_root / "worlds" / f"{world_name}.sdf"
    # PX4's px4-rc.gzsim spawns the top-level vehicle from the explicit
    # ``PX4_GZ_MODELS/<model>/model.sdf`` path. It does not resolve that file
    # through GZ_SIM_RESOURCE_PATH. Always bind a Trial-local top-level model,
    # even when only x500_base or world fields are changed.
    trusted_sources = [source_model_sdf, source_vehicle_model_sdf, source_world_sdf]
    for source in trusted_sources:
        if not source.is_file() or source.is_symlink():
            raise ScenarioEffectUnsupportedError(
                f"trusted pinned PX4 Gazebo input is missing or unsafe: {source}"
            )
        try:
            source.resolve().relative_to(px4_root)
        except ValueError as exc:
            raise ScenarioEffectUnsupportedError(
                f"trusted PX4 Gazebo input escapes PX4_AUTOPILOT_DIR: {source}"
            ) from exc

    build_root = px4_root / "build" / "px4_sitl_default"
    source_rootfs = build_root / "rootfs"
    px4_executable = build_root / "bin" / "px4"
    px4_plugins = build_root / "src" / "modules" / "simulation" / "gz_plugins"
    px4_server_config = px4_root / "src" / "modules" / "simulation" / "gz_bridge" / "server.config"
    required_runtime_paths = (
        source_rootfs,
        px4_executable,
        px4_plugins,
        px4_server_config,
    )
    if any(not path.exists() for path in required_runtime_paths):
        raise ScenarioEffectUnsupportedError(
            "the pinned PX4 SITL build is incomplete; Trial-local wind launch "
            "requires rootfs, px4, Gazebo plugins, and server config"
        )

    runtime_root = run_dir / "scenario_runtime"
    model_root = runtime_root / "models"
    world_root = runtime_root / "worlds"
    overlay_model_dir = model_root / "x500_base"
    overlay_vehicle_model_dir = model_root / normalized_model
    overlay_world_sdf = world_root / f"{world_name}.sdf"
    if (
        overlay_model_dir.exists()
        or overlay_vehicle_model_dir.exists()
        or overlay_world_sdf.exists()
    ):
        raise RuntimeError("Trial-local scenario runtime overlay already exists")
    model_root.mkdir(parents=True, exist_ok=True)
    world_root.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source_model_dir, overlay_model_dir)
    shutil.copytree(source_vehicle_model_dir, overlay_vehicle_model_dir)
    shutil.copy2(source_world_sdf, overlay_world_sdf)

    overlay_model_sdf = overlay_model_dir / "model.sdf"
    model_tree = _parse_trusted_local_xml(
        overlay_model_sdf,
        trusted_root=runtime_root,
        context="Trial-local PX4 model SDF",
    )
    model_root_xml = model_tree.getroot()
    if model_root_xml is None:
        raise RuntimeError("pinned x500_base model SDF has no root element")
    base_link = model_root_xml.find("./model[@name='x500_base']/link[@name='base_link']")
    if base_link is None:
        raise RuntimeError("pinned x500_base model has no base_link")
    gust_profile = (
        compiled_sdf_profile.get("wind_gust") if isinstance(compiled_sdf_profile, dict) else None
    )
    wind_requested = compiled is not None or gust_profile is not None
    if compiled is not None and gust_profile is not None and compiled["speed_mps"] > 1e-9:
        raise ScenarioEffectUnsupportedError(
            "the bundled sinusoidal gust profile cannot be superimposed exactly on a "
            "non-zero steady-wind vector; split these into separate physical scenarios"
        )
    if wind_requested:
        enable_wind = base_link.find("enable_wind")
        if enable_wind is None:
            enable_wind = ET.SubElement(base_link, "enable_wind")
        enable_wind.text = "true"

    applied_sdf_profile: dict[str, Any] = {}
    if compiled_sdf_profile is not None and "sensor_noise" in compiled_sdf_profile:
        applied_sdf_profile["sensor_noise"] = _apply_sensor_noise_sdf(
            base_link,
            compiled_sdf_profile["sensor_noise"],
        )
    if compiled_sdf_profile is not None and "payload" in compiled_sdf_profile:
        applied_sdf_profile["payload"] = _apply_payload_sdf(
            base_link,
            compiled_sdf_profile["payload"],
        )

    sanitized_classic_material_scripts = 0
    for material in model_root_xml.findall(".//material"):
        script = material.find("script")
        if script is None:
            continue
        uri = script.findtext("uri", default="").strip()
        if uri != "file://media/materials/scripts/gazebo.material":
            continue
        material_name = script.findtext("name", default="").strip()
        if material_name != "Gazebo/DarkGrey":
            raise RuntimeError(
                "pinned x500_base model has an unsupported Gazebo Classic material "
                f"reference: {material_name or '<unnamed>'}"
            )
        material.remove(script)
        for tag, value in (
            ("ambient", "0.2 0.2 0.2 1"),
            ("diffuse", "0.2 0.2 0.2 1"),
            ("specular", "0.1 0.1 0.1 1"),
        ):
            color = material.find(tag)
            if color is None:
                color = ET.SubElement(material, tag)
            color.text = value
        sanitized_classic_material_scripts += 1

    ET.indent(model_tree, space="  ")
    model_tree.write(overlay_model_sdf, encoding="utf-8", xml_declaration=True)

    overlay_vehicle_model_sdf = overlay_vehicle_model_dir / "model.sdf"
    vehicle_profile_sections = (
        {"actuator_dynamics", "actuator_failure"} & set(compiled_sdf_profile)
        if isinstance(compiled_sdf_profile, dict)
        else set()
    )
    if vehicle_profile_sections:
        vehicle_tree = _parse_trusted_local_xml(
            overlay_vehicle_model_sdf,
            trusted_root=runtime_root,
            context="Trial-local PX4 vehicle model SDF",
        )
        vehicle_root_xml = vehicle_tree.getroot()
        if vehicle_root_xml is None:
            raise RuntimeError("pinned x500 vehicle model SDF has no root element")
        if "actuator_dynamics" in vehicle_profile_sections:
            applied_sdf_profile["actuator_dynamics"] = _apply_actuator_dynamics_sdf(
                vehicle_root_xml,
                compiled_sdf_profile["actuator_dynamics"],
            )
        if "actuator_failure" in vehicle_profile_sections:
            applied_sdf_profile["actuator_failure"] = _apply_actuator_failure_sdf(
                vehicle_root_xml,
                compiled_sdf_profile["actuator_failure"],
            )
        ET.indent(vehicle_tree, space="  ")
        vehicle_tree.write(
            overlay_vehicle_model_sdf,
            encoding="utf-8",
            xml_declaration=True,
        )

    world_tree = _parse_trusted_local_xml(
        overlay_world_sdf,
        trusted_root=runtime_root,
        context="Trial-local PX4 world SDF",
    )
    world_root_xml = world_tree.getroot()
    if world_root_xml is None:
        raise RuntimeError("pinned Gazebo world SDF has no root element")
    world_xml = world_root_xml.find(f"./world[@name='{world_name}']")
    if world_xml is None:
        raise RuntimeError(f"pinned world SDF does not define world {world_name!r}")

    # Gazebo does not inject the default server-config systems once a world
    # declares an SDF system plugin of its own.  Materialize the pinned PX4
    # systems into this Trial-local world before adding WindEffects so PX4 still
    # gets scene/info, entity creation, physics, sensors, and the bridge inputs.
    server_config_tree = _parse_trusted_local_xml(
        px4_server_config,
        trusted_root=px4_root,
        context="pinned PX4 Gazebo server config",
    )
    configured_plugins = server_config_tree.findall("./plugins/plugin")
    if not configured_plugins:
        raise RuntimeError("pinned PX4 Gazebo server config has no system plugins")
    materialized_plugins: list[ET.Element] = []
    wind_plugin_observation: dict[str, Any] | None = None
    if wind_requested:
        plugin_keys = {
            (plugin.get("filename"), plugin.get("name")) for plugin in world_xml.findall("plugin")
        }
        for configured_plugin in configured_plugins:
            plugin_key = (
                configured_plugin.get("filename"),
                configured_plugin.get("name"),
            )
            if not all(plugin_key):
                raise RuntimeError("pinned PX4 Gazebo server config has an invalid system plugin")
            if plugin_key in plugin_keys:
                continue
            materialized_plugin = copy.deepcopy(configured_plugin)
            materialized_plugin.attrib.pop("entity_name", None)
            materialized_plugin.attrib.pop("entity_type", None)
            world_xml.append(materialized_plugin)
            materialized_plugins.append(configured_plugin)
            plugin_keys.add(plugin_key)

        wind_xml = world_xml.find("wind")
        if wind_xml is None:
            wind_xml = ET.SubElement(world_xml, "wind")
        linear_velocity = wind_xml.find("linear_velocity")
        if linear_velocity is None:
            linear_velocity = ET.SubElement(wind_xml, "linear_velocity")
        linear_velocity.text = "0 0 0"

        plugins = [
            plugin
            for plugin in world_xml.findall("plugin")
            if plugin.get("name") == WIND_EFFECTS_PLUGIN_NAME
            or plugin.get("filename") == WIND_EFFECTS_PLUGIN_FILENAME
        ]
        if len(plugins) > 1:
            raise RuntimeError("world SDF contains multiple conflicting WindEffects plugins")
        if plugins:
            plugin = plugins[0]
            plugin.set("filename", WIND_EFFECTS_PLUGIN_FILENAME)
            plugin.set("name", WIND_EFFECTS_PLUGIN_NAME)
        else:
            plugin = ET.SubElement(
                world_xml,
                "plugin",
                {
                    "filename": WIND_EFFECTS_PLUGIN_FILENAME,
                    "name": WIND_EFFECTS_PLUGIN_NAME,
                },
            )
        wind_plugin_observation = _configure_wind_effects_plugin(
            plugin,
            gust_profile,
        )
        if wind_plugin_observation is not None:
            applied_sdf_profile["wind_gust"] = wind_plugin_observation
    ET.indent(world_tree, space="  ")
    world_tree.write(overlay_world_sdf, encoding="utf-8", xml_declaration=True)

    existing_resource_path = launch_env.get("GZ_SIM_RESOURCE_PATH", "")
    overlay_paths = [str(model_root), str(world_root)]
    if existing_resource_path:
        overlay_paths.append(existing_resource_path)
    launch_env["GZ_SIM_RESOURCE_PATH"] = os.pathsep.join(overlay_paths)

    for source in source_rootfs.rglob("*"):
        if not source.is_symlink():
            continue
        try:
            source.resolve(strict=True).relative_to(px4_root)
        except (OSError, ValueError) as exc:
            raise ScenarioEffectUnsupportedError(
                f"PX4 rootfs contains an unsafe external symlink: {source}"
            ) from exc

    trial_rootfs = runtime_root / "px4_rootfs"
    shutil.copytree(
        source_rootfs,
        trial_rootfs,
        symlinks=False,
        ignore=shutil.ignore_patterns(
            "dataman",
            "eeprom",
            "log",
            "parameters.bson",
            "parameters_backup.bson",
        ),
    )
    resource_paths = [
        str(model_root),
        str(gazebo_root / "models"),
        str(world_root),
        str(gazebo_root / "worlds"),
    ]
    if existing_resource_path:
        resource_paths.append(existing_resource_path)
    trial_gz_env = trial_rootfs / "gz_env.sh"
    trial_gz_env.write_text(
        "\n".join(
            [
                "#!/usr/bin/env bash",
                "# Generated per Trial by DroneDream; never edits the pinned PX4 checkout.",
                f"export PX4_GZ_MODELS={shlex.quote(str(model_root))}",
                f"export PX4_GZ_WORLDS={shlex.quote(str(world_root))}",
                f"export PX4_GZ_PLUGINS={shlex.quote(str(px4_plugins))}",
                f"export PX4_GZ_SERVER_CONFIG={shlex.quote(str(px4_server_config))}",
                f"export GZ_SIM_RESOURCE_PATH={shlex.quote(os.pathsep.join(resource_paths))}",
                f"export GZ_SIM_SYSTEM_PLUGIN_PATH={shlex.quote(str(px4_plugins))}",
                f"export GZ_SIM_SERVER_CONFIG_PATH={shlex.quote(str(px4_server_config))}",
                "",
            ]
        ),
        encoding="utf-8",
    )
    px4_sim_model = (
        simulator_model if simulator_model.startswith("gz_") else f"gz_{normalized_model}"
    )
    return {
        "compiled_wind": compiled,
        "compiled_sdf_profile": compiled_sdf_profile,
        "applied_sdf_profile": applied_sdf_profile,
        "model_sdf_path": str(overlay_model_sdf),
        "model_sdf_sha256": _sha256_hex(overlay_model_sdf),
        "vehicle_model_sdf_path": str(overlay_vehicle_model_sdf),
        "vehicle_model_sdf_sha256": _sha256_hex(overlay_vehicle_model_sdf),
        "sanitized_classic_material_scripts": sanitized_classic_material_scripts,
        "world_sdf_path": str(overlay_world_sdf),
        "world_sdf_sha256": _sha256_hex(overlay_world_sdf),
        "wind_enabled_link": "x500_base/base_link" if wind_requested else None,
        "wind_effects_plugin": (
            {
                "filename": WIND_EFFECTS_PLUGIN_FILENAME,
                "name": WIND_EFFECTS_PLUGIN_NAME,
                "profile": wind_plugin_observation,
            }
            if wind_requested
            else None
        ),
        "materialized_px4_system_plugins": [
            {
                "filename": plugin.get("filename"),
                "name": plugin.get("name"),
            }
            for plugin in materialized_plugins
        ],
        "px4_server_config_path": str(px4_server_config),
        "px4_server_config_sha256": _sha256_hex(px4_server_config),
        "px4_executable_path": str(px4_executable),
        "px4_sim_model": px4_sim_model,
        "px4_vehicle_model_instance": f"{normalized_model}_0",
        "px4_trial_rootfs_path": str(trial_rootfs),
        "px4_trial_gz_env_path": str(trial_gz_env),
        "px4_trial_gz_env_sha256": _sha256_hex(trial_gz_env),
    }


def _wrap_launch_command_for_trial_world(
    command: str,
    overlay: dict[str, Any],
    *,
    launch_env: dict[str, str],
    headless: bool,
) -> str:
    """Launch PX4 from a clean Trial rootfs whose ``gz_env.sh`` selects the overlay."""

    if os.environ.get("PX4_LAUNCH_COMMAND_TEMPLATE", "").strip():
        raise ScenarioEffectUnsupportedError(
            "bundled steady wind cannot prove Trial-world selection with a custom "
            "PX4_LAUNCH_COMMAND_TEMPLATE; the site launcher must emit its own "
            "physical-effect evidence"
        )
    rootfs_raw = overlay.get("px4_trial_rootfs_path")
    executable_raw = overlay.get("px4_executable_path")
    simulator_model = overlay.get("px4_sim_model")
    if (
        not isinstance(rootfs_raw, str)
        or not isinstance(executable_raw, str)
        or not isinstance(simulator_model, str)
    ):
        raise RuntimeError("Trial-local PX4 launch metadata is incomplete")
    rootfs = Path(rootfs_raw).resolve()
    executable = Path(executable_raw).resolve()
    if not rootfs.is_dir() or not executable.is_file():
        raise RuntimeError("Trial-local PX4 rootfs or pinned executable is unavailable")
    if not re.fullmatch(r"gz_[A-Za-z0-9_.-]+", simulator_model):
        raise RuntimeError("Trial-local PX4 simulator model is invalid")
    launch_env.pop("PX4_GZ_STANDALONE", None)
    launch_env["GZ_IP"] = os.environ.get("GZ_IP", "127.0.0.1")
    quoted_rootfs = shlex.quote(str(rootfs))
    return (
        f"cd {quoted_rootfs}; "
        f"HEADLESS={'1' if headless else '0'} "
        f"PX4_SIM_MODEL={shlex.quote(simulator_model)} "
        f"GZ_IP={shlex.quote(launch_env['GZ_IP'])} "
        f"{shlex.quote(str(executable))} -d -w {quoted_rootfs} {quoted_rootfs}"
    )


def _gazebo_cli() -> str | None:
    configured = os.environ.get("DRONEDREAM_GAZEBO_EXECUTABLE", "").strip()
    if configured and Path(configured).is_file():
        return configured
    return shutil.which("gz")


_PROTOBUF_NUMBER = r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?"


def _parse_wind_info_response(response_text: str) -> dict[str, Any]:
    velocity_match = re.search(
        r"\blinear_velocity\s*\{(?P<body>.*?)\}",
        response_text,
        re.DOTALL,
    )
    if velocity_match is None:
        raise RuntimeError("Gazebo wind_info response omitted linear_velocity")
    body = velocity_match.group("body")
    vector: dict[str, float] = {}
    for axis in ("x", "y", "z"):
        match = re.search(rf"\b{axis}\s*:\s*({_PROTOBUF_NUMBER})", body)
        vector[axis] = round(float(match.group(1)), 12) if match else 0.0
    enable_match = re.search(r"\benable_wind\s*:\s*(true|false)\b", response_text, re.I)
    if enable_match is None:
        raise RuntimeError("Gazebo wind_info response omitted enable_wind")
    return {
        "linear_velocity_mps": vector,
        "enable_wind": enable_match.group(1).lower() == "true",
    }


def _parse_protobuf_string_message(response_text: str) -> str:
    match = re.search(
        r'\bdata\s*:\s*("(?:\\.|[^"\\])*")',
        response_text,
        re.DOTALL,
    )
    if match is None:
        raise RuntimeError("Gazebo generated-world-SDF response omitted StringMsg.data")
    try:
        value = ast.literal_eval(match.group(1))
    except (SyntaxError, ValueError) as exc:
        raise RuntimeError("Gazebo generated-world-SDF response is malformed") from exc
    if not isinstance(value, str):
        raise RuntimeError("Gazebo generated-world-SDF response is not text")
    if len(value.encode("utf-8")) > MAX_GENERATED_WORLD_SDF_BYTES:
        raise RuntimeError("Gazebo generated-world-SDF response exceeds the evidence limit")
    return value


def _required_float_text(
    parent: ET.Element,
    path: str,
    *,
    context: str,
) -> float:
    raw = parent.findtext(path)
    try:
        value = float(raw or "")
    except ValueError as exc:
        raise RuntimeError(f"generated runtime SDF has invalid {context}") from exc
    if not math.isfinite(value):
        raise RuntimeError(f"generated runtime SDF has non-finite {context}")
    return value


def _assert_runtime_float(
    actual: float,
    expected: float,
    *,
    context: str,
) -> None:
    if not math.isclose(actual, expected, rel_tol=1e-9, abs_tol=1e-12):
        raise RuntimeError(
            f"generated runtime SDF {context} mismatch: "
            f"expected {expected:.17g}, observed {actual:.17g}"
        )


def _runtime_sdf_profile_observation(
    generated_sdf: str,
    *,
    generated_path: Path,
    expected_vehicle_model: str,
    applied_sdf_profile: dict[str, Any],
    require_wind_mode: bool,
) -> dict[str, Any]:
    root = _parse_bounded_xml_text(
        generated_sdf,
        byte_limit=MAX_GENERATED_WORLD_SDF_BYTES,
        context="Gazebo generated-world-SDF response",
    )
    matching_models = [
        model for model in root.iter("model") if model.get("name") == expected_vehicle_model
    ]
    if len(matching_models) != 1:
        raise RuntimeError(
            "generated runtime SDF does not expose exactly one expected vehicle "
            f"model {expected_vehicle_model}"
        )
    model = matching_models[0]
    base_link = model.find("./link[@name='base_link']")
    if base_link is None:
        raise RuntimeError(f"generated runtime SDF has no {expected_vehicle_model}/base_link")
    enabled = (base_link.findtext("enable_wind") or "").strip().lower() == "true"
    if require_wind_mode and not enabled:
        raise RuntimeError(
            "generated runtime SDF does not prove expected wind-enabled vehicle "
            f"{expected_vehicle_model}/base_link enable_wind=true"
        )
    verified_sections: list[str] = []

    expected_sensor = applied_sdf_profile.get("sensor_noise")
    if isinstance(expected_sensor, dict):
        gps = base_link.find("./sensor[@name='navsat_sensor']")
        barometer = base_link.find("./sensor[@name='air_pressure_sensor']")
        imu = base_link.find("./sensor[@name='imu_sensor']")
        if gps is None or barometer is None or imu is None:
            raise RuntimeError("generated runtime SDF omitted a profiled x500 sensor")
        for axis, expected_key in (
            ("horizontal", "gazebo_navsat_horizontal_stddev_deg"),
            ("vertical", "gazebo_navsat_vertical_stddev_m"),
        ):
            actual = _required_float_text(
                gps,
                f"./navsat/position_sensing/{axis}/noise/stddev",
                context=f"navsat {axis} position noise",
            )
            _assert_runtime_float(
                actual,
                float(expected_sensor[expected_key]),
                context=f"navsat {axis} position noise",
            )
        actual_baro = _required_float_text(
            barometer,
            "./air_pressure/pressure/noise/stddev",
            context="barometer pressure noise",
        )
        _assert_runtime_float(
            actual_baro,
            float(expected_sensor["barometer_pressure_stddev_pa"]),
            context="barometer pressure noise",
        )
        for key, expected in expected_sensor["imu_stddev"].items():
            group, axis = key.split(".", 1)
            actual = _required_float_text(
                imu,
                f"./imu/{group}/{axis}/noise/stddev",
                context=f"IMU {group} {axis} noise",
            )
            _assert_runtime_float(
                actual,
                float(expected),
                context=f"IMU {group} {axis} noise",
            )
        verified_sections.append("sensor_noise")

    expected_payload = applied_sdf_profile.get("payload")
    if isinstance(expected_payload, dict):
        final_mass = _required_float_text(
            base_link,
            "./inertial/mass",
            context="base_link mass",
        )
        _assert_runtime_float(
            final_mass,
            float(expected_payload["final_mass_kg"]),
            context="base_link mass",
        )
        for name, expected in expected_payload["final_inertia_kg_m2"].items():
            actual = _required_float_text(
                base_link,
                f"./inertial/inertia/{name}",
                context=f"base_link inertia {name}",
            )
            _assert_runtime_float(
                actual,
                float(expected),
                context=f"base_link inertia {name}",
            )
        verified_sections.append("payload")

    expected_actuator = applied_sdf_profile.get("actuator_dynamics")
    if isinstance(expected_actuator, dict):
        observed_motors: set[int] = set()
        for plugin in model.findall("plugin"):
            if plugin.get("name") != "gz::sim::systems::MulticopterMotorModel":
                continue
            try:
                motor_number = int(plugin.findtext("motorNumber", default=""))
            except ValueError as exc:
                raise RuntimeError("generated runtime SDF has invalid motorNumber") from exc
            if motor_number in observed_motors:
                raise RuntimeError("generated runtime SDF has duplicate motorNumber")
            observed_motors.add(motor_number)
            expected_motor = next(
                (
                    item
                    for item in expected_actuator["motors"]
                    if item["motor_number"] == motor_number
                ),
                None,
            )
            if expected_motor is None:
                raise RuntimeError("generated runtime SDF exposes an unexpected motor plugin")
            for tag, key in (
                ("timeConstantUp", "time_constant_up_s"),
                ("timeConstantDown", "time_constant_down_s"),
            ):
                actual = _required_float_text(
                    plugin,
                    tag,
                    context=f"motor {motor_number} {tag}",
                )
                _assert_runtime_float(
                    actual,
                    float(expected_motor[key]),
                    context=f"motor {motor_number} {tag}",
                )
        expected_numbers = {int(item["motor_number"]) for item in expected_actuator["motors"]}
        if observed_motors != expected_numbers:
            raise RuntimeError(
                "generated runtime SDF motor plugin coverage does not match the profile"
            )
        verified_sections.append("actuator_dynamics")

    expected_failure = applied_sdf_profile.get("actuator_failure")
    if isinstance(expected_failure, dict):
        expected_motors = {int(item["motor_number"]): item for item in expected_failure["motors"]}
        observed_motors: set[int] = set()
        for plugin in model.findall("plugin"):
            if plugin.get("name") != "gz::sim::systems::MulticopterMotorModel":
                continue
            try:
                motor_number = int(plugin.findtext("motorNumber", default=""))
            except ValueError as exc:
                raise RuntimeError("generated runtime SDF has invalid motorNumber") from exc
            if motor_number in observed_motors or motor_number not in expected_motors:
                raise RuntimeError("generated runtime SDF has invalid hard-stop motor coverage")
            observed_motors.add(motor_number)
            expected_motor = expected_motors[motor_number]
            actual_max = _required_float_text(
                plugin,
                "maxRotVelocity",
                context=f"motor {motor_number} maxRotVelocity",
            )
            _assert_runtime_float(
                actual_max,
                float(expected_motor["final_max_rot_velocity_rad_s"]),
                context=f"motor {motor_number} maxRotVelocity",
            )
            if plugin.findtext("jointName", default="") != expected_motor["joint_name"]:
                raise RuntimeError(f"generated runtime SDF motor {motor_number} jointName mismatch")
        if observed_motors != set(expected_motors):
            raise RuntimeError(
                "generated runtime SDF hard-stop motor coverage does not match the profile"
            )

        publishers = [
            plugin
            for plugin in model.findall("plugin")
            if plugin.get("name") == JOINT_STATE_PUBLISHER_PLUGIN_NAME
            or plugin.get("filename") == JOINT_STATE_PUBLISHER_PLUGIN_FILENAME
        ]
        if len(publishers) != 1:
            raise RuntimeError(
                "generated runtime SDF does not expose exactly one joint-state publisher"
            )
        publisher = publishers[0]
        expected_publisher = expected_failure["joint_state_publisher"]
        if (
            publisher.get("filename") != expected_publisher["filename"]
            or publisher.get("name") != expected_publisher["name"]
            or publisher.findtext("topic", default="") != expected_publisher["topic"]
            or publisher.findall("joint_name") == []
            or [item.text or "" for item in publisher.findall("joint_name")]
            != expected_publisher["joint_names"]
        ):
            raise RuntimeError(
                "generated runtime SDF joint-state publisher does not match the profile"
            )
        _assert_runtime_float(
            _required_float_text(
                publisher,
                "update_rate",
                context="joint-state publisher update_rate",
            ),
            float(expected_publisher["update_rate_hz"]),
            context="joint-state publisher update_rate",
        )
        verified_sections.append("actuator_failure")

    expected_gust = applied_sdf_profile.get("wind_gust")
    if isinstance(expected_gust, dict):
        wind_plugins = [
            plugin
            for plugin in root.iter("plugin")
            if plugin.get("name") == WIND_EFFECTS_PLUGIN_NAME
            or plugin.get("filename") == WIND_EFFECTS_PLUGIN_FILENAME
        ]
        if len(wind_plugins) != 1:
            raise RuntimeError(
                "generated runtime SDF does not expose exactly one WindEffects plugin"
            )
        plugin = wind_plugins[0]
        for path, expected, context in (
            (
                "./horizontal/magnitude/time_for_rise",
                expected_gust["time_for_rise_s"],
                "gust magnitude time_for_rise",
            ),
            (
                "./horizontal/magnitude/sin/amplitude_percent",
                expected_gust["amplitude_percent"],
                "gust amplitude_percent",
            ),
            (
                "./horizontal/magnitude/sin/period",
                expected_gust["period_s"],
                "gust period",
            ),
            (
                "./horizontal/direction/time_for_rise",
                expected_gust["time_for_rise_s"],
                "gust direction time_for_rise",
            ),
        ):
            _assert_runtime_float(
                _required_float_text(plugin, path, context=context),
                float(expected),
                context=context,
            )
        verified_sections.append("wind_gust")

    generated_path.parent.mkdir(parents=True, exist_ok=True)
    generated_path.write_text(generated_sdf, encoding="utf-8")
    return {
        "source_vehicle_model": "x500_base",
        "vehicle_model": expected_vehicle_model,
        "link_name": "base_link",
        "enable_wind": enabled,
        "verified_profile_sections": verified_sections,
        "applied_sdf_profile": applied_sdf_profile,
        "sdf_path": str(generated_path),
        "sdf_sha256": _sha256_hex(generated_path),
    }


def _runtime_wind_mode_observation(
    generated_sdf: str,
    *,
    generated_path: Path,
    expected_vehicle_model: str,
) -> dict[str, Any]:
    return _runtime_sdf_profile_observation(
        generated_sdf,
        generated_path=generated_path,
        expected_vehicle_model=expected_vehicle_model,
        applied_sdf_profile={},
        require_wind_mode=True,
    )


def _run_gazebo_command(
    argv: list[str],
    *,
    timeout: float,
    failure_context: str,
) -> str:
    try:
        response = subprocess.run(  # noqa: S603 - resolved gz executable, fixed argv.
            argv,
            capture_output=True,
            check=False,
            text=True,
            timeout=timeout,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise RuntimeError(f"{failure_context}: {exc}") from exc
    response_text = _subprocess_text(response.stdout) + "\n" + _subprocess_text(response.stderr)
    if response.returncode != 0:
        raise RuntimeError(
            f"{failure_context}: exit={response.returncode}, response={response_text.strip()[:400]}"
        )
    return response_text


def _apply_steady_wind_effects(
    request: dict[str, Any],
    engine: Any,
    overlay: dict[str, Any] | None,
    *,
    run_dir: Path,
    world: str,
) -> dict[str, dict[str, Any]]:
    compiled = engine.compile_bundled_steady_wind(request)
    compiled_sdf_profile = engine.compile_bundled_sdf_profile(request)
    if compiled is None and compiled_sdf_profile is None:
        return {}
    if (
        overlay is None
        or overlay.get("compiled_wind") != compiled
        or overlay.get("compiled_sdf_profile") != compiled_sdf_profile
    ):
        raise RuntimeError("Trial-local physical scenario overlay is missing or request-mismatched")
    gz_cli = _gazebo_cli()
    if not gz_cli:
        raise ScenarioEffectUnsupportedError(
            "Gazebo gz CLI is unavailable; physical SDF profiles require "
            "generate_world_sdf and wind profiles also require wind_info"
        )
    world_name = _validated_world_name(world)
    wind_topic = f"/world/{world_name}/wind"
    wind_info_service = f"/world/{world_name}/wind_info"
    generated_sdf_service = f"/world/{world_name}/generate_world_sdf"
    gust_profile = (
        compiled_sdf_profile.get("wind_gust") if isinstance(compiled_sdf_profile, dict) else None
    )
    wind_requested = compiled is not None or gust_profile is not None
    services_text = _run_gazebo_command(
        [gz_cli, "service", "--list"],
        timeout=10.0,
        failure_context="could not inspect Gazebo services",
    )
    services = set(services_text.split())
    required_services = {generated_sdf_service}
    if wind_requested:
        required_services.add(wind_info_service)
    missing_services = sorted(service for service in required_services if service not in services)
    if missing_services:
        raise ScenarioEffectUnsupportedError(
            "Gazebo physical-profile verification services are unavailable: "
            + ", ".join(missing_services)
        )

    timeout_ms = max(
        100,
        _parse_int(os.environ.get("PX4_GAZEBO_WIND_TIMEOUT_MS"), default=5000),
    )
    vector: dict[str, float] | None = None
    initial_vector = {"x": 0.0, "y": 0.0, "z": 0.0}
    readback: dict[str, Any] | None = None
    if wind_requested:
        vector = (
            gust_profile["mean_linear_velocity_mps"]
            if gust_profile is not None
            else compiled["linear_velocity_mps"]
        )
        wind_message = (
            "linear_velocity { "
            f"x: {initial_vector['x']:.17g} y: {initial_vector['y']:.17g} "
            f"z: {initial_vector['z']:.17g}"
            " } enable_wind: true"
        )
        _run_gazebo_command(
            [
                gz_cli,
                "topic",
                "-t",
                wind_topic,
                "-m",
                "gz.msgs.Wind",
                "-p",
                wind_message,
            ],
            timeout=max(5.0, (timeout_ms / 1000.0) + 2.0),
            failure_context="could not publish Gazebo wind profile",
        )

        readback_error = ""
        attempts = max(
            1,
            min(
                50,
                _parse_int(
                    os.environ.get("PX4_GAZEBO_WIND_READBACK_ATTEMPTS"),
                    default=10,
                ),
            ),
        )
        for attempt in range(attempts):
            try:
                response_text = _run_gazebo_command(
                    [
                        gz_cli,
                        "service",
                        "-s",
                        wind_info_service,
                        "--reqtype",
                        "gz.msgs.Empty",
                        "--reptype",
                        "gz.msgs.Wind",
                        "--timeout",
                        str(timeout_ms),
                        "--req",
                        "",
                    ],
                    timeout=max(5.0, (timeout_ms / 1000.0) + 2.0),
                    failure_context="Gazebo wind_info request failed",
                )
                candidate = _parse_wind_info_response(response_text)
                vector_matches = all(
                    math.isclose(
                        candidate["linear_velocity_mps"][axis],
                        initial_vector[axis],
                        rel_tol=1e-9,
                        abs_tol=1e-9,
                    )
                    for axis in ("x", "y", "z")
                )
                if vector_matches and candidate["enable_wind"] is True:
                    readback = {
                        "linear_velocity_mps": {
                            axis: round(candidate["linear_velocity_mps"][axis], 12)
                            for axis in ("x", "y", "z")
                        },
                        "enable_wind": True,
                    }
                    break
                readback_error = f"mismatched readback {candidate}"
            except RuntimeError as exc:
                readback_error = str(exc)
            if attempt + 1 < attempts:
                time.sleep(0.1)
        if readback is None:
            raise RuntimeError(
                "Gazebo wind_info never proved the zero-wind takeoff profile: " + readback_error
            )

    runtime_sdf: dict[str, Any] | None = None
    runtime_sdf_error = ""
    expected_vehicle_model = overlay.get("px4_vehicle_model_instance")
    if not isinstance(expected_vehicle_model, str) or not re.fullmatch(
        r"x500(?:_depth|_vision)?_0", expected_vehicle_model
    ):
        raise RuntimeError("Trial-local expected PX4 vehicle instance metadata is invalid")
    runtime_sdf_attempts = max(
        1,
        min(
            120,
            _parse_int(
                os.environ.get("PX4_GAZEBO_RUNTIME_SDF_ATTEMPTS"),
                default=60,
            ),
        ),
    )
    generated_path = run_dir / "scenario_runtime" / "generated_world.sdf"
    last_attempt_path = run_dir / "scenario_runtime" / "generated_world.last_attempt.sdf"
    for attempt in range(runtime_sdf_attempts):
        generated_response = _run_gazebo_command(
            [
                gz_cli,
                "service",
                "-s",
                generated_sdf_service,
                "--reqtype",
                "gz.msgs.SdfGeneratorConfig",
                "--reptype",
                "gz.msgs.StringMsg",
                "--timeout",
                str(timeout_ms),
                "--req",
                "global_entity_gen_config { expand_include_tags { data: true } }",
            ],
            timeout=max(5.0, (timeout_ms / 1000.0) + 5.0),
            failure_context="Gazebo generated-world-SDF request failed",
        )
        generated_sdf = _parse_protobuf_string_message(generated_response)
        last_attempt_path.parent.mkdir(parents=True, exist_ok=True)
        last_attempt_path.write_text(generated_sdf, encoding="utf-8")
        try:
            runtime_sdf = _runtime_sdf_profile_observation(
                generated_sdf,
                generated_path=generated_path,
                expected_vehicle_model=expected_vehicle_model,
                applied_sdf_profile=overlay.get("applied_sdf_profile", {}),
                require_wind_mode=wind_requested,
            )
            break
        except RuntimeError as exc:
            runtime_sdf_error = str(exc)
        if attempt + 1 < runtime_sdf_attempts:
            time.sleep(0.25)
    if runtime_sdf is None:
        raise RuntimeError(
            "Gazebo runtime SDF never proved the requested physical profile: " + runtime_sdf_error
        )
    observations: list[dict[str, Any]] = []
    if readback is not None:
        observations.append(
            {
                "source": wind_info_service,
                "kind": "readback",
                "value": readback,
                "sha256": engine.scenario_effect_value_sha256(readback),
            }
        )
    observations.extend(
        [
            {
                "source": generated_sdf_service,
                "kind": "artifact",
                "value": runtime_sdf,
                "sha256": engine.scenario_effect_value_sha256(runtime_sdf),
            },
            {
                "source": "trial_overlay/world_sdf",
                "kind": "artifact",
                "value": {
                    "path": overlay["world_sdf_path"],
                    "sha256": overlay["world_sdf_sha256"],
                    "linear_velocity_mps": vector,
                    "wind_effects_plugin": overlay["wind_effects_plugin"],
                    "materialized_px4_system_plugins": overlay["materialized_px4_system_plugins"],
                    "px4_server_config": {
                        "path": overlay["px4_server_config_path"],
                        "sha256": overlay["px4_server_config_sha256"],
                    },
                },
            },
            {
                "source": "trial_overlay/x500_base_model_sdf",
                "kind": "artifact",
                "value": {
                    "path": overlay["model_sdf_path"],
                    "sha256": overlay["model_sdf_sha256"],
                    "wind_enabled_link": overlay["wind_enabled_link"],
                    "sanitized_classic_material_scripts": overlay[
                        "sanitized_classic_material_scripts"
                    ],
                },
            },
            {
                "source": "trial_overlay/x500_model_sdf",
                "kind": "artifact",
                "value": {
                    "path": overlay.get("vehicle_model_sdf_path"),
                    "sha256": overlay.get("vehicle_model_sdf_sha256"),
                },
            },
            {
                "source": "trial_overlay/px4_gz_env",
                "kind": "artifact",
                "value": {
                    "path": overlay["px4_trial_gz_env_path"],
                    "sha256": overlay["px4_trial_gz_env_sha256"],
                    "rootfs_path": overlay["px4_trial_rootfs_path"],
                    "state_policy": ("clean_copy_without_prior_params_dataman_logs_or_eeprom"),
                },
            },
        ]
    )
    effects_by_id = {effect["effect_id"]: effect for effect in request["effects"]}
    records: dict[str, dict[str, Any]] = {}
    applied_effect_ids = set(compiled["requested_effect_ids"] if compiled else [])
    if compiled_sdf_profile is not None:
        applied_effect_ids.update(compiled_sdf_profile["requested_effect_ids"])
    for effect_id in sorted(applied_effect_ids):
        effect = effects_by_id[effect_id]
        is_steady_wind = effect_id in engine.BUNDLED_STEADY_WIND_EFFECT_IDS
        records[effect_id] = _scenario_effect_record(
            effect,
            status="applied",
            capability_status="available",
            reason=(
                (
                    "Gazebo wind_info proved zero wind for safe takeoff and generated runtime "
                    f"SDF proved {expected_vehicle_model}/base_link WindMode; requested wind "
                    "must be activated after the stable-hover gate"
                )
                if is_steady_wind
                else (
                    "Gazebo generated runtime SDF exactly matched the request-bound "
                    f"x500 physical profile for {effect_id}"
                )
            ),
            evidence={
                "requested_value_sha256": engine.scenario_effect_value_sha256(
                    effect["requested_value"]
                ),
                "compiled_wind": compiled,
                "compiled_sdf_profile": compiled_sdf_profile,
                "verification": {
                    "status": "verified",
                    "method": (
                        "gazebo_zero_wind_takeoff_and_generated_world_sdf"
                        if is_steady_wind
                        else "trial_local_sdf_and_generated_world_sdf"
                    ),
                    "observations": observations,
                },
            },
        )
        if effect_id in engine.BUNDLED_WIND_ACTIVATION_EFFECT_IDS:
            records[effect_id]["_activation_pending"] = True
    return records


def _apply_obstacle_effect(
    effect: dict[str, Any],
    *,
    run_dir: Path,
    world: str,
) -> dict[str, Any]:
    gz_cli = _gazebo_cli()
    if not gz_cli:
        raise ScenarioEffectUnsupportedError(
            "Gazebo gz CLI is unavailable; obstacle injection requires the "
            "/world/<world>/create UserCommands service"
        )
    service = f"/world/{world}/create"
    try:
        services = subprocess.run(  # noqa: S603 - resolved gz executable, fixed argv.
            [gz_cli, "service", "--list"],
            capture_output=True,
            check=False,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise ScenarioEffectUnsupportedError(f"could not inspect Gazebo services: {exc}") from exc
    service_output = _subprocess_text(services.stdout) + "\n" + _subprocess_text(services.stderr)
    if services.returncode != 0 or service not in service_output.split():
        raise ScenarioEffectUnsupportedError(
            f"Gazebo service {service} is unavailable; the world must load the "
            "UserCommands system plugin"
        )

    timeout_ms = max(
        100,
        _parse_int(os.environ.get("PX4_GAZEBO_ENTITY_FACTORY_TIMEOUT_MS"), default=5000),
    )
    created_entities: list[dict[str, Any]] = []
    obstacles = effect["requested_value"]
    for index, obstacle in enumerate(obstacles):
        entity_name, sdf_path, sdf_sha256 = _obstacle_sdf(
            obstacle,
            source_index=index,
            run_dir=run_dir,
        )
        request_text = (
            f'sdf_filename: "{_protobuf_quote(str(sdf_path))}" '
            f'name: "{entity_name}" allow_renaming: false'
        )
        try:
            response = subprocess.run(  # noqa: S603 - resolved gz executable, no shell.
                [
                    gz_cli,
                    "service",
                    "-s",
                    service,
                    "--reqtype",
                    "gz.msgs.EntityFactory",
                    "--reptype",
                    "gz.msgs.Boolean",
                    "--timeout",
                    str(timeout_ms),
                    "--req",
                    request_text,
                ],
                capture_output=True,
                check=False,
                text=True,
                timeout=max(5.0, (timeout_ms / 1000.0) + 2.0),
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise RuntimeError(
                f"Gazebo obstacle create request failed for {entity_name}: {exc}"
            ) from exc
        response_text = _subprocess_text(response.stdout) + "\n" + _subprocess_text(response.stderr)
        accepted = bool(re.search(r"\bdata\s*:\s*true\b", response_text, re.I))
        if response.returncode != 0 or not accepted:
            raise RuntimeError(
                f"Gazebo rejected obstacle {entity_name}: "
                f"exit={response.returncode}, response={response_text.strip()[:400]}"
            )
        created_entities.append(
            {
                "source_index": index,
                "entity_name": entity_name,
                "service": service,
                "response_data": True,
                "sdf_path": str(sdf_path),
                "sdf_sha256": sdf_sha256,
            }
        )
    reason = f"Gazebo acknowledged {len(created_entities)} static obstacle create request(s)"
    return _scenario_effect_record(
        effect,
        status="applied",
        capability_status="available",
        reason=reason,
        evidence={"created_entities": created_entities},
    )


def _load_px4_parameter_request(args: argparse.Namespace) -> dict[str, object]:
    if args.px4_params is None:
        return {}
    if not args.px4_params.is_file():
        raise ValueError(f"PX4 parameter request does not exist: {args.px4_params}")
    payload = _json_load(args.px4_params)
    if not isinstance(payload, dict):
        raise ValueError("PX4 parameter request must be a JSON object")
    return {str(name): value for name, value in payload.items()}


def _parameter_context() -> dict[str, object]:
    raw = os.environ.get("PX4_PARAMETER_CONTEXT_JSON", "").strip()
    if not raw:
        return {}
    payload = json.loads(raw)
    if not isinstance(payload, dict):
        raise ValueError("PX4_PARAMETER_CONTEXT_JSON must be a JSON object")
    return {str(key): value for key, value in payload.items()}


def _parameter_transport() -> str:
    transport = os.environ.get("PX4_PARAMETER_TRANSPORT", "environment").strip().lower()
    if transport not in {"environment", "mavsdk"}:
        raise ValueError("PX4_PARAMETER_TRANSPORT must be environment or mavsdk")
    return transport


def _prepare_px4_launch_environment(
    requested: dict[str, object],
) -> tuple[dict[str, str], dict[str, str]]:
    """Return launch environment and the previous override values for evidence."""

    launch_env = os.environ.copy()
    previous = {key: value for key, value in launch_env.items() if key.startswith("PX4_PARAM_")}
    if requested and _parameter_transport() == "environment":
        engine = _load_parameter_engine()
        launch_env.update(
            engine.build_px4_parameter_environment(
                requested,
                px4_version=os.environ.get("PX4_PARAMETER_PX4_VERSION", "main"),
                enforce_safe_bounds=_parse_bool(
                    os.environ.get("PX4_PARAMETER_ENFORCE_SAFE_BOUNDS"), default=True
                ),
            )
        )
    return launch_env, previous


def _trial_gazebo_partition(run_dir: Path) -> str:
    """Return a deterministic, collision-resistant transport partition per Trial."""

    identity = str(run_dir.resolve(strict=False)).encode("utf-8")
    return f"dronedream_{hashlib.sha256(identity).hexdigest()[:24]}"


def _apply_or_verify_px4_parameters(
    requested: dict[str, object],
    *,
    run_dir: Path,
    previous_environment: dict[str, str],
) -> None:
    if not requested:
        return
    engine = _load_parameter_engine()
    transport = _parameter_transport()
    connection = os.environ.get(
        "PX4_PARAMETER_CONNECTION",
        os.environ.get("PX4_OFFBOARD_CONNECTION", DEFAULT_OFFBOARD_CONNECTION),
    ).strip()
    timeout_seconds = _parse_float(os.environ.get("PX4_PARAMETER_TIMEOUT_SECONDS"), default=15.0)
    px4_version = os.environ.get("PX4_PARAMETER_PX4_VERSION", "main")
    context = _parameter_context()
    enforce_safe = _parse_bool(os.environ.get("PX4_PARAMETER_ENFORCE_SAFE_BOUNDS"), default=True)
    if transport == "environment":
        asyncio.run(
            engine.verify_environment_parameters_with_mavsdk(
                requested,
                run_dir,
                connection=connection,
                previous_environment=previous_environment,
                timeout_seconds=timeout_seconds,
                px4_version=px4_version,
                context=context,
                enforce_safe_bounds=enforce_safe,
                reconcile_live_mismatches=True,
            )
        )
        return
    asyncio.run(
        engine.apply_parameters_with_mavsdk(
            requested,
            run_dir,
            connection=connection,
            timeout_seconds=timeout_seconds,
            px4_version=px4_version,
            context=context,
            enforce_safe_bounds=enforce_safe,
        )
    )


def _normalize_telemetry_payload(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict) or not isinstance(payload.get("samples"), list):
        raise ValueError("telemetry must be an object containing samples[]")
    samples = payload["samples"]
    if not samples:
        raise ValueError("telemetry samples[] cannot be empty")
    if len(samples) > MAX_TELEMETRY_SAMPLES:
        raise ValueError(f"telemetry exceeds the {MAX_TELEMETRY_SAMPLES}-sample contract limit")

    normalized: list[dict[str, Any]] = []
    for idx, sample in enumerate(samples):
        if not isinstance(sample, dict):
            raise ValueError(f"telemetry sample {idx} must be an object")
        for key in REQUIRED_SAMPLE_KEYS:
            if key not in sample:
                raise ValueError(f"telemetry sample {idx} missing required key: {key}")
        cleaned = {
            "t": float(sample["t"]),
            "x": float(sample["x"]),
            "y": float(sample["y"]),
            "z": float(sample["z"]),
            "vx": float(sample["vx"]),
            "vy": float(sample["vy"]),
            "vz": float(sample["vz"]),
            "yaw": float(sample["yaw"]),
            "armed": _bool_from_value(sample["armed"]),
            "mode": str(sample["mode"]),
            "crashed": _bool_from_value(sample["crashed"]),
        }
        for numeric_key in ("t", "x", "y", "z", "vx", "vy", "vz", "yaw"):
            numeric_value = cleaned[numeric_key]
            if (
                isinstance(numeric_value, bool)
                or not isinstance(numeric_value, (int, float))
                or not math.isfinite(numeric_value)
            ):
                raise ValueError(f"telemetry sample {idx} contains non-finite {numeric_key}")
        normalized.append(cleaned)
    for idx in range(1, len(normalized)):
        if normalized[idx]["t"] <= normalized[idx - 1]["t"]:
            raise ValueError(f"telemetry sample {idx} timestamp must be strictly increasing")

    meta = payload.get("meta") if isinstance(payload.get("meta"), dict) else {}
    return {
        "schema_version": "dronedream.telemetry.v1",
        "samples": normalized,
        "meta": meta,
    }


def _write_dry_run_telemetry(path: Path, *, vehicle: str, world: str) -> None:
    payload = {
        "schema_version": "dronedream.telemetry.v1",
        "samples": [
            {
                "t": 0.0,
                "x": 0.0,
                "y": 0.0,
                "z": 3.0,
                "vx": 0.0,
                "vy": 0.0,
                "vz": 0.0,
                "yaw": 0.0,
                "armed": True,
                "mode": "offboard",
                "crashed": False,
            }
        ],
        "meta": {
            "simulator": "px4_gazebo",
            "vehicle": vehicle,
            "world": world,
            "mode": "site_dry_run",
        },
    }
    _json_dump(path, payload)


ULogIdentity = tuple[int, int, int, int]
ULogSnapshot = dict[Path, ULogIdentity]


def _ulog_identity(path: Path) -> ULogIdentity:
    info = path.stat()
    return (
        int(info.st_dev),
        int(info.st_ino),
        int(info.st_mtime_ns),
        int(info.st_size),
    )


def snapshot_ulogs(root: Path) -> ULogSnapshot:
    snapshot: ULogSnapshot = {}
    for path in root.rglob("*.ulg"):
        try:
            if path.is_file():
                snapshot[path.resolve()] = _ulog_identity(path)
        except OSError:
            continue
    return snapshot


def find_latest_ulog(root: Path, *, before: ULogSnapshot | None = None) -> Path:
    candidates = [path for path in root.rglob("*.ulg") if path.is_file()]
    if before is not None:
        changed: list[Path] = []
        for path in candidates:
            try:
                resolved = path.resolve()
                if before.get(resolved) != _ulog_identity(path):
                    changed.append(path)
            except OSError:
                continue
        candidates = changed
    if not candidates:
        qualifier = "new or changed " if before is not None else ""
        raise FileNotFoundError(f"No {qualifier}ULog files found under {root}")
    return max(candidates, key=lambda path: (_ulog_identity(path)[2], str(path)))


def _dataset_map(ulog: Any) -> dict[str, Any]:
    return {dataset.name: dataset for dataset in getattr(ulog, "data_list", [])}


def _sample_indices(length: int, maximum: int | None = None) -> list[int]:
    if length <= 0:
        return []
    if maximum is None:
        maximum = MAX_TELEMETRY_SAMPLES
    if maximum <= 0:
        raise ValueError("maximum telemetry sample count must be positive")
    if length <= maximum:
        return list(range(length))
    if maximum == 1:
        return [length - 1]
    # Integer arithmetic keeps the selection deterministic and preserves both
    # endpoints without accumulating floating-point rounding drift.
    return [index * (length - 1) // (maximum - 1) for index in range(maximum)]


def _to_float_list(values: Any, indices: list[int], *, default: float = 0.0) -> list[float]:
    if values is None:
        return [default] * len(indices)
    return [float(values[idx]) for idx in indices]


def _bool_from_value(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
    # pyulog exposes integer and floating fields as NumPy scalar types.  Those
    # implement numbers.Real but are not instances of Python's built-in
    # int/float classes.  Keep the accepted value set fail-closed at exact
    # Boolean encodings rather than coercing arbitrary truthy objects.
    if isinstance(value, numbers.Real) and not isinstance(value, bool):
        normalized_number = float(value)
        if math.isfinite(normalized_number) and normalized_number in {0.0, 1.0}:
            return normalized_number == 1.0
    raise ValueError(f"invalid boolean telemetry value: {value!r}")


def _armed_from_px4_state(value: Any) -> bool:
    """PX4 vehicle_status.arming_state uses enum value 2 for ARMED."""

    try:
        numeric = int(value)
    except (TypeError, ValueError, OverflowError):
        raise ValueError(f"invalid PX4 arming_state value: {value!r}") from None
    return numeric == 2


def _extract_vehicle_status(
    dataset_map: dict[str, Any], indices: list[int]
) -> tuple[list[bool], list[str]]:
    sample_count = len(indices)
    status = dataset_map.get("vehicle_status")
    if status is None:
        return [True] * sample_count, ["unknown"] * sample_count

    data = status.data
    arming_state_values = data.get("arming_state")
    armed_values = data.get("armed")
    if arming_state_values is not None:
        if len(arming_state_values) == 0:
            armed = [True] * sample_count
        else:
            armed = [
                _armed_from_px4_state(arming_state_values[min(index, len(arming_state_values) - 1)])
                for index in indices
            ]
    elif armed_values is not None:
        if len(armed_values) == 0:
            armed = [True] * sample_count
        else:
            armed = [
                _bool_from_value(armed_values[min(index, len(armed_values) - 1)])
                for index in indices
            ]
    else:
        armed = [True] * sample_count

    nav_state_values = data.get("nav_state")
    if nav_state_values is None or len(nav_state_values) == 0:
        mode = ["unknown"] * sample_count
    else:
        mode = [str(nav_state_values[min(index, len(nav_state_values) - 1)]) for index in indices]
    return armed, mode


def _extract_crash_flags(dataset_map: dict[str, Any], indices: list[int]) -> list[bool]:
    sample_count = len(indices)
    failure = dataset_map.get("failure_detector_status")
    if failure is None:
        return [False] * sample_count

    fields = (
        "fd_alt",
        "fd_arm_escs",
        "fd_battery",
        "fd_ext",
        "fd_imbalanced_prop",
        "fd_motor",
        "fd_pitch",
        "fd_roll",
    )
    flags_by_field: list[Any] = [
        failure.data.get(field) for field in fields if failure.data.get(field) is not None
    ]
    if not flags_by_field:
        return [False] * sample_count

    crashed: list[bool] = []
    for index in indices:
        crashed.append(
            any(
                _bool_from_value(field_values[index])
                for field_values in flags_by_field
                if index < len(field_values)
            )
        )
    return crashed


def _quat_to_yaw(q0: float, q1: float, q2: float, q3: float) -> float:
    siny_cosp = 2.0 * (q0 * q3 + q1 * q2)
    cosy_cosp = 1.0 - 2.0 * (q2 * q2 + q3 * q3)
    return math.atan2(siny_cosp, cosy_cosp)


def _extract_yaw_values(
    dataset_map: dict[str, Any],
    vx_values: list[float],
    vy_values: list[float],
    indices: list[int],
) -> list[float]:
    sample_count = len(indices)
    for attitude_name in (
        "vehicle_attitude",
        "vehicle_attitude_groundtruth",
        "vehicle_attitude_setpoint",
    ):
        attitude_dataset = dataset_map.get(attitude_name)
        if attitude_dataset is None:
            continue
        q0 = attitude_dataset.data.get("q[0]")
        q1 = attitude_dataset.data.get("q[1]")
        q2 = attitude_dataset.data.get("q[2]")
        q3 = attitude_dataset.data.get("q[3]")
        if any(component is None for component in (q0, q1, q2, q3)):
            continue
        size = min(len(q0), len(q1), len(q2), len(q3))
        if size <= 0:
            continue
        attitude_yaw_values = [
            _quat_to_yaw(
                float(q0[min(index, size - 1)]),
                float(q1[min(index, size - 1)]),
                float(q2[min(index, size - 1)]),
                float(q3[min(index, size - 1)]),
            )
            for index in indices
        ]
        return attitude_yaw_values

    yaw_values: list[float] = []
    for idx in range(sample_count):
        vx = vx_values[idx]
        vy = vy_values[idx]
        if abs(vx) > 1e-6 or abs(vy) > 1e-6:
            yaw_values.append(math.atan2(vy, vx))
        else:
            yaw_values.append(0.0)
    return yaw_values


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def retain_ulog_snapshot(source_path: Path, run_dir: Path) -> Path:
    """Copy the exact ULog bytes used for extraction into the Trial run dir."""

    run_dir.mkdir(parents=True, exist_ok=True)
    destination = run_dir / RETAINED_ULOG_NAME
    temporary = run_dir / f".{RETAINED_ULOG_NAME}.{os.getpid()}.{time.time_ns()}.tmp"
    copied = 0
    try:
        source_info = source_path.lstat()
        if stat.S_ISLNK(source_info.st_mode) or not stat.S_ISREG(source_info.st_mode):
            raise ValueError("ULog source must be a regular, non-symlink file")
        with source_path.open("rb") as source, temporary.open("xb") as target:
            opened_info = os.fstat(source.fileno())
            if (
                not stat.S_ISREG(opened_info.st_mode)
                or opened_info.st_dev != source_info.st_dev
                or opened_info.st_ino != source_info.st_ino
            ):
                raise ValueError("ULog source changed before its snapshot was opened")
            while chunk := source.read(1024 * 1024):
                copied += len(chunk)
                if copied > MAX_ULOG_BYTES:
                    raise ValueError(f"ULog exceeds the {MAX_ULOG_BYTES}-byte safety limit")
                target.write(chunk)
            final_info = os.fstat(source.fileno())
            if (
                copied != opened_info.st_size
                or final_info.st_size != opened_info.st_size
                or final_info.st_mtime_ns != opened_info.st_mtime_ns
            ):
                raise ValueError("ULog source changed while its snapshot was being copied")
            target.flush()
            os.fsync(target.fileno())
        if copied == 0:
            raise ValueError("ULog cannot be empty")
        temporary.replace(destination)
    except OSError as exc:
        raise ValueError(f"could not retain ULog snapshot {source_path}: {exc}") from exc
    finally:
        with contextlib.suppress(OSError):
            temporary.unlink()
    return destination


def ulog_to_telemetry_json(ulog_path: Path, output_path: Path, vehicle: str, world: str) -> None:
    try:
        from pyulog import ULog
    except ModuleNotFoundError as exc:  # pragma: no cover - exercised via wrapper integration
        raise RuntimeError("pyulog is required for PX4_TELEMETRY_MODE=ulog") from exc

    try:
        ulog_size = ulog_path.stat().st_size
    except OSError as exc:
        raise ValueError(f"could not inspect ULog {ulog_path}: {exc}") from exc
    if ulog_size > MAX_ULOG_BYTES:
        raise ValueError(f"ULog exceeds the {MAX_ULOG_BYTES}-byte safety limit")

    ulog = ULog(str(ulog_path))
    datasets = _dataset_map(ulog)
    local_position = datasets.get("vehicle_local_position")
    if local_position is None:
        raise ValueError("vehicle_local_position dataset is required in ULog")

    data = local_position.data
    timestamps = data.get("timestamp")
    if timestamps is None or len(timestamps) == 0:
        raise ValueError("vehicle_local_position.timestamp is required and cannot be empty")

    indices = _sample_indices(len(timestamps))
    t0 = float(timestamps[0])
    x_values = _to_float_list(data.get("x"), indices)
    y_values = _to_float_list(data.get("y"), indices)
    z_values = _to_float_list(data.get("z"), indices)
    vx_values = _to_float_list(data.get("vx"), indices)
    vy_values = _to_float_list(data.get("vy"), indices)
    vz_values = _to_float_list(data.get("vz"), indices)
    yaw_values = _extract_yaw_values(datasets, vx_values, vy_values, indices)
    armed_values, mode_values = _extract_vehicle_status(datasets, indices)
    crashed_values = _extract_crash_flags(datasets, indices)

    samples = []
    for output_index, source_index in enumerate(indices):
        samples.append(
            {
                "t": (float(timestamps[source_index]) - t0) / 1_000_000.0,
                "x": x_values[output_index],
                "y": y_values[output_index],
                "z": -z_values[output_index],
                "vx": vx_values[output_index],
                "vy": vy_values[output_index],
                "vz": -vz_values[output_index],
                "yaw": yaw_values[output_index],
                "armed": armed_values[output_index],
                "mode": mode_values[output_index],
                "crashed": crashed_values[output_index],
            }
        )

    if not samples:
        raise ValueError("Converted telemetry samples cannot be empty")

    payload = {
        "samples": samples,
        "meta": {
            "simulator": "px4_gazebo",
            "source": "ulog",
            "ulog_path": str(ulog_path),
            "origin_source_sha256": _sha256_file(ulog_path),
            "origin_source_byte_count": ulog_size,
            "origin_extraction_revision": "pyulog-vehicle-local-position-1.0",
            "origin_coordinate_frame": "PX4_LOCAL_NED",
            "coordinate_transform": (
                "x=north_m;y=east_m;z=-down_m;vx=north_mps;vy=east_mps;vz=-down_mps;yaw=px4_ned_rad"
            ),
            "vehicle": vehicle,
            "world": world,
        },
    }
    _json_dump(output_path, payload)


def _render_launch_command(template: str, values: dict[str, str]) -> str:
    rendered = template
    for key, value in values.items():
        rendered = rendered.replace("{" + key + "}", value)
    return rendered


def _split_command(command: str) -> list[str]:
    """Split configured commands without corrupting native Windows paths."""

    argv = shlex.split(command, posix=os.name != "nt")
    if os.name == "nt":
        return [
            item[1:-1] if len(item) >= 2 and item[0] == item[-1] and item[0] in {'"', "'"} else item
            for item in argv
        ]
    return argv


def _terminate_process_group(proc: subprocess.Popen[str], stderr_log: Path, *, label: str) -> None:
    if proc.poll() is not None:
        return
    if os.name == "nt":
        try:
            subprocess.run(  # noqa: S603, S607
                ["taskkill", "/PID", str(proc.pid), "/T", "/F"],  # noqa: S607
                text=True,
                capture_output=True,
                check=False,
                timeout=WINDOWS_PROCESS_TREE_TERMINATION_TIMEOUT_SECONDS,
            )
            _append_log(
                stderr_log,
                f"[local_px4_launch_wrapper] Sent SIGTERM to {label} process group "
                "(taskkill tree on Windows)",
            )
        except subprocess.TimeoutExpired:
            _append_log(
                stderr_log,
                f"[local_px4_launch_wrapper] Timed out terminating {label} "
                "process tree; killing the launcher process as a fallback",
            )
            with contextlib.suppress(OSError):
                proc.kill()
        except OSError as exc:
            _append_log(
                stderr_log,
                f"[local_px4_launch_wrapper] Could not terminate {label} "
                f"process tree during cleanup: {exc}",
            )
            return
        with contextlib.suppress(subprocess.TimeoutExpired):
            proc.wait(timeout=2.0)
        return

    kill_process_group = getattr(os, "killpg", None)
    if not callable(kill_process_group):
        return
    try:
        kill_process_group(proc.pid, signal.SIGTERM)
        _append_log(
            stderr_log,
            f"[local_px4_launch_wrapper] Sent SIGTERM to {label} process group",
        )
    except OSError:
        return

    deadline = time.time() + 2.0
    while time.time() < deadline:
        if proc.poll() is not None:
            return
        time.sleep(0.1)

    try:
        kill_process_group(proc.pid, getattr(signal, "SIGKILL", signal.SIGTERM))
        _append_log(
            stderr_log,
            f"[local_px4_launch_wrapper] Sent SIGKILL to {label} process group",
        )
    except OSError:
        return


def _launch_process(
    command: str,
    *,
    stdout_log: Path,
    stderr_log: Path,
    launch_env: dict[str, str] | None = None,
) -> subprocess.Popen[str]:
    out_handle = stdout_log.open("a", encoding="utf-8")
    err_handle = stderr_log.open("a", encoding="utf-8")
    start_new_session = os.name != "nt"
    creationflags = 0
    if os.name == "nt":
        creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) | getattr(
            subprocess, "CREATE_NO_WINDOW", 0
        )
        shell_preference = os.environ.get("PX4_WINDOWS_COMMAND_SHELL", "powershell").lower()
        if shell_preference == "direct":
            shell_argv = _split_command(command)
        elif shell_preference == "wsl":
            wsl = shutil.which("wsl")
            if not wsl:
                raise RuntimeError("PX4_WINDOWS_COMMAND_SHELL=wsl but wsl.exe was not found")
            shell_argv = [wsl, "bash", "-lc", command]
        elif shell_preference == "bash":
            bash = shutil.which("bash")
            if not bash:
                raise RuntimeError("PX4_WINDOWS_COMMAND_SHELL=bash but bash was not found")
            shell_argv = [bash, "-lc", command]
        else:
            shell_argv = [
                "powershell.exe",
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                command,
            ]
    else:
        shell_argv = ["bash", "-lc", command]
    proc = subprocess.Popen(  # noqa: S603
        shell_argv,
        stdout=out_handle,
        stderr=err_handle,
        text=True,
        start_new_session=start_new_session,
        creationflags=creationflags,
        env=launch_env,
    )
    proc._stdout_handle = out_handle  # type: ignore[attr-defined]
    proc._stderr_handle = err_handle  # type: ignore[attr-defined]
    return proc


def _close_launch_handles(proc: subprocess.Popen[str]) -> None:
    out_handle = getattr(proc, "_stdout_handle", None)
    err_handle = getattr(proc, "_stderr_handle", None)
    if out_handle is not None:
        out_handle.close()
    if err_handle is not None:
        err_handle.close()


def _cleanup_process(proc: subprocess.Popen[str] | None, stderr_log: Path, *, label: str) -> None:
    if proc is None:
        return
    _terminate_process_group(proc, stderr_log, label=label)
    _close_launch_handles(proc)


def _default_offboard_executor_command() -> str:
    script_path = Path(__file__).resolve().parent / "px4_offboard_track_executor.py"
    return f"{shlex.quote(sys.executable)} {shlex.quote(str(script_path))}"


def _default_track_marker_command(args: argparse.Namespace) -> str:
    script_path = Path(__file__).resolve().parent / "gazebo_track_marker.py"
    z_offset = _parse_float(
        os.environ.get("PX4_GAZEBO_TRACK_MARKER_Z_OFFSET"),
        default=DEFAULT_TRACK_MARKER_Z_OFFSET,
    )
    color = (
        os.environ.get("PX4_GAZEBO_TRACK_MARKER_COLOR", DEFAULT_TRACK_MARKER_COLOR).strip()
        or DEFAULT_TRACK_MARKER_COLOR
    )
    line_width = _parse_float(
        os.environ.get("PX4_GAZEBO_TRACK_MARKER_LINE_WIDTH"),
        default=DEFAULT_TRACK_MARKER_LINE_WIDTH,
    )
    mode = (
        os.environ.get("PX4_GAZEBO_TRACK_MARKER_MODE", DEFAULT_TRACK_MARKER_MODE).strip()
        or DEFAULT_TRACK_MARKER_MODE
    ).lower()
    return (
        f"{shlex.quote(sys.executable)} {shlex.quote(str(script_path))} "
        f"--track {shlex.quote(str(args.track))} "
        f"--world {shlex.quote(args.world)} "
        f"--z-offset {shlex.quote(str(z_offset))} "
        f"--color {shlex.quote(color)} "
        f"--line-width {shlex.quote(str(line_width))} "
        f"--mode {shlex.quote(mode)}"
    )


def _build_track_marker_command(args: argparse.Namespace) -> str:
    override = os.environ.get("PX4_GAZEBO_TRACK_MARKER_COMMAND", "").strip()
    if override:
        return override
    return _default_track_marker_command(args)


def _run_track_marker(args: argparse.Namespace, stderr_log: Path) -> int:
    command = _build_track_marker_command(args)
    stdout_log = args.run_dir / "track_marker_stdout.log"
    stderr_marker_log = args.run_dir / "track_marker_stderr.log"
    _append_log(args.stdout_log, f"[local_px4_launch_wrapper] Track marker command: {command}")
    timeout_seconds = max(
        1.0,
        min(
            300.0,
            _parse_float(
                os.environ.get("PX4_GAZEBO_TRACK_MARKER_PROCESS_TIMEOUT_SECONDS"),
                default=60.0,
            ),
        ),
    )
    try:
        proc = subprocess.run(  # noqa: S603
            _split_command(command),
            text=True,
            capture_output=True,
            check=False,
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired as exc:
        stdout_log.write_text(_subprocess_text(exc.stdout), encoding="utf-8")
        stderr_marker_log.write_text(_subprocess_text(exc.stderr), encoding="utf-8")
        _append_log(
            stderr_log,
            "[local_px4_launch_wrapper] WARNING: track marker timed out "
            f"after {timeout_seconds:g}s",
        )
        return 124
    stdout_log.write_text(proc.stdout or "", encoding="utf-8")
    stderr_marker_log.write_text(proc.stderr or "", encoding="utf-8")
    _append_log(
        args.stdout_log,
        f"[local_px4_launch_wrapper] Track marker exit code: {proc.returncode}",
    )
    if proc.returncode != 0:
        _append_log(
            stderr_log,
            "[local_px4_launch_wrapper] WARNING: track marker failed "
            f"with code {proc.returncode}; see {stderr_marker_log}",
        )
    return proc.returncode


def _build_offboard_executor_argv(args: argparse.Namespace) -> list[str]:
    command = (
        os.environ.get("PX4_OFFBOARD_EXECUTOR_COMMAND", "").strip()
        or _default_offboard_executor_command()
    )
    setpoint_rate_hz = _parse_float(
        os.environ.get("PX4_OFFBOARD_SETPOINT_RATE_HZ"),
        default=DEFAULT_OFFBOARD_SETPOINT_RATE_HZ,
    )
    takeoff_timeout = max(
        1.0,
        min(
            600.0,
            _parse_float(
                os.environ.get("PX4_OFFBOARD_TAKEOFF_TIMEOUT_SECONDS"),
                default=DEFAULT_OFFBOARD_TAKEOFF_TIMEOUT_SECONDS,
            ),
        ),
    )
    track_timeout = max(
        1.0,
        min(
            3600.0,
            _parse_float(
                os.environ.get("PX4_OFFBOARD_TRACK_TIMEOUT_SECONDS"),
                default=DEFAULT_OFFBOARD_TRACK_TIMEOUT_SECONDS,
            ),
        ),
    )
    connection = (
        os.environ.get("PX4_OFFBOARD_CONNECTION", DEFAULT_OFFBOARD_CONNECTION).strip()
        or DEFAULT_OFFBOARD_CONNECTION
    )
    offboard_log = args.run_dir / "offboard_executor.log"

    argv = _split_command(command)
    argv.extend(
        [
            "--run-dir",
            str(args.run_dir),
            "--track",
            str(args.track),
            "--params",
            str(args.params),
            "--vehicle",
            args.vehicle,
            "--world",
            args.world,
            "--connection",
            connection,
            "--setpoint-rate-hz",
            str(setpoint_rate_hz),
            "--takeoff-timeout-seconds",
            str(takeoff_timeout),
            "--track-timeout-seconds",
            str(track_timeout),
            "--log",
            str(offboard_log),
        ]
    )
    return argv


def _run_offboard_executor(args: argparse.Namespace, stderr_log: Path) -> int:
    argv = _build_offboard_executor_argv(args)
    _append_log(
        args.stdout_log,
        f"[local_px4_launch_wrapper] Offboard executor command: {shlex.join(argv)}",
    )
    timeout_seconds = max(
        30.0,
        min(
            7200.0,
            _parse_float(
                os.environ.get("PX4_OFFBOARD_PROCESS_TIMEOUT_SECONDS"),
                default=(
                    DEFAULT_OFFBOARD_TAKEOFF_TIMEOUT_SECONDS
                    + DEFAULT_OFFBOARD_TRACK_TIMEOUT_SECONDS
                    + 180.0
                ),
            ),
        ),
    )
    offboard_env = os.environ.copy()
    # PX4 starts Gazebo with this transport bind address. The offboard child
    # must advertise its runtime-effect publishers on the same interface;
    # otherwise WSL may select its virtual Ethernet address while Gazebo is
    # listening only on loopback, leaving matching topics unable to connect.
    offboard_env["GZ_IP"] = os.environ.get("GZ_IP", "127.0.0.1")
    try:
        proc = subprocess.run(  # noqa: S603
            argv,
            text=True,
            capture_output=True,
            check=False,
            timeout=timeout_seconds,
            env=offboard_env,
        )
    except subprocess.TimeoutExpired as exc:
        if exc.stdout:
            _append_log(args.stdout_log, _subprocess_text(exc.stdout))
        if exc.stderr:
            _append_log(stderr_log, _subprocess_text(exc.stderr))
        _append_log(
            stderr_log,
            f"[local_px4_launch_wrapper] Offboard executor timed out after {timeout_seconds:g}s",
        )
        return 124
    if proc.stdout:
        _append_log(args.stdout_log, proc.stdout)
    if proc.stderr:
        _append_log(stderr_log, proc.stderr)
    return proc.returncode


def _protobuf_field_blocks(text: str, field_name: str) -> list[str]:
    blocks: list[str] = []
    pattern = re.compile(rf"\b{re.escape(field_name)}\s*\{{")
    for match in pattern.finditer(text):
        opening = text.find("{", match.start())
        depth = 0
        in_string = False
        escaped = False
        for index in range(opening, len(text)):
            character = text[index]
            if in_string:
                if escaped:
                    escaped = False
                elif character == "\\":
                    escaped = True
                elif character == '"':
                    in_string = False
                continue
            if character == '"':
                in_string = True
            elif character == "{":
                depth += 1
            elif character == "}":
                depth -= 1
                if depth == 0:
                    blocks.append(text[opening + 1 : index])
                    break
    return blocks


def _parse_actuator_failure_joint_state(
    raw: str,
    profile: dict[str, Any],
    *,
    raw_path: Path,
) -> dict[str, Any]:
    velocities: dict[str, list[float]] = {f"rotor_{number}_joint": [] for number in range(4)}
    for joint_block in _protobuf_field_blocks(raw, "joint"):
        name_match = re.search(r'\bname\s*:\s*"([^"]+)"', joint_block)
        if name_match is None or name_match.group(1) not in velocities:
            continue
        axis_blocks = _protobuf_field_blocks(joint_block, "axis1")
        if len(axis_blocks) != 1:
            continue
        velocity_match = re.search(
            rf"\bvelocity\s*:\s*({_PROTOBUF_NUMBER})",
            axis_blocks[0],
        )
        if velocity_match is None:
            continue
        velocity = float(velocity_match.group(1))
        if not math.isfinite(velocity):
            raise RuntimeError("Gazebo joint-state readback contains non-finite velocity")
        velocities[name_match.group(1)].append(velocity)

    missing = sorted(name for name, values in velocities.items() if not values)
    if missing:
        raise RuntimeError(
            "Gazebo joint-state readback omitted rotor velocity samples: " + ", ".join(missing)
        )
    maxima = {name: max(abs(value) for value in values) for name, values in velocities.items()}
    target_joint = str(profile["target_joint_name"])
    target_max = maxima[target_joint]
    healthy_maxima = {name: value for name, value in maxima.items() if name != target_joint}
    failed_limit = float(profile["max_failed_motor_abs_velocity_rad_s"])
    healthy_minimum = float(profile["min_healthy_motor_abs_velocity_rad_s"])
    hard_stop_verified = target_max <= failed_limit
    healthy_motion_verified = all(value >= healthy_minimum for value in healthy_maxima.values())
    if not hard_stop_verified:
        raise RuntimeError(
            "failed rotor exceeded the hard-stop velocity boundary: "
            f"joint={target_joint}, max={target_max:.17g}, limit={failed_limit:.17g}"
        )
    if not healthy_motion_verified:
        raise RuntimeError(
            "healthy rotors did not all exceed the motion boundary during the "
            f"failure trial: maxima={healthy_maxima}, minimum={healthy_minimum:.17g}"
        )
    return {
        "failure_mode": profile["failure_mode"],
        "failure_start": profile["failure_start"],
        "target_motor_number": int(profile["target_motor_number"]),
        "target_joint_name": target_joint,
        "target_sample_count": len(velocities[target_joint]),
        "target_max_abs_velocity_rad_s": round(target_max, 12),
        "healthy_sample_counts": {name: len(velocities[name]) for name in sorted(healthy_maxima)},
        "healthy_joint_max_abs_velocity_rad_s": {
            name: round(healthy_maxima[name], 12) for name in sorted(healthy_maxima)
        },
        "max_failed_motor_abs_velocity_rad_s": failed_limit,
        "min_healthy_motor_abs_velocity_rad_s": healthy_minimum,
        "hard_stop_verified": hard_stop_verified,
        "healthy_motion_verified": healthy_motion_verified,
        "raw_log_path": str(raw_path),
        "raw_log_sha256": _sha256_hex(raw_path),
    }


def _start_actuator_failure_observer(
    request: dict[str, Any],
    engine: Any,
    overlay: dict[str, Any] | None,
    *,
    run_dir: Path,
) -> dict[str, Any] | None:
    compiled = engine.compile_bundled_sdf_profile(request)
    profile = compiled.get("actuator_failure") if isinstance(compiled, dict) else None
    if not isinstance(profile, dict):
        return None
    if (
        overlay is None
        or overlay.get("compiled_sdf_profile") != compiled
        or overlay.get("applied_sdf_profile", {}).get("actuator_failure") is None
    ):
        raise RuntimeError("actuator-failure observer is missing its exact SDF overlay")
    gz_cli = _gazebo_cli()
    if not gz_cli:
        raise ScenarioEffectUnsupportedError(
            "Gazebo gz CLI is unavailable; hard actuator failure requires joint-state readback"
        )
    topic = str(profile["joint_state_topic"])
    topic_seen = False
    topic_error = ""
    for _attempt in range(50):
        try:
            topics = set(
                _run_gazebo_command(
                    [gz_cli, "topic", "--list"],
                    timeout=5.0,
                    failure_context="could not inspect Gazebo topics",
                ).split()
            )
            if topic in topics:
                topic_seen = True
                break
            topic_error = f"topic {topic!r} not present"
        except RuntimeError as exc:
            topic_error = str(exc)
        time.sleep(0.1)
    if not topic_seen:
        raise ScenarioEffectUnsupportedError(
            "Gazebo actuator-failure joint-state topic is unavailable: " + topic_error
        )

    raw_path = run_dir / "actuator_failure_joint_state.log"
    stderr_path = run_dir / "actuator_failure_joint_state.stderr.log"
    stdout_handle = raw_path.open("w", encoding="utf-8")
    stderr_handle = stderr_path.open("w", encoding="utf-8")
    command = [gz_cli, "topic", "--echo", "--topic", topic]
    stdbuf = shutil.which("stdbuf")
    if stdbuf:
        command = [stdbuf, "-oL", "-eL", *command]
    try:
        process = subprocess.Popen(  # noqa: S603 - resolved executable and fixed argv.
            command,
            stdout=stdout_handle,
            stderr=stderr_handle,
            text=True,
            start_new_session=(os.name != "nt"),
        )
    except Exception:
        stdout_handle.close()
        stderr_handle.close()
        raise
    return {
        "process": process,
        "stdout_handle": stdout_handle,
        "stderr_handle": stderr_handle,
        "raw_path": raw_path,
        "stderr_path": stderr_path,
        "profile": profile,
        "topic": topic,
    }


def _finish_actuator_failure_observer(observer: dict[str, Any]) -> dict[str, Any]:
    process = observer["process"]
    try:
        time.sleep(0.25)
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5.0)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5.0)
    finally:
        observer["stdout_handle"].close()
        observer["stderr_handle"].close()
    raw_path = Path(observer["raw_path"])
    if not raw_path.is_file() or raw_path.stat().st_size > MAX_JSON_BYTES:
        raise RuntimeError("Gazebo actuator-failure joint-state log is missing or too large")
    try:
        raw = raw_path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise RuntimeError("Gazebo actuator-failure joint-state log is unreadable") from exc
    return _parse_actuator_failure_joint_state(
        raw,
        observer["profile"],
        raw_path=raw_path,
    )


def _augment_actuator_failure_record(
    record: dict[str, Any],
    observation: dict[str, Any],
    engine: Any,
    *,
    topic: str,
) -> None:
    evidence = record.get("evidence")
    verification = evidence.get("verification") if isinstance(evidence, dict) else None
    observations = verification.get("observations") if isinstance(verification, dict) else None
    if not isinstance(observations, list):
        raise RuntimeError("actuator-failure SDF evidence is missing verification observations")
    observations.append(
        {
            "source": topic,
            "kind": "readback",
            "value": observation,
            "sha256": engine.scenario_effect_value_sha256(observation),
        }
    )
    verification["method"] = "trial_local_sdf_generated_world_plus_gazebo_joint_state"


def _resolve_real_launch_command(args: argparse.Namespace) -> tuple[str, str | None]:
    setup_commands = os.environ.get("PX4_SETUP_COMMANDS", "").strip()
    simulator_model = args.simulator_model or args.vehicle
    airframe = args.airframe or simulator_model
    make_target = _make_target_for_vehicle(simulator_model)
    launch_template = os.environ.get("PX4_LAUNCH_COMMAND_TEMPLATE", "").strip()
    autopilot_dir = os.environ.get("PX4_AUTOPILOT_DIR", "").strip()

    values = {
        "run_dir": shlex.quote(str(args.run_dir)),
        "input": shlex.quote(str(args.input)),
        "params": shlex.quote(str(args.params)),
        "track": shlex.quote(str(args.track)),
        "telemetry": shlex.quote(str(args.telemetry)),
        "stdout_log": shlex.quote(str(args.stdout_log)),
        "stderr_log": shlex.quote(str(args.stderr_log)),
        "vehicle": shlex.quote(args.vehicle),
        "airframe": shlex.quote(airframe),
        "simulator_model": shlex.quote(simulator_model),
        "world": shlex.quote(args.world),
        "px4_version": shlex.quote(args.px4_version),
        "headless": "1" if _parse_bool(args.headless, default=True) else "0",
        "extra_args": args.extra_args,
        "make_target": shlex.quote(make_target),
        "px4_autopilot_dir": shlex.quote(autopilot_dir),
    }

    if launch_template:
        return _render_launch_command(launch_template, values), autopilot_dir or None

    if not autopilot_dir:
        raise ValueError(
            "PX4_AUTOPILOT_DIR is required in real mode when PX4_LAUNCH_COMMAND_TEMPLATE is unset"
        )

    autopilot_path = Path(autopilot_dir)
    if not autopilot_path.exists() or not autopilot_path.is_dir():
        raise ValueError(f"PX4_AUTOPILOT_DIR does not exist or is not a directory: {autopilot_dir}")

    components: list[str] = []
    if setup_commands:
        components.append(setup_commands)
    components.append(f"cd {shlex.quote(str(autopilot_path))}")
    components.append(f"HEADLESS={values['headless']} make px4_sitl {shlex.quote(make_target)}")
    return "; ".join(components), str(autopilot_path)


def _write_launch_config(
    args: argparse.Namespace,
    *,
    autopilot_dir: str | None,
    setup_commands: str,
    make_target: str,
    px4_parameters: dict[str, object],
    gazebo_transport_partition: str | None = None,
) -> None:
    gui_command = (
        os.environ.get("PX4_GAZEBO_GUI_COMMAND", DEFAULT_GUI_COMMAND).strip() or DEFAULT_GUI_COMMAND
    )
    track_marker_command = _build_track_marker_command(args)
    track_marker_stdout_log = args.run_dir / "track_marker_stdout.log"
    track_marker_stderr_log = args.run_dir / "track_marker_stderr.log"
    gui_stdout_log = args.run_dir / "gui_stdout.log"
    gui_stderr_log = args.run_dir / "gui_stderr.log"
    payload = {
        "vehicle": args.vehicle,
        "airframe": args.airframe or args.vehicle,
        "simulator_model": args.simulator_model or args.vehicle,
        "world": args.world,
        "px4_version": args.px4_version,
        "headless": _parse_bool(args.headless, default=True),
        "make_target": make_target,
        "PX4_AUTOPILOT_DIR": autopilot_dir,
        "PX4_SETUP_COMMANDS": setup_commands,
        "GZ_PARTITION": gazebo_transport_partition,
        "GZ_IP": os.environ.get("GZ_IP", "127.0.0.1"),
        "PX4_PARAMETER_TRANSPORT": _parameter_transport() if px4_parameters else None,
        "px4_parameter_names": sorted(px4_parameters),
        "PX4_ENABLE_OFFBOARD_EXECUTOR": _parse_bool(
            os.environ.get("PX4_ENABLE_OFFBOARD_EXECUTOR"),
            default=DEFAULT_ENABLE_OFFBOARD_EXECUTOR,
        ),
        "PX4_OFFBOARD_CONNECTION": os.environ.get(
            "PX4_OFFBOARD_CONNECTION", DEFAULT_OFFBOARD_CONNECTION
        ),
        "gui_client_enabled": _parse_bool(
            os.environ.get("PX4_GAZEBO_LAUNCH_GUI_CLIENT"),
            default=DEFAULT_LAUNCH_GUI_CLIENT,
        ),
        "gui_command": gui_command,
        "PX4_GAZEBO_RAW_GUI_COMMAND": os.environ.get("PX4_GAZEBO_RAW_GUI_COMMAND", "").strip(),
        "PX4_GAZEBO_GUI_WINDOW_MODE": os.environ.get("PX4_GAZEBO_GUI_WINDOW_MODE", "").strip(),
        "PX4_GAZEBO_GUI_WINDOW_GEOMETRY": os.environ.get(
            "PX4_GAZEBO_GUI_WINDOW_GEOMETRY", ""
        ).strip(),
        "PX4_GAZEBO_GUI_WINDOW_WIDTH": os.environ.get("PX4_GAZEBO_GUI_WINDOW_WIDTH", "").strip(),
        "PX4_GAZEBO_GUI_WINDOW_HEIGHT": os.environ.get("PX4_GAZEBO_GUI_WINDOW_HEIGHT", "").strip(),
        "gui_require_client": _parse_bool(
            os.environ.get("PX4_GAZEBO_REQUIRE_GUI_CLIENT"),
            default=DEFAULT_REQUIRE_GUI_CLIENT,
        ),
        "gui_start_delay_seconds": _parse_float(
            os.environ.get("PX4_GAZEBO_GUI_START_DELAY_SECONDS"),
            default=DEFAULT_GUI_START_DELAY_SECONDS,
        ),
        "gui_wait_timeout_seconds": _parse_float(
            os.environ.get("PX4_GAZEBO_GUI_WAIT_TIMEOUT_SECONDS"),
            default=DEFAULT_GUI_WAIT_TIMEOUT_SECONDS,
        ),
        "track_marker_enabled": _parse_bool(
            os.environ.get("PX4_GAZEBO_DRAW_TRACK_MARKER"),
            default=DEFAULT_DRAW_TRACK_MARKER,
        ),
        "track_marker_command": track_marker_command,
        "track_marker_start_delay_seconds": _parse_float(
            os.environ.get("PX4_GAZEBO_TRACK_MARKER_START_DELAY_SECONDS"),
            default=DEFAULT_TRACK_MARKER_START_DELAY_SECONDS,
        ),
        "track_marker_require": _parse_bool(
            os.environ.get("PX4_GAZEBO_REQUIRE_TRACK_MARKER"),
            default=DEFAULT_REQUIRE_TRACK_MARKER,
        ),
        "track_marker_z_offset": _parse_float(
            os.environ.get("PX4_GAZEBO_TRACK_MARKER_Z_OFFSET"),
            default=DEFAULT_TRACK_MARKER_Z_OFFSET,
        ),
        "track_marker_color": os.environ.get(
            "PX4_GAZEBO_TRACK_MARKER_COLOR", DEFAULT_TRACK_MARKER_COLOR
        ).strip()
        or DEFAULT_TRACK_MARKER_COLOR,
        "track_marker_line_width": _parse_float(
            os.environ.get("PX4_GAZEBO_TRACK_MARKER_LINE_WIDTH"),
            default=DEFAULT_TRACK_MARKER_LINE_WIDTH,
        ),
        "track_marker_mode": os.environ.get(
            "PX4_GAZEBO_TRACK_MARKER_MODE", DEFAULT_TRACK_MARKER_MODE
        ).strip()
        or DEFAULT_TRACK_MARKER_MODE,
        "paths": {
            "run_dir": str(args.run_dir),
            "input": str(args.input),
            "params": str(args.params),
            "px4_params": str(args.px4_params) if args.px4_params is not None else None,
            "track": str(args.track),
            "telemetry": str(args.telemetry),
            "stdout_log": str(args.stdout_log),
            "stderr_log": str(args.stderr_log),
            "gui_stdout_log": str(gui_stdout_log),
            "gui_stderr_log": str(gui_stderr_log),
            "track_marker_stdout_log": str(track_marker_stdout_log),
            "track_marker_stderr_log": str(track_marker_stderr_log),
        },
    }
    launch_config_path = args.run_dir / "launch_config.json"
    existing: dict[str, Any] = {}
    if launch_config_path.is_file():
        with contextlib.suppress(OSError, UnicodeError, json.JSONDecodeError, ValueError):
            loaded = _json_load(launch_config_path)
            if isinstance(loaded, dict):
                existing = loaded
    # The outer runner owns execution identity, firmware verification and
    # timeout semantics. Preserve those fields while adding this wrapper's
    # concrete launch/process details.
    existing.update(payload)
    _json_dump(launch_config_path, existing)


def _automatic_ulog_root() -> Path:
    ulog_root_raw = os.environ.get("PX4_ULOG_ROOT", "").strip()
    if ulog_root_raw:
        return Path(ulog_root_raw)
    autopilot_dir = os.environ.get("PX4_AUTOPILOT_DIR", "").strip()
    if not autopilot_dir:
        raise ValueError("PX4_AUTOPILOT_DIR is required to locate default PX4 ULog root")
    return Path(autopilot_dir) / "build" / "px4_sitl_default" / "rootfs" / "log"


def _prepare_automatic_ulog() -> tuple[Path, ULogSnapshot] | None:
    telemetry_mode = (
        os.environ.get("PX4_TELEMETRY_MODE", DEFAULT_TELEMETRY_MODE).strip().lower()
        or DEFAULT_TELEMETRY_MODE
    )
    if telemetry_mode != "ulog" or os.environ.get("PX4_ULOG_PATH", "").strip():
        return None
    root = _automatic_ulog_root()
    return root, snapshot_ulogs(root)


def _finalize_real_telemetry(
    args: argparse.Namespace,
    *,
    automatic_ulog: tuple[Path, ULogSnapshot] | None,
) -> None:
    telemetry_source = os.environ.get("PX4_TELEMETRY_SOURCE_JSON", "").strip()
    telemetry_mode = (
        os.environ.get("PX4_TELEMETRY_MODE", DEFAULT_TELEMETRY_MODE).strip().lower()
        or DEFAULT_TELEMETRY_MODE
    )

    if telemetry_source:
        source_path = Path(telemetry_source)
        if not source_path.exists():
            raise ValueError(f"PX4_TELEMETRY_SOURCE_JSON does not exist: {telemetry_source}")
        shutil.copyfile(source_path, args.telemetry)

    if telemetry_mode == "json":
        if not args.telemetry.exists():
            raise ValueError("Telemetry JSON missing after launcher exit")
        payload = _json_load(args.telemetry)
        normalized = _normalize_telemetry_payload(payload)
        _json_dump(args.telemetry, normalized)
        return

    if telemetry_mode == "ulog":
        ulog_path_raw = os.environ.get("PX4_ULOG_PATH", "").strip()
        if ulog_path_raw:
            ulog_path = Path(ulog_path_raw)
            if not ulog_path.is_file():
                raise FileNotFoundError(
                    f"PX4_ULOG_PATH does not exist or is not a file: {ulog_path_raw}"
                )
        else:
            if automatic_ulog is None:
                raise RuntimeError("Automatic ULog snapshot was not captured before PX4 launch")
            ulog_root, before = automatic_ulog
            try:
                ulog_path = find_latest_ulog(ulog_root, before=before)
            except FileNotFoundError as exc:
                raise FileNotFoundError(
                    f"No new or changed ULog files were produced by this PX4 run under: {ulog_root}"
                ) from exc

        retained_ulog_path = retain_ulog_snapshot(
            ulog_path,
            args.run_dir,
        )
        ulog_to_telemetry_json(
            retained_ulog_path,
            args.telemetry,
            vehicle=args.vehicle,
            world=args.world,
        )
        payload = _json_load(args.telemetry)
        normalized = _normalize_telemetry_payload(payload)
        _json_dump(args.telemetry, normalized)
        return

    raise ValueError(f"Unsupported PX4_TELEMETRY_MODE: {telemetry_mode}")


def main() -> int:
    args = _parse_args()
    args.run_dir.mkdir(parents=True, exist_ok=True)

    make_target = _make_target_for_vehicle(args.simulator_model or args.vehicle)
    setup_commands = os.environ.get("PX4_SETUP_COMMANDS", "").strip()
    run_seconds = max(1, _parse_int(os.environ.get("PX4_RUN_SECONDS"), default=DEFAULT_RUN_SECONDS))
    ready_timeout_seconds = max(
        1,
        _parse_int(
            os.environ.get("PX4_READY_TIMEOUT_SECONDS"),
            default=DEFAULT_READY_TIMEOUT_SECONDS,
        ),
    )
    site_dry_run = _parse_bool(os.environ.get("PX4_SITE_DRY_RUN"), default=DEFAULT_SITE_DRY_RUN)
    enable_offboard_executor = _parse_bool(
        os.environ.get("PX4_ENABLE_OFFBOARD_EXECUTOR"),
        default=DEFAULT_ENABLE_OFFBOARD_EXECUTOR,
    )
    headless = _parse_bool(args.headless, default=True)
    gui_launch_enabled = _parse_bool(
        os.environ.get("PX4_GAZEBO_LAUNCH_GUI_CLIENT"),
        default=DEFAULT_LAUNCH_GUI_CLIENT,
    )
    require_gui_client = _parse_bool(
        os.environ.get("PX4_GAZEBO_REQUIRE_GUI_CLIENT"),
        default=DEFAULT_REQUIRE_GUI_CLIENT,
    )
    gui_command = (
        os.environ.get("PX4_GAZEBO_GUI_COMMAND", DEFAULT_GUI_COMMAND).strip() or DEFAULT_GUI_COMMAND
    )
    gui_start_delay_seconds = max(
        0.0,
        _parse_float(
            os.environ.get("PX4_GAZEBO_GUI_START_DELAY_SECONDS"),
            default=DEFAULT_GUI_START_DELAY_SECONDS,
        ),
    )
    gui_wait_timeout_seconds = max(
        0.0,
        _parse_float(
            os.environ.get("PX4_GAZEBO_GUI_WAIT_TIMEOUT_SECONDS"),
            default=DEFAULT_GUI_WAIT_TIMEOUT_SECONDS,
        ),
    )
    display = os.environ.get("DISPLAY", "").strip()
    draw_track_marker = _parse_bool(
        os.environ.get("PX4_GAZEBO_DRAW_TRACK_MARKER"),
        default=DEFAULT_DRAW_TRACK_MARKER,
    )
    track_marker_start_delay_seconds = max(
        0.0,
        _parse_float(
            os.environ.get("PX4_GAZEBO_TRACK_MARKER_START_DELAY_SECONDS"),
            default=DEFAULT_TRACK_MARKER_START_DELAY_SECONDS,
        ),
    )
    require_track_marker = _parse_bool(
        os.environ.get("PX4_GAZEBO_REQUIRE_TRACK_MARKER"),
        default=DEFAULT_REQUIRE_TRACK_MARKER,
    )
    gui_stdout_log = args.run_dir / "gui_stdout.log"
    gui_stderr_log = args.run_dir / "gui_stderr.log"

    try:
        scenario_engine, scenario_effect_request, scenario_effect_evidence_path = (
            _load_scenario_effect_request(args.run_dir)
        )
        preflight_effects = _preflight_scenario_effects(
            scenario_effect_request,
            site_dry_run=site_dry_run,
        )
        if preflight_effects is not None and scenario_effect_request is not None:
            _write_scenario_effect_evidence(
                scenario_engine,
                scenario_effect_request,
                scenario_effect_evidence_path,
                world=args.world,
                effects=preflight_effects,
            )
            _append_log(
                args.stdout_log,
                "[local_px4_launch_wrapper] Scenario-effect preflight returned "
                "explicit unsupported/skipped evidence; PX4 was not launched",
            )
            _append_log(args.stderr_log, "")
            return 0
    except Exception as exc:
        _append_log(
            args.stderr_log,
            f"[local_px4_launch_wrapper] Invalid scenario-effect request: {exc}",
        )
        return 2

    try:
        _copy_used_inputs(args.run_dir, args.params, args.track)
        px4_parameters = _load_px4_parameter_request(args)
        gazebo_transport_partition = _trial_gazebo_partition(args.run_dir)
        # Each wrapper is a single-Trial process, so give Gazebo Transport a
        # Trial-private discovery domain. This prevents a just-terminated
        # simulator's subscriber records from accepting wind messages meant
        # for the next Trial in the same worker campaign.
        os.environ["GZ_PARTITION"] = gazebo_transport_partition
        # Resolve this once before constructing any child environment so PX4,
        # Gazebo, the offboard executor, and evidence probes all advertise on
        # the same interface for the complete Trial lifetime.
        os.environ["GZ_IP"] = _gazebo_transport_ip()
        launch_env, previous_parameter_environment = _prepare_px4_launch_environment(px4_parameters)
        launch_env["PX4_GZ_WORLD"] = args.world
    except Exception as exc:
        _append_log(
            args.stderr_log,
            f"[local_px4_launch_wrapper] Failed preparing params/track: {exc}",
        )
        return 2

    if site_dry_run:
        _write_launch_config(
            args,
            autopilot_dir=os.environ.get("PX4_AUTOPILOT_DIR", "").strip() or None,
            setup_commands=setup_commands,
            make_target=make_target,
            px4_parameters=px4_parameters,
            gazebo_transport_partition=gazebo_transport_partition,
        )
        if px4_parameters:
            engine = _load_parameter_engine()
            engine.write_simulated_parameter_evidence(
                px4_parameters,
                args.run_dir,
                px4_version=os.environ.get("PX4_PARAMETER_PX4_VERSION", "main"),
                context=_parameter_context(),
                enforce_safe_bounds=_parse_bool(
                    os.environ.get("PX4_PARAMETER_ENFORCE_SAFE_BOUNDS"), default=True
                ),
            )
        _write_dry_run_telemetry(args.telemetry, vehicle=args.vehicle, world=args.world)
        _append_log(
            args.stdout_log,
            "[local_px4_launch_wrapper] site dry-run enabled; no PX4 process launched",
        )
        _append_log(args.stderr_log, "")
        return 0

    try:
        automatic_ulog = _prepare_automatic_ulog()
    except Exception as exc:
        _append_log(
            args.stderr_log,
            f"[local_px4_launch_wrapper] Failed capturing pre-launch ULog snapshot: {exc}",
        )
        return 2

    px4_proc: subprocess.Popen[str] | None = None
    gui_proc: subprocess.Popen[str] | None = None
    steady_wind_overlay: dict[str, Any] | None = None
    actuator_failure_observer: dict[str, Any] | None = None
    scenario_applied_by_id: dict[str, dict[str, Any]] = {}
    actuator_failure_ids: set[str] = set()
    runtime_effect_ids: set[str] = set()
    previous_signal_handlers: dict[int, Any] = {}

    def _raise_shutdown(signum: int, _frame: Any) -> None:
        raise RuntimeError(f"received shutdown signal {signum}")

    if os.name != "nt":
        for shutdown_signal in (signal.SIGINT, signal.SIGTERM):
            previous_signal_handlers[int(shutdown_signal)] = signal.getsignal(shutdown_signal)
            signal.signal(shutdown_signal, _raise_shutdown)
    try:
        command, resolved_autopilot_dir = _resolve_real_launch_command(args)
        if scenario_effect_request is not None:
            steady_wind_ids = {
                effect["effect_id"]
                for effect in scenario_effect_request["effects"]
                if effect["effect_id"] in scenario_engine.BUNDLED_STEADY_WIND_EFFECT_IDS
                or effect["effect_id"] in scenario_engine.BUNDLED_SDF_PROFILE_EFFECT_IDS
            }
            if steady_wind_ids:
                try:
                    steady_wind_overlay = _prepare_steady_wind_overlay(
                        scenario_effect_request,
                        scenario_engine,
                        run_dir=args.run_dir,
                        autopilot_dir=resolved_autopilot_dir,
                        simulator_model=args.simulator_model or args.vehicle,
                        world=args.world,
                        launch_env=launch_env,
                    )
                except ScenarioEffectUnsupportedError as exc:
                    _write_scenario_effect_evidence(
                        scenario_engine,
                        scenario_effect_request,
                        scenario_effect_evidence_path,
                        world=args.world,
                        effects=_scenario_effect_failure_records(
                            scenario_effect_request,
                            applied_by_id={},
                            failing_ids=steady_wind_ids,
                            reason=str(exc),
                            unsupported=True,
                        ),
                    )
                    raise
                except Exception as exc:
                    _write_scenario_effect_evidence(
                        scenario_engine,
                        scenario_effect_request,
                        scenario_effect_evidence_path,
                        world=args.world,
                        effects=_scenario_effect_failure_records(
                            scenario_effect_request,
                            applied_by_id={},
                            failing_ids=steady_wind_ids,
                            reason=str(exc),
                            unsupported=False,
                        ),
                    )
                    raise
        if steady_wind_overlay is not None:
            command = _wrap_launch_command_for_trial_world(
                command,
                steady_wind_overlay,
                launch_env=launch_env,
                headless=headless,
            )
            if automatic_ulog is not None:
                automatic_ulog = (
                    Path(steady_wind_overlay["px4_trial_rootfs_path"]) / "log",
                    {},
                )
        _write_launch_config(
            args,
            autopilot_dir=resolved_autopilot_dir,
            setup_commands=setup_commands,
            make_target=make_target,
            px4_parameters=px4_parameters,
            gazebo_transport_partition=gazebo_transport_partition,
        )
        _append_log(args.stdout_log, f"[local_px4_launch_wrapper] Launch command: {command}")
        _append_log(
            args.stdout_log,
            f"[local_px4_launch_wrapper] Gazebo Transport partition: {gazebo_transport_partition}",
        )
        px4_proc = _launch_process(
            command,
            stdout_log=args.stdout_log,
            stderr_log=args.stderr_log,
            launch_env=launch_env,
        )
        _append_log(
            args.stdout_log,
            f"[local_px4_launch_wrapper] Waiting {ready_timeout_seconds}s "
            "for PX4 readiness (simple fixed wait)",
        )
        ready_deadline = time.time() + float(ready_timeout_seconds)
        while time.time() < ready_deadline:
            if px4_proc.poll() is not None:
                break
            time.sleep(min(0.1, max(0.0, ready_deadline - time.time())))

        if px4_proc.poll() is not None and px4_proc.returncode != 0:
            raise RuntimeError(
                f"PX4 process exited before execution with code {px4_proc.returncode}"
            )
        if px4_parameters and px4_proc.poll() is not None:
            raise RuntimeError(
                f"PX4 process exited before parameter verification with code {px4_proc.returncode}"
            )
        _apply_or_verify_px4_parameters(
            px4_parameters,
            run_dir=args.run_dir,
            previous_environment=previous_parameter_environment,
        )
        if px4_parameters:
            _append_log(
                args.stdout_log,
                "[local_px4_launch_wrapper] PX4 parameter readback verified before flight",
            )

        if scenario_effect_request is not None and scenario_effect_request["effects"]:
            applied_by_id = scenario_applied_by_id
            runtime_effect_ids = {
                effect["effect_id"]
                for effect in scenario_effect_request["effects"]
                if effect["effect_id"]
                in (
                    scenario_engine.BUNDLED_RUNTIME_EFFECT_IDS
                    | scenario_engine.BUNDLED_WIND_ACTIVATION_EFFECT_IDS
                )
            }
            actuator_failure_ids = {
                effect["effect_id"]
                for effect in scenario_effect_request["effects"]
                if effect["effect_id"] == "scenario_type.actuator_failure"
            }
            if runtime_effect_ids and not enable_offboard_executor:
                reason = "flight-timed scenario effects require PX4_ENABLE_OFFBOARD_EXECUTOR=true"
                _write_scenario_effect_evidence(
                    scenario_engine,
                    scenario_effect_request,
                    scenario_effect_evidence_path,
                    world=args.world,
                    effects=_scenario_effect_failure_records(
                        scenario_effect_request,
                        applied_by_id={},
                        failing_ids=runtime_effect_ids,
                        reason=reason,
                        unsupported=True,
                    ),
                )
                raise ScenarioEffectUnsupportedError(reason)
            steady_wind_ids = {
                effect["effect_id"]
                for effect in scenario_effect_request["effects"]
                if effect["effect_id"] in scenario_engine.BUNDLED_STEADY_WIND_EFFECT_IDS
                or effect["effect_id"] in scenario_engine.BUNDLED_SDF_PROFILE_EFFECT_IDS
            }
            if steady_wind_ids:
                try:
                    applied_by_id.update(
                        _apply_steady_wind_effects(
                            scenario_effect_request,
                            scenario_engine,
                            steady_wind_overlay,
                            run_dir=args.run_dir,
                            world=args.world,
                        )
                    )
                except ScenarioEffectUnsupportedError as exc:
                    _write_scenario_effect_evidence(
                        scenario_engine,
                        scenario_effect_request,
                        scenario_effect_evidence_path,
                        world=args.world,
                        effects=_scenario_effect_failure_records(
                            scenario_effect_request,
                            applied_by_id=applied_by_id,
                            failing_ids=steady_wind_ids,
                            reason=str(exc),
                            unsupported=True,
                        ),
                    )
                    raise
                except Exception as exc:
                    _write_scenario_effect_evidence(
                        scenario_engine,
                        scenario_effect_request,
                        scenario_effect_evidence_path,
                        world=args.world,
                        effects=_scenario_effect_failure_records(
                            scenario_effect_request,
                            applied_by_id=applied_by_id,
                            failing_ids=steady_wind_ids,
                            reason=str(exc),
                            unsupported=False,
                        ),
                    )
                    raise

            obstacle_effect = next(
                (
                    effect
                    for effect in scenario_effect_request["effects"]
                    if effect["effect_id"] == "obstacles"
                ),
                None,
            )
            if obstacle_effect is not None:
                try:
                    applied_by_id["obstacles"] = _apply_obstacle_effect(
                        obstacle_effect,
                        run_dir=args.run_dir,
                        world=args.world,
                    )
                except ScenarioEffectUnsupportedError as exc:
                    _write_scenario_effect_evidence(
                        scenario_engine,
                        scenario_effect_request,
                        scenario_effect_evidence_path,
                        world=args.world,
                        effects=_scenario_effect_failure_records(
                            scenario_effect_request,
                            applied_by_id=applied_by_id,
                            failing_ids={"obstacles"},
                            reason=str(exc),
                            unsupported=True,
                        ),
                    )
                    raise
                except Exception as exc:
                    _write_scenario_effect_evidence(
                        scenario_engine,
                        scenario_effect_request,
                        scenario_effect_evidence_path,
                        world=args.world,
                        effects=_scenario_effect_failure_records(
                            scenario_effect_request,
                            applied_by_id=applied_by_id,
                            failing_ids={"obstacles"},
                            reason=str(exc),
                            unsupported=False,
                        ),
                    )
                    raise
            expected_preflight_ids = {
                effect["effect_id"]
                for effect in scenario_effect_request["effects"]
                if effect["effect_id"] not in runtime_effect_ids
            }
            _validate_pre_executor_effect_records(
                scenario_engine,
                applied_by_id,
                expected_preflight_ids=expected_preflight_ids,
                runtime_effect_ids=runtime_effect_ids,
            )
            if not runtime_effect_ids and not actuator_failure_ids:
                _write_scenario_effect_evidence(
                    scenario_engine,
                    scenario_effect_request,
                    scenario_effect_evidence_path,
                    world=args.world,
                    effects=[
                        applied_by_id[effect["effect_id"]]
                        for effect in scenario_effect_request["effects"]
                    ],
                )
            _append_log(
                args.stdout_log,
                "[local_px4_launch_wrapper] Preflight Gazebo scenario effects applied "
                "with runtime readback evidence",
            )

        should_launch_gui = (not headless) and gui_launch_enabled and bool(display)
        if should_launch_gui:
            if gui_start_delay_seconds > 0:
                _append_log(
                    args.stdout_log,
                    f"[local_px4_launch_wrapper] Waiting {gui_start_delay_seconds}s "
                    "before launching GUI client",
                )
                time.sleep(gui_start_delay_seconds)

            gui_proc = _launch_process(
                gui_command,
                stdout_log=gui_stdout_log,
                stderr_log=gui_stderr_log,
                launch_env=os.environ.copy(),
            )
            _append_log(
                args.stdout_log,
                f"[local_px4_launch_wrapper] GUI client launch command: {gui_command}",
            )

            startup_deadline = time.time() + gui_wait_timeout_seconds
            while time.time() < startup_deadline:
                if gui_proc.poll() is not None:
                    break
                time.sleep(0.1)
            if gui_proc.poll() is not None:
                gui_error = (
                    "[local_px4_launch_wrapper] GUI client exited early "
                    f"with code {gui_proc.returncode}; command={gui_command}"
                )
                _append_log(gui_stderr_log, gui_error)
                _append_log(args.stderr_log, gui_error)
                _close_launch_handles(gui_proc)
                gui_proc = None
                if require_gui_client:
                    raise RuntimeError(
                        "GUI client failed to start and PX4_GAZEBO_REQUIRE_GUI_CLIENT=true"
                    )
            else:
                _append_log(
                    args.stdout_log,
                    f"[local_px4_launch_wrapper] GUI client running after "
                    f"{gui_wait_timeout_seconds}s startup window",
                )
        else:
            reason_bits: list[str] = []
            if headless:
                reason_bits.append("headless=true")
            if not gui_launch_enabled:
                reason_bits.append("PX4_GAZEBO_LAUNCH_GUI_CLIENT=false")
            if not display:
                reason_bits.append("DISPLAY is empty")
            _append_log(
                args.stdout_log,
                "[local_px4_launch_wrapper] GUI client not launched: " + ", ".join(reason_bits),
            )

        if px4_proc.poll() is not None and enable_offboard_executor:
            raise RuntimeError(
                f"PX4 process exited before offboard execution with code {px4_proc.returncode}"
            )

        should_draw_track_marker = (not headless) and bool(display) and draw_track_marker
        if should_draw_track_marker:
            if track_marker_start_delay_seconds > 0:
                _append_log(
                    args.stdout_log,
                    (
                        "[local_px4_launch_wrapper] Waiting "
                        f"{track_marker_start_delay_seconds}s before drawing track marker"
                    ),
                )
                time.sleep(track_marker_start_delay_seconds)
            marker_exit = _run_track_marker(args, args.stderr_log)
            if marker_exit != 0 and require_track_marker:
                raise RuntimeError(
                    "track marker failed and PX4_GAZEBO_REQUIRE_TRACK_MARKER=true "
                    f"(exit={marker_exit})"
                )
        else:
            reason_bits = []
            if headless:
                reason_bits.append("headless=true")
            if not display:
                reason_bits.append("DISPLAY empty")
            if not draw_track_marker:
                reason_bits.append("PX4_GAZEBO_DRAW_TRACK_MARKER=false")
            _append_log(
                args.stdout_log,
                "[local_px4_launch_wrapper] Track marker not launched: " + " / ".join(reason_bits),
            )

        if enable_offboard_executor:
            if scenario_effect_request is not None and actuator_failure_ids:
                try:
                    actuator_failure_observer = _start_actuator_failure_observer(
                        scenario_effect_request,
                        scenario_engine,
                        steady_wind_overlay,
                        run_dir=args.run_dir,
                    )
                except Exception as exc:
                    remaining = {
                        effect_id: record
                        for effect_id, record in scenario_applied_by_id.items()
                        if effect_id not in actuator_failure_ids
                    }
                    _write_scenario_effect_evidence(
                        scenario_engine,
                        scenario_effect_request,
                        scenario_effect_evidence_path,
                        world=args.world,
                        effects=_scenario_effect_failure_records(
                            scenario_effect_request,
                            applied_by_id=remaining,
                            failing_ids=actuator_failure_ids,
                            reason=str(exc),
                            unsupported=isinstance(
                                exc,
                                ScenarioEffectUnsupportedError,
                            ),
                        ),
                    )
                    raise
            executor_exit = _run_offboard_executor(args, args.stderr_log)
            if actuator_failure_observer is not None:
                observer = actuator_failure_observer
                actuator_failure_observer = None
                try:
                    joint_observation = _finish_actuator_failure_observer(observer)
                    effect_id = "scenario_type.actuator_failure"
                    _augment_actuator_failure_record(
                        scenario_applied_by_id[effect_id],
                        joint_observation,
                        scenario_engine,
                        topic=str(observer["topic"]),
                    )
                except Exception as exc:
                    remaining = {
                        effect_id: record
                        for effect_id, record in scenario_applied_by_id.items()
                        if effect_id not in actuator_failure_ids
                    }
                    _write_scenario_effect_evidence(
                        scenario_engine,
                        scenario_effect_request,
                        scenario_effect_evidence_path,
                        world=args.world,
                        effects=_scenario_effect_failure_records(
                            scenario_effect_request,
                            applied_by_id=remaining,
                            failing_ids=actuator_failure_ids,
                            reason=str(exc),
                            unsupported=False,
                        ),
                    )
                    raise
                if executor_exit != 0 or not runtime_effect_ids:
                    _write_scenario_effect_evidence(
                        scenario_engine,
                        scenario_effect_request,
                        scenario_effect_evidence_path,
                        world=args.world,
                        effects=[
                            scenario_applied_by_id[effect["effect_id"]]
                            for effect in scenario_effect_request["effects"]
                        ],
                    )
            if scenario_effect_request is not None and runtime_effect_ids:
                runtime_records = _load_runtime_effect_records(
                    scenario_engine,
                    scenario_effect_request,
                    run_dir=args.run_dir,
                )
                runtime_records = _merge_staged_wind_effect_records(
                    scenario_engine,
                    scenario_applied_by_id,
                    runtime_records,
                )
                scenario_applied_by_id.update(runtime_records)
                expected_effect_ids = {
                    effect["effect_id"] for effect in scenario_effect_request["effects"]
                }
                if set(scenario_applied_by_id) != expected_effect_ids:
                    missing = sorted(expected_effect_ids - set(scenario_applied_by_id))
                    raise RuntimeError(
                        "scenario-effect dispatcher omitted effects after flight: "
                        + ", ".join(missing)
                    )
                _write_scenario_effect_evidence(
                    scenario_engine,
                    scenario_effect_request,
                    scenario_effect_evidence_path,
                    world=args.world,
                    effects=[
                        scenario_applied_by_id[effect["effect_id"]]
                        for effect in scenario_effect_request["effects"]
                    ],
                )
            _append_log(
                args.stdout_log,
                f"[local_px4_launch_wrapper] Offboard executor exit code: {executor_exit}",
            )
            if executor_exit != 0:
                raise RuntimeError(f"offboard executor failed with code {executor_exit}")
            if scenario_effect_request is not None and scenario_effect_request["effects"]:
                expected_effect_ids = {
                    effect["effect_id"] for effect in scenario_effect_request["effects"]
                }
                if set(scenario_applied_by_id) != expected_effect_ids:
                    missing = sorted(expected_effect_ids - set(scenario_applied_by_id))
                    raise RuntimeError(
                        "scenario-effect dispatcher omitted effects after flight: "
                        + ", ".join(missing)
                    )
                _write_scenario_effect_evidence(
                    scenario_engine,
                    scenario_effect_request,
                    scenario_effect_evidence_path,
                    world=args.world,
                    effects=[
                        scenario_applied_by_id[effect["effect_id"]]
                        for effect in scenario_effect_request["effects"]
                    ],
                )
                _append_log(
                    args.stdout_log,
                    "[local_px4_launch_wrapper] All scenario effects verified after flight",
                )
        else:
            _append_log(
                args.stdout_log,
                "[local_px4_launch_wrapper] PX4_ENABLE_OFFBOARD_EXECUTOR=false; "
                "preserving launcher-only behavior",
            )
            if px4_proc.poll() is None:
                time.sleep(float(run_seconds))

        _cleanup_process(gui_proc, args.stderr_log, label="GUI")
        gui_proc = None
        _cleanup_process(px4_proc, args.stderr_log, label="PX4")
        px4_proc = None
        _append_log(
            args.stdout_log,
            "[local_px4_launch_wrapper] PX4 process terminated after execution window",
        )
        _finalize_real_telemetry(args, automatic_ulog=automatic_ulog)
        return 0
    except Exception as exc:
        _cleanup_process(gui_proc, args.stderr_log, label="GUI")
        _cleanup_process(px4_proc, args.stderr_log, label="PX4")
        _append_log(args.stderr_log, f"[local_px4_launch_wrapper] Real mode failure: {exc}")
        return 1
    finally:
        if actuator_failure_observer is not None:
            process = actuator_failure_observer["process"]
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5.0)
                except subprocess.TimeoutExpired:
                    process.kill()
                    with contextlib.suppress(subprocess.TimeoutExpired):
                        process.wait(timeout=5.0)
            actuator_failure_observer["stdout_handle"].close()
            actuator_failure_observer["stderr_handle"].close()
        for shutdown_signal_number, previous_handler in previous_signal_handlers.items():
            signal.signal(shutdown_signal_number, previous_handler)


if __name__ == "__main__":
    raise SystemExit(main())
