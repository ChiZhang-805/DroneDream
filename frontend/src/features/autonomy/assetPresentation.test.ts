import { existsSync, readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

import type { AutonomyExternalAssetReference } from "./assetLibraryStore";
import {
  catalogAssetDefinitions,
  catalogAssetPresentation,
  unrepresentedExternalAssets,
} from "./assetPresentation";

function external(id: string, name: string, kind: "map" | "vehicle" = "map"): AutonomyExternalAssetReference {
  return {
    schemaVersion: 1,
    id,
    kind,
    name,
    sourceApplication: "catalog",
    sourceFormat: "fixture",
    version: "1",
    maturity: "simulation_ready",
    contentSha256: "a".repeat(64),
    qualificationId: null,
    importedAt: "2026-09-28T00:00:00.000Z",
  };
}

describe("asset card presentation", () => {
  it("keeps the built-in repository at eight maps and thirteen aircraft even before the runtime responds", () => {
    expect(catalogAssetDefinitions("map")).toHaveLength(8);
    expect(catalogAssetDefinitions("vehicle")).toHaveLength(13);
    expect(new Set(catalogAssetDefinitions("map").map((item) => item.key)).size).toBe(8);
    expect(new Set(catalogAssetDefinitions("vehicle").map((item) => item.key)).size).toBe(13);
  });

  it("merges the seven catalog map sources into their converted map cards", () => {
    const represented = catalogAssetDefinitions("map").map((item) => ({ id: item.resourceId, name: item.en }));
    const sources = [
      external("open-rmf-airport-terminal", "Airport Terminal"),
      external("open-rmf-battle-royale", "Open Test Arena"),
      external("open-rmf-campus", "Campus Site"),
      external("open-rmf-clinic", "Two-level Clinic"),
      external("open-rmf-hotel", "Three-level Hotel"),
      external("open-rmf-office", "Office"),
      external("open-rmf-triple-h", "Triple-H Corridor Test"),
    ];

    expect(unrepresentedExternalAssets("map", represented, sources)).toEqual([]);
  });

  it("uses concise bilingual names and bundled previews", () => {
    expect(catalogAssetPresentation("map", "open-rmf-battle-royale", "battle-royale", true)).toEqual({
      key: "open-test-arena",
      name: "开放试验场",
      previewUrl: "/asset-previews/maps/open-test-arena.webp",
    });
    expect(catalogAssetPresentation("vehicle", "px4-x500-lidar-front", "x500", false).name).toBe("X500 Front LiDAR");
  });

  it("preserves genuinely user-imported assets", () => {
    const userMap = external("user-map-lab-west", "West laboratory");
    expect(unrepresentedExternalAssets("map", [], [userMap])).toEqual([userMap]);
  });

  it("ships every reviewed preview referenced by the presentation catalog", () => {
    const manifestPath = join(process.cwd(), "public", "asset-previews", "manifest.json");
    const manifest = JSON.parse(readFileSync(manifestPath, "utf8")) as { files: Array<{ path: string }> };
    expect(manifest.files).toHaveLength(21);
    for (const entry of manifest.files) {
      expect(existsSync(join(process.cwd(), "public", "asset-previews", entry.path))).toBe(true);
    }
  });
});
