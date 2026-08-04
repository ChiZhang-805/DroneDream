import {
  controllerKey,
  DISTRIBUTION_CATALOG,
  type DistributionCatalog,
  type DistributionController,
  type DistributionEdition,
  type DistributionVehiclePack,
  type EditionId,
  type RegionId,
} from "./catalog";

export interface DistributionSelectionDraft {
  schemaVersion: 1;
  editionId: EditionId;
  region: RegionId;
  vehiclePackId: string;
  controllerKey: string | null;
  optionalModules: string[];
}

export const DISTRIBUTION_SELECTION_STORAGE_KEY =
  "dronedream:distribution-selection:v1";

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

export function parseDistributionSelectionDraft(
  value: unknown,
  catalog: DistributionCatalog = DISTRIBUTION_CATALOG,
): DistributionSelectionDraft {
  if (!isRecord(value)) throw new Error("distribution selection must be an object");
  const expectedKeys = [
    "schemaVersion",
    "editionId",
    "region",
    "vehiclePackId",
    "controllerKey",
    "optionalModules",
  ].sort();
  const actualKeys = Object.keys(value).sort();
  if (
    actualKeys.length !== expectedKeys.length
    || actualKeys.some((key, index) => key !== expectedKeys[index])
  ) {
    throw new Error("distribution selection has unsupported or missing fields");
  }
  if (
    value.schemaVersion !== 1
    || typeof value.editionId !== "string"
    || !catalog.editions.some((edition) => edition.editionId === value.editionId)
    || (value.region !== "cn" && value.region !== "global")
    || typeof value.vehiclePackId !== "string"
    || (value.controllerKey !== null && typeof value.controllerKey !== "string")
    || !Array.isArray(value.optionalModules)
    || value.optionalModules.some((moduleId) => typeof moduleId !== "string" || !moduleId)
  ) {
    throw new Error("distribution selection is malformed or unsupported");
  }
  return normalizeDistributionSelection({
    schemaVersion: 1,
    editionId: value.editionId as EditionId,
    region: value.region,
    vehiclePackId: value.vehiclePackId,
    controllerKey: value.controllerKey,
    optionalModules: value.optionalModules as string[],
  }, catalog);
}

export type DistributionSelectionIssueCode =
  | "vehicle-pack-required"
  | "vehicle-pack-incompatible"
  | "vehicle-pack-planned"
  | "vehicle-pack-unvalidated"
  | "controller-required"
  | "controller-incompatible"
  | "edition-contract-only"
  | "download-estimate-pending"
  | "native-plan-required";

export interface DistributionSelectionIssue {
  code: DistributionSelectionIssueCode;
  severity: "blocking" | "notice";
}

export interface DistributionInstallationPreview {
  selection: DistributionSelectionDraft;
  edition: DistributionEdition;
  compatibleVehiclePacks: DistributionVehiclePack[];
  selectedVehiclePack: DistributionVehiclePack | null;
  compatibleControllers: DistributionController[];
  selectedController: DistributionController | null;
  requiredModules: string[];
  optionalModules: string[];
  downloadEstimateBytes: number | null;
  issues: DistributionSelectionIssue[];
  canRequestNativePlan: boolean;
  canApply: false;
}

function editionById(catalog: DistributionCatalog, editionId: EditionId): DistributionEdition {
  const edition = catalog.editions.find((candidate) => candidate.editionId === editionId);
  if (!edition) throw new Error(`unknown distribution edition: ${editionId}`);
  return edition;
}

export function compatibleVehiclePacks(
  catalog: DistributionCatalog,
  editionId: EditionId,
  region: RegionId,
): DistributionVehiclePack[] {
  return catalog.vehiclePacks
    .filter((pack) => (
      pack.supportedEditions.includes(editionId)
      && pack.supportRegions.includes(region)
    ))
    .sort((left, right) => (
      Number(editionId === "sim" && right.productAvailability === "simulation-only")
      - Number(editionId === "sim" && left.productAvailability === "simulation-only")
      ||
      Number(right.goldenCandidate) - Number(left.goldenCandidate)
      || Number(left.validationStatus === "planned") - Number(right.validationStatus === "planned")
      || left.packId.localeCompare(right.packId)
    ));
}

function controllersForRegion(
  pack: DistributionVehiclePack | null,
  region: RegionId,
): DistributionController[] {
  if (!pack) return [];
  return pack.controllers.filter((controller) => controller.regions.includes(region));
}

export function createDefaultDistributionSelection(
  region: RegionId = "global",
  catalog: DistributionCatalog = DISTRIBUTION_CATALOG,
): DistributionSelectionDraft {
  const editionId: EditionId = "sim";
  const pack = compatibleVehiclePacks(catalog, editionId, region)[0];
  return {
    schemaVersion: 1,
    editionId,
    region,
    vehiclePackId: pack?.packId ?? "",
    controllerKey: null,
    optionalModules: [],
  };
}

export function normalizeDistributionSelection(
  selection: DistributionSelectionDraft,
  catalog: DistributionCatalog = DISTRIBUTION_CATALOG,
): DistributionSelectionDraft {
  const edition = editionById(catalog, selection.editionId);
  const packs = compatibleVehiclePacks(catalog, selection.editionId, selection.region);
  const selectedPack = packs.find((pack) => pack.packId === selection.vehiclePackId) ?? packs[0];
  const controllers = controllersForRegion(selectedPack ?? null, selection.region);
  const selectedController = controllers.find(
    (controller) => controllerKey(controller) === selection.controllerKey,
  );
  const controllerRequired = selection.editionId !== "sim" && controllers.length > 0;
  const optionalModules = selection.optionalModules.filter(
    (moduleId, index, modules) => (
      edition.optionalModules.includes(moduleId)
      && modules.indexOf(moduleId) === index
    ),
  );
  return {
    schemaVersion: 1,
    editionId: selection.editionId,
    region: selection.region,
    vehiclePackId: selectedPack?.packId ?? "",
    controllerKey: selectedController
      ? controllerKey(selectedController)
      : controllerRequired
        ? controllerKey(controllers[0])
        : null,
    optionalModules,
  };
}

export function buildDistributionInstallationPreview(
  rawSelection: DistributionSelectionDraft,
  catalog: DistributionCatalog = DISTRIBUTION_CATALOG,
): DistributionInstallationPreview {
  const edition = editionById(catalog, rawSelection.editionId);
  const compatiblePacks = compatibleVehiclePacks(
    catalog,
    rawSelection.editionId,
    rawSelection.region,
  );
  const selectedPack = compatiblePacks.find(
    (pack) => pack.packId === rawSelection.vehiclePackId,
  ) ?? null;
  const controllers = controllersForRegion(selectedPack, rawSelection.region);
  const selectedController = controllers.find(
    (controller) => controllerKey(controller) === rawSelection.controllerKey,
  ) ?? null;
  const issues: DistributionSelectionIssue[] = [];

  if (!rawSelection.vehiclePackId) {
    issues.push({ code: "vehicle-pack-required", severity: "blocking" });
  } else if (!selectedPack) {
    issues.push({ code: "vehicle-pack-incompatible", severity: "blocking" });
  }
  if (selectedPack?.validationStatus === "planned") {
    issues.push({ code: "vehicle-pack-planned", severity: "blocking" });
  } else if (selectedPack?.validationStatus !== "validated") {
    issues.push({ code: "vehicle-pack-unvalidated", severity: "blocking" });
  }
  if (rawSelection.editionId !== "sim" && controllers.length > 0 && !rawSelection.controllerKey) {
    issues.push({ code: "controller-required", severity: "blocking" });
  } else if (rawSelection.controllerKey && !selectedController) {
    issues.push({ code: "controller-incompatible", severity: "blocking" });
  }
  if (edition.implementationStatus !== "integrated-contract") {
    issues.push({ code: "edition-contract-only", severity: "blocking" });
  }
  if (edition.downloadEstimateState !== "verified") {
    issues.push({ code: "download-estimate-pending", severity: "notice" });
  }
  issues.push({ code: "native-plan-required", severity: "blocking" });

  const optionalModules = rawSelection.optionalModules.filter(
    (moduleId, index, modules) => (
      edition.optionalModules.includes(moduleId)
      && modules.indexOf(moduleId) === index
    ),
  );
  const requiredModules = [...edition.requiredModules];
  const hasSelectionBlocker = issues.some((issue) => (
    issue.severity === "blocking" && issue.code !== "native-plan-required"
  ));
  return {
    selection: {
      ...rawSelection,
      optionalModules,
    },
    edition,
    compatibleVehiclePacks: compatiblePacks,
    selectedVehiclePack: selectedPack,
    compatibleControllers: controllers,
    selectedController,
    requiredModules,
    optionalModules,
    downloadEstimateBytes: edition.downloadEstimateBytes,
    issues,
    canRequestNativePlan: !hasSelectionBlocker,
    canApply: false,
  };
}
