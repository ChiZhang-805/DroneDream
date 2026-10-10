import { describe, expect, it } from "vitest";

import {
  FALLBACK_ASSET_PAIR_CATALOG,
  compatibleAircraftChoices,
  compatibleMapChoices,
  selectedPair,
} from "./assetPairSelection";

describe("asset pair selection", () => {
  it("shows all assets while both selections are empty", () => {
    expect(compatibleMapChoices(FALLBACK_ASSET_PAIR_CATALOG, null)).toHaveLength(1);
    expect(compatibleAircraftChoices(FALLBACK_ASSET_PAIR_CATALOG, null)).toHaveLength(13);
    expect(FALLBACK_ASSET_PAIR_CATALOG.pair_count).toBe(13);
    expect(FALLBACK_ASSET_PAIR_CATALOG.counts).toEqual({ qualified_builtin: 1, compatible_requires_qualification: 12, incompatible: 0 });
  });

  it("keeps all aircraft visible for the outdoor campus while only one pair is qualified", () => {
    const aircraft = compatibleAircraftChoices(FALLBACK_ASSET_PAIR_CATALOG, "dronedream-school-map");
    expect(aircraft).toHaveLength(13);
    expect(aircraft.filter((choice) => choice.qualifiedPairCount > 0).map((choice) => choice.resourceId)).toEqual([
      "px4-x500-depth",
    ]);
  });

  it("filters every aircraft selection down to the single real default map", () => {
    expect(compatibleMapChoices(FALLBACK_ASSET_PAIR_CATALOG, "px4-standard-vtol").map((choice) => choice.resourceId)).toEqual([
      "dronedream-school-map",
    ]);
  });

  it("reports the default qualified map and aircraft pair", () => {
    const pair = selectedPair(FALLBACK_ASSET_PAIR_CATALOG, "dronedream-school-map", "px4-x500-depth");
    expect(pair?.status).toBe("qualified_builtin");
    expect(pair?.qualification_id).toBe("asset-qualification-582554632b54abc53723f55b");
  });
});
