import { beforeEach, expect, it, vi } from "vitest";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import { AutonomyConversationSidebar } from "../components/AutonomyConversationSidebar";
import { listAutonomyConversations, loadAutonomyConversation, preserveLegacyAutonomyConversation, saveAutonomyConversation, updateAutonomyConversation } from "../features/autonomy/conversationStore";
import { defaultAutonomyWorkspace, saveAutonomyWorkspace } from "../features/autonomy/workspaceStore";

// 功能：
//   创建隔离的会话样本，不调用模型或飞控。
// 输入：
//   id：会话标识。
// 输出：
//   workspace：已保存的测试会话。
function seed(id: string) {
  const workspace = defaultAutonomyWorkspace();
  workspace.mission.conversationId = id;
  workspace.mission.intent = id;
  workspace.mission.messages = [{ id, role: "user", content: id, createdAt: new Date().toISOString(), planContractId: null }];
  return saveAutonomyConversation("account", "autonomy", workspace);
}

beforeEach(() => { localStorage.clear(); vi.restoreAllMocks(); });

it("preserves pin and generated title when an earlier planning snapshot returns", () => {
  const snapshot = seed("one");
  seed("two");
  updateAutonomyConversation("account", "autonomy", "one", { pinned: true, title: "去外卖点取餐" });
  saveAutonomyConversation("account", "autonomy", snapshot);
  expect(listAutonomyConversations("account", "autonomy")[0]).toMatchObject({ id: "one", pinned: true, title: "去外卖点取餐", generatedTitle: true });
  expect(listAutonomyConversations("other", "autonomy")).toEqual([]);
  expect(listAutonomyConversations("account", "sim")).toEqual([]);
});

it("never resurrects deleted conversations through late replies, titles or legacy migration", () => {
  const snapshot = seed("one");
  saveAutonomyWorkspace("account", "autonomy", snapshot);
  updateAutonomyConversation("account", "autonomy", "one", { deleted: true });
  saveAutonomyConversation("account", "autonomy", snapshot);
  updateAutonomyConversation("account", "autonomy", "one", { title: "迟到的模型标题" });
  preserveLegacyAutonomyConversation("account", "autonomy");
  expect(loadAutonomyConversation("account", "autonomy", "one")).toBeNull();
  expect(listAutonomyConversations("account", "autonomy")).toEqual([]);
});

it("supports pin/unpin, cancellation and deletion of the active conversation", () => {
  seed("one"); seed("two");
  const router = createMemoryRouter([{ path: "*", element: <AutonomyConversationSidebar ownerId="account" edition="autonomy" locale="zh-CN" /> }], { initialEntries: ["/autonomy/conversations/one"] });
  render(<RouterProvider router={router} />);
  const row = screen.getByRole("link", { name: "one" }).parentElement!;
  fireEvent.click(within(row).getByRole("button", { name: "置顶对话" }));
  expect(within(row).getByRole("button", { name: "取消置顶" })).toBeVisible();
  fireEvent.click(within(row).getByRole("button", { name: "取消置顶" }));
  const confirm = vi.spyOn(window, "confirm").mockReturnValue(false);
  fireEvent.click(within(row).getByRole("button", { name: "删除对话" }));
  expect(screen.getByRole("link", { name: "one" })).toBeVisible();
  confirm.mockReturnValue(true);
  fireEvent.click(within(row).getByRole("button", { name: "删除对话" }));
  expect(screen.queryByRole("link", { name: "one" })).toBeNull();
  expect(router.state.location.pathname).toBe("/autonomy");
  expect(screen.getByRole("link", { name: "two" })).toBeVisible();
});

it("rejects empty or oversized generated names without changing the existing title", () => {
  seed("one");
  expect(() => updateAutonomyConversation("account", "autonomy", "one", { title: " " })).toThrow("TITLE_INVALID");
  expect(() => updateAutonomyConversation("account", "autonomy", "one", { title: "长".repeat(33) })).toThrow("TITLE_INVALID");
  expect(listAutonomyConversations("account", "autonomy")[0].title).toBe("one");
});
