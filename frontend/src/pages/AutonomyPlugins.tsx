import {
  ArrowRight, Blocks, CheckCircle2, ChevronDown, ChevronRight, CircleAlert, Eye,
  GitBranch, Layers3, Library, Search, ShieldCheck, Sparkles, Trash2, Upload,
  Waypoints, X,
} from "lucide-react";
import {
  useCallback, useEffect, useMemo, useRef, useState, type CSSProperties,
  type KeyboardEvent as ReactKeyboardEvent, type MouseEvent as ReactMouseEvent,
} from "react";
import { NavLink } from "react-router-dom";

import {
  AgentCoreRequestError, AgentCoreUnavailableError, editAgentCoreHarness,
  applyAgentCoreHarnessProfile, getAgentCoreHarnessCatalog, getAgentCoreHarnessState,
  importAgentCorePlugin, listAgentCorePlugins, setAgentCorePlugin,
  uninstallAgentCorePlugin, type AgentCoreHarnessCatalog,
  type AgentCoreHarnessOperation, type AgentCoreHarnessState, type AgentCorePluginEntry,
} from "../features/autonomy/agentCore";
import {
  categoryLabel, harnessCategoryColors, puzzlePath, type PuzzleConnector,
} from "../features/autonomy/harnessVisualLayout";
import { useI18n } from "../i18n/I18nProvider";
import "./AutonomyPlugins.css";

type StudioView = "harness" | "library";
type PieceLevel = 1 | 2;

type HarnessAtom = {
  id: string; title: string; description: string; category: string; color: string;
  protected: boolean; replaceable: boolean; enabled: boolean; settingCount: number;
  nodeIds: string[];
};
type HarnessGroup = {
  id: string; title: string; description: string; category: string; color: string;
  protected: boolean; replaceable: boolean; nodeIds: string[]; atoms: HarnessAtom[];
};
type PieceSelection = { level: PieceLevel; groupId: string; atomId?: string };
type PieceDetails = {
  key: string; level: PieceLevel; title: string; description: string; category: string;
  color: string; protected: boolean; replaceable: boolean; nodeIds: string[];
  atomCount: number; selection: PieceSelection;
};
type ContextMenuState = { piece: PieceSelection; x: number; y: number; submenu: boolean; submenuLeft: boolean };
type PieceOverride = Pick<PieceDetails, "title" | "description" | "category" | "color">;
type ReplacementCandidate = {
  key: string; title: string; description: string; category: string; color: string;
  groupKey: string; groupLabel: string; pluginId?: string;
  action?: "enable" | "apply-profile"; previewPiece?: PieceDetails;
};

const GROUP_COLORS = ["#ee466d", "#765ee8", "#18a6cf", "#26b985", "#f19a38"];
const CONNECTOR_NONE: PuzzleConnector = { profile: "round", sign: 0 };
const CONNECTOR_TAB: PuzzleConnector = { profile: "round", sign: 1 };
const CONNECTOR_SLOT: PuzzleConnector = { profile: "round", sign: -1 };

const PREVIEW_GROUPS = [
  {
    id: "intake", category: "input", color: GROUP_COLORS[0],
    title: ["任务接入", "Task intake"], description: ["理解目标并建立可靠的任务上下文", "Understand the goal and establish trusted task context"],
    atoms: [
      { id: "intent", title: ["意图解析", "Intent parser"], description: ["提取目标、约束和中断指令", "Extract goals, constraints, and interrupts"], category: "input", protected: false, settingCount: 2 },
      { id: "context", title: ["上下文装载", "Context loader"], description: ["绑定地图、飞行器与实时状态", "Bind map, aircraft, and live state"], category: "memory", protected: false, settingCount: 1 },
      { id: "guard", title: ["输入安全门", "Input safety gate"], description: ["阻止越权或不完整的任务进入执行", "Block unsafe or incomplete tasks"], category: "safety", protected: true, settingCount: 2 },
    ],
  },
  {
    id: "planning", category: "planning", color: GROUP_COLORS[1],
    title: ["规划决策", "Plan and decide"], description: ["生成路线，并在约束内作出决策", "Build routes and make decisions within constraints"],
    atoms: [
      { id: "planner", title: ["任务规划", "Mission planner"], description: ["把自然语言转成可执行任务图", "Turn natural language into an executable graph"], category: "orchestration", protected: false, settingCount: 3 },
      { id: "route", title: ["路径规划", "Route planner"], description: ["依据障碍物和实时位置生成航路", "Route around obstacles from the live position"], category: "control", protected: false, settingCount: 2 },
      { id: "approval", title: ["决策审批", "Decision approval"], description: ["在高风险动作前请求必要确认", "Request confirmation before high-risk actions"], category: "assurance", protected: true, settingCount: 1 },
    ],
  },
  {
    id: "execution", category: "control", color: GROUP_COLORS[2],
    title: ["飞行执行", "Flight control"], description: ["持续下发控制，并保持高频闭环", "Dispatch control through a high-frequency closed loop"],
    atoms: [
      { id: "dispatch", title: ["指令调度", "Command dispatch"], description: ["将计划转成 PX4 或真机命令", "Translate plans into PX4 or device commands"], category: "integration", protected: false, settingCount: 2 },
      { id: "telemetry", title: ["遥测同步", "Telemetry sync"], description: ["高频读取姿态、位置与健康状态", "Read pose, position, and health at high frequency"], category: "control", protected: true, settingCount: 2 },
      { id: "reroute", title: ["动态重规划", "Live replanning"], description: ["被打断时先悬停，再从当前位置重规划", "Hover on interrupt, then replan from the live position"], category: "orchestration", protected: false, settingCount: 3 },
    ],
  },
  {
    id: "verification", category: "assurance", color: GROUP_COLORS[3],
    title: ["验证交付", "Verify results"], description: ["监测风险，确认结果并生成证据", "Monitor risk, confirm results, and produce evidence"],
    atoms: [
      { id: "monitor", title: ["安全监测", "Safety monitor"], description: ["识别碰撞、失联和任务偏差", "Detect collision, disconnect, and mission drift"], category: "safety", protected: true, settingCount: 2 },
      { id: "validator", title: ["结果验证", "Result validator"], description: ["用真实状态而不是路径穿越判断成功", "Judge success from real state, never path crossing"], category: "assurance", protected: true, settingCount: 2 },
      { id: "report", title: ["证据交付", "Evidence delivery"], description: ["保存轨迹、录像和任务回执", "Save trajectory, recording, and mission receipt"], category: "integration", protected: false, settingCount: 1 },
    ],
  },
] as const;

function hasCjk(value: string): boolean { return /[\u3400-\u9fff]/u.test(value); }
function englishIdentifier(value: string): string {
  return value.split(/[._-]+/u).filter(Boolean)
    .map((part) => `${part.charAt(0).toUpperCase()}${part.slice(1)}`).join(" ");
}
function pluginName(chinese: boolean, plugin: AgentCorePluginEntry): string {
  if (chinese || !hasCjk(plugin.name)) return plugin.name;
  return englishIdentifier(plugin.plugin_id.replace(/^dronedream\./u, ""));
}
function harnessPluginName(
  chinese: boolean,
  plugin: AgentCoreHarnessCatalog["plugins"][number],
): string {
  if (chinese || !hasCjk(plugin.name)) return plugin.name;
  return englishIdentifier(plugin.plugin_id.replace(/^harness\./u, ""));
}
function errorText(error: unknown, chinese: boolean): string {
  if (error instanceof AgentCoreUnavailableError) return chinese
    ? "当前显示 Harness 结构预览；桌面版登录后会载入实时插件。"
    : "Showing the Harness structure preview. The desktop app loads live plugins after sign-in.";
  if (error instanceof AgentCoreRequestError) return error.message;
  return error instanceof Error ? error.message : chinese ? "插件操作失败。" : "The plug-in operation failed.";
}
function itemLabel(chinese: boolean, item: { title: string; title_zh: string }): string {
  return chinese ? item.title_zh : hasCjk(item.title) ? englishIdentifier(item.title) : item.title;
}
function itemDescription(chinese: boolean, item: { description: string; description_zh: string }): string {
  const value = chinese ? item.description_zh : item.description;
  return value || (chinese ? "可替换、可配置的 Harness 能力" : "A replaceable, configurable Harness capability");
}
function previewGroups(chinese: boolean): HarnessGroup[] {
  const languageIndex = chinese ? 0 : 1;
  return PREVIEW_GROUPS.map((group) => ({
    id: group.id, category: group.category, color: group.color,
    title: group.title[languageIndex], description: group.description[languageIndex],
    protected: false, replaceable: true, nodeIds: [],
    atoms: group.atoms.map((atom) => ({
      id: atom.id, title: atom.title[languageIndex], description: atom.description[languageIndex],
      category: atom.category, color: harnessCategoryColors[atom.category] ?? group.color,
      protected: atom.protected, replaceable: !atom.protected, enabled: true,
      settingCount: atom.settingCount, nodeIds: [],
    })),
  }));
}
function catalogGroups(chinese: boolean, catalog: AgentCoreHarnessCatalog | null, harness: AgentCoreHarnessState | null): HarnessGroup[] {
  if (!catalog) return previewGroups(chinese);
  const nodes = harness?.current.candidate.nodes ?? [];
  const activeIds = new Set(nodes.map((node) => node.node_id));
  const levelOne = catalog.composition_items
    .filter((item) => item.level === 1 && item.parent_item_id === null)
    .filter((item) => !activeIds.size || item.member_node_ids.some((id) => activeIds.has(id)))
    .sort((left, right) => left.order - right.order).slice(0, 5);
  const groups = levelOne.map((group, groupIndex): HarnessGroup => {
    const memberNodes = nodes.filter((node) => group.member_node_ids.includes(node.node_id));
    const atoms = catalog.composition_items
      .filter((item) => item.level === 2 && item.parent_item_id === group.item_id)
      .filter((item) => !activeIds.size || item.member_node_ids.some((id) => activeIds.has(id)))
      .sort((left, right) => left.order - right.order).map((item): HarnessAtom => {
        const atomNodes = nodes.filter((node) => item.member_node_ids.includes(node.node_id));
        return {
          id: item.item_id, title: itemLabel(chinese, item), description: itemDescription(chinese, item),
          category: item.category_id, color: harnessCategoryColors[item.category_id] ?? GROUP_COLORS[groupIndex % GROUP_COLORS.length],
          protected: item.protected || atomNodes.some((node) => node.capabilities.protected),
          replaceable: item.replaceable && atomNodes.every((node) => node.capabilities.replaceable),
          enabled: !activeIds.size || item.member_node_ids.some((id) => activeIds.has(id)),
          settingCount: catalog.composition_items.filter((detail) => detail.level === 3 && detail.parent_item_id === item.item_id).length,
          nodeIds: item.member_node_ids.filter((id) => activeIds.has(id)),
        };
      });
    return {
      id: group.item_id, title: itemLabel(chinese, group), description: itemDescription(chinese, group),
      category: group.category_id, color: GROUP_COLORS[groupIndex % GROUP_COLORS.length],
      protected: group.protected || memberNodes.some((node) => node.capabilities.protected),
      replaceable: memberNodes.length > 0 && memberNodes.every((node) => node.capabilities.replaceable),
      nodeIds: group.member_node_ids.filter((id) => activeIds.has(id)), atoms,
    };
  });
  return groups.length >= 3 ? groups : previewGroups(chinese);
}
function operation(baseRevision: number, action: AgentCoreHarnessOperation["operation"], payload: Record<string, unknown>): AgentCoreHarnessOperation {
  const id = globalThis.crypto?.randomUUID?.() ?? `${Date.now()}-${Math.random().toString(16).slice(2)}`;
  return { schema_version: "dronedream.harness-edit-operation.v1", client_operation_id: `plugin-studio-${id}`, base_revision: baseRevision, operation: action, payload };
}
function pieceKey(selection: PieceSelection): string {
  return selection.level === 1 ? selection.groupId : `${selection.groupId}:${selection.atomId ?? ""}`;
}
function findPiece(groups: HarnessGroup[], selection: PieceSelection): PieceDetails | null {
  const group = groups.find((value) => value.id === selection.groupId);
  if (!group) return null;
  if (selection.level === 1) return {
    key: pieceKey(selection), level: 1, title: group.title, description: group.description,
    category: group.category, color: group.color, protected: group.protected,
    replaceable: group.replaceable, nodeIds: group.nodeIds, atomCount: group.atoms.length, selection,
  };
  const atom = group.atoms.find((value) => value.id === selection.atomId);
  return atom ? {
    key: pieceKey(selection), level: 2, title: atom.title, description: atom.description,
    category: atom.category, color: atom.color, protected: atom.protected,
    replaceable: atom.replaceable, nodeIds: atom.nodeIds, atomCount: atom.settingCount, selection,
  } : null;
}
function GroupIcon({ index }: { index: number }) {
  const Icon = [Waypoints, GitBranch, Layers3, ShieldCheck, Sparkles][index] ?? Blocks;
  return <Icon aria-hidden="true" />;
}
function PuzzleShape({ first, last }: { first: boolean; last: boolean }) {
  return <svg className="agent-puzzle-shape" viewBox="0 0 306 132" preserveAspectRatio="none" aria-hidden="true">
    <path d={puzzlePath(270, first ? CONNECTOR_NONE : CONNECTOR_SLOT, last ? CONNECTOR_NONE : CONNECTOR_TAB)} />
  </svg>;
}

export function AutonomyPlugins() {
  const { interfaceLocale } = useI18n();
  const chinese = interfaceLocale === "zh-CN";
  const uploadInput = useRef<HTMLInputElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);
  const [view, setView] = useState<StudioView>("harness");
  const [plugins, setPlugins] = useState<AgentCorePluginEntry[]>([]);
  const [catalog, setCatalog] = useState<AgentCoreHarnessCatalog | null>(null);
  const [harness, setHarness] = useState<AgentCoreHarnessState | null>(null);
  const [expandedGroupId, setExpandedGroupId] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [contextMenu, setContextMenu] = useState<ContextMenuState | null>(null);
  const [detailsSelection, setDetailsSelection] = useState<PieceSelection | null>(null);
  const [hiddenPieceKeys, setHiddenPieceKeys] = useState<Set<string>>(() => new Set());
  const [pieceOverrides, setPieceOverrides] = useState<Record<string, PieceOverride>>({});

  const refresh = useCallback(async () => {
    setLoading(true);
    const [pluginResult, catalogResult, harnessResult] = await Promise.allSettled([
      listAgentCorePlugins(), getAgentCoreHarnessCatalog(), getAgentCoreHarnessState(),
    ]);
    if (pluginResult.status === "fulfilled") setPlugins(pluginResult.value);
    if (catalogResult.status === "fulfilled") setCatalog(catalogResult.value);
    if (harnessResult.status === "fulfilled") setHarness(harnessResult.value);
    const firstFailure = [pluginResult, catalogResult, harnessResult]
      .find((result) => result.status === "rejected" && !(result.reason instanceof AgentCoreUnavailableError));
    setError(firstFailure?.status === "rejected" ? errorText(firstFailure.reason, chinese) : null);
    setLoading(false);
  }, [chinese]);
  useEffect(() => { void refresh(); }, [refresh]);

  const baseGroups = useMemo(() => catalogGroups(chinese, catalog, harness), [catalog, chinese, harness]);
  const groups = useMemo(() => baseGroups.filter((group) => !hiddenPieceKeys.has(group.id)).map((group) => ({
    ...group, ...(pieceOverrides[group.id] ?? {}),
    atoms: group.atoms.filter((atom) => !hiddenPieceKeys.has(`${group.id}:${atom.id}`))
      .map((atom) => ({ ...atom, ...(pieceOverrides[`${group.id}:${atom.id}`] ?? {}) })),
  })), [baseGroups, hiddenPieceKeys, pieceOverrides]);
  const activeGroupId = expandedGroupId && groups.some((group) => group.id === expandedGroupId) ? expandedGroupId : groups[0]?.id ?? null;
  const activeGroup = groups.find((group) => group.id === activeGroupId) ?? null;
  const activeProfile = catalog?.profiles.find((profile) => profile.profile_id === harness?.current.candidate.profile_id);
  const selectedPiece = contextMenu ? findPiece(groups, contextMenu.piece) : null;
  const detailsPiece = detailsSelection ? findPiece(groups, detailsSelection) : null;

  const visiblePlugins = useMemo(() => {
    const needle = query.trim().toLocaleLowerCase(interfaceLocale);
    if (!needle) return plugins;
    return plugins.filter((plugin) => [plugin.name, plugin.plugin_id, plugin.publisher]
      .some((value) => value.toLocaleLowerCase(interfaceLocale).includes(needle)));
  }, [interfaceLocale, plugins, query]);
  const replacementCandidates = useMemo(() => {
    if (!selectedPiece) return [];
    if (!catalog) {
      const candidates = selectedPiece.level === 1
        ? groups.map((group) => findPiece(groups, { level: 1, groupId: group.id }))
        : groups.flatMap((group) => group.atoms.map((atom) => findPiece(groups, { level: 2, groupId: group.id, atomId: atom.id })));
      return candidates.filter((candidate): candidate is PieceDetails => Boolean(candidate && candidate.key !== selectedPiece.key))
        .map((candidate): ReplacementCandidate => ({
          key: candidate.key, title: candidate.title, description: candidate.description,
          category: candidate.category, color: candidate.color,
          groupKey: candidate.category, groupLabel: categoryLabel(candidate.category, chinese),
          previewPiece: candidate,
        }))
        .sort((left, right) => Number(right.category === selectedPiece.category) - Number(left.category === selectedPiece.category)
          || left.title.localeCompare(right.title, interfaceLocale));
    }

    const ownerItemId = selectedPiece.level === 2 ? selectedPiece.selection.atomId : undefined;
    return catalog.plugins
      .filter((plugin) => !plugin.enabled && plugin.activation_mode === "single")
      .filter((plugin) => selectedPiece.level === 1
        ? plugin.granularity === "large"
        : plugin.granularity === "small" && Boolean(ownerItemId && plugin.owner_item_ids.includes(ownerItemId)))
      .map((plugin): ReplacementCandidate => {
        const slotItem = catalog.composition_items.find((item) => item.level === 3
          && item.parent_item_id === ownerItemId && item.plugin_slot_ids.includes(plugin.slot_id));
        const category = slotItem?.category_id ?? selectedPiece.category;
        return {
          key: `plugin:${plugin.plugin_id}`, pluginId: plugin.plugin_id,
          action: plugin.slot_id === "harness.profile" ? "apply-profile" : "enable",
          title: harnessPluginName(chinese, plugin), description: plugin.description,
          category, color: harnessCategoryColors[category] ?? selectedPiece.color,
          groupKey: plugin.slot_id, groupLabel: plugin.slot_label,
        };
      })
      .sort((left, right) => left.groupLabel.localeCompare(right.groupLabel, interfaceLocale)
        || left.title.localeCompare(right.title, interfaceLocale));
  }, [catalog, chinese, groups, interfaceLocale, selectedPiece]);

  useEffect(() => {
    if (!contextMenu) return undefined;
    const close = () => setContextMenu(null);
    const closeOnEscape = (event: KeyboardEvent) => { if (event.key === "Escape") close(); };
    window.addEventListener("click", close); window.addEventListener("blur", close);
    window.addEventListener("resize", close); window.addEventListener("scroll", close, true);
    window.addEventListener("keydown", closeOnEscape);
    window.requestAnimationFrame(() => menuRef.current?.querySelector<HTMLElement>(":scope > [role='menuitem']")?.focus());
    return () => {
      window.removeEventListener("click", close); window.removeEventListener("blur", close);
      window.removeEventListener("resize", close); window.removeEventListener("scroll", close, true);
      window.removeEventListener("keydown", closeOnEscape);
    };
  }, [contextMenu]);
  useEffect(() => {
    if (!detailsPiece) return undefined;
    const closeOnEscape = (event: KeyboardEvent) => { if (event.key === "Escape") setDetailsSelection(null); };
    window.addEventListener("keydown", closeOnEscape);
    return () => window.removeEventListener("keydown", closeOnEscape);
  }, [detailsPiece]);

  const openContextMenu = (event: ReactMouseEvent, piece: PieceSelection) => {
    event.preventDefault();
    setContextMenu({
      piece,
      x: Math.max(10, Math.min(event.clientX, window.innerWidth - 250)),
      y: Math.max(10, Math.min(event.clientY, window.innerHeight - 200)),
      submenu: false,
      submenuLeft: event.clientX + 500 > window.innerWidth,
    });
  };
  const openContextMenuFromKeyboard = (event: ReactKeyboardEvent, piece: PieceSelection) => {
    if (!((event.shiftKey && event.key === "F10") || event.key === "ContextMenu")) return;
    event.preventDefault();
    const rect = event.currentTarget.getBoundingClientRect();
    setContextMenu({
      piece, x: rect.left + 24, y: rect.top + 24, submenu: false,
      submenuLeft: rect.left + 500 > window.innerWidth,
    });
  };
  const menuKeyDown = (event: ReactKeyboardEvent<HTMLDivElement>) => {
    const items = Array.from(event.currentTarget.querySelectorAll<HTMLElement>(":scope > [role='menuitem']:not([disabled])"));
    const currentIndex = items.indexOf(document.activeElement as HTMLElement);
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault(); const delta = event.key === "ArrowDown" ? 1 : -1;
      items[(currentIndex + delta + items.length) % items.length]?.focus();
    } else if (event.key === "Home" || event.key === "End") {
      event.preventDefault(); items[event.key === "Home" ? 0 : items.length - 1]?.focus();
    } else if (event.key === "ArrowRight" && (document.activeElement as HTMLElement)?.dataset.submenu === "replace") {
      event.preventDefault(); setContextMenu((value) => value ? { ...value, submenu: true } : null);
      window.requestAnimationFrame(() => menuRef.current?.querySelector<HTMLElement>(".agent-piece-submenu [role='menuitem']:not([disabled])")?.focus());
    }
  };

  const importPlugin = async (file: File | undefined) => {
    if (!file) return;
    setBusy("import"); setError(null);
    try { await importAgentCorePlugin(file); await refresh(); }
    catch (reason) { setError(errorText(reason, chinese)); }
    finally { setBusy(null); if (uploadInput.current) uploadInput.current.value = ""; }
  };
  const removePlugin = async (plugin: AgentCorePluginEntry) => {
    setBusy(plugin.plugin_id); setError(null);
    try { await uninstallAgentCorePlugin(plugin.plugin_id); await refresh(); }
    catch (reason) { setError(errorText(reason, chinese)); }
    finally { setBusy(null); }
  };
  const removePiece = async (piece: PieceDetails) => {
    setContextMenu(null);
    if (piece.protected) { setError(chinese ? "安全锁定模块不能从 Harness 中删除。" : "Safety-locked modules cannot be removed from the Harness."); return; }
    if (!harness || !piece.nodeIds.length) { setHiddenPieceKeys((values) => new Set(values).add(piece.key)); return; }
    const nodes = harness.current.candidate.nodes.filter((node) => piece.nodeIds.includes(node.node_id));
    if (!nodes.length || nodes.some((node) => !node.capabilities.removable)) {
      setError(chinese ? "该模块包含 Harness 必需能力，不能删除。" : "This piece contains required Harness capability and cannot be removed."); return;
    }
    setBusy(piece.key); setError(null);
    try {
      let revision = harness.current.revision;
      for (const node of nodes) {
        const result = await editAgentCoreHarness(operation(revision, "remove_node", { node_id: node.node_id }));
        revision = result.revision.revision;
      }
      setPieceOverrides({}); setHiddenPieceKeys(new Set()); await refresh();
    } catch (reason) { setError(errorText(reason, chinese)); await refresh(); }
    finally { setBusy(null); }
  };
  const replacePiece = async (source: PieceDetails, target: ReplacementCandidate) => {
    setContextMenu(null);
    if (target.previewPiece) {
      setPieceOverrides((values) => ({ ...values, [source.key]: {
        title: target.title, description: target.description, category: target.category, color: target.color,
      } }));
      return;
    }
    if (!target.pluginId || !target.action) {
      setError(chinese ? "该替换项当前没有可用的后端插件。" : "This replacement has no available backend plug-in.");
      return;
    }
    setBusy(source.key); setError(null);
    try {
      if (target.action === "apply-profile") await applyAgentCoreHarnessProfile(target.pluginId);
      else await setAgentCorePlugin(target.pluginId, true);
      setPieceOverrides({}); setHiddenPieceKeys(new Set()); await refresh();
    } catch (reason) { setError(errorText(reason, chinese)); await refresh(); }
    finally { setBusy(null); }
  };

  const libraryToolbar = <div className="agent-plugin-toolbar agent-plugin-header-toolbar">
    <label className="agent-plugin-search"><Search aria-hidden="true" /><input value={query} onChange={(event) => setQuery(event.target.value)}
      placeholder={chinese ? "搜索插件" : "Search plug-ins"} aria-label={chinese ? "搜索插件" : "Search plug-ins"} /></label>
    <button type="button" className="btn btn-primary" disabled={busy === "import"} onClick={() => uploadInput.current?.click()}>
      <Upload aria-hidden="true" />{busy === "import" ? (chinese ? "正在导入" : "Importing") : (chinese ? "导入插件" : "Import Plugins")}</button>
    <input ref={uploadInput} type="file" accept=".zip" hidden onChange={(event) => void importPlugin(event.target.files?.[0])} />
  </div>;

  return <section className="agent-plugin-page agent-plugin-studio">
    <header className="agent-plugin-studio-header">
      {view === "harness" ? <div className="agent-plugin-introduction">
        <span className="agent-plugin-eyebrow"><Sparkles aria-hidden="true" />{chinese ? "模块化飞行智能" : "Modular flight intelligence"}</span>
        <p>{chinese ? "用一级插件快速拼出 Harness，需要时再展开二级插件。" : "Build a Harness with level-one blocks, then open level-two plug-ins only when needed."}</p>
      </div> : libraryToolbar}
      <nav className="agent-plugin-view-switch" aria-label={chinese ? "插件视图" : "Plugin view"}>
        <button type="button" className={view === "harness" ? "is-active" : ""} onClick={() => setView("harness")}><GitBranch aria-hidden="true" />Harness</button>
        <button type="button" className={view === "library" ? "is-active" : ""} onClick={() => setView("library")}><Library aria-hidden="true" />{chinese ? "插件库" : "Library"}</button>
      </nav>
    </header>
    {error ? <p className="agent-plugin-notice" role="status"><CircleAlert aria-hidden="true" />{error}</p> : null}

    {view === "harness" ? <div className="agent-harness-overview">
      <header className="agent-harness-summary">
        <div><span className="agent-harness-live-dot" aria-hidden="true" /><small>{chinese ? "当前 Harness" : "Current Harness"}</small>
          <strong>{activeProfile ? (hasCjk(activeProfile.name) && !chinese ? englishIdentifier(activeProfile.profile_id) : activeProfile.name) : (chinese ? "均衡闭环" : "Balanced closed loop")}</strong></div>
        <p>{chinese ? `${groups.length} 个一级插件 · ${groups.reduce((count, group) => count + group.atoms.length, 0)} 个二级插件` : `${groups.length} level-one blocks · ${groups.reduce((count, group) => count + group.atoms.length, 0)} level-two plug-ins`}</p>
        <NavLink to="/autonomy/plugins/harness">{chinese ? "打开编排器" : "Open composer"}<ArrowRight aria-hidden="true" /></NavLink>
      </header>
      <div className="agent-harness-stage-track" role="list" aria-label={chinese ? "一级插件" : "Level-one plug-ins"}>
        {groups.map((group, index) => {
          const expanded = group.id === activeGroupId; const selection: PieceSelection = { level: 1, groupId: group.id };
          return <button type="button" role="listitem" key={group.id} className={expanded ? "is-expanded" : ""}
            style={{ "--piece-color": group.color, "--stage-index": index } as CSSProperties}
            onClick={() => setExpandedGroupId(group.id)} onContextMenu={(event) => openContextMenu(event, selection)}
            onKeyDown={(event) => openContextMenuFromKeyboard(event, selection)} aria-expanded={expanded}
            aria-label={`${group.title}. ${chinese ? "右击打开菜单" : "Right-click for actions"}`}>
            <PuzzleShape first={index === 0} last={index === groups.length - 1} />
            <span className="agent-harness-stage-number">{String(index + 1).padStart(2, "0")}</span>
            <span className="agent-harness-stage-icon"><GroupIcon index={index} /></span>
            <span className="agent-harness-stage-copy"><strong>{group.title}</strong><small>{group.description}</small></span>
            <span className="agent-harness-stage-count">{group.atoms.length}</span><ChevronDown className="agent-harness-stage-chevron" aria-hidden="true" />
          </button>;
        })}
      </div>
      {activeGroup ? <section className="agent-harness-atom-panel" key={activeGroup.id} style={{ "--piece-color": activeGroup.color } as CSSProperties}>
        <header><div><span>{chinese ? "二级拼图" : "Level two"}</span><h2>{activeGroup.title}</h2></div>
          <p>{chinese ? "右击任意拼图即可查看详情、替换或删除。" : "Right-click any piece to inspect, replace, or remove it."}</p></header>
        <div className="agent-harness-atom-grid" role="list" aria-label={chinese ? `${activeGroup.title} 的二级插件` : `Level-two plug-ins for ${activeGroup.title}`}>
          {activeGroup.atoms.map((atom, index) => {
            const selection: PieceSelection = { level: 2, groupId: activeGroup.id, atomId: atom.id };
            return <article key={atom.id} role="listitem" tabIndex={0} style={{ "--atom-index": index, "--piece-color": atom.color } as CSSProperties}
              onContextMenu={(event) => openContextMenu(event, selection)} onKeyDown={(event) => openContextMenuFromKeyboard(event, selection)}
              aria-label={`${atom.title}. ${chinese ? "右击打开菜单" : "Right-click for actions"}`}>
              <PuzzleShape first={false} last={false} /><span className="agent-harness-atom-status"><CheckCircle2 aria-hidden="true" /></span>
              <div><strong>{atom.title}</strong><p>{atom.description}</p></div>
              <footer><span>{categoryLabel(atom.category, chinese)}</span>{atom.protected ? <span><ShieldCheck aria-hidden="true" />{chinese ? "安全锁定" : "Safety locked"}</span> : null}
                {atom.settingCount ? <span>{chinese ? `${atom.settingCount} 项设置` : `${atom.settingCount} settings`}</span> : null}</footer>
            </article>;
          })}
        </div>
      </section> : null}
    </div> : <div className="agent-plugin-library-view">
      {loading && !plugins.length ? <p className="agent-plugin-empty">{chinese ? "正在读取插件" : "Loading plug-ins"}</p> : null}
      {!loading && !visiblePlugins.length ? <p className="agent-plugin-empty">{chinese ? "没有已安装的独立插件" : "No standalone plug-ins installed"}</p> : null}
      <div className="agent-plugin-simple-list">{visiblePlugins.map((plugin) => <article key={plugin.plugin_id}>
        <Blocks aria-hidden="true" /><strong>{pluginName(chinese, plugin)}</strong>
        {plugin.removable ? <button type="button" aria-label={chinese ? `删除 ${pluginName(chinese, plugin)}` : `Delete ${pluginName(chinese, plugin)}`}
          disabled={busy === plugin.plugin_id} onClick={() => void removePlugin(plugin)}><Trash2 aria-hidden="true" /></button> : null}
      </article>)}</div>
    </div>}

    {contextMenu && selectedPiece ? <div ref={menuRef} className={`agent-piece-context-menu${contextMenu.submenuLeft ? " is-submenu-left" : ""}`} role="menu"
      aria-label={chinese ? `${selectedPiece.title} 操作` : `${selectedPiece.title} actions`} style={{ left: contextMenu.x, top: contextMenu.y }}
      onClick={(event) => event.stopPropagation()} onKeyDown={menuKeyDown}>
      <button role="menuitem" type="button" onClick={() => { setDetailsSelection(selectedPiece.selection); setContextMenu(null); }}><Eye aria-hidden="true" /><span>{chinese ? "查看详情…" : "View details…"}</span></button>
      <button role="menuitem" type="button" data-submenu="replace" aria-haspopup="menu" aria-expanded={contextMenu.submenu}
        disabled={!replacementCandidates.length || (!catalog && !selectedPiece.replaceable)}
        onPointerEnter={() => setContextMenu((value) => value ? { ...value, submenu: true } : null)}
        onClick={() => setContextMenu((value) => value ? { ...value, submenu: true } : null)}>
        <Blocks aria-hidden="true" /><span>{chinese ? "替换" : "Replace"}</span><ChevronRight className="is-trailing" aria-hidden="true" /></button>
      <button role="menuitem" type="button" className="is-danger" disabled={selectedPiece.protected || busy === selectedPiece.key}
        onClick={() => void removePiece(selectedPiece)}><Trash2 aria-hidden="true" /><span>{selectedPiece.protected ? (chinese ? "安全锁定" : "Safety locked") : (chinese ? "删除" : "Remove")}</span></button>
      {contextMenu.submenu ? <div className="agent-piece-submenu" role="menu" aria-label={chinese ? "同级替换项" : "Same-level replacements"}
        onKeyDown={(event) => { if (event.key === "ArrowLeft" || event.key === "Escape") { event.preventDefault(); event.stopPropagation(); setContextMenu((value) => value ? { ...value, submenu: false } : null); menuRef.current?.querySelector<HTMLElement>("[data-submenu='replace']")?.focus(); } }}>
        <header>{chinese ? `仅显示 ${selectedPiece.level} 级拼图` : `Level ${selectedPiece.level} pieces only`}</header>
        {replacementCandidates.map((candidate, index) => <div key={candidate.key} className="agent-piece-submenu-row">
          {(index === 0 || replacementCandidates[index - 1]?.groupKey !== candidate.groupKey) ? <small role="presentation">{candidate.groupLabel}</small> : null}
          <button role="menuitem" type="button" onClick={() => void replacePiece(selectedPiece, candidate)}>
            <span style={{ "--candidate-color": candidate.color } as CSSProperties} /><strong>{candidate.title}</strong></button>
        </div>)}
      </div> : null}
    </div> : null}

    {detailsPiece ? <div className="agent-piece-dialog-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) setDetailsSelection(null); }}>
      <article className="agent-piece-dialog" role="dialog" aria-modal="true" aria-labelledby="agent-piece-dialog-title" style={{ "--piece-color": detailsPiece.color } as CSSProperties}>
        <button type="button" className="agent-piece-dialog-close" aria-label={chinese ? "关闭" : "Close"} onClick={() => setDetailsSelection(null)}><X aria-hidden="true" /></button>
        <span className="agent-piece-dialog-icon"><Blocks aria-hidden="true" /></span>
        <div><small>{chinese ? `${detailsPiece.level} 级拼图` : `Level ${detailsPiece.level} piece`} · {categoryLabel(detailsPiece.category, chinese)}</small>
          <h2 id="agent-piece-dialog-title">{detailsPiece.title}</h2><p>{detailsPiece.description}</p></div>
        <dl><div><dt>{chinese ? "包含能力" : "Capabilities"}</dt><dd>{detailsPiece.level === 1 ? detailsPiece.atomCount : 1}</dd></div>
          <div><dt>{chinese ? "保护状态" : "Protection"}</dt><dd>{detailsPiece.protected ? (chinese ? "安全锁定" : "Safety locked") : (chinese ? "可编辑" : "Editable")}</dd></div></dl>
      </article>
    </div> : null}
  </section>;
}
