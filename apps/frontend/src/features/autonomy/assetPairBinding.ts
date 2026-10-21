import type { AgentCoreAssetPairRuntimeContracts, AgentCoreAssetQualificationJob, AgentCoreAssetVersion } from "./agentCore";
import type { AutonomyAssetLibrary, AutonomyExternalAssetReference } from "./assetLibraryStore";
import { autonomyAssetPairQualified } from "./autonomyPlanning";
import { resolveAgentCoreAssetPair } from "./agentCorePlanning";
import { defaultAutonomyWorkspace, normalizeAutonomyWorkspace, type AutonomyMapPack, type AutonomyWorkspaceState } from "./workspaceStore";

// 功能：
//   将后端资产版本转换为界面索引，不把索引本身视为认证。
// 输入：
//   version：Core 返回的资产版本。
//   qualificationId：可选的组合认证标识。
// 输出：
//   reference：资产库展示和精确版本选择所需的引用。
export function externalAssetReferenceFromVersion(
  version: AgentCoreAssetVersion,
  qualificationId: string | null = null,
): AutonomyExternalAssetReference {
  const ir = version.asset_ir;
  const source = ir && typeof ir.source === "object" && ir.source
    ? ir.source as Record<string, unknown>
    : {};
  const name = typeof ir?.name === "string" ? ir.name.trim() : version.asset_id;
  return {
    schemaVersion: 1,
    id: version.asset_id,
    kind: version.kind,
    name: name || version.asset_id,
    sourceApplication: typeof source.application === "string" ? source.application : "External source",
    sourceFormat: typeof source.source_format === "string" ? source.source_format : "ddpkg",
    version: typeof ir?.version === "string" ? ir.version : "1",
    maturity: version.maturity,
    contentSha256: version.content_sha256,
    qualificationId,
    importedAt: version.imported_at,
  };
}

// 功能：
//   把已核验的同一组合原子映射到工作区，使用后端物理契约并撤销旧计划。
// 输入：
//   workspace：当前任务工作区。
//   assetLibrary：用于保留现有同内容资产名称的本地资产库。
//   job：组合认证任务。
//   mapVersion：认证后的地图版本。
//   vehicleVersion：认证后的飞机版本。
//   runtimeContracts：从已验证回执提取的运行契约。
// 输出：
//   binding：同步后的工作区及资产引用；不满足绑定条件时为 null。
export function bindVerifiedAssetPair(workspace: AutonomyWorkspaceState, assetLibrary: AutonomyAssetLibrary, job: AgentCoreAssetQualificationJob, mapVersion: AgentCoreAssetVersion, vehicleVersion: AgentCoreAssetVersion, runtimeContracts: AgentCoreAssetPairRuntimeContracts) {
  const qualificationId = job.qualification_id;
  const valid = job.state === "qualified"
    && job.progress_percent === 100
    && /^asset-qualification-[0-9a-f]{24}$/u.test(qualificationId ?? "")
    && (mapVersion.kind === "map" || mapVersion.kind === "world")
    && vehicleVersion.kind === "vehicle"
    && mapVersion.maturity === "qualified"
    && vehicleVersion.maturity === "qualified"
    && job.map_asset_id === mapVersion.asset_id
    && job.vehicle_asset_id === vehicleVersion.asset_id
    && job.result_map_content_sha256 === mapVersion.content_sha256
    && job.result_vehicle_content_sha256 === vehicleVersion.content_sha256
    && runtimeContracts.schema_version === "dronedream.asset-pair-runtime-contracts.v1"
    && runtimeContracts.map.asset_id === mapVersion.asset_id
    && runtimeContracts.map.content_sha256 === mapVersion.content_sha256
    && runtimeContracts.map.coordinate_frame === "ENU"
    && runtimeContracts.vehicle.asset_id === vehicleVersion.asset_id
    && runtimeContracts.vehicle.content_sha256 === vehicleVersion.content_sha256
    && runtimeContracts.vehicle.coordinate_frame === "base_link_frd";
  if (!valid || !qualificationId) return null;

  const mapAsset = externalAssetReferenceFromVersion(mapVersion, qualificationId);
  const vehicleAsset = externalAssetReferenceFromVersion(vehicleVersion, qualificationId);
  const runtimeVehicle = runtimeContracts.vehicle;
  const runtimeMap = runtimeContracts.map;
  const knownSensor = (sensor: string): AutonomyWorkspaceState["aircraft"]["sensors"][number] | null => {
    const normalized = sensor.trim().toLowerCase().replaceAll("-", "_");
    if (["rgb", "camera", "rgb_camera", "color_camera"].includes(normalized)) return "rgb";
    if (["depth", "depth_camera", "rgbd", "oakd_lite_depth"].includes(normalized)) return "depth";
    if (normalized.includes("stereo")) return "stereo";
    if (normalized.includes("thermal")) return "thermal";
    if (normalized.includes("lidar")) return "lidar";
    if (["gps", "gnss"].includes(normalized)) return "gps";
    if (["vio", "visual_inertial_odometry"].includes(normalized)) return "vio";
    return null;
  };
  const runtimeSensors = [...new Set(runtimeVehicle.sensors.map(knownSensor).filter((sensor): sensor is NonNullable<typeof sensor> => Boolean(sensor)))];
  const vehicleRuntimeContract: NonNullable<AutonomyWorkspaceState["aircraft"]["agentCoreRuntimeContract"]> = {
    schemaVersion: 1,
    assetId: runtimeVehicle.asset_id,
    contentSha256: runtimeVehicle.content_sha256,
    coordinateFrame: runtimeVehicle.coordinate_frame,
    dryMassKg: runtimeVehicle.dry_mass_kg,
    maximumTakeoffMassKg: runtimeVehicle.max_takeoff_mass_kg,
    bodyRadiusM: runtimeVehicle.body_radius_m,
    bodyHeightM: runtimeVehicle.body_height_m,
    maximumSpeedMps: runtimeVehicle.max_speed_mps,
    maximumAccelerationMps2: runtimeVehicle.max_acceleration_mps2,
    qualifiedRangeM: runtimeVehicle.qualified_range_m,
    reserveBatteryPercent: runtimeVehicle.reserve_battery_percent,
    maximumPickupPayloadKg: runtimeVehicle.max_pickup_payload_kg,
    sensors: runtimeVehicle.sensors,
    vehicleClass: runtimeVehicle.vehicle_class,
    simulationTargets: runtimeVehicle.simulation_targets.map((target) => ({
      targetId: target.target_id,
      simulator: target.simulator,
      simulatorVersion: target.simulator_version,
      rosDistribution: target.ros_distribution,
      autopilot: target.autopilot,
      entrypoint: target.entrypoint,
    })),
  };
  const mapRuntimeContract: NonNullable<AutonomyWorkspaceState["mapPack"]["agentCoreRuntimeContract"]> = {
    schemaVersion: 1,
    assetId: runtimeMap.asset_id,
    contentSha256: runtimeMap.content_sha256,
    coordinateFrame: runtimeMap.coordinate_frame,
    nodeCount: runtimeMap.node_count,
    edgeCount: runtimeMap.edge_count,
    namedEntityCount: runtimeMap.named_entity_count,
    navigationBoundsM: {
      minimum: runtimeMap.navigation_bounds_m.minimum,
      maximum: runtimeMap.navigation_bounds_m.maximum,
      span: runtimeMap.navigation_bounds_m.span,
    },
    semanticLayers: runtimeMap.semantic_layers,
    simulationTargets: runtimeMap.simulation_targets.map((target) => ({
      targetId: target.target_id,
      simulator: target.simulator,
      simulatorVersion: target.simulator_version,
      rosDistribution: target.ros_distribution,
      autopilot: target.autopilot,
      entrypoint: target.entrypoint,
    })),
  };
  const updatedAt = new Date().toISOString();
  const existingAircraft = assetLibrary.aircraft.find((candidate) => (
    candidate.agentCoreAssetId === vehicleAsset.id
    && candidate.agentCoreContentSha256 === vehicleAsset.contentSha256
  ));
  const aircraft = existingAircraft ? {
    ...existingAircraft,
    status: "validated-unsigned" as const,
    qualificationReceiptId: qualificationId,
    qualificationContentHash: vehicleAsset.contentSha256,
    agentCoreAssetId: vehicleAsset.id,
    agentCoreContentSha256: vehicleAsset.contentSha256,
    agentCoreRuntimeContract: vehicleRuntimeContract,
    dryMassKg: runtimeVehicle.dry_mass_kg,
    maximumTakeoffMassKg: runtimeVehicle.max_takeoff_mass_kg,
    bodyHeightM: runtimeVehicle.body_height_m,
    reserveBatteryPercent: runtimeVehicle.reserve_battery_percent,
    maximumPickupPayloadKg: runtimeVehicle.max_pickup_payload_kg,
    maximumSpeedMps: runtimeVehicle.max_speed_mps,
    maximumAccelerationMps2: runtimeVehicle.max_acceleration_mps2,
    sensors: runtimeSensors,
    sensorMounts: [],
    updatedAt,
  } : {
    ...defaultAutonomyWorkspace().aircraft,
    id: `imported-${vehicleAsset.id}-${vehicleAsset.contentSha256.slice(0, 10)}`,
    version: 1,
    name: vehicleAsset.name,
    manufacturer: vehicleAsset.sourceApplication,
    status: "validated-unsigned" as const,
    qualificationReceiptId: qualificationId,
    qualificationContentHash: vehicleAsset.contentSha256,
    agentCoreAssetId: vehicleAsset.id,
    agentCoreContentSha256: vehicleAsset.contentSha256,
    agentCoreRuntimeContract: vehicleRuntimeContract,
    airframe: runtimeVehicle.vehicle_class.replaceAll("_", " "),
    dryMassKg: runtimeVehicle.dry_mass_kg,
    maximumTakeoffMassKg: runtimeVehicle.max_takeoff_mass_kg,
    bodyHeightM: runtimeVehicle.body_height_m,
    reserveBatteryPercent: runtimeVehicle.reserve_battery_percent,
    maximumPickupPayloadKg: runtimeVehicle.max_pickup_payload_kg,
    maximumSpeedMps: runtimeVehicle.max_speed_mps,
    maximumAccelerationMps2: runtimeVehicle.max_acceleration_mps2,
    sensors: runtimeSensors,
    sensorMounts: [],
    updatedAt,
  };
  const sourceFile: AutonomyMapPack["sourceFiles"][number] = {
    name: mapAsset.name,
    bytes: 0,
    format: mapAsset.sourceFormat,
    importedAt: mapAsset.importedAt,
    sha256: mapAsset.contentSha256,
    receiptId: qualificationId,
    admission: "admitted",
    parser: mapAsset.sourceApplication,
    layers: ["mesh", "semantic"],
  };
  const existingMap = assetLibrary.maps.find((candidate) => (
    candidate.agentCoreAssetId === mapAsset.id
    && candidate.agentCoreContentSha256 === mapAsset.contentSha256
  ));
  const mapPack = existingMap ? {
    ...existingMap,
    status: "qualified" as const,
    contentHash: mapAsset.contentSha256,
    qualificationReceiptId: qualificationId,
    calibrated: true,
    compilerSceneId: null,
    agentCoreAssetId: mapAsset.id,
    agentCoreContentSha256: mapAsset.contentSha256,
    agentCoreRuntimeContract: mapRuntimeContract,
    coordinateFrame: runtimeMap.coordinate_frame,
    sourceFiles: [
      sourceFile,
      ...existingMap.sourceFiles.filter((file) => file.sha256 !== mapAsset.contentSha256),
    ],
    updatedAt,
  } : {
    ...defaultAutonomyWorkspace().mapPack,
    id: `imported-${mapAsset.id}-${mapAsset.contentSha256.slice(0, 10)}`,
    version: 1,
    name: mapAsset.name,
    status: "qualified" as const,
    contentHash: mapAsset.contentSha256,
    qualificationReceiptId: qualificationId,
    agentCoreAssetId: mapAsset.id,
    agentCoreContentSha256: mapAsset.contentSha256,
    agentCoreRuntimeContract: mapRuntimeContract,
    coordinateFrame: runtimeMap.coordinate_frame,
    calibrated: true,
    compilerSceneId: null,
    sourceFiles: [sourceFile],
    updatedAt,
  };
  const nextWorkspace = normalizeAutonomyWorkspace({ ...workspace,
    aircraft,
    mapPack,
    mission: {
      ...workspace.mission,
      aircraftProfileId: aircraft.id,
      mapPackId: mapPack.id,
      compiledPlan: null,
      planningRunId: null,
      updatedAt,
    },
  });
  if (!autonomyAssetPairQualified(nextWorkspace)) return null;
  return { workspace: nextWorkspace, mapAsset, vehicleAsset };

}

// 功能：
//   在规划前从 Core 恢复所选资产的真实组合认证，不改选已固定的文件版本。
// 输入：
//   workspace：本次提交的资产选择和任务。
//   assetLibrary：当前账户资产库。
// 输出：
//   boundWorkspace：可供规划使用的同步工作区；证据缺失或损坏时抛出错误。
export async function reconcileAgentCoreWorkspace(workspace: AutonomyWorkspaceState, assetLibrary: AutonomyAssetLibrary) {
  const pair = await resolveAgentCoreAssetPair(workspace);
  const binding = bindVerifiedAssetPair(workspace, assetLibrary, pair.job, pair.mapVersion, pair.vehicleVersion, pair.evidence.runtime_contracts);
  if (!binding) throw new Error("AGENT_CORE_ASSET_PAIR_BINDING_REQUIRED");
  return binding.workspace;
}
