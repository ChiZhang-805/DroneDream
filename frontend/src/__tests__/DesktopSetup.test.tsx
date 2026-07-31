import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { StrictMode } from "react";
import { MemoryRouter, useLocation } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

const optionalAuthState = vi.hoisted(() => ({
  current: null as null | {
    configured: boolean;
    loading: boolean;
    account: {
      id: string;
      email: string | null;
      displayName: string;
      avatarUrl: string | null;
    } | null;
  },
}));
const updaterState = vi.hoisted(() => ({
  current: {
    status: "current" as
      | "checking"
      | "current"
      | "available"
      | "downloading"
      | "installing"
      | "error",
    availableVersion: null as string | null,
    progress: null as number | null,
    error: null as string | null,
    desktopRuntime: true,
    checkForUpdates: vi.fn(async () => undefined),
    installAvailableUpdate: vi.fn(async () => undefined),
  },
}));
const browserAuthMocks = vi.hoisted(() => ({
  configuration: {
    supabaseUrl: "https://yggabfynndpzymlqvnim.supabase.co",
    publishableKey: "public-test-key-for-browser-auth",
  } as { supabaseUrl: string; publishableKey: string } | null,
  adoptSession: vi.fn(async () => undefined),
}));

vi.mock("../features/auth/AuthContext", async (importOriginal) => {
  const original =
    await importOriginal<typeof import("../features/auth/AuthContext")>();
  return {
    ...original,
    useOptionalAuth: () => optionalAuthState.current,
  };
});

vi.mock("../desktop/updaterContext", async (importOriginal) => {
  const original =
    await importOriginal<typeof import("../desktop/updaterContext")>();
  return {
    ...original,
    useAppUpdaterState: () => updaterState.current,
  };
});

vi.mock("../features/auth/supabaseClient", async (importOriginal) => {
  const original =
    await importOriginal<typeof import("../features/auth/supabaseClient")>();
  return {
    ...original,
    browserAuthConfiguration: () => browserAuthMocks.configuration,
  };
});

vi.mock("../features/auth/browserAuth", () => ({
  adoptBrowserAuthSession: browserAuthMocks.adoptSession,
}));

import type {
  InstallerRuntimeAutoStartResult,
  InstallerRuntimeDiscardResult,
  InstallerRuntimeIntent,
  RuntimeInstallPlan,
  RuntimeInstallSnapshot,
  RuntimeStatusReport,
  SystemPrerequisiteReport,
} from "../desktop/bridge";
import { apiClient } from "../api/client";
import { formatBytes } from "../desktop/format";
import { I18nProvider } from "../i18n/I18nProvider";
import { DesktopSetup } from "../pages/DesktopSetup";
import { resetDesktopReadinessSession } from "../desktop/readiness";

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
          <LocationProbe />
        </MemoryRouter>
      </I18nProvider>
    </StrictMode>
  ) : (
    <I18nProvider>
      <MemoryRouter initialEntries={[initialEntry]}>
        <DesktopSetup />
        <LocationProbe />
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

function LocationProbe() {
  const location = useLocation();
  return <output data-testid="current-route">{location.pathname}</output>;
}

afterEach(() => {
  optionalAuthState.current = null;
  resetDesktopReadinessSession();
  updaterState.current = {
    status: "current",
    availableVersion: null,
    progress: null,
    error: null,
    desktopRuntime: true,
    checkForUpdates: vi.fn(async () => undefined),
    installAvailableUpdate: vi.fn(async () => undefined),
  };
  browserAuthMocks.configuration = {
    supabaseUrl: "https://yggabfynndpzymlqvnim.supabase.co",
    publishableKey: "public-test-key-for-browser-auth",
  };
  browserAuthMocks.adoptSession.mockReset();
  browserAuthMocks.adoptSession.mockResolvedValue(undefined);
  vi.restoreAllMocks();
  vi.unstubAllEnvs();
});

describe("DesktopSetup", () => {
  it("explains the capability boundary in a normal browser", () => {
    renderPage();
    expect(
      screen.getByRole("heading", { name: "Open this page in the DroneDream desktop app" }),
    ).toBeInTheDocument();
    expect(screen.getByText(/web version cannot inspect Windows, WSL,? or local disks/i)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Check again" })).not.toBeInTheDocument();
  });

  it("shows a ready installed runtime with the single browser sign-in entry", async () => {
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
    expect(screen.queryByRole("link", { name: "Open tuning workspace" }))
      .not.toBeInTheDocument();
    expect(screen.getByRole("button", {
      name: "Sign in and enter tuning workspace",
    })).toBeEnabled();
    expect(screen.getByRole("progressbar", { name: "Startup readiness progress" }))
      .toHaveAttribute("aria-valuenow", "100");
    expect(invoke).toHaveBeenCalledTimes(2);
    expect(invoke).not.toHaveBeenCalledWith("get_runtime_install_plan", expect.anything());
  });

  it("shows 100 percent local readiness while a configured account is still loading", async () => {
    optionalAuthState.current = {
      configured: true,
      loading: true,
      account: null,
    };
    window.__TAURI__ = {
      core: {
        invoke: vi.fn(async (command: string) => {
          if (command === "probe_system_prerequisites") return prerequisites;
          if (command === "probe_runtime_status") return runtime;
          throw new Error(`Unexpected command: ${command}`);
        }),
      },
    };

    renderPage();

    expect(await screen.findByText("DroneDreamRuntime · Installed · Running"))
      .toBeInTheDocument();
    expect(screen.getByRole("progressbar", { name: "Startup readiness progress" }))
      .toHaveAttribute("aria-valuenow", "100");
    expect(screen.getByRole("button", {
      name: "Sign in and enter tuning workspace",
    })).toBeEnabled();
    expect(screen.queryByRole("link", { name: "Open tuning workspace" }))
      .not.toBeInTheDocument();
  });

  it("offers the browser sign-in only after local checks reach 100 percent", async () => {
    optionalAuthState.current = {
      configured: true,
      loading: false,
      account: null,
    };
    window.__TAURI__ = {
      core: {
        invoke: vi.fn(async (command: string) => {
          if (command === "probe_system_prerequisites") return prerequisites;
          if (command === "probe_runtime_status") return runtime;
          throw new Error(`Unexpected command: ${command}`);
        }),
      },
    };

    renderPage();

    expect(await screen.findByText("Sign in to finish")).toBeInTheDocument();
    expect(screen.getByRole("progressbar", { name: "Startup readiness progress" }))
      .toHaveAttribute("aria-valuenow", "100");
    expect(screen.getByRole("button", {
      name: "Sign in and enter tuning workspace",
    }))
      .toBeEnabled();
    expect(screen.queryByRole("link", { name: "Open tuning workspace" }))
      .not.toBeInTheDocument();
  });

  it("does not automatically recheck a ready environment when the window regains focus", async () => {
    optionalAuthState.current = {
      configured: true,
      loading: false,
      account: null,
    };
    const invoke = vi.fn(async (command: string) => {
      if (command === "probe_system_prerequisites") return prerequisites;
      if (command === "probe_runtime_status") return runtime;
      throw new Error(`Unexpected command: ${command}`);
    });
    window.__TAURI__ = { core: { invoke } };

    renderPage();

    expect(await screen.findByRole("button", {
      name: "Sign in and enter tuning workspace",
    })).toBeEnabled();
    expect(invoke).toHaveBeenCalledTimes(2);

    await act(async () => {
      window.dispatchEvent(new Event("focus"));
      await Promise.resolve();
    });

    expect(invoke).toHaveBeenCalledTimes(2);
    expect(screen.getByRole("progressbar", { name: "Startup readiness progress" }))
      .toHaveAttribute("aria-valuenow", "100");
  });

  it("fails closed at 100 percent when account configuration is missing", async () => {
    optionalAuthState.current = {
      configured: false,
      loading: false,
      account: null,
    };
    browserAuthMocks.configuration = null;
    const invoke = vi.fn(async (command: string) => {
      if (command === "probe_system_prerequisites") return prerequisites;
      if (command === "probe_runtime_status") return runtime;
      throw new Error(`Unexpected command: ${command}`);
    });
    window.__TAURI__ = { core: { invoke } };
    const user = userEvent.setup();

    renderPage();
    const signIn = await screen.findByRole("button", {
      name: "Sign in and enter tuning workspace",
    });
    expect(screen.getByRole("progressbar", { name: "Startup readiness progress" }))
      .toHaveAttribute("aria-valuenow", "100");
    expect(screen.queryByText("Account authentication is not configured in this desktop build."))
      .not.toBeInTheDocument();

    await user.click(signIn);

    expect(await screen.findByText(
      "This desktop build is missing the public account configuration. Install a release build that passed the account configuration gate.",
    )).toBeInTheDocument();
    expect(invoke).not.toHaveBeenCalledWith("begin_browser_auth", expect.anything());
    expect(screen.getByTestId("current-route")).toHaveTextContent("/");
  });

  it("adopts exactly the session returned by the native browser flow", async () => {
    optionalAuthState.current = {
      configured: true,
      loading: false,
      account: null,
    };
    const browserSession = {
      accessToken: "header.payload.signature",
      refreshToken: "refresh-token-value",
    };
    const invoke = vi.fn(async (
      command: string,
      args?: Record<string, unknown>,
    ) => {
      if (command === "probe_system_prerequisites") return prerequisites;
      if (command === "probe_runtime_status") return runtime;
      if (command === "begin_browser_auth") return browserSession;
      throw new Error(`Unexpected command: ${command} ${JSON.stringify(args)}`);
    });
    window.__TAURI__ = { core: { invoke } };
    const user = userEvent.setup();

    renderPage();
    await user.click(await screen.findByRole("button", {
      name: "Sign in and enter tuning workspace",
    }));

    await waitFor(() => {
      expect(browserAuthMocks.adoptSession).toHaveBeenCalledTimes(1);
      expect(browserAuthMocks.adoptSession).toHaveBeenCalledWith(browserSession);
    });
    expect(invoke).toHaveBeenCalledWith("begin_browser_auth", {
      request: {
        locale: "en",
        supabaseUrl: "https://yggabfynndpzymlqvnim.supabase.co",
        publishableKey: "public-test-key-for-browser-auth",
      },
    });
  });

  it("enters only after the browser flow and local backend accept the same account", async () => {
    optionalAuthState.current = {
      configured: true,
      loading: false,
      account: null,
    };
    const browserSession = {
      accessToken: "header.payload.signature",
      refreshToken: "refresh-token-value",
    };
    browserAuthMocks.adoptSession.mockImplementationOnce(async () => {
      optionalAuthState.current = {
        configured: true,
        loading: false,
        account: {
          id: "user-accepted",
          email: "pilot@example.com",
          displayName: "Pilot",
          avatarUrl: null,
        },
      };
    });
    const verifySession = vi
      .spyOn(apiClient, "verifyAuthenticatedSession")
      .mockResolvedValue({ status: "ready", user_id: "user-accepted" });
    window.__TAURI__ = {
      core: {
        invoke: vi.fn(async (command: string) => {
          if (command === "probe_system_prerequisites") return prerequisites;
          if (command === "probe_runtime_status") return runtime;
          if (command === "begin_browser_auth") return browserSession;
          throw new Error(`Unexpected command: ${command}`);
        }),
      },
    };

    renderPage();

    expect(await screen.findByRole("button", {
      name: "Sign in and enter tuning workspace",
    })).toBeEnabled();
    expect(verifySession).not.toHaveBeenCalled();
    expect(screen.getByTestId("current-route")).toHaveTextContent("/");

    await userEvent.click(screen.getByRole("button", {
      name: "Sign in and enter tuning workspace",
    }));

    await waitFor(() => {
      expect(screen.getByTestId("current-route")).toHaveTextContent("/assistant");
    });
    expect(screen.getByRole("progressbar", { name: "Startup readiness progress" }))
      .toHaveAttribute("aria-valuenow", "100");
    expect(verifySession).toHaveBeenCalledTimes(1);
  });

  it("keeps the workspace locked when the backend identity differs from the signed-in account", async () => {
    optionalAuthState.current = {
      configured: true,
      loading: false,
      account: null,
    };
    browserAuthMocks.adoptSession.mockImplementationOnce(async () => {
      optionalAuthState.current = {
        configured: true,
        loading: false,
        account: {
          id: "user-expected",
          email: "pilot@example.com",
          displayName: "Pilot",
          avatarUrl: null,
        },
      };
    });
    vi.spyOn(apiClient, "verifyAuthenticatedSession").mockResolvedValue({
      status: "ready",
      user_id: "user-other",
    });
    window.__TAURI__ = {
      core: {
        invoke: vi.fn(async (command: string) => {
          if (command === "probe_system_prerequisites") return prerequisites;
          if (command === "probe_runtime_status") return runtime;
          if (command === "begin_browser_auth") {
            return {
              accessToken: "header.payload.signature",
              refreshToken: "refresh-token-value",
            };
          }
          throw new Error(`Unexpected command: ${command}`);
        }),
      },
    };

    renderPage();

    await userEvent.click(await screen.findByRole("button", {
      name: "Sign in and enter tuning workspace",
    }));
    expect(await screen.findByText(/different account identity/i)).toBeVisible();
    expect(screen.queryByRole("link", { name: "Open tuning workspace" }))
      .not.toBeInTheDocument();
    expect(screen.getByRole("progressbar", { name: "Startup readiness progress" }))
      .toHaveAttribute("aria-valuenow", "100");
  });

  it("blocks entry and offers the signed updater when a newer application is available", async () => {
    const installAvailableUpdate = vi.fn(async () => undefined);
    updaterState.current = {
      ...updaterState.current,
      status: "available",
      availableVersion: "1.0.1",
      installAvailableUpdate,
    };
    window.__TAURI__ = {
      core: {
        invoke: vi.fn(async (command: string) => {
          if (command === "probe_system_prerequisites") return prerequisites;
          if (command === "probe_runtime_status") return runtime;
          throw new Error(`Unexpected command: ${command}`);
        }),
      },
    };

    renderPage();

    const update = await screen.findByRole("button", {
      name: "Version 1.0.1 is available. Click to update.",
    });
    expect(screen.queryByRole("link", { name: "Open tuning workspace" }))
      .not.toBeInTheDocument();
    expect(screen.getByRole("progressbar", { name: "Startup readiness progress" }))
      .toHaveAttribute("aria-valuenow", "100");
    await userEvent.click(update);
    expect(installAvailableUpdate).toHaveBeenCalledTimes(1);
  });

  it("keeps checking through a transient system-probe timeout instead of showing an error", async () => {
    let prerequisiteAttempts = 0;
    const invoke = vi.fn(async (command: string) => {
      if (command === "probe_system_prerequisites") {
        prerequisiteAttempts += 1;
        if (prerequisiteAttempts === 1) {
          throw new Error("read-only system probe timed out after 40 seconds.");
        }
        return prerequisites;
      }
      if (command === "probe_runtime_status") return runtime;
      throw new Error(`Unexpected command: ${command}`);
    });
    window.__TAURI__ = { core: { invoke } };

    renderPage();

    await waitFor(() => expect(prerequisiteAttempts).toBe(1));
    expect(screen.queryByRole("dialog", { name: "Setup needs attention" }))
      .not.toBeInTheDocument();
    expect(screen.getByText("Checking system")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Open tuning workspace" }))
      .not.toBeInTheDocument();
    expect(screen.getByRole("progressbar", { name: "Startup readiness progress" }))
      .toHaveAttribute("aria-valuenow", "99");

    await waitFor(() => {
      expect(prerequisiteAttempts).toBe(2);
      expect(screen.getByRole("progressbar", {
        name: "Startup readiness progress",
      })).toHaveAttribute("aria-valuenow", "100");
    }, { timeout: 3_000 });
    expect(prerequisiteAttempts).toBe(2);
    expect(screen.queryByRole("dialog", { name: "Setup needs attention" }))
      .not.toBeInTheDocument();
  });

  it("does not unlock the workspace until a completed install passes fresh health checks", async () => {
    const completedSnapshot = installSnapshot({
      phase: "completed",
      bytesDownloaded: 8 * 1024 ** 3,
      currentPart: 8,
      totalParts: 8,
      message: "Installation completed",
      resumable: false,
      installedVersion: "2026.07",
    });
    const invoke = vi.fn(async (command: string) => {
      if (command === "probe_system_prerequisites") return prerequisites;
      if (command === "probe_runtime_status") return missingRuntime;
      if (command === "get_runtime_install_progress") return completedSnapshot;
      if (command === "get_runtime_install_plan") return plan;
      throw new Error(`Unexpected command: ${command}`);
    });
    window.__TAURI__ = { core: { invoke } };

    renderPage();

    expect(await screen.findByText("Checking services")).toBeInTheDocument();
    await waitFor(() => {
      expect(screen.getByRole("dialog", { name: "Setup needs attention" }))
        .toBeInTheDocument();
    });
    expect(screen.queryByRole("link", { name: "Open tuning workspace" }))
      .not.toBeInTheDocument();
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
    expect(screen.getByRole("progressbar", { name: "Startup readiness progress" }))
      .toHaveAttribute("aria-valuenow", "0");
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

    await act(async () => {
      resolveAutoStart({
        disposition: "started",
        mode: "install-all",
        targetRoot: "E:\\DroneDream",
        snapshot: activeSnapshot,
        message: null,
      });
    });
    await waitFor(() => expect(screen.getByText("2.0 GiB / 8.0 GiB"))
      .toBeInTheDocument());
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
        diagnosticsPath: null,
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
        diagnosticsPath: null,
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
    let resolveStart!: (snapshot: RuntimeInstallSnapshot) => void;
    const pendingStart = new Promise<RuntimeInstallSnapshot>((resolve) => {
      resolveStart = resolve;
    });
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
        return pendingStart;
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

    expect(screen.getByText("Preparing download")).toBeInTheDocument();
    expect(screen.queryByText("Pausing setup")).not.toBeInTheDocument();
    resolveStart(progress);

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

  it.each([
    [
      "runtime_service_unhealthy",
      "Runtime services did not start",
      "The runtime started, but its internal API did not become healthy.",
    ],
    [
      "runtime_host_connectivity",
      "Windows could not reach the runtime",
      "The service may be running in WSL, but Windows could not reach its local health endpoint.",
    ],
    [
      "runtime_health_unknown",
      "Runtime health could not be confirmed",
      "DroneDream could not determine whether the problem is inside WSL or on the Windows-to-WSL connection.",
    ],
  ])("explains the %s runtime health failure without exposing raw details first", async (
    code,
    title,
    hint,
  ) => {
    const progress = installSnapshot({
      phase: "failed",
      error: {
        code,
        message: "Low-level runtime health failure.",
        retryable: true,
        diagnosticsPath: null,
      },
    });
    const invoke = vi.fn(async (command: string) => {
      if (command === "probe_system_prerequisites") return prerequisites;
      if (command === "probe_runtime_status") return missingRuntime;
      if (command === "get_runtime_install_progress") return progress;
      if (command === "get_runtime_install_plan") return plan;
      throw new Error(`Unexpected command: ${command}`);
    });
    window.__TAURI__ = { core: { invoke } };

    renderPage();

    const dialog = await screen.findByRole("dialog", { name: title });
    expect(dialog).toHaveTextContent(hint);
    expect(dialog).not.toHaveTextContent("Low-level runtime health failure.");
    expect(screen.getByRole("button", { name: "View error information" }))
      .toBeEnabled();
  });

  it("shows and copies the exported diagnostic path", async () => {
    const user = userEvent.setup();
    const writeText = vi.spyOn(navigator.clipboard, "writeText");
    const diagnosticsPath =
      "C:\\Users\\student\\AppData\\Local\\DroneDream\\diagnostics\\runtime-install.log";
    const progress = installSnapshot({
      phase: "failed",
      error: {
        code: "runtime_service_unhealthy",
        message: "The runtime API did not become healthy.",
        retryable: true,
        diagnosticsPath,
      },
    });
    const invoke = vi.fn(async (command: string) => {
      if (command === "probe_system_prerequisites") return prerequisites;
      if (command === "probe_runtime_status") return missingRuntime;
      if (command === "get_runtime_install_progress") return progress;
      if (command === "get_runtime_install_plan") return plan;
      throw new Error(`Unexpected command: ${command}`);
    });
    window.__TAURI__ = { core: { invoke } };

    renderPage();

    expect(await screen.findByText(diagnosticsPath)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Copy log path" }));
    expect(writeText).toHaveBeenCalledWith(diagnosticsPath);
    expect(screen.getByText("Log path copied.")).toBeInTheDocument();
  });

  it("keeps the runtime health dialog fully localized in Chinese", async () => {
    const progress = installSnapshot({
      phase: "failed",
      error: {
        code: "runtime_host_connectivity",
        message: "connection timed out",
        retryable: true,
        diagnosticsPath: "C:\\DroneDream\\diagnostics\\runtime-install.log",
      },
    });
    const invoke = vi.fn(async (command: string) => {
      if (command === "probe_system_prerequisites") return prerequisites;
      if (command === "probe_runtime_status") return missingRuntime;
      if (command === "get_runtime_install_progress") return progress;
      if (command === "get_runtime_install_plan") return plan;
      throw new Error(`Unexpected command: ${command}`);
    });
    window.__TAURI__ = { core: { invoke } };

    renderPage("zh-CN");

    const dialog = await screen.findByRole("dialog", {
      name: "Windows 无法连接运行环境",
    });
    expect(dialog).toHaveTextContent(
      "WSL 内的服务可能已经启动，但 Windows 无法连接其本地健康检查地址。",
    );
    expect(dialog).toHaveTextContent("诊断日志");
    expect(screen.getByRole("button", { name: "复制日志路径" })).toBeEnabled();
    expect(dialog).not.toHaveTextContent("View error information");
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
        diagnosticsPath: null,
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

    const dialog = await screen.findByRole("dialog", { name: "Setup needs attention" });
    expect(dialog).toBeInTheDocument();
    const detailsButton = screen.getByRole("button", { name: "View error information" });
    await waitFor(() => expect(detailsButton).toHaveFocus());
    await user.click(detailsButton);
    expect(screen.getByText("No eligible fixed local disk was detected."))
      .toBeInTheDocument();
    expect(invoke).toHaveBeenCalledTimes(2);
    expect(invoke).not.toHaveBeenCalledWith("get_runtime_install_plan", expect.anything());
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog", { name: "Setup needs attention" }))
      .not.toBeInTheDocument();
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
