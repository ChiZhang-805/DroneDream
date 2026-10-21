import { describe, expect, it } from "vitest";

import {
  DISTRIBUTION_CATALOG,
  validateDistributionCatalog,
} from "../features/distribution/catalog";
import {
  buildDistributionInstallationPreview,
  createDefaultDistributionSelection,
  normalizeDistributionSelection,
} from "../features/distribution/installationSelection";

describe("versioned distribution catalog", () => {
  it("contains one shared core with three editions and eight honest pack states", () => {
    expect(DISTRIBUTION_CATALOG.editions.map((edition) => edition.editionId))
      .toEqual(["sim", "lab", "field"]);
    expect(DISTRIBUTION_CATALOG.vehiclePacks).toHaveLength(8);
    expect(DISTRIBUTION_CATALOG.vehiclePacks.filter((pack) => pack.goldenCandidate))
      .toHaveLength(3);
    expect(DISTRIBUTION_CATALOG.vehiclePacks.filter(
      (pack) => pack.validationStatus === "validated",
    )).toHaveLength(0);
    expect(DISTRIBUTION_CATALOG.vehiclePacks.filter(
      (pack) => pack.validationStatus === "contract-only",
    )).toHaveLength(5);
    expect(DISTRIBUTION_CATALOG.vehiclePacks.filter(
      (pack) => pack.validationStatus === "planned",
    )).toHaveLength(3);
  });

  it("fails closed when source hashes or verified size claims are malformed", () => {
    const badHash = structuredClone(DISTRIBUTION_CATALOG);
    badHash.sourceBindings.vehiclePackRegistry.sha256 = "not-a-hash";
    expect(() => validateDistributionCatalog(badHash)).toThrow(/unsafe or unbound/);

    const falseEstimate = structuredClone(DISTRIBUTION_CATALOG);
    falseEstimate.editions[0].downloadEstimateState = "verified";
    falseEstimate.editions[0].downloadEstimateBytes = null;
    expect(() => validateDistributionCatalog(falseEstimate))
      .toThrow(/cannot claim a verified estimate/);

    const emptyEstimate = structuredClone(DISTRIBUTION_CATALOG);
    emptyEstimate.editions[0].downloadEstimateState = "verified";
    emptyEstimate.editions[0].downloadEstimateBytes = 0;
    expect(() => validateDistributionCatalog(emptyEstimate)).toThrow(/downloadEstimateBytes/);

    const prematureEstimate = structuredClone(DISTRIBUTION_CATALOG);
    prematureEstimate.editions[0].downloadEstimateBytes = 1024;
    expect(() => validateDistributionCatalog(prematureEstimate)).toThrow(/before the build plan/);
  });

  it("rejects unknown enums, omitted booleans, planned golden candidates, and extra fields", () => {
    const badAutopilot = structuredClone(DISTRIBUTION_CATALOG) as unknown as {
      vehiclePacks: Array<Record<string, unknown>>;
    };
    badAutopilot.vehiclePacks[0].autopilotFamily = "unknown";
    expect(() => validateDistributionCatalog(badAutopilot)).toThrow(/autopilotFamily/);

    const omittedSimulatorFlag = structuredClone(DISTRIBUTION_CATALOG) as unknown as {
      editions: Array<Record<string, unknown>>;
    };
    delete omittedSimulatorFlag.editions[0].includesLargeSimulator;
    expect(() => validateDistributionCatalog(omittedSimulatorFlag))
      .toThrow(/unsupported or missing fields/);

    const plannedGolden = structuredClone(DISTRIBUTION_CATALOG);
    plannedGolden.vehiclePacks[5].goldenCandidate = true;
    expect(() => validateDistributionCatalog(plannedGolden)).toThrow(/planned pack/);

    const overstatedController = structuredClone(DISTRIBUTION_CATALOG);
    overstatedController.vehiclePacks[1].controllers[0].status = "validated";
    expect(() => validateDistributionCatalog(overstatedController))
      .toThrow(/cannot overstate Vehicle Pack validation/);

    const extraField = structuredClone(DISTRIBUTION_CATALOG) as unknown as Record<string, unknown>;
    extraField.unreviewedCapability = true;
    expect(() => validateDistributionCatalog(extraField)).toThrow(/unsupported or missing fields/);
  });
});

describe("distribution installation selection", () => {
  it("defaults to the simulation-only X500 reference without inventing a controller", () => {
    const selection = createDefaultDistributionSelection("global");
    const preview = buildDistributionInstallationPreview(selection);

    expect(selection).toEqual({
      schemaVersion: 1,
      editionId: "sim",
      region: "global",
      vehiclePackId: "px4-gazebo-x500-reference",
      controllerKey: null,
      optionalModules: [],
    });
    expect(preview.selectedVehiclePack?.productAvailability).toBe("simulation-only");
    expect(preview.compatibleControllers).toHaveLength(0);
    expect(preview.canApply).toBe(false);
    expect(preview.issues.map((issue) => issue.code)).toEqual([
      "vehicle-pack-unvalidated",
      "download-estimate-pending",
      "native-plan-required",
    ]);
  });

  it("normalizes incompatible region, vehicle, controller, and optional modules", () => {
    const normalized = normalizeDistributionSelection({
      schemaVersion: 1,
      editionId: "field",
      region: "cn",
      vehiclePackId: "holybro-x500-v2-pixhawk6",
      controllerKey: "Holybro::Pixhawk 6X",
      optionalModules: ["qgroundcontrol-external", "unknown", "qgroundcontrol-external"],
    });

    expect(normalized.vehiclePackId).toBe("amovlab-mfp450-pixhawk6c");
    expect(normalized.controllerKey).toBe("Holybro::Pixhawk 6C");
    expect(normalized.optionalModules).toEqual(["qgroundcontrol-external"]);
  });

  it("keeps Field lightweight and blocks planned hardware from native planning", () => {
    const selection = normalizeDistributionSelection({
      schemaVersion: 1,
      editionId: "field",
      region: "cn",
      vehiclePackId: "amovlab-p450-px4",
      controllerKey: null,
      optionalModules: [],
    });
    const preview = buildDistributionInstallationPreview(selection);

    expect(preview.requiredModules).not.toContain("runtime-simulation");
    expect(preview.requiredModules).not.toContain("simulator-gazebo-harmonic");
    expect(preview.selectedVehiclePack?.validationStatus).toBe("planned");
    expect(preview.selectedController?.status).toBe("planned");
    expect(preview.canRequestNativePlan).toBe(false);
    expect(preview.canApply).toBe(false);
  });

  it("never treats a locally selected option as permission to apply modules", () => {
    const preview = buildDistributionInstallationPreview({
      schemaVersion: 1,
      editionId: "lab",
      region: "global",
      vehiclePackId: "holybro-x500-v2-pixhawk6",
      controllerKey: "Holybro::Pixhawk 6C",
      optionalModules: ["qgroundcontrol-external"],
    });

    expect(preview.selectedController?.model).toBe("Pixhawk 6C");
    expect(preview.optionalModules).toEqual(["qgroundcontrol-external"]);
    expect(preview.issues.map((issue) => issue.code)).toContain("edition-contract-only");
    expect(preview.issues.map((issue) => issue.code)).toContain("vehicle-pack-unvalidated");
    expect(preview.canApply).toBe(false);
  });
});
