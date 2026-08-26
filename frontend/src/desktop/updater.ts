import { useCallback, useEffect, useRef, useState } from "react";
import { check, type Update } from "@tauri-apps/plugin-updater";
import { relaunch } from "@tauri-apps/plugin-process";

import {
  checkComponentUpdates as checkSignedComponentUpdates,
  ensureAppUpdateIdle,
  getEnginePackStatus,
  installEmbeddedEnginePack,
  installComponentUpdate,
  isDesktopRuntime,
  stopRuntimeForExit,
  type ComponentUpdateId,
  type ComponentUpdateCandidate,
  type ComponentUpdateReport,
  type EnginePackStatus,
} from "./bridge";

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

interface AppUpdateState {
  status: AppUpdateStatus;
  availableVersion: string | null;
  updateRequired: boolean;
  progress: number | null;
  error: string | null;
  enginePack: EnginePackStatus | null;
  componentUpdates: ComponentUpdateReport | null;
}

const CURRENT_STATE: AppUpdateState = {
  status: "current",
  availableVersion: null,
  updateRequired: false,
  progress: null,
  error: null,
  enginePack: null,
  componentUpdates: null,
};

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

export function useAppUpdater() {
  const desktopRuntime = isDesktopRuntime();
  const updateRef = useRef<Update | null>(null);
  const updateDownloadedRef = useRef(false);
  const checkGenerationRef = useRef(0);
  const installInFlightRef = useRef(false);
  const [state, setState] = useState<AppUpdateState>(() => (
    desktopRuntime && import.meta.env.MODE !== "test"
      ? { ...CURRENT_STATE, status: "checking" }
      : CURRENT_STATE
  ));

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
    const generation = ++checkGenerationRef.current;
    setState((current) => ({ ...current, status: "checking", error: null, progress: null }));
    let enginePack: EnginePackStatus | null = null;
    try {
      // The installed app's embedded Engine Pack is part of its executable
      // contract. Reconcile it before advertising a newer app so a user who
      // defers that app update still runs the engine paired with this build.
      enginePack = await ensureEnginePackCurrent(generation);
      if (!enginePack || generation !== checkGenerationRef.current) return;
      const previousUpdate = updateRef.current;
      updateRef.current = null;
      updateDownloadedRef.current = false;
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
      if (!update) {
        await reconcileComponentPacks(generation, enginePack);
        return;
      }
      setState({
        status: "available",
        availableVersion: update.version,
        updateRequired: appUpdateIsRequired(update),
        progress: null,
        error: null,
        enginePack,
        componentUpdates: null,
      });
    } catch (error) {
      if (generation !== checkGenerationRef.current) return;
      // Tauri reports an endpoint that has no published channel manifest as
      // ReleaseNotFound. That is a valid pre-release channel state, not a
      // launcher failure. Network, parsing, signature and platform errors keep
      // their explicit error state below.
      if (isNoPublishedDesktopUpdate(error)) {
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
  }, [desktopRuntime, ensureEnginePackCurrent, reconcileComponentPacks]);

  const installAvailableUpdate = useCallback(async () => {
    const update = updateRef.current;
    if (
      !update
      || state.status !== "available"
      || installInFlightRef.current
    ) return;
    installInFlightRef.current = true;
    let downloaded = 0;
    let contentLength = updaterDownloadSize(update.rawJson);
    setState((current) => ({ ...current, status: "downloading", progress: 0, error: null }));
    try {
      if (!updateDownloadedRef.current) {
        await update.download((event) => {
          if (event.event === "Started") {
            contentLength = event.data.contentLength ?? contentLength;
            setState((current) => ({ ...current, progress: 0 }));
            return;
          }
          if (event.event === "Progress") {
            downloaded += event.data.chunkLength;
            if (contentLength > 0) {
              const progress = Math.min(99, Math.floor((downloaded / contentLength) * 100));
              setState((current) => ({ ...current, progress }));
            }
            return;
          }
          setState((current) => ({ ...current, progress: 100 }));
        });
        updateDownloadedRef.current = true;
      }
      setState((current) => ({ ...current, status: "installing", progress: 100 }));
      try {
        await ensureAppUpdateIdle();
      } catch (error) {
        // Runtime Base releases from before the Engine Pack manager cannot
        // prove idleness. They must not block the desktop bootstrap forever:
        // stop only DroneDreamRuntime after the package is fully downloaded,
        // then continue with the signed desktop installer.
        if (!isLegacyRuntimeIdleProbeUnavailable(error)) throw error;
      }
      await stopRuntimeForExit();
      await update.install();
      await relaunch();
    } catch (error) {
      setState((current) => ({
        ...current,
        status: "available",
        progress: null,
        error: errorMessage(error),
      }));
    } finally {
      installInFlightRef.current = false;
    }
  }, [state.status]);

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
    void checkForUpdates();
    return () => {
      checkGenerationRef.current += 1;
      void updateRef.current?.close();
      updateRef.current = null;
      updateDownloadedRef.current = false;
    };
  }, [checkForUpdates]);

  return {
    ...state,
    desktopRuntime,
    checkForUpdates,
    installAvailableUpdate,
    installComponentUpdates,
    reconcileEnginePack,
    reconcileComponentPacks,
  };
}
