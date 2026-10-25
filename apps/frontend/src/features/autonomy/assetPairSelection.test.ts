import { describe, expect, it } from "vitest";

import {
  FALLBACK_ASSET_PAIR_CATALOG,
  compatibleAircraftChoices,
  compatibleMapChoices,
  selectedPair,
} from "./assetPairSelection";

describe("asset pair selection", () => {
  it("does not resurrect retired defaults from an older sidecar", () => {
    const oldPair = { ...FALLBACK_ASSET_PAIR_CATALOG.pairs[0], vehicle_resource_id: "px4-x500-flow" };
    const olderCatalog = { ...FALLBACK_ASSET_PAIR_CATALOG, pairs: [...FALLBACK_ASSET_PAIR_CATALOG.pairs, oldPair] };
    expect(compatibleAircraftChoices(olderCatalog, null).map(choice => choice.resourceId)).toEqual(["px4-x500-depth"]);
    expect(selectedPair(olderCatalog, "dronedream-school-map", "px4-x500-flow")).toBeNull();
  });
  it("shows all assets while both selections are empty", () => {
    expect(compatibleMapChoices(FALLBACK_ASSET_PAIR_CATALOG, null)).toHaveLength(1);
    expect(compatibleAircraftChoices(FALLBACK_ASSET_PAIR_CATALOG, null)).toHaveLength(1);
    expect(FALLBACK_ASSET_PAIR_CATALOG.pair_count).toBe(1);
    expect(FALLBACK_ASSET_PAIR_CATALOG.counts).toEqual({ qualified_builtin: 1, compatible_requires_qualification: 0, incompatible: 0 });
  });

  it("only lists the admitted aircraft for the outdoor campus", () => {
    const aircraft = compatibleAircraftChoices(FALLBACK_ASSET_PAIR_CATALOG, "dronedream-school-map");
    expect(aircraft).toHaveLength(1);
    expect(aircraft.filter((choice) => choice.qualifiedPairCount > 0).map((choice) => choice.resourceId)).toEqual([
      "px4-x500-depth",
    ]);
  });

  it("does not offer a map for a retired aircraft", () => {
    expect(compatibleMapChoices(FALLBACK_ASSET_PAIR_CATALOG, "px4-standard-vtol").map((choice) => choice.resourceId)).toEqual([]);
  });

  it("reports the default qualified map and aircraft pair", () => {
    const pair = selectedPair(FALLBACK_ASSET_PAIR_CATALOG, "dronedream-school-map", "px4-x500-depth");
    expect(pair?.status).toBe("qualified_builtin");
    expect(pair?.qualification_id).toBe("asset-qualification-57aa3819b5591401b2a92387");
  });
});
