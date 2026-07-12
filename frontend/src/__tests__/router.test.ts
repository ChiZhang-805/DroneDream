import { afterEach, describe, expect, it, vi } from "vitest";

const requiredComponentIds = [
  "wsl-runtime",
  "host-ownership",
  "runtime-manifest",
  "local-backend",
  "px4",
  "gazebo",
] as const;

const readyPrerequisites = {
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
  diagnostics: [],
};

function installDesktopBridge(runtime: unknown = readyRuntime) {
  const invoke = vi.fn(async (command: string) => {
    if (command === "probe_system_prerequisites") return readyPrerequisites;
    if (command === "probe_runtime_status") return runtime;
    throw new Error(`Unexpected command: ${command}`);
  });
  window.__TAURI__ = { core: { invoke } };
  return invoke;
}

afterEach(() => {
  window.history.replaceState(null, "", "/");
});

describe("environment-aware routing", () => {
  it("uses hash routing and allows guarded routes only after a fresh ready probe", async () => {
    const invoke = installDesktopBridge();
    window.history.replaceState(null, "", "/#/desktop/setup");
    vi.resetModules();
    const { router } = await import("../router");

    expect(router.state.location.pathname).toBe("/desktop/setup");
    await router.navigate("/dashboard");
    expect(window.location.hash).toBe("#/dashboard");
    expect(invoke.mock.calls.map(([command]) => command).sort()).toEqual([
      "probe_runtime_status",
      "probe_system_prerequisites",
    ]);

    router.dispose();
  });

  it("guards every desktop business route", async () => {
    installDesktopBridge();
    window.history.replaceState(null, "", "/#/desktop/setup");
    vi.resetModules();
    const { router } = await import("../router");
    const children = router.routes[0]?.children ?? [];
    const guardedPaths = [
      "dashboard",
      "jobs/new",
      "jobs/:jobId",
      "trials/:trialId",
      "history",
      "batches",
      "batches/new",
      "batches/:batchId",
      "compare",
      "ece498",
    ];

    for (const path of guardedPaths) {
      expect(children.find((route) => route.path === path)?.loader, path)
        .toEqual(expect.any(Function));
    }
    expect(children.find((route) => route.path === "desktop/setup")?.loader)
      .toBeUndefined();

    router.dispose();
  });

  it("redirects direct desktop navigation when readiness is missing or uncertain", async () => {
    const missingRuntime = {
      ...readyRuntime,
      installed: false,
      running: false,
      ready: false,
      version: null,
      dataRoot: null,
      components: readyRuntime.components.map((component) => ({
        ...component,
        status: "missing",
      })),
    };
    const invoke = installDesktopBridge(missingRuntime);
    window.history.replaceState(null, "", "/#/desktop/setup");
    vi.resetModules();
    const { router } = await import("../router");

    await router.navigate("/jobs/new");
    expect(router.state.location.pathname).toBe("/desktop/setup");
    expect(window.location.hash).toBe("#/desktop/setup");
    expect(invoke).toHaveBeenCalledTimes(2);

    router.dispose();
  });

  it("fails closed when either desktop readiness command rejects", async () => {
    window.__TAURI__ = {
      core: {
        invoke: vi.fn(async (command: string) => {
          if (command === "probe_system_prerequisites") return readyPrerequisites;
          throw new Error("runtime probe unavailable");
        }),
      },
    };
    window.history.replaceState(null, "", "/#/desktop/setup");
    vi.resetModules();
    const { router } = await import("../router");

    await router.navigate("/history");
    expect(router.state.location.pathname).toBe("/desktop/setup");

    router.dispose();
  });

  it("keeps browser routes unguarded", async () => {
    delete window.__TAURI__;
    window.history.replaceState(null, "", "/desktop/setup");
    vi.resetModules();
    const { router } = await import("../router");

    expect(router.state.location.pathname).toBe("/desktop/setup");
    await router.navigate("/jobs/new");
    expect(window.location.pathname).toBe("/jobs/new");
    expect(window.location.hash).toBe("");

    router.dispose();
  });

  it("recovers unknown desktop and browser routes inside the product", async () => {
    installDesktopBridge();
    window.history.replaceState(null, "", "/#/desktop/setup");
    vi.resetModules();
    const desktop = await import("../router");
    await desktop.router.navigate("/removed-route");
    expect(desktop.router.state.location.pathname).toBe("/desktop/setup");
    desktop.router.dispose();

    delete window.__TAURI__;
    window.history.replaceState(null, "", "/history");
    vi.resetModules();
    const browser = await import("../router");
    await browser.router.navigate("/removed-route");
    expect(browser.router.state.location.pathname).toBe("/");
    expect(window.location.hash).toBe("");
    browser.router.dispose();
  });
});
