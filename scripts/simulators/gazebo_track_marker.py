#!/usr/bin/env python3
"""Draw DroneDream reference track markers in Gazebo Sim."""

from __future__ import annotations

import argparse
import json
import math
import shutil
import subprocess
import time
from pathlib import Path

CLOSE_DISTANCE_THRESHOLD_M = 2.0


class TrackMarkerError(RuntimeError):
    """Track marker failure."""


def _append_log(log_path: Path | None, message: str) -> None:
    if log_path is None:
        return
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(message.rstrip("\n") + "\n")


def _extract_track_container(payload: object) -> list[object]:
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in ("points", "samples", "reference_track"):
            value = payload.get(key)
            if isinstance(value, list):
                return value
    raise TrackMarkerError("reference track JSON must be a list or contain points/samples/reference_track list")


def load_reference_points(path: Path) -> list[dict[str, float]]:
    if not path.exists():
        raise TrackMarkerError(f"track file does not exist: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise TrackMarkerError(f"malformed track JSON: {exc}") from exc

    raw_points = _extract_track_container(payload)
    normalized: list[dict[str, float]] = []
    for idx, item in enumerate(raw_points):
        if not isinstance(item, dict):
            raise TrackMarkerError(f"track point {idx} must be an object")
        if "x" not in item or "y" not in item:
            raise TrackMarkerError(f"track point {idx} missing x or y")
        try:
            x = float(item["x"])
            y = float(item["y"])
            z = float(item.get("z", 0.0))
        except (TypeError, ValueError):
            raise TrackMarkerError(f"track point {idx} has non-numeric x/y/z") from None
        if not (math.isfinite(x) and math.isfinite(y) and math.isfinite(z)):
            raise TrackMarkerError(f"track point {idx} has non-finite x/y/z")
        normalized.append({"x": x, "y": y, "z": z})

    if not normalized:
        raise TrackMarkerError("track contains no valid points")
    return normalized


def project_points_to_ground(points: list[dict[str, float]], z_offset: float) -> list[tuple[float, float, float]]:
    return [(float(p["x"]), float(p["y"]), float(z_offset)) for p in points]


def maybe_close_track(points: list[tuple[float, float, float]], threshold_m: float = CLOSE_DISTANCE_THRESHOLD_M) -> list[tuple[float, float, float]]:
    if len(points) < 3:
        return points
    start = points[0]
    end = points[-1]
    distance = math.dist((start[0], start[1]), (end[0], end[1]))
    if distance <= threshold_m:
        return [*points, start]
    return points


def _parse_color(color: str) -> tuple[float, float, float, float]:
    parts = color.split()
    if len(parts) != 4:
        raise TrackMarkerError("--color must contain exactly four floats: 'r g b a'")
    try:
        values = tuple(float(p) for p in parts)
    except ValueError:
        raise TrackMarkerError("--color must contain numeric floats") from None
    if not all(math.isfinite(v) for v in values):
        raise TrackMarkerError("--color contains non-finite values")
    return values


def _line_type_token(mode: str) -> int:
    # gz.msgs.Marker enum: LINE_STRIP=4, POINTS=8
    return 4 if mode == "line_strip" else 8


def _marker_points_text(points: list[tuple[float, float, float]]) -> str:
    return " ".join(f"point {{ x: {x} y: {y} z: {z} }}" for x, y, z in points)


def build_marker_service_request(
    *,
    points: list[tuple[float, float, float]],
    world: str,
    color: str,
    line_width: float,
    marker_namespace: str,
    marker_id: int,
    mode: str,
) -> str:
    r, g, b, a = _parse_color(color)
    line_type = _line_type_token(mode)
    points_text = _marker_points_text(points)
    return (
        f"ns: '{marker_namespace}' id: {marker_id} action: ADD_MODIFY type: {line_type} "
        f"scale {{ x: {line_width} y: {line_width} z: {line_width} }} "
        f"material {{ diffuse {{ r: {r} g: {g} b: {b} a: {a} }} "
        f"ambient {{ r: {r} g: {g} b: {b} a: {a} }} }} "
        f"lifetime {{ sec: 0 nsec: 0 }} {points_text}"
    )


def build_marker_command(*, world: str, request: str) -> list[str]:
    return [
        "gz",
        "service",
        "-s",
        f"/world/{world}/marker",
        "--reqtype",
        "gz.msgs.Marker",
        "--reptype",
        "gz.msgs.Boolean",
        "--timeout",
        "3000",
        "--req",
        request,
    ]


def _run_cmd(argv: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(argv, text=True, capture_output=True, check=False)  # noqa: S603


def _marker_backend_available() -> bool:
    return shutil.which("gz") is not None


def draw_track_marker(
    *,
    track_path: Path,
    world: str,
    z_offset: float,
    color: str,
    line_width: float,
    marker_namespace: str,
    marker_id: int,
    mode: str,
    hold_seconds: float,
    log_path: Path | None,
) -> int:
    points = load_reference_points(track_path)
    projected = project_points_to_ground(points, z_offset)
    if mode == "line_strip":
        projected = maybe_close_track(projected)
    if not projected:
        raise TrackMarkerError("no projected points available for marker drawing")

    if not _marker_backend_available():
        raise TrackMarkerError("marker backend unavailable: gz command not found")

    request = build_marker_service_request(
        points=projected,
        world=world,
        color=color,
        line_width=line_width,
        marker_namespace=marker_namespace,
        marker_id=marker_id,
        mode=mode,
    )
    cmd = build_marker_command(world=world, request=request)

    _append_log(log_path, f"[gazebo_track_marker] backend=gz_service world={world} mode={mode}")
    _append_log(log_path, f"[gazebo_track_marker] command={cmd}")

    result = _run_cmd(cmd)
    if result.stdout:
        _append_log(log_path, f"[gazebo_track_marker] stdout={result.stdout.strip()}")
    if result.stderr:
        _append_log(log_path, f"[gazebo_track_marker] stderr={result.stderr.strip()}")

    if result.returncode != 0:
        raise TrackMarkerError(f"marker service unavailable or failed (exit={result.returncode})")

    if hold_seconds > 0:
        _append_log(log_path, f"[gazebo_track_marker] hold_seconds={hold_seconds}")
        time.sleep(hold_seconds)
    return 0


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Draw DroneDream reference track marker in Gazebo")
    parser.add_argument("--track", required=True, type=Path)
    parser.add_argument("--world", default="default")
    parser.add_argument("--z-offset", type=float, default=0.03)
    parser.add_argument("--color", default="0 0.8 1 1")
    parser.add_argument("--line-width", type=float, default=0.08)
    parser.add_argument("--marker-namespace", default="dronedream_track")
    parser.add_argument("--marker-id", type=int, default=805)
    parser.add_argument("--mode", choices=("line_strip", "points"), default="line_strip")
    parser.add_argument("--hold-seconds", type=float, default=0.0)
    parser.add_argument("--log", type=Path)
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    try:
        return draw_track_marker(
            track_path=args.track,
            world=args.world,
            z_offset=args.z_offset,
            color=args.color,
            line_width=args.line_width,
            marker_namespace=args.marker_namespace,
            marker_id=args.marker_id,
            mode=args.mode,
            hold_seconds=max(0.0, args.hold_seconds),
            log_path=args.log,
        )
    except TrackMarkerError as exc:
        message = f"[gazebo_track_marker] {exc}"
        print(message)
        _append_log(args.log, message)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
