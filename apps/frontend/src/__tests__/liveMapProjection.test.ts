import { describe, expect, it } from "vitest";
import type { AgentCoreLiveMap, AgentCoreLiveTelemetry } from "../features/autonomy/agentCore";
import { projectLiveMapPoint, projectLiveTelemetry, validLiveMap } from "../features/autonomy/liveMapProjection";

const map: AgentCoreLiveMap = {
  schema_version: "dronedream.live-map.v1", map_id: "selected-map", map_content_sha256: "a".repeat(64),
  coordinate_frame: "gazebo-enu", width_px: 2000, height_px: 1000,
  world_to_image: [4, 0, 1000, 0, -2, 500],
};
const telemetry: AgentCoreLiveTelemetry = {
  schema_version: "dronedream.live-telemetry.v1", mode: "simulation", coordinate_frame: "gazebo-enu",
  map_id: map.map_id, map_content_sha256: map.map_content_sha256, updated_at_unix_ms: 1,
  east_m: -41, north_m: -83, up_m: 2,
  route_points_m: [[-41, -83, 2], [-41, -30, 2], [43, 55, 2]],
};

describe("registered Live map projection", () => {
  it("maps ENU corners and origin to the actual image, with north pointing up", () => {
    expect(projectLiveMapPoint(map, -250, 250)).toEqual({ x: 0, y: 0 });
    expect(projectLiveMapPoint(map, 250, -250)).toEqual({ x: 2000, y: 1000 });
    expect(projectLiveMapPoint(map, 0, 0)).toEqual({ x: 1000, y: 500 });
    expect(projectLiveTelemetry(map, telemetry)?.current).toEqual({ x: 836, y: 666 });
  });

  it("does not stretch a route or move its landmarks when the destination or aircraft changes", () => {
    const first = projectLiveTelemetry(map, telemetry)!;
    const second = projectLiveTelemetry(map, { ...telemetry, east_m: 240, north_m: 230,
      route_points_m: [[-41, -83, 2], [200, -120, 2]] })!;
    expect(second.start).toEqual(first.start);
    expect(second.current).toEqual({ x: 1960, y: 40 });
    expect(first.points).toBe("836,666 836,560 1172,390");
  });

  it("supports explicit rotated registration without assuming north-up imagery", () => {
    expect(projectLiveMapPoint({ ...map, world_to_image: [0, 2, 500, 4, 0, 1000] }, -41, -83))
      .toEqual({ x: 334, y: 836 });
  });

  it("rejects an unrelated version/frame and cannot place unregistered telemetry at the image center", () => {
    expect(projectLiveTelemetry(map, { ...telemetry, map_content_sha256: "b".repeat(64) })).toBeNull();
    expect(projectLiveTelemetry(map, { ...telemetry, map_id: "other-map" })).toBeNull();
    expect(projectLiveTelemetry(map, { ...telemetry, coordinate_frame: "wgs84" })).toBeNull();
    expect(projectLiveTelemetry(map, { ...telemetry, map_content_sha256: undefined })).toBeNull();
  });

  it("does not invent a connecting line across damaged route points or clamp positions into the map", () => {
    const result = projectLiveTelemetry(map, { ...telemetry, east_m: 300,
      route_points_m: [[0, 0, 2], [NaN, 2, 2], [100, 20, 2]] })!;
    expect(result.points).toBe("");
    expect(result.current?.x).toBe(2200);
    expect(result.outsideImage).toBe(true);
  });

  it("rejects degenerate registrations and invalid dimensions", () => {
    expect(validLiveMap({ ...map, world_to_image: [0, 0, 0, 0, 0, 0] })).toBe(false);
    expect(validLiveMap({ ...map, width_px: 0 })).toBe(false);
    expect(validLiveMap({ ...map, world_to_image: [Infinity, 0, 0, 0, 1, 0] })).toBe(false);
  });
});
