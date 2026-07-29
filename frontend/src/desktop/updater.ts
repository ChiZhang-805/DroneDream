import { useCallback, useEffect, useRef, useState } from "react";
import { check, type Update } from "@tauri-apps/plugin-updater";
import { relaunch } from "@tauri-apps/plugin-process";

import { isDesktopRuntime } from "./bridge";

export type AppUpdateStatus =
  | "checking"
  | "current"
  | "available"
  | "downloading"
  | "installing"
  | "error";

interface AppUpdateState {
  status: AppUpdateStatus;
  availableVersion: string | null;
  progress: number | null;
  error: string | null;
}

const CURRENT_STATE: AppUpdateState = {
  status: "current",
  availableVersion: null,
  progress: null,
  error: null,
};

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
        setState(CURRENT_STATE);
        return;
      }
      setState({
        status: "available",
        availableVersion: update.version,
        progress: null,
        error: null,
      });
    } catch (error) {
      if (generation !== checkGenerationRef.current) return;
      setState({
        status: "error",
        availableVersion: null,
        progress: null,
        error: error instanceof Error ? error.message : String(error),
      });
    }
  }, [desktopRuntime]);

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
        error: error instanceof Error ? error.message : String(error),
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
  };
}
