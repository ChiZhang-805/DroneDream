export const ACTIVATE_DESKTOP_AUTH_EVENT =
  "drone-dream:activate-desktop-auth";

export function activateDesktopAuthSession(): void {
  window.dispatchEvent(new Event(ACTIVATE_DESKTOP_AUTH_EVENT));
}
