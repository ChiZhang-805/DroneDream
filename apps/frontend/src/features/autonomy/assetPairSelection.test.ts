import { describe, expect, it } from "vitest";

import {
  FALLBACK_ASSET_PAIR_CATALOG,
  compatibleAircraftChoices,
  compatibleMapChoices,
  selectedPair,
  reconcilePairSelection,
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
    expect(FALLBACK_ASSET_PAIR_CATALOG.counts).toEqual({ qualified_builtin: 7, compatible_requires_qualification: 29, incompatible: 0 });
  });

  it("allows only the qualified aircraft after selecting the campus", () => {
    const aircraft = compatibleAircraftChoices(FALLBACK_ASSET_PAIR_CATALOG, "dronedream-school-map");
    expect(aircraft).toHaveLength(1);
    expect(aircraft.filter((choice) => choice.qualifiedPairCount > 0).map((choice) => choice.resourceId)).toEqual([
      "px4-x500-depth",
    ]);
  });

  it("allows only the harbour after selecting Standard VTOL", () => {
    const maps = compatibleMapChoices(FALLBACK_ASSET_PAIR_CATALOG, "px4-standard-vtol");
    expect(maps.map((choice) => choice.resourceId)).toEqual(["dronedream-vuosaari-harbour-map"]);
    expect(maps[0].qualifiedPairCount).toBe(1);
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

  it("restricts hospital selection in both directions and leaves display-only aircraft unavailable", () => {
    expect(compatibleAircraftChoices(FALLBACK_ASSET_PAIR_CATALOG, "dronedream-meilahti-hospital-map")
      .map((choice) => choice.resourceId)).toEqual(["px4-x500-depth"]);
    expect(compatibleAircraftChoices(FALLBACK_ASSET_PAIR_CATALOG, "dronedream-vuosaari-harbour-map")
      .map((choice) => choice.resourceId)).toEqual(["px4-x500-depth", "px4-standard-vtol"]);
    expect(compatibleMapChoices(FALLBACK_ASSET_PAIR_CATALOG, "px4-tiltrotor")).toEqual([]);
    expect(compatibleAircraftChoices(FALLBACK_ASSET_PAIR_CATALOG, null)
      .filter((choice) => choice.qualifiedPairCount > 0).map((choice) => choice.resourceId))
      .toEqual(["px4-x500-depth", "px4-standard-vtol"]);
  });

  it("does not enable a pair based on its status label without receipt and asset bindings", () => {
    const original = FALLBACK_ASSET_PAIR_CATALOG.pairs[0];
    for (const patch of [{ qualification_id: null }, { qualified_map_asset_id: null },
      { qualified_vehicle_asset_id: null }, { compatible: false }]) {
      const catalog = { ...FALLBACK_ASSET_PAIR_CATALOG, pairs: [{ ...original, ...patch }] };
      expect(compatibleAircraftChoices(catalog, original.map_resource_id)).toEqual([]);
      expect(compatibleMapChoices(catalog, original.vehicle_resource_id)).toEqual([]);
    }
  });

  it("clears an invalid aircraft after a catalog change without silently choosing a replacement", () => {
    expect(reconcilePairSelection(FALLBACK_ASSET_PAIR_CATALOG,
      "dronedream-meilahti-hospital-map", "px4-standard-vtol"))
      .toEqual({ mapId: "dronedream-meilahti-hospital-map", vehicleId: null });
    expect(reconcilePairSelection(FALLBACK_ASSET_PAIR_CATALOG, null, "px4-standard-vtol"))
      .toEqual({ mapId: null, vehicleId: "px4-standard-vtol" });
    expect(reconcilePairSelection(FALLBACK_ASSET_PAIR_CATALOG,
      "dronedream-vuosaari-harbour-map", "px4-standard-vtol"))
      .toEqual({ mapId: "dronedream-vuosaari-harbour-map", vehicleId: "px4-standard-vtol" });
    const removed = { ...FALLBACK_ASSET_PAIR_CATALOG, pairs: FALLBACK_ASSET_PAIR_CATALOG.pairs
      .filter((pair) => pair.map_resource_id !== "dronedream-vuosaari-harbour-map") };
    expect(reconcilePairSelection(removed, "dronedream-vuosaari-harbour-map", "px4-standard-vtol"))
      .toEqual({ mapId: null, vehicleId: null });
  });
});
