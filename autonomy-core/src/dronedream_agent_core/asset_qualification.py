from __future__ import annotations

import hashlib
import json
import math
from collections import deque
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4
from xml.etree import ElementTree

from pydantic import BaseModel, ConfigDict, Field

from .contracts import MapAsset, VehicleAsset
from .hashing import sha256_json


class AssetQualificationReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    schema_version: Literal["dronedream.asset-qualification-check.v1"] = (
        "dronedream.asset-qualification-check.v1"
    )
    check_id: str = Field(pattern=r"^asset-check-[0-9a-f]{24}$")
    asset_id: str
    check_type: str
    accepted: bool
    input_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    output_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    issue_codes: list[str] = Field(default_factory=list)
    details: dict[str, Any] = Field(default_factory=dict)
    checked_at: datetime


def _receipt(
    asset_id: str,
    check_type: str,
    source: object,
    *,
    issues: list[str],
    details: dict[str, Any] | None = None,
) -> AssetQualificationReceipt:
    unique_issues = list(dict.fromkeys(issues))
    output = {"accepted": not unique_issues, "issue_codes": unique_issues, "details": details or {}}
    return AssetQualificationReceipt(
        check_id=f"asset-check-{uuid4().hex[:24]}",
        asset_id=asset_id,
        check_type=check_type,
        accepted=not unique_issues,
        input_sha256=sha256_json(source),
        output_sha256=sha256_json(output),
        issue_codes=unique_issues,
        details=details or {},
        checked_at=datetime.now(UTC),
    )


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("JSON_ROOT_NOT_OBJECT")
    return value


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _finite(value: object) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool) and math.isfinite(value)


def _positive(value: object) -> bool:
    return _finite(value) and float(value) > 0.0


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _elements(root: ElementTree.Element, name: str) -> list[ElementTree.Element]:
    return [element for element in root.iter() if _local(element.tag) == name]


def _safe_file(staging: Path, relative: object) -> Path | None:
    if not isinstance(relative, str) or not relative:
        return None
    path = (staging / relative).resolve()
    root = staging.resolve()
    return path if root in path.parents and path.is_file() else None


def _source_receipts(
    staging: Path,
    asset_id: str,
    manifest: dict[str, Any],
) -> tuple[list[AssetQualificationReceipt], dict[str, Any]]:
    receipts: list[AssetQualificationReceipt] = []
    files = manifest.get("files", {})
    path = _safe_file(
        staging,
        files.get("qualification_receipt") if isinstance(files, dict) else None,
    )
    qualification: dict[str, Any] = {}
    issues: list[str] = []
    if path is None:
        issues.append("QUALIFICATION_RECEIPT_MISSING")
    else:
        try:
            qualification = _load_json(path)
        except (OSError, json.JSONDecodeError, ValueError):
            issues.append("QUALIFICATION_RECEIPT_INVALID")
    if qualification and manifest.get("qualification") != qualification:
        issues.append("QUALIFICATION_MANIFEST_MISMATCH")
    if qualification.get("schema_version") != "dronedream.asset-qualification-receipt.v1":
        issues.append("QUALIFICATION_RECEIPT_SCHEMA_INVALID")
    receipts.append(
        _receipt(
            asset_id,
            "source-receipt",
            qualification,
            issues=issues,
            details={"receipt_sha256": _sha256(path) if path else None},
        )
    )

    evidence_issues: list[str] = []
    evidence: dict[str, Any] = {}
    evidence_path = _safe_file(staging, qualification.get("mission_evidence_file"))
    if evidence_path is None:
        evidence_issues.append("QUALIFICATION_EVIDENCE_MISSING")
    else:
        if _sha256(evidence_path) != qualification.get("mission_evidence_sha256"):
            evidence_issues.append("QUALIFICATION_EVIDENCE_HASH_MISMATCH")
        try:
            evidence = _load_json(evidence_path)
        except (OSError, json.JSONDecodeError, ValueError):
            evidence_issues.append("QUALIFICATION_EVIDENCE_INVALID")
    required_gates = qualification.get("required_gates")
    if (
        not isinstance(required_gates, dict)
        or not required_gates
        or not all(value is True for value in required_gates.values())
    ):
        evidence_issues.append("QUALIFICATION_REQUIRED_GATES_FAILED")
    evidence_gates = evidence.get("gates")
    if evidence.get("status") != "verified" or not isinstance(evidence_gates, dict):
        evidence_issues.append("QUALIFICATION_EVIDENCE_NOT_VERIFIED")
    elif isinstance(required_gates, dict) and any(
        evidence_gates.get(gate) is not True for gate in required_gates
    ):
        evidence_issues.append("QUALIFICATION_GATE_EVIDENCE_MISMATCH")
    for flag in (
        "gazebo_runtime_verified",
        "px4_mission_smoke_verified",
        "simulation_execution_ready",
    ):
        if qualification.get(flag) is not True:
            evidence_issues.append(f"QUALIFICATION_{flag.upper()}_FALSE")
    receipts.append(
        _receipt(
            asset_id,
            "runtime-evidence",
            {"qualification": qualification, "evidence": evidence},
            issues=evidence_issues,
            details={
                "evidence_sha256": _sha256(evidence_path) if evidence_path else None,
                "verified_gate_count": len(evidence_gates)
                if isinstance(evidence_gates, dict)
                else 0,
            },
        )
    )
    return receipts, qualification


def _integrity_receipt(
    staging: Path,
    asset_id: str,
    manifest: dict[str, Any],
) -> AssetQualificationReceipt:
    identity = manifest.get("artifact_identity")
    issues: list[str] = []
    verified: dict[str, str] = {}
    if not isinstance(identity, dict):
        issues.append("ASSET_ARTIFACT_IDENTITY_MISSING")
        identity = {}
    declared_sets = [
        value
        for key, value in identity.items()
        if key.endswith("file_sha256") or key.endswith("files_sha256")
        if isinstance(value, dict)
    ]
    if declared_sets:
        for relative, expected in {
            str(relative): expected
            for declared in declared_sets
            for relative, expected in declared.items()
        }.items():
            candidates = (_safe_file(staging, relative), _safe_file(staging, f"gazebo/{relative}"))
            path = next((candidate for candidate in candidates if candidate is not None), None)
            if path is None:
                issues.append("ASSET_DECLARED_EXPORT_MISSING")
                continue
            actual = _sha256(path)
            verified[str(relative)] = actual
            if not isinstance(expected, str) or expected != actual:
                issues.append("ASSET_DECLARED_EXPORT_HASH_MISMATCH")
    elif not any(key.endswith("_sha256") for key in identity):
        issues.append("ASSET_DECLARED_EXPORT_HASHES_MISSING")
    return _receipt(
        asset_id,
        "package-export-integrity",
        identity,
        issues=issues,
        details={"verified_file_count": len(verified), "verified_sha256": verified},
    )


def _map_core_receipts(
    asset_id: str,
    resolved: dict[str, Path],
) -> tuple[list[AssetQualificationReceipt], MapAsset | None, dict[str, Any]]:
    receipts: list[AssetQualificationReceipt] = []
    issues: list[str] = []
    graph: MapAsset | None = None
    semantic: dict[str, Any] = {}
    try:
        graph = MapAsset.model_validate_json(resolved["graph"].read_text(encoding="utf-8"))
    except (OSError, ValueError, KeyError):
        issues.append("MAP_GRAPH_INVALID")
    try:
        semantic = _load_json(resolved["semantic"])
    except (OSError, json.JSONDecodeError, ValueError, KeyError):
        issues.append("MAP_SEMANTIC_INVALID")
    if graph is not None and graph.asset_id != asset_id:
        issues.append("MAP_ASSET_ID_MISMATCH")
    if graph is not None and graph.coordinate_frame != "map_enu":
        issues.append("MAP_GRAPH_FRAME_INVALID")
    if str(semantic.get("coordinate_frame", "")).upper() != "ENU":
        issues.append("MAP_SEMANTIC_FRAME_INVALID")
    if semantic.get("schema_version") != "dronedream.autonomy.school-map-semantic.v1":
        issues.append("MAP_SEMANTIC_SCHEMA_INVALID")
    bindings = semantic.get("simulation_bindings")
    if not isinstance(bindings, dict) or not bindings:
        issues.append("MAP_SIMULATION_BINDINGS_MISSING")
    receipts.append(
        _receipt(
            asset_id,
            "map-format-frame-semantic",
            {"graph": graph, "semantic": semantic},
            issues=issues,
            details={
                "node_count": len(graph.nodes) if graph else 0,
                "edge_count": len(graph.edges) if graph else 0,
                "binding_count": len(bindings) if isinstance(bindings, dict) else 0,
            },
        )
    )
    return receipts, graph, semantic


def _map_seam_receipt(
    asset_id: str,
    graph: MapAsset | None,
    semantic: dict[str, Any],
) -> AssetQualificationReceipt:
    issues: list[str] = []
    max_distance_error = math.inf
    minimum_degree = math.inf
    if graph is not None:
        nodes = {node.node_id: node for node in graph.nodes}
        max_distance_error = 0.0
        for edge in graph.edges:
            start = nodes[edge.from_node].position_m
            end = nodes[edge.to_node].position_m
            measured = math.dist((start.x, start.y, start.z), (end.x, end.y, end.z))
            max_distance_error = max(max_distance_error, abs(measured - edge.distance_m))
        tolerances = semantic.get("tolerances_m")
        endpoint_tolerance = (
            float(tolerances.get("route_endpoint", 0.01)) if isinstance(tolerances, dict) else 0.01
        )
        if max_distance_error > endpoint_tolerance:
            issues.append("MAP_ROUTE_NUMERIC_GAP")
        roads = semantic.get("roads")
        segments = roads.get("segments") if isinstance(roads, dict) else None
        junctions = roads.get("junctions") if isinstance(roads, dict) else None
        if not isinstance(segments, list) or not segments:
            issues.append("MAP_ROAD_SEGMENTS_MISSING")
        if not isinstance(junctions, list) or not junctions:
            issues.append("MAP_ROAD_JUNCTIONS_MISSING")
        if isinstance(segments, list) and isinstance(junctions, list):
            for junction in junctions:
                if not isinstance(junction, dict) or not all(
                    _finite(junction.get(key)) for key in ("x", "y")
                ):
                    issues.append("MAP_ROAD_JUNCTION_INVALID")
                    continue
                location = (float(junction["x"]), float(junction["y"]))
                degree = 0
                for segment in segments:
                    points = segment.get("points") if isinstance(segment, dict) else None
                    if not isinstance(points, list):
                        continue
                    matched_indexes = [
                        index
                        for index, point in enumerate(points)
                        if isinstance(point, list)
                        and len(point) >= 2
                        and _finite(point[0])
                        and _finite(point[1])
                        and math.dist(location, (float(point[0]), float(point[1])))
                        <= endpoint_tolerance
                    ]
                    for index in matched_indexes:
                        degree += 1 if index in {0, len(points) - 1} else 2
                minimum_degree = min(minimum_degree, degree)
                if degree < int(junction.get("minimum_degree", 2)):
                    issues.append("MAP_ROAD_JUNCTION_DEGREE_FAILED")
    return _receipt(
        asset_id,
        "map-seam-intersection",
        {"graph": graph, "roads": semantic.get("roads")},
        issues=issues,
        details={
            "maximum_edge_distance_error_m": max_distance_error,
            "maximum_shared_endpoint_gap_m": 0.0 if graph else None,
            "minimum_measured_junction_degree": minimum_degree
            if math.isfinite(minimum_degree)
            else None,
        },
    )


def _map_material_receipt(
    asset_id: str,
    semantic: dict[str, Any],
    resolved: dict[str, Path],
) -> AssetQualificationReceipt:
    issues: list[str] = []
    contract = semantic.get("physical_material_contract")
    profiles = contract.get("profiles") if isinstance(contract, dict) else None
    assignments = contract.get("semantic_material_ids") if isinstance(contract, dict) else None
    if not isinstance(profiles, dict) or not profiles:
        issues.append("MAP_MATERIAL_PROFILES_MISSING")
        profiles = {}
    if not isinstance(assignments, dict) or not assignments:
        issues.append("MAP_MATERIAL_ASSIGNMENTS_MISSING")
        assignments = {}
    for profile in profiles.values():
        required = (
            "density_kg_m3",
            "youngs_modulus_pa",
            "characteristic_strength_mpa",
            "contact_stiffness_n_m",
            "contact_damping_n_s_m",
        )
        if not isinstance(profile, dict) or not all(
            _positive(profile.get(key)) for key in required
        ):
            issues.append("MAP_MATERIAL_PHYSICS_INVALID")
            continue
        for key in (
            "friction_mu",
            "friction_mu2",
            "poisson_ratio",
            "restitution",
            "visual_opacity",
        ):
            limit = 2.0 if "friction" in key else 1.0
            value = profile.get(key)
            if not _finite(value) or not 0.0 <= float(value) <= limit:
                issues.append("MAP_MATERIAL_PHYSICS_INVALID")
    values = (semantic.get("collision_primitives"), semantic.get("visual_only_primitives"))
    primitives = [
        item
        for group in values
        if isinstance(group, list)
        for item in group
        if isinstance(item, dict)
    ]
    for primitive in primitives:
        profile_id = assignments.get(primitive.get("semantic"))
        if not isinstance(profile_id, str) or profile_id not in profiles:
            issues.append("MAP_PRIMITIVE_MATERIAL_UNRESOLVED")
        shape_valid = (
            all(_positive(primitive.get(key)) for key in ("size_x", "size_y", "size_z"))
            or _positive(primitive.get("radius_m"))
            or (
                isinstance(primitive.get("uri"), str)
                and all(_positive(primitive.get(key)) for key in ("scale_x", "scale_y", "scale_z"))
            )
        )
        if not shape_valid:
            issues.append("MAP_PRIMITIVE_GEOMETRY_INVALID")
    physics_path = resolved.get("physics_world_sdf") or resolved.get("world_sdf")
    engine = None
    try:
        root = ElementTree.parse(physics_path).getroot()  # type: ignore[arg-type]
        physics = _elements(root, "physics")
        if not physics:
            issues.append("MAP_PHYSICS_ENGINE_MISSING")
        else:
            engine = physics[0].attrib.get("type", "")
            if engine.lower() not in {"dart", "ode", "bullet", "tpe"}:
                issues.append("MAP_PHYSICS_ENGINE_UNSUPPORTED")
    except (ElementTree.ParseError, OSError, TypeError):
        issues.append("MAP_PHYSICS_SDF_INVALID")
    return _receipt(
        asset_id,
        "map-material-physics",
        {"contract": contract, "primitive_count": len(primitives)},
        issues=issues,
        details={
            "material_profile_count": len(profiles),
            "material_assignment_count": len(assignments),
            "primitive_count": len(primitives),
            "physics_engine": engine,
        },
    )


def _map_navigation_receipt(
    asset_id: str,
    graph: MapAsset | None,
    qualification: dict[str, Any],
) -> AssetQualificationReceipt:
    issues: list[str] = []
    reachable = 0
    if graph is not None:
        adjacency = {node.node_id: set() for node in graph.nodes}
        for edge in graph.edges:
            adjacency[edge.from_node].add(edge.to_node)
            if edge.bidirectional:
                adjacency[edge.to_node].add(edge.from_node)
            if edge.qualification == "flight-verified" and not edge.evidence_sha256:
                issues.append("MAP_FLIGHT_EDGE_EVIDENCE_MISSING")
        start = graph.named_entities.get("office-launch-pad") or graph.nodes[0].node_id
        queue: deque[str] = deque([start])
        visited = {start}
        while queue:
            for neighbor in adjacency[queue.popleft()]:
                if neighbor not in visited:
                    visited.add(neighbor)
                    queue.append(neighbor)
        reachable = len(visited)
        if reachable != len(graph.nodes):
            issues.append("MAP_GRAPH_DISCONNECTED")
        if any(node_id not in visited for node_id in graph.named_entities.values()):
            issues.append("MAP_NAMED_ENTITY_UNREACHABLE")
        if not any(edge.qualification == "flight-verified" for edge in graph.edges):
            issues.append("MAP_NO_FLIGHT_VERIFIED_ROUTE")
    measurements = qualification.get("measurements")
    clearance = measurements.get("dynamic_clearance") if isinstance(measurements, dict) else None
    if not isinstance(clearance, dict) or int(clearance.get("unsafe_collision_count", -1)) != 0:
        issues.append("MAP_UNSAFE_DYNAMIC_PENETRATION")
    if not isinstance(clearance, dict) or not _positive(clearance.get("sample_count")):
        issues.append("MAP_DYNAMIC_CLEARANCE_EVIDENCE_MISSING")
    return _receipt(
        asset_id,
        "map-navigability-clearance",
        {"graph": graph, "measurements": measurements},
        issues=issues,
        details={
            "reachable_node_count": reachable,
            "total_node_count": len(graph.nodes) if graph else 0,
            "unsafe_collision_count": clearance.get("unsafe_collision_count")
            if isinstance(clearance, dict)
            else None,
            "clearance_sample_count": clearance.get("sample_count")
            if isinstance(clearance, dict)
            else None,
        },
    )


def _map_export_receipt(
    asset_id: str,
    manifest: dict[str, Any],
    resolved: dict[str, Path],
) -> AssetQualificationReceipt:
    issues: list[str] = []
    details: dict[str, Any] = {}
    for key in ("world_sdf", "physics_world_sdf"):
        path = resolved.get(key)
        if path is None:
            issues.append("MAP_EXPORT_VARIANT_MISSING")
            continue
        try:
            root = ElementTree.parse(path).getroot()
            if _local(root.tag) != "sdf" or not _elements(root, "world"):
                issues.append("MAP_EXPORT_SDF_INVALID")
            details[f"{key}_sha256"] = _sha256(path)
        except (ElementTree.ParseError, OSError):
            issues.append("MAP_EXPORT_SDF_INVALID")
    identity = manifest.get("artifact_identity")
    if isinstance(identity, dict):
        for identity_key, file_key in (
            ("world_sdf_sha256", "world_sdf"),
            ("physics_world_sdf_sha256", "physics_world_sdf"),
            ("semantic_sha256", "semantic"),
        ):
            expected = identity.get(identity_key)
            path = resolved.get(file_key)
            if path is not None and isinstance(expected, str) and _sha256(path) != expected:
                issues.append("MAP_EXPORT_HASH_MISMATCH")
    return _receipt(
        asset_id,
        "map-export",
        {"files": manifest.get("files"), "identity": identity},
        issues=issues,
        details=details,
    )


def _map_receipts(
    asset_id: str,
    manifest: dict[str, Any],
    resolved: dict[str, Path],
    qualification: dict[str, Any],
) -> list[AssetQualificationReceipt]:
    receipts, graph, semantic = _map_core_receipts(asset_id, resolved)
    receipts.extend(
        [
            _map_seam_receipt(asset_id, graph, semantic),
            _map_material_receipt(asset_id, semantic, resolved),
            _map_navigation_receipt(asset_id, graph, qualification),
            _map_export_receipt(asset_id, manifest, resolved),
        ]
    )
    return receipts


def _vehicle_core(
    asset_id: str,
    manifest: dict[str, Any],
    resolved: dict[str, Path],
) -> tuple[AssetQualificationReceipt, VehicleAsset | None, ElementTree.Element | None, str | None]:
    issues: list[str] = []
    vehicle: VehicleAsset | None = None
    root: ElementTree.Element | None = None
    try:
        vehicle = VehicleAsset.model_validate_json(
            resolved["vehicle_metadata"].read_text(encoding="utf-8")
        )
    except (OSError, ValueError, KeyError):
        issues.append("VEHICLE_METADATA_INVALID")
    try:
        root = ElementTree.parse(resolved["vehicle_sdf"]).getroot()
        if _local(root.tag) != "sdf" or not _elements(root, "model"):
            issues.append("VEHICLE_SDF_ROOT_INVALID")
    except (ElementTree.ParseError, OSError, KeyError):
        issues.append("VEHICLE_SDF_PARSE_FAILED")
    if vehicle is not None and vehicle.asset_id != asset_id:
        issues.append("VEHICLE_ASSET_ID_MISMATCH")
    source_model = None
    if root is not None:
        source_model = next(
            (
                element.text.strip()
                for element in _elements(root, "uri")
                if element.text and element.text.strip().startswith("model://")
            ),
            None,
        )
        if source_model is None and not _elements(root, "link"):
            issues.append("VEHICLE_GEOMETRY_SOURCE_MISSING")
    return (
        _receipt(
            asset_id,
            "vehicle-cad-urdf-sdf-format",
            {"vehicle": vehicle, "manifest": manifest},
            issues=issues,
            details={
                "format": "sdf",
                "source_model": source_model,
                "model_count": len(_elements(root, "model")) if root is not None else 0,
            },
        ),
        vehicle,
        root,
        source_model,
    )


def _vehicle_mass_receipt(
    asset_id: str,
    vehicle: VehicleAsset | None,
    root: ElementTree.Element | None,
    physical: dict[str, Any],
) -> AssetQualificationReceipt:
    issues: list[str] = []
    if physical.get("mass_and_inertia_from_source_model") is not True:
        issues.append("VEHICLE_INERTIA_UNVERIFIED")
    local_masses: list[float] = []
    inertia_count = 0
    if root is not None:
        for inertial in _elements(root, "inertial"):
            for mass_element in _elements(inertial, "mass"):
                try:
                    mass = float(mass_element.text or "nan")
                except ValueError:
                    mass = math.nan
                local_masses.append(mass)
                if not _positive(mass):
                    issues.append("VEHICLE_LINK_MASS_INVALID")
            for inertia in _elements(inertial, "inertia"):
                values: dict[str, float] = {}
                for name in ("ixx", "iyy", "izz"):
                    element = next(iter(_elements(inertia, name)), None)
                    if element is not None and element.text:
                        try:
                            values[name] = float(element.text)
                        except ValueError:
                            values[name] = math.nan
                if not all(_positive(values.get(name)) for name in ("ixx", "iyy", "izz")):
                    issues.append("VEHICLE_INERTIA_TENSOR_INVALID")
                else:
                    inertia_count += 1
                    x, y, z = values["ixx"], values["iyy"], values["izz"]
                    if x + y < z or x + z < y or y + z < x:
                        issues.append("VEHICLE_INERTIA_TENSOR_INVALID")
    if vehicle is not None and vehicle.max_takeoff_mass_kg < vehicle.dry_mass_kg:
        issues.append("VEHICLE_MAX_MASS_BELOW_DRY_MASS")
    return _receipt(
        asset_id,
        "vehicle-mass-inertia",
        {"vehicle": vehicle, "physical": physical},
        issues=issues,
        details={
            "dry_mass_kg": vehicle.dry_mass_kg if vehicle else None,
            "local_inertial_link_count": len(local_masses),
            "local_inertia_tensor_count": inertia_count,
            "source_model_verified": physical.get("mass_and_inertia_from_source_model") is True,
        },
    )


def _vehicle_controller_receipt(
    asset_id: str,
    vehicle: VehicleAsset | None,
    resolved: dict[str, Path],
) -> AssetQualificationReceipt:
    issues: list[str] = []
    controller: dict[str, Any] = {}
    try:
        controller = _load_json(resolved["controller_params"])
    except (OSError, json.JSONDecodeError, ValueError, KeyError):
        issues.append("VEHICLE_CONTROLLER_PARAMS_INVALID")
    required = {"kp_xy", "ki_xy", "kd_xy", "vel_limit", "accel_limit", "disturbance_rejection"}
    if not required <= set(controller):
        issues.append("VEHICLE_CONTROLLER_PARAMS_INCOMPLETE")
    if any(not _finite(controller.get(key)) for key in required & set(controller)):
        issues.append("VEHICLE_CONTROLLER_PARAMS_INVALID")
    if vehicle is not None:
        if float(controller.get("vel_limit", math.inf)) > vehicle.max_speed_mps:
            issues.append("VEHICLE_CONTROLLER_SPEED_EXCEEDS_ENVELOPE")
        if float(controller.get("accel_limit", math.inf)) > vehicle.max_acceleration_mps2:
            issues.append("VEHICLE_CONTROLLER_ACCEL_EXCEEDS_ENVELOPE")
    if any(float(controller.get(key, -1.0)) < 0.0 for key in ("kp_xy", "ki_xy", "kd_xy")):
        issues.append("VEHICLE_CONTROLLER_GAIN_INVALID")
    return _receipt(
        asset_id,
        "vehicle-controller",
        controller,
        issues=issues,
        details={"parameters": controller},
    )


def _vehicle_payload_receipt(
    asset_id: str,
    identity: dict[str, Any],
    qualification: dict[str, Any],
    root: ElementTree.Element | None,
    resolved: dict[str, Path],
) -> AssetQualificationReceipt:
    issues: list[str] = []
    details: dict[str, Any] = {}
    path = resolved.get("payload_sdf")
    if path is None:
        issues.append("VEHICLE_PAYLOAD_SDF_MISSING")
    else:
        try:
            payload_root = ElementTree.parse(path).getroot()
            masses = [float(element.text or "nan") for element in _elements(payload_root, "mass")]
            if not masses or any(not _positive(value) for value in masses):
                issues.append("VEHICLE_PAYLOAD_MASS_INVALID")
            payload_mass = sum(masses)
            details["sdf_mass_kg"] = payload_mass
            mission_payload = identity.get("mission_payload")
            expected = mission_payload.get("mass_kg") if isinstance(mission_payload, dict) else None
            if not _positive(expected) or not math.isclose(
                payload_mass, float(expected), rel_tol=1e-6, abs_tol=1e-6
            ):
                issues.append("VEHICLE_PAYLOAD_MASS_MISMATCH")
        except (ElementTree.ParseError, OSError, ValueError):
            issues.append("VEHICLE_PAYLOAD_SDF_INVALID")
    plugins = _elements(root, "plugin") if root is not None else []
    detachable = next(
        (plugin for plugin in plugins if "DetachableJoint" in plugin.attrib.get("name", "")),
        None,
    )
    if detachable is None:
        issues.append("VEHICLE_PAYLOAD_ATTACHMENT_PLUGIN_MISSING")
    else:
        required = {"parent_link", "child_link", "attach_topic", "detach_topic", "output_topic"}
        present = {_local(element.tag) for element in detachable.iter()}
        if not required <= present:
            issues.append("VEHICLE_PAYLOAD_ATTACHMENT_INTERFACE_INCOMPLETE")
    measurements = qualification.get("measurements")
    retention = measurements.get("payload_retention") if isinstance(measurements, dict) else None
    if not isinstance(retention, dict) or not _positive(retention.get("settled_sample_count")):
        issues.append("VEHICLE_PAYLOAD_RETENTION_EVIDENCE_MISSING")
    details["retention"] = retention
    return _receipt(
        asset_id,
        "vehicle-payload",
        {"identity": identity, "retention": retention},
        issues=issues,
        details=details,
    )


def _vehicle_receipts(
    asset_id: str,
    manifest: dict[str, Any],
    resolved: dict[str, Path],
    qualification: dict[str, Any],
) -> list[AssetQualificationReceipt]:
    core, vehicle, root, source_model = _vehicle_core(asset_id, manifest, resolved)
    physical_value = manifest.get("physical_material_contract")
    physical = physical_value if isinstance(physical_value, dict) else {}
    receipts = [core, _vehicle_mass_receipt(asset_id, vehicle, root, physical)]
    identity_value = manifest.get("artifact_identity")
    identity = identity_value if isinstance(identity_value, dict) else {}

    motor_issues: list[str] = []
    if physical.get("rotor_dynamics_from_source_model") is not True:
        motor_issues.append("VEHICLE_ROTOR_DYNAMICS_UNVERIFIED")
    maximum_thrust = identity.get("maximum_thrust_n")
    if not _positive(maximum_thrust):
        motor_issues.append("VEHICLE_MAXIMUM_THRUST_MISSING")
    if not isinstance(source_model, str):
        motor_issues.append("VEHICLE_MOTOR_SOURCE_MODEL_MISSING")
    receipts.append(
        _receipt(
            asset_id,
            "vehicle-motor-propeller",
            {"physical": physical, "identity": identity},
            issues=motor_issues,
            details={"maximum_thrust_n": maximum_thrust, "source_model": source_model},
        )
    )

    sensor_issues: list[str] = []
    sensor_set = set(vehicle.sensors) if vehicle else set()
    if not {"imu", "barometer", "odometry"} <= sensor_set or not (
        {"gps", "vio", "slam", "uwb"} & sensor_set
    ):
        sensor_issues.append("VEHICLE_SENSOR_SUITE_INCOMPLETE")
    if vehicle is None or not 10.0 <= vehicle.reserve_battery_percent <= 90.0:
        sensor_issues.append("VEHICLE_BATTERY_RESERVE_INVALID")
    if not isinstance(source_model, str):
        sensor_issues.append("VEHICLE_BATTERY_SOURCE_MODEL_MISSING")
    receipts.append(
        _receipt(
            asset_id,
            "vehicle-battery-sensors",
            vehicle,
            issues=sensor_issues,
            details={
                "reserve_battery_percent": vehicle.reserve_battery_percent if vehicle else None,
                "sensors": sorted(sensor_set),
                "battery_dynamics_source": source_model,
            },
        )
    )
    receipts.append(_vehicle_controller_receipt(asset_id, vehicle, resolved))
    receipts.append(_vehicle_payload_receipt(asset_id, identity, qualification, root, resolved))

    envelope_issues: list[str] = []
    measurements = qualification.get("measurements")
    loaded_mass = measurements.get("loaded_mass_kg") if isinstance(measurements, dict) else None
    loaded_twr = (
        measurements.get("loaded_thrust_to_weight") if isinstance(measurements, dict) else None
    )
    minimum_twr = identity.get("minimum_qualified_thrust_to_weight", 1.6)
    if (
        not _positive(loaded_mass)
        or vehicle is None
        or float(loaded_mass) > vehicle.max_takeoff_mass_kg
    ):
        envelope_issues.append("VEHICLE_LOADED_MASS_OUTSIDE_ENVELOPE")
    if not _positive(loaded_twr) or float(loaded_twr) < float(minimum_twr):
        envelope_issues.append("VEHICLE_THRUST_TO_WEIGHT_INSUFFICIENT")
    if (
        vehicle is not None
        and vehicle.max_takeoff_mass_kg - vehicle.dry_mass_kg < vehicle.max_pickup_payload_kg
    ):
        envelope_issues.append("VEHICLE_PAYLOAD_EXCEEDS_MASS_MARGIN")
    calculated_twr = None
    if _positive(maximum_thrust) and _positive(loaded_mass):
        calculated_twr = float(maximum_thrust) / (float(loaded_mass) * 9.80665)
        if not _positive(loaded_twr) or not math.isclose(
            calculated_twr, float(loaded_twr), rel_tol=0.01, abs_tol=0.01
        ):
            envelope_issues.append("VEHICLE_THRUST_TO_WEIGHT_MISMATCH")
    receipts.append(
        _receipt(
            asset_id,
            "vehicle-flight-envelope",
            {"vehicle": vehicle, "measurements": measurements, "identity": identity},
            issues=envelope_issues,
            details={
                "loaded_mass_kg": loaded_mass,
                "loaded_thrust_to_weight": loaded_twr,
                "calculated_loaded_thrust_to_weight": calculated_twr,
                "minimum_qualified_thrust_to_weight": minimum_twr,
            },
        )
    )
    return receipts


def qualify_staged_asset(
    *,
    staging: Path,
    kind: Literal["map", "vehicle"],
    manifest: dict[str, Any],
    resolved: dict[str, Path],
) -> list[AssetQualificationReceipt]:
    """Recompute qualification from staged bytes; never trust the source status flag."""

    asset_id = str(manifest.get("asset_id", ""))
    receipts, qualification = _source_receipts(staging, asset_id, manifest)
    receipts.append(_integrity_receipt(staging, asset_id, manifest))
    if kind == "map":
        receipts.extend(_map_receipts(asset_id, manifest, resolved, qualification))
    else:
        receipts.extend(_vehicle_receipts(asset_id, manifest, resolved, qualification))
    return receipts
