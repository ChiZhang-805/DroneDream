import { fireEvent, render, screen, within } from "@testing-library/react";
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
      children: [
        { path: "dashboard", element: <div>Dashboard content</div> },
        { path: "desktop/setup", element: <div>Runtime Base upgrade</div> },
      ],
    },
  ], { initialEntries: ["/dashboard"] });
  const page = render(
    <I18nProvider>
      <RouterProvider router={router} />
    </I18nProvider>,
  );
  return { ...page, router };
}

async function openRuntimeSettings(locale: "en" | "zh-CN" = "en") {
  fireEvent.click(screen.getByRole("button", {
    name: locale === "zh-CN" ? "设置" : "Settings",
  }));
  const quickSettings = screen.getByRole("dialog", {
    name: locale === "zh-CN" ? "设置" : "Settings",
  });
  fireEvent.click(within(quickSettings).getByRole("button", {
    name: /Runtime/,
  }));
  return screen.findByRole("region", {
    name: locale === "zh-CN" ? "设置" : "Settings",
  });
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

  it("reserves the account-adjacent download action for application updates", () => {
    updaterState.current = {
      ...updaterState.current,
      status: "componentAvailable",
      componentUpdates: {
        catalogSequence: 1,
        generatedAt: "2026-08-16T00:00:00Z",
        expiresAt: "2026-08-23T00:00:00Z",
        candidates: [],
      },
    };
    installReadyDesktopBridge();
    window.history.replaceState(null, "", "/?docsPreview=1");
    const { router } = renderDashboard();

    expect(document.querySelector(".app-update-button")).toBeNull();

    router.dispose();
  });

  it("keeps generic update failures in settings without showing a download icon", async () => {
    const checkForUpdates = vi.fn(async () => undefined);
    updaterState.current = {
      ...updaterState.current,
      status: "error",
      error: "Update service unavailable",
      checkForUpdates,
    };
    installReadyDesktopBridge();
    window.history.replaceState(null, "", "/?docsPreview=1");
    const { router } = renderDashboard();

    expect(screen.queryByRole("button", { name: "Account options" })).toBeNull();
    expect(document.querySelector(".app-update-button")).toBeNull();

    const dialog = await openRuntimeSettings();
    fireEvent.click(within(dialog).getByRole("button", { name: "Retry" }));
    expect(checkForUpdates).toHaveBeenCalledOnce();

    router.dispose();
  });

  it("replaces the download icon with live application download progress", () => {
    updaterState.current = {
      ...updaterState.current,
      status: "downloading",
      progress: 42,
    };
    installReadyDesktopBridge();
    window.history.replaceState(null, "", "/?docsPreview=1");
    const { router } = renderDashboard();

    const progress = screen.getByRole("button", { name: /42%/ });
    expect(progress).toBeDisabled();
    expect(progress).toHaveTextContent("42%");
    expect(progress.querySelector("svg")).toBeNull();

    router.dispose();
  });

  it("holds at 100% while the completed update exits and relaunches", () => {
    updaterState.current = {
      ...updaterState.current,
      status: "installing",
      progress: 100,
    };
    installReadyDesktopBridge();
    window.history.replaceState(null, "", "/?docsPreview=1");
    const { router } = renderDashboard();

    const progress = screen.getByRole("button", { name: /100%/ });
    expect(progress).toBeDisabled();
    expect(progress).toHaveTextContent("100%");

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

describe("Settings update center", () => {
  it("checks again from the current state and keeps environment checks separate", async () => {
    const checkForUpdates = vi.fn(async () => undefined);
    updaterState.current = { ...updaterState.current, checkForUpdates };
    installReadyDesktopBridge();
    window.history.replaceState(null, "", "/?docsPreview=1");
    const { router } = renderDashboard();

    const dialog = await openRuntimeSettings();
    expect(within(dialog).getByRole("heading", { name: "Software updates" })).toBeVisible();
    expect(within(dialog).getByRole("status", {
      name: "software version state: up-to-date",
    })).toBeVisible();
    fireEvent.click(within(dialog).getByRole("button", { name: "Check for updates" }));

    expect(checkForUpdates).toHaveBeenCalledOnce();
    expect(within(dialog).getByRole("button", { name: "Check environment" })).toBeEnabled();
    router.dispose();
  });

  it("shows required application updates and invokes the signed installer", async () => {
    const installAvailableUpdate = vi.fn(async () => undefined);
    updaterState.current = {
      ...updaterState.current,
      status: "available",
      availableVersion: "1.0.1",
      updateRequired: true,
      installAvailableUpdate,
    };
    installReadyDesktopBridge();
    window.history.replaceState(null, "", "/?docsPreview=1");
    const { router } = renderDashboard();

    const dialog = await openRuntimeSettings();
    expect(within(dialog).getByRole("status", {
      name: "software version state: old-version · v1.0.1",
    })).toBeVisible();
    fireEvent.click(within(dialog).getByRole("button", { name: "Install update" }));

    expect(installAvailableUpdate).toHaveBeenCalledOnce();
    router.dispose();
  });

  it("summarizes the signed pack version and installs the selected update set", async () => {
    const installComponentUpdates = vi.fn(async () => undefined);
    updaterState.current = {
      ...updaterState.current,
      status: "componentAvailable",
      updateRequired: true,
      componentUpdates: {
        catalogSequence: 2,
        generatedAt: "2026-08-23T00:00:00Z",
        expiresAt: "2026-08-30T00:00:00Z",
        candidates: [{
          componentId: "capability-pack",
          version: "1.2.0",
          releaseSequence: 12,
          urgency: "required",
          installMode: "user-confirmed",
          dependencies: [],
          packId: `sha256:${"5".repeat(64)}`,
          installedVersion: "1.1.0",
          installedReleaseSequence: 11,
          available: true,
        }],
      },
      installComponentUpdates,
    };
    installReadyDesktopBridge();
    window.history.replaceState(null, "", "/?docsPreview=1");
    const { router } = renderDashboard();

    const dialog = await openRuntimeSettings();
    expect(within(dialog).getByRole("status", {
      name: "software version state: old-version · v1.2.0",
    })).toBeVisible();
    fireEvent.click(within(dialog).getByRole("button", { name: "Install pack updates" }));

    expect(installComponentUpdates).toHaveBeenCalledOnce();
    router.dispose();
  });

  it("renders application download progress", async () => {
    updaterState.current = {
      ...updaterState.current,
      status: "downloading",
      progress: 42,
    };
    installReadyDesktopBridge();
    window.history.replaceState(null, "", "/?docsPreview=1");
    const { router } = renderDashboard();

    const dialog = await openRuntimeSettings();
    expect(within(dialog).getByRole("progressbar", { name: "Update progress" }))
      .toHaveValue(42);
    expect(within(dialog).getByRole("status", {
      name: "software version state: downloading · 42%",
    })).toBeVisible();
    router.dispose();
  });

  it("opens the Runtime Base upgrade entry for an incompatible manager", async () => {
    updaterState.current = {
      ...updaterState.current,
      status: "runtimeBaseRequired",
      updateRequired: true,
    };
    installReadyDesktopBridge();
    window.history.replaceState(null, "", "/?docsPreview=1");
    const { router } = renderDashboard();

    const dialog = await openRuntimeSettings();
    fireEvent.click(within(dialog).getByRole("button", {
      name: "Open Runtime Base upgrade",
    }));

    expect(router.state.location.pathname).toBe("/desktop/setup");
    router.dispose();
  });

  it("renders independently authored Simplified Chinese update copy", async () => {
    installReadyDesktopBridge();
    window.localStorage.setItem("drone-dream:locale", "zh-CN");
    window.history.replaceState(null, "", "/?docsPreview=1");
    const { router } = renderDashboard();

    const dialog = await openRuntimeSettings("zh-CN");
    expect(within(dialog).getByRole("heading", { name: "软件更新" })).toBeVisible();
    expect(within(dialog).getByRole("status", {
      name: "软件版本状态： 已是最新版本",
    })).toBeVisible();
    expect(within(dialog).getByRole("button", { name: "检查更新" })).toBeEnabled();
    router.dispose();
  });
});
