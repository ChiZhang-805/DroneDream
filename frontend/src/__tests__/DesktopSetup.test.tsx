import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { StrictMode } from "react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import type {
  InstallerRuntimeAutoStartResult,
  InstallerRuntimeDiscardResult,
  InstallerRuntimeIntent,
  RuntimeInstallPlan,
  RuntimeInstallSnapshot,
  RuntimeStatusReport,
  SystemPrerequisiteReport,
} from "../desktop/bridge";
import { formatBytes } from "../desktop/format";
import { I18nProvider } from "../i18n/I18nProvider";
import { DesktopSetup } from "../pages/DesktopSetup";

const prerequisites: SystemPrerequisiteReport = {
  platform: "windows",
  supported: true,
  windows: {
    caption: "Windows 11 Pro",
    version: "10.0.26100",
    buildNumber: "26100",
    architecture: "64-bit",
  },
  wsl: {
    executableAvailable: true,
    distributions: [{ name: "Ubuntu-22.04", version: 2, isDefault: true }],
  },
  memory: { totalBytes: 32 * 1024 ** 3, availableBytes: 20 * 1024 ** 3 },
  disks: [
    {
      drive: "C:",
      totalBytes: 1024 * 1024 ** 3,
      freeBytes: 390 * 1024 ** 3,
      isSystemDrive: true,
    },
    {
      drive: "E:",
      totalBytes: 2 * 1024 ** 4,
      freeBytes: 80 * 1024 ** 3,
      isSystemDrive: false,
    },
  ],
  gpus: [
    {
      name: "NVIDIA GeForce RTX 4060 Laptop GPU",
      driverVersion: "32.0.15.9000",
      adapterRamBytes: 8 * 1024 ** 3,
    },
  ],
  probeErrors: [],
};

const runtime: RuntimeStatusReport = {
  runtimeName: "DroneDreamRuntime",
  installed: true,
  running: true,
  ready: true,
  version: "2026.07",
  dataRoot: "E:\\DroneDream\\Runtime",
  components: [
    {
      id: "wsl-runtime",
      label: "Dedicated WSL2 runtime",
      status: "ready",
      required: true,
      version: null,
      detail: "E:\\DroneDream\\Runtime",
    },
    {
      id: "host-ownership",
      label: "Host ownership receipt",
      status: "ready",
      required: true,
      version: "2026.07",
      detail: "E:\\DroneDream\\.dronedream-runtime-root.json",
    },
    {
      id: "runtime-manifest",
      label: "Runtime manifest",
      status: "ready",
      required: true,
      version: "2026.07",
      detail: "/opt/dronedream/runtime-manifest.json",
    },
    {
      id: "local-backend",
      label: "Local DroneDream API",
      status: "ready",
      required: true,
      version: null,
      detail: "http://127.0.0.1:8000/health",
    },
    {
      id: "px4",
      label: "PX4 SITL",
      status: "ready",
      required: true,
      version: "v1.16",
      detail: "Pinned and healthy",
    },
    {
      id: "gazebo",
      label: "Gazebo simulator",
      status: "ready",
      required: true,
      version: "gz-harmonic",
      detail: null,
    },
  ],
  diagnostics: [],
};

const missingRuntime: RuntimeStatusReport = {
  runtimeName: "DroneDreamRuntime",
  installed: false,
  running: false,
  ready: false,
  version: null,
  dataRoot: null,
  components: [
    {
      id: "wsl-runtime",
      label: "Dedicated WSL2 runtime",
      status: "missing",
      required: true,
      version: null,
      detail: null,
    },
    {
      id: "host-ownership",
      label: "Host ownership receipt",
      status: "missing",
      required: true,
      version: null,
      detail: null,
    },
    {
      id: "runtime-manifest",
      label: "Runtime manifest",
      status: "missing",
      required: true,
      version: null,
      detail: null,
    },
    {
      id: "local-backend",
      label: "Local DroneDream API",
      status: "missing",
      required: true,
      version: null,
      detail: null,
    },
    {
      id: "px4",
      label: "PX4 SITL",
      status: "missing",
      required: true,
      version: null,
      detail: null,
    },
    {
      id: "gazebo",
      label: "Gazebo simulator",
      status: "missing",
      required: true,
      version: null,
      detail: null,
    },
  ],
  diagnostics: [],
};

const plan: RuntimeInstallPlan = {
  runtimeName: "DroneDreamRuntime",
  targetRoot: "E:\\DroneDream",
  estimatedDownloadBytes: 8 * 1024 ** 3,
  estimatedInstalledBytes: 24 * 1024 ** 3,
  requiresAdministrator: true,
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
      title: "Enable WSL2",
      description: "Prepare WSL2.",
      requiresAdministrator: true,
      destructive: false,
      estimatedBytes: null,
    },
    {
      id: "download",
      title: "Download runtime",
      description: "Download the runtime image.",
      requiresAdministrator: false,
      destructive: false,
      estimatedBytes: 8 * 1024 ** 3,
    },
    {
      id: "import",
      title: "Import runtime",
      description: "Import the dedicated distribution.",
      requiresAdministrator: false,
      destructive: false,
      estimatedBytes: 24 * 1024 ** 3,
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

const idleInstallSnapshot: RuntimeInstallSnapshot = {
  operationId: null,
  phase: "idle",
  bytesDownloaded: 0,
  bytesTotal: null,
  currentPart: null,
  totalParts: null,
  message: null,
  error: null,
  resumable: false,
  requiresRestart: false,
  targetRoot: null,
  installedVersion: null,
  updatedAt: null,
};

const noInstallerRuntimeIntent: InstallerRuntimeIntent = {
  status: "none",
  mode: null,
  targetRoot: null,
  message: null,
};

const noInstallerAutoStart: InstallerRuntimeAutoStartResult = {
  disposition: "none",
  mode: null,
  targetRoot: null,
  snapshot: null,
  message: null,
};

const discardedInstallerIntent: InstallerRuntimeDiscardResult = {
  discarded: true,
  message: "The pending installer choice was cleared.",
};

function installSnapshot(
  overrides: Partial<RuntimeInstallSnapshot> = {},
): RuntimeInstallSnapshot {
  return {
    operationId: "install-1",
    phase: "downloading",
    bytesDownloaded: 1024 ** 3,
    bytesTotal: 8 * 1024 ** 3,
    currentPart: 1,
    totalParts: 8,
    message: "Downloading runtime part 1 of 8",
    error: null,
    resumable: true,
    requiresRestart: false,
    targetRoot: "E:\\DroneDream",
    installedVersion: null,
    updatedAt: "2026-07-12T10:00:00Z",
    ...overrides,
  };
}

function renderPage(
  locale: "en" | "zh-CN" = "en",
  installerIntent: InstallerRuntimeIntent = noInstallerRuntimeIntent,
  installerResult: unknown = noInstallerAutoStart,
  strict = false,
  discardResult: unknown = discardedInstallerIntent,
  initialEntry = "/",
) {
  window.localStorage.setItem("drone-dream:locale", locale);
  const originalTauri = window.__TAURI__;
  const originalInvoke = window.__TAURI__?.core?.invoke;
  const installerIntentInvoke = vi.fn(async (
    command: string,
    args?: Record<string, unknown>,
  ) => {
    void command;
    void args;
    return installerIntent;
  });
  const installerInvoke = vi.fn(async (
    command: string,
    args?: Record<string, unknown>,
  ) => {
    void command;
    void args;
    return installerResult;
  });
  const installerDiscardInvoke = vi.fn(async (
    command: string,
    args?: Record<string, unknown>,
  ) => {
    void command;
    void args;
    return discardResult;
  });
  let wrappedTauri = originalTauri;
  if (originalInvoke) {
    wrappedTauri = {
      core: {
        invoke: async (command, args) => {
          if (command === "get_installer_runtime_intent") {
            return installerIntentInvoke(command, args);
          }
          if (command === "auto_start_installer_runtime") {
            return installerInvoke(command, args);
          }
          if (command === "discard_installer_runtime_intent") {
            return installerDiscardInvoke(command, args);
          }
          return originalInvoke(command, args);
        },
      },
    };
    window.__TAURI__ = wrappedTauri;
  }
  const page = render(strict ? (
    <StrictMode>
      <I18nProvider>
        <MemoryRouter initialEntries={[initialEntry]}>
          <DesktopSetup />
        </MemoryRouter>
      </I18nProvider>
    </StrictMode>
  ) : (
    <I18nProvider>
      <MemoryRouter initialEntries={[initialEntry]}>
        <DesktopSetup />
      </MemoryRouter>
    </I18nProvider>
  ));
  const originalUnmount = page.unmount;
  page.unmount = () => {
    originalUnmount();
    if (window.__TAURI__ === wrappedTauri) window.__TAURI__ = originalTauri;
  };
  return Object.assign(page, {
    installerIntentInvoke,
    installerInvoke,
    installerDiscardInvoke,
  });
}

afterEach(() => {
  vi.unstubAllEnvs();
});

describe("DesktopSetup", () => {
  it("explains the capability boundary in a normal browser", () => {
    renderPage();
    expect(
      screen.getByRole("heading", { name: "Open this page in the DroneDream desktop app" }),
    ).toBeInTheDocument();
    expect(screen.getByText(/web version cannot inspect Windows, WSL or local disks/i)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Check again" })).not.toBeInTheDocument();
  });

  it("shows a ready installed runtime without offering a duplicate install", async () => {
    const invoke = vi.fn(async (command: string) => {
      if (command === "probe_system_prerequisites") return prerequisites;
      if (command === "probe_runtime_status") return runtime;
      throw new Error(`Unexpected command: ${command}`);
    });
    window.__TAURI__ = { core: { invoke } };

    renderPage();

    expect(await screen.findByText("Windows 11 Pro")).toBeInTheDocument();
    expect(screen.getByText("DroneDreamRuntime · Installed · Running")).toBeInTheDocument();
    expect(screen.getByText("PX4 SITL")).toBeInTheDocument();
    expect(screen.queryByRole("combobox", { name: "Runtime disk" })).not.toBeInTheDocument();
    expect(screen.queryByText("Validate Windows, virtualization, memory, and disk"))
      .not.toBeInTheDocument();
    expect(screen.getByText("The installed runtime is ready.")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Open tuning workspace" })).toHaveAttribute(
      "href",
      "/dashboard",
    );
    expect(invoke).toHaveBeenCalledTimes(2);
    expect(invoke).not.toHaveBeenCalledWith("get_runtime_install_plan", expect.anything());
  });

  it("shows the install plan only when the runtime is confirmed missing", async () => {
    const invoke = vi.fn(async (command: string) => {
      if (command === "probe_system_prerequisites") return prerequisites;
      if (command === "probe_runtime_status") return missingRuntime;
      if (command === "get_runtime_install_progress") return idleInstallSnapshot;
      if (command === "get_runtime_install_plan") return plan;
      throw new Error(`Unexpected command: ${command}`);
    });
    window.__TAURI__ = { core: { invoke } };

    renderPage();

    expect((await screen.findAllByText("Ready to install")).length).toBeGreaterThan(0);
    expect(screen.queryByRole("combobox", { name: "Runtime disk" }))
      .not.toBeInTheDocument();
    expect(
      await screen.findByText("Validate Windows, virtualization, memory, and disk"),
    ).toBeInTheDocument();
    expect(screen.getByText(/removes verified temporary files only after a successful import/i))
      .toBeInTheDocument();
    expect(screen.getByText("Runtime download is not published yet")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Install DroneDreamRuntime" }))
      .toBeDisabled();
    expect(invoke).toHaveBeenCalledWith(
      "get_runtime_install_plan",
      undefined,
    );
  });

  it("explains which guarded feature sent the user to setup", async () => {
    const invoke = vi.fn(async (command: string) => {
      if (command === "probe_system_prerequisites") return prerequisites;
      if (command === "probe_runtime_status") return missingRuntime;
      if (command === "get_runtime_install_progress") return idleInstallSnapshot;
      if (command === "get_runtime_install_plan") return plan;
      throw new Error(`Unexpected command: ${command}`);
    });
    window.__TAURI__ = { core: { invoke } };

    renderPage(
      "en",
      noInstallerRuntimeIntent,
      noInstallerAutoStart,
      false,
      discardedInstallerIntent,
      "/desktop/setup?required=experiment",
    );

    expect(await screen.findByText("This feature needs DroneDreamRuntime"))
      .toBeInTheDocument();
    expect(screen.getByText("Create a tuning experiment")).toBeInTheDocument();
    expect(screen.getByText(/requested action was stopped safely/i))
      .toBeInTheDocument();
  });

  it("starts a confirmed install-all handoff automatically exactly once", async () => {
    vi.stubEnv(
      "VITE_RUNTIME_RELEASE_MANIFEST_URL",
      "https://downloads.example.test/dronedream/runtime-manifest.json",
    );
    const automaticSnapshot = installSnapshot({
      phase: "queued",
      bytesDownloaded: 0,
      currentPart: null,
      totalParts: null,
      message: "Queued from the Windows installer",
    });
    const invoke = vi.fn(async (command: string) => {
      if (command === "probe_system_prerequisites") return prerequisites;
      if (command === "probe_runtime_status") return missingRuntime;
      if (command === "get_runtime_install_progress") return idleInstallSnapshot;
      if (command === "get_runtime_install_plan") return plan;
      throw new Error(`Unexpected command: ${command}`);
    });
    window.__TAURI__ = { core: { invoke } };

    const page = renderPage(
      "en",
      {
        status: "ready",
        mode: "install-all",
        targetRoot: "E:\\DroneDream",
        message: "Install everything was confirmed.",
      },
      {
        disposition: "started",
        mode: "install-all",
        targetRoot: "E:\\DroneDream",
        snapshot: automaticSnapshot,
        message: "The confirmed installation started.",
      },
      true,
    );

    expect(await screen.findByText("One-click runtime installation started"))
      .toHaveClass("sr-only");
    expect(screen.getByText("Preparing download")).toBeInTheDocument();
    expect(screen.getByText("Preparing installation")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Pause installation" })).toBeEnabled();
    expect(page.container.querySelector(".launcher-stage-strip")).not.toBeInTheDocument();
    expect(page.container.querySelector(".desktop-launcher > .section-card"))
      .not.toBeInTheDocument();
    expect(screen.queryByText(/Keep DroneDream open while/i)).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Install DroneDreamRuntime" }))
      .not.toBeInTheDocument();
    expect(page.installerIntentInvoke).toHaveBeenCalledTimes(1);
    expect(page.installerInvoke).toHaveBeenCalledTimes(1);
    expect(page.installerInvoke).toHaveBeenCalledWith(
      "auto_start_installer_runtime",
      undefined,
    );
    expect(invoke).toHaveBeenCalledWith("get_runtime_install_plan", {
      targetRoot: "E:\\DroneDream",
    });
    expect(invoke).not.toHaveBeenCalledWith(
      "start_runtime_install",
      expect.anything(),
    );
  });

  it("does not claim the handoff until the exact plan and controls have rendered", async () => {
    let resolvePlan!: (value: RuntimeInstallPlan) => void;
    const pendingPlan = new Promise<RuntimeInstallPlan>((resolve) => {
      resolvePlan = resolve;
    });
    const automaticSnapshot = installSnapshot({
      phase: "queued",
      bytesDownloaded: 0,
      currentPart: null,
      totalParts: null,
      message: "Queued",
    });
    const invoke = vi.fn(async (command: string) => {
      if (command === "probe_system_prerequisites") return prerequisites;
      if (command === "probe_runtime_status") return missingRuntime;
      if (command === "get_runtime_install_progress") return idleInstallSnapshot;
      if (command === "get_runtime_install_plan") return pendingPlan;
      throw new Error(`Unexpected command: ${command}`);
    });
    window.__TAURI__ = { core: { invoke } };

    const page = renderPage(
      "en",
      {
        status: "ready",
        mode: "install-all",
        targetRoot: "E:\\DroneDream",
        message: null,
      },
      {
        disposition: "started",
        mode: "install-all",
        targetRoot: "E:\\DroneDream",
        snapshot: automaticSnapshot,
        message: null,
      },
    );

    await waitFor(() => expect(invoke).toHaveBeenCalledWith(
      "get_runtime_install_plan",
      { targetRoot: "E:\\DroneDream" },
    ));
    expect(page.installerInvoke).not.toHaveBeenCalled();

    resolvePlan(plan);
    expect(await screen.findByText("First-run installation plan")).toBeInTheDocument();
    expect(screen.getAllByText("8.0 GiB")).not.toHaveLength(0);
    await waitFor(() => expect(page.installerInvoke).toHaveBeenCalledTimes(1));
    expect(screen.queryByText("Runtime download is not published yet"))
      .not.toBeInTheDocument();
  });

  it("cancels a confirmed automatic install before a runtime operation starts", async () => {
    vi.stubEnv(
      "VITE_RUNTIME_RELEASE_MANIFEST_URL",
      "https://downloads.example.test/dronedream/runtime-manifest.json",
    );
    let resolveAutoStart!: (value: InstallerRuntimeAutoStartResult) => void;
    const pendingAutoStart = new Promise<InstallerRuntimeAutoStartResult>((resolve) => {
      resolveAutoStart = resolve;
    });
    const user = userEvent.setup();
    const invoke = vi.fn(async (command: string) => {
      if (command === "probe_system_prerequisites") return prerequisites;
      if (command === "probe_runtime_status") return missingRuntime;
      if (command === "get_runtime_install_progress") return idleInstallSnapshot;
      if (command === "get_runtime_install_plan") return plan;
      throw new Error(`Unexpected command: ${command}`);
    });
    window.__TAURI__ = { core: { invoke } };

    const page = renderPage(
      "en",
      {
        status: "ready",
        mode: "install-all",
        targetRoot: "E:\\DroneDream",
        message: null,
      },
      pendingAutoStart,
    );

    const cancel = await screen.findByRole("button", {
      name: "Cancel automatic installation",
    });
    await user.click(cancel);

    expect(await screen.findByText("Automatic runtime installation was cancelled"))
      .toBeInTheDocument();
    expect(page.installerDiscardInvoke).toHaveBeenCalledTimes(1);
    expect(invoke).not.toHaveBeenCalledWith(
      "start_runtime_install",
      expect.anything(),
    );
    expect(screen.queryByRole("combobox", { name: "Runtime disk" }))
      .not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Install DroneDreamRuntime" }))
      .toBeEnabled();

    resolveAutoStart(noInstallerAutoStart);
  });

  it("reveals an active operation when auto-start completes after a successful discard", async () => {
    let resolveAutoStart!: (value: InstallerRuntimeAutoStartResult) => void;
    const pendingAutoStart = new Promise<InstallerRuntimeAutoStartResult>((resolve) => {
      resolveAutoStart = resolve;
    });
    const activeSnapshot = installSnapshot({
      phase: "downloading",
      bytesDownloaded: 4 * 1024 ** 3,
      message: "Late native operation",
    });
    let progressCalls = 0;
    const invoke = vi.fn(async (command: string) => {
      if (command === "probe_system_prerequisites") return prerequisites;
      if (command === "probe_runtime_status") return missingRuntime;
      if (command === "get_runtime_install_progress") {
        progressCalls += 1;
        return progressCalls >= 3 ? activeSnapshot : idleInstallSnapshot;
      }
      if (command === "get_runtime_install_plan") return plan;
      throw new Error(`Unexpected command: ${command}`);
    });
    window.__TAURI__ = { core: { invoke } };
    const user = userEvent.setup();
    const page = renderPage(
      "en",
      {
        status: "ready",
        mode: "install-all",
        targetRoot: "E:\\DroneDream",
        message: null,
      },
      pendingAutoStart,
    );

    await waitFor(() => expect(page.installerInvoke).toHaveBeenCalledTimes(1));
    await user.click(await screen.findByRole("button", {
      name: "Cancel automatic installation",
    }));
    expect(await screen.findByText("Automatic runtime installation was cancelled"))
      .toBeInTheDocument();

    resolveAutoStart({
      disposition: "started",
      mode: "install-all",
      targetRoot: "E:\\DroneDream",
      snapshot: activeSnapshot,
      message: null,
    });

    expect(await screen.findByText("The runtime operation may already have started"))
      .toBeInTheDocument();
    expect(screen.getByText(/became visible after the pending request was cleared/i))
      .toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Pause installation" })).toBeEnabled();
    expect(screen.getByText("4.0 GiB / 8.0 GiB")).toBeInTheDocument();
    expect(screen.queryByText("Automatic runtime installation was cancelled"))
      .not.toBeInTheDocument();
    expect(page.installerDiscardInvoke).toHaveBeenCalledTimes(1);
  });

  it("keeps the journal and attaches progress when pending discard is too late", async () => {
    let resolveAutoStart!: (value: InstallerRuntimeAutoStartResult) => void;
    const pendingAutoStart = new Promise<InstallerRuntimeAutoStartResult>((resolve) => {
      resolveAutoStart = resolve;
    });
    const user = userEvent.setup();
    const activeSnapshot = installSnapshot({
      phase: "downloading",
      bytesDownloaded: 2 * 1024 ** 3,
      message: "The native operation already started",
    });
    let progressCalls = 0;
    const invoke = vi.fn(async (command: string) => {
      if (command === "probe_system_prerequisites") return prerequisites;
      if (command === "probe_runtime_status") return missingRuntime;
      if (command === "get_runtime_install_progress") {
        progressCalls += 1;
        return progressCalls === 1 ? idleInstallSnapshot : activeSnapshot;
      }
      if (command === "get_runtime_install_plan") return plan;
      throw new Error(`Unexpected command: ${command}`);
    });
    window.__TAURI__ = { core: { invoke } };

    const page = renderPage(
      "en",
      {
        status: "ready",
        mode: "install-all",
        targetRoot: "E:\\DroneDream",
        message: null,
      },
      pendingAutoStart,
      false,
      {
        discarded: false,
        message: "The runtime operation has already started.",
      },
    );

    await waitFor(() => expect(page.installerInvoke).toHaveBeenCalledTimes(1));
    await user.click(await screen.findByRole("button", {
      name: "Cancel automatic installation",
    }));

    expect(await screen.findByText("The runtime operation may already have started"))
      .toBeInTheDocument();
    expect(screen.getByText("The runtime operation has already started."))
      .toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Pause installation" })).toBeEnabled();
    expect(screen.getByText("2.0 GiB / 8.0 GiB")).toBeInTheDocument();
    expect(page.installerDiscardInvoke).toHaveBeenCalledTimes(1);

    resolveAutoStart({
      disposition: "started",
      mode: "install-all",
      targetRoot: "E:\\DroneDream",
      snapshot: activeSnapshot,
      message: null,
    });
  });

  it("consumes a blocked confirmed target and falls back to a simple retry", async () => {
    vi.stubEnv(
      "VITE_RUNTIME_RELEASE_MANIFEST_URL",
      "https://downloads.example.test/dronedream/runtime-manifest.json",
    );
    const blockedPlan: RuntimeInstallPlan = {
      ...plan,
      canInstall: false,
      blockers: ["The selected disk no longer has enough free space."],
    };
    let resolveAutoStart!: (value: InstallerRuntimeAutoStartResult) => void;
    const pendingAutoStart = new Promise<InstallerRuntimeAutoStartResult>((resolve) => {
      resolveAutoStart = resolve;
    });
    const invoke = vi.fn(async (
      command: string,
      args?: Record<string, unknown>,
    ) => {
      if (command === "probe_system_prerequisites") return prerequisites;
      if (command === "probe_runtime_status") return missingRuntime;
      if (command === "get_runtime_install_progress") return idleInstallSnapshot;
      if (command === "get_runtime_install_plan") {
        const targetRoot = args?.targetRoot;
        return targetRoot === "C:\\DroneDream"
          ? { ...plan, targetRoot }
          : blockedPlan;
      }
      throw new Error(`Unexpected command: ${command}`);
    });
    window.__TAURI__ = { core: { invoke } };

    const page = renderPage(
      "en",
      {
        status: "ready",
        mode: "custom",
        targetRoot: "E:\\DroneDream",
        message: null,
      },
      pendingAutoStart,
    );

    expect((await screen.findAllByText(/visible plan has blockers/i)).length)
      .toBeGreaterThan(0);
    await waitFor(() => expect(page.installerInvoke).toHaveBeenCalledTimes(1));
    resolveAutoStart({
      disposition: "invalid",
      mode: null,
      targetRoot: null,
      snapshot: null,
      message: "The installer-selected target is no longer safe to use.",
    });
    expect(await screen.findByText("The confirmed installer choice is no longer valid"))
      .toBeInTheDocument();
    expect(invoke).not.toHaveBeenCalledWith(
      "start_runtime_install",
      expect.anything(),
    );

    expect(screen.queryByRole("combobox", { name: "Runtime disk" }))
      .not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Install DroneDreamRuntime" }))
      .toBeDisabled();
    expect(screen.getByRole("dialog", { name: "Setup needs attention" }))
      .toBeInTheDocument();
  });

  it("keeps a ready handoff pending when its exact plan rejects, then retries safely", async () => {
    vi.stubEnv(
      "VITE_RUNTIME_RELEASE_MANIFEST_URL",
      "https://downloads.example.test/dronedream/runtime-manifest.json",
    );
    const user = userEvent.setup();
    const automaticSnapshot = installSnapshot({
      phase: "queued",
      bytesDownloaded: 0,
      currentPart: null,
      totalParts: null,
      message: "Queued after retry",
    });
    let planCalls = 0;
    const invoke = vi.fn(async (
      command: string,
      args?: Record<string, unknown>,
    ) => {
      if (command === "probe_system_prerequisites") return prerequisites;
      if (command === "probe_runtime_status") return missingRuntime;
      if (command === "get_runtime_install_progress") return idleInstallSnapshot;
      if (command === "get_runtime_install_plan") {
        if (args?.targetRoot === "E:\\DroneDream") {
          planCalls += 1;
          if (planCalls === 1) {
            throw new Error("The confirmed E: drive was removed.");
          }
          return plan;
        }
        return { ...plan, targetRoot: "C:\\DroneDream" };
      }
      throw new Error(`Unexpected command: ${command}`);
    });
    window.__TAURI__ = { core: { invoke } };

    const page = renderPage(
      "en",
      {
        status: "ready",
        mode: "custom",
        targetRoot: "E:\\DroneDream",
        message: null,
      },
      {
        disposition: "started",
        mode: "custom",
        targetRoot: "E:\\DroneDream",
        snapshot: automaticSnapshot,
        message: null,
      },
    );

    expect(await screen.findByText(/confirmed E: drive was removed/i)).toBeInTheDocument();
    expect(screen.getByText("Automatic setup needs attention")).toBeInTheDocument();
    expect(screen.getAllByText("E:\\DroneDream")).not.toHaveLength(0);
    expect(screen.getByRole("button", { name: "Cancel automatic installation" }))
      .toBeEnabled();
    expect(page.installerInvoke).not.toHaveBeenCalled();

    await user.click(screen.getByRole("button", {
      name: "Try again",
    }));
    expect(await screen.findByText("One-click runtime installation started"))
      .toBeInTheDocument();
    expect(page.installerIntentInvoke).toHaveBeenCalledTimes(2);
    expect(page.installerInvoke).toHaveBeenCalledTimes(1);
  });

  it("never auto-starts after a prerequisite probe failure and exposes atomic cancel", async () => {
    const user = userEvent.setup();
    const invoke = vi.fn(async (command: string) => {
      if (command === "probe_system_prerequisites") {
        throw new Error("system probe unavailable");
      }
      if (command === "probe_runtime_status") return missingRuntime;
      throw new Error(`Unexpected command: ${command}`);
    });
    window.__TAURI__ = { core: { invoke } };

    const page = renderPage(
      "en",
      {
        status: "ready",
        mode: "install-all",
        targetRoot: "E:\\DroneDream",
        message: null,
      },
      {
        disposition: "invalid",
        mode: null,
        targetRoot: null,
        snapshot: null,
        message: "The target could not be revalidated.",
      },
    );

    expect(await screen.findByText(/system probe unavailable/i)).toBeInTheDocument();
    expect(screen.getByText("Automatic setup needs attention")).toBeInTheDocument();
    expect(screen.getByText("E:\\DroneDream")).toBeInTheDocument();
    expect(page.installerInvoke).not.toHaveBeenCalled();
    const cancel = screen.getByRole("button", {
      name: "Cancel automatic installation",
    });
    expect(cancel).toBeEnabled();
    await user.click(cancel);

    expect(await screen.findByText("Automatic runtime installation was cancelled"))
      .toBeInTheDocument();
    expect(page.installerDiscardInvoke).toHaveBeenCalledTimes(1);
    expect(page.installerInvoke).not.toHaveBeenCalled();
    expect(screen.queryByText("Automatic setup needs attention"))
      .not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Cancel automatic installation" }))
      .not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Pause installation" }))
      .not.toBeInTheDocument();
  });

  it("resumes the validated target without asking for storage again", async () => {
    vi.stubEnv(
      "VITE_RUNTIME_RELEASE_MANIFEST_URL",
      "https://downloads.example.test/dronedream/runtime-manifest.json",
    );
    const user = userEvent.setup();
    const cancelledOnE = installSnapshot({
      phase: "cancelled",
      message: "Cancelled on E",
    });
    const invoke = vi.fn(async (
      command: string,
      args?: Record<string, unknown>,
    ) => {
      if (command === "probe_system_prerequisites") return prerequisites;
      if (command === "probe_runtime_status") return missingRuntime;
      if (command === "get_runtime_install_progress") return cancelledOnE;
      if (command === "get_runtime_install_plan") {
        return {
          ...plan,
          targetRoot: String(args?.targetRoot ?? plan.targetRoot),
        };
      }
      if (command === "start_runtime_install") {
        return installSnapshot({
          phase: "queued",
          targetRoot: "E:\\DroneDream",
          bytesDownloaded: 0,
          currentPart: null,
          totalParts: null,
          message: "Queued on E",
        });
      }
      throw new Error(`Unexpected command: ${command}`);
    });
    window.__TAURI__ = { core: { invoke } };
    renderPage();

    expect(screen.queryByRole("combobox", { name: "Runtime disk" }))
      .not.toBeInTheDocument();
    const install = await screen.findByRole("button", { name: "Resume installation" });
    await user.click(install);

    expect(invoke).toHaveBeenCalledWith("start_runtime_install", {
      request: {
        targetRoot: "E:\\DroneDream",
        releaseManifestUrl:
          "https://downloads.example.test/dronedream/runtime-manifest.json",
      },
    });
  });

  it("recovers an active native operation after an auto-start contract error", async () => {
    vi.stubEnv(
      "VITE_RUNTIME_RELEASE_MANIFEST_URL",
      "https://downloads.example.test/dronedream/runtime-manifest.json",
    );
    const activeSnapshot = installSnapshot({
      phase: "downloading",
      bytesDownloaded: 3 * 1024 ** 3,
      message: "Native download is active",
    });
    let progressCalls = 0;
    const invoke = vi.fn(async (command: string) => {
      if (command === "probe_system_prerequisites") return prerequisites;
      if (command === "probe_runtime_status") return missingRuntime;
      if (command === "get_runtime_install_progress") {
        progressCalls += 1;
        return progressCalls === 1 ? idleInstallSnapshot : activeSnapshot;
      }
      if (command === "get_runtime_install_plan") return plan;
      throw new Error(`Unexpected command: ${command}`);
    });
    window.__TAURI__ = { core: { invoke } };

    renderPage(
      "en",
      {
        status: "ready",
        mode: "install-all",
        targetRoot: "E:\\DroneDream",
        message: null,
      },
      {
        disposition: "started",
        mode: "install-all",
        targetRoot: "E:\\DroneDream",
        snapshot: { ...activeSnapshot, phase: "teleporting" },
        message: null,
      },
    );

    expect(await screen.findByText("The installer choice could not be checked"))
      .toBeInTheDocument();
    expect(await screen.findByRole("button", { name: "Pause installation" }))
      .toBeEnabled();
    expect(screen.getByText("3.0 GiB / 8.0 GiB")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Install DroneDreamRuntime" }))
      .not.toBeInTheDocument();
    expect(progressCalls).toBeGreaterThanOrEqual(2);
  });

  it("keeps manual start locked when auto-start fails with no observable operation", async () => {
    vi.stubEnv(
      "VITE_RUNTIME_RELEASE_MANIFEST_URL",
      "https://downloads.example.test/dronedream/runtime-manifest.json",
    );
    const invoke = vi.fn(async (command: string) => {
      if (command === "probe_system_prerequisites") return prerequisites;
      if (command === "probe_runtime_status") return missingRuntime;
      if (command === "get_runtime_install_progress") return idleInstallSnapshot;
      if (command === "get_runtime_install_plan") return plan;
      throw new Error(`Unexpected command: ${command}`);
    });
    window.__TAURI__ = { core: { invoke } };

    renderPage(
      "en",
      {
        status: "ready",
        mode: "install-all",
        targetRoot: "E:\\DroneDream",
        message: null,
      },
      {
        disposition: "started",
        mode: "install-all",
        targetRoot: "E:\\DroneDream",
        snapshot: null,
        message: null,
      },
    );

    expect(await screen.findByText("The installer choice could not be checked"))
      .toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Try again" }))
      .toBeEnabled();
    expect(screen.queryByRole("button", { name: "Install DroneDreamRuntime" }))
      .not.toBeInTheDocument();
    expect(screen.queryByRole("combobox", { name: "Runtime disk" }))
      .not.toBeInTheDocument();
  });

  it("does not auto-install after an app-only choice and explains the option in Chinese", async () => {
    vi.stubEnv(
      "VITE_RUNTIME_RELEASE_MANIFEST_URL",
      "https://downloads.example.test/dronedream/runtime-manifest.json",
    );
    const invoke = vi.fn(async (command: string) => {
      if (command === "probe_system_prerequisites") return prerequisites;
      if (command === "probe_runtime_status") return missingRuntime;
      if (command === "get_runtime_install_progress") return idleInstallSnapshot;
      if (command === "get_runtime_install_plan") return plan;
      throw new Error(`Unexpected command: ${command}`);
    });
    window.__TAURI__ = { core: { invoke } };

    const page = renderPage("zh-CN", {
      status: "desktopOnly",
      mode: "install-app-only",
      targetRoot: null,
      message: null,
    }, {
      disposition: "desktopOnly",
      mode: "install-app-only",
      targetRoot: null,
      snapshot: null,
      message: "The desktop application was installed without the runtime.",
    });

    expect(await screen.findByText("已选择仅安装桌面程序")).toBeInTheDocument();
    expect(screen.getByText(/以后可以在此页面核对方案并手动安装/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "安装 DroneDreamRuntime" })).toBeEnabled();
    expect(page.installerIntentInvoke).toHaveBeenCalledTimes(1);
    await waitFor(() => expect(page.installerInvoke).toHaveBeenCalledTimes(1));
    expect(invoke).not.toHaveBeenCalledWith(
      "start_runtime_install",
      expect.anything(),
    );
  });

  it("surfaces fail-closed cleanup recovery for an app-only receipt", async () => {
    const user = userEvent.setup();
    const invoke = vi.fn(async (command: string) => {
      if (command === "probe_system_prerequisites") return prerequisites;
      if (command === "probe_runtime_status") return missingRuntime;
      if (command === "get_runtime_install_progress") return idleInstallSnapshot;
      if (command === "get_runtime_install_plan") return plan;
      throw new Error(`Unexpected command: ${command}`);
    });
    window.__TAURI__ = { core: { invoke } };

    const page = renderPage("en", {
      status: "desktopOnly",
      mode: "install-app-only",
      targetRoot: null,
      message: null,
    }, {
      disposition: "invalid",
      mode: null,
      targetRoot: null,
      snapshot: null,
      message: "The desktop-only request cannot replay, but cleanup is pending.",
    });

    expect(await screen.findByText("The confirmed installer choice is no longer valid"))
      .toBeInTheDocument();
    expect(screen.getByText(/cannot replay, but cleanup is pending/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Try again" }))
      .toBeEnabled();
    const discard = screen.getByRole("button", {
      name: "Cancel automatic installation",
    });
    expect(discard).toBeEnabled();
    await user.click(discard);
    expect(await screen.findByText("Automatic runtime installation was cancelled"))
      .toBeInTheDocument();
    expect(page.installerDiscardInvoke).toHaveBeenCalledTimes(1);
    expect(invoke).not.toHaveBeenCalledWith(
      "start_runtime_install",
      expect.anything(),
    );
  });

  it("cleans a terminal receipt and verifies an already installed runtime", async () => {
    const user = userEvent.setup();
    let cleanupStarted = false;
    const cleanupFailure = installSnapshot({
      phase: "failed",
      error: {
        code: "installer_receipt_cleanup_failed",
        message: "The runtime is ready, but its terminal receipt is still locked.",
        retryable: true,
      },
      installedVersion: "v0.1.0-beta.1",
      resumable: true,
    });
    const invoke = vi.fn(async (command: string) => {
      if (command === "probe_system_prerequisites") return prerequisites;
      if (command === "probe_runtime_status") {
        return cleanupStarted ? runtime : missingRuntime;
      }
      if (command === "get_runtime_install_progress") return idleInstallSnapshot;
      if (command === "get_runtime_install_plan") return plan;
      throw new Error(`Unexpected command: ${command}`);
    });
    window.__TAURI__ = { core: { invoke } };

    const page = renderPage("en", {
      status: "ready",
      mode: "install-all",
      targetRoot: "E:\\DroneDream",
      message: null,
    }, {
      disposition: "started",
      mode: "install-all",
      targetRoot: "E:\\DroneDream",
      snapshot: cleanupFailure,
      message: null,
    });

    const cleanup = await screen.findByRole("button", {
      name: "Clean up and recheck the terminal request",
    });
    expect(cleanup).toBeEnabled();
    expect(screen.queryByRole("button", { name: "Retry installation" }))
      .not.toBeInTheDocument();
    cleanupStarted = true;
    await user.click(cleanup);

    expect(await screen.findByText("The terminal installer request was cleaned up"))
      .toBeInTheDocument();
    expect(await screen.findByText("The installed runtime is ready."))
      .toBeInTheDocument();
    expect(page.installerDiscardInvoke).toHaveBeenCalledTimes(1);
    expect(invoke).not.toHaveBeenCalledWith(
      "start_runtime_install",
      expect.anything(),
    );
  });

  it("returns to explicit manual retry after cleaning a failed terminal receipt", async () => {
    vi.stubEnv(
      "VITE_RUNTIME_RELEASE_MANIFEST_URL",
      "https://downloads.example.test/dronedream/runtime-manifest.json",
    );
    const user = userEvent.setup();
    const cleanupFailure = installSnapshot({
      phase: "failed",
      error: {
        code: "installer_receipt_cleanup_failed",
        message: "The failed operation is terminal, but cleanup is pending.",
        retryable: true,
      },
      installedVersion: null,
      resumable: true,
    });
    const invoke = vi.fn(async (command: string) => {
      if (command === "probe_system_prerequisites") return prerequisites;
      if (command === "probe_runtime_status") return missingRuntime;
      if (command === "get_runtime_install_progress") return idleInstallSnapshot;
      if (command === "get_runtime_install_plan") return plan;
      throw new Error(`Unexpected command: ${command}`);
    });
    window.__TAURI__ = { core: { invoke } };

    const page = renderPage("en", {
      status: "ready",
      mode: "install-all",
      targetRoot: "E:\\DroneDream",
      message: null,
    }, {
      disposition: "started",
      mode: "install-all",
      targetRoot: "E:\\DroneDream",
      snapshot: cleanupFailure,
      message: null,
    });

    const cleanup = await screen.findByRole("button", {
      name: "Clean up and recheck the terminal request",
    });
    await user.click(cleanup);

    expect(await screen.findByText("The terminal installer request was cleaned up"))
      .toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Install DroneDreamRuntime" }))
      .toBeEnabled();
    expect(page.installerDiscardInvoke).toHaveBeenCalledTimes(1);
    expect(invoke).not.toHaveBeenCalledWith(
      "start_runtime_install",
      expect.anything(),
    );
  });

  it("fails closed for an invalid handoff without silently starting on another disk", async () => {
    vi.stubEnv(
      "VITE_RUNTIME_RELEASE_MANIFEST_URL",
      "https://downloads.example.test/dronedream/runtime-manifest.json",
    );
    const user = userEvent.setup();
    const invoke = vi.fn(async (command: string) => {
      if (command === "probe_system_prerequisites") return prerequisites;
      if (command === "probe_runtime_status") return missingRuntime;
      if (command === "get_runtime_install_progress") return idleInstallSnapshot;
      if (command === "get_runtime_install_plan") return plan;
      throw new Error(`Unexpected command: ${command}`);
    });
    window.__TAURI__ = { core: { invoke } };

    const page = renderPage("en", {
      status: "invalid",
      mode: null,
      targetRoot: null,
      message: "The selected E: drive no longer has enough free space.",
    }, {
      disposition: "invalid",
      mode: null,
      targetRoot: null,
      snapshot: null,
      message: "The selected E: drive no longer has enough free space.",
    });

    expect(await screen.findByText("The confirmed installer choice is no longer valid"))
      .toBeInTheDocument();
    expect(screen.getByText(/without choosing a different disk/i)).toBeInTheDocument();
    expect(screen.getByText(/selected E: drive no longer has enough free space/i))
      .toBeInTheDocument();
    await waitFor(() => expect(page.installerInvoke).toHaveBeenCalledTimes(1));
    const retry = screen.getByRole("button", {
      name: "Try again",
    });
    const discard = screen.getByRole("button", {
      name: "Cancel automatic installation",
    });
    expect(retry).toBeEnabled();
    expect(discard).toBeEnabled();

    await user.click(retry);
    await waitFor(() => expect(page.installerIntentInvoke).toHaveBeenCalledTimes(2));
    await waitFor(() => expect(page.installerInvoke).toHaveBeenCalledTimes(2));
    await user.click(screen.getByRole("button", {
      name: "Cancel automatic installation",
    }));
    expect(await screen.findByText("Automatic runtime installation was cancelled"))
      .toBeInTheDocument();
    expect(page.installerDiscardInvoke).toHaveBeenCalledTimes(1);
    expect(invoke).not.toHaveBeenCalledWith(
      "start_runtime_install",
      expect.anything(),
    );
  });

  it("restores an interrupted installer-owned operation without a second start call", async () => {
    vi.stubEnv(
      "VITE_RUNTIME_RELEASE_MANIFEST_URL",
      "https://downloads.example.test/dronedream/runtime-manifest.json",
    );
    const resumedSnapshot = installSnapshot({
      phase: "downloading",
      bytesDownloaded: 2 * 1024 ** 3,
      message: "Resumed verified parts",
    });
    const invoke = vi.fn(async (command: string) => {
      if (command === "probe_system_prerequisites") return prerequisites;
      if (command === "probe_runtime_status") return missingRuntime;
      if (command === "get_runtime_install_progress") return resumedSnapshot;
      if (command === "get_runtime_install_plan") return plan;
      throw new Error(`Unexpected command: ${command}`);
    });
    window.__TAURI__ = { core: { invoke } };

    renderPage(
      "en",
      {
        status: "ready",
        mode: "custom",
        targetRoot: "E:\\DroneDream",
        message: "Custom installation was confirmed.",
      },
      {
        disposition: "resumed",
        mode: "custom",
        targetRoot: "E:\\DroneDream",
        snapshot: resumedSnapshot,
        message: "The interrupted installation resumed.",
      },
    );

    expect(await screen.findByText("Runtime installation resumed")).toBeInTheDocument();
    expect(screen.getByText("2.0 GiB / 8.0 GiB")).toBeInTheDocument();
    expect(invoke).not.toHaveBeenCalledWith(
      "start_runtime_install",
      expect.anything(),
    );
  });

  it("starts and cancels a published runtime installation with live byte progress", async () => {
    vi.stubEnv(
      "VITE_RUNTIME_RELEASE_MANIFEST_URL",
      "https://downloads.example.test/dronedream/runtime-manifest.json",
    );
    const user = userEvent.setup();
    let progress: RuntimeInstallSnapshot = idleInstallSnapshot;
    const invoke = vi.fn(async (command: string) => {
      if (command === "probe_system_prerequisites") return prerequisites;
      if (command === "probe_runtime_status") return missingRuntime;
      if (command === "get_runtime_install_progress") return progress;
      if (command === "get_runtime_install_plan") return plan;
      if (command === "start_runtime_install") {
        progress = installSnapshot({
          phase: "queued",
          bytesDownloaded: 0,
          bytesTotal: 8 * 1024 ** 3,
          currentPart: null,
          totalParts: null,
          message: "Queued",
        });
        return progress;
      }
      if (command === "cancel_runtime_install") {
        progress = installSnapshot({
          phase: "cancelled",
          message: "Cancelled by user",
        });
        return progress;
      }
      throw new Error(`Unexpected command: ${command}`);
    });
    window.__TAURI__ = { core: { invoke } };

    renderPage();
    const install = await screen.findByRole("button", {
      name: "Install DroneDreamRuntime",
    });
    expect(install).toBeEnabled();
    await user.click(install);

    expect(await screen.findByText("Preparing installation")).toBeInTheDocument();
    expect(invoke).toHaveBeenCalledWith("start_runtime_install", {
      request: {
        targetRoot: "E:\\DroneDream",
        releaseManifestUrl:
          "https://downloads.example.test/dronedream/runtime-manifest.json",
      },
    });

    await user.click(screen.getByRole("button", { name: "Pause installation" }));
    expect(await screen.findByRole("button", { name: "Resume installation" }))
      .toBeEnabled();
    expect(screen.getByText("1.0 GiB / 8.0 GiB")).toBeInTheDocument();
    expect(invoke).toHaveBeenCalledWith("cancel_runtime_install", undefined);
  });

  it("offers a safe retry and restart continuation for resumable installs", async () => {
    vi.stubEnv(
      "VITE_RUNTIME_RELEASE_MANIFEST_URL",
      "https://downloads.example.test/dronedream/runtime-manifest.json",
    );
    const user = userEvent.setup();
    let progress = installSnapshot({
      phase: "failed",
      error: {
        code: "NETWORK_INTERRUPTED",
        message: "The connection was interrupted.",
        retryable: true,
      },
    });
    const invoke = vi.fn(async (command: string) => {
      if (command === "probe_system_prerequisites") return prerequisites;
      if (command === "probe_runtime_status") return missingRuntime;
      if (command === "get_runtime_install_progress") return progress;
      if (command === "get_runtime_install_plan") return plan;
      if (command === "start_runtime_install") {
        progress = installSnapshot({
          phase: "waitingForRestart",
          error: null,
          requiresRestart: true,
          message: "Restart Windows to enable WSL2.",
        });
        return progress;
      }
      throw new Error(`Unexpected command: ${command}`);
    });
    window.__TAURI__ = { core: { invoke } };

    renderPage();
    expect(await screen.findByText("NETWORK_INTERRUPTED")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Retry installation" }));
    expect(await screen.findByText("Restart Windows to continue")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Continue installation" }))
      .not.toBeInTheDocument();
    expect(screen.getAllByText(/reopen this page and start the installation again/i).length)
      .toBeGreaterThan(0);
  });

  it("cancels an installer-owned restart continuation without using ordinary start", async () => {
    const user = userEvent.setup();
    const waitingForRestart = installSnapshot({
      phase: "waitingForRestart",
      bytesDownloaded: 0,
      bytesTotal: null,
      currentPart: null,
      totalParts: null,
      requiresRestart: true,
      message: "Restart Windows to enable WSL2.",
    });
    const invoke = vi.fn(async (command: string) => {
      if (command === "probe_system_prerequisites") return prerequisites;
      if (command === "probe_runtime_status") return missingRuntime;
      if (command === "get_runtime_install_progress") return idleInstallSnapshot;
      if (command === "get_runtime_install_plan") return plan;
      throw new Error(`Unexpected command: ${command}`);
    });
    window.__TAURI__ = { core: { invoke } };

    const page = renderPage("en", {
      status: "ready",
      mode: "install-all",
      targetRoot: "E:\\DroneDream",
      message: "Runtime setup is ready to continue after restart.",
    }, {
      disposition: "resumed",
      mode: "install-all",
      targetRoot: "E:\\DroneDream",
      snapshot: waitingForRestart,
      message: null,
    });

    expect(await screen.findByText("Restart Windows to continue")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Continue installation" }))
      .not.toBeInTheDocument();
    expect(screen.getAllByText(/will continue automatically/i).length)
      .toBeGreaterThan(0);
    const discard = screen.getByRole("button", {
      name: "Cancel pending post-restart setup",
    });
    expect(discard).toBeEnabled();
    await user.click(discard);

    expect(await screen.findByText("Pending post-restart setup was cancelled"))
      .toBeInTheDocument();
    expect(page.installerDiscardInvoke).toHaveBeenCalledTimes(1);
    expect(invoke).not.toHaveBeenCalledWith(
      "start_runtime_install",
      expect.anything(),
    );
  });

  it("uses the recommended fixed disk without showing another storage step", async () => {
    const invoke = vi.fn(async (
      command: string,
      args?: Record<string, unknown>,
    ) => {
      if (command === "probe_system_prerequisites") return prerequisites;
      if (command === "probe_runtime_status") return missingRuntime;
      if (command === "get_runtime_install_progress") return idleInstallSnapshot;
      if (command === "get_runtime_install_plan") {
        return { ...plan, targetRoot: String(args?.targetRoot ?? plan.targetRoot) };
      }
      throw new Error(`Unexpected command: ${command}`);
    });
    window.__TAURI__ = { core: { invoke } };

    renderPage();

    await screen.findByText("Ready to install");
    expect(screen.queryByRole("combobox", { name: "Runtime disk" }))
      .not.toBeInTheDocument();
    expect(invoke).toHaveBeenCalledWith(
      "get_runtime_install_plan",
      undefined,
    );
    expect(screen.getAllByText("E:\\DroneDream").length).toBeGreaterThan(0);
  });

  it("does not offer paths that are not fixed local drive roots", async () => {
    const report: SystemPrerequisiteReport = {
      ...prerequisites,
      disks: [
        ...prerequisites.disks,
        {
          drive: "\\\\server\\share",
          totalBytes: 2 * 1024 ** 4,
          freeBytes: 1024 ** 4,
          isSystemDrive: false,
        },
      ],
    };
    window.__TAURI__ = {
      core: {
        invoke: vi.fn(async (command: string) => {
          if (command === "probe_system_prerequisites") return report;
          if (command === "probe_runtime_status") return missingRuntime;
          if (command === "get_runtime_install_progress") return idleInstallSnapshot;
          return plan;
        }),
      },
    };

    renderPage();

    await screen.findByText("Ready to install");
    expect(screen.queryByRole("combobox", { name: "Runtime disk" }))
      .not.toBeInTheDocument();
    expect(screen.queryByText("server")).not.toBeInTheDocument();
  });

  it("keeps the Chinese first-run launcher compact", async () => {
    window.__TAURI__ = {
      core: {
        invoke: vi.fn(async (command: string) => {
          if (command === "probe_system_prerequisites") return prerequisites;
          if (command === "probe_runtime_status") return missingRuntime;
          if (command === "get_runtime_install_progress") return idleInstallSnapshot;
          return plan;
        }),
      },
    };

    renderPage("zh-CN");

    expect(await screen.findByText("准备运行环境")).toBeInTheDocument();
    expect(screen.queryByRole("combobox", { name: "运行环境磁盘" }))
      .not.toBeInTheDocument();
  });

  it("keeps successful sections when one desktop command fails", async () => {
    window.__TAURI__ = {
      core: {
        invoke: vi.fn(async (command: string) => {
          if (command === "probe_system_prerequisites") return prerequisites;
          if (command === "get_runtime_install_plan") return plan;
          throw new Error("runtime probe unavailable");
        }),
      },
    };

    renderPage();

    expect(await screen.findByText("Windows 11 Pro")).toBeInTheDocument();
    expect(screen.queryByRole("combobox", { name: "Runtime disk" })).not.toBeInTheDocument();
    expect(screen.getByText(/probe_runtime_status: runtime probe unavailable/i)).toBeInTheDocument();
  });

  it("does not enable local tuning without a fresh supported system report", async () => {
    const invoke = vi.fn(async (command: string) => {
      if (command === "probe_system_prerequisites") {
        throw new Error("system probe unavailable");
      }
      if (command === "probe_runtime_status") return runtime;
      throw new Error(`Unexpected command: ${command}`);
    });
    window.__TAURI__ = { core: { invoke } };
    const page = renderPage();

    expect(await screen.findByText(/system probe unavailable/i)).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Create a tuning experiment" }))
      .not.toBeInTheDocument();

    page.unmount();
    window.__TAURI__ = {
      core: {
        invoke: vi.fn(async (command: string) => {
          if (command === "probe_system_prerequisites") {
            return { ...prerequisites, supported: false };
          }
          if (command === "probe_runtime_status") return runtime;
          throw new Error(`Unexpected command: ${command}`);
        }),
      },
    };
    renderPage();

    expect(await screen.findByText("Setup action required")).toBeInTheDocument();
    expect(screen.getByText("Runtime healthy")).toBeInTheDocument();
    expect(screen.queryByText("Ready for local tuning")).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Create a tuning experiment" }))
      .not.toBeInTheDocument();
  });

  it("fails closed when required memory information is missing or insufficient", async () => {
    let report: SystemPrerequisiteReport = { ...prerequisites, memory: null };
    const invoke = vi.fn(async (command: string) => {
      if (command === "probe_system_prerequisites") return report;
      if (command === "probe_runtime_status") return runtime;
      throw new Error(`Unexpected command: ${command}`);
    });
    window.__TAURI__ = { core: { invoke } };
    const page = renderPage();

    expect(await screen.findByText("Setup action required")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Create a tuning experiment" }))
      .not.toBeInTheDocument();

    page.unmount();
    report = {
      ...prerequisites,
      memory: { totalBytes: 14 * 1024 ** 3, availableBytes: 8 * 1024 ** 3 },
    };
    renderPage();

    expect(await screen.findByText("Setup action required")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Create a tuning experiment" }))
      .not.toBeInTheDocument();
  });

  it("does not expose manual diagnostics on a healthy launcher", async () => {
    const invoke = vi.fn(async (command: string) => {
      if (command === "probe_system_prerequisites") return prerequisites;
      if (command === "probe_runtime_status") return runtime;
      throw new Error(`Unexpected command: ${command}`);
    });
    window.__TAURI__ = { core: { invoke } };
    renderPage();

    await screen.findByText("DroneDreamRuntime · Installed · Running");
    expect(screen.queryByRole("button", { name: "Check again" }))
      .not.toBeInTheDocument();
  });

  it("does not request a default install plan when no eligible disk exists", async () => {
    const user = userEvent.setup();
    const noDiskReport = { ...prerequisites, disks: [] };
    const invoke = vi.fn(async (command: string) => {
      if (command === "probe_system_prerequisites") return noDiskReport;
      if (command === "probe_runtime_status") return missingRuntime;
      throw new Error(`Unexpected command: ${command}`);
    });
    window.__TAURI__ = { core: { invoke } };
    renderPage();

    expect(await screen.findByRole("dialog", { name: "Setup needs attention" }))
      .toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "View error information" }));
    expect(screen.getByText("No eligible fixed local disk was detected."))
      .toBeInTheDocument();
    expect(invoke).toHaveBeenCalledTimes(2);
    expect(invoke).not.toHaveBeenCalledWith("get_runtime_install_plan", expect.anything());
  });

  it("does not offer first installation when the runtime probe is uncertain", async () => {
    const uncertainRuntime: RuntimeStatusReport = {
      ...missingRuntime,
      components: missingRuntime.components.map((component) => ({
        ...component,
        status: "unknown",
      })),
      diagnostics: ["Unable to inspect the WSL registry."],
    };
    const invoke = vi.fn(async (command: string) => {
      if (command === "probe_system_prerequisites") return prerequisites;
      if (command === "probe_runtime_status") return uncertainRuntime;
      throw new Error(`Unexpected command: ${command}`);
    });
    window.__TAURI__ = { core: { invoke } };
    renderPage();

    expect(await screen.findByText("Unable to inspect the WSL registry.")).toBeInTheDocument();
    expect(screen.queryByRole("combobox", { name: "Runtime disk" })).not.toBeInTheDocument();
    expect(invoke).toHaveBeenCalledTimes(2);
    expect(invoke).not.toHaveBeenCalledWith("get_runtime_install_plan", expect.anything());
  });

  it("shows attention for an installed runtime with an unhealthy required component", async () => {
    const user = userEvent.setup();
    const contradictoryRuntime: RuntimeStatusReport = {
      ...runtime,
      ready: false,
      components: runtime.components.map((component) =>
        component.id === "local-backend"
          ? { ...component, status: "unhealthy" }
          : component,
      ),
    };
    const invoke = vi.fn(async (command: string) => {
      if (command === "probe_system_prerequisites") return prerequisites;
      if (command === "probe_runtime_status") return contradictoryRuntime;
      if (command === "repair_runtime") return runtime;
      throw new Error(`Unexpected command: ${command}`);
    });
    window.__TAURI__ = { core: { invoke } };
    renderPage();

    expect(await screen.findByText("The installed runtime needs attention.")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Create a tuning experiment" }))
      .not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Repair and restart runtime" }));
    expect(await screen.findByText("The installed runtime is ready.")).toBeInTheDocument();
    expect(invoke).toHaveBeenCalledWith("repair_runtime", undefined);
  });

  it("starts an installed runtime that is currently stopped", async () => {
    const user = userEvent.setup();
    const stoppedRuntime: RuntimeStatusReport = {
      ...runtime,
      running: false,
      ready: false,
    };
    const invoke = vi.fn(async (command: string) => {
      if (command === "probe_system_prerequisites") return prerequisites;
      if (command === "probe_runtime_status") return stoppedRuntime;
      if (command === "start_runtime") return runtime;
      throw new Error(`Unexpected command: ${command}`);
    });
    window.__TAURI__ = { core: { invoke } };
    renderPage();

    await user.click(await screen.findByRole("button", { name: "Start runtime" }));
    expect(await screen.findByText("The installed runtime is ready.")).toBeInTheDocument();
    expect(invoke).toHaveBeenCalledWith("start_runtime", undefined);
  });

  it("rejects a native plan whose canInstall flag contradicts its blockers", async () => {
    const contradictoryPlan = {
      ...plan,
      canInstall: true,
      blockers: ["The selected disk is unavailable."],
    };
    window.__TAURI__ = {
      core: {
        invoke: vi.fn(async (command: string) => {
          if (command === "probe_system_prerequisites") return prerequisites;
          if (command === "probe_runtime_status") return missingRuntime;
          if (command === "get_runtime_install_progress") return idleInstallSnapshot;
          return contradictoryPlan;
        }),
      },
    };
    renderPage();

    expect(await screen.findByText(/plan.canInstall must be true exactly/i))
      .toBeInTheDocument();
    expect(screen.queryByText("The selected disk is unavailable.")).not.toBeInTheDocument();
  });

  it("stops the request chain after the page is unmounted", async () => {
    let resolvePrerequisites!: (value: SystemPrerequisiteReport) => void;
    const pendingPrerequisites = new Promise<SystemPrerequisiteReport>((resolve) => {
      resolvePrerequisites = resolve;
    });
    const invoke = vi.fn(async (command: string) => {
      if (command === "probe_system_prerequisites") return pendingPrerequisites;
      if (command === "probe_runtime_status") return missingRuntime;
      if (command === "get_runtime_install_progress") return idleInstallSnapshot;
      if (command === "get_runtime_install_plan") return plan;
      throw new Error(`Unexpected command: ${command}`);
    });
    window.__TAURI__ = { core: { invoke } };
    const page = renderPage();

    page.unmount();
    resolvePrerequisites(prerequisites);
    await pendingPrerequisites;
    await Promise.resolve();

    expect(invoke).not.toHaveBeenCalledWith("get_runtime_install_plan", expect.anything());
  });

  it("localizes stable native component and plan-step identifiers", async () => {
    const localizedPlan: RuntimeInstallPlan = {
      ...plan,
      steps: plan.steps.map((step) =>
        step.id === "preflight"
          ? {
              ...step,
              title: "Native English title",
              description: "Native English description",
            }
          : step,
      ),
    };
    window.__TAURI__ = {
      core: {
        invoke: vi.fn(async (command: string) => {
          if (command === "probe_system_prerequisites") return prerequisites;
          if (command === "probe_runtime_status") return missingRuntime;
          if (command === "get_runtime_install_progress") return idleInstallSnapshot;
          return localizedPlan;
        }),
      },
    };
    renderPage("zh-CN");

    expect(await screen.findByText("专用 WSL2 运行环境")).toBeInTheDocument();
    expect(screen.getByText("检查 Windows、虚拟化、内存和磁盘")).toBeInTheDocument();
    expect(screen.queryByText("Native English title")).not.toBeInTheDocument();
  });

  it("formats desktop storage values using binary units", () => {
    expect(formatBytes(0)).toBe("0 B");
    expect(formatBytes(16 * 1024 ** 3)).toBe("16.0 GiB");
    expect(formatBytes(-1)).toBe("—");
    expect(formatBytes(0.5)).toBe("—");
  });

  it("keeps the healthy launcher free of a details or refresh control", async () => {
    const invoke = vi.fn(async (command: string) => {
      if (command === "probe_system_prerequisites") return prerequisites;
      if (command === "probe_runtime_status") return runtime;
      return plan;
    });
    window.__TAURI__ = { core: { invoke } };
    renderPage();

    expect((await screen.findAllByText("Ready")).length).toBeGreaterThan(0);
    expect(screen.queryByRole("button", { name: "Check again" }))
      .not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "System and installation details" }))
      .not.toBeInTheDocument();
  });
});
