from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from xml.etree import ElementTree

import pytest

from app.autonomy.catalog import get_bundled_map_manifest, get_scene, list_scenes
from app.autonomy.qualification import MapPackQualificationRequest, qualify_map_pack
from app.autonomy.school_map_artifact import (
    PHYSICAL_MATERIAL_PROFILES,
    PX4_X500_COLLISION_CENTER_ABOVE_MODEL_ROOT_M,
    PX4_X500_MODEL_ROOT_TO_CONTACT_M,
    ROAD_NETWORK,
    ROUTE_ENDPOINT_TOLERANCE_M,
    SEMANTIC_FLOAT_DECIMAL_PLACES,
    SEMANTIC_PHYSICAL_MATERIAL,
    STRUCTURAL_TOLERANCE_M,
    TEACHING_OPEN_DOOR_CLEARANCE_M,
    TEACHING_OPEN_DOOR_PAIR_CENTER_X,
    VEHICLE_COLLISION_DIAMETER_M,
    VEHICLE_COLLISION_HEIGHT_M,
    BoxPrimitive,
    CapsulePrimitive,
    CylinderPrimitive,
    MeshPrimitive,
    SpherePrimitive,
    _canonicalize_semantic_value,
    export_school_map_gazebo_artifact,
    get_school_map_gazebo_artifact,
    get_school_map_gazebo_summary,
    school_map_collision_primitives,
    school_map_runtime_collision_primitives,
)

VEHICLE_COLLISION_RADIUS_M = VEHICLE_COLLISION_DIAMETER_M / 2
VEHICLE_COLLISION_HALF_HEIGHT_M = VEHICLE_COLLISION_HEIGHT_M / 2
ROUTE_COLLISION_SAMPLE_M = 0.04


def test_school_map_semantic_float_projection_is_cross_platform_stable() -> None:
    assert SEMANTIC_FLOAT_DECIMAL_PLACES == 12
    windows_libm_value = 0.923884769991249355
    linux_libm_value = 0.923884769991250021

    assert _canonicalize_semantic_value(windows_libm_value) == _canonicalize_semantic_value(
        linux_libm_value
    )
    canonical_zero = _canonicalize_semantic_value(-0.0)
    assert isinstance(canonical_zero, float)
    assert canonical_zero == 0.0
    assert math.copysign(1.0, canonical_zero) == 1.0
    with pytest.raises(ValueError, match="must be finite"):
        _canonicalize_semantic_value(math.inf)


def _bounds(primitive: object, axis: str) -> tuple[float, float]:
    center = getattr(primitive, f"center_{axis}")
    if hasattr(primitive, f"size_{axis}"):
        size = getattr(primitive, f"size_{axis}")
    elif hasattr(primitive, "height_m") and axis == "z":
        size = primitive.height_m
    elif hasattr(primitive, "radius_m"):
        size = primitive.radius_m * 2
    else:
        raise TypeError(f"No axis-aligned bounds for {primitive!r}")
    return center - size / 2, center + size / 2


def _box_horizontal_bounds_x(primitive: BoxPrimitive) -> tuple[float, float]:
    half_extent = (
        abs(math.cos(primitive.yaw_rad)) * primitive.size_x / 2
        + abs(math.sin(primitive.yaw_rad)) * primitive.size_y / 2
    )
    return primitive.center_x - half_extent, primitive.center_x + half_extent


def _box_horizontal_bounds_y(primitive: BoxPrimitive) -> tuple[float, float]:
    half_extent = (
        abs(math.sin(primitive.yaw_rad)) * primitive.size_x / 2
        + abs(math.cos(primitive.yaw_rad)) * primitive.size_y / 2
    )
    return primitive.center_y - half_extent, primitive.center_y + half_extent


def _boxes_have_positive_volume_overlap(a: BoxPrimitive, b: BoxPrimitive) -> bool:
    if (
        min(_box_horizontal_bounds_x(a)[1], _box_horizontal_bounds_x(b)[1])
        - max(_box_horizontal_bounds_x(a)[0], _box_horizontal_bounds_x(b)[0])
        <= STRUCTURAL_TOLERANCE_M
        or min(_box_horizontal_bounds_y(a)[1], _box_horizontal_bounds_y(b)[1])
        - max(_box_horizontal_bounds_y(a)[0], _box_horizontal_bounds_y(b)[0])
        <= STRUCTURAL_TOLERANCE_M
    ):
        return False
    if (
        min(_bounds(a, "z")[1], _bounds(b, "z")[1]) - max(_bounds(a, "z")[0], _bounds(b, "z")[0])
        <= STRUCTURAL_TOLERANCE_M
    ):
        return False

    def corners(item: BoxPrimitive) -> list[tuple[float, float]]:
        cosine = math.cos(item.yaw_rad)
        sine = math.sin(item.yaw_rad)
        return [
            (
                item.center_x + cosine * x - sine * y,
                item.center_y + sine * x + cosine * y,
            )
            for x, y in (
                (-item.size_x / 2, -item.size_y / 2),
                (-item.size_x / 2, item.size_y / 2),
                (item.size_x / 2, item.size_y / 2),
                (item.size_x / 2, -item.size_y / 2),
            )
        ]

    a_corners = corners(a)
    b_corners = corners(b)
    axes = (
        (math.cos(a.yaw_rad), math.sin(a.yaw_rad)),
        (-math.sin(a.yaw_rad), math.cos(a.yaw_rad)),
        (math.cos(b.yaw_rad), math.sin(b.yaw_rad)),
        (-math.sin(b.yaw_rad), math.cos(b.yaw_rad)),
    )
    for axis_x, axis_y in axes:
        a_projection = [x * axis_x + y * axis_y for x, y in a_corners]
        b_projection = [x * axis_x + y * axis_y for x, y in b_corners]
        overlap = min(max(a_projection), max(b_projection)) - max(
            min(a_projection), min(b_projection)
        )
        if overlap <= STRUCTURAL_TOLERANCE_M:
            return False
    return True


def _cylinder_axis_endpoints(
    primitive: CylinderPrimitive | CapsulePrimitive,
) -> tuple[tuple[float, float, float], tuple[float, float, float]]:
    roll = primitive.roll_rad
    pitch = primitive.pitch_rad
    yaw = primitive.yaw_rad
    axis = (
        math.cos(yaw) * math.sin(pitch) * math.cos(roll) + math.sin(yaw) * math.sin(roll),
        math.sin(yaw) * math.sin(pitch) * math.cos(roll) - math.cos(yaw) * math.sin(roll),
        math.cos(pitch) * math.cos(roll),
    )
    half_length = (
        primitive.height_m if isinstance(primitive, CylinderPrimitive) else primitive.length_m
    ) / 2
    center = (primitive.center_x, primitive.center_y, primitive.center_z)
    return (
        tuple(center[index] - axis[index] * half_length for index in range(3)),
        tuple(center[index] + axis[index] * half_length for index in range(3)),
    )


def _point_segment_distance(
    point: tuple[float, float, float],
    start: tuple[float, float, float],
    end: tuple[float, float, float],
) -> float:
    delta = tuple(end[index] - start[index] for index in range(3))
    length_squared = sum(component * component for component in delta)
    if length_squared == 0:
        return math.dist(point, start)
    ratio = max(
        0.0,
        min(
            1.0,
            sum((point[index] - start[index]) * delta[index] for index in range(3))
            / length_squared,
        ),
    )
    closest = tuple(start[index] + ratio * delta[index] for index in range(3))
    return math.dist(point, closest)


def _vehicle_intersects_primitive(
    point: tuple[float, float, float],
    primitive: (
        BoxPrimitive | CylinderPrimitive | CapsulePrimitive | SpherePrimitive | MeshPrimitive
    ),
) -> bool:
    if isinstance(primitive, BoxPrimitive):
        if (
            abs(point[2] - primitive.center_z)
            > primitive.size_z / 2 + VEHICLE_COLLISION_HALF_HEIGHT_M
        ):
            return False
        delta_x = point[0] - primitive.center_x
        delta_y = point[1] - primitive.center_y
        cosine = math.cos(primitive.yaw_rad)
        sine = math.sin(primitive.yaw_rad)
        local_x = cosine * delta_x + sine * delta_y
        local_y = -sine * delta_x + cosine * delta_y
        outside_x = max(abs(local_x) - primitive.size_x / 2, 0.0)
        outside_y = max(abs(local_y) - primitive.size_y / 2, 0.0)
        return math.hypot(outside_x, outside_y) <= VEHICLE_COLLISION_RADIUS_M
    vehicle_sphere_radius = math.hypot(
        VEHICLE_COLLISION_RADIUS_M,
        VEHICLE_COLLISION_HALF_HEIGHT_M,
    )
    if isinstance(primitive, (CylinderPrimitive, CapsulePrimitive)):
        if (
            isinstance(primitive, CylinderPrimitive)
            and abs(primitive.roll_rad) <= 1e-12
            and abs(primitive.pitch_rad) <= 1e-12
        ):
            horizontal_distance = math.hypot(
                point[0] - primitive.center_x,
                point[1] - primitive.center_y,
            )
            vertical_distance = abs(point[2] - primitive.center_z)
            return (
                horizontal_distance <= primitive.radius_m + VEHICLE_COLLISION_RADIUS_M
                and vertical_distance <= primitive.height_m / 2 + VEHICLE_COLLISION_HALF_HEIGHT_M
            )
        start, end = _cylinder_axis_endpoints(primitive)
        return (
            _point_segment_distance(point, start, end) <= primitive.radius_m + vehicle_sphere_radius
        )
    if isinstance(primitive, SpherePrimitive):
        return (
            math.dist(point, (primitive.center_x, primitive.center_y, primitive.center_z))
            <= primitive.radius_m + vehicle_sphere_radius
        )
    if not isinstance(primitive, MeshPrimitive):
        raise TypeError(f"Unsupported collision primitive {primitive!r}")
    return False


def _sample_reference_route() -> list[tuple[float, float, float]]:
    scene = get_scene("school-campus-v1")
    assert scene is not None
    samples: list[tuple[float, float, float]] = []
    for start, end in zip(scene.reference_path[:-1], scene.reference_path[1:], strict=True):
        start_point = (start.x, start.y, start.z)
        end_point = (end.x, end.y, end.z)
        sample_count = max(
            1,
            math.ceil(math.dist(start_point, end_point) / ROUTE_COLLISION_SAMPLE_M),
        )
        samples.extend(
            tuple(
                start_point[axis]
                + (end_point[axis] - start_point[axis]) * sample_index / sample_count
                for axis in range(3)
            )
            for sample_index in range(sample_count)
        )
    final = scene.reference_path[-1]
    samples.append((final.x, final.y, final.z))
    return samples


def test_school_map_exports_parseable_content_addressed_sdf() -> None:
    artifact = get_school_map_gazebo_artifact()
    assert artifact.summary == get_school_map_gazebo_summary()


def test_school_map_physical_material_contract_covers_every_collision() -> None:
    primitives = school_map_collision_primitives()
    runtime_primitives = school_map_runtime_collision_primitives()
    semantics = {primitive.semantic for primitive in (*primitives, *runtime_primitives)}

    assert semantics == set(SEMANTIC_PHYSICAL_MATERIAL)
    assert set(SEMANTIC_PHYSICAL_MATERIAL.values()) <= set(PHYSICAL_MATERIAL_PROFILES)
    for profile in PHYSICAL_MATERIAL_PROFILES.values():
        assert profile["density_kg_m3"] > 0
        assert profile["youngs_modulus_pa"] > 0
        assert 0 < profile["poisson_ratio"] < 0.5
        assert profile["characteristic_strength_mpa"] > 0
        assert 0 < profile["friction_mu"] <= 2
        assert 0 < profile["friction_mu2"] <= profile["friction_mu"]
        assert 0 <= profile["restitution"] <= 1
        assert profile["contact_stiffness_n_m"] > 0
        assert profile["contact_damping_n_s_m"] > 0
        assert 0 < profile["visual_opacity"] <= 1


def test_runtime_collision_envelopes_contain_every_omitted_detail_solid() -> None:
    detailed = [
        primitive
        for primitive in school_map_collision_primitives()
        if not isinstance(primitive, MeshPrimitive)
    ]
    runtime = school_map_runtime_collision_primitives()
    runtime_names = {primitive.name for primitive in runtime}
    envelopes = [
        primitive for primitive in runtime if primitive.semantic.startswith("conservative-")
    ]

    def contains(envelope: object, detail: object) -> bool:
        tolerance = 1e-9
        if isinstance(envelope, BoxPrimitive) and isinstance(detail, BoxPrimitive):
            return all(
                envelope_bounds[0] <= detail_bounds[0] + tolerance
                and envelope_bounds[1] >= detail_bounds[1] - tolerance
                for envelope_bounds, detail_bounds in (
                    (_box_horizontal_bounds_x(envelope), _box_horizontal_bounds_x(detail)),
                    (_box_horizontal_bounds_y(envelope), _box_horizontal_bounds_y(detail)),
                    (_bounds(envelope, "z"), _bounds(detail, "z")),
                )
            )
        if isinstance(envelope, SpherePrimitive) and isinstance(detail, SpherePrimitive):
            return (
                math.dist(
                    (envelope.center_x, envelope.center_y, envelope.center_z),
                    (detail.center_x, detail.center_y, detail.center_z),
                )
                + detail.radius_m
                <= envelope.radius_m + tolerance
            )
        return False

    omitted = [primitive for primitive in detailed if primitive.name not in runtime_names]
    assert len(detailed) == 4023
    assert len(runtime) == 1535
    assert len(omitted) == 2788
    for detail in omitted:
        assert any(contains(envelope, detail) for envelope in envelopes), detail.name


def test_school_map_material_contract_preserves_realtime_rigid_contact() -> None:
    artifact = get_school_map_gazebo_artifact()
    semantic = json.loads(artifact.semantic_json)
    root = ElementTree.fromstring(artifact.model_sdf)
    collisions = root.findall(".//collision")
    material_contract = semantic["physical_material_contract"]

    assert len(collisions) == artifact.summary["collision_primitive_count"]
    assert all(collision.find("surface") is None for collision in collisions)
    assert material_contract["gazebo_contact_model"] == "dart-default-rigid-contact"
    assert material_contract["custom_elastic_contact_enabled"] is False
    assert material_contract["profiles"] == PHYSICAL_MATERIAL_PROFILES
    assert material_contract["semantic_material_ids"] == SEMANTIC_PHYSICAL_MATERIAL
    root = ElementTree.fromstring(artifact.model_sdf)
    links = root.findall("./model/link")
    collisions = root.findall("./model/link/collision")
    visuals = root.findall("./model/link/visual")

    assert root.attrib["version"] == "1.9"
    assert root.findtext("./model/static") == "true"
    assert [link.attrib["name"] for link in links] == ["school-map-static-geometry"]
    assert len(collisions) == artifact.summary["collision_primitive_count"]
    assert len(visuals) == artifact.summary["visual_primitive_count"]
    assert len({item.attrib["name"] for item in collisions}) == len(collisions)
    assert all(
        item.find("./geometry/box/size") is not None
        or item.find("./geometry/cylinder/radius") is not None
        or item.find("./geometry/capsule/radius") is not None
        or item.find("./geometry/sphere/radius") is not None
        for item in collisions
    )
    assert all(
        item.find("./geometry/box/size") is not None
        or item.find("./geometry/cylinder/radius") is not None
        or item.find("./geometry/sphere/radius") is not None
        or item.find("./geometry/mesh/uri") is not None
        for item in visuals
    )
    assert (
        hashlib.sha256(artifact.model_sdf.encode()).hexdigest()
        == artifact.summary["model_sdf_sha256"]
    )
    assert (
        hashlib.sha256(artifact.semantic_json.encode()).hexdigest()
        == artifact.summary["semantic_sha256"]
    )
    assert artifact.summary["gazebo_asset_contract_generated"] is True
    assert artifact.summary["gazebo_runtime_verified"] is False
    assert artifact.summary["simulation_execution_ready"] is False
    physics_root = ElementTree.fromstring(artifact.package_files["model.physics.sdf"])
    assert len(physics_root.findall("./model/link/collision")) == len(collisions)
    assert physics_root.findall("./model/link/visual") == []


def test_school_map_world_declares_px4_sensor_environment() -> None:
    artifact = get_school_map_gazebo_artifact()
    root = ElementTree.fromstring(artifact.package_files["world.sdf"])

    assert root.findtext("./world/gravity") == "0 0 -9.80665"
    assert root.findtext("./world/magnetic_field") == "6e-06 2.3e-05 -4.2e-05"
    assert root.find("./world/atmosphere").attrib["type"] == "adiabatic"
    assert root.find("./world/physics").attrib["type"] == "ode"
    assert root.findtext("./world/physics/max_step_size") == "0.004"
    assert root.findtext("./world/physics/real_time_update_rate") == "250"
    assert len(root.findall("./world/scene")) == 1
    assert root.findtext("./world/spherical_coordinates/world_frame_orientation") == "ENU"


def test_public_scene_catalog_exposes_only_the_canonical_school_map_name() -> None:
    public_scenes = list_scenes()
    assert [(scene.id, scene.name) for scene in public_scenes] == [
        ("school-campus-v1", "School Map")
    ]


def test_frontend_reads_the_backend_manifest_instead_of_freezing_its_digest() -> None:
    artifact_cache_before = get_school_map_gazebo_artifact.cache_info()
    manifest = get_bundled_map_manifest("school-campus-v1")
    artifact_cache_after = get_school_map_gazebo_artifact.cache_info()
    assert manifest is not None
    frontend_source = (
        Path(__file__).resolve().parents[2] / "frontend" / "src" / "pages" / "AutonomyPlatform.tsx"
    ).read_text(encoding="utf-8")
    frontend_api_types = (
        Path(__file__).resolve().parents[2] / "frontend" / "src" / "types" / "api.ts"
    ).read_text(encoding="utf-8")

    assert manifest["manifest_sha256"] not in frontend_source
    assert "map_pack_manifest: AutonomyBundledMapManifest" in frontend_api_types
    assert artifact_cache_after == artifact_cache_before


def test_school_map_export_materializes_digest_bound_files(tmp_path: Path) -> None:
    output_directory = tmp_path / "school-map"
    hashes = export_school_map_gazebo_artifact(output_directory)

    assert set(hashes) == {
        "model.sdf",
        "model.physics.sdf",
        "model.config",
        "world.sdf",
        "world.physics.sdf",
        "README.md",
        "ros_gz_bridge.yaml",
        "semantic.json",
        "summary.json",
        "meshes/training-gate-1.obj",
        "meshes/training-gate-2.obj",
        "meshes/training-gate-3.obj",
        "meshes/training-gate.mtl",
        "materials/textures/campus-surface.ppm",
    }
    assert ElementTree.fromstring((output_directory / "model.sdf").read_text()).tag == "sdf"
    world_root = ElementTree.fromstring((output_directory / "world.sdf").read_text())
    config_root = ElementTree.fromstring((output_directory / "model.config").read_text())
    assert world_root.find("./world/model") is not None
    assert config_root.findtext("./name") == "School Map"
    assert json.loads((output_directory / "semantic.json").read_text())["name"] == "School Map"
    assert all(
        hashlib.sha256((output_directory / name).read_bytes()).hexdigest() == digest
        for name, digest in hashes.items()
    )


def test_school_map_stairs_share_exact_tread_landing_and_floor_planes() -> None:
    primitives = {primitive.name: primitive for primitive in school_map_collision_primitives()}
    tolerance = STRUCTURAL_TOLERANCE_M

    for storey in (1, 2):
        first_last = primitives[f"teaching-stair-{storey}-a-12"]
        second_first = primitives[f"teaching-stair-{storey}-b-1"]
        second_last = primitives[f"teaching-stair-{storey}-b-12"]
        middle = primitives[f"teaching-stair-{storey}-mid-landing"]
        upper = primitives[f"teaching-stair-{storey}-upper-landing"]

        assert abs(_bounds(first_last, "y")[1] - _bounds(middle, "y")[0]) <= tolerance
        assert abs(_bounds(second_first, "y")[1] - _bounds(middle, "y")[0]) <= tolerance
        assert abs(_bounds(first_last, "z")[1] - _bounds(middle, "z")[1]) <= tolerance
        assert abs(_bounds(second_first, "z")[0] - _bounds(middle, "z")[1]) <= tolerance
        assert abs(_bounds(second_last, "y")[0] - _bounds(upper, "y")[1]) <= tolerance
        assert abs(_bounds(second_last, "z")[1] - _bounds(upper, "z")[1]) <= tolerance

    stair_treads = [
        primitive for primitive in primitives.values() if primitive.semantic == "stair-tread"
    ]
    assert len(stair_treads) == 72
    assert "cafeteria-stair-1-upper-landing" in primitives
    assert all(
        f"cafeteria-floor-2-{side}" in primitives for side in ("west", "east", "south", "north")
    )


def test_school_map_semantic_road_graph_reaches_every_facility() -> None:
    semantic = json.loads(get_school_map_gazebo_artifact().semantic_json)
    roads = semantic["roads"]

    def key(point: list[float]) -> tuple[float, float]:
        return (round(point[0], 3), round(point[1], 3))

    adjacency: dict[tuple[float, float], set[tuple[float, float]]] = {}
    for segment in roads["segments"]:
        assert segment["width_m"] >= 4.8
        for start, end in zip(segment["points"][:-1], segment["points"][1:], strict=True):
            a, b = key(start), key(end)
            adjacency.setdefault(a, set()).add(b)
            adjacency.setdefault(b, set()).add(a)
    start = key(roads["facility_anchors"]["campus-gate"])
    visited: set[tuple[float, float]] = set()
    pending = [start]
    while pending:
        node = pending.pop()
        if node in visited:
            continue
        visited.add(node)
        pending.extend(adjacency.get(node, ()))
    for anchor in roads["facility_anchors"].values():
        exact = min(
            (abs(node[0] - anchor[0]) + abs(node[1] - anchor[1]) for node in visited),
            default=float("inf"),
        )
        assert exact <= ROUTE_ENDPOINT_TOLERANCE_M
    for junction in roads["junctions"]:
        node = (round(junction["x"], 3), round(junction["y"], 3))
        assert len(adjacency.get(node, set())) >= junction["minimum_degree"]


def test_school_map_facility_columns_share_canopy_bottom_planes() -> None:
    primitives = {primitive.name: primitive for primitive in school_map_collision_primitives()}
    bike_roof_bottom = _bounds(primitives["bike-shelter-roof"], "z")[0]
    pickup_roof_bottom = _bounds(primitives["pickup-canopy"], "z")[0]

    for primitive in primitives.values():
        if primitive.name.startswith("bike-shelter-column-"):
            assert abs(_bounds(primitive, "z")[1] - bike_roof_bottom) <= STRUCTURAL_TOLERANCE_M
        if primitive.name.startswith("pickup-column-"):
            assert abs(_bounds(primitive, "z")[1] - pickup_roof_bottom) <= STRUCTURAL_TOLERANCE_M
    assert len([name for name in primitives if name.endswith("-pole")]) == 22
    assert len([name for name in primitives if name.endswith("-arm")]) == 22


def test_road_endpoints_share_entrance_step_and_threshold_planes() -> None:
    primitives = {primitive.name: primitive for primitive in school_map_collision_primitives()}
    semantic = json.loads(get_school_map_gazebo_artifact().semantic_json)

    teaching_steps = [primitives[f"teaching-entry-step-{index}"] for index in range(1, 5)]
    cafeteria_steps = [primitives[f"cafeteria-entry-step-{index}"] for index in range(1, 3)]
    for steps, facility, threshold_name in (
        (teaching_steps, "teaching-building", "teaching-entry-threshold"),
        (cafeteria_steps, "cafeteria", "cafeteria-entry-threshold"),
    ):
        road_end = semantic["roads"]["facility_anchors"][facility][1]
        assert abs(_bounds(steps[0], "y")[0] - road_end) <= ROUTE_ENDPOINT_TOLERANCE_M
        for current, following in zip(steps[:-1], steps[1:], strict=True):
            assert (
                abs(_bounds(current, "y")[1] - _bounds(following, "y")[0]) <= STRUCTURAL_TOLERANCE_M
            )
        threshold = primitives[threshold_name]
        assert (
            abs(_bounds(steps[-1], "y")[1] - _bounds(threshold, "y")[0]) <= STRUCTURAL_TOLERANCE_M
        )
        assert (
            abs(_bounds(steps[-1], "z")[1] - _bounds(threshold, "z")[1]) <= STRUCTURAL_TOLERANCE_M
        )


def test_teaching_closed_doors_and_frames_match_the_rendered_collision_state() -> None:
    primitives = {primitive.name: primitive for primitive in school_map_collision_primitives()}
    west_wall = primitives["teaching-south-1-west"]
    east_wall = primitives["teaching-south-1-east"]
    west_frame = primitives["teaching-entry-frame-west"]
    center_frame = primitives["teaching-entry-frame-center"]
    east_frame = primitives["teaching-entry-frame-east"]
    open_west = primitives["teaching-entry-door-1-west-open"]
    open_east = primitives["teaching-entry-door-2-west-open"]
    closed_west = primitives["teaching-entry-door-3-east-closed"]
    closed_east = primitives["teaching-entry-door-4-east-closed"]
    threshold = primitives["teaching-entry-threshold"]

    interfaces = (
        (_bounds(west_wall, "x")[1], _bounds(west_frame, "x")[0]),
        (_bounds(center_frame, "x")[1], _bounds(closed_west, "x")[0]),
        (_bounds(closed_west, "x")[1], _bounds(closed_east, "x")[0]),
        (_bounds(closed_east, "x")[1], _bounds(east_frame, "x")[0]),
        (_bounds(east_frame, "x")[1], _bounds(east_wall, "x")[0]),
        (_bounds(threshold, "y")[1], _bounds(closed_west, "y")[0]),
    )
    assert all(abs(left - right) <= STRUCTURAL_TOLERANCE_M for left, right in interfaces)
    assert _bounds(center_frame, "x")[0] - _bounds(west_frame, "x")[1] == pytest.approx(3.99)
    for obstruction in (
        west_frame,
        center_frame,
        east_frame,
        open_west,
        open_east,
        closed_west,
        closed_east,
    ):
        assert _bounds(obstruction, "z")[0] == pytest.approx(0.22)
        assert _bounds(obstruction, "z")[1] == pytest.approx(2.92)
    assert open_west.yaw_rad == pytest.approx(-open_east.yaw_rad)
    west_inner_tip = _box_horizontal_bounds_x(open_west)[1]
    east_inner_tip = _box_horizontal_bounds_x(open_east)[0]
    assert east_inner_tip - west_inner_tip > 0.76
    assert west_inner_tip + 0.38 < TEACHING_OPEN_DOOR_PAIR_CENTER_X < east_inner_tip - 0.38


def test_cafeteria_closed_doors_and_frames_match_the_rendered_collision_state() -> None:
    primitives = {primitive.name: primitive for primitive in school_map_collision_primitives()}
    sequence = [
        primitives["cafeteria-south-1-west"],
        primitives["cafeteria-entry-frame-west-left"],
        primitives["cafeteria-entry-door-west-1-closed"],
        primitives["cafeteria-entry-door-west-2-closed"],
        primitives["cafeteria-entry-frame-west-right"],
        primitives["cafeteria-entry-frame-east-left"],
        primitives["cafeteria-entry-door-east-1-closed"],
        primitives["cafeteria-entry-door-east-2-closed"],
        primitives["cafeteria-entry-frame-east-right"],
        primitives["cafeteria-south-1-east"],
    ]
    for current, following in zip(sequence[:-1], sequence[1:], strict=True):
        assert abs(_bounds(current, "x")[1] - _bounds(following, "x")[0]) <= STRUCTURAL_TOLERANCE_M

    threshold = primitives["cafeteria-entry-threshold"]
    second_step = primitives["cafeteria-entry-step-2"]
    first_leaf = primitives["cafeteria-entry-door-west-1-closed"]
    top_frame = primitives["cafeteria-entry-frame-west-top"]
    header = primitives["cafeteria-south-1-header"]
    assert _bounds(second_step, "y")[1] == pytest.approx(_bounds(threshold, "y")[0])
    assert _bounds(threshold, "y")[1] == pytest.approx(_bounds(first_leaf, "y")[0])
    assert _bounds(first_leaf, "z")[0] == pytest.approx(0.22)
    assert _bounds(first_leaf, "z")[1] == pytest.approx(_bounds(top_frame, "z")[0])
    assert _bounds(top_frame, "z")[1] == pytest.approx(_bounds(header, "z")[0])


def test_reference_mission_crosses_teaching_facade_through_open_pair() -> None:
    scene = get_scene("school-campus-v1")
    assert scene is not None
    primitives = {primitive.name: primitive for primitive in school_map_collision_primitives()}
    west_clear_edge = _bounds(primitives["teaching-entry-frame-west"], "x")[1]
    east_clear_edge = _bounds(primitives["teaching-entry-frame-center"], "x")[0]
    vehicle_radius = 0.76 / 2
    crossings: list[float] = []

    for start, end in zip(scene.reference_path[:-1], scene.reference_path[1:], strict=True):
        if start.y == end.y or (start.y - 2.0) * (end.y - 2.0) > 0:
            continue
        ratio = (2.0 - start.y) / (end.y - start.y)
        crossing_x = start.x + (end.x - start.x) * ratio
        if -29.23 <= crossing_x <= -20.77:
            crossings.append(crossing_x)

    assert crossings == pytest.approx([TEACHING_OPEN_DOOR_PAIR_CENTER_X] * 2)
    assert all(
        west_clear_edge + vehicle_radius <= crossing <= east_clear_edge - vehicle_radius
        for crossing in crossings
    )


def test_open_door_semantic_clearance_is_derived_from_rotated_leaf_envelopes() -> None:
    semantic = json.loads(get_school_map_gazebo_artifact().semantic_json)
    primitives = {primitive.name: primitive for primitive in school_map_collision_primitives()}
    west_leaf = primitives["teaching-entry-door-1-west-open"]
    east_leaf = primitives["teaching-entry-door-2-west-open"]
    measured_clearance = (
        _box_horizontal_bounds_x(east_leaf)[0] - _box_horizontal_bounds_x(west_leaf)[1]
    )

    assert measured_clearance == pytest.approx(TEACHING_OPEN_DOOR_CLEARANCE_M)
    assert semantic["vehicle_clearance"]["minimum_open_door_clearance_m"] == pytest.approx(
        measured_clearance
    )
    assert measured_clearance > 0.76 * 2


def test_visible_tree_trunks_are_exported_as_matching_cylinder_collisions() -> None:
    artifact = get_school_map_gazebo_artifact()
    semantic = json.loads(artifact.semantic_json)
    root = ElementTree.fromstring(artifact.model_sdf)
    trunk_primitives = [
        primitive
        for primitive in school_map_collision_primitives()
        if primitive.semantic == "tree-trunk"
    ]

    assert len(trunk_primitives) == 38
    assert all(primitive.radius_m == pytest.approx(0.24) for primitive in trunk_primitives)
    assert all(
        primitive.center_z == pytest.approx(primitive.height_m / 2)
        for primitive in trunk_primitives
    )
    collision_names = {
        collision.attrib["name"] for collision in root.findall("./model/link/collision")
    }
    assert {f"campus-tree-{index}-trunk-collision" for index in range(1, 39)}.issubset(
        collision_names
    )
    tree_crowns = [
        primitive
        for primitive in school_map_collision_primitives()
        if primitive.semantic == "tree-crown"
    ]
    assert len(tree_crowns) == 152
    assert "tree-trunks-and-crowns" in semantic["geometry_scope"]


def test_school_map_manifest_and_qualification_bind_unverified_gazebo_contract() -> None:
    manifest = get_bundled_map_manifest("school-campus-v1")
    assert manifest is not None
    assert manifest["gazebo_artifact"] == get_school_map_gazebo_artifact().summary

    payload = {
        "name": "School Map",
        "pack_id": "map-school",
        "version": 1,
        "compiler_scene_id": "school-campus-v1",
        "representation": "hybrid-3d",
        "coordinate_frame": "ENU",
        "resolution_m": 0.05,
        "floor_count": 3,
        "bounds_m": {"x": 120, "y": 90, "z": 12.6},
        "origin": {"latitude": None, "longitude": None, "altitude_m": None},
        "live_updates": "depth-fusion",
        "calibrated": True,
        "confidence_percent": 100,
        "semantic_layers": manifest["semantic_layers"],
        "planning_layers": manifest["planning_layers"],
        "source_asset_receipt_ids": [],
    }
    receipt = qualify_map_pack(MapPackQualificationRequest.model_validate(payload))

    assert receipt.status == "qualified"
    assert receipt.manifest_sha256 == manifest["manifest_sha256"]
    assert {issue.code for issue in receipt.issues} == {"map.gazebo-runtime.not-verified"}


@pytest.mark.parametrize("floor", [1, 2, 3])
def test_teaching_walls_share_slab_and_next_interface_planes(floor: int) -> None:
    primitives = {primitive.name: primitive for primitive in school_map_collision_primitives()}
    lower = primitives[f"teaching-north-{floor}-lower"]
    upper = primitives[f"teaching-north-{floor}-upper"]
    slab_top = (floor - 1) * 3.6 + 0.22
    next_interface = floor * 3.6

    assert abs(_bounds(lower, "z")[0] - slab_top) <= STRUCTURAL_TOLERANCE_M
    assert abs(_bounds(upper, "z")[1] - next_interface) <= STRUCTURAL_TOLERANCE_M


@pytest.mark.parametrize(
    ("building", "floor_count"),
    [("teaching", 3), ("cafeteria", 2)],
)
def test_exterior_wall_corners_butt_without_gap_or_volume_overlap(
    building: str,
    floor_count: int,
) -> None:
    primitives = {primitive.name: primitive for primitive in school_map_collision_primitives()}

    for floor in range(1, floor_count + 1):
        north = primitives[f"{building}-north-{floor}-lower"]
        west = primitives[f"{building}-west-{floor}"]
        south_name = (
            f"{building}-south-{floor}-west"
            if building == "teaching" and floor == 1
            else "cafeteria-south-1-west"
            if building == "cafeteria" and floor == 1
            else f"{building}-south-{floor}"
        )
        south = primitives[south_name]

        assert abs(_bounds(west, "y")[1] - _bounds(north, "y")[0]) <= STRUCTURAL_TOLERANCE_M
        assert abs(_bounds(west, "y")[0] - _bounds(south, "y")[1]) <= STRUCTURAL_TOLERANCE_M


def test_room_shell_door_and_window_interfaces_are_exact_butt_joints() -> None:
    primitives = {primitive.name: primitive for primitive in school_map_collision_primitives()}
    prefix = "classroom-1-1"
    left = primitives[f"{prefix}-left-wall"]
    front_west = primitives[f"{prefix}-front-wall-west"]
    back_lower = primitives[f"{prefix}-back-wall-lower"]
    frame_west = primitives[f"{prefix}-frame-west"]
    frame_top = primitives[f"{prefix}-frame-top"]
    header = primitives[f"{prefix}-front-wall-header"]
    leaf = primitives[f"{prefix}-leaf-closed"]
    window_pier = primitives[f"{prefix}-back-wall-pier-1"]
    window_frame_west = primitives[f"{prefix}-back-wall-window-1-frame-west"]
    window_frame_bottom = primitives[f"{prefix}-back-wall-window-1-frame-bottom"]
    window_glass = primitives[f"{prefix}-back-wall-window-1-glass"]
    window_mullion = primitives[f"{prefix}-back-wall-window-1-mullion-vertical"]

    assert _bounds(front_west, "y")[1] == pytest.approx(_bounds(left, "y")[0])
    assert _bounds(left, "y")[1] == pytest.approx(_bounds(back_lower, "y")[0])
    assert _bounds(front_west, "x")[1] == pytest.approx(_bounds(frame_west, "x")[0])
    assert _bounds(frame_top, "z")[1] == pytest.approx(_bounds(header, "z")[0])
    assert _bounds(leaf, "z")[0] == pytest.approx(0.22)
    assert _bounds(window_pier, "x")[1] == pytest.approx(_bounds(window_frame_west, "x")[0])
    assert _bounds(window_frame_west, "x")[1] == pytest.approx(_bounds(window_glass, "x")[0])
    assert _bounds(window_frame_bottom, "z")[1] == pytest.approx(_bounds(window_glass, "z")[0])
    assert _bounds(window_glass, "y")[1] == pytest.approx(_bounds(window_mullion, "y")[0])


@pytest.mark.parametrize("floor", [1, 2, 3])
def test_facade_trim_meets_wall_and_belt_without_penetration(floor: int) -> None:
    primitives = {primitive.name: primitive for primitive in school_map_collision_primitives()}
    wall = primitives[f"teaching-north-{floor}-lower"]
    pilaster = primitives[f"teaching-facade-pilaster-{floor}-1"]
    belt = primitives[f"teaching-facade-belt-{floor}"]

    assert _bounds(wall, "y")[1] == pytest.approx(_bounds(pilaster, "y")[0])
    assert _bounds(pilaster, "z")[1] == pytest.approx(_bounds(belt, "z")[0])


def test_fence_rails_posts_and_gate_header_share_exact_interfaces() -> None:
    primitives = {primitive.name: primitive for primitive in school_map_collision_primitives()}
    corner_post = primitives["fence-south-west-post-1"]
    first_rail = primitives["fence-south-west-rail-1"]
    last_rail = primitives["fence-south-west-rail-26"]
    gate_post = primitives["campus-main-gate-west"]
    gate_header = primitives["campus-main-gate-header"]

    assert _bounds(corner_post, "x")[1] == pytest.approx(_bounds(first_rail, "x")[0])
    assert _bounds(last_rail, "x")[1] == pytest.approx(_bounds(gate_post, "x")[0])
    assert _bounds(gate_post, "z")[1] == pytest.approx(_bounds(gate_header, "z")[0])

    fence_posts = [
        primitive
        for primitive in primitives.values()
        if primitive.semantic in {"fence-post", "gate-post"}
    ]
    centers = {(round(item.center_x, 6), round(item.center_y, 6)) for item in fence_posts}
    assert len(centers) == len(fence_posts)


def test_fixed_furniture_supports_share_floor_or_supported_surface_planes() -> None:
    primitives = {primitive.name: primitive for primitive in school_map_collision_primitives()}
    desktop = primitives["classroom-1-1-desk-1-1-desktop"]
    desk_leg = primitives["classroom-1-1-desk-1-1-desk-leg-1"]
    chair_seat = primitives["classroom-1-1-desk-1-1-chair-seat"]
    chair_leg = primitives["classroom-1-1-desk-1-1-chair-leg-1"]
    teacher_desk = primitives["classroom-1-1-teacher-desk"]
    cafeteria_top = primitives["cafeteria-1-table-1-1-top"]
    cafeteria_support = primitives["cafeteria-1-table-1-1-support"]

    assert _bounds(desk_leg, "z")[0] == pytest.approx(0.22)
    assert _bounds(desk_leg, "z")[1] == pytest.approx(_bounds(desktop, "z")[0])
    assert _bounds(chair_leg, "z")[0] == pytest.approx(0.22)
    assert _bounds(chair_leg, "z")[1] == pytest.approx(_bounds(chair_seat, "z")[0])
    assert _bounds(teacher_desk, "z")[0] == pytest.approx(0.22)
    assert _bounds(cafeteria_support, "z")[0] == pytest.approx(0.22)
    assert _bounds(cafeteria_support, "z")[1] == pytest.approx(_bounds(cafeteria_top, "z")[0])


def test_launch_pickup_and_canopy_components_are_grounded_and_supported() -> None:
    artifact = get_school_map_gazebo_artifact()
    semantic = json.loads(artifact.semantic_json)
    primitives = {primitive.name: primitive for primitive in school_map_collision_primitives()}
    pickup_pad = primitives["takeout-drone-pad"]
    launch_pad = primitives["office-drone-launch-pad"]
    guard_booth = primitives["guard-booth"]
    guard_roof = primitives["guard-booth-roof"]

    assert _bounds(pickup_pad, "z")[0] == pytest.approx(0)
    assert _bounds(launch_pad, "z")[0] == pytest.approx(7.42)
    assert _bounds(guard_booth, "z")[1] == pytest.approx(_bounds(guard_roof, "z")[0])
    scene = get_scene("school-campus-v1")
    assert scene is not None
    launch_semantic = next(item for item in scene.objects if item.id == "office-drone-launch")
    assert (
        launch_semantic.center.x,
        launch_semantic.center.y,
        launch_semantic.center.z,
    ) == pytest.approx((launch_pad.center_x, launch_pad.center_y, launch_pad.center_z))
    assert (
        launch_semantic.size.x,
        launch_semantic.size.y,
        launch_semantic.size.z,
    ) == pytest.approx((launch_pad.radius_m * 2, launch_pad.radius_m * 2, launch_pad.height_m))
    spawn = semantic["simulation_bindings"]["px4_recommended_spawn"]
    assert spawn["surface"] == launch_pad.name
    assert spawn["pose_reference"] == "px4-x500-model-root"
    assert spawn["contact_surface_offset_z"] == pytest.approx(PX4_X500_MODEL_ROOT_TO_CONTACT_M)
    assert spawn["z"] + PX4_X500_MODEL_ROOT_TO_CONTACT_M == pytest.approx(
        _bounds(launch_pad, "z")[1]
    )
    assert semantic["simulation_bindings"]["mission_waypoint_reference"] == (
        "vehicle-collision-envelope-center"
    )
    assert semantic["simulation_bindings"]["vehicle_collision_center_offset"] == {
        "x": 0.0,
        "y": 0.0,
        "z": PX4_X500_COLLISION_CENTER_ABOVE_MODEL_ROOT_M,
    }
    assert artifact.package_files["ros_gz_bridge.yaml"].startswith("- ros_topic_name: /clock\n")
    assert "PX4 mission" in artifact.package_files["README.md"]


def test_training_gate_meshes_are_closed_manifolds_and_supported() -> None:
    artifact = get_school_map_gazebo_artifact()
    primitives = {primitive.name: primitive for primitive in school_map_collision_primitives()}
    for index in range(1, 4):
        mesh_name = f"meshes/training-gate-{index}.obj"
        mesh = artifact.package_files[mesh_name]
        faces = [
            tuple(
                int(vertex.split("//", maxsplit=1)[0]) for vertex in line.removeprefix("f ").split()
            )
            for line in mesh.splitlines()
            if line.startswith("f ")
        ]
        vertices = [line for line in mesh.splitlines() if line.startswith("v ")]
        normals = [line for line in mesh.splitlines() if line.startswith("vn ")]
        assert len(vertices) == len(normals)
        edge_counts: dict[tuple[int, int], int] = {}
        for face in faces:
            for start, end in zip(face, (*face[1:], face[0]), strict=True):
                edge = tuple(sorted((start, end)))
                edge_counts[edge] = edge_counts.get(edge, 0) + 1
        assert faces
        assert set(edge_counts.values()) == {2}

        ring = primitives[f"school-training-gate-{index}-ring"]
        north_post = primitives[f"school-training-gate-{index}-post-north"]
        north_foot = primitives[f"school-training-gate-{index}-foot-north"]
        assert ring.uri == mesh_name
        assert _bounds(north_foot, "z")[1] == pytest.approx(_bounds(north_post, "z")[0])
        assert _bounds(north_post, "z")[1] == pytest.approx(ring.center_z - 0.09)

        collision_segments = [
            primitive
            for primitive in primitives.values()
            if primitive.name.startswith(f"school-training-gate-{index}-collision-segment-")
        ]
        assert len(collision_segments) == 32
        assert all(isinstance(segment, CapsulePrimitive) for segment in collision_segments)
        endpoints = [_cylinder_axis_endpoints(segment) for segment in collision_segments]
        for segment_index, (_, end) in enumerate(endpoints):
            next_start, _ = endpoints[(segment_index + 1) % len(endpoints)]
            assert math.dist(end, next_start) <= STRUCTURAL_TOLERANCE_M


def test_reference_mission_starts_on_launch_pad_and_uses_open_office_door() -> None:
    scene = get_scene("school-campus-v1")
    assert scene is not None
    assert (scene.reference_path[0].x, scene.reference_path[0].y) == pytest.approx((-42.25, 15.3))
    assert (scene.reference_path[-1].x, scene.reference_path[-1].y) == pytest.approx((-42.25, 15.3))

    primitives = {primitive.name: primitive for primitive in school_map_collision_primitives()}
    west_frame = primitives["office-frame-west"]
    east_frame = primitives["office-frame-east"]
    vehicle_radius = 0.76 / 2
    office_crossings: list[float] = []
    for start, end in zip(scene.reference_path[:-1], scene.reference_path[1:], strict=True):
        if start.y == end.y or (start.y - 10.6) * (end.y - 10.6) > 0:
            continue
        ratio = (10.6 - start.y) / (end.y - start.y)
        crossing_x = start.x + (end.x - start.x) * ratio
        if -51.0 <= crossing_x <= -39.5:
            office_crossings.append(crossing_x)

    assert len(office_crossings) == 2
    assert office_crossings[0] == pytest.approx(office_crossings[1])
    door_center = office_crossings[0]
    assert _bounds(west_frame, "x")[1] + vehicle_radius < door_center
    assert door_center < _bounds(east_frame, "x")[0] - vehicle_radius

    cafeteria_entrance = next(
        item for item in scene.objects if item.id == "cafeteria-main-entrance"
    )
    assert cafeteria_entrance.traversable is False


def test_reference_mission_vehicle_envelope_clears_every_static_collision() -> None:
    primitives = school_map_collision_primitives()
    collisions: list[tuple[tuple[float, float, float], str]] = []
    for sample in _sample_reference_route():
        for primitive in primitives:
            if _vehicle_intersects_primitive(sample, primitive):
                collisions.append((sample, primitive.name))
                if len(collisions) >= 20:
                    break
        if len(collisions) >= 20:
            break

    assert not collisions, (
        f"40 mm sampled School Map mission corridor intersects collision geometry: {collisions}"
    )


def test_stair_handrails_have_collision_volume_and_butt_post_tops() -> None:
    primitives = school_map_collision_primitives()
    rails = [item for item in primitives if item.semantic == "stair-handrail"]
    posts = [item for item in primitives if item.semantic == "stair-handrail-post"]

    assert len(rails) == 12
    assert len(posts) == 84
    for rail in rails:
        assert isinstance(rail, CylinderPrimitive)
        endpoints = _cylinder_axis_endpoints(rail)
        matching_posts = [
            post
            for post in posts
            if post.name.split("-post-")[0] == rail.name.split("-rail-")[0]
            and f"-{post.name.split('-post-')[1][0]}-" in rail.name
        ]
        assert matching_posts
        for endpoint in endpoints:
            nearest_top = min(
                math.dist(
                    endpoint,
                    (post.center_x, post.center_y, _bounds(post, "z")[1] + rail.radius_m),
                )
                for post in matching_posts
            )
            assert nearest_top <= STRUCTURAL_TOLERANCE_M


def test_entrance_canopies_butt_exterior_wall_faces_without_overlap() -> None:
    primitives = {primitive.name: primitive for primitive in school_map_collision_primitives()}
    assert _bounds(primitives["main-door-canopy"], "y")[1] == pytest.approx(
        _bounds(primitives["teaching-south-1-west"], "y")[0]
    )
    assert _bounds(primitives["cafeteria-entry-canopy"], "y")[1] == pytest.approx(
        _bounds(primitives["cafeteria-south-1-west"], "y")[0]
    )


def test_road_markings_and_crosswalk_contract_matches_low_speed_campus_surface() -> None:
    artifact = get_school_map_gazebo_artifact()
    semantic = json.loads(artifact.semantic_json)
    markings = semantic["road_markings"]

    assert markings == {
        "centerline_width_m": 0.11,
        "centerline_dash_m": 1.6,
        "centerline_gap_m": 1.1,
        "crosswalk_bar_count": 7,
        "crosswalk_bar_width_m": 0.34,
        "crosswalk_bar_spacing_m": 0.62,
        "crosswalk_length_m": 3.8,
        "junction_centerline_inset_m": 0.3,
        "crosswalk_clearance_m": 0.18,
    }
    assert len(semantic["crosswalks"]) == 3
    assert all(crosswalk["axis"] in {"x", "y"} for crosswalk in semantic["crosswalks"])
    assert {crosswalk["id"]: crosswalk["bar_count"] for crosswalk in semantic["crosswalks"]} == {
        "teaching-entry-crosswalk": 7,
        "cafeteria-entry-crosswalk": 7,
        "main-gate-crosswalk": 9,
    }
    assert (
        next(
            crosswalk
            for crosswalk in semantic["crosswalks"]
            if crosswalk["id"] == "main-gate-crosswalk"
        )["axis"]
        == "x"
    )
    surface = artifact.package_files["materials/textures/campus-surface.ppm"]
    assert surface.startswith("P3\n480 360\n255\n")
    assert "63 66 73" in surface
    assert "240 238 233" in surface
    root = ElementTree.fromstring(artifact.model_sdf)
    albedo_map = root.findtext(
        "./model/link/visual[@name='school-map-ground-visual']/material/pbr/metal/albedo_map"
    )
    assert albedo_map == "materials/textures/campus-surface.ppm"


def test_all_collision_primitives_have_unique_names_and_positive_dimensions() -> None:
    primitives = school_map_collision_primitives()
    assert len({primitive.name for primitive in primitives}) == len(primitives)
    for primitive in primitives:
        dimensions = [
            value
            for attribute, value in primitive.__dict__.items()
            if attribute.startswith("size_") or attribute in {"radius_m", "height_m", "length_m"}
        ]
        assert all(value > 0 for value in dimensions), primitive.name


def test_box_collision_components_never_use_positive_volume_interpenetration() -> None:
    boxes = [
        primitive
        for primitive in school_map_collision_primitives()
        if isinstance(primitive, BoxPrimitive)
    ]
    overlaps: list[tuple[str, str]] = []
    for index, current in enumerate(boxes):
        for following in boxes[index + 1 :]:
            if _boxes_have_positive_volume_overlap(current, following):
                overlaps.append((current.name, following.name))
                if len(overlaps) >= 20:
                    break
        if len(overlaps) >= 20:
            break

    assert not overlaps, f"collision boxes interpenetrate by more than 1 mm: {overlaps}"


def test_upright_cylinders_spheres_and_boxes_do_not_interpenetrate() -> None:
    primitives = school_map_collision_primitives()
    boxes = [item for item in primitives if isinstance(item, BoxPrimitive)]
    cylinders = [
        item
        for item in primitives
        if isinstance(item, CylinderPrimitive)
        and abs(item.roll_rad) <= 1e-12
        and abs(item.pitch_rad) <= 1e-12
    ]
    spheres = [item for item in primitives if isinstance(item, SpherePrimitive)]
    overlaps: list[tuple[str, str]] = []

    def horizontal_circle_box_distance(
        center_x: float,
        center_y: float,
        box: BoxPrimitive,
    ) -> float:
        delta_x = center_x - box.center_x
        delta_y = center_y - box.center_y
        cosine = math.cos(box.yaw_rad)
        sine = math.sin(box.yaw_rad)
        local_x = cosine * delta_x + sine * delta_y
        local_y = -sine * delta_x + cosine * delta_y
        outside_x = max(abs(local_x) - box.size_x / 2, 0.0)
        outside_y = max(abs(local_y) - box.size_y / 2, 0.0)
        return math.hypot(outside_x, outside_y)

    for cylinder in cylinders:
        for box in boxes:
            vertical_overlap = min(_bounds(cylinder, "z")[1], _bounds(box, "z")[1]) - max(
                _bounds(cylinder, "z")[0], _bounds(box, "z")[0]
            )
            if (
                vertical_overlap > STRUCTURAL_TOLERANCE_M
                and horizontal_circle_box_distance(
                    cylinder.center_x,
                    cylinder.center_y,
                    box,
                )
                < cylinder.radius_m - STRUCTURAL_TOLERANCE_M
            ):
                overlaps.append((cylinder.name, box.name))

    for sphere in spheres:
        for box in boxes:
            horizontal_distance = horizontal_circle_box_distance(
                sphere.center_x,
                sphere.center_y,
                box,
            )
            vertical_distance = max(
                abs(sphere.center_z - box.center_z) - box.size_z / 2,
                0.0,
            )
            if (
                math.hypot(horizontal_distance, vertical_distance)
                < sphere.radius_m - STRUCTURAL_TOLERANCE_M
            ):
                overlaps.append((sphere.name, box.name))

        for cylinder in cylinders:
            horizontal_distance = max(
                math.hypot(
                    sphere.center_x - cylinder.center_x,
                    sphere.center_y - cylinder.center_y,
                )
                - cylinder.radius_m,
                0.0,
            )
            vertical_distance = max(
                abs(sphere.center_z - cylinder.center_z) - cylinder.height_m / 2,
                0.0,
            )
            if (
                math.hypot(horizontal_distance, vertical_distance)
                < sphere.radius_m - STRUCTURAL_TOLERANCE_M
            ):
                overlaps.append((sphere.name, cylinder.name))

    for index, current in enumerate(cylinders):
        for following in cylinders[index + 1 :]:
            vertical_overlap = min(
                _bounds(current, "z")[1],
                _bounds(following, "z")[1],
            ) - max(_bounds(current, "z")[0], _bounds(following, "z")[0])
            horizontal_distance = math.hypot(
                current.center_x - following.center_x,
                current.center_y - following.center_y,
            )
            if (
                vertical_overlap > STRUCTURAL_TOLERANCE_M
                and horizontal_distance
                < current.radius_m + following.radius_m - STRUCTURAL_TOLERANCE_M
            ):
                overlaps.append((current.name, following.name))

    for index, current in enumerate(spheres):
        current_tree = current.name.split("-crown-")[0]
        for following in spheres[index + 1 :]:
            if current_tree == following.name.split("-crown-")[0]:
                continue
            if (
                math.dist(
                    (current.center_x, current.center_y, current.center_z),
                    (following.center_x, following.center_y, following.center_z),
                )
                < current.radius_m + following.radius_m - STRUCTURAL_TOLERANCE_M
            ):
                overlaps.append((current.name, following.name))

    assert not overlaps[:20], f"mixed collision primitives interpenetrate: {overlaps[:20]}"


def test_tree_trunks_butt_canopies_and_tree_crowns_clear_every_road_edge() -> None:
    primitives = {primitive.name: primitive for primitive in school_map_collision_primitives()}

    def point_segment_distance(
        point: tuple[float, float],
        start: list[float],
        end: list[float],
    ) -> float:
        delta_x = end[0] - start[0]
        delta_y = end[1] - start[1]
        length_squared = delta_x * delta_x + delta_y * delta_y
        ratio = max(
            0.0,
            min(
                1.0,
                ((point[0] - start[0]) * delta_x + (point[1] - start[1]) * delta_y)
                / length_squared,
            ),
        )
        return math.hypot(
            point[0] - (start[0] + ratio * delta_x),
            point[1] - (start[1] + ratio * delta_y),
        )

    tree_crowns = [
        item
        for item in primitives.values()
        if isinstance(item, SpherePrimitive) and item.semantic == "tree-crown"
    ]
    assert len(tree_crowns) == 152
    for tree_index in range(1, 39):
        trunk = primitives[f"campus-tree-{tree_index}-trunk"]
        crown = primitives[f"campus-tree-{tree_index}-crown-1"]
        assert _bounds(trunk, "z")[1] == pytest.approx(crown.center_z - crown.radius_m)

    for crown in tree_crowns:
        for segment in ROAD_NETWORK["segments"]:
            for start, end in zip(segment["points"][:-1], segment["points"][1:], strict=True):
                clearance = (
                    point_segment_distance((crown.center_x, crown.center_y), start, end)
                    - segment["width_m"] / 2
                    - crown.radius_m
                )
                assert clearance >= STRUCTURAL_TOLERANCE_M, (
                    crown.name,
                    segment["id"],
                    clearance,
                )
