import type { AgentCoreMapRefinementPending } from "./agentCore";

/** Presentation state only. It never carries a plan or execution authority. */
export interface AutonomyMapRefinementState {
  state: "awaiting-observation";
  threadId: string;
  nextAction: AgentCoreMapRefinementPending["next_action"];
  message: string;
  requestCount: number;
  observationCount: number;
  physicalCalls: number;
}

export function mapRefinementSnapshot(result: AgentCoreMapRefinementPending): AutonomyMapRefinementState {
  return {
    state: "awaiting-observation",
    threadId: result.thread_id,
    nextAction: result.next_action,
    message: result.message,
    requestCount: result.pending_requests?.length ?? 0,
    observationCount: result.observation_records?.length ?? 0,
    physicalCalls: result.physical_calls ?? 0,
  };
}

export function normalizeMapRefinement(value: unknown): AutonomyMapRefinementState | null {
  if (!value || typeof value !== "object") return null;
  const entry = value as Partial<AutonomyMapRefinementState>;
  if (entry.state !== "awaiting-observation" || typeof entry.threadId !== "string"
    || !entry.threadId.trim() || typeof entry.message !== "string"
    || !["inspect-map-gaps", "supply-registered-map-view"].includes(entry.nextAction ?? "")) return null;
  const count = (n: unknown) => typeof n === "number" && Number.isFinite(n)
    ? Math.max(0, Math.min(10_000, Math.floor(n))) : 0;
  return {
    state: "awaiting-observation",
    threadId: entry.threadId.slice(0, 160),
    nextAction: entry.nextAction!,
    message: entry.message.slice(0, 4_000),
    requestCount: count(entry.requestCount),
    observationCount: count(entry.observationCount),
    physicalCalls: count(entry.physicalCalls),
  };
}

export function mapRefinementBrief(chinese: boolean): string {
  return chinese
    ? "已完成本轮地图复查。部分连接路径仍需要更清楚的图像信息；补充地图来源或选择可分析图像的模型后，可以在当前任务中继续规划。"
    : "This map review is complete. Some connecting paths still need clearer visual evidence. Update the map source or select a model with visual analysis, then continue planning this task.";
}
