import { beforeEach, expect, it, vi } from "vitest";
import { AgentCoreRequestError } from "../features/autonomy/agentCore";
import * as planning from "../features/autonomy/agentCorePlanning";
import { planAutonomyMission } from "../features/autonomy/autonomyPlanning";
import { defaultAutonomyWorkspace } from "../features/autonomy/workspaceStore";

beforeEach(() => {
  vi.spyOn(planning, "inspectAgentCoreAssetBindings").mockResolvedValue({
    planning_ready: true, context_sha256: "a".repeat(64),
  } as Awaited<ReturnType<typeof planning.inspectAgentCoreAssetBindings>>);
});

it("returns a conversation question without a fake plan and preserves the full follow-up intent", async () => {
  vi.spyOn(planning, "planWithAgentCore").mockRejectedValue(new AgentCoreRequestError(409,
    "MISSION_CLARIFICATION_REQUIRED", ["要送回办公室，还是送到其他位置？"], {
      questions: [{
        questionId: "delivery.destination",
        prompt: "要送回办公室，还是送到其他位置？",
        options: [
          { optionId: "A", label: "送回办公室", response: "送回办公室。" },
          { optionId: "B", label: "送到大厅", response: "送到大厅。" },
        ],
        allowOther: true,
        otherLabel: "其他",
      }],
    }));
  const result = await planAutonomyMission({
    edition: "autonomy", accountId: "account-test", publicDemo: false,
    workspace: defaultAutonomyWorkspace(), conversationId: "conversation-test", turnId: "turn-test",
    intent: "拿下快递\n补充指令：东门那个", instruction: "东门那个", chinese: true,
    selectedModel: { accessMode: "platform", provider: "kimi", model: "kimi-k2.6" },
    requestPurpose: "initial_plan",
  });
  expect(planning.planWithAgentCore).toHaveBeenCalledWith(expect.objectContaining({ instruction: "拿下快递\n补充指令：东门那个" }));
  expect(result.planningBrief).toBe("还需要确认一项任务信息。");
  expect(result.compiledPlan).toBeNull();
  expect(result.plannerArtifact).toBeNull();
  expect(result.compileResult).toBeNull();
  expect(result.clarification?.questions[0]?.options[0]?.response).toBe("送回办公室。");
});
