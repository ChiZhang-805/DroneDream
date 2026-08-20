from __future__ import annotations

import importlib.util
import json
import math
import sys
from pathlib import Path

import pytest

from app.autonomy.school_map_artifact import (
    school_map_collision_primitives,
    school_map_runtime_collision_primitives,
)
from app.autonomy.school_map_mission_validation import (
    model_root_to_world_envelope_center,
    vehicle_clearance_to_primitive_m,
)

RUNNER_PATH = (
    Path(__file__).resolve().parents[2] / "scripts" / "simulators" / "school_map_px4_mission.py"
)
SPEC = importlib.util.spec_from_file_location("school_map_px4_mission", RUNNER_PATH)
assert SPEC is not None and SPEC.loader is not None
runner = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = runner
SPEC.loader.exec_module(runner)


def test_payload_spawn_and_pickup_share_the_same_precise_acceptance_radius() -> None:
    assert pytest.approx(0.20) == runner.PICKUP_ACCEPTANCE_RADIUS_M
    assert runner.PICKUP_PAYLOAD_SPAWN_RADIUS_M == runner.PICKUP_ACCEPTANCE_RADIUS_M


def test_live_progress_cannot_jump_across_the_symmetric_return_route() -> None:
    route = [(float(index), 0.0, 1.0) for index in range(30)]

    index = runner._monotonic_route_progress_index((25.0, 0.0, 1.0), route, 3)

    assert index == 9
    assert index - 3 == runner.ROUTE_PROGRESS_MAXIMUM_LOOKAHEAD_WAYPOINTS


def test_designated_landing_pad_contact_is_not_hidden_as_free_flight() -> None:
    exact = model_root_to_world_envelope_center((-42.25, 15.3, 7.487))
    solver_contact = (exact[0], exact[1], exact[2] - 0.000565)

    result = runner._dynamic_safety_clearance(
        [exact, solver_contact],
        school_map_runtime_collision_primitives(),
        exact,
    )

    assert result["unsafe_collision_count"] == 0
    assert result["minimum_clearance_primitive"] == "office-drone-launch-pad"
    assert result["minimum_clearance_m"] == pytest.approx(-0.000565)
    assert result["designated_pad_contact"]["within_solver_tolerance"] is True


def test_landing_contact_over_two_millimeters_fails_the_contact_gate() -> None:
    endpoint = model_root_to_world_envelope_center((-42.25, 15.3, 7.487))
    point = (endpoint[0], endpoint[1], endpoint[2] - 0.0021)

    result = runner._dynamic_safety_clearance(
        [point],
        school_map_runtime_collision_primitives(),
        endpoint,
    )

    assert result["designated_pad_contact"]["within_solver_tolerance"] is False


def test_live_clearance_uses_the_same_designated_pad_contact_contract() -> None:
    primitives = runner.school_map_runtime_collision_primitives()
    spawn_model_root = (-42.25, 15.3, 7.487)
    exact = model_root_to_world_envelope_center(spawn_model_root)
    solver_contact = (exact[0], exact[1], exact[2] - 0.0018)

    assert math.dist(exact, runner._route_points()[0]) > 0.4

    result = runner._dynamic_safety_clearance(
        [solver_contact],
        primitives,
        exact,
    )

    assert result["unsafe_collision_count"] == 0
    assert result["designated_contact_sample_count"] == 1
    assert result["designated_pad_contact"]["within_solver_tolerance"] is True


def test_runtime_safety_uses_the_same_conservative_geometry_exported_to_gazebo() -> None:
    point = (16.61, 11.86, 1.465)
    detailed_clearance = min(
        vehicle_clearance_to_primitive_m(point, primitive)
        for primitive in school_map_collision_primitives()
    )

    result = runner._dynamic_safety_clearance(
        [point],
        school_map_runtime_collision_primitives(),
        model_root_to_world_envelope_center((-42.25, 15.3, 7.487)),
    )

    assert detailed_clearance > 0.56
    assert result["unsafe_collision_count"] == 1
    assert result["minimum_clearance_primitive"] == (
        "cafeteria-1-table-1-1-conservative-furniture-envelope"
    )
    assert result["minimum_clearance_m"] == pytest.approx(-0.01)


def test_payload_retention_uses_model_root_relative_physical_pose() -> None:
    vehicles = [runner.GazeboPoseSample(float(index), float(index), 2.0, 3.0) for index in range(4)]
    payloads = [
        runner.GazeboPoseSample(float(index), float(index), 2.0, 3.12) for index in range(1, 4)
    ]

    result = runner._payload_retention_measurements(vehicles, payloads)

    assert result["settled_sample_count"] == 2
    assert result["maximum_attachment_error_m"] == pytest.approx(0.0, abs=1e-12)
    assert result["final_attachment_error_m"] == pytest.approx(0.0, abs=1e-12)


def test_missing_payload_measurements_are_strict_json_nulls() -> None:
    result = runner._payload_retention_measurements([], [])

    assert result == {
        "settled_sample_count": 0,
        "maximum_attachment_error_m": None,
        "final_attachment_error_m": None,
    }


def test_final_clearance_resampling_removes_stationary_pose_duplicates() -> None:
    points = [(0.0, 0.0, 1.0)] * 100 + [(1.0, 0.0, 1.0)] * 100

    result = runner._resample_recorded_centers(points, interval_m=0.04)

    assert len(result) == 26
    assert result[0] == points[0]
    assert result[-1] == points[-1]


def test_precreated_run_directory_preserves_only_a_valid_early_abort_file(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    abort_path = run_dir / "live_abort.request.json"
    abort_path.write_text(
        json.dumps({"reason": "operator_abort: stop", "world_paused": False}),
        encoding="utf-8",
    )

    runner._prepare_run_directory(run_dir)

    assert abort_path.is_file()
    assert runner._read_live_abort_request(abort_path) == ("operator_abort: stop", False)


def test_precreated_run_directory_rejects_unexpected_artifacts(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "unexpected.log").write_text("stale", encoding="utf-8")

    with pytest.raises(FileExistsError, match="unexpected.log"):
        runner._prepare_run_directory(run_dir)


def test_precreated_run_directory_rejects_an_invalid_early_abort(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "live_abort.request.json").write_text("not-json", encoding="utf-8")

    with pytest.raises(RuntimeError, match="abort request is invalid"):
        runner._prepare_run_directory(run_dir)


@pytest.mark.parametrize(
    "payload",
    (
        "x" * (runner.MAX_LIVE_ABORT_REQUEST_BYTES + 1),
        "not-json",
        json.dumps({"reason": "", "world_paused": False}),
        json.dumps({"reason": "operator_abort: stop", "world_paused": "false"}),
    ),
)
def test_live_abort_reader_rejects_oversized_or_invalid_requests(
    tmp_path: Path,
    payload: str,
) -> None:
    path = tmp_path / "live_abort.request.json"
    path.write_text(payload, encoding="utf-8")

    with pytest.raises(RuntimeError, match="abort"):
        runner._read_live_abort_request(path)
