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
    MissionAction,
    MissionContract,
    MissionMetrics,
    MissionStep,
    MissionTaskGraph,
    MissionTaskNode,
    OnboardRuntimeProfile,
    PerceptionMode,
    RoutePoint,
    RuntimeBridge,
    RuntimeComponent,
    RuntimeComponentId,
    RuntimeComponentStatus,
    RuntimeMode,
    SafetyAction,
    TaskExecutor,
    TaskNodeStatus,
    TaskRisk,
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


def runtime_profile_for(request: AutonomyCompileRequest) -> OnboardRuntimeProfile:
    """Describe the runtime boundary without claiming that hardware is connected."""

    if request.execution_target == "simulation":
        mode: RuntimeMode = "simulation_contract"
        bridge: RuntimeBridge = "px4_gazebo"
        status: RuntimeComponentStatus = "available"
        authority = True
    elif request.execution_target == "hitl":
        mode = "hitl_shadow"
        bridge = "px4_hitl_shadow"
        status = "shadow"
        authority = False
    else:
        mode = "hardware_locked"
        bridge = "px4_hardware_locked"
        status = "locked"
        authority = False

    component_specs: tuple[tuple[RuntimeComponentId, str, float], ...] = (
        ("mission_executive", "Runs the bounded mission state machine.", 20.0),
        ("perception_vio_slam", "Accepts versioned VIO, SLAM, map and vision observations.", 30.0),
        ("world_model", "Maintains obstacle, gate, terrain and payload state.", 20.0),
        ("global_planner", "Builds the route corridor between mission checkpoints.", 2.0),
        ("local_planner", "Repairs the trajectory inside the approved corridor.", 20.0),
        ("trajectory_tracker", "Converts a qualified trajectory to PX4 setpoint contracts.", 50.0),
        ("px4_bridge", "Separates simulator, HITL shadow and locked aircraft transports.", 50.0),
        ("safety_supervisor", "Overrides progress with hold, land or abort decisions.", 50.0),
        ("evidence_recorder", "Hash-chains accepted observations and decisions.", 20.0),
    )
    components = [
        RuntimeComponent(
            id=component_id,
            status=status,
            role=role,
            rate_hz=rate_hz,
            actuator_authority=authority and component_id == "px4_bridge",
        )
        for component_id, role, rate_hz in component_specs
    ]
    return OnboardRuntimeProfile(
        mode=mode,
        bridge=bridge,
        command_authority=authority,
        components=components,
        fail_safe_actions=["hold", "land", "abort"],
    )


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
    return "school-campus-v1"


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
    if scene_id in {"school-campus-v1", "stairwell-coffee-return"}:
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
            MissionStep(order=1, action="takeoff", label="Launch into the vegetation corridor"),
            MissionStep(
                order=2,
                action="pass_gate",
                label="Pass three gates through their geometric centers",
            ),
            MissionStep(order=3, action="land", label="Complete the inspection hover and land"),
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


def _task_graph(steps: list[MissionStep]) -> MissionTaskGraph:
    """Expand intent into an auditable, fail-closed execution graph.

    The language model can describe goals, but every motion segment is gated by
    perception, corridor planning, dynamics checks and explicit completion
    evidence before the mission executive advances the graph.
    """

    nodes: list[MissionTaskNode] = []

    def append_node(
        task_id: str,
        label: str,
        *,
        depends_on: list[str],
        executor: TaskExecutor,
        risk: TaskRisk,
        timeout_s: float,
        fallback: SafetyAction,
        expected_output: str,
        completion_evidence: list[str],
        max_retries: int = 2,
        status: TaskNodeStatus = "pending",
    ) -> str:
        nodes.append(
            MissionTaskNode(
                task_id=task_id,
                label=label,
                status=status,
                depends_on=depends_on,
                executor=executor,
                risk=risk,
                max_retries=max_retries,
                timeout_s=timeout_s,
                fallback=fallback,
                expected_output=expected_output,
                completion_evidence=completion_evidence,
            )
        )
        return task_id

    previous = append_node(
        "preflight-pack-identity",
        "Bind the immutable Vehicle Pack, firmware identity and control adapter",
        depends_on=[],
        executor="mission_executive",
        risk="critical",
        max_retries=0,
        timeout_s=15.0,
        fallback="abort",
        expected_output="Vehicle, firmware and adapter identities match the mission contract",
        completion_evidence=["vehicle-pack.digest", "firmware.identity", "adapter.identity"],
        status="ready",
    )
    previous = append_node(
        "preflight-sensors",
        "Verify required sensor calibration, time synchronization and stream health",
        depends_on=[previous],
        executor="perception",
        risk="critical",
        max_retries=1,
        timeout_s=30.0,
        fallback="abort",
        expected_output=(
            "Every required localization and obstacle stream is healthy and synchronized"
        ),
        completion_evidence=["sensor.calibration", "clock.offset", "stream.health"],
    )
    previous = append_node(
        "preflight-flight-envelope",
        "Validate mass, center of gravity, thrust, energy reserve and braking envelope",
        depends_on=[previous],
        executor="mission_executive",
        risk="critical",
        max_retries=0,
        timeout_s=20.0,
        fallback="abort",
        expected_output="A task-specific flight-envelope qualification receipt",
        completion_evidence=["mass.total", "cg.bound", "thrust.margin", "battery.reserve"],
    )
    previous = append_node(
        "world-map-binding",
        "Bind the selected Map Pack, coordinate frame, semantic entities and geofence",
        depends_on=[previous],
        executor="global_planner",
        risk="high",
        max_retries=1,
        timeout_s=30.0,
        fallback="hold",
        expected_output=(
            "A versioned world frame with grounded mission entities and hard boundaries"
        ),
        completion_evidence=[
            "map-pack.digest",
            "frame.transform",
            "semantic.bindings",
            "geofence.version",
        ],
    )
    previous = append_node(
        "world-localization",
        "Establish bounded localization and initialize the live obstacle world model",
        depends_on=[previous],
        executor="perception",
        risk="critical",
        max_retries=2,
        timeout_s=45.0,
        fallback="hold",
        expected_output="Localization covariance and observable free-space satisfy launch limits",
        completion_evidence=[
            "localization.covariance",
            "free-space.snapshot",
            "dynamic-overlay.age",
        ],
    )
    previous = append_node(
        "plan-global-corridor",
        "Generate the global route corridor and a payload-aware return alternative",
        depends_on=[previous],
        executor="global_planner",
        risk="high",
        max_retries=3,
        timeout_s=60.0,
        fallback="hold",
        expected_output=(
            "Primary and contingency corridors satisfy map, clearance and energy constraints"
        ),
        completion_evidence=["corridor.primary", "corridor.contingency", "energy.projection"],
    )

    executor_by_action: dict[MissionAction, TaskExecutor] = {
        "takeoff": "px4_bridge",
        "transit": "local_planner",
        "traverse_stairs": "local_planner",
        "pass_gate": "local_planner",
        "pickup": "payload_controller",
        "return": "global_planner",
        "land": "px4_bridge",
    }
    risk_by_action: dict[MissionAction, TaskRisk] = {
        "takeoff": "high",
        "transit": "medium",
        "traverse_stairs": "high",
        "pass_gate": "high",
        "pickup": "high",
        "return": "medium",
        "land": "high",
    }
    for step in steps:
        prefix = f"mission-{step.order:02d}-{step.action.replace('_', '-')}"
        fallback: SafetyAction = "land" if step.action in {"return", "land"} else "hold"
        previous = append_node(
            f"{prefix}-observe",
            f"Refresh perception and confirm the local world before: {step.label}",
            depends_on=[previous],
            executor="perception",
            risk=risk_by_action[step.action],
            max_retries=3,
            timeout_s=20.0,
            fallback="hold",
            expected_output="A time-bounded local obstacle and semantic-target snapshot",
            completion_evidence=[
                "perception.sequence",
                "local-map.age",
                "tracked-entities.snapshot",
            ],
        )
        previous = append_node(
            f"{prefix}-plan",
            f"Plan or repair the local trajectory segment for: {step.label}",
            depends_on=[previous],
            executor="global_planner" if step.action == "return" else "local_planner",
            risk=risk_by_action[step.action],
            max_retries=3,
            timeout_s=45.0,
            fallback="hold",
            expected_output=(
                "A collision-free, time-parameterized segment inside the approved corridor"
            ),
            completion_evidence=[
                "trajectory.revision",
                "corridor.containment",
                "clearance.prediction",
            ],
        )
        previous = append_node(
            f"{prefix}-qualify",
            f"Check geometry, dynamics, energy and safety policy for: {step.label}",
            depends_on=[previous],
            executor="mission_executive",
            risk="critical" if step.action in {"takeoff", "land", "pickup"} else "high",
            max_retries=1,
            timeout_s=15.0,
            fallback=fallback,
            expected_output="The proposed segment passes every deterministic execution gate",
            completion_evidence=["dynamics.acceptance", "energy.margin", "safety.acceptance"],
        )
        previous = append_node(
            f"{prefix}-execute",
            step.label,
            depends_on=[previous],
            executor=executor_by_action[step.action],
            risk=risk_by_action[step.action],
            max_retries=1 if step.action in {"takeoff", "land"} else 2,
            timeout_s=120.0 if step.action in {"transit", "traverse_stairs", "return"} else 45.0,
            fallback=fallback,
            expected_output=f"Controller-accepted completion of {step.action}",
            completion_evidence=["pose.trace", "clearance.minimum", "controller.acceptance"],
        )
        previous = append_node(
            f"{prefix}-verify",
            f"Verify completion evidence and settle the task state for: {step.label}",
            depends_on=[previous],
            executor="mission_executive",
            risk="high" if step.action in {"pickup", "land"} else "medium",
            max_retries=2,
            timeout_s=20.0,
            fallback=fallback,
            expected_output=(
                "Completion evidence is consistent, current and attributable to this task"
            ),
            completion_evidence=["task.result", "task.evidence", "world-state.revision"],
        )
        if step.action == "pickup":
            previous = append_node(
                f"{prefix}-recompute-envelope",
                (
                    "Confirm payload attachment and recompute mass, center of gravity, thrust "
                    "and return energy"
                ),
                depends_on=[previous],
                executor="mission_executive",
                risk="critical",
                max_retries=1,
                timeout_s=25.0,
                fallback="land",
                expected_output="The loaded aircraft remains inside its qualified return envelope",
                completion_evidence=[
                    "payload.confirmed",
                    "mass.loaded",
                    "cg.loaded",
                    "return-energy.margin",
                ],
            )
    previous = append_node(
        "postflight-state",
        "Confirm landing, disarm the vehicle and close command authority",
        depends_on=[previous],
        executor="px4_bridge",
        risk="critical",
        max_retries=1,
        timeout_s=20.0,
        fallback="abort",
        expected_output="Landed and disarmed state with actuator authority revoked",
        completion_evidence=["vehicle.landed", "vehicle.disarmed", "authority.revoked"],
    )
    append_node(
        "postflight-evidence",
        "Seal mission results, anomalies, task revisions and replay evidence",
        depends_on=[previous],
        executor="mission_executive",
        risk="low",
        max_retries=2,
        timeout_s=20.0,
        fallback="hold",
        expected_output="A hash-chained mission evidence head",
        completion_evidence=[
            "mission.result",
            "task-graph.revisions",
            "decision.log",
            "evidence.chain-head",
        ],
    )
    return MissionTaskGraph(nodes=nodes, active_node_ids=["preflight-pack-identity"])


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
            readiness="simulation_ready",
            adapter=adapter,
            can_execute=True,
            validated_signed_pack_count=VALIDATED_SIGNED_PACK_COUNT,
            blockers=[],
            required_next_steps=[
                "Run the PX4/Gazebo qualification job and retain its signed evidence receipt."
            ],
        )
    if blockers:
        if target == "simulation":
            required.extend(
                [
                    (
                        "Adjust payload, speed, acceleration, or the vehicle envelope until "
                        "all trajectory feasibility checks pass."
                    ),
                    (
                        "Recompile the same simulation mission and review every reported "
                        "geometry or dynamics issue before qualification."
                    ),
                ]
            )
        else:
            required.extend(
                [
                    (
                        "Complete and sign the simulation qualification for the identical "
                        "mission contract."
                    ),
                    "Bind a validated signed Vehicle Pack and firmware identity.",
                    "Obtain a short-lived operator confirmation after live preflight checks.",
                ]
            )
        return ExecutionPolicy(
            readiness="denied",
            adapter=adapter,
            can_execute=False,
            validated_signed_pack_count=VALIDATED_SIGNED_PACK_COUNT,
            blockers=sorted(set(blockers)),
            required_next_steps=required,
        )
    return ExecutionPolicy(
        readiness="preview_only",
        adapter=adapter,
        can_execute=False,
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
    task_graph = _task_graph(steps)
    points = [
        point.model_copy(
            deep=True,
            update={
                "speed_limit_mps": min(
                    point.speed_limit_mps,
                    request.vehicle.max_speed_mps,
                )
            },
        )
        for point in scene.reference_path
    ]
    route_length, vertical_travel = _route_metrics(points)
    launch_mass = request.vehicle.dry_mass_kg + request.vehicle.launch_payload_kg
    pickup_delta = (
        request.vehicle.pickup_payload_kg if any(step.action == "pickup" for step in steps) else 0.0
    )
    loaded_mass = launch_mass + pickup_delta
    thrust_to_weight = request.vehicle.max_total_thrust_n / (loaded_mass * GRAVITY)
    trajectory_speed_mps = max(
        (point.speed_limit_mps for point in points),
        default=request.vehicle.max_speed_mps,
    )
    braking_distance = (
        trajectory_speed_mps**2 / (2 * request.vehicle.max_acceleration_mps2)
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
                    f"Post-pickup thrust-to-weight must remain at least {MIN_THRUST_TO_WEIGHT:.2f}."
                ),
            )
        )
    if braking_distance > scene.minimum_clearance_m:
        issues.append(
            ValidationIssue(
                code="trajectory.braking-envelope-exceeds-clearance",
                severity="error",
                message=(
                    "The stopping envelope is larger than the scene's verified minimum clearance."
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
    if scene_id in {"school-campus-v1", "stairwell-coffee-return"} and perception == "vision":
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
        "intent": request.natural_language,
        "scene_id": scene_id,
        "perception_mode": perception,
        "steps": [step.model_dump(mode="json") for step in steps],
        "task_graph": task_graph.model_dump(mode="json"),
        "vehicle": request.vehicle.model_dump(mode="json"),
    }
    digest = hashlib.sha256(
        json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    contract = MissionContract(
        contract_id=f"mission-{digest[:20]}",
        edition=request.edition,
        execution_target=request.execution_target,
        scene_id=scene_id,
        perception_mode=perception,
        intent=request.natural_language,
        steps=steps,
        task_graph=task_graph,
        immutable_safety_rules=[
            (
                "A language or vision model may propose mission goals but cannot issue "
                "actuator commands."
            ),
            ("Every trajectory must pass geometry, dynamics, payload and edition-policy checks."),
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
            math.dist((a.x, a.y, a.z), (b.x, b.y, b.z)) / min(a.speed_limit_mps, b.speed_limit_mps)
            for a, b in zip(points, points[1:], strict=False)
        ),
        minimum_clearance_m=scene.minimum_clearance_m,
        launch_mass_kg=launch_mass,
        post_pickup_mass_kg=loaded_mass,
        post_pickup_thrust_to_weight=thrust_to_weight,
        braking_distance_m=braking_distance,
    )
    return AutonomyCompileResponse(
        scene=scene,
        contract=contract,
        trajectory=points,
        feasible=feasible,
        issues=issues,
        metrics=metrics,
        execution_policy=_policy(request, feasible),
        planner={
            "semantic_layer": "bounded-natural-language-contract-v1",
            "global_layer": "prevalidated-corridor-graph-v1",
            "trajectory_layer": "payload-aware-speed-profile-v1",
            "safety_layer": "deterministic-geometric-policy-kernel-v1",
        },
        runtime_profile=runtime_profile_for(request),
    )


__all__ = ["AutonomyCompileError", "compile_autonomy_mission"]
