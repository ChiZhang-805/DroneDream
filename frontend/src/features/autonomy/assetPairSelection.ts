import type { AgentCoreAssetPairCatalog, AgentCoreAssetPairCatalogEntry } from "./agentCore";

type LocalizedName = { "zh-CN": string; "en-US": string };

export type PairCatalogChoice = {
  resourceId: string;
  name: LocalizedName;
  compatiblePairCount: number;
  qualifiedPairCount: number;
};

const MAPS: Array<{ resourceId: string; name: LocalizedName }> = [
  {
    resourceId: "dronedream-school-map",
    name: { "zh-CN": "赫尔辛基大学昆普拉校区", "en-US": "Kumpula Campus" },
  },
];

const VEHICLES: Array<{ resourceId: string; name: LocalizedName; vehicleClass: "multicopter" | "vtol" }> = [
  { resourceId: "px4-x500-depth", name: { "zh-CN": "X500 深度感知", "en-US": "X500 Depth" }, vehicleClass: "multicopter" },
  { resourceId: "px4-x500-flow", name: { "zh-CN": "X500 光流型", "en-US": "X500 Flow" }, vehicleClass: "multicopter" },
  { resourceId: "px4-x500-lidar-down", name: { "zh-CN": "X500 下视雷达", "en-US": "X500 Down LiDAR" }, vehicleClass: "multicopter" },
  { resourceId: "px4-x500-lidar-front", name: { "zh-CN": "X500 前视雷达", "en-US": "X500 Front LiDAR" }, vehicleClass: "multicopter" },
  { resourceId: "px4-x500-mono-cam", name: { "zh-CN": "X500 前视相机", "en-US": "X500 Front Cam" }, vehicleClass: "multicopter" },
  { resourceId: "px4-x500-mono-cam-down", name: { "zh-CN": "X500 下视相机", "en-US": "X500 Down Cam" }, vehicleClass: "multicopter" },
  { resourceId: "px4-x500-lidar-2d", name: { "zh-CN": "X500 二维雷达", "en-US": "X500 2D LiDAR" }, vehicleClass: "multicopter" },
  { resourceId: "px4-x500-vision", name: { "zh-CN": "X500 视觉里程计", "en-US": "X500 Vision" }, vehicleClass: "multicopter" },
  { resourceId: "px4-x500-gimbal", name: { "zh-CN": "X500 云台巡检", "en-US": "X500 Gimbal" }, vehicleClass: "multicopter" },
  { resourceId: "px4-x500", name: { "zh-CN": "X500 标准型", "en-US": "X500 Standard" }, vehicleClass: "multicopter" },
  { resourceId: "px4-standard-vtol", name: { "zh-CN": "标准垂直起降机", "en-US": "Standard VTOL" }, vehicleClass: "vtol" },
  { resourceId: "px4-tiltrotor", name: { "zh-CN": "倾转旋翼机", "en-US": "Tiltrotor VTOL" }, vehicleClass: "vtol" },
  { resourceId: "px4-quadtailsitter", name: { "zh-CN": "四旋翼尾座机", "en-US": "Tailsitter VTOL" }, vehicleClass: "vtol" },
];

const OUTDOOR_VTOL_MAPS = new Set(["dronedream-school-map"]);

const QUALIFIED_MAP_ASSET_IDS: Record<string, string> = {
  "dronedream-school-map": "dronedream.school-map.v1",
};

const QUALIFICATION_IDS: Record<string, string> = {
  "dronedream-school-map": "asset-qualification-582554632b54abc53723f55b",
};

function fallbackPair(map: (typeof MAPS)[number], vehicle: (typeof VEHICLES)[number]): AgentCoreAssetPairCatalogEntry {
  const qualified = vehicle.resourceId === "px4-x500-depth";
  const compatible = vehicle.vehicleClass !== "vtol" || OUTDOOR_VTOL_MAPS.has(map.resourceId);
  const status = qualified ? "qualified_builtin" as const
    : compatible ? "compatible_requires_qualification" as const : "incompatible" as const;
  return {
    schema_version: "dronedream.asset-pair-compatibility.v1",
    pair_id: `${map.resourceId}::${vehicle.resourceId}`,
    map_resource_id: map.resourceId,
    map_display_name: map.name,
    environment_class: map.resourceId.includes("campus") || map.resourceId.includes("battle") ? "outdoor" : "indoor",
    vehicle_resource_id: vehicle.resourceId,
    vehicle_display_name: vehicle.name,
    vehicle_class: vehicle.vehicleClass,
    status,
    compatible,
    qualification_id: qualified ? QUALIFICATION_IDS[map.resourceId] : null,
    qualified_map_asset_id: qualified ? QUALIFIED_MAP_ASSET_IDS[map.resourceId] : null,
    qualified_vehicle_asset_id: qualified ? "dronedream.my-drone.v1" : null,
    qualification_scope: qualified ? "exact_builtin_normalized_package" : null,
    reasons: [],
    required_gates: status === "compatible_requires_qualification" ? ["aircraft_map_pair_qualification"] : [],
    sensor_constraints: [],
  };
}

const FALLBACK_PAIRS = MAPS.flatMap((map) => VEHICLES.map((vehicle) => fallbackPair(map, vehicle)));

export const FALLBACK_ASSET_PAIR_CATALOG: AgentCoreAssetPairCatalog = {
  schema_version: "dronedream.asset-pair-catalog.v1",
  catalog_revision: "frontend-fallback-2026-10-11.1",
  map_count: MAPS.length,
  vehicle_count: VEHICLES.length,
  pair_count: FALLBACK_PAIRS.length,
  counts: {
    qualified_builtin: FALLBACK_PAIRS.filter((pair) => pair.status === "qualified_builtin").length,
    compatible_requires_qualification: FALLBACK_PAIRS.filter((pair) => pair.status === "compatible_requires_qualification").length,
    incompatible: FALLBACK_PAIRS.filter((pair) => pair.status === "incompatible").length,
  },
  pairs: FALLBACK_PAIRS,
};

function uniqueChoices(pairs: AgentCoreAssetPairCatalogEntry[], kind: "map" | "vehicle"): PairCatalogChoice[] {
  const resourceId = (pair: AgentCoreAssetPairCatalogEntry) => kind === "map" ? pair.map_resource_id : pair.vehicle_resource_id;
  const names = (pair: AgentCoreAssetPairCatalogEntry) => kind === "map" ? pair.map_display_name : pair.vehicle_display_name;
  return [...new Set(pairs.map(resourceId))].map((id) => {
    const assetPairs = pairs.filter((pair) => resourceId(pair) === id);
    return {
      resourceId: id,
      name: (kind === "map" ? MAPS : VEHICLES).find((item) => item.resourceId === id)?.name ?? names(assetPairs[0]),
      compatiblePairCount: assetPairs.filter((pair) => pair.compatible).length,
      qualifiedPairCount: assetPairs.filter((pair) => pair.status === "qualified_builtin").length,
    };
  });
}

export function compatibleAircraftChoices(catalog: AgentCoreAssetPairCatalog, selectedMapId: string | null): PairCatalogChoice[] {
  const pairs = selectedMapId ? catalog.pairs.filter((pair) => pair.map_resource_id === selectedMapId && pair.compatible) : catalog.pairs;
  return uniqueChoices(pairs, "vehicle");
}

export function compatibleMapChoices(catalog: AgentCoreAssetPairCatalog, selectedVehicleId: string | null): PairCatalogChoice[] {
  const pairs = selectedVehicleId ? catalog.pairs.filter((pair) => pair.vehicle_resource_id === selectedVehicleId && pair.compatible) : catalog.pairs;
  return uniqueChoices(pairs, "map");
}

export function selectedPair(catalog: AgentCoreAssetPairCatalog, mapId: string | null, vehicleId: string | null): AgentCoreAssetPairCatalogEntry | null {
  if (!mapId || !vehicleId) return null;
  return catalog.pairs.find((pair) => pair.map_resource_id === mapId && pair.vehicle_resource_id === vehicleId) ?? null;
}
