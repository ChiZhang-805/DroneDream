import { fireEvent, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it } from "vitest";

import { I18nProvider } from "../i18n/I18nProvider";
import { NewJob } from "../pages/NewJob";

function renderWizard(locale: "en" | "zh-CN") {
  window.localStorage.setItem("drone-dream:locale", locale);
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
  fireEvent.change(screen.getByRole("textbox"), {
    target: { value: "numeric-hints-study" },
  });
  fireEvent.submit(nameDialog);
  return result;
}

function advance(label: "Next" | "下一步", count: number): void {
  for (let index = 0; index < count; index += 1) {
    fireEvent.click(screen.getByRole("button", { name: label }));
  }
}

describe("NewJob numeric field hints", () => {
  beforeEach(() => {
    window.localStorage.clear();
  });

  it("keeps English track dimensions and acceptance thresholds concise and discoverable", () => {
    renderWizard("en");

    const circleHint = screen.getByText("Distance from the center to the circular path.");
    expect(circleHint).toBeVisible();
    expect(circleHint).toHaveAttribute("title", circleHint.textContent);

    fireEvent.change(screen.getByLabelText("Track type"), { target: { value: "u_turn" } });
    expect(screen.getByText("Length of each straight leg in the U-shaped path.")).toBeVisible();
    expect(screen.getByText("Radius of the semicircle joining both straight legs.")).toBeVisible();

    advance("Next", 3);
    const iterationHint = screen.getByText("Maximum optimizer update rounds before stopping.");
    expect(iterationHint).toBeVisible();
    expect(iterationHint).toHaveAttribute("title", iterationHint.textContent);
    expect(screen.getByText("Desired upper bound for root-mean-square track error.")).toBeVisible();
    expect(screen.getByText("Required successful-run fraction, from 0 to 1.")).toBeVisible();
  });

  it("renders the same numeric guidance as single Chinese hint lines", () => {
    renderWizard("zh-CN");

    expect(screen.getByText("圆心到圆形航迹的距离。")).toBeVisible();
    fireEvent.change(screen.getByLabelText("航迹类型"), { target: { value: "u_turn" } });
    expect(screen.getByText("U 型航迹中每段直线的长度。")).toBeVisible();
    expect(screen.getByText("连接两段直线的半圆转弯半径。")).toBeVisible();

    advance("下一步", 3);
    expect(screen.getByText("停止前允许优化器更新的最大轮数。")).toBeVisible();
    expect(screen.getByText("期望的航迹均方根误差上限。")).toBeVisible();
    expect(screen.getByText("要求的成功运行比例，范围 0 至 1。")).toBeVisible();
  });
});
