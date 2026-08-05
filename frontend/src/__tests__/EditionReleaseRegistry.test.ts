import { describe, expect, it } from "vitest";

import handoffStatus from "../../../website/releases/edition-handoff-status.json";
import {
  fallbackEditionAvailability,
  type EditionAvailabilityDocument,
  type EditionId,
} from "../site/editionAvailability";
import {
  buildEditionReleaseRegistry,
  editionThemes,
  getEditionRelease,
  isEditionHandoffRegistry,
  type EditionHandoffRegistry,
} from "../site/editionReleaseRegistry";

function publishEdition(
  document: EditionAvailabilityDocument,
  id: EditionId,
  fingerprint: string,
) {
  const edition = document.editions.find((candidate) => candidate.id === id);
  if (!edition) throw new Error(`Missing ${id} fixture`);
  edition.releaseStatus = "published";
  edition.availability = "downloadable";
  edition.signatureState = "signed";
  edition.downloadUrl = `/downloads/${edition.fileName}`;
  edition.checksumUrl = `/downloads/${edition.fileName}.sha256`;
  edition.signatureUrl = `/downloads/${edition.fileName}.sig`;
  edition.receiptUrl = `/downloads/${edition.fileName}.receipt.json`;
  edition.urlFamily = "/downloads";
  edition.sizeBytes = 10_000_000 + fingerprint.charCodeAt(0);
  edition.sha256 = fingerprint.repeat(64);
  edition.sourceCommit = fingerprint.repeat(40);
  edition.publishedAt = document.generatedAt;
  return edition;
}

function acceptHandoff(
  registry: EditionHandoffRegistry,
  document: EditionAvailabilityDocument,
  id: EditionId,
) {
  const handoff = registry.editions.find((candidate) => candidate.id === id);
  const edition = document.editions.find((candidate) => candidate.id === id);
  if (!handoff || !edition) throw new Error(`Missing ${id} fixture`);
  Object.assign(handoff, {
    handoffStatus: "accepted-release-ready",
    acceptedArtifact: {
      fileName: edition.fileName,
      sourceCommit: edition.sourceCommit,
      sizeBytes: edition.sizeBytes,
      sha256: edition.sha256,
      signatureState: edition.signatureState,
      receiptUrl: edition.receiptUrl,
      urlFamily: edition.urlFamily,
      downloadUrl: edition.downloadUrl,
      checksumUrl: edition.checksumUrl,
      signatureUrl: edition.signatureUrl,
      publishedAt: edition.publishedAt,
    },
  });
}

describe("edition release registry", () => {
  it("keeps four independently themed downloads unavailable without exact handoffs", () => {
    const registry = buildEditionReleaseRegistry(fallbackEditionAvailability);
    expect(registry.entries.map(({ id }) => id)).toEqual(["sim", "lab", "field", "universal"]);
    expect(registry.entries.every(({ downloadReady, downloadUrl }) => (
      !downloadReady && downloadUrl === null
    ))).toBe(true);
    expect(editionThemes).toEqual({
      sim: { accentA: "#00D9FF", accentB: "#2671FF", accentC: "#744CFF" },
      lab: { accentA: "#A7E84A", accentB: "#20C77A", accentC: "#087E69" },
      field: { accentA: "#FFC247", accentB: "#FF754B", accentC: "#D746A5" },
      universal: { accentA: "#FF5574", accentB: "#6A4CFF", accentC: "#E657D1" },
    });
    expect(isEditionHandoffRegistry(handoffStatus, fallbackEditionAvailability)).toBe(true);
  });

  it("unlocks only the edition whose metadata and handoff match exactly", () => {
    const availability = structuredClone(fallbackEditionAvailability);
    publishEdition(availability, "sim", "a");
    const handoffs = structuredClone(handoffStatus) as EditionHandoffRegistry;
    acceptHandoff(handoffs, availability, "sim");
    expect(isEditionHandoffRegistry(handoffs, availability)).toBe(true);

    const registry = buildEditionReleaseRegistry(availability);
    expect(getEditionRelease(registry, "sim").downloadReady).toBe(true);
    expect(getEditionRelease(registry, "lab").downloadReady).toBe(false);
    expect(getEditionRelease(registry, "field").downloadReady).toBe(false);
    expect(getEditionRelease(registry, "universal").downloadReady).toBe(false);
  });

  it("rejects published metadata until its software-line handoff is accepted", () => {
    const availability = structuredClone(fallbackEditionAvailability);
    publishEdition(availability, "universal", "b");
    expect(isEditionHandoffRegistry(handoffStatus, availability)).toBe(false);
  });

  it("rejects cross-edition bytes, URLs, branches, and handoff fields", () => {
    const availability = structuredClone(fallbackEditionAvailability);
    publishEdition(availability, "sim", "c");
    publishEdition(availability, "lab", "d");
    const handoffs = structuredClone(handoffStatus) as EditionHandoffRegistry;
    acceptHandoff(handoffs, availability, "sim");
    acceptHandoff(handoffs, availability, "lab");

    const wrongBytes = structuredClone(handoffs);
    wrongBytes.editions[0]!.acceptedArtifact!.sha256 =
      wrongBytes.editions[1]!.acceptedArtifact!.sha256;
    expect(isEditionHandoffRegistry(wrongBytes, availability)).toBe(false);

    const wrongUrl = structuredClone(handoffs);
    wrongUrl.editions[0]!.acceptedArtifact!.downloadUrl =
      wrongUrl.editions[1]!.acceptedArtifact!.downloadUrl;
    expect(isEditionHandoffRegistry(wrongUrl, availability)).toBe(false);

    const wrongBranch = structuredClone(handoffs);
    wrongBranch.editions[0]!.sourceBranch = "codex/software-lab";
    expect(isEditionHandoffRegistry(wrongBranch, availability)).toBe(false);

    const missingReceipt = structuredClone(handoffs);
    missingReceipt.editions[0]!.acceptedArtifact!.receiptUrl = "";
    expect(isEditionHandoffRegistry(missingReceipt, availability)).toBe(false);
  });
});
