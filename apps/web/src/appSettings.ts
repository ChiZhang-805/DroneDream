export const OPEN_APP_SETTINGS_EVENT = "dronedream:open-settings";

export type AppSettingsTarget = "general" | "memory" | "model" | "course" | "runtime";

export function openAppSettings(target: AppSettingsTarget = "general"): void {
  window.dispatchEvent(new CustomEvent(OPEN_APP_SETTINGS_EVENT, {
    detail: { target },
  }));
}
