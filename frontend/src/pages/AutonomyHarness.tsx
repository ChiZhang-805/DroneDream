import {
  Background, BaseEdge, Controls, Handle, MarkerType, Position, ReactFlow,
  applyEdgeChanges, applyNodeChanges, type Connection, type Edge, type EdgeChange,
  useNodesInitialized, useReactFlow, type EdgeProps, type Node, type NodeChange, type NodeProps,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import {
  AlertTriangle, ArrowLeft, BadgeCheck, BrainCircuit, Check, ChevronDown,
  ChevronRight, CircleDot, Database, GitBranch, Inbox, Play, PlugZap, Redo2,
  RefreshCw, RotateCcw, ScrollText, ShieldCheck, Undo2, Waypoints, Wrench, X,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState, type CSSProperties } from "react";
import { NavLink } from "react-router-dom";

import {
  AgentCoreRequestError, AgentCoreUnavailableError, dryRunAgentCoreHarness,
  editAgentCoreHarness, getAgentCoreHarnessCatalog, getAgentCoreHarnessState,
  listAgentCoreHarnessReceipts, redoAgentCoreHarness, setAgentCorePlugin,
  undoAgentCoreHarness, type AgentCoreHarnessCatalog,
  type AgentCoreHarnessCompositionItem, type AgentCoreHarnessDryRun,
  type AgentCoreHarnessEdge, type AgentCoreHarnessNode,
  type AgentCoreHarnessOperation, type AgentCoreHarnessState,
} from "../features/autonomy/agentCore";
import {
  MODEL_BAR_HEIGHT, MODEL_BAR_WIDTH, PUZZLE_HEIGHT, PUZZLE_TAB_DEPTH,
  categoryLabel, flowCertainty, harnessCategoryColors, layoutHarnessItems,
  puzzleBodyWidth, puzzlePath, type FlowCertainty, type HarnessVisualPlacement,
} from "../features/autonomy/harnessVisualLayout";
import { useI18n } from "../i18n/I18nProvider";
import "./AutonomyHarness.css";

type CatalogPlugin = AgentCoreHarnessCatalog["plugins"][number];
type HarnessNodeData = Record<string, unknown> & {
  item: AgentCoreHarnessCompositionItem;
  node: AgentCoreHarnessNode | null;
  chinese: boolean;
  issueCodes: string[];
  plugin: CatalogPlugin | null;
  policyValue: string | null;
  preview: boolean;
  focus: boolean;
  placement: HarnessVisualPlacement;
  runtimeNodeCount: number;
  onPluginDrop?: (pluginId: string, slotId: string) => void;
};
type HarnessFlowNode = Node<HarnessNodeData, "harness">;
type HarnessEdgeData = Record<string, unknown> & {
  binding?: AgentCoreHarnessEdge;
  certainty: FlowCertainty;
};
type HarnessFlowEdge = Edge<HarnessEdgeData, "harness-flow">;

function itemIcon(item: AgentCoreHarnessCompositionItem, kind?: AgentCoreHarnessNode["node_kind"]) {
  if (item.icon === "inbox") return <Inbox />;
  if (item.icon === "brain" || kind === "model_call") return <BrainCircuit />;
  if (item.icon === "shield" || kind === "safety_barrier") return <ShieldCheck />;
  if (item.icon === "badge-check") return <BadgeCheck />;
  if (item.icon === "database") return <Database />;
  if (item.icon === "plug") return <PlugZap />;
  if (kind === "tool_call") return <Wrench />;
  if (kind === "branch" || kind === "join") return <GitBranch />;
  if (kind === "bounded_loop") return <RotateCcw />;
  if (kind === "input" || kind === "output") return <CircleDot />;
  return <Waypoints />;
}

function PuzzleShape({ placement }: { placement: HarnessVisualPlacement }) {
  const width = placement.bodyWidth + PUZZLE_TAB_DEPTH * 2;
  return (
    <svg className="harness-puzzle-shape" viewBox={`0 0 ${width} ${PUZZLE_HEIGHT}`} aria-hidden="true">
      <path d={puzzlePath(placement.bodyWidth, placement.left, placement.right)} />
    </svg>
  );
}

function identifierLabel(identifier: string): string {
  return identifier.replace(/^dronedream\./u, "")
    .replace(/^(harness\.)?(profile-|topology\.)/u, "")
    .split(/[._-]+/u).filter(Boolean)
    .map((part) => `${part.charAt(0).toUpperCase()}${part.slice(1)}`).join(" ");
}

function catalogLabel(chinese: boolean, name: string, identifier: string): string {
  const chineseNames: Record<string, string> = {
    "harness.profile-balanced": "均衡自主",
    "harness.profile-evaluation-lab": "评估实验",
    "harness.profile-field-readiness": "实地准备",
    "harness.profile-emergency-response": "紧急响应",
    "topology.balanced-closed-loop": "均衡闭环",
    "topology.committee-closed-loop": "多模型审查闭环",
    "topology.rapid-safe": "快速安全闭环",
  };
  if (chinese) return chineseNames[identifier] ?? name;
  return /[\u3400-\u9fff]/u.test(name) ? identifierLabel(identifier) : name;
}

function HarnessPuzzleNode({ data, selected }: NodeProps<HarnessFlowNode>) {
  const {
    item, node, chinese, issueCodes, plugin, policyValue: value, preview, focus,
    placement, runtimeNodeCount, onPluginDrop,
  } = data;
  const title = chinese ? item.title_zh : item.title;
  const subtitle = item.kind === "phase"
    ? chinese ? `${runtimeNodeCount} 个节点` : `${runtimeNodeCount} nodes`
    : item.kind === "stage"
      ? node?.node_kind === "model_call"
        ? chinese ? "结构化模型调用" : "Structured model call"
        : node?.handler_id ?? ""
      : plugin ? catalogLabel(chinese, plugin.name, plugin.plugin_id)
        : value ?? (chinese ? "选择插件" : "Choose plugin");
  const color = harnessCategoryColors[item.category_id] ?? "#6552c7";
  const style = {
    "--piece-color": color,
    "--piece-body-width": `${placement.bodyWidth}px`,
    "--piece-outer-width": `${placement.bodyWidth + PUZZLE_TAB_DEPTH * 2}px`,
    "--model-width": `${MODEL_BAR_WIDTH}px`,
    "--model-height": `${MODEL_BAR_HEIGHT}px`,
  } as CSSProperties;

  return (
    <article
      className={`harness-visual-node is-${item.visual_kind} is-${item.kind} ${selected ? "is-selected" : ""} ${issueCodes.length ? "has-issue" : ""} ${preview ? "is-drop-preview" : ""} ${focus ? "is-focus" : ""}`}
      style={style}
      aria-label={title}
      onDragOver={item.kind === "plugin-slot" ? (event) => event.preventDefault() : undefined}
      onDrop={item.kind === "plugin-slot" ? (event) => {
        event.preventDefault();
        const pluginId = event.dataTransfer.getData("application/x-dronedream-plugin");
        const slotId = item.plugin_slot_ids[0];
        if (pluginId && slotId) onPluginDrop?.(pluginId, slotId);
      } : undefined}
    >
      {item.visual_kind === "puzzle" ? <PuzzleShape placement={placement} /> : null}
      {!preview && item.level <= 2 ? (
        <>
          <Handle type="target" position={Position.Top} id="flow-in" className="harness-flow-handle is-target" />
          <Handle type="source" position={Position.Top} id="flow-out" className="harness-flow-handle is-source" />
          <Handle type="target" position={Position.Left} id="edit-in" className="harness-edit-handle" />
          <Handle type="source" position={Position.Right} id="edit-out" className="harness-edit-handle" />
        </>
      ) : null}
      <div className="harness-piece-content">
        <span className="harness-piece-icon">{itemIcon(item, node?.node_kind)}</span>
        <div><strong>{title}</strong><small>{subtitle}</small></div>
        {item.enterable && !preview ? <ChevronRight className="harness-node-enter" /> : null}
      </div>
      {!preview ? (
        <footer>
          <span>{categoryLabel(item.category_id, chinese)}</span>
          {item.protected ? <ShieldCheck /> : issueCodes.length ? <AlertTriangle /> : <Check />}
        </footer>
      ) : null}
    </article>
  );
}

function HarnessFlowEdgeView({
  id, sourceX, sourceY, targetX, targetY, markerEnd, style,
}: EdgeProps<HarnessFlowEdge>) {
  const horizontal = Math.abs(targetX - sourceX);
  const lift = Math.max(48, Math.min(110, 42 + horizontal * 0.14));
  const path = `M ${sourceX} ${sourceY} C ${sourceX} ${sourceY - lift}, ${targetX} ${targetY - lift}, ${targetX} ${targetY}`;
  return <BaseEdge id={id} path={path} markerEnd={markerEnd} style={style} />;
}

const nodeTypes = { harness: HarnessPuzzleNode };
const edgeTypes = { "harness-flow": HarnessFlowEdgeView };

function CanvasAutoFit({ signature, level }: { signature: string; level: 1 | 2 | 3 }) {
  const nodesInitialized = useNodesInitialized();
  const { fitView } = useReactFlow();
  useEffect(() => {
    if (!nodesInitialized) return;
    const frame = window.requestAnimationFrame(() => {
      void fitView({ padding: level === 1 ? 0.1 : 0.18, duration: 220 });
    });
    return () => window.cancelAnimationFrame(frame);
  }, [fitView, level, nodesInitialized, signature]);
  return null;
}

function operation(
  baseRevision: number,
  action: AgentCoreHarnessOperation["operation"],
  payload: Record<string, unknown>,
): AgentCoreHarnessOperation {
  return {
    schema_version: "dronedream.harness-edit-operation.v1",
    client_operation_id: `desktop-${crypto.randomUUID()}`,
    base_revision: baseRevision,
    operation: action,
    payload,
  };
}

function apiError(value: unknown, chinese: boolean): string {
  if (value instanceof AgentCoreUnavailableError) {
    return chinese ? "请在 DroneDream 桌面软件中打开编排器。" : value.message;
  }
  if (value instanceof AgentCoreRequestError && value.message.startsWith("HARNESS_REVISION_CONFLICT")) {
    return chinese ? "编排已更新，正在重新载入。" : "The Harness changed elsewhere. Reloading it now.";
  }
  if (value instanceof Error) return value.message;
  return chinese ? "编排操作失败。" : "The Harness operation failed.";
}

function slotTitle(slotId: string, chinese: boolean): string {
  const values: Record<string, [string, string]> = {
    "harness.scheduler": ["调度器", "Scheduler"],
    "harness.retry-policy": ["重试策略", "Retry policy"],
    "harness.timeout-policy": ["超时策略", "Timeout policy"],
    "harness.budget-policy": ["调用预算", "Call budget"],
    "harness.fallback-policy": ["回退策略", "Fallback policy"],
    "harness.cache-policy": ["缓存策略", "Cache policy"],
    "harness.event-bus": ["事件总线", "Event bus"],
    "harness.observers": ["观测器", "Observers"],
  };
  return values[slotId]?.[chinese ? 0 : 1] ?? identifierLabel(slotId);
}

function policyValue(
  item: AgentCoreHarnessCompositionItem,
  node: AgentCoreHarnessNode | null,
  chinese: boolean,
): string | null {
  if (!node || item.kind !== "policy") return null;
  if (item.item_id.endsWith(".timeout")) return `${node.policy.timeout_seconds} ${chinese ? "秒" : "sec"}`;
  if (item.item_id.endsWith(".retry")) return chinese ? `${node.policy.retry_limit} 次` : `${node.policy.retry_limit} attempts`;
  if (item.item_id.endsWith(".failure")) {
    return chinese && node.policy.failure_mode === "fail-closed" ? "失败即关闭" : node.policy.failure_mode;
  }
  if (item.item_id.endsWith(".cache")) {
    return node.policy.cacheable ? (chinese ? "已启用" : "Enabled") : (chinese ? "未启用" : "Disabled");
  }
  return null;
}

function edgeAppearance(certainty: FlowCertainty): Pick<HarnessFlowEdge, "style" | "markerEnd"> {
  const color = certainty === "definite" ? "#4b4350" : "#8f8792";
  return {
    style: {
      stroke: color,
      strokeWidth: certainty === "definite" ? 2.2 : 1.8,
      strokeDasharray: certainty === "possible" ? "7 7" : undefined,
    },
    markerEnd: { type: MarkerType.ArrowClosed, width: 16, height: 16, color },
  };
}

export function AutonomyHarness() {
  const { interfaceLocale } = useI18n();
  const chinese = interfaceLocale === "zh-CN";
  const [catalog, setCatalog] = useState<AgentCoreHarnessCatalog | null>(null);
  const [harness, setHarness] = useState<AgentCoreHarnessState | null>(null);
  const [nodes, setNodes] = useState<HarnessFlowNode[]>([]);
  const [edges, setEdges] = useState<HarnessFlowEdge[]>([]);
  const [path, setPath] = useState<string[]>([]);
  const [orderByParent, setOrderByParent] = useState<Record<string, string[]>>({});
  const [selectedItemId, setSelectedItemId] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [dryRun, setDryRun] = useState<AgentCoreHarnessDryRun | null>(null);
  const [receipts, setReceipts] = useState<Array<Record<string, unknown>> | null>(null);
  const [contextMenu, setContextMenu] = useState<{ itemId: string; x: number; y: number } | null>(null);
  const dragRef = useRef<{ id: string; originalIndex: number; targetIndex: number } | null>(null);

  const load = useCallback(async () => {
    try {
      const [nextCatalog, nextHarness] = await Promise.all([
        getAgentCoreHarnessCatalog(), getAgentCoreHarnessState(),
      ]);
      setCatalog(nextCatalog);
      setHarness(nextHarness);
      setError(null);
    } catch (value) {
      setError(apiError(value, chinese));
    }
  }, [chinese]);

  useEffect(() => { void load(); }, [load]);

  const edit = useCallback(async (
    action: AgentCoreHarnessOperation["operation"], payload: Record<string, unknown>,
  ) => {
    if (!harness) return;
    setBusy(action);
    setError(null);
    try {
      await editAgentCoreHarness(operation(harness.current.revision, action, payload));
      await load();
    } catch (value) {
      setError(apiError(value, chinese));
      if (value instanceof AgentCoreRequestError && value.status === 409) await load();
    } finally {
      setBusy(null);
    }
  }, [chinese, harness, load]);

  const activatePlugin = useCallback(async (pluginId: string, slotId: string) => {
    const plugin = catalog?.plugins.find((value) => value.plugin_id === pluginId && value.slot_id === slotId);
    if (!plugin) return;
    setBusy(`plugin:${pluginId}`);
    setError(null);
    try {
      await setAgentCorePlugin(pluginId, plugin.activation_mode === "multiple" ? !plugin.enabled : true);
      await load();
    } catch (value) {
      setError(apiError(value, chinese));
    } finally {
      setBusy(null);
    }
  }, [catalog, chinese, load]);

  const itemMap = useMemo(
    () => new Map((catalog?.composition_items ?? []).map((item) => [item.item_id, item])), [catalog],
  );
  const nodeMap = useMemo(
    () => new Map((harness?.current.candidate.nodes ?? []).map((node) => [node.node_id, node])), [harness],
  );
  const level = Math.min(3, path.length + 1) as 1 | 2 | 3;
  const parentId = path.at(-1) ?? null;
  const parentKey = parentId ?? "root";

  const visibleItems = useMemo(() => {
    if (!catalog || !harness) return [];
    const values = catalog.composition_items.filter((item) => (
      item.level === level && item.parent_item_id === parentId
      && item.member_node_ids.some((id) => nodeMap.has(id))
    )).sort((left, right) => left.order - right.order);
    const defaults = values.map((item) => item.item_id);
    const preferred = orderByParent[parentKey] ?? [];
    const ids = [...preferred.filter((id) => defaults.includes(id)), ...defaults.filter((id) => !preferred.includes(id))];
    return ids.map((id) => itemMap.get(id))
      .filter((item): item is AgentCoreHarnessCompositionItem => Boolean(item));
  }, [catalog, harness, itemMap, level, nodeMap, orderByParent, parentId, parentKey]);

  const categorySummary = useMemo(() => {
    const counts = new Map<string, number>();
    for (const item of visibleItems) counts.set(item.category_id, (counts.get(item.category_id) ?? 0) + 1);
    return [...counts.entries()];
  }, [visibleItems]);

  const displayItems = useMemo(() => {
    if (level !== 3) return visibleItems;
    const categoryOrder = ["orchestration", "safety", "memory", "control", "integration", "assurance"];
    return [...visibleItems].sort((left, right) => {
      const leftCategory = categoryOrder.indexOf(left.category_id);
      const rightCategory = categoryOrder.indexOf(right.category_id);
      const categoryDifference = (leftCategory < 0 ? 99 : leftCategory) - (rightCategory < 0 ? 99 : rightCategory);
      return categoryDifference || left.order - right.order;
    });
  }, [level, visibleItems]);

  const buildNodes = useCallback((
    items: AgentCoreHarnessCompositionItem[], previewIndex: number | null = null,
  ): HarnessFlowNode[] => {
    if (!catalog || !harness) return [];
    const issues = new Map<string, string[]>();
    for (const issue of harness.current.validation.issues) {
      if (issue.node_id) issues.set(issue.node_id, [...(issues.get(issue.node_id) ?? []), issue.code]);
    }
    const placements = layoutHarnessItems(items, {
      maxWidth: level === 3 ? 900 : 1140,
      startX: level === 3 ? 62 : 54,
      startY: level === 3 ? 190 : 86,
      rowGap: level === 3 ? 144 : 166,
      previewIndex, previewGap: 30,
      breakOnCategory: level === 3,
    });
    const nextNodes = items.map((item, index): HarnessFlowNode => {
      const node = item.member_node_ids.length === 1 ? nodeMap.get(item.member_node_ids[0]) ?? null : null;
      const slotId = item.plugin_slot_ids[0];
      const plugin = slotId ? catalog.plugins.find((value) => value.slot_id === slotId && value.enabled) ?? null : null;
      const placement = placements[index];
      return {
        id: item.item_id,
        type: "harness",
        position: { x: placement.x, y: placement.y },
        data: {
          item, node, chinese,
          issueCodes: item.member_node_ids.flatMap((id) => issues.get(id) ?? []),
          plugin, policyValue: policyValue(item, node, chinese), preview: false, focus: false,
          placement, runtimeNodeCount: item.member_node_ids.filter((id) => nodeMap.has(id)).length,
          onPluginDrop: activatePlugin,
        },
        draggable: true,
      };
    });
    if (level === 3 && parentId) {
      const focusItem = itemMap.get(parentId);
      const focusNode = focusItem?.member_node_ids.length === 1
        ? nodeMap.get(focusItem.member_node_ids[0]) ?? null : null;
      if (focusItem) {
        const focusIsModel = focusItem.visual_kind === "model";
        const focusBodyWidth = focusIsModel ? MODEL_BAR_WIDTH : puzzleBodyWidth(focusItem);
        const focusPlacement: HarnessVisualPlacement = {
          id: `focus:${focusItem.item_id}`,
          x: focusIsModel ? 366 : 426,
          y: focusIsModel ? 54 : 24,
          row: 0,
          bodyWidth: focusBodyWidth,
          height: focusIsModel ? MODEL_BAR_HEIGHT : PUZZLE_HEIGHT,
          kind: focusIsModel ? "model" : "puzzle",
          left: { profile: "round", sign: 0 }, right: { profile: "round", sign: 0 },
        };
        nextNodes.unshift({
          id: focusPlacement.id, type: "harness",
          position: { x: focusPlacement.x, y: focusPlacement.y },
          data: {
            item: { ...focusItem, enterable: false },
            node: focusNode, chinese, issueCodes: [], plugin: null, policyValue: null,
            preview: false, focus: true, placement: focusPlacement,
            runtimeNodeCount: focusItem.member_node_ids.filter((id) => nodeMap.has(id)).length,
          },
          draggable: false,
        });
      }
    }
    return nextNodes;
  }, [activatePlugin, catalog, chinese, harness, itemMap, level, nodeMap, parentId]);

  const buildEdges = useCallback((): HarnessFlowEdge[] => {
    if (!harness || level === 3) return [];
    const nextEdges: HarnessFlowEdge[] = [];
    if (level === 1) {
      const owner = new Map<string, string>();
      for (const item of visibleItems) for (const nodeId of item.member_node_ids) owner.set(nodeId, item.item_id);
      const grouped = new Map<string, { binding: AgentCoreHarnessEdge; certainty: FlowCertainty }>();
      for (const binding of harness.current.candidate.edges) {
        const source = owner.get(binding.source.node_id);
        const target = owner.get(binding.target.node_id);
        if (!source || !target || source === target) continue;
        const certainty = flowCertainty(binding, nodeMap.get(binding.source.node_id), nodeMap.get(binding.target.node_id));
        const id = `${source}->${target}`;
        const previous = grouped.get(id);
        if (!previous || certainty === "definite") grouped.set(id, { binding, certainty });
      }
      for (const [id, value] of grouped) {
        const [source, target] = id.split("->");
        nextEdges.push({
          id, source, target, sourceHandle: "flow-out", targetHandle: "flow-in",
          type: "harness-flow", data: { certainty: value.certainty }, ...edgeAppearance(value.certainty),
        });
      }
      return nextEdges;
    }
    const owner = new Map(visibleItems.flatMap((item) => item.member_node_ids.map((id) => [id, item.item_id] as const)));
    for (const binding of harness.current.candidate.edges) {
      const source = owner.get(binding.source.node_id);
      const target = owner.get(binding.target.node_id);
      if (!source || !target) continue;
      const certainty = flowCertainty(binding, nodeMap.get(binding.source.node_id), nodeMap.get(binding.target.node_id));
      nextEdges.push({
        id: binding.edge_id, source, target, sourceHandle: "flow-out", targetHandle: "flow-in",
        type: "harness-flow", data: { binding, certainty }, ...edgeAppearance(certainty),
      });
    }
    return nextEdges;
  }, [harness, level, nodeMap, visibleItems]);

  useEffect(() => {
    if (!catalog || !harness) return;
    setNodes(buildNodes(displayItems));
    setEdges(buildEdges());
  }, [buildEdges, buildNodes, catalog, displayItems, harness]);

  const selectedItem = selectedItemId ? itemMap.get(selectedItemId) ?? null : null;
  const selectedNode = selectedItem?.member_node_ids.length === 1
    ? nodeMap.get(selectedItem.member_node_ids[0]) ?? null : null;
  const selectedSlot = selectedItem?.kind === "plugin-slot" ? selectedItem.plugin_slot_ids[0] : null;
  const selectedSlotPlugins = selectedSlot ? (catalog?.plugins ?? []).filter((plugin) => plugin.slot_id === selectedSlot) : [];
  const stageForLevel = level === 3 && parentId ? itemMap.get(parentId) ?? null : null;
  const smallPlugins = (catalog?.plugins ?? []).filter((plugin) => (stageForLevel?.plugin_slot_ids ?? []).includes(plugin.slot_id));

  const enterItem = (item: AgentCoreHarnessCompositionItem) => {
    if (!item.enterable || item.level >= 3) return;
    setPath((current) => item.level === 1 ? [item.item_id] : [current[0], item.item_id]);
    setSelectedItemId(null);
    setContextMenu(null);
  };

  const onNodesChange = useCallback((changes: NodeChange<HarnessFlowNode>[]) => {
    setNodes((values) => applyNodeChanges(changes, values));
  }, []);
  const onEdgesChange = useCallback((changes: EdgeChange<HarnessFlowEdge>[]) => {
    setEdges((values) => applyEdgeChanges(changes, values));
    for (const change of changes) {
      if (change.type !== "remove") continue;
      const edge = edges.find((value) => value.id === change.id);
      if (edge?.data?.binding) void edit("disconnect", { edge: edge.data.binding });
    }
  }, [edges, edit]);

  const connect = useCallback((connection: Connection) => {
    if (level !== 2 || !connection.source || !connection.target) return;
    const sourceItem = itemMap.get(connection.source);
    const targetItem = itemMap.get(connection.target);
    const source = sourceItem ? nodeMap.get(sourceItem.member_node_ids[0]) : null;
    const target = targetItem ? nodeMap.get(targetItem.member_node_ids[0]) : null;
    const sourcePort = source?.output_ports[0];
    const targetPort = target?.input_ports[0];
    if (!source || !target || !sourcePort || !targetPort) return;
    const binding: AgentCoreHarnessEdge = {
      schema_version: "dronedream.harness-edge-binding.v1",
      edge_id: `${source.node_id}:${sourcePort.port_id}->${target.node_id}:${targetPort.port_id}`,
      source: { node_id: source.node_id, port_id: sourcePort.port_id },
      target: { node_id: target.node_id, port_id: targetPort.port_id },
      schema_ref: sourcePort.schema_ref, transform_plugin_id: null,
      binding_mode: sourcePort.cardinality === "event" ? "control" : "direct",
    };
    void edit("connect", { edge: binding });
  }, [edit, itemMap, level, nodeMap]);

  const beginGameDrag = (flowNode: HarnessFlowNode) => {
    if (flowNode.id.startsWith("focus:")) return;
    const originalIndex = displayItems.findIndex((item) => item.item_id === flowNode.id);
    dragRef.current = { id: flowNode.id, originalIndex, targetIndex: originalIndex };
  };

  const previewGameDrop = (flowNode: HarnessFlowNode) => {
    const drag = dragRef.current;
    if (!drag) return;
    const basePlacements = layoutHarnessItems(displayItems, {
      maxWidth: level === 3 ? 900 : 1140, startX: level === 3 ? 62 : 54,
      startY: level === 3 ? 190 : 86, rowGap: level === 3 ? 144 : 166,
      breakOnCategory: level === 3,
    });
    let targetIndex = 0;
    let distance = Number.POSITIVE_INFINITY;
    basePlacements.forEach((placement, index) => {
      const next = Math.hypot(flowNode.position.x - placement.x, flowNode.position.y - placement.y);
      if (next < distance) { distance = next; targetIndex = index; }
    });
    drag.targetIndex = targetIndex;
    const reordered = [...displayItems];
    const [moved] = reordered.splice(drag.originalIndex, 1);
    reordered.splice(targetIndex, 0, moved);
    const previewNodes = buildNodes(reordered, targetIndex);
    const ghost = previewNodes.find((value) => value.id === drag.id);
    if (!ghost) return;
    setNodes([
      ...previewNodes.filter((value) => value.id !== drag.id),
      { ...ghost, id: "__drop-preview__", data: { ...ghost.data, preview: true }, draggable: false, selectable: false },
      { ...flowNode, data: { ...flowNode.data, placement: ghost.data.placement } },
    ]);
  };

  const finishGameDrag = () => {
    const drag = dragRef.current;
    dragRef.current = null;
    if (!drag) return;
    const reordered = [...displayItems];
    const [moved] = reordered.splice(drag.originalIndex, 1);
    reordered.splice(drag.targetIndex, 0, moved);
    setOrderByParent((current) => ({ ...current, [parentKey]: reordered.map((item) => item.item_id) }));
    setNodes(buildNodes(reordered));
    if (level === 2) {
      const placements = layoutHarnessItems(reordered, { maxWidth: 1140, startX: 54, startY: 86, rowGap: 166 });
      const positions = Object.fromEntries(reordered.flatMap((item, index) => {
        const runtimeId = item.member_node_ids.length === 1 ? item.member_node_ids[0] : null;
        return runtimeId ? [[runtimeId, { x: placements[index].x, y: placements[index].y, pinned: true }]] : [];
      }));
      void edit("update_layout", { positions });
    }
  };

  const runDry = async () => {
    setBusy("dry-run");
    try {
      setDryRun(await dryRunAgentCoreHarness(harness?.current.candidate));
      setReceipts(null); setError(null);
    } catch (value) { setError(apiError(value, chinese)); }
    finally { setBusy(null); }
  };
  const openReceipts = async () => {
    setBusy("receipts");
    try { setReceipts(await listAgentCoreHarnessReceipts(60)); setDryRun(null); }
    catch (value) { setError(apiError(value, chinese)); }
    finally { setBusy(null); }
  };
  const history = async (direction: "undo" | "redo") => {
    if (!harness) return;
    setBusy(direction);
    try {
      if (direction === "undo") await undoAgentCoreHarness(harness.current.revision);
      else await redoAgentCoreHarness(harness.current.revision);
      await load();
    } catch (value) { setError(apiError(value, chinese)); }
    finally { setBusy(null); }
  };

  const activeIsCurrent = harness?.active.revision === harness?.current.revision;
  const currentState = harness?.current.state ?? "candidate";
  const breadcrumbs = path.map((id) => itemMap.get(id))
    .filter((item): item is AgentCoreHarnessCompositionItem => Boolean(item));

  return (
    <section className="harness-editor-page" onClick={() => setContextMenu(null)}>
      <header className="harness-editor-header">
        <div className="harness-editor-heading">
          <h1>{chinese ? "编排器" : "Harness Composer"}</h1>
          <nav aria-label={chinese ? "插件页面" : "Plugin pages"}>
            <NavLink to="/autonomy/plugins">{chinese ? "插件库" : "Plugin library"}</NavLink>
            <NavLink to="/autonomy/plugins/harness">{chinese ? "编排器" : "Composer"}</NavLink>
          </nav>
        </div>
        <div className="harness-editor-status">
          <span className={`is-${currentState}`}>
            {currentState === "rejected" ? (chinese ? "需要修正" : "Needs repair")
              : activeIsCurrent ? (chinese ? "已激活" : "Active")
                : (chinese ? "下一任务生效" : "Next task")}
          </span>
          {harness ? <code>R{harness.current.revision}</code> : null}
          <button type="button" onClick={() => void load()} aria-label={chinese ? "刷新" : "Refresh"}><RefreshCw /></button>
        </div>
      </header>

      <div className="harness-editor-toolbar">
        <label><span>{chinese ? "配置" : "Profile"}</span>
          <select value={harness?.current.candidate.profile_id ?? ""} disabled={!catalog || busy !== null}
            onChange={(event) => void edit("apply_profile", { profile_id: event.target.value })}>
            {(catalog?.profiles ?? []).map((profile) => <option key={profile.profile_id} value={profile.profile_id}>{catalogLabel(chinese, profile.name, profile.profile_id)}</option>)}
          </select><ChevronDown /></label>
        <label><span>{chinese ? "拓扑" : "Topology"}</span>
          <select value={harness?.current.candidate.topology_id ?? ""} disabled={!catalog || busy !== null}
            onChange={(event) => void edit("apply_template", { topology_id: event.target.value })}>
            {(catalog?.topology_templates ?? []).map((template) => <option key={template.topology_id} value={template.topology_id}>{catalogLabel(chinese, template.name, template.topology_id)}</option>)}
          </select><ChevronDown /></label>
        <span className="harness-toolbar-separator" />
        <button type="button" disabled={!harness?.can_undo || busy !== null} onClick={() => void history("undo")}><Undo2 />{chinese ? "撤销" : "Undo"}</button>
        <button type="button" disabled={!harness?.can_redo || busy !== null} onClick={() => void history("redo")}><Redo2 />{chinese ? "重做" : "Redo"}</button>
        <button type="button" disabled={busy !== null} onClick={() => void openReceipts()}><ScrollText />{chinese ? "记录" : "Receipts"}</button>
        <button type="button" className="is-primary" disabled={!harness || busy !== null} onClick={() => void runDry()}><Play />{chinese ? "试运行" : "Dry run"}</button>
      </div>

      <div className="harness-level-bar">
        <nav aria-label={chinese ? "编排层级" : "Harness levels"}>
          <button type="button" className={!path.length ? "is-current" : ""}
            onClick={() => { setPath([]); setSelectedItemId(null); }}>{chinese ? "完整流程" : "Workflow"}</button>
          {breadcrumbs.map((item, index) => <span key={item.item_id}><ChevronRight />
            <button type="button" className={index === breadcrumbs.length - 1 ? "is-current" : ""}
              onClick={() => { setPath(path.slice(0, index + 1)); setSelectedItemId(null); }}>
              {chinese ? item.title_zh : item.title}
            </button></span>)}
        </nav>
        {level < 3 ? <div className="harness-flow-legend">
          <span><i className="is-solid" />{chinese ? "确定" : "Definite"}</span>
          <span><i className="is-dashed" />{chinese ? "可能" : "Possible"}</span>
          <span><b><BrainCircuit /></b>{chinese ? "模型" : "Model"}</span>
        </div> : null}
      </div>

      {error ? <div className="harness-editor-error" role="alert"><AlertTriangle />{error}</div> : null}

      <div className={`harness-editor-workspace ${selectedItem ? "has-inspector" : ""}`}>
        <aside className="harness-palette">
          <header><h2>{level === 1 ? (chinese ? "流程" : "Workflow") : level === 2 ? (chinese ? "节点" : "Nodes") : (chinese ? "插件" : "Plugins")}</h2><span>{displayItems.length}</span></header>
          <div className="harness-category-list">
            {categorySummary.map(([categoryId, count]) => <span key={categoryId}
              style={{ "--category-color": harnessCategoryColors[categoryId] } as CSSProperties}>
              <i />{categoryLabel(categoryId, chinese)}<b>{count}</b>
            </span>)}
          </div>
          {level === 3 ? <div className="harness-plugin-pieces">
            {[...new Set(smallPlugins.map((plugin) => plugin.slot_id))].map((slotId) => <section key={slotId}>
              <h3>{slotTitle(slotId, chinese)}</h3>
              {smallPlugins.filter((plugin) => plugin.slot_id === slotId).map((plugin) => <button
                type="button" draggable disabled={busy !== null} className={plugin.enabled ? "is-enabled" : ""}
                key={plugin.plugin_id}
                onDragStart={(event) => {
                  event.dataTransfer.effectAllowed = "move";
                  event.dataTransfer.setData("application/x-dronedream-plugin", plugin.plugin_id);
                }}
                onClick={() => void activatePlugin(plugin.plugin_id, slotId)}>
                <PlugZap /><span>{catalogLabel(chinese, plugin.name, plugin.plugin_id)}</span>
              </button>)}
            </section>)}
          </div> : null}
          <NavLink className="harness-switch-link" to="/autonomy/plugins"><ArrowLeft />{chinese ? "插件开关" : "Plugin switches"}</NavLink>
        </aside>

        <main className="harness-canvas" aria-label={chinese ? "Harness 拼图画布" : "Harness puzzle canvas"}>
          {harness && catalog ? <ReactFlow
            nodes={nodes} edges={edges} nodeTypes={nodeTypes} edgeTypes={edgeTypes}
            onNodesChange={onNodesChange} onEdgesChange={onEdgesChange} onConnect={connect}
            onNodeClick={(_event, flowNode) => setSelectedItemId(flowNode.data.item.item_id)}
            onNodeDoubleClick={(_event, flowNode) => enterItem(flowNode.data.item)}
            onPaneClick={() => setSelectedItemId(null)}
            onNodeDragStart={(_event, flowNode) => beginGameDrag(flowNode)}
            onNodeDrag={(_event, flowNode) => previewGameDrop(flowNode)}
            onNodeDragStop={() => finishGameDrag()}
            onNodeContextMenu={(event, flowNode) => {
              event.preventDefault();
              const item = flowNode.data.item;
              setSelectedItemId(item.item_id);
              setContextMenu({ itemId: item.item_id, x: event.clientX, y: event.clientY });
            }}
            fitView fitViewOptions={{ padding: level === 1 ? 0.1 : 0.18 }} minZoom={typeof window !== "undefined" && window.innerWidth <= 560 ? 0.2 : 0.45} maxZoom={1.7}
            deleteKeyCode={null} proOptions={{ hideAttribution: true }}>
            <CanvasAutoFit
              signature={`${level}:${parentId ?? "root"}:${displayItems.map((item) => item.item_id).join("|")}`}
              level={level}
            />
            <Background gap={24} size={1} color="#e4dce0" /><Controls showInteractive={false} />
          </ReactFlow> : <div className="harness-canvas-loading"><RefreshCw />{chinese ? "正在读取" : "Loading"}</div>}
        </main>

        {selectedItem ? <aside className="harness-inspector">
          <header><h2>{chinese ? "详情" : "Details"}</h2><button type="button" onClick={() => setSelectedItemId(null)}><X /></button></header>
          <div className="harness-inspector-title">
            <span style={{ color: harnessCategoryColors[selectedItem.category_id] }}>{itemIcon(selectedItem, selectedNode?.node_kind)}</span>
            <div><strong>{chinese ? selectedItem.title_zh : selectedItem.title}</strong><small>{categoryLabel(selectedItem.category_id, chinese)}</small></div>
          </div>
          {selectedItem.enterable ? <button type="button" className="harness-enter-level" onClick={() => enterItem(selectedItem)}><ChevronRight />{chinese ? "进入下一级" : "Enter next level"}</button> : null}
          {selectedNode && selectedItem.kind === "policy" ? <>
            {selectedItem.item_id.endsWith(".timeout") ? <label><span>{chinese ? "超时（秒）" : "Timeout (seconds)"}</span><input type="number" min={0.1} max={600} value={selectedNode.policy.timeout_seconds}
              onChange={(event) => void edit("update_node", { node_id: selectedNode.node_id, policy: { timeout_seconds: Number(event.target.value) } })} /></label> : null}
            {selectedItem.item_id.endsWith(".retry") ? <label><span>{chinese ? "重试次数" : "Retry limit"}</span><input type="number" min={0} max={5} value={selectedNode.policy.retry_limit}
              onChange={(event) => void edit("update_node", { node_id: selectedNode.node_id, policy: { retry_limit: Number(event.target.value) } })} /></label> : null}
            {selectedItem.item_id.endsWith(".failure") ? <label><span>{chinese ? "失败处理" : "Failure mode"}</span><select value={selectedNode.policy.failure_mode} disabled={selectedItem.protected}
              onChange={(event) => void edit("update_node", { node_id: selectedNode.node_id, policy: { failure_mode: event.target.value } })}>
              <option value="fail-closed">{chinese ? "失败即关闭" : "Fail closed"}</option><option value="isolate">{chinese ? "隔离" : "Isolate"}</option><option value="fallback">{chinese ? "回退" : "Fallback"}</option>
            </select></label> : null}
            {selectedItem.item_id.endsWith(".cache") ? <label className="harness-check-label"><input type="checkbox" checked={selectedNode.policy.cacheable}
              onChange={(event) => void edit("update_node", { node_id: selectedNode.node_id, policy: { cacheable: event.target.checked } })} /><span>{chinese ? "允许节点缓存" : "Allow node cache"}</span></label> : null}
          </> : null}
          {selectedSlot ? <section className="harness-slot-options"><h3>{chinese ? "替换插件" : "Replace plugin"}</h3>
            {selectedSlotPlugins.map((plugin) => <button type="button" className={plugin.enabled ? "is-active" : ""} key={plugin.plugin_id}
              onClick={() => void activatePlugin(plugin.plugin_id, selectedSlot)} disabled={busy !== null}>
              <span /><strong>{catalogLabel(chinese, plugin.name, plugin.plugin_id)}</strong>{plugin.enabled ? <Check /> : <PlugZap />}
            </button>)}
          </section> : null}
          {selectedItem.protected ? <p className="harness-protected-note"><ShieldCheck />{chinese ? "安全边界不可绕过" : "Safety boundary cannot be bypassed"}</p> : null}
        </aside> : null}
      </div>

      {dryRun ? <section className="harness-run-drawer">
        <header><div><Play /><h2>{chinese ? "结构试运行" : "Structural dry run"}</h2></div><button type="button" onClick={() => setDryRun(null)}><X /></button></header>
        <div className="harness-run-metrics">
          <span><small>{chinese ? "状态" : "Status"}</small><strong>{dryRun.valid ? (chinese ? "通过" : "Passed") : (chinese ? "阻塞" : "Blocked")}</strong></span>
          <span><small>{chinese ? "节点" : "Nodes"}</small><strong>{dryRun.node_count}</strong></span>
          <span><small>{chinese ? "并行层" : "Layers"}</small><strong>{dryRun.layers.length}</strong></span>
          <span><small>{chinese ? "外部调用" : "External calls"}</small><strong>{dryRun.external_calls_executed}</strong></span>
        </div><ol>{dryRun.layers.map((values, index) => <li key={values.join(":")}><strong>{index + 1}</strong><span>{values.join(" · ")}</span></li>)}</ol>
      </section> : null}

      {receipts ? <section className="harness-run-drawer harness-receipts-drawer">
        <header><div><ScrollText /><h2>{chinese ? "变更记录" : "Change receipts"}</h2></div><button type="button" onClick={() => setReceipts(null)}><X /></button></header>
        <ol>{receipts.length ? receipts.map((receipt, index) => {
          const payload = receipt.payload && typeof receipt.payload === "object" ? receipt.payload as Record<string, unknown> : {};
          return <li key={String(receipt.receipt_id ?? index)}><strong>{receipts.length - index}</strong><span><b>{identifierLabel(String(receipt.event ?? "harness.event"))}</b>
            <small>{new Date(String(receipt.created_at ?? "")).toLocaleString(interfaceLocale)}{payload.revision ? ` · R${String(payload.revision)}` : ""}</small></span></li>;
        }) : <li><span>{chinese ? "暂无记录" : "No receipts yet"}</span></li>}</ol>
      </section> : null}

      {contextMenu && selectedItem ? <div className="harness-context-menu" style={{ left: contextMenu.x, top: contextMenu.y }} onClick={(event) => event.stopPropagation()}>
        {selectedItem.enterable ? <button type="button" onClick={() => enterItem(selectedItem)}>{chinese ? "进入下一级" : "Enter next level"}<ChevronRight /></button> : null}
        <button type="button" onClick={() => { setSelectedItemId(selectedItem.item_id); setContextMenu(null); }}>{chinese ? "查看详情" : "Inspect"}</button>
        {selectedItem.kind === "plugin-slot" ? <NavLink to="/autonomy/plugins">{chinese ? "插件开关" : "Plugin switches"}</NavLink> : null}
        <button type="button" onClick={() => void runDry()}>{chinese ? "试运行" : "Dry run"}</button>
        {selectedNode?.capabilities.removable ? <button type="button" className="is-danger" onClick={() => void edit("remove_node", { node_id: selectedNode.node_id })}>{chinese ? "移除节点" : "Remove node"}</button> : null}
      </div> : null}
    </section>
  );
}
