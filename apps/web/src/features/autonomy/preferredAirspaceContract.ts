import type { AirspaceRequest } from "./agentCore";

export type CorridorVolume = [number, number, number, number, number, number, number, number | null];
export interface AirspaceSnapshot {
  schema_version: "dronedream.preferred-airspace.v1";
  coordinate_frame: "ENU";
  authority: "preference-only";
  airspace_sha256: string;
  snapshot_sha256: string;
  binding: { sources: AirspaceRequest; radius_m: number; height_m: number };
  volumes: CorridorVolume[];
  obstacles: [number, number, number, number, number, number][];
}

// 功能：
//   独立核验返回坐标、体积预算和当前资产身份；拒绝旧回包、非有限值和错误 ENU 表示。
// 输入：
//   value：Core 回包。
//   expected：发起请求时的资产对。
// 输出：
//   snapshot：可渲染的静态软偏好数据。
export function parseAirspaceSnapshot(value: unknown, expected: AirspaceRequest): AirspaceSnapshot {
  const data = value as AirspaceSnapshot | null;
  const finite = (v: unknown): v is number => typeof v === "number" && Number.isFinite(v) && Math.abs(v) <= 1e6;
  if (!data || data.schema_version !== "dronedream.preferred-airspace.v1"
    || data.coordinate_frame !== "ENU" || data.authority !== "preference-only"
    || !/^[a-f0-9]{64}$/u.test(data.airspace_sha256) || !/^[a-f0-9]{64}$/u.test(data.snapshot_sha256)
    || !data.binding?.sources || !finite(data.binding.radius_m) || data.binding.radius_m <= 0
    || !finite(data.binding.height_m) || data.binding.height_m <= 0
    || Object.entries(expected).some(([key, value]) => data.binding.sources[key as keyof AirspaceRequest] !== value)
    || !Array.isArray(data.volumes) || data.volumes.length > 200_000
    || !Array.isArray(data.obstacles) || data.obstacles.length > 100_000
    || data.volumes.some((v) => !Array.isArray(v) || v.length !== 8 || !v.slice(0, 7).every(finite)
      || v.slice(3, 6).some((size) => size === null || size <= 0)
      || v[2] - v[5] / 2 - data.binding.height_m / 2 < v[6] - 1e-7
      || (v[7] !== null && (!finite(v[7]) || v[7] <= v[6]
        || v[2] + v[5] / 2 + data.binding.height_m / 2 > v[7] + 1e-7)))
    || data.obstacles.some((v) => !Array.isArray(v) || v.length !== 6 || !v.every(finite)
      || v[0] >= v[3] || v[1] >= v[4] || v[2] >= v[5])) {
    throw new Error("AIRSPACE_RESPONSE_INVALID");
  }
  return data;
}
