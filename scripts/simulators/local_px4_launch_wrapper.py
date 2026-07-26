#!/usr/bin/env python3
"""Site-specific PX4/Gazebo launch wrapper used by px4_gazebo_runner.py.

This script is intentionally a thin, configurable launcher layer:
- CI/dev dry-run mode emits deterministic fixture telemetry.
- Real mode launches a local PX4/Gazebo command configured by env vars.
- Telemetry validation/normalization guarantees telemetry JSON exists on success.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import hashlib
import json
import math
import os
import re
import shlex
import shutil
import signal
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

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
MAX_JSON_BYTES = 16 * 1024 * 1024
MAX_TELEMETRY_SAMPLES = 50_000
MAX_ULOG_BYTES = 1024 * 1024 * 1024

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
    engine.write_json_atomic(evidence_path, payload)


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

    unavailable = [
        effect
        for effect in request["effects"]
        if effect["effect_id"] != "obstacles"
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


def _gazebo_cli() -> str | None:
    configured = os.environ.get("DRONEDREAM_GAZEBO_EXECUTABLE", "").strip()
    if configured and Path(configured).is_file():
        return configured
    return shutil.which("gz")


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
            if not math.isfinite(cleaned[numeric_key]):
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
    if isinstance(value, (int, float)) and not isinstance(value, bool):
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
        yaw_values = [
            _quat_to_yaw(
                float(q0[min(index, size - 1)]),
                float(q1[min(index, size - 1)]),
                float(q2[min(index, size - 1)]),
                float(q3[min(index, size - 1)]),
            )
            for index in indices
        ]
        return yaw_values

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
                timeout=10,
            )
            _append_log(
                stderr_log,
                f"[local_px4_launch_wrapper] Sent SIGTERM to {label} process group "
                "(taskkill tree on Windows)",
            )
        except OSError:
            return
        with contextlib.suppress(subprocess.TimeoutExpired):
            proc.wait(timeout=2.0)
        return

    try:
        os.killpg(proc.pid, signal.SIGTERM)
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
        os.killpg(proc.pid, signal.SIGKILL)
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
    try:
        proc = subprocess.run(  # noqa: S603
            argv,
            text=True,
            capture_output=True,
            check=False,
            timeout=timeout_seconds,
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

        ulog_to_telemetry_json(
            ulog_path,
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
    previous_signal_handlers: dict[int, Any] = {}

    def _raise_shutdown(signum: int, _frame: Any) -> None:
        raise RuntimeError(f"received shutdown signal {signum}")

    if os.name != "nt":
        for shutdown_signal in (signal.SIGINT, signal.SIGTERM):
            previous_signal_handlers[int(shutdown_signal)] = signal.getsignal(shutdown_signal)
            signal.signal(shutdown_signal, _raise_shutdown)
    try:
        command, resolved_autopilot_dir = _resolve_real_launch_command(args)
        _write_launch_config(
            args,
            autopilot_dir=resolved_autopilot_dir,
            setup_commands=setup_commands,
            make_target=make_target,
            px4_parameters=px4_parameters,
        )
        _append_log(args.stdout_log, f"[local_px4_launch_wrapper] Launch command: {command}")
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
            obstacle_effect = next(
                effect
                for effect in scenario_effect_request["effects"]
                if effect["effect_id"] == "obstacles"
            )
            try:
                applied_obstacles = _apply_obstacle_effect(
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
                    effects=[
                        _scenario_effect_record(
                            obstacle_effect,
                            status="unsupported",
                            capability_status="unsupported",
                            reason=str(exc),
                        )
                    ],
                )
                raise
            except Exception as exc:
                _write_scenario_effect_evidence(
                    scenario_engine,
                    scenario_effect_request,
                    scenario_effect_evidence_path,
                    world=args.world,
                    effects=[
                        _scenario_effect_record(
                            obstacle_effect,
                            status="failed",
                            capability_status="available",
                            reason=str(exc),
                        )
                    ],
                )
                raise
            _write_scenario_effect_evidence(
                scenario_engine,
                scenario_effect_request,
                scenario_effect_evidence_path,
                world=args.world,
                effects=[applied_obstacles],
            )
            _append_log(
                args.stdout_log,
                "[local_px4_launch_wrapper] Gazebo obstacle creation acknowledged "
                "and scenario-effect evidence written",
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
            executor_exit = _run_offboard_executor(args, args.stderr_log)
            _append_log(
                args.stdout_log,
                f"[local_px4_launch_wrapper] Offboard executor exit code: {executor_exit}",
            )
            if executor_exit != 0:
                raise RuntimeError(f"offboard executor failed with code {executor_exit}")
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
        for shutdown_signal, previous_handler in previous_signal_handlers.items():
            signal.signal(shutdown_signal, previous_handler)


if __name__ == "__main__":
    raise SystemExit(main())
