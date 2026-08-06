import type { EditionId } from "./editionAvailability";

export type EditionBrandSurface =
  | "product-card"
  | "download-chooser"
  | "account"
  | "browser-callback";

export type EditionBrandAssetKind = "mark" | "lockup";

export type EditionBrandPlacementViolation =
  | "invalid-dimensions"
  | "wrong-edition"
  | "wrong-visible-name"
  | "invalid-mark-shape"
  | "invalid-lockup-shape"
  | "compact-slot-requires-mark"
  | "unsafe-object-fit"
  | "stretched-asset"
  | "asset-exceeds-slot"
  | "invalid-decorative-accessibility"
  | "missing-standalone-accessible-name";

export interface EditionBrandAssetMetadata {
  edition: EditionId;
  kind: EditionBrandAssetKind;
  naturalWidth: number;
  naturalHeight: number;
}

export interface EditionBrandPlacement {
  surface: EditionBrandSurface;
  expectedEdition: EditionId;
  asset: EditionBrandAssetMetadata;
  slotWidth: number;
  slotHeight: number;
  renderedWidth: number;
  renderedHeight: number;
  objectFit: "contain" | "cover" | "fill" | "none" | "scale-down";
  visibleEditionName: string | null;
  alt: string;
  ariaHidden: boolean;
}

export interface EditionBrandPlacementAssessment {
  accepted: boolean;
  allowedAssetKind: "mark" | "mark-or-lockup";
  violations: EditionBrandPlacementViolation[];
}

export const EDITION_LOCKUP_MIN_RENDERED_WIDTH = 320;
export const EDITION_LOCKUP_MIN_RENDERED_HEIGHT = 30;

export const editionDisplayNames: Record<EditionId, string> = {
  universal: "DroneDream",
  sim: "DroneDream · SIM",
  lab: "DroneDream · LAB",
  field: "DroneDream · FIELD",
};

const DIMENSION_TOLERANCE = 0.5;
const RATIO_TOLERANCE = 0.02;
const MARK_RATIO_MIN = 0.96;
const MARK_RATIO_MAX = 1.04;
const LOCKUP_RATIO_MIN = 3;

function positiveFinite(value: number): boolean {
  return Number.isFinite(value) && value > 0;
}

function ratioDifference(left: number, right: number): number {
  return Math.abs(left - right) / right;
}

export function assessEditionBrandPlacement(
  placement: EditionBrandPlacement,
): EditionBrandPlacementAssessment {
  const violations: EditionBrandPlacementViolation[] = [];
  const dimensions = [
    placement.asset.naturalWidth,
    placement.asset.naturalHeight,
    placement.slotWidth,
    placement.slotHeight,
    placement.renderedWidth,
    placement.renderedHeight,
  ];
  const validDimensions = dimensions.every(positiveFinite);
  if (!validDimensions) violations.push("invalid-dimensions");

  if (placement.asset.edition !== placement.expectedEdition) {
    violations.push("wrong-edition");
  }

  const expectedName = editionDisplayNames[placement.expectedEdition];
  if (
    placement.visibleEditionName !== null &&
    placement.visibleEditionName !== expectedName
  ) {
    violations.push("wrong-visible-name");
  }

  const compact =
    !validDimensions ||
    placement.renderedWidth < EDITION_LOCKUP_MIN_RENDERED_WIDTH ||
    placement.renderedHeight < EDITION_LOCKUP_MIN_RENDERED_HEIGHT;
  const allowedAssetKind = compact ? "mark" : "mark-or-lockup";

  if (validDimensions) {
    const naturalRatio = placement.asset.naturalWidth / placement.asset.naturalHeight;
    const renderedRatio = placement.renderedWidth / placement.renderedHeight;
    if (
      placement.asset.kind === "mark" &&
      (naturalRatio < MARK_RATIO_MIN || naturalRatio > MARK_RATIO_MAX)
    ) {
      violations.push("invalid-mark-shape");
    }
    if (
      placement.asset.kind === "lockup" &&
      naturalRatio < LOCKUP_RATIO_MIN
    ) {
      violations.push("invalid-lockup-shape");
    }
    if (ratioDifference(renderedRatio, naturalRatio) > RATIO_TOLERANCE) {
      violations.push("stretched-asset");
    }
    if (
      placement.renderedWidth > placement.slotWidth + DIMENSION_TOLERANCE ||
      placement.renderedHeight > placement.slotHeight + DIMENSION_TOLERANCE
    ) {
      violations.push("asset-exceeds-slot");
    }
  }

  if (placement.asset.kind === "lockup" && compact) {
    violations.push("compact-slot-requires-mark");
  }
  if (placement.objectFit !== "contain") {
    violations.push("unsafe-object-fit");
  }

  if (placement.visibleEditionName !== null) {
    if (placement.alt !== "" || !placement.ariaHidden) {
      violations.push("invalid-decorative-accessibility");
    }
  } else if (placement.alt !== expectedName || placement.ariaHidden) {
    violations.push("missing-standalone-accessible-name");
  }

  return {
    accepted: violations.length === 0,
    allowedAssetKind,
    violations,
  };
}
