import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const {
  checkMock,
  checkComponentUpdatesMock,
  ensureAppUpdateIdleMock,
  getAppUpdateProgressMock,
  getEnginePackStatusMock,
  installAppUpdateInBackgroundMock,
  installEmbeddedEnginePackMock,
  installComponentUpdateMock,
  listJobsMock,
  listenAppUpdateProgressMock,
  probeRuntimeStatusMock,
  relaunchMock,
  stopRuntimeForExitMock,
} = vi.hoisted(() => ({
  checkMock: vi.fn(),
  checkComponentUpdatesMock: vi.fn(),
  ensureAppUpdateIdleMock: vi.fn(),
  getAppUpdateProgressMock: vi.fn(),
  getEnginePackStatusMock: vi.fn(),
  installAppUpdateInBackgroundMock: vi.fn(),
  installEmbeddedEnginePackMock: vi.fn(),
  installComponentUpdateMock: vi.fn(),
  listJobsMock: vi.fn(),
  listenAppUpdateProgressMock: vi.fn(),
  probeRuntimeStatusMock: vi.fn(),
  relaunchMock: vi.fn(),
  stopRuntimeForExitMock: vi.fn(),
}));

vi.mock("@tauri-apps/plugin-updater", () => ({
  check: checkMock,
}));
vi.mock("@tauri-apps/plugin-process", () => ({
  relaunch: relaunchMock,
}));
vi.mock("../desktop/bridge", () => ({
  isDesktopRuntime: () => true,
  ensureAppUpdateIdle: ensureAppUpdateIdleMock,
  checkComponentUpdates: checkComponentUpdatesMock,
  getAppUpdateProgress: getAppUpdateProgressMock,
  getEnginePackStatus: getEnginePackStatusMock,
  installAppUpdateInBackground: installAppUpdateInBackgroundMock,
  installEmbeddedEnginePack: installEmbeddedEnginePackMock,
  installComponentUpdate: installComponentUpdateMock,
  listenAppUpdateProgress: listenAppUpdateProgressMock,
  probeRuntimeStatus: probeRuntimeStatusMock,
  stopRuntimeForExit: stopRuntimeForExitMock,
}));
vi.mock("../api/client", () => ({
  apiClient: { listJobs: listJobsMock },
}));

import {
  appUpdateIsRequired,
  detectRunningUpdateBlock,
  isNoPublishedDesktopUpdate,
  isLegacyRuntimeIdleProbeUnavailable,
  orderComponentUpdates,
  selectManualComponentUpdates,
  updaterDownloadSize,
  useAppUpdater,
} from "../desktop/updater";

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((nextResolve) => {
    resolve = nextResolve;
  });
  return { promise, resolve };
}

function update(version: string, overrides: Record<string, unknown> = {}) {
  return {
    version,
    body: "update-policy: recommended",
    rawJson: {},
    close: vi.fn(async () => undefined),
    download: vi.fn(async () => undefined),
    install: vi.fn(async () => undefined),
    ...overrides,
  };
}

beforeEach(() => {
  vi.stubEnv("MODE", "production");
  checkMock.mockReset();
  ensureAppUpdateIdleMock.mockReset();
  ensureAppUpdateIdleMock.mockResolvedValue(undefined);
  getAppUpdateProgressMock.mockReset();
  getAppUpdateProgressMock.mockResolvedValue({ running: false, progress: null });
  listenAppUpdateProgressMock.mockReset();
  listenAppUpdateProgressMock.mockResolvedValue(vi.fn());
  relaunchMock.mockReset();
  relaunchMock.mockResolvedValue(undefined);
  stopRuntimeForExitMock.mockReset();
  stopRuntimeForExitMock.mockResolvedValue(undefined);
  probeRuntimeStatusMock.mockReset();
  probeRuntimeStatusMock.mockResolvedValue({
    runtimeName: "DroneDream Runtime",
    installed: true,
    running: false,
    ready: false,
    version: "1.0.0",
    dataRoot: "Q:\\DroneDreamRuntime",
    components: [],
    diagnostics: [],
  });
  listJobsMock.mockReset();
  listJobsMock.mockResolvedValue({ items: [], page: 1, page_size: 100, total: 0 });
  getEnginePackStatusMock.mockReset();
  getEnginePackStatusMock.mockResolvedValue({
    supported: true,
    updateRequired: false,
    embeddedPackId: `sha256:${"1".repeat(64)}`,
    embeddedSourceCommit: "2".repeat(40),
    installedPackId: `sha256:${"1".repeat(64)}`,
    installedSourceCommit: "2".repeat(40),
    message: null,
  });
  installEmbeddedEnginePackMock.mockReset();
  installAppUpdateInBackgroundMock.mockReset();
  installAppUpdateInBackgroundMock.mockImplementation(async (onProgress: (event: {
    phase: string; progress: number; attempt: number;
  }) => void) => {
    onProgress({ phase: "downloading", progress: 48, attempt: 1 });
    onProgress({ phase: "installing", progress: 100, attempt: 1 });
  });
  checkComponentUpdatesMock.mockReset();
  checkComponentUpdatesMock.mockResolvedValue({
    catalogSequence: 1,
    generatedAt: "2026-08-16T00:00:00Z",
    expiresAt: "2026-08-23T00:00:00Z",
    candidates: [],
  });
  installComponentUpdateMock.mockReset();
});

afterEach(() => {
  vi.unstubAllEnvs();
});

describe("useAppUpdater", () => {
  it("treats routine updates as optional and only signed required policy as blocking", () => {
    expect(appUpdateIsRequired({ body: undefined, rawJson: {} })).toBe(false);
    expect(appUpdateIsRequired({
      body: "update-policy: recommended",
      rawJson: {},
    })).toBe(false);
    expect(appUpdateIsRequired({
      body: "update-policy: required",
      rawJson: {},
    })).toBe(true);
    expect(appUpdateIsRequired({
      body: "update-policy: recommended",
      rawJson: { updatePolicy: "required" },
    })).toBe(true);
  });

  it("reads the signed updater installer length without accepting malformed values", () => {
    expect(updaterDownloadSize({
      platforms: { "windows-x86_64": { size: 83_000_000 } },
    })).toBe(83_000_000);
    expect(updaterDownloadSize({ platforms: { "windows-x86_64": { size: -1 } } })).toBe(0);
    expect(updaterDownloadSize({ platforms: { "windows-x86_64": { size: "83000000" } } })).toBe(0);
  });

  it("recognizes only the legacy Runtime idle-probe bootstrap failure", () => {
    expect(isLegacyRuntimeIdleProbeUnavailable(new Error(
      "The Runtime Base must be upgraded before DroneDream can update safely.",
    ))).toBe(true);
    expect(isLegacyRuntimeIdleProbeUnavailable(new Error(
      "Engine Pack update is waiting for active experiments to finish (1 jobs, 0 trials)",
    ))).toBe(false);
  });

  it("treats an unpublished desktop channel as current without hiding real updater errors", async () => {
    const unpublished = new Error("Could not fetch a valid release JSON from the remote");
    expect(isNoPublishedDesktopUpdate(unpublished)).toBe(true);
    expect(isNoPublishedDesktopUpdate(new Error("network unavailable"))).toBe(false);

    checkMock.mockRejectedValue(unpublished);
    const hook = renderHook(() => useAppUpdater());
    await waitFor(() => expect(checkMock).toHaveBeenCalledOnce());
    await act(async () => hook.result.current.checkForUpdates());
    await waitFor(() => expect(hook.result.current.status).toBe("current"));

    expect(hook.result.current.error).toBeNull();
    expect(getEnginePackStatusMock).toHaveBeenCalledOnce();
    hook.unmount();
  });

  it("keeps genuine desktop updater failures visible", async () => {
    checkMock.mockRejectedValue(new Error("network unavailable"));
    const hook = renderHook(() => useAppUpdater());
    await waitFor(() => expect(checkMock).toHaveBeenCalledOnce());
    await act(async () => hook.result.current.checkForUpdates());
    await waitFor(() => expect(hook.result.current.status).toBe("error"));

    expect(hook.result.current.error).toBe("network unavailable");
    hook.unmount();
  });

  it("discards a stale check that finishes after a newer request", async () => {
    const first = deferred<ReturnType<typeof update>>();
    const second = deferred<ReturnType<typeof update>>();
    const staleUpdate = update("1.0.1");
    const currentUpdate = update("1.0.2");
    checkMock
      .mockReturnValueOnce(first.promise)
      .mockReturnValueOnce(second.promise);

    const hook = renderHook(() => useAppUpdater());
    await waitFor(() => expect(checkMock).toHaveBeenCalledOnce());
    let retry!: Promise<void>;
    act(() => {
      retry = hook.result.current.checkForUpdates();
    });
    await waitFor(() => expect(checkMock).toHaveBeenCalledTimes(2));

    second.resolve(currentUpdate);
    await act(async () => retry);
    expect(hook.result.current.availableVersion).toBe("1.0.2");

    first.resolve(staleUpdate);
    await waitFor(() => expect(staleUpdate.close).toHaveBeenCalledOnce());
    expect(hook.result.current.availableVersion).toBe("1.0.2");
    hook.unmount();
  });

  it("starts only one installer when invoked twice before rerender", async () => {
    const installing = deferred<void>();
    const availableUpdate = update("1.0.2");
    installAppUpdateInBackgroundMock.mockReturnValue(installing.promise);
    checkMock.mockResolvedValue(availableUpdate);
    const hook = renderHook(() => useAppUpdater());
    await waitFor(() => expect(hook.result.current.status).toBe("available"));

    let firstInstall!: Promise<void>;
    let secondInstall!: Promise<void>;
    act(() => {
      firstInstall = hook.result.current.installAvailableUpdate();
      secondInstall = hook.result.current.installAvailableUpdate();
    });
    await waitFor(() => expect(installAppUpdateInBackgroundMock).toHaveBeenCalledOnce());

    installing.resolve();
    await act(async () => Promise.all([firstInstall, secondInstall]));
    expect(installAppUpdateInBackgroundMock).toHaveBeenCalledOnce();
    hook.unmount();
  });

  it("does not download, install, or relaunch while a Runtime experiment is active", async () => {
    const availableUpdate = update("1.0.0");
    checkMock.mockResolvedValue(availableUpdate);
    probeRuntimeStatusMock.mockResolvedValue({
      runtimeName: "DroneDream Runtime",
      installed: true,
      running: true,
      ready: true,
      version: "1.0.0",
      dataRoot: "Q:\\DroneDreamRuntime",
      components: [],
      diagnostics: [],
    });
    listJobsMock.mockResolvedValue({
      items: [{ id: "job-running", display_name: "Office delivery" }],
      page: 1,
      page_size: 100,
      total: 1,
    });
    const hook = renderHook(() => useAppUpdater());
    await waitFor(() => expect(hook.result.current.status).toBe("available"));

    await act(async () => hook.result.current.installAvailableUpdate());

    expect(installAppUpdateInBackgroundMock).not.toHaveBeenCalled();
    expect(stopRuntimeForExitMock).not.toHaveBeenCalled();
    expect(hook.result.current.status).toBe("available");
    expect(hook.result.current.blockedActivity).toMatchObject({
      kind: "running",
      runningJobs: [{ id: "job-running", name: "Office delivery" }],
    });
    hook.unmount();
  });

  it("hands the complete download, install, and restart lifecycle to the native process", async () => {
    const availableUpdate = update("1.0.2");
    checkMock.mockResolvedValue(availableUpdate);
    const hook = renderHook(() => useAppUpdater());
    await waitFor(() => expect(hook.result.current.status).toBe("available"));

    await act(async () => hook.result.current.installAvailableUpdate());

    expect(installAppUpdateInBackgroundMock).toHaveBeenCalledOnce();
    expect(hook.result.current.progress).toBe(100);
    expect(hook.result.current.status).toBe("installing");
    expect(probeRuntimeStatusMock).toHaveBeenCalledOnce();
    hook.unmount();
  });

  it("does not cancel or reset a native update during a transient auth disable", async () => {
    const nativeUpdate = deferred<void>();
    installAppUpdateInBackgroundMock.mockImplementation(async (onProgress: (event: {
      phase: string; progress: number; attempt: number;
    }) => void) => {
      onProgress({ phase: "downloading", progress: 41, attempt: 1 });
      await nativeUpdate.promise;
    });
    const availableUpdate = update("1.0.2");
    checkMock.mockResolvedValue(availableUpdate);
    const hook = renderHook(
      ({ enabled }) => useAppUpdater({ enabled }),
      { initialProps: { enabled: true } },
    );
    await waitFor(() => expect(hook.result.current.status).toBe("available"));

    let installation!: Promise<void>;
    act(() => {
      installation = hook.result.current.installAvailableUpdate();
    });
    await waitFor(() => expect(hook.result.current.progress).toBe(41));

    hook.rerender({ enabled: false });
    expect(hook.result.current.status).toBe("downloading");
    expect(hook.result.current.progress).toBe(41);
    expect(availableUpdate.close).not.toHaveBeenCalled();

    nativeUpdate.resolve();
    await act(async () => installation);
    hook.unmount();
  });

  it("restores one process-owned download after the updater view remounts", async () => {
    getAppUpdateProgressMock.mockResolvedValue({
      running: true,
      progress: { phase: "downloading", progress: 31, attempt: 1 },
    });
    const firstView = renderHook(() => useAppUpdater());
    await waitFor(() => expect(firstView.result.current.progress).toBe(31));
    expect(firstView.result.current.status).toBe("downloading");
    expect(checkMock).not.toHaveBeenCalled();
    firstView.unmount();

    getAppUpdateProgressMock.mockResolvedValue({
      running: true,
      progress: { phase: "downloading", progress: 32, attempt: 1 },
    });
    const secondView = renderHook(() => useAppUpdater());
    await waitFor(() => expect(secondView.result.current.progress).toBe(32));
    expect(secondView.result.current.status).toBe("downloading");
    expect(checkMock).not.toHaveBeenCalled();
    secondView.unmount();
  });

  it("queries only exact RUNNING jobs when a ready Runtime is active", async () => {
    probeRuntimeStatusMock.mockResolvedValue({
      runtimeName: "DroneDream Runtime",
      installed: true,
      running: true,
      ready: true,
      version: "1.0.0",
      dataRoot: "Q:\\DroneDreamRuntime",
      components: [],
      diagnostics: [],
    });

    await expect(detectRunningUpdateBlock()).resolves.toBeNull();

    expect(listJobsMock).toHaveBeenCalledWith({
      status: "RUNNING",
      page: 1,
      page_size: 100,
    });
  });

  it("reconciles the embedded Engine Pack after confirming the app is current", async () => {
    const pendingPack = {
      supported: true,
      updateRequired: true,
      embeddedPackId: `sha256:${"3".repeat(64)}`,
      embeddedSourceCommit: "4".repeat(40),
      installedPackId: `sha256:${"1".repeat(64)}`,
      installedSourceCommit: "2".repeat(40),
      message: null,
    };
    const installedPack = { ...pendingPack, updateRequired: false };
    checkMock.mockResolvedValue(null);
    getEnginePackStatusMock.mockResolvedValue(pendingPack);
    installEmbeddedEnginePackMock.mockResolvedValue(installedPack);

    const hook = renderHook(() => useAppUpdater());
    await waitFor(() => expect(checkMock).toHaveBeenCalledOnce());
    await act(async () => hook.result.current.checkForUpdates());
    await waitFor(() => expect(hook.result.current.status).toBe("current"));

    expect(getEnginePackStatusMock).toHaveBeenCalledOnce();
    expect(installEmbeddedEnginePackMock).toHaveBeenCalledOnce();
    expect(checkMock.mock.invocationCallOrder[1]).toBeLessThan(
      getEnginePackStatusMock.mock.invocationCallOrder[0],
    );
    expect(hook.result.current.enginePack).toEqual(installedPack);
    hook.unmount();
  });

  it("advertises an app update without letting Engine Pack reconciliation strand recovery", async () => {
    const availableUpdate = update("1.0.2");
    checkMock.mockResolvedValue(availableUpdate);

    const hook = renderHook(() => useAppUpdater());
    await waitFor(() => expect(hook.result.current.status).toBe("available"));

    expect(hook.result.current.enginePack).toBeNull();
    expect(getEnginePackStatusMock).not.toHaveBeenCalled();
    expect(checkMock).toHaveBeenCalledOnce();
    hook.unmount();
  });

  it("defers Engine Pack activation while an experiment is active", async () => {
    checkMock.mockResolvedValue(null);
    getEnginePackStatusMock.mockResolvedValue({
      supported: true,
      updateRequired: true,
      embeddedPackId: `sha256:${"3".repeat(64)}`,
      embeddedSourceCommit: "4".repeat(40),
      installedPackId: `sha256:${"1".repeat(64)}`,
      installedSourceCommit: "2".repeat(40),
      message: null,
    });
    installEmbeddedEnginePackMock.mockRejectedValue(
      new Error("Engine Pack update is waiting for active experiments to finish (1 jobs, 1 trials)"),
    );

    const hook = renderHook(() => useAppUpdater());
    await waitFor(() => expect(checkMock).toHaveBeenCalledOnce());
    await act(async () => hook.result.current.checkForUpdates());
    await waitFor(() => expect(hook.result.current.status).toBe("engineUpdateDeferred"));

    expect(hook.result.current.error).toContain("active experiments");
    expect(relaunchMock).not.toHaveBeenCalled();
    hook.unmount();
  });

  it("requires a one-time Runtime Base upgrade when the manager is unavailable", async () => {
    checkMock.mockResolvedValue(null);
    getEnginePackStatusMock.mockResolvedValue({
      supported: false,
      updateRequired: true,
      runtimeBaseUpgradeAvailable: true,
      embeddedPackId: `sha256:${"3".repeat(64)}`,
      embeddedSourceCommit: "4".repeat(40),
      installedPackId: null,
      installedSourceCommit: null,
      message: "The installed Runtime Base predates Engine Pack updates.",
    });

    const hook = renderHook(() => useAppUpdater());
    await waitFor(() => expect(checkMock).toHaveBeenCalledOnce());
    await act(async () => hook.result.current.checkForUpdates());
    await waitFor(() => expect(hook.result.current.status).toBe("runtimeBaseRequired"));

    expect(installEmbeddedEnginePackMock).not.toHaveBeenCalled();
    hook.unmount();
  });

  it("keeps an unavailable Runtime Base upgrade non-blocking and skips component mutation", async () => {
    vi.stubEnv("VITE_COMPONENT_UPDATE_CATALOG_ENABLED", "true");
    checkMock.mockResolvedValue(null);
    getEnginePackStatusMock.mockResolvedValue({
      supported: false,
      updateRequired: true,
      runtimeBaseUpgradeAvailable: false,
      embeddedPackId: `sha256:${"3".repeat(64)}`,
      embeddedSourceCommit: "4".repeat(40),
      installedPackId: null,
      installedSourceCommit: null,
      message: "The signed Runtime Base channel does not contain a newer build.",
    });

    const hook = renderHook(() => useAppUpdater());
    await waitFor(() => expect(checkMock).toHaveBeenCalledOnce());
    await act(async () => hook.result.current.checkForUpdates());
    await waitFor(() => expect(hook.result.current.status).toBe("current"));

    expect(hook.result.current.updateRequired).toBe(false);
    expect(hook.result.current.error).toBeNull();
    expect(hook.result.current.enginePack).toMatchObject({
      supported: false,
      updateRequired: true,
      runtimeBaseUpgradeAvailable: false,
    });
    expect(installEmbeddedEnginePackMock).not.toHaveBeenCalled();
    expect(checkMock).toHaveBeenCalledTimes(2);
    expect(checkComponentUpdatesMock).not.toHaveBeenCalled();
    hook.unmount();
  });

  it("surfaces signed component updates only after the app and Engine Pack are current", async () => {
    vi.stubEnv("VITE_COMPONENT_UPDATE_CATALOG_ENABLED", "true");
    checkMock.mockResolvedValue(null);
    checkComponentUpdatesMock.mockResolvedValue({
      catalogSequence: 4,
      generatedAt: "2026-08-16T00:00:00Z",
      expiresAt: "2026-08-23T00:00:00Z",
      candidates: [{
        componentId: "capability-pack",
        version: "1.2.0",
        releaseSequence: 12,
        urgency: "required",
        installMode: "user-confirmed",
        dependencies: [],
        packId: `sha256:${"5".repeat(64)}`,
        installedVersion: "1.1.0",
        installedReleaseSequence: 11,
        available: true,
      }],
    });

    const hook = renderHook(() => useAppUpdater());
    await waitFor(() => expect(checkMock).toHaveBeenCalledOnce());
    await act(async () => hook.result.current.checkForUpdates());
    await waitFor(() => expect(hook.result.current.status).toBe("componentAvailable"));

    expect(getEnginePackStatusMock).toHaveBeenCalledOnce();
    expect(checkComponentUpdatesMock).toHaveBeenCalledOnce();
    expect(hook.result.current.updateRequired).toBe(true);
    hook.unmount();
  });

  it("installs capability before assets and rechecks the signed catalog", async () => {
    vi.stubEnv("VITE_COMPONENT_UPDATE_CATALOG_ENABLED", "true");
    checkMock.mockResolvedValue(null);
    const availableReport = {
      catalogSequence: 5,
      generatedAt: "2026-08-16T00:00:00Z",
      expiresAt: "2026-08-23T00:00:00Z",
      candidates: [
        {
          componentId: "asset-pack",
          version: "2.0.0",
          releaseSequence: 20,
          urgency: "recommended",
          installMode: "user-confirmed",
          dependencies: [{
            componentId: "capability-pack",
            minimumReleaseSequence: 12,
          }],
          packId: `sha256:${"6".repeat(64)}`,
          installedVersion: null,
          installedReleaseSequence: 0,
          available: true,
        },
        {
          componentId: "capability-pack",
          version: "1.2.0",
          releaseSequence: 12,
          urgency: "recommended",
          installMode: "user-confirmed",
          dependencies: [],
          packId: `sha256:${"5".repeat(64)}`,
          installedVersion: "1.1.0",
          installedReleaseSequence: 11,
          available: true,
        },
      ],
    };
    checkComponentUpdatesMock
      .mockResolvedValueOnce(availableReport)
      .mockResolvedValueOnce({ ...availableReport, candidates: [] });
    installComponentUpdateMock.mockImplementation(async (componentId: string) => ({
      componentId,
      packId: `sha256:${"7".repeat(64)}`,
      version: "1.0.0",
      releaseSequence: 1,
      activated: true,
    }));

    const hook = renderHook(() => useAppUpdater());
    await waitFor(() => expect(checkMock).toHaveBeenCalledOnce());
    await act(async () => hook.result.current.checkForUpdates());
    await waitFor(() => expect(hook.result.current.status).toBe("componentAvailable"));
    await act(async () => hook.result.current.installComponentUpdates());

    expect(ensureAppUpdateIdleMock).toHaveBeenCalledOnce();
    expect(installComponentUpdateMock.mock.calls.map(([componentId]) => componentId)).toEqual([
      "capability-pack",
      "asset-pack",
    ]);
    expect(checkComponentUpdatesMock).toHaveBeenCalledTimes(2);
    expect(hook.result.current.status).toBe("current");
    hook.unmount();
  });

  it("installs signed automatic capability updates without silently downloading assets", async () => {
    vi.stubEnv("VITE_COMPONENT_UPDATE_CATALOG_ENABLED", "true");
    checkMock.mockResolvedValue(null);
    const automatic = {
      catalogSequence: 6,
      generatedAt: "2026-08-16T00:00:00Z",
      expiresAt: "2026-08-23T00:00:00Z",
      candidates: [{
        componentId: "capability-pack",
        version: "1.3.0",
        releaseSequence: 13,
        urgency: "recommended",
        installMode: "automatic",
        dependencies: [],
        packId: `sha256:${"8".repeat(64)}`,
        installedVersion: "1.2.0",
        installedReleaseSequence: 12,
        available: true,
      }],
    };
    checkComponentUpdatesMock
      .mockResolvedValueOnce(automatic)
      .mockResolvedValueOnce({ ...automatic, candidates: [] });
    installComponentUpdateMock.mockResolvedValue({
      componentId: "capability-pack",
      packId: `sha256:${"8".repeat(64)}`,
      version: "1.3.0",
      releaseSequence: 13,
      activated: true,
    });

    const hook = renderHook(() => useAppUpdater());
    await waitFor(() => expect(checkMock).toHaveBeenCalledOnce());
    await act(async () => hook.result.current.checkForUpdates());
    await waitFor(() => expect(hook.result.current.status).toBe("current"));

    expect(installComponentUpdateMock).toHaveBeenCalledWith(
      "capability-pack",
      undefined,
    );
    hook.unmount();
  });

  it("keeps urgency separate from delivery and resolves signed dependencies", () => {
    const capability = {
      componentId: "capability-pack" as const,
      version: "1.2.0",
      releaseSequence: 12,
      urgency: "recommended" as const,
      installMode: "user-confirmed" as const,
      dependencies: [],
      packId: `sha256:${"5".repeat(64)}`,
      installedVersion: "1.1.0",
      installedReleaseSequence: 11,
      available: true,
    };
    const asset = {
      ...capability,
      componentId: "asset-pack" as const,
      urgency: "required" as const,
      dependencies: [{
        componentId: "capability-pack" as const,
        minimumReleaseSequence: 12,
      }],
    };
    const optional = { ...capability, urgency: "optional" as const };

    expect(orderComponentUpdates([asset, capability])).toEqual([
      "capability-pack",
      "asset-pack",
    ]);
    expect(selectManualComponentUpdates([asset, capability]).map((item) => item.componentId))
      .toEqual(["asset-pack", "capability-pack"]);
    expect(selectManualComponentUpdates([optional])).toEqual([optional]);
  });
});
