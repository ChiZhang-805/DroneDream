const REDUCE_MOTION_STORAGE_KEY = "dronedream:reduce-motion";
export const REDUCE_MOTION_CHANGE_EVENT = "dronedream:reduce-motion-change";

export function appReducedMotionEnabled(): boolean {
  return window.localStorage.getItem(REDUCE_MOTION_STORAGE_KEY) === "true";
}

export function setAppReducedMotionEnabled(enabled: boolean): void {
  window.localStorage.setItem(REDUCE_MOTION_STORAGE_KEY, String(enabled));
  window.dispatchEvent(new CustomEvent(REDUCE_MOTION_CHANGE_EVENT));
}
