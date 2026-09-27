import { beforeEach, expect, it, vi } from "vitest";
import * as core from "../features/autonomy/agentCore";
import * as cloud from "../features/settings/cloudModelAccess";
import { executeBoundAgentCoreMission, interpretAgentCoreAsset, planWithAgentCore, type AgentCorePlanningInput } from "../features/autonomy/agentCorePlanning";
import { defaultAutonomyWorkspace } from "../features/autonomy/workspaceStore";
import sample from "./fixtures/qualifiedAssetPair.json";

const threadId = "thread-job-grant-test";
const planId = `plan-${"a".repeat(32)}`;
let input: AgentCorePlanningInput;

// 功能：
//   隔离云端与飞行副作用，保留真实前端授权和任务分派逻辑。
// 输入：
//   无。
// 输出：
//   input：绑定已认证资产与当前 Kimi 模型的测试请求。
beforeEach(() => {
  vi.restoreAllMocks();
  localStorage.clear();
  input = {
    edition: "autonomy", accountId: "account-test", conversationId: "conversation-test",
    instruction: "从办公室取餐再返回，悬停10秒，不扫码，先给计划", locale: "zh-CN",
    accessMode: "platform", provider: "kimi", model: "kimi-k2.6",
    agentCoreProfileId: null, agentCoreSelectionId: null,
    workspace: defaultAutonomyWorkspace(), harnessContextSha256: "a".repeat(64), requestPurpose: "initial_plan",
  };
  const thread: core.AgentCoreThread = { thread_id: threadId, title: "取餐任务", selected_model: "kimi-k2.6", state: "awaiting_confirmation",
    selected_map_id: null, selected_map_content_sha256: null, selected_vehicle_id: null,
    selected_vehicle_content_sha256: null, pinned: false, archived: false,
    created_at: "2026-09-21T00:00:00Z", updated_at: "2026-09-21T00:00:00Z",
    messages: [{ message_id: "plan-message", sequence: 1, role: "assistant", kind: "plan",
      content: "取餐计划", created_at: "2026-09-21T00:00:00Z", metadata: { plan_revision_id: planId } }] };
  vi.spyOn(core, "getAgentCoreBootstrap").mockResolvedValue({
    models: [{ id: "kimi-k2.6", source: "default", provider: "kimi" }],
    asset_versions: sample.versions, threads: [],
  } as unknown as Awaited<ReturnType<typeof core.getAgentCoreBootstrap>>);
  vi.spyOn(core, "createAgentCoreThread").mockResolvedValue(thread);
  vi.spyOn(core, "patchAgentCoreThread").mockResolvedValue(thread);
  vi.spyOn(core, "getAgentCoreThread").mockResolvedValue(thread);
  vi.spyOn(cloud, "issueManagedModelGrant").mockResolvedValue({
    grant: "ddg_test", scope: "job", max_calls: 256, gateway_base_url: "https://project.supabase.co/functions/v1/model-gateway",
  } as cloud.ManagedModelGrant);
});

it("planning requests a thread-bound job grant before any model stage", async () => {
  vi.spyOn(core, "prepareAgentCoreMission").mockRejectedValue(new Error("STOP_AT_BACKEND_BOUNDARY"));
  const execute = vi.spyOn(core, "executeAgentCoreMission");
  await expect(planWithAgentCore(input)).rejects.toThrow("STOP_AT_BACKEND_BOUNDARY");
  expect(cloud.issueManagedModelGrant).toHaveBeenCalledWith("job", threadId, "kimi", "kimi-k2.6");
  expect(core.prepareAgentCoreMission).toHaveBeenCalledWith(threadId, expect.objectContaining({ message: input.instruction, model_grant: "ddg_test" }));
  expect(execute).not.toHaveBeenCalled();
});

it("generates a real-model title before planning without executing, and tolerates naming failure", async () => {
  const title = vi.spyOn(core, "requestAgentCoreConversationTitle").mockResolvedValue({ title: "去外卖点取餐" });
  const prepare = vi.spyOn(core, "prepareAgentCoreMission").mockRejectedValue(new Error("PLANNING_BOUNDARY"));
  const onConversationTitle = vi.fn();
  await expect(planWithAgentCore({ ...input, onConversationTitle })).rejects.toThrow("PLANNING_BOUNDARY");
  expect(title).toHaveBeenCalledWith(threadId, expect.objectContaining({ message: input.instruction, model_grant: "ddg_test" }));
  expect(onConversationTitle).toHaveBeenCalledExactlyOnceWith("去外卖点取餐");
  expect(title.mock.invocationCallOrder[0]).toBeLessThan(prepare.mock.invocationCallOrder[0]);
  title.mockRejectedValue(new Error("NAMING_UNAVAILABLE"));
  onConversationTitle.mockClear();
  await expect(planWithAgentCore({ ...input, onConversationTitle })).rejects.toThrow("PLANNING_BOUNDARY");
  expect(onConversationTitle).not.toHaveBeenCalled();
  expect(prepare).toHaveBeenCalledTimes(2);
});

it("asset interpretation uses a job grant for validation and bounded retries", async () => {
  vi.spyOn(core, "requestAgentCoreAssetInterpretation").mockRejectedValue(new Error("STOP_AT_BACKEND_BOUNDARY"));
  await expect(interpretAgentCoreAsset({ ...input, kind: "map", assetId: input.workspace.mapPack.agentCoreAssetId!, contentSha256: null })).rejects.toThrow("STOP_AT_BACKEND_BOUNDARY");
  expect(cloud.issueManagedModelGrant).toHaveBeenCalledWith("job", threadId, "kimi", "kimi-k2.6");
});

it("confirmed execution gets a separate job grant, while a changed plan gets none", async () => {
  localStorage.setItem("dronedream:agent-core-thread:v1:account-test:autonomy:conversation-test", threadId);
  vi.spyOn(core, "executeAgentCoreMission").mockRejectedValue(new Error("STOP_AT_BACKEND_BOUNDARY"));
  await expect(executeBoundAgentCoreMission({ ...input, planRevisionId: `plan-${"b".repeat(32)}` })).rejects.toThrow("PLAN_CHANGED");
  expect(cloud.issueManagedModelGrant).not.toHaveBeenCalled();
  await expect(executeBoundAgentCoreMission({ ...input, planRevisionId: planId })).rejects.toThrow("STOP_AT_BACKEND_BOUNDARY");
  expect(cloud.issueManagedModelGrant).toHaveBeenCalledExactlyOnceWith("job", threadId, "kimi", "kimi-k2.6");
});
