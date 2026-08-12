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
});
