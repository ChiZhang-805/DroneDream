import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it } from "vitest";

import {
  SimEditionSettingsPanel,
  SimOverview,
} from "../editions/sim/SimEditionExperience";
import { I18nProvider } from "../i18n/I18nProvider";

function renderOverview(entry = "/sim") {
  return render(
    <I18nProvider>
      <MemoryRouter initialEntries={[entry]}>
        <SimOverview />
      </MemoryRouter>
    </I18nProvider>,
  );
}

afterEach(() => window.localStorage.clear());

describe("DroneDream Sim experience", () => {
  it("shows only simulation surfaces and external dependencies", () => {
    window.localStorage.setItem("drone-dream:locale", "en");
    const { container } = renderOverview();

    expect(screen.getByRole("heading", { level: 1, name: "DroneDream \u00b7 SIM" }))
      .toBeInTheDocument();
    const lockup = container.querySelector(".sim-overview-lockup");
    const mark = container.querySelector(".sim-brand-mark");
    expect(lockup?.getAttribute("src")).toContain("dronedream-sim-dot-lockup.png");
    expect(lockup).toHaveAttribute("aria-hidden", "true");
    expect(mark?.getAttribute("src")).toContain("dronedream-sim-mark.png");
    expect(mark).toHaveAttribute("aria-hidden", "true");
    expect(screen.getByRole("list", { name: "Simulation workspace" }))
      .toHaveTextContent("PX4 SITL");
    expect(screen.getByRole("list", { name: "External dependencies" }))
      .toHaveTextContent("Runtime Base");
    expect(screen.getAllByRole("listitem")).toHaveLength(6);
    for (const label of [
      "Simulation",
      "PX4 SITL",
      "Gazebo",
      "Sim Vehicle Packs",
      "Runtime Base",
      "Engine Pack",
    ]) {
      expect(screen.getByText(label)).toBeInTheDocument();
    }
    expect(screen.getAllByText("External")).toHaveLength(2);
    expect(screen.getByRole("link", { name: /Open setup preview/ }))
      .toHaveAttribute("href", "/desktop/setup");
    expect(screen.queryByText(/DroneDream Lab/)).not.toBeInTheDocument();
    expect(screen.queryByText(/DroneDream Field/)).not.toBeInTheDocument();
  });

  it("renders independent Simplified Chinese copy", () => {
    window.localStorage.setItem("drone-dream:locale", "zh-CN");
    renderOverview();

    expect(screen.getByRole("heading", { level: 1, name: "DroneDream \u00b7 SIM" }))
      .toBeInTheDocument();
    expect(screen.getByText("纯仿真内测预览")).toBeInTheDocument();
    expect(screen.getByText("Sim 仿真机型包")).toBeInTheDocument();
    expect(screen.getAllByText("外置")).toHaveLength(2);
    expect(screen.getByRole("link", { name: /打开设置预览/ }))
      .toBeInTheDocument();
  });

  it("explains fail-closed redirects without offering a mode switch", () => {
    window.localStorage.setItem("drone-dream:locale", "en");
    renderOverview("/sim?blocked=hardware");

    expect(screen.getByRole("alert")).toHaveTextContent(
      "Unavailable in DroneDream Sim",
    );
    expect(screen.queryByRole("radio")).not.toBeInTheDocument();
  });

  it("exposes the fixed Sim mode in settings", () => {
    window.localStorage.setItem("drone-dream:locale", "en");
    render(
      <I18nProvider>
        <SimEditionSettingsPanel />
      </I18nProvider>,
    );

    expect(screen.getByRole("heading", { name: "Sim edition" })).toBeInTheDocument();
    expect(screen.getByText(/There is no Lab or Field mode switch/)).toBeInTheDocument();
    expect(screen.queryByRole("radio")).not.toBeInTheDocument();
  });
});
