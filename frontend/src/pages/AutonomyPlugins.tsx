import {
  ArrowRight, Blocks, CheckCircle2, ChevronDown, CircleAlert, GitBranch,
  Layers3, Library, Search, ShieldCheck, Sparkles, Trash2, Upload, Waypoints,
} from "lucide-react";
import {
  useCallback, useEffect, useMemo, useRef, useState, type CSSProperties,
} from "react";
import { NavLink } from "react-router-dom";

import {
  AgentCoreRequestError,
  AgentCoreUnavailableError,
  getAgentCoreHarnessCatalog,
  getAgentCoreHarnessState,
  importAgentCorePlugin,
  listAgentCorePlugins,
  uninstallAgentCorePlugin,
  type AgentCoreHarnessCatalog,
  type AgentCoreHarnessState,
  type AgentCorePluginEntry,
} from "../features/autonomy/agentCore";
import { useI18n } from "../i18n/I18nProvider";
import "./AutonomyPlugins.css";

type StudioView = "harness" | "library";

type HarnessAtom = {
  id: string;
  title: string;
  description: string;
  category: string;
  protected: boolean;
  enabled: boolean;
  settingCount: number;
};

type HarnessGroup = {
  id: string;
  title: string;
  description: string;
  color: string;
  atoms: HarnessAtom[];
};

const GROUP_COLORS = ["#f23866", "#6d57e8", "#0ea5d7", "#1fbf82", "#f09a3e"];

const PREVIEW_GROUPS: Array<{
  id: string;
  color: string;
  title: [string, string];
  description: [string, string];
  atoms: Array<{
    id: string;
    title: [string, string];
    description: [string, string];
    category: string;
    protected: boolean;
    enabled: boolean;
    settingCount: number;
  }>;
}> = [
  {
    id: "intake", color: GROUP_COLORS[0],
    title: ["任务接入", "Task intake"],
    description: ["理解目标并建立可靠的任务上下文", "Understand the goal and establish trusted task context"],
    atoms: [
      { id: "intent", title: ["意图解析", "Intent parser"], description: ["提取目标、约束和中断指令", "Extract goals, constraints, and interrupts"], category: "input", protected: false, enabled: true, settingCount: 2 },
      { id: "context", title: ["上下文装载", "Context loader"], description: ["绑定地图、飞行器与实时状态", "Bind map, aircraft, and live state"], category: "memory", protected: false, enabled: true, settingCount: 1 },
      { id: "guard", title: ["输入安全门", "Input safety gate"], description: ["阻止越权或不完整的任务进入执行", "Block unsafe or incomplete tasks"], category: "safety", protected: true, enabled: true, settingCount: 2 },
    ],
  },
  {
    id: "planning", color: GROUP_COLORS[1],
    title: ["规划与决策", "Plan and decide"],
    description: ["生成路线，并在约束内作出决策", "Build routes and make decisions within constraints"],
    atoms: [
      { id: "planner", title: ["任务规划", "Mission planner"], description: ["把自然语言转成可执行任务图", "Turn natural language into an executable graph"], category: "orchestration", protected: false, enabled: true, settingCount: 3 },
      { id: "route", title: ["路径规划", "Route planner"], description: ["依据障碍物和实时位置生成航路", "Route around obstacles from the live position"], category: "control", protected: false, enabled: true, settingCount: 2 },
      { id: "approval", title: ["决策审批", "Decision approval"], description: ["在高风险动作前请求必要确认", "Request confirmation before high-risk actions"], category: "assurance", protected: true, enabled: true, settingCount: 1 },
    ],
  },
  {
    id: "execution", color: GROUP_COLORS[2],
    title: ["飞行执行", "Flight execution"],
    description: ["持续下发控制，并保持高频闭环", "Dispatch control through a high-frequency closed loop"],
    atoms: [
      { id: "dispatch", title: ["指令调度", "Command dispatch"], description: ["将计划转成 PX4 或真机命令", "Translate plans into PX4 or device commands"], category: "integration", protected: false, enabled: true, settingCount: 2 },
      { id: "telemetry", title: ["遥测同步", "Telemetry sync"], description: ["高频读取姿态、位置与健康状态", "Read pose, position, and health at high frequency"], category: "control", protected: true, enabled: true, settingCount: 2 },
      { id: "reroute", title: ["动态重规划", "Live replanning"], description: ["被打断时先悬停，再从当前位置重规划", "Hover on interrupt, then replan from the live position"], category: "orchestration", protected: false, enabled: true, settingCount: 3 },
    ],
  },
  {
    id: "verification", color: GROUP_COLORS[3],
    title: ["验证与交付", "Verify and deliver"],
    description: ["监测风险，确认结果并生成证据", "Monitor risk, confirm results, and produce evidence"],
    atoms: [
      { id: "monitor", title: ["安全监测", "Safety monitor"], description: ["识别碰撞、失联和任务偏差", "Detect collision, disconnect, and mission drift"], category: "safety", protected: true, enabled: true, settingCount: 2 },
      { id: "validator", title: ["结果验证", "Result validator"], description: ["用真实状态而不是路径穿越判断成功", "Judge success from real state, never path crossing"], category: "assurance", protected: true, enabled: true, settingCount: 2 },
      { id: "report", title: ["证据交付", "Evidence delivery"], description: ["保存轨迹、录像和任务回执", "Save trajectory, recording, and mission receipt"], category: "integration", protected: false, enabled: true, settingCount: 1 },
    ],
  },
];

function hasCjk(value: string): boolean {
  return /[\u3400-\u9fff]/u.test(value);
}

function englishIdentifier(value: string): string {
  return value
    .split(/[._-]+/u)
    .filter(Boolean)
    .map((part) => `${part.charAt(0).toUpperCase()}${part.slice(1)}`)
    .join(" ");
}

function pluginName(chinese: boolean, plugin: AgentCorePluginEntry): string {
  if (chinese || !hasCjk(plugin.name)) return plugin.name;
  return englishIdentifier(plugin.plugin_id.replace(/^dronedream\./u, ""));
}

function errorText(error: unknown, chinese: boolean): string {
  if (error instanceof AgentCoreUnavailableError) {
    return chinese ? "当前显示 Harness 结构预览；桌面版登录后会载入实时插件。" : "Showing the Harness structure preview. The desktop app loads live plugins after sign-in.";
  }
  if (error instanceof AgentCoreRequestError) return error.message;
  return error instanceof Error
    ? error.message
    : chinese ? "插件操作失败。" : "The plugin operation failed.";
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
    ...group,
    title: group.title[languageIndex],
    description: group.description[languageIndex],
    atoms: group.atoms.map((atom) => ({
      ...atom,
      title: atom.title[languageIndex],
      description: atom.description[languageIndex],
    })),
  }));
}

function catalogGroups(
  chinese: boolean,
  catalog: AgentCoreHarnessCatalog | null,
  harness: AgentCoreHarnessState | null,
): HarnessGroup[] {
  if (!catalog) return previewGroups(chinese);
  const activeIds = new Set(harness?.current.candidate.nodes.map((node) => node.node_id) ?? []);
  const levelOne = catalog.composition_items
    .filter((item) => item.level === 1 && item.parent_item_id === null)
    .filter((item) => !activeIds.size || item.member_node_ids.some((id) => activeIds.has(id)))
    .sort((left, right) => left.order - right.order)
    .slice(0, 5);

  const groups = levelOne.map((group, groupIndex): HarnessGroup => {
    const atoms = catalog.composition_items
      .filter((item) => item.level === 2 && item.parent_item_id === group.item_id)
      .filter((item) => !activeIds.size || item.member_node_ids.some((id) => activeIds.has(id)))
      .sort((left, right) => left.order - right.order)
      .map((item): HarnessAtom => ({
        id: item.item_id,
        title: itemLabel(chinese, item),
        description: itemDescription(chinese, item),
        category: item.category_id,
        protected: item.protected,
        enabled: !activeIds.size || item.member_node_ids.some((id) => activeIds.has(id)),
        settingCount: catalog.composition_items.filter((detail) => detail.level === 3 && detail.parent_item_id === item.item_id).length,
      }));
    return {
      id: group.item_id,
      title: itemLabel(chinese, group),
      description: itemDescription(chinese, group),
      color: GROUP_COLORS[groupIndex % GROUP_COLORS.length],
      atoms,
    };
  });
  return groups.length >= 3 ? groups : previewGroups(chinese);
}

function GroupIcon({ index }: { index: number }) {
  const Icon = [Waypoints, GitBranch, Layers3, ShieldCheck, Sparkles][index] ?? Blocks;
  return <Icon aria-hidden="true" />;
}

export function AutonomyPlugins() {
  const { interfaceLocale } = useI18n();
  const chinese = interfaceLocale === "zh-CN";
  const uploadInput = useRef<HTMLInputElement>(null);
  const [view, setView] = useState<StudioView>("harness");
  const [plugins, setPlugins] = useState<AgentCorePluginEntry[]>([]);
  const [catalog, setCatalog] = useState<AgentCoreHarnessCatalog | null>(null);
  const [harness, setHarness] = useState<AgentCoreHarnessState | null>(null);
  const [expandedGroupId, setExpandedGroupId] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

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

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const groups = useMemo(() => catalogGroups(chinese, catalog, harness), [catalog, chinese, harness]);
  const activeGroupId = expandedGroupId && groups.some((group) => group.id === expandedGroupId)
    ? expandedGroupId
    : groups[0]?.id ?? null;
  const activeGroup = groups.find((group) => group.id === activeGroupId) ?? null;
  const activeProfile = catalog?.profiles.find((profile) => profile.profile_id === harness?.current.candidate.profile_id);

  const visiblePlugins = useMemo(() => {
    const needle = query.trim().toLocaleLowerCase(interfaceLocale);
    if (!needle) return plugins;
    return plugins.filter((plugin) => [plugin.name, plugin.plugin_id, plugin.publisher]
      .some((value) => value.toLocaleLowerCase(interfaceLocale).includes(needle)));
  }, [interfaceLocale, plugins, query]);

  const importPlugin = async (file: File | undefined) => {
    if (!file) return;
    setBusy("import");
    setError(null);
    try {
      await importAgentCorePlugin(file);
      await refresh();
    } catch (reason) {
      setError(errorText(reason, chinese));
    } finally {
      setBusy(null);
      if (uploadInput.current) uploadInput.current.value = "";
    }
  };

  const removePlugin = async (plugin: AgentCorePluginEntry) => {
    setBusy(plugin.plugin_id);
    setError(null);
    try {
      await uninstallAgentCorePlugin(plugin.plugin_id);
      await refresh();
    } catch (reason) {
      setError(errorText(reason, chinese));
    } finally {
      setBusy(null);
    }
  };

  return (
    <section className="agent-plugin-page agent-plugin-studio">
      <header className="agent-plugin-studio-header">
        <div>
          <span className="agent-plugin-eyebrow"><Sparkles aria-hidden="true" />{chinese ? "模块化飞行智能" : "Modular flight intelligence"}</span>
          <p>{chinese ? "用一级插件快速拼出 Harness，需要时再展开二级插件。" : "Build a Harness with level-one blocks, then open level-two plug-ins only when needed."}</p>
        </div>
        <nav className="agent-plugin-view-switch" aria-label={chinese ? "插件视图" : "Plugin view"}>
          <button type="button" className={view === "harness" ? "is-active" : ""} onClick={() => setView("harness")}>
            <GitBranch aria-hidden="true" />Harness
          </button>
          <button type="button" className={view === "library" ? "is-active" : ""} onClick={() => setView("library")}>
            <Library aria-hidden="true" />{chinese ? "插件库" : "Library"}
          </button>
        </nav>
      </header>

      {error ? <p className="agent-plugin-notice" role="status"><CircleAlert aria-hidden="true" />{error}</p> : null}

      {view === "harness" ? (
        <div className="agent-harness-overview">
          <header className="agent-harness-summary">
            <div>
              <span className="agent-harness-live-dot" aria-hidden="true" />
              <small>{chinese ? "当前 Harness" : "Current Harness"}</small>
              <strong>{activeProfile ? (hasCjk(activeProfile.name) && !chinese ? englishIdentifier(activeProfile.profile_id) : activeProfile.name) : (chinese ? "均衡闭环" : "Balanced closed loop")}</strong>
            </div>
            <p>{chinese ? `${groups.length} 个一级插件 · ${groups.reduce((count, group) => count + group.atoms.length, 0)} 个二级插件` : `${groups.length} level-one blocks · ${groups.reduce((count, group) => count + group.atoms.length, 0)} level-two plug-ins`}</p>
            <NavLink to="/autonomy/plugins/harness">{chinese ? "打开编排器" : "Open composer"}<ArrowRight aria-hidden="true" /></NavLink>
          </header>

          <div className="agent-harness-stage-track" role="list" aria-label={chinese ? "一级插件" : "Level-one plug-ins"}>
            {groups.map((group, index) => {
              const expanded = group.id === activeGroupId;
              return (
                <button
                  type="button"
                  role="listitem"
                  key={group.id}
                  className={expanded ? "is-expanded" : ""}
                  style={{ "--stage-color": group.color, "--stage-index": index } as CSSProperties}
                  onClick={() => setExpandedGroupId(group.id)}
                  aria-expanded={expanded}
                >
                  <span className="agent-harness-stage-number">{String(index + 1).padStart(2, "0")}</span>
                  <span className="agent-harness-stage-icon"><GroupIcon index={index} /></span>
                  <span className="agent-harness-stage-copy"><strong>{group.title}</strong><small>{group.description}</small></span>
                  <span className="agent-harness-stage-count">{group.atoms.length}</span>
                  <ChevronDown className="agent-harness-stage-chevron" aria-hidden="true" />
                </button>
              );
            })}
          </div>

          {activeGroup ? (
            <section className="agent-harness-atom-panel" key={activeGroup.id} style={{ "--stage-color": activeGroup.color } as CSSProperties}>
              <header>
                <div><span>{chinese ? "二级插件" : "Level two"}</span><h2>{activeGroup.title}</h2></div>
                <p>{chinese ? "每项能力都可替换或单独配置；内部策略不会再形成第三层。" : "Each capability can be replaced or configured. Internal policies no longer create a third visible level."}</p>
              </header>
              <div className="agent-harness-atom-grid">
                {activeGroup.atoms.map((atom, index) => (
                  <article key={atom.id} style={{ "--atom-index": index } as CSSProperties}>
                    <span className="agent-harness-atom-status"><CheckCircle2 aria-hidden="true" /></span>
                    <div><strong>{atom.title}</strong><p>{atom.description}</p></div>
                    <footer>
                      <span>{atom.category}</span>
                      {atom.protected ? <span><ShieldCheck aria-hidden="true" />{chinese ? "安全锁定" : "Safety locked"}</span> : null}
                      {atom.settingCount ? <span>{chinese ? `${atom.settingCount} 项设置` : `${atom.settingCount} settings`}</span> : null}
                    </footer>
                  </article>
                ))}
              </div>
            </section>
          ) : null}

          <div className="agent-harness-level-guide">
            <span><b>01</b><strong>{chinese ? "一级插件" : "Level one"}</strong><small>{chinese ? "一段完整工作能力，通常 3–5 块拼成 Harness" : "A complete work stage; usually 3–5 compose a Harness"}</small></span>
            <ArrowRight aria-hidden="true" />
            <span><b>02</b><strong>{chinese ? "二级插件" : "Level two"}</strong><small>{chinese ? "可替换的原子能力，供高级用户精细调整" : "Replaceable atomic capability for deeper control"}</small></span>
          </div>
        </div>
      ) : (
        <div className="agent-plugin-library-view">
          <div className="agent-plugin-toolbar">
            <label className="agent-plugin-search">
              <Search aria-hidden="true" />
              <input
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                placeholder={chinese ? "搜索插件" : "Search plug-ins"}
                aria-label={chinese ? "搜索插件" : "Search plug-ins"}
              />
            </label>
            <button type="button" className="btn btn-primary" disabled={busy === "import"} onClick={() => uploadInput.current?.click()}>
              <Upload aria-hidden="true" />
              {busy === "import" ? (chinese ? "正在导入" : "Importing") : (chinese ? "导入插件" : "Import plug-in")}
            </button>
            <input ref={uploadInput} type="file" accept=".zip" hidden onChange={(event) => void importPlugin(event.target.files?.[0])} />
          </div>

          {loading && !plugins.length ? <p className="agent-plugin-empty">{chinese ? "正在读取插件" : "Loading plug-ins"}</p> : null}
          {!loading && !visiblePlugins.length ? <p className="agent-plugin-empty">{chinese ? "没有已安装的独立插件" : "No standalone plug-ins installed"}</p> : null}

          <div className="agent-plugin-simple-list">
            {visiblePlugins.map((plugin) => (
              <article key={plugin.plugin_id}>
                <Blocks aria-hidden="true" />
                <strong>{pluginName(chinese, plugin)}</strong>
                <span>v{plugin.version}</span>
                {plugin.removable ? (
                  <button
                    type="button"
                    aria-label={chinese ? `删除 ${pluginName(chinese, plugin)}` : `Delete ${pluginName(chinese, plugin)}`}
                    disabled={busy === plugin.plugin_id}
                    onClick={() => void removePlugin(plugin)}
                  ><Trash2 aria-hidden="true" /></button>
                ) : null}
              </article>
            ))}
          </div>
        </div>
      )}
    </section>
  );
}
