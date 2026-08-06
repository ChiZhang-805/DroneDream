import { describe, expect, it } from "vitest";

import {
  assessEditionBrandPlacement,
  editionDisplayNames,
  type EditionBrandPlacement,
  type EditionBrandSurface,
} from "../site/editionBrandPlacement";
import type { EditionId } from "../site/editionAvailability";

function syntheticPlacement(
  overrides: Partial<EditionBrandPlacement> = {},
): EditionBrandPlacement {
  return {
    surface: "product-card",
    expectedEdition: "sim",
    asset: {
      edition: "sim",
      kind: "mark",
      naturalWidth: 1024,
      naturalHeight: 1024,
    },
    slotWidth: 64,
    slotHeight: 64,
    renderedWidth: 64,
    renderedHeight: 64,
    objectFit: "contain",
    visibleEditionName: editionDisplayNames.sim,
    alt: "",
    ariaHidden: true,
    ...overrides,
  };
}

function syntheticLockup(
  surface: EditionBrandSurface,
  edition: EditionId,
): EditionBrandPlacement {
  return syntheticPlacement({
    surface,
    expectedEdition: edition,
    asset: {
      edition,
      kind: "lockup",
      naturalWidth: 1840,
      naturalHeight: 340,
    },
    slotWidth: 400,
    slotHeight: 90,
    renderedWidth: 368,
    renderedHeight: 68,
    visibleEditionName: editionDisplayNames[edition],
  });
}

describe("edition brand placement contract", () => {
  it.each([
    ["product-card", "sim"],
    ["product-card", "lab"],
    ["product-card", "field"],
    ["download-chooser", "universal"],
    ["account", "lab"],
    ["browser-callback", "field"],
  ] as const)("accepts a natural-width lockup on a large %s surface", (surface, edition) => {
    const assessment = assessEditionBrandPlacement(syntheticLockup(surface, edition));

    expect(assessment).toEqual({
      accepted: true,
      allowedAssetKind: "mark-or-lockup",
      violations: [],
    });
  });

  it.each([
    "product-card",
    "download-chooser",
    "account",
    "browser-callback",
  ] as const)("requires a mark on a compact %s surface", (surface) => {
    const assessment = assessEditionBrandPlacement(syntheticPlacement({ surface }));

    expect(assessment.accepted).toBe(true);
    expect(assessment.allowedAssetKind).toBe("mark");
  });

  it("rejects a lockup rendered at compact icon size", () => {
    const placement = syntheticLockup("download-chooser", "universal");
    placement.slotWidth = 64;
    placement.slotHeight = 24;
    placement.renderedWidth = 64;
    placement.renderedHeight = 64 / (1840 / 340);

    expect(assessEditionBrandPlacement(placement).violations)
      .toContain("compact-slot-requires-mark");
  });

  it("rejects cross-edition assets and labels", () => {
    const placement = syntheticLockup("browser-callback", "field");
    placement.asset.edition = "lab";
    placement.visibleEditionName = editionDisplayNames.lab;

    expect(assessEditionBrandPlacement(placement).violations).toEqual(
      expect.arrayContaining(["wrong-edition", "wrong-visible-name"]),
    );
  });

  it("rejects stretched and non-natural lockup geometry", () => {
    const placement = syntheticLockup("product-card", "sim");
    placement.asset.naturalWidth = 700;
    placement.asset.naturalHeight = 300;
    placement.renderedWidth = 300;
    placement.renderedHeight = 60;

    expect(assessEditionBrandPlacement(placement).violations).toEqual(
      expect.arrayContaining(["invalid-lockup-shape", "stretched-asset"]),
    );
  });

  it("rejects crop-prone sizing and object-fit modes", () => {
    const placement = syntheticLockup("account", "lab");
    placement.slotWidth = 320;
    placement.slotHeight = 64;
    placement.renderedWidth = 368;
    placement.renderedHeight = 68;
    placement.objectFit = "cover";

    expect(assessEditionBrandPlacement(placement).violations).toEqual(
      expect.arrayContaining(["asset-exceeds-slot", "unsafe-object-fit"]),
    );
  });

  it("rejects a non-square mark metadata shape", () => {
    const placement = syntheticPlacement();
    placement.asset.naturalWidth = 1200;
    placement.renderedWidth = 75;

    expect(assessEditionBrandPlacement(placement).violations)
      .toContain("invalid-mark-shape");
  });

  it("requires decorative images beside an exact visible edition name", () => {
    const placement = syntheticPlacement({
      alt: editionDisplayNames.sim,
      ariaHidden: false,
    });

    expect(assessEditionBrandPlacement(placement).violations)
      .toContain("invalid-decorative-accessibility");
  });

  it("requires the exact edition name for a standalone brand image", () => {
    const valid = syntheticLockup("browser-callback", "sim");
    valid.visibleEditionName = null;
    valid.alt = editionDisplayNames.sim;
    valid.ariaHidden = false;
    expect(assessEditionBrandPlacement(valid).accepted).toBe(true);

    valid.alt = editionDisplayNames.field;
    expect(assessEditionBrandPlacement(valid).violations)
      .toContain("missing-standalone-accessible-name");
  });

  it("fails closed on invalid synthetic dimensions", () => {
    const placement = syntheticPlacement({ renderedWidth: 0 });

    expect(assessEditionBrandPlacement(placement).violations)
      .toContain("invalid-dimensions");
  });
});
