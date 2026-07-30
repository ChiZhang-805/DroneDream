import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import type { ReactNode } from "react";
import { RouterProvider, createMemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

const launcherAuthState = vi.hoisted(() => ({
  current: {
    configured: false,
    loading: false,
    account: null as null | {
      id: string;
      email: string | null;
      displayName: string;
      avatarUrl: string | null;
    },
  },
}));

vi.mock("../features/auth/AuthContext", async (importOriginal) => {
  const original =
    await importOriginal<typeof import("../features/auth/AuthContext")>();
  const unavailable = async () => undefined;
  return {
    ...original,
    AuthProvider: ({ children }: { children: ReactNode }) => children,
    useAuth: () => ({
      ...launcherAuthState.current,
      googleEnabled: false,
      appleEnabled: false,
      signInWithPassword: unavailable,
      sendRegistrationCode: unavailable,
      verifyRegistrationCode: unavailable,
      signInWithProvider: unavailable,
      updateDisplayName: unavailable,
      updateAvatar: unavailable,
      signOut: unavailable,
    }),
  };
});

import { AppShell } from "../AppShell";
import { I18nProvider } from "../i18n/I18nProvider";
import { resetDesktopReadinessSession } from "../desktop/readiness";

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
  resetDesktopReadinessSession();
  delete window.__TAURI__;
  window.localStorage.clear();
  window.sessionStorage.clear();
  launcherAuthState.current = {
    configured: false,
    loading: false,
    account: null,
  };
});

describe("desktop launcher chrome", () => {
  it("does not expose a header sign-in control on the startup launcher", () => {
    launcherAuthState.current = {
      configured: true,
      loading: false,
      account: null,
    };
    installDesktopBridge();
    const { router } = renderLauncher();

    expect(screen.queryByRole("button", { name: "Account" }))
      .not.toBeInTheDocument();
    expect(document.querySelector(".launcher-account-button"))
      .not.toBeInTheDocument();
    expect(screen.queryByRole("dialog", { name: "Sign in to DroneDream" }))
      .not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Settings" })).toBeInTheDocument();

    router.dispose();
  });
  it("moves language selection into an accessible settings dialog", async () => {
    window.localStorage.setItem("drone-dream:locale", "en");
    installDesktopBridge();
    const { router } = renderLauncher();

    const checked = await screen.findByText("Checked");
    expect(checked.closest(".launcher-runtime-indicator")).toHaveClass("is-checked");
    expect(screen.queryByRole("combobox", { name: "Language" })).not.toBeInTheDocument();
    const settings = screen.getByRole("button", { name: "Settings" });
    expect(settings).toHaveAttribute("aria-expanded", "false");

    fireEvent.click(settings);
    expect(settings).toHaveAttribute("aria-expanded", "true");
    expect(document.body).toHaveStyle({ overflow: "hidden" });
    expect(document.querySelector(".launcher-main")).toHaveProperty("inert", true);
    const dialog = screen.getByRole("dialog", { name: "Settings" });
    expect(dialog).toBeInTheDocument();
    expect(within(dialog).queryByText("DroneDream")).not.toBeInTheDocument();
    expect(within(dialog).queryByText("Interface language")).not.toBeInTheDocument();
    expect(within(dialog).queryByText(
      "Run a full Windows, WSL, backend, PX4, and Gazebo check. DroneDream reuses the result until you check again or a real run detects a problem.",
    )).not.toBeInTheDocument();
    expect(within(dialog).getByRole("button", { name: "English" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    expect(within(dialog).getByRole("button", { name: "English" }).querySelector("svg"))
      .toBeInTheDocument();
    expect(within(dialog).getByRole("button", { name: "简体中文" }).querySelector("svg"))
      .toBeInTheDocument();
    expect(within(dialog).getByRole("button", { name: /Included allowance/ }))
      .toHaveAttribute("aria-pressed", "true");
    expect(within(dialog).getByRole("link", { name: "Manage subscription" }))
      .toHaveAttribute("href", "https://getdronedream.com/pricing/");
    fireEvent.click(within(dialog).getByRole("button", { name: /Use my API key/ }));
    expect(within(dialog).getByLabelText("Model profile")).toHaveValue("default");

    fireEvent.change(within(dialog).getByLabelText("Model provider"), {
      target: { value: "qwen" },
    });
    expect(within(dialog).getByLabelText("Model name")).toHaveValue("qwen-plus");
    expect(within(dialog).getByLabelText("Compatible API base URL")).toHaveValue(
      "https://dashscope.aliyuncs.com/compatible-mode/v1",
    );
    fireEvent.change(within(dialog).getByLabelText("Model API key"), {
      target: { value: "session-only-key" },
    });
    await waitFor(() => {
      expect(window.sessionStorage.getItem("dronedream:model-access-key:v1"))
        .toBeNull();
      expect(window.localStorage.getItem("dronedream:model-access:v1"))
        .toContain("qwen-plus");
      expect(window.localStorage.getItem("dronedream:model-access:v1"))
        .not.toContain("session-only-key");
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "Add profile" }));
    expect(within(dialog).getByLabelText("Model profile")).not.toHaveValue("default");
    expect(within(dialog).getByLabelText("Model provider")).toHaveValue("custom");
    fireEvent.change(within(dialog).getByLabelText("Model API key"), {
      target: { value: "second-memory-only-key" },
    });
    await waitFor(() => {
      expect(window.localStorage.getItem("dronedream:model-access:v1"))
        .not.toContain("second-memory-only-key");
    });

    fireEvent.click(within(dialog).getByRole("button", { name: "简体中文" }));
    await waitFor(() => {
      expect(window.localStorage.getItem("drone-dream:locale")).toBe("zh-CN");
    });
    const chineseDialog = screen.getByRole("dialog", { name: "设置" });
    expect(within(chineseDialog).getByRole("button", { name: "English" })).toBeInTheDocument();
    expect(within(chineseDialog).getByRole("button", { name: "简体中文" })).toBeInTheDocument();
    expect(within(chineseDialog).getByRole("button", { name: "检查运行环境" }))
      .toBeInTheDocument();
    expect(within(chineseDialog).getByText("运行环境正常")).toBeInTheDocument();
    expect(within(chineseDialog).queryByText("界面语言")).not.toBeInTheDocument();
    expect(within(chineseDialog).queryByText("Simplified Chinese")).not.toBeInTheDocument();
    expect(within(chineseDialog).queryByText(
      "全面检查 Windows、WSL、本地后端、PX4 与 Gazebo。检查结果会在本次软件运行期间复用，除非你手动重检或真实运行发现异常。",
    )).not.toBeInTheDocument();

    fireEvent.click(within(chineseDialog).getByRole("button", { name: "关闭设置" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    await waitFor(() => expect(screen.getByRole("button", { name: "设置" })).toHaveFocus());
    expect(document.body).not.toHaveStyle({ overflow: "hidden" });
    expect(document.querySelector(".launcher-main")).toHaveProperty("inert", false);

    router.dispose();
  });

  it("closes the settings dialog with Escape and restores focus", async () => {
    window.localStorage.setItem("drone-dream:locale", "en");
    installDesktopBridge();
    const { router } = renderLauncher();
    const settings = screen.getByRole("button", { name: "Settings" });

    fireEvent.click(settings);
    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    await waitFor(() => expect(settings).toHaveFocus());

    router.dispose();
  });

  it("keeps keyboard focus inside the settings dialog", async () => {
    window.localStorage.setItem("drone-dream:locale", "en");
    installDesktopBridge();
    const { router } = renderLauncher();

    fireEvent.click(screen.getByRole("button", { name: "Settings" }));
    const dialog = screen.getByRole("dialog", { name: "Settings" });
    const close = within(dialog).getByRole("button", { name: "Close settings" });
    await waitFor(() => expect(close).toHaveFocus());

    fireEvent.keyDown(document, { key: "Tab", shiftKey: true });
    expect(dialog).toContainElement(document.activeElement as HTMLElement);
    expect(close).not.toHaveFocus();
    fireEvent.keyDown(document, { key: "Tab" });
    expect(close).toHaveFocus();

    router.dispose();
  });

  it("shows warning details and updates to a red result after a manual full check", async () => {
    window.localStorage.setItem("drone-dream:locale", "en");
    let runtimeProbeCount = 0;
    const readyRuntime = {
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
      diagnostics: ["Optional GPU telemetry is unavailable."],
    };
    const missingRuntime = {
      ...readyRuntime,
      installed: false,
      running: false,
      ready: false,
      dataRoot: null,
      components: readyRuntime.components.map((component) => ({
        ...component,
        status: "missing",
      })),
      diagnostics: ["Runtime installation was not found."],
    };
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
            runtimeProbeCount += 1;
            return runtimeProbeCount === 1 ? readyRuntime : missingRuntime;
          }
          throw new Error(`Unexpected command: ${command}`);
        }),
      },
    };
    const { router } = renderLauncher();

    fireEvent.click(screen.getByRole("button", { name: "Settings" }));
    expect(await screen.findByText("Ready with warnings")).toBeInTheDocument();
    fireEvent.click(screen.getByText("View details"));
    expect(screen.getByText("Optional GPU telemetry is unavailable.")).toBeInTheDocument();
    expect(screen.getByText("Optional GPU telemetry is unavailable.").closest(
      ".settings-runtime-details-scroll",
    )).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Check environment" }));
    expect(await screen.findByText("Environment unavailable")).toBeInTheDocument();
    fireEvent.click(screen.getByText("View details"));
    expect(screen.getByText("DroneDreamRuntime is not installed.")).toBeInTheDocument();
    expect(runtimeProbeCount).toBe(2);

    router.dispose();
  });
});
