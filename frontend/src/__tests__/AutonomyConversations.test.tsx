import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { Link, Outlet, RouterProvider, createMemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { AutonomyConversationSidebar } from "../components/AutonomyConversationSidebar";
import { acquireAutonomyPlanning } from "../features/autonomy/conversationActivity";
import { autonomyConversationPath, listAutonomyConversations, loadAutonomyConversation, newAutonomyConversation, preserveLegacyAutonomyConversation, saveAutonomyConversation } from "../features/autonomy/conversationStore";
import { defaultAutonomyWorkspace, saveAutonomyWorkspace } from "../features/autonomy/workspaceStore";
import { AutonomyLive, AutonomyOverview, AutonomyPlatform } from "../pages/AutonomyPlatform";

const mocks = vi.hoisted(() => ({ plan: vi.fn(), reconcile: vi.fn(), boundThread: vi.fn(), runtime: vi.fn(), execute: vi.fn(), sources: vi.fn(), frame: vi.fn(), owner: null as null | { id: string } }));
vi.mock("../features/auth/AuthContext", () => ({ useOptionalAuth: () => ({ account: mocks.owner }) }));
vi.mock("../theme/EditionThemeProvider", () => ({ useEditionTheme: () => ({ id: "autonomy" }) }));
vi.mock("../features/settings/ModelAccessContext", () => ({ useModelAccess: () => ({
  settings: { accessMode: "platform", managedProvider: "kimi", managedModel: "kimi-test" },
  profiles: [], selectAccessMode: vi.fn(), selectManagedModel: vi.fn(), selectProfile: vi.fn(),
}) }));
vi.mock("../components/AssistantModelPicker", () => ({ AssistantModelPicker: () => <span>Test model picker</span> }));
vi.mock("../features/experiment/useVoiceInput", () => ({ useVoiceInput: () => ({ state: "idle", cancel: vi.fn() }) }));
vi.mock("../features/settings/cloudModelAccess", async (original) => ({
  ...await original<typeof import("../features/settings/cloudModelAccess")>(),
  DEFAULT_MANAGED_MODEL_CATALOG: [{ provider: "kimi", model: "kimi-test", available: true }],
  completeManagedModelCatalog: () => [{ provider: "kimi", model: "kimi-test", available: true }],
  managedModelAvailableForAssistant: () => true,
  getManagedModelCatalog: async () => ({ models: [] }),
}));
vi.mock("../features/autonomy/agentCore", async (original) => ({
  ...await original<typeof import("../features/autonomy/agentCore")>(),
  getAgentCoreStatus: async () => ({ available: true }),
  getAgentCoreBootstrap: async () => ({ plugins: [] }),
  getAgentCoreRuntimeStatus: mocks.runtime,
  getAgentCoreLiveSources: mocks.sources,
  getAgentCoreLiveFrame: mocks.frame,
}));
vi.mock("../features/autonomy/agentCorePlanning", async (original) => ({
  ...await original<typeof import("../features/autonomy/agentCorePlanning")>(),
  getBoundAgentCoreThread: mocks.boundThread,
  executeBoundAgentCoreMission: mocks.execute,
}));
vi.mock("../features/autonomy/assetPairBinding", async (original) => ({
  ...await original<typeof import("../features/autonomy/assetPairBinding")>(),
  reconcileAgentCoreWorkspace: mocks.reconcile,
}));
vi.mock("../features/autonomy/autonomyPlanning", async (original) => ({
  ...await original<typeof import("../features/autonomy/autonomyPlanning")>(),
  planAutonomyMission: mocks.plan,
}));

// 功能：
//   构造不调用模型、不取得飞行权限的会话存储测试样本。
// 输入：
//   id：会话标识；content：用户消息。
// 输出：
//   workspace：测试会话。
function conversation(id: string, content = "拿下快递") {
  const workspace = defaultAutonomyWorkspace();
  workspace.mission = { ...workspace.mission, conversationId: id, intent: content, messages: [{ id: `message-${id}`, role: "user", content, createdAt: new Date().toISOString(), planContractId: null }] };
  return workspace;
}

// 功能：
//   构造可持久化的展示计划，以真实页面检查执行入口，不授予真实飞行权限。
// 输入：
//   id：会话标识。
// 输出：
//   workspace：含最小有效图和关联回复的测试会话。
function preparedConversation(id: string) {
  const workspace = conversation(id, "帮我取餐");
  workspace.mission.planningRunId = `revision-${id}`;
  workspace.mission.compiledPlan = { source: "agent-core", contractId: "contract-test", readiness: "simulation_ready", canExecute: true, feasible: true, steps: [], issues: [], metrics: { routeLengthM: 10 }, taskGraph: { nodes: [{ task_id: "takeoff", label: "起飞", status: "pending", executor: "px4_bridge", risk: "high", fallback: "land", inserted_by: "compiler", depends_on: [] }] } } as unknown as NonNullable<typeof workspace.mission.compiledPlan>;
  workspace.mission.messages.push({ id: "plan-message", role: "assistant", content: "计划已生成", createdAt: new Date().toISOString(), planContractId: "contract-test" });
  return workspace;
}

// 功能：
//   装配实际自主任务页面与侧边栏，使用替身规划器验证导航及异步边界。
// 输入：
//   initial：初始页面地址。
// 输出：
//   router：可观测导航状态的测试路由。
function renderWorkspace(initial = "/autonomy") {
  const router = createMemoryRouter([{
    element: <><Link to="/autonomy">Chatbot</Link><AutonomyConversationSidebar ownerId="local" edition="autonomy" locale="en" /><Outlet /></>,
    children: [{ path: "/autonomy", element: <AutonomyPlatform />, children: [
      { index: true, element: <AutonomyOverview /> },
      { path: "conversations/:conversationId", element: <AutonomyOverview /> },
      { path: "conversations/:conversationId/live", element: <AutonomyLive /> },
      { path: "live", element: <AutonomyLive /> },
    ] }],
  }], { initialEntries: [initial] });
  render(<RouterProvider router={router} />);
  return router;
}

beforeEach(() => {
  localStorage.clear();
  mocks.owner = null;
  mocks.plan.mockReset().mockResolvedValue({ compiledPlan: null, planningBrief: "你指的是哪个取件处？", planningRunId: "test-plan" });
  mocks.reconcile.mockReset().mockImplementation(async (workspace) => workspace);
  mocks.boundThread.mockReset().mockResolvedValue({ thread_id: "core-test", state: "awaiting_confirmation", messages: [] });
  mocks.runtime.mockReset().mockResolvedValue({ runtime_available: true, resources_ready: true, provisioned: true, issue: null });
  mocks.execute.mockReset().mockResolvedValue({ state: "executing", execution_id: "execution-test" });
  mocks.sources.mockReset().mockResolvedValue({ sources: [] });
  mocks.frame.mockReset().mockResolvedValue(new Blob(["test frame"], { type: "image/png" }));
});

describe("autonomy conversation persistence", () => {
  it("always opens the Chatbot root as a blank new task even when an older conversation exists", async () => {
    const existing = conversation("saved", "这条旧消息不能出现在新任务页");
    saveAutonomyConversation("local", "autonomy", existing);
    saveAutonomyWorkspace("local", "autonomy", existing);
    renderWorkspace("/autonomy");
    expect(await screen.findByText("What should your drone do?")).toBeVisible();
    expect(screen.getByRole("textbox")).toHaveValue("");
    expect(screen.queryByText("这条旧消息不能出现在新任务页")).not.toBeInTheDocument();
  });

  it("isolates accounts and editions and does not create a conversation for an empty composer", () => {
    expect(listAutonomyConversations("local", "autonomy")).toEqual([]);
    saveAutonomyConversation("owner-a", "autonomy", conversation("one"));
    expect(listAutonomyConversations("owner-b", "autonomy")).toEqual([]);
    expect(listAutonomyConversations("owner-a", "universal")).toEqual([]);
    expect(loadAutonomyConversation("owner-a", "autonomy", "one")?.mission.messages).toHaveLength(1);
    expect(() => saveAutonomyConversation("owner-a", "autonomy", newAutonomyConversation(conversation("one")))).toThrow("EMPTY");
  });

  it("preserves the old singleton message once, without replacing a newer conversation", () => {
    saveAutonomyWorkspace("local", "autonomy", conversation("one", "原消息"));
    preserveLegacyAutonomyConversation("local", "autonomy");
    saveAutonomyConversation("local", "autonomy", conversation("one", "新消息"));
    preserveLegacyAutonomyConversation("local", "autonomy");
    expect(listAutonomyConversations("local", "autonomy")).toHaveLength(1);
    expect(loadAutonomyConversation("local", "autonomy", "one")?.mission.intent).toBe("新消息");
  });

  it("reports storage failure rather than claiming a conversation was saved", () => {
    const storage = { length: 0, key: () => null, getItem: () => null, setItem: () => { throw new Error("quota"); } };
    expect(() => saveAutonomyConversation("local", "autonomy", conversation("one"), storage)).toThrow("quota");
  });

  it("holds one planning request across route changes and releases it idempotently", () => {
    const release = acquireAutonomyPlanning("local", "autonomy", "lease-test");
    expect(acquireAutonomyPlanning("local", "autonomy", "lease-test")).toBeNull();
    release?.();
    const newer = acquireAutonomyPlanning("local", "autonomy", "lease-test");
    release?.();
    expect(acquireAutonomyPlanning("local", "autonomy", "lease-test")).toBeNull();
    newer?.();
  });
});

describe("Chatbot to independent conversation", () => {
  it.each(["failed", "completed"])("terminal %s state overrides an accepted start receipt", async (state) => {
    saveAutonomyConversation("local", "autonomy", preparedConversation("terminal"));
    renderWorkspace("/autonomy/conversations/terminal");
    const start = await screen.findByRole("button", { name: "开始仿真" });
    await waitFor(() => expect(start).toBeEnabled());
    mocks.boundThread.mockResolvedValue({ thread_id: "core-test", state,
      messages: state === "failed" ? [{ kind: "error", content: "运行插件加载失败" }] : [] });
    fireEvent.click(start);
    expect(await screen.findByRole("button", { name: state === "failed" ? "运行失败" : "已完成" }, { timeout: 3500 })).toBeDisabled();
    expect(screen.queryByRole("button", { name: "正在运行" })).toBeNull();
    if (state === "failed") expect(screen.getByRole("alert")).toHaveTextContent("运行插件加载失败");
  });
  it("starts from the plan card, records acceptance only after the receipt, and keeps viewing disabled without frames", async () => {
    const requested = preparedConversation("requested");
    saveAutonomyConversation("local", "autonomy", requested);
    saveAutonomyWorkspace("local", "autonomy", conversation("other", "检查另一处"));
    renderWorkspace("/autonomy/conversations/requested");
    const start = await screen.findByRole("button", { name: "开始仿真" });
    await waitFor(() => expect(start).toBeEnabled());
    expect(mocks.execute).not.toHaveBeenCalled();
    expect(mocks.boundThread).toHaveBeenCalledWith(expect.objectContaining({ conversationId: "requested" }));
    expect(screen.queryByText(/执行请求已受理/)).toBeNull();
    fireEvent.click(start);
    await waitFor(() => expect(mocks.execute).toHaveBeenCalledOnce());
    expect(mocks.execute).toHaveBeenCalledWith(expect.objectContaining({ conversationId: "requested", planRevisionId: "revision-requested" }));
    expect(await screen.findByText(/执行请求已受理/)).toBeVisible();
    expect(screen.getByRole("button", { name: "查看运行（等待画面）" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "正在运行" })).toBeDisabled();
  });

  it("shows the confirmation but prevents starting until the runtime is ready", async () => {
    const workspace = preparedConversation("not-ready");
    saveAutonomyConversation("local", "autonomy", workspace);
    mocks.runtime.mockResolvedValue({ runtime_available: false, resources_ready: false, provisioned: true, issue: "RUNTIME_NOT_READY" });
    renderWorkspace("/autonomy/conversations/not-ready");
    const start = await screen.findByRole("button", { name: "开始仿真" });
    expect(start).toBeDisabled();
    fireEvent.click(start);
    expect(mocks.execute).not.toHaveBeenCalled();
  });

  it("does not announce acceptance after execution rejection", async () => {
    saveAutonomyConversation("local", "autonomy", preparedConversation("reject"));
    mocks.execute.mockRejectedValue(new Error("AGENT_CORE_PLAN_CHANGED_REVIEW_AGAIN"));
    renderWorkspace("/autonomy/conversations/reject");
    const start = await screen.findByRole("button", { name: "开始仿真" });
    await waitFor(() => expect(start).toBeEnabled());
    fireEvent.click(start);
    expect(await screen.findByRole("alert")).toBeVisible();
    expect(screen.queryByText(/执行请求已受理/)).toBeNull();
  });

  it("enables viewing only after a simulation camera frame decodes, not just a source flag", async () => {
    const workspace = preparedConversation("view");
    workspace.mission.messages.push({ id: "execution-accepted:revision-view", role: "assistant", content: "执行请求已受理", createdAt: new Date().toISOString(), planContractId: null });
    saveAutonomyConversation("local", "autonomy", workspace);
    mocks.boundThread.mockResolvedValue({ thread_id: "core-view", state: "executing", messages: [] });
    mocks.sources.mockResolvedValue({ sources: [{ id: "front", ready: true, mode: "simulation", transport: "agent-core-frame" }] });
    let decode: (bitmap: unknown) => void = () => {};
    vi.stubGlobal("createImageBitmap", vi.fn(() => new Promise((resolve) => { decode = resolve; })));
    renderWorkspace("/autonomy/conversations/view");
    await waitFor(() => expect(mocks.frame).toHaveBeenCalled());
    expect(screen.getByRole("button", { name: "查看运行（等待画面）" })).toBeDisabled();
    await act(async () => decode({ width: 640, height: 480, close: vi.fn() }));
    expect(await screen.findByRole("link", { name: "查看运行" })).toHaveAttribute("href", "/autonomy/conversations/view/live?source=front&autoplay=1");
    vi.unstubAllGlobals();
  });

  it.each(["failed", "completed"])("does not keep waiting for a camera after the run is %s", async (state) => {
    const workspace = preparedConversation("ended");
    workspace.mission.messages.push({ id: "execution-accepted:revision-ended", role: "assistant", content: "执行请求已受理", createdAt: new Date().toISOString(), planContractId: null });
    saveAutonomyConversation("local", "autonomy", workspace);
    mocks.boundThread.mockResolvedValue({ thread_id: "core-ended", state, messages: [] });
    renderWorkspace("/autonomy/conversations/ended");
    expect(await screen.findByRole("button", { name: "运行已结束（无实时画面）" })).toBeDisabled();
    expect(screen.queryByRole("button", { name: "查看运行（等待画面）" })).toBeNull();
    expect(mocks.frame).not.toHaveBeenCalled();
  });

  it("refuses a deleted mission live link without silently selecting another mission", async () => {
    saveAutonomyWorkspace("local", "autonomy", conversation("other"));
    renderWorkspace("/autonomy/conversations/missing/live");
    expect(await screen.findByRole("alert")).toHaveTextContent("could not be read");
    expect(screen.queryByRole("button", { name: "确认并开始仿真" })).toBeNull();
    expect(mocks.execute).not.toHaveBeenCalled();
  });

  it("does not restore a deleted conversation when the pending model reply arrives", async () => {
    let complete: (result: unknown) => void = () => {};
    mocks.plan.mockReturnValue(new Promise((resolve) => { complete = resolve; }));
    const router = renderWorkspace();
    fireEvent.change(await screen.findByRole("textbox"), { target: { value: "去外卖点取餐" } });
    fireEvent.click(screen.getByRole("button", { name: "Build mission contract" }));
    await waitFor(() => expect(mocks.plan).toHaveBeenCalledOnce());
    vi.spyOn(window, "confirm").mockReturnValue(true);
    fireEvent.click(screen.getByRole("button", { name: "Delete conversation" }));
    await screen.findByText("What should your drone do?");
    await act(async () => { complete({ compiledPlan: null, planningBrief: "迟到的规划回复", planningRunId: "test" }); });
    expect(router.state.location.pathname).toBe("/autonomy");
    expect(listAutonomyConversations("local", "autonomy")).toEqual([]);
    expect(screen.queryByText("迟到的规划回复")).not.toBeInTheDocument();
  });

  it("stores the model title independently from the full first user message", async () => {
    mocks.plan.mockImplementation(async (input) => {
      input.onConversationTitle("去外卖点取餐");
      return { compiledPlan: null, planningBrief: "请确认取餐点", planningRunId: "title-test" };
    });
    renderWorkspace();
    fireEvent.change(await screen.findByRole("textbox"), { target: { value: "请从办公室出发帮我拿外卖然后返回" } });
    fireEvent.click(screen.getByRole("button", { name: "Build mission contract" }));
    expect(await screen.findByRole("link", { name: "去外卖点取餐" })).toBeVisible();
    expect(await screen.findByText("请确认取餐点")).toBeVisible();
    expect(screen.getByText("请从办公室出发帮我拿外卖然后返回")).toBeVisible();
    expect(mocks.plan.mock.calls[0][0].chinese).toBe(true);
  });

  it("creates and lists the first message before asset checks, even if those checks fail", async () => {
    let rejectAssets: (reason: Error) => void = () => {};
    mocks.reconcile.mockReturnValue(new Promise((_, reject) => { rejectAssets = reject; }));
    const router = renderWorkspace();
    const composer = await screen.findByRole("textbox");
    fireEvent.change(composer, { target: { value: "拿下快递" } });
    fireEvent.click(screen.getByRole("button", { name: "Build mission contract" }));
    await waitFor(() => expect(router.state.location.pathname).toMatch(/^\/autonomy\/conversations\//u));
    expect(within(screen.getByRole("region", { name: "Conversations" })).getByRole("link", { name: "领取快递" })).toBeVisible();
    expect(screen.getByLabelText("Generating mission plan")).toBeVisible();
    await act(async () => { rejectAssets(new Error("ASSET_NOT_READY")); });
    expect(await screen.findByRole("alert")).toHaveTextContent("ASSET_NOT_READY");
    expect(mocks.plan).not.toHaveBeenCalled();
    const id = listAutonomyConversations("local", "autonomy")[0].id;
    expect(loadAutonomyConversation("local", "autonomy", id)?.mission.planningError).toContain("ASSET_NOT_READY");
  });

  it("opens a blank Chatbot while a reply is pending and keeps that reply in its original conversation", async () => {
    let complete: (result: unknown) => void = () => {};
    mocks.plan.mockReturnValue(new Promise((resolve) => { complete = resolve; }));
    const router = renderWorkspace();
    fireEvent.change(await screen.findByRole("textbox"), { target: { value: "去取件处" } });
    fireEvent.click(screen.getByRole("button", { name: "Build mission contract" }));
    await waitFor(() => expect(mocks.plan).toHaveBeenCalledOnce());
    const firstPath = router.state.location.pathname;
    fireEvent.click(screen.getByRole("link", { name: "Chatbot" }));
    await screen.findByText("What should your drone do?");
    await act(async () => { complete({ compiledPlan: null, planningBrief: "请确认取件处", planningRunId: "test" }); });
    expect(router.state.location.pathname).toBe("/autonomy");
    expect(screen.queryByText("请确认取件处")).not.toBeInTheDocument();
    fireEvent.change(screen.getByRole("textbox"), { target: { value: "检查操场" } });
    mocks.plan.mockResolvedValue({ compiledPlan: null, planningBrief: "请确认检查范围", planningRunId: "test-2" });
    fireEvent.click(screen.getByRole("button", { name: "Build mission contract" }));
    await screen.findByText("请确认检查范围");
    expect(router.state.location.pathname).not.toBe(firstPath);
    expect(listAutonomyConversations("local", "autonomy")).toHaveLength(2);
    fireEvent.click(screen.getByRole("link", { name: "领取快递" }));
    expect(await screen.findByText("请确认取件处")).toBeVisible();
    expect(screen.queryByText("请确认检查范围")).not.toBeInTheDocument();
  });

  it("reopens a saved conversation on reload and refuses a missing id instead of loading another conversation", async () => {
    saveAutonomyConversation("local", "autonomy", conversation("saved", "恢复会话"));
    const router = renderWorkspace(autonomyConversationPath("saved"));
    expect(await screen.findByText("恢复会话", { selector: ".autonomy-conversation-message *" })).toBeVisible();
    await act(async () => { await router.navigate(autonomyConversationPath("missing")); });
    expect(await screen.findByRole("alert")).toHaveTextContent("could not be read");
    expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
  });
});
