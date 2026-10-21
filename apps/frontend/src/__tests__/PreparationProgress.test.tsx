import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { PreparationProgress } from "../features/autonomy/PreparationProgress";
import { followPreparationProgress } from "../features/autonomy/preparationProgressTransport";
import { getAgentCorePreparationProgress } from "../features/autonomy/agentCore";

vi.mock("../features/autonomy/agentCore", () => ({ getAgentCorePreparationProgress: vi.fn() }));
const request = vi.mocked(getAgentCorePreparationProgress);
beforeEach(() => { vi.useFakeTimers(); request.mockReset(); });
afterEach(() => { cleanup(); vi.useRealTimers(); vi.restoreAllMocks(); });

it("shows only the current real stage and updates without typing delays", () => {
  const view = render(<PreparationProgress events={[{ stage: "assets", zh: "内部资产说明", en: "Internal asset details" }]} chinese />);
  expect(screen.getByRole("status")).toHaveTextContent("正在读取地图与无人机");
  expect(screen.queryByText("内部资产说明")).toBeNull();
  view.rerender(<PreparationProgress events={[{ stage: "route", zh: "内部路线说明", en: "Internal route details" }]} chinese />);
  expect(screen.getByRole("status")).toHaveTextContent("正在规划路线");
  expect(screen.queryByText("内部路线说明")).toBeNull();
  expect(vi.getTimerCount()).toBe(0);
  view.rerender(<p>计划已返回，等待确认</p>);
  expect(screen.queryByRole("status")).toBeNull();
});
it("shows the runtime title for execution monitoring and in-flight model work", () => {
  render(
    <PreparationProgress
      events={[{ stage: "runtime", zh: "正在生成局部导航建议", en: "Generating guidance" }]}
      chinese
    />,
  );
  expect(screen.getByRole("heading")).toHaveTextContent("正在执行并调整任务");
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
