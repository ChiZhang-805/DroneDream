export const primaryEditionIds = ["sim", "lab", "field"] as const;
export const editionIds = [...primaryEditionIds, "universal"] as const;

export type EditionId = (typeof editionIds)[number];
export type PrimaryEditionId = (typeof primaryEditionIds)[number];
export type EditionReleaseStatus = "planned-not-built" | "published";
export type EditionAvailability = "unavailable" | "downloadable";
export type EditionSignatureState = "not-provided" | "signed";

export type EditionArtifact = {
  id: EditionId;
  releaseStatus: EditionReleaseStatus;
  availability: EditionAvailability;
  signatureState: EditionSignatureState;
  version: string;
  fileName: string;
  downloadUrl: string | null;
  checksumUrl: string | null;
  signatureUrl: string | null;
  receiptUrl: string | null;
  urlFamily: string | null;
  sizeBytes: number | null;
  sha256: string | null;
  sourceCommit: string | null;
  publishedAt: string | null;
};

export type EditionAvailabilityDocument = {
  schemaVersion: 3;
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
    availability: "unavailable",
    signatureState: "not-provided",
    version: "1.0.0",
    fileName: `DroneDream-${displayId}-1.0.0.exe`,
    downloadUrl: null,
    checksumUrl: null,
    signatureUrl: null,
    receiptUrl: null,
    urlFamily: null,
    sizeBytes: null,
    sha256: null,
    sourceCommit: null,
    publishedAt: null,
  };
}

export const fallbackEditionAvailability: EditionAvailabilityDocument = {
  schemaVersion: 3,
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

export function artifactUrlFamily(value: string, expectedFileName: string) {
  if (value === `/downloads/${expectedFileName}`) return "/downloads";
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
    ) return null;
    const prefix = "/ChiZhang-805/DroneDream/releases/download/";
    if (!url.pathname.startsWith(prefix)) return null;
    const remainder = url.pathname.slice(prefix.length);
    const separator = remainder.indexOf("/");
    const releaseTag = remainder.slice(0, separator);
    if (
      separator <= 0 ||
      !/^[A-Za-z0-9._-]+$/u.test(releaseTag) ||
      remainder.slice(separator + 1) !== expectedFileName
    ) return null;
    return `${url.origin}${prefix}${releaseTag}`;
  } catch {
    return null;
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
    "id", "releaseStatus", "availability", "signatureState", "version",
    "fileName", "downloadUrl", "checksumUrl", "signatureUrl", "receiptUrl",
    "urlFamily", "sizeBytes", "sha256", "sourceCommit", "publishedAt",
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
    edition.receiptUrl,
    edition.urlFamily,
    edition.sizeBytes,
    edition.sha256,
    edition.sourceCommit,
    edition.publishedAt,
  ];
  if (edition.releaseStatus === "planned-not-built") {
    return edition.availability === "unavailable" &&
      edition.signatureState === "not-provided" &&
      nullableFields.every((field) => field === null);
  }
  if (edition.releaseStatus !== "published") return false;
  if (
    edition.availability !== "downloadable" ||
    edition.signatureState !== "signed" ||
    typeof edition.downloadUrl !== "string" ||
    typeof edition.checksumUrl !== "string" ||
    typeof edition.signatureUrl !== "string" ||
    typeof edition.receiptUrl !== "string" ||
    typeof edition.urlFamily !== "string" ||
    typeof edition.sizeBytes !== "number" ||
    !Number.isSafeInteger(edition.sizeBytes) ||
    edition.sizeBytes <= 0 ||
    typeof edition.sha256 !== "string" ||
    !/^[a-f\d]{64}$/u.test(edition.sha256) ||
    typeof edition.sourceCommit !== "string" ||
    !/^[a-f\d]{40}$/u.test(edition.sourceCommit) ||
    typeof edition.publishedAt !== "string" ||
    !isIsoCalendarDate(edition.publishedAt)
  ) return false;

  const fileName = edition.fileName as string;
  const families = [
    artifactUrlFamily(edition.downloadUrl, fileName),
    artifactUrlFamily(edition.checksumUrl, `${fileName}.sha256`),
    artifactUrlFamily(edition.signatureUrl, `${fileName}.sig`),
    artifactUrlFamily(edition.receiptUrl, `${fileName}.receipt.json`),
  ];
  return families.every((family) => family === edition.urlFamily);
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
    document.schemaVersion !== 3 ||
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
  if (!editionIds.every((id, index) => isEditionArtifact(editions[index], id))) return false;

  const generatedAt = document.generatedAt as string;
  const published = editions.filter((edition) => (
    (edition as EditionArtifact).releaseStatus === "published"
  )) as EditionArtifact[];
  if (published.some((edition) => edition.publishedAt! > generatedAt)) return false;
  for (const field of ["downloadUrl", "checksumUrl", "signatureUrl", "receiptUrl", "sha256"] as const) {
    const values = published.map((edition) => edition[field]);
    if (new Set(values).size !== values.length) return false;
  }
  return true;
}

export function isEditionDownloadReady(edition: EditionArtifact) {
  return editionIds.includes(edition.id) &&
    edition.releaseStatus === "published" &&
    isEditionArtifact(edition, edition.id);
}
