import { describe, expect, it } from "vitest";

import { generateReferenceTrack } from "../utils/referenceTrack";

describe("hover reference track", () => {
  it("produces a 10-second stationary local preview contract", () => {
    const points = generateReferenceTrack("hover", 0, 0, 3, {
      circle_radius_m: 5,
      u_turn_straight_length_m: 10,
      u_turn_turn_radius_m: 3,
      lemniscate_scale_m: 4,
    });

    expect(points).toHaveLength(101);
    expect(new Set(points.map((point) => `${point.x},${point.y},${point.z}`))).toEqual(
      new Set(["0,0,3"]),
    );
  });

  it("does not render invalid sensor-independent geometry as a usable reference", () => {
    const geometry = { circle_radius_m: 5, u_turn_straight_length_m: 10, u_turn_turn_radius_m: 3, lemniscate_scale_m: 4 };
    expect(generateReferenceTrack("circle", Number.NaN, 0, 3, geometry)).toEqual([]);
    expect(generateReferenceTrack("circle", 0, 0, 3, { ...geometry, circle_radius_m: -1 })).toEqual([]);
    expect(generateReferenceTrack("u_turn", 0, 0, 3, { ...geometry, u_turn_turn_radius_m: 0 })).toEqual([]);
    expect(generateReferenceTrack("lemniscate", 0, 0, 3, { ...geometry, lemniscate_scale_m: Infinity })).toEqual([]);
  });

  it("does not silently substitute a figure eight for an unknown track kind", () => {
    const geometry = { circle_radius_m: 5, u_turn_straight_length_m: 10, u_turn_turn_radius_m: 3, lemniscate_scale_m: 4 };
    // Exercise an unvalidated restored draft, beyond the compile-time union.
    expect(generateReferenceTrack("unknown" as "circle", 0, 0, 3, geometry)).toEqual([]);
  });

  it("rejects coordinate overflow instead of returning a partly invalid polyline", () => {
    const geometry = { circle_radius_m: Number.MAX_VALUE, u_turn_straight_length_m: 10, u_turn_turn_radius_m: 3, lemniscate_scale_m: 4 };
    expect(generateReferenceTrack("circle", Number.MAX_VALUE, 0, 3, geometry)).toEqual([]);
  });
});
