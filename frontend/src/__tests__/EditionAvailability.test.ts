import { describe, expect, it } from "vitest";

import {
  fallbackEditionAvailability,
  isEditionAvailabilityDocument,
  isEditionDownloadReady,
  type EditionAvailabilityDocument,
} from "../site/editionAvailability";

function publishedAvailability(): EditionAvailabilityDocument {
  const document = structuredClone(fallbackEditionAvailability);
  const sim = document.editions[0];
  if (!sim) throw new Error("Missing Sim edition fixture");
  sim.releaseStatus = "published";
  sim.downloadUrl = "/downloads/DroneDream-Sim-1.0.0.exe";
  sim.checksumUrl = "/downloads/DroneDream-Sim-1.0.0.exe.sha256";
  sim.signatureUrl = "/downloads/DroneDream-Sim-1.0.0.exe.sig";
  sim.sizeBytes = 12_345_678;
  sim.sha256 = "a".repeat(64);
  sim.sourceCommit = "b".repeat(40);
  sim.publishedAt = "2026-08-05";
  return document;
}

describe("edition availability metadata", () => {
  it("keeps the three planned editions ordered and unavailable", () => {
    expect(isEditionAvailabilityDocument(fallbackEditionAvailability)).toBe(true);
    expect(fallbackEditionAvailability.editions.map(({ id }) => id)).toEqual([
      "sim",
      "lab",
      "field",
    ]);
    expect(fallbackEditionAvailability.editions.map(({ fileName }) => fileName)).toEqual([
      "DroneDream-Sim-1.0.0.exe",
      "DroneDream-Lab-1.0.0.exe",
      "DroneDream-Field-1.0.0.exe",
    ]);
    expect(fallbackEditionAvailability.editions.every((edition) => (
      edition.downloadUrl === null && !isEditionDownloadReady(edition)
    ))).toBe(true);
    expect(fallbackEditionAvailability.vehiclePacks).toEqual({
      total: 8,
      validated: 0,
      contractOnly: 5,
      planned: 3,
      selectionStage: "post-install",
    });
  });

  it("enables an edition only when every exact artifact binding is present", () => {
    const document = publishedAvailability();
    expect(isEditionAvailabilityDocument(document)).toBe(true);
    expect(isEditionDownloadReady(document.editions[0]!)).toBe(true);

    for (const field of [
      "downloadUrl",
      "checksumUrl",
      "signatureUrl",
      "sizeBytes",
      "sha256",
      "sourceCommit",
      "publishedAt",
    ] as const) {
      const incomplete = publishedAvailability();
      Object.assign(incomplete.editions[0]!, { [field]: null });
      expect(isEditionAvailabilityDocument(incomplete), field).toBe(false);
      expect(isEditionDownloadReady(incomplete.editions[0]!), field).toBe(false);
    }
  });

  it("rejects unsafe URLs, unexpected fields, and inconsistent vehicle-pack totals", () => {
    const unsafe = publishedAvailability();
    unsafe.editions[0]!.downloadUrl = "javascript:alert(1)";
    expect(isEditionAvailabilityDocument(unsafe)).toBe(false);

    const foreign = publishedAvailability();
    foreign.editions[0]!.downloadUrl =
      "https://github.com/other/project/releases/download/v1/DroneDream-Sim-1.0.0.exe";
    expect(isEditionAvailabilityDocument(foreign)).toBe(false);

    const extra = structuredClone(fallbackEditionAvailability) as unknown as Record<string, unknown>;
    extra.available = true;
    expect(isEditionAvailabilityDocument(extra)).toBe(false);

    const inconsistent = structuredClone(fallbackEditionAvailability);
    inconsistent.vehiclePacks.validated = 1;
    expect(isEditionAvailabilityDocument(inconsistent)).toBe(false);
  });
});
