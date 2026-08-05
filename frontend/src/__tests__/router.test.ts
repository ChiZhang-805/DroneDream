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
    if (command === "start_runtime") return runtime;
    throw new Error(`Unexpected command: ${command}`);
  });
  window.__TAURI__ = { core: { invoke } };
  return invoke;
}

afterEach(() => {
  window.history.replaceState(null, "", "/");
});

describe("environment-aware routing", () => {
  it("uses cached pre-workspace readiness without rechecking guarded routes", async () => {
    const invoke = installDesktopBridge();
    window.history.replaceState(null, "", "/#/desktop/setup");
    vi.resetModules();
    const { ensureOverallDesktopReadiness } = await import("../desktop/readiness");
    await ensureOverallDesktopReadiness({ autoStart: false });
    const { approveDesktopStartupGateWithoutCloudAuth } =
      await import("../desktop/startupGate");
    approveDesktopStartupGateWithoutCloudAuth();
    const { router } = await import("../router");

    expect(router.state.location.pathname).toBe("/desktop/setup");
    await router.navigate("/jobs/new");
    expect(window.location.hash).toBe("#/jobs/new");
    expect(invoke.mock.calls.map(([command]) => command).sort()).toEqual([
      "probe_runtime_status",
      "probe_system_prerequisites",
    ]);
    await router.navigate("/history");
    await router.navigate("/jobs/new");
    expect(invoke).toHaveBeenCalledTimes(2);

    router.dispose();
  });

  it("routes a true desktop cold start through the 3D launcher", async () => {
    installDesktopBridge();
    window.history.replaceState(null, "", "/#/");
    vi.resetModules();
    const { router } = await import("../router");
    const indexRoute = router.routes[0]?.children?.find((route) => route.index);
    const indexElement = (indexRoute as unknown as {
      element?: { props?: { to?: string; replace?: boolean } };
    } | undefined)?.element;

    expect(indexElement?.props?.to).toBe("/desktop/setup");
    expect(indexElement?.props?.replace).toBe(true);

    router.dispose();
  });

  it("guards runtime-backed routes while keeping preview and static pages open", async () => {
    installDesktopBridge();
    window.history.replaceState(null, "", "/#/desktop/setup");
    vi.resetModules();
    const { router } = await import("../router");
    const children = router.routes[0]?.children ?? [];
    const guardedPaths = [
      "jobs/new",
      "jobs/:jobId",
      "trials/:trialId",
      "compare",
    ];

    for (const path of guardedPaths) {
      expect(children.find((route) => route.path === path)?.loader, path)
        .toEqual(expect.any(Function));
    }
    expect(children.find((route) => route.path === "desktop/setup")?.loader)
      .toBeUndefined();
    expect(children.find((route) => route.path === "batches/*")?.loader)
      .toEqual(expect.any(Function));
    for (const path of ["dashboard", "history", "scenarios"]) {
      expect(children.find((route) => route.path === path)?.loader, path)
        .toBeUndefined();
    }
    for (const path of [
      "assistant",
      "dashboard",
      "jobs/new",
      "jobs/:jobId",
      "trials/:trialId",
      "history",
      "scenarios",
      "compare",
      "desktop/setup",
    ]) {
      const route = children.find((candidate) => candidate.path === path);
      expect(route?.lazy, path).toEqual(expect.any(Function));
      expect(route?.element, path).toBeUndefined();
    }
    expect(children.find((route) => route.path === "ece498")).toBeUndefined();

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
    expect(router.state.location.pathname).toBe("/dashboard");
    expect(router.state.location.search).toBe("?settings=runtime&required=experiment");
    expect(window.location.hash).toBe("#/dashboard?settings=runtime&required=experiment");
    expect(invoke).not.toHaveBeenCalled();

    router.dispose();
  });

  it("does not probe or start a stopped runtime from a guarded deep link", async () => {
    const stoppedRuntime = {
      ...readyRuntime,
      running: false,
      ready: false,
      components: readyRuntime.components.map((component) => ({
        ...component,
        status: component.id === "host-ownership" ? "ready" : "stopped",
      })),
    };
    const invoke = vi.fn(async (command: string) => {
      if (command === "probe_system_prerequisites") return readyPrerequisites;
      if (command === "probe_runtime_status") return stoppedRuntime;
      if (command === "start_runtime") return readyRuntime;
      throw new Error(`Unexpected command: ${command}`);
    });
    window.__TAURI__ = { core: { invoke } };
    window.history.replaceState(null, "", "/#/desktop/setup");
    vi.resetModules();
    const { router } = await import("../router");

    await router.navigate("/jobs/new");
    expect(router.state.location.pathname).toBe("/dashboard");
    expect(router.state.location.search).toBe("?settings=runtime&required=experiment");
    expect(invoke).not.toHaveBeenCalled();
    expect(invoke.mock.calls.filter(([command]) => command === "start_runtime"))
      .toHaveLength(0);

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

    await router.navigate("/jobs/new");
    expect(router.state.location.pathname).toBe("/dashboard");
    expect(router.state.location.search).toBe("?settings=runtime&required=experiment");

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
    expect(desktop.router.state.location.pathname).toBe("/dashboard");
    desktop.router.dispose();

    delete window.__TAURI__;
    window.history.replaceState(null, "", "/history");
    vi.resetModules();
    const browser = await import("../router");
    await browser.router.navigate("/removed-route");
    expect(browser.router.state.location.pathname).toBe("/assistant");
    expect(window.location.hash).toBe("");
    browser.router.dispose();
  });

  it("redirects retired batch pages to the overview", async () => {
    installDesktopBridge();
    window.history.replaceState(null, "", "/#/dashboard");
    vi.resetModules();
    const { router } = await import("../router");

    await router.navigate("/batches/new");
    expect(router.state.location.pathname).toBe("/dashboard");

    router.dispose();
  });

  it("exposes the integrated Lab workspace in Universal", async () => {
    delete window.__TAURI__;
    window.history.replaceState(null, "", "/lab");
    vi.resetModules();
    const { router } = await import("../router");
    const children = router.routes[0]?.children ?? [];

    expect(children.find((route) => route.path === "lab")?.lazy)
      .toEqual(expect.any(Function));
    expect(router.state.location.pathname).toBe("/lab");

    router.dispose();
  });
});
