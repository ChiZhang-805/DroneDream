import {
  editionIds,
  isEditionDownloadReady,
  type EditionArtifact,
  type EditionAvailabilityDocument,
  type EditionId,
} from "./editionAvailability.ts";

export const editionThemes = {
  sim: { accentA: "#00D9FF", accentB: "#2671FF", accentC: "#744CFF" },
  lab: { accentA: "#A7E84A", accentB: "#20C77A", accentC: "#087E69" },
  field: { accentA: "#FFC247", accentB: "#FF754B", accentC: "#D746A5" },
  universal: { accentA: "#FF5574", accentB: "#6A4CFF", accentC: "#E657D1" },
} as const satisfies Record<EditionId, {
  accentA: string;
  accentB: string;
  accentC: string;
}>;

export type EditionArtifactBinding = {
  fileName: string;
  sourceCommit: string | null;
  sizeBytes: number | null;
  sha256: string | null;
  signatureState: EditionArtifact["signatureState"];
  receiptUrl: string | null;
  urlFamily: string | null;
};

export type EditionReleaseRegistryEntry = {
  id: EditionId;
  artifact: EditionArtifactBinding;
  downloadReady: boolean;
  downloadUrl: string | null;
  checksumUrl: string | null;
  signatureUrl: string | null;
  theme: (typeof editionThemes)[EditionId];
};

export type EditionReleaseRegistry = {
  schemaVersion: 1;
  sourceSchemaVersion: 3;
  generatedAt: string;
  entries: EditionReleaseRegistryEntry[];
};

export function buildEditionReleaseRegistry(
  availability: EditionAvailabilityDocument,
): EditionReleaseRegistry {
  const entries = editionIds.map((id) => {
    const edition = availability.editions.find((candidate) => candidate.id === id);
    if (!edition) throw new Error(`Missing required edition metadata: ${id}`);
    const downloadReady = isEditionDownloadReady(edition);
    return {
      id,
      artifact: {
        fileName: edition.fileName,
        sourceCommit: edition.sourceCommit,
        sizeBytes: edition.sizeBytes,
        sha256: edition.sha256,
        signatureState: edition.signatureState,
        receiptUrl: edition.receiptUrl,
        urlFamily: edition.urlFamily,
      },
      downloadReady,
      downloadUrl: downloadReady ? edition.downloadUrl : null,
      checksumUrl: downloadReady ? edition.checksumUrl : null,
      signatureUrl: downloadReady ? edition.signatureUrl : null,
      theme: editionThemes[id],
    } satisfies EditionReleaseRegistryEntry;
  });
  return {
    schemaVersion: 1,
    sourceSchemaVersion: availability.schemaVersion,
    generatedAt: availability.generatedAt,
    entries,
  };
}

export function getEditionRelease(
  registry: EditionReleaseRegistry,
  id: EditionId,
) {
  const release = registry.entries.find((candidate) => candidate.id === id);
  if (!release) throw new Error(`Missing required edition release: ${id}`);
  return release;
}

export type EditionAcceptedHandoff = {
  fileName: string;
  sourceCommit: string;
  sizeBytes: number;
  sha256: string;
  signatureState: "signed";
  receiptUrl: string;
  urlFamily: string;
  downloadUrl: string;
  checksumUrl: string;
  signatureUrl: string;
  publishedAt: string;
  checksumSha256: string;
  checksumSizeBytes: number;
  signatureSha256: string;
  signatureSizeBytes: number;
  receiptSha256: string;
  receiptSizeBytes: number;
};

export type EditionHandoffEntry = {
  id: EditionId;
  sourceBranch: string;
  observedRemoteHead: string;
  handoffStatus: "awaiting-exact-handoff" | "accepted-release-ready";
  acceptedArtifact: EditionAcceptedHandoff | null;
  note: string;
};

export type EditionHandoffRegistry = {
  schemaVersion: 1;
  generatedAt: string;
  contract: "dronedream.exact-edition-exe-handoff.v1";
  editions: EditionHandoffEntry[];
};

const editionSourceBranches: Record<EditionId, string> = {
  sim: "codex/software-sim",
  lab: "codex/software-lab",
  field: "codex/software-field",
  universal: "codex/software",
};

function hasExactKeys(value: Record<string, unknown>, expected: string[]) {
  const keys = Object.keys(value).sort();
  const sortedExpected = [...expected].sort();
  return keys.length === sortedExpected.length &&
    keys.every((key, index) => key === sortedExpected[index]);
}

function acceptedHandoffMatches(
  value: unknown,
  release: EditionReleaseRegistryEntry,
  availability: EditionAvailabilityDocument,
) {
  if (!value || typeof value !== "object") return false;
  const handoff = value as Record<string, unknown>;
  if (!hasExactKeys(handoff, [
    "fileName", "sourceCommit", "sizeBytes", "sha256", "signatureState",
    "receiptUrl", "urlFamily", "downloadUrl", "checksumUrl", "signatureUrl",
    "publishedAt", "checksumSha256", "checksumSizeBytes", "signatureSha256",
    "signatureSizeBytes", "receiptSha256", "receiptSizeBytes",
  ])) return false;
  const edition = availability.editions.find((candidate) => candidate.id === release.id);
  if (!edition || !release.downloadReady) return false;
  return handoff.fileName === release.artifact.fileName &&
    handoff.sourceCommit === release.artifact.sourceCommit &&
    handoff.sizeBytes === release.artifact.sizeBytes &&
    handoff.sha256 === release.artifact.sha256 &&
    handoff.signatureState === release.artifact.signatureState &&
    handoff.receiptUrl === release.artifact.receiptUrl &&
    handoff.urlFamily === release.artifact.urlFamily &&
    handoff.downloadUrl === release.downloadUrl &&
    handoff.checksumUrl === release.checksumUrl &&
    handoff.signatureUrl === release.signatureUrl &&
    typeof handoff.checksumSha256 === "string" &&
    /^[a-f\d]{64}$/u.test(handoff.checksumSha256) &&
    typeof handoff.checksumSizeBytes === "number" &&
    Number.isSafeInteger(handoff.checksumSizeBytes) && handoff.checksumSizeBytes > 0 &&
    typeof handoff.signatureSha256 === "string" &&
    /^[a-f\d]{64}$/u.test(handoff.signatureSha256) &&
    typeof handoff.signatureSizeBytes === "number" &&
    Number.isSafeInteger(handoff.signatureSizeBytes) && handoff.signatureSizeBytes > 0 &&
    typeof handoff.receiptSha256 === "string" &&
    /^[a-f\d]{64}$/u.test(handoff.receiptSha256) &&
    typeof handoff.receiptSizeBytes === "number" &&
    Number.isSafeInteger(handoff.receiptSizeBytes) && handoff.receiptSizeBytes > 0 &&
    handoff.publishedAt === edition.publishedAt;
}

export function isEditionHandoffRegistry(
  value: unknown,
  availability: EditionAvailabilityDocument,
): value is EditionHandoffRegistry {
  if (!value || typeof value !== "object") return false;
  const document = value as Record<string, unknown>;
  if (!hasExactKeys(document, ["schemaVersion", "generatedAt", "contract", "editions"])) {
    return false;
  }
  if (
    document.schemaVersion !== 1 ||
    document.generatedAt !== availability.generatedAt ||
    document.contract !== "dronedream.exact-edition-exe-handoff.v1" ||
    !Array.isArray(document.editions) ||
    document.editions.length !== editionIds.length
  ) return false;

  const registry = buildEditionReleaseRegistry(availability);
  const rawEditions = document.editions as unknown[];
  const entriesValid = editionIds.every((id, index) => {
    const rawEntry = rawEditions[index];
    if (!rawEntry || typeof rawEntry !== "object") return false;
    const entry = rawEntry as Record<string, unknown>;
    if (!hasExactKeys(entry, [
      "id", "sourceBranch", "observedRemoteHead", "handoffStatus",
      "acceptedArtifact", "note",
    ])) return false;
    if (
      entry.id !== id ||
      entry.sourceBranch !== editionSourceBranches[id] ||
      typeof entry.observedRemoteHead !== "string" ||
      !/^[a-f\d]{40}$/u.test(entry.observedRemoteHead) ||
      typeof entry.note !== "string" ||
      entry.note.length === 0
    ) return false;
    const release = getEditionRelease(registry, id);
    if (entry.handoffStatus === "awaiting-exact-handoff") {
      return entry.acceptedArtifact === null && !release.downloadReady &&
        release.artifact.sourceCommit === null &&
        release.artifact.sizeBytes === null &&
        release.artifact.sha256 === null &&
        release.artifact.signatureState === "not-provided" &&
        release.artifact.receiptUrl === null &&
        release.artifact.urlFamily === null;
    }
    return entry.handoffStatus === "accepted-release-ready" &&
      acceptedHandoffMatches(entry.acceptedArtifact, release, availability);
  });
  if (!entriesValid) return false;
  const accepted = rawEditions
    .map((entry) => (entry as EditionHandoffEntry).acceptedArtifact)
    .filter((artifact): artifact is EditionAcceptedHandoff => artifact !== null);
  const hashes = accepted.flatMap((artifact) => [
    artifact.sha256,
    artifact.checksumSha256,
    artifact.signatureSha256,
    artifact.receiptSha256,
  ]);
  return new Set(hashes).size === hashes.length;
}

export type EditionPublicationFile = {
  kind: "installer" | "checksum" | "signature" | "receipt";
  fileName: string;
  sourceUrl: string;
  sha256: string;
  sizeBytes: number;
};

export type EditionPublicationEntry = {
  id: EditionId;
  sourceCommit: string;
  urlFamily: string;
  files: EditionPublicationFile[];
};

export type EditionPublicationPlan = {
  schemaVersion: 1;
  generatedAt: string;
  entries: EditionPublicationEntry[];
};

export function buildEditionPublicationPlan(
  availability: EditionAvailabilityDocument,
  handoffs: EditionHandoffRegistry,
): EditionPublicationPlan {
  if (!isEditionHandoffRegistry(handoffs, availability)) {
    throw new Error("Edition handoffs do not match release metadata");
  }
  const registry = buildEditionReleaseRegistry(availability);
  const entries = editionIds.flatMap((id) => {
    const release = getEditionRelease(registry, id);
    const handoff = handoffs.editions.find((candidate) => candidate.id === id);
    if (!release.downloadReady) return [];
    if (!handoff?.acceptedArtifact) {
      throw new Error(`Missing accepted handoff for ${id}`);
    }
    const artifact = handoff.acceptedArtifact;
    return [{
      id,
      sourceCommit: artifact.sourceCommit,
      urlFamily: artifact.urlFamily,
      files: [
        {
          kind: "installer",
          fileName: artifact.fileName,
          sourceUrl: artifact.downloadUrl,
          sha256: artifact.sha256,
          sizeBytes: artifact.sizeBytes,
        },
        {
          kind: "checksum",
          fileName: `${artifact.fileName}.sha256`,
          sourceUrl: artifact.checksumUrl,
          sha256: artifact.checksumSha256,
          sizeBytes: artifact.checksumSizeBytes,
        },
        {
          kind: "signature",
          fileName: `${artifact.fileName}.sig`,
          sourceUrl: artifact.signatureUrl,
          sha256: artifact.signatureSha256,
          sizeBytes: artifact.signatureSizeBytes,
        },
        {
          kind: "receipt",
          fileName: `${artifact.fileName}.receipt.json`,
          sourceUrl: artifact.receiptUrl,
          sha256: artifact.receiptSha256,
          sizeBytes: artifact.receiptSizeBytes,
        },
      ],
    } satisfies EditionPublicationEntry];
  });
  return { schemaVersion: 1, generatedAt: availability.generatedAt, entries };
}
