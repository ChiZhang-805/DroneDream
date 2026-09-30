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
  it("preserves a structured error code and bounded diagnostic reference", async () => {
    const detail = { code: "HARNESS_CONFIGURATION_UPGRADE_REQUIRED", error_id: "a".repeat(32) };
    invoke.mockResolvedValue({ status: 409, contentType: "application/json", bodyBase64: btoa(JSON.stringify({ detail })) });
    await expect(getAgentCoreBootstrap()).rejects.toThrow(`${detail.code}:${detail.error_id}`);
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
    const detail = {
      code: "MISSION_CLARIFICATION_REQUIRED",
      fields: [valid ? "Which pickup point?" : "x".repeat(241)],
      questions: valid ? [{
        question_id: "pickup.location",
        prompt: "Which pickup point?",
        options: [
          { option_id: "A", label: "Pantry", response: "Use the pantry pickup point." },
          { option_id: "B", label: "Supplies", response: "Use the supplies pickup point." },
        ],
        allow_other: true,
        other_label: "Other",
      }] : [],
    };
    invoke.mockResolvedValue({ status: 409, contentType: "application/json", bodyBase64: btoa(JSON.stringify({ detail })) });
    try {
      await prepareAgentCoreMission("thread-test", {} as Parameters<typeof prepareAgentCoreMission>[1]);
      expect.fail("Request should return an error, not a plan");
    } catch (error) {
      expect(error).toBeInstanceOf(AgentCoreRequestError);
      expect((error as AgentCoreRequestError).clarificationFields).toEqual(valid ? detail.fields : []);
      expect((error as AgentCoreRequestError).clarification?.questions[0]?.options[0]?.label)
        .toBe(valid ? "Pantry" : undefined);
    }
    expect(invoke).toHaveBeenCalledTimes(1);
  });
});
