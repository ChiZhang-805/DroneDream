from dronedream_agent_core.contracts import GraphRoute, Vector3, VehicleAsset
from dronedream_agent_plugins.planning_quality_plugins import _energy_reserve_gate


def _vehicle() -> VehicleAsset:
    return VehicleAsset(
        asset_id="vehicle-a",
        name="vehicle",
        dry_mass_kg=1,
        max_takeoff_mass_kg=2,
        body_radius_m=0.2,
        body_height_m=0.2,
        max_speed_mps=2,
        max_acceleration_mps2=2,
        qualified_range_m=400,
        reserve_battery_percent=20,
        max_pickup_payload_kg=0.5,
        sensors=["camera"],
    )


def _route(length_m: float) -> GraphRoute:
    return GraphRoute(
        start_node="start",
        goal_node="goal",
        node_ids=["start", "goal"],
        edge_ids=["edge"],
        positions_m=[Vector3(x=0, y=0, z=1), Vector3(x=length_m, y=0, z=1)],
        route_length_m=length_m,
        all_edges_flight_verified=True,
    )


def test_energy_gate_uses_vehicle_qualified_range_without_double_reserving() -> None:
    result = _energy_reserve_gate(route=_route(400), vehicle=_vehicle())

    assert result["accepted"] is True
    assert result["usable_range_m"] == 400


def test_energy_gate_configuration_can_tighten_but_never_expand_asset_envelope() -> None:
    expanded = _energy_reserve_gate(
        route=_route(401),
        vehicle=_vehicle(),
        configuration={"qualified_range_m": 1000, "reserve_fraction": 0.05},
    )
    tightened = _energy_reserve_gate(
        route=_route(350),
        vehicle=_vehicle(),
        configuration={"qualified_range_m": 400, "reserve_fraction": 0.4},
    )

    assert expanded["accepted"] is False
    assert expanded["qualified_range_m"] == 400
    assert expanded["reserve_fraction"] == 0.2
    assert tightened["accepted"] is False
    assert tightened["usable_range_m"] == 300
