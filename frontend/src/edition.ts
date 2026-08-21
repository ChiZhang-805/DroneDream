import type { BrandEditionId } from "./brand/edition-brand.generated";
import type { UniversalWorkspaceId } from "./features/distribution/universalMode";

export const BUILD_EDITION: BrandEditionId = __DRONEDREAM_BUILD_EDITION__;
export const EDITION_IS_FIXED = BUILD_EDITION !== "universal";
export const BUILD_HAS_SIM_WORKSPACE =
  __DRONEDREAM_BUILD_EDITION__ === "universal"
  || __DRONEDREAM_BUILD_EDITION__ === "sim";
export const BUILD_HAS_LAB_WORKSPACE =
  __DRONEDREAM_BUILD_EDITION__ === "universal"
  || __DRONEDREAM_BUILD_EDITION__ === "lab";
export const BUILD_HAS_FIELD_WORKSPACE =
  __DRONEDREAM_BUILD_EDITION__ === "universal";
export const BUILD_HAS_AUTONOMY_WORKSPACE = true;
export const BUILD_HAS_VEHICLE_STUDIO =
  __DRONEDREAM_BUILD_EDITION__ === "universal";

export function editionHasWorkspace(
  edition: BrandEditionId,
  workspace: UniversalWorkspaceId,
): boolean {
  return edition === "universal" || edition === workspace;
}

export function editionHasVehicleStudio(edition: BrandEditionId): boolean {
  return edition === "universal";
}

export function initialWorkspaceMode(
  stored: UniversalWorkspaceId,
): UniversalWorkspaceId {
  return EDITION_IS_FIXED ? BUILD_EDITION as UniversalWorkspaceId : stored;
}

export function editionLandingPath(edition = BUILD_EDITION): string {
  if (edition === "sim") return "/sim";
  if (edition === "lab") return "/lab";
  if (edition === "field") return "/field";
  if (edition === "autonomy") return "/autonomy";
  return "/assistant";
}
