import type { AgentCoreLiveMap, AgentCoreLiveTelemetry } from "./agentCore";

export function validLiveMap(map: AgentCoreLiveMap): boolean {
  if (map.schema_version !== "dronedream.live-map.v1" || map.coordinate_frame !== "gazebo-enu") return false;
  if (!map.map_id || !/^[0-9a-f]{64}$/u.test(map.map_content_sha256)) return false;
  if (!Number.isInteger(map.width_px) || !Number.isInteger(map.height_px)
    || map.width_px <= 0 || map.height_px <= 0 || map.width_px > 16384 || map.height_px > 16384) return false;
  if (!Array.isArray(map.world_to_image) || map.world_to_image.length !== 6
    || !map.world_to_image.every(Number.isFinite)) return false;
  const [a, b, , d, e] = map.world_to_image;
  return Math.abs(a * e - b * d) > 1e-12;
}

export function projectLiveMapPoint(map: AgentCoreLiveMap, east: number, north: number) {
  const [a, b, c, d, e, f] = map.world_to_image;
  return { x: a * east + b * north + c, y: d * east + e * north + f };
}

export function projectLiveTelemetry(map: AgentCoreLiveMap, telemetry: AgentCoreLiveTelemetry | null) {
  if (!validLiveMap(map) || !telemetry || telemetry.coordinate_frame !== map.coordinate_frame
    || telemetry.map_id !== map.map_id || telemetry.map_content_sha256 !== map.map_content_sha256) return null;
  const route = telemetry.route_points_m ?? [];
  // Never remove a damaged point and then draw a shortcut across the missing segment.
  const routeValid = route.every((point) => Array.isArray(point) && point.length >= 2
    && Number.isFinite(point[0]) && Number.isFinite(point[1]));
  const projected = routeValid ? route.map((point) => projectLiveMapPoint(map, point[0], point[1])) : [];
  const current = typeof telemetry.east_m === "number" && Number.isFinite(telemetry.east_m)
    && typeof telemetry.north_m === "number" && Number.isFinite(telemetry.north_m)
    ? projectLiveMapPoint(map, telemetry.east_m, telemetry.north_m) : null;
  return {
    points: projected.map((point) => `${point.x},${point.y}`).join(" "),
    start: projected.length >= 2 ? projected[0] : null,
    goal: projected.length >= 2 ? projected.at(-1)! : null,
    current,
    outsideImage: current !== null && (current.x < 0 || current.x > map.width_px || current.y < 0 || current.y > map.height_px),
  };
}
