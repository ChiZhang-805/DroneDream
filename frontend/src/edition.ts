import { EDITION_BRAND_TOKENS } from "./brand/edition-brand.generated";

export type AppEdition = "universal" | "lab";

export function resolveAppEdition(value: string | undefined): AppEdition {
  return value === "lab" ? "lab" : "universal";
}

export const appEdition = resolveAppEdition(
  import.meta.env.VITE_DRONEDREAM_EDITION,
);

export const labEditionEnabled = appEdition === "lab";

export function resolveAppDisplayName(edition: AppEdition) {
  return EDITION_BRAND_TOKENS[edition].productName;
}

export const appDisplayName = resolveAppDisplayName(appEdition);
