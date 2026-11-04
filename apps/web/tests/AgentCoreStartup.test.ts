import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const bridge = vi.hoisted(() => ({ status: vi.fn(), restart: vi.fn() }));
vi.mock("../src/features/autonomy/agentCore", () => ({
  getAgentCoreStatus: bridge.status,
  restartAgentCore: bridge.restart,
}));

beforeEach(() => {
  vi.resetModules();
  vi.resetAllMocks();
  vi.useFakeTimers();
});
afterEach(() => vi.useRealTimers());

describe("Agent Core startup", () => {
  it("shares the native startup operation and waits for health before entry", async () => {
    bridge.status
      .mockResolvedValueOnce({ restarting: true, available: false })
      .mockResolvedValueOnce({ restarting: false, available: true });
    const startup = await import("../src/desktop/agentCoreStartup");
    const check = startup.checkAgentCoreStartup();
    expect(startup.checkAgentCoreStartup()).toBe(check);
    expect(startup.getAgentCoreStartupState()).toBe("checking");
    await vi.advanceTimersByTimeAsync(250);
    await check;
    expect(startup.getAgentCoreStartupState()).toBe("ready");
    expect(bridge.status).toHaveBeenCalledTimes(2);
  });

  it("automatically retries an unavailable Core without leaving the launcher", async () => {
    bridge.status.mockResolvedValue({ restarting: false, available: false });
    bridge.restart.mockResolvedValue({ restarting: false, available: true });
    const startup = await import("../src/desktop/agentCoreStartup");
    const check = startup.checkAgentCoreStartup();
    expect(startup.getAgentCoreStartupState()).toBe("checking");
    expect(bridge.restart).not.toHaveBeenCalled();
    await vi.advanceTimersByTimeAsync(1_000);
    await check;
    expect(startup.getAgentCoreStartupState()).toBe("ready");
    expect(bridge.restart).toHaveBeenCalledTimes(1);
  });

  it("recovers automatically when the first native bridge call fails", async () => {
    bridge.status.mockRejectedValueOnce(new Error("Core process exited"));
    bridge.restart.mockResolvedValue({ restarting: false, available: true });
    const startup = await import("../src/desktop/agentCoreStartup");
    const check = startup.checkAgentCoreStartup();
    await vi.advanceTimersByTimeAsync(1_000);
    await check;
    expect(startup.getAgentCoreStartupState()).toBe("ready");
    expect(bridge.restart).toHaveBeenCalledTimes(1);
  });

  it("stops at a visible failure state instead of waiting at 90 percent forever", async () => {
    bridge.status.mockResolvedValue({ restarting: false, available: false });
    bridge.restart.mockResolvedValue({ restarting: false, available: false });
    const startup = await import("../src/desktop/agentCoreStartup");
    const check = startup.checkAgentCoreStartup();

    await vi.advanceTimersByTimeAsync(2_000);
    await check;

    expect(startup.getAgentCoreStartupState()).toBe("failed");
    expect(bridge.restart).toHaveBeenCalledTimes(2);
  });

  it("allows an explicit retry after a bounded startup failure", async () => {
    bridge.status.mockResolvedValue({ restarting: false, available: false });
    bridge.restart
      .mockResolvedValueOnce({ restarting: false, available: false })
      .mockResolvedValueOnce({ restarting: false, available: false })
      .mockResolvedValueOnce({ restarting: false, available: true });
    const startup = await import("../src/desktop/agentCoreStartup");
    const first = startup.checkAgentCoreStartup();
    await vi.advanceTimersByTimeAsync(2_000);
    await first;
    expect(startup.getAgentCoreStartupState()).toBe("failed");

    await startup.checkAgentCoreStartup(true);

    expect(startup.getAgentCoreStartupState()).toBe("ready");
    expect(bridge.restart).toHaveBeenCalledTimes(3);
  });
});
