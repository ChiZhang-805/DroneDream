import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

const pluginMocks = vi.hoisted(() => ({
  catalog: vi.fn(),
  editHarness: vi.fn(),
  harness: vi.fn(),
  plugins: vi.fn(),
}));

vi.mock("../i18n/I18nProvider", () => ({
  useI18n: () => ({ interfaceLocale: "en-US" }),
}));

vi.mock("../features/autonomy/agentCore", () => ({
  AgentCoreRequestError: class AgentCoreRequestError extends Error { status = 400; },
  AgentCoreUnavailableError: class AgentCoreUnavailableError extends Error {},
  editAgentCoreHarness: pluginMocks.editHarness,
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
    expect(screen.getByText(/Right-click any piece to inspect, replace, or remove it/)).toBeInTheDocument();
    expect(screen.queryByText(/A complete work stage/)).not.toBeInTheDocument();
  });

  it("switches to the standalone plug-in library without leaving the page", async () => {
    render(<MemoryRouter><AutonomyPlugins /></MemoryRouter>);
    await screen.findByText("Balanced closed loop");

    fireEvent.click(screen.getByRole("button", { name: "Library" }));

    expect(screen.getByRole("textbox", { name: "Search plug-ins" })).toBeInTheDocument();
    expect(screen.queryByText("Modular flight intelligence")).not.toBeInTheDocument();
    expect(screen.getByRole("textbox", { name: "Search plug-ins" }).closest("header")).toHaveClass("agent-plugin-studio-header");
    expect(screen.getByText("No standalone plug-ins installed")).toBeInTheDocument();
  });

  it("opens a desktop context menu on right-click and shows a details card", async () => {
    render(<MemoryRouter><AutonomyPlugins /></MemoryRouter>);
    await screen.findByText("Balanced closed loop");

    fireEvent.contextMenu(screen.getByRole("listitem", { name: /Task intake/ }), { clientX: 220, clientY: 180 });

    expect(screen.getByRole("menu", { name: "Task intake actions" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("menuitem", { name: "View details…" }));

    expect(screen.getByRole("dialog", { name: "Task intake" })).toBeInTheDocument();
    expect(screen.getByText("Level 1 piece · Input")).toBeInTheDocument();
  });

  it("keeps replacement candidates at the same level and grouped by category", async () => {
    render(<MemoryRouter><AutonomyPlugins /></MemoryRouter>);
    await screen.findByText("Balanced closed loop");
    fireEvent.click(screen.getByText("Plan and decide"));

    fireEvent.contextMenu(screen.getByRole("listitem", { name: /Route planner/ }), { clientX: 350, clientY: 320 });
    fireEvent.click(screen.getByRole("menuitem", { name: "Replace" }));

    const submenu = screen.getByRole("menu", { name: "Same-level replacements" });
    expect(submenu).toHaveTextContent("Level 2 pieces only");
    expect(submenu).toHaveTextContent("Control");
    expect(submenu).not.toHaveTextContent("Task intake");

    fireEvent.keyDown(submenu, { key: "Escape" });
    expect(screen.queryByRole("menu", { name: "Same-level replacements" })).not.toBeInTheDocument();
    expect(screen.getByRole("menu", { name: "Route planner actions" })).toBeInTheDocument();
  });

  it("removes an editable preview piece but keeps safety-locked pieces protected", async () => {
    render(<MemoryRouter><AutonomyPlugins /></MemoryRouter>);
    await screen.findByText("Balanced closed loop");

    fireEvent.contextMenu(screen.getByRole("listitem", { name: /Intent parser/ }), { clientX: 320, clientY: 340 });
    fireEvent.click(screen.getByRole("menuitem", { name: "Remove" }));
    expect(screen.queryByText("Intent parser")).not.toBeInTheDocument();

    fireEvent.contextMenu(screen.getByRole("listitem", { name: /Input safety gate/ }), { clientX: 520, clientY: 340 });
    expect(screen.getByRole("menuitem", { name: "Safety locked" })).toBeDisabled();
  });

  it("supports the keyboard context-menu shortcut", async () => {
    render(<MemoryRouter><AutonomyPlugins /></MemoryRouter>);
    await screen.findByText("Balanced closed loop");
    const piece = screen.getByRole("listitem", { name: /Task intake/ });

    fireEvent.keyDown(piece, { key: "F10", shiftKey: true });

    expect(screen.getByRole("menu", { name: "Task intake actions" })).toBeInTheDocument();
  });
});
