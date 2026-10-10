"""Load and export the sole bundled Kumpula Campus Gazebo asset."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

VEHICLE_COLLISION_DIAMETER_M = 0.76
VEHICLE_COLLISION_HEIGHT_M = 0.43
PX4_X500_MODEL_ROOT_TO_CONTACT_M = 0.013
PX4_X500_COLLISION_CENTER_ABOVE_MODEL_ROOT_M = (
    PX4_X500_MODEL_ROOT_TO_CONTACT_M + VEHICLE_COLLISION_HEIGHT_M / 2
)
STRUCTURAL_TOLERANCE_M = 0.001


@dataclass(frozen=True)
class BoxPrimitive:
    """An oriented collision box in the map ENU frame."""

    name: str
    center_x: float
    center_y: float
    center_z: float
    size_x: float
    size_y: float
    size_z: float
    semantic: str
    yaw_rad: float = 0.0
    roll_rad: float = 0.0
    pitch_rad: float = 0.0


@dataclass(frozen=True)
class CylinderPrimitive:
    """A cylindrical collision primitive retained by the generic validator."""

    name: str
    center_x: float
    center_y: float
    center_z: float
    radius_m: float
    height_m: float
    semantic: str
    yaw_rad: float = 0.0
    roll_rad: float = 0.0
    pitch_rad: float = 0.0


@dataclass(frozen=True)
class CapsulePrimitive:
    """A capsule collision primitive retained by the generic validator."""

    name: str
    center_x: float
    center_y: float
    center_z: float
    radius_m: float
    length_m: float
    semantic: str
    yaw_rad: float = 0.0
    roll_rad: float = 0.0
    pitch_rad: float = 0.0


@dataclass(frozen=True)
class SpherePrimitive:
    """A spherical collision primitive retained by the generic validator."""

    name: str
    center_x: float
    center_y: float
    center_z: float
    radius_m: float
    semantic: str
    yaw_rad: float = 0.0
    roll_rad: float = 0.0
    pitch_rad: float = 0.0


@dataclass(frozen=True)
class MeshPrimitive:
    """A mesh collision primitive retained by the generic validator."""

    name: str
    center_x: float
    center_y: float
    center_z: float
    uri: str
    semantic: str
    scale_x: float = 1.0
    scale_y: float = 1.0
    scale_z: float = 1.0
    yaw_rad: float = 0.0
    roll_rad: float = 0.0
    pitch_rad: float = 0.0


CollisionPrimitive = (
    BoxPrimitive | CylinderPrimitive | CapsulePrimitive | SpherePrimitive | MeshPrimitive
)


@dataclass(frozen=True)
class SchoolMapGazeboArtifact:
    """Content-addressed in-memory view of the Kumpula runtime package."""

    model_sdf: str
    semantic_json: str
    summary: dict[str, object]
    package_files: dict[str, bytes]


_KUMPULA_PACKAGE_ROOT = Path(__file__).resolve().parent / "assets" / "kumpula-campus" / "gazebo"


def _package_files() -> dict[str, bytes]:
    """Read every Kumpula runtime file, including binary orthophotography."""
    if not _KUMPULA_PACKAGE_ROOT.is_dir():
        raise FileNotFoundError(f"Kumpula map package is missing: {_KUMPULA_PACKAGE_ROOT}")
    files = {
        path.relative_to(_KUMPULA_PACKAGE_ROOT).as_posix(): path.read_bytes()
        for path in sorted(_KUMPULA_PACKAGE_ROOT.rglob("*"))
        if path.is_file() and path.name != "summary.json"
    }
    required = {
        "model.sdf",
        "world.sdf",
        "world.physics.sdf",
        "world.perception.sdf",
        "semantic.json",
        "collision-primitives.json",
        "qualification-evidence.json",
        "materials/textures/kumpula-orthophoto.jpg",
        "meshes/kumpula-buildings.obj",
        "meshes/kumpula-buildings.mtl",
        "meshes/kumpula-ground.obj",
    }
    missing = required - files.keys()
    if missing:
        raise FileNotFoundError(f"Kumpula map package is incomplete: {sorted(missing)}")
    return files


def _collision_boxes() -> list[BoxPrimitive]:
    """Read the exact conservative boxes shared by Gazebo and planning."""
    payload = json.loads(
        (_KUMPULA_PACKAGE_ROOT / "collision-primitives.json").read_text(encoding="utf-8")
    )
    primitives = payload.get("primitives")
    if not isinstance(primitives, list) or not primitives:
        raise ValueError("KUMPULA_COLLISION_PRIMITIVES_MISSING")
    return [BoxPrimitive(**primitive) for primitive in primitives]


def school_map_collision_primitives() -> list[CollisionPrimitive]:
    """Return an independent copy of the authoritative Kumpula collision set."""
    return list(_collision_boxes())


def school_map_runtime_collision_primitives() -> list[CollisionPrimitive]:
    """Use the same collision set at qualification and runtime."""
    return list(_collision_boxes())


def get_school_map_gazebo_summary() -> dict[str, object]:
    """Build a content-addressed summary from the current package bytes."""
    source_summary = json.loads(
        (_KUMPULA_PACKAGE_ROOT / "summary.json").read_text(encoding="utf-8")
    )
    files = _package_files()
    hashes = {name: hashlib.sha256(content).hexdigest() for name, content in files.items()}
    collision_payload = json.loads(files["collision-primitives.json"])
    collision_primitives = collision_payload.get("primitives", [])
    evidence = json.loads(files["qualification-evidence.json"])
    flight_bound_files = evidence.get("flight_bound_files", {})
    postflight_validated_files = evidence.get("postflight_validated_files", {})
    gates = evidence.get("gates", {})
    runtime = evidence.get("runtime", {})
    measurements = evidence.get("measurements", {})
    evidence_valid = (
        evidence.get("schema_version") == "dronedream.kumpula-campus-qualification-evidence.v1"
        and evidence.get("status") == "verified"
        and runtime.get("simulator") == "gazebo-harmonic"
        and runtime.get("autopilot") == "px4"
        and runtime.get("executor_return_code") == 0
        and all(flight_bound_files.get(name) == hashes.get(name) for name in flight_bound_files)
        and set(flight_bound_files)
        == {
            "world.sdf",
            "model.sdf",
            "collision-primitives.json",
        }
        and postflight_validated_files == {"semantic.json": hashes["semantic.json"]}
        and bool(gates)
        and all(value is True for value in gates.values())
        and measurements.get("unsafe_collision_count") == 0
        and int(measurements.get("pose_sample_count", 0)) > 0
    )
    return {
        **source_summary,
        "collision_primitive_count": len(collision_primitives),
        "format": "sdf",
        "sdf_version": "1.9",
        "model_sdf_sha256": hashes["model.sdf"],
        "semantic_sha256": hashes["semantic.json"],
        "world_sdf_sha256": hashes["world.sdf"],
        "physics_world_sdf_sha256": hashes["world.physics.sdf"],
        "perception_world_sdf_sha256": hashes["world.perception.sdf"],
        "package_file_sha256": hashes,
        "package_manifest_sha256": hashlib.sha256(
            json.dumps(hashes, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest(),
        "package_file_count": len(files),
        "gazebo_asset_contract_generated": True,
        "gazebo_cli_validation_required": True,
        "qualification_evidence_sha256": hashes["qualification-evidence.json"],
        "gazebo_runtime_verified": evidence_valid,
        "px4_mission_smoke_verified": evidence_valid,
        "simulation_execution_ready": evidence_valid,
    }


@lru_cache(maxsize=1)
def get_school_map_gazebo_artifact() -> SchoolMapGazeboArtifact:
    """Load the real Kumpula package through the stable map API."""
    files = _package_files()
    return SchoolMapGazeboArtifact(
        model_sdf=files["model.sdf"].decode("utf-8"),
        semantic_json=files["semantic.json"].decode("utf-8"),
        summary=get_school_map_gazebo_summary(),
        package_files=files,
    )


def export_school_map_gazebo_artifact(output_directory: Path) -> dict[str, str]:
    """Export Kumpula byte-for-byte and return every emitted SHA-256 digest."""
    artifact = get_school_map_gazebo_artifact()
    output_directory.mkdir(parents=True, exist_ok=True)
    files = dict(artifact.package_files)
    files["summary.json"] = (json.dumps(artifact.summary, indent=2, sort_keys=True) + "\n").encode(
        "utf-8"
    )
    for name, content in files.items():
        output_path = output_directory / name
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(content)
    return {name: hashlib.sha256(content).hexdigest() for name, content in files.items()}
