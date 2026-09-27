import { Airplay, Layers3, Navigation2, Route, ShieldCheck } from "lucide-react";
import { Link } from "react-router-dom";
import type { ReactNode } from "react";
import type { AutonomyWorkspaceState } from "./workspaceStore";
import { missionStepTitle } from "./missionPresentation";

// 功能：
//   用会话短标题展示紧凑计划和逐行步骤；保留阻断问题，不显示内部执行元数据。
// 输入：
//   chinese：对话语言；workspace：已验证计划；title：侧边栏同源标题；formatIssue：问题翻译器；controls：显式执行控件。
// 输出：
//   card：自适应高度的计划卡片，不自动执行。
export function MissionPlanCard({ chinese, workspace, title, formatIssue, controls }: { chinese: boolean; workspace: AutonomyWorkspaceState; title: string; formatIssue: (issue: { code: string; message: string }, chinese: boolean) => string; controls?: ReactNode }) {
  const plan = workspace.mission.compiledPlan;
  if (!plan) return null;
  const blockingIssues = plan.issues.filter((issue) => issue.severity === "error");
  return <section className="autonomy-inline-plan" aria-live="polite">
    <header><div><small>Generated mission plan</small><h3>{title}</h3></div></header>
    <div className="autonomy-inline-plan-bindings">
      <span><Navigation2 aria-hidden="true" /><small>{chinese ? "无人机" : "Aircraft"}</small><strong>{workspace.aircraft.name}</strong></span>
      <span><Layers3 aria-hidden="true" /><small>{chinese ? "地图" : "Map"}</small><strong>{workspace.mapPack.name}</strong></span>
      <span><Route aria-hidden="true" /><small>{chinese ? "路线" : "Route"}</small><strong>{plan.metrics.routeLengthM.toFixed(1)} {chinese ? "米" : "m"}</strong></span>
    </div>
    {blockingIssues.length > 0 && <ul className="autonomy-inline-plan-issues">{blockingIssues.map((issue) => <li key={issue.code}><ShieldCheck aria-hidden="true" /><span>{formatIssue(issue, chinese)}</span></li>)}</ul>}
    <div className="autonomy-plan-steps">
      <h4>{chinese ? "执行步骤" : "Execution steps"}</h4>
      <ol>{plan.taskGraph.nodes.map((node, index) => {
        const action = plan.plannerBinding?.task_graph.nodes.find((item) => item.node_id === node.task_id)?.action ?? plan.steps[index]?.action ?? "";
        return <li key={node.task_id}><i>{String(index + 1).padStart(2, "0")}</i><span>{missionStepTitle(action, node.label, chinese, workspace.mission.intent)}</span></li>;
      })}</ol>
    </div>
    <footer>{controls ?? <Link className="btn btn-primary" to={workspace.mission.conversationId ? `/autonomy/conversations/${encodeURIComponent(workspace.mission.conversationId)}/live` : "/autonomy/live"}><Airplay aria-hidden="true" />{chinese ? "打开仿真" : "Open simulation"}</Link>}</footer>
  </section>;
}
