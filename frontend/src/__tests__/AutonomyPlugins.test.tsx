import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

const pluginMocks = vi.hoisted(() => ({
  catalog: vi.fn(),
  harness: vi.fn(),
  plugins: vi.fn(),
}));

vi.mock("../i18n/I18nProvider", () => ({
  useI18n: () => ({ interfaceLocale: "en-US" }),
}));

vi.mock("../features/autonomy/agentCore", () => ({
  AgentCoreRequestError: class AgentCoreRequestError extends Error { status = 400; },
  AgentCoreUnavailableError: class AgentCoreUnavailableError extends Error {},
  getAgentCoreHarnessCatalog: pluginMocks.catalog,
  getAgentCoreHarnessState: pluginMocks.harness,
  importAgentCorePlugin: vi.fn(),
  listAgentCorePlugins: pluginMocks.plugins,
  uninstallAgentCorePlugin: vi.fn(),
}));

import { AutonomyPlugins } from "../pages/AutonomyPlugins";

describe("two-level plug-in studio", () => {
  beforeEach(() => {
    pluginMocks.catalog.mockResolvedValue(null);
    pluginMocks.harness.mockResolvedValue(null);
    pluginMocks.plugins.mockResolvedValue([]);
  });

  it("keeps the default Harness to four level-one blocks and exposes level two on demand", async () => {
    render(<MemoryRouter><AutonomyPlugins /></MemoryRouter>);

    expect(await screen.findByText("Balanced closed loop")).toBeInTheDocument();
    expect(screen.getByText("4 level-one blocks · 12 level-two plug-ins")).toBeInTheDocument();
    expect(screen.queryByText(/level three/i)).not.toBeInTheDocument();

    fireEvent.click(screen.getByText("Plan and decide"));

    expect(screen.getByRole("heading", { name: "Plan and decide" })).toBeInTheDocument();
    expect(screen.getByText("Route planner")).toBeInTheDocument();
    expect(screen.getByText(/Internal policies no longer create a third visible level/)).toBeInTheDocument();
  });

  it("switches to the standalone plug-in library without leaving the page", async () => {
    render(<MemoryRouter><AutonomyPlugins /></MemoryRouter>);
    await screen.findByText("Balanced closed loop");

    fireEvent.click(screen.getByRole("button", { name: "Library" }));

    expect(screen.getByRole("textbox", { name: "Search plug-ins" })).toBeInTheDocument();
    expect(screen.getByText("No standalone plug-ins installed")).toBeInTheDocument();
  });
});
