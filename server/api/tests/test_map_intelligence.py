from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.autonomy.map_intelligence import (
    ExternalVerificationHint,
    GeographicCoordinate,
    MapEnrichmentPolicy,
    MapEvidenceBundle,
    MapEvidenceRecord,
    MapFeaturePoint,
    MapObstacle,
    MapRouteEdge,
    analyze_map_evidence,
    build_map_reasoning_packet,
    validate_map_evidence,
)
from app.autonomy.models import Vector3


def _v(x: float, y: float, z: float = 2.0) -> Vector3:
    return Vector3(x=x, y=y, z=z)


def _geo(latitude_offset: float, longitude_offset: float) -> GeographicCoordinate:
    return GeographicCoordinate(
        latitude=60.20 + latitude_offset,
        longitude=24.96 + longitude_offset,
    )


def _evidence(identity: str, source: str = "scene-geometry") -> MapEvidenceRecord:
    return MapEvidenceRecord(
        evidence_id=identity,
        source=source,
        authority="source",
        storage="durable",
        confidence=0.98,
        claims=[
            "building-identity",
            "building-footprint",
            "entrance-location",
            "handoff-location",
            "route-centerline",
            "route-traversability",
            "coordinate-registration",
            "map-boundary",
            "obstacle-footprint",
        ],
        observed_at=datetime(2026, 10, 22, tzinfo=timezone.utc),
    )


def _bundle(*, candidate_route: bool = False) -> MapEvidenceBundle:
    return MapEvidenceBundle(
        map_id="fixture-campus",
        map_version=1,
        coordinate_frame="ENU",
        georeferenced=True,
        boundary_m=[
            _v(-5.0, -5.0, 0.0),
            _v(40.0, -5.0, 0.0),
            _v(40.0, 10.0, 0.0),
            _v(-5.0, 10.0, 0.0),
        ],
        evidence=[_evidence("scene-1")],
        points=[
            MapFeaturePoint(
                point_id="building-a",
                kind="building",
                position_m=_v(0.0, 2.0, 0.0),
                geographic_position=_geo(0.0, 0.0),
                label="Building A",
                status="verified",
                evidence_ids=["scene-1"],
            ),
            MapFeaturePoint(
                point_id="handoff-a",
                kind="handoff",
                position_m=_v(0.0, 0.0),
                geographic_position=_geo(0.0, 0.00001),
                label="Building A handoff",
                building_id="building-a",
                status="verified",
                evidence_ids=["scene-1"],
            ),
            MapFeaturePoint(
                point_id="junction-a",
                kind="junction",
                position_m=_v(10.0, 0.0),
                geographic_position=_geo(0.0, 0.0001),
                label="Main junction",
                status="verified",
                evidence_ids=["scene-1"],
            ),
        ],
        routes=[
            MapRouteEdge(
                route_id="road-a",
                start_point_id="handoff-a",
                end_point_id="junction-a",
                centerline_m=[_v(0.0, 0.0), _v(5.0, 0.0), _v(10.0, 0.0)],
                kind="road",
                status="candidate" if candidate_route else "verified",
                evidence_ids=["scene-1"],
            )
        ],
    )


def test_local_map_graph_is_ready_without_any_online_provider() -> None:
    result = analyze_map_evidence(_bundle())
    assert result.local_receipt.status == "ready_for_qualification"
    assert result.local_receipt.component_count == 1
    assert result.online_status == "skipped"
    assert result.verification_plan == []


def test_online_enrichment_requires_an_explicit_paid_budget() -> None:
    result = analyze_map_evidence(
        _bundle(candidate_route=True),
        MapEnrichmentPolicy(mode="deep"),
    )
    assert result.online_status == "skipped"
    assert result.verification_plan == []


def test_online_failure_falls_back_without_discarding_local_receipt() -> None:
    class BrokenVerifier:
        provider_id = "google-maps"

        def verify(self, bundle, requests):
            raise TimeoutError("offline")

    result = analyze_map_evidence(
        _bundle(candidate_route=True),
        MapEnrichmentPolicy(
            mode="deep",
            explicit_online_enrichment=True,
            maximum_paid_calls=2,
        ),
        BrokenVerifier(),
    )
    assert result.online_status == "fallback"
    assert result.local_receipt.status == "blocked"
    assert [request.operation for request in result.verification_plan] == [
        "routes.compare-path"
    ]


def test_google_hint_is_advisory_and_cannot_change_durable_digest() -> None:
    now = datetime(2026, 10, 22, tzinfo=timezone.utc)

    class HintVerifier:
        provider_id = "google-maps"

        def verify(self, bundle, requests):
            return [
                ExternalVerificationHint(
                    operation=requests[0].operation,
                    subject_ids=requests[0].subject_ids,
                    verdict="supports",
                    confidence=0.91,
                    summary="The online route appears consistent with the local candidate.",
                    observed_at=now,
                    expires_at=now + timedelta(days=30),
                )
            ]

    bundle = _bundle(candidate_route=True)
    local_digest = validate_map_evidence(bundle).durable_graph_sha256
    result = analyze_map_evidence(
        bundle,
        MapEnrichmentPolicy(
            mode="deep",
            explicit_online_enrichment=True,
            maximum_paid_calls=1,
        ),
        HintVerifier(),
    )
    assert result.online_status == "succeeded"
    assert result.local_receipt.durable_graph_sha256 == local_digest
    assert result.advisory_hints[0].verdict == "supports"
    packet = build_map_reasoning_packet(result)
    assert packet.decision_authority == "advisory_only"
    assert packet.online_hints == result.advisory_hints
    assert "do-not-promote-online-hints" in packet.required_constraints


def test_google_evidence_cannot_be_marked_durable_or_authoritative() -> None:
    now = datetime(2026, 10, 22, tzinfo=timezone.utc)
    try:
        MapEvidenceRecord(
            evidence_id="google-1",
            source="google-routes",
            authority="source",
            storage="durable",
            confidence=0.9,
            claims=["route-centerline"],
            observed_at=now,
        )
    except ValueError as exc:
        assert "ephemeral and advisory" in str(exc)
    else:
        raise AssertionError("Google evidence was incorrectly accepted as durable source truth")


def test_disconnected_route_and_endpoint_mismatch_are_blocking() -> None:
    bundle = _bundle()
    bundle.points.append(
        MapFeaturePoint(
            point_id="junction-b",
            kind="junction",
            position_m=_v(30.0, 0.0),
            geographic_position=_geo(0.0, 0.0003),
            label="Detached junction",
            status="verified",
            evidence_ids=["scene-1"],
        )
    )
    bundle.routes[0].centerline_m[-1] = _v(8.0, 0.0)
    receipt = validate_map_evidence(bundle)
    codes = {issue.code for issue in receipt.issues}
    assert receipt.status == "blocked"
    assert "map.route.endpoint-coordinate-mismatch" in codes
    assert "map.point.route-disconnected" in codes


def test_duplicate_reverse_edge_and_building_crossing_are_blocking() -> None:
    bundle = _bundle()
    bundle.routes.append(
        MapRouteEdge(
            route_id="road-a-reverse",
            start_point_id="junction-a",
            end_point_id="handoff-a",
            centerline_m=[_v(10.0, 0.0), _v(0.0, 0.0)],
            kind="road",
            status="verified",
            evidence_ids=["scene-1"],
        )
    )
    bundle.obstacles.append(
        MapObstacle(
            obstacle_id="building-footprint",
            kind="building",
            footprint_m=[
                _v(4.0, -1.0, 0.0),
                _v(6.0, -1.0, 0.0),
                _v(6.0, 1.0, 0.0),
                _v(4.0, 1.0, 0.0),
            ],
            status="verified",
            evidence_ids=["scene-1"],
        )
    )
    receipt = validate_map_evidence(bundle)
    codes = {issue.code for issue in receipt.issues}
    assert "map.route.duplicate-edge" in codes
    assert "map.route.obstacle-crossing" in codes


def test_sub_five_centimetre_route_jitter_is_rejected() -> None:
    bundle = _bundle()
    bundle.routes[0].centerline_m = [
        _v(0.0, 0.0),
        _v(0.01, 0.01),
        _v(10.0, 0.0),
    ]
    receipt = validate_map_evidence(bundle)
    assert "map.route.centerline-jitter" in {issue.code for issue in receipt.issues}


def test_generic_geometry_evidence_does_not_prove_a_route() -> None:
    bundle = _bundle()
    bundle.evidence[0].claims = ["building-identity", "handoff-location"]
    receipt = validate_map_evidence(bundle)
    codes = {issue.code for issue in receipt.issues}
    assert "map.route.required-evidence-claims-missing" in codes
    assert "map.point.required-evidence-claim-missing" in codes


def test_online_plan_requires_a_registered_geographic_frame() -> None:
    bundle = _bundle(candidate_route=True)
    bundle.georeferenced = False
    result = analyze_map_evidence(
        bundle,
        MapEnrichmentPolicy(
            mode="deep",
            explicit_online_enrichment=True,
            maximum_paid_calls=10,
        ),
    )
    assert result.online_status == "skipped"
    assert result.verification_plan == []


def test_off_map_route_extension_is_rejected() -> None:
    bundle = _bundle()
    bundle.routes[0].centerline_m = [
        _v(0.0, 0.0),
        _v(5.0, 20.0),
        _v(10.0, 0.0),
    ]
    receipt = validate_map_evidence(bundle)
    assert "map.route.outside-boundary" in {issue.code for issue in receipt.issues}


def test_distinct_alternate_path_between_same_nodes_is_allowed() -> None:
    bundle = _bundle()
    bundle.routes.append(
        MapRouteEdge(
            route_id="road-alternate",
            start_point_id="handoff-a",
            end_point_id="junction-a",
            centerline_m=[_v(0.0, 0.0), _v(5.0, 3.0), _v(10.0, 0.0)],
            kind="path",
            status="verified",
            evidence_ids=["scene-1"],
        )
    )
    receipt = validate_map_evidence(bundle)
    assert "map.route.duplicate-edge" not in {issue.code for issue in receipt.issues}
