from __future__ import annotations

import hashlib
import json
from pathlib import Path
from xml.etree import ElementTree

import pytest

from app.autonomy.catalog import get_bundled_map_manifest, get_scene, list_scenes
from app.autonomy.school_map_artifact import (
    BoxPrimitive,
    export_school_map_gazebo_artifact,
    get_school_map_gazebo_artifact,
    school_map_collision_primitives,
    school_map_runtime_collision_primitives,
)
from app.autonomy.school_map_mission_validation import (
    sample_polyline,
    validate_route_clearance,
)


def test_public_catalog_contains_only_the_real_kumpula_map() -> None:
    scenes = list_scenes()
    assert [(scene.id, scene.name) for scene in scenes] == [("school-campus-v1", "Kumpula Campus")]
    assert get_scene("stairwell-coffee-return") is None
    assert get_scene("forest-gate-inspection") is None
    assert get_scene("service-corridor-dock") is None


def test_kumpula_package_contains_real_3d_geometry_and_no_training_assets() -> None:
    artifact = get_school_map_gazebo_artifact()
    names = set(artifact.package_files)
    assert {
        "meshes/kumpula-buildings.obj",
        "meshes/kumpula-buildings.mtl",
        "meshes/kumpula-ground.obj",
        "materials/textures/kumpula-orthophoto.jpg",
        "collision-primitives.json",
        "qualification-evidence.json",
        "model.sdf",
        "world.sdf",
    }.issubset(names)
    assert all("training" not in name.casefold() for name in names)
    assert b"KumpulaCampusBuildings" in artifact.package_files["meshes/kumpula-buildings.obj"]
    assert len(artifact.package_files["materials/textures/kumpula-orthophoto.jpg"]) > 100_000


def test_kumpula_semantics_bind_named_buildings_and_strict_runtime_coordinates() -> None:
    semantic = json.loads(get_school_map_gazebo_artifact().semantic_json)
    names = {entity["name"] for entity in semantic["entities"]}
    assert {"Exactum", "Physicum", "Chemicum", "Dynamicum"}.issubset(names)
    assert semantic["coordinate_frame"] == "ENU"
    assert semantic["bounds_m"] == {"x": 500.0, "y": 500.0, "z": 35.0}
    assert semantic["runtime_bindings"] == {
        "schema_version": "dronedream.map-runtime-bindings.v1",
        "simulator": "gazebo-harmonic",
        "coordinate_frame": "ENU",
        "vehicle_spawn": {"x": -41.0, "y": -83.0, "z": 0.067},
        "mission_launch_waypoint": {"x": -41.0, "y": -83.0, "z": 1.5},
    }


def test_planning_and_gazebo_use_the_same_collision_boxes() -> None:
    planning = school_map_collision_primitives()
    runtime = school_map_runtime_collision_primitives()
    assert planning == runtime
    assert len(planning) == 44
    assert all(isinstance(primitive, BoxPrimitive) for primitive in planning)
    semantics = {primitive.semantic for primitive in planning}
    assert semantics == {"building", "launch-pad", "pickup-pad"}


def test_reference_route_is_collision_free_for_the_qualified_vehicle() -> None:
    scene = get_scene("school-campus-v1")
    assert scene is not None
    points = [(point.x, point.y, point.z) for point in scene.reference_path]
    result = validate_route_clearance(
        sample_polyline(points, 0.04),
        school_map_collision_primitives(),
    )
    assert result.collisions == ()
    assert result.sample_count == 11_425
    assert result.minimum_clearance_m > 1.2


def test_navigation_graph_exposes_only_flight_verified_public_endpoints() -> None:
    graph_path = (
        Path(__file__).parents[1]
        / "app"
        / "autonomy"
        / "assets"
        / "kumpula-campus"
        / "navigation-graph.json"
    )
    graph = json.loads(graph_path.read_text(encoding="utf-8"))
    assert graph["named_entities"]["campus-south-launch-pad"] == "verified-000"
    assert graph["named_entities"]["chemicum-south-handoff-point"] == "verified-004"
    assert all(edge["qualification"] == "flight-verified" for edge in graph["edges"])
    assert all(len(edge["evidence_sha256"]) == 64 for edge in graph["edges"])


def test_sdf_documents_parse_and_reference_the_kumpula_model() -> None:
    artifact = get_school_map_gazebo_artifact()
    model = ElementTree.fromstring(artifact.model_sdf)
    world = ElementTree.fromstring(artifact.package_files["world.sdf"])
    assert model.find(".//model").attrib["name"] == "kumpula_campus"
    assert world.find(".//model").attrib["name"] == "kumpula_campus"


def test_export_preserves_every_source_byte_and_digest(tmp_path: Path) -> None:
    artifact = get_school_map_gazebo_artifact()
    output = tmp_path / "kumpula-campus"
    hashes = export_school_map_gazebo_artifact(output)
    assert set(hashes) == set(artifact.package_files) | {"summary.json"}
    for name, content in artifact.package_files.items():
        emitted = output / name
        assert emitted.read_bytes() == content
        assert hashes[name] == hashlib.sha256(content).hexdigest()


def test_manifest_is_content_addressed_to_the_current_gazebo_artifact() -> None:
    manifest = get_bundled_map_manifest("school-campus-v1")
    assert manifest is not None
    assert manifest["name"] == "Kumpula Campus"
    assert manifest["bounds_m"] == {"x": 500.0, "y": 500.0, "z": 35.0}
    assert manifest["floor_count"] == 1
    assert manifest["gazebo_artifact"] == get_school_map_gazebo_artifact().summary
    assert manifest["gazebo_artifact"]["collision_primitive_count"] == 44
    assert manifest["gazebo_artifact"]["gazebo_runtime_verified"] is True
    assert manifest["gazebo_artifact"]["px4_mission_smoke_verified"] is True
    assert manifest["gazebo_artifact"]["simulation_execution_ready"] is True
    assert len(manifest["manifest_sha256"]) == 64
    int(manifest["manifest_sha256"], 16)


@pytest.mark.parametrize("key", ["world.sdf", "model.sdf", "semantic.json"])
def test_summary_hashes_match_package_bytes(key: str) -> None:
    artifact = get_school_map_gazebo_artifact()
    expected = hashlib.sha256(artifact.package_files[key]).hexdigest()
    assert artifact.summary["package_file_sha256"][key] == expected
