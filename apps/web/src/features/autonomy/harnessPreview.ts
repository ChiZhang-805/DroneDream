import type {
  AgentCoreHarnessCatalog,
  AgentCoreHarnessCandidate,
  AgentCoreHarnessCompositionItem,
  AgentCoreHarnessEdge,
  AgentCoreHarnessNode,
  AgentCoreHarnessRevision,
  AgentCoreHarnessState,
} from "./agentCore";

type PreviewStage = {
  id: string;
  title: string;
  titleZh: string;
  description: string;
  descriptionZh: string;
  category: string;
  kind: AgentCoreHarnessNode["node_kind"];
  icon: string;
  protected?: boolean;
};

type PreviewPhase = {
  id: string;
  title: string;
  titleZh: string;
  description: string;
  descriptionZh: string;
  category: string;
  icon: string;
  stages: PreviewStage[];
};

const PREVIEW_PHASES: PreviewPhase[] = [
  {
    id: "intake",
    title: "Task intake",
    titleZh: "任务接入",
    description: "Understand the goal and establish trusted task context.",
    descriptionZh: "理解目标并建立可靠的任务上下文。",
    category: "input",
    icon: "inbox",
    stages: [
      { id: "intent", title: "Intent parser", titleZh: "意图解析", description: "Extract goals, constraints, and live interrupts.", descriptionZh: "提取目标、约束和实时打断指令。", category: "reasoning", kind: "model_call", icon: "brain" },
      { id: "context", title: "Context loader", titleZh: "上下文装载", description: "Bind the map, aircraft, and live state.", descriptionZh: "绑定地图、飞行器与实时状态。", category: "memory", kind: "transform", icon: "database" },
      { id: "guard", title: "Input safety gate", titleZh: "输入安全门", description: "Block unsafe or incomplete missions.", descriptionZh: "阻止越权或不完整的任务进入执行。", category: "safety", kind: "safety_barrier", icon: "shield", protected: true },
    ],
  },
  {
    id: "planning",
    title: "Plan and decide",
    titleZh: "规划与决策",
    description: "Build routes and make decisions within constraints.",
    descriptionZh: "生成路线，并在约束内作出决策。",
    category: "planning",
    icon: "brain",
    stages: [
      { id: "mission-plan", title: "Mission planner", titleZh: "任务规划", description: "Turn language into an executable mission graph.", descriptionZh: "把自然语言转成可执行任务图。", category: "orchestration", kind: "model_call", icon: "brain" },
      { id: "route-plan", title: "Route planner", titleZh: "路径规划", description: "Route around mapped and observed obstacles.", descriptionZh: "依据地图与感知障碍物生成航路。", category: "planning", kind: "tool_call", icon: "waypoints" },
      { id: "approval", title: "Decision approval", titleZh: "决策审批", description: "Hold high-risk actions for required approval.", descriptionZh: "在高风险动作前请求必要确认。", category: "assurance", kind: "human_approval", icon: "badge-check", protected: true },
    ],
  },
  {
    id: "execution",
    title: "Flight execution",
    titleZh: "飞行执行",
    description: "Dispatch control through a high-frequency closed loop.",
    descriptionZh: "持续下发控制，并保持高频闭环。",
    category: "control",
    icon: "plug",
    stages: [
      { id: "dispatch", title: "Command dispatch", titleZh: "指令调度", description: "Translate the plan into PX4 or device commands.", descriptionZh: "将计划转成 PX4 或真机命令。", category: "integration", kind: "tool_call", icon: "plug" },
      { id: "telemetry", title: "Telemetry sync", titleZh: "遥测同步", description: "Read pose, position, and health at high frequency.", descriptionZh: "高频读取姿态、位置与健康状态。", category: "control", kind: "bounded_loop", icon: "waypoints", protected: true },
      { id: "replan", title: "Live replanning", titleZh: "动态重规划", description: "Hover on interrupt, then replan from live position.", descriptionZh: "被打断时先悬停，再从实时位置重规划。", category: "orchestration", kind: "branch", icon: "brain" },
    ],
  },
  {
    id: "verification",
    title: "Verify and deliver",
    titleZh: "验证与交付",
    description: "Monitor risk, confirm results, and preserve evidence.",
    descriptionZh: "监测风险，确认结果并保存证据。",
    category: "assurance",
    icon: "badge-check",
    stages: [
      { id: "monitor", title: "Safety monitor", titleZh: "安全监测", description: "Detect collisions, disconnects, and mission drift.", descriptionZh: "识别碰撞、失联和任务偏差。", category: "safety", kind: "safety_barrier", icon: "shield", protected: true },
      { id: "validate", title: "Result validator", titleZh: "结果验证", description: "Judge success from observed state, never path crossing.", descriptionZh: "用真实状态判断成功，不以穿越路径代替。", category: "assurance", kind: "join", icon: "badge-check", protected: true },
      { id: "evidence", title: "Evidence delivery", titleZh: "证据交付", description: "Save trajectory, recording, and mission receipts.", descriptionZh: "保存轨迹、录像和任务回执。", category: "output", kind: "output", icon: "database" },
    ],
  },
];

const inputPort = (id: string): AgentCoreHarnessNode["input_ports"][number] => ({
  port_id: "flow-in",
  schema_ref: "dronedream.harness.preview.v1",
  required: id !== "intake.intent",
  cardinality: "one",
  confidentiality: "task",
  maximum_connections: 4,
});

const outputPort = (): AgentCoreHarnessNode["output_ports"][number] => ({
  port_id: "flow-out",
  schema_ref: "dronedream.harness.preview.v1",
  required: false,
  cardinality: "one",
  confidentiality: "task",
  maximum_connections: 4,
});

function previewNodes(): AgentCoreHarnessNode[] {
  return PREVIEW_PHASES.flatMap((phase) => phase.stages.map((stage) => {
    const nodeId = `${phase.id}.${stage.id}`;
    return {
      node_id: nodeId,
      descriptor_id: `preview.${nodeId}`,
      title: stage.title,
      title_zh: stage.titleZh,
      node_kind: stage.kind,
      handler_id: `preview.${nodeId}`,
      runtime_node_kind: stage.protected ? "barrier" : stage.kind === "tool_call" ? "plugin" : "core",
      required_inputs: [],
      output_key: nodeId,
      input_ports: [inputPort(nodeId)],
      output_ports: [outputPort()],
      policy: {
        timeout_seconds: stage.kind === "bounded_loop" ? 10 : 30,
        retry_limit: stage.protected ? 0 : 2,
        failure_mode: stage.protected ? "fail-closed" : "fallback",
        fallback_handler_id: null,
        cacheable: stage.kind === "transform",
        authority: stage.kind === "tool_call" || stage.kind === "bounded_loop" ? "simulate" : "plan",
        maximum_model_calls: stage.kind === "model_call" ? 3 : null,
        maximum_tool_calls: stage.kind === "tool_call" ? 8 : null,
      },
      capabilities: {
        removable: !stage.protected,
        replaceable: !stage.protected,
        branchable: stage.kind === "model_call" || stage.kind === "branch",
        wrappable_in_loop: !stage.protected,
        protected: Boolean(stage.protected),
        allowed_operations: stage.protected ? ["move_node", "update_node"] : ["move_node", "update_node", "remove_node", "connect"],
      },
      category: stage.category,
      icon: stage.icon,
    } satisfies AgentCoreHarnessNode;
  }));
}

function previewEdges(nodes: AgentCoreHarnessNode[]): AgentCoreHarnessEdge[] {
  return nodes.slice(0, -1).map((node, index) => ({
    schema_version: "dronedream.harness-edge-binding.v1",
    edge_id: `preview-edge-${index + 1}`,
    source: { node_id: node.node_id, port_id: "flow-out" },
    target: { node_id: nodes[index + 1].node_id, port_id: "flow-in" },
    schema_ref: "dronedream.harness.preview.v1",
    transform_plugin_id: null,
    binding_mode: "direct",
  }));
}

function previewCompositionItems(): AgentCoreHarnessCompositionItem[] {
  return PREVIEW_PHASES.flatMap((phase, phaseIndex) => {
    const phaseId = `composition.phase.${phase.id}`;
    const memberNodeIds = phase.stages.map((stage) => `${phase.id}.${stage.id}`);
    const stageItems = phase.stages.map((stage, stageIndex): AgentCoreHarnessCompositionItem => {
      const nodeId = `${phase.id}.${stage.id}`;
      const itemId = `composition.stage.${nodeId}`;
      return {
        schema_version: "dronedream.harness-composition-item.v1",
        item_id: itemId,
        level: 2,
        parent_item_id: phaseId,
        kind: "stage",
        granularity: "medium",
        title: stage.title,
        title_zh: stage.titleZh,
        description: stage.description,
        description_zh: stage.descriptionZh,
        category_id: stage.category,
        color_token: phaseIndex === 0 ? "amber" : phaseIndex === 1 ? "violet" : phaseIndex === 2 ? "blue" : "green",
        visual_kind: "puzzle",
        aspect_ratio: "1.5:1",
        icon: stage.icon,
        order: stageIndex,
        member_node_ids: [nodeId],
        plugin_slot_ids: [],
        child_item_ids: [],
        enterable: false,
        replaceable: !stage.protected,
        protected: Boolean(stage.protected),
        scope: "node",
      };
    });
    const phaseItem: AgentCoreHarnessCompositionItem = {
      schema_version: "dronedream.harness-composition-item.v1",
      item_id: phaseId,
      level: 1,
      parent_item_id: null,
      kind: "phase",
      granularity: "large",
      title: phase.title,
      title_zh: phase.titleZh,
      description: phase.description,
      description_zh: phase.descriptionZh,
      category_id: phase.category,
      color_token: phaseIndex === 0 ? "amber" : phaseIndex === 1 ? "violet" : phaseIndex === 2 ? "blue" : "green",
      visual_kind: "puzzle",
      aspect_ratio: "1.5:1",
      icon: phase.icon,
      order: phaseIndex,
      member_node_ids: memberNodeIds,
      plugin_slot_ids: [],
      child_item_ids: stageItems.map((item) => item.item_id),
      enterable: true,
      replaceable: false,
      protected: phase.stages.some((stage) => stage.protected),
      scope: "phase",
    };
    return [phaseItem, ...stageItems];
  });
}

export function createHarnessPreview(): {
  catalog: AgentCoreHarnessCatalog;
  harness: AgentCoreHarnessState;
} {
  const nodes = previewNodes();
  const edges = previewEdges(nodes);
  const candidate: AgentCoreHarnessCandidate = {
    schema_version: "dronedream.harness-topology-candidate.v2",
    topology_id: "topology.balanced-closed-loop",
    name: "Balanced closed loop",
    profile_id: "harness.profile-balanced",
    base_revision: 0,
    nodes,
    edges,
    loops: [],
    maximum_parallelism: 4,
    layout: {
      positions: Object.fromEntries(nodes.map((node, index) => [node.node_id, { x: 72 + index * 190, y: 88, pinned: false }])),
      viewport: { x: 0, y: 0, zoom: 0.78 },
      collapsed_node_ids: [],
      selected_node_id: null,
    },
    metadata: { preview: true },
  };
  const revision: AgentCoreHarnessRevision = {
    revision: 0,
    parent_revision: null,
    state: "active",
    candidate,
    validation: {
      valid: true,
      issues: [],
      semantic_sha256: null,
      layout_sha256: null,
      compiled_topology: null,
    },
    created_at: "2026-01-01T00:00:00Z",
    activated_at: "2026-01-01T00:00:00Z",
    applies_next_run: false,
  };
  return {
    catalog: {
      schema_version: "dronedream.harness-catalog.v1",
      node_descriptors: [],
      topology_templates: [{
        topology_id: candidate.topology_id,
        name: candidate.name,
        node_count: nodes.length,
        maximum_parallelism: candidate.maximum_parallelism,
        metadata: { preview: true },
      }],
      plugins: [],
      profiles: [{
        profile_id: candidate.profile_id,
        name: "Balanced autonomy",
        description: "A safe, medium-length mission Harness.",
        enabled: true,
        health: "preview",
        trust_status: "builtin",
      }],
      composition_items: previewCompositionItems(),
      context_commands: {
        phase: ["open", "inspect", "library"],
        stage: ["inspect", "library"],
      },
    },
    harness: { active: revision, current: revision, can_undo: false, can_redo: false },
  };
}
