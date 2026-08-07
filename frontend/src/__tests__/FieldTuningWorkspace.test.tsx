import { fireEvent, render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";

import { FieldTuningWorkspace } from "../field/FieldTuningWorkspace";

describe("FieldTuningWorkspace", () => {
  beforeEach(() => {
    delete window.__TAURI__;
  });

  it("runs the complete fixture Model and Harness loop without hardware authority", () => {
    const { container } = render(
      <FieldTuningWorkspace
        locale="en"
        selectedPackId="holybro-x500-v2-pixhawk6"
        selectedControllerId="Holybro::Pixhawk 6C"
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Run safe tuning demo" }));

    expect(screen.getByRole("heading", { name: "Candidate history" })).toBeInTheDocument();
    expect(screen.getAllByRole("row")).toHaveLength(6);
    expect(screen.getByText("Independent holdout")).toBeInTheDocument();
    expect(screen.getByText("Demo-qualified only")).toBeInTheDocument();
    expect(container.querySelector("[data-authority='false']")).toBeTruthy();
    expect(container.querySelector("[data-simulation='false']")).toBeTruthy();
  });

  it("returns a typed real-hardware denial with all mandatory evidence", () => {
    render(
      <FieldTuningWorkspace
        locale="en"
        selectedPackId="holybro-x500-v2-pixhawk6"
        selectedControllerId="Holybro::Pixhawk 6C"
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Evaluate current hardware gate" }));

    const status = screen.getByRole("status");
    expect(within(status).getByText("field.registry.zero-validated-packs"))
      .toBeInTheDocument();
    expect(within(status).getByText("parameter-snapshot")).toBeInTheDocument();
    expect(within(status).getByText("transaction-rollback")).toBeInTheDocument();
    expect(within(status).getByText(/canExecute=false/)).toBeInTheDocument();
  });

  it("authors the Chinese tuning workflow independently", () => {
    render(
      <FieldTuningWorkspace
        locale="zh-CN"
        selectedPackId="holybro-x500-v2-pixhawk6"
        selectedControllerId="Holybro::Pixhawk 6C"
      />,
    );

    expect(screen.getByRole("heading", { name: "真机自主调参" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "运行安全调参演示" })).toBeInTheDocument();
    expect(screen.getByText("Model 提出受边界约束的候选参数，Harness 负责受控实验、遥测评分、失败分类和回滚证据。"))
      .toBeInTheDocument();
  });
});
