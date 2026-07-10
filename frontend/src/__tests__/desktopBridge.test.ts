import { describe, expect, it, vi } from "vitest";

import {
  DesktopCommandContractError,
  DesktopRuntimeUnavailableError,
  getRuntimeInstallPlan,
  isDesktopRuntime,
  probeRuntimeStatus,
  probeSystemPrerequisites,
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
  steps: [],
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

  it("rejects a runtime with the wrong identity or incomplete required components", async () => {
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
    await expect(probeRuntimeStatus()).rejects.toThrow(/must mark exactly/i);
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
});
