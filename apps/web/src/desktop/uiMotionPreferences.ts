const REDUCE_MOTION_STORAGE_KEY = "dronedream:reduce-motion";

export const REDUCE_MOTION_CHANGE_EVENT = "dronedream:reduce-motion-change";

// When browser storage is denied, honor the current tab's choice without
// claiming it was durably saved. A reload cannot recover this in-memory value.
let unsavedPreference: boolean | undefined;

/** Read a device/UI preference, not cloud account memory or flight authorization. */
export function appReducedMotionEnabled(): boolean {
  if (typeof window === "undefined") return false;
  if (unsavedPreference !== undefined) return unsavedPreference;
  try { return window.localStorage.getItem(REDUCE_MOTION_STORAGE_KEY) === "true"; }
  catch { return false; }
}

/** Apply immediately and attempt persistence; storage denial must not crash the settings surface. */
export function setAppReducedMotionEnabled(enabled: boolean): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(REDUCE_MOTION_STORAGE_KEY, String(enabled));
    unsavedPreference = undefined;
  } catch { unsavedPreference = enabled; }
  window.dispatchEvent(new CustomEvent(REDUCE_MOTION_CHANGE_EVENT));
}

/** Observe both same-tab setters and another tab's preference update or storage clear. */
export function subscribeToAppReducedMotion(onChange: () => void): () => void {
  if (typeof window === "undefined") return () => undefined;
  const onStorage = (event: StorageEvent) => {
    if (event.key === null || event.key === REDUCE_MOTION_STORAGE_KEY) onChange();
  };
  window.addEventListener(REDUCE_MOTION_CHANGE_EVENT, onChange);
  window.addEventListener("storage", onStorage);
  return () => {
    window.removeEventListener(REDUCE_MOTION_CHANGE_EVENT, onChange);
    window.removeEventListener("storage", onStorage);
  };
}
