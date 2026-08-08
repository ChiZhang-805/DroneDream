import { afterEach, describe, expect, it, vi } from "vitest";

import type {
  RuntimeStatusReport,
  SystemPrerequisiteReport,
} from "../desktop/bridge";
import {
  canAutoStartRuntime,
  clearRuntimeAutoStartFailure,
  DESKTOP_READINESS_CHECK_IDS,
  DESKTOP_READINESS_SUCCESS_REVEAL_DELAY_MS,
  ensureOverallDesktopReadiness,
  getDesktopReadinessProgress,
  isOverallDesktopReady,
  isRuntimeConfirmedMissing,
  isRuntimeFullyReady,
  resetDesktopReadinessSession,
  subscribeDesktopReadinessProgress,
} from "../desktop/readiness";

const componentIds = [
  "wsl-runtime",
  "host-ownership",
  "runtime-manifest",
  "local-backend",
  "px4",
  "gazebo",
] as const;

const prerequisites: SystemPrerequisiteReport = {
  platform: "windows",
  supported: true,
  windows: {
    caption: "Windows 11 Pro",
    version: "10.0.26100",
    buildNumber: "26100",
    architecture: "64-bit",
  },
  wsl: { executableAvailable: true, distributions: [] },
  memory: { totalBytes: 16 * 1024 ** 3, availableBytes: 8 * 1024 ** 3 },
  disks: [],
  gpus: [],
  probeErrors: [],
};

const readyRuntime: RuntimeStatusReport = {
  runtimeName: "DroneDreamRuntime",
  installed: true,
  running: true,
  ready: true,
  version: "2026.07",
  dataRoot: "E:\\DroneDream",
  components: componentIds.map((id) => ({
    id,
    label: id,
    status: "ready",
    required: true,
    version: null,
    detail: null,
  })),
  diagnostics: [],
};

const missingRuntime: RuntimeStatusReport = {
  ...readyRuntime,
  installed: false,
  running: false,
  ready: false,
  version: null,
  dataRoot: null,
  components: readyRuntime.components.map((component) => ({
    ...component,
    status: "missing",
  })),
};

const stoppedRuntime: RuntimeStatusReport = {
  ...readyRuntime,
  running: false,
  ready: false,
  components: readyRuntime.components.map((component) => ({
    ...component,
    status: component.id === "host-ownership" ? "ready" : "stopped",
  })),
};

afterEach(() => {
  resetDesktopReadinessSession();
  delete window.__TAURI__;
  vi.restoreAllMocks();
});

describe("desktop readiness", () => {
  it("uses an exact three-second success reveal delay outside tests", () => {
    expect(DESKTOP_READINESS_SUCCESS_REVEAL_DELAY_MS).toBe(3_000);
  });

  it("requires supported Windows, known memory, WSL, and a fully ready runtime", () => {
    expect(isOverallDesktopReady(prerequisites, readyRuntime)).toBe(true);
    expect(isOverallDesktopReady({ ...prerequisites, supported: false }, readyRuntime))
      .toBe(false);
    expect(isOverallDesktopReady({ ...prerequisites, memory: null }, readyRuntime))
      .toBe(false);
    expect(isOverallDesktopReady({
      ...prerequisites,
      memory: { totalBytes: 14 * 1024 ** 3, availableBytes: 8 * 1024 ** 3 },
    }, readyRuntime)).toBe(false);
    expect(isOverallDesktopReady({
      ...prerequisites,
      wsl: { executableAvailable: false, distributions: [] },
    }, readyRuntime)).toBe(false);
    expect(isOverallDesktopReady(prerequisites, missingRuntime)).toBe(false);
  });

  it("does not block an installed runtime for GPU or disk-only probe failures", () => {
    expect(isOverallDesktopReady({
      ...prerequisites,
      disks: [],
      gpus: [],
      probeErrors: ["Disk probe failed", "GPU probe failed"],
    }, readyRuntime)).toBe(true);
  });

  it("requires every required component to be ready", () => {
    expect(isRuntimeFullyReady(readyRuntime)).toBe(true);
    expect(isRuntimeFullyReady({
      ...readyRuntime,
      components: readyRuntime.components.map((component) =>
        component.id === "px4" ? { ...component, status: "unknown" } : component,
      ),
    })).toBe(false);
  });

  it("distinguishes confirmed missing from an uncertain failed probe", () => {
    expect(isRuntimeConfirmedMissing(missingRuntime)).toBe(true);
    expect(isRuntimeConfirmedMissing({
      ...missingRuntime,
      components: missingRuntime.components.map((component) =>
        component.id === "wsl-runtime"
          ? { ...component, status: "unknown" }
          : component,
      ),
      diagnostics: ["Unable to inspect the WSL registry."],
    })).toBe(false);
  });

  it("auto-starts only a confirmed stopped runtime with valid ownership", () => {
    expect(canAutoStartRuntime(prerequisites, stoppedRuntime)).toBe(true);
    expect(canAutoStartRuntime(prerequisites, readyRuntime)).toBe(false);
    expect(canAutoStartRuntime(prerequisites, missingRuntime)).toBe(false);
    expect(canAutoStartRuntime(prerequisites, {
      ...stoppedRuntime,
      components: stoppedRuntime.components.map((component) =>
        component.id === "host-ownership"
          ? { ...component, status: "unhealthy" }
          : component,
      ),
    })).toBe(false);
    expect(canAutoStartRuntime(prerequisites, {
      ...stoppedRuntime,
      running: true,
      components: stoppedRuntime.components.map((component) =>
        component.id === "local-backend"
          ? { ...component, status: "unhealthy" }
          : component,
      ),
    })).toBe(false);
    expect(canAutoStartRuntime({
      ...prerequisites,
      wsl: { executableAvailable: false, distributions: [] },
    }, stoppedRuntime)).toBe(false);
  });

  it("shares one automatic start across concurrent readiness callers", async () => {
    let resolveStart: (runtime: RuntimeStatusReport) => void = () => undefined;
    const pendingStart = new Promise<RuntimeStatusReport>((resolve) => {
      resolveStart = resolve;
    });
    const invoke = vi.fn(async (command: string) => {
      if (command === "probe_system_prerequisites") return prerequisites;
      if (command === "probe_runtime_status") return stoppedRuntime;
      if (command === "start_runtime") return pendingStart;
      throw new Error(`Unexpected command: ${command}`);
    });
    window.__TAURI__ = { core: { invoke } };
    const firstStarting = vi.fn();
    const secondStarting = vi.fn();

    const first = ensureOverallDesktopReadiness({
      autoStart: true,
      onStarting: firstStarting,
    });
    const second = ensureOverallDesktopReadiness({
      autoStart: true,
      onStarting: secondStarting,
    });
    await vi.waitFor(() => {
      expect(invoke.mock.calls.filter(([command]) => command === "start_runtime"))
        .toHaveLength(1);
    });
    resolveStart(readyRuntime);

    await expect(Promise.all([first, second])).resolves.toEqual([
      expect.objectContaining({ ready: true }),
      expect.objectContaining({ ready: true }),
    ]);
    expect(firstStarting).toHaveBeenCalledTimes(1);
    expect(secondStarting).toHaveBeenCalledTimes(1);
  });

  it("stops at zero when Runtime is missing and leaves later checks pending", async () => {
    const invoke = vi.fn(async (command: string) => {
      if (command === "probe_runtime_status") return missingRuntime;
      if (command === "probe_system_prerequisites") return prerequisites;
      throw new Error(`Unexpected command: ${command}`);
    });
    window.__TAURI__ = { core: { invoke } };

    const snapshot = await ensureOverallDesktopReadiness({ autoStart: true });
    const progress = getDesktopReadinessProgress();

    expect(snapshot.ready).toBe(false);
    expect(progress.percent).toBe(0);
    expect(progress.running).toBe(false);
    expect(progress.checks[0]).toEqual(expect.objectContaining({
      id: "runtime",
      status: "failed",
    }));
    expect(progress.checks.slice(1).every((check) => check.status === "pending"))
      .toBe(true);
    expect(invoke.mock.calls.some(([command]) => command === "start_runtime"))
      .toBe(false);
  });

  it("auto-starts one owned stopped Runtime and completes all seven checks", async () => {
    const observedStatuses: Array<readonly string[]> = [];
    const unsubscribe = subscribeDesktopReadinessProgress((progress) => {
      observedStatuses.push(progress.checks.map((check) => `${check.id}:${check.status}`));
    });
    const invoke = vi.fn(async (command: string) => {
      if (command === "probe_runtime_status") return stoppedRuntime;
      if (command === "probe_system_prerequisites") return prerequisites;
      if (command === "start_runtime") return readyRuntime;
      throw new Error(`Unexpected command: ${command}`);
    });
    window.__TAURI__ = { core: { invoke } };

    const snapshot = await ensureOverallDesktopReadiness({ autoStart: true });
    const progress = getDesktopReadinessProgress();
    unsubscribe();

    expect(snapshot.ready).toBe(true);
    expect(progress).toEqual(expect.objectContaining({ percent: 100, running: false }));
    expect(progress.checks.every((check) => check.status === "passed")).toBe(true);
    expect(invoke.mock.calls.filter(([command]) => command === "start_runtime"))
      .toHaveLength(1);
    const firstPassedIndexes = DESKTOP_READINESS_CHECK_IDS.map((id) =>
      observedStatuses.findIndex((statuses) => statuses.includes(`${id}:passed`))
    );
    expect(firstPassedIndexes.every((index) => index >= 0)).toBe(true);
    expect(firstPassedIndexes).toEqual([...firstPassedIndexes].sort((left, right) => left - right));
    for (const [checkIndex, id] of DESKTOP_READINESS_CHECK_IDS.entries()) {
      expect(observedStatuses.slice(0, firstPassedIndexes[checkIndex]))
        .toContainEqual(expect.arrayContaining([`${id}:checking`]));
    }
  });

  it("fails closed at the first unhealthy component and leaves later checks pending", async () => {
    const unhealthyRuntime: RuntimeStatusReport = {
      ...readyRuntime,
      ready: false,
      components: readyRuntime.components.map((component) =>
        component.id === "local-backend"
          ? { ...component, status: "unhealthy", detail: "health check failed" }
          : component,
      ),
    };
    const invoke = vi.fn(async (command: string) => {
      if (command === "probe_runtime_status") return unhealthyRuntime;
      if (command === "probe_system_prerequisites") return prerequisites;
      throw new Error(`Unexpected command: ${command}`);
    });
    window.__TAURI__ = { core: { invoke } };

    await ensureOverallDesktopReadiness({ autoStart: true });
    const progress = getDesktopReadinessProgress();

    expect(progress.percent).toBe(57);
    expect(progress.running).toBe(false);
    expect(progress.checks.find((check) => check.id === "backend"))
      .toEqual(expect.objectContaining({
        status: "failed",
        detail: "health check failed",
      }));
    expect(progress.checks.find((check) => check.id === "px4")?.status).toBe("pending");
    expect(progress.checks.find((check) => check.id === "gazebo")?.status).toBe("pending");
  });

  it("suppresses automatic retry after failure until readiness is restored", async () => {
    let runtime: RuntimeStatusReport = stoppedRuntime;
    let startCount = 0;
    const invoke = vi.fn(async (command: string) => {
      if (command === "probe_system_prerequisites") return prerequisites;
      if (command === "probe_runtime_status") return runtime;
      if (command === "start_runtime") {
        startCount += 1;
        if (startCount === 1) throw new Error("health check failed");
        return readyRuntime;
      }
      throw new Error(`Unexpected command: ${command}`);
    });
    window.__TAURI__ = { core: { invoke } };

    await expect(ensureOverallDesktopReadiness({ autoStart: true }))
      .rejects.toThrow("health check failed");
    const suppressed = await ensureOverallDesktopReadiness({ autoStart: true });
    expect(suppressed.ready).toBe(false);
    expect(suppressed.autoStartFailed).toBe(true);
    expect(invoke.mock.calls.filter(([command]) => command === "start_runtime"))
      .toHaveLength(1);

    runtime = readyRuntime;
    clearRuntimeAutoStartFailure();
    const restored = await ensureOverallDesktopReadiness({ autoStart: true });
    expect(restored.ready).toBe(true);
    expect(restored.autoStartFailed).toBe(false);
  });
});
