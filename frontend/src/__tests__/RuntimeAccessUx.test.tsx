import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

const runtimeSessionContractMocks = vi.hoisted(() => ({
  verify: vi.fn(async <T,>(report: T) => report),
}));
const openerMocks = vi.hoisted(() => ({
  openUrl: vi.fn(async () => undefined),
}));
const distributionPlanMocks = vi.hoisted(() => ({
  validate: vi.fn(async (request: { selection: Record<string, unknown> }) => ({
    schemaVersion: 1,
    kind: "dronedream-distribution-plan-validation",
    planVersion: "1.0.0",
    productDisplayVersion: "1.0.0",
    sourceCommit: "a".repeat(40),
    sourceTreeClean: true,
    planSha256: "b".repeat(64),
    selection: request.selection,
    catalog: {
      registryManifestSha256: "c".repeat(64),
      capabilityPolicySha256: "d".repeat(64),
      editionManifestSha256: "e".repeat(64),
      vehiclePackManifestSha256: "f".repeat(64),
      vehiclePackPayloadSha256: "1".repeat(64),
      vehiclePackSignatureState: "missing",
      validationTier: "contract-only",
    },
    requiredModules: ["desktop-core", "runtime-simulation"],
    optionalModules: [],
    capabilities: {
      defaultDecision: "deny",
      frontendIsAuthority: false,
      enabledOrConditioned: ["simulation.execute"],
      denied: ["hardware.arm", "hardware.flight", "hardware.parameter.write"],
    },
    rollback: { status: "missing", reference: null },
    blockers: ["native-apply-not-implemented"],
    canApply: false,
    executionAuthorized: false,
  })),
}));

vi.mock("../desktop/runtimeSessionContract", async (importOriginal) => {
  const original = await importOriginal<
    typeof import("../desktop/runtimeSessionContract")
  >();
  return {
    ...original,
    verifyRuntimeSessionContract: runtimeSessionContractMocks.verify,
  };
});

vi.mock("@tauri-apps/plugin-opener", () => ({
  openUrl: openerMocks.openUrl,
}));

vi.mock("../desktop/bridge", async (importOriginal) => {
  const original = await importOriginal<typeof import("../desktop/bridge")>();
  return {
    ...original,
    validateDistributionPlan: distributionPlanMocks.validate,
  };
});

import { apiClient } from "../api/client";
import { AppShell } from "../AppShell";
import { I18nProvider } from "../i18n/I18nProvider";
import { Dashboard } from "../pages/Dashboard";
import { DesktopSetup } from "../pages/DesktopSetup";
import { resetDesktopReadinessSession } from "../desktop/readiness";
import { History } from "../pages/History";

const missingRuntime = {
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

const readyRuntime = {
  ...missingRuntime,
  installed: true,
  running: true,
  ready: true,
  version: "2026.07",
  dataRoot: "E:\\DroneDream",
  components: missingRuntime.components.map((component) => ({
    ...component,
    status: "ready",
  })),
};

const autoStartableRuntime = {
  ...readyRuntime,
  running: false,
  ready: false,
  components: readyRuntime.components.map((component) => ({
    ...component,
    status: component.id === "host-ownership" ? "ready" : "stopped",
  })),
};

async function openSettingsWorkspace() {
  fireEvent.click(screen.getByRole("button", { name: /Settings|设置/ }));
  const quickSettings = screen.getByRole("dialog", {
    name: /Settings|设置/,
  });
  fireEvent.click(within(quickSettings).getByRole("button", {
    name: /All settings|全部设置/,
  }));
  return screen.findByRole("region", { name: /Settings|设置/ });
}

const prerequisites = {
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

describe("desktop runtime access UX", () => {
afterEach(() => {
  resetDesktopReadinessSession();
    runtimeSessionContractMocks.verify.mockReset();
    runtimeSessionContractMocks.verify.mockImplementation(async (report) => report);
    openerMocks.openUrl.mockReset();
    openerMocks.openUrl.mockResolvedValue(undefined);
    distributionPlanMocks.validate.mockClear();
    delete window.__TAURI__;
    window.localStorage.clear();
    vi.restoreAllMocks();
  });

  it("keeps read-only pages visible, marks runtime routes, and avoids backend calls", async () => {
    window.localStorage.setItem("dronedream:universal-workspace:v2", "lab");
    const invoke = vi.fn(async (command: string) => {
      if (command === "probe_system_prerequisites") return prerequisites;
      if (command === "probe_runtime_status") return missingRuntime;
      throw new Error(`Unexpected command: ${command}`);
    });
    window.__TAURI__ = { core: { invoke } };
    const listJobs = vi.spyOn(apiClient, "listJobs");
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    const router = createMemoryRouter([
      {
        path: "/",
        element: <AppShell />,
        children: [
          { path: "dashboard", element: <Dashboard /> },
          { path: "history", element: <History /> },
        ],
      },
    ], { initialEntries: ["/dashboard"] });

    render(
      <I18nProvider>
        <QueryClientProvider client={queryClient}>
          <RouterProvider router={router} />
        </QueryClientProvider>
      </I18nProvider>,
    );

    expect(await screen.findByText("Runtime disconnected"))
      .toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Experiment" }))
      .not.toHaveClass("runtime-locked");
    expect(screen.getByRole("link", { name: "Run History" }))
      .not.toHaveClass("runtime-locked");
    expect(screen.getByRole("link", { name: "Evidence Review" }))
      .toHaveAttribute("href", "/lab/validation");
    expect(screen.queryByRole("link", { name: "ECE498BH" })).not.toBeInTheDocument();
    const workspace = await openSettingsWorkspace();
    fireEvent.click(within(workspace).getByRole("tab", { name: "ECE498BH" }));
    const courseLink = within(workspace).getByRole("link", { name: "Open course" });
    expect(courseLink).toHaveAttribute("target", "_blank");
    fireEvent.click(courseLink);
    await waitFor(() => {
      expect(openerMocks.openUrl).toHaveBeenCalledWith(
        "https://binhu7.github.io/courses/ECE498/Spring2025/ECE498home.html",
      );
    });
    openerMocks.openUrl.mockRejectedValueOnce(new Error("browser unavailable"));
    fireEvent.click(courseLink);
    fireEvent.click(within(workspace).getByRole("button", { name: "Back to app" }));
    expect(await screen.findByRole("alert"))
      .toHaveTextContent(/course page could not be opened/i);
    fireEvent.click(screen.getByRole("button", { name: "Dismiss" }));
    expect(screen.queryByRole("alert")).toBeNull();
    expect(screen.queryByRole("link", { name: "New Batch" })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Batch Runs" })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Environment" })).not.toBeInTheDocument();
    expect(screen.getByRole("navigation", { name: "Primary navigation" })
      .querySelectorAll("a")).toHaveLength(7);
    expect(listJobs).not.toHaveBeenCalled();
    expect(invoke.mock.calls.filter(([command]) => command === "probe_runtime_status"))
      .toHaveLength(0);

    await act(async () => {
      await router.navigate("/history");
    });
    await waitFor(() => {
      expect(screen.getByText("Runtime disconnected")).toBeInTheDocument();
    });
    expect(listJobs).not.toHaveBeenCalled();

    router.dispose();
    queryClient.clear();
  });

  it("starts an owned stopped runtime only after the explicit settings check", async () => {
    let resolveStart: (value: typeof readyRuntime) => void = () => undefined;
    const pendingStart = new Promise<typeof readyRuntime>((resolve) => {
      resolveStart = resolve;
    });
    const invoke = vi.fn(async (command: string) => {
      if (command === "probe_system_prerequisites") return prerequisites;
      if (command === "probe_runtime_status") return autoStartableRuntime;
      if (command === "start_runtime") return pendingStart;
      throw new Error(`Unexpected command: ${command}`);
    });
    window.__TAURI__ = { core: { invoke } };
    const listJobs = vi.spyOn(apiClient, "listJobs").mockResolvedValue({
      items: [],
      total: 0,
      page: 1,
      page_size: 10,
    } as never);
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    const router = createMemoryRouter([
      {
        path: "/",
        element: <AppShell />,
        children: [
          { path: "dashboard", element: <Dashboard /> },
          { path: "history", element: <History /> },
        ],
      },
    ], { initialEntries: ["/dashboard"] });

    render(
      <I18nProvider>
        <QueryClientProvider client={queryClient}>
          <RouterProvider router={router} />
        </QueryClientProvider>
      </I18nProvider>,
    );

    expect(await screen.findByText("Runtime disconnected")).toBeInTheDocument();
    expect(invoke.mock.calls.filter(([command]) => command !== "get_installer_locale"))
      .toHaveLength(0);
    const workspace = await openSettingsWorkspace();
    expect(invoke.mock.calls.filter(([command]) => command !== "get_installer_locale"))
      .toHaveLength(0);
    fireEvent.click(within(workspace).getByRole("tab", { name: "Runtime" }));
    fireEvent.click(within(workspace).getByRole("button", { name: "Check environment" }));
    await waitFor(() => {
      expect(invoke.mock.calls.filter(([command]) => command === "start_runtime"))
        .toHaveLength(1);
    });
    fireEvent.click(within(workspace).getByRole("button", { name: "Back to app" }));
    await act(async () => {
      await router.navigate("/history");
    });
    expect(invoke.mock.calls.filter(([command]) => command === "start_runtime"))
      .toHaveLength(1);

    resolveStart(readyRuntime);
    await waitFor(() => expect(listJobs).toHaveBeenCalled());
    expect(screen.queryByText("Starting the local runtime")).not.toBeInTheDocument();
    await act(async () => {
      await router.navigate("/dashboard");
    });
    expect(await screen.findByRole("link", { name: "+ New experiment" }))
      .toHaveAttribute("href", "/jobs/new");
    router.dispose();
    queryClient.clear();
  });

  it("shows one actionable failure when a manually requested start fails", async () => {
    const invoke = vi.fn(async (command: string) => {
      if (command === "probe_system_prerequisites") return prerequisites;
      if (command === "probe_runtime_status") return autoStartableRuntime;
      if (command === "start_runtime") throw new Error("health check failed");
      throw new Error(`Unexpected command: ${command}`);
    });
    window.__TAURI__ = { core: { invoke } };
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    const router = createMemoryRouter([
      {
        path: "/",
        element: <AppShell />,
        children: [
          { path: "dashboard", element: <Dashboard /> },
          { path: "history", element: <History /> },
        ],
      },
    ], { initialEntries: ["/dashboard"] });

    render(
      <I18nProvider>
        <QueryClientProvider client={queryClient}>
          <RouterProvider router={router} />
        </QueryClientProvider>
      </I18nProvider>,
    );

    expect(await screen.findByText("Runtime disconnected"))
      .toBeInTheDocument();
    expect(invoke.mock.calls.filter(([command]) => command !== "get_installer_locale"))
      .toHaveLength(0);
    const workspace = await openSettingsWorkspace();
    expect(invoke.mock.calls.filter(([command]) => command !== "get_installer_locale"))
      .toHaveLength(0);
    fireEvent.click(within(workspace).getByRole("tab", { name: "Runtime" }));
    fireEvent.click(within(workspace).getByRole("button", { name: "Check environment" }));
    expect(await screen.findByText("The local runtime could not start"))
      .toBeInTheDocument();
    fireEvent.click(within(workspace).getByRole("button", { name: "Back to app" }));
    expect(screen.getAllByRole("button", { name: "Open settings" }).length)
      .toBeGreaterThan(0);
    fireEvent.click(screen.getAllByRole("button", { name: "Open settings" })[0]);
    const targetedWorkspace = await screen.findByRole("region", { name: "Settings" });
    expect(within(targetedWorkspace).getByRole("tab", { name: "Runtime" }))
      .toHaveAttribute("aria-selected", "true");
    fireEvent.click(within(targetedWorkspace).getByRole("button", { name: "Back to app" }));
    expect(invoke.mock.calls.filter(([command]) => command === "start_runtime"))
      .toHaveLength(1);
    await act(async () => {
      await router.navigate("/history");
    });
    expect(await screen.findByText("The local runtime could not start"))
      .toBeInTheDocument();
    expect(invoke.mock.calls.filter(([command]) => command === "start_runtime"))
      .toHaveLength(1);
    router.dispose();
    queryClient.clear();
  });

  it("auto-starts exactly once from the real setup route without a manual button", async () => {
    const invoke = vi.fn(async (command: string) => {
      if (command === "get_installer_runtime_intent") {
        return { status: "none", mode: null, targetRoot: null, message: null };
      }
      if (command === "probe_system_prerequisites") return prerequisites;
      if (command === "probe_runtime_status") return autoStartableRuntime;
      if (command === "start_runtime") return readyRuntime;
      throw new Error(`Unexpected command: ${command}`);
    });
    window.__TAURI__ = { core: { invoke } };
    const router = createMemoryRouter([
      {
        path: "/",
        element: <AppShell />,
        children: [{ path: "desktop/setup", element: <DesktopSetup /> }],
      },
    ], { initialEntries: ["/desktop/setup"] });

    render(
      <I18nProvider>
        <RouterProvider router={router} />
      </I18nProvider>,
    );

    await waitFor(() => {
      expect(invoke.mock.calls.filter(([command]) => command === "probe_runtime_status").length)
        .toBeGreaterThanOrEqual(2);
    });
    await waitFor(() => {
      expect(invoke.mock.calls.filter(([command]) => command === "start_runtime"))
        .toHaveLength(1);
    });
    expect(await screen.findByText("The installed runtime is ready."))
      .toBeInTheDocument();
    expect(await screen.findByRole("button", {
      name: "Sign in and enter DroneDream",
    })).toBeEnabled();
    expect(screen.queryByRole("button", { name: "Start runtime" }))
      .not.toBeInTheDocument();
    expect(invoke.mock.calls.filter(([command]) => command === "start_runtime"))
      .toHaveLength(1);

    router.dispose();
  });

  it("never checks on workspace entry, navigation, settings open, or locale changes", async () => {
    const invoke = vi.fn(async (command: string) => {
      if (command === "probe_system_prerequisites") return prerequisites;
      if (command === "probe_runtime_status") return readyRuntime;
      if (command === "start_runtime") return readyRuntime;
      throw new Error(`Unexpected command: ${command}`);
    });
    window.__TAURI__ = { core: { invoke } };
    const router = createMemoryRouter([
      {
        path: "/",
        element: <AppShell />,
        children: [
          { path: "dashboard", element: <div>Dashboard placeholder</div> },
          { path: "history", element: <div>History placeholder</div> },
        ],
      },
    ], { initialEntries: ["/dashboard"] });

    render(
      <I18nProvider>
        <RouterProvider router={router} />
      </I18nProvider>,
    );

    expect(invoke.mock.calls.filter(([command]) => command !== "get_installer_locale"))
      .toHaveLength(0);
    await act(async () => {
      await router.navigate("/history?view=recent");
    });
    expect(screen.getByText("History placeholder")).toBeInTheDocument();
    expect(invoke.mock.calls.filter(([command]) => command === "probe_runtime_status"))
      .toHaveLength(0);

    const workspace = await openSettingsWorkspace();
    expect(invoke.mock.calls.filter(([command]) => command !== "get_installer_locale"))
      .toHaveLength(0);
    fireEvent.click(within(workspace).getByRole("tab", { name: "General" }));
    fireEvent.click(within(workspace).getByRole("button", { name: "简体中文" }));
    expect(invoke.mock.calls.filter(([command]) => command !== "get_installer_locale"))
      .toHaveLength(0);
    fireEvent.click(within(workspace).getByRole("button", { name: "English" }));
    expect(invoke.mock.calls.filter(([command]) => command !== "get_installer_locale"))
      .toHaveLength(0);
    fireEvent.click(within(workspace).getByRole("tab", { name: "Runtime" }));
    fireEvent.click(within(workspace).getByRole("button", { name: "Check environment" }));
    await waitFor(() => {
      expect(invoke.mock.calls.filter(([command]) => command === "probe_runtime_status"))
        .toHaveLength(1);
    });
    expect(invoke.mock.calls.filter(([command]) => command === "probe_system_prerequisites"))
      .toHaveLength(1);
    expect(invoke.mock.calls.filter(([command]) => command === "start_runtime"))
      .toHaveLength(1);
    await waitFor(() => {
      expect(within(workspace).getByRole("button", { name: "Check environment" }))
        .not.toBeDisabled();
    }, { timeout: 7_000 });
    fireEvent.click(within(workspace).getByRole("button", { name: "Back to app" }));

    router.dispose();
  });

  it("keeps a ready launcher frozen on focus and changes it only after a manual check", async () => {
    let currentRuntime: typeof readyRuntime | typeof missingRuntime = readyRuntime;
    const invoke = vi.fn(async (command: string) => {
      if (command === "get_installer_runtime_intent") {
        return { status: "none", mode: null, targetRoot: null, message: null };
      }
      if (command === "probe_system_prerequisites") return prerequisites;
      if (command === "probe_runtime_status") return currentRuntime;
      throw new Error(`Unexpected command: ${command}`);
    });
    window.__TAURI__ = { core: { invoke } };
    const router = createMemoryRouter([
      {
        path: "/",
        element: <AppShell />,
        children: [
          { path: "desktop/setup", element: <DesktopSetup /> },
        ],
      },
    ], { initialEntries: ["/desktop/setup?required=experiment"] });

    render(
      <I18nProvider>
        <RouterProvider router={router} />
      </I18nProvider>,
    );

    expect(await screen.findByText("The installed runtime is ready."))
      .toBeInTheDocument();
    expect(screen.getAllByText("Ready for local tuning").length).toBeGreaterThan(0);
    expect(screen.queryByRole("link", { name: "Experiment" }))
      .not.toBeInTheDocument();
    expect(screen.queryByText("This feature needs DroneDreamRuntime"))
      .not.toBeInTheDocument();
    const initialRuntimeProbeCount = invoke.mock.calls.filter(
      ([command]) => command === "probe_runtime_status",
    ).length;

    currentRuntime = missingRuntime;
    fireEvent.focus(window);

    await act(async () => Promise.resolve());
    expect(screen.getByText("The installed runtime is ready.")).toBeInTheDocument();
    expect(invoke.mock.calls.filter(
      ([command]) => command === "probe_runtime_status",
    )).toHaveLength(initialRuntimeProbeCount);

    const workspace = await openSettingsWorkspace();
    fireEvent.click(within(workspace).getByRole("tab", { name: "Runtime" }));
    fireEvent.click(within(workspace).getByRole("button", { name: "Check environment" }));

    await waitFor(() => {
      expect(within(workspace).getByRole("button", { name: "Check environment" }))
        .not.toBeDisabled();
      expect(within(workspace).getByText("Environment unavailable"))
        .toBeInTheDocument();
      expect(invoke.mock.calls.filter(
        ([command]) => command === "probe_runtime_status",
      )).toHaveLength(initialRuntimeProbeCount + 1);
    }, { timeout: 7_000 });
    expect(within(workspace).getByText("DroneDreamRuntime is not installed."))
      .toBeInTheDocument();
    fireEvent.click(within(workspace).getByRole("button", { name: "Back to app" }));
    expect(screen.getByRole("progressbar", { name: "Startup readiness progress" }))
      .toHaveAttribute("aria-valuenow", "0");

    router.dispose();
  }, 12_000);
});
