import {
  Background, Controls, Handle, MarkerType, MiniMap, Position, ReactFlow,
  applyEdgeChanges, applyNodeChanges, type Connection, type Edge, type EdgeChange,
  type Node, type NodeChange, type NodeProps,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import {
  AlertTriangle, ArrowLeft, BadgeCheck, BrainCircuit, Check, ChevronDown,
  ChevronRight, CircleDot, Database, GitBranch, Inbox, MousePointer2, Play,
  PlugZap, Redo2, RefreshCw, RotateCcw, ScrollText, ShieldCheck, Undo2,
  Waypoints, Wrench, X,
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
  shapeIndex: number;
  shapeCount: number;
  runtimeNodeCount: number;
  onPluginDrop?: (pluginId: string, slotId: string) => void;
};
type HarnessFlowNode = Node<HarnessNodeData, "harness">;
type HarnessEdgeData = Record<string, unknown> & { binding?: AgentCoreHarnessEdge };
type HarnessFlowEdge = Edge<HarnessEdgeData>;

const colorByToken: Record<string, string> = {
  amber: "#f2a900", green: "#78a800", blue: "#3784e8", red: "#e33f49",
  violet: "#7537e5", cyan: "#1598b7",
};

function itemIcon(item: AgentCoreHarnessCompositionItem, kind?: AgentCoreHarnessNode["node_kind"]) {
  if (item.icon === "inbox") return <Inbox />;
  if (item.icon === "brain") return <BrainCircuit />;
  if (item.icon === "shield") return <ShieldCheck />;
  if (item.icon === "badge-check") return <BadgeCheck />;
  if (item.icon === "database") return <Database />;
  if (item.icon === "plug") return <PlugZap />;
  if (kind === "model_call") return <BrainCircuit />;
  if (kind === "tool_call") return <Wrench />;
  if (kind === "safety_barrier") return <ShieldCheck />;
  if (kind === "branch" || kind === "join") return <GitBranch />;
  if (kind === "bounded_loop") return <RotateCcw />;
  if (kind === "input" || kind === "output") return <CircleDot />;
  return <Waypoints />;
}

function PuzzleShape({ level, index, count }: { level: 1 | 2 | 3; index: number; count: number }) {
  const metrics = level === 1
    ? { width: 280, height: 140, insetX: 18, insetY: 12, radius: 11, half: 22 }
    : level === 2
      ? { width: 250, height: 114, insetX: 16, insetY: 10, radius: 10, half: 18 }
      : { width: 198, height: 92, insetX: 14, insetY: 10, radius: 8, half: 15 };
  const columns = level === 3 ? 4 : 3;
  const row = Math.floor(index / columns);
  const column = index % columns;
  const parity = (row + column) % 2 === 0;
  const top = row === 0 ? 0 : ((row - 1 + column) % 2 === 0 ? -1 : 1);
  const right = column === columns - 1 || index + 1 >= count ? 0 : (parity ? 1 : -1);
  const bottom = index + columns >= count ? 0 : (parity ? 1 : -1);
  const left = column === 0 ? 0 : ((row + column - 1) % 2 === 0 ? -1 : 1);
  const { width, height, insetX, insetY, radius, half } = metrics;
  const x0 = insetX; const x1 = width - insetX; const y0 = insetY; const y1 = height - insetY;
  const cx = width / 2; const cy = height / 2;
  const path = [
    `M ${x0 + radius} ${y0}`,
    `L ${cx - half} ${y0}`,
    top ? `C ${cx - half} ${y0 - top * insetY} ${cx + half} ${y0 - top * insetY} ${cx + half} ${y0}` : `L ${cx + half} ${y0}`,
    `L ${x1 - radius} ${y0} Q ${x1} ${y0} ${x1} ${y0 + radius}`,
    `L ${x1} ${cy - half}`,
    right ? `C ${x1 + right * insetX} ${cy - half} ${x1 + right * insetX} ${cy + half} ${x1} ${cy + half}` : `L ${x1} ${cy + half}`,
    `L ${x1} ${y1 - radius} Q ${x1} ${y1} ${x1 - radius} ${y1}`,
    `L ${cx + half} ${y1}`,
    bottom ? `C ${cx + half} ${y1 + bottom * insetY} ${cx - half} ${y1 + bottom * insetY} ${cx - half} ${y1}` : `L ${cx - half} ${y1}`,
    `L ${x0 + radius} ${y1} Q ${x0} ${y1} ${x0} ${y1 - radius}`,
    `L ${x0} ${cy + half}`,
    left ? `C ${x0 - left * insetX} ${cy + half} ${x0 - left * insetX} ${cy - half} ${x0} ${cy - half}` : `L ${x0} ${cy - half}`,
    `L ${x0} ${y0 + radius} Q ${x0} ${y0} ${x0 + radius} ${y0} Z`,
  ].join(" ");
  return <svg className="harness-puzzle-shape" viewBox={`0 0 ${width} ${height}`} aria-hidden="true"><path d={path} /></svg>;
}

function HarnessPuzzleNode({ data, selected }: NodeProps<HarnessFlowNode>) {
  const { item, node, chinese, issueCodes, plugin, policyValue, preview, focus, shapeIndex, shapeCount, runtimeNodeCount, onPluginDrop } = data;
  const title = chinese ? item.title_zh : item.title;
  const subtitle = item.kind === "phase"
    ? chinese ? `${runtimeNodeCount} 个阶段 · ${item.plugin_slot_ids.length} 类插件` : `${runtimeNodeCount} stages · ${item.plugin_slot_ids.length} plugin slots`
    : item.kind === "stage" ? node?.handler_id ?? ""
      : plugin ? catalogLabel(chinese, plugin.name, plugin.plugin_id)
        : policyValue ?? (chinese ? "拖入插件进行替换" : "Drop a plugin to replace");
  return (
    <article
      className={`harness-puzzle-node level-${item.level} is-${item.kind} is-${item.color_token} ${selected ? "is-selected" : ""} ${issueCodes.length ? "has-issue" : ""} ${preview ? "is-drop-preview" : ""} ${focus ? "is-focus" : ""}`}
      style={{ "--piece-color": colorByToken[item.color_token] ?? colorByToken.red } as CSSProperties}
      aria-label={title}
      onDragOver={item.kind === "plugin-slot" ? (event) => event.preventDefault() : undefined}
      onDrop={item.kind === "plugin-slot" ? (event) => {
        event.preventDefault();
        const pluginId = event.dataTransfer.getData("application/x-dronedream-plugin");
        const slotId = item.plugin_slot_ids[0];
        if (pluginId && slotId) onPluginDrop?.(pluginId, slotId);
      } : undefined}
    >
      <PuzzleShape level={item.level} index={shapeIndex} count={shapeCount} />
      {!preview && item.level === 2 ? <><Handle type="target" position={Position.Left} id={node?.input_ports[0]?.port_id ?? "control.in"} /><Handle type="source" position={Position.Right} id={node?.output_ports[0]?.port_id ?? "control.out"} /></> : null}
      <div className="harness-puzzle-content">
        <span>{itemIcon(item, node?.node_kind)}</span>
        <div><strong>{title}</strong><small>{subtitle}</small></div>
        {item.enterable && !preview ? <ChevronRight className="harness-node-enter" /> : null}
        {item.protected && !item.enterable && !preview ? <ShieldCheck className="harness-node-lock" /> : null}
      </div>
      {!preview ? <footer><span>{item.granularity === "large" ? (chinese ? "大插件" : "Large") : item.granularity === "medium" ? (chinese ? "阶段" : "Stage") : (chinese ? "小插件" : "Small")}</span><span>{item.scope === "workflow" ? (chinese ? "全流程" : "Workflow") : item.scope === "phase" ? (chinese ? "阶段组" : "Phase") : (chinese ? "单节点" : "Node")}</span>{issueCodes.length ? <AlertTriangle /> : <Check />}</footer> : null}
    </article>
  );
}

const nodeTypes = { harness: HarnessPuzzleNode };

function operation(baseRevision: number, action: AgentCoreHarnessOperation["operation"], payload: Record<string, unknown>): AgentCoreHarnessOperation {
  return { schema_version: "dronedream.harness-edit-operation.v1", client_operation_id: `desktop-${crypto.randomUUID()}`, base_revision: baseRevision, operation: action, payload };
}
function apiError(value: unknown, chinese: boolean): string {
  if (value instanceof AgentCoreUnavailableError) return chinese ? "Harness 编排器需要在 DroneDream 桌面软件中运行。" : value.message;
  if (value instanceof AgentCoreRequestError && value.message.startsWith("HARNESS_REVISION_CONFLICT")) return chinese ? "Harness 已在别处更新，正在重新载入。" : "The Harness changed elsewhere. Reloading it now.";
  if (value instanceof Error) return value.message;
  return chinese ? "Harness 操作失败。" : "The Harness operation failed.";
}
function hasCjk(value: string): boolean { return /[\u3400-\u9fff]/u.test(value); }
function identifierLabel(identifier: string): string { return identifier.replace(/^dronedream\./u, "").replace(/^(harness\.)?(profile-|topology\.)/u, "").split(/[._-]+/u).filter(Boolean).map((part) => `${part.charAt(0).toUpperCase()}${part.slice(1)}`).join(" "); }
function catalogLabel(chinese: boolean, name: string, identifier: string): string { return chinese || !hasCjk(name) ? name : identifierLabel(identifier); }
function slotTitle(slotId: string, chinese: boolean): string {
  const values: Record<string, [string, string]> = {
    "harness.scheduler": ["调度器", "Scheduler"], "harness.retry-policy": ["重试策略", "Retry policy"],
    "harness.timeout-policy": ["超时策略", "Timeout policy"], "harness.budget-policy": ["调用预算", "Call budget"],
    "harness.fallback-policy": ["回退策略", "Fallback policy"], "harness.cache-policy": ["缓存策略", "Cache policy"],
    "harness.event-bus": ["事件总线", "Event bus"], "harness.observers": ["观测器", "Observers"],
  };
  return values[slotId]?.[chinese ? 0 : 1] ?? identifierLabel(slotId);
}
function itemPosition(level: 1 | 2 | 3, index: number) {
  if (level === 1) return { x: 90 + (index % 3) * 244, y: 74 + Math.floor(index / 3) * 116 };
  if (level === 2) return { x: 90 + (index % 3) * 218, y: 104 + Math.floor(index / 3) * 94 };
  return { x: 58 + (index % 4) * 170, y: 260 + Math.floor(index / 4) * 72 };
}
function policyValue(item: AgentCoreHarnessCompositionItem, node: AgentCoreHarnessNode | null, chinese: boolean): string | null {
  if (!node || item.kind !== "policy") return null;
  if (item.item_id.endsWith(".timeout")) return `${node.policy.timeout_seconds} ${chinese ? "秒" : "sec"}`;
  if (item.item_id.endsWith(".retry")) return chinese ? `${node.policy.retry_limit} 次` : `${node.policy.retry_limit} attempts`;
  if (item.item_id.endsWith(".failure")) return chinese && node.policy.failure_mode === "fail-closed" ? "失败即关闭" : node.policy.failure_mode;
  if (item.item_id.endsWith(".cache")) return node.policy.cacheable ? (chinese ? "已启用" : "Enabled") : (chinese ? "未启用" : "Disabled");
  return null;
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
  const dragRef = useRef<{ id: string; originalIndex: number; targetIndex: number; base: Record<string, { x: number; y: number }> } | null>(null);

  const load = useCallback(async () => {
    try { const [nextCatalog, nextHarness] = await Promise.all([getAgentCoreHarnessCatalog(), getAgentCoreHarnessState()]); setCatalog(nextCatalog); setHarness(nextHarness); setError(null); }
    catch (value) { setError(apiError(value, chinese)); }
  }, [chinese]);
  useEffect(() => { void load(); }, [load]);

  const edit = useCallback(async (action: AgentCoreHarnessOperation["operation"], payload: Record<string, unknown>) => {
    if (!harness) return;
    setBusy(action); setError(null);
    try { await editAgentCoreHarness(operation(harness.current.revision, action, payload)); await load(); }
    catch (value) { setError(apiError(value, chinese)); if (value instanceof AgentCoreRequestError && value.status === 409) await load(); }
    finally { setBusy(null); }
  }, [chinese, harness, load]);

  const activatePlugin = useCallback(async (pluginId: string, slotId: string) => {
    const plugin = catalog?.plugins.find((value) => value.plugin_id === pluginId && value.slot_id === slotId);
    if (!plugin) return;
    setBusy(`plugin:${pluginId}`); setError(null);
    try { await setAgentCorePlugin(pluginId, plugin.activation_mode === "multiple" ? !plugin.enabled : true); await load(); }
    catch (value) { setError(apiError(value, chinese)); }
    finally { setBusy(null); }
  }, [catalog, chinese, load]);

  const itemMap = useMemo(() => new Map((catalog?.composition_items ?? []).map((item) => [item.item_id, item])), [catalog]);
  const nodeMap = useMemo(() => new Map((harness?.current.candidate.nodes ?? []).map((node) => [node.node_id, node])), [harness]);
  const level = Math.min(3, path.length + 1) as 1 | 2 | 3;
  const parentId = path.at(-1) ?? null;
  const parentKey = parentId ?? "root";
  const visibleItems = useMemo(() => {
    if (!catalog || !harness) return [];
    const values = catalog.composition_items.filter((item) => item.level === level && item.parent_item_id === parentId && item.member_node_ids.some((id) => nodeMap.has(id)));
    const defaults = values.sort((a, b) => a.order - b.order).map((item) => item.item_id);
    const preferred = orderByParent[parentKey] ?? [];
    const ids = [...preferred.filter((id) => defaults.includes(id)), ...defaults.filter((id) => !preferred.includes(id))];
    return ids.map((id) => itemMap.get(id)).filter((item): item is AgentCoreHarnessCompositionItem => Boolean(item));
  }, [catalog, harness, itemMap, level, nodeMap, orderByParent, parentId, parentKey]);

  useEffect(() => {
    if (!catalog || !harness) return;
    const issues = new Map<string, string[]>();
    for (const issue of harness.current.validation.issues) if (issue.node_id) issues.set(issue.node_id, [...(issues.get(issue.node_id) ?? []), issue.code]);
    const nextNodes: HarnessFlowNode[] = visibleItems.map((item, index) => {
      const node = item.member_node_ids.length === 1 ? nodeMap.get(item.member_node_ids[0]) ?? null : null;
      const slotId = item.plugin_slot_ids[0];
      const plugin = slotId ? catalog.plugins.find((value) => value.slot_id === slotId && value.enabled) ?? null : null;
      return { id: item.item_id, type: "harness", position: itemPosition(level, index), data: { item, node, chinese, issueCodes: item.member_node_ids.flatMap((id) => issues.get(id) ?? []), plugin, policyValue: policyValue(item, node, chinese), preview: false, focus: false, shapeIndex: index, shapeCount: visibleItems.length, runtimeNodeCount: item.member_node_ids.filter((id) => nodeMap.has(id)).length, onPluginDrop: activatePlugin }, draggable: true };
    });
    if (level === 3 && parentId) {
      const focusItem = itemMap.get(parentId); const focusNode = focusItem?.member_node_ids.length === 1 ? nodeMap.get(focusItem.member_node_ids[0]) ?? null : null;
      if (focusItem) nextNodes.unshift({ id: `focus:${focusItem.item_id}`, type: "harness", position: { x: 390, y: 70 }, data: { item: focusItem, node: focusNode, chinese, issueCodes: [], plugin: null, policyValue: null, preview: false, focus: true, shapeIndex: 0, shapeCount: 1, runtimeNodeCount: focusItem.member_node_ids.filter((id) => nodeMap.has(id)).length }, draggable: false });
    }
    setNodes(nextNodes);
    const nextEdges: HarnessFlowEdge[] = [];
    if (level === 1) {
      const owner = new Map<string, string>(); for (const item of visibleItems) for (const nodeId of item.member_node_ids) owner.set(nodeId, item.item_id);
      const seen = new Set<string>();
      for (const binding of harness.current.candidate.edges) { const source = owner.get(binding.source.node_id); const target = owner.get(binding.target.node_id); if (!source || !target || source === target) continue; const id = `${source}->${target}`; if (seen.has(id)) continue; seen.add(id); nextEdges.push({ id, source, target, type: "smoothstep", markerEnd: { type: MarkerType.ArrowClosed, width: 15, height: 15 }, data: {} }); }
    } else if (level === 2) {
      const owner = new Map(visibleItems.flatMap((item) => item.member_node_ids.map((id) => [id, item.item_id] as const)));
      for (const binding of harness.current.candidate.edges) { const source = owner.get(binding.source.node_id); const target = owner.get(binding.target.node_id); if (source && target) nextEdges.push({ id: binding.edge_id, source, target, sourceHandle: binding.source.port_id, targetHandle: binding.target.port_id, type: "smoothstep", markerEnd: { type: MarkerType.ArrowClosed, width: 15, height: 15 }, data: { binding } }); }
    } else if (parentId) for (const item of visibleItems) nextEdges.push({ id: `${parentId}->${item.item_id}`, source: `focus:${parentId}`, target: item.item_id, type: "smoothstep", data: {} });
    setEdges(nextEdges);
  }, [activatePlugin, catalog, chinese, harness, itemMap, level, nodeMap, parentId, visibleItems]);

  const selectedItem = selectedItemId ? itemMap.get(selectedItemId) ?? null : null;
  const selectedNode = selectedItem?.member_node_ids.length === 1 ? nodeMap.get(selectedItem.member_node_ids[0]) ?? null : null;
  const selectedSlot = selectedItem?.kind === "plugin-slot" ? selectedItem.plugin_slot_ids[0] : null;
  const selectedSlotPlugins = selectedSlot ? (catalog?.plugins ?? []).filter((plugin) => plugin.slot_id === selectedSlot) : [];
  const stageForLevel = level === 3 && parentId ? itemMap.get(parentId) ?? null : null;
  const smallPlugins = (catalog?.plugins ?? []).filter((plugin) => (stageForLevel?.plugin_slot_ids ?? []).includes(plugin.slot_id));
  const enterItem = (item: AgentCoreHarnessCompositionItem) => { if (!item.enterable || item.level >= 3) return; setPath((current) => item.level === 1 ? [item.item_id] : [current[0], item.item_id]); setSelectedItemId(null); setContextMenu(null); };

  const onNodesChange = useCallback((changes: NodeChange<HarnessFlowNode>[]) => setNodes((values) => applyNodeChanges(changes, values)), []);
  const onEdgesChange = useCallback((changes: EdgeChange<HarnessFlowEdge>[]) => { setEdges((values) => applyEdgeChanges(changes, values)); for (const change of changes) if (change.type === "remove") { const edge = edges.find((value) => value.id === change.id); if (edge?.data?.binding) void edit("disconnect", { edge: edge.data.binding }); } }, [edges, edit]);
  const connect = useCallback((connection: Connection) => {
    if (level !== 2 || !connection.source || !connection.target) return;
    const sourceItem = itemMap.get(connection.source); const targetItem = itemMap.get(connection.target);
    const source = sourceItem ? nodeMap.get(sourceItem.member_node_ids[0]) : null; const target = targetItem ? nodeMap.get(targetItem.member_node_ids[0]) : null;
    const sourcePort = source?.output_ports[0]; const targetPort = target?.input_ports[0]; if (!source || !target || !sourcePort || !targetPort) return;
    const binding: AgentCoreHarnessEdge = { schema_version: "dronedream.harness-edge-binding.v1", edge_id: `${source.node_id}:${sourcePort.port_id}->${target.node_id}:${targetPort.port_id}`, source: { node_id: source.node_id, port_id: sourcePort.port_id }, target: { node_id: target.node_id, port_id: targetPort.port_id }, schema_ref: sourcePort.schema_ref, transform_plugin_id: null, binding_mode: sourcePort.cardinality === "event" ? "control" : "direct" };
    void edit("connect", { edge: binding });
  }, [edit, itemMap, level, nodeMap]);

  const beginGameDrag = (node: HarnessFlowNode) => {
    if (node.id.startsWith("focus:")) return;
    const ids = visibleItems.map((item) => item.item_id); const originalIndex = ids.indexOf(node.id);
    dragRef.current = { id: node.id, originalIndex, targetIndex: originalIndex, base: Object.fromEntries(nodes.filter((value) => !value.id.startsWith("focus:")).map((value) => [value.id, { ...value.position }])) };
  };
  const previewGameDrop = (node: HarnessFlowNode) => {
    const drag = dragRef.current; if (!drag) return;
    const slots = visibleItems.map((_item, index) => itemPosition(level, index)); let targetIndex = 0; let distance = Number.POSITIVE_INFINITY;
    slots.forEach((slot, index) => { const next = Math.hypot(node.position.x - slot.x, node.position.y - slot.y); if (next < distance) { distance = next; targetIndex = index; } }); drag.targetIndex = targetIndex;
    const target = slots[targetIndex]; const draggedItem = itemMap.get(drag.id); if (!target || !draggedItem) return;
    setNodes((values) => {
      const shifted = values.filter((value) => value.id !== "__drop-preview__").map((value) => {
        if (value.id === drag.id || value.id.startsWith("focus:")) return value; const base = drag.base[value.id]; if (!base) return value;
        const index = visibleItems.findIndex((item) => item.item_id === value.id); const columns = level === 3 ? 4 : 3;
        if (Math.floor(index / columns) !== Math.floor(targetIndex / columns)) return { ...value, position: base };
        return { ...value, position: { x: base.x + (index < targetIndex ? -34 : 34), y: base.y } };
      });
      shifted.push({ id: "__drop-preview__", type: "harness", position: target, data: { item: draggedItem, node: null, chinese, issueCodes: [], plugin: null, policyValue: null, preview: true, focus: false, shapeIndex: targetIndex, shapeCount: visibleItems.length, runtimeNodeCount: draggedItem.member_node_ids.filter((id) => nodeMap.has(id)).length }, draggable: false, selectable: false }); return shifted;
    });
  };
  const finishGameDrag = (node: HarnessFlowNode) => {
    const drag = dragRef.current; dragRef.current = null; if (!drag) return;
    const ids = visibleItems.map((item) => item.item_id); const moved = ids.splice(drag.originalIndex, 1)[0]; ids.splice(drag.targetIndex, 0, moved); setOrderByParent((current) => ({ ...current, [parentKey]: ids })); setNodes((values) => values.filter((value) => value.id !== "__drop-preview__"));
    const item = itemMap.get(node.id); const runtimeNode = item?.member_node_ids.length === 1 ? nodeMap.get(item.member_node_ids[0]) : null; if (level === 2 && runtimeNode) void edit("move_node", { node_id: runtimeNode.node_id, x: node.position.x, y: node.position.y });
  };

  const runDry = async () => { setBusy("dry-run"); try { setDryRun(await dryRunAgentCoreHarness(harness?.current.candidate)); setReceipts(null); setError(null); } catch (value) { setError(apiError(value, chinese)); } finally { setBusy(null); } };
  const openReceipts = async () => { setBusy("receipts"); try { setReceipts(await listAgentCoreHarnessReceipts(60)); setDryRun(null); } catch (value) { setError(apiError(value, chinese)); } finally { setBusy(null); } };
  const history = async (direction: "undo" | "redo") => { if (!harness) return; setBusy(direction); try { if (direction === "undo") await undoAgentCoreHarness(harness.current.revision); else await redoAgentCoreHarness(harness.current.revision); await load(); } catch (value) { setError(apiError(value, chinese)); } finally { setBusy(null); } };
  const activeIsCurrent = harness?.active.revision === harness?.current.revision; const currentState = harness?.current.state ?? "candidate";
  const breadcrumbs = path.map((id) => itemMap.get(id)).filter((item): item is AgentCoreHarnessCompositionItem => Boolean(item));

  return (
    <section className="harness-editor-page" onClick={() => setContextMenu(null)}>
      <header className="harness-editor-header"><div className="harness-editor-heading"><h1>Harness</h1><nav aria-label={chinese ? "插件页面" : "Plugin pages"}><NavLink to="/autonomy/plugins">{chinese ? "插件库" : "Plugin library"}</NavLink><NavLink to="/autonomy/plugins/harness">Harness</NavLink></nav></div><div className="harness-editor-status"><span className={`is-${currentState}`}>{currentState === "rejected" ? (chinese ? "需要修正" : "Needs repair") : activeIsCurrent ? (chinese ? "已激活" : "Active") : (chinese ? "下一任务生效" : "Next task")}</span>{harness ? <code>R{harness.current.revision}</code> : null}<button type="button" onClick={() => void load()} aria-label={chinese ? "刷新" : "Refresh"}><RefreshCw /></button></div></header>
      <div className="harness-editor-toolbar"><label><span>{chinese ? "大插件配置" : "Large profile plugin"}</span><select value={harness?.current.candidate.profile_id ?? ""} disabled={!catalog || busy !== null} onChange={(event) => void edit("apply_profile", { profile_id: event.target.value })}>{(catalog?.profiles ?? []).map((profile) => <option key={profile.profile_id} value={profile.profile_id}>{catalogLabel(chinese, profile.name, profile.profile_id)}</option>)}</select><ChevronDown /></label><label><span>{chinese ? "大插件拓扑" : "Large topology plugin"}</span><select value={harness?.current.candidate.topology_id ?? ""} disabled={!catalog || busy !== null} onChange={(event) => void edit("apply_template", { topology_id: event.target.value })}>{(catalog?.topology_templates ?? []).map((template) => <option key={template.topology_id} value={template.topology_id}>{catalogLabel(chinese, template.name, template.topology_id)}</option>)}</select><ChevronDown /></label><span className="harness-toolbar-separator" /><button type="button" disabled={!harness?.can_undo || busy !== null} onClick={() => void history("undo")}><Undo2 />{chinese ? "撤销" : "Undo"}</button><button type="button" disabled={!harness?.can_redo || busy !== null} onClick={() => void history("redo")}><Redo2 />{chinese ? "重做" : "Redo"}</button><button type="button" disabled={busy !== null} onClick={() => void openReceipts()}><ScrollText />{chinese ? "记录" : "Receipts"}</button><button type="button" className="is-primary" disabled={!harness || busy !== null} onClick={() => void runDry()}><Play />{chinese ? "试运行" : "Dry run"}</button></div>
      <div className="harness-level-bar"><nav aria-label={chinese ? "Harness 层级" : "Harness levels"}><button type="button" className={!path.length ? "is-current" : ""} onClick={() => { setPath([]); setSelectedItemId(null); }}>{chinese ? "第一级 · 完整流程" : "Level 1 · Workflow"}</button>{breadcrumbs.map((item, index) => <span key={item.item_id}><ChevronRight /><button type="button" className={index === breadcrumbs.length - 1 ? "is-current" : ""} onClick={() => { setPath(path.slice(0, index + 1)); setSelectedItemId(null); }}>{chinese ? item.title_zh : item.title}</button></span>)}</nav><p><MousePointer2 />{chinese ? "右击拼图进入下一级；拖动时会显示游戏式落位预览" : "Right-click to drill down; drag for a game-like placement preview"}</p></div>
      {error ? <div className="harness-editor-error" role="alert"><AlertTriangle />{error}</div> : null}
      <div className="harness-editor-workspace">
        <aside className="harness-palette"><header><h2>{level === 1 ? (chinese ? "大插件" : "Large plugins") : level === 2 ? (chinese ? "阶段" : "Stages") : (chinese ? "小插件" : "Small plugins")}</h2><span>{level}</span></header>{level < 3 ? <div className="harness-level-guide"><strong>{chinese ? `第 ${level} 级` : `Level ${level}`}</strong><p>{level === 1 ? (chinese ? "先看完整任务的六个大环节。" : "Start with six major workflow phases.") : (chinese ? "查看该环节中的真实执行阶段。" : "Inspect executable stages in this phase.")}</p></div> : null}{level === 3 ? <div className="harness-plugin-pieces">{[...new Set(smallPlugins.map((plugin) => plugin.slot_id))].map((slotId) => <section key={slotId}><h3>{slotTitle(slotId, chinese)}</h3>{smallPlugins.filter((plugin) => plugin.slot_id === slotId).map((plugin) => <button type="button" draggable disabled={busy !== null} className={plugin.enabled ? "is-enabled" : ""} key={plugin.plugin_id} onDragStart={(event) => { event.dataTransfer.effectAllowed = "move"; event.dataTransfer.setData("application/x-dronedream-plugin", plugin.plugin_id); }} onClick={() => void activatePlugin(plugin.plugin_id, slotId)}><PlugZap /><span><strong>{catalogLabel(chinese, plugin.name, plugin.plugin_id)}</strong><small>{plugin.enabled ? (chinese ? "正在使用" : "In use") : (chinese ? "拖到右侧槽位" : "Drag to a slot")}</small></span></button>)}</section>)}</div> : null}<section className="harness-palette-plugins"><h3>{chinese ? "原开关页面" : "Switch view"}</h3><NavLink to="/autonomy/plugins"><ArrowLeft />{chinese ? "管理全部插件开关" : "Manage every plugin switch"}</NavLink></section></aside>
        <main className="harness-canvas" aria-label={chinese ? "Harness 拼图画布" : "Harness puzzle canvas"}>{harness && catalog ? <ReactFlow nodes={nodes} edges={edges} nodeTypes={nodeTypes} onNodesChange={onNodesChange} onEdgesChange={onEdgesChange} onConnect={connect} onNodeClick={(_event, flowNode) => setSelectedItemId(flowNode.data.item.item_id)} onNodeDoubleClick={(_event, flowNode) => enterItem(flowNode.data.item)} onPaneClick={() => setSelectedItemId(null)} onNodeDragStart={(_event, flowNode) => beginGameDrag(flowNode)} onNodeDrag={(_event, flowNode) => previewGameDrop(flowNode)} onNodeDragStop={(_event, flowNode) => finishGameDrag(flowNode)} onNodeContextMenu={(event, flowNode) => { event.preventDefault(); const item = flowNode.data.item; setSelectedItemId(item.item_id); setContextMenu({ itemId: item.item_id, x: event.clientX, y: event.clientY }); }} fitView fitViewOptions={{ padding: level === 1 ? 0.12 : 0.2 }} minZoom={0.45} maxZoom={1.8} deleteKeyCode={null} proOptions={{ hideAttribution: true }}><Background gap={24} size={1} color="#ddcfd5" /><Controls showInteractive={false} /><MiniMap pannable zoomable nodeStrokeWidth={3} /></ReactFlow> : <div className="harness-canvas-loading"><RefreshCw />{chinese ? "正在读取 Harness" : "Loading Harness"}</div>}</main>
        <aside className="harness-inspector"><header><h2>{chinese ? "拼图详情" : "Puzzle details"}</h2>{selectedItem ? <button type="button" onClick={() => setSelectedItemId(null)}><X /></button> : null}</header>{selectedItem ? <><div className="harness-inspector-title"><span style={{ color: colorByToken[selectedItem.color_token] }}>{itemIcon(selectedItem, selectedNode?.node_kind)}</span><div><strong>{chinese ? selectedItem.title_zh : selectedItem.title}</strong><small>{selectedItem.item_id}</small></div></div><dl><div><dt>{chinese ? "级别" : "Level"}</dt><dd>{selectedItem.level}</dd></div><div><dt>{chinese ? "粒度" : "Granularity"}</dt><dd>{selectedItem.granularity === "large" ? (chinese ? "大插件" : "Large") : selectedItem.granularity === "medium" ? (chinese ? "阶段" : "Stage") : (chinese ? "小插件" : "Small")}</dd></div><div><dt>{chinese ? "执行节点" : "Runtime nodes"}</dt><dd>{selectedItem.member_node_ids.length}</dd></div></dl>{selectedItem.enterable ? <button type="button" className="harness-enter-level" onClick={() => enterItem(selectedItem)}><ChevronRight />{chinese ? "进入下一级" : "Enter next level"}</button> : null}{selectedNode && selectedItem.kind === "policy" ? <>{selectedItem.item_id.endsWith(".timeout") ? <label><span>{chinese ? "超时（秒）" : "Timeout (seconds)"}</span><input type="number" min={0.1} max={600} value={selectedNode.policy.timeout_seconds} onChange={(event) => void edit("update_node", { node_id: selectedNode.node_id, policy: { timeout_seconds: Number(event.target.value) } })} /></label> : null}{selectedItem.item_id.endsWith(".retry") ? <label><span>{chinese ? "重试次数" : "Retry limit"}</span><input type="number" min={0} max={5} value={selectedNode.policy.retry_limit} onChange={(event) => void edit("update_node", { node_id: selectedNode.node_id, policy: { retry_limit: Number(event.target.value) } })} /></label> : null}{selectedItem.item_id.endsWith(".failure") ? <label><span>{chinese ? "失败处理" : "Failure mode"}</span><select value={selectedNode.policy.failure_mode} disabled={selectedItem.protected} onChange={(event) => void edit("update_node", { node_id: selectedNode.node_id, policy: { failure_mode: event.target.value } })}><option value="fail-closed">{chinese ? "失败即关闭" : "Fail closed"}</option><option value="isolate">{chinese ? "隔离" : "Isolate"}</option><option value="fallback">{chinese ? "回退" : "Fallback"}</option></select></label> : null}{selectedItem.item_id.endsWith(".cache") ? <label className="harness-check-label"><input type="checkbox" checked={selectedNode.policy.cacheable} onChange={(event) => void edit("update_node", { node_id: selectedNode.node_id, policy: { cacheable: event.target.checked } })} /><span>{chinese ? "允许节点缓存" : "Allow node cache"}</span></label> : null}</> : null}{selectedSlot ? <section className="harness-slot-options"><h3>{chinese ? "替换小插件" : "Replace small plugin"}</h3>{selectedSlotPlugins.map((plugin) => <button type="button" className={plugin.enabled ? "is-active" : ""} key={plugin.plugin_id} onClick={() => void activatePlugin(plugin.plugin_id, selectedSlot)} disabled={busy !== null}><span /><strong>{catalogLabel(chinese, plugin.name, plugin.plugin_id)}</strong>{plugin.enabled ? <Check /> : <PlugZap />}</button>)}<p>{chinese ? "单选槽位会自动停用同槽位的旧插件；多选槽位可同时启用。" : "Single slots replace the previous plugin; multi slots may stay enabled together."}</p></section> : null}{selectedItem.protected ? <p className="harness-protected-note"><ShieldCheck />{chinese ? "该安全边界不可被插件绕过" : "Plugins cannot bypass this safety boundary"}</p> : null}</> : <div className="harness-inspector-empty"><Waypoints /><p>{chinese ? "选择拼图查看详情，或右击进入下一层。" : "Select a puzzle for details, or right-click to drill down."}</p></div>}</aside>
      </div>
      {dryRun ? <section className="harness-run-drawer"><header><div><Play /><h2>{chinese ? "结构试运行" : "Structural dry run"}</h2></div><button type="button" onClick={() => setDryRun(null)}><X /></button></header><div className="harness-run-metrics"><span><small>{chinese ? "状态" : "Status"}</small><strong>{dryRun.valid ? (chinese ? "通过" : "Passed") : (chinese ? "阻塞" : "Blocked")}</strong></span><span><small>{chinese ? "节点" : "Nodes"}</small><strong>{dryRun.node_count}</strong></span><span><small>{chinese ? "并行层" : "Layers"}</small><strong>{dryRun.layers.length}</strong></span><span><small>{chinese ? "外部调用" : "External calls"}</small><strong>{dryRun.external_calls_executed}</strong></span></div><ol>{dryRun.layers.map((values, index) => <li key={values.join(":")}><strong>{index + 1}</strong><span>{values.join(" · ")}</span></li>)}</ol></section> : null}
      {receipts ? <section className="harness-run-drawer harness-receipts-drawer"><header><div><ScrollText /><h2>{chinese ? "变更记录" : "Change receipts"}</h2></div><button type="button" onClick={() => setReceipts(null)}><X /></button></header><ol>{receipts.length ? receipts.map((receipt, index) => { const payload = receipt.payload && typeof receipt.payload === "object" ? receipt.payload as Record<string, unknown> : {}; return <li key={String(receipt.receipt_id ?? index)}><strong>{receipts.length - index}</strong><span><b>{identifierLabel(String(receipt.event ?? "harness.event"))}</b><small>{new Date(String(receipt.created_at ?? "")).toLocaleString(interfaceLocale)}{payload.revision ? ` · R${String(payload.revision)}` : ""}</small></span></li>; }) : <li><span>{chinese ? "还没有 Harness 变更记录。" : "There are no Harness change receipts yet."}</span></li>}</ol></section> : null}
      {contextMenu && selectedItem ? <div className="harness-context-menu" style={{ left: contextMenu.x, top: contextMenu.y }} onClick={(event) => event.stopPropagation()}>{selectedItem.enterable ? <button type="button" onClick={() => enterItem(selectedItem)}>{chinese ? "进入下一级" : "Enter next level"}<ChevronRight /></button> : null}<button type="button" onClick={() => { setSelectedItemId(selectedItem.item_id); setContextMenu(null); }}>{chinese ? "查看详情" : "Inspect"}</button>{selectedItem.kind === "plugin-slot" ? <NavLink to="/autonomy/plugins">{chinese ? "打开插件开关" : "Open plugin switches"}</NavLink> : null}<button type="button" onClick={() => void runDry()}>{chinese ? "结构试运行" : "Structural dry run"}</button>{selectedNode?.capabilities.removable ? <button type="button" className="is-danger" onClick={() => void edit("remove_node", { node_id: selectedNode.node_id })}>{chinese ? "移除节点" : "Remove node"}</button> : null}</div> : null}
    </section>
  );
}
