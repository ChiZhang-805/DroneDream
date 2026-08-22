import { describe, expect, it } from "vitest";

import { editionHasWorkspace } from "../edition";
import { assistantArtifactMatchesEdition } from "../features/experiment/assistantProductPolicy";
import {
  assistantTaskIsAllowed,
  assistantTaskOptions,
} from "../features/experiment/assistantTaskRouter";

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

  it("gives AGENT an external-asset workflow while retaining legacy history", () => {
    expect(assistantTaskOptions("autonomy", "en").map(({ id }) => id)).toEqual([
      "mission_autonomy",
      "asset_import_qualification",
      "simulation_experiment",
    ]);
    expect(assistantTaskIsAllowed("autonomy", "asset_import_qualification")).toBe(true);
    expect(assistantArtifactMatchesEdition("autonomy", "external_asset_qualification_plan"))
      .toBe(true);
    expect(assistantArtifactMatchesEdition("autonomy", "universal_vehicle_model"))
      .toBe(false);
    expect(assistantArtifactMatchesEdition(
      "autonomy",
      "universal_vehicle_model",
      { legacyRead: true },
    )).toBe(true);
  });
});
