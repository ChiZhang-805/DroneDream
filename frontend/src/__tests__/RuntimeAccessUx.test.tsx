import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import { apiClient } from "../api/client";
import { AppShell } from "../AppShell";
import { I18nProvider } from "../i18n/I18nProvider";
import { Dashboard } from "../pages/Dashboard";
import { DesktopSetup } from "../pages/DesktopSetup";
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

const stoppedRuntime = {
  ...readyRuntime,
  running: false,
  ready: false,
  components: readyRuntime.components.map((component) => ({
    ...component,
    status: component.id === "wsl-runtime" ? "ready" : "stopped",
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
    vi.restoreAllMocks();
  });

  it("keeps read-only pages visible, marks runtime routes, and avoids backend calls", async () => {
    window.__TAURI__ = {
      core: {
        invoke: vi.fn(async (command: string) => {
          if (command === "probe_system_prerequisites") return prerequisites;
          if (command === "probe_runtime_status") return missingRuntime;
          throw new Error(`Unexpected command: ${command}`);
        }),
      },
    };
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
    expect(screen.getByRole("link", { name: "History / Reports" }))
      .not.toHaveClass("runtime-locked");
    expect(screen.getByRole("link", { name: "ECE498" }))
      .not.toHaveClass("runtime-locked");
    expect(screen.getByRole("link", { name: "New Experiment" }))
      .toHaveClass("runtime-locked");
    expect(screen.getByRole("link", { name: "New Batch" }))
      .toHaveClass("runtime-locked");
    expect(screen.getByRole("link", { name: "Batches" }))
      .toHaveClass("runtime-locked");
    expect(listJobs).not.toHaveBeenCalled();

    await router.navigate("/history");
    await waitFor(() => {
      expect(screen.getByText("Runtime data is not available yet")).toBeInTheDocument();
    });
    expect(listJobs).not.toHaveBeenCalled();

    router.dispose();
    queryClient.clear();
  });

  it("invalidates a previous ready state when only the setup query changes", async () => {
    let runtimeProbeCount = 0;
    let resolveSecondProbe: (value: typeof missingRuntime) => void = () => undefined;
    const secondProbe = new Promise<typeof missingRuntime>((resolve) => {
      resolveSecondProbe = resolve;
    });
    window.__TAURI__ = {
      core: {
        invoke: vi.fn(async (command: string) => {
          if (command === "probe_system_prerequisites") return prerequisites;
          if (command === "probe_runtime_status") {
            runtimeProbeCount += 1;
            return runtimeProbeCount === 1 ? readyRuntime : secondProbe;
          }
          throw new Error(`Unexpected command: ${command}`);
        }),
      },
    };
    const router = createMemoryRouter([
      {
        path: "/",
        element: <AppShell />,
        children: [
          { path: "desktop/setup", element: <div>Setup placeholder</div> },
        ],
      },
    ], { initialEntries: ["/desktop/setup"] });

    render(
      <I18nProvider>
        <RouterProvider router={router} />
      </I18nProvider>,
    );

    expect(await screen.findByText("Ready for local tuning")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "New Experiment" }))
      .not.toBeInTheDocument();

    await router.navigate("/desktop/setup?required=batch");
    await waitFor(() => {
      expect(screen.getByText("Checking…")).toBeInTheDocument();
    });
    expect(runtimeProbeCount).toBe(2);

    resolveSecondProbe(missingRuntime);
    await waitFor(() => {
      expect(screen.getByText("Runtime")).toBeInTheDocument();
    });

    router.dispose();
  });

  it("syncs a manual setup recheck from ready to stopped into the global gate", async () => {
    let currentRuntime = readyRuntime;
    let pendingRuntimeProbe: Promise<typeof stoppedRuntime> | null = null;
    window.__TAURI__ = {
      core: {
        invoke: vi.fn(async (command: string) => {
          if (command === "get_installer_runtime_intent") {
            return { status: "none", mode: null, targetRoot: null, message: null };
          }
          if (command === "probe_system_prerequisites") return prerequisites;
          if (command === "probe_runtime_status") {
            return pendingRuntimeProbe ?? currentRuntime;
          }
          throw new Error(`Unexpected command: ${command}`);
        }),
      },
    };
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
    expect(screen.queryByRole("link", { name: "New Experiment" }))
      .not.toBeInTheDocument();
    expect(screen.queryByText("This feature needs DroneDreamRuntime"))
      .not.toBeInTheDocument();

    let resolveRuntimeProbe: (value: typeof stoppedRuntime) => void = () => undefined;
    pendingRuntimeProbe = new Promise<typeof stoppedRuntime>((resolve) => {
      resolveRuntimeProbe = resolve;
    });
    fireEvent.click(screen.getByRole("button", { name: "Check again" }));
    expect(screen.getByText("This feature needs DroneDreamRuntime"))
      .toBeInTheDocument();

    currentRuntime = stoppedRuntime;
    pendingRuntimeProbe = null;
    resolveRuntimeProbe(stoppedRuntime);

    expect(await screen.findByText("DroneDreamRuntime · Installed · Stopped"))
      .toBeInTheDocument();
    await waitFor(() => {
      expect(screen.getByText("Runtime")).toBeInTheDocument();
    });

    router.dispose();
  });
});
