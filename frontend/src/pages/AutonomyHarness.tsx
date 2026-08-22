import {
  Background,
  Controls,
  Handle,
  MarkerType,
  MiniMap,
  Position,
  ReactFlow,
  applyEdgeChanges,
  applyNodeChanges,
  type Connection,
  type Edge,
  type EdgeChange,
  type Node,
  type NodeChange,
  type NodeProps,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import {
  AlertTriangle,
  ArrowLeft,
  BrainCircuit,
  Check,
  ChevronDown,
  CircleDot,
  GitBranch,
  LayoutDashboard,
  Play,
  Plus,
  Redo2,
  RefreshCw,
  RotateCcw,
  ScrollText,
  ShieldCheck,
  Trash2,
  Undo2,
  Waypoints,
  Wrench,
  X,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { NavLink } from "react-router-dom";

import {
  AgentCoreRequestError,
  AgentCoreUnavailableError,
  dryRunAgentCoreHarness,
  editAgentCoreHarness,
  getAgentCoreHarnessCatalog,
  getAgentCoreHarnessState,
  listAgentCoreHarnessReceipts,
  redoAgentCoreHarness,
  undoAgentCoreHarness,
  type AgentCoreHarnessCandidate,
  type AgentCoreHarnessCatalog,
  type AgentCoreHarnessDryRun,
  type AgentCoreHarnessEdge,
  type AgentCoreHarnessNode,
  type AgentCoreHarnessOperation,
  type AgentCoreHarnessState,
} from "../features/autonomy/agentCore";
import { useI18n } from "../i18n/I18nProvider";
import "./AutonomyHarness.css";

type HarnessNodeData = Record<string, unknown> & {
  node: AgentCoreHarnessNode;
  chinese: boolean;
  issueCodes: string[];
};
type HarnessFlowNode = Node<HarnessNodeData, "harness">;
type HarnessEdgeData = Record<string, unknown> & { binding: AgentCoreHarnessEdge };
type HarnessFlowEdge = Edge<HarnessEdgeData>;

function nodeIcon(kind: AgentCoreHarnessNode["node_kind"]) {
  if (kind === "model_call") return <BrainCircuit />;
  if (kind === "tool_call") return <Wrench />;
  if (kind === "safety_barrier") return <ShieldCheck />;
  if (kind === "branch" || kind === "join") return <GitBranch />;
  if (kind === "bounded_loop") return <RotateCcw />;
  if (kind === "input" || kind === "output") return <CircleDot />;
  return <Waypoints />;
}

function HarnessPuzzleNode({ data, selected }: NodeProps<HarnessFlowNode>) {
  const { node, chinese, issueCodes } = data;
  return (
    <article
      className={`harness-puzzle-node is-${node.node_kind} ${selected ? "is-selected" : ""} ${issueCodes.length ? "has-issue" : ""}`}
      aria-label={chinese ? node.title_zh : node.title}
    >
      <svg className="harness-puzzle-shape" viewBox="0 0 240 104" aria-hidden="true">
        <path d="M18 4h75c0 14 10 20 23 20s23-6 23-20h83a14 14 0 0 1 14 14v22c-13 0-20 10-20 22s7 22 20 22v2a14 14 0 0 1-14 14h-78c0-12-10-19-24-19s-24 7-24 19H18A14 14 0 0 1 4 86V66c13 0 20-10 20-22S17 22 4 22v-4A14 14 0 0 1 18 4Z" />
      </svg>
      {node.input_ports.map((port, index) => (
        <Handle
          key={port.port_id}
          id={port.port_id}
          type="target"
          position={Position.Left}
          style={{ top: `${(index + 1) * 100 / (node.input_ports.length + 1)}%` }}
          title={`${port.port_id} · ${port.schema_ref}`}
        />
      ))}
      {node.output_ports.map((port, index) => (
        <Handle
          key={port.port_id}
          id={port.port_id}
          type="source"
          position={Position.Right}
          style={{ top: `${(index + 1) * 100 / (node.output_ports.length + 1)}%` }}
          title={`${port.port_id} · ${port.schema_ref}`}
        />
      ))}
      <div className="harness-puzzle-content">
        <span>{nodeIcon(node.node_kind)}</span>
        <div>
          <strong>{chinese ? node.title_zh : node.title}</strong>
          <small>{node.handler_id}</small>
        </div>
        {node.capabilities.protected ? <ShieldCheck className="harness-node-lock" /> : null}
      </div>
      <footer>
        <span>{chinese ? `重试 ${node.policy.retry_limit}` : `${node.policy.retry_limit} retries`}</span>
        <span>{node.policy.timeout_seconds}s</span>
        {issueCodes.length ? <AlertTriangle /> : <Check />}
      </footer>
    </article>
  );
}

const nodeTypes = { harness: HarnessPuzzleNode };

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
    return chinese ? "Harness 编排器需要在 DroneDream 桌面软件中运行。" : value.message;
  }
  if (value instanceof AgentCoreRequestError) {
    if (value.message.startsWith("HARNESS_REVISION_CONFLICT")) {
      return chinese ? "Harness 已在别处更新，正在重新载入。" : "The Harness changed elsewhere. Reloading it now.";
    }
    return value.message;
  }
  return value instanceof Error
    ? value.message
    : chinese ? "Harness 操作失败。" : "The Harness operation failed.";
}

function hasCjk(value: string): boolean {
  return /[\u3400-\u9fff]/u.test(value);
}

function identifierLabel(identifier: string): string {
  return identifier
    .replace(/^dronedream\./u, "")
    .replace(/^(harness\.)?(profile-|topology\.)/u, "")
    .split(/[._-]+/u)
    .filter(Boolean)
    .map((part) => `${part.charAt(0).toUpperCase()}${part.slice(1)}`)
    .join(" ");
}

function catalogLabel(chinese: boolean, name: string, identifier: string): string {
  if (chinese || !hasCjk(name)) return name;
  return identifierLabel(identifier);
}

const contextCommandLabels: Record<string, [string, string]> = {
  inspect: ["查看详情", "Inspect"],
  dry_run: ["结构试运行", "Structural dry run"],
  remove_node: ["移除节点", "Remove node"],
};

function flowNodes(
  candidate: AgentCoreHarnessCandidate,
  chinese: boolean,
  issueMap: Map<string, string[]>,
): HarnessFlowNode[] {
  return candidate.nodes.map((node) => ({
    id: node.node_id,
    type: "harness",
    position: candidate.layout.positions[node.node_id] ?? { x: 0, y: 0 },
    data: { node, chinese, issueCodes: issueMap.get(node.node_id) ?? [] },
    draggable: true,
  }));
}

function flowEdges(candidate: AgentCoreHarnessCandidate): HarnessFlowEdge[] {
  return candidate.edges.map((binding) => ({
    id: binding.edge_id,
    source: binding.source.node_id,
    target: binding.target.node_id,
    sourceHandle: binding.source.port_id,
    targetHandle: binding.target.port_id,
    type: "smoothstep",
    markerEnd: { type: MarkerType.ArrowClosed, width: 15, height: 15 },
    data: { binding },
  }));
}

export function AutonomyHarness() {
  const { interfaceLocale } = useI18n();
  const chinese = interfaceLocale === "zh-CN";
  const [catalog, setCatalog] = useState<AgentCoreHarnessCatalog | null>(null);
  const [harness, setHarness] = useState<AgentCoreHarnessState | null>(null);
  const [nodes, setNodes] = useState<HarnessFlowNode[]>([]);
  const [edges, setEdges] = useState<HarnessFlowEdge[]>([]);
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [dryRun, setDryRun] = useState<AgentCoreHarnessDryRun | null>(null);
  const [receipts, setReceipts] = useState<Array<Record<string, unknown>> | null>(null);
  const [paletteQuery, setPaletteQuery] = useState("");
  const [contextMenu, setContextMenu] = useState<{ nodeId: string; x: number; y: number } | null>(null);

  const load = useCallback(async () => {
    try {
      const [nextCatalog, nextHarness] = await Promise.all([
        getAgentCoreHarnessCatalog(),
        getAgentCoreHarnessState(),
      ]);
      setCatalog(nextCatalog);
      setHarness(nextHarness);
      setError(null);
    } catch (value) {
      setError(apiError(value, chinese));
    }
  }, [chinese]);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    if (!harness) return;
    const issues = new Map<string, string[]>();
    for (const issue of harness.current.validation.issues) {
      if (!issue.node_id) continue;
      issues.set(issue.node_id, [...(issues.get(issue.node_id) ?? []), issue.code]);
    }
    setNodes(flowNodes(harness.current.candidate, chinese, issues));
    setEdges(flowEdges(harness.current.candidate));
  }, [chinese, harness]);

  const edit = useCallback(async (
    action: AgentCoreHarnessOperation["operation"],
    payload: Record<string, unknown>,
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
    if (!harness || !connection.source || !connection.target || !connection.sourceHandle || !connection.targetHandle) return;
    const source = harness.current.candidate.nodes.find((node) => node.node_id === connection.source);
    const sourcePort = source?.output_ports.find((port) => port.port_id === connection.sourceHandle);
    if (!sourcePort) return;
    const binding: AgentCoreHarnessEdge = {
      schema_version: "dronedream.harness-edge-binding.v1",
      edge_id: `${connection.source}:${connection.sourceHandle}->${connection.target}:${connection.targetHandle}`,
      source: { node_id: connection.source, port_id: connection.sourceHandle },
      target: { node_id: connection.target, port_id: connection.targetHandle },
      schema_ref: sourcePort.schema_ref,
      transform_plugin_id: null,
      binding_mode: sourcePort.cardinality === "event" ? "control" : "direct",
    };
    void edit("connect", { edge: binding });
  }, [edit, harness]);

  const selectedNode = useMemo(
    () => harness?.current.candidate.nodes.find((node) => node.node_id === selectedNodeId) ?? null,
    [harness, selectedNodeId],
  );

  const descriptors = useMemo(() => {
    if (!catalog || !harness) return [];
    const existing = new Set(harness.current.candidate.nodes.map((node) => node.descriptor_id));
    const query = paletteQuery.trim().toLocaleLowerCase(interfaceLocale);
    return catalog.node_descriptors.filter((descriptor) => {
      if (descriptor.capabilities.protected || existing.has(descriptor.descriptor_id)) return false;
      const text = `${descriptor.title} ${descriptor.title_zh} ${descriptor.handler_id}`.toLocaleLowerCase(interfaceLocale);
      return !query || text.includes(query);
    });
  }, [catalog, harness, interfaceLocale, paletteQuery]);

  const autoLayout = async () => {
    if (!harness) return;
    setBusy("layout");
    try {
      const { default: ELK } = await import("elkjs/lib/elk.bundled.js");
      const elk = new ELK();
      const graph = await elk.layout({
        id: "root",
        layoutOptions: {
          "elk.algorithm": "layered",
          "elk.direction": "RIGHT",
          "elk.spacing.nodeNode": "54",
          "elk.layered.spacing.nodeNodeBetweenLayers": "90",
        },
        children: harness.current.candidate.nodes.map((node) => ({
          id: node.node_id,
          width: 240,
          height: 104,
        })),
        edges: harness.current.candidate.edges.map((edge) => ({
          id: edge.edge_id,
          sources: [edge.source.node_id],
          targets: [edge.target.node_id],
        })),
      });
      const positions = Object.fromEntries((graph.children ?? []).map((node) => [
        node.id,
        { x: node.x ?? 0, y: node.y ?? 0, pinned: false },
      ]));
      await edit("update_layout", { positions });
    } catch (value) {
      setError(apiError(value, chinese));
      setBusy(null);
    }
  };

  const runDry = async () => {
    setBusy("dry-run");
    try {
      setDryRun(await dryRunAgentCoreHarness(harness?.current.candidate));
      setReceipts(null);
      setError(null);
    } catch (value) {
      setError(apiError(value, chinese));
    } finally {
      setBusy(null);
    }
  };

  const openReceipts = async () => {
    setBusy("receipts");
    try {
      setReceipts(await listAgentCoreHarnessReceipts(60));
      setDryRun(null);
      setError(null);
    } catch (value) {
      setError(apiError(value, chinese));
    } finally {
      setBusy(null);
    }
  };

  const history = async (direction: "undo" | "redo") => {
    if (!harness) return;
    setBusy(direction);
    try {
      if (direction === "undo") await undoAgentCoreHarness(harness.current.revision);
      else await redoAgentCoreHarness(harness.current.revision);
      await load();
    } catch (value) {
      setError(apiError(value, chinese));
    } finally {
      setBusy(null);
    }
  };

  const currentState = harness?.current.state ?? "candidate";
  const activeIsCurrent = harness?.active.revision === harness?.current.revision;
  const contextCommands = selectedNode
    ? catalog?.context_commands[selectedNode.capabilities.protected ? "protected_node" : "optional_node"] ?? []
    : [];

  const runContextCommand = (command: string) => {
    if (!selectedNode) return;
    if (command === "inspect") setSelectedNodeId(selectedNode.node_id);
    if (command === "dry_run") void runDry();
    if (command === "remove_node" && selectedNode.capabilities.removable) {
      void edit("remove_node", { node_id: selectedNode.node_id });
    }
    setContextMenu(null);
  };

  return (
    <section className="harness-editor-page" onClick={() => setContextMenu(null)}>
      <header className="harness-editor-header">
        <div className="harness-editor-heading">
          <h1>Harness</h1>
          <nav aria-label={chinese ? "插件页面" : "Plugin pages"}>
            <NavLink to="/autonomy/plugins">{chinese ? "插件库" : "Plugin library"}</NavLink>
            <NavLink to="/autonomy/plugins/harness">Harness</NavLink>
          </nav>
        </div>
        <div className="harness-editor-status">
          <span className={`is-${currentState}`}>
            {currentState === "rejected"
              ? chinese ? "需要修正" : "Needs repair"
              : activeIsCurrent
                ? chinese ? "已激活" : "Active"
                : chinese ? "下一任务生效" : "Next task"}
          </span>
          {harness ? <code>R{harness.current.revision}</code> : null}
          <button type="button" onClick={() => void load()} aria-label={chinese ? "刷新" : "Refresh"}><RefreshCw /></button>
        </div>
      </header>

      <div className="harness-editor-toolbar">
        <label>
          <span>{chinese ? "配置" : "Profile"}</span>
          <select
            value={harness?.current.candidate.profile_id ?? ""}
            disabled={!catalog || busy !== null}
            onChange={(event) => void edit("apply_profile", { profile_id: event.target.value })}
          >
            {(catalog?.profiles ?? []).map((profile) => <option key={profile.profile_id} value={profile.profile_id}>{catalogLabel(chinese, profile.name, profile.profile_id)}</option>)}
          </select>
          <ChevronDown />
        </label>
        <label>
          <span>{chinese ? "拓扑" : "Topology"}</span>
          <select
            value={harness?.current.candidate.topology_id ?? ""}
            disabled={!catalog || busy !== null}
            onChange={(event) => void edit("apply_template", { topology_id: event.target.value })}
          >
            {(catalog?.topology_templates ?? []).map((template) => <option key={template.topology_id} value={template.topology_id}>{catalogLabel(chinese, template.name, template.topology_id)}</option>)}
          </select>
          <ChevronDown />
        </label>
        <span className="harness-toolbar-separator" />
        <button type="button" disabled={!harness?.can_undo || busy !== null} onClick={() => void history("undo")}><Undo2 />{chinese ? "撤销" : "Undo"}</button>
        <button type="button" disabled={!harness?.can_redo || busy !== null} onClick={() => void history("redo")}><Redo2 />{chinese ? "重做" : "Redo"}</button>
        <button type="button" disabled={!harness || busy !== null} onClick={() => void autoLayout()}><LayoutDashboard />{chinese ? "整理" : "Layout"}</button>
        <button type="button" disabled={busy !== null} onClick={() => void openReceipts()}><ScrollText />{chinese ? "记录" : "Receipts"}</button>
        <button type="button" className="is-primary" disabled={!harness || busy !== null} onClick={() => void runDry()}><Play />{chinese ? "试运行" : "Dry run"}</button>
      </div>

      {error ? <div className="harness-editor-error" role="alert"><AlertTriangle />{error}</div> : null}

      <div className="harness-editor-workspace">
        <aside className="harness-palette">
          <header><h2>{chinese ? "节点" : "Nodes"}</h2><span>{descriptors.length}</span></header>
          <input
            type="search"
            value={paletteQuery}
            onChange={(event) => setPaletteQuery(event.target.value)}
            placeholder={chinese ? "搜索节点" : "Search nodes"}
          />
          <div className="harness-palette-list">
            {descriptors.map((descriptor) => (
              <button
                type="button"
                key={descriptor.descriptor_id}
                disabled={busy !== null}
                onClick={() => void edit("add_node", {
                  descriptor_id: descriptor.descriptor_id,
                  x: 80,
                  y: 80,
                })}
              >
                <span>{nodeIcon(descriptor.node_kind)}</span>
                <strong>{chinese ? descriptor.title_zh : descriptor.title}</strong>
                <Plus />
              </button>
            ))}
            {!descriptors.length ? <p>{chinese ? "当前拓扑已包含所有可选节点。" : "All optional nodes are already in this topology."}</p> : null}
          </div>
          <section className="harness-palette-plugins">
            <h3>{chinese ? "运行策略" : "Runtime policies"}</h3>
            {(catalog?.plugins ?? []).filter((plugin) => plugin.enabled && !["harness.profile", "harness.workflow-topology"].includes(plugin.slot_id)).map((plugin) => (
              <div key={plugin.plugin_id}><span className={`is-${plugin.health}`} /><strong>{catalogLabel(chinese, plugin.name, plugin.plugin_id)}</strong></div>
            ))}
            <NavLink to="/autonomy/plugins"><ArrowLeft />{chinese ? "管理开关" : "Manage switches"}</NavLink>
          </section>
        </aside>

        <main className="harness-canvas" aria-label={chinese ? "Harness 画布" : "Harness canvas"}>
          {harness ? (
            <ReactFlow
              nodes={nodes}
              edges={edges}
              nodeTypes={nodeTypes}
              onNodesChange={onNodesChange}
              onEdgesChange={onEdgesChange}
              onConnect={connect}
              onNodeClick={(_event, node) => setSelectedNodeId(node.id)}
              onPaneClick={() => setSelectedNodeId(null)}
              onNodeDragStop={(_event, node) => void edit("move_node", {
                node_id: node.id,
                x: node.position.x,
                y: node.position.y,
              })}
              onNodeContextMenu={(event, node) => {
                event.preventDefault();
                setSelectedNodeId(node.id);
                setContextMenu({ nodeId: node.id, x: event.clientX, y: event.clientY });
              }}
              fitView
              fitViewOptions={{ padding: 0.18 }}
              minZoom={0.25}
              maxZoom={1.8}
              deleteKeyCode={null}
              proOptions={{ hideAttribution: true }}
            >
              <Background gap={24} size={1} color="#ddcfd5" />
              <Controls showInteractive={false} />
              <MiniMap pannable zoomable nodeStrokeWidth={3} />
            </ReactFlow>
          ) : <div className="harness-canvas-loading"><RefreshCw />{chinese ? "正在读取 Harness" : "Loading Harness"}</div>}
        </main>

        <aside className="harness-inspector">
          <header><h2>{chinese ? "检查器" : "Inspector"}</h2>{selectedNode ? <button type="button" onClick={() => setSelectedNodeId(null)}><X /></button> : null}</header>
          {selectedNode ? <>
            <div className="harness-inspector-title"><span>{nodeIcon(selectedNode.node_kind)}</span><div><strong>{chinese ? selectedNode.title_zh : selectedNode.title}</strong><small>{selectedNode.node_id}</small></div></div>
            <dl>
              <div><dt>{chinese ? "处理器" : "Handler"}</dt><dd>{selectedNode.handler_id}</dd></div>
              <div><dt>{chinese ? "权限" : "Authority"}</dt><dd>{selectedNode.policy.authority}</dd></div>
              <div><dt>{chinese ? "输入" : "Inputs"}</dt><dd>{selectedNode.input_ports.length}</dd></div>
              <div><dt>{chinese ? "输出" : "Outputs"}</dt><dd>{selectedNode.output_ports.length}</dd></div>
            </dl>
            <label><span>{chinese ? "超时（秒）" : "Timeout (seconds)"}</span><input type="number" min={0.1} max={600} step={1} defaultValue={selectedNode.policy.timeout_seconds} onBlur={(event) => void edit("update_node", { node_id: selectedNode.node_id, policy: { timeout_seconds: Number(event.target.value) } })} /></label>
            <label><span>{chinese ? "重试次数" : "Retry limit"}</span><input type="number" min={0} max={5} defaultValue={selectedNode.policy.retry_limit} onBlur={(event) => void edit("update_node", { node_id: selectedNode.node_id, policy: { retry_limit: Number(event.target.value) } })} /></label>
            <label><span>{chinese ? "失败处理" : "Failure mode"}</span><select value={selectedNode.policy.failure_mode} disabled={selectedNode.capabilities.protected} onChange={(event) => void edit("update_node", { node_id: selectedNode.node_id, policy: { failure_mode: event.target.value } })}><option value="fail-closed">Fail closed</option><option value="isolate">Isolate</option><option value="fallback">Fallback</option></select></label>
            <p className="harness-auto-save"><Check />{chinese ? "修改自动验证并应用" : "Changes validate and apply automatically"}</p>
            {selectedNode.capabilities.removable ? <button type="button" className="harness-remove-node" onClick={() => void edit("remove_node", { node_id: selectedNode.node_id })}><Trash2 />{chinese ? "移除节点" : "Remove node"}</button> : <p className="harness-protected-note"><ShieldCheck />{chinese ? "核心节点受安全边界保护" : "Core node protected by the safety boundary"}</p>}
          </> : <div className="harness-inspector-empty"><Waypoints /><p>{chinese ? "选择节点查看端口、策略与安全边界。" : "Select a node to inspect its ports, policy, and safety boundary."}</p></div>}
        </aside>
      </div>

      {harness?.current.validation.issues.length ? <section className="harness-validation-strip"><AlertTriangle /><div><strong>{chinese ? "当前候选拓扑未激活" : "Current candidate is not active"}</strong>{harness.current.validation.issues.map((issue) => <span key={`${issue.code}:${issue.node_id}:${issue.edge_id}`}>{issue.code}{issue.node_id ? ` · ${issue.node_id}` : ""}</span>)}</div></section> : null}

      {dryRun ? <section className="harness-run-drawer">
        <header><div><Play /><h2>{chinese ? "结构试运行" : "Structural dry run"}</h2></div><button type="button" onClick={() => setDryRun(null)}><X /></button></header>
        <div className="harness-run-metrics"><span><small>{chinese ? "状态" : "Status"}</small><strong>{dryRun.valid ? chinese ? "通过" : "Passed" : chinese ? "阻塞" : "Blocked"}</strong></span><span><small>{chinese ? "节点" : "Nodes"}</small><strong>{dryRun.node_count}</strong></span><span><small>{chinese ? "并行层" : "Layers"}</small><strong>{dryRun.layers.length}</strong></span><span><small>{chinese ? "外部调用" : "External calls"}</small><strong>{dryRun.external_calls_executed}</strong></span></div>
        <ol>{dryRun.layers.map((layer, index) => <li key={layer.join(":")}><strong>{index + 1}</strong><span>{layer.join(" · ")}</span></li>)}</ol>
      </section> : null}

      {receipts ? <section className="harness-run-drawer harness-receipts-drawer">
        <header><div><ScrollText /><h2>{chinese ? "变更记录" : "Change receipts"}</h2></div><button type="button" onClick={() => setReceipts(null)}><X /></button></header>
        <ol>{receipts.length ? receipts.map((receipt, index) => {
          const payload = receipt.payload && typeof receipt.payload === "object" ? receipt.payload as Record<string, unknown> : {};
          return <li key={String(receipt.receipt_id ?? index)}><strong>{receipts.length - index}</strong><span><b>{identifierLabel(String(receipt.event ?? "harness.event"))}</b><small>{new Date(String(receipt.created_at ?? "")).toLocaleString(interfaceLocale)}{payload.revision ? ` · R${String(payload.revision)}` : ""}</small></span></li>;
        }) : <li><span>{chinese ? "还没有 Harness 变更记录。" : "There are no Harness change receipts yet."}</span></li>}</ol>
      </section> : null}

      {contextMenu && selectedNode ? <div className="harness-context-menu" style={{ left: contextMenu.x, top: contextMenu.y }} onClick={(event) => event.stopPropagation()}>
        {contextCommands.filter((command) => contextCommandLabels[command]).map((command) => (
          <button type="button" key={command} className={command === "remove_node" ? "is-danger" : ""} onClick={() => runContextCommand(command)}>{contextCommandLabels[command][chinese ? 0 : 1]}</button>
        ))}
      </div> : null}
    </section>
  );
}
