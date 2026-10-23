import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { AgentCoreRequestError, getAgentCoreBootstrap, prepareAgentCoreMission } from "../features/autonomy/agentCore";
import * as auth from "../features/auth/authTokenStore";

const invoke = vi.fn();
beforeEach(() => {
  invoke.mockReset();
  Object.assign(window, { __TAURI__: { core: { invoke } } });
  vi.spyOn(auth, "getAuthAccessToken").mockReturnValue("offline-session-token-only");
});
afterEach(() => { delete (window as Window & { __TAURI__?: unknown }).__TAURI__; });

describe("desktop Core identity and typed clarification", () => {
  it("preserves an HTTP 202 map review response without interpreting it as a mission plan", async () => {
    const pending = { status: "map_refinement_pending", state: "awaiting-observation", thread_id: "thread-test",
      actuator_authority: false, next_action: "inspect-map-gaps", message: "Inspect the connecting path." };
    invoke.mockResolvedValue({ status: 202, contentType: "application/json", bodyBase64: btoa(JSON.stringify(pending)) });
    expect(await prepareAgentCoreMission("thread-test", {} as Parameters<typeof prepareAgentCoreMission>[1])).toEqual(pending);
    expect(invoke).toHaveBeenCalledTimes(1);
  });
  it("forwards the current in-memory identity without persisting a credential", async () => {
    invoke.mockResolvedValue({ status: 200, contentType: "application/json", bodyBase64: btoa("{}") });
    const write = vi.spyOn(Storage.prototype, "setItem");
    await getAgentCoreBootstrap();
    expect(invoke).toHaveBeenCalledWith("agent_core_request", expect.objectContaining({
      request: expect.objectContaining({ identityToken: "offline-session-token-only", path: "/v1/bootstrap" }),
    }));
    expect(write).not.toHaveBeenCalled();
  });

  it.each([true, false])("accepts only bounded clarification contracts (valid=%s)", async (valid) => {
    const detail = { code: "MISSION_CLARIFICATION_REQUIRED", fields: [valid ? "Which pickup point?" : "x".repeat(241)] };
    invoke.mockResolvedValue({ status: 409, contentType: "application/json", bodyBase64: btoa(JSON.stringify({ detail })) });
    try {
      await prepareAgentCoreMission("thread-test", {} as Parameters<typeof prepareAgentCoreMission>[1]);
      expect.fail("Request should return an error, not a plan");
    } catch (error) {
      expect(error).toBeInstanceOf(AgentCoreRequestError);
      expect((error as AgentCoreRequestError).clarificationFields).toEqual(valid ? detail.fields : []);
    }
    expect(invoke).toHaveBeenCalledTimes(1);
  });
});
