import { beforeEach, expect, it, vi } from "vitest";
import { AgentCoreRequestError, type AgentCoreMapRefinementPending } from "../features/autonomy/agentCore";
import * as planning from "../features/autonomy/agentCorePlanning";
import { planAutonomyMission } from "../features/autonomy/autonomyPlanning";
import { defaultAutonomyWorkspace } from "../features/autonomy/workspaceStore";

beforeEach(() => {
  vi.restoreAllMocks();
  vi.spyOn(planning, "inspectAgentCoreAssetBindings").mockResolvedValue({
    planning_ready: true, context_sha256: "a".repeat(64),
  } as Awaited<ReturnType<typeof planning.inspectAgentCoreAssetBindings>>);
});

it("returns an explicit waiting state for a map review, with no plan or public compiler fallback", async () => {
  const pending: AgentCoreMapRefinementPending = {
    status: "map_refinement_pending", state: "awaiting-observation", thread_id: "thread-review",
    actuator_authority: false, next_action: "supply-registered-map-view", message: "An aligned view is needed.",
    observation_records: [{ view: "initial" }], physical_calls: 1,
  };
  vi.spyOn(planning, "planWithAgentCore").mockResolvedValue(pending);
  const result = await planAutonomyMission({
    edition: "universal", accountId: "account-test", publicDemo: false,
    workspace: defaultAutonomyWorkspace(), conversationId: "conversation-test", turnId: "turn-test",
    intent: "Collect the chemistry sample.", instruction: "Collect the chemistry sample.", chinese: false,
    selectedModel: { accessMode: "platform", provider: "kimi", model: "kimi-k2.6" }, requestPurpose: "initial_plan",
  });
  expect(result.mapRefinement).toMatchObject({ state: "awaiting-observation", observationCount: 1, nextAction: "supply-registered-map-view" });
  expect(result.planningBrief).toContain("map review is complete");
  expect(result.compiledPlan).toBeNull();
  expect(result.planningRunId).toBeNull();
  expect(result.plannerArtifact).toBeNull();
  expect(result.compileRequest).toBeNull();
});

it("returns a conversation question without a fake plan and preserves the full follow-up intent", async () => {
  vi.spyOn(planning, "planWithAgentCore").mockRejectedValue(new AgentCoreRequestError(409,
    "MISSION_CLARIFICATION_REQUIRED", ["要送回办公室，还是送到其他位置？"]));
  const result = await planAutonomyMission({
    edition: "autonomy", accountId: "account-test", publicDemo: false,
    workspace: defaultAutonomyWorkspace(), conversationId: "conversation-test", turnId: "turn-test",
    intent: "拿下快递\n补充指令：东门那个", instruction: "东门那个", chinese: true,
    selectedModel: { accessMode: "platform", provider: "kimi", model: "kimi-k2.6" },
    requestPurpose: "initial_plan",
  });
  expect(planning.planWithAgentCore).toHaveBeenCalledWith(expect.objectContaining({ instruction: "拿下快递\n补充指令：东门那个" }));
  expect(result.planningBrief).toContain("要送回办公室，还是送到其他位置？");
  expect(result.compiledPlan).toBeNull();
  expect(result.plannerArtifact).toBeNull();
  expect(result.compileResult).toBeNull();
});
