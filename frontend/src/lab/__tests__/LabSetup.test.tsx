import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it } from "vitest";

import { I18nProvider } from "../../i18n/I18nProvider";
import { LabSetup } from "../LabSetup";
import fakeReceipt from "../__fixtures__/sim-qualification-receipt.fake.json";

function renderLab(locale: "en" | "zh-CN" = "en") {
  window.localStorage.setItem("drone-dream:locale", locale);
  return render(
    <I18nProvider>
      <MemoryRouter>
        <LabSetup />
      </MemoryRouter>
    </I18nProvider>,
  );
}

describe("Lab setup", () => {
  beforeEach(() => {
    window.localStorage.clear();
  });

  it("separates simulation and hardware workflows without UI authority", async () => {
    const user = userEvent.setup();
    renderLab();

    expect(screen.getByRole("heading", { name: "Sim-to-Real calibration laboratory" }))
      .toBeInTheDocument();
    expect(screen.getByText("0 of 8")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Simulation workspace/i }))
      .toHaveAttribute("aria-pressed", "true");
    const workspaceNotice = screen.getByText(
      "Workspace selection changes the workflow only; it never grants hardware authority.",
      { exact: true },
    );
    expect(workspaceNotice).toBeInTheDocument();
    expect(workspaceNotice.closest(".lab-page"))
      .toHaveAttribute("data-grants-hardware-authority", "false");

    await user.click(screen.getByRole("button", { name: /Hardware laboratory/i }));
    expect(screen.getByRole("button", { name: /Hardware laboratory/i }))
      .toHaveAttribute("aria-pressed", "true");
    const packSelect = screen.getByRole("combobox", { name: "Vehicle Pack" });
    expect(packSelect).toHaveValue("holybro-x500-v2-pixhawk6");
    expect(within(packSelect).getAllByRole("option")).toHaveLength(7);

    for (const name of [
      "Discover controller",
      "Write parameters",
      "Arm vehicle",
      "Start flight / HITL",
    ]) {
      expect(screen.getByRole("button", { name })).toBeDisabled();
    }
  });

  it("previews fake Sim evidence while retaining a deny decision", async () => {
    const user = userEvent.setup();
    renderLab();

    const evidenceTab = screen.getByRole("tab", { name: "Qualification evidence" });
    await user.click(evidenceTab);
    const file = new File(
      [JSON.stringify(fakeReceipt)],
      "sim-receipt.fake.json",
      { type: "application/json" },
    );
    Object.defineProperty(file, "text", {
      value: async () => JSON.stringify(fakeReceipt),
    });
    await user.upload(screen.getByLabelText("Choose JSON evidence"), file);

    expect(await screen.findByText("sim-receipt.fake.json")).toBeInTheDocument();
    expect(screen.getByText("PREVIEW ONLY")).toBeInTheDocument();
    expect(screen.getByText("MPC_XY_P")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /authorize/i })).not.toBeInTheDocument();
  });

  it("supports arrow-key tab navigation and exposes a fail-closed safety review", async () => {
    const user = userEvent.setup();
    renderLab();

    const setupTab = screen.getByRole("tab", { name: "Setup" });
    setupTab.focus();
    await user.keyboard("{ArrowRight}{ArrowRight}");

    const safetyTab = screen.getByRole("tab", { name: "Safety review" });
    expect(safetyTab).toHaveAttribute("aria-selected", "true");
    expect(safetyTab).toHaveFocus();
    const quorum = screen.getByLabelText("Execution quorum");
    expect(within(quorum).getAllByText("Missing")).toHaveLength(3);
    expect(within(quorum).getByText("DENY")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Confirm hardware action" }))
      .toBeDisabled();
    expect(screen.getByLabelText("Operator challenge")).toBeDisabled();
  });

  it("provides independently authored Simplified Chinese product copy", async () => {
    const user = userEvent.setup();
    renderLab("zh-CN");

    expect(screen.getByRole("heading", { name: "Sim-to-Real 校准实验室" }))
      .toBeInTheDocument();
    expect(screen.getByText(/同一份受预算约束的作业/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /真机实验室/ }));
    expect(screen.getByRole("button", { name: "写入参数" })).toBeDisabled();
    expect(screen.getByText("真机执行已拒绝")).toBeInTheDocument();
  });
});
