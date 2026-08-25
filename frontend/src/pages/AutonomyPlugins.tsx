import { Blocks, CircleAlert, Search, Trash2, Upload } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import {
  AgentCoreRequestError,
  AgentCoreUnavailableError,
  importAgentCorePlugin,
  listAgentCorePlugins,
  uninstallAgentCorePlugin,
  type AgentCorePluginEntry,
} from "../features/autonomy/agentCore";
import { useI18n } from "../i18n/I18nProvider";

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
    return chinese ? "插件系统需要在 DroneDream 桌面软件中运行。" : error.message;
  }
  if (error instanceof AgentCoreRequestError) return error.message;
  return error instanceof Error
    ? error.message
    : chinese ? "插件操作失败。" : "The plugin operation failed.";
}

export function AutonomyPlugins() {
  const { interfaceLocale } = useI18n();
  const chinese = interfaceLocale === "zh-CN";
  const uploadInput = useRef<HTMLInputElement>(null);
  const [plugins, setPlugins] = useState<AgentCorePluginEntry[]>([]);
  const [query, setQuery] = useState("");
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      setPlugins(await listAgentCorePlugins());
      setError(null);
    } catch (reason) {
      setError(errorText(reason, chinese));
    } finally {
      setLoading(false);
    }
  }, [chinese]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

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
    <section className="agent-plugin-page agent-plugin-page-simple">
      <div className="agent-plugin-toolbar">
        <label className="agent-plugin-search">
          <Search aria-hidden="true" />
          <input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder={chinese ? "搜索插件" : "Search plugins"}
            aria-label={chinese ? "搜索插件" : "Search plugins"}
          />
        </label>
        <button type="button" className="btn btn-primary" disabled={busy === "import"} onClick={() => uploadInput.current?.click()}>
          <Upload aria-hidden="true" />
          {busy === "import" ? (chinese ? "正在导入" : "Importing") : (chinese ? "导入" : "Import")}
        </button>
        <input ref={uploadInput} type="file" accept=".zip" hidden onChange={(event) => void importPlugin(event.target.files?.[0])} />
      </div>

      {error ? <p className="agent-plugin-error" role="alert"><CircleAlert aria-hidden="true" />{error}</p> : null}
      {loading && !plugins.length ? <p className="agent-plugin-empty">{chinese ? "正在读取插件" : "Loading plugins"}</p> : null}
      {!loading && !visiblePlugins.length ? <p className="agent-plugin-empty">{chinese ? "没有插件" : "No plugins"}</p> : null}

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
    </section>
  );
}
