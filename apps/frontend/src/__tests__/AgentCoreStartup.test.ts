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

  it("keeps a failed startup blocked until an explicit successful retry", async () => {
    bridge.status.mockResolvedValue({ restarting: false, available: false });
    bridge.restart.mockResolvedValue({ restarting: false, available: true });
    const startup = await import("../desktop/agentCoreStartup");
    await startup.checkAgentCoreStartup();
    expect(startup.getAgentCoreStartupState()).toBe("failed");
    expect(bridge.restart).not.toHaveBeenCalled();
    await startup.checkAgentCoreStartup(true);
    expect(startup.getAgentCoreStartupState()).toBe("ready");
    expect(bridge.restart).toHaveBeenCalledTimes(1);
  });

  it("does not approve entry when the native bridge fails", async () => {
    bridge.status.mockRejectedValue(new Error("Core process exited"));
    const startup = await import("../desktop/agentCoreStartup");
    await startup.checkAgentCoreStartup();
    expect(startup.getAgentCoreStartupState()).toBe("failed");
  });
});
