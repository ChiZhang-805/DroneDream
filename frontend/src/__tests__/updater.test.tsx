import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const { checkMock, relaunchMock } = vi.hoisted(() => ({
  checkMock: vi.fn(),
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
}));

import { useAppUpdater } from "../desktop/updater";

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
    close: vi.fn(async () => undefined),
    downloadAndInstall: vi.fn(async () => undefined),
    ...overrides,
  };
}

beforeEach(() => {
  vi.stubEnv("MODE", "production");
  checkMock.mockReset();
  relaunchMock.mockReset();
  relaunchMock.mockResolvedValue(undefined);
});

afterEach(() => {
  vi.unstubAllEnvs();
});

describe("useAppUpdater", () => {
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
    expect(availableUpdate.downloadAndInstall).toHaveBeenCalledOnce();

    installing.resolve();
    await act(async () => Promise.all([firstInstall, secondInstall]));
    expect(relaunchMock).toHaveBeenCalledOnce();
    hook.unmount();
  });
});
