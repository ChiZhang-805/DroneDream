import rawCatalog from "./catalog.v1.json";

export const EDITION_IDS = ["sim", "lab", "field"] as const;
export const REGION_IDS = ["cn", "global"] as const;

export type EditionId = (typeof EDITION_IDS)[number];
export type RegionId = (typeof REGION_IDS)[number];
export type DistributionLocale = "en" | "zh-CN";
export type DistributionValidationStatus = "validated" | "contract-only" | "planned";
export type DistributionImplementationStatus = "integrated-contract" | "contract-only";

export interface LocalizedText {
  en: string;
  "zh-CN": string;
}

export interface DistributionSourceBinding {
  path: string;
  sha256: string;
}

export interface DistributionEdition {
  editionId: EditionId;
  editionVersion: string;
  displayName: LocalizedText;
  description: LocalizedText;
  implementationStatus: DistributionImplementationStatus;
  validationTier: string;
  artifactBaseName: string;
  requiredModules: string[];
  optionalModules: string[];
  forbiddenModules: string[];
  includesLargeSimulator: boolean;
  downloadEstimateBytes: number | null;
  downloadEstimateState: "pending-build-plan" | "verified";
}

export interface DistributionController {
  vendor: string;
  model: string;
  status: DistributionValidationStatus;
  regions: RegionId[];
}

export interface DistributionVehiclePack {
  packId: string;
  packVersion: string;
  displayName: LocalizedText;
  manufacturer: string;
  vehicleClass: string;
  supportRegions: RegionId[];
  supportedEditions: EditionId[];
  validationStatus: DistributionValidationStatus;
  validationTier: string;
  autopilotFamily: "px4" | "ardupilot" | "crazyflie";
  adapterStatus: "integrated-contract" | "contract-only" | "planned";
  controllers: DistributionController[];
  segments: string[];
  goldenCandidate: boolean;
  productAvailability:
    | "simulation-only"
    | "listed-available"
    | "variant-limited"
    | "listed-sold-out"
    | "documentation-only";
  manifestSha256: string;
}

export interface DistributionCatalog {
  schemaVersion: 1;
  kind: "dronedream-frontend-distribution-catalog";
  catalogVersion: string;
  productDisplayVersion: "1.0.0";
  sourceBindings: {
    editionManifests: Record<EditionId, DistributionSourceBinding>;
    vehiclePackRegistry: DistributionSourceBinding;
  };
  editions: DistributionEdition[];
  vehiclePacks: DistributionVehiclePack[];
}

const SHA256_PATTERN = /^[0-9a-f]{64}$/;
const VERSION_PATTERN = /^[0-9]+\.[0-9]+\.[0-9]+$/;
const SAFE_ID_PATTERN = /^[a-z0-9]+(?:-[a-z0-9]+)*$/;
const EDITION_SET = new Set<string>(EDITION_IDS);
const REGION_SET = new Set<string>(REGION_IDS);
const VALIDATION_STATUS_SET = new Set<string>(["validated", "contract-only", "planned"]);
const IMPLEMENTATION_STATUS_SET = new Set<string>(["integrated-contract", "contract-only"]);
const AUTOPILOT_FAMILY_SET = new Set<string>(["px4", "ardupilot", "crazyflie"]);
const ADAPTER_STATUS_SET = new Set<string>(["integrated-contract", "contract-only", "planned"]);
const PRODUCT_AVAILABILITY_SET = new Set<string>([
  "simulation-only",
  "listed-available",
  "variant-limited",
  "listed-sold-out",
  "documentation-only",
]);

function requireExactKeys(
  record: Record<string, unknown>,
  expectedKeys: readonly string[],
  label: string,
): void {
  const actual = Object.keys(record).sort();
  const expected = [...expectedKeys].sort();
  if (actual.length !== expected.length || actual.some((key, index) => key !== expected[index])) {
    throw new Error(`${label} has unsupported or missing fields`);
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function requireRecord(value: unknown, label: string): Record<string, unknown> {
  if (!isRecord(value)) throw new Error(`${label} must be an object`);
  return value;
}

function requireString(value: unknown, label: string): string {
  if (typeof value !== "string" || !value.trim()) {
    throw new Error(`${label} must be non-empty text`);
  }
  return value;
}

function requireStringArray(value: unknown, label: string): string[] {
  if (
    !Array.isArray(value)
    || value.some((item) => typeof item !== "string" || !item.trim())
  ) {
    throw new Error(`${label} must be a non-empty string array`);
  }
  if (new Set(value).size !== value.length) {
    throw new Error(`${label} must not contain duplicates`);
  }
  return [...value];
}

function requireLocalizedText(value: unknown, label: string): LocalizedText {
  const record = requireRecord(value, label);
  requireExactKeys(record, ["en", "zh-CN"], label);
  return {
    en: requireString(record.en, `${label}.en`),
    "zh-CN": requireString(record["zh-CN"], `${label}.zh-CN`),
  };
}

function requireEditionId(value: unknown, label: string): EditionId {
  if (typeof value !== "string" || !EDITION_SET.has(value)) {
    throw new Error(`${label} is unsupported`);
  }
  return value as EditionId;
}

function requireRegionIds(value: unknown, label: string): RegionId[] {
  const regions = requireStringArray(value, label);
  if (regions.length === 0 || regions.some((region) => !REGION_SET.has(region))) {
    throw new Error(`${label} contains an unsupported region`);
  }
  return regions as RegionId[];
}

function requireSourceBinding(value: unknown, label: string): DistributionSourceBinding {
  const record = requireRecord(value, label);
  requireExactKeys(record, ["path", "sha256"], label);
  const path = requireString(record.path, `${label}.path`);
  const sha256 = requireString(record.sha256, `${label}.sha256`);
  const pathSegments = path.split("/");
  if (
    path.startsWith("/")
    || path.includes("\\")
    || /^[a-zA-Z]:/.test(path)
    || pathSegments.some((segment) => segment === "." || segment === ".." || !segment)
    || !SHA256_PATTERN.test(sha256)
  ) {
    throw new Error(`${label} is unsafe or unbound`);
  }
  return { path, sha256 };
}

function parseEdition(value: unknown, index: number): DistributionEdition {
  const label = `distribution catalog editions[${index}]`;
  const record = requireRecord(value, label);
  requireExactKeys(record, [
    "editionId",
    "editionVersion",
    "displayName",
    "description",
    "implementationStatus",
    "validationTier",
    "artifactBaseName",
    "requiredModules",
    "optionalModules",
    "forbiddenModules",
    "includesLargeSimulator",
    "downloadEstimateBytes",
    "downloadEstimateState",
  ], label);
  const editionId = requireEditionId(record.editionId, `${label}.editionId`);
  const editionVersion = requireString(record.editionVersion, `${label}.editionVersion`);
  if (!VERSION_PATTERN.test(editionVersion)) {
    throw new Error(`${label}.editionVersion is invalid`);
  }
  const requiredModules = requireStringArray(record.requiredModules, `${label}.requiredModules`);
  const optionalModules = requireStringArray(record.optionalModules, `${label}.optionalModules`);
  const forbiddenModules = requireStringArray(record.forbiddenModules, `${label}.forbiddenModules`);
  const allModules = [...requiredModules, ...optionalModules, ...forbiddenModules];
  if (new Set(allModules).size !== allModules.length) {
    throw new Error(`${label} module sets must be disjoint`);
  }
  const implementationStatus = requireString(
    record.implementationStatus,
    `${label}.implementationStatus`,
  );
  if (!IMPLEMENTATION_STATUS_SET.has(implementationStatus)) {
    throw new Error(`${label}.implementationStatus is unsupported`);
  }
  const validationTier = requireString(record.validationTier, `${label}.validationTier`);
  if (implementationStatus === "contract-only" && validationTier !== "contract-only") {
    throw new Error(`${label}.validationTier overstates a contract-only edition`);
  }
  const downloadEstimateBytes = record.downloadEstimateBytes;
  if (
    downloadEstimateBytes !== null
    && (
      typeof downloadEstimateBytes !== "number"
      || !Number.isSafeInteger(downloadEstimateBytes)
      || downloadEstimateBytes <= 0
    )
  ) {
    throw new Error(`${label}.downloadEstimateBytes is invalid`);
  }
  const downloadEstimateState = requireString(
    record.downloadEstimateState,
    `${label}.downloadEstimateState`,
  );
  if (!new Set(["pending-build-plan", "verified"]).has(downloadEstimateState)) {
    throw new Error(`${label}.downloadEstimateState is unsupported`);
  }
  if (downloadEstimateState === "verified" && downloadEstimateBytes === null) {
    throw new Error(`${label} cannot claim a verified estimate without bytes`);
  }
  if (downloadEstimateState === "pending-build-plan" && downloadEstimateBytes !== null) {
    throw new Error(`${label} cannot publish bytes before the build plan is verified`);
  }
  if (typeof record.includesLargeSimulator !== "boolean") {
    throw new Error(`${label}.includesLargeSimulator must be boolean`);
  }
  return {
    editionId,
    editionVersion,
    displayName: requireLocalizedText(record.displayName, `${label}.displayName`),
    description: requireLocalizedText(record.description, `${label}.description`),
    implementationStatus: implementationStatus as DistributionImplementationStatus,
    validationTier,
    artifactBaseName: requireString(record.artifactBaseName, `${label}.artifactBaseName`),
    requiredModules,
    optionalModules,
    forbiddenModules,
    includesLargeSimulator: record.includesLargeSimulator,
    downloadEstimateBytes,
    downloadEstimateState: downloadEstimateState as DistributionEdition["downloadEstimateState"],
  };
}

function parseController(value: unknown, label: string): DistributionController {
  const record = requireRecord(value, label);
  requireExactKeys(record, ["vendor", "model", "status", "regions"], label);
  const status = requireString(record.status, `${label}.status`);
  if (!VALIDATION_STATUS_SET.has(status)) throw new Error(`${label}.status is unsupported`);
  return {
    vendor: requireString(record.vendor, `${label}.vendor`),
    model: requireString(record.model, `${label}.model`),
    status: status as DistributionValidationStatus,
    regions: requireRegionIds(record.regions, `${label}.regions`),
  };
}

function parseVehiclePack(value: unknown, index: number): DistributionVehiclePack {
  const label = `distribution catalog vehiclePacks[${index}]`;
  const record = requireRecord(value, label);
  requireExactKeys(record, [
    "packId",
    "packVersion",
    "displayName",
    "manufacturer",
    "vehicleClass",
    "supportRegions",
    "supportedEditions",
    "validationStatus",
    "validationTier",
    "autopilotFamily",
    "adapterStatus",
    "controllers",
    "segments",
    "goldenCandidate",
    "productAvailability",
    "manifestSha256",
  ], label);
  const packId = requireString(record.packId, `${label}.packId`);
  if (!SAFE_ID_PATTERN.test(packId)) throw new Error(`${label}.packId is invalid`);
  const packVersion = requireString(record.packVersion, `${label}.packVersion`);
  if (!VERSION_PATTERN.test(packVersion)) throw new Error(`${label}.packVersion is invalid`);
  const validationStatus = requireString(record.validationStatus, `${label}.validationStatus`);
  if (!VALIDATION_STATUS_SET.has(validationStatus)) {
    throw new Error(`${label}.validationStatus is unsupported`);
  }
  const validationTier = requireString(record.validationTier, `${label}.validationTier`);
  if (
    (validationStatus === "planned" && validationTier !== "planned")
    || (validationStatus === "contract-only" && validationTier !== "contract-only")
    || (
      validationStatus === "validated"
      && (validationTier === "planned" || validationTier === "contract-only")
    )
  ) {
    throw new Error(`${label}.validationTier overstates or contradicts validation status`);
  }
  const supportedEditions = requireStringArray(
    record.supportedEditions,
    `${label}.supportedEditions`,
  );
  if (
    supportedEditions.length === 0
    || supportedEditions.some((edition) => !EDITION_SET.has(edition))
  ) {
    throw new Error(`${label}.supportedEditions contains an unsupported edition`);
  }
  if (!Array.isArray(record.controllers)) throw new Error(`${label}.controllers must be an array`);
  const controllers = record.controllers.map((controller, controllerIndex) => (
    parseController(controller, `${label}.controllers[${controllerIndex}]`)
  ));
  const validationRank: Record<DistributionValidationStatus, number> = {
    planned: 0,
    "contract-only": 1,
    validated: 2,
  };
  if (controllers.some((controller) => (
    validationRank[controller.status] > validationRank[validationStatus as DistributionValidationStatus]
  ))) {
    throw new Error(`${label}.controllers cannot overstate Vehicle Pack validation`);
  }
  const controllerKeys = controllers.map(controllerKey);
  if (new Set(controllerKeys).size !== controllerKeys.length) {
    throw new Error(`${label}.controllers must not contain duplicates`);
  }
  const manifestSha256 = requireString(record.manifestSha256, `${label}.manifestSha256`);
  if (!SHA256_PATTERN.test(manifestSha256)) {
    throw new Error(`${label}.manifestSha256 is invalid`);
  }
  const autopilotFamily = requireString(record.autopilotFamily, `${label}.autopilotFamily`);
  if (!AUTOPILOT_FAMILY_SET.has(autopilotFamily)) {
    throw new Error(`${label}.autopilotFamily is unsupported`);
  }
  const adapterStatus = requireString(record.adapterStatus, `${label}.adapterStatus`);
  if (!ADAPTER_STATUS_SET.has(adapterStatus)) {
    throw new Error(`${label}.adapterStatus is unsupported`);
  }
  const productAvailability = requireString(
    record.productAvailability,
    `${label}.productAvailability`,
  );
  if (!PRODUCT_AVAILABILITY_SET.has(productAvailability)) {
    throw new Error(`${label}.productAvailability is unsupported`);
  }
  if (typeof record.goldenCandidate !== "boolean") {
    throw new Error(`${label}.goldenCandidate must be boolean`);
  }
  if (record.goldenCandidate && validationStatus === "planned") {
    throw new Error(`${label} cannot mark a planned pack as a golden candidate`);
  }
  return {
    packId,
    packVersion,
    displayName: requireLocalizedText(record.displayName, `${label}.displayName`),
    manufacturer: requireString(record.manufacturer, `${label}.manufacturer`),
    vehicleClass: requireString(record.vehicleClass, `${label}.vehicleClass`),
    supportRegions: requireRegionIds(record.supportRegions, `${label}.supportRegions`),
    supportedEditions: supportedEditions as EditionId[],
    validationStatus: validationStatus as DistributionValidationStatus,
    validationTier,
    autopilotFamily: autopilotFamily as DistributionVehiclePack["autopilotFamily"],
    adapterStatus: adapterStatus as DistributionVehiclePack["adapterStatus"],
    controllers,
    segments: requireStringArray(record.segments, `${label}.segments`),
    goldenCandidate: record.goldenCandidate,
    productAvailability: productAvailability as DistributionVehiclePack["productAvailability"],
    manifestSha256,
  };
}

export function validateDistributionCatalog(value: unknown): DistributionCatalog {
  const record = requireRecord(value, "distribution catalog");
  requireExactKeys(record, [
    "schemaVersion",
    "kind",
    "catalogVersion",
    "productDisplayVersion",
    "sourceBindings",
    "editions",
    "vehiclePacks",
  ], "distribution catalog");
  if (
    record.schemaVersion !== 1
    || record.kind !== "dronedream-frontend-distribution-catalog"
  ) {
    throw new Error("distribution catalog identity is unsupported");
  }
  const catalogVersion = requireString(record.catalogVersion, "distribution catalog version");
  if (!VERSION_PATTERN.test(catalogVersion) || record.productDisplayVersion !== "1.0.0") {
    throw new Error("distribution catalog version is unsupported");
  }
  const sourceBindings = requireRecord(record.sourceBindings, "distribution catalog sourceBindings");
  requireExactKeys(
    sourceBindings,
    ["editionManifests", "vehiclePackRegistry"],
    "distribution catalog sourceBindings",
  );
  const editionBindings = requireRecord(
    sourceBindings.editionManifests,
    "distribution catalog editionManifests",
  );
  requireExactKeys(editionBindings, EDITION_IDS, "distribution catalog editionManifests");
  const parsedEditionBindings = Object.fromEntries(EDITION_IDS.map((editionId) => [
    editionId,
    requireSourceBinding(
      editionBindings[editionId],
      `distribution catalog editionManifests.${editionId}`,
    ),
  ])) as Record<EditionId, DistributionSourceBinding>;
  if (!Array.isArray(record.editions)) throw new Error("distribution catalog editions must be an array");
  const editions = record.editions.map(parseEdition);
  if (
    editions.length !== EDITION_IDS.length
    || new Set(editions.map((edition) => edition.editionId)).size !== EDITION_IDS.length
  ) {
    throw new Error("distribution catalog must contain exactly Sim, Lab, and Field");
  }
  if (!Array.isArray(record.vehiclePacks)) {
    throw new Error("distribution catalog vehiclePacks must be an array");
  }
  const vehiclePacks = record.vehiclePacks.map(parseVehiclePack);
  if (
    vehiclePacks.length < 6
    || vehiclePacks.length > 8
    || new Set(vehiclePacks.map((pack) => pack.packId)).size !== vehiclePacks.length
  ) {
    throw new Error("distribution catalog must contain 6 to 8 unique Vehicle Packs");
  }
  if (vehiclePacks.filter((pack) => pack.goldenCandidate).length !== 3) {
    throw new Error("distribution catalog must contain exactly three golden candidates");
  }
  return {
    schemaVersion: 1,
    kind: "dronedream-frontend-distribution-catalog",
    catalogVersion,
    productDisplayVersion: "1.0.0",
    sourceBindings: {
      editionManifests: parsedEditionBindings,
      vehiclePackRegistry: requireSourceBinding(
        sourceBindings.vehiclePackRegistry,
        "distribution catalog vehiclePackRegistry",
      ),
    },
    editions,
    vehiclePacks,
  };
}

export function controllerKey(controller: DistributionController): string {
  return `${controller.vendor}::${controller.model}`;
}

export function localizedDistributionText(
  value: LocalizedText,
  locale: DistributionLocale,
): string {
  return value[locale];
}

export const DISTRIBUTION_CATALOG = validateDistributionCatalog(rawCatalog);
