import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";

import { I18nProvider } from "../../i18n/I18nProvider";
import { LabCalibrationWorkspace } from "../LabCalibrationWorkspace";
import fixture from "../__fixtures__/calibration-input.fake.json";

function renderWorkspace(locale: "en" | "zh-CN" = "en") {
  window.localStorage.setItem("drone-dream:locale", locale);
  return render(
    <I18nProvider>
      <MemoryRouter><LabCalibrationWorkspace /></MemoryRouter>
    </I18nProvider>,
  );
}

describe("Lab calibration workspace", () => {
  it("renders the Lab positioning and imports one evidence-bound cycle", async () => {
    const user = userEvent.setup();
    const { container } = renderWorkspace();

    const root = container.querySelector(".lab-calibration");
    expect(root).toHaveAttribute("data-brand-edition", "lab");
    expect(root).toHaveAttribute("data-presentation-only", "true");
    expect(root).toHaveAttribute("data-grants-hardware-authority", "false");
    expect(screen.getByText("Proposal only")).toBeInTheDocument();
    expect(screen.getByText("Constraints enforced")).toBeInTheDocument();

    const file = new File([JSON.stringify(fixture)], "lab-cycle.fake.json", {
      type: "application/json",
    });
    Object.defineProperty(file, "text", { value: async () => JSON.stringify(fixture) });
    await user.upload(screen.getByLabelText("Import bound cycle evidence"), file);

    expect(await screen.findByText("lab_job_fixture_001")).toBeInTheDocument();
    expect(screen.getByText("Sim-real gap")).toBeInTheDocument();
    expect(screen.getByText(/Denied: sim-real gap exceeds tolerance/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "DENY" })).toBeDisabled();
    expect(screen.getByRole("link", { name: /Open simulation optimization/ }))
      .toHaveAttribute("href", "/jobs/new");
    const progression = screen.getByRole("list");
    expect(within(progression).getByText("Model calibration")).toBeInTheDocument();
    expect(within(progression).getByText("Independent holdout")).toBeInTheDocument();
  });

  it("rejects evidence that attempts to grant authority", async () => {
    const user = userEvent.setup();
    renderWorkspace();
    const unsafe = {
      ...fixture,
      authority: { decision: "allow", grantsHardwareAuthority: true },
    };
    const file = new File([JSON.stringify(unsafe)], "unsafe.json", { type: "application/json" });
    Object.defineProperty(file, "text", { value: async () => JSON.stringify(unsafe) });
    await user.upload(screen.getByLabelText("Import bound cycle evidence"), file);

    expect(await screen.findByText("Evidence rejected")).toBeInTheDocument();
    expect(screen.getByText(/must not grant authority/)).toBeInTheDocument();
  });

  it("provides independently authored Chinese workflow copy", () => {
    renderWorkspace("zh-CN");
    expect(screen.getByRole("heading", { name: "双向校准闭环" })).toBeInTheDocument();
    expect(screen.getByText("仅提出建议")).toBeInTheDocument();
    expect(screen.getByText("强制约束")).toBeInTheDocument();
    expect(screen.getByText("真机权限")).toBeInTheDocument();
  });
});
