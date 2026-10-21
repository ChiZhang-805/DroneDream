"""Evidence-bound topology checks for newly imported maps.

The module deliberately separates durable map facts from optional online hints.
Local geometry, user-supplied semantics, licensed open data, operator review and
qualification flights may become durable evidence.  Google Maps responses remain
short-lived advisory material and cannot silently rewrite or qualify a Map Pack.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
from typing import Literal, Protocol

from pydantic import Field, model_validator

from app.autonomy.models import StrictModel, Vector3

GOOGLE_EVIDENCE_SOURCES = {"google-places", "google-routes", "google-roads"}
MAX_GOOGLE_CACHE_AGE = timedelta(days=30)
ENDPOINT_TOLERANCE_M = 0.50
MIN_CENTERLINE_SEGMENT_M = 0.05
MIN_VERIFIED_CONFIDENCE = 0.80

MapEvidenceSource = Literal[
    "user-upload",
    "scene-geometry",
    "openstreetmap",
    "local-vision",
    "gps-trace",
    "human-review",
    "qualification-flight",
    "google-places",
    "google-routes",
    "google-roads",
]
EvidenceAuthority = Literal["source", "operator", "observed", "advisory"]
EvidenceStorage = Literal["durable", "ephemeral"]
EvidenceClaim = Literal[
    "building-identity",
    "building-footprint",
    "entrance-location",
    "handoff-location",
    "route-centerline",
    "route-traversability",
    "coordinate-registration",
    "map-boundary",
    "obstacle-footprint",
]
MapPointKind = Literal[
    "building",
    "entrance",
    "handoff",
    "junction",
    "launch",
    "emergency",
]
MapFactStatus = Literal["unknown", "candidate", "verified"]
RouteDirection = Literal["bidirectional", "forward"]
RouteKind = Literal[
    "road",
    "path",
    "courtyard",
    "parking-aisle",
    "forest-trail",
    "indoor-corridor",
]
MapAnalysisMode = Literal["local", "balanced", "deep"]


class MapEvidenceRecord(StrictModel):
    evidence_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]*$", min_length=3, max_length=160)
    source: MapEvidenceSource
    authority: EvidenceAuthority
    storage: EvidenceStorage
    confidence: float = Field(ge=0.0, le=1.0)
    claims: list[EvidenceClaim] = Field(min_length=1, max_length=16)
    observed_at: datetime
    expires_at: datetime | None = None
    reference: str | None = Field(default=None, max_length=1000)

    @model_validator(mode="after")
    def validate_storage_policy(self) -> MapEvidenceRecord:
        if self.observed_at.utcoffset() is None:
            raise ValueError("observed_at must include a timezone")
        if self.expires_at is not None and self.expires_at.utcoffset() is None:
            raise ValueError("expires_at must include a timezone")
        if self.storage == "ephemeral" and self.expires_at is None:
            raise ValueError("ephemeral evidence requires expires_at")
        if self.expires_at is not None and self.expires_at <= self.observed_at:
            raise ValueError("expires_at must be after observed_at")
        if self.source in GOOGLE_EVIDENCE_SOURCES:
            if self.authority != "advisory" or self.storage != "ephemeral":
                raise ValueError("Google Maps evidence must remain ephemeral and advisory")
            if self.expires_at is None or self.expires_at - self.observed_at > MAX_GOOGLE_CACHE_AGE:
                raise ValueError("Google Maps evidence may be cached for at most 30 days")
        return self


class GeographicCoordinate(StrictModel):
    latitude: float = Field(ge=-90.0, le=90.0)
    longitude: float = Field(ge=-180.0, le=180.0)
    altitude_m: float | None = Field(default=None, ge=-20_000.0, le=100_000.0)


class MapFeaturePoint(StrictModel):
    point_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]*$", min_length=2, max_length=160)
    kind: MapPointKind
    position_m: Vector3
    geographic_position: GeographicCoordinate | None = None
    label: str = Field(min_length=1, max_length=240)
    building_id: str | None = Field(
        default=None,
        pattern=r"^[a-z0-9][a-z0-9._-]*$",
        max_length=160,
    )
    status: MapFactStatus
    evidence_ids: list[str] = Field(default_factory=list, max_length=32)
    external_place_ids: dict[str, str] = Field(default_factory=dict, max_length=8)

    @model_validator(mode="after")
    def validate_building_binding(self) -> MapFeaturePoint:
        if self.kind in {"entrance", "handoff"} and self.building_id is None:
            raise ValueError(f"{self.kind} points require building_id")
        if self.kind == "building" and self.building_id is not None:
            raise ValueError("building points cannot bind to another building")
        return self


class MapRouteEdge(StrictModel):
    route_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]*$", min_length=2, max_length=160)
    start_point_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]*$", max_length=160)
    end_point_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]*$", max_length=160)
    centerline_m: list[Vector3] = Field(min_length=2, max_length=10_000)
    direction: RouteDirection = "bidirectional"
    kind: RouteKind
    status: MapFactStatus
    evidence_ids: list[str] = Field(default_factory=list, max_length=32)


class MapObstacle(StrictModel):
    obstacle_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]*$", min_length=2, max_length=160)
    kind: Literal["building", "wall", "vegetation", "restricted"]
    footprint_m: list[Vector3] = Field(min_length=3, max_length=20_000)
    status: MapFactStatus
    evidence_ids: list[str] = Field(default_factory=list, max_length=32)


class MapEvidenceBundle(StrictModel):
    schema_version: Literal["dronedream.autonomy.map-evidence.v1"] = (
        "dronedream.autonomy.map-evidence.v1"
    )
    map_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]*$", min_length=2, max_length=160)
    map_version: int = Field(ge=1, le=1_000_000)
    coordinate_frame: Literal["ENU", "NED", "WGS84", "building-local"]
    georeferenced: bool
    boundary_m: list[Vector3] = Field(min_length=3, max_length=20_000)
    points: list[MapFeaturePoint] = Field(max_length=100_000)
    routes: list[MapRouteEdge] = Field(max_length=200_000)
    obstacles: list[MapObstacle] = Field(default_factory=list, max_length=100_000)
    evidence: list[MapEvidenceRecord] = Field(default_factory=list, max_length=100_000)


class MapIntelligenceIssue(StrictModel):
    code: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]*$", max_length=160)
    severity: Literal["info", "warning", "error"]
    subject_ids: list[str] = Field(default_factory=list, max_length=64)
    message: str = Field(min_length=1, max_length=1000)


class MapIntelligenceReceipt(StrictModel):
    schema_version: Literal["dronedream.autonomy.map-intelligence-receipt.v1"] = (
        "dronedream.autonomy.map-intelligence-receipt.v1"
    )
    map_id: str
    map_version: int
    status: Literal["blocked", "ready_for_qualification"]
    durable_graph_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    issue_count: int = Field(ge=0)
    component_count: int = Field(ge=0)
    building_count: int = Field(ge=0)
    route_count: int = Field(ge=0)
    issues: list[MapIntelligenceIssue]
    created_at: datetime


class MapEnrichmentPolicy(StrictModel):
    mode: MapAnalysisMode = "local"
    explicit_online_enrichment: bool = False
    maximum_paid_calls: int = Field(default=0, ge=0, le=10_000)

    @model_validator(mode="after")
    def validate_paid_mode(self) -> MapEnrichmentPolicy:
        if self.maximum_paid_calls and not self.explicit_online_enrichment:
            raise ValueError("paid calls require explicit_online_enrichment")
        return self


class ExternalVerificationRequest(StrictModel):
    provider_id: Literal["google-maps"] = "google-maps"
    operation: Literal[
        "places.resolve-entrances",
        "routes.compare-path",
        "routes.compare-components",
        "roads.snap-trace",
    ]
    subject_ids: list[str] = Field(min_length=1, max_length=64)
    rationale: str = Field(min_length=1, max_length=500)
    estimated_calls: int = Field(default=1, ge=1, le=100)


class ExternalVerificationHint(StrictModel):
    provider_id: Literal["google-maps"] = "google-maps"
    operation: str = Field(min_length=1, max_length=120)
    subject_ids: list[str] = Field(min_length=1, max_length=64)
    verdict: Literal["supports", "contradicts", "ambiguous"]
    confidence: float = Field(ge=0.0, le=1.0)
    summary: str = Field(min_length=1, max_length=1000)
    observed_at: datetime
    expires_at: datetime

    @model_validator(mode="after")
    def validate_ephemeral_window(self) -> ExternalVerificationHint:
        if self.observed_at.utcoffset() is None or self.expires_at.utcoffset() is None:
            raise ValueError("online hint timestamps must include a timezone")
        if self.expires_at <= self.observed_at:
            raise ValueError("expires_at must be after observed_at")
        if self.expires_at - self.observed_at > MAX_GOOGLE_CACHE_AGE:
            raise ValueError("Google Maps hints may be cached for at most 30 days")
        return self


class MapIntelligenceResult(StrictModel):
    local_receipt: MapIntelligenceReceipt
    verification_plan: list[ExternalVerificationRequest]
    advisory_hints: list[ExternalVerificationHint]
    online_status: Literal["skipped", "succeeded", "fallback"]
    fallback_reason: str | None = Field(default=None, max_length=500)


class MapReasoningPacket(StrictModel):
    """Bounded context for a model that may propose, but not certify, map corrections."""

    schema_version: Literal["dronedream.autonomy.map-reasoning-packet.v1"] = (
        "dronedream.autonomy.map-reasoning-packet.v1"
    )
    map_id: str
    map_version: int
    durable_graph_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    decision_authority: Literal["advisory_only"] = "advisory_only"
    unresolved_issues: list[MapIntelligenceIssue]
    online_hints: list[ExternalVerificationHint]
    required_constraints: list[
        Literal[
            "do-not-invent-entrances",
            "do-not-promote-online-hints",
            "preserve-coordinate-registration",
            "require-connected-obstacle-free-graph",
        ]
    ]


class ExternalMapVerifier(Protocol):
    provider_id: str

    def verify(
        self,
        bundle: MapEvidenceBundle,
        requests: list[ExternalVerificationRequest],
    ) -> list[ExternalVerificationHint]: ...


def _distance(a: Vector3, b: Vector3) -> float:
    return math.dist((a.x, a.y, a.z), (b.x, b.y, b.z))


def _orientation(a: Vector3, b: Vector3, c: Vector3) -> float:
    return (b.x - a.x) * (c.y - a.y) - (b.y - a.y) * (c.x - a.x)


def _properly_intersects(a: Vector3, b: Vector3, c: Vector3, d: Vector3) -> bool:
    """Return true only for an interior crossing, allowing shared boundary endpoints."""
    ab_c = _orientation(a, b, c)
    ab_d = _orientation(a, b, d)
    cd_a = _orientation(c, d, a)
    cd_b = _orientation(c, d, b)
    epsilon = 1e-9
    return (
        ab_c * ab_d < -epsilon
        and cd_a * cd_b < -epsilon
    )


def _inside_polygon(point: Vector3, polygon: list[Vector3]) -> bool:
    inside = False
    previous = polygon[-1]
    for current in polygon:
        crosses_y = (current.y > point.y) != (previous.y > point.y)
        if crosses_y:
            crossing_x = (
                (previous.x - current.x)
                * (point.y - current.y)
                / (previous.y - current.y)
                + current.x
            )
            if point.x < crossing_x:
                inside = not inside
        previous = current
    return inside


def _on_polygon_boundary(point: Vector3, polygon: list[Vector3]) -> bool:
    tolerance = 1e-7
    edges = zip(polygon, polygon[1:] + polygon[:1], strict=True)
    for start, end in edges:
        if abs(_orientation(start, end, point)) > tolerance:
            continue
        if (
            min(start.x, end.x) - tolerance <= point.x <= max(start.x, end.x) + tolerance
            and min(start.y, end.y) - tolerance <= point.y <= max(start.y, end.y) + tolerance
        ):
            return True
    return False


def _inside_or_on_polygon(point: Vector3, polygon: list[Vector3]) -> bool:
    return _inside_polygon(point, polygon) or _on_polygon_boundary(point, polygon)


def _point_segment_distance(point: Vector3, start: Vector3, end: Vector3) -> float:
    delta = (end.x - start.x, end.y - start.y, end.z - start.z)
    length_squared = sum(value * value for value in delta)
    if length_squared == 0.0:
        return _distance(point, start)
    projection = (
        (point.x - start.x) * delta[0]
        + (point.y - start.y) * delta[1]
        + (point.z - start.z) * delta[2]
    ) / length_squared
    projection = min(1.0, max(0.0, projection))
    nearest = Vector3(
        x=start.x + projection * delta[0],
        y=start.y + projection * delta[1],
        z=start.z + projection * delta[2],
    )
    return _distance(point, nearest)


def _polylines_overlap(left: MapRouteEdge, right: MapRouteEdge) -> bool:
    tolerance_m = 1.0

    def covered(points: list[Vector3], line: list[Vector3]) -> bool:
        segments = list(zip(line, line[1:], strict=False))
        return all(
            min(_point_segment_distance(point, start, end) for start, end in segments)
            <= tolerance_m
            for point in points
        )

    return covered(left.centerline_m, right.centerline_m) and covered(
        right.centerline_m,
        left.centerline_m,
    )


def _route_crosses_obstacle(route: MapRouteEdge, obstacle: MapObstacle) -> bool:
    polygon_edges = list(
        zip(
            obstacle.footprint_m,
            obstacle.footprint_m[1:] + obstacle.footprint_m[:1],
            strict=True,
        )
    )
    for start, end in zip(route.centerline_m, route.centerline_m[1:], strict=False):
        midpoint = Vector3(
            x=(start.x + end.x) / 2,
            y=(start.y + end.y) / 2,
            z=(start.z + end.z) / 2,
        )
        if _inside_polygon(midpoint, obstacle.footprint_m):
            return True
        if any(_properly_intersects(start, end, a, b) for a, b in polygon_edges):
            return True
    return False


def _route_self_intersects(route: MapRouteEdge) -> bool:
    segments = list(zip(route.centerline_m, route.centerline_m[1:], strict=False))
    for index, (a, b) in enumerate(segments):
        for other_index in range(index + 2, len(segments)):
            if other_index == index + 1:
                continue
            c, d = segments[other_index]
            if _properly_intersects(a, b, c, d):
                return True
    return False


def _connected_components(
    points: dict[str, MapFeaturePoint],
    routes: list[MapRouteEdge],
) -> list[set[str]]:
    adjacency: dict[str, set[str]] = defaultdict(set)
    for route in routes:
        if route.start_point_id not in points or route.end_point_id not in points:
            continue
        adjacency[route.start_point_id].add(route.end_point_id)
        adjacency[route.end_point_id].add(route.start_point_id)
    unvisited = set(adjacency)
    components: list[set[str]] = []
    while unvisited:
        root = min(unvisited)
        component = {root}
        queue = deque([root])
        unvisited.remove(root)
        while queue:
            for neighbour in adjacency[queue.popleft()]:
                if neighbour in unvisited:
                    unvisited.remove(neighbour)
                    component.add(neighbour)
                    queue.append(neighbour)
        components.append(component)
    return components


def _durable_graph_digest(bundle: MapEvidenceBundle) -> str:
    durable_ids = {item.evidence_id for item in bundle.evidence if item.storage == "durable"}
    projection = {
        "map_id": bundle.map_id,
        "map_version": bundle.map_version,
        "coordinate_frame": bundle.coordinate_frame,
        "georeferenced": bundle.georeferenced,
        "boundary_m": [item.model_dump(mode="json") for item in bundle.boundary_m],
        "points": [
            item.model_dump(mode="json")
            | {"evidence_ids": sorted(set(item.evidence_ids) & durable_ids)}
            for item in sorted(bundle.points, key=lambda value: value.point_id)
        ],
        "routes": [
            item.model_dump(mode="json")
            | {"evidence_ids": sorted(set(item.evidence_ids) & durable_ids)}
            for item in sorted(bundle.routes, key=lambda value: value.route_id)
        ],
        "obstacles": [
            item.model_dump(mode="json")
            for item in sorted(bundle.obstacles, key=lambda value: value.obstacle_id)
        ],
        "evidence": [
            item.model_dump(mode="json")
            for item in sorted(bundle.evidence, key=lambda value: value.evidence_id)
            if item.storage == "durable"
        ],
    }
    encoded = json.dumps(projection, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def validate_map_evidence(bundle: MapEvidenceBundle) -> MapIntelligenceReceipt:
    """Validate evidence, endpoint binding, connectivity and obstacle avoidance."""
    issues: list[MapIntelligenceIssue] = []
    evidence = {item.evidence_id: item for item in bundle.evidence}
    points = {item.point_id: item for item in bundle.points}
    obstacles = {item.obstacle_id: item for item in bundle.obstacles}

    registration_evidence = [
        item
        for item in bundle.evidence
        if item.storage == "durable" and "coordinate-registration" in item.claims
    ]
    if bundle.georeferenced and not registration_evidence:
        issues.append(
            MapIntelligenceIssue(
                code="map.georeference.evidence-missing",
                severity="error",
                subject_ids=[bundle.map_id],
                message="A georeferenced map requires durable coordinate-registration evidence.",
            )
        )
    boundary_evidence = [
        item
        for item in bundle.evidence
        if item.storage == "durable" and "map-boundary" in item.claims
    ]
    if not boundary_evidence:
        issues.append(
            MapIntelligenceIssue(
                code="map.boundary.evidence-missing",
                severity="error",
                subject_ids=[bundle.map_id],
                message="The map boundary requires durable evidence.",
            )
        )

    for values, label in (
        (bundle.evidence, "evidence_id"),
        (bundle.points, "point_id"),
        (bundle.routes, "route_id"),
        (bundle.obstacles, "obstacle_id"),
    ):
        identities = [getattr(item, label) for item in values]
        if len(identities) != len(set(identities)):
            issues.append(
                MapIntelligenceIssue(
                    code=f"map.{label}.duplicate",
                    severity="error",
                    subject_ids=[],
                    message=f"{label} values must be unique.",
                )
            )

    for point in bundle.points:
        if not _inside_or_on_polygon(point.position_m, bundle.boundary_m):
            issues.append(
                MapIntelligenceIssue(
                    code="map.point.outside-boundary",
                    severity="error",
                    subject_ids=[point.point_id],
                    message="Map points must remain inside the admitted map boundary.",
                )
            )
        unknown_evidence = sorted(set(point.evidence_ids) - set(evidence))
        if unknown_evidence:
            issues.append(
                MapIntelligenceIssue(
                    code="map.point.evidence-missing",
                    severity="error",
                    subject_ids=[point.point_id, *unknown_evidence],
                    message="The point references evidence that is not present in the bundle.",
                )
            )
        if point.building_id is not None:
            building = points.get(point.building_id)
            if building is None or building.kind != "building":
                issues.append(
                    MapIntelligenceIssue(
                        code="map.point.building-binding-invalid",
                        severity="error",
                        subject_ids=[point.point_id, point.building_id],
                        message="An entrance or handoff must bind to a declared building point.",
                    )
                )
        durable_evidence = [
            evidence[identity]
            for identity in point.evidence_ids
            if identity in evidence and evidence[identity].storage == "durable"
        ]
        if point.status == "verified" and not durable_evidence:
            issues.append(
                MapIntelligenceIssue(
                    code="map.point.verified-without-durable-evidence",
                    severity="error",
                    subject_ids=[point.point_id],
                    message="A verified point needs at least one durable source or observation.",
                )
            )
        required_claim = {
            "building": "building-identity",
            "entrance": "entrance-location",
            "handoff": "handoff-location",
            "junction": "route-centerline",
            "launch": "route-traversability",
            "emergency": "route-traversability",
        }[point.kind]
        durable_claims = {claim for item in durable_evidence for claim in item.claims}
        if point.status == "verified" and required_claim not in durable_claims:
            issues.append(
                MapIntelligenceIssue(
                    code="map.point.required-evidence-claim-missing",
                    severity="error",
                    subject_ids=[point.point_id],
                    message=f"A verified {point.kind} needs durable {required_claim} evidence.",
                )
            )
        if point.status == "verified" and not any(
            item.confidence >= MIN_VERIFIED_CONFIDENCE and required_claim in item.claims
            for item in durable_evidence
        ):
            issues.append(
                MapIntelligenceIssue(
                    code="map.point.verified-confidence-insufficient",
                    severity="error",
                    subject_ids=[point.point_id],
                    message="Verified point evidence must meet the minimum confidence threshold.",
                )
            )
        if point.status != "verified":
            issues.append(
                MapIntelligenceIssue(
                    code="map.point.unresolved",
                    severity="error",
                    subject_ids=[point.point_id],
                    message=(
                        "Unknown and candidate points require durable review before qualification."
                    ),
                )
            )

    for obstacle in bundle.obstacles:
        unknown_evidence = sorted(set(obstacle.evidence_ids) - set(evidence))
        durable_evidence = [
            evidence[identity]
            for identity in obstacle.evidence_ids
            if identity in evidence and evidence[identity].storage == "durable"
        ]
        durable_claims = {claim for item in durable_evidence for claim in item.claims}
        if unknown_evidence:
            issues.append(
                MapIntelligenceIssue(
                    code="map.obstacle.evidence-missing",
                    severity="error",
                    subject_ids=[obstacle.obstacle_id, *unknown_evidence],
                    message="The obstacle references evidence that is not present in the bundle.",
                )
            )
        if obstacle.status != "verified" or "obstacle-footprint" not in durable_claims:
            issues.append(
                MapIntelligenceIssue(
                    code="map.obstacle.unresolved",
                    severity="error",
                    subject_ids=[obstacle.obstacle_id],
                    message="Obstacle footprints require durable evidence before qualification.",
                )
            )
        if obstacle.status == "verified" and not any(
            item.confidence >= MIN_VERIFIED_CONFIDENCE
            and "obstacle-footprint" in item.claims
            for item in durable_evidence
        ):
            issues.append(
                MapIntelligenceIssue(
                    code="map.obstacle.verified-confidence-insufficient",
                    severity="error",
                    subject_ids=[obstacle.obstacle_id],
                    message="Verified obstacle evidence must meet the confidence threshold.",
                )
            )

    attached_buildings = {
        point.building_id
        for point in bundle.points
        if point.kind in {"entrance", "handoff"} and point.building_id is not None
    }
    for building in (point for point in bundle.points if point.kind == "building"):
        if building.point_id not in attached_buildings:
            issues.append(
                MapIntelligenceIssue(
                    code="map.building.access-point-missing",
                    severity="error",
                    subject_ids=[building.point_id],
                    message="Every building needs a sourced entrance or outdoor handoff candidate.",
                )
            )

    incident_counts: dict[str, int] = defaultdict(int)
    route_pairs: dict[tuple[str, str], list[MapRouteEdge]] = defaultdict(list)
    for route in bundle.routes:
        if any(
            not _inside_or_on_polygon(item, bundle.boundary_m)
            for item in route.centerline_m
        ):
            issues.append(
                MapIntelligenceIssue(
                    code="map.route.outside-boundary",
                    severity="error",
                    subject_ids=[route.route_id],
                    message="Route geometry must remain inside the admitted map boundary.",
                )
            )
        start = points.get(route.start_point_id)
        end = points.get(route.end_point_id)
        if start is None or end is None:
            issues.append(
                MapIntelligenceIssue(
                    code="map.route.endpoint-missing",
                    severity="error",
                    subject_ids=[route.route_id, route.start_point_id, route.end_point_id],
                    message="Every route endpoint must reference a declared point.",
                )
            )
            continue
        if start.point_id == end.point_id:
            issues.append(
                MapIntelligenceIssue(
                    code="map.route.same-endpoint",
                    severity="error",
                    subject_ids=[route.route_id, start.point_id],
                    message="A route edge must connect two different points.",
                )
            )
        incident_counts[start.point_id] += 1
        incident_counts[end.point_id] += 1
        if start.kind == "building" or end.kind == "building":
            issues.append(
                MapIntelligenceIssue(
                    code="map.route.building-centre-endpoint",
                    severity="error",
                    subject_ids=[route.route_id],
                    message=(
                        "Routes must terminate at entrances, handoffs or junctions, "
                        "not building centres."
                    ),
                )
            )
        if _distance(route.centerline_m[0], start.position_m) > ENDPOINT_TOLERANCE_M or _distance(
            route.centerline_m[-1], end.position_m
        ) > ENDPOINT_TOLERANCE_M:
            issues.append(
                MapIntelligenceIssue(
                    code="map.route.endpoint-coordinate-mismatch",
                    severity="error",
                    subject_ids=[route.route_id, start.point_id, end.point_id],
                    message=(
                        "Route coordinates must meet the coordinates of both "
                        "referenced endpoints."
                    ),
                )
            )
        if any(
            _distance(a, b) < MIN_CENTERLINE_SEGMENT_M
            for a, b in zip(route.centerline_m, route.centerline_m[1:], strict=False)
        ):
            issues.append(
                MapIntelligenceIssue(
                    code="map.route.centerline-jitter",
                    severity="error",
                    subject_ids=[route.route_id],
                    message=(
                        "Route centerlines cannot contain duplicate or sub-5 cm "
                        "jitter segments."
                    ),
                )
            )
        if _route_self_intersects(route):
            issues.append(
                MapIntelligenceIssue(
                    code="map.route.centerline-self-intersection",
                    severity="error",
                    subject_ids=[route.route_id],
                    message="A single route centerline cannot loop across itself.",
                )
            )
        unknown_evidence = sorted(set(route.evidence_ids) - set(evidence))
        if unknown_evidence:
            issues.append(
                MapIntelligenceIssue(
                    code="map.route.evidence-missing",
                    severity="error",
                    subject_ids=[route.route_id, *unknown_evidence],
                    message="The route references evidence that is not present in the bundle.",
                )
            )
        durable_evidence = [
            evidence[identity]
            for identity in route.evidence_ids
            if identity in evidence and evidence[identity].storage == "durable"
        ]
        if route.status == "verified" and not durable_evidence:
            issues.append(
                MapIntelligenceIssue(
                    code="map.route.verified-without-durable-evidence",
                    severity="error",
                    subject_ids=[route.route_id],
                    message="A verified route needs durable evidence independent of online hints.",
                )
            )
        durable_claims = {claim for item in durable_evidence for claim in item.claims}
        required_route_claims = {"route-centerline", "route-traversability"}
        if route.status == "verified" and not required_route_claims.issubset(durable_claims):
            issues.append(
                MapIntelligenceIssue(
                    code="map.route.required-evidence-claims-missing",
                    severity="error",
                    subject_ids=[route.route_id],
                    message=(
                        "A verified route needs durable centerline and traversability evidence."
                    ),
                )
            )
        if route.status == "verified" and any(
            not any(
                item.confidence >= MIN_VERIFIED_CONFIDENCE and claim in item.claims
                for item in durable_evidence
            )
            for claim in required_route_claims
        ):
            issues.append(
                MapIntelligenceIssue(
                    code="map.route.verified-confidence-insufficient",
                    severity="error",
                    subject_ids=[route.route_id],
                    message="Verified route evidence must meet the confidence threshold.",
                )
            )
        if route.status != "verified":
            issues.append(
                MapIntelligenceIssue(
                    code="map.route.unresolved",
                    severity="error",
                    subject_ids=[route.route_id],
                    message=(
                        "Unknown and candidate routes require durable review before qualification."
                    ),
                )
            )
        if route.start_point_id <= route.end_point_id:
            pair = (route.start_point_id, route.end_point_id)
        else:
            pair = (route.end_point_id, route.start_point_id)
        overlapping = [
            previous
            for previous in route_pairs[pair]
            if _polylines_overlap(previous, route)
        ]
        if overlapping:
            issues.append(
                MapIntelligenceIssue(
                    code="map.route.duplicate-edge",
                    severity="error",
                    subject_ids=[overlapping[0].route_id, route.route_id],
                    message=(
                        "A bidirectional road is one topology edge, even when "
                        "rendered as two lanes."
                    ),
                )
            )
        route_pairs[pair].append(route)
        for obstacle in obstacles.values():
            if _route_crosses_obstacle(route, obstacle):
                issues.append(
                    MapIntelligenceIssue(
                        code="map.route.obstacle-crossing",
                        severity="error",
                        subject_ids=[route.route_id, obstacle.obstacle_id],
                        message="A route centerline crosses a declared obstacle footprint.",
                    )
                )

    for point in bundle.points:
        if point.kind in {"entrance", "handoff", "junction", "launch", "emergency"} and not (
            incident_counts[point.point_id]
        ):
            issues.append(
                MapIntelligenceIssue(
                    code="map.point.route-disconnected",
                    severity="error",
                    subject_ids=[point.point_id],
                    message="Every usable route point must connect to the navigation graph.",
                )
            )

    components = _connected_components(points, bundle.routes)
    if len(components) > 1:
        issues.append(
            MapIntelligenceIssue(
                code="map.route.graph-disconnected",
                severity="error",
                subject_ids=[min(component) for component in components],
                message="All admitted route edges must form one connected navigation graph.",
            )
        )
    if not bundle.routes:
        issues.append(
            MapIntelligenceIssue(
                code="map.route.graph-empty",
                severity="error",
                subject_ids=[],
                message="A flight-ready map requires a navigation graph.",
            )
        )

    blocked = any(issue.severity == "error" for issue in issues)
    return MapIntelligenceReceipt(
        map_id=bundle.map_id,
        map_version=bundle.map_version,
        status="blocked" if blocked else "ready_for_qualification",
        durable_graph_sha256=_durable_graph_digest(bundle),
        issue_count=len(issues),
        component_count=len(components),
        building_count=sum(point.kind == "building" for point in bundle.points),
        route_count=len(bundle.routes),
        issues=issues,
        created_at=datetime.now(timezone.utc),
    )


def build_google_verification_plan(
    bundle: MapEvidenceBundle,
    policy: MapEnrichmentPolicy,
) -> list[ExternalVerificationRequest]:
    """Spend a bounded online budget only on unresolved, high-value questions."""
    if (
        policy.mode == "local"
        or not policy.explicit_online_enrichment
        or policy.maximum_paid_calls == 0
        or not bundle.georeferenced
    ):
        return []

    requests: list[ExternalVerificationRequest] = []
    access_points: dict[str, list[MapFeaturePoint]] = defaultdict(list)
    for point in bundle.points:
        if point.building_id is not None and point.kind in {"entrance", "handoff"}:
            access_points[point.building_id].append(point)
    for building in (point for point in bundle.points if point.kind == "building"):
        unresolved = not access_points[building.point_id] or any(
            point.status != "verified" for point in access_points[building.point_id]
        )
        can_locate = building.geographic_position is not None or "google" in (
            building.external_place_ids
        )
        if unresolved and can_locate:
            requests.append(
                ExternalVerificationRequest(
                    operation="places.resolve-entrances",
                    subject_ids=[building.point_id],
                    rationale=(
                        "Check unresolved building entrances and road-side "
                        "navigation points."
                    ),
                )
            )

    components = _connected_components(
        {item.point_id: item for item in bundle.points},
        bundle.routes,
    )
    if len(components) > 1:
        ordered = sorted(components, key=lambda item: min(item))
        for left, right in zip(ordered, ordered[1:], strict=False):
            left_id = min(left)
            right_id = min(right)
            left_point = next(item for item in bundle.points if item.point_id == left_id)
            right_point = next(item for item in bundle.points if item.point_id == right_id)
            if (
                left_point.geographic_position is None
                or right_point.geographic_position is None
            ):
                continue
            requests.append(
                ExternalVerificationRequest(
                    operation="routes.compare-components",
                    subject_ids=[left_id, right_id],
                    rationale=(
                        "Check whether two locally disconnected route components "
                        "have a real link."
                    ),
                )
            )

    evidence = {item.evidence_id: item for item in bundle.evidence}
    points = {item.point_id: item for item in bundle.points}
    for route in bundle.routes:
        route_sources = {
            evidence[identity].source for identity in route.evidence_ids if identity in evidence
        }
        start = points.get(route.start_point_id)
        end = points.get(route.end_point_id)
        if (
            start is None
            or end is None
            or start.geographic_position is None
            or end.geographic_position is None
        ):
            continue
        if "gps-trace" in route_sources:
            requests.append(
                ExternalVerificationRequest(
                    operation="roads.snap-trace",
                    subject_ids=[route.route_id],
                    rationale="Compare a GPS-derived centerline with the nearby road network.",
                )
            )
        elif route.status != "verified":
            requests.append(
                ExternalVerificationRequest(
                    operation="routes.compare-path",
                    subject_ids=[route.start_point_id, route.end_point_id, route.route_id],
                    rationale="Compare an unresolved local route with an online route result.",
                )
            )

    budget = policy.maximum_paid_calls
    return requests[:budget]


def analyze_map_evidence(
    bundle: MapEvidenceBundle,
    policy: MapEnrichmentPolicy | None = None,
    verifier: ExternalMapVerifier | None = None,
) -> MapIntelligenceResult:
    """Run local validation first and degrade cleanly when online verification is unavailable."""
    effective_policy = policy or MapEnrichmentPolicy()
    local_receipt = validate_map_evidence(bundle)
    plan = build_google_verification_plan(bundle, effective_policy)
    if not plan:
        return MapIntelligenceResult(
            local_receipt=local_receipt,
            verification_plan=[],
            advisory_hints=[],
            online_status="skipped",
        )
    if verifier is None or verifier.provider_id != "google-maps":
        return MapIntelligenceResult(
            local_receipt=local_receipt,
            verification_plan=plan,
            advisory_hints=[],
            online_status="fallback",
            fallback_reason="Google Maps verifier is unavailable; local analysis remains usable.",
        )
    try:
        hints = verifier.verify(bundle, plan)
    except Exception as exc:  # Provider/network faults must not invalidate local work.
        return MapIntelligenceResult(
            local_receipt=local_receipt,
            verification_plan=plan,
            advisory_hints=[],
            online_status="fallback",
            fallback_reason=f"Google Maps verification failed: {type(exc).__name__}",
        )
    return MapIntelligenceResult(
        local_receipt=local_receipt,
        verification_plan=plan,
        advisory_hints=hints,
        online_status="succeeded",
    )


def build_map_reasoning_packet(result: MapIntelligenceResult) -> MapReasoningPacket:
    """Expose unresolved facts and online hints without giving the model qualification authority."""
    return MapReasoningPacket(
        map_id=result.local_receipt.map_id,
        map_version=result.local_receipt.map_version,
        durable_graph_sha256=result.local_receipt.durable_graph_sha256,
        unresolved_issues=result.local_receipt.issues,
        online_hints=result.advisory_hints,
        required_constraints=[
            "do-not-invent-entrances",
            "do-not-promote-online-hints",
            "preserve-coordinate-registration",
            "require-connected-obstacle-free-graph",
        ],
    )


__all__ = [
    "ExternalMapVerifier",
    "ExternalVerificationHint",
    "ExternalVerificationRequest",
    "GeographicCoordinate",
    "MapEnrichmentPolicy",
    "MapEvidenceBundle",
    "MapEvidenceRecord",
    "MapFeaturePoint",
    "MapIntelligenceIssue",
    "MapIntelligenceReceipt",
    "MapIntelligenceResult",
    "MapReasoningPacket",
    "MapObstacle",
    "MapRouteEdge",
    "analyze_map_evidence",
    "build_map_reasoning_packet",
    "build_google_verification_plan",
    "validate_map_evidence",
]
