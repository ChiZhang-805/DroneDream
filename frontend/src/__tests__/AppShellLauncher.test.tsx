import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { RouterProvider, createMemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import { AppShell } from "../AppShell";
import { I18nProvider } from "../i18n/I18nProvider";

const requiredComponentIds = [
  "wsl-runtime",
  "host-ownership",
  "runtime-manifest",
  "local-backend",
  "px4",
  "gazebo",
] as const;

function installDesktopBridge() {
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
            components: requiredComponentIds.map((id) => ({
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

function renderLauncher() {
  const router = createMemoryRouter([
    {
      path: "/",
      element: <AppShell />,
      children: [{ path: "desktop/setup", element: <div>Launcher content</div> }],
    },
  ], { initialEntries: ["/desktop/setup"] });
  const page = render(
    <I18nProvider>
      <RouterProvider router={router} />
    </I18nProvider>,
  );
  return { ...page, router };
}

afterEach(() => {
  delete window.__TAURI__;
  window.localStorage.clear();
});

describe("desktop launcher chrome", () => {
  it("moves language selection into an accessible settings dialog", async () => {
    window.localStorage.setItem("drone-dream:locale", "en");
    installDesktopBridge();
    const { router } = renderLauncher();

    expect(screen.queryByRole("combobox", { name: "Language" })).not.toBeInTheDocument();
    const settings = screen.getByRole("button", { name: "Settings" });
    expect(settings).toHaveAttribute("aria-expanded", "false");

    fireEvent.click(settings);
    expect(settings).toHaveAttribute("aria-expanded", "true");
    const dialog = screen.getByRole("dialog", { name: "Settings" });
    expect(dialog).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "English" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );

    fireEvent.click(screen.getByRole("button", { name: "Simplified Chinese" }));
    await waitFor(() => {
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
      expect(window.localStorage.getItem("drone-dream:locale")).toBe("zh-CN");
    });
    expect(screen.getByRole("button", { name: "设置" })).toHaveFocus();

    fireEvent.click(screen.getByRole("button", { name: "设置" }));
    expect(screen.getByRole("dialog", { name: "设置" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "英文" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "简体中文" })).toBeInTheDocument();
    expect(screen.queryByText("English")).not.toBeInTheDocument();
    expect(screen.queryByText("Simplified Chinese")).not.toBeInTheDocument();

    router.dispose();
  });

  it("closes the settings dialog with Escape and restores focus", () => {
    window.localStorage.setItem("drone-dream:locale", "en");
    installDesktopBridge();
    const { router } = renderLauncher();
    const settings = screen.getByRole("button", { name: "Settings" });

    fireEvent.click(settings);
    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(settings).toHaveFocus();

    router.dispose();
  });
});
