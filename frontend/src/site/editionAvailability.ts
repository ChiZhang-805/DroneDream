export const primaryEditionIds = ["sim", "lab", "field"] as const;

export type PrimaryEditionId = (typeof primaryEditionIds)[number];

export const editionInstallerNames: Record<PrimaryEditionId, string> = {
  sim: "DroneDream-Sim_1.0.0_x64-setup.exe",
  lab: "DroneDream-Lab_1.0.0_x64-setup.exe",
  field: "DroneDream-Field_1.0.0_x64-setup.exe",
};

const formalEditionInstallerNames: Record<PrimaryEditionId, string> = {
  sim: "DroneDream-Sim-1.0.0.exe",
  lab: "DroneDream-Lab-1.0.0.exe",
  field: "DroneDream-Field-1.0.0.exe",
};

export type EditionArtifact = {
  id: PrimaryEditionId;
  status: "unavailable" | "published";
  version: "1.0.0";
  fileName: string;
  downloadUrl: string | null;
  checksumUrl: string | null;
  signatureUrl: string | null;
  receiptUrl: string | null;
  sizeBytes: number | null;
  sha256: string | null;
  sourceCommit: string | null;
  publishedAt: string | null;
};

export type EditionAvailabilityDocument = {
  schemaVersion: 1;
  generatedAt: string;
  editions: EditionArtifact[];
};

function unavailableEdition(id: PrimaryEditionId): EditionArtifact {
  return {
    id,
    status: "unavailable",
    version: "1.0.0",
    fileName: editionInstallerNames[id],
    downloadUrl: null,
    checksumUrl: null,
    signatureUrl: null,
    receiptUrl: null,
    sizeBytes: null,
    sha256: null,
    sourceCommit: null,
    publishedAt: null,
  };
}

export const fallbackEditionAvailability: EditionAvailabilityDocument = {
  schemaVersion: 1,
  generatedAt: "2026-08-11",
  editions: primaryEditionIds.map(unavailableEdition),
};

function hasExactKeys(value: Record<string, unknown>, expected: readonly string[]) {
  const actual = Object.keys(value).sort();
  const wanted = [...expected].sort();
  return actual.length === wanted.length
    && actual.every((key, index) => key === wanted[index]);
}

function isIsoDate(value: unknown): value is string {
  if (typeof value !== "string" || !/^\d{4}-\d{2}-\d{2}$/u.test(value)) return false;
  const parsed = new Date(`${value}T00:00:00Z`);
  return !Number.isNaN(parsed.getTime()) && parsed.toISOString().slice(0, 10) === value;
}

function releaseFamily(urlValue: string, expectedName: string) {
  try {
    const url = new URL(urlValue);
    if (
      url.protocol !== "https:"
      || url.hostname !== "github.com"
      || url.username
      || url.password
      || url.port
      || url.search
      || url.hash
    ) return null;
    const prefix = "/ChiZhang-805/DroneDream/releases/download/";
    if (!url.pathname.startsWith(prefix)) return null;
    const remainder = url.pathname.slice(prefix.length);
    const separator = remainder.indexOf("/");
    if (separator <= 0 || remainder.slice(separator + 1) !== expectedName) return null;
    const tag = remainder.slice(0, separator);
    if (!/^[A-Za-z0-9._-]+$/u.test(tag)) return null;
    return `${url.origin}${prefix}${tag}`;
  } catch {
    return null;
  }
}

function isEditionArtifact(value: unknown, expectedId: PrimaryEditionId): value is EditionArtifact {
  if (!value || typeof value !== "object") return false;
  const edition = value as Record<string, unknown>;
  if (!hasExactKeys(edition, [
    "id", "status", "version", "fileName", "downloadUrl", "checksumUrl",
    "signatureUrl", "receiptUrl", "sizeBytes", "sha256", "sourceCommit", "publishedAt",
  ])) return false;
  if (
    edition.id !== expectedId
    || edition.version !== "1.0.0"
    || (
      edition.fileName !== editionInstallerNames[expectedId]
      && edition.fileName !== formalEditionInstallerNames[expectedId]
    )
  ) return false;

  const releaseFields = [
    edition.downloadUrl,
    edition.checksumUrl,
    edition.signatureUrl,
    edition.receiptUrl,
    edition.sizeBytes,
    edition.sha256,
    edition.sourceCommit,
    edition.publishedAt,
  ];
  if (edition.status === "unavailable") {
    return releaseFields.every((field) => field === null);
  }
  if (
    edition.status !== "published"
    || typeof edition.downloadUrl !== "string"
    || typeof edition.checksumUrl !== "string"
    || typeof edition.signatureUrl !== "string"
    || typeof edition.receiptUrl !== "string"
    || typeof edition.sizeBytes !== "number"
    || !Number.isSafeInteger(edition.sizeBytes)
    || edition.sizeBytes <= 0
    || typeof edition.sha256 !== "string"
    || !/^[a-f\d]{64}$/u.test(edition.sha256)
    || typeof edition.sourceCommit !== "string"
    || !/^[a-f\d]{40}$/u.test(edition.sourceCommit)
    || !isIsoDate(edition.publishedAt)
  ) return false;

  const fileName = edition.fileName as string;
  const family = releaseFamily(edition.downloadUrl, fileName);
  return family !== null
    && releaseFamily(edition.checksumUrl, `${fileName}.sha256`) === family
    && releaseFamily(edition.signatureUrl, `${fileName}.sig`) === family
    && releaseFamily(edition.receiptUrl, `${fileName}.receipt.json`) === family;
}

export function isEditionAvailabilityDocument(
  value: unknown,
): value is EditionAvailabilityDocument {
  if (!value || typeof value !== "object") return false;
  const document = value as Record<string, unknown>;
  if (!hasExactKeys(document, ["schemaVersion", "generatedAt", "editions"])) return false;
  if (
    document.schemaVersion !== 1
    || !isIsoDate(document.generatedAt)
    || !Array.isArray(document.editions)
    || document.editions.length !== primaryEditionIds.length
  ) return false;
  const editions = document.editions as unknown[];
  return primaryEditionIds.every((id, index) => isEditionArtifact(editions[index], id));
}
