from __future__ import annotations

import json
import math
from xml.etree import ElementTree

import pytest

from app.autonomy.px4_x500_vehicle import (
    MY_DRONE_PAYLOAD_STATE_TOPIC,
    PX4_X500_DRY_MASS_KG,
    PX4_X500_MAXIMUM_THRUST_N,
    TAKEOUT_PAYLOAD_CENTER_ABOVE_MODEL_ROOT_M,
    TAKEOUT_PAYLOAD_MASS_KG,
    TAKEOUT_PAYLOAD_SIZE_M,
    get_my_drone_gazebo_artifact,
    px4_x500_loaded_thrust_to_weight,
    px4_x500_maximum_qualified_payload_kg,
)
from app.autonomy.school_map_artifact import (
    PX4_X500_MODEL_ROOT_TO_CONTACT_M,
    VEHICLE_COLLISION_HEIGHT_M,
)


def test_pinned_px4_x500_contract_matches_runtime_sdf_calculation() -> None:
    assert pytest.approx(2.0643076923076924) == PX4_X500_DRY_MASS_KG
    assert pytest.approx(34.19432) == PX4_X500_MAXIMUM_THRUST_N
    assert px4_x500_maximum_qualified_payload_kg() == pytest.approx(0.114974, abs=1e-6)
    assert px4_x500_loaded_thrust_to_weight(TAKEOUT_PAYLOAD_MASS_KG) >= 1.6


def test_takeout_payload_is_inside_the_qualified_vehicle_vertical_envelope() -> None:
    payload_bottom = TAKEOUT_PAYLOAD_CENTER_ABOVE_MODEL_ROOT_M - TAKEOUT_PAYLOAD_SIZE_M[2] / 2
    payload_top = TAKEOUT_PAYLOAD_CENTER_ABOVE_MODEL_ROOT_M + TAKEOUT_PAYLOAD_SIZE_M[2] / 2
    envelope_bottom = PX4_X500_MODEL_ROOT_TO_CONTACT_M
    envelope_top = envelope_bottom + VEHICLE_COLLISION_HEIGHT_M

    assert payload_bottom > envelope_bottom
    assert payload_top < envelope_top
    # The parcel is only 60 mm wide.  Its side has at least 24 mm clearance
    # from the conservatively projected nearest face of each angled landing leg.
    nearest_leg_inner_face_y = 0.098 - (0.015 / 2 * math.cos(0.35) + 0.21 / 2 * math.sin(0.35))
    assert nearest_leg_inner_face_y - TAKEOUT_PAYLOAD_SIZE_M[1] / 2 > 0.024


def test_my_drone_artifact_binds_x500_and_dynamic_payload_joint() -> None:
    artifact = get_my_drone_gazebo_artifact()
    model = ElementTree.fromstring(artifact.files["model.sdf"])
    payload = ElementTree.fromstring(artifact.files["takeout-payload.sdf"])
    summary = json.loads(artifact.files["summary.json"])

    assert model.findtext(".//include/uri") == "model://x500"
    assert model.findtext(".//plugin/parent_link") == "base_link"
    assert model.findtext(".//plugin/child_model") == "takeout_payload"
    assert model.findtext(".//plugin/output_topic") == MY_DRONE_PAYLOAD_STATE_TOPIC
    assert payload.findtext(".//link/inertial/mass") == "0.1"
    assert summary["control_interface"] == "mavsdk"
    assert summary["mission_payload"]["loaded_thrust_to_weight"] >= 1.6
    assert set(summary["payload_files_sha256"]) == {
        "model.config",
        "model.sdf",
        "takeout-payload.sdf",
    }
