import type { BrandEditionId } from "../../brand/edition-brand.generated";
import type {
  AutonomyHarnessInspectRequest,
  AutonomyHarnessInspectResponse,
} from "../../types/api";
import {
  autonomyAircraftRadiusM,
  type AutonomyWorkspaceState,
} from "./workspaceStore";

export type AutonomyPlannerArtifactStatus =
  | "needs_assets"
  | "needs_input"
  | "draft"
  | "blocked";

export type AutonomyPlannerAction =
  | "resolve"
  | "takeoff"
  | "navigate"
  | "traverse"
  | "pickup"
  | "inspect"
  | "return"
  | "land"
  | "abort";

export interface AutonomyPlannerTaskNode {
  node_id: string;
  action: AutonomyPlannerAction;
  target: string;
  depends_on: string[];
  success_evidence: string[];
}

export interface AutonomyPlannerTaskGraph {
  nodes: AutonomyPlannerTaskNode[];
}

export interface AutonomyPlannerArtifact {
  schema_version: "dronedream.autonomy.planner-response.v1";
  status: AutonomyPlannerArtifactStatus;
  goal: string;
  asset_bindings: {
    aircraft_id: string;
    aircraft_version: number;
    map_id: string;
    map_version: number;
    context_sha256: string;
  };
  grounded_entities: Array<Record<string, unknown>>;
  task_graph: AutonomyPlannerTaskGraph;
  tool_requests: Array<Record<string, unknown>>;
  tool_receipts: Array<Record<string, unknown>>;
  assumptions: string[];
  blockers: string[];
  repair: {
    attempt: number;
    max_attempts: number;
    repeated_plan_hashes: number;
    stop_reason: string | null;
  };
  safety_policy: {
    actuator_authority: false;
    may_relax_constraints: false;
    execution_requires_deterministic_validation: true;
  };
}

const INSPECTION_TOOLS = [
  "vehicle.inspect_binding",
  "map.inspect_binding",
  "mission.validate_asset_readiness",
] as const;

const PLANNING_TOOLS = [
  "map.resolve_entity",
  "route.query_topology",
  "route.plan_global_corridor",
  "trajectory.plan_segment",
  "mission.validate_plan",
] as const;

function canonicalJson(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(canonicalJson).join(",")}]`;
  if (value && typeof value === "object") {
    return `{${Object.entries(value as Record<string, unknown>)
      .sort(([left], [right]) => left.localeCompare(right))
      .map(([key, item]) => `${JSON.stringify(key)}:${canonicalJson(item)}`)
      .join(",")}}`;
  }
  return JSON.stringify(value);
}

export async function autonomyCanonicalSha256(value: unknown): Promise<string> {
  const bytes = new TextEncoder().encode(canonicalJson(value));
  const digest = await crypto.subtle.digest("SHA-256", bytes);
  return [...new Uint8Array(digest)]
    .map((byte) => byte.toString(16).padStart(2, "0"))
    .join("");
}

export function autonomyHarnessRequest(
  edition: BrandEditionId,
  workspace: AutonomyWorkspaceState,
  naturalLanguage: string,
): AutonomyHarnessInspectRequest {
  const localizationSources = workspace.aircraft.sensors
    .filter((sensor) => sensor === "gps" || sensor === "vio");
  return {
    schema_version: "dronedream.autonomy.harness-inspect.v1",
    edition,
    natural_language: naturalLanguage.slice(0, 2_000),
    aircraft: {
      kind: "aircraft",
      asset_id: workspace.aircraft.id,
      name: workspace.aircraft.name,
      version: workspace.aircraft.version,
      status: workspace.aircraft.status,
      content_hash: workspace.aircraft.qualificationContentHash,
      qualification_receipt_id: workspace.aircraft.qualificationReceiptId,
      capabilities: {
        body_radius_m: autonomyAircraftRadiusM(workspace.aircraft),
        dry_mass_kg: workspace.aircraft.dryMassKg,
        maximum_takeoff_mass_kg: workspace.aircraft.maximumTakeoffMassKg,
        maximum_thrust_n: workspace.aircraft.maximumThrustN,
        maximum_speed_mps: workspace.aircraft.maximumSpeedMps,
        maximum_acceleration_mps2: workspace.aircraft.maximumAccelerationMps2,
        maximum_pickup_payload_kg: workspace.aircraft.maximumPickupPayloadKg,
        reserve_battery_percent: workspace.aircraft.reserveBatteryPercent,
        localization_sources: localizationSources,
      },
    },
    map_pack: {
      kind: "map",
      asset_id: workspace.mapPack.id,
      name: workspace.mapPack.name,
      version: workspace.mapPack.version,
      status: workspace.mapPack.status,
      content_hash: workspace.mapPack.contentHash,
      qualification_receipt_id: workspace.mapPack.qualificationReceiptId,
      capabilities: {
        representation: workspace.mapPack.representation,
        coordinate_frame: workspace.mapPack.coordinateFrame,
        resolution_m: workspace.mapPack.resolutionM,
        floor_count: workspace.mapPack.floorCount,
        bounds_x_m: workspace.mapPack.boundsM.x,
        bounds_y_m: workspace.mapPack.boundsM.y,
        bounds_z_m: workspace.mapPack.boundsM.z,
        confidence_percent: workspace.mapPack.confidencePercent,
        live_updates: workspace.mapPack.liveUpdates,
        origin_latitude: workspace.mapPack.origin.latitude,
        origin_longitude: workspace.mapPack.origin.longitude,
        origin_altitude_m: workspace.mapPack.origin.altitudeM,
        semantic_layers: workspace.mapPack.semanticLayers,
        planning_layers: workspace.mapPack.planningLayers,
        compiler_scene_id: workspace.mapPack.compilerSceneId,
      },
    },
  };
}

function localIssues(request: AutonomyHarnessInspectRequest): {
  aircraft: string[];
  map: string[];
} {
  const aircraft: string[] = [];
  const map: string[] = [];
  if (!(["validated-unsigned", "signed"] as string[]).includes(request.aircraft.status)) {
    aircraft.push("aircraft.pack.not-validated");
  }
  if (!request.aircraft.qualification_receipt_id) {
    aircraft.push("aircraft.qualification-receipt.missing");
  }
  if (!request.aircraft.content_hash) aircraft.push("aircraft.content-hash.missing");
  aircraft.push("aircraft.qualification-registry.unavailable");
  const localization = request.aircraft.capabilities.localization_sources;
  if (!Array.isArray(localization) || localization.length === 0) {
    aircraft.push("aircraft.localization-source.missing");
  }
  if (request.map_pack.status !== "qualified") map.push("map.pack.not-qualified");
  if (!request.map_pack.content_hash) map.push("map.content-hash.missing");
  if (!request.map_pack.qualification_receipt_id) map.push("map.qualification-receipt.missing");
  map.push("map.qualification-registry.unavailable");
  const planningLayers = request.map_pack.capabilities.planning_layers;
  if (
    !Array.isArray(planningLayers)
    || !planningLayers.includes("collision-geometry")
    || !planningLayers.includes("occupancy")
  ) {
    map.push("map.collision-layers.missing");
  }
  if (!request.map_pack.capabilities.compiler_scene_id) map.push("map.compiler-scene.unbound");
  return { aircraft, map };
}

export async function localAutonomyHarnessInspection(
  request: AutonomyHarnessInspectRequest,
): Promise<AutonomyHarnessInspectResponse> {
  const issues = localIssues(request);
  const blockers = [...new Set([...issues.aircraft, ...issues.map])].sort();
  const planningReady = blockers.length === 0;
  const receipt = (toolId: string, toolIssues: string[], evidence: Record<string, string | number | boolean | string[] | null>) => ({
    tool_id: toolId,
    tool_version: "1.0.0",
    outcome: toolIssues.length ? "blocked" as const : "accepted" as const,
    evidence,
    issue_codes: toolIssues,
  });
  return {
    schema_version: "dronedream.autonomy.harness-context.v1",
    prompt_version: "dronedream.autonomy.system.v1",
    tool_registry_version: "dronedream.autonomy.tools.v1",
    context_sha256: await autonomyCanonicalSha256({ request, blockers }),
    status: planningReady ? "draft" : "needs_assets",
    planning_ready: planningReady,
    blockers,
    required_next_actions: [
      ...(issues.aircraft.length ? ["Validate and save a qualified Vehicle Pack."] : []),
      ...(issues.map.length ? ["Import, compile, and qualify a planning-capable Map Pack."] : []),
    ],
    eligible_tool_ids: planningReady
      ? [...INSPECTION_TOOLS, ...PLANNING_TOOLS]
      : [...INSPECTION_TOOLS],
    tool_receipts: [
      receipt("vehicle.inspect_binding", issues.aircraft, {
        asset_id: request.aircraft.asset_id,
        version: request.aircraft.version,
        status: request.aircraft.status,
      }),
      receipt("map.inspect_binding", issues.map, {
        asset_id: request.map_pack.asset_id,
        version: request.map_pack.version,
        status: request.map_pack.status,
      }),
      receipt("mission.validate_asset_readiness", blockers, {
        one_aircraft_bound: true,
        one_map_bound: true,
        planning_ready: planningReady,
      }),
    ],
    repair_policy: {
      schema_version: "dronedream.autonomy.repair-policy.v1",
      semantic_attempt_limit: 3,
      trajectory_attempt_limit: 5,
      repeated_plan_hash_limit: 2,
      may_relax_safety_constraints: false,
    },
  };
}

export function autonomyModelContext(
  request: AutonomyHarnessInspectRequest,
  inspection: AutonomyHarnessInspectResponse,
): Record<string, unknown> {
  return {
    schema_version: inspection.schema_version,
    prompt_version: inspection.prompt_version,
    tool_registry_version: inspection.tool_registry_version,
    context_sha256: inspection.context_sha256,
    planning_ready: inspection.planning_ready,
    blockers: inspection.blockers,
    required_next_actions: inspection.required_next_actions,
    eligible_tool_ids: inspection.eligible_tool_ids,
    tool_receipts: inspection.tool_receipts,
    repair_policy: inspection.repair_policy,
    selected_aircraft: request.aircraft,
    selected_map: request.map_pack,
  };
}

export function parseAutonomyPlannerArtifact(value: unknown): AutonomyPlannerArtifact | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  const artifact = value as Partial<AutonomyPlannerArtifact>;
  if (
    artifact.schema_version !== "dronedream.autonomy.planner-response.v1"
    || !["needs_assets", "needs_input", "draft", "blocked"].includes(String(artifact.status))
    || typeof artifact.goal !== "string"
    || !artifact.asset_bindings
    || !artifact.repair
    || !artifact.safety_policy
    || artifact.safety_policy.actuator_authority !== false
    || artifact.safety_policy.may_relax_constraints !== false
    || artifact.safety_policy.execution_requires_deterministic_validation !== true
    || !Array.isArray(artifact.grounded_entities)
    || !Array.isArray(artifact.tool_requests)
    || !Array.isArray(artifact.tool_receipts)
    || !Array.isArray(artifact.assumptions)
    || !Array.isArray(artifact.blockers)
    || !validPlannerTaskGraph(artifact.task_graph, artifact.status === "draft")
  ) return null;
  const bindings = artifact.asset_bindings;
  if (
    typeof bindings.aircraft_id !== "string"
    || !bindings.aircraft_id
    || !Number.isSafeInteger(bindings.aircraft_version)
    || bindings.aircraft_version < 1
    || typeof bindings.map_id !== "string"
    || !bindings.map_id
    || !Number.isSafeInteger(bindings.map_version)
    || bindings.map_version < 1
    || typeof bindings.context_sha256 !== "string"
    || !/^[0-9a-f]{64}$/u.test(bindings.context_sha256)
  ) return null;
  if (
    !Number.isSafeInteger(artifact.repair.attempt)
    || artifact.repair.attempt < 0
    || artifact.repair.attempt > 3
    || artifact.repair.max_attempts !== 3
    || !Number.isSafeInteger(artifact.repair.repeated_plan_hashes)
    || artifact.repair.repeated_plan_hashes < 0
    || artifact.repair.repeated_plan_hashes > 2
    || artifact.repair.repeated_plan_hashes > artifact.repair.attempt
    || (artifact.repair.stop_reason !== null
      && typeof artifact.repair.stop_reason !== "string")
  ) return null;
  return artifact as AutonomyPlannerArtifact;
}

const PLANNER_ACTIONS = new Set<AutonomyPlannerAction>([
  "resolve",
  "takeoff",
  "navigate",
  "traverse",
  "pickup",
  "inspect",
  "return",
  "land",
  "abort",
]);

function validPlannerTaskGraph(value: unknown, requireNodes: boolean): value is AutonomyPlannerTaskGraph {
  if (!value || typeof value !== "object" || Array.isArray(value)) return false;
  const graph = value as Partial<AutonomyPlannerTaskGraph>;
  if (!Array.isArray(graph.nodes) || graph.nodes.length > 64) return false;
  if (requireNodes && graph.nodes.length === 0) return false;
  const identifiers = new Set<string>();
  for (const node of graph.nodes) {
    if (
      !node
      || typeof node !== "object"
      || Array.isArray(node)
      || Object.keys(node).sort().join("\0")
        !== "action\0depends_on\0node_id\0success_evidence\0target"
      || typeof node.node_id !== "string"
      || !/^[a-z0-9][a-z0-9-]{0,63}$/u.test(node.node_id)
      || identifiers.has(node.node_id)
      || typeof node.action !== "string"
      || !PLANNER_ACTIONS.has(node.action as AutonomyPlannerAction)
      || typeof node.target !== "string"
      || node.target.trim().length === 0
      || node.target.length > 160
      || !Array.isArray(node.depends_on)
      || node.depends_on.length > 16
      || node.depends_on.some((dependency) => (
        typeof dependency !== "string"
        || !/^[a-z0-9][a-z0-9-]{0,63}$/u.test(dependency)
      ))
      || new Set(node.depends_on).size !== node.depends_on.length
      || !Array.isArray(node.success_evidence)
      || node.success_evidence.length < 1
      || node.success_evidence.length > 16
      || node.success_evidence.some((evidence) => (
        typeof evidence !== "string" || !evidence.trim() || evidence.length > 120
      ))
    ) return false;
    identifiers.add(node.node_id);
  }
  if (graph.nodes.some((node) => node.depends_on.some((dependency) => !identifiers.has(dependency)))) {
    return false;
  }
  const remaining = new Map(graph.nodes.map((node) => [node.node_id, new Set(node.depends_on)]));
  while (remaining.size > 0) {
    const roots = [...remaining.entries()]
      .filter(([, dependencies]) => dependencies.size === 0)
      .map(([nodeId]) => nodeId);
    if (roots.length === 0) return false;
    roots.forEach((nodeId) => remaining.delete(nodeId));
    remaining.forEach((dependencies) => roots.forEach((nodeId) => dependencies.delete(nodeId)));
  }
  return true;
}

export function autonomyPlannerBindingIssues(
  artifact: AutonomyPlannerArtifact,
  request: AutonomyHarnessInspectRequest,
  inspection: AutonomyHarnessInspectResponse,
): string[] {
  const issues: string[] = [];
  if (artifact.status !== "draft") issues.push(`planner.status.${artifact.status}`);
  if (artifact.asset_bindings.aircraft_id !== request.aircraft.asset_id) {
    issues.push("planner.aircraft-id.mismatch");
  }
  if (artifact.asset_bindings.aircraft_version !== request.aircraft.version) {
    issues.push("planner.aircraft-version.mismatch");
  }
  if (artifact.asset_bindings.map_id !== request.map_pack.asset_id) {
    issues.push("planner.map-id.mismatch");
  }
  if (artifact.asset_bindings.map_version !== request.map_pack.version) {
    issues.push("planner.map-version.mismatch");
  }
  if (artifact.asset_bindings.context_sha256 !== inspection.context_sha256) {
    issues.push("planner.context-hash.mismatch");
  }
  const actions = new Set(artifact.task_graph.nodes.map((node) => node.action));
  if (!actions.has("takeoff")) issues.push("planner.task-graph.takeoff-missing");
  if (!actions.has("land")) issues.push("planner.task-graph.land-missing");
  const pickupRequested = /pickup|takeout|collect|retrieve|取物|取餐|外卖/iu
    .test(request.natural_language);
  const returnRequested = /return|come back|返航|返回|回来/iu
    .test(request.natural_language);
  if (pickupRequested && !actions.has("pickup")) {
    issues.push("planner.task-graph.pickup-missing");
  }
  if (returnRequested && !actions.has("return")) {
    issues.push("planner.task-graph.return-missing");
  }
  if (
    pickupRequested
    && returnRequested
    && request.aircraft.asset_id === "aircraft-my-drone"
    && request.map_pack.asset_id === "map-school"
  ) {
    const canonicalTargets = new Set([
      "takeoff:office-drone-launch-pad",
      "pickup:takeout-pickup",
      "return:office-drone-launch-pad",
      "land:office-drone-launch-pad",
    ]);
    const boundTargets = new Set(
      artifact.task_graph.nodes.map((node) => `${node.action}:${node.target}`),
    );
    canonicalTargets.forEach((binding) => {
      if (!boundTargets.has(binding)) issues.push(`planner.route-target.missing.${binding}`);
    });
  }
  if (artifact.blockers.length > 0) issues.push("planner.blockers.present");
  return issues;
}

export function autonomyAssetBlockerMessage(
  inspection: AutonomyHarnessInspectResponse,
  chinese: boolean,
): string {
  if (inspection.planning_ready) {
    return chinese
      ? "已绑定当前无人机与地图，正在生成可验证的任务草案。"
      : "The selected aircraft and map are bound; a verifiable mission draft can now be prepared.";
  }
  const missingAircraft = inspection.blockers.some((code) => code.startsWith("aircraft."));
  const missingMap = inspection.blockers.some((code) => code.startsWith("map."));
  if (chinese) {
    if (missingAircraft && missingMap) return "我已经保存这条任务指令，但当前无人机和地图尚未达到规划条件。请先完成无人机资格验证，并导入、编译和验证可用于碰撞规划的三维地图。";
    if (missingAircraft) return "我已经保存这条任务指令，但当前无人机缺少经过验证的能力与传感器合同。请先完成无人机配置和资格验证。";
    return "我已经保存这条任务指令，但当前地图缺少可验证的三维碰撞层、坐标或资格凭据。请先完成地图导入、编译和验证。";
  }
  if (missingAircraft && missingMap) return "I saved the mission intent, but neither the aircraft nor the map is qualified for planning. Validate the Vehicle Pack and import, compile, and qualify a collision-capable 3D Map Pack first.";
  if (missingAircraft) return "I saved the mission intent, but the selected aircraft lacks a qualified capability and sensor contract. Complete the aircraft configuration and qualification first.";
  return "I saved the mission intent, but the selected map lacks qualified 3D collision geometry, coordinates, or a qualification receipt. Complete map import, compilation, and qualification first.";
}
