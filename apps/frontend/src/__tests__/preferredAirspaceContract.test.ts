import { describe, expect, it } from "vitest";
import { parseAirspaceSnapshot } from "../features/autonomy/preferredAirspaceContract";

const pair = { map_asset_id: "map-test", vehicle_asset_id: "vehicle-test", map_content_sha256: "a".repeat(64), vehicle_content_sha256: "b".repeat(64) };
const sample = () => ({ schema_version: "dronedream.preferred-airspace.v1", coordinate_frame: "ENU", authority: "preference-only",
  airspace_sha256: "c".repeat(64), snapshot_sha256: "d".repeat(64), binding: { sources: pair, radius_m: .2, height_m: .4 },
  volumes: [[0, 0, 1.7, 1, 1, .8, 0, 3]], obstacles: [[-1, -1, -.2, 1, 1, 0]] });

describe("preferred airspace boundary", () => {
  it("accepts bound static preferences", () => expect(parseAirspaceSnapshot(sample(), pair).volumes).toHaveLength(1));
  it("rejects stale map selection", () => expect(() => parseAirspaceSnapshot(sample(), { ...pair, map_content_sha256: "e".repeat(64) })).toThrow());
  it.each([NaN, Infinity, -1, 0])("rejects invalid size %s", (size) => {
    const data = sample(); data.volumes[0][3] = size;
    expect(() => parseAirspaceSnapshot(data, pair)).toThrow();
  });
  it("does not accept NED as ENU", () => {
    const data = sample(); data.coordinate_frame = "NED";
    expect(() => parseAirspaceSnapshot(data, pair)).toThrow();
  });
  it("rejects claiming control authority", () => {
    const data = sample(); data.authority = "flight-ready";
    expect(() => parseAirspaceSnapshot(data, pair)).toThrow();
  });
  it.each([0.1, 2.8])("rejects a height band that puts the body inside floor or ceiling: %s", (height) => {
    const data = sample(); data.volumes[0][2] = height;
    expect(() => parseAirspaceSnapshot(data, pair)).toThrow();
  });
});
