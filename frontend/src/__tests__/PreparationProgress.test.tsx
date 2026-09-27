import { act, cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { PreparationProgress } from "../features/autonomy/PreparationProgress";
import { followPreparationProgress } from "../features/autonomy/preparationProgressTransport";
import { getAgentCorePreparationProgress } from "../features/autonomy/agentCore";

vi.mock("../features/autonomy/agentCore", () => ({ getAgentCorePreparationProgress: vi.fn() }));
const request = vi.mocked(getAgentCorePreparationProgress);
beforeEach(() => { vi.useFakeTimers(); request.mockReset(); });
afterEach(() => { cleanup(); vi.useRealTimers(); vi.restoreAllMocks(); });

it("types summaries, switches a single heading and removes progress immediately for the reply", () => {
  const view = render(<PreparationProgress events={[{ stage: "assets", zh: "已经读取地图中的八个地点", en: "Map loaded" }]} chinese />);
  const detail = () => view.container.querySelector(".autonomy-preparation-detail")!.textContent;
  expect(detail()).toBe("");
  act(() => { vi.advanceTimersByTime(25); });
  expect(detail()).toBe("已经读");
  view.rerender(<PreparationProgress events={[{ stage: "assets", zh: "旧阶段", en: "Old" }, { stage: "route", zh: "正在查询办公室与取餐点的连通关系", en: "Checking connectivity" }]} chinese />);
  expect(screen.getAllByRole("heading")).toHaveLength(1);
  expect(screen.getByRole("heading")).toHaveTextContent("正在规划路线");
  expect(detail()).toBe("");
  act(() => { vi.advanceTimersByTime(100); });
  expect(detail()).not.toContain("旧阶段");
  view.rerender(<p>计划已返回，等待确认</p>);
  expect(view.container.querySelector(".autonomy-preparation-progress")).toBeNull();
  expect(vi.getTimerCount()).toBe(0);
});

it("appends same-stage details without restarting already visible text", () => {
  const first = { stage: "assets", zh: "已读取地图", en: "Map read" };
  const view = render(<PreparationProgress events={[first]} chinese />);
  act(() => { vi.advanceTimersByTime(100); });
  expect(vi.getTimerCount()).toBe(0);
  view.rerender(<PreparationProgress events={[first, { stage: "assets", zh: "解析缓存已命中", en: "Cache hit" }]} chinese />);
  expect(view.container.querySelector(".autonomy-preparation-detail")).toHaveTextContent("已读取地图");
  act(() => { vi.advanceTimersByTime(200); });
  expect(view.container.querySelector(".autonomy-preparation-detail")).toHaveTextContent("解析缓存已命中");
});

it("streams lengthy clearance explanations and real counters without switching the heading", () => {
  const first = { stage: "clearance", zh: "检查连续路线与机体包络。".repeat(35), en: "Checking continuous clearance" };
  const view = render(<PreparationProgress events={[first]} chinese />);
  act(() => { vi.advanceTimersByTime(100); });
  expect(view.container.querySelector(".autonomy-preparation-detail")!.textContent!.length).toBeLessThan(first.zh.length);
  const heading = screen.getByRole("heading");
  expect(heading).toHaveTextContent("正在检查三维通行间隙");
  view.rerender(<PreparationProgress events={[first, { stage: "clearance", zh: "已检查32个位置，用时4.1秒", en: "32 positions checked" }]} chinese />);
  expect(screen.getByRole("heading")).toBe(heading);
  act(() => { vi.advanceTimersByTime(10000); });
  expect(view.container.querySelector(".autonomy-preparation-detail")).toHaveTextContent("已检查32个位置，用时4.1秒");
});

it("serially polls, deduplicates receipts and stops after completion", async () => {
  const event = { sequence: 1, stage: "assets", zh: "真实读取", en: "Actual read" };
  request.mockResolvedValueOnce({ state: "running", events: [event] });
  request.mockResolvedValueOnce({ state: "completed", events: [event, { ...event, sequence: 2, stage: "ready" }] });
  const publish = vi.fn();
  const stop = followPreparationProgress("thread", "request", publish);
  await vi.advanceTimersByTimeAsync(1000);
  expect(request).toHaveBeenNthCalledWith(2, "thread", "request", 1);
  expect(publish).toHaveBeenCalledTimes(2);
  await vi.advanceTimersByTimeAsync(10000);
  expect(request).toHaveBeenCalledTimes(2);
  stop();
});

it("ignores an in-flight progress reply after the actual plan has completed", async () => {
  let resolve!: (value: Awaited<ReturnType<typeof getAgentCorePreparationProgress>>) => void;
  request.mockImplementationOnce(() => new Promise((done) => { resolve = done; }));
  const publish = vi.fn();
  const stop = followPreparationProgress("thread", "request", publish);
  await vi.advanceTimersByTimeAsync(5000);
  expect(request).toHaveBeenCalledTimes(1);
  stop();
  resolve({ state: "running", events: [{ sequence: 1, stage: "route", zh: "迟到事件", en: "Late event" }] });
  await vi.advanceTimersByTimeAsync(5000);
  expect(publish).not.toHaveBeenCalled();
  expect(request).toHaveBeenCalledTimes(1);
});

it("reports unavailable progress truthfully without synthesizing a successful plan", async () => {
  request.mockRejectedValue(new Error("offline"));
  const publish = vi.fn();
  const stop = followPreparationProgress("thread", "request", publish);
  await vi.advanceTimersByTimeAsync(3500);
  expect(publish).toHaveBeenCalledOnce();
  expect(publish.mock.calls[0][0].stage).toBe("connection");
  stop();
});
