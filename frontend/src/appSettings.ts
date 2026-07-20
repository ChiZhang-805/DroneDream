export const OPEN_APP_SETTINGS_EVENT = "dronedream:open-settings";

export function openAppSettings(): void {
  window.dispatchEvent(new Event(OPEN_APP_SETTINGS_EVENT));
}
