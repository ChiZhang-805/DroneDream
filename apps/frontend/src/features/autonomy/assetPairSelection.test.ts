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
    expect(compatibleAircraftChoices(olderCatalog, null).map(choice => choice.resourceId)).toEqual([
      "px4-x500-depth",
      "px4-x500-lidar-front",
      "px4-x500-gimbal",
      "px4-standard-vtol",
      "px4-tiltrotor",
      "px4-quadtailsitter",
    ]);
    expect(selectedPair(olderCatalog, "dronedream-school-map", "px4-x500-flow")).toBeNull();
  });
  it("shows all assets while both selections are empty", () => {
    expect(compatibleMapChoices(FALLBACK_ASSET_PAIR_CATALOG, null)).toHaveLength(6);
    expect(compatibleAircraftChoices(FALLBACK_ASSET_PAIR_CATALOG, null)).toHaveLength(6);
    expect(FALLBACK_ASSET_PAIR_CATALOG.pair_count).toBe(36);
    expect(FALLBACK_ASSET_PAIR_CATALOG.counts).toEqual({ qualified_builtin: 6, compatible_requires_qualification: 30, incompatible: 0 });
  });

  it("lists the six admitted aircraft for the outdoor campus", () => {
    const aircraft = compatibleAircraftChoices(FALLBACK_ASSET_PAIR_CATALOG, "dronedream-school-map");
    expect(aircraft).toHaveLength(6);
    expect(aircraft.filter((choice) => choice.qualifiedPairCount > 0).map((choice) => choice.resourceId)).toEqual([
      "px4-x500-depth",
    ]);
  });

  it("offers the reviewed outdoor maps for Standard VTOL while keeping the pair unqualified", () => {
    const maps = compatibleMapChoices(FALLBACK_ASSET_PAIR_CATALOG, "px4-standard-vtol");
    expect(maps).toHaveLength(6);
    expect(maps.every((choice) => choice.qualifiedPairCount === 0)).toBe(true);
  });

  it("reports the default qualified map and aircraft pair", () => {
    const pair = selectedPair(FALLBACK_ASSET_PAIR_CATALOG, "dronedream-school-map", "px4-x500-depth");
    expect(pair?.status).toBe("qualified_builtin");
    expect(pair?.qualification_id).toBe("asset-qualification-e6b4e5d8d596851ee549d46a");
  });

  it("keeps every Helsinki map bound to its exact qualified package", () => {
    const choices = compatibleMapChoices(FALLBACK_ASSET_PAIR_CATALOG, "px4-x500-depth");
    expect(choices.map((choice) => choice.resourceId)).toEqual([
      "dronedream-school-map",
      "dronedream-meilahti-hospital-map",
      "dronedream-kalasatama-waterfront-map",
      "dronedream-vuosaari-harbour-map",
      "dronedream-suomenlinna-map",
      "dronedream-uutela-coastal-forest-map",
    ]);
    expect(choices.every((choice) => choice.qualifiedPairCount === 1)).toBe(true);
  });
});
