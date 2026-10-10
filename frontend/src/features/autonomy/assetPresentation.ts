import type { AutonomyExternalAssetReference } from "./assetLibraryStore";

export type CatalogAssetKind = "map" | "vehicle";

export type CatalogAssetDefinition = {
  key: string;
  resourceId: string;
  zh: string;
  en: string;
  aliases: string[];
};

export type CatalogAssetPresentation = {
  key: string | null;
  name: string;
  previewUrl: string | null;
};

const MAPS: CatalogAssetDefinition[] = [
  {
    key: "kumpula-campus",
    resourceId: "dronedream-school-map",
    zh: "赫尔辛基大学昆普拉校区",
    en: "Kumpula Campus",
    aliases: [
      "kumpula campus",
      "kumpula-campus",
      "school map",
      "school-map",
      "dronedream.school-map",
      "kumpulan kampus",
      "昆普拉校区",
      "昆普拉科学园区",
      "赫尔辛基大学昆普拉校区",
    ],
  },
];

const VEHICLES: CatalogAssetDefinition[] = [
  { key: "x500-depth", resourceId: "px4-x500-depth", zh: "X500 深度感知", en: "X500 Depth", aliases: ["dronedream.my-drone", "my drone", "x500 depth", "x500-depth", "x500_depth"] },
  { key: "x500-flow", resourceId: "px4-x500-flow", zh: "X500 光流型", en: "X500 Flow", aliases: ["x500 optical-flow", "x500 optical flow", "x500-flow", "x500_flow"] },
  { key: "x500-lidar-down", resourceId: "px4-x500-lidar-down", zh: "X500 下视雷达", en: "X500 Down LiDAR", aliases: ["x500 downward-lidar", "x500 downward lidar", "x500-lidar-down", "x500_lidar_down"] },
  { key: "x500-lidar-front", resourceId: "px4-x500-lidar-front", zh: "X500 前视雷达", en: "X500 Front LiDAR", aliases: ["x500 forward-lidar", "x500 forward lidar", "x500-lidar-front", "x500_lidar_front"] },
  { key: "x500-mono-front", resourceId: "px4-x500-mono-cam", zh: "X500 前视相机", en: "X500 Front Cam", aliases: ["x500 forward monocular-camera", "x500 forward monocular camera", "x500-mono-cam", "x500_mono_cam"] },
  { key: "x500-mono-down", resourceId: "px4-x500-mono-cam-down", zh: "X500 下视相机", en: "X500 Down Cam", aliases: ["x500 downward monocular-camera", "x500 downward monocular camera", "x500-mono-cam-down", "x500_mono_cam_down"] },
  { key: "x500-lidar-2d", resourceId: "px4-x500-lidar-2d", zh: "X500 二维雷达", en: "X500 2D LiDAR", aliases: ["x500 2d-lidar", "x500 2d lidar", "x500-lidar-2d", "x500_lidar_2d"] },
  { key: "x500-vision", resourceId: "px4-x500-vision", zh: "X500 视觉里程计", en: "X500 Vision", aliases: ["x500 vision", "x500-vision", "x500_vision"] },
  { key: "x500-gimbal", resourceId: "px4-x500-gimbal", zh: "X500 云台巡检", en: "X500 Gimbal", aliases: ["x500 gimbal", "x500-gimbal", "x500_gimbal"] },
  { key: "x500", resourceId: "px4-x500", zh: "X500 标准型", en: "X500 Standard", aliases: ["x500 general", "px4-x500", "x500"] },
  { key: "standard-vtol", resourceId: "px4-standard-vtol", zh: "标准垂直起降机", en: "Standard VTOL", aliases: ["standard vtol", "standard-vtol", "standard_vtol"] },
  { key: "tiltrotor", resourceId: "px4-tiltrotor", zh: "倾转旋翼机", en: "Tiltrotor VTOL", aliases: ["tiltrotor"] },
  { key: "quadtailsitter", resourceId: "px4-quadtailsitter", zh: "四旋翼尾座机", en: "Tailsitter VTOL", aliases: ["quad tailsitter", "quadtailsitter"] },
];

function normalizedIdentity(id: string, name: string): string {
  return `${id} ${name}`
    .normalize("NFKC")
    .toLocaleLowerCase("en-US")
    .replaceAll("_", "-")
    .replace(/[^\p{L}\p{N}.\-\s]+/gu, " ")
    .replace(/\s+/gu, " ")
    .trim();
}

function definitions(kind: CatalogAssetKind): CatalogAssetDefinition[] {
  return kind === "map" ? MAPS : VEHICLES;
}

function findDefinition(kind: CatalogAssetKind, id: string, name: string): CatalogAssetDefinition | null {
  const identity = normalizedIdentity(id, name);
  return definitions(kind).find((definition) => (
    definition.resourceId === id
    || definition.aliases.some((alias) => {
      const normalizedAlias = normalizedIdentity(alias, "");
      if (normalizedAlias === "x500") {
        return /(^|[.\-\s])x500($|[.\-\s])/u.test(identity)
          && !identity.includes("x500-");
      }
      return identity.includes(normalizedAlias);
    })
  )) ?? null;
}

export function catalogAssetDefinitions(kind: CatalogAssetKind): readonly CatalogAssetDefinition[] {
  return definitions(kind);
}

export function catalogAssetKey(kind: CatalogAssetKind, id: string, name: string): string | null {
  return findDefinition(kind, id, name)?.key ?? null;
}

export function catalogAssetPresentation(
  kind: CatalogAssetKind,
  id: string,
  name: string,
  chinese: boolean,
): CatalogAssetPresentation {
  const definition = findDefinition(kind, id, name);
  if (!definition) return { key: null, name: name.trim(), previewUrl: null };
  return {
    key: definition.key,
    name: chinese ? definition.zh : definition.en,
    previewUrl: `${import.meta.env.BASE_URL}asset-previews/${kind === "map" ? "maps" : "vehicles"}/${definition.key}.webp`,
  };
}

export function unrepresentedExternalAssets(
  kind: CatalogAssetKind,
  represented: Array<{ id: string; name: string }>,
  externalAssets: AutonomyExternalAssetReference[],
): AutonomyExternalAssetReference[] {
  const seen = new Set(represented.map((asset) => (
    catalogAssetKey(kind, asset.id, asset.name) ?? `${kind}:${asset.id}`
  )));
  return externalAssets.filter((asset) => {
    const candidateKind = asset.kind === "vehicle" ? "vehicle" : "map";
    if (candidateKind !== kind) return false;
    const key = catalogAssetKey(kind, asset.id, asset.name) ?? `${kind}:${asset.id}`;
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}
