import { describe, expect, it } from "vitest";

import {
  FALLBACK_ASSET_PAIR_CATALOG,
  compatibleAircraftChoices,
  compatibleMapChoices,
  selectedPair,
} from "./assetPairSelection";

describe("asset pair selection", () => {
  it("shows all assets while both selections are empty", () => {
    expect(compatibleMapChoices(FALLBACK_ASSET_PAIR_CATALOG, null)).toHaveLength(8);
    expect(compatibleAircraftChoices(FALLBACK_ASSET_PAIR_CATALOG, null)).toHaveLength(13);
    expect(FALLBACK_ASSET_PAIR_CATALOG.pair_count).toBe(104);
    expect(FALLBACK_ASSET_PAIR_CATALOG.counts).toEqual({ qualified_builtin: 8, compatible_requires_qualification: 78, incompatible: 18 });
  });

  it("filters VTOL aircraft out of indoor maps", () => {
    const aircraft = compatibleAircraftChoices(FALLBACK_ASSET_PAIR_CATALOG, "open-rmf-office");
    expect(aircraft).toHaveLength(10);
    expect(aircraft.some((choice) => choice.resourceId === "px4-standard-vtol")).toBe(false);
  });

  it("filters a VTOL selection down to its two outdoor maps", () => {
    expect(compatibleMapChoices(FALLBACK_ASSET_PAIR_CATALOG, "px4-standard-vtol").map((choice) => choice.resourceId)).toEqual([
      "open-rmf-battle-royale",
      "open-rmf-campus",
    ]);
  });

  it("never reports an incompatible pair as selectable", () => {
    expect(selectedPair(FALLBACK_ASSET_PAIR_CATALOG, "open-rmf-office", "px4-standard-vtol")?.compatible).toBe(false);
  });
});
