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

/** Normalize presentation-only workspace IDs; unknown saved values cannot select a new capability. */
export function parseUniversalMode(value: unknown): UniversalWorkspaceId {
  return typeof value === "string" && MODE_SET.has(value)
    ? value as UniversalWorkspaceId
    : "universal";
}

/** Resolve localStorage inside the guard: the property getter itself can raise SecurityError. */
export function loadUniversalMode(storage?: Pick<Storage, "getItem">) {
  try {
    return parseUniversalMode((storage ?? window.localStorage).getItem(UNIVERSAL_MODE_STORAGE_KEY));
  } catch {
    return "universal" as const;
  }
}

/** Notify sibling presentation views after a successful save; this never changes installed edition policy. */
export function persistUniversalMode(
  mode: UniversalWorkspaceId,
  storage?: Pick<Storage, "setItem">,
) {
  try {
    (storage ?? window.localStorage).setItem(UNIVERSAL_MODE_STORAGE_KEY, mode);
    window.dispatchEvent(new CustomEvent(UNIVERSAL_WORKSPACE_CHANGED_EVENT, {
      detail: { mode },
    }));
  } catch {
    // Mode persistence is presentation-only. Storage failure must not affect
    // capability policy, installation selection, or application availability.
  }
}

/** Set theme metadata only; these DOM attributes are explicitly not a hardware authorization source. */
export function applyUniversalMode(
  mode: BrandEditionId,
  root: HTMLElement = document.documentElement,
) {
  root.dataset.brandEdition = mode;
  root.dataset.productMode = mode;
  root.dataset.themePresentationOnly = "true";
  root.dataset.themeGrantsHardwareAuthority = "false";
}
