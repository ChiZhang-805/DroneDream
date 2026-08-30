import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

const pluginMocks = vi.hoisted(() => ({
  applyProfile: vi.fn(),
  catalog: vi.fn(),
  editHarness: vi.fn(),
  harness: vi.fn(),
  plugins: vi.fn(),
  setPlugin: vi.fn(),
}));

vi.mock("../i18n/I18nProvider", () => ({
  useI18n: () => ({ interfaceLocale: "en-US" }),
}));

vi.mock("../features/autonomy/agentCore", () => ({
  AgentCoreRequestError: class AgentCoreRequestError extends Error { status = 400; },
  AgentCoreUnavailableError: class AgentCoreUnavailableError extends Error {},
  applyAgentCoreHarnessProfile: pluginMocks.applyProfile,
  editAgentCoreHarness: pluginMocks.editHarness,
  getAgentCoreHarnessCatalog: pluginMocks.catalog,
  getAgentCoreHarnessState: pluginMocks.harness,
  importAgentCorePlugin: vi.fn(),
  listAgentCorePlugins: pluginMocks.plugins,
  setAgentCorePlugin: pluginMocks.setPlugin,
  uninstallAgentCorePlugin: vi.fn(),
}));

import { AutonomyPlugins } from "../pages/AutonomyPlugins";

describe("two-level plug-in studio", () => {
  beforeEach(() => {
    vi.clearAllMocks();
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

  it("switches a live level-two replacement through its real Harness plug-in slot", async () => {
    const compositionItem = (id: string, level: number, parent: string | null, nodeId: string, order: number) => ({
      item_id: id, level, parent_item_id: parent, title: id.split(".").at(-1), title_zh: "",
      description: `${id} description`, description_zh: "", category_id: "control",
      order, member_node_ids: nodeId ? [nodeId] : [], plugin_slot_ids: [] as string[], child_item_ids: [] as string[],
      replaceable: true, protected: false,
    });
    const phases = [
      ["composition.phase.alpha", "composition.stage.alpha", "mission.tool-advice", "Tool advisor"],
      ["composition.phase.beta", "composition.stage.beta", "mission.plan-evaluation", "Plan evaluation"],
      ["composition.phase.gamma", "composition.stage.gamma", "mission.route-resolve", "Route resolution"],
    ] as const;
    const items = phases.flatMap(([phaseId, stageId, nodeId, title], index) => {
      const phase = { ...compositionItem(phaseId, 1, null, nodeId, index), title: `Phase ${index + 1}` };
      const stage = { ...compositionItem(stageId, 2, phaseId, nodeId, index), title };
      return [phase, stage];
    });
    items.push({
      ...compositionItem("composition.slot.budget", 3, "composition.stage.alpha", "", 0),
      title: "Call budget", plugin_slot_ids: ["harness.budget-policy"],
    });
    pluginMocks.catalog.mockResolvedValue({
      composition_items: items,
      node_descriptors: [], profiles: [], topology_templates: [], context_commands: {},
      plugins: [
        {
          plugin_id: "harness.budget-standard", name: "Standard budget", description: "Standard call budget",
          slot_id: "harness.budget-policy", slot_label: "Call budget", activation_mode: "single",
          enabled: true, granularity: "small", owner_item_ids: ["composition.stage.alpha"],
        },
        {
          plugin_id: "harness.budget-cost-capped", name: "Cost-capped budget", description: "Bounded call budget",
          slot_id: "harness.budget-policy", slot_label: "Call budget", activation_mode: "single",
          enabled: false, granularity: "small", owner_item_ids: ["composition.stage.alpha"],
        },
      ],
    });
    const nodes = phases.map(([, , nodeId]) => ({
      node_id: nodeId, capabilities: { protected: false, replaceable: true, removable: true },
    }));
    const current = { revision: 4, candidate: { nodes, profile_id: "harness.profile-balanced" } };
    pluginMocks.harness.mockResolvedValue({ active: current, current, can_undo: false, can_redo: false });
    pluginMocks.setPlugin.mockResolvedValue({});

    render(<MemoryRouter><AutonomyPlugins /></MemoryRouter>);
    await screen.findByText("3 level-one blocks · 3 level-two plug-ins");
    fireEvent.contextMenu(screen.getByRole("listitem", { name: /Tool advisor/ }), { clientX: 350, clientY: 320 });
    fireEvent.click(screen.getByRole("menuitem", { name: "Replace" }));

    const submenu = screen.getByRole("menu", { name: "Same-level replacements" });
    expect(submenu).toHaveTextContent("Call budget");
    fireEvent.click(screen.getByRole("menuitem", { name: "Cost-capped budget" }));

    await waitFor(() => expect(pluginMocks.setPlugin).toHaveBeenCalledWith("harness.budget-cost-capped", true));
    expect(pluginMocks.editHarness).not.toHaveBeenCalled();
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
