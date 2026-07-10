import { fireEvent, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it } from "vitest";

import { I18nProvider } from "../i18n/I18nProvider";
import { NewJob } from "../pages/NewJob";

function renderChineseWizard() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <I18nProvider>
      <QueryClientProvider client={queryClient}>
        <MemoryRouter>
          <NewJob />
        </MemoryRouter>
      </QueryClientProvider>
    </I18nProvider>,
  );
}

describe("Chinese experiment wizard", () => {
  beforeEach(() => {
    window.localStorage.clear();
    window.localStorage.setItem("drone-dream:locale", "zh-CN");
  });

  it("translates the seven-step navigation and core step actions", () => {
    renderChineseWizard();

    expect(screen.getByRole("heading", { name: "新建调优实验" })).toBeVisible();
    expect(screen.getByRole("heading", { name: "机型与 PX4 配置" })).toBeVisible();
    expect(screen.getByRole("radio", { name: /^基础模式/ })).toHaveTextContent(
      "使用保守预设",
    );
    expect(screen.getByRole("button", { name: /上一步/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /保存草稿/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /创建调优实验/ })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /待调参数/ }));
    expect(screen.getByRole("heading", { name: "控制参数搜索空间" })).toBeVisible();
    expect(screen.getByText("查找 PX4 参数")).toBeVisible();
    expect(screen.getByRole("button", { name: /重新应用预设/ })).toBeVisible();
    expect(screen.getByRole("heading", { name: "XY 位置与速度环" })).toBeVisible();

    fireEvent.click(screen.getByRole("button", { name: /飞行航迹/ }));
    fireEvent.change(screen.getByLabelText(/Track Type/i), {
      target: { value: "custom" },
    });
    expect(screen.getByRole("button", { name: "添加航点" })).toBeVisible();
    expect(screen.getByRole("button", { name: "撤销" })).toBeVisible();

    fireEvent.click(screen.getByRole("button", { name: /检查并运行/ }));
    expect(screen.getByRole("heading", { name: "检查实验配置" })).toBeVisible();
    expect(screen.getByText("API 安全兼容")).toBeVisible();
  });
});
