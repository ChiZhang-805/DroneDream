import { isDesktopRuntime } from "./bridge";
import { resetDesktopReadinessSession } from "./readiness";

export interface DesktopLauncherRestartOptions {
  isDesktop?: () => boolean;
  reload?: () => void;
}

/**
 * Return a signed-out desktop edition to the same launcher route used by a
 * fresh process. Reloading is intentional: the Runtime access provider only
 * performs its coordinated probe/start sequence when it mounts on this route.
 */
export function restartDesktopLauncherAfterSignOut(
  options: DesktopLauncherRestartOptions = {},
): boolean {
  const desktop = options.isDesktop ?? isDesktopRuntime;
  if (!desktop()) return false;

  resetDesktopReadinessSession();

  const launcherUrl = new URL(window.location.href);
  launcherUrl.search = "";
  launcherUrl.hash = "/desktop/setup";
  window.history.replaceState(null, "", launcherUrl.href);

  const reload = options.reload ?? (() => window.location.reload());
  reload();
  return true;
}
