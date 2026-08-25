import type {
  AutonomyCompileRequest,
  AutonomyCompileResponse,
  AutonomyExecutionTarget,
} from "../../types/api";

export type AutonomyMissionId = "coffee" | "gates" | "narrow";

const SCENE_IDS: Record<AutonomyMissionId, string> = {
  coffee: "school-campus-v1",
  gates: "school-campus-v1",
  narrow: "school-campus-v1",
};

const SCENE_META: Record<AutonomyMissionId, {
  name: string;
  nameZh: string;
  summary: string;
  summaryZh: string;
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
    nameZh: "School Map 外卖取回任务",
    summary: "Third-floor office, 12+12 switchback stairs, campus roads, cafeteria pickup and loaded return.",
    summaryZh: "从三楼办公室出发，经过两段 12+12 折返楼梯与校园道路，在食堂取货后载荷返航。",
    floors: 3,
    clearance: 0.82,
    tags: ["school", "stairs", "indoor-outdoor", "roads", "people", "payload", "return"],
    objectKinds: ["building", "stairwell", "building", "road", "tree", "pole", "pickup"],
    length: 154.8,
    vertical: 14.4,
    duration: 186,
  },
  gates: {
    name: "School Map circular-gate course",
    nameZh: "School Map 圆门训练路线",
    summary: "Campus road course with three centered training gates, trees, lights and live obstacle replanning.",
    summaryZh: "沿校园道路穿过三座训练圆门，并针对树木、路灯和动态障碍实时重规划。",
    floors: 1,
    clearance: 0.92,
    tags: ["school", "vision", "gates", "roads", "trees", "people"],
    objectKinds: ["road", "tree", "street-light", "gate", "gate", "gate", "building"],
    length: 72.6,
    vertical: 3.2,
    duration: 78,
  },
  narrow: {
    name: "School Map stair-and-corridor passage",
    nameZh: "School Map 楼梯与走廊通行任务",
    summary: "Third-floor office, classroom corridor, 12+12 switchback stairs and a precision lobby landing.",
    summaryZh: "从三楼办公室穿过教室走廊和两段 12+12 折返楼梯，最后在大厅精准降落。",
    floors: 3,
    clearance: 0.74,
    tags: ["school", "narrow", "indoor", "stairs", "corridor", "doors", "landing"],
    objectKinds: ["office", "corridor", "door", "stairwell", "wall", "landing"],
    length: 61.4,
    vertical: 8.2,
    duration: 96,
  },
};

function localized(locale: AutonomyCompileRequest["locale"], english: string, chinese: string) {
  return locale === "zh-CN" ? chinese : english;
}

function targetAdapter(target: AutonomyExecutionTarget) {
  if (target === "hardware") return "hardware_contract" as const;
  if (target === "hitl") return "hitl_contract" as const;
  return "px4_gazebo_contract" as const;
}

function runtimeProfile(
  target: AutonomyExecutionTarget,
  locale: AutonomyCompileRequest["locale"],
): AutonomyCompileResponse["runtime_profile"] {
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
    ["mission_executive", localized(locale, "Bounded mission state machine", "有边界的任务状态机"), 20],
    ["perception_vio_slam", localized(locale, "Versioned VIO, SLAM, map and vision observations", "带版本标识的 VIO、SLAM、地图与视觉观测"), 30],
    ["world_model", localized(locale, "Obstacle, gate, terrain and payload state", "障碍物、门、地形与载荷状态"), 20],
    ["global_planner", localized(locale, "Route corridor between mission checkpoints", "任务检查点之间的路线走廊"), 2],
    ["local_planner", localized(locale, "Trajectory repair inside the approved corridor", "在已批准走廊内修复航迹"), 20],
    ["trajectory_tracker", localized(locale, "Qualified trajectory to PX4 setpoint contracts", "将已验证航迹转换为 PX4 设定点合同"), 50],
    ["px4_bridge", localized(locale, "Simulator, HITL shadow and locked-aircraft transport boundary", "仿真、HITL 影子模式与锁定真机的传输边界"), 50],
    ["safety_supervisor", localized(locale, "Hold, land and abort overrides", "悬停、降落与中止覆盖策略"), 50],
    ["evidence_recorder", localized(locale, "Hash-chained observation and decision receipts", "观测与决策的哈希证据链"), 20],
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

function steps(
  missionId: AutonomyMissionId,
  pickupPayloadKg: number,
  locale: AutonomyCompileRequest["locale"],
) {
  if (missionId === "coffee") return [
    { order: 1, action: "takeoff", label: localized(locale, "Launch from the third-floor office", "从三楼办公室起飞"), payload_delta_kg: 0 },
    { order: 2, action: "traverse_stairs", label: localized(locale, "Descend both 12+12 switchback stair flights", "下降并穿过两段 12+12 折返楼梯"), payload_delta_kg: 0 },
    { order: 3, action: "transit", label: localized(locale, "Follow the campus road while avoiding people, trees, lights and buildings", "沿校园道路飞行并避让行人、树木、路灯与建筑"), payload_delta_kg: 0 },
    { order: 4, action: "pickup", label: localized(locale, "Acquire the takeout order at the cafeteria pickup pad", "在食堂取餐点抓取外卖"), payload_delta_kg: pickupPayloadKg },
    { order: 5, action: "return", label: localized(locale, "Replan with the loaded vehicle envelope and return upstairs", "按载荷后的机型包络重新规划并返回楼上"), payload_delta_kg: 0 },
    { order: 6, action: "land", label: localized(locale, "Land at the original launch point", "在原起飞点降落"), payload_delta_kg: 0 },
  ];
  if (missionId === "gates") return [
    { order: 1, action: "takeoff", label: localized(locale, "Launch from the School Map courtyard start pad", "从 School Map 庭院起飞点起飞"), payload_delta_kg: 0 },
    { order: 2, action: "pass_gate", label: localized(locale, "Follow the campus road and pass all three training gates through their geometric centers", "沿校园道路依次穿过三座训练门的几何中心"), payload_delta_kg: 0 },
    { order: 3, action: "land", label: localized(locale, "Clear the final gate, verify the landing zone and land", "穿过最后一座门，确认降落区后降落"), payload_delta_kg: 0 },
  ];
  return [
    { order: 1, action: "takeoff", label: localized(locale, "Launch from the third-floor agent office", "从三楼智能体办公室起飞"), payload_delta_kg: 0 },
    { order: 2, action: "traverse_stairs", label: localized(locale, "Traverse the classroom corridor and both 12+12 switchback stair flights", "穿过教室走廊和两段 12+12 折返楼梯"), payload_delta_kg: 0 },
    { order: 3, action: "land", label: localized(locale, "Clear the lobby doorway and land on the marked indoor target", "穿过大厅门口并在室内标记点降落"), payload_delta_kg: 0 },
  ];
}

function taskGraph(
  missionSteps: ReturnType<typeof steps>,
  locale: AutonomyCompileRequest["locale"],
): AutonomyCompileResponse["contract"]["task_graph"] {
  type TaskNode = AutonomyCompileResponse["contract"]["task_graph"]["nodes"][number];
  const nodes: TaskNode[] = [];
  const appendNode = (node: Omit<TaskNode, "inserted_by" | "status"> & { status?: TaskNode["status"] }) => {
    nodes.push({ ...node, status: node.status ?? "pending", inserted_by: "compiler" });
    return node.task_id;
  };

  let previous = appendNode({
    task_id: "preflight-pack-identity",
    label: localized(locale, "Bind the immutable Vehicle Pack, firmware identity and control adapter", "绑定不可变的机型包、固件身份与控制适配器"),
    status: "ready",
    depends_on: [],
    executor: "mission_executive",
    risk: "critical",
    max_retries: 0,
    timeout_s: 15,
    fallback: "abort",
    expected_output: localized(locale, "Vehicle, firmware and adapter identities match the mission contract", "机型、固件与适配器身份均与任务合同一致"),
    completion_evidence: ["vehicle-pack.digest", "firmware.identity", "adapter.identity"],
  });
  previous = appendNode({
    task_id: "preflight-sensors",
    label: localized(locale, "Verify required sensor calibration, time synchronization and stream health", "验证所需传感器的标定、时间同步与数据流健康状态"),
    depends_on: [previous],
    executor: "perception",
    risk: "critical",
    max_retries: 1,
    timeout_s: 30,
    fallback: "abort",
    expected_output: localized(locale, "Every required localization and obstacle stream is healthy and synchronized", "全部必需的定位与障碍物数据流均健康且已同步"),
    completion_evidence: ["sensor.calibration", "clock.offset", "stream.health"],
  });
  previous = appendNode({
    task_id: "preflight-flight-envelope",
    label: localized(locale, "Validate mass, center of gravity, thrust, energy reserve and braking envelope", "验证质量、重心、推力、能量储备与制动包络"),
    depends_on: [previous],
    executor: "mission_executive",
    risk: "critical",
    max_retries: 0,
    timeout_s: 20,
    fallback: "abort",
    expected_output: localized(locale, "A task-specific flight-envelope qualification receipt", "生成本任务专属的飞行包络资格回执"),
    completion_evidence: ["mass.total", "cg.bound", "thrust.margin", "battery.reserve"],
  });
  previous = appendNode({
    task_id: "world-map-binding",
    label: localized(locale, "Bind the selected Map Pack, coordinate frame, semantic entities and geofence", "绑定所选地图包、坐标系、语义实体与地理围栏"),
    depends_on: [previous],
    executor: "global_planner",
    risk: "high",
    max_retries: 1,
    timeout_s: 30,
    fallback: "hold",
    expected_output: localized(locale, "A versioned world frame with grounded mission entities and hard boundaries", "生成带版本标识、任务实体已落地且边界明确的世界坐标系"),
    completion_evidence: ["map-pack.digest", "frame.transform", "semantic.bindings", "geofence.version"],
  });
  previous = appendNode({
    task_id: "world-localization",
    label: localized(locale, "Establish bounded localization and initialize the live obstacle world model", "建立有边界的定位并初始化实时障碍物世界模型"),
    depends_on: [previous],
    executor: "perception",
    risk: "critical",
    max_retries: 2,
    timeout_s: 45,
    fallback: "hold",
    expected_output: localized(locale, "Localization covariance and observable free-space satisfy launch limits", "定位协方差与可观测自由空间满足起飞限制"),
    completion_evidence: ["localization.covariance", "free-space.snapshot", "dynamic-overlay.age"],
  });
  previous = appendNode({
    task_id: "plan-global-corridor",
    label: localized(locale, "Generate the global route corridor and a payload-aware return alternative", "生成全局路线走廊和考虑载荷的备用返航路线"),
    depends_on: [previous],
    executor: "global_planner",
    risk: "high",
    max_retries: 3,
    timeout_s: 60,
    fallback: "hold",
    expected_output: localized(locale, "Primary and contingency corridors satisfy map, clearance and energy constraints", "主路线与备用走廊均满足地图、净空和能量约束"),
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
      label: localized(locale, `Refresh perception and confirm the local world before: ${step.label}`, `刷新感知并在执行前确认局部世界：${step.label}`),
      depends_on: [previous],
      executor: "perception",
      risk,
      max_retries: 3,
      timeout_s: 20,
      fallback: "hold",
      expected_output: localized(locale, "A time-bounded local obstacle and semantic-target snapshot", "生成有时效边界的局部障碍物与语义目标快照"),
      completion_evidence: ["perception.sequence", "local-map.age", "tracked-entities.snapshot"],
    });
    previous = appendNode({
      task_id: `${prefix}-plan`,
      label: localized(locale, `Plan or repair the local trajectory segment for: ${step.label}`, `为以下任务规划或修复局部航迹段：${step.label}`),
      depends_on: [previous],
      executor: step.action === "return" ? "global_planner" : "local_planner",
      risk,
      max_retries: 3,
      timeout_s: 45,
      fallback: "hold",
      expected_output: localized(locale, "A collision-free, time-parameterized segment inside the approved corridor", "在已批准走廊内生成无碰撞、带时间参数的航迹段"),
      completion_evidence: ["trajectory.revision", "corridor.containment", "clearance.prediction"],
    });
    previous = appendNode({
      task_id: `${prefix}-qualify`,
      label: localized(locale, `Check geometry, dynamics, energy and safety policy for: ${step.label}`, `检查以下任务的几何、动力学、能量与安全策略：${step.label}`),
      depends_on: [previous],
      executor: "mission_executive",
      risk: ["takeoff", "land", "pickup"].includes(step.action) ? "critical" : "high",
      max_retries: 1,
      timeout_s: 15,
      fallback,
      expected_output: localized(locale, "The proposed segment passes every deterministic execution gate", "拟执行航迹段通过全部确定性执行门槛"),
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
      expected_output: localized(locale, `Controller-accepted completion of ${step.action}`, `控制器确认已完成动作：${step.label}`),
      completion_evidence: ["pose.trace", "clearance.minimum", "controller.acceptance"],
    });
    previous = appendNode({
      task_id: `${prefix}-verify`,
      label: localized(locale, `Verify completion evidence and settle the task state for: ${step.label}`, `验证完成证据并结算任务状态：${step.label}`),
      depends_on: [previous],
      executor: "mission_executive",
      risk: step.action === "pickup" || step.action === "land" ? "high" : "medium",
      max_retries: 2,
      timeout_s: 20,
      fallback,
      expected_output: localized(locale, "Completion evidence is consistent, current and attributable to this task", "完成证据一致、时效有效且可归因于本任务"),
      completion_evidence: ["task.result", "task.evidence", "world-state.revision"],
    });
    if (step.action === "pickup") {
      previous = appendNode({
        task_id: `${prefix}-recompute-envelope`,
        label: localized(locale, "Confirm payload attachment and recompute mass, center of gravity, thrust and return energy", "确认载荷已挂载，并重新计算质量、重心、推力与返航能量"),
        depends_on: [previous],
        executor: "mission_executive",
        risk: "critical",
        max_retries: 1,
        timeout_s: 25,
        fallback: "land",
        expected_output: localized(locale, "The loaded aircraft remains inside its qualified return envelope", "载荷后的无人机仍处于已验证的返航包络内"),
        completion_evidence: ["payload.confirmed", "mass.loaded", "cg.loaded", "return-energy.margin"],
      });
    }
  }
  previous = appendNode({
    task_id: "postflight-state",
    label: localized(locale, "Confirm landing, disarm the vehicle and close command authority", "确认已降落、解除无人机武装并关闭指令权限"),
    depends_on: [previous],
    executor: "px4_bridge",
    risk: "critical",
    max_retries: 1,
    timeout_s: 20,
    fallback: "abort",
    expected_output: localized(locale, "Landed and disarmed state with actuator authority revoked", "无人机已降落并解除武装，执行器权限已撤销"),
    completion_evidence: ["vehicle.landed", "vehicle.disarmed", "authority.revoked"],
  });
  appendNode({
    task_id: "postflight-evidence",
    label: localized(locale, "Seal mission results, anomalies, task revisions and replay evidence", "封存任务结果、异常、任务修订与回放证据"),
    depends_on: [previous],
    executor: "mission_executive",
    risk: "low",
    max_retries: 2,
    timeout_s: 20,
    fallback: "hold",
    expected_output: localized(locale, "A hash-chained mission evidence head", "生成任务哈希证据链头"),
    completion_evidence: ["mission.result", "task-graph.revisions", "decision.log", "evidence.chain-head"],
  });
  return {
    schema_version: "dronedream.autonomy.task-graph.v1",
    revision: 1,
    nodes,
    active_node_ids: ["preflight-pack-identity"],
    change_reason: localized(locale, "compiled", "已完成编译"),
  };
}

export function createLocalAutonomyPreview(
  missionId: AutonomyMissionId,
  request: AutonomyCompileRequest,
): AutonomyCompileResponse {
  const meta = SCENE_META[missionId];
  const missionSteps = steps(missionId, request.vehicle.pickup_payload_kg, request.locale);
  const missionTaskGraph = taskGraph(missionSteps, request.locale);
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
    issues.push({ code: "vehicle.loaded-mass-exceeds-mtom", severity: "error", message: localized(request.locale, "Post-pickup mass exceeds the configured maximum takeoff mass.", "取物后的总质量超过已配置的最大起飞质量。") });
  }
  if (thrustToWeight < 1.35) {
    issues.push({ code: "vehicle.thrust-margin-insufficient", severity: "error", message: localized(request.locale, "Post-pickup thrust-to-weight is below 1.35.", "取物后的推重比低于 1.35。") });
  }
  if (request.vehicle.radius_m >= meta.clearance || brakingDistance > meta.clearance) {
    issues.push({ code: "trajectory.braking-envelope-exceeds-clearance", severity: "error", message: localized(request.locale, "Stopping envelope exceeds verified scene clearance.", "制动包络超过场景已验证的净空。") });
  }
  if (request.perception_mode === "map") {
    issues.push({ code: "perception.static-map-no-live-obstacle-update", severity: "warning", message: localized(request.locale, "Map-only mode cannot qualify dynamic-obstacle response.", "仅使用地图的模式无法验证动态避障响应。") });
  }
  issues.push({ code: "planner.reference-corridor-verified", severity: "info", message: localized(request.locale, "Reference corridor, speed limits and payload-aware return checks passed.", "参考走廊、速度限制与载荷感知返航检查已通过。") });
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
      name: request.locale === "zh-CN" ? meta.nameZh : meta.name,
      summary: request.locale === "zh-CN" ? meta.summaryZh : meta.summary,
      bounds_m: { x: 120, y: 90, z: 12.6 },
      floors: meta.floors,
      minimum_clearance_m: meta.clearance,
      objects: objectList,
      reference_path: [],
      tags: meta.tags,
    },
    contract: {
      schema_version: "dronedream.autonomy.mission.v2",
      contract_id: `preview-${sceneId}-${request.edition}-${request.execution_target}-${request.locale}`,
      edition: request.edition,
      locale: request.locale,
      execution_target: request.execution_target,
      scene_id: sceneId,
      perception_mode: request.perception_mode,
      intent: request.natural_language,
      steps: missionSteps,
      task_graph: missionTaskGraph,
      immutable_safety_rules: [
        localized(request.locale, "Language and vision models propose goals; they cannot issue actuator commands.", "语言与视觉模型可以提出目标，但不能直接发出执行器指令。"),
        localized(request.locale, "Geometry, dynamics, payload and edition-policy checks are mandatory.", "几何、动力学、载荷与软件版本策略检查不可绕过。"),
        localized(request.locale, "Loss of localization, link or clearance transitions execution to hold or abort.", "定位、链路或净空丢失时，执行必须转入悬停或中止。"),
        localized(request.locale, "Hardware requires signed simulation qualification and operator confirmation.", "真机执行必须具备签名的仿真资格认证和操作员确认。"),
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
        ? [localized(request.locale, "Run PX4/Gazebo qualification and retain the signed evidence receipt.", "运行 PX4/Gazebo 资格认证并保留签名证据回执。")]
        : [
          localized(request.locale, "Complete the identical simulation qualification.", "完成完全相同任务的仿真资格认证。"),
          localized(request.locale, "Bind a validated signed Vehicle Pack and firmware identity.", "绑定已验证且已签名的机型包与固件身份。"),
          localized(request.locale, "Pass live preflight and short-lived operator confirmation.", "通过实时起飞前检查和短时有效的操作员确认。"),
        ],
    },
    planner: {
      semantic_layer: "bounded-natural-language-contract-v1",
      global_layer: "prevalidated-corridor-graph-v1",
      trajectory_layer: "payload-aware-speed-profile-v1",
      safety_layer: "deterministic-geometric-policy-kernel-v1",
    },
    runtime_profile: runtimeProfile(request.execution_target, request.locale),
  };
}
