import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { describe, expect, it } from "vitest";

import { FIELD_CATALOG } from "../field/catalog";
import { DISTRIBUTION_CATALOG } from "../features/distribution/catalog";

describe("Field catalog projection", () => {
  it("is an exact, source-bound projection of Field-compatible packs", () => {
    const fieldEdition = DISTRIBUTION_CATALOG.editions.find(
      (edition) => edition.editionId === "field",
    );
    const projectedPacks = DISTRIBUTION_CATALOG.vehiclePacks
      .filter((pack) => pack.supportedEditions.includes("field"))
      .map((pack) => ({
        packId: pack.packId,
        displayName: pack.displayName,
        manufacturer: pack.manufacturer,
        vehicleClass: pack.vehicleClass,
        validationStatus: pack.validationStatus,
        validationTier: pack.validationTier,
        adapterStatus: pack.adapterStatus,
        controllers: pack.controllers.map(({ vendor, model, status }) => ({
          vendor,
          model,
          status,
        })),
        manifestSha256: pack.manifestSha256,
      }));

    expect(fieldEdition).toBeDefined();
    expect(FIELD_CATALOG.sourceBindings).toEqual({
      fieldManifestSha256:
        DISTRIBUTION_CATALOG.sourceBindings.editionManifests.field.sha256,
      vehiclePackRegistrySha256:
        DISTRIBUTION_CATALOG.sourceBindings.vehiclePackRegistry.sha256,
    });
    expect(FIELD_CATALOG.vehiclePacks).toEqual(projectedPacks);
  });

  it("contains no validated pack and excludes non-Field pack records", () => {
    expect(FIELD_CATALOG.vehiclePacks).toHaveLength(7);
    expect(FIELD_CATALOG.vehiclePacks.some(
      (pack) => pack.validationStatus === "validated",
    )).toBe(false);
    expect(FIELD_CATALOG.vehiclePacks.map((pack) => pack.packId)).not.toContain(
      "px4-gazebo-x500-reference",
    );
  });

  it("keeps forbidden runtime vocabulary out of Field runtime sources", () => {
    const runtimeSources = ["catalog.ts", "safety.ts"].map((name) =>
      readFileSync(resolve(process.cwd(), "src/field", name), "utf8"),
    ).join("\n");

    expect(runtimeSources).not.toMatch(/gazebo|sitl|hitl|simulation/i);
  });
});
