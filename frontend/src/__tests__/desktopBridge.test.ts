import { describe, expect, it, vi } from "vitest";

import {
  DesktopRuntimeUnavailableError,
  getRuntimeInstallPlan,
  isDesktopRuntime,
  probeRuntimeStatus,
  probeSystemPrerequisites,
} from "../desktop/bridge";

describe("desktop bridge", () => {
  it("stays unavailable in a normal browser", async () => {
    expect(isDesktopRuntime()).toBe(false);
    await expect(probeSystemPrerequisites()).rejects.toBeInstanceOf(
      DesktopRuntimeUnavailableError,
    );
  });

  it("routes typed calls through the Tauri global API", async () => {
    const invoke = vi.fn(async (command: string) => ({ command }));
    window.__TAURI__ = { core: { invoke } };

    expect(isDesktopRuntime()).toBe(true);
    await probeSystemPrerequisites();
    await probeRuntimeStatus();
    await getRuntimeInstallPlan("E:\\DroneDream");

    expect(invoke.mock.calls.map(([command]) => command)).toEqual([
      "probe_system_prerequisites",
      "probe_runtime_status",
      "get_runtime_install_plan",
    ]);
    expect(invoke).toHaveBeenLastCalledWith(
      "get_runtime_install_plan",
      { targetRoot: "E:\\DroneDream" },
    );
  });
});
