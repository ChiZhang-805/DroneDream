import { useCallback, useEffect, useRef, useState } from "react";
import { check, type Update } from "@tauri-apps/plugin-updater";
import { relaunch } from "@tauri-apps/plugin-process";

import {
  ensureAppUpdateIdle,
  getEnginePackStatus,
  installEmbeddedEnginePack,
  isDesktopRuntime,
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
  | "runtimeBaseRequired"
  | "error";

interface AppUpdateState {
  status: AppUpdateStatus;
  availableVersion: string | null;
  updateRequired: boolean;
  progress: number | null;
  error: string | null;
  enginePack: EnginePackStatus | null;
}

const CURRENT_STATE: AppUpdateState = {
  status: "current",
  availableVersion: null,
  updateRequired: false,
  progress: null,
  error: null,
  enginePack: null,
};

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

function isActiveExperimentDeferral(message: string): boolean {
  return message.includes("waiting for active experiments to finish");
}

export function useAppUpdater() {
  const desktopRuntime = isDesktopRuntime();
  const updateRef = useRef<Update | null>(null);
  const checkGenerationRef = useRef(0);
  const installInFlightRef = useRef(false);
  const [state, setState] = useState<AppUpdateState>(() => (
    desktopRuntime && import.meta.env.MODE !== "test"
      ? { ...CURRENT_STATE, status: "checking" }
      : CURRENT_STATE
  ));

  const reconcileEnginePack = useCallback(async (generation?: number) => {
    if (!desktopRuntime || import.meta.env.MODE === "test") return;
    setState((current) => ({
      ...current,
      status: "reconcilingEngine",
      progress: null,
      error: null,
    }));
    try {
      const observed = await getEnginePackStatus();
      if (generation !== undefined && generation !== checkGenerationRef.current) return;
      if (!observed.supported) {
        setState({
          status: "runtimeBaseRequired",
          availableVersion: null,
          updateRequired: true,
          progress: null,
          error: observed.message,
          enginePack: observed,
        });
        return;
      }
      if (!observed.updateRequired) {
        setState({ ...CURRENT_STATE, enginePack: observed });
        return;
      }
      const installed = await installEmbeddedEnginePack();
      if (generation !== undefined && generation !== checkGenerationRef.current) return;
      setState({ ...CURRENT_STATE, enginePack: installed });
    } catch (error) {
      if (generation !== undefined && generation !== checkGenerationRef.current) return;
      const message = errorMessage(error);
      setState((current) => ({
        ...current,
        status: isActiveExperimentDeferral(message)
          ? "engineUpdateDeferred"
          : "engineError",
        progress: null,
        error: message,
      }));
    }
  }, [desktopRuntime]);

  const checkForUpdates = useCallback(async () => {
    if (!desktopRuntime || import.meta.env.MODE === "test") {
      setState(CURRENT_STATE);
      return;
    }
    if (installInFlightRef.current) return;
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
      if (!update) {
        await reconcileEnginePack(generation);
        return;
      }
      setState({
        status: "available",
        availableVersion: update.version,
        updateRequired: appUpdateIsRequired(update),
        progress: null,
        error: null,
        enginePack: null,
      });
    } catch (error) {
      if (generation !== checkGenerationRef.current) return;
      setState({
        status: "error",
        availableVersion: null,
        updateRequired: false,
        progress: null,
        error: errorMessage(error),
        enginePack: null,
      });
    }
  }, [desktopRuntime, reconcileEnginePack]);

  const installAvailableUpdate = useCallback(async () => {
    const update = updateRef.current;
    if (
      !update
      || state.status !== "available"
      || installInFlightRef.current
    ) return;
    installInFlightRef.current = true;
    let downloaded = 0;
    let contentLength = 0;
    setState((current) => ({ ...current, status: "downloading", progress: 0, error: null }));
    try {
      await ensureAppUpdateIdle();
      await update.downloadAndInstall((event) => {
        if (event.event === "Started") {
          contentLength = event.data.contentLength ?? 0;
          return;
        }
        if (event.event === "Progress") {
          downloaded += event.data.chunkLength;
          const progress = contentLength > 0
            ? Math.min(99, Math.round((downloaded / contentLength) * 100))
            : null;
          setState((current) => ({ ...current, progress }));
          return;
        }
        setState((current) => ({ ...current, status: "installing", progress: 100 }));
      });
      setState((current) => ({ ...current, status: "installing", progress: 100 }));
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

  useEffect(() => {
    void checkForUpdates();
    return () => {
      checkGenerationRef.current += 1;
      void updateRef.current?.close();
      updateRef.current = null;
    };
  }, [checkForUpdates]);

  return {
    ...state,
    desktopRuntime,
    checkForUpdates,
    installAvailableUpdate,
    reconcileEnginePack,
  };
}
