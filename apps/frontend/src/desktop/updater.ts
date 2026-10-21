import { useCallback, useEffect, useRef, useState } from "react";
import { check, type Update } from "@tauri-apps/plugin-updater";

import {
  checkComponentUpdates as checkSignedComponentUpdates,
  ensureAppUpdateIdle,
  getAppUpdateProgress,
  getEnginePackStatus,
  installAppUpdateInBackground,
  installEmbeddedEnginePack,
  installComponentUpdate,
  isDesktopRuntime,
  listenAppUpdateProgress,
  probeRuntimeStatus,
  type ComponentUpdateId,
  type ComponentUpdateCandidate,
  type ComponentUpdateReport,
  type EnginePackStatus,
  type NativeAppUpdateProgress,
} from "./bridge";
import { apiClient } from "../api/client";

export type AppUpdateStatus =
  | "checking"
  | "current"
  | "available"
  | "downloading"
  | "installing"
  | "reconcilingEngine"
  | "engineUpdateDeferred"
  | "engineError"
  | "componentAvailable"
  | "installingComponents"
  | "componentUpdateDeferred"
  | "componentError"
  | "runtimeBaseRequired"
  | "error";

export interface AppUpdateBlock {
  kind: "running" | "verification-failed";
  runningJobs: Array<{ id: string; name: string }>;
  message: string;
}

interface AppUpdateState {
  status: AppUpdateStatus;
  availableVersion: string | null;
  updateRequired: boolean;
  progress: number | null;
  error: string | null;
  enginePack: EnginePackStatus | null;
  componentUpdates: ComponentUpdateReport | null;
  blockedActivity?: AppUpdateBlock | null;
}

const CURRENT_STATE: AppUpdateState = {
  status: "current",
  availableVersion: null,
  updateRequired: false,
  progress: null,
  error: null,
  enginePack: null,
  componentUpdates: null,
  blockedActivity: null,
};

export const AUTOMATIC_UPDATE_CHECK_INTERVAL_MS = 6 * 60 * 60 * 1000;

const COMPONENT_INSTALL_ORDER: ComponentUpdateId[] = [
  "capability-pack",
  "asset-pack",
];

export function orderComponentUpdates(
  candidates: ComponentUpdateCandidate[],
): ComponentUpdateId[] {
  const available = candidates.filter((candidate) => candidate.available);
  const byId = new Map(available.map((candidate) => [candidate.componentId, candidate]));
  const pending = new Set(byId.keys());
  const ordered: ComponentUpdateId[] = [];
  while (pending.size > 0) {
    const ready = COMPONENT_INSTALL_ORDER.filter((componentId) => {
      if (!pending.has(componentId)) return false;
      const candidate = byId.get(componentId);
      return candidate?.dependencies.every((dependency) => !pending.has(dependency.componentId));
    });
    if (ready.length === 0) {
      throw new Error("The signed component update dependency graph contains a cycle.");
    }
    for (const componentId of ready) {
      pending.delete(componentId);
      ordered.push(componentId);
    }
  }
  return ordered;
}

export function selectManualComponentUpdates(
  candidates: ComponentUpdateCandidate[],
): ComponentUpdateCandidate[] {
  const available = candidates.filter((candidate) => candidate.available);
  const required = available.filter((candidate) => candidate.urgency === "required");
  const recommended = available.filter((candidate) => candidate.urgency === "recommended");
  const primary = required.length > 0
    ? required
    : recommended.length > 0
      ? recommended
      : available.filter((candidate) => candidate.urgency === "optional");
  const selected = new Map(primary.map((candidate) => [candidate.componentId, candidate]));
  const byId = new Map(available.map((candidate) => [candidate.componentId, candidate]));
  let changed = true;
  while (changed) {
    changed = false;
    for (const candidate of [...selected.values()]) {
      for (const dependency of candidate.dependencies) {
        const pendingDependency = byId.get(dependency.componentId);
        if (pendingDependency && !selected.has(pendingDependency.componentId)) {
          selected.set(pendingDependency.componentId, pendingDependency);
          changed = true;
        }
      }
    }
  }
  return [...selected.values()];
}

function componentCatalogEnabled(): boolean {
  return import.meta.env.VITE_COMPONENT_UPDATE_CATALOG_ENABLED === "true";
}

function componentCatalogUrl(): string | undefined {
  return import.meta.env.VITE_COMPONENT_UPDATE_CATALOG_URL?.trim() || undefined;
}

const NO_PUBLISHED_DESKTOP_UPDATE = "Could not fetch a valid release JSON from the remote";
const LEGACY_RUNTIME_IDLE_PROBE_UNAVAILABLE =
  "The Runtime Base must be upgraded before DroneDream can update safely.";

export function isNoPublishedDesktopUpdate(error: unknown): boolean {
  return errorMessage(error).trim() === NO_PUBLISHED_DESKTOP_UPDATE;
}

const UPDATE_POLICY_PATTERN = /^update-policy:\s*(recommended|required)$/gmu;

/**
 * Update policy is carried inside the signed updater metadata. Unknown or
 * missing values remain recommended so a routine release never locks users
 * out of a healthy workspace.
 */
export function appUpdateIsRequired(update: Pick<Update, "body" | "rawJson">): boolean {
  const rawPolicy = update.rawJson.updatePolicy;
  if (rawPolicy === "required") return true;
  if (rawPolicy === "recommended") return false;

  const matches = Array.from((update.body ?? "").matchAll(UPDATE_POLICY_PATTERN));
  return matches.length === 1 && matches[0][1] === "required";
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

export function isLegacyRuntimeIdleProbeUnavailable(error: unknown): boolean {
  return errorMessage(error).trim() === LEGACY_RUNTIME_IDLE_PROBE_UNAVAILABLE;
}

export function updaterDownloadSize(rawJson: Record<string, unknown>): number {
  const platforms = rawJson.platforms;
  if (!platforms || typeof platforms !== "object" || Array.isArray(platforms)) return 0;
  const windows = (platforms as Record<string, unknown>)["windows-x86_64"];
  if (!windows || typeof windows !== "object" || Array.isArray(windows)) return 0;
  const size = (windows as Record<string, unknown>).size;
  return typeof size === "number" && Number.isSafeInteger(size) && size > 0 ? size : 0;
}

function isActiveExperimentDeferral(message: string): boolean {
  return message.includes("waiting for active experiments to finish");
}

export async function detectRunningUpdateBlock(): Promise<AppUpdateBlock | null> {
  try {
    const runtime = await probeRuntimeStatus();
    if (!runtime.installed || !runtime.running) return null;
    if (!runtime.ready) {
      return {
        kind: "verification-failed",
        runningJobs: [],
        message: "DroneDream could not verify whether the running Runtime has an active experiment. Stop the Runtime or try again after it becomes ready.",
      };
    }
    const jobs = await apiClient.listJobs({ status: "RUNNING", page: 1, page_size: 100 });
    if (jobs.items.length === 0) return null;
    const runningJobs = jobs.items.map((job) => ({
      id: job.id,
      name: job.display_name?.trim() || job.id,
    }));
    return {
      kind: "running",
      runningJobs,
      message: runningJobs.length === 1
        ? `“${runningJobs[0].name}” is currently running. Finish or stop it before updating DroneDream.`
        : `${runningJobs.length} experiments are currently running. Finish or stop them before updating DroneDream.`,
    };
  } catch (error) {
    return {
      kind: "verification-failed",
      runningJobs: [],
      message: `DroneDream could not safely verify active experiments: ${errorMessage(error)}`,
    };
  }
}

export function useAppUpdater(options: { enabled?: boolean } = {}) {
  const enabled = options.enabled ?? true;
  const desktopRuntime = isDesktopRuntime();
  const updateRef = useRef<Update | null>(null);
  const checkGenerationRef = useRef(0);
  const installInFlightRef = useRef(false);
  const [state, setState] = useState<AppUpdateState>(() => (
    desktopRuntime && import.meta.env.MODE !== "test"
      ? CURRENT_STATE
      : CURRENT_STATE
  ));

  const applyNativeAppUpdateProgress = useCallback((event: NativeAppUpdateProgress) => {
    installInFlightRef.current = true;
    const installing = event.phase === "installing" || event.phase === "restarting";
    setState((current) => ({
      ...current,
      status: installing ? "installing" : "downloading",
      progress: Math.max(current.progress ?? 0, event.progress),
      error: null,
      blockedActivity: null,
    }));
  }, []);

  const restoreNativeAppUpdate = useCallback(async (): Promise<boolean> => {
    if (!desktopRuntime || import.meta.env.MODE === "test") return false;
    try {
      const snapshot = await getAppUpdateProgress();
      if (!snapshot.running) return false;
      installInFlightRef.current = true;
      if (snapshot.progress) applyNativeAppUpdateProgress(snapshot.progress);
      return true;
    } catch {
      // An older or temporarily unavailable bridge must not block an explicit
      // signed update check. The native single-flight guard remains final.
      return installInFlightRef.current;
    }
  }, [applyNativeAppUpdateProgress, desktopRuntime]);

  const reconcileComponentPacks = useCallback(async (
    generation?: number,
    enginePack?: EnginePackStatus | null,
  ) => {
    if (!desktopRuntime || import.meta.env.MODE === "test") return;
    // A healthy installed Runtime may keep running its existing Engine Pack
    // while the signed Runtime channel has no compatible newer base. Preserve
    // that evidence, but do not attempt component mutation through a manager
    // whose capabilities were not verified.
    if (enginePack && !enginePack.supported) {
      setState({ ...CURRENT_STATE, enginePack });
      return;
    }
    if (!componentCatalogEnabled()) {
      setState({ ...CURRENT_STATE, enginePack: enginePack ?? null });
      return;
    }
    try {
      let report = await checkSignedComponentUpdates(componentCatalogUrl());
      if (generation !== undefined && generation !== checkGenerationRef.current) return;
      let candidates = report.candidates.filter((candidate) => candidate.available);
      const automaticCandidates = candidates.filter((candidate) => {
        if (candidate.installMode !== "automatic") return false;
        return candidate.dependencies.every((dependency) => {
          const pendingDependency = candidates.find((entry) => (
            entry.componentId === dependency.componentId
          ));
          return !pendingDependency || pendingDependency.installMode === "automatic";
        });
      });
      if (automaticCandidates.length > 0 && !installInFlightRef.current) {
        const automaticIds = orderComponentUpdates(automaticCandidates);
        installInFlightRef.current = true;
        setState({
          status: "installingComponents",
          availableVersion: null,
          updateRequired: automaticCandidates.some((candidate) => (
            candidate.urgency === "required"
          )),
          progress: 0,
          error: null,
          enginePack: enginePack ?? null,
          componentUpdates: report,
        });
        try {
          await ensureAppUpdateIdle();
          for (let index = 0; index < automaticIds.length; index += 1) {
            await installComponentUpdate(automaticIds[index], componentCatalogUrl());
            setState((current) => ({
              ...current,
              progress: Math.round(((index + 1) / automaticIds.length) * 100),
            }));
          }
          report = await checkSignedComponentUpdates(componentCatalogUrl());
          if (generation !== undefined && generation !== checkGenerationRef.current) return;
          candidates = report.candidates.filter((candidate) => candidate.available);
        } catch (error) {
          if (generation !== undefined && generation !== checkGenerationRef.current) return;
          const message = errorMessage(error);
          setState({
            status: isActiveExperimentDeferral(message)
              ? "componentUpdateDeferred"
              : "componentError",
            availableVersion: null,
            updateRequired: automaticCandidates.some((candidate) => (
              candidate.urgency === "required"
            )),
            progress: null,
            error: message,
            enginePack: enginePack ?? null,
            componentUpdates: report,
          });
          return;
        } finally {
          installInFlightRef.current = false;
        }
      }
      if (candidates.length === 0) {
        setState({
          ...CURRENT_STATE,
          enginePack: enginePack ?? null,
          componentUpdates: report,
        });
        return;
      }
      setState({
        status: "componentAvailable",
        availableVersion: null,
        updateRequired: candidates.some((candidate) => candidate.urgency === "required"),
        progress: null,
        error: null,
        enginePack: enginePack ?? null,
        componentUpdates: report,
      });
    } catch (error) {
      if (generation !== undefined && generation !== checkGenerationRef.current) return;
      setState({
        status: "componentError",
        availableVersion: null,
        updateRequired: false,
        progress: null,
        error: errorMessage(error),
        enginePack: enginePack ?? null,
        componentUpdates: null,
      });
    }
  }, [desktopRuntime]);

  const ensureEnginePackCurrent = useCallback(async (
    generation?: number,
  ): Promise<EnginePackStatus | null> => {
    if (!desktopRuntime || import.meta.env.MODE === "test") return null;
    setState((current) => ({
      ...current,
      status: "reconcilingEngine",
      progress: null,
      error: null,
    }));
    try {
      const observed = await getEnginePackStatus();
      if (generation !== undefined && generation !== checkGenerationRef.current) return null;
      if (!observed.supported) {
        const runtimeBaseUpgradeAvailable =
          observed.runtimeBaseUpgradeAvailable !== false;
        if (!runtimeBaseUpgradeAvailable) {
          setState({ ...CURRENT_STATE, enginePack: observed });
          return observed;
        }
        setState({
          status: "runtimeBaseRequired",
          availableVersion: null,
          updateRequired: true,
          progress: null,
          error: observed.message,
          enginePack: observed,
          componentUpdates: null,
        });
        return null;
      }
      const current = observed.updateRequired
        ? await installEmbeddedEnginePack()
        : observed;
      if (generation !== undefined && generation !== checkGenerationRef.current) return null;
      return current;
    } catch (error) {
      if (generation !== undefined && generation !== checkGenerationRef.current) return null;
      const message = errorMessage(error);
      setState((current) => ({
        ...current,
        status: isActiveExperimentDeferral(message)
          ? "engineUpdateDeferred"
          : "engineError",
        progress: null,
        error: message,
      }));
      return null;
    }
  }, [desktopRuntime]);

  const reconcileEnginePack = useCallback(async (generation?: number) => {
    const current = await ensureEnginePackCurrent(generation);
    if (!current) return;
    await reconcileComponentPacks(generation, current);
  }, [ensureEnginePackCurrent, reconcileComponentPacks]);

  const checkForUpdates = useCallback(async () => {
    if (!desktopRuntime || import.meta.env.MODE === "test") {
      setState(CURRENT_STATE);
      return;
    }
    if (installInFlightRef.current) return;
    if (await restoreNativeAppUpdate()) return;
    const generation = ++checkGenerationRef.current;
    setState((current) => ({ ...current, status: "checking", error: null, progress: null }));
    try {
      const previousUpdate = updateRef.current;
      updateRef.current = null;
      await previousUpdate?.close();
      if (generation !== checkGenerationRef.current) return;
      const update = await check({
        timeout: 15_000,
        allowDowngrades: false,
      });
      if (generation !== checkGenerationRef.current) {
        await update?.close();
        return;
      }
      updateRef.current = update;
      if (update) {
        // A desktop update is the recovery path for a stale updater or an
        // Engine Pack contract that the installed build cannot reconcile.
        // Advertise it before touching optional component state so that a
        // recoverable component failure can never strand the application.
        setState({
          status: "available",
          availableVersion: update.version,
          updateRequired: appUpdateIsRequired(update),
          progress: null,
          error: null,
          enginePack: null,
          componentUpdates: null,
        });
        return;
      }
      const enginePack = await ensureEnginePackCurrent(generation);
      if (!enginePack || generation !== checkGenerationRef.current) return;
      await reconcileComponentPacks(generation, enginePack);
    } catch (error) {
      if (generation !== checkGenerationRef.current) return;
      // Tauri reports an endpoint that has no published channel manifest as
      // ReleaseNotFound. That is a valid pre-release channel state, not a
      // launcher failure. Network, parsing, signature and platform errors keep
      // their explicit error state below.
      if (isNoPublishedDesktopUpdate(error)) {
        const enginePack = await ensureEnginePackCurrent(generation);
        if (!enginePack || generation !== checkGenerationRef.current) return;
        await reconcileComponentPacks(generation, enginePack);
        return;
      }
      setState({
        status: "error",
        availableVersion: null,
        updateRequired: false,
        progress: null,
        error: errorMessage(error),
        enginePack: null,
        componentUpdates: null,
      });
    }
  }, [desktopRuntime, ensureEnginePackCurrent, reconcileComponentPacks, restoreNativeAppUpdate]);

  const checkForAppUpdateSilently = useCallback(async () => {
    if (
      !enabled
      || !desktopRuntime
      || import.meta.env.MODE === "test"
      || installInFlightRef.current
      || updateRef.current
    ) return;
    if (await restoreNativeAppUpdate()) return;
    const generation = ++checkGenerationRef.current;
    try {
      const update = await check({ timeout: 15_000, allowDowngrades: false });
      if (generation !== checkGenerationRef.current || !enabled) {
        await update?.close();
        return;
      }
      if (!update) return;
      updateRef.current = update;
      setState({
        status: "available",
        availableVersion: update.version,
        updateRequired: appUpdateIsRequired(update),
        progress: null,
        error: null,
        enginePack: null,
        componentUpdates: null,
        blockedActivity: null,
      });
    } catch {
      // Scheduled checks are deliberately invisible. The next six-hour poll,
      // an explicit settings check, or the next authenticated launch retries.
    }
  }, [desktopRuntime, enabled, restoreNativeAppUpdate]);

  const installAvailableUpdate = useCallback(async () => {
    const update = updateRef.current;
    if (
      !update
      || state.status !== "available"
      || installInFlightRef.current
    ) return;
    installInFlightRef.current = true;
    setState((current) => ({
      ...current,
      status: "downloading",
      progress: 0,
      error: null,
      blockedActivity: null,
    }));
    try {
      const initialBlock = await detectRunningUpdateBlock();
      if (initialBlock) {
        setState((current) => ({
          ...current,
          status: "available",
          progress: null,
          blockedActivity: initialBlock,
        }));
        return;
      }
      await installAppUpdateInBackground(applyNativeAppUpdateProgress);
    } catch (error) {
      const lateBlock = await detectRunningUpdateBlock();
      setState((current) => ({
        ...current,
        status: "available",
        progress: null,
        error: errorMessage(error),
        blockedActivity: lateBlock,
      }));
    } finally {
      installInFlightRef.current = false;
    }
  }, [applyNativeAppUpdateProgress, state.status]);

  const dismissBlockedActivity = useCallback(() => {
    setState((current) => ({ ...current, blockedActivity: null }));
  }, []);

  const installComponentUpdates = useCallback(async () => {
    const report = state.componentUpdates;
    if (
      !report
      || state.status !== "componentAvailable"
      || installInFlightRef.current
    ) return;
    const selectedCandidates = selectManualComponentUpdates(report.candidates);
    const componentIds = orderComponentUpdates(selectedCandidates);
    if (componentIds.length === 0) return;

    installInFlightRef.current = true;
    setState((current) => ({
      ...current,
      status: "installingComponents",
      progress: 0,
      error: null,
    }));
    try {
      await ensureAppUpdateIdle();
      for (let index = 0; index < componentIds.length; index += 1) {
        await installComponentUpdate(componentIds[index], componentCatalogUrl());
        setState((current) => ({
          ...current,
          progress: Math.round(((index + 1) / componentIds.length) * 100),
        }));
      }
      await reconcileComponentPacks(undefined, state.enginePack);
    } catch (error) {
      const message = errorMessage(error);
      setState((current) => ({
        ...current,
        status: isActiveExperimentDeferral(message)
          ? "componentUpdateDeferred"
          : "componentError",
        progress: null,
        error: message,
      }));
    } finally {
      installInFlightRef.current = false;
    }
  }, [reconcileComponentPacks, state.componentUpdates, state.enginePack, state.status]);

  useEffect(() => {
    if (!desktopRuntime || import.meta.env.MODE === "test") return undefined;
    let disposed = false;
    let unlisten: (() => void) | undefined;
    void (async () => {
      try {
        const nextUnlisten = await listenAppUpdateProgress((event) => {
          if (!disposed) applyNativeAppUpdateProgress(event);
        });
        if (disposed) {
          nextUnlisten();
          return;
        }
        unlisten = nextUnlisten;
        await restoreNativeAppUpdate();
      } catch {
        // The persistent listener is a continuity enhancement. The installer
        // invocation still owns its own listener and reports actionable errors.
      }
    })();
    return () => {
      disposed = true;
      unlisten?.();
    };
  }, [applyNativeAppUpdateProgress, desktopRuntime, restoreNativeAppUpdate]);

  useEffect(() => {
    if (!enabled) {
      // Authentication refreshes can briefly remove the account from React
      // state. Once the user has started an update, ownership has moved to the
      // native process and must never be cancelled or visually reset.
      if (installInFlightRef.current) return undefined;
      checkGenerationRef.current += 1;
      void updateRef.current?.close();
      updateRef.current = null;
      setState(CURRENT_STATE);
      return;
    }
    if (import.meta.env.MODE === "test") {
      void checkForUpdates();
      return () => {
        if (installInFlightRef.current) return;
        checkGenerationRef.current += 1;
        void updateRef.current?.close();
        updateRef.current = null;
      };
    }
    void checkForAppUpdateSilently();
    const timer = window.setInterval(() => {
      void checkForAppUpdateSilently();
    }, AUTOMATIC_UPDATE_CHECK_INTERVAL_MS);
    return () => {
      window.clearInterval(timer);
      if (installInFlightRef.current) return;
      checkGenerationRef.current += 1;
      void updateRef.current?.close();
      updateRef.current = null;
    };
  }, [checkForAppUpdateSilently, checkForUpdates, enabled]);

  return {
    ...state,
    desktopRuntime,
    checkForUpdates,
    installAvailableUpdate,
    dismissBlockedActivity,
    installComponentUpdates,
    reconcileEnginePack,
    reconcileComponentPacks,
  };
}
