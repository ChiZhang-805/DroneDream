import { describe, expect, it } from "vitest";

import publicEditionAvailability from "../../public/downloads/editions.json";
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
  sim.availability = "downloadable";
  sim.signatureState = "signed";
  sim.downloadUrl = "/downloads/DroneDream-Sim-1.0.0.exe";
  sim.checksumUrl = "/downloads/DroneDream-Sim-1.0.0.exe.sha256";
  sim.signatureUrl = "/downloads/DroneDream-Sim-1.0.0.exe.sig";
  sim.receiptUrl = "/downloads/DroneDream-Sim-1.0.0.exe.receipt.json";
  sim.urlFamily = "/downloads";
  sim.sizeBytes = 12_345_678;
  sim.sha256 = "a".repeat(64);
  sim.sourceCommit = "b".repeat(40);
  sim.publishedAt = "2026-08-05";
  return document;
}

describe("edition availability metadata", () => {
  it("keeps the public metadata byte contract aligned with the runtime fallback", () => {
    expect(isEditionAvailabilityDocument(publicEditionAvailability)).toBe(true);
    expect(publicEditionAvailability).toEqual(fallbackEditionAvailability);
  });

  it("keeps the three primary editions plus Universal ordered and unavailable", () => {
    expect(isEditionAvailabilityDocument(fallbackEditionAvailability)).toBe(true);
    expect(fallbackEditionAvailability.editions.map(({ id }) => id)).toEqual([
      "sim",
      "lab",
      "field",
      "universal",
    ]);
    expect(fallbackEditionAvailability.editions.map(({ fileName }) => fileName)).toEqual([
      "DroneDream-Sim-1.0.0.exe",
      "DroneDream-Lab-1.0.0.exe",
      "DroneDream-Field-1.0.0.exe",
      "DroneDream-Universal-1.0.0.exe",
    ]);
    expect(fallbackEditionAvailability.editions.every((edition) => (
      edition.availability === "unavailable" &&
      edition.signatureState === "not-provided" &&
      edition.downloadUrl === null &&
      edition.receiptUrl === null &&
      !isEditionDownloadReady(edition)
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
      "receiptUrl",
      "urlFamily",
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

  it("rejects availability, signature, receipt, and release-family mismatches", () => {
    const unavailable = publishedAvailability();
    unavailable.editions[0]!.availability = "unavailable";
    expect(isEditionAvailabilityDocument(unavailable)).toBe(false);

    const unsigned = publishedAvailability();
    unsigned.editions[0]!.signatureState = "not-provided";
    expect(isEditionAvailabilityDocument(unsigned)).toBe(false);

    const mixedRelease = publishedAvailability();
    mixedRelease.editions[0]!.receiptUrl =
      "https://github.com/ChiZhang-805/DroneDream/releases/download/other/DroneDream-Sim-1.0.0.exe.receipt.json";
    expect(isEditionAvailabilityDocument(mixedRelease)).toBe(false);

    const wrongFamily = publishedAvailability();
    wrongFamily.editions[0]!.urlFamily =
      "https://github.com/ChiZhang-805/DroneDream/releases/download/v1.0.0";
    expect(isEditionAvailabilityDocument(wrongFamily)).toBe(false);

    const leakedPlanned = structuredClone(fallbackEditionAvailability);
    leakedPlanned.editions[0]!.sha256 = "a".repeat(64);
    expect(isEditionAvailabilityDocument(leakedPlanned)).toBe(false);
  });

  it("rejects cross-edition routing, duplicate bytes, and stale publication dates", () => {
    const crossRouted = publishedAvailability();
    crossRouted.editions[0]!.fileName = "DroneDream-Universal-1.0.0.exe";
    expect(isEditionAvailabilityDocument(crossRouted)).toBe(false);

    const duplicate = publishedAvailability();
    const lab = duplicate.editions[1]!;
    Object.assign(lab, {
      releaseStatus: "published",
      availability: "downloadable",
      signatureState: "signed",
      downloadUrl: "/downloads/DroneDream-Lab-1.0.0.exe",
      checksumUrl: "/downloads/DroneDream-Lab-1.0.0.exe.sha256",
      signatureUrl: "/downloads/DroneDream-Lab-1.0.0.exe.sig",
      receiptUrl: "/downloads/DroneDream-Lab-1.0.0.exe.receipt.json",
      sizeBytes: 12_345_678,
      sha256: duplicate.editions[0]!.sha256,
      sourceCommit: "c".repeat(40),
      publishedAt: "2026-08-05",
    });
    expect(isEditionAvailabilityDocument(duplicate)).toBe(false);

    const stale = publishedAvailability();
    stale.generatedAt = "2026-08-04";
    expect(isEditionAvailabilityDocument(stale)).toBe(false);
  });

  it("rejects unsafe URLs, unexpected fields, and inconsistent vehicle-pack totals", () => {
    const unsafe = publishedAvailability();
    unsafe.editions[0]!.downloadUrl = "javascript:alert(1)";
    expect(isEditionAvailabilityDocument(unsafe)).toBe(false);

    const foreign = publishedAvailability();
    foreign.editions[0]!.downloadUrl =
      "https://github.com/other/project/releases/download/v1/DroneDream-Sim-1.0.0.exe";
    expect(isEditionAvailabilityDocument(foreign)).toBe(false);

    const uppercaseHash = publishedAvailability();
    uppercaseHash.editions[0]!.sha256 = "A".repeat(64);
    expect(isEditionAvailabilityDocument(uppercaseHash)).toBe(false);

    const extra = structuredClone(fallbackEditionAvailability) as unknown as Record<string, unknown>;
    extra.available = true;
    expect(isEditionAvailabilityDocument(extra)).toBe(false);

    const inconsistent = structuredClone(fallbackEditionAvailability);
    inconsistent.vehiclePacks.validated = 1;
    expect(isEditionAvailabilityDocument(inconsistent)).toBe(false);
  });
});
