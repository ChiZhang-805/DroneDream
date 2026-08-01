import { describe, expect, it, vi } from "vitest";

import {
  autoStartInstallerRuntime,
  beginBrowserAuth,
  cancelBrowserAuth,
  cancelRuntimeInstall,
  desktopApiRequest,
  desktopDownloadArtifact,
  DesktopCommandContractError,
  DesktopRuntimeUnavailableError,
  discardInstallerRuntimeIntent,
  ensureAppUpdateIdle,
  getEnginePackStatus,
  getInstallerRuntimeIntent,
  getRuntimeInstallProgress,
  getRuntimeInstallPlan,
  isDesktopRuntime,
  probeRuntimeStatus,
  probeSystemPrerequisites,
  repairRuntime,
  installEmbeddedEnginePack,
  startRuntime,
  startRuntimeInstall,
  stopRuntimeForExit,
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

  it("validates the browser-auth command without exposing returned tokens", async () => {
    const session = {
      accessToken: "header.payload.signature",
      refreshToken: "refresh-token-value",
    };
    const invoke = vi.fn(async (command: string) => {
      if (command === "begin_browser_auth") return session;
      if (command === "cancel_browser_auth") return true;
      throw new Error(`Unexpected command: ${command}`);
    });
    window.__TAURI__ = { core: { invoke } };

    await expect(beginBrowserAuth({
      locale: "zh-CN",
      supabaseUrl: "https://yggabfynndpzymlqvnim.supabase.co",
      publishableKey: "public-test-key-for-browser-auth",
    })).resolves.toEqual(session);
    await expect(cancelBrowserAuth()).resolves.toBe(true);
    expect(invoke).toHaveBeenNthCalledWith(1, "begin_browser_auth", {
      request: {
        locale: "zh-CN",
        supabaseUrl: "https://yggabfynndpzymlqvnim.supabase.co",
        publishableKey: "public-test-key-for-browser-auth",
      },
    });
    expect(invoke).toHaveBeenNthCalledWith(2, "cancel_browser_auth", undefined);
  });

  it("validates Engine Pack identities and routes the idle preflight", async () => {
    const status = {
      supported: true,
      updateRequired: true,
      embeddedPackId: `sha256:${"1".repeat(64)}`,
      embeddedSourceCommit: "2".repeat(40),
      installedPackId: `sha256:${"3".repeat(64)}`,
      installedSourceCommit: "4".repeat(40),
      message: null,
    };
    const invoke = vi.fn(async (command: string) => {
      if (command === "ensure_app_update_idle") return null;
      if (command === "get_engine_pack_status") return status;
      if (command === "install_embedded_engine_pack") {
        return { ...status, updateRequired: false };
      }
      throw new Error(`Unexpected command: ${command}`);
    });
    window.__TAURI__ = { core: { invoke } };

    await expect(ensureAppUpdateIdle()).resolves.toBeUndefined();
    await expect(getEnginePackStatus()).resolves.toEqual(status);
    await expect(installEmbeddedEnginePack()).resolves.toMatchObject({
      updateRequired: false,
    });
    expect(invoke.mock.calls.map(([command]) => command)).toEqual([
      "ensure_app_update_idle",
      "get_engine_pack_status",
      "install_embedded_engine_pack",
    ]);

    invoke.mockResolvedValueOnce({
      ...status,
      embeddedPackId: "sha256:not-a-digest",
    });
    await expect(getEnginePackStatus()).rejects.toMatchObject({
      name: "DesktopCommandContractError",
      command: "get_engine_pack_status",
    });
  });

  it("rejects malformed browser-auth tokens at the native boundary", async () => {
    const invoke = vi.fn().mockResolvedValue({
      accessToken: "valid-token",
      refreshToken: "secret refresh token",
    });
    window.__TAURI__ = { core: { invoke } };

    const error = await beginBrowserAuth({
      locale: "en",
      supabaseUrl: "https://yggabfynndpzymlqvnim.supabase.co",
      publishableKey: "public-test-key-for-browser-auth",
    }).catch((caught: unknown) => caught);
    expect(error).toBeInstanceOf(DesktopCommandContractError);
    expect(String(error)).not.toContain("secret refresh token");
  });

  it("validates the bounded native API response contract", async () => {
    const invoke = vi.fn().mockResolvedValue({
      status: 200,
      contentType: "application/json",
      bodyBase64: btoa('{"success":true}'),
    });
    window.__TAURI__ = { core: { invoke } };

    await expect(desktopApiRequest({
      method: "GET",
      path: "/api/v1/session",
      accessToken: "account-token",
    })).resolves.toMatchObject({ status: 200 });
    expect(invoke).toHaveBeenCalledWith("desktop_api_request", {
      request: {
        method: "GET",
        path: "/api/v1/session",
        accessToken: "account-token",
      },
    });

    invoke.mockResolvedValueOnce({
      status: 200,
      contentType: "application/json",
      bodyBase64: "not base64",
    });
    await expect(desktopApiRequest({
      method: "GET",
      path: "/api/v1/session",
    })).rejects.toMatchObject({
      name: "DesktopCommandContractError",
      command: "desktop_api_request",
    });
  });

  it("validates the native streaming-download response contract", async () => {
    const invoke = vi.fn().mockResolvedValue({
      savedPath: "C:\\Users\\pilot\\Downloads\\telemetry.ulg",
      bytes: 70 * 1024 * 1024,
    });
    window.__TAURI__ = { core: { invoke } };

    await expect(desktopDownloadArtifact({
      artifactId: "art_large_1",
      filename: "telemetry.ulg",
      accessToken: "account-token",
    })).resolves.toEqual({
      savedPath: "C:\\Users\\pilot\\Downloads\\telemetry.ulg",
      bytes: 70 * 1024 * 1024,
    });
    expect(invoke).toHaveBeenCalledWith("desktop_download_artifact", {
      request: {
        artifactId: "art_large_1",
        filename: "telemetry.ulg",
        accessToken: "account-token",
      },
    });

    invoke.mockResolvedValueOnce({ savedPath: "", bytes: -1 });
    await expect(desktopDownloadArtifact({
      artifactId: "art_large_1",
      filename: "telemetry.ulg",
    })).rejects.toMatchObject({
      name: "DesktopCommandContractError",
      command: "desktop_download_artifact",
    });
  });

  it("accepts only the native unit response for runtime exit termination", async () => {
    const invoke = vi.fn()
      .mockResolvedValueOnce(null)
      .mockResolvedValueOnce({ stopped: true });
    window.__TAURI__ = { core: { invoke } };

    await expect(stopRuntimeForExit()).resolves.toBeUndefined();
    await expect(stopRuntimeForExit()).rejects.toMatchObject({
      name: "DesktopCommandContractError",
      command: "stop_runtime_for_exit",
    });
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
      phase: "completed",
      resumable: false,
      installedVersion: null,
    });
    await expect(getRuntimeInstallProgress()).rejects.toThrow(/requires installedVersion/i);

    invoke.mockResolvedValueOnce({
      ...installSnapshot,
      phase: "waitingForRestart",
      resumable: false,
      requiresRestart: true,
    });
    await expect(getRuntimeInstallProgress()).rejects.toThrow(/must be resumable/i);

    invoke.mockResolvedValueOnce({
      ...installSnapshot,
      phase: "failed",
      resumable: false,
      error: {
        code: "network_error",
        message: "Retry later",
        retryable: true,
        diagnosticsPath: null,
      },
    });
    await expect(getRuntimeInstallProgress()).rejects.toThrow(/must match error.retryable/i);

    invoke.mockResolvedValueOnce({
      ...installSnapshot,
      phase: "teleporting",
    });
    await expect(getRuntimeInstallProgress()).rejects.toThrow(/unknown value/i);
  });

  it("normalizes optional diagnostic paths and rejects unsafe native paths", async () => {
    const invoke = vi.fn();
    window.__TAURI__ = { core: { invoke } };
    const failure = {
      ...installSnapshot,
      phase: "failed",
      error: {
        code: "runtime_service_unhealthy",
        message: "The runtime API did not become healthy.",
        retryable: true,
      },
    };

    invoke.mockResolvedValueOnce(failure);
    await expect(getRuntimeInstallProgress()).resolves.toMatchObject({
      error: { diagnosticsPath: null },
    });

    invoke.mockResolvedValueOnce({
      ...failure,
      error: {
        ...failure.error,
        diagnosticsPath: "c:\\Users\\student\\AppData\\Local\\DroneDream\\diagnostics\\install.log",
      },
    });
    await expect(getRuntimeInstallProgress()).resolves.toMatchObject({
      error: {
        diagnosticsPath:
          "C:\\Users\\student\\AppData\\Local\\DroneDream\\diagnostics\\install.log",
      },
    });

    invoke.mockResolvedValueOnce({
      ...failure,
      error: { ...failure.error, diagnosticsPath: "diagnostics\\install.log" },
    });
    await expect(getRuntimeInstallProgress()).rejects.toThrow(
      /absolute local Windows path/i,
    );

    invoke.mockResolvedValueOnce({
      ...failure,
      error: { ...failure.error, diagnosticsPath: "C:\\Logs\\..\\secrets.txt" },
    });
    await expect(getRuntimeInstallProgress()).rejects.toThrow(/unsafe Windows path segment/i);

    for (const diagnosticsPath of [
      "C:\\Logs/../secrets.txt",
      "C:\\Logs\\CON\\install.log",
      "C:\\Logs\\nul.txt",
      "C:\\Logs\\line\u2028break.log",
      "C:\\Logs\\hidden\u202Etxt.log",
    ]) {
      invoke.mockResolvedValueOnce({
        ...failure,
        error: { ...failure.error, diagnosticsPath },
      });
      await expect(getRuntimeInstallProgress()).rejects.toThrow(
        /absolute local Windows path|unsafe Windows path segment/i,
      );
    }
  });

  it("single-lines native multiline stderr without losing its error identity", async () => {
    const invoke = vi.fn();
    window.__TAURI__ = { core: { invoke } };
    const diagnosticsPath =
      "E:\\DroneDream.download-cache\\diagnostics\\runtime-health-test.log";
    invoke.mockResolvedValueOnce({
      ...installSnapshot,
      phase: "failed",
      error: {
        code: "runtime_service_unhealthy",
        message:
          "curl: (7) connection failed\r\n\tretrying WSL\0API\x7f unavailable",
        retryable: true,
        diagnosticsPath,
      },
    });

    const snapshot = await getRuntimeInstallProgress();

    expect(snapshot.error).toEqual({
      code: "runtime_service_unhealthy",
      message: "curl: (7) connection failed retrying WSL API unavailable",
      retryable: true,
      diagnosticsPath,
    });
    expect([...snapshot.error!.message].every((character) => {
      const codePoint = character.codePointAt(0) ?? 0;
      return codePoint > 0x1f && codePoint !== 0x7f;
    })).toBe(true);
  });

  it("bounds long Unicode native errors by JavaScript UTF-16 length", async () => {
    const invoke = vi.fn();
    window.__TAURI__ = { core: { invoke } };
    const diagnosticsPath =
      "E:\\DroneDream.download-cache\\diagnostics\\runtime-health-unicode.log";
    invoke.mockResolvedValueOnce({
      ...installSnapshot,
      phase: "failed",
      error: {
        code: "runtime_health_unknown",
        message: `error: ${"🚁".repeat(3000)} unreachable suffix`,
        retryable: true,
        diagnosticsPath,
      },
    });

    const snapshot = await getRuntimeInstallProgress();
    const error = snapshot.error;

    expect(error?.code).toBe("runtime_health_unknown");
    expect(error?.diagnosticsPath).toBe(diagnosticsPath);
    expect(error?.message).toHaveLength(4096);
    expect(error?.message.endsWith("…")).toBe(true);
    expect(error?.message).not.toContain("unreachable suffix");
    const finalContentUnit = error?.message.charCodeAt(error.message.length - 2) ?? 0;
    expect(finalContentUnit < 0xd800 || finalContentUnit > 0xdbff).toBe(true);
  });

  it("removes Unicode bidi and format controls from native errors", async () => {
    const invoke = vi.fn();
    window.__TAURI__ = { core: { invoke } };
    invoke.mockResolvedValueOnce({
      ...installSnapshot,
      phase: "failed",
      error: {
        code: "runtime_health_unknown",
        message: "safe\u202Egnp.exe\u2066 text\u200Bafter",
        retryable: true,
        diagnosticsPath: null,
      },
    });

    const snapshot = await getRuntimeInstallProgress();

    expect(snapshot.error?.message).toBe("safe gnp.exe text after");
    expect(snapshot.error?.message).not.toMatch(/[\u202E\u2066\u200B]/u);
  });
});
