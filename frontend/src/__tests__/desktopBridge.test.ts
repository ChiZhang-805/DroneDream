import { describe, expect, it, vi } from "vitest";

import {
  autoStartInstallerRuntime,
  cancelRuntimeInstall,
  DesktopCommandContractError,
  DesktopRuntimeUnavailableError,
  discardInstallerRuntimeIntent,
  getInstallerRuntimeIntent,
  getRuntimeInstallProgress,
  getRuntimeInstallPlan,
  isDesktopRuntime,
  probeRuntimeStatus,
  probeSystemPrerequisites,
  repairRuntime,
  startRuntime,
  startRuntimeInstall,
} from "../desktop/bridge";

const prerequisiteReport = {
  platform: "windows",
  supported: true,
  windows: null,
  wsl: { executableAvailable: true, distributions: [] },
  memory: null,
  disks: [],
  gpus: [],
  probeErrors: [],
};

const runtimeReport = {
  runtimeName: "DroneDreamRuntime",
  installed: false,
  running: false,
  ready: false,
  version: null,
  dataRoot: null,
  components: [
    "wsl-runtime",
    "host-ownership",
    "runtime-manifest",
    "local-backend",
    "px4",
    "gazebo",
  ].map((id) => ({
    id,
    label: id,
    status: "missing",
    required: true,
    version: null,
    detail: null,
  })),
  diagnostics: [],
};

const installPlan = {
  runtimeName: "DroneDreamRuntime",
  targetRoot: "E:\\DroneDream",
  estimatedDownloadBytes: 1,
  estimatedInstalledBytes: 2,
  requiresAdministrator: false,
  requiresRestart: false,
  canInstall: true,
  blockers: [],
  steps: [
    {
      id: "preflight",
      title: "Validate prerequisites",
      description: "Check the computer.",
      requiresAdministrator: false,
      destructive: false,
      estimatedBytes: null,
    },
    {
      id: "enable-wsl",
      title: "Verify WSL2",
      description: "Check WSL2.",
      requiresAdministrator: false,
      destructive: false,
      estimatedBytes: null,
    },
    {
      id: "download",
      title: "Download runtime",
      description: "Download the runtime.",
      requiresAdministrator: false,
      destructive: false,
      estimatedBytes: 1,
    },
    {
      id: "import",
      title: "Import runtime",
      description: "Import the runtime.",
      requiresAdministrator: false,
      destructive: false,
      estimatedBytes: 2,
    },
    {
      id: "smoke-test",
      title: "Verify runtime",
      description: "Run smoke tests.",
      requiresAdministrator: false,
      destructive: false,
      estimatedBytes: null,
    },
  ],
};

const installSnapshot = {
  operationId: "install-1",
  phase: "downloading",
  bytesDownloaded: 1024,
  bytesTotal: 4096,
  currentPart: 1,
  totalParts: 4,
  message: "Downloading part 1 of 4",
  error: null,
  resumable: true,
  requiresRestart: false,
  targetRoot: "E:\\DroneDream",
  installedVersion: null,
  updatedAt: "2026-07-12T10:00:00Z",
};

describe("desktop bridge", () => {
  it("stays unavailable in a normal browser", async () => {
    expect(isDesktopRuntime()).toBe(false);
    await expect(probeSystemPrerequisites()).rejects.toBeInstanceOf(
      DesktopRuntimeUnavailableError,
    );
  });

  it("routes typed calls through the Tauri global API", async () => {
    const invoke = vi.fn(async (command: string) => {
      if (command === "probe_system_prerequisites") return prerequisiteReport;
      if (command === "probe_runtime_status") return runtimeReport;
      return installPlan;
    });
    window.__TAURI__ = { core: { invoke } };

    expect(isDesktopRuntime()).toBe(true);
    await probeSystemPrerequisites();
    await probeRuntimeStatus();
    await getRuntimeInstallPlan("E:\\DroneDream");

    expect(invoke.mock.calls.map(([command]) => command)).toEqual([
      "probe_system_prerequisites",
      "probe_runtime_status",
      "get_runtime_install_plan",
    ]);
    expect(invoke).toHaveBeenLastCalledWith(
      "get_runtime_install_plan",
      { targetRoot: "E:\\DroneDream" },
    );
  });

  it("rejects malformed native responses at the trust boundary", async () => {
    window.__TAURI__ = {
      core: {
        invoke: vi.fn(async () => ({ ...runtimeReport, components: undefined })),
      },
    };

    await expect(probeRuntimeStatus()).rejects.toMatchObject({
      name: "DesktopCommandContractError",
      command: "probe_runtime_status",
    });
    await expect(probeRuntimeStatus()).rejects.toBeInstanceOf(
      DesktopCommandContractError,
    );
  });

  it("rejects unknown component states instead of crashing the setup page", async () => {
    window.__TAURI__ = {
      core: {
        invoke: vi.fn(async () => ({
          ...runtimeReport,
          components: [
            ...runtimeReport.components.slice(0, -1),
            {
              id: "gazebo",
              label: "Gazebo simulator",
              status: "starting",
              required: true,
              version: null,
              detail: null,
            },
          ],
        })),
      },
    };

    await expect(probeRuntimeStatus()).rejects.toThrow(/unknown value/i);
  });

  it("accepts the complete uninstalled runtime contract including host ownership", async () => {
    window.__TAURI__ = {
      core: { invoke: vi.fn(async () => runtimeReport) },
    };

    await expect(probeRuntimeStatus()).resolves.toMatchObject({
      installed: false,
      running: false,
      ready: false,
      components: expect.arrayContaining([
        expect.objectContaining({
          id: "host-ownership",
          status: "missing",
          required: true,
        }),
      ]),
    });
  });

  it("rejects a runtime with the wrong identity or missing known required components", async () => {
    const invoke = vi.fn();
    window.__TAURI__ = { core: { invoke } };

    invoke.mockResolvedValueOnce({
      ...runtimeReport,
      runtimeName: "PersonalUbuntu",
    });
    await expect(probeRuntimeStatus()).rejects.toThrow(/runtimeName must equal/i);

    invoke.mockResolvedValueOnce({
      ...runtimeReport,
      components: runtimeReport.components.slice(0, -1),
    });
    await expect(probeRuntimeStatus()).rejects.toThrow(/must mark all known/i);

    invoke.mockResolvedValueOnce({
      ...runtimeReport,
      components: runtimeReport.components.map((component) =>
        component.id === "host-ownership"
          ? { ...component, required: false }
          : component,
      ),
    });
    await expect(probeRuntimeStatus()).rejects.toThrow(/must mark all known/i);
  });

  it("accepts additional required runtime components for forward compatibility", async () => {
    window.__TAURI__ = {
      core: {
        invoke: vi.fn(async () => ({
          ...runtimeReport,
          components: [
            ...runtimeReport.components,
            {
              id: "future-safety-gate",
              label: "Future safety gate",
              status: "missing",
              required: true,
              version: null,
              detail: null,
            },
          ],
        })),
      },
    };

    await expect(probeRuntimeStatus()).resolves.toMatchObject({
      installed: false,
      ready: false,
    });
  });

  it("rejects contradictory installed, running, ready, and data-root states", async () => {
    const invoke = vi.fn();
    window.__TAURI__ = { core: { invoke } };

    invoke.mockResolvedValueOnce({
      ...runtimeReport,
      running: true,
    });
    await expect(probeRuntimeStatus()).rejects.toThrow(/running cannot be true/i);

    invoke.mockResolvedValueOnce({
      ...runtimeReport,
      installed: true,
    });
    await expect(probeRuntimeStatus()).rejects.toThrow(/dataRoot must be non-empty/i);

    invoke.mockResolvedValueOnce({
      ...runtimeReport,
      installed: true,
      running: true,
      ready: true,
      dataRoot: "E:\\DroneDream",
      version: "0.1.0",
    });
    await expect(probeRuntimeStatus()).rejects.toThrow(/required component .* is missing/i);
  });

  it("rejects an install plan for a different or non-canonical target", async () => {
    const invoke = vi.fn();
    window.__TAURI__ = { core: { invoke } };

    invoke.mockResolvedValueOnce(installPlan);
    await expect(getRuntimeInstallPlan("C:\\DroneDream")).rejects.toThrow(
      /must match the requested target C:\\DroneDream/i,
    );

    invoke.mockResolvedValueOnce({ ...installPlan, targetRoot: "e:\\DroneDream" });
    await expect(getRuntimeInstallPlan("E:\\DroneDream")).rejects.toThrow(
      /must be a canonical path/i,
    );

    invoke.mockClear();
    await expect(getRuntimeInstallPlan("E:\\Users")).rejects.toThrow(
      /must be a drive root/i,
    );
    expect(invoke).not.toHaveBeenCalled();
  });

  it("requires the complete ordered install workflow and safe display fields", async () => {
    const invoke = vi.fn();
    window.__TAURI__ = { core: { invoke } };

    invoke.mockResolvedValueOnce({ ...installPlan, steps: installPlan.steps.slice(0, -1) });
    await expect(getRuntimeInstallPlan("E:\\DroneDream")).rejects.toThrow(
      /must contain preflight, enable-wsl, download, import, smoke-test/i,
    );

    invoke.mockResolvedValueOnce({
      ...installPlan,
      steps: installPlan.steps.map((step, index) =>
        index === 0 ? { ...step, title: "" } : step,
      ),
    });
    await expect(getRuntimeInstallPlan("E:\\DroneDream")).rejects.toThrow(
      /title must not be empty/i,
    );
  });

  it("requires blocker and administrator summaries to agree with the steps", async () => {
    const invoke = vi.fn();
    window.__TAURI__ = { core: { invoke } };

    invoke.mockResolvedValueOnce({
      ...installPlan,
      canInstall: true,
      blockers: ["Disk is unavailable."],
    });
    await expect(getRuntimeInstallPlan("E:\\DroneDream")).rejects.toThrow(
      /canInstall must be true exactly when plan.blockers is empty/i,
    );

    invoke.mockResolvedValueOnce({ ...installPlan, requiresAdministrator: true });
    await expect(getRuntimeInstallPlan("E:\\DroneDream")).rejects.toThrow(
      /must match the enable-wsl step/i,
    );

    invoke.mockResolvedValueOnce({
      ...installPlan,
      steps: installPlan.steps.map((step) =>
        step.id === "download" ? { ...step, requiresAdministrator: true } : step,
      ),
    });
    await expect(getRuntimeInstallPlan("E:\\DroneDream")).rejects.toThrow(
      /step download cannot require administrator approval/i,
    );
  });

  it("routes installer lifecycle commands with the exact Tauri request wrapper", async () => {
    const invoke = vi.fn(async (command: string) => {
      if (command === "start_runtime" || command === "repair_runtime") {
        return runtimeReport;
      }
      return installSnapshot;
    });
    window.__TAURI__ = { core: { invoke } };

    await startRuntimeInstall({
      targetRoot: "e:\\DroneDream\\",
      releaseManifestUrl: "https://example.com/releases/runtime.json",
    });
    await getRuntimeInstallProgress();
    await cancelRuntimeInstall();
    await startRuntime();
    await repairRuntime();

    expect(invoke).toHaveBeenNthCalledWith(1, "start_runtime_install", {
      request: {
        targetRoot: "E:\\DroneDream",
        releaseManifestUrl: "https://example.com/releases/runtime.json",
      },
    });
    expect(invoke).toHaveBeenNthCalledWith(2, "get_runtime_install_progress", undefined);
    expect(invoke).toHaveBeenNthCalledWith(3, "cancel_runtime_install", undefined);
    expect(invoke).toHaveBeenNthCalledWith(4, "start_runtime", undefined);
    expect(invoke).toHaveBeenNthCalledWith(5, "repair_runtime", undefined);
  });

  it("strictly validates and routes the atomic installer handoff", async () => {
    const invoke = vi.fn();
    window.__TAURI__ = { core: { invoke } };

    invoke.mockResolvedValueOnce({
      disposition: "started",
      mode: "custom",
      targetRoot: "E:\\DroneDream",
      snapshot: installSnapshot,
      message: "The confirmed installation started.",
    });
    await expect(autoStartInstallerRuntime()).resolves.toMatchObject({
      disposition: "started",
      mode: "custom",
      targetRoot: "E:\\DroneDream",
      snapshot: { operationId: "install-1" },
    });
    expect(invoke).toHaveBeenLastCalledWith(
      "auto_start_installer_runtime",
      undefined,
    );

    invoke.mockResolvedValueOnce({
      disposition: "desktopOnly",
      mode: "install-app-only",
      targetRoot: null,
      snapshot: null,
      message: null,
    });
    await expect(autoStartInstallerRuntime()).resolves.toMatchObject({
      disposition: "desktopOnly",
      mode: "install-app-only",
    });
  });

  it("strictly validates the read-only installer intent peek", async () => {
    const invoke = vi.fn();
    window.__TAURI__ = { core: { invoke } };

    invoke.mockResolvedValueOnce({
      status: "ready",
      mode: "install-all",
      targetRoot: "E:\\DroneDream",
      message: "Install everything was confirmed.",
    });
    await expect(getInstallerRuntimeIntent()).resolves.toEqual({
      status: "ready",
      mode: "install-all",
      targetRoot: "E:\\DroneDream",
      message: "Install everything was confirmed.",
    });
    expect(invoke).toHaveBeenLastCalledWith(
      "get_installer_runtime_intent",
      undefined,
    );

    invoke.mockResolvedValueOnce({
      status: "desktopOnly",
      mode: "install-app-only",
      targetRoot: null,
      message: null,
    });
    await expect(getInstallerRuntimeIntent()).resolves.toMatchObject({
      status: "desktopOnly",
      mode: "install-app-only",
    });
  });

  it("strictly validates and routes pending installer-intent discard", async () => {
    const invoke = vi.fn();
    window.__TAURI__ = { core: { invoke } };

    invoke.mockResolvedValueOnce({
      discarded: true,
      message: "The pending installer choice was cleared.",
    });
    await expect(discardInstallerRuntimeIntent()).resolves.toEqual({
      discarded: true,
      message: "The pending installer choice was cleared.",
    });
    expect(invoke).toHaveBeenLastCalledWith(
      "discard_installer_runtime_intent",
      undefined,
    );

    invoke.mockResolvedValueOnce({ discarded: "yes", message: null });
    await expect(discardInstallerRuntimeIntent()).rejects.toThrow(
      /discardResult.discarded must be a boolean/i,
    );
  });

  it("rejects contradictory read-only installer intents", async () => {
    const invoke = vi.fn();
    window.__TAURI__ = { core: { invoke } };

    invoke.mockResolvedValueOnce({
      status: "ready",
      mode: "install-app-only",
      targetRoot: "E:\\DroneDream",
      message: null,
    });
    await expect(getInstallerRuntimeIntent()).rejects.toThrow(
      /requires install-all or custom mode/i,
    );

    invoke.mockResolvedValueOnce({
      status: "none",
      mode: null,
      targetRoot: "E:\\DroneDream",
      message: null,
    });
    await expect(getInstallerRuntimeIntent()).rejects.toThrow(
      /cannot return targetRoot/i,
    );
  });

  it("rejects contradictory atomic installer handoff responses", async () => {
    const invoke = vi.fn();
    window.__TAURI__ = { core: { invoke } };

    invoke.mockResolvedValueOnce({
      disposition: "started",
      mode: "install-app-only",
      targetRoot: "E:\\DroneDream",
      snapshot: installSnapshot,
      message: null,
    });
    await expect(autoStartInstallerRuntime()).rejects.toThrow(
      /requires install-all or custom mode/i,
    );

    invoke.mockResolvedValueOnce({
      disposition: "resumed",
      mode: "install-all",
      targetRoot: "C:\\DroneDream",
      snapshot: installSnapshot,
      message: null,
    });
    await expect(autoStartInstallerRuntime()).rejects.toThrow(
      /targetRoot must match/i,
    );

    invoke.mockResolvedValueOnce({
      disposition: "none",
      mode: null,
      targetRoot: null,
      snapshot: installSnapshot,
      message: null,
    });
    await expect(autoStartInstallerRuntime()).rejects.toThrow(
      /cannot return targetRoot or snapshot/i,
    );
  });

  it("fails closed for unsafe release URLs and contradictory installer snapshots", async () => {
    const invoke = vi.fn();
    window.__TAURI__ = { core: { invoke } };

    expect(() => startRuntimeInstall({
      targetRoot: "E:\\DroneDream",
      releaseManifestUrl: "http://example.com/runtime.json",
    })).toThrow(/absolute HTTPS URL/i);
    expect(invoke).not.toHaveBeenCalled();

    invoke.mockResolvedValueOnce({
      ...installSnapshot,
      bytesDownloaded: 4097,
    });
    await expect(getRuntimeInstallProgress()).rejects.toThrow(/cannot exceed bytesTotal/i);

    invoke.mockResolvedValueOnce({
      ...installSnapshot,
      phase: "failed",
      error: null,
    });
    await expect(getRuntimeInstallProgress()).rejects.toThrow(/requires an error/i);

    invoke.mockResolvedValueOnce({
      ...installSnapshot,
      phase: "teleporting",
    });
    await expect(getRuntimeInstallProgress()).rejects.toThrow(/unknown value/i);
  });
});
