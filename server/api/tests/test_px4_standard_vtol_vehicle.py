from __future__ import annotations

import hashlib
import json
from xml.etree import ElementTree as ET

import pytest

from app.autonomy.px4_standard_vtol_vehicle import (
    AIRFRAME_MASS_KG,
    DRY_MASS_KG,
    PAYLOAD_CENTER_M,
    VERTICAL_THRUST_N,
    export_standard_vtol_gazebo_artifact,
    get_standard_vtol_gazebo_artifact,
)


def test_mission_assembly_preserves_vtol_and_adds_physical_perception_and_payload():
    artifact = get_standard_vtol_gazebo_artifact()
    model = ET.fromstring(artifact.files["model.sdf"]).find("model")
    assert [item.findtext("uri") for item in model.findall("include")] == [
        "model://standard_vtol", "model://OakD-Lite",
    ]
    assert model.find("joint").attrib["type"] == "fixed"
    assert model.findtext("joint/parent") == "base_link"
    assert model.findtext("joint/child") == "camera_link"
    assert model.findtext("plugin/child_model") == "takeout_payload"
    assert artifact.summary["px4_sitl_model"] == "standard_vtol"
    assert "maximum_qualified_payload_kg" not in artifact.summary
    assert pytest.approx(5 + 5 * 0.005 + 3e-8) == AIRFRAME_MASS_KG
    assert pytest.approx(AIRFRAME_MASS_KG + 0.061) == DRY_MASS_KG
    assert pytest.approx(180) == VERTICAL_THRUST_N


def test_payload_clears_wing_and_lift_rotors():
    payload = get_standard_vtol_gazebo_artifact().summary["mission_payload"]
    half_x, half_y, half_z = [size / 2 for size in payload["size_m"]]
    assert PAYLOAD_CENTER_M - half_z > 0.246 - 0.07 + 0.05 / 2
    for rotor_x, rotor_y in [(0.35, 0.35), (-0.35, 0.35), (0.35, -0.35), (-0.35, -0.35)]:
        assert abs(rotor_x) - half_x > 0.1
        assert abs(rotor_y) - half_y > 0.1


def test_exported_summary_binds_actual_model_bytes(tmp_path):
    hashes = export_standard_vtol_gazebo_artifact(tmp_path)
    summary = json.loads((tmp_path / "summary.json").read_text())
    for name, digest in summary["payload_files_sha256"].items():
        assert digest == hashes[name] == hashlib.sha256((tmp_path / name).read_bytes()).hexdigest()


def test_loaded_envelope_rests_on_the_actual_wing_collision_surface():
    envelope = get_standard_vtol_gazebo_artifact().summary["collision_envelope"]
    center = envelope["collision_center_offset_model_m"]["z"]
    half_height = envelope["body_height_m"] / 2
    assert center - half_height == pytest.approx(0.246 - 0.07 - 0.025)
    assert center + half_height == pytest.approx(PAYLOAD_CENTER_M + 0.08)
