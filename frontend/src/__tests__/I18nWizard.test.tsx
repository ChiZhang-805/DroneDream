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

describe("Chinese experiment wizard", () => {
  beforeEach(() => {
    window.localStorage.clear();
    window.localStorage.setItem("drone-dream:locale", "zh-CN");
  });

  it("keeps all five steps Chinese, read-only, and sequential", () => {
    renderChineseWizard();

    expect(screen.getByRole("heading", { name: "新建调优实验" })).toBeVisible();
    expect(screen.getByRole("heading", { name: "飞行任务配置" })).toBeVisible();
    expect(screen.getByRole("heading", { name: "机型与 PX4 配置" })).toBeVisible();
    expect(screen.getByRole("heading", { name: "优化目标" })).toBeVisible();
    expect(screen.getByRole("heading", { name: "飞行航迹配置" })).toBeVisible();
    const modeSelector = screen.getByLabelText("调优模式");
    expect(modeSelector).toHaveValue("basic");
    expect(modeSelector.closest(".form-grid")).not.toBeNull();
    expect(modeSelector.closest(".section-card")).not.toBeNull();

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
    expect(within(progress).getByText("飞行任务")).toBeVisible();
    expect(within(progress).getByText("检查并运行")).toBeVisible();
    expect(screen.queryByRole("button", { name: "上一步" })).toBeNull();
    expect(screen.queryByRole("button", { name: "创建调优实验" })).toBeNull();
    expect(screen.queryByRole("button", { name: /保存草稿|恢复默认值/ })).toBeNull();
    expect(screen.queryByText("Experiment Name")).toBeNull();
    expect(screen.getByText("以 X/Y 为圆心、按所选半径生成完整正圆。")).toBeVisible();
    expect(screen.queryByText("A full circle centered on X/Y with the chosen radius.")).toBeNull();

    fireEvent.change(screen.getByLabelText("航迹类型"), {
      target: { value: "u_turn" },
    });
    expect(screen.getByText("由两段等长直线和一个半圆转弯组成。")).toBeVisible();

    fireEvent.change(screen.getByLabelText("机架"), {
      target: { value: "quad_x" },
    });
    expect(screen.getByText("通用 X 型四旋翼配置。")).toBeVisible();

    fireEvent.change(screen.getByLabelText("航迹类型"), {
      target: { value: "custom" },
    });
    fireEvent.click(screen.getByRole("button", { name: "编辑自定义航迹" }));
    expect(screen.getByRole("button", { name: "添加航点" })).toBeVisible();
    expect(screen.getByRole("button", { name: "撤销" })).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "关闭航迹编辑器" }));

    next();
    expect(screen.getByRole("heading", { name: "控制参数搜索空间" })).toBeVisible();
    expect(screen.getByText("查找 PX4 参数")).toBeVisible();
    expect(screen.queryByRole("button", { name: "创建调优实验" })).toBeNull();

    next();
    expect(screen.getByRole("heading", { name: "仿真场景套件" })).toBeVisible();
    expect(screen.getByLabelText("标称搜索")).toHaveValue("true");
    expect(screen.getByText("在噪声场景中施加中等传感器噪声。")).toBeVisible();
    fireEvent.change(screen.getByLabelText("传感器噪声等级"), {
      target: { value: "high" },
    });
    expect(screen.getByText("施加严重传感器噪声进行压力测试。")).toBeVisible();

    next();
    expect(screen.getByRole("heading", { name: "约束与计算预算" })).toBeVisible();
    expect(screen.queryByRole("button", { name: "创建调优实验" })).toBeNull();
    expect(screen.queryByText("合成工作流仿真器")).not.toBeInTheDocument();
    expect(screen.queryByText("精度优先实验策略")).not.toBeInTheDocument();
    expect(screen.queryByText(/预计试验上限/)).not.toBeInTheDocument();

    next();
    expect(screen.getByRole("heading", { name: "检查实验配置" })).toBeVisible();
    expect(screen.getByRole("button", { name: "创建调优实验" })).toBeVisible();
    expect(screen.queryByRole("button", { name: "下一步" })).toBeNull();
  });
});
