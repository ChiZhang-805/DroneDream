#!/usr/bin/env python3
"""Verify the one bundled map/vehicle pair before desktop release staging.

The verifier deliberately reads the DDPKG archives themselves.  Catalog labels,
screenshots, and a previous build receipt are not accepted as substitutes for the
bytes that will be installed on a user's computer.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any
from xml.etree import ElementTree


class AssetVerificationError(ValueError):
    """Raised when a bundled asset cannot support the advertised workflow."""


def _object(value: object, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise AssetVerificationError(f"{label} must be a JSON object")
    return value


def _array(value: object, label: str) -> list[Any]:
    if not isinstance(value, list):
        raise AssetVerificationError(f"{label} must be a JSON array")
    return value


def _text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise AssetVerificationError(f"{label} must be non-empty text")
    return value


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _json_bytes(data: bytes, label: str) -> dict[str, Any]:
    try:
        return _object(json.loads(data.decode("utf-8")), label)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AssetVerificationError(f"{label} is not valid UTF-8 JSON") from exc


def _safe_archive_path(value: str, label: str) -> str:
    path = PurePosixPath(value)
    if not value or path.is_absolute() or ".." in path.parts or "\\" in value:
        raise AssetVerificationError(f"{label} contains an unsafe archive path: {value!r}")
    return path.as_posix()


def _require_subset(actual: set[str], required: set[str], label: str) -> None:
    missing = sorted(required - actual)
    if missing:
        raise AssetVerificationError(f"{label} is missing: {missing}")


def _finite_vector(value: object, label: str) -> tuple[float, float, float]:
    payload = _object(value, label)
    result: list[float] = []
    for axis in ("x", "y", "z"):
        number = payload.get(axis)
        if isinstance(number, bool) or not isinstance(number, (int, float)):
            raise AssetVerificationError(f"{label}.{axis} must be numeric")
        converted = float(number)
        if not math.isfinite(converted):
            raise AssetVerificationError(f"{label}.{axis} must be finite")
        result.append(converted)
    return result[0], result[1], result[2]


@dataclass(frozen=True)
class Package:
    path: Path
    archive_sha256: str
    manifest: dict[str, Any]
    files: dict[str, bytes]
    asset_ir: dict[str, Any]
    qualification: dict[str, Any]


def _load_package(path: Path, expected_sha256: str) -> Package:
    if not path.is_file():
        raise AssetVerificationError(f"DDPKG is missing: {path}")
    raw = path.read_bytes()
    actual_archive_sha256 = _sha256(raw)
    if actual_archive_sha256 != expected_sha256:
        raise AssetVerificationError(
            f"{path.name} SHA-256 mismatch: {actual_archive_sha256} != {expected_sha256}"
        )
    try:
        with zipfile.ZipFile(path) as archive:
            names = archive.namelist()
            if len(names) != len(set(names)):
                raise AssetVerificationError(f"{path.name} contains duplicate archive members")
            normalized_names = {_safe_archive_path(name, path.name) for name in names}
            if normalized_names != set(names):
                raise AssetVerificationError(f"{path.name} contains non-canonical paths")
            files = {name: archive.read(name) for name in names if not name.endswith("/")}
    except zipfile.BadZipFile as exc:
        raise AssetVerificationError(f"{path.name} is not a valid DDPKG ZIP archive") from exc

    manifest = _json_bytes(files.get("manifest.json", b""), f"{path.name}/manifest.json")
    if manifest.get("schema_version") != "dronedream.ddpkg.v1":
        raise AssetVerificationError(f"{path.name} uses an unsupported manifest schema")
    declared_files = _array(manifest.get("files"), f"{path.name}.manifest.files")
    declared_paths: set[str] = set()
    for index, item in enumerate(declared_files):
        entry = _object(item, f"{path.name}.manifest.files[{index}]")
        entry_path = _safe_archive_path(
            _text(entry.get("path"), f"{path.name}.manifest.files[{index}].path"),
            path.name,
        )
        if entry_path in declared_paths:
            raise AssetVerificationError(f"{path.name} declares {entry_path} more than once")
        declared_paths.add(entry_path)
        payload = files.get(entry_path)
        if payload is None:
            raise AssetVerificationError(f"{path.name} omits declared member {entry_path}")
        if entry.get("size_bytes") != len(payload) or entry.get("sha256") != _sha256(payload):
            raise AssetVerificationError(f"{path.name} member receipt drifted: {entry_path}")
    if set(files) != declared_paths | {"manifest.json"}:
        raise AssetVerificationError(f"{path.name} contains undeclared or unlisted members")

    asset_ir_path = _safe_archive_path(
        _text(manifest.get("asset_ir_path"), f"{path.name}.manifest.asset_ir_path"), path.name
    )
    asset_ir = _json_bytes(files.get(asset_ir_path, b""), f"{path.name}/{asset_ir_path}")
    qualification_binding = _object(
        manifest.get("qualification"), f"{path.name}.manifest.qualification"
    )
    if qualification_binding.get("maturity") != "qualified":
        raise AssetVerificationError(f"{path.name} is not marked qualified")
    evidence_paths = _array(
        qualification_binding.get("evidence_paths"), f"{path.name}.qualification.evidence_paths"
    )
    if len(evidence_paths) != 1:
        raise AssetVerificationError(f"{path.name} must bind exactly one qualification receipt")
    evidence_path = _safe_archive_path(
        _text(evidence_paths[0], f"{path.name}.qualification.evidence_path"), path.name
    )
    qualification = _json_bytes(files.get(evidence_path, b""), f"{path.name}/{evidence_path}")
    return Package(path, actual_archive_sha256, manifest, files, asset_ir, qualification)


def _verify_map(package: Package) -> dict[str, Any]:
    ir = package.asset_ir
    if ir.get("kind") != "map" or package.manifest.get("asset_kind") != "map":
        raise AssetVerificationError("school-map.ddpkg is not a map package")
    _require_subset(
        set(_array(ir.get("capabilities"), "map.capabilities")),
        {"gazebo", "semantic-map", "content-addressed"},
        "map capabilities",
    )
    geometry = _object(ir.get("geometry"), "map.geometry")
    physics = _object(ir.get("physics"), "map.physics")
    if int(geometry.get("visual_count", 0)) < 1 or int(geometry.get("collision_count", 0)) < 1:
        raise AssetVerificationError("map must contain visual and collision geometry")
    if physics.get("collision_complete") is not True:
        raise AssetVerificationError("map collision geometry is not complete")
    targets = _array(ir.get("simulation_targets"), "map.simulation_targets")
    if len(targets) != 1 or _object(targets[0], "map target").get("simulator") != "gazebo-harmonic":
        raise AssetVerificationError("map must expose only its verified Gazebo Harmonic target")

    required = {
        "normalized/map/gazebo/model.sdf",
        "normalized/map/gazebo/world.sdf",
        "normalized/map/gazebo/collision-primitives.json",
        "normalized/map/gazebo/semantic.json",
        "normalized/map/navigation-graph.json",
        "normalized/map/gazebo/meshes/kumpula-buildings.obj",
        "normalized/map/gazebo/meshes/kumpula-ground.obj",
        "normalized/map/gazebo/materials/textures/kumpula-orthophoto.jpg",
    }
    _require_subset(set(package.files), required, "map package")
    try:
        ElementTree.fromstring(package.files["normalized/map/gazebo/model.sdf"])
        ElementTree.fromstring(package.files["normalized/map/gazebo/world.sdf"])
    except ElementTree.ParseError as exc:
        raise AssetVerificationError("map SDF is not valid XML") from exc

    semantic = _json_bytes(
        package.files["normalized/map/gazebo/semantic.json"], "map semantic contract"
    )
    if semantic.get("coordinate_frame") != "ENU":
        raise AssetVerificationError("map semantic coordinate frame must be ENU")
    display_name = _object(semantic.get("display_name"), "map.display_name")
    _text(display_name.get("en-US"), "map.display_name.en-US")
    _text(display_name.get("zh-CN"), "map.display_name.zh-CN")
    entities = _array(semantic.get("entities"), "map.entities")
    if len(entities) < 2:
        raise AssetVerificationError("map must expose named mission entities")
    kinds: set[str] = set()
    english_aliases: set[str] = set()
    chinese_aliases: set[str] = set()
    for index, raw_entity in enumerate(entities):
        entity = _object(raw_entity, f"map.entities[{index}]")
        _text(entity.get("entity_id"), f"map.entities[{index}].entity_id")
        _text(entity.get("name"), f"map.entities[{index}].name")
        _text(entity.get("name_zh"), f"map.entities[{index}].name_zh")
        _finite_vector(entity.get("position_m"), f"map.entities[{index}].position_m")
        aliases = {
            _text(alias, f"map.entities[{index}].alias")
            for alias in _array(
                entity.get("aliases"), f"map.entities[{index}].aliases"
            )
        }
        english_aliases.update(alias for alias in aliases if alias.isascii())
        chinese_aliases.update(alias for alias in aliases if not alias.isascii())
        kinds.add(_text(entity.get("kind"), f"map.entities[{index}].kind"))
    _require_subset(kinds, {"launch", "pickup"}, "map mission entity kinds")
    if not english_aliases or not chinese_aliases:
        raise AssetVerificationError("map entities require both English and Chinese aliases")

    graph = _json_bytes(package.files["normalized/map/navigation-graph.json"], "navigation graph")
    nodes = _array(graph.get("nodes"), "navigation nodes")
    edges = _array(graph.get("edges"), "navigation edges")
    node_ids = {
        _text(_object(node, "navigation node").get("node_id"), "navigation node id")
        for node in nodes
    }
    if len(node_ids) != len(nodes) or not edges:
        raise AssetVerificationError("navigation graph must contain unique nodes and edges")
    evidence = package.qualification
    runtime_artifacts = _object(
        _object(evidence.get("runtime_evidence"), "runtime evidence").get("artifacts"),
        "runtime evidence artifacts",
    )
    # Current map packages bind road/open-area graph edges to the reviewed map
    # survey. Older packages used the qualification mission digest for the same
    # check, so retain that read-only fallback without treating a mission route
    # as a reusable navigation route.
    source_evidence = _text(
        runtime_artifacts.get("navigation_evidence_sha256")
        or runtime_artifacts.get("source_mission_evidence_sha256"),
        "navigation evidence SHA-256",
    )
    for raw_edge in edges:
        edge = _object(raw_edge, "navigation edge")
        if edge.get("from_node") not in node_ids or edge.get("to_node") not in node_ids:
            raise AssetVerificationError("navigation edge references an unknown node")
        if (
            edge.get("qualification") not in {"flight-verified", "geometry-derived"}
            or edge.get("evidence_sha256") != source_evidence
        ):
            raise AssetVerificationError(
                "navigation edge is not bound to the reviewed navigation evidence"
            )
    named_entities = _object(graph.get("named_entities"), "navigation named entities")
    if not any(key.isascii() for key in named_entities) or not any(
        not key.isascii() for key in named_entities
    ):
        raise AssetVerificationError("navigation graph requires English and Chinese names")
    if any(value not in node_ids for value in named_entities.values()):
        raise AssetVerificationError("navigation alias references an unknown node")

    return {
        "visuals": int(geometry["visual_count"]),
        "collisions": int(geometry["collision_count"]),
        "named_entities": len(named_entities),
        "navigation_nodes": len(nodes),
        "navigation_edges": len(edges),
        "world_sha256": _sha256(package.files["normalized/map/gazebo/world.sdf"]),
        "semantic_sha256": _sha256(package.files["normalized/map/gazebo/semantic.json"]),
    }


def _verify_vehicle(package: Package) -> dict[str, Any]:
    ir = package.asset_ir
    if ir.get("kind") != "vehicle" or package.manifest.get("asset_kind") != "vehicle":
        raise AssetVerificationError("my-drone.ddpkg is not a vehicle package")
    _require_subset(
        set(_array(ir.get("capabilities"), "vehicle.capabilities")),
        {"gazebo", "content-addressed", "px4.sitl-model=x500", "perception.forward-depth"},
        "vehicle capabilities",
    )
    physics = _object(ir.get("physics"), "vehicle.physics")
    for key in ("collision_complete", "mass_complete", "inertia_complete"):
        if physics.get(key) is not True:
            raise AssetVerificationError(f"vehicle physics field {key} is not complete")
    required_sensors = {"imu", "magnetometer", "barometer", "gps", "odometry", "oakd-lite-depth"}
    sensor_kinds = {
        _text(_object(sensor, "vehicle sensor").get("kind"), "vehicle sensor kind")
        for sensor in _array(ir.get("sensors"), "vehicle.sensors")
    }
    _require_subset(sensor_kinds, required_sensors, "vehicle sensors")
    targets = _array(ir.get("simulation_targets"), "vehicle.simulation_targets")
    if len(targets) != 1:
        raise AssetVerificationError("vehicle must expose exactly one verified simulation target")
    target = _object(targets[0], "vehicle target")
    if target.get("simulator") != "gazebo-harmonic" or target.get("autopilot") != "px4":
        raise AssetVerificationError("vehicle target must be the qualified PX4/Gazebo pair")

    required = {
        "normalized/vehicle/controller_params.json",
        "normalized/vehicle/vehicle.json",
        "normalized/vehicle/gazebo/model.sdf",
        "normalized/vehicle/gazebo/takeout-payload.sdf",
    }
    _require_subset(set(package.files), required, "vehicle package")
    try:
        model = ElementTree.fromstring(package.files["normalized/vehicle/gazebo/model.sdf"])
        payload = ElementTree.fromstring(
            package.files["normalized/vehicle/gazebo/takeout-payload.sdf"]
        )
    except ElementTree.ParseError as exc:
        raise AssetVerificationError("vehicle SDF is not valid XML") from exc
    if model.findtext(".//include/uri") != "model://x500_depth":
        raise AssetVerificationError("vehicle does not bind the qualified PX4 x500_depth model")
    plugin = model.find(".//plugin[@filename='gz-sim-detachable-joint-system']")
    if plugin is None or plugin.findtext("child_model") != "takeout_payload":
        raise AssetVerificationError("vehicle payload attachment plug-in is missing")
    if payload.find(".//collision") is None or payload.find(".//visual") is None:
        raise AssetVerificationError("payload requires both collision and visual geometry")
    return {
        "sensors": sorted(sensor_kinds),
        "vehicle_sha256": _sha256(package.files["normalized/vehicle/gazebo/model.sdf"]),
        "controller_sha256": _sha256(package.files["normalized/vehicle/controller_params.json"]),
    }


def verify(asset_root: Path, license_manifest_path: Path) -> dict[str, Any]:
    """Verify the exact active asset pair and return a compact release receipt."""
    index_path = asset_root / "index.json"
    index = _json_bytes(index_path.read_bytes(), "default asset index")
    if index.get("schema_version") != "dronedream.bundled-assets.v3":
        raise AssetVerificationError("default asset index must use bundled-assets.v3")
    pairs = _array(index.get("qualified_pairs"), "qualified_pairs")
    pair = _object(index.get("qualified_pair"), "qualified pair")
    if not pairs or pair not in pairs:
        raise AssetVerificationError("the active qualified pair must be present in the catalog")
    packages = [
        _object(value, "qualified pair package")
        for value in _array(pair.get("packages"), "pair packages")
    ]
    if len(packages) != 2 or {value.get("kind") for value in packages} != {"map", "vehicle"}:
        raise AssetVerificationError("qualified pair must contain one map and one vehicle")
    loaded: dict[str, Package] = {}
    for entry in packages:
        kind = _text(entry.get("kind"), "package kind")
        file_name = _safe_archive_path(_text(entry.get("file"), "package file"), "asset index")
        if PurePosixPath(file_name).parent != PurePosixPath("."):
            raise AssetVerificationError(
                "default DDPKG files must be direct children of the asset root"
            )
        package = _load_package(
            asset_root / file_name, _text(entry.get("sha256"), "package SHA-256")
        )
        if package.manifest.get("asset_id") != entry.get("asset_id"):
            raise AssetVerificationError(f"{file_name} asset ID does not match the index")
        if package.manifest.get("content_sha256") != entry.get("content_sha256"):
            raise AssetVerificationError(f"{file_name} content identity does not match the index")
        loaded[kind] = package

    map_summary = _verify_map(loaded["map"])
    vehicle_summary = _verify_vehicle(loaded["vehicle"])
    map_receipt = loaded["map"].qualification
    vehicle_receipt = loaded["vehicle"].qualification
    if map_receipt != vehicle_receipt:
        raise AssetVerificationError("map and vehicle do not carry the same pair receipt bytes")
    if (
        map_receipt.get("status") != "verified"
        or map_receipt.get("qualification_id") != pair.get("qualification_id")
    ):
        raise AssetVerificationError("asset pair receipt is not the active verified qualification")
    receipt_path = _text(
        _array(
            loaded["map"].manifest["qualification"]["evidence_paths"],
            "receipt paths",
        )[0],
        "receipt path",
    )
    if pair.get("receipt_sha256") != _sha256(loaded["map"].files[receipt_path]):
        raise AssetVerificationError(
            "qualified pair receipt SHA-256 does not match the archive"
        )
    runtime = _object(map_receipt.get("runtime_evidence"), "pair runtime evidence")
    if runtime.get("status") != "verified":
        raise AssetVerificationError("pair runtime evidence is not verified")
    gates = _object(runtime.get("gates"), "pair runtime gates")
    if not gates or any(value is not True for value in gates.values()):
        raise AssetVerificationError("every recorded runtime evidence gate must pass")
    artifacts = _object(runtime.get("artifacts"), "pair runtime artifacts")
    expected_artifacts = {
        "world_sha256": map_summary["world_sha256"],
        "semantic_sha256": map_summary["semantic_sha256"],
        "vehicle_sha256": vehicle_summary["vehicle_sha256"],
        "controller_params_sha256": vehicle_summary["controller_sha256"],
    }
    for key, expected in expected_artifacts.items():
        if artifacts.get(key) != expected:
            raise AssetVerificationError(f"runtime evidence is not bound to current {key}")

    license_manifest = _json_bytes(license_manifest_path.read_bytes(), "asset license manifest")
    if license_manifest.get("license_expression") != "MIT":
        raise AssetVerificationError("first-party default assets require an explicit MIT grant")
    licensed_assets = _array(license_manifest.get("assets"), "licensed assets")
    licensed = {
        (
            _text(item.get("asset_id"), "licensed asset id"),
            _text(item.get("sha256"), "licensed SHA-256"),
        )
        for item in (_object(value, "licensed asset") for value in licensed_assets)
    }
    active = {
        (str(entry["asset_id"]), loaded[str(entry["kind"])].archive_sha256)
        for entry in packages
    }
    if licensed != active:
        raise AssetVerificationError("license grant does not identify the exact active archives")

    return {
        "schema_version": "dronedream.qualified-default-assets-release-check.v1",
        "status": "verified",
        "qualification_id": pair["qualification_id"],
        "simulator": "gazebo-harmonic",
        "autopilot": "px4",
        "map": map_summary,
        "vehicle": vehicle_summary,
        "license": "MIT",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--asset-root", required=True, type=Path)
    parser.add_argument("--license-manifest", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        receipt = verify(args.asset_root.resolve(), args.license_manifest.resolve())
    except (AssetVerificationError, FileNotFoundError, OSError) as exc:
        print(f"default asset verification failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(receipt, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
