import { describe, expect, it } from "vitest";

import {
  extractPoints,
  to3DProjectedCoordinates,
} from "../components/trajectoryReplayMath";

describe("trajectoryReplayMath", () => {
  it("extractPoints supports samples/points/trajectory/path/reference_track", () => {
    const payloads = [
      { samples: [{ x: 1, y: 2, z: 3, t: 1 }] },
      { points: [{ x: 2, y: 3, z: 4, t: 2 }] },
      { trajectory: [{ x: 3, y: 4, z: 5, t: 3 }] },
      { path: [{ x: 4, y: 5, z: 6, t: 4 }] },
      { reference_track: [{ x: 5, y: 6, z: 7, t: 5 }] },
    ];

    const extracted = payloads.map((payload) => extractPoints(payload));

    expect(extracted).toHaveLength(5);
    extracted.forEach((points) => {
      expect(points).toHaveLength(1);
      expect(points[0].x).toBeTypeOf("number");
      expect(points[0].y).toBeTypeOf("number");
      expect(points[0].z).toBeTypeOf("number");
      expect(points[0].t).toBeTypeOf("number");
    });
  });

  it("uses z=0 default when z is missing", () => {
    const points = extractPoints({ samples: [{ t: 0, x: 1, y: 2 }] });
    expect(points).toEqual([{ t: 0, x: 1, y: 2, z: 0 }]);
  });

  it("3D projection returns finite SVG coordinates", () => {
    const projected = to3DProjectedCoordinates([
      { t: 0, x: 0, y: 0, z: 0 },
      { t: 1, x: 1, y: 2, z: 3 },
      { t: 2, x: 2, y: 0.5, z: -1 },
    ]);

    const pairs = projected.linePoints.split(" ");
    expect(pairs.length).toBe(3);

    for (const pair of pairs) {
      const [x, y] = pair.split(",").map(Number);
      expect(Number.isFinite(x)).toBe(true);
      expect(Number.isFinite(y)).toBe(true);
    }

    expect(Number.isFinite(projected.markerX(1))).toBe(true);
    expect(Number.isFinite(projected.markerY(1))).toBe(true);
  });

  it("3D projection remains valid when all z are identical", () => {
    const projected = to3DProjectedCoordinates([
      { t: 0, x: 0, y: 0, z: 2 },
      { t: 1, x: 2, y: 1, z: 2 },
    ]);

    expect(projected.linePoints).not.toContain("NaN");
    expect(projected.linePoints).not.toContain("Infinity");
  });
});
