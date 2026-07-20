import { fireEvent, render, screen } from "@testing-library/react";
import { RouterProvider, createMemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import { AppShell } from "../AppShell";
import { I18nProvider } from "../i18n/I18nProvider";
import { resetDesktopReadinessSession } from "../desktop/readiness";

const updaterMock = vi.hoisted(() => ({
  status: "current" as "current" | "available",
  availableVersion: null as string | null,
  progress: null as number | null,
  error: null as string | null,
  checkForUpdates: vi.fn(async () => undefined),
  installAvailableUpdate: vi.fn(async () => undefined),
}));

vi.mock("../desktop/updater", () => ({
  useAppUpdater: () => ({
    ...updaterMock,
    desktopRuntime: true,
  }),
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
  updaterMock.status = "current";
  updaterMock.availableVersion = null;
  updaterMock.checkForUpdates.mockClear();
  updaterMock.installAvailableUpdate.mockClear();
  resetDesktopReadinessSession();
  delete window.__TAURI__;
  window.localStorage.clear();
});

describe("desktop updater control", () => {
  it("uses the purple current-version control to run a manual check", () => {
    installReadyDesktopBridge();
    const { router } = renderDashboard();

    const pill = screen.getByText("DroneDream 1.0.0").closest(".app-version-pill");
    expect(pill).not.toHaveClass("is-update-available");
    fireEvent.click(screen.getByRole("button", {
      name: "DroneDream is up to date. Click to check again.",
    }));
    expect(updaterMock.checkForUpdates).toHaveBeenCalledOnce();

    router.dispose();
  });

  it("turns yellow and installs the explicitly published newer version", () => {
    updaterMock.status = "available";
    updaterMock.availableVersion = "1.0.1";
    installReadyDesktopBridge();
    const { router } = renderDashboard();

    const pill = screen.getByText("DroneDream 1.0.0").closest(".app-version-pill");
    expect(pill).toHaveClass("is-update-available");
    fireEvent.click(screen.getByRole("button", {
      name: "Version 1.0.1 is available. Click to update.",
    }));
    expect(updaterMock.installAvailableUpdate).toHaveBeenCalledOnce();

    router.dispose();
  });
});
