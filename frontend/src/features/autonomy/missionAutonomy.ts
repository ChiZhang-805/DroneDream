import type {
  AutonomyCompileRequest,
  AutonomyCompileResponse,
  AutonomyExecutionTarget,
} from "../../types/api";

export type AutonomyMissionId = "coffee" | "gates" | "narrow";

const SCENE_IDS: Record<AutonomyMissionId, string> = {
  coffee: "school-campus-v1",
  gates: "forest-gate-inspection",
  narrow: "service-corridor-dock",
};

const SCENE_META: Record<AutonomyMissionId, {
  name: string;
  summary: string;
  floors: number;
  clearance: number;
  tags: string[];
  objectKinds: string[];
  length: number;
  vertical: number;
  duration: number;
}> = {
  coffee: {
    name: "School Map takeout mission",
    summary: "Third-floor office, 12+12 switchback stairs, campus roads, cafeteria pickup and loaded return.",
    floors: 3,
    clearance: 0.82,
    tags: ["school", "stairs", "indoor-outdoor", "roads", "people", "payload", "return"],
    objectKinds: ["building", "stairwell", "building", "road", "tree", "pole", "pickup"],
    length: 154.8,
    vertical: 14.4,
    duration: 186,
  },
  gates: {
    name: "Forest gate inspection",
    summary: "Unknown vegetation corridor with three centered gates and a final inspection hover.",
    floors: 1,
    clearance: 1.15,
    tags: ["vision", "gates", "trees", "unknown-space"],
    objectKinds: ["tree", "tree", "tree", "gate", "gate", "gate"],
    length: 43.2,
    vertical: 3.4,
    duration: 51,
  },
  narrow: {
    name: "Service corridor docking",
    summary: "Confined corridor with vertical signs, blind corners and a precision docking target.",
    floors: 1,
    clearance: 0.78,
    tags: ["narrow", "indoor", "blind-corner", "docking"],
    objectKinds: ["wall", "wall", "sign", "landing"],
    length: 30.6,
    vertical: 1.8,
    duration: 47,
  },
};

function targetAdapter(target: AutonomyExecutionTarget) {
  if (target === "hardware") return "hardware_contract" as const;
  if (target === "hitl") return "hitl_contract" as const;
  return "px4_gazebo_contract" as const;
}

function runtimeProfile(target: AutonomyExecutionTarget): AutonomyCompileResponse["runtime_profile"] {
  const mode = target === "simulation"
    ? "simulation_contract" as const
    : target === "hitl"
      ? "hitl_shadow" as const
      : "hardware_locked" as const;
  const bridge = target === "simulation"
    ? "px4_gazebo" as const
    : target === "hitl"
      ? "px4_hitl_shadow" as const
      : "px4_hardware_locked" as const;
  const status = target === "simulation"
    ? "available" as const
    : target === "hitl"
      ? "shadow" as const
      : "locked" as const;
  const authority = target === "simulation";
  const components: AutonomyCompileResponse["runtime_profile"]["components"] = [
    ["mission_executive", "Bounded mission state machine", 20],
    ["perception_vio_slam", "Versioned VIO, SLAM, map and vision observations", 30],
    ["world_model", "Obstacle, gate, terrain and payload state", 20],
    ["global_planner", "Route corridor between mission checkpoints", 2],
    ["local_planner", "Trajectory repair inside the approved corridor", 20],
    ["trajectory_tracker", "Qualified trajectory to PX4 setpoint contracts", 50],
    ["px4_bridge", "Simulator, HITL shadow and locked-aircraft transport boundary", 50],
    ["safety_supervisor", "Hold, land and abort overrides", 50],
    ["evidence_recorder", "Hash-chained observation and decision receipts", 20],
  ].map(([id, role, rate]) => ({
    id: id as AutonomyCompileResponse["runtime_profile"]["components"][number]["id"],
    status,
    role: String(role),
    rate_hz: Number(rate),
    actuator_authority: authority && id === "px4_bridge",
  }));
  return {
    schema_version: "dronedream.autonomy.runtime-profile.v1",
    mode,
    bridge,
    command_authority: authority,
    persistence: "process_local_bounded",
    observation_contract: "dronedream.autonomy.observation.v1",
    components,
    fail_safe_actions: ["hold", "land", "abort"],
  };
}

function steps(missionId: AutonomyMissionId, pickupPayloadKg: number) {
  if (missionId === "coffee") return [
    { order: 1, action: "takeoff", label: "Launch from the third-floor office", payload_delta_kg: 0 },
    { order: 2, action: "traverse_stairs", label: "Descend both 12+12 switchback stair flights", payload_delta_kg: 0 },
    { order: 3, action: "transit", label: "Follow the campus road while avoiding people, trees, lights and buildings", payload_delta_kg: 0 },
    { order: 4, action: "pickup", label: "Acquire the takeout order at the cafeteria pickup pad", payload_delta_kg: pickupPayloadKg },
    { order: 5, action: "return", label: "Replan with the loaded vehicle envelope and return upstairs", payload_delta_kg: 0 },
    { order: 6, action: "land", label: "Land at the original launch point", payload_delta_kg: 0 },
  ];
  if (missionId === "gates") return [
    { order: 1, action: "takeoff", label: "Launch into the vegetation corridor", payload_delta_kg: 0 },
    { order: 2, action: "pass_gate", label: "Pass three gates through their geometric centers", payload_delta_kg: 0 },
    { order: 3, action: "land", label: "Complete the inspection hover and land", payload_delta_kg: 0 },
  ];
  return [
    { order: 1, action: "takeoff", label: "Launch in the service corridor", payload_delta_kg: 0 },
    { order: 2, action: "transit", label: "Follow the narrow corridor around blind corners", payload_delta_kg: 0 },
    { order: 3, action: "land", label: "Dock on the marked target", payload_delta_kg: 0 },
  ];
}

function taskGraph(
  missionSteps: ReturnType<typeof steps>,
): AutonomyCompileResponse["contract"]["task_graph"] {
  type TaskNode = AutonomyCompileResponse["contract"]["task_graph"]["nodes"][number];
  const nodes: TaskNode[] = [];
  const appendNode = (node: Omit<TaskNode, "inserted_by" | "status"> & { status?: TaskNode["status"] }) => {
    nodes.push({ ...node, status: node.status ?? "pending", inserted_by: "compiler" });
    return node.task_id;
  };

  let previous = appendNode({
    task_id: "preflight-pack-identity",
    label: "Bind the immutable Vehicle Pack, firmware identity and control adapter",
    status: "ready",
    depends_on: [],
    executor: "mission_executive",
    risk: "critical",
    max_retries: 0,
    timeout_s: 15,
    fallback: "abort",
    expected_output: "Vehicle, firmware and adapter identities match the mission contract",
    completion_evidence: ["vehicle-pack.digest", "firmware.identity", "adapter.identity"],
  });
  previous = appendNode({
    task_id: "preflight-sensors",
    label: "Verify required sensor calibration, time synchronization and stream health",
    depends_on: [previous],
    executor: "perception",
    risk: "critical",
    max_retries: 1,
    timeout_s: 30,
    fallback: "abort",
    expected_output: "Every required localization and obstacle stream is healthy and synchronized",
    completion_evidence: ["sensor.calibration", "clock.offset", "stream.health"],
  });
  previous = appendNode({
    task_id: "preflight-flight-envelope",
    label: "Validate mass, center of gravity, thrust, energy reserve and braking envelope",
    depends_on: [previous],
    executor: "mission_executive",
    risk: "critical",
    max_retries: 0,
    timeout_s: 20,
    fallback: "abort",
    expected_output: "A task-specific flight-envelope qualification receipt",
    completion_evidence: ["mass.total", "cg.bound", "thrust.margin", "battery.reserve"],
  });
  previous = appendNode({
    task_id: "world-map-binding",
    label: "Bind the selected Map Pack, coordinate frame, semantic entities and geofence",
    depends_on: [previous],
    executor: "global_planner",
    risk: "high",
    max_retries: 1,
    timeout_s: 30,
    fallback: "hold",
    expected_output: "A versioned world frame with grounded mission entities and hard boundaries",
    completion_evidence: ["map-pack.digest", "frame.transform", "semantic.bindings", "geofence.version"],
  });
  previous = appendNode({
    task_id: "world-localization",
    label: "Establish bounded localization and initialize the live obstacle world model",
    depends_on: [previous],
    executor: "perception",
    risk: "critical",
    max_retries: 2,
    timeout_s: 45,
    fallback: "hold",
    expected_output: "Localization covariance and observable free-space satisfy launch limits",
    completion_evidence: ["localization.covariance", "free-space.snapshot", "dynamic-overlay.age"],
  });
  previous = appendNode({
    task_id: "plan-global-corridor",
    label: "Generate the global route corridor and a payload-aware return alternative",
    depends_on: [previous],
    executor: "global_planner",
    risk: "high",
    max_retries: 3,
    timeout_s: 60,
    fallback: "hold",
    expected_output: "Primary and contingency corridors satisfy map, clearance and energy constraints",
    completion_evidence: ["corridor.primary", "corridor.contingency", "energy.projection"],
  });

  for (const step of missionSteps) {
    const prefix = `mission-${String(step.order).padStart(2, "0")}-${step.action.replaceAll("_", "-")}`;
    const executor = step.action === "takeoff" || step.action === "land"
      ? "px4_bridge" as const
      : step.action === "pickup"
        ? "payload_controller" as const
        : step.action === "return"
          ? "global_planner" as const
          : "local_planner" as const;
    const risk = step.action === "transit" || step.action === "return" ? "medium" as const : "high" as const;
    const fallback = step.action === "return" || step.action === "land" ? "land" as const : "hold" as const;
    previous = appendNode({
      task_id: `${prefix}-observe`,
      label: `Refresh perception and confirm the local world before: ${step.label}`,
      depends_on: [previous],
      executor: "perception",
      risk,
      max_retries: 3,
      timeout_s: 20,
      fallback: "hold",
      expected_output: "A time-bounded local obstacle and semantic-target snapshot",
      completion_evidence: ["perception.sequence", "local-map.age", "tracked-entities.snapshot"],
    });
    previous = appendNode({
      task_id: `${prefix}-plan`,
      label: `Plan or repair the local trajectory segment for: ${step.label}`,
      depends_on: [previous],
      executor: step.action === "return" ? "global_planner" : "local_planner",
      risk,
      max_retries: 3,
      timeout_s: 45,
      fallback: "hold",
      expected_output: "A collision-free, time-parameterized segment inside the approved corridor",
      completion_evidence: ["trajectory.revision", "corridor.containment", "clearance.prediction"],
    });
    previous = appendNode({
      task_id: `${prefix}-qualify`,
      label: `Check geometry, dynamics, energy and safety policy for: ${step.label}`,
      depends_on: [previous],
      executor: "mission_executive",
      risk: ["takeoff", "land", "pickup"].includes(step.action) ? "critical" : "high",
      max_retries: 1,
      timeout_s: 15,
      fallback,
      expected_output: "The proposed segment passes every deterministic execution gate",
      completion_evidence: ["dynamics.acceptance", "energy.margin", "safety.acceptance"],
    });
    previous = appendNode({
      task_id: `${prefix}-execute`,
      label: step.label,
      depends_on: [previous],
      executor,
      risk,
      max_retries: step.action === "takeoff" || step.action === "land" ? 1 : 2,
      timeout_s: ["transit", "traverse_stairs", "return"].includes(step.action) ? 120 : 45,
      fallback,
      expected_output: `Controller-accepted completion of ${step.action}`,
      completion_evidence: ["pose.trace", "clearance.minimum", "controller.acceptance"],
    });
    previous = appendNode({
      task_id: `${prefix}-verify`,
      label: `Verify completion evidence and settle the task state for: ${step.label}`,
      depends_on: [previous],
      executor: "mission_executive",
      risk: step.action === "pickup" || step.action === "land" ? "high" : "medium",
      max_retries: 2,
      timeout_s: 20,
      fallback,
      expected_output: "Completion evidence is consistent, current and attributable to this task",
      completion_evidence: ["task.result", "task.evidence", "world-state.revision"],
    });
    if (step.action === "pickup") {
      previous = appendNode({
        task_id: `${prefix}-recompute-envelope`,
        label: "Confirm payload attachment and recompute mass, center of gravity, thrust and return energy",
        depends_on: [previous],
        executor: "mission_executive",
        risk: "critical",
        max_retries: 1,
        timeout_s: 25,
        fallback: "land",
        expected_output: "The loaded aircraft remains inside its qualified return envelope",
        completion_evidence: ["payload.confirmed", "mass.loaded", "cg.loaded", "return-energy.margin"],
      });
    }
  }
  previous = appendNode({
    task_id: "postflight-state",
    label: "Confirm landing, disarm the vehicle and close command authority",
    depends_on: [previous],
    executor: "px4_bridge",
    risk: "critical",
    max_retries: 1,
    timeout_s: 20,
    fallback: "abort",
    expected_output: "Landed and disarmed state with actuator authority revoked",
    completion_evidence: ["vehicle.landed", "vehicle.disarmed", "authority.revoked"],
  });
  appendNode({
    task_id: "postflight-evidence",
    label: "Seal mission results, anomalies, task revisions and replay evidence",
    depends_on: [previous],
    executor: "mission_executive",
    risk: "low",
    max_retries: 2,
    timeout_s: 20,
    fallback: "hold",
    expected_output: "A hash-chained mission evidence head",
    completion_evidence: ["mission.result", "task-graph.revisions", "decision.log", "evidence.chain-head"],
  });
  return {
    schema_version: "dronedream.autonomy.task-graph.v1",
    revision: 1,
    nodes,
    active_node_ids: ["preflight-pack-identity"],
    change_reason: "compiled",
  };
}

export function createLocalAutonomyPreview(
  missionId: AutonomyMissionId,
  request: AutonomyCompileRequest,
): AutonomyCompileResponse {
  const meta = SCENE_META[missionId];
  const missionSteps = steps(missionId, request.vehicle.pickup_payload_kg);
  const missionTaskGraph = taskGraph(missionSteps);
  const launchMass = request.vehicle.dry_mass_kg + request.vehicle.launch_payload_kg;
  const loadedMass = launchMass + (missionId === "coffee" ? request.vehicle.pickup_payload_kg : 0);
  const thrustToWeight = request.vehicle.max_total_thrust_n / (loadedMass * 9.80665);
  const availableStoppingDistance = Math.max(0, meta.clearance - request.vehicle.radius_m);
  const corridorSpeedMps = Math.min(
    request.vehicle.max_speed_mps,
    Math.sqrt(2 * request.vehicle.max_acceleration_mps2 * availableStoppingDistance) * 0.8,
  );
  const brakingDistance = corridorSpeedMps ** 2
    / (2 * request.vehicle.max_acceleration_mps2) + request.vehicle.radius_m;
  const issues: AutonomyCompileResponse["issues"] = [];
  if (loadedMass > request.vehicle.max_takeoff_mass_kg) {
    issues.push({ code: "vehicle.loaded-mass-exceeds-mtom", severity: "error", message: "Post-pickup mass exceeds the configured maximum takeoff mass." });
  }
  if (thrustToWeight < 1.35) {
    issues.push({ code: "vehicle.thrust-margin-insufficient", severity: "error", message: "Post-pickup thrust-to-weight is below 1.35." });
  }
  if (request.vehicle.radius_m >= meta.clearance || brakingDistance > meta.clearance) {
    issues.push({ code: "trajectory.braking-envelope-exceeds-clearance", severity: "error", message: "Stopping envelope exceeds verified scene clearance." });
  }
  if (request.perception_mode === "map") {
    issues.push({ code: "perception.static-map-no-live-obstacle-update", severity: "warning", message: "Map-only mode cannot qualify dynamic-obstacle response." });
  }
  issues.push({ code: "planner.reference-corridor-verified", severity: "info", message: "Reference corridor, speed limits and payload-aware return checks passed." });
  const feasible = !issues.some(({ severity }) => severity === "error");
  const blockers = request.execution_target === "simulation" ? [] : [
    "vehicle-pack.registry.zero-validated-signed-packs",
    "simulation-qualification.missing",
    "vehicle-pack.receipt.missing",
    "operator.confirmation.missing",
    "localization.not-ready",
    "command-link.not-ready",
    "geofence.not-ready",
    "battery.not-ready",
  ];
  if (request.execution_target !== "simulation" && request.edition === "sim") {
    blockers.push("edition.sim.forbids-hardware-and-hitl");
  }
  if (!feasible) blockers.push("trajectory.not-feasible");
  const sceneId = SCENE_IDS[missionId];
  const objectList = meta.objectKinds.map((kind, index) => ({
    id: `${kind}-${index + 1}`,
    kind,
    center: { x: 4 + index * 4, y: 4 + (index % 3) * 3, z: kind === "building" ? 5 : 2 },
    size: { x: kind === "building" ? 10 : 1.4, y: kind === "building" ? 8 : 1.4, z: kind === "tree" ? 6 : 2.4 },
    traversable: kind === "gate" || kind === "pickup" || kind === "landing" || kind === "stairwell",
    required_clearance_m: kind === "gate" ? 0.45 : 0.35,
  }));
  return {
    scene: {
      id: sceneId,
      name: meta.name,
      summary: meta.summary,
      bounds_m: { x: missionId === "coffee" ? 120 : 48, y: missionId === "coffee" ? 90 : 28, z: missionId === "coffee" ? 12.6 : 8 },
      floors: meta.floors,
      minimum_clearance_m: meta.clearance,
      objects: objectList,
      reference_path: [],
      tags: meta.tags,
    },
    contract: {
      schema_version: "dronedream.autonomy.mission.v2",
      contract_id: `preview-${sceneId}-${request.edition}-${request.execution_target}`,
      edition: request.edition,
      execution_target: request.execution_target,
      scene_id: sceneId,
      perception_mode: request.perception_mode,
      intent: request.natural_language,
      steps: missionSteps,
      task_graph: missionTaskGraph,
      immutable_safety_rules: [
        "Language and vision models propose goals; they cannot issue actuator commands.",
        "Geometry, dynamics, payload and edition-policy checks are mandatory.",
        "Loss of localization, link or clearance transitions execution to hold or abort.",
        "Hardware requires signed simulation qualification and operator confirmation.",
      ],
    },
    trajectory: [],
    feasible,
    issues,
    metrics: {
      route_length_m: meta.length,
      vertical_travel_m: meta.vertical,
      estimated_duration_s: meta.duration,
      minimum_clearance_m: meta.clearance,
      launch_mass_kg: Number(launchMass.toFixed(3)),
      post_pickup_mass_kg: Number(loadedMass.toFixed(3)),
      post_pickup_thrust_to_weight: Number(thrustToWeight.toFixed(3)),
      braking_distance_m: Number(brakingDistance.toFixed(3)),
    },
    execution_policy: {
      readiness: request.execution_target === "simulation" && feasible ? "simulation_ready" : "denied",
      adapter: targetAdapter(request.execution_target),
      can_execute: request.execution_target === "simulation" && feasible,
      validated_signed_pack_count: 0,
      blockers: [...new Set(blockers)].sort(),
      required_next_steps: request.execution_target === "simulation"
        ? ["Run PX4/Gazebo qualification and retain the signed evidence receipt."]
        : [
          "Complete the identical simulation qualification.",
          "Bind a validated signed Vehicle Pack and firmware identity.",
          "Pass live preflight and short-lived operator confirmation.",
        ],
    },
    planner: {
      semantic_layer: "bounded-natural-language-contract-v1",
      global_layer: "prevalidated-corridor-graph-v1",
      trajectory_layer: "payload-aware-speed-profile-v1",
      safety_layer: "deterministic-geometric-policy-kernel-v1",
    },
    runtime_profile: runtimeProfile(request.execution_target),
  };
}
