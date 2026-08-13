import { describe, expect, it } from "vitest";

import {
  editionHasVehicleStudio,
  editionHasWorkspace,
} from "../edition";

describe("desktop edition ownership", () => {
  it("makes Universal the only three-workspace product", () => {
    for (const workspace of ["sim", "lab", "field"] as const) {
      expect(editionHasWorkspace("universal", workspace)).toBe(true);
    }
    expect(editionHasWorkspace("sim", "sim")).toBe(true);
    expect(editionHasWorkspace("sim", "lab")).toBe(false);
    expect(editionHasWorkspace("sim", "field")).toBe(false);
    expect(editionHasWorkspace("lab", "sim")).toBe(false);
    expect(editionHasWorkspace("lab", "lab")).toBe(true);
    expect(editionHasWorkspace("lab", "field")).toBe(false);
    expect(editionHasWorkspace("field", "field")).toBe(true);
  });

  it("keeps Vehicle Studio exclusive to Universal", () => {
    expect(editionHasVehicleStudio("universal")).toBe(true);
    for (const edition of ["sim", "lab", "field"] as const) {
      expect(editionHasVehicleStudio(edition)).toBe(false);
    }
  });
});
