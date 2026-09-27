import { render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";
import { MissionPlanCard } from "../features/autonomy/MissionPlanCard";
import { conversationUsesChinese, missionStepTitle, provisionalMissionTitle, taskUsesChinese } from "../features/autonomy/missionPresentation";
import { defaultAutonomyWorkspace } from "../features/autonomy/workspaceStore";

// 功能：
//   构造纯展示样本，保留不应显示的内部字段以检查信息精简边界。
// 输入：
//   count：任务步骤数。
// 输出：
//   workspace：不连接模型或飞控的测试快照。
function fixture(count = 8) {
  const workspace = defaultAutonomyWorkspace();
  workspace.mission.intent = "从办公室出发取外卖然后返回";
  const actions = ["takeoff", "navigate", "delivery.precontact-hold", "pickup", "delivery.confirm-custody", "delivery.verify-loaded-stability", "return", "land"];
  workspace.mission.compiledPlan = {
    issues: [], metrics: { routeLengthM: 413.2 },
    taskGraph: { nodes: Array.from({ length: count }, (_, i) => ({ task_id: `node-${i}`, label: `Task node ${i}`, risk_level: "high", timeout_s: 20, success_evidence: ["hidden evidence"] })) },
    steps: [], plannerBinding: { task_graph: { nodes: Array.from({ length: count }, (_, i) => ({ node_id: `node-${i}`, action: actions[i % actions.length] })) } },
  } as unknown as NonNullable<typeof workspace.mission.compiledPlan>;
  return workspace;
}

describe("user-message language", () => {
  it.each([
    ["请用 My Drone 在 School Map 取餐", true], ["Please fly from 办公室 to the pickup point", false],
    ["去拿外卖", true], ["Pick up my meal and return", false], ["School Map，帮我取一下外卖", true],
  ])("classifies %s without reading system locale", (message, chinese) => expect(taskUsesChinese(message)).toBe(chinese));
  it("inherits language for numeric replies and follows an explicit language switch", () => {
    const workspace = fixture();
    expect(conversationUsesChinese(workspace)).toBe(true);
    workspace.mission.messages = ["请帮我取餐", "2", "Please return to the office"].map((content, i) => ({ id: String(i), role: "user", content, createdAt: "", planContractId: null }));
    expect(conversationUsesChinese(workspace)).toBe(false);
    expect(taskUsesChinese("10", true)).toBe(true);
    expect(taskUsesChinese("https://example.com", true)).toBe(true);
  });
  it("uses brief same-language provisional activity names", () => {
    expect(provisionalMissionTitle("从办公室出发帮我拿外卖然后回来，先给我计划")).toBe("去取餐点取餐");
    expect(provisionalMissionTitle("Please pick up a meal and return to my office")).toBe("Meal pickup");
  });
});

describe("compact plan presentation", () => {
  it.each([true, false])("renders the short shared title and three summary fields, chinese=%s", (chinese) => {
    const workspace = fixture();
    const before = JSON.stringify(workspace);
    render(<MemoryRouter><MissionPlanCard chinese={chinese} workspace={workspace} title={chinese ? "去外卖点取餐" : "Meal pickup"} formatIssue={(issue) => issue.message} /></MemoryRouter>);
    expect(screen.getByText("Generated mission plan")).toBeVisible();
    expect(screen.getByRole("heading", { level: 3 })).toHaveTextContent(chinese ? "去外卖点取餐" : "Meal pickup");
    expect(screen.getByText(chinese ? "无人机" : "Aircraft")).toBeVisible();
    expect(screen.getByText(chinese ? "地图" : "Map")).toBeVisible();
    expect(screen.getByText(chinese ? "路线" : "Route")).toBeVisible();
    const steps = screen.getAllByRole("listitem");
    expect(steps).toHaveLength(8);
    expect(steps[0]).toHaveTextContent(chinese ? "01起飞" : "01Take off");
    expect(steps[7]).toHaveTextContent(chinese ? "08安全降落" : "08Land safely");
    expect(screen.getAllByRole("link")).toHaveLength(1);
    expect(screen.getByRole("link", { name: chinese ? "打开仿真" : "Open simulation" })).toHaveAttribute("href", "/autonomy/live");
    expect(screen.queryByText(/Perception|Simulation ready|hash-bound|Task node|hidden evidence|20s/)).toBeNull();
    expect(JSON.stringify(workspace)).toBe(before);
  });
  it("retains every step in a long plan without a collapsed or scrollable graph component", () => {
    const { container } = render(<MemoryRouter><MissionPlanCard chinese workspace={fixture(40)} title="长任务" formatIssue={(issue) => issue.message} /></MemoryRouter>);
    expect(screen.getAllByRole("listitem")).toHaveLength(40);
    expect(container.querySelector("details, .autonomy-task-graph")).toBeNull();
    expect(within(screen.getAllByRole("listitem")[39]).getByText("40")).toBeVisible();
  });
  it("opens the live route for this exact conversation, not the last global workspace", () => {
    const workspace = fixture();
    workspace.mission.conversationId = "task/with space";
    render(<MemoryRouter><MissionPlanCard chinese workspace={workspace} title="取餐" formatIssue={(issue) => issue.message} /></MemoryRouter>);
    expect(screen.getByRole("link", { name: "打开仿真" })).toHaveAttribute("href", "/autonomy/conversations/task%2Fwith%20space/live");
  });
  it("does not hide blocking errors or turn opening simulation into execution", () => {
    const workspace = fixture();
    workspace.mission.compiledPlan!.issues = [{ code: "blocked", message: "需要确认任务地点", severity: "error" }];
    render(<MemoryRouter><MissionPlanCard chinese workspace={workspace} title="取餐" formatIssue={(issue) => issue.message} /></MemoryRouter>);
    expect(screen.getByText("需要确认任务地点")).toBeVisible();
    expect(screen.queryByRole("button")).toBeNull();
  });
  it("keeps unknown plugin labels only when they match the conversation language", () => {
    expect(missionStepTitle("custom.step", "清点物品", true, "")).toBe("清点物品");
    expect(missionStepTitle("custom.step", "Count items", true, "")).toBe("执行任务步骤");
    expect(missionStepTitle("custom.step", "Count items", false, "")).toBe("Count items");
  });
});
