import { fireEvent, render, screen } from "@testing-library/react";
import type { ReactNode } from "react";
import { RouterProvider, createMemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import { AppShell } from "../AppShell";
import { I18nProvider } from "../i18n/I18nProvider";
import { resetDesktopReadinessSession } from "../desktop/readiness";

const updaterState = vi.hoisted(() => ({
  current: {
    status: "current",
    availableVersion: null as string | null,
    updateRequired: false,
    progress: null as number | null,
    error: null as string | null,
    enginePack: null,
    componentUpdates: null as import("../desktop/bridge").ComponentUpdateReport | null,
    desktopRuntime: true,
    checkForUpdates: vi.fn(async () => undefined),
    installAvailableUpdate: vi.fn(async () => undefined),
    installComponentUpdates: vi.fn(async () => undefined),
    reconcileEnginePack: vi.fn(async () => undefined),
    reconcileComponentPacks: vi.fn(async () => undefined),
  },
}));

vi.mock("../desktop/updaterContext", () => ({
  AppUpdaterProvider: ({ children }: { children: ReactNode }) => children,
  useAppUpdaterState: () => updaterState.current,
}));

const componentIds = [
  "wsl-runtime",
  "host-ownership",
  "runtime-manifest",
  "local-backend",
  "px4",
  "gazebo",
];

function installReadyDesktopBridge() {
  window.__TAURI__ = {
    core: {
      invoke: vi.fn(async (command: string) => {
        if (command === "probe_system_prerequisites") {
          return {
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
        }
        if (command === "probe_runtime_status") {
          return {
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
        }
        throw new Error(`Unexpected command: ${command}`);
      }),
    },
  };
}

function renderDashboard() {
  const router = createMemoryRouter([
    {
      path: "/",
      element: <AppShell />,
      children: [{ path: "dashboard", element: <div>Dashboard content</div> }],
    },
  ], { initialEntries: ["/dashboard"] });
  const page = render(
    <I18nProvider>
      <RouterProvider router={router} />
    </I18nProvider>,
  );
  return { ...page, router };
}

afterEach(() => {
  resetDesktopReadinessSession();
  delete window.__TAURI__;
  window.localStorage.clear();
  window.history.replaceState(null, "", "/");
  updaterState.current = {
    ...updaterState.current,
    status: "current",
    availableVersion: null,
    updateRequired: false,
    progress: null,
    error: null,
    enginePack: null,
    componentUpdates: null,
    checkForUpdates: vi.fn(async () => undefined),
    installAvailableUpdate: vi.fn(async () => undefined),
    installComponentUpdates: vi.fn(async () => undefined),
    reconcileEnginePack: vi.fn(async () => undefined),
    reconcileComponentPacks: vi.fn(async () => undefined),
  };
});

describe("workspace sidebar version module", () => {
  it("does not render the removed version/update pill", () => {
    installReadyDesktopBridge();
    window.history.replaceState(null, "", "/?docsPreview=1");
    const { router } = renderDashboard();

    expect(screen.queryByText("DroneDream 1.0.0")).not.toBeInTheDocument();
    expect(document.querySelector(".app-version-pill")).toBeNull();
    expect(screen.getByRole("button", { name: "Account" })).toBeVisible();
    expect(screen.queryByRole("button", { name: "Update DroneDream" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Account options" })).toBeNull();

    router.dispose();
  });

  it("shows a compact account-adjacent update action only when an update is ready", () => {
    const installAvailableUpdate = vi.fn(async () => undefined);
    updaterState.current = {
      ...updaterState.current,
      status: "available",
      availableVersion: "1.0.0",
      installAvailableUpdate,
    };
    installReadyDesktopBridge();
    window.history.replaceState(null, "", "/?docsPreview=1");
    const { router } = renderDashboard();

    const update = screen.getByRole("button", { name: "Update DroneDream" });
    expect(update).toHaveClass("app-update-button");
    expect(screen.queryByRole("button", { name: "Account options" })).toBeNull();
    fireEvent.click(update);
    expect(installAvailableUpdate).toHaveBeenCalledOnce();

    router.dispose();
  });

  it("uses the same account-adjacent action for signed workflow and asset updates", () => {
    const installComponentUpdates = vi.fn(async () => undefined);
    updaterState.current = {
      ...updaterState.current,
      status: "componentAvailable",
      componentUpdates: {
        catalogSequence: 1,
        generatedAt: "2026-08-16T00:00:00Z",
        expiresAt: "2026-08-23T00:00:00Z",
        candidates: [],
      },
      installComponentUpdates,
    };
    installReadyDesktopBridge();
    window.history.replaceState(null, "", "/?docsPreview=1");
    const { router } = renderDashboard();

    const update = screen.getByRole("button", {
      name: "Update DroneDream workflows and assets",
    });
    fireEvent.click(update);
    expect(installComponentUpdates).toHaveBeenCalledOnce();

    router.dispose();
  });

  it("keeps the account options affordance when an update check fails without finding an update", () => {
    updaterState.current = {
      ...updaterState.current,
      status: "error",
      error: "Update service unavailable",
    };
    installReadyDesktopBridge();
    window.history.replaceState(null, "", "/?docsPreview=1");
    const { router } = renderDashboard();

    expect(screen.queryByRole("button", { name: "Account options" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Retry DroneDream update" })).toBeNull();

    router.dispose();
  });

  it("keeps the account name action independent from the trailing update slot", () => {
    updaterState.current = {
      ...updaterState.current,
      status: "available",
      availableVersion: "1.0.0",
    };
    installReadyDesktopBridge();
    window.history.replaceState(null, "", "/?docsPreview=1");
    const { router } = renderDashboard();

    fireEvent.click(screen.getByRole("button", { name: "Account" }));
    expect(screen.getByRole("menu", { name: "Account" })).toBeVisible();
    expect(updaterState.current.installAvailableUpdate).not.toHaveBeenCalled();

    router.dispose();
  });
});
