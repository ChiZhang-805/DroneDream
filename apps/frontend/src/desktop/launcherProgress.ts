import type { DesktopRuntimeAccessStatus } from "./access";
import type { RuntimeStatusReport } from "./bridge";

/**
 * Startup progress is evidence driven. These values are checkpoints, not a
 * timer: the launcher may advance only after the corresponding native probe
 * has returned fresh evidence for this app session.
 */
export const LAUNCHER_PROGRESS_CHECKPOINTS = {
  prerequisites: 20,
  runtimeRegistration: 35,
  runtimeInstalled: 45,
  runtimeRunning: 55,
  runtimeComponents: 85,
  runtimeAccess: 95,
  complete: 100,
} as const;

export interface LauncherProgressEvidence {
  enabled: boolean;
  blocked?: boolean;
  prerequisitesFresh: boolean;
  runtimeFresh: boolean;
  runtime: RuntimeStatusReport | null;
  runtimeAccessStatus: DesktopRuntimeAccessStatus;
  complete: boolean;
}

/** Required components have equal display weight; this is not an ETA or readiness authorization. */
function componentProgress(runtime: RuntimeStatusReport): number {
  const required = runtime.components.filter((component) => component.required);
  if (required.length === 0) return LAUNCHER_PROGRESS_CHECKPOINTS.runtimeRunning;
  const ready = required.filter((component) => component.status === "ready").length;
  const span = LAUNCHER_PROGRESS_CHECKPOINTS.runtimeComponents -
    LAUNCHER_PROGRESS_CHECKPOINTS.runtimeRunning;
  return LAUNCHER_PROGRESS_CHECKPOINTS.runtimeRunning +
    Math.floor((ready / required.length) * span);
}

/**
 * Derive the visible launcher percentage exclusively from completed checks.
 * A missing Runtime never leaves 0%, and 100% remains reserved for the full
 * local readiness contract. No elapsed-time milestone can grant progress.
 */
export function launcherProgressFromEvidence({
  enabled,
  blocked = false,
  prerequisitesFresh,
  runtimeFresh,
  runtime,
  runtimeAccessStatus,
  complete,
}: LauncherProgressEvidence): number {
  if (!enabled || blocked) return 0;
  // A cached ready report or caller's stale completion flag cannot provide fresh
  // evidence after a restart. The native access gate still owns launch permission.
  if (complete && prerequisitesFresh && runtimeFresh && runtime?.installed &&
      runtime.running && runtime.ready &&
      (runtimeAccessStatus === "ready" || runtimeAccessStatus === "browser") &&
      runtime.components.every((component) => !component.required || component.status === "ready")) {
    // Provider-free/browser presentation has no native access gate to await.
    // This percentage covers local checks only; explicit sign-in is a later gate.
    return LAUNCHER_PROGRESS_CHECKPOINTS.complete;
  }

  let progress = 0;
  if (prerequisitesFresh) {
    progress = LAUNCHER_PROGRESS_CHECKPOINTS.prerequisites;
  }
  if (runtimeFresh && runtime) {
    progress = Math.max(progress, LAUNCHER_PROGRESS_CHECKPOINTS.runtimeRegistration);
  }
  if (runtimeFresh && runtime?.installed) {
    progress = Math.max(progress, LAUNCHER_PROGRESS_CHECKPOINTS.runtimeInstalled);
  }
  if (runtimeFresh && runtime?.installed && runtime.running) {
    progress = Math.max(progress, LAUNCHER_PROGRESS_CHECKPOINTS.runtimeRunning);
    progress = Math.max(progress, componentProgress(runtime));
  }
  if (prerequisitesFresh && runtimeFresh && runtime?.installed && runtime.running &&
      runtime.ready && runtimeAccessStatus === "ready") {
    progress = Math.max(progress, LAUNCHER_PROGRESS_CHECKPOINTS.runtimeAccess);
  }

  return Math.min(progress, LAUNCHER_PROGRESS_CHECKPOINTS.runtimeAccess);
}
