import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { Link, Outlet, RouterProvider, createMemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { AutonomyConversationSidebar } from "../components/AutonomyConversationSidebar";
import { acquireAutonomyPlanning } from "../features/autonomy/conversationActivity";
import { autonomyConversationPath, listAutonomyConversations, loadAutonomyConversation, newAutonomyConversation, preserveLegacyAutonomyConversation, saveAutonomyConversation } from "../features/autonomy/conversationStore";
import { defaultAutonomyWorkspace, saveAutonomyWorkspace } from "../features/autonomy/workspaceStore";
import { AutonomyOverview, AutonomyPlatform } from "../pages/AutonomyPlatform";

const mocks = vi.hoisted(() => ({ plan: vi.fn(), reconcile: vi.fn(), owner: null as null | { id: string } }));
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
});

describe("autonomy conversation persistence", () => {
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
  it("creates and lists the first message before asset checks, even if those checks fail", async () => {
    let rejectAssets: (reason: Error) => void = () => {};
    mocks.reconcile.mockReturnValue(new Promise((_, reject) => { rejectAssets = reject; }));
    const router = renderWorkspace();
    const composer = await screen.findByRole("textbox");
    fireEvent.change(composer, { target: { value: "拿下快递" } });
    fireEvent.click(screen.getByRole("button", { name: "Build mission contract" }));
    await waitFor(() => expect(router.state.location.pathname).toMatch(/^\/autonomy\/conversations\//u));
    expect(within(screen.getByRole("region", { name: "Conversations" })).getByRole("link", { name: "拿下快递" })).toBeVisible();
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
    fireEvent.click(screen.getByRole("link", { name: "去取件处" }));
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
