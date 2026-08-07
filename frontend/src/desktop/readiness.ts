import {
  probeRuntimeStatus,
  startRuntime,
} from "./bridge";
import type {
  RuntimeStatusReport,
  SystemPrerequisiteReport,
} from "./bridge";
import { probeSystemPrerequisitesWithStartupGrace } from "./prerequisiteProbe";
import { resetDesktopStartupGateSession } from "./startupGate";

export const MINIMUM_MEMORY_BYTES = 15 * 1024 ** 3;

export interface DesktopReadinessSnapshot {
  prerequisites: SystemPrerequisiteReport;
  runtime: RuntimeStatusReport;
  ready: boolean;
  autoStartFailed: boolean;
}

export type DesktopReadinessCheckId =
  | "runtime"
  | "system"
  | "ownership"
  | "manifest"
  | "backend"
  | "px4"
  | "gazebo";

export type DesktopReadinessCheckStatus =
  | "pending"
  | "checking"
  | "passed"
  | "failed";

export interface DesktopReadinessCheck {
  id: DesktopReadinessCheckId;
  status: DesktopReadinessCheckStatus;
  detail: string | null;
}

export interface DesktopReadinessProgress {
  checks: readonly DesktopReadinessCheck[];
  percent: number;
  running: boolean;
}

export const DESKTOP_READINESS_CHECK_IDS: readonly DesktopReadinessCheckId[] = [
  "runtime",
  "system",
  "ownership",
  "manifest",
  "backend",
  "px4",
  "gazebo",
];

export interface EnsureDesktopReadinessOptions {
  autoStart?: boolean;
  onStarting?: () => void;
  shouldAutoStart?: () => boolean;
  force?: boolean;
}

let runtimeStartInFlight: Promise<DesktopReadinessSnapshot> | null = null;
let fullReadinessProbeInFlight: Promise<DesktopReadinessSnapshot> | null = null;
let autoStartFailureKey: string | null = null;
let runtimeLifetimeClaimed = false;

type DesktopReadinessProgressListener = (progress: DesktopReadinessProgress) => void;

function emptyReadinessProgress(): DesktopReadinessProgress {
  return {
    checks: DESKTOP_READINESS_CHECK_IDS.map((id) => ({
      id,
      status: "pending",
      detail: null,
    })),
    percent: 0,
    running: false,
  };
}

let desktopReadinessProgress = emptyReadinessProgress();
const desktopReadinessProgressListeners = new Set<DesktopReadinessProgressListener>();

function publishReadinessProgress(
  checks: readonly DesktopReadinessCheck[],
  running: boolean,
): DesktopReadinessProgress {
  const passed = checks.filter((check) => check.status === "passed").length;
  desktopReadinessProgress = {
    checks,
    percent: Math.round((passed / DESKTOP_READINESS_CHECK_IDS.length) * 100),
    running,
  };
  for (const listener of desktopReadinessProgressListeners) {
    listener(desktopReadinessProgress);
  }
  return desktopReadinessProgress;
}

function updateReadinessCheck(
  id: DesktopReadinessCheckId,
  status: DesktopReadinessCheckStatus,
  detail: string | null = null,
  running = true,
): void {
  let reachedFailure = false;
  const checks = desktopReadinessProgress.checks.map((check) => {
    if (check.id === id) {
      reachedFailure = status === "failed";
      return { id, status, detail };
    }
    if (reachedFailure) return { ...check, status: "pending" as const, detail: null };
    return check;
  });
  publishReadinessProgress(checks, running);
}

function beginReadinessChecks(): void {
  const progress = emptyReadinessProgress();
  publishReadinessProgress(
    progress.checks.map((check, index) => ({
      ...check,
      status: index === 0 ? "checking" : "pending",
    })),
    true,
  );
}

function componentCheck(
  runtime: RuntimeStatusReport,
  id: DesktopReadinessCheckId,
  componentId: string,
): boolean {
  updateReadinessCheck(id, "checking");
  const component = runtime.components.find((candidate) => candidate.id === componentId);
  const passed = component?.status === "ready";
  updateReadinessCheck(
    id,
    passed ? "passed" : "failed",
    component?.detail ?? component?.status ?? "missing",
    passed,
  );
  return passed;
}

function completeRuntimeComponentChecks(runtime: RuntimeStatusReport): boolean {
  const checks: ReadonlyArray<[DesktopReadinessCheckId, string]> = [
    ["ownership", "host-ownership"],
    ["manifest", "runtime-manifest"],
    ["backend", "local-backend"],
    ["px4", "px4"],
    ["gazebo", "gazebo"],
  ];
  for (const [id, componentId] of checks) {
    if (!componentCheck(runtime, id, componentId)) return false;
  }
  publishReadinessProgress(desktopReadinessProgress.checks, false);
  return true;
}

export function getDesktopReadinessProgress(): DesktopReadinessProgress {
  return desktopReadinessProgress;
}

export function subscribeDesktopReadinessProgress(
  listener: DesktopReadinessProgressListener,
): () => void {
  desktopReadinessProgressListeners.add(listener);
  return () => desktopReadinessProgressListeners.delete(listener);
}

export interface DesktopReadinessSession {
  snapshot: DesktopReadinessSnapshot;
  lastFullCheckAt: number;
}

type DesktopReadinessListener = (session: DesktopReadinessSession) => void;

let desktopReadinessSession: DesktopReadinessSession | null = null;
const desktopReadinessListeners = new Set<DesktopReadinessListener>();

function rememberDesktopReadiness(
  snapshot: DesktopReadinessSnapshot,
  fullCheck: boolean,
): DesktopReadinessSnapshot {
  desktopReadinessSession = {
    snapshot,
    lastFullCheckAt: fullCheck
      ? Date.now()
      : desktopReadinessSession?.lastFullCheckAt ?? Date.now(),
  };
  for (const listener of desktopReadinessListeners) {
    listener(desktopReadinessSession);
  }
  return snapshot;
}

export function getDesktopReadinessSession(): DesktopReadinessSession | null {
  return desktopReadinessSession;
}

export function subscribeDesktopReadiness(
  listener: DesktopReadinessListener,
): () => void {
  desktopReadinessListeners.add(listener);
  return () => desktopReadinessListeners.delete(listener);
}

/** Reset module-scoped session state between isolated app/test sessions. */
export function resetDesktopReadinessSession(): void {
  desktopReadinessSession = null;
  fullReadinessProbeInFlight = null;
  runtimeStartInFlight = null;
  autoStartFailureKey = null;
  runtimeLifetimeClaimed = false;
  desktopReadinessProgress = emptyReadinessProgress();
  resetDesktopStartupGateSession();
}

function runtimeIdentityKey(runtime: RuntimeStatusReport): string {
  return [
    runtime.runtimeName,
    runtime.version ?? "unknown-version",
    runtime.dataRoot ?? "unknown-root",
  ].join("|");
}

function autoStartFailedFor(runtime: RuntimeStatusReport): boolean {
  return autoStartFailureKey === runtimeIdentityKey(runtime);
}

export function clearRuntimeAutoStartFailure(): void {
  autoStartFailureKey = null;
  if (desktopReadinessSession?.snapshot.autoStartFailed) {
    rememberDesktopReadiness({
      ...desktopReadinessSession.snapshot,
      autoStartFailed: false,
    }, false);
  }
}

function areDesktopPrerequisitesReady(
  prerequisites: SystemPrerequisiteReport | null,
): prerequisites is SystemPrerequisiteReport {
  return Boolean(
    prerequisites &&
    prerequisites.platform.toLowerCase() === "windows" &&
    prerequisites.supported &&
    prerequisites.windows &&
    prerequisites.memory &&
    prerequisites.memory.totalBytes >= MINIMUM_MEMORY_BYTES &&
    prerequisites.wsl.executableAvailable,
  );
}

export function isRuntimeFullyReady(report: RuntimeStatusReport | null): boolean {
  const requiredComponents = report?.components.filter((component) => component.required) ?? [];
  return Boolean(
    report?.ready &&
    report.installed &&
    report.running &&
    requiredComponents.length > 0 &&
    requiredComponents.every((component) => component.status === "ready"),
  );
}

export function isRuntimeConfirmedMissing(report: RuntimeStatusReport | null): boolean {
  const requiredComponents = report?.components.filter((component) => component.required) ?? [];
  return Boolean(
    report &&
    !report.installed &&
    !report.running &&
    !report.ready &&
    requiredComponents.length > 0 &&
    requiredComponents.every((component) => component.status === "missing"),
  );
}

export function isOverallDesktopReady(
  prerequisites: SystemPrerequisiteReport | null,
  runtime: RuntimeStatusReport | null,
): boolean {
  return Boolean(
    areDesktopPrerequisitesReady(prerequisites) &&
    isRuntimeFullyReady(runtime),
  );
}

/**
 * Automatic start is deliberately narrower than repair. Only a confirmed,
 * owned installation whose dedicated WSL distribution is stopped may be
 * started without asking the user. Unknown, unhealthy, missing, or foreign
 * registrations always remain behind the explicit setup/repair flow.
 */
export function canAutoStartRuntime(
  prerequisites: SystemPrerequisiteReport | null,
  runtime: RuntimeStatusReport | null,
): runtime is RuntimeStatusReport {
  if (
    !areDesktopPrerequisitesReady(prerequisites) ||
    !runtime?.installed ||
    runtime.running ||
    runtime.ready
  ) {
    return false;
  }

  const required = runtime.components.filter((component) => component.required);
  const byId = new Map(required.map((component) => [component.id, component]));
  return Boolean(
    required.length > 0 &&
    byId.get("wsl-runtime")?.status === "stopped" &&
    byId.get("host-ownership")?.status === "ready" &&
    required.every((component) =>
      component.status === "ready" || component.status === "stopped"
    ),
  );
}

export async function probeOverallDesktopReadiness(): Promise<DesktopReadinessSnapshot> {
  beginReadinessChecks();
  const runtime = await probeRuntimeStatus();
  if (!runtime.installed) {
    updateReadinessCheck("runtime", "failed", "not-installed", false);
  } else {
    updateReadinessCheck("runtime", "passed", runtime.version);
    updateReadinessCheck("system", "checking");
  }
  const prerequisites = await probeSystemPrerequisitesWithStartupGrace();
  const prerequisitesReady = areDesktopPrerequisitesReady(prerequisites);
  if (runtime.installed) {
    updateReadinessCheck(
      "system",
      prerequisitesReady ? "passed" : "failed",
      prerequisites.probeErrors[0] ?? null,
      prerequisitesReady,
    );
    if (prerequisitesReady && runtime.running) {
      completeRuntimeComponentChecks(runtime);
    }
  }
  const ready = isOverallDesktopReady(prerequisites, runtime);
  if (!runtime.running) runtimeLifetimeClaimed = false;
  if (ready || !runtime.installed) clearRuntimeAutoStartFailure();
  return rememberDesktopReadiness({
    prerequisites,
    runtime,
    ready,
    autoStartFailed: autoStartFailedFor(runtime),
  }, true);
}

async function startRuntimeForSnapshot(
  snapshot: DesktopReadinessSnapshot,
  options: EnsureDesktopReadinessOptions,
  fullCheck: boolean,
): Promise<DesktopReadinessSnapshot> {
  const {
    autoStart = false,
    onStarting,
    shouldAutoStart = () => true,
  } = options;

  if (!autoStart || !shouldAutoStart()) {
    if (snapshot.runtime.running && !snapshot.ready) {
      completeRuntimeComponentChecks(snapshot.runtime);
    }
    return snapshot;
  }

  if (snapshot.ready) {
    runtimeLifetimeClaimed = true;
    publishReadinessProgress(desktopReadinessProgress.checks, false);
    return snapshot;
  }

  // The full startup check claims the Runtime lifetime once. Later route
  // guards reuse that result instead of probing or issuing another start.
  if (snapshot.ready && runtimeLifetimeClaimed) return snapshot;

  if (runtimeStartInFlight) {
    onStarting?.();
    return runtimeStartInFlight;
  }
  if (
    snapshot.autoStartFailed ||
    (!snapshot.ready &&
      !canAutoStartRuntime(snapshot.prerequisites, snapshot.runtime))
  ) {
    if (snapshot.runtime.installed && !snapshot.runtime.running) {
      updateReadinessCheck("runtime", "failed", "start-not-authorized", false);
    }
    return snapshot;
  }

  onStarting?.();
  updateReadinessCheck("runtime", "checking", snapshot.runtime.version);
  const failureKey = runtimeIdentityKey(snapshot.runtime);
  const operation: Promise<DesktopReadinessSnapshot> = startRuntime()
    .then((runtime) => {
      const ready = isOverallDesktopReady(snapshot.prerequisites, runtime);
      updateReadinessCheck(
        "runtime",
        runtime.installed && runtime.running ? "passed" : "failed",
        runtime.version,
        runtime.installed && runtime.running,
      );
      if (runtime.installed && runtime.running) {
        completeRuntimeComponentChecks(runtime);
      }
      runtimeLifetimeClaimed = ready;
      if (ready) {
        clearRuntimeAutoStartFailure();
      } else {
        autoStartFailureKey = failureKey;
      }
      return rememberDesktopReadiness({
        prerequisites: snapshot.prerequisites,
        runtime,
        ready,
        autoStartFailed: !ready,
      }, fullCheck);
    })
    .catch((error: unknown) => {
      runtimeLifetimeClaimed = false;
      autoStartFailureKey = failureKey;
      updateReadinessCheck(
        "runtime",
        "failed",
        error instanceof Error ? error.message : "start-failed",
        false,
      );
      rememberDesktopReadiness({
        ...snapshot,
        autoStartFailed: true,
      }, fullCheck);
      throw error;
    })
    .finally(() => {
      if (runtimeStartInFlight === operation) runtimeStartInFlight = null;
    });
  runtimeStartInFlight = operation;
  return operation;
}

/**
 * Probe readiness and, when explicitly enabled, join or begin the one global
 * automatic Runtime start operation. Route loaders, API guards, and the
 * visible access provider all use this coordinator so navigation cannot race
 * a transient WSL startup state or launch duplicate maintenance commands.
 */
export async function ensureOverallDesktopReadiness(
  options: EnsureDesktopReadinessOptions = {},
): Promise<DesktopReadinessSnapshot> {
  const {
    autoStart = false,
    onStarting,
    force = false,
  } = options;

  if (autoStart && runtimeStartInFlight) {
    onStarting?.();
    return runtimeStartInFlight;
  }

  let snapshot = !force ? desktopReadinessSession?.snapshot : undefined;
  if (!snapshot) {
    if (!fullReadinessProbeInFlight) {
      const operation = probeOverallDesktopReadiness().finally(() => {
        if (fullReadinessProbeInFlight === operation) {
          fullReadinessProbeInFlight = null;
        }
      });
      fullReadinessProbeInFlight = operation;
    }
    snapshot = await fullReadinessProbeInFlight;
  }

  return startRuntimeForSnapshot(snapshot, options, true);
}

/**
 * Lightweight pre-run guard. It rechecks only the owned Runtime status and
 * reuses the system prerequisites established by the app-start full check.
 */
export async function ensureDesktopRuntimeLiveness(
  options: Pick<EnsureDesktopReadinessOptions, "autoStart" | "onStarting"> = {},
): Promise<DesktopReadinessSnapshot> {
  if (!desktopReadinessSession) {
    return ensureOverallDesktopReadiness({ ...options, autoStart: options.autoStart ?? true });
  }
  if (runtimeStartInFlight) {
    options.onStarting?.();
    return runtimeStartInFlight;
  }

  const previous = desktopReadinessSession.snapshot;
  const runtime = await probeRuntimeStatus();
  const snapshot: DesktopReadinessSnapshot = {
    prerequisites: previous.prerequisites,
    runtime,
    ready: isOverallDesktopReady(previous.prerequisites, runtime),
    autoStartFailed: autoStartFailedFor(runtime),
  };
  if (!runtime.running) runtimeLifetimeClaimed = false;
  if (snapshot.ready) {
    runtimeLifetimeClaimed = true;
    clearRuntimeAutoStartFailure();
    return rememberDesktopReadiness(snapshot, false);
  }

  rememberDesktopReadiness(snapshot, false);
  return startRuntimeForSnapshot(
    snapshot,
    { ...options, autoStart: options.autoStart ?? true },
    false,
  );
}
