import {
  BRAND_EDITION_IDS,
  type BrandEditionId,
} from "../../brand/edition-brand.generated";

export const UNIVERSAL_MODE_STORAGE_KEY = "dronedream:universal-mode:v1";

const MODE_SET = new Set<string>(BRAND_EDITION_IDS);

export function parseUniversalMode(value: unknown): BrandEditionId {
  return typeof value === "string" && MODE_SET.has(value)
    ? value as BrandEditionId
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
  mode: BrandEditionId,
  storage: Pick<Storage, "setItem"> = window.localStorage,
) {
  try {
    storage.setItem(UNIVERSAL_MODE_STORAGE_KEY, mode);
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
}
