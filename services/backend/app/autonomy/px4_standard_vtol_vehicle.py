"""Mission assembly around the pinned PX4 Standard VTOL airframe.

This describes physical components, not a flight qualification. The PX4
airframe remains a VTOL; short delivery missions use its multicopter mode.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from xml.etree import ElementTree as ET

from .px4_x500_vehicle import (
    STANDARD_GRAVITY_M_S2,
    TAKEOUT_PAYLOAD_MASS_KG,
    TAKEOUT_PAYLOAD_MAXIMUM_ATTACHMENT_ERROR_M,
    TAKEOUT_PAYLOAD_SIZE_M,
    MyDroneGazeboArtifact,
    takeout_payload_sdf,
)

# PX4 standard_vtol: 5 kg body, five 0.005 kg rotors, three 1e-8 kg surfaces.
AIRFRAME_MASS_KG = 5.02500003
CAMERA_MASS_KG = 0.061
DRY_MASS_KG = AIRFRAME_MASS_KG + CAMERA_MASS_KG
# Only the four vertical motors contribute to the hover thrust budget.
VERTICAL_THRUST_N = 4 * 2e-5 * 1500**2
BASE_LINK_HEIGHT_M = 0.246
CAMERA_POSE_M = (0.6, 0.03, 0.32)
# Above the wing's collision top (0.201 m); clear of all four lift rotors.
PAYLOAD_CENTER_M = 0.32
# Pinned wing collider: model pose 0.246, collider pose -0.07, height 0.05.
# The loaded payload is the highest collider; this same bound is used at rest
# and in flight, so a correctly grounded airframe is not treated as penetration.
COLLISION_BOTTOM_M = BASE_LINK_HEIGHT_M - 0.07 - 0.05 / 2
COLLISION_TOP_M = PAYLOAD_CENTER_M + TAKEOUT_PAYLOAD_SIZE_M[2] / 2
MODEL_NAME = "my_drone"


def get_standard_vtol_gazebo_artifact() -> MyDroneGazeboArtifact:
    sdf = ET.Element("sdf", {"version": "1.10"})
    model = ET.SubElement(sdf, "model", {"name": MODEL_NAME})
    airframe = ET.SubElement(model, "include", {"merge": "true"})
    ET.SubElement(airframe, "uri").text = "model://standard_vtol"
    camera = ET.SubElement(model, "include", {"merge": "true"})
    ET.SubElement(camera, "uri").text = "model://OakD-Lite"
    ET.SubElement(camera, "pose").text = "0.6 0.03 0.32 0 0 0"
    joint = ET.SubElement(model, "joint", {"name": "CameraJoint", "type": "fixed"})
    ET.SubElement(joint, "parent").text = "base_link"
    ET.SubElement(joint, "child").text = "camera_link"
    plugin = ET.SubElement(model, "plugin", {
        "filename": "gz-sim-detachable-joint-system",
        "name": "gz::sim::systems::DetachableJoint",
    })
    for name, value in {
        "parent_link": "base_link",
        "child_model": "takeout_payload",
        "child_link": "payload_link",
        "attach_topic": "/model/my_drone/takeout_payload/attach",
        "detach_topic": "/model/my_drone/takeout_payload/detach",
        "output_topic": "/model/my_drone/takeout_payload/state",
        "suppress_child_warning": "true",
    }.items():
        ET.SubElement(plugin, name).text = value
    ET.indent(sdf, space="  ")
    model_xml = '<?xml version="1.0"?>\n' + ET.tostring(sdf, encoding="unicode") + "\n"
    loaded_mass = DRY_MASS_KG + TAKEOUT_PAYLOAD_MASS_KG
    summary = {
        "schema_version": "dronedream.my-drone-gazebo-artifact.v1",
        "model_name": MODEL_NAME,
        "source_model": "model://standard_vtol",
        "px4_sitl_model": "standard_vtol",
        "control_interface": "mavsdk",
        "dry_mass_kg": DRY_MASS_KG,
        "maximum_thrust_n": VERTICAL_THRUST_N,
        "minimum_qualified_thrust_to_weight": 1.6,
        "collision_envelope": {
            "body_radius_m": 1.2,
            "body_height_m": COLLISION_TOP_M - COLLISION_BOTTOM_M,
            "collision_center_offset_model_m": {
                "x": 0.0, "y": 0.0,
                "z": (COLLISION_TOP_M + COLLISION_BOTTOM_M) / 2,
            },
        },
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
            "camera_mass_kg": CAMERA_MASS_KG,
            "optical_center_relative_to_base_link_m": (
                CAMERA_POSE_M[0] + 0.01233, CAMERA_POSE_M[1] - 0.03,
                CAMERA_POSE_M[2] + 0.01878 - BASE_LINK_HEIGHT_M,
            ),
        },
        "mission_payload": {
            "model_name": "takeout_payload", "link_name": "payload_link",
            "mass_kg": TAKEOUT_PAYLOAD_MASS_KG, "size_m": TAKEOUT_PAYLOAD_SIZE_M,
            "center_above_model_root_m": PAYLOAD_CENTER_M,
            "maximum_attachment_error_m": TAKEOUT_PAYLOAD_MAXIMUM_ATTACHMENT_ERROR_M,
            "loaded_mass_kg": loaded_mass,
            "loaded_thrust_to_weight": VERTICAL_THRUST_N / (loaded_mass * STANDARD_GRAVITY_M_S2),
            "attach_topic": "/model/my_drone/takeout_payload/attach",
            "detach_topic": "/model/my_drone/takeout_payload/detach",
            "state_topic": "/model/my_drone/takeout_payload/state",
        },
    }
    files = {
        "model.config": '<?xml version="1.0"?>\n<model><name>DroneDream Standard VTOL</name>'
        '<version>1.0.0</version><sdf version="1.10">model.sdf</sdf></model>\n',
        "model.sdf": model_xml,
        "takeout-payload.sdf": takeout_payload_sdf(),
    }
    summary["payload_files_sha256"] = {
        name: hashlib.sha256(content.encode("utf-8")).hexdigest()
        for name, content in sorted(files.items())
    }
    files["summary.json"] = json.dumps(summary, indent=2, sort_keys=True) + "\n"
    return MyDroneGazeboArtifact(files=files, summary=summary)


def export_standard_vtol_gazebo_artifact(output_directory: Path) -> dict[str, str]:
    artifact = get_standard_vtol_gazebo_artifact()
    output_directory.mkdir(parents=True, exist_ok=True)
    result = {}
    for name, content in artifact.files.items():
        target = output_directory / name
        target.write_text(content, encoding="utf-8", newline="\n")
        result[name] = hashlib.sha256(target.read_bytes()).hexdigest()
    return result
