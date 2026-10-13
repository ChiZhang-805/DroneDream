import type { PreparationProgressEvent } from "./conversationActivity";
import "./PreparationProgress.css";

const TITLES: Record<string, [string, string]> = {
  assets: ["正在读取地图与无人机", "Reading map and aircraft"],
  interpretation: ["正在解析资产知识", "Interpreting asset knowledge"],
  naming: ["正在整理任务名称", "Naming the conversation"],
  intent: ["正在理解任务", "Understanding the task"],
  intent_review: ["正在复核任务要求", "Reviewing task requirements"],
  tools: ["正在查询与计算", "Querying and calculating"],
  decomposition: ["正在分解任务步骤", "Decomposing task steps"],
  route: ["正在规划路线", "Planning the route"],
  clearance: ["正在检查三维通行间隙", "Checking 3D route clearance"],
  runtime: ["正在执行并调整任务", "Executing and adjusting the mission"],
  verification: ["正在校验计划", "Validating the plan"],
  ready: ["正在整理回复", "Preparing the reply"],
  failed: ["正在处理本次结果", "Handling the result"],
  connection: ["正在等待进度连接", "Waiting for progress connection"],
};

// Follow actual preparation events without exposing internal explanatory prose.
export function PreparationProgress({ events, chinese }: { events: PreparationProgressEvent[]; chinese: boolean }) {
  const stage = events.at(-1)?.stage ?? "assets";
  const title = (TITLES[stage] ?? ["正在处理任务", "Processing the task"])[chinese ? 0 : 1];
  return <div className="autonomy-preparation-progress" role="status" aria-live="polite">
    <span className="autonomy-progress-spinner" aria-hidden="true" />
    <h3>{title}</h3>
  </div>;
}
