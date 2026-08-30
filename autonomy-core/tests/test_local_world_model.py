import pytest

from dronedream_agent_core.contracts import RangeRayObservation, Vector3
from dronedream_agent_core.local_world_model import MetricVoxelMap


def _map() -> MetricVoxelMap:
    world = MetricVoxelMap(
        resolution_m=1.0,
        minimum_bound_m=Vector3(x=0.0, y=0.0, z=0.0),
        maximum_bound_m=Vector3(x=9.99, y=5.99, z=0.99),
    )
    world.mark_box(
        minimum_m=Vector3(x=0.01, y=0.01, z=0.01),
        maximum_m=Vector3(x=9.9, y=5.9, z=0.9),
        occupied=False,
        confidence=0.70,
    )
    return world


def test_clearance_aware_path_uses_observed_doorway() -> None:
    world = _map()
    world.mark_box(
        minimum_m=Vector3(x=4.01, y=0.01, z=0.01),
        maximum_m=Vector3(x=4.9, y=1.9, z=0.9),
        occupied=True,
    )
    world.mark_box(
        minimum_m=Vector3(x=4.01, y=3.01, z=0.01),
        maximum_m=Vector3(x=4.9, y=5.9, z=0.9),
        occupied=True,
    )

    path = world.plan_path(
        start_m=Vector3(x=1.5, y=2.5, z=0.5),
        goal_m=Vector3(x=8.5, y=2.5, z=0.5),
        required_clearance_m=0.1,
    )

    assert path[0].x == 1.5
    assert path[-1].x == 8.5
    assert any(4.0 <= point.x < 5.0 and 2.0 <= point.y < 3.0 for point in path)


def test_unknown_space_is_not_treated_as_free() -> None:
    world = MetricVoxelMap(
        resolution_m=0.5,
        minimum_bound_m=Vector3(x=0.0, y=0.0, z=0.0),
        maximum_bound_m=Vector3(x=4.0, y=1.0, z=1.0),
    )
    world.integrate_ray(
        RangeRayObservation(
            origin_m=Vector3(x=0.1, y=0.25, z=0.25),
            endpoint_m=Vector3(x=1.9, y=0.25, z=0.25),
            hit=False,
            confidence=0.95,
            observed_at_monotonic_seconds=1.0,
        )
    )

    with pytest.raises(ValueError, match="goal is not in observed"):
        world.plan_path(
            start_m=Vector3(x=0.25, y=0.25, z=0.25),
            goal_m=Vector3(x=3.75, y=0.25, z=0.25),
            required_clearance_m=0.0,
        )


def test_text_only_summary_exposes_metric_evidence_and_authority_boundary() -> None:
    world = _map()
    summary = world.text_map_summary()

    assert summary["source_of_truth"] == "metric-range-observations-not-rendered-image"
    assert summary["unknown_space_policy"] == "blocked-until-observed"
    assert int(summary["observed_free_voxel_count"]) > 0
    assert "actuator commands" in str(summary["model_authority"])
