import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

const runtimeSessionContractMocks = vi.hoisted(() => ({
  verify: vi.fn(async <T,>(report: T) => report),
}));
const openerMocks = vi.hoisted(() => ({
  openUrl: vi.fn(async () => undefined),
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
    delete window.__TAURI__;
    window.localStorage.clear();
    vi.restoreAllMocks();
  });

  it("keeps read-only pages visible, marks runtime routes, and avoids backend calls", async () => {
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

    expect(await screen.findByText("Runtime data is not available yet"))
      .toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Dashboard" }))
      .not.toHaveClass("runtime-locked");
    expect(screen.getByRole("link", { name: "Run History" }))
      .not.toHaveClass("runtime-locked");
    expect(screen.getByRole("link", { name: "Fixed Scenarios" }))
      .toHaveAttribute("href", "/scenarios");
    const courseLink = screen.getByRole("link", { name: "ECE498BH" });
    expect(courseLink)
      .not.toHaveClass("runtime-locked");
    expect(courseLink)
      .toHaveAttribute(
        "href",
        "https://binhu7.github.io/courses/ECE498/Spring2025/ECE498home.html",
      );
    expect(courseLink)
      .toHaveAttribute("target", "_blank");
    fireEvent.click(courseLink);
    await waitFor(() => {
      expect(openerMocks.openUrl).toHaveBeenCalledWith(
        "https://binhu7.github.io/courses/ECE498/Spring2025/ECE498home.html",
      );
    });
    openerMocks.openUrl.mockRejectedValueOnce(new Error("browser unavailable"));
    fireEvent.click(courseLink);
    expect(await screen.findByRole("alert"))
      .toHaveTextContent(/course page could not be opened/i);
    fireEvent.click(screen.getByRole("button", { name: "Dismiss" }));
    expect(screen.queryByRole("alert")).toBeNull();
    expect(screen.queryByRole("link", { name: "Experiment" }))
      .not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "New Batch" })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Batch Runs" })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Environment" })).not.toBeInTheDocument();
    expect(screen.getByRole("navigation", { name: "Primary navigation" })
      .querySelectorAll("a")).toHaveLength(5);
    expect(listJobs).not.toHaveBeenCalled();
    expect(invoke.mock.calls.filter(([command]) => command === "probe_runtime_status"))
      .toHaveLength(0);

    await act(async () => {
      await router.navigate("/history");
    });
    await waitFor(() => {
      expect(screen.getByText("Runtime data is not available yet")).toBeInTheDocument();
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

    expect(await screen.findByText("Runtime data is not available yet")).toBeInTheDocument();
    expect(invoke.mock.calls.filter(([command]) => command !== "get_installer_locale"))
      .toHaveLength(0);
    fireEvent.click(screen.getByRole("button", { name: "Settings" }));
    expect(invoke.mock.calls.filter(([command]) => command !== "get_installer_locale"))
      .toHaveLength(0);
    fireEvent.click(screen.getByRole("button", { name: "Check environment" }));
    await waitFor(() => {
      expect(invoke.mock.calls.filter(([command]) => command === "start_runtime"))
        .toHaveLength(1);
    });
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
    expect(screen.queryByRole("link", { name: "Experiment" }))
      .not.toBeInTheDocument();

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

    expect(await screen.findByText("Runtime data is not available yet"))
      .toBeInTheDocument();
    expect(invoke.mock.calls.filter(([command]) => command !== "get_installer_locale"))
      .toHaveLength(0);
    fireEvent.click(screen.getByRole("button", { name: "Settings" }));
    expect(invoke.mock.calls.filter(([command]) => command !== "get_installer_locale"))
      .toHaveLength(0);
    fireEvent.click(screen.getByRole("button", { name: "Check environment" }));
    expect(await screen.findByText("The local runtime could not start"))
      .toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: "Open settings" }).length)
      .toBeGreaterThan(0);
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

  it("does not auto-start from the explicit setup route", async () => {
    const invoke = vi.fn(async (command: string) => {
      if (command === "probe_system_prerequisites") return prerequisites;
      if (command === "probe_runtime_status") return autoStartableRuntime;
      throw new Error(`Unexpected command: ${command}`);
    });
    window.__TAURI__ = { core: { invoke } };
    const router = createMemoryRouter([
      {
        path: "/",
        element: <AppShell />,
        children: [{ path: "desktop/setup", element: <div>Setup placeholder</div> }],
      },
    ], { initialEntries: ["/desktop/setup"] });

    render(
      <I18nProvider>
        <RouterProvider router={router} />
      </I18nProvider>,
    );

    expect(await screen.findByText("Setup placeholder")).toBeInTheDocument();
    await waitFor(() => {
      expect(invoke.mock.calls.filter(([command]) => command === "probe_runtime_status"))
        .toHaveLength(1);
    });
    expect(invoke.mock.calls.some(([command]) => command === "start_runtime")).toBe(false);

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

    fireEvent.click(screen.getByRole("button", { name: "Settings" }));
    expect(invoke.mock.calls.filter(([command]) => command !== "get_installer_locale"))
      .toHaveLength(0);
    fireEvent.click(screen.getByRole("button", { name: "简体中文" }));
    expect(invoke.mock.calls.filter(([command]) => command !== "get_installer_locale"))
      .toHaveLength(0);
    fireEvent.click(screen.getByRole("button", { name: "English" }));
    expect(invoke.mock.calls.filter(([command]) => command !== "get_installer_locale"))
      .toHaveLength(0);
    fireEvent.click(screen.getByRole("button", { name: "Check environment" }));
    await waitFor(() => {
      expect(invoke.mock.calls.filter(([command]) => command === "probe_runtime_status"))
        .toHaveLength(1);
    });
    expect(invoke.mock.calls.filter(([command]) => command === "probe_system_prerequisites"))
      .toHaveLength(1);
    expect(invoke.mock.calls.filter(([command]) => command === "start_runtime"))
      .toHaveLength(1);
    await waitFor(() => {
      expect(screen.getByRole("button", { name: "Check environment" }))
        .not.toBeDisabled();
    });
    fireEvent.click(screen.getByRole("button", { name: "Close settings" }));

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

    fireEvent.click(screen.getByRole("button", { name: "Settings" }));
    fireEvent.click(screen.getByRole("button", { name: "Check environment" }));

    expect(await screen.findByText("Environment unavailable")).toBeInTheDocument();
    expect(screen.getByText("DroneDreamRuntime is not installed."))
      .toBeInTheDocument();
    expect(invoke.mock.calls.filter(
      ([command]) => command === "probe_runtime_status",
    )).toHaveLength(initialRuntimeProbeCount + 1);
    expect(screen.getByRole("progressbar", { name: "Startup readiness progress" }))
      .toHaveAttribute("aria-valuenow", "99");

    router.dispose();
  });
});
