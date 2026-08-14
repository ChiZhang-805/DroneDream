"""Bounded natural-language compiler, trajectory checks, and edition policy."""

from __future__ import annotations

import hashlib
import json
import math

from app.autonomy.catalog import SCENES, get_scene
from app.autonomy.models import (
    AutonomyCompileRequest,
    AutonomyCompileResponse,
    ExecutionAdapter,
    ExecutionPolicy,
    MissionContract,
    MissionMetrics,
    MissionStep,
    PerceptionMode,
    RoutePoint,
    ValidationIssue,
)

GRAVITY = 9.80665
MIN_THRUST_TO_WEIGHT = 1.35
VALIDATED_SIGNED_PACK_COUNT = 0


class AutonomyCompileError(ValueError):
    def __init__(self, code: str, message: str, status_code: int = 422) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


def _select_scene(request: AutonomyCompileRequest) -> str:
    if request.scene_id:
        if request.scene_id not in SCENES:
            raise AutonomyCompileError(
                "UNKNOWN_AUTONOMY_SCENE",
                "The requested terrain scene is not registered.",
                404,
            )
        return request.scene_id
    text = request.natural_language.casefold()
    if any(token in text for token in ("gate", "圆门", "穿门", "树林", "forest")):
        return "forest-gate-inspection"
    if any(token in text for token in ("dock", "走廊", "corridor", "停靠", "狭窄")):
        return "service-corridor-dock"
    return "stairwell-coffee-return"


def _select_perception(request: AutonomyCompileRequest) -> PerceptionMode:
    if request.perception_mode:
        return request.perception_mode
    text = request.natural_language.casefold()
    mentions_map = any(token in text for token in ("map", "地图", "occupancy"))
    mentions_vision = any(
        token in text for token in ("camera", "vision", "摄像", "视觉", "rgb", "depth")
    )
    if mentions_map and mentions_vision:
        return "fusion"
    if mentions_vision:
        return "vision"
    if mentions_map:
        return "map"
    return "fusion"


def _steps(scene_id: str, pickup_payload_kg: float) -> list[MissionStep]:
    if scene_id == "stairwell-coffee-return":
        return [
            MissionStep(order=1, action="takeoff", label="Launch from the third-floor office"),
            MissionStep(
                order=2,
                action="traverse_stairs",
                label="Descend the narrow stairwell through two landings",
            ),
            MissionStep(
                order=3,
                action="transit",
                label="Exit to the courtyard and avoid trees, signs, poles and buildings",
            ),
            MissionStep(
                order=4,
                action="pickup",
                label="Acquire the coffee at the docking target",
                payload_delta_kg=pickup_payload_kg,
            ),
            MissionStep(
                order=5,
                action="return",
                label="Replan with the loaded vehicle envelope and return upstairs",
            ),
            MissionStep(order=6, action="land", label="Land at the original launch point"),
        ]
    if scene_id == "forest-gate-inspection":
        return [
            MissionStep(
                order=1, action="takeoff", label="Launch into the vegetation corridor"
            ),
            MissionStep(
                order=2,
                action="pass_gate",
                label="Pass three gates through their geometric centers",
            ),
            MissionStep(
                order=3, action="land", label="Complete the inspection hover and land"
            ),
        ]
    return [
        MissionStep(order=1, action="takeoff", label="Launch in the service corridor"),
        MissionStep(
            order=2,
            action="transit",
            label="Follow the narrow collision-free corridor around blind corners",
        ),
        MissionStep(order=3, action="land", label="Dock on the marked target"),
    ]


def _route_metrics(points: list[RoutePoint]) -> tuple[float, float]:
    distance = 0.0
    vertical = 0.0
    for start, end in zip(points, points[1:], strict=False):
        dx, dy, dz = end.x - start.x, end.y - start.y, end.z - start.z
        distance += math.sqrt(dx * dx + dy * dy + dz * dz)
        vertical += abs(dz)
    return distance, vertical


def _policy(request: AutonomyCompileRequest, feasible: bool) -> ExecutionPolicy:
    target = request.execution_target
    adapter: ExecutionAdapter
    if target == "simulation":
        adapter = "px4_gazebo_contract"
    elif target == "hitl":
        adapter = "hitl_contract"
    else:
        adapter = "hardware_contract"
    blockers: list[str] = []
    required: list[str] = []

    if target != "simulation" and request.edition == "sim":
        blockers.append("edition.sim.forbids-hardware-and-hitl")
    if target != "simulation" and VALIDATED_SIGNED_PACK_COUNT == 0:
        blockers.append("vehicle-pack.registry.zero-validated-signed-packs")
    if target != "simulation" and not request.evidence.simulation_qualified:
        blockers.append("simulation-qualification.missing")
    if target != "simulation" and not request.evidence.signed_vehicle_pack_id:
        blockers.append("vehicle-pack.receipt.missing")
    if target != "simulation" and not request.evidence.operator_confirmed:
        blockers.append("operator.confirmation.missing")
    for ready, code in (
        (request.evidence.localization_ready, "localization.not-ready"),
        (request.evidence.link_ready, "command-link.not-ready"),
        (request.evidence.geofence_ready, "geofence.not-ready"),
        (request.evidence.battery_ready, "battery.not-ready"),
    ):
        if target != "simulation" and not ready:
            blockers.append(code)
    if not feasible:
        blockers.append("trajectory.not-feasible")

    if target == "simulation" and feasible:
        return ExecutionPolicy(
            readiness="simulation_ready", adapter=adapter, can_execute=True,
            validated_signed_pack_count=VALIDATED_SIGNED_PACK_COUNT,
            blockers=[],
            required_next_steps=[
                "Run the PX4/Gazebo qualification job and retain its signed evidence receipt."
            ],
        )
    if blockers:
        required.extend([
            (
                "Complete and sign the simulation qualification for the identical mission "
                "contract."
            ),
            "Bind a validated signed Vehicle Pack and firmware identity.",
            "Obtain a short-lived operator confirmation after live preflight checks.",
        ])
        return ExecutionPolicy(
            readiness="denied", adapter=adapter, can_execute=False,
            validated_signed_pack_count=VALIDATED_SIGNED_PACK_COUNT,
            blockers=sorted(set(blockers)), required_next_steps=required,
        )
    return ExecutionPolicy(
        readiness="preview_only", adapter=adapter, can_execute=False,
        validated_signed_pack_count=VALIDATED_SIGNED_PACK_COUNT,
        blockers=["runtime.execution-adapter.not-bound"],
        required_next_steps=["Bind the audited runtime adapter before enabling execution."],
    )


def compile_autonomy_mission(request: AutonomyCompileRequest) -> AutonomyCompileResponse:
    """Compile intent into a deterministic contract; never emit raw actuator commands."""

    scene_id = _select_scene(request)
    scene = get_scene(scene_id)
    if scene is None:  # defensive registry invariant
        raise AutonomyCompileError(
            "AUTONOMY_SCENE_UNAVAILABLE",
            "The terrain scene is unavailable.",
            503,
        )
    perception = _select_perception(request)
    steps = _steps(scene_id, request.vehicle.pickup_payload_kg)
    points = [point.model_copy(deep=True) for point in scene.reference_path]
    route_length, vertical_travel = _route_metrics(points)
    launch_mass = request.vehicle.dry_mass_kg + request.vehicle.launch_payload_kg
    pickup_delta = (
        request.vehicle.pickup_payload_kg
        if any(step.action == "pickup" for step in steps)
        else 0.0
    )
    loaded_mass = launch_mass + pickup_delta
    thrust_to_weight = request.vehicle.max_total_thrust_n / (loaded_mass * GRAVITY)
    braking_distance = (
        request.vehicle.max_speed_mps**2 / (2 * request.vehicle.max_acceleration_mps2)
        + request.vehicle.radius_m
    )
    issues: list[ValidationIssue] = []
    if loaded_mass > request.vehicle.max_takeoff_mass_kg:
        issues.append(
            ValidationIssue(
                code="vehicle.loaded-mass-exceeds-mtom",
                severity="error",
                message="Post-pickup mass exceeds the configured maximum takeoff mass.",
            )
        )
    if thrust_to_weight < MIN_THRUST_TO_WEIGHT:
        issues.append(
            ValidationIssue(
                code="vehicle.thrust-margin-insufficient",
                severity="error",
                message=(
                    "Post-pickup thrust-to-weight must remain at least "
                    f"{MIN_THRUST_TO_WEIGHT:.2f}."
                ),
            )
        )
    if braking_distance > scene.minimum_clearance_m:
        issues.append(
            ValidationIssue(
                code="trajectory.braking-envelope-exceeds-clearance",
                severity="error",
                message=(
                    "The stopping envelope is larger than the scene's verified minimum "
                    "clearance."
                ),
            )
        )
    if perception == "map":
        issues.append(
            ValidationIssue(
                code="perception.static-map-no-live-obstacle-update",
                severity="warning",
                message=(
                    "Map-only operation cannot qualify dynamic-obstacle response; use vision "
                    "or fusion for hardware handoff."
                ),
            )
        )
    if scene_id == "stairwell-coffee-return" and perception == "vision":
        issues.append(
            ValidationIssue(
                code="perception.no-global-return-map",
                severity="warning",
                message=(
                    "Vision-only return depends on retained route memory and relocalization at "
                    "each stair landing."
                ),
            )
        )
    issues.append(
        ValidationIssue(
            code="planner.reference-corridor-verified",
            severity="info",
            message=(
                "The route uses a bounded reference corridor with speed limits and "
                "payload-aware return checks."
            ),
        )
    )
    feasible = not any(issue.severity == "error" for issue in issues)

    canonical = {
        "edition": request.edition,
        "execution_target": request.execution_target,
        "scene_id": scene_id,
        "perception_mode": perception,
        "steps": [step.model_dump(mode="json") for step in steps],
        "vehicle": request.vehicle.model_dump(mode="json"),
    }
    digest = hashlib.sha256(
        json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    contract = MissionContract(
        contract_id=f"mission-{digest[:20]}", edition=request.edition,
        execution_target=request.execution_target, scene_id=scene_id,
        perception_mode=perception, intent=request.natural_language, steps=steps,
        immutable_safety_rules=[
            (
                "A language or vision model may propose mission goals but cannot issue "
                "actuator commands."
            ),
            (
                "Every trajectory must pass geometry, dynamics, payload and edition-policy "
                "checks."
            ),
            (
                "Loss of localization, command link or safety clearance transitions execution "
                "to hold or abort."
            ),
            (
                "Hardware execution requires an independently signed simulation qualification "
                "and operator challenge."
            ),
        ],
    )
    metrics = MissionMetrics(
        route_length_m=route_length,
        vertical_travel_m=vertical_travel,
        estimated_duration_s=sum(
            math.dist((a.x, a.y, a.z), (b.x, b.y, b.z))
            / min(a.speed_limit_mps, b.speed_limit_mps)
            for a, b in zip(points, points[1:], strict=False)
        ),
        minimum_clearance_m=scene.minimum_clearance_m,
        launch_mass_kg=launch_mass,
        post_pickup_mass_kg=loaded_mass,
        post_pickup_thrust_to_weight=thrust_to_weight,
        braking_distance_m=braking_distance,
    )
    return AutonomyCompileResponse(
        scene=scene, contract=contract, trajectory=points, feasible=feasible,
        issues=issues, metrics=metrics, execution_policy=_policy(request, feasible),
        planner={
            "semantic_layer": "bounded-natural-language-contract-v1",
            "global_layer": "prevalidated-corridor-graph-v1",
            "trajectory_layer": "payload-aware-speed-profile-v1",
            "safety_layer": "deterministic-geometric-policy-kernel-v1",
        },
    )


__all__ = ["AutonomyCompileError", "compile_autonomy_mission"]
