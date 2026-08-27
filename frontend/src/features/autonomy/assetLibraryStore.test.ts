import { describe, expect, it } from "vitest";

import {
  loadAutonomyAssetLibrary,
  saveAutonomyAssetLibrary,
  withExternalAutonomyAsset,
  type AutonomyAssetLibrary,
  type AutonomyExternalAssetReference,
} from "./assetLibraryStore";
import { defaultAutonomyWorkspace } from "./workspaceStore";

const SHA_A = "a".repeat(64);
const SHA_B = "b".repeat(64);

function external(
  id: string,
  kind: AutonomyExternalAssetReference["kind"],
  contentSha256: string,
): AutonomyExternalAssetReference {
  return {
    schemaVersion: 1,
    id,
    kind,
    name: kind === "vehicle" ? "My Drone" : "School Map",
    sourceApplication: "DroneDream Legacy",
    sourceFormat: "ddpkg",
    version: "1",
    maturity: "qualified",
    contentSha256,
    qualificationId: null,
    importedAt: "2026-08-27T00:00:00.000Z",
  };
}

describe("autonomy asset library", () => {
  it("migrates canonical Aircraft and Maps history to one visible asset each", () => {
    const workspace = defaultAutonomyWorkspace(new Date("2026-08-27T00:00:00.000Z"));
    const stored: AutonomyAssetLibrary = {
      schemaVersion: 2,
      aircraft: [workspace.aircraft],
      maps: [workspace.mapPack],
      externalAssets: [
        external("dronedream.my-drone.v1", "vehicle", SHA_A),
        external("dronedream.my-drone.v1", "vehicle", SHA_B),
        external("dronedream.school-map.v1", "map", SHA_A),
        external("dronedream.school-map.v1", "world", SHA_B),
      ],
    };
    const storage = {
      getItem: () => JSON.stringify(stored),
    };

    const library = loadAutonomyAssetLibrary("local", "universal", workspace, storage);

    expect(library.aircraft).toHaveLength(1);
    expect(library.maps).toHaveLength(1);
    expect(library.externalAssets).toHaveLength(0);
  });

  it("keeps only the newest registered version of a custom logical asset", () => {
    const workspace = defaultAutonomyWorkspace(new Date("2026-08-27T00:00:00.000Z"));
    const empty: AutonomyAssetLibrary = {
      schemaVersion: 2,
      aircraft: [workspace.aircraft],
      maps: [workspace.mapPack],
      externalAssets: [],
    };

    const first = withExternalAutonomyAsset(empty, external("customer.drone.v1", "vehicle", SHA_A));
    const second = withExternalAutonomyAsset(first, external("customer.drone.v1", "vehicle", SHA_B));

    expect(second.externalAssets).toHaveLength(1);
    expect(second.externalAssets[0]?.contentSha256).toBe(SHA_B);
  });

  it("persists the migrated library instead of writing duplicate legacy cards back", () => {
    const workspace = defaultAutonomyWorkspace(new Date("2026-08-27T00:00:00.000Z"));
    let value = "";
    const saved = saveAutonomyAssetLibrary("local", "universal", {
      schemaVersion: 2,
      aircraft: [workspace.aircraft, { ...workspace.aircraft }],
      maps: [workspace.mapPack, { ...workspace.mapPack }],
      externalAssets: [
        external("dronedream.my-drone.v1", "vehicle", SHA_A),
        external("dronedream.school-map.v1", "map", SHA_A),
      ],
    }, {
      setItem: (_key, next) => { value = next; },
    });

    expect(saved.aircraft).toHaveLength(1);
    expect(saved.maps).toHaveLength(1);
    expect(saved.externalAssets).toHaveLength(0);
    expect(JSON.parse(value)).toEqual(saved);
  });
});
