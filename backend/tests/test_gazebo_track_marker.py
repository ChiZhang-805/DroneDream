from __future__ import annotations

import importlib.util
import json
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "simulators" / "gazebo_track_marker.py"
SPEC = importlib.util.spec_from_file_location("gazebo_track_marker", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
marker = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(marker)


def _write_track(path: Path, payload: object) -> Path:
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


@pytest.mark.parametrize(
    "payload",
    [
        [{"x": 1, "y": 2, "z": 3}],
        {"points": [{"x": 1, "y": 2}]},
        {"samples": [{"x": 1, "y": 2, "z": 4}]},
        {"reference_track": [{"x": 1, "y": 2, "z": 5}]},
    ],
)
def test_load_reference_points_supported_shapes(tmp_path: Path, payload: object):
    track = _write_track(tmp_path / "track.json", payload)
    points = marker.load_reference_points(track)
    assert points[0]["x"] == 1.0
    assert points[0]["y"] == 2.0
    assert "z" in points[0]


def test_project_points_to_ground_overwrites_z():
    points = [{"x": 0.0, "y": 1.0, "z": 9.0}, {"x": 2.0, "y": 3.0, "z": 8.0}]
    projected = marker.project_points_to_ground(points, z_offset=0.03)
    assert projected == [(0.0, 1.0, 0.03), (2.0, 3.0, 0.03)]


def test_maybe_close_track_closes_near_loop_and_not_u_turn():
    near_closed = [(0.0, 0.0, 0.03), (2.0, 0.0, 0.03), (0.8, 0.8, 0.03)]
    closed = marker.maybe_close_track(near_closed)
    assert closed[-1] == near_closed[0]

    u_turn = [(0.0, 0.0, 0.03), (5.0, 0.0, 0.03), (10.0, 0.0, 0.03)]
    not_closed = marker.maybe_close_track(u_turn)
    assert len(not_closed) == len(u_turn)


def test_load_reference_points_errors(tmp_path: Path):
    malformed = tmp_path / "bad.json"
    malformed.write_text("{bad", encoding="utf-8")
    with pytest.raises(marker.TrackMarkerError, match="malformed"):
        marker.load_reference_points(malformed)

    empty = _write_track(tmp_path / "empty.json", {"points": []})
    with pytest.raises(marker.TrackMarkerError, match="no valid points"):
        marker.load_reference_points(empty)


def test_build_marker_command_is_deterministic():
    request = marker.build_marker_service_request(
        points=[(1.0, 2.0, 0.03)],
        world="default",
        color="0 0.8 1 1",
        line_width=0.08,
        marker_namespace="dronedream_track",
        marker_id=805,
        mode="line_strip",
    )
    command = marker.build_marker_command(world="default", request=request)
    assert command[0] == "gz"
    assert "/world/default/marker" in command
    assert "--req" in command


def test_draw_track_marker_success_and_failure(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    track = _write_track(tmp_path / "track.json", {"points": [{"x": 0, "y": 0, "z": 3}]})
    log = tmp_path / "marker.log"

    monkeypatch.setattr(marker.shutil, "which", lambda _: "/usr/bin/gz")

    def _ok(_argv: list[str]) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(_argv, 0, stdout="ok", stderr="")

    monkeypatch.setattr(marker, "_run_cmd", _ok)
    ok_exit = marker.draw_track_marker(
        track_path=track,
        world="default",
        z_offset=0.03,
        color="0 0.8 1 1",
        line_width=0.08,
        marker_namespace="dronedream_track",
        marker_id=805,
        mode="line_strip",
        hold_seconds=0,
        log_path=log,
    )
    assert ok_exit == 0
    assert "backend=gz_service" in log.read_text(encoding="utf-8")

    def _fail(_argv: list[str]) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(_argv, 9, stdout="", stderr="boom")

    monkeypatch.setattr(marker, "_run_cmd", _fail)
    with pytest.raises(marker.TrackMarkerError, match="marker service unavailable"):
        marker.draw_track_marker(
            track_path=track,
            world="default",
            z_offset=0.03,
            color="0 0.8 1 1",
            line_width=0.08,
            marker_namespace="dronedream_track",
            marker_id=805,
            mode="line_strip",
            hold_seconds=0,
            log_path=log,
        )
