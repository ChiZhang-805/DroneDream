import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

const coreState = vi.hoisted(() => ({ value: "ready" as "ready" | "checking" }));
vi.mock("../desktop/agentCoreStartup", () => ({
  getAgentCoreStartupState: () => coreState.value,
  subscribeAgentCoreStartup: () => () => undefined,
  checkAgentCoreStartup: vi.fn(async () => undefined),
}));

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

import { AppShell } from "../AppShell";
import { I18nProvider } from "../i18n/I18nProvider";
import { DesktopSetup } from "../pages/DesktopSetup";
import { resetDesktopReadinessSession } from "../desktop/readiness";
import { openAppSettings } from "../appSettings";

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

async function openSettingsWorkspace() {
  openAppSettings("general");
  return screen.findByRole("region", { name: /Settings|设置/ });
}

describe("desktop startup access", () => {
  afterEach(() => {
    resetDesktopReadinessSession();
    coreState.value = "ready";
    runtimeSessionContractMocks.verify.mockReset();
    runtimeSessionContractMocks.verify.mockImplementation(async (report) => report);
    delete window.__TAURI__;
    window.localStorage.clear();
    window.sessionStorage.clear();
    vi.restoreAllMocks();
  });

  it.each(["/dashboard", "/history", "/autonomy"])("redirects an unqualified direct entry %s to the launcher", async (entry) => {
    window.__TAURI__ = { core: { invoke: vi.fn(async (command: string) => {
      if (command === "get_installer_locale") return "en";
      throw new Error(`Unexpected command: ${command}`);
    }) } };
    coreState.value = "checking";
    const mounted = vi.fn();
    function InternalPage() { mounted(); return <div>Internal workspace</div>; }
    const router = createMemoryRouter([{
      path: "/", element: <AppShell />, children: [
        { path: entry.slice(1), element: <InternalPage /> },
        { path: "desktop/setup", element: <div>Startup recovery</div> },
      ],
    }], { initialEntries: [entry] });
    render(<I18nProvider><RouterProvider router={router} /></I18nProvider>);
    expect(await screen.findByText("Startup recovery")).toBeInTheDocument();
    expect(router.state.location.pathname).toBe("/desktop/setup");
    expect(mounted).not.toHaveBeenCalled();
    expect(screen.queryByRole("navigation", { name: "Primary navigation" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Settings" })).toBeEnabled();
    router.dispose();
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
      name: "Sign in",
    })).toBeEnabled();
    expect(screen.queryByRole("button", { name: "Start runtime" }))
      .not.toBeInTheDocument();
    expect(invoke.mock.calls.filter(([command]) => command === "start_runtime"))
      .toHaveLength(1);

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
    expect(screen.getByLabelText("Email")).toBeInTheDocument();
    expect(screen.queryByRole("progressbar")).not.toBeInTheDocument();

    router.dispose();
  }, 12_000);
});
