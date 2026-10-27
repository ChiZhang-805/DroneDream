import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const bridge = vi.hoisted(() => ({ status: vi.fn(), restart: vi.fn() }));
vi.mock("../features/autonomy/agentCore", () => ({
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
    const startup = await import("../desktop/agentCoreStartup");
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
    const startup = await import("../desktop/agentCoreStartup");
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
    const startup = await import("../desktop/agentCoreStartup");
    const check = startup.checkAgentCoreStartup();
    await vi.advanceTimersByTimeAsync(1_000);
    await check;
    expect(startup.getAgentCoreStartupState()).toBe("ready");
    expect(bridge.restart).toHaveBeenCalledTimes(1);
  });
});
