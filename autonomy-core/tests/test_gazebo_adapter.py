import json
import subprocess

import dronedream_agent_core.gazebo_adapter as gazebo_adapter
from dronedream_agent_core.gazebo_adapter import (
    _gazebo_image_png,
    _is_tolerated_landing_contact,
    _landing_confirmed,
    _live_camera_sdf,
    _publish_native_terminal_lifecycle,
)


def test_landing_ground_contact_has_narrow_phase_surface_and_depth_boundary() -> None:
    assert _is_tolerated_landing_contact(
        phase="LANDING",
        primitive_name="school-map-ground",
        clearance_m=-0.0139,
    )
    assert not _is_tolerated_landing_contact(
        phase="TRACK",
        primitive_name="school-map-ground",
        clearance_m=-0.0139,
    )
    assert not _is_tolerated_landing_contact(
        phase="LANDING",
        primitive_name="campus-main-gate-header",
        clearance_m=-0.0139,
    )
    assert not _is_tolerated_landing_contact(
        phase="LANDING",
        primitive_name="school-map-ground",
        clearance_m=-0.0201,
    )


def test_native_terminal_lifecycle_requires_px4_on_ground_evidence() -> None:
    accepted = {
        "cleanup": {
            "land": "confirmed_on_ground: telemetry",
            "landing_observation": {"state": "ON_GROUND"},
        }
    }
    assert _landing_confirmed(accepted)
    assert not _landing_confirmed({"cleanup": {"land": "requested"}})
    assert not _landing_confirmed(
        {
            "cleanup": {
                "land": "confirmed_on_ground: telemetry",
                "landing_observation": {"state": "IN_AIR"},
            }
        }
    )


def test_native_terminal_lifecycle_publication_is_contract_bound(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_run(command, *, env, timeout):
        captured["command"] = command
        captured["env"] = env
        captured["timeout"] = timeout
        return subprocess.CompletedProcess(command, 0, "published", "")

    monkeypatch.setattr(gazebo_adapter, "_run", fake_run)
    receipt = _publish_native_terminal_lifecycle(
        contract_id="mission-contract-1",
        executor_return_code=0,
        env={"ROS_DOMAIN_ID": "74"},
    )

    command = captured["command"]
    assert isinstance(command, list)
    payload = json.loads(command[-1])
    assert payload == {
        "contract_id": "mission-contract-1",
        "terminal_state": "ON_GROUND",
        "executor_return_code": 0,
        "landing_confirmed": True,
        "safe_to_stop_watchdog": True,
    }
    assert receipt["publisher_exit_code"] == 0


def test_live_camera_frame_is_encoded_as_browser_png() -> None:
    class Frame:
        width = 2
        height = 1
        step = 6
        pixel_format_type = 3
        data = bytes((255, 0, 0, 0, 255, 0))

    payload = _gazebo_image_png(Frame())

    assert payload.startswith(b"\x89PNG\r\n\x1a\n")
    assert payload.endswith(b"IEND\xaeB`\x82")


def test_live_camera_is_positioned_from_the_real_route() -> None:
    sdf, camera = _live_camera_sdf([(0.0, 0.0, 2.0), (12.0, 8.0, 5.0)])

    assert '<topic>/dronedream/live/camera</topic>' in sdf
    assert "<width>1280</width><height>720</height>" in sdf
    assert camera[0] < 0.0
    assert camera[1] < 0.0
    assert camera[2] > 5.0
