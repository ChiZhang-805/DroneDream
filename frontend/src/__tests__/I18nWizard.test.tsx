import { fireEvent, render, screen, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it } from "vitest";

import { I18nProvider } from "../i18n/I18nProvider";
import { NewJob } from "../pages/NewJob";

function renderChineseWizard() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  const result = render(
    <I18nProvider>
      <QueryClientProvider client={queryClient}>
        <MemoryRouter>
          <NewJob />
        </MemoryRouter>
      </QueryClientProvider>
    </I18nProvider>,
  );
  const nameDialog = screen.getByRole("dialog");
  fireEvent.change(within(nameDialog).getByRole("textbox"), {
    target: { value: "x500-test" },
  });
  fireEvent.submit(nameDialog);
  return result;
}

function next(): void {
  fireEvent.click(screen.getByRole("button", { name: "下一步" }));
}

function byId<T extends HTMLElement>(id: string): T {
  const element = document.querySelector<T>(`#${id}`);
  if (!element) throw new Error(`Missing control: ${id}`);
  return element;
}

describe("Chinese experiment wizard", () => {
  beforeEach(() => {
    window.localStorage.clear();
    window.localStorage.setItem("drone-dream:locale", "zh-CN");
  });

  it("keeps all five steps Chinese, compact, read-only, and sequential", () => {
    renderChineseWizard();

    expect(screen.getByRole("heading", { name: "新建调优实验" })).toBeVisible();
    expect(screen.getByRole("heading", { name: "飞行任务配置" })).toBeVisible();
    expect(screen.getByRole("heading", { name: "机型与 PX4 配置" })).toBeVisible();
    expect(screen.getByRole("heading", { name: "优化目标" })).toBeVisible();
    expect(screen.getByRole("heading", { name: "飞行航迹配置" })).toBeVisible();
    expect(screen.getByLabelText("调优模式")).toHaveValue("basic");

    const progress = screen.getByRole("navigation", { name: "实验配置进度" });
    const progressItems = within(progress).getAllByRole("listitem");
    expect(progressItems).toHaveLength(5);
    expect(progressItems.map((item) => item.textContent?.replace(/^\d+/, "").trim())).toEqual([
      "飞行任务",
      "待调参数",
      "仿真场景",
      "约束与预算",
      "检查并运行",
    ]);
    expect(within(progress).queryAllByRole("button")).toHaveLength(0);
    expect(screen.queryByRole("button", { name: "上一步" })).toBeNull();
    expect(screen.queryByRole("button", { name: "创建调优实验" })).toBeNull();
    expect(screen.queryByText("Experiment Name")).toBeNull();

    expect(document.querySelector("#vehicle_type")).toBeNull();
    expect(byId<HTMLInputElement>("circle_radius_m")).toHaveAttribute("placeholder", "0–100");
    expect(document.querySelectorAll(".wizard-panel .form-hint")).toHaveLength(0);

    fireEvent.change(byId<HTMLSelectElement>("track_type"), { target: { value: "custom" } });
    fireEvent.click(screen.getByRole("button", { name: "编辑自定义航迹" }));
    expect(screen.getByRole("button", { name: "添加航点" })).toBeVisible();
    expect(screen.getByRole("button", { name: "撤销" })).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "关闭航迹编辑器" }));

    next();
    expect(screen.getByRole("heading", { name: "控制参数搜索空间" })).toBeVisible();
    expect(screen.queryByRole("button", { name: "创建调优实验" })).toBeNull();

    next();
    expect(screen.getByRole("heading", { name: "仿真场景套件" })).toBeVisible();
    expect(screen.getByLabelText("标称搜索")).toHaveValue("true");
    fireEvent.change(screen.getByLabelText("传感器噪声等级"), { target: { value: "high" } });
    expect(screen.getByLabelText("传感器噪声等级")).toHaveValue("high");
    expect(document.querySelectorAll(".wizard-panel .form-hint")).toHaveLength(0);

    next();
    expect(screen.getByRole("heading", { name: "约束与计算预算" })).toBeVisible();
    expect(screen.queryByRole("button", { name: "创建调优实验" })).toBeNull();

    next();
    expect(screen.getByRole("heading", { name: "检查实验配置" })).toBeVisible();
    expect(screen.getByRole("button", { name: "创建调优实验" })).toBeVisible();
    expect(screen.queryByRole("button", { name: "下一步" })).toBeNull();
  });
});
