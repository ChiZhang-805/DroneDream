import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const {
  checkMock,
  checkComponentUpdatesMock,
  ensureAppUpdateIdleMock,
  getEnginePackStatusMock,
  installEmbeddedEnginePackMock,
  installComponentUpdateMock,
  relaunchMock,
} = vi.hoisted(() => ({
  checkMock: vi.fn(),
  checkComponentUpdatesMock: vi.fn(),
  ensureAppUpdateIdleMock: vi.fn(),
  getEnginePackStatusMock: vi.fn(),
  installEmbeddedEnginePackMock: vi.fn(),
  installComponentUpdateMock: vi.fn(),
  relaunchMock: vi.fn(),
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
  getEnginePackStatus: getEnginePackStatusMock,
  installEmbeddedEnginePack: installEmbeddedEnginePackMock,
  installComponentUpdate: installComponentUpdateMock,
}));

import { appUpdateIsRequired, useAppUpdater } from "../desktop/updater";

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
    downloadAndInstall: vi.fn(async () => undefined),
    ...overrides,
  };
}

beforeEach(() => {
  vi.stubEnv("MODE", "production");
  checkMock.mockReset();
  ensureAppUpdateIdleMock.mockReset();
  ensureAppUpdateIdleMock.mockResolvedValue(undefined);
  relaunchMock.mockReset();
  relaunchMock.mockResolvedValue(undefined);
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
    const availableUpdate = update("1.0.2", {
      downloadAndInstall: vi.fn(() => installing.promise),
    });
    checkMock.mockResolvedValue(availableUpdate);
    const hook = renderHook(() => useAppUpdater());
    await waitFor(() => expect(hook.result.current.status).toBe("available"));

    let firstInstall!: Promise<void>;
    let secondInstall!: Promise<void>;
    act(() => {
      firstInstall = hook.result.current.installAvailableUpdate();
      secondInstall = hook.result.current.installAvailableUpdate();
    });
    await waitFor(() => expect(availableUpdate.downloadAndInstall).toHaveBeenCalledOnce());

    installing.resolve();
    await act(async () => Promise.all([firstInstall, secondInstall]));
    expect(relaunchMock).toHaveBeenCalledOnce();
    hook.unmount();
  });

  it("does not download or relaunch while a Runtime experiment is active", async () => {
    const availableUpdate = update("1.0.0");
    checkMock.mockResolvedValue(availableUpdate);
    ensureAppUpdateIdleMock.mockRejectedValue(
      new Error("Engine Pack update is waiting for active experiments to finish (1 jobs, 0 trials)"),
    );
    const hook = renderHook(() => useAppUpdater());
    await waitFor(() => expect(hook.result.current.status).toBe("available"));

    await act(async () => hook.result.current.installAvailableUpdate());

    expect(availableUpdate.downloadAndInstall).not.toHaveBeenCalled();
    expect(relaunchMock).not.toHaveBeenCalled();
    expect(hook.result.current.status).toBe("available");
    expect(hook.result.current.error).toContain("active experiments");
    hook.unmount();
  });

  it("reconciles the embedded Engine Pack before checking or advertising an app update", async () => {
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
    await waitFor(() => expect(hook.result.current.status).toBe("current"));

    expect(getEnginePackStatusMock).toHaveBeenCalledOnce();
    expect(installEmbeddedEnginePackMock).toHaveBeenCalledOnce();
    expect(getEnginePackStatusMock.mock.invocationCallOrder[0]).toBeLessThan(
      checkMock.mock.invocationCallOrder[0],
    );
    expect(hook.result.current.enginePack).toEqual(installedPack);
    hook.unmount();
  });

  it("keeps the reconciled Engine Pack visible while an app update is available", async () => {
    const availableUpdate = update("1.0.2");
    checkMock.mockResolvedValue(availableUpdate);

    const hook = renderHook(() => useAppUpdater());
    await waitFor(() => expect(hook.result.current.status).toBe("available"));

    expect(hook.result.current.enginePack?.updateRequired).toBe(false);
    expect(getEnginePackStatusMock).toHaveBeenCalledOnce();
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
      embeddedPackId: `sha256:${"3".repeat(64)}`,
      embeddedSourceCommit: "4".repeat(40),
      installedPackId: null,
      installedSourceCommit: null,
      message: "The installed Runtime Base predates Engine Pack updates.",
    });

    const hook = renderHook(() => useAppUpdater());
    await waitFor(() => expect(hook.result.current.status).toBe("runtimeBaseRequired"));

    expect(installEmbeddedEnginePackMock).not.toHaveBeenCalled();
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
        policy: "required",
        packId: `sha256:${"5".repeat(64)}`,
        installedVersion: "1.1.0",
        installedReleaseSequence: 11,
        available: true,
      }],
    });

    const hook = renderHook(() => useAppUpdater());
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
          policy: "recommended",
          packId: `sha256:${"6".repeat(64)}`,
          installedVersion: null,
          installedReleaseSequence: 0,
          available: true,
        },
        {
          componentId: "capability-pack",
          version: "1.2.0",
          releaseSequence: 12,
          policy: "recommended",
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
});
