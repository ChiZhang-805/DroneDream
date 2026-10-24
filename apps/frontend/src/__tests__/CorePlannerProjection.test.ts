import { readFileSync } from "node:fs";
import { createHash } from "node:crypto";
import { afterEach, expect, it, vi } from "vitest";
import { parseAutonomyPlannerArtifact, verifyCorePlannerDigest, autonomyPlannerBindingIssues, autonomyHarnessRequest } from "../features/autonomy/missionHarness";
import * as planning from "../features/autonomy/agentCorePlanning";
import { planAutonomyMission } from "../features/autonomy/autonomyPlanning";
import { defaultAutonomyWorkspace } from "../features/autonomy/workspaceStore";
import type { AgentCoreMissionPrepareSummary } from "../features/autonomy/agentCore";

afterEach(() => vi.restoreAllMocks());

// 功能：
//   生成不含用户数据的协议回归输入。
// 输入：
//   无。
// 输出：
//   artifact：包含插件动作和非固定预算的计划。
function fixture() {
  return {
    schema_version: "dronedream.autonomy.planner-response.v1", status: "draft", goal: "取餐返回",
    asset_bindings: { aircraft_id: "aircraft-my-drone", aircraft_version: 1, map_id: "map-school", map_version: 1, context_sha256: "a".repeat(64) },
    grounded_entities: [], tool_requests: [], tool_receipts: [], assumptions: [], blockers: [],
    task_graph: { nodes: ["takeoff", "delivery.precontact-hold", "pickup", "return", "land"].map((action, index) => ({
      node_id: `step-${index}`, action, target: `verified-${index}`, depends_on: index ? [`step-${index - 1}`] : [], success_evidence: ["完成条件"],
    })) },
    repair: { attempt: 1, max_attempts: 5, repeated_plan_hashes: 0, stop_reason: null },
    safety_policy: { actuator_authority: false, may_relax_constraints: false, execution_requires_deterministic_validation: true },
  };
}

it("accepts Core domain actions without weakening public compiler templates", () => {
  const artifact = fixture();
  expect(parseAutonomyPlannerArtifact(artifact)).toBeNull();
  const parsed = parseAutonomyPlannerArtifact(artifact, "agent-core")!;
  expect(parsed).toBe(artifact);
  const request = autonomyHarnessRequest("autonomy", defaultAutonomyWorkspace(), "取餐后返回");
  const inspection = { context_sha256: "a".repeat(64) } as Awaited<ReturnType<typeof planning.inspectAgentCoreAssetBindings>>;
  expect(autonomyPlannerBindingIssues(parsed, request, inspection, "agent-core")).toEqual([]);
  expect(autonomyPlannerBindingIssues(parsed, request, inspection)).toContain("planner.route-profile.unsupported");
});

it.each(["cycle", "dependency", "budget", "action", "authority", "blocker"])("rejects malformed Core %s", (kind) => {
  const value = fixture();
  if (kind === "cycle") value.task_graph.nodes[0].depends_on = ["step-4"];
  if (kind === "dependency") value.task_graph.nodes[0].depends_on = ["missing"];
  if (kind === "budget") value.repair.attempt = 6;
  if (kind === "action") value.task_graph.nodes[1].action = "delivery..pickup";
  if (kind === "authority") value.safety_policy.actuator_authority = true;
  if (kind === "blocker") Object.assign(value, { blockers: [null] });
  expect(parseAutonomyPlannerArtifact(value, "agent-core")).toBeNull();
});

it("checks exact Python JSON bytes and rejects object/hash tampering", async () => {
  const value = fixture();
  const canonical = JSON.stringify(value).replace('"attempt":1', '"attempt":1.0');
  const artifact = parseAutonomyPlannerArtifact(JSON.parse(canonical), "agent-core")!;
  const digest = createHash("sha256").update(canonical).digest("hex");
  expect(await verifyCorePlannerDigest(artifact, canonical, digest)).toBe(true);
  expect(await verifyCorePlannerDigest({ ...artifact, goal: "篡改" }, canonical, digest)).toBe(false);
  expect(await verifyCorePlannerDigest(artifact, canonical, "0".repeat(64))).toBe(false);
  expect(await verifyCorePlannerDigest(artifact, "{", digest)).toBe(false);
});

// 真实故障记录只在本机通过环境变量读取，不提交账户或任务数据到公开源码。
it.skipIf(!process.env.DRONEDREAM_PLANNER_REPLAY)("replays a real model result through the entire UI planning boundary", async () => {
  const summary = JSON.parse(readFileSync(process.env.DRONEDREAM_PLANNER_REPLAY!, "utf8")) as AgentCoreMissionPrepareSummary;
  const bindings = summary.integration_artifact.asset_bindings;
  const workspace = defaultAutonomyWorkspace();
  workspace.aircraft.id = bindings.aircraft_id;
  workspace.aircraft.version = bindings.aircraft_version;
  workspace.mapPack.id = bindings.map_id;
  workspace.mapPack.version = bindings.map_version;
  vi.spyOn(planning, "inspectAgentCoreAssetBindings").mockResolvedValue({ planning_ready: true, context_sha256: bindings.context_sha256 } as Awaited<ReturnType<typeof planning.inspectAgentCoreAssetBindings>>);
  vi.spyOn(planning, "planWithAgentCore").mockResolvedValue(summary);
  const input = {
    edition: "autonomy" as const, accountId: "replay", publicDemo: false, workspace,
    conversationId: "replay", turnId: "replay", intent: "从办公室取餐后返回，不用扫码", instruction: "取餐返回", chinese: true,
    selectedModel: { accessMode: "platform" as const, provider: "kimi" as const, model: "kimi-k2.6" }, requestPurpose: "initial_plan" as const,
  };
  const result = await planAutonomyMission(input);
  expect(result.planningBrief.length).toBeGreaterThan(20);
  expect(result.plannerArtifact?.task_graph.nodes.length).toBe(8);
  expect(result.compiledPlan?.source).toBe("agent-core");
  expect(result.compiledPlan?.feasible).toBe(true);
  expect(result.compiledPlan?.routePositionsM?.length).toBeGreaterThan(2);
  expect(result.compileRequest).toBeNull();
  const wrongGraph = structuredClone(summary);
  wrongGraph.mission_plan.task_graph.nodes[0].depends_on = ["land"];
  vi.mocked(planning.planWithAgentCore).mockResolvedValue(wrongGraph);
  await expect(planAutonomyMission(input)).rejects.toThrow("task graph binding");
  const tampered = structuredClone(summary);
  tampered.integration_artifact.goal = "篡改";
  vi.mocked(planning.planWithAgentCore).mockResolvedValue(tampered);
  await expect(planAutonomyMission(input)).rejects.toThrow("digest mismatch");
});
