import {
  type BrandEditionId,
} from "../../brand/edition-brand.generated";

export const UNIVERSAL_WORKSPACE_IDS = [
  "universal",
  "sim",
  "lab",
  "field",
  "autonomy",
] as const;
export type UniversalWorkspaceId = (typeof UNIVERSAL_WORKSPACE_IDS)[number];

export const UNIVERSAL_MODE_STORAGE_KEY = "dronedream:universal-workspace:v2";
export const UNIVERSAL_WORKSPACE_CHANGED_EVENT = "dronedream:universal-workspace-changed";

const MODE_SET = new Set<string>(UNIVERSAL_WORKSPACE_IDS);

export function parseUniversalMode(value: unknown): UniversalWorkspaceId {
  return typeof value === "string" && MODE_SET.has(value)
    ? value as UniversalWorkspaceId
    : "universal";
}

export function loadUniversalMode(storage: Pick<Storage, "getItem"> = window.localStorage) {
  try {
    return parseUniversalMode(storage.getItem(UNIVERSAL_MODE_STORAGE_KEY));
  } catch {
    return "universal" as const;
  }
}

export function persistUniversalMode(
  mode: UniversalWorkspaceId,
  storage: Pick<Storage, "setItem"> = window.localStorage,
) {
  try {
    storage.setItem(UNIVERSAL_MODE_STORAGE_KEY, mode);
    window.dispatchEvent(new CustomEvent(UNIVERSAL_WORKSPACE_CHANGED_EVENT, {
      detail: { mode },
    }));
  } catch {
    // Mode persistence is presentation-only. Storage failure must not affect
    // capability policy, installation selection, or application availability.
  }
}

export function applyUniversalMode(
  mode: BrandEditionId,
  root: HTMLElement = document.documentElement,
) {
  root.dataset.brandEdition = mode;
  root.dataset.productMode = mode;
  root.dataset.themePresentationOnly = "true";
  root.dataset.themeGrantsHardwareAuthority = "false";
}
