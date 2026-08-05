export type AppEdition = "universal" | "lab";

export function resolveAppEdition(value: string | undefined): AppEdition {
  return value === "lab" ? "lab" : "universal";
}

export const appEdition = resolveAppEdition(
  import.meta.env.VITE_DRONEDREAM_EDITION,
);

export const labEditionEnabled = appEdition === "lab";

export function resolveAppDisplayName(edition: AppEdition) {
  return edition === "lab" ? "DroneDream · LAB" : "DroneDream";
}

export const appDisplayName = resolveAppDisplayName(appEdition);
