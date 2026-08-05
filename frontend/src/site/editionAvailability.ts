export const primaryEditionIds = ["sim", "lab", "field"] as const;
export const editionIds = [...primaryEditionIds, "universal"] as const;

export type EditionId = (typeof editionIds)[number];
export type PrimaryEditionId = (typeof primaryEditionIds)[number];
export type EditionReleaseStatus = "planned-not-built" | "published";

export type EditionArtifact = {
  id: EditionId;
  releaseStatus: EditionReleaseStatus;
  version: string;
  fileName: string;
  downloadUrl: string | null;
  checksumUrl: string | null;
  signatureUrl: string | null;
  sizeBytes: number | null;
  sha256: string | null;
  sourceCommit: string | null;
  publishedAt: string | null;
};

export type EditionAvailabilityDocument = {
  schemaVersion: 1;
  generatedAt: string;
  vehiclePacks: {
    total: number;
    validated: number;
    contractOnly: number;
    planned: number;
    selectionStage: "post-install";
  };
  editions: EditionArtifact[];
};

function plannedEdition(id: EditionId): EditionArtifact {
  const displayId = `${id.slice(0, 1).toUpperCase()}${id.slice(1)}`;
  return {
    id,
    releaseStatus: "planned-not-built",
    version: "1.0.0",
    fileName: `DroneDream-${displayId}-1.0.0.exe`,
    downloadUrl: null,
    checksumUrl: null,
    signatureUrl: null,
    sizeBytes: null,
    sha256: null,
    sourceCommit: null,
    publishedAt: null,
  };
}

export const fallbackEditionAvailability: EditionAvailabilityDocument = {
  schemaVersion: 1,
  generatedAt: "2026-08-05",
  vehiclePacks: {
    total: 8,
    validated: 0,
    contractOnly: 5,
    planned: 3,
    selectionStage: "post-install",
  },
  editions: editionIds.map(plannedEdition),
};

function isIsoCalendarDate(value: string) {
  if (!/^\d{4}-\d{2}-\d{2}$/u.test(value)) return false;
  const parsed = new Date(`${value}T00:00:00Z`);
  return !Number.isNaN(parsed.getTime()) && parsed.toISOString().slice(0, 10) === value;
}

function isAllowedArtifactUrl(value: string, expectedFileName: string) {
  if (value === `/downloads/${expectedFileName}`) return true;
  try {
    const url = new URL(value);
    if (
      url.protocol !== "https:" ||
      url.hostname !== "github.com" ||
      url.port ||
      url.username ||
      url.password ||
      url.search ||
      url.hash
    ) return false;
    const prefix = "/ChiZhang-805/DroneDream/releases/download/";
    if (!url.pathname.startsWith(prefix)) return false;
    const remainder = url.pathname.slice(prefix.length);
    const separator = remainder.indexOf("/");
    return separator > 0 &&
      /^[A-Za-z0-9._-]+$/u.test(remainder.slice(0, separator)) &&
      remainder.slice(separator + 1) === expectedFileName;
  } catch {
    return false;
  }
}

function hasExactKeys(value: Record<string, unknown>, expected: string[]) {
  const keys = Object.keys(value).sort();
  return keys.length === expected.length &&
    keys.every((key, index) => key === [...expected].sort()[index]);
}

function isEditionArtifact(value: unknown, expectedId: EditionId): value is EditionArtifact {
  if (!value || typeof value !== "object") return false;
  const edition = value as Record<string, unknown>;
  if (!hasExactKeys(edition, [
    "id", "releaseStatus", "version", "fileName", "downloadUrl",
    "checksumUrl", "signatureUrl", "sizeBytes", "sha256", "sourceCommit",
    "publishedAt",
  ])) return false;
  if (
    edition.id !== expectedId ||
    edition.version !== "1.0.0" ||
    edition.fileName !== `DroneDream-${expectedId.slice(0, 1).toUpperCase()}${expectedId.slice(1)}-1.0.0.exe`
  ) return false;

  const nullableFields = [
    edition.downloadUrl,
    edition.checksumUrl,
    edition.signatureUrl,
    edition.sizeBytes,
    edition.sha256,
    edition.sourceCommit,
    edition.publishedAt,
  ];
  if (edition.releaseStatus === "planned-not-built") {
    return nullableFields.every((field) => field === null);
  }
  if (edition.releaseStatus !== "published") return false;
  if (
    typeof edition.downloadUrl !== "string" ||
    typeof edition.checksumUrl !== "string" ||
    typeof edition.signatureUrl !== "string" ||
    typeof edition.sizeBytes !== "number" ||
    !Number.isSafeInteger(edition.sizeBytes) ||
    edition.sizeBytes <= 0 ||
    typeof edition.sha256 !== "string" ||
    !/^[a-f\d]{64}$/iu.test(edition.sha256) ||
    typeof edition.sourceCommit !== "string" ||
    !/^[a-f\d]{40}$/iu.test(edition.sourceCommit) ||
    typeof edition.publishedAt !== "string" ||
    !isIsoCalendarDate(edition.publishedAt)
  ) return false;

  const fileName = edition.fileName as string;
  return isAllowedArtifactUrl(edition.downloadUrl, fileName) &&
    isAllowedArtifactUrl(edition.checksumUrl, `${fileName}.sha256`) &&
    isAllowedArtifactUrl(edition.signatureUrl, `${fileName}.sig`);
}

export function isEditionAvailabilityDocument(
  value: unknown,
): value is EditionAvailabilityDocument {
  if (!value || typeof value !== "object") return false;
  const document = value as Record<string, unknown>;
  if (!hasExactKeys(document, ["schemaVersion", "generatedAt", "vehiclePacks", "editions"])) {
    return false;
  }
  if (
    document.schemaVersion !== 1 ||
    typeof document.generatedAt !== "string" ||
    !isIsoCalendarDate(document.generatedAt) ||
    !document.vehiclePacks ||
    typeof document.vehiclePacks !== "object" ||
    !Array.isArray(document.editions) ||
    document.editions.length !== editionIds.length
  ) return false;

  const packs = document.vehiclePacks as Record<string, unknown>;
  if (!hasExactKeys(packs, ["total", "validated", "contractOnly", "planned", "selectionStage"])) {
    return false;
  }
  const counts = [packs.total, packs.validated, packs.contractOnly, packs.planned];
  if (
    packs.selectionStage !== "post-install" ||
    !counts.every((count) => typeof count === "number" && Number.isSafeInteger(count) && count >= 0) ||
    packs.total !== (packs.validated as number) + (packs.contractOnly as number) + (packs.planned as number)
  ) return false;

  const editions = document.editions as unknown[];
  return editionIds.every((id, index) => isEditionArtifact(editions[index], id));
}

export function isEditionDownloadReady(edition: EditionArtifact) {
  return editionIds.includes(edition.id) &&
    edition.releaseStatus === "published" &&
    isEditionArtifact(edition, edition.id);
}
