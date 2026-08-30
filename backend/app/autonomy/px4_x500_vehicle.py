"""Pinned PX4 Gazebo X500-depth physics and DroneDream payload contract.

The values in this module are derived from the PX4 ``x500`` and ``x500_base``
SDF files pinned by the Runtime release.  They are intentionally shared by the
map artifact, mission runner, backend qualification, and frontend generated
contract so the displayed aircraft cannot silently diverge from simulation.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final
from xml.etree import ElementTree

PX4_X500_BASE_LINK_MASS_KG: Final = 2.0
PX4_X500_ROTOR_LINK_MASS_KG: Final = 0.016076923076923075
PX4_X500_ROTOR_COUNT: Final = 4
PX4_X500_DEPTH_CAMERA_MASS_KG: Final = 0.061
PX4_X500_DRY_MASS_KG: Final = (
    PX4_X500_BASE_LINK_MASS_KG + PX4_X500_ROTOR_COUNT * PX4_X500_ROTOR_LINK_MASS_KG
    + PX4_X500_DEPTH_CAMERA_MASS_KG
)
PX4_X500_MOTOR_CONSTANT: Final = 8.54858e-06
PX4_X500_MAX_ROTOR_VELOCITY_RAD_S: Final = 1000.0
PX4_X500_MAXIMUM_THRUST_N: Final = (
    PX4_X500_ROTOR_COUNT * PX4_X500_MOTOR_CONSTANT * PX4_X500_MAX_ROTOR_VELOCITY_RAD_S**2
)
PX4_X500_MINIMUM_QUALIFIED_THRUST_TO_WEIGHT: Final = 1.6
STANDARD_GRAVITY_M_S2: Final = 9.80665

TAKEOUT_PAYLOAD_MODEL_NAME: Final = "takeout_payload"
TAKEOUT_PAYLOAD_LINK_NAME: Final = "payload_link"
TAKEOUT_PAYLOAD_MASS_KG: Final = 0.04
TAKEOUT_PAYLOAD_SIZE_M: Final = (0.16, 0.06, 0.16)
# PX4 model root is 0.24 m below base_link.  This center keeps the parcel
# between the landing legs, above the 0.013 m skid contact plane, and below the
# body collision whose lower face is 0.222 m above the model root.
TAKEOUT_PAYLOAD_CENTER_ABOVE_MODEL_ROOT_M: Final = 0.12
TAKEOUT_PAYLOAD_RELATIVE_TO_BASE_LINK_M: Final = (0.0, 0.0, -0.12)
TAKEOUT_PAYLOAD_MAXIMUM_ATTACHMENT_ERROR_M: Final = 0.02

MY_DRONE_MODEL_NAME: Final = "my_drone"
MY_DRONE_PAYLOAD_ATTACH_TOPIC: Final = "/model/my_drone/takeout_payload/attach"
MY_DRONE_PAYLOAD_DETACH_TOPIC: Final = "/model/my_drone/takeout_payload/detach"
MY_DRONE_PAYLOAD_STATE_TOPIC: Final = "/model/my_drone/takeout_payload/state"


def px4_x500_maximum_qualified_payload_kg() -> float:
    """Return the analytical payload ceiling at the qualified T/W ratio."""

    maximum_mass = PX4_X500_MAXIMUM_THRUST_N / (
        PX4_X500_MINIMUM_QUALIFIED_THRUST_TO_WEIGHT * STANDARD_GRAVITY_M_S2
    )
    return maximum_mass - PX4_X500_DRY_MASS_KG


def px4_x500_loaded_thrust_to_weight(payload_mass_kg: float) -> float:
    if not math.isfinite(payload_mass_kg) or payload_mass_kg < 0:
        raise ValueError("payload mass must be finite and non-negative")
    return PX4_X500_MAXIMUM_THRUST_N / (
        (PX4_X500_DRY_MASS_KG + payload_mass_kg) * STANDARD_GRAVITY_M_S2
    )


@dataclass(frozen=True)
class MyDroneGazeboArtifact:
    files: dict[str, str]
    summary: dict[str, Any]


def _model_config() -> str:
    root = ElementTree.Element("model")
    ElementTree.SubElement(root, "name").text = "DroneDream My Drone"
    ElementTree.SubElement(root, "version").text = "1.0.0"
    sdf = ElementTree.SubElement(root, "sdf", {"version": "1.9"})
    sdf.text = "model.sdf"
    description = ElementTree.SubElement(root, "description")
    description.text = (
        "PX4 Gazebo X500 with OakD-Lite depth perception and a qualified "
        "DroneDream payload joint."
    )
    ElementTree.indent(root, space="  ")
    return '<?xml version="1.0"?>\n' + ElementTree.tostring(root, encoding="unicode") + "\n"


def _my_drone_model_sdf() -> str:
    sdf = ElementTree.Element("sdf", {"version": "1.9"})
    model = ElementTree.SubElement(sdf, "model", {"name": MY_DRONE_MODEL_NAME})
    include = ElementTree.SubElement(model, "include", {"merge": "true"})
    ElementTree.SubElement(include, "uri").text = "model://x500_depth"
    plugin = ElementTree.SubElement(
        model,
        "plugin",
        {
            "filename": "gz-sim-detachable-joint-system",
            "name": "gz::sim::systems::DetachableJoint",
        },
    )
    ElementTree.SubElement(plugin, "parent_link").text = "base_link"
    ElementTree.SubElement(plugin, "child_model").text = TAKEOUT_PAYLOAD_MODEL_NAME
    ElementTree.SubElement(plugin, "child_link").text = TAKEOUT_PAYLOAD_LINK_NAME
    ElementTree.SubElement(plugin, "attach_topic").text = MY_DRONE_PAYLOAD_ATTACH_TOPIC
    ElementTree.SubElement(plugin, "detach_topic").text = MY_DRONE_PAYLOAD_DETACH_TOPIC
    ElementTree.SubElement(plugin, "output_topic").text = MY_DRONE_PAYLOAD_STATE_TOPIC
    ElementTree.SubElement(plugin, "suppress_child_warning").text = "true"
    ElementTree.indent(sdf, space="  ")
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        + ElementTree.tostring(sdf, encoding="unicode")
        + "\n"
    )


def takeout_payload_sdf() -> str:
    """Return a complete dynamic 0.04 kg parcel model for Gazebo creation."""

    size_x, size_y, size_z = TAKEOUT_PAYLOAD_SIZE_M
    mass = TAKEOUT_PAYLOAD_MASS_KG
    inertia_x = mass * (size_y**2 + size_z**2) / 12
    inertia_y = mass * (size_x**2 + size_z**2) / 12
    inertia_z = mass * (size_x**2 + size_y**2) / 12
    sdf = ElementTree.Element("sdf", {"version": "1.9"})
    model = ElementTree.SubElement(sdf, "model", {"name": TAKEOUT_PAYLOAD_MODEL_NAME})
    ElementTree.SubElement(model, "static").text = "false"
    ElementTree.SubElement(model, "self_collide").text = "false"
    link = ElementTree.SubElement(model, "link", {"name": TAKEOUT_PAYLOAD_LINK_NAME})
    inertial = ElementTree.SubElement(link, "inertial")
    ElementTree.SubElement(inertial, "mass").text = f"{mass:g}"
    inertia = ElementTree.SubElement(inertial, "inertia")
    ElementTree.SubElement(inertia, "ixx").text = f"{inertia_x:.12g}"
    ElementTree.SubElement(inertia, "iyy").text = f"{inertia_y:.12g}"
    ElementTree.SubElement(inertia, "izz").text = f"{inertia_z:.12g}"
    for cross_term in ("ixy", "ixz", "iyz"):
        ElementTree.SubElement(inertia, cross_term).text = "0"
    geometry_size = " ".join(f"{value:g}" for value in TAKEOUT_PAYLOAD_SIZE_M)
    for element_name in ("collision", "visual"):
        element = ElementTree.SubElement(link, element_name, {"name": f"parcel-{element_name}"})
        geometry = ElementTree.SubElement(element, "geometry")
        box = ElementTree.SubElement(geometry, "box")
        ElementTree.SubElement(box, "size").text = geometry_size
        if element_name == "visual":
            material = ElementTree.SubElement(element, "material")
            ElementTree.SubElement(material, "ambient").text = "0.88 0.48 0.12 1"
            ElementTree.SubElement(material, "diffuse").text = "0.96 0.58 0.18 1"
    ElementTree.indent(sdf, space="  ")
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        + ElementTree.tostring(sdf, encoding="unicode")
        + "\n"
    )


def get_my_drone_gazebo_artifact() -> MyDroneGazeboArtifact:
    loaded_mass = PX4_X500_DRY_MASS_KG + TAKEOUT_PAYLOAD_MASS_KG
    summary: dict[str, Any] = {
        "schema_version": "dronedream.my-drone-gazebo-artifact.v1",
        "model_name": MY_DRONE_MODEL_NAME,
        "source_model": "model://x500_depth",
        "control_interface": "mavsdk",
        "dry_mass_kg": PX4_X500_DRY_MASS_KG,
        "maximum_thrust_n": PX4_X500_MAXIMUM_THRUST_N,
        "minimum_qualified_thrust_to_weight": PX4_X500_MINIMUM_QUALIFIED_THRUST_TO_WEIGHT,
        "maximum_qualified_payload_kg": px4_x500_maximum_qualified_payload_kg(),
        "perception": {
            "sensor_id": "oakd-lite-depth",
            "sensor_type": "depth-camera",
            "topic": "/depth_camera",
            "update_rate_hz": 30,
            "image_width": 640,
            "image_height": 480,
            "horizontal_fov_rad": 1.274,
            "minimum_depth_m": 0.2,
            "maximum_depth_m": 19.1,
            "camera_mass_kg": PX4_X500_DEPTH_CAMERA_MASS_KG,
            "optical_center_relative_to_collision_center_m": (0.13233, 0.0, 0.03278),
        },
        "mission_payload": {
            "model_name": TAKEOUT_PAYLOAD_MODEL_NAME,
            "link_name": TAKEOUT_PAYLOAD_LINK_NAME,
            "mass_kg": TAKEOUT_PAYLOAD_MASS_KG,
            "size_m": TAKEOUT_PAYLOAD_SIZE_M,
            "center_above_model_root_m": TAKEOUT_PAYLOAD_CENTER_ABOVE_MODEL_ROOT_M,
            "maximum_attachment_error_m": TAKEOUT_PAYLOAD_MAXIMUM_ATTACHMENT_ERROR_M,
            "loaded_mass_kg": loaded_mass,
            "loaded_thrust_to_weight": px4_x500_loaded_thrust_to_weight(TAKEOUT_PAYLOAD_MASS_KG),
            "attach_topic": MY_DRONE_PAYLOAD_ATTACH_TOPIC,
            "detach_topic": MY_DRONE_PAYLOAD_DETACH_TOPIC,
            "state_topic": MY_DRONE_PAYLOAD_STATE_TOPIC,
        },
    }
    files = {
        "model.config": _model_config(),
        "model.sdf": _my_drone_model_sdf(),
        "takeout-payload.sdf": takeout_payload_sdf(),
        "summary.json": json.dumps(summary, indent=2, sort_keys=True) + "\n",
    }
    summary["payload_files_sha256"] = {
        name: hashlib.sha256(content.encode("utf-8")).hexdigest()
        for name, content in sorted(files.items())
        if name != "summary.json"
    }
    files["summary.json"] = json.dumps(summary, indent=2, sort_keys=True) + "\n"
    return MyDroneGazeboArtifact(files=files, summary=summary)


def export_my_drone_gazebo_artifact(output_directory: Path) -> dict[str, str]:
    artifact = get_my_drone_gazebo_artifact()
    output_directory.mkdir(parents=True, exist_ok=True)
    result: dict[str, str] = {}
    for name, content in artifact.files.items():
        target = output_directory / name
        target.write_text(content, encoding="utf-8")
        result[name] = hashlib.sha256(target.read_bytes()).hexdigest()
    return result
