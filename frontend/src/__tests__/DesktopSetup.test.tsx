import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";

import type {
  RuntimeInstallPlan,
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
      freeBytes: 640 * 1024 ** 3,
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
      id: "storage",
      title: "Prepare dedicated runtime storage",
      description: "Create an isolated data directory.",
      requiresAdministrator: false,
      destructive: false,
      estimatedBytes: 24 * 1024 ** 3,
    },
  ],
};

function renderPage(locale: "en" | "zh-CN" = "en") {
  window.localStorage.setItem("drone-dream:locale", locale);
  return render(
    <I18nProvider>
      <MemoryRouter>
        <DesktopSetup />
      </MemoryRouter>
    </I18nProvider>,
  );
}

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
    expect(screen.queryByText("Prepare dedicated runtime storage")).not.toBeInTheDocument();
    expect(screen.getByText("The installed runtime is ready.")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Create a tuning experiment" })).toHaveAttribute(
      "href",
      "/jobs/new",
    );
    expect(invoke).toHaveBeenCalledTimes(2);
    expect(invoke).not.toHaveBeenCalledWith("get_runtime_install_plan", expect.anything());
  });

  it("shows the install plan only when the runtime is confirmed missing", async () => {
    const invoke = vi.fn(async (command: string) => {
      if (command === "probe_system_prerequisites") return prerequisites;
      if (command === "probe_runtime_status") return missingRuntime;
      if (command === "get_runtime_install_plan") return plan;
      throw new Error(`Unexpected command: ${command}`);
    });
    window.__TAURI__ = { core: { invoke } };

    renderPage();

    expect(await screen.findByRole("combobox", { name: "Runtime disk" })).toHaveValue("E:");
    expect(await screen.findByText("Prepare dedicated runtime storage")).toBeInTheDocument();
    expect(invoke).toHaveBeenCalledWith(
      "get_runtime_install_plan",
      { targetRoot: "E:\\DroneDream" },
    );
  });

  it("re-fetches the plan for a user-selected fixed disk", async () => {
    const user = userEvent.setup();
    const invoke = vi.fn(async (
      command: string,
      args?: Record<string, unknown>,
    ) => {
      if (command === "probe_system_prerequisites") return prerequisites;
      if (command === "probe_runtime_status") return missingRuntime;
      if (command === "get_runtime_install_plan") {
        return { ...plan, targetRoot: String(args?.targetRoot ?? plan.targetRoot) };
      }
      throw new Error(`Unexpected command: ${command}`);
    });
    window.__TAURI__ = { core: { invoke } };

    renderPage();

    const selector = await screen.findByRole("combobox", { name: "Runtime disk" });
    expect(selector).toHaveValue("E:");
    await user.selectOptions(selector, "C:");

    await waitFor(() => expect(selector).toBeEnabled());
    expect(selector).toHaveValue("C:");
    expect(invoke).toHaveBeenCalledWith(
      "get_runtime_install_plan",
      { targetRoot: "C:\\DroneDream" },
    );
    expect(screen.getAllByText("C:\\DroneDream")).toHaveLength(2);
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
          return plan;
        }),
      },
    };

    renderPage();

    const selector = await screen.findByRole("combobox", { name: "Runtime disk" });
    expect(screen.getAllByRole("option")).toHaveLength(2);
    expect(selector).not.toHaveTextContent("server");
  });

  it("provides the storage selector in Chinese", async () => {
    window.__TAURI__ = {
      core: {
        invoke: vi.fn(async (command: string) => {
          if (command === "probe_system_prerequisites") return prerequisites;
          if (command === "probe_runtime_status") return missingRuntime;
          return plan;
        }),
      },
    };

    renderPage("zh-CN");

    expect(
      await screen.findByRole("combobox", { name: "运行环境磁盘" }),
    ).toHaveValue("E:");
    expect(screen.getByText("运行环境目录")).toBeInTheDocument();
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
    expect(screen.queryByRole("link", { name: "Create a tuning experiment" }))
      .not.toBeInTheDocument();
  });

  it("retains and marks the last successful runtime result after a transient refresh failure", async () => {
    const user = userEvent.setup();
    let runtimeFails = false;
    const invoke = vi.fn(async (command: string) => {
      if (command === "probe_system_prerequisites") return prerequisites;
      if (command === "probe_runtime_status") {
        if (runtimeFails) throw new Error("temporary runtime failure");
        return runtime;
      }
      throw new Error(`Unexpected command: ${command}`);
    });
    window.__TAURI__ = { core: { invoke } };
    renderPage();

    await screen.findByText("DroneDreamRuntime · Installed · Running");
    runtimeFails = true;
    await user.click(screen.getByRole("button", { name: "Check again" }));

    expect(await screen.findByText(/temporary runtime failure/i)).toBeInTheDocument();
    expect(screen.getByText("DroneDreamRuntime · Installed · Running")).toBeInTheDocument();
    expect(screen.getByText("Last successful result")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Create a tuning experiment" }))
      .not.toBeInTheDocument();
  });

  it("does not request a default install plan when no eligible disk exists", async () => {
    const noDiskReport = { ...prerequisites, disks: [] };
    const invoke = vi.fn(async (command: string) => {
      if (command === "probe_system_prerequisites") return noDiskReport;
      if (command === "probe_runtime_status") return missingRuntime;
      throw new Error(`Unexpected command: ${command}`);
    });
    window.__TAURI__ = { core: { invoke } };
    renderPage();

    expect(
      await screen.findByText("No eligible fixed local disk was detected."),
    ).toBeInTheDocument();
    expect(invoke).toHaveBeenCalledTimes(2);
    expect(invoke).not.toHaveBeenCalledWith("get_runtime_install_plan", expect.anything());
  });

  it("shows attention for an installed runtime with an unhealthy required component", async () => {
    const contradictoryRuntime: RuntimeStatusReport = {
      ...runtime,
      ready: false,
      components: runtime.components.map((component) =>
        component.id === "local-backend"
          ? { ...component, status: "unhealthy" }
          : component,
      ),
    };
    window.__TAURI__ = {
      core: {
        invoke: vi.fn(async (command: string) => {
          if (command === "probe_system_prerequisites") return prerequisites;
          if (command === "probe_runtime_status") return contradictoryRuntime;
          throw new Error(`Unexpected command: ${command}`);
        }),
      },
    };
    renderPage();

    expect(await screen.findByText("The installed runtime needs attention.")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Create a tuning experiment" }))
      .not.toBeInTheDocument();
  });

  it("does not trust canInstall when the native plan also reports blockers", async () => {
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
          return contradictoryPlan;
        }),
      },
    };
    renderPage();

    expect(
      await screen.findByText("Resolve the following blockers before installation."),
    ).toBeInTheDocument();
    expect(screen.getByText("The selected disk is unavailable.")).toBeInTheDocument();
  });

  it("stops the request chain after the page is unmounted", async () => {
    let resolvePrerequisites!: (value: SystemPrerequisiteReport) => void;
    const pendingPrerequisites = new Promise<SystemPrerequisiteReport>((resolve) => {
      resolvePrerequisites = resolve;
    });
    const invoke = vi.fn(async (command: string) => {
      if (command === "probe_system_prerequisites") return pendingPrerequisites;
      if (command === "probe_runtime_status") return missingRuntime;
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
      steps: [
        {
          ...plan.steps[0],
          id: "preflight",
          title: "Native English title",
          description: "Native English description",
        },
      ],
    };
    window.__TAURI__ = {
      core: {
        invoke: vi.fn(async (command: string) => {
          if (command === "probe_system_prerequisites") return prerequisites;
          if (command === "probe_runtime_status") return missingRuntime;
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

  it("exposes a refresh action after the first check", async () => {
    const invoke = vi.fn(async (command: string) => {
      if (command === "probe_system_prerequisites") return prerequisites;
      if (command === "probe_runtime_status") return runtime;
      return plan;
    });
    window.__TAURI__ = { core: { invoke } };
    renderPage();

    await waitFor(() => expect(screen.getByRole("button", { name: "Check again" })).toBeEnabled());
  });
});
