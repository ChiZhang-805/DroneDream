"""Metric indoor world model for depth/Lidar/VIO driven local autonomy.

This intentionally does not ask a language model to infer metric free space from
pixels.  Calibrated range observations update a bounded occupancy grid; the
planner then searches only observed free cells and preserves a vehicle-sized
clearance envelope.  A text-only model can consume :func:`text_map_summary` for
semantic decisions without becoming the final collision authority.
"""

from __future__ import annotations

import heapq
import math
from collections.abc import Iterable
from dataclasses import dataclass

from .contracts import MetricVoxelMapSnapshot, RangeRayObservation, Vector3

VoxelKey = tuple[int, int, int]
Point = tuple[float, float, float]


@dataclass
class _VoxelEvidence:
    log_odds: float = 0.0
    observations: int = 0
    latest_monotonic_seconds: float = 0.0


class MetricVoxelMap:
    """A bounded, conservative occupancy map with fail-closed unknown space."""

    def __init__(
        self,
        *,
        resolution_m: float,
        minimum_bound_m: Vector3,
        maximum_bound_m: Vector3,
        unknown_is_occupied: bool = True,
    ) -> None:
        if not 0.02 < resolution_m <= 5.0:
            raise ValueError("resolution_m must be in (0.02, 5.0]")
        minimum = _point(minimum_bound_m)
        maximum = _point(maximum_bound_m)
        if any(minimum[index] >= maximum[index] for index in range(3)):
            raise ValueError("metric map bounds must have positive volume")
        self.resolution_m = resolution_m
        self.minimum_bound_m = minimum_bound_m
        self.maximum_bound_m = maximum_bound_m
        self.unknown_is_occupied = unknown_is_occupied
        self._minimum = minimum
        self._maximum = maximum
        self._evidence: dict[VoxelKey, _VoxelEvidence] = {}
        self.observation_count = 0
        self.latest_observation_monotonic_seconds: float | None = None

    def _inside(self, point: Point) -> bool:
        return all(
            self._minimum[index] <= point[index] <= self._maximum[index]
            for index in range(3)
        )

    def key_for(self, point: Vector3 | Point) -> VoxelKey:
        raw = _point(point) if isinstance(point, Vector3) else point
        if not self._inside(raw):
            raise ValueError("point is outside metric map bounds")
        return tuple(
            int(math.floor((raw[index] - self._minimum[index]) / self.resolution_m))
            for index in range(3)
        )

    def center_for(self, key: VoxelKey) -> Vector3:
        values = tuple(
            self._minimum[index] + (key[index] + 0.5) * self.resolution_m
            for index in range(3)
        )
        return Vector3(x=values[0], y=values[1], z=values[2])

    def _update(
        self,
        key: VoxelKey,
        *,
        occupied: bool,
        confidence: float,
        observed_at: float,
    ) -> None:
        evidence = self._evidence.setdefault(key, _VoxelEvidence())
        bounded_confidence = max(0.05, min(0.99, confidence))
        measurement = math.log(bounded_confidence / (1.0 - bounded_confidence))
        if not occupied:
            measurement = -abs(measurement)
        evidence.log_odds = max(-6.0, min(6.0, evidence.log_odds + measurement))
        evidence.observations += 1
        evidence.latest_monotonic_seconds = max(
            evidence.latest_monotonic_seconds,
            observed_at,
        )

    def integrate_ray(self, observation: RangeRayObservation) -> None:
        origin = _point(observation.origin_m)
        endpoint = _point(observation.endpoint_m)
        if not self._inside(origin) or not self._inside(endpoint):
            raise ValueError("range ray must remain inside metric map bounds")
        distance = math.dist(origin, endpoint)
        sample_count = max(1, math.ceil(distance / (self.resolution_m * 0.45)))
        traversed: list[VoxelKey] = []
        for index in range(sample_count + 1):
            ratio = index / sample_count
            sample = tuple(
                origin[axis] + (endpoint[axis] - origin[axis]) * ratio for axis in range(3)
            )
            key = self.key_for(sample)
            if not traversed or traversed[-1] != key:
                traversed.append(key)
        free_keys = traversed[:-1] if observation.hit else traversed
        for key in free_keys:
            self._update(
                key,
                occupied=False,
                confidence=observation.confidence,
                observed_at=observation.observed_at_monotonic_seconds,
            )
        if observation.hit:
            self._update(
                traversed[-1],
                occupied=True,
                confidence=observation.confidence,
                observed_at=observation.observed_at_monotonic_seconds,
            )
        self.observation_count += 1
        self.latest_observation_monotonic_seconds = max(
            self.latest_observation_monotonic_seconds or 0.0,
            observation.observed_at_monotonic_seconds,
        )

    def integrate_rays(self, observations: Iterable[RangeRayObservation]) -> None:
        for observation in observations:
            self.integrate_ray(observation)

    def mark_box(
        self,
        *,
        minimum_m: Vector3,
        maximum_m: Vector3,
        occupied: bool,
        confidence: float = 0.99,
        observed_at_monotonic_seconds: float = 0.0,
    ) -> None:
        minimum = self.key_for(minimum_m)
        maximum = self.key_for(maximum_m)
        for x in range(minimum[0], maximum[0] + 1):
            for y in range(minimum[1], maximum[1] + 1):
                for z in range(minimum[2], maximum[2] + 1):
                    self._update(
                        (x, y, z),
                        occupied=occupied,
                        confidence=confidence,
                        observed_at=observed_at_monotonic_seconds,
                    )
        self.observation_count += 1
        self.latest_observation_monotonic_seconds = max(
            self.latest_observation_monotonic_seconds or 0.0,
            observed_at_monotonic_seconds,
        )

    def occupancy_probability(self, key: VoxelKey) -> float | None:
        evidence = self._evidence.get(key)
        if evidence is None:
            return None
        return 1.0 / (1.0 + math.exp(-evidence.log_odds))

    def is_occupied(self, key: VoxelKey) -> bool:
        probability = self.occupancy_probability(key)
        if probability is None:
            return self.unknown_is_occupied
        return probability >= 0.65

    def is_observed_free(self, key: VoxelKey) -> bool:
        probability = self.occupancy_probability(key)
        return probability is not None and probability <= 0.35

    def _clearance_ok(self, key: VoxelKey, required_clearance_m: float) -> bool:
        if self.is_occupied(key):
            return False
        if required_clearance_m <= 0.0:
            return True
        radius = math.ceil(required_clearance_m / self.resolution_m) + 1
        center = _point(self.center_for(key))
        voxel_radius = math.sqrt(3.0) * self.resolution_m / 2.0
        for x in range(key[0] - radius, key[0] + radius + 1):
            for y in range(key[1] - radius, key[1] + radius + 1):
                for z in range(key[2] - radius, key[2] + radius + 1):
                    candidate = (x, y, z)
                    probability = self.occupancy_probability(candidate)
                    if probability is None or probability < 0.65:
                        continue
                    occupied_center = _point(self.center_for(candidate))
                    if math.dist(center, occupied_center) - voxel_radius < required_clearance_m:
                        return False
        return True

    def plan_path(
        self,
        *,
        start_m: Vector3,
        goal_m: Vector3,
        required_clearance_m: float,
        maximum_expansions: int = 200_000,
    ) -> list[Vector3]:
        """Plan through observed free space using clearance-aware 3-D A*."""

        start = self.key_for(start_m)
        goal = self.key_for(goal_m)
        if not self._clearance_ok(start, required_clearance_m):
            raise ValueError("start is not in observed collision-free space")
        if not self._clearance_ok(goal, required_clearance_m):
            raise ValueError("goal is not in observed collision-free space")
        frontier: list[tuple[float, float, VoxelKey]] = [(0.0, 0.0, start)]
        came_from: dict[VoxelKey, VoxelKey] = {}
        cost: dict[VoxelKey, float] = {start: 0.0}
        visited: set[VoxelKey] = set()
        offsets = [
            (x, y, z)
            for x in (-1, 0, 1)
            for y in (-1, 0, 1)
            for z in (-1, 0, 1)
            if (x, y, z) != (0, 0, 0)
        ]
        while frontier and len(visited) < maximum_expansions:
            _estimate, current_cost, current = heapq.heappop(frontier)
            if current in visited:
                continue
            visited.add(current)
            if current == goal:
                keys = [goal]
                while keys[-1] != start:
                    keys.append(came_from[keys[-1]])
                keys.reverse()
                return [start_m, *[self.center_for(key) for key in keys[1:-1]], goal_m]
            for offset in offsets:
                neighbor = tuple(current[index] + offset[index] for index in range(3))
                neighbor_center = _point(self.center_for(neighbor))
                if not self._inside(neighbor_center):
                    continue
                if not self._clearance_ok(neighbor, required_clearance_m):
                    continue
                step = self.resolution_m * math.sqrt(sum(value * value for value in offset))
                new_cost = current_cost + step
                if new_cost >= cost.get(neighbor, math.inf):
                    continue
                cost[neighbor] = new_cost
                came_from[neighbor] = current
                heuristic = math.dist(neighbor_center, _point(goal_m))
                heapq.heappush(frontier, (new_cost + heuristic, new_cost, neighbor))
        raise ValueError("no observed collision-free path exists inside the search bound")

    def frontier_centers(self, *, limit: int = 256) -> list[Vector3]:
        """Return observed-free cells adjacent to unknown space for bounded exploration."""

        frontiers: list[Vector3] = []
        for key in sorted(self._evidence):
            if not self.is_observed_free(key):
                continue
            if any(
                (key[0] + dx, key[1] + dy, key[2] + dz) not in self._evidence
                for dx, dy, dz in (
                    (-1, 0, 0),
                    (1, 0, 0),
                    (0, -1, 0),
                    (0, 1, 0),
                    (0, 0, -1),
                    (0, 0, 1),
                )
            ):
                frontiers.append(self.center_for(key))
                if len(frontiers) >= limit:
                    break
        return frontiers

    def snapshot(self) -> MetricVoxelMapSnapshot:
        occupied = [key for key in sorted(self._evidence) if self.is_occupied(key)]
        free = [key for key in sorted(self._evidence) if self.is_observed_free(key)]
        return MetricVoxelMapSnapshot(
            resolution_m=self.resolution_m,
            minimum_bound_m=self.minimum_bound_m,
            maximum_bound_m=self.maximum_bound_m,
            occupied_voxels=occupied,
            free_voxels=free,
            observation_count=self.observation_count,
            latest_observation_monotonic_seconds=self.latest_observation_monotonic_seconds,
        )

    def text_map_summary(self) -> dict[str, object]:
        """Bounded numeric context suitable for a text-only semantic planner."""

        snapshot = self.snapshot()
        frontiers = self.frontier_centers(limit=32)
        return {
            "source_of_truth": "metric-range-observations-not-rendered-image",
            "resolution_m": snapshot.resolution_m,
            "bounds_m": {
                "minimum": snapshot.minimum_bound_m.model_dump(mode="json"),
                "maximum": snapshot.maximum_bound_m.model_dump(mode="json"),
            },
            "observed_free_voxel_count": len(snapshot.free_voxels),
            "occupied_voxel_count": len(snapshot.occupied_voxels),
            "unknown_space_policy": "blocked-until-observed",
            "frontier_centers_m": [point.model_dump(mode="json") for point in frontiers],
            "model_authority": (
                "select semantic goal/frontier only; metric path and actuator commands require "
                "deterministic safety approval"
            ),
        }


def _point(value: Vector3) -> Point:
    return value.x, value.y, value.z
