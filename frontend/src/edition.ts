import type { BrandEditionId } from "./brand/edition-brand.generated";
import type { UniversalWorkspaceId } from "./features/distribution/universalMode";

const SUPPORTED_EDITIONS = new Set<BrandEditionId>([
  "universal",
  "sim",
  "lab",
  "field",
]);

function resolveBuildEdition(): BrandEditionId {
  const configured = (import.meta.env.VITE_DRONEDREAM_EDITION as string | undefined)
    ?.trim()
    .toLowerCase() as BrandEditionId | undefined;
  return configured && SUPPORTED_EDITIONS.has(configured)
    ? configured
    : "universal";
}

export const BUILD_EDITION = resolveBuildEdition();
export const EDITION_IS_FIXED = BUILD_EDITION !== "universal";

export function initialWorkspaceMode(
  stored: UniversalWorkspaceId,
): UniversalWorkspaceId {
  return EDITION_IS_FIXED ? BUILD_EDITION as UniversalWorkspaceId : stored;
}

export function editionLandingPath(edition = BUILD_EDITION): string {
  if (edition === "sim") return "/sim";
  if (edition === "lab") return "/lab";
  if (edition === "field") return "/field";
  return "/assistant";
}
