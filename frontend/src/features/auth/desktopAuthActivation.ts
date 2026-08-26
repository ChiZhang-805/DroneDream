export const ACTIVATE_DESKTOP_AUTH_EVENT =
  "drone-dream:activate-desktop-auth";
export const ADOPT_DESKTOP_AUTH_EVENT =
  "drone-dream:adopt-desktop-auth";
export const DESKTOP_AUTH_REFRESH_FAILED_EVENT =
  "drone-dream:desktop-auth-refresh-failed";

export function activateDesktopAuthSession(): void {
  window.dispatchEvent(new Event(ACTIVATE_DESKTOP_AUTH_EVENT));
}
