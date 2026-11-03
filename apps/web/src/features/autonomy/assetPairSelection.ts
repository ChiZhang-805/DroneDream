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
  {
    resourceId: "dronedream-meilahti-hospital-map",
    name: { "zh-CN": "梅拉赫蒂医院园区", "en-US": "Meilahti Hospital Campus" },
  },
  {
    resourceId: "dronedream-kalasatama-waterfront-map",
    name: { "zh-CN": "卡拉萨塔马滨水区", "en-US": "Kalasatama Waterfront" },
  },
  {
    resourceId: "dronedream-vuosaari-harbour-map",
    name: { "zh-CN": "沃萨里港", "en-US": "Vuosaari Harbour" },
  },
  {
    resourceId: "dronedream-suomenlinna-map",
    name: { "zh-CN": "芬兰堡海上要塞", "en-US": "Suomenlinna Sea Fortress" },
  },
  {
    resourceId: "dronedream-uutela-coastal-forest-map",
    name: { "zh-CN": "乌特拉海岸森林", "en-US": "Uutela Coastal Forest" },
  },
];

const VEHICLES: Array<{ resourceId: string; name: LocalizedName; vehicleClass: "multicopter" | "vtol" }> = [
  { resourceId: "px4-x500-depth", name: { "zh-CN": "X500 深度感知", "en-US": "X500 Depth" }, vehicleClass: "multicopter" },
  { resourceId: "px4-x500-lidar-front", name: { "zh-CN": "X500 前视雷达", "en-US": "X500 Front LiDAR" }, vehicleClass: "multicopter" },
  { resourceId: "px4-x500-gimbal", name: { "zh-CN": "X500 云台巡检", "en-US": "X500 Gimbal" }, vehicleClass: "multicopter" },
  { resourceId: "px4-standard-vtol", name: { "zh-CN": "标准垂直起降机", "en-US": "Standard VTOL" }, vehicleClass: "vtol" },
  { resourceId: "px4-tiltrotor", name: { "zh-CN": "倾转旋翼机", "en-US": "Tiltrotor VTOL" }, vehicleClass: "vtol" },
  { resourceId: "px4-quadtailsitter", name: { "zh-CN": "四旋翼尾座机", "en-US": "Tailsitter VTOL" }, vehicleClass: "vtol" },
];

const OUTDOOR_VTOL_MAPS = new Set(MAPS.map((map) => map.resourceId));

const QUALIFIED_MAP_ASSET_IDS: Record<string, string> = {
  "dronedream-school-map": "dronedream.school-map.v1",
  "dronedream-meilahti-hospital-map": "dronedream.meilahti-hospital-map.v1",
  "dronedream-kalasatama-waterfront-map": "dronedream.kalasatama-waterfront-map.v1",
  "dronedream-vuosaari-harbour-map": "dronedream.vuosaari-harbour-map.v1",
  "dronedream-suomenlinna-map": "dronedream.suomenlinna-map.v1",
  "dronedream-uutela-coastal-forest-map": "dronedream.uutela-coastal-forest-map.v1",
};

const QUALIFICATION_IDS: Record<string, string> = {
  "dronedream-school-map::px4-x500-depth": "asset-qualification-e6b4e5d8d596851ee549d46a",
  "dronedream-school-map::px4-x500-lidar-front": "asset-qualification-c2530cfa922c9c29ee12f31f",
  "dronedream-school-map::px4-x500-gimbal": "asset-qualification-08b97c5d290c35ef0270b265",
  "dronedream-school-map::px4-standard-vtol": "asset-qualification-c09f82f7c90406604c5c3c1a",
  "dronedream-meilahti-hospital-map::px4-x500-depth": "asset-qualification-6fb9cd6b77569fecb298c000",
  "dronedream-meilahti-hospital-map::px4-x500-lidar-front": "asset-qualification-4ae75ac68327ba080dcc4a58",
  "dronedream-meilahti-hospital-map::px4-x500-gimbal": "asset-qualification-9002f03b65a566fc7b808797",
  "dronedream-meilahti-hospital-map::px4-standard-vtol": "asset-qualification-da07175de8153218eba99d51",
  "dronedream-kalasatama-waterfront-map::px4-x500-depth": "asset-qualification-d2fb2947d03555333fc64ac4",
  "dronedream-kalasatama-waterfront-map::px4-x500-lidar-front": "asset-qualification-13601718b345a7a23d44078c",
  "dronedream-kalasatama-waterfront-map::px4-x500-gimbal": "asset-qualification-32847dfe7fd8412ad7743056",
  "dronedream-kalasatama-waterfront-map::px4-standard-vtol": "asset-qualification-572ca435e901ce3f36650aa0",
  "dronedream-vuosaari-harbour-map::px4-x500-depth": "asset-qualification-94994abb257e999e2f0805f6",
  "dronedream-vuosaari-harbour-map::px4-x500-lidar-front": "asset-qualification-52a2e3eaf1c480b2073c5e59",
  "dronedream-vuosaari-harbour-map::px4-x500-gimbal": "asset-qualification-c9f836104ffb2d326e681006",
  "dronedream-vuosaari-harbour-map::px4-standard-vtol": "asset-qualification-fa690ccfacd75c5c9e137b97",
  "dronedream-suomenlinna-map::px4-x500-depth": "asset-qualification-49de1e9af06907248637e4be",
  "dronedream-suomenlinna-map::px4-x500-lidar-front": "asset-qualification-68960df62ecefafa71d95718",
  "dronedream-suomenlinna-map::px4-x500-gimbal": "asset-qualification-1657d42dae17e60b699b65b4",
  "dronedream-suomenlinna-map::px4-standard-vtol": "asset-qualification-976368484eaec9caaa675dbf",
  "dronedream-uutela-coastal-forest-map::px4-x500-depth": "asset-qualification-23d9556be930ad2c8f3a4ce0",
  "dronedream-uutela-coastal-forest-map::px4-x500-lidar-front": "asset-qualification-e70183b83c1fb286db869a22",
  "dronedream-uutela-coastal-forest-map::px4-x500-gimbal": "asset-qualification-cf73ae68d2b91cf4d6b7f21a",
  "dronedream-uutela-coastal-forest-map::px4-standard-vtol": "asset-qualification-0fcedc4ca736c8a730e785c9",
};

const QUALIFIED_VEHICLE_ASSET_IDS: Record<string, string> = {
  "px4-x500-depth": "dronedream.my-drone.v1",
  "px4-x500-lidar-front": "x500-lidar-front",
  "px4-x500-gimbal": "x500-gimbal",
  "px4-standard-vtol": "standard-vtol",
};

function fallbackPair(map: (typeof MAPS)[number], vehicle: (typeof VEHICLES)[number]): AgentCoreAssetPairCatalogEntry {
  const pairId = `${map.resourceId}::${vehicle.resourceId}`;
  const qualificationId = QUALIFICATION_IDS[pairId];
  const qualified = Boolean(qualificationId);
  const compatible = vehicle.vehicleClass !== "vtol" || OUTDOOR_VTOL_MAPS.has(map.resourceId);
  const status = qualified ? "qualified_builtin" as const
    : compatible ? "compatible_requires_qualification" as const : "incompatible" as const;
  return {
    schema_version: "dronedream.asset-pair-compatibility.v1",
    pair_id: `${map.resourceId}::${vehicle.resourceId}`,
    map_resource_id: map.resourceId,
    map_display_name: map.name,
    environment_class: "outdoor_campus",
    vehicle_resource_id: vehicle.resourceId,
    vehicle_display_name: vehicle.name,
    vehicle_class: vehicle.vehicleClass,
    status,
    compatible,
    qualification_id: qualificationId ?? null,
    qualified_map_asset_id: qualified ? QUALIFIED_MAP_ASSET_IDS[map.resourceId] : null,
    qualified_vehicle_asset_id: qualified ? QUALIFIED_VEHICLE_ASSET_IDS[vehicle.resourceId] : null,
    qualification_scope: qualified ? "exact_builtin_normalized_package" : null,
    reasons: [],
    required_gates: status === "compatible_requires_qualification" ? ["aircraft_map_pair_qualification"] : [],
    sensor_constraints: [],
  };
}

const FALLBACK_PAIRS = MAPS.flatMap((map) => VEHICLES.map((vehicle) => fallbackPair(map, vehicle)));

export const FALLBACK_ASSET_PAIR_CATALOG: AgentCoreAssetPairCatalog = {
  schema_version: "dronedream.asset-pair-catalog.v1",
  catalog_revision: "frontend-builtin-pairs",
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
  pairs = pairs.filter(pair => VEHICLES.some(vehicle => vehicle.resourceId === pair.vehicle_resource_id));
  const resourceId = (pair: AgentCoreAssetPairCatalogEntry) => kind === "map" ? pair.map_resource_id : pair.vehicle_resource_id;
  const names = (pair: AgentCoreAssetPairCatalogEntry) => kind === "map" ? pair.map_display_name : pair.vehicle_display_name;
  return [...new Set(pairs.map(resourceId))].map((id) => {
    const assetPairs = pairs.filter((pair) => resourceId(pair) === id);
    return {
      resourceId: id,
      name: (kind === "map" ? MAPS : VEHICLES).find((item) => item.resourceId === id)?.name ?? names(assetPairs[0]),
      compatiblePairCount: assetPairs.filter((pair) => pair.compatible).length,
      qualifiedPairCount: assetPairs.filter(isMissionReadyPair).length,
    };
  });
}

export function compatibleAircraftChoices(catalog: AgentCoreAssetPairCatalog, selectedMapId: string | null): PairCatalogChoice[] {
  const pairs = selectedMapId ? catalog.pairs.filter((pair) => pair.map_resource_id === selectedMapId && isMissionReadyPair(pair)) : catalog.pairs;
  return uniqueChoices(pairs, "vehicle");
}

export function compatibleMapChoices(catalog: AgentCoreAssetPairCatalog, selectedVehicleId: string | null): PairCatalogChoice[] {
  const pairs = selectedVehicleId ? catalog.pairs.filter((pair) => pair.vehicle_resource_id === selectedVehicleId && isMissionReadyPair(pair)) : catalog.pairs;
  return uniqueChoices(pairs, "map");
}

export function isMissionReadyPair(pair: AgentCoreAssetPairCatalogEntry | null): boolean {
  return Boolean(pair?.compatible && pair.status === "qualified_builtin"
    && pair.qualification_id && pair.qualified_map_asset_id && pair.qualified_vehicle_asset_id);
}

export function reconcilePairSelection(
  catalog: AgentCoreAssetPairCatalog, mapId: string | null, vehicleId: string | null,
): { mapId: string | null; vehicleId: string | null } {
  const mapAvailable = compatibleMapChoices(catalog, null)
    .some((choice) => choice.resourceId === mapId && choice.qualifiedPairCount > 0);
  const aircraftAvailable = compatibleAircraftChoices(catalog, mapAvailable ? mapId : null)
    .some((choice) => choice.resourceId === vehicleId && choice.qualifiedPairCount > 0);
  return { mapId: mapAvailable ? mapId : null, vehicleId: aircraftAvailable ? vehicleId : null };
}

export function selectedPair(catalog: AgentCoreAssetPairCatalog, mapId: string | null, vehicleId: string | null): AgentCoreAssetPairCatalogEntry | null {
  if (!mapId || !vehicleId || !VEHICLES.some(vehicle => vehicle.resourceId === vehicleId)) return null;
  return catalog.pairs.find((pair) => pair.map_resource_id === mapId && pair.vehicle_resource_id === vehicleId) ?? null;
}
