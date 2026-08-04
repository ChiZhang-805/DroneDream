import { isDesktopRuntime } from "../../desktop/bridge";

export const publicDemoConsole =
  import.meta.env.VITE_PUBLIC_DEMO_CONSOLE === "true";

/**
 * The public console is a browser-side preview and draft surface. A production
 * browser build must never become an execution client merely because an API
 * happens to be reachable. Tests opt into the same boundary explicitly so the
 * established desktop-oriented component tests remain unchanged.
 */
export function isWebConsolePreviewRuntime(): boolean {
  if (isDesktopRuntime()) return false;
  if (publicDemoConsole || import.meta.env.PROD) return true;
  return import.meta.env.MODE === "test"
    && new URLSearchParams(window.location.search).has("webPreview");
}
