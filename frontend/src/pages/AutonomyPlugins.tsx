import {
  Activity,
  Blocks,
  BrainCircuit,
  CheckCircle2,
  ChevronDown,
  CircleAlert,
  Gauge,
  KeyRound,
  Map as MapIcon,
  Plane,
  Plus,
  RefreshCw,
  Search,
  ShieldCheck,
  Sparkles,
  Trash2,
  Wrench,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import {
  AgentCoreRequestError,
  AgentCoreUnavailableError,
  getAgentCorePluginGovernance,
  getAgentCorePluginMarketplace,
  healthcheckAgentCorePlugin,
  importAgentCorePlugin,
  installAgentCoreMarketplacePlugin,
  listAgentCorePlugins,
  replaceAgentCorePluginGovernance,
  replaceAgentCorePluginMarketplaceSources,
  revokeAgentCorePlugin,
  setAgentCorePlugin,
  trustAgentCorePlugin,
  uninstallAgentCorePlugin,
  type AgentCorePluginEntry,
  type AgentCorePluginGovernancePolicy,
  type AgentCorePluginMarketplaceCatalog,
} from "../features/autonomy/agentCore";
import { useI18n } from "../i18n/I18nProvider";

type GroupedSlot = {
  id: string;
  label: string;
  order: number;
  mode: AgentCorePluginEntry["placement"]["activation_mode"];
  plugins: AgentCorePluginEntry[];
};

type GroupedCategory = {
  id: string;
  label: string;
  order: number;
  slots: GroupedSlot[];
};

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

function localizedLabel(chinese: boolean, label: string, identifier: string): string {
  if (chinese) return label || identifier;
  return label && !hasCjk(label) ? label : englishIdentifier(identifier);
}

function localizedPluginName(chinese: boolean, plugin: AgentCorePluginEntry): string {
  if (chinese || !hasCjk(plugin.name)) return plugin.name;
  return englishIdentifier(plugin.plugin_id.replace(/^dronedream\./u, ""));
}

function localizedDescription(chinese: boolean, plugin: AgentCorePluginEntry): string {
  if (chinese || !hasCjk(plugin.description)) return plugin.description;
  return `Provides ${englishIdentifier(plugin.placement.slot_id).toLocaleLowerCase()} capability.`;
}

function errorText(error: unknown, chinese: boolean): string {
  if (error instanceof AgentCoreUnavailableError) {
    return chinese ? "插件系统需要在 DroneDream 桌面软件中运行。" : error.message;
  }
  if (error instanceof AgentCoreRequestError) return error.message;
  return error instanceof Error
    ? error.message
    : chinese ? "插件操作失败。" : "The plugin operation failed.";
}

function CategoryIcon({ id }: { id: string }) {
  if (/safety|guard|validation/u.test(id)) return <ShieldCheck />;
  if (/planning|route|navigation/u.test(id)) return <MapIcon />;
  if (/flight|ros|control/u.test(id)) return <Plane />;
  if (/model|reason|harness/u.test(id)) return <BrainCircuit />;
  if (/tool|connector|asset/u.test(id)) return <Wrench />;
  if (/evidence|evaluation/u.test(id)) return <Gauge />;
  if (/runtime|simulation/u.test(id)) return <Activity />;
  return <Blocks />;
}

function PluginSwitch({
  plugin,
  busy,
  chinese,
  onToggle,
}: {
  plugin: AgentCorePluginEntry;
  busy: boolean;
  chinese: boolean;
  onToggle: () => void;
}) {
  const locked = !plugin.disable_allowed || (plugin.enabled && plugin.slot_required);
  const label = locked
    ? chinese ? "系统必需插件" : "Required system plugin"
    : plugin.enabled
      ? chinese ? "停用插件" : "Disable plugin"
      : chinese ? "启用插件" : "Enable plugin";
  return (
    <button
      type="button"
      className={`agent-plugin-switch ${plugin.enabled ? "is-on" : ""} ${locked ? "is-locked" : ""}`}
      aria-label={label}
      aria-pressed={plugin.enabled}
      disabled={locked || busy}
      onClick={(event) => {
        event.stopPropagation();
        onToggle();
      }}
    >
      <span />
    </button>
  );
}

export function AutonomyPlugins() {
  const { interfaceLocale } = useI18n();
  const chinese = interfaceLocale === "zh-CN";
  const uploadInput = useRef<HTMLInputElement>(null);
  const [plugins, setPlugins] = useState<AgentCorePluginEntry[]>([]);
  const [query, setQuery] = useState("");
  const [selected, setSelected] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [governanceOpen, setGovernanceOpen] = useState(false);
  const [governance, setGovernance] = useState<AgentCorePluginGovernancePolicy | null>(null);
  const [marketplaceOpen, setMarketplaceOpen] = useState(false);
  const [marketplace, setMarketplace] = useState<AgentCorePluginMarketplaceCatalog | null>(null);
  const [sourceName, setSourceName] = useState("");
  const [sourceUrl, setSourceUrl] = useState("");

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      setPlugins(await listAgentCorePlugins());
      setError(null);
    } catch (value) {
      setError(errorText(value, chinese));
    } finally {
      setLoading(false);
    }
  }, [chinese]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const act = useCallback(async (key: string, action: () => Promise<unknown>) => {
    setBusy(key);
    setError(null);
    try {
      await action();
      await refresh();
    } catch (value) {
      setError(errorText(value, chinese));
    } finally {
      setBusy(null);
    }
  }, [chinese, refresh]);

  const groups = useMemo<GroupedCategory[]>(() => {
    const normalizedQuery = query.trim().toLocaleLowerCase(interfaceLocale);
    const visible = normalizedQuery
      ? plugins.filter((plugin) => [
        plugin.plugin_id,
        plugin.name,
        plugin.description,
        plugin.placement.category_label,
        plugin.placement.slot_label,
      ].some((value) => value.toLocaleLowerCase(interfaceLocale).includes(normalizedQuery)))
      : plugins;
    const categories = new globalThis.Map<string, {
      id: string;
      label: string;
      order: number;
      slots: globalThis.Map<string, GroupedSlot>;
    }>();
    for (const plugin of visible) {
      const placement = plugin.placement;
      const category = categories.get(placement.category_id) ?? {
        id: placement.category_id,
        label: placement.category_label,
        order: placement.category_order,
        slots: new globalThis.Map<string, GroupedSlot>(),
      };
      const slot = category.slots.get(placement.slot_id) ?? {
        id: placement.slot_id,
        label: placement.slot_label,
        order: placement.slot_order,
        mode: placement.activation_mode,
        plugins: [],
      };
      slot.plugins.push(plugin);
      category.slots.set(slot.id, slot);
      categories.set(category.id, category);
    }
    return [...categories.values()]
      .sort((left, right) => left.order - right.order || left.id.localeCompare(right.id))
      .map((category) => ({
        ...category,
        slots: [...category.slots.values()]
          .sort((left, right) => left.order - right.order || left.id.localeCompare(right.id))
          .map((slot) => ({
            ...slot,
            plugins: slot.plugins.sort((left, right) => (
              left.placement.plugin_order - right.placement.plugin_order
              || left.plugin_id.localeCompare(right.plugin_id)
            )),
          })),
      }));
  }, [interfaceLocale, plugins, query]);

  const toggle = async (plugin: AgentCorePluginEntry) => {
    if (!plugin.enabled && !plugin.builtin && !["verified", "local-approved"].includes(plugin.trust_status)) {
      setSelected(plugin.plugin_id);
      setError(chinese
        ? "启用外部插件前，需要先核对发布者、权限与包哈希并批准当前版本。"
        : "Review the publisher, permissions, and package hash, then approve this version before enabling it.");
      return;
    }
    await act(plugin.plugin_id, () => setAgentCorePlugin(plugin.plugin_id, !plugin.enabled));
  };

  const upload = async (file: File | undefined) => {
    if (!file) return;
    await act("import", () => importAgentCorePlugin(file));
    if (uploadInput.current) uploadInput.current.value = "";
  };

  const openGovernance = async () => {
    const next = !governanceOpen;
    setGovernanceOpen(next);
    setMarketplaceOpen(false);
    if (!next || governance) return;
    try {
      setGovernance((await getAgentCorePluginGovernance()).policy);
    } catch (value) {
      setError(errorText(value, chinese));
    }
  };

  const openMarketplace = async () => {
    const next = !marketplaceOpen;
    setMarketplaceOpen(next);
    setGovernanceOpen(false);
    if (!next) return;
    try {
      setMarketplace(await getAgentCorePluginMarketplace());
    } catch (value) {
      setError(errorText(value, chinese));
    }
  };

  const saveSources = async (sources: AgentCorePluginMarketplaceCatalog["sources"]) => {
    setBusy("marketplace-sources");
    try {
      await replaceAgentCorePluginMarketplaceSources(sources);
      setMarketplace(await getAgentCorePluginMarketplace());
      setError(null);
    } catch (value) {
      setError(errorText(value, chinese));
    } finally {
      setBusy(null);
    }
  };

  const addSource = async () => {
    if (!marketplace || !sourceName.trim() || !sourceUrl.trim()) return;
    await saveSources([...marketplace.sources, {
      schema_version: "dronedream.plugin-marketplace-source.v1",
      source_id: `custom-${crypto.randomUUID().replaceAll("-", "").slice(0, 12)}`,
      name: sourceName.trim(),
      index_url: sourceUrl.trim(),
      enabled: true,
    }]);
    setSourceName("");
    setSourceUrl("");
  };

  return (
    <section className="agent-plugin-page">
      <header className="agent-plugin-page-header">
        <h1>{chinese ? "插件" : "Plugins"}</h1>
        <div>
          <label className="agent-plugin-search">
            <Search aria-hidden="true" />
            <input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder={chinese ? "搜索插件" : "Search plugins"}
              aria-label={chinese ? "搜索插件" : "Search plugins"}
            />
          </label>
          <button type="button" className={marketplaceOpen ? "is-active" : ""} onClick={() => void openMarketplace()} aria-label={chinese ? "插件市场" : "Plugin marketplace"}><Sparkles /></button>
          <button type="button" className={governanceOpen ? "is-active" : ""} onClick={() => void openGovernance()} aria-label={chinese ? "插件治理" : "Plugin governance"}><ShieldCheck /></button>
          <button type="button" onClick={() => uploadInput.current?.click()} aria-label={chinese ? "导入插件" : "Import plugin"} disabled={busy === "import"}><Plus /></button>
          <button type="button" onClick={() => void refresh()} aria-label={chinese ? "刷新" : "Refresh"} disabled={loading}><RefreshCw /></button>
          <input ref={uploadInput} type="file" accept=".zip" hidden onChange={(event) => void upload(event.target.files?.[0])} />
        </div>
      </header>

      {error ? <div className="agent-plugin-error" role="alert"><CircleAlert />{error}</div> : null}

      {governanceOpen && governance ? (
        <section className="agent-plugin-governance">
          <header><ShieldCheck /><h2>{chinese ? "插件治理" : "Plugin governance"}</h2></header>
          <div className="agent-plugin-governance-grid">
            <label><span>{chinese ? "策略" : "Policy"}</span><select value={governance.mode} onChange={(event) => setGovernance({ ...governance, mode: event.target.value as "personal" | "managed" })}><option value="personal">{chinese ? "个人" : "Personal"}</option><option value="managed">{chinese ? "企业托管" : "Managed"}</option></select></label>
            <label><span>{chinese ? "外部插件上限" : "External plugin limit"}</span><input type="number" min={0} max={2000} value={governance.maximum_external_plugins} onChange={(event) => setGovernance({ ...governance, maximum_external_plugins: Number(event.target.value) })} /></label>
            <label className="agent-plugin-check"><input type="checkbox" checked={governance.require_verified_signatures} onChange={(event) => setGovernance({ ...governance, require_verified_signatures: event.target.checked })} />{chinese ? "强制签名" : "Require signatures"}</label>
            <label className="agent-plugin-check"><input type="checkbox" checked={governance.allow_local_approval} onChange={(event) => setGovernance({ ...governance, allow_local_approval: event.target.checked })} />{chinese ? "允许本机批准" : "Allow local approval"}</label>
            <label className="is-wide"><span>{chinese ? "允许的发布者" : "Allowed publishers"}</span><input value={governance.allowed_publishers.join(", ")} onChange={(event) => setGovernance({ ...governance, allowed_publishers: event.target.value.split(",").map((value) => value.trim()).filter(Boolean) })} /></label>
            <label className="is-wide"><span>{chinese ? "禁用权限" : "Denied permissions"}</span><input value={governance.denied_permissions.join(", ")} onChange={(event) => setGovernance({ ...governance, denied_permissions: event.target.value.split(",").map((value) => value.trim()).filter(Boolean) })} /></label>
          </div>
          <button type="button" className="btn btn-primary" disabled={busy !== null} onClick={() => void act("governance", () => replaceAgentCorePluginGovernance(governance))}>{chinese ? "保存策略" : "Save policy"}</button>
        </section>
      ) : null}

      {marketplaceOpen && marketplace ? (
        <section className="agent-plugin-marketplace">
          <header><Sparkles /><h2>{chinese ? "插件市场" : "Plugin marketplace"}</h2></header>
          <div className="agent-plugin-source-create"><input value={sourceName} onChange={(event) => setSourceName(event.target.value)} placeholder={chinese ? "源名称" : "Source name"} /><input value={sourceUrl} onChange={(event) => setSourceUrl(event.target.value)} placeholder="https://…/index.json" /><button type="button" onClick={() => void addSource()} disabled={!sourceName.trim() || !sourceUrl.trim()}>{chinese ? "添加源" : "Add source"}</button></div>
          {marketplace.sources.map((source) => <div className="agent-plugin-source" key={source.source_id}><label><input type="checkbox" checked={source.enabled} onChange={() => void saveSources(marketplace.sources.map((item) => item.source_id === source.source_id ? { ...item, enabled: !item.enabled } : item))} />{source.name}</label><span>{source.index_url}</span><button type="button" onClick={() => void saveSources(marketplace.sources.filter((item) => item.source_id !== source.source_id))}><Trash2 />{chinese ? "移除" : "Remove"}</button></div>)}
          <div className="agent-plugin-marketplace-grid">{marketplace.entries.map((entry) => <article key={`${entry.source_id}:${entry.plugin_id}:${entry.version}`}><strong>{chinese || !hasCjk(entry.name) ? entry.name : englishIdentifier(entry.plugin_id)}</strong><span>{entry.publisher} · v{entry.version}</span><button type="button" disabled={busy !== null} onClick={() => void act(`market:${entry.plugin_id}`, () => installAgentCoreMarketplacePlugin(entry.source_id, entry.plugin_id, entry.version))}>{chinese ? "安装" : "Install"}</button></article>)}</div>
        </section>
      ) : null}

      {loading && !plugins.length ? <div className="agent-plugin-loading"><RefreshCw />{chinese ? "正在连接插件运行时" : "Connecting to the plugin runtime"}</div> : null}
      {!loading && !error && !groups.length ? <div className="agent-plugin-loading"><Blocks />{chinese ? "没有匹配的插件" : "No matching plugins"}</div> : null}

      <div className="agent-plugin-categories">
        {groups.map((category) => (
          <section className="agent-plugin-category" key={category.id}>
            <header><CategoryIcon id={category.id} /><h2>{localizedLabel(chinese, category.label, category.id)}</h2></header>
            {category.slots.map((slot) => (
              <section className="agent-plugin-slot" key={slot.id}>
                <header><h3>{localizedLabel(chinese, slot.label, slot.id)}</h3><span>{slot.mode === "single" ? (chinese ? "单选" : "Single choice") : slot.mode === "pipeline" ? (chinese ? "有序管线" : "Ordered pipeline") : (chinese ? "可多选" : "Multiple choice")}</span></header>
                <div className="agent-plugin-list">
                  {slot.plugins.map((plugin) => (
                    <article className={`agent-plugin-entry ${selected === plugin.plugin_id ? "is-expanded" : ""}`} key={plugin.plugin_id}>
                      <button type="button" className="agent-plugin-summary" onClick={() => setSelected((current) => current === plugin.plugin_id ? null : plugin.plugin_id)}>
                        <span className="agent-plugin-icon"><CategoryIcon id={category.id} /></span>
                        <span className="agent-plugin-name"><strong>{localizedPluginName(chinese, plugin)}</strong><small>{plugin.plugin_id}</small></span>
                        <span className={`agent-plugin-health is-${plugin.health} is-${plugin.trust_status}`}>{plugin.trust_status === "revoked" ? (chinese ? "已撤销" : "Revoked") : plugin.trust_status === "unverified" ? (chinese ? "待批准" : "Approval required") : plugin.health === "healthy" ? (chinese ? "正常" : "Healthy") : plugin.enabled ? (chinese ? "待检查" : "Check required") : (chinese ? "已停用" : "Disabled")}</span>
                        <span className="agent-plugin-version">v{plugin.version}</span>
                        <PluginSwitch plugin={plugin} busy={busy === plugin.plugin_id} chinese={chinese} onToggle={() => void toggle(plugin)} />
                        <ChevronDown className="agent-plugin-chevron" />
                      </button>
                      {selected === plugin.plugin_id ? (
                        <div className="agent-plugin-detail">
                          <p>{localizedDescription(chinese, plugin)}</p>
                          <dl>
                            <div><dt>{chinese ? "发布者" : "Publisher"}</dt><dd>{plugin.publisher}</dd></div>
                            <div><dt>{chinese ? "信任" : "Trust"}</dt><dd>{plugin.trust_status}</dd></div>
                            <div><dt>{chinese ? "运行方式" : "Runtime"}</dt><dd>{plugin.runtime_kind}</dd></div>
                            <div><dt>{chinese ? "故障策略" : "Failure policy"}</dt><dd>{plugin.placement.failure_mode}</dd></div>
                            <div><dt>{chinese ? "切换策略" : "Swap policy"}</dt><dd>{plugin.placement.swap_policy}</dd></div>
                            <div><dt>{chinese ? "权限" : "Permissions"}</dt><dd>{plugin.permissions.length ? plugin.permissions.join(" · ") : (chinese ? "无" : "None")}</dd></div>
                            <div className="is-wide"><dt>{chinese ? "包哈希" : "Package hash"}</dt><dd title={plugin.package_sha256}>{plugin.package_sha256}</dd></div>
                          </dl>
                          {plugin.last_error ? <div className="agent-plugin-error"><CircleAlert />{plugin.last_error}</div> : null}
                          <div className="agent-plugin-actions">
                            {!plugin.builtin && plugin.trust_status === "unverified" ? <button type="button" onClick={() => void act(`${plugin.plugin_id}:trust`, () => trustAgentCorePlugin(plugin.plugin_id))}><CheckCircle2 />{chinese ? "批准此版本" : "Approve version"}</button> : null}
                            <button type="button" onClick={() => void act(`${plugin.plugin_id}:health`, () => healthcheckAgentCorePlugin(plugin.plugin_id))}><RefreshCw />{chinese ? "健康检查" : "Health check"}</button>
                            {!plugin.builtin && plugin.trust_status !== "revoked" ? <button type="button" onClick={() => void act(`${plugin.plugin_id}:revoke`, () => revokeAgentCorePlugin(plugin.plugin_id))}><KeyRound />{chinese ? "撤销信任" : "Revoke trust"}</button> : null}
                            {plugin.removable ? <button type="button" className="is-danger" onClick={() => void act(`${plugin.plugin_id}:remove`, () => uninstallAgentCorePlugin(plugin.plugin_id))}><Trash2 />{chinese ? "卸载" : "Uninstall"}</button> : null}
                          </div>
                        </div>
                      ) : null}
                    </article>
                  ))}
                </div>
              </section>
            ))}
          </section>
        ))}
      </div>
    </section>
  );
}
