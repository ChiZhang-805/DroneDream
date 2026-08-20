from __future__ import annotations

import math
from typing import Any

from dronedream_agent_core.contracts import CoveragePattern, CoveragePlanRequest, Vector3
from dronedream_agent_core.plugin_api import PluginDefinition

from ._helpers import hook_plugin


def _inside_polygon(x: float, y: float, polygon: list[Vector3]) -> bool:
    inside = False
    previous = polygon[-1]
    for current in polygon:
        intersects = (current.y > y) != (previous.y > y) and x < (
            (previous.x - current.x) * (y - current.y) / (previous.y - current.y) + current.x
        )
        if intersects:
            inside = not inside
        previous = current
    return inside


def _bounds(request: CoveragePlanRequest) -> tuple[float, float, float, float]:
    if request.polygon_enu_m:
        xs = [point.x for point in request.polygon_enu_m]
        ys = [point.y for point in request.polygon_enu_m]
        return min(xs), max(xs), min(ys), max(ys)
    half_width = request.width_m / 2.0
    half_height = request.height_m / 2.0
    return (
        request.center_enu_m.x - half_width,
        request.center_enu_m.x + half_width,
        request.center_enu_m.y - half_height,
        request.center_enu_m.y + half_height,
    )


def _lawnmower(*, request: CoveragePlanRequest, **_: Any) -> dict[str, object]:
    min_x, max_x, min_y, max_y = _bounds(request)
    min_x += request.boundary_margin_m
    max_x -= request.boundary_margin_m
    min_y += request.boundary_margin_m
    max_y -= request.boundary_margin_m
    if min_x >= max_x or min_y >= max_y:
        raise ValueError("COVERAGE_MARGIN_COLLAPSES_REGION")
    lane_count = max(2, int(math.ceil((max_y - min_y) / request.lane_spacing_m)) + 1)
    points: list[Vector3] = []
    for lane in range(lane_count):
        y = min(max_y, min_y + lane * (max_y - min_y) / (lane_count - 1))
        candidates = [min_x, max_x] if lane % 2 == 0 else [max_x, min_x]
        for x in candidates:
            if not request.polygon_enu_m or _inside_polygon(x, y, request.polygon_enu_m):
                points.append(Vector3(x=x, y=y, z=request.altitude_m))
    if len(points) < 2:
        raise ValueError("COVERAGE_PATTERN_HAS_TOO_FEW_SAFE_POINTS")
    pattern = CoveragePattern(
        pattern="lawnmower",
        points_enu_m=points,
        lane_count=lane_count,
        estimated_area_m2=(max_x - min_x) * (max_y - min_y),
        deterministic_gates={
            "bounded_region": True,
            "positive_spacing": request.lane_spacing_m > 0,
            "alternating_lanes": True,
            "finite_points": all(
                math.isfinite(value) for point in points for value in (point.x, point.y, point.z)
            ),
        },
    )
    return pattern.model_dump(mode="json")


def _spiral(*, request: CoveragePlanRequest, **_: Any) -> dict[str, object]:
    min_x, max_x, min_y, max_y = _bounds(request)
    min_x += request.boundary_margin_m
    max_x -= request.boundary_margin_m
    min_y += request.boundary_margin_m
    max_y -= request.boundary_margin_m
    points: list[Vector3] = []
    rings = 0
    while min_x < max_x and min_y < max_y and len(points) < 10_000:
        ring = [
            Vector3(x=min_x, y=min_y, z=request.altitude_m),
            Vector3(x=max_x, y=min_y, z=request.altitude_m),
            Vector3(x=max_x, y=max_y, z=request.altitude_m),
            Vector3(x=min_x, y=max_y, z=request.altitude_m),
        ]
        points.extend(
            point
            for point in ring
            if not request.polygon_enu_m or _inside_polygon(point.x, point.y, request.polygon_enu_m)
        )
        min_x += request.lane_spacing_m
        max_x -= request.lane_spacing_m
        min_y += request.lane_spacing_m
        max_y -= request.lane_spacing_m
        rings += 1
    if len(points) < 2:
        raise ValueError("COVERAGE_PATTERN_HAS_TOO_FEW_SAFE_POINTS")
    pattern = CoveragePattern(
        pattern="inward-spiral",
        points_enu_m=points,
        lane_count=rings,
        estimated_area_m2=max(request.width_m * request.height_m, 0.01),
        deterministic_gates={
            "bounded_region": True,
            "positive_spacing": request.lane_spacing_m > 0,
            "inward_progression": True,
            "finite_points": all(
                math.isfinite(value) for point in points for value in (point.x, point.y, point.z)
            ),
        },
    )
    return pattern.model_dump(mode="json")


def _definition(
    *, plugin_id: str, name: str, description: str, handler: Any, enabled: bool, order: int
) -> PluginDefinition:
    return hook_plugin(
        module_name=__name__,
        plugin_id=plugin_id,
        name=name,
        description=description,
        capability_id=f"{plugin_id}.plan",
        capability_kind="runtime-replanner",
        capability_name=name,
        capability_description=description,
        category_id="runtime",
        category_label="运行期与在线换路",
        slot_id="runtime.coverage-planner",
        slot_label="区域覆盖轨迹",
        activation_mode="single",
        category_order=70,
        slot_order=35,
        plugin_order=order,
        hooks={"plan_coverage": handler},
        default_enabled=enabled,
        failure_mode="fail-closed",
        swap_policy="safe-hold",
        configuration_schema={
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        },
    )


def plugin_definitions() -> list[PluginDefinition]:
    return [
        _definition(
            plugin_id="runtime.coverage-lawnmower",
            name="往复覆盖",
            description="以可验证的平行往复航线覆盖矩形或多边形区域。",
            handler=_lawnmower,
            enabled=True,
            order=10,
        ),
        _definition(
            plugin_id="runtime.coverage-inward-spiral",
            name="内收螺旋覆盖",
            description="从边界向中心逐层内收，适合近方形开阔区域。",
            handler=_spiral,
            enabled=False,
            order=20,
        ),
    ]
