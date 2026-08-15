from __future__ import annotations

from app.autonomy.harness import (
    AUTONOMY_SYSTEM_PROMPT,
    autonomy_tool_registry,
    inspect_autonomy_harness,
)
from app.autonomy.models import AutonomyHarnessAsset, AutonomyHarnessInspectRequest


def _aircraft(*, ready: bool) -> AutonomyHarnessAsset:
    return AutonomyHarnessAsset(
        kind="aircraft",
        asset_id="aircraft-primary",
        name="Primary research quadrotor",
        version=2,
        status="validated-unsigned" if ready else "draft",
        content_hash=None,
        qualification_receipt_id="vehicle-receipt-v2" if ready else None,
        capabilities={
            "body_radius_m": 0.44,
            "dry_mass_kg": 1.55,
            "maximum_takeoff_mass_kg": 2.8,
            "maximum_thrust_n": 39.0,
            "maximum_speed_mps": 4.0,
            "maximum_acceleration_mps2": 3.0,
            "reserve_battery_percent": 25.0,
            "localization_sources": ["gps", "vio"],
        },
    )


def _map(*, ready: bool) -> AutonomyHarnessAsset:
    return AutonomyHarnessAsset(
        kind="map",
        asset_id="map-engineering-building",
        name="Engineering Building",
        version=4,
        status="qualified" if ready else "draft",
        content_hash="a" * 64 if ready else None,
        qualification_receipt_id="map-receipt-v4" if ready else None,
        capabilities={
            "coordinate_frame": "building-local",
            "resolution_m": 0.1,
            "semantic_layers": ["free-space", "stairs", "pickup-zones"],
            "planning_layers": ["collision-geometry", "occupancy", "esdf"],
            "compiler_scene_id": "stairwell-coffee-return" if ready else None,
        },
    )


def _request(*, aircraft_ready: bool, map_ready: bool) -> AutonomyHarnessInspectRequest:
    return AutonomyHarnessInspectRequest(
        edition="universal",
        natural_language="Fly from the office to the coffee pickup point and return.",
        aircraft=_aircraft(ready=aircraft_ready),
        map_pack=_map(ready=map_ready),
    )


def test_harness_blocks_planning_when_assets_are_not_qualified() -> None:
    result = inspect_autonomy_harness(_request(aircraft_ready=False, map_ready=False))

    assert result.status == "needs_assets"
    assert result.planning_ready is False
    assert "aircraft.pack.not-validated" in result.blockers
    assert "map.pack.not-qualified" in result.blockers
    assert result.eligible_tool_ids == [
        "vehicle.inspect_binding",
        "map.inspect_binding",
        "mission.validate_asset_readiness",
    ]
    assert all(receipt.outcome == "blocked" for receipt in result.tool_receipts)


def test_harness_exposes_planning_tools_only_after_asset_gates_pass() -> None:
    result = inspect_autonomy_harness(_request(aircraft_ready=True, map_ready=True))

    assert result.status == "draft"
    assert result.planning_ready is True
    assert result.blockers == []
    assert "map.resolve_entity" in result.eligible_tool_ids
    assert "mission.validate_plan" in result.eligible_tool_ids
    assert all(receipt.outcome == "accepted" for receipt in result.tool_receipts)


def test_harness_context_hash_is_deterministic_and_prompt_has_no_actuator_authority() -> None:
    first = inspect_autonomy_harness(_request(aircraft_ready=True, map_ready=True))
    second = inspect_autonomy_harness(_request(aircraft_ready=True, map_ready=True))

    assert first.context_sha256 == second.context_sha256
    assert len(first.context_sha256) == 64
    assert "Never emit" in AUTONOMY_SYSTEM_PROMPT
    assert "actuator" in AUTONOMY_SYSTEM_PROMPT
    assert all(definition["read_only"] for definition in autonomy_tool_registry().values())
