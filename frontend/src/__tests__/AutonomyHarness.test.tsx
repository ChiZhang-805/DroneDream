import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";

const harnessMocks = vi.hoisted(() => ({
  catalog: vi.fn(),
  state: vi.fn(),
}));

vi.mock("../i18n/I18nProvider", () => ({
  useI18n: () => ({ interfaceLocale: "zh-CN" }),
}));

vi.mock("@xyflow/react", () => ({
  Background: () => null,
  Controls: () => null,
  Handle: () => null,
  MarkerType: { ArrowClosed: "arrow" },
  MiniMap: () => null,
  Position: { Left: "left", Right: "right" },
  ReactFlow: ({ nodes }: { nodes: Array<{ id: string; data: { node: { title_zh: string } } }> }) => (
    <div data-testid="harness-canvas">{nodes.map((node) => <span key={node.id}>{node.data.node.title_zh}</span>)}</div>
  ),
  applyEdgeChanges: (_changes: unknown, values: unknown) => values,
  applyNodeChanges: (_changes: unknown, values: unknown) => values,
}));

vi.mock("../features/autonomy/agentCore", () => ({
  AgentCoreRequestError: class AgentCoreRequestError extends Error { status = 400; },
  AgentCoreUnavailableError: class AgentCoreUnavailableError extends Error {},
  dryRunAgentCoreHarness: vi.fn(),
  editAgentCoreHarness: vi.fn(),
  getAgentCoreHarnessCatalog: harnessMocks.catalog,
  getAgentCoreHarnessState: harnessMocks.state,
  listAgentCoreHarnessReceipts: vi.fn(),
  redoAgentCoreHarness: vi.fn(),
  undoAgentCoreHarness: vi.fn(),
}));

import { AutonomyHarness } from "../pages/AutonomyHarness";

const node = {
  node_id: "mission.request-ingest",
  descriptor_id: "mission.request-ingest",
  title: "Request ingest",
  title_zh: "接收任务",
  node_kind: "input",
  handler_id: "core.request-ingest",
  runtime_node_kind: "core",
  required_inputs: [],
  output_key: "request",
  input_ports: [],
  output_ports: [{ port_id: "request", schema_ref: "dronedream.request.v1", required: false, cardinality: "one", confidentiality: "task", maximum_connections: 8 }],
  policy: { timeout_seconds: 30, retry_limit: 0, failure_mode: "fail-closed", fallback_handler_id: null, cacheable: false, authority: "plan", maximum_model_calls: null, maximum_tool_calls: null },
  capabilities: { removable: false, replaceable: false, branchable: false, wrappable_in_loop: false, protected: true, allowed_operations: ["move_node", "update_node"] },
  category: "core",
  icon: "circle-dot",
};

const candidate = {
  schema_version: "dronedream.harness-topology-candidate.v2",
  topology_id: "topology.balanced-closed-loop",
  name: "均衡闭环拓扑",
  profile_id: "harness.profile-balanced",
  base_revision: 0,
  nodes: [node],
  edges: [],
  loops: [],
  maximum_parallelism: 4,
  layout: { positions: { [node.node_id]: { x: 80, y: 80, pinned: false } }, viewport: { x: 0, y: 0, zoom: 1 }, collapsed_node_ids: [], selected_node_id: null },
  metadata: {},
};

describe("visual Harness composer", () => {
  it("keeps the switch library linked while rendering the active runtime revision", async () => {
    const revision = {
      revision: 4,
      parent_revision: 3,
      state: "active",
      candidate,
      validation: { valid: true, issues: [], semantic_sha256: "a".repeat(64), layout_sha256: "b".repeat(64), compiled_topology: {} },
      created_at: "2026-08-22T00:00:00Z",
      activated_at: "2026-08-22T00:00:00Z",
      applies_next_run: true,
    };
    harnessMocks.catalog.mockResolvedValue({
      schema_version: "dronedream.harness-catalog.v1",
      node_descriptors: [{ ...node, schema_version: "dronedream.harness-node-descriptor.v1" }],
      topology_templates: [{ topology_id: candidate.topology_id, name: candidate.name, node_count: 1, maximum_parallelism: 4, metadata: {} }],
      plugins: [],
      profiles: [{ profile_id: candidate.profile_id, name: "均衡", description: "", enabled: true, health: "healthy", trust_status: "builtin" }],
      context_commands: { protected_node: ["inspect", "dry_run"] },
    });
    harnessMocks.state.mockResolvedValue({ active: revision, current: revision, can_undo: true, can_redo: false });

    render(<MemoryRouter initialEntries={["/autonomy/plugins/harness"]}><AutonomyHarness /></MemoryRouter>);

    expect(await screen.findByText("接收任务")).toBeVisible();
    expect(screen.getByRole("link", { name: "插件库" })).toHaveAttribute("href", "/autonomy/plugins");
    expect(screen.getByRole("link", { name: "管理开关" })).toHaveAttribute("href", "/autonomy/plugins");
    expect(screen.getByText("R4")).toBeVisible();
    expect(screen.getByText("已激活")).toBeVisible();
  });
});
