import {
  Activity,
  Airplay,
  ArrowUp,
  Blocks,
  Cable,
  Camera,
  Check,
  ChevronRight,
  CircleCheck,
  CircleUserRound,
  Cpu,
  Database,
  FileClock,
  Gauge,
  GitBranch,
  Globe2,
  HardDrive,
  Layers3,
  MapPin,
  Mic,
  Paperclip,
  Navigation2,
  Orbit,
  Plus,
  Radar,
  Radio,
  Route,
  ScanLine,
  ShieldCheck,
  Sparkles,
  Trash2,
  Upload,
  Play,
  Square,
  VideoOff,
  Waypoints,
  Weight,
  X,
} from "lucide-react";
import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type Dispatch,
  type FormEvent,
  type ReactNode,
  type SetStateAction,
} from "react";
import {
  Link,
  Navigate,
  NavLink,
  Outlet,
  useLocation,
  useOutletContext,
} from "react-router-dom";

import type { BrandEditionId } from "../brand/edition-brand.generated";
import { apiClient } from "../api/client";
import { openAppSettings } from "../appSettings";
import { AssistantModelPicker } from "../components/AssistantModelPicker";
import {
  defaultAutonomyWorkspace,
  isAutonomyAircraftAssetQualified,
  loadAutonomyWorkspace,
  normalizeAutonomyWorkspace,
  saveAutonomyWorkspace,
  type AutonomyConversationMessage,
  type AutonomyMapPack,
  type AutonomyWorkspaceState,
} from "../features/autonomy/workspaceStore";
import {
  loadAutonomyAssetLibrary,
  saveAutonomyAssetLibrary,
  withCurrentAutonomyAssets,
  withExternalAutonomyAsset,
  type AutonomyAssetLibrary,
  type AutonomyExternalAssetReference,
} from "../features/autonomy/assetLibraryStore";
import {
  autonomyAssetPairQualified,
  autonomyMapPackQualified,
  planAutonomyMission,
  type AutonomyPlanningModel,
} from "../features/autonomy/autonomyPlanning";
import {
  AgentCoreRequestError,
  AgentCoreUnavailableError,
  cancelAgentCoreAssetQualificationJob,
  createAgentCoreAssetQualificationJob,
  createAgentCoreRemoteAssetImportJob,
  getAgentCoreAssetImportJobIssues,
  getAgentCoreAssetQualificationEvidence,
  getAgentCoreBootstrap,
  getAgentCoreStatus,
  getAgentCoreAssetQualificationJob,
  getAgentCoreAssetQualificationJobIssues,
  getAgentCoreExecutionEvidence,
  getAgentCoreLiveFrame,
  getAgentCoreLiveSources,
  getAgentCoreLiveTelemetry,
  getAgentCoreRuntimeStatus,
  listAgentCoreAssetImportJobs,
  listAgentCoreAssetSourceAdapters,
  pauseAgentCoreAssetQualificationJob,
  pickAndCreateAgentCoreAssetImportJob,
  pickAndSubmitAgentCoreCompanionResult,
  processAgentCoreAssetImportJob,
  restartAgentCore,
  startAgentCoreAssetQualificationJob,
  type AgentCoreAssetImportJob,
  type AgentCoreAssetIssue,
  type AgentCoreAssetPairRuntimeContracts,
  type AgentCoreAssetQualificationEvidence,
  type AgentCoreAssetQualificationJob,
  type AgentCoreAssetSourceAdapter,
  type AgentCoreAssetVersion,
  type AgentCoreExecutionEvidence,
  type AgentCoreLiveSource,
  type AgentCoreLiveTelemetry,
  type AgentCorePluginEntry,
} from "../features/autonomy/agentCore";
import {
  executeBoundAgentCoreMission,
  getBoundAgentCoreThread,
  submitRuntimeMessageToBoundAgentCore,
} from "../features/autonomy/agentCorePlanning";
import { useOptionalAuth } from "../features/auth/AuthContext";
import { publicDemoConsole } from "../features/demo/publicDemo";
import { consumeAutonomyHandoff } from "../features/experiment/assistantTaskRouter";
import { useVoiceInput } from "../features/experiment/useVoiceInput";
import { createExperimentWorkspaceId } from "../features/experiment/workspaceRegistry";
import {
  completeManagedModelCatalog,
  DEFAULT_MANAGED_MODEL_CATALOG,
  getManagedModelCatalog,
  managedModelAvailableForAssistant,
} from "../features/settings/cloudModelAccess";
import { useModelAccess } from "../features/settings/ModelAccessContext";
import { localeSafeError, useI18n } from "../i18n/I18nProvider";
import { useEditionTheme } from "../theme/EditionThemeProvider";
import type { AutonomyAssetConnector } from "../types/api";

type WorkspaceContext = {
  edition: BrandEditionId;
  chinese: boolean;
  workspace: AutonomyWorkspaceState;
  assetLibrary: AutonomyAssetLibrary;
  persist: (next: AutonomyWorkspaceState) => void;
  selectAircraft: (aircraftId: string) => void;
  selectMap: (mapId: string) => void;
  registerExternalAsset: (
    version: AgentCoreAssetVersion,
    qualificationId?: string | null,
  ) => AutonomyExternalAssetReference | null;
  bindQualifiedAssetPair: (
    job: AgentCoreAssetQualificationJob,
    mapVersion: AgentCoreAssetVersion,
    vehicleVersion: AgentCoreAssetVersion,
    runtimeContracts: AgentCoreAssetPairRuntimeContracts,
  ) => boolean;
  agentCorePlugins: AgentCorePluginEntry[];
  missionComposerDraft: string;
  setMissionComposerDraft: Dispatch<SetStateAction<string>>;
  removeAsset: (kind: "aircraft" | "map" | "external", id: string, contentSha256?: string | null) => void;
};

const IGNORE_EXTERNAL_ASSET: WorkspaceContext["registerExternalAsset"] = () => null;

type AutonomySectionId = "overview" | "aircraft" | "maps" | "plugins" | "live";

const SECTION_ICONS = {
  overview: Orbit,
  aircraft: Navigation2,
  maps: Layers3,
  plugins: Blocks,
  live: Airplay,
} as const;

const SECTION_COPY = {
  en: {
    overview: "Overview",
    aircraft: "Aircraft",
    maps: "Maps",
    plugins: "Plugins",
    live: "Live",
    title: "Autonomy",
  },
  zh: {
    overview: "总览",
    aircraft: "无人机",
    maps: "地图",
    plugins: "插件",
    live: "实时运行",
    title: "自主任务",
  },
} as const;

function useAutonomyWorkspace(): WorkspaceContext {
  return useOutletContext<WorkspaceContext>();
}

function updatedWorkspace(
  workspace: AutonomyWorkspaceState,
  patch: Partial<AutonomyWorkspaceState>,
): AutonomyWorkspaceState {
  return { ...workspace, ...patch };
}

const ASSET_QUALIFICATION_REQUIRED_INPUTS = new Set([
  "qualification_evidence",
  "qualification_environment_versions",
  "local_qualification_run",
]);

function companionResultRequired(job: AgentCoreAssetImportJob): boolean {
  return job.state === "needs_input" && job.required_inputs.some(
    (value) => !ASSET_QUALIFICATION_REQUIRED_INPUTS.has(value),
  );
}

function adapterPluginRequired(job: AgentCoreAssetImportJob): boolean {
  return job.state === "needs_input" && job.required_inputs.some(
    (value) => value.startsWith("plugin_adapter:"),
  );
}

function qualificationIdForAssetVersion(
  version: AgentCoreAssetVersion,
  jobs: AgentCoreAssetQualificationJob[],
): string | null {
  const match = jobs
    .filter((job) => job.state === "qualified" && Boolean(job.qualification_id))
    .filter((job) => version.kind === "vehicle"
      ? job.vehicle_asset_id === version.asset_id
        && job.result_vehicle_content_sha256 === version.content_sha256
      : job.map_asset_id === version.asset_id
        && job.result_map_content_sha256 === version.content_sha256)
    .sort((left, right) => right.updated_at.localeCompare(left.updated_at))[0];
  return match?.qualification_id ?? null;
}

function externalAssetReferenceFromVersion(
  version: AgentCoreAssetVersion,
  qualificationId: string | null = null,
): AutonomyExternalAssetReference {
  const ir = version.asset_ir;
  const source = ir && typeof ir.source === "object" && ir.source
    ? ir.source as Record<string, unknown>
    : {};
  const name = typeof ir?.name === "string" ? ir.name.trim() : version.asset_id;
  return {
    schemaVersion: 1,
    id: version.asset_id,
    kind: version.kind,
    name: name || version.asset_id,
    sourceApplication: typeof source.application === "string" ? source.application : "External source",
    sourceFormat: typeof source.source_format === "string" ? source.source_format : "ddpkg",
    version: typeof ir?.version === "string" ? ir.version : "1",
    maturity: version.maturity,
    contentSha256: version.content_sha256,
    qualificationId,
    importedAt: version.imported_at,
  };
}

function normalizedAutonomyPath(pathname: string): string {
  const withoutBasename = pathname === "/console"
    ? "/"
    : pathname.startsWith("/console/")
      ? pathname.slice("/console".length)
      : pathname;
  return withoutBasename.replace(/\/+$/u, "") || "/";
}

function Metric({ icon, label, value }: { icon: ReactNode; label: string; value: string }) {
  return <div className="autonomy-asset-metric"><span>{icon}{label}</span><strong>{value}</strong></div>;
}

function readinessLabel(ready: boolean, chinese: boolean): string {
  return ready
    ? chinese ? "已就绪" : "Ready"
    : chinese ? "未就绪" : "Blocked";
}

const AUTONOMY_ISSUE_COPY: Readonly<Record<string, { zh: string; en: string }>> = {
  "asset.aircraft.not-qualified": {
    zh: "所选无人机尚未通过当前任务的飞行包络检查。",
    en: "The selected aircraft has not passed the flight-envelope checks for this mission.",
  },
  "asset.map.not-qualified": {
    zh: "所选地图尚未完成标定并绑定到合格的三维场景。",
    en: "The selected map is not calibrated and bound to a qualified three-dimensional scene.",
  },
};

const STRUCTURED_TERM_COPY: Readonly<Record<string, { zh: string; en: string }>> = {
  language_model: { zh: "语言模型", en: "Language model" },
  mission_executive: { zh: "任务执行器", en: "Mission executive" },
  perception: { zh: "感知系统", en: "Perception" },
  global_planner: { zh: "全局规划器", en: "Global planner" },
  local_planner: { zh: "局部规划器", en: "Local planner" },
  payload_controller: { zh: "载荷控制器", en: "Payload controller" },
  px4_bridge: { zh: "PX4 桥接器", en: "PX4 bridge" },
  operator: { zh: "操作员", en: "Operator" },
  continue: { zh: "继续", en: "Continue" },
  hold: { zh: "悬停", en: "Hold" },
  land: { zh: "降落", en: "Land" },
  abort: { zh: "中止", en: "Abort" },
  landed: { zh: "已着陆", en: "Landed" },
  disarmed: { zh: "已解除武装", en: "Disarmed" },
};

function localizedAutonomyError(
  value: unknown,
  chinese: boolean,
  fallback: { zh: string; en: string },
): string {
  return localeSafeError(value, chinese ? "zh-CN" : "en", fallback);
}

function localizedPlanIssue(
  issue: { code: string; message: string },
  chinese: boolean,
): string {
  const authored = AUTONOMY_ISSUE_COPY[issue.code];
  if (authored) return chinese ? authored.zh : authored.en;
  return localizedAutonomyError(issue.message, chinese, {
    zh: `任务计划存在需要处理的问题（${issue.code}）。`,
    en: `The mission plan has an issue that requires attention (${issue.code}).`,
  });
}

function localizedStructuredTerm(value: string, chinese: boolean): string {
  const authored = STRUCTURED_TERM_COPY[value];
  return authored ? (chinese ? authored.zh : authored.en) : value.replaceAll("_", " ");
}

function localizedTaskNodeLabel(
  node: { task_id: string; label: string },
  index: number,
  chinese: boolean,
): string {
  return localizedAutonomyError(node.label, chinese, {
    zh: `任务节点 ${index + 1}（${node.task_id}）`,
    en: `Task node ${index + 1} (${node.task_id})`,
  });
}

function AgentCoreAssetIssueDetails({
  jobId,
  kind,
  chinese,
  enabled,
}: {
  jobId: string;
  kind: "import" | "qualification";
  chinese: boolean;
  enabled: boolean;
}) {
  const [issues, setIssues] = useState<AgentCoreAssetIssue[]>([]);
  useEffect(() => {
    let active = true;
    if (!enabled) {
      setIssues([]);
      return () => { active = false; };
    }
    const request = kind === "import"
      ? getAgentCoreAssetImportJobIssues(jobId)
      : getAgentCoreAssetQualificationJobIssues(jobId);
    void request.then((report) => {
      if (active) setIssues(report.issues);
    }).catch(() => {
      if (active) setIssues([]);
    });
    return () => { active = false; };
  }, [enabled, jobId, kind]);
  if (!issues.length) return null;
  const locale = chinese ? "zh-CN" : "en-US";
  return (
    <details className="autonomy-asset-issue-details">
      <summary>{chinese ? "查看问题与修复建议" : "View issue and repair guidance"}</summary>
      {issues.map((issue) => (
        <article key={`${issue.code}:${issue.location}`} data-severity={issue.severity}>
          <header><strong>{issue.title[locale]}</strong><code>{issue.code}</code></header>
          <small>{issue.location}</small>
          <p>{issue.detail[locale]}</p>
          <span>{issue.actions.map((action) => action[locale]).join(" · ")}</span>
        </article>
      ))}
    </details>
  );
}

function AgentCoreQualificationEvidenceDetails({
  job,
  chinese,
}: {
  job: AgentCoreAssetQualificationJob;
  chinese: boolean;
}) {
  const [evidence, setEvidence] = useState<AgentCoreAssetQualificationEvidence | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(false);
  if (job.state !== "qualified") return null;
  const load = async () => {
    setLoading(true);
    setError(false);
    try {
      setEvidence(await getAgentCoreAssetQualificationEvidence(job.job_id));
    } catch {
      setError(true);
    } finally {
      setLoading(false);
    }
  };
  const gates = Object.entries(evidence?.receipt.runtime_evidence?.gates ?? {});
  const pluginChecks = evidence?.receipt.plugin_checks ?? [];
  return (
    <details
      className="autonomy-qualification-evidence"
      onToggle={(event) => {
        if (event.currentTarget.open && !evidence && !loading) void load();
      }}
    >
      <summary>{loading
        ? chinese ? "正在校验证据" : "Verifying evidence"
        : chinese ? "查看认证证据" : "View qualification evidence"}</summary>
      {error ? <p>{chinese ? "证据校验失败，请重新运行认证。" : "Evidence verification failed. Run qualification again."}</p> : null}
      {evidence ? <>
        <dl>
          <div><dt>{chinese ? "认证 ID" : "Qualification ID"}</dt><dd>{evidence.qualification_id}</dd></div>
          <div><dt>{chinese ? "地图哈希" : "Map hash"}</dt><dd>{evidence.map_content_sha256.slice(0, 16)}</dd></div>
          <div><dt>{chinese ? "无人机哈希" : "Aircraft hash"}</dt><dd>{evidence.vehicle_content_sha256.slice(0, 16)}</dd></div>
          <div><dt>{chinese ? "核心门禁" : "Core gates"}</dt><dd>{gates.filter(([, passed]) => passed).length}/{gates.length}</dd></div>
          <div><dt>{chinese ? "插件检查" : "Plugin checks"}</dt><dd>{pluginChecks.filter((item) => item.accepted).length}/{pluginChecks.length}</dd></div>
          {evidence.receipt.plugin_snapshot_sha256 ? <div><dt>{chinese ? "插件快照" : "Plugin snapshot"}</dt><dd>{evidence.receipt.plugin_snapshot_sha256.slice(0, 16)}</dd></div> : null}
        </dl>
        {pluginChecks.length ? <ul className="autonomy-qualification-plugin-checks">{pluginChecks.map((check) => <li key={`${check.plugin_id}:${check.check_id}`}><span>{check.check_id}</span><strong>{check.accepted ? chinese ? "通过" : "Passed" : chinese ? "拒绝" : "Rejected"}</strong></li>)}</ul> : null}
      </> : null}
    </details>
  );
}

export function AutonomyAssetConnectorPanel({
  kind,
  chinese,
  compact = false,
}: {
  kind: "map" | "vehicle";
  chinese: boolean;
  compact?: boolean;
}) {
  const outletWorkspace = useOutletContext<WorkspaceContext | null>();
  const assetLibrary = outletWorkspace?.assetLibrary ?? { externalAssets: [] };
  const registerExternalAsset = outletWorkspace?.registerExternalAsset ?? IGNORE_EXTERNAL_ASSET;
  const [connectors, setConnectors] = useState<AutonomyAssetConnector[]>([]);
  const [coreAdapters, setCoreAdapters] = useState<AgentCoreAssetSourceAdapter[]>([]);
  const [jobs, setJobs] = useState<AgentCoreAssetImportJob[]>([]);
  const [catalogState, setCatalogState] = useState<"loading" | "ready" | "unavailable">("loading");
  const [importing, setImporting] = useState(false);
  const [importError, setImportError] = useState<string | null>(null);
  const [remoteOpen, setRemoteOpen] = useState(false);
  const [remoteType, setRemoteType] = useState<"direct_url" | "git">("direct_url");
  const [remoteLocation, setRemoteLocation] = useState("");
  const [remoteRef, setRemoteRef] = useState("");
  const [remoteSubpath, setRemoteSubpath] = useState("");
  const [remoteSha256, setRemoteSha256] = useState("");
  useEffect(() => {
    let active = true;
    void Promise.all([
      listAgentCoreAssetSourceAdapters(),
      listAgentCoreAssetImportJobs(),
      getAgentCoreBootstrap(),
    ]).then(([adapters, entries, bootstrap]) => {
      if (!active) return;
      setCoreAdapters(adapters.filter((adapter) => adapter.asset_kinds.includes(kind)));
      setJobs(entries.filter((job) => job.asset_kind === kind || job.asset_kind === null).slice(0, 4));
      bootstrap.asset_versions
        .filter((version) => (
          (version.kind === kind || (kind === "map" && version.kind === "world"))
          && ["simulation_ready", "flight_ready", "qualified"].includes(version.maturity)
        ))
        .forEach((version) => registerExternalAsset(
          version,
          qualificationIdForAssetVersion(version, bootstrap.asset_qualification_jobs),
        ));
      setCatalogState("ready");
    }).catch(async (error) => {
      if (!active) return;
      if (!(error instanceof AgentCoreUnavailableError)) {
        setCatalogState("unavailable");
        return;
      }
      try {
        const catalog = await apiClient.listAutonomyAssetConnectors();
        if (!active) return;
        setConnectors(catalog.items.filter((connector) => connector.asset_kinds.includes(kind)));
        setCatalogState("unavailable");
      } catch {
        if (active) setCatalogState("unavailable");
      }
    });
    return () => { active = false; };
  }, [kind, registerExternalAsset]);
  const importAsset = async (sourceKind: "file" | "directory") => {
    setImporting(true);
    setImportError(null);
    try {
      const created = await pickAndCreateAgentCoreAssetImportJob(
        kind,
        sourceKind,
        chinese ? "zh-CN" : "en-US",
        coreAdapters,
      );
      if (!created) return;
      const processed = await processAgentCoreAssetImportJob(created.job_id);
      setJobs((current) => [processed, ...current.filter((job) => job.job_id !== processed.job_id)].slice(0, 4));
      if (
        processed.state === "qualified"
        && processed.asset_id
        && processed.qualified_content_sha256
      ) {
        const bootstrap = await getAgentCoreBootstrap();
        const version = bootstrap.asset_versions.find((candidate) => (
          candidate.asset_id === processed.asset_id
          && candidate.content_sha256 === processed.qualified_content_sha256
        ));
        if (version) registerExternalAsset(
          version,
          qualificationIdForAssetVersion(version, bootstrap.asset_qualification_jobs),
        );
      }
    } catch (error) {
      setImportError(localizedAutonomyError(error, chinese, {
        zh: "资产导入失败。",
        en: "Asset import failed.",
      }));
    } finally {
      setImporting(false);
    }
  };
  if (compact) {
    return (
      <div className="autonomy-repository-import">
        <button
          type="button"
          className="btn btn-primary"
          onClick={() => void importAsset("file")}
          disabled={importing || catalogState !== "ready"}
        >
          <Upload aria-hidden="true" />
          {importing
            ? (chinese ? "正在导入" : "Importing")
            : kind === "vehicle"
              ? (chinese ? "导入无人机" : "Import aircraft")
              : (chinese ? "导入地图" : "Import map")}
        </button>
        {importError ? <span role="alert">{importError}</span> : null}
      </div>
    );
  }
  const submitCompanionResult = async (job: AgentCoreAssetImportJob) => {
    setImporting(true);
    setImportError(null);
    try {
      const processed = await pickAndSubmitAgentCoreCompanionResult(job, chinese ? "zh-CN" : "en-US");
      if (!processed) return;
      setJobs((current) => [processed, ...current.filter((entry) => entry.job_id !== processed.job_id)].slice(0, 4));
      if (
        processed.state === "qualified"
        && processed.asset_id
        && processed.qualified_content_sha256
      ) {
        const bootstrap = await getAgentCoreBootstrap();
        const version = bootstrap.asset_versions.find((candidate) => (
          candidate.asset_id === processed.asset_id
          && candidate.content_sha256 === processed.qualified_content_sha256
        ));
        if (version) registerExternalAsset(
          version,
          qualificationIdForAssetVersion(version, bootstrap.asset_qualification_jobs),
        );
      }
    } catch (error) {
      setImportError(localizedAutonomyError(error, chinese, {
        zh: "转换结果导入失败。",
        en: "Converted result import failed.",
      }));
    } finally {
      setImporting(false);
    }
  };
  const importRemoteAsset = async () => {
    setImporting(true);
    setImportError(null);
    try {
      const created = await createAgentCoreRemoteAssetImportJob({
        source_type: remoteType,
        location: remoteLocation.trim(),
        expected_kind: kind,
        ...(remoteType === "git" && remoteRef.trim() ? { git_ref: remoteRef.trim() } : {}),
        ...(remoteType === "git" && remoteSubpath.trim() ? { subpath: remoteSubpath.trim() } : {}),
        ...(remoteSha256.trim() ? { expected_sha256: remoteSha256.trim().toLowerCase() } : {}),
      });
      const processed = await processAgentCoreAssetImportJob(created.job_id);
      setJobs((current) => [processed, ...current.filter((job) => job.job_id !== processed.job_id)].slice(0, 4));
      setRemoteOpen(false);
    } catch (error) {
      setImportError(localizedAutonomyError(error, chinese, {
        zh: "远程资产导入失败。",
        en: "Remote asset import failed.",
      }));
    } finally {
      setImporting(false);
    }
  };
  const adapters = coreAdapters.length ? coreAdapters.map((adapter) => ({
    id: adapter.adapter_id,
    name: adapter.name,
    formats: adapter.source_formats,
    enabled: adapter.enabled,
    availability: adapter.availability,
  })) : connectors.map((connector) => ({
    id: connector.connector_id,
    name: connector.name,
    formats: connector.source_formats,
    enabled: connector.enabled,
    availability: connector.availability,
  }));
  const pluginsHref = window.location.hash.startsWith("#/")
    ? "#/autonomy/plugins"
    : `${window.location.pathname === "/console" || window.location.pathname.startsWith("/console/") ? "/console" : ""}/autonomy/plugins`;
  return (
    <section className="autonomy-config-card autonomy-connector-panel">
      <header>
        <Cable aria-hidden="true" />
        <h2>{chinese ? "外部资产导入" : "External asset import"}</h2>
        <span className="autonomy-connector-import-actions">
          <button type="button" className="btn" onClick={() => void importAsset("file")} disabled={importing || catalogState !== "ready"}>
            <Upload aria-hidden="true" />{importing ? (chinese ? "正在导入" : "Importing") : (chinese ? "导入文件" : "Import file")}
          </button>
          <button type="button" className="btn" onClick={() => void importAsset("directory")} disabled={importing || catalogState !== "ready"}>
            {chinese ? "导入文件夹" : "Import folder"}
          </button>
          <button type="button" className="btn" onClick={() => setRemoteOpen((current) => !current)} disabled={importing || catalogState !== "ready"}>
            <Globe2 aria-hidden="true" />{chinese ? "远程来源" : "Remote source"}
          </button>
        </span>
      </header>
      {remoteOpen ? <div className="autonomy-remote-import">
        <div className="autonomy-remote-import-tabs">
          <button type="button" data-active={remoteType === "direct_url"} onClick={() => setRemoteType("direct_url")}><Globe2 aria-hidden="true" />{chinese ? "文件网址" : "File URL"}</button>
          <button type="button" data-active={remoteType === "git"} onClick={() => setRemoteType("git")}><GitBranch aria-hidden="true" />Git</button>
        </div>
        <label><span>{remoteType === "git" ? (chinese ? "Git 仓库 HTTPS 地址" : "Git repository HTTPS URL") : (chinese ? "文件 HTTPS 地址" : "File HTTPS URL")}</span><input type="url" value={remoteLocation} onChange={(event) => setRemoteLocation(event.target.value)} placeholder="https://" /></label>
        {remoteType === "git" ? <div className="autonomy-remote-git-fields"><label><span>{chinese ? "分支或标签" : "Branch or tag"}</span><input value={remoteRef} onChange={(event) => setRemoteRef(event.target.value)} /></label><label><span>{chinese ? "资产子目录" : "Asset subdirectory"}</span><input value={remoteSubpath} onChange={(event) => setRemoteSubpath(event.target.value)} /></label></div> : null}
        <label><span>{chinese ? "预期 SHA-256（可选）" : "Expected SHA-256 (optional)"}</span><input value={remoteSha256} maxLength={64} onChange={(event) => setRemoteSha256(event.target.value)} /></label>
        <footer><button type="button" className="btn btn-primary" disabled={importing || !remoteLocation.trim() || Boolean(remoteSha256 && !/^[0-9a-fA-F]{64}$/u.test(remoteSha256))} onClick={() => void importRemoteAsset()}>{importing ? (chinese ? "正在导入" : "Importing") : (chinese ? "导入" : "Import")}</button></footer>
      </div> : null}
      {catalogState === "loading" ? <span className="autonomy-connector-state">{chinese ? "正在读取连接器" : "Loading connectors"}</span> : null}
      {catalogState === "unavailable" ? <span className="autonomy-connector-state is-unavailable">{chinese ? "需要桌面端导入" : "Desktop import required"}</span> : null}
      {importError ? <span className="autonomy-connector-state is-unavailable">{importError}</span> : null}
      {adapters.length ? <div className="autonomy-connector-grid">{adapters.map((adapter) => (
        <article key={adapter.id} data-enabled={adapter.enabled}>
          <span><strong>{adapter.name}</strong><small>{adapter.formats.join(" · ")}</small></span>
          <em>{adapter.enabled
            ? adapter.availability === "builtin"
              ? (chinese ? "内置可用" : "Built in")
              : (chinese ? "可用" : "Available")
            : adapter.availability === "companion_required"
              ? (chinese ? "需要本机配套程序" : "Companion required")
              : (chinese ? "需要插件" : "Plugin required")}</em>
        </article>
      ))}</div> : null}
      {jobs.length ? <div className="autonomy-import-jobs">{jobs.map((job) => {
        const states: Record<AgentCoreAssetImportJob["state"], [string, string]> = {
          created: ["已创建", "Created"],
          quarantining: ["隔离检查", "Quarantining"],
          parsing: ["正在解析", "Parsing"],
          needs_input: ["需要补充", "Input required"],
          normalizing: ["正在归一化", "Normalizing"],
          building: ["正在构建", "Building"],
          validating: ["正在验证", "Validating"],
          qualified: ["已认证", "Qualified"],
          failed: ["失败", "Failed"],
          cancelled: ["已取消", "Cancelled"],
        };
        return <article key={job.job_id}>
          <span><strong>{job.source_name}</strong><small>{job.detected_source_format ?? job.source_format} · {job.progress_percent}%</small></span>
          {companionResultRequired(job) ? (
            <span className="autonomy-connector-import-actions">
              {adapterPluginRequired(job) ? (
                <a className="btn" href={pluginsHref}>
                  {chinese ? "打开插件" : "Open plugins"}
                </a>
              ) : null}
              <button type="button" className="btn" onClick={() => void submitCompanionResult(job)} disabled={importing}>
                {chinese ? "提交转换结果" : "Submit converted package"}
              </button>
            </span>
          ) : <em data-state={job.state}>{states[job.state][chinese ? 0 : 1]}</em>}
          <AgentCoreAssetIssueDetails
            jobId={job.job_id}
            kind="import"
            chinese={chinese}
            enabled={Boolean(job.issue_codes.length || job.required_inputs.length)}
          />
        </article>;
      })}</div> : null}
      {assetLibrary.externalAssets.some((asset) => asset.kind === kind || (kind === "map" && asset.kind === "world")) ? (
        <div className="autonomy-import-jobs autonomy-imported-sources">
          {assetLibrary.externalAssets
            .filter((asset) => asset.kind === kind || (kind === "map" && asset.kind === "world"))
            .slice(0, 6)
            .map((asset) => (
              <article key={`${asset.id}:${asset.contentSha256}`}>
                <span><strong>{asset.name}</strong><small>{asset.sourceApplication} · {asset.maturity.replaceAll("_", " ")}</small></span>
                <em data-state={asset.maturity === "qualified" && asset.qualificationId ? "qualified" : "created"}>
                  {asset.maturity === "qualified" && asset.qualificationId
                    ? chinese ? "可成对绑定" : "Ready for pair binding"
                    : chinese ? "等待成对认证" : "Pair qualification required"}
                </em>
              </article>
            ))}
        </div>
      ) : null}
    </section>
  );
}

const QUALIFICATION_INPUT_MATURITY = new Set<AgentCoreAssetVersion["maturity"]>([
  "simulation_ready",
  "flight_ready",
  "qualified",
]);

function qualificationAssetLabel(version: AgentCoreAssetVersion): string {
  const name = typeof version.asset_ir.name === "string" && version.asset_ir.name.trim()
    ? version.asset_ir.name.trim()
    : version.asset_id;
  return `${name} · ${version.maturity.replaceAll("_", " ")} · ${version.content_sha256.slice(0, 10)}`;
}

export function AutonomyAssetQualificationPanel({ chinese }: { chinese: boolean }) {
  const { registerExternalAsset, bindQualifiedAssetPair } = useAutonomyWorkspace();
  const [versions, setVersions] = useState<AgentCoreAssetVersion[]>([]);
  const [jobs, setJobs] = useState<AgentCoreAssetQualificationJob[]>([]);
  const [mapHash, setMapHash] = useState("");
  const [vehicleHash, setVehicleHash] = useState("");
  const [activeJobId, setActiveJobId] = useState<string | null>(null);
  const [working, setWorking] = useState(false);
  const [state, setState] = useState<"loading" | "ready" | "unavailable">("loading");
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    const bootstrap = await getAgentCoreBootstrap();
    const nextVersions = bootstrap.asset_versions.filter((version) => (
      QUALIFICATION_INPUT_MATURITY.has(version.maturity)
    ));
    setVersions(nextVersions);
    setJobs(bootstrap.asset_qualification_jobs);
    setMapHash((current) => current || nextVersions.find((version) => (
      version.kind === "map" || version.kind === "world"
    ))?.content_sha256 || "");
    setVehicleHash((current) => current || nextVersions.find((version) => (
      version.kind === "vehicle"
    ))?.content_sha256 || "");
    setActiveJobId((current) => current || bootstrap.asset_qualification_jobs.find((job) => (
      !["qualified", "failed", "cancelled"].includes(job.state)
    ))?.job_id || bootstrap.asset_qualification_jobs[0]?.job_id || null);
    bootstrap.asset_versions
      .filter((version) => version.maturity === "qualified")
      .forEach((version) => registerExternalAsset(
        version,
        qualificationIdForAssetVersion(version, bootstrap.asset_qualification_jobs),
      ));
    setState("ready");
  }, [registerExternalAsset]);

  useEffect(() => {
    let active = true;
    void refresh().catch(() => {
      if (active) setState("unavailable");
    });
    return () => { active = false; };
  }, [refresh]);

  const activeJob = jobs.find((job) => job.job_id === activeJobId) ?? null;
  useEffect(() => {
    if (!activeJob || !["preparing", "running", "validating"].includes(activeJob.state)) return undefined;
    let active = true;
    const timer = window.setInterval(() => {
      void getAgentCoreAssetQualificationJob(activeJob.job_id).then((next) => {
        if (!active) return;
        setJobs((current) => [next, ...current.filter((job) => job.job_id !== next.job_id)]);
        if (next.state === "qualified") void refresh();
      }).catch(() => {
        if (active) setError(chinese ? "无法读取认证进度。" : "Qualification progress is unavailable.");
      });
    }, 1_500);
    return () => {
      active = false;
      window.clearInterval(timer);
    };
  }, [activeJob, chinese, refresh]);

  const mapVersions = versions.filter((version) => version.kind === "map" || version.kind === "world");
  const vehicleVersions = versions.filter((version) => version.kind === "vehicle");
  const selectedMap = mapVersions.find((version) => version.content_sha256 === mapHash) ?? null;
  const selectedVehicle = vehicleVersions.find((version) => version.content_sha256 === vehicleHash) ?? null;
  const qualifiedMap = activeJob?.state === "qualified"
    ? mapVersions.find((version) => (
      version.asset_id === activeJob.map_asset_id
      && version.content_sha256 === activeJob.result_map_content_sha256
    )) ?? null
    : null;
  const qualifiedVehicle = activeJob?.state === "qualified"
    ? vehicleVersions.find((version) => (
      version.asset_id === activeJob.vehicle_asset_id
      && version.content_sha256 === activeJob.result_vehicle_content_sha256
    )) ?? null
    : null;
  const qualifiedPairBindable = Boolean(
    activeJob?.qualification_id
    && qualifiedMap?.maturity === "qualified"
    && qualifiedVehicle?.maturity === "qualified",
  );

  const updateJob = (next: AgentCoreAssetQualificationJob) => {
    setJobs((current) => [next, ...current.filter((job) => job.job_id !== next.job_id)]);
    setActiveJobId(next.job_id);
  };
  const createAndStart = async () => {
    if (!selectedMap || !selectedVehicle) return;
    setWorking(true);
    setError(null);
    try {
      const created = await createAgentCoreAssetQualificationJob({
        map_asset_id: selectedMap.asset_id,
        map_content_sha256: selectedMap.content_sha256,
        vehicle_asset_id: selectedVehicle.asset_id,
        vehicle_content_sha256: selectedVehicle.content_sha256,
      });
      updateJob(await startAgentCoreAssetQualificationJob(created.job_id));
    } catch (reason) {
      setError(localizedAutonomyError(reason, chinese, {
        zh: "无法启动成对认证。",
        en: "Pair qualification could not start.",
      }));
    } finally {
      setWorking(false);
    }
  };
  const bindActiveQualifiedPair = async () => {
    if (!activeJob || !qualifiedMap || !qualifiedVehicle) return;
    setWorking(true);
    setError(null);
    try {
      const evidence = await getAgentCoreAssetQualificationEvidence(activeJob.job_id);
      const evidenceMatches = evidence.job_id === activeJob.job_id
        && evidence.qualification_id === activeJob.qualification_id
        && evidence.map_asset_id === qualifiedMap.asset_id
        && evidence.map_content_sha256 === qualifiedMap.content_sha256
        && evidence.vehicle_asset_id === qualifiedVehicle.asset_id
        && evidence.vehicle_content_sha256 === qualifiedVehicle.content_sha256;
      const bound = evidenceMatches && bindQualifiedAssetPair(
        activeJob,
        qualifiedMap,
        qualifiedVehicle,
        evidence.runtime_contracts,
      );
      if (!bound) {
        setError(chinese
          ? "认证证据、运行契约与资产版本不一致，无法绑定。请重新认证这一对资产。"
          : "Qualification evidence, runtime contracts, and asset versions do not match. Qualify the pair again.");
      }
    } catch (reason) {
      setError(localizedAutonomyError(reason, chinese, {
        zh: "无法读取并绑定认证运行契约。",
        en: "The qualified runtime contracts could not be loaded and bound.",
      }));
    } finally {
      setWorking(false);
    }
  };
  const runAction = async (
    action: (jobId: string) => Promise<AgentCoreAssetQualificationJob>,
  ) => {
    if (!activeJob) return;
    setWorking(true);
    setError(null);
    try {
      updateJob(await action(activeJob.job_id));
    } catch (reason) {
      setError(localizedAutonomyError(reason, chinese, {
        zh: "认证状态更新失败。",
        en: "Qualification state update failed.",
      }));
    } finally {
      setWorking(false);
    }
  };
  const states: Record<AgentCoreAssetQualificationJob["state"], [string, string]> = {
    created: ["等待开始", "Ready to start"],
    preparing: ["准备仿真资产", "Preparing assets"],
    running: ["PX4 与 Gazebo 正在运行", "PX4 and Gazebo running"],
    validating: ["正在验证证据", "Validating evidence"],
    paused: ["已暂停", "Paused"],
    qualified: ["成对认证完成", "Pair qualified"],
    failed: ["认证失败", "Qualification failed"],
    cancelled: ["已取消", "Cancelled"],
  };
  return (
    <section className="autonomy-config-card autonomy-pair-qualification">
      <header>
        <ShieldCheck aria-hidden="true" />
        <h2>{chinese ? "地图与无人机成对认证" : "Map and aircraft pair qualification"}</h2>
        {activeJob ? <em data-state={activeJob.state}>{states[activeJob.state][chinese ? 0 : 1]}</em> : null}
      </header>
      {state === "loading" ? <span className="autonomy-connector-state">{chinese ? "正在读取可认证资产" : "Loading eligible assets"}</span> : null}
      {state === "unavailable" ? <span className="autonomy-connector-state is-unavailable">{chinese ? "需要桌面端认证" : "Desktop qualification required"}</span> : null}
      {state === "ready" ? <div className="autonomy-pair-selectors">
        <label><span>{chinese ? "地图版本" : "Map version"}</span><select value={mapHash} onChange={(event) => setMapHash(event.target.value)} disabled={working || Boolean(activeJob && !["qualified", "failed", "cancelled"].includes(activeJob.state))}><option value="">{chinese ? "选择地图" : "Choose map"}</option>{mapVersions.map((version) => <option key={version.content_sha256} value={version.content_sha256}>{qualificationAssetLabel(version)}</option>)}</select></label>
        <label><span>{chinese ? "无人机版本" : "Aircraft version"}</span><select value={vehicleHash} onChange={(event) => setVehicleHash(event.target.value)} disabled={working || Boolean(activeJob && !["qualified", "failed", "cancelled"].includes(activeJob.state))}><option value="">{chinese ? "选择无人机" : "Choose aircraft"}</option>{vehicleVersions.map((version) => <option key={version.content_sha256} value={version.content_sha256}>{qualificationAssetLabel(version)}</option>)}</select></label>
      </div> : null}
      {activeJob ? <div className="autonomy-pair-progress">
        <span><i style={{ width: `${activeJob.progress_percent}%` }} /></span>
        <strong>{activeJob.progress_percent}%</strong>
        <small>{activeJob.qualification_id ?? activeJob.job_id}</small>
      </div> : null}
      {activeJob ? <AgentCoreAssetIssueDetails
        jobId={activeJob.job_id}
        kind="qualification"
        chinese={chinese}
        enabled={Boolean(activeJob.issue_codes.length)}
      /> : null}
      {activeJob ? <AgentCoreQualificationEvidenceDetails job={activeJob} chinese={chinese} /> : null}
      {error ? <span className="autonomy-connector-state is-unavailable">{error}</span> : null}
      <footer className="autonomy-pair-actions">
        {activeJob?.state === "qualified" ? <button
          type="button"
          className="btn btn-primary"
          disabled={working || !qualifiedPairBindable || !qualifiedMap || !qualifiedVehicle}
          onClick={() => void bindActiveQualifiedPair()}
        >{chinese ? "绑定这一对资产" : "Bind this qualified pair"}</button> : null}
        {activeJob?.state === "paused" || activeJob?.state === "created" ? <button type="button" className="btn btn-primary" disabled={working} onClick={() => void runAction(startAgentCoreAssetQualificationJob)}>{chinese ? "继续认证" : "Resume qualification"}</button> : null}
        {activeJob && ["preparing", "running", "validating"].includes(activeJob.state) ? <button type="button" className="btn" disabled={working} onClick={() => void runAction(pauseAgentCoreAssetQualificationJob)}>{chinese ? "安全暂停" : "Pause safely"}</button> : null}
        {activeJob && !["qualified", "failed", "cancelled"].includes(activeJob.state) ? <button type="button" className="btn" disabled={working} onClick={() => void runAction(cancelAgentCoreAssetQualificationJob)}>{chinese ? "取消" : "Cancel"}</button> : null}
        {(!activeJob || ["qualified", "failed", "cancelled"].includes(activeJob.state)) ? <button type="button" className="btn btn-primary" disabled={working || !selectedMap || !selectedVehicle || state !== "ready"} onClick={() => void createAndStart()}>{chinese ? "开始真实仿真认证" : "Start real simulation qualification"}</button> : null}
      </footer>
    </section>
  );
}

function AutonomyTemplateIcon({ index }: { index: number }) {
  const Icon = [Route, Camera, Layers3][index] ?? Route;
  return <Icon className="assistant-example-icon" aria-hidden="true" strokeWidth={1.8} />;
}

function AutonomyCloudTerminalIcon() {
  return (
    <svg
      className="assistant-cloud-terminal-icon"
      viewBox="0 0 112 80"
      role="presentation"
      focusable="false"
    >
      <path
        d="M34 65h48c14.4 0 26-10.8 26-24.2 0-12.5-10.2-22.9-23.3-24.1C79.2 7.3 68.5 2 57.2 4.2 43.8 6.8 34.4 17 32.9 29.4 17.7 29.9 5.5 40.2 5.5 47.8 5.5 57.4 18.3 65 34 65Z"
        fill="none"
        stroke="currentColor"
        strokeWidth="6"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <path
        className="assistant-terminal-chevron"
        d="m38 39 10 8-10 8"
        fill="none"
        stroke="currentColor"
        strokeWidth="5.5"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <path
        className="assistant-terminal-underscore"
        d="M55 55h17"
        fill="none"
        stroke="currentColor"
        strokeWidth="5.5"
        strokeLinecap="round"
      />
    </svg>
  );
}

function normalizedAssetReference(value: string): string {
  return value.normalize("NFKC").toLocaleLowerCase().replace(/[^\p{L}\p{N}]+/gu, "");
}

function resolveMissionAssets(
  workspace: AutonomyWorkspaceState,
  assetLibrary: AutonomyAssetLibrary,
  naturalLanguage: string,
): AutonomyWorkspaceState {
  const normalizedIntent = normalizedAssetReference(naturalLanguage);
  const referencedAsset = <T extends { id: string; name: string }>(assets: T[]): T | null => assets
    .map((asset) => ({
      asset,
      references: [asset.name, asset.id]
        .map(normalizedAssetReference)
        .filter((reference) => reference.length >= 4),
    }))
    .filter(({ references }) => references.some((reference) => normalizedIntent.includes(reference)))
    .sort((left, right) => Math.max(...right.references.map((reference) => reference.length))
      - Math.max(...left.references.map((reference) => reference.length)))[0]?.asset ?? null;
  const referencedAircraft = referencedAsset(assetLibrary.aircraft.filter(isAutonomyAircraftAssetQualified));
  const referencedMap = referencedAsset(assetLibrary.maps.filter(autonomyMapPackQualified));
  let aircraft = referencedAircraft ?? workspace.aircraft;
  let mapPack = referencedMap ?? workspace.mapPack;
  if (
    aircraft.qualificationReceiptId
    && mapPack.qualificationReceiptId
    && aircraft.qualificationReceiptId !== mapPack.qualificationReceiptId
  ) {
    if (referencedAircraft && !referencedMap) {
      mapPack = assetLibrary.maps.find((candidate) => (
        autonomyMapPackQualified(candidate)
        && candidate.qualificationReceiptId === referencedAircraft.qualificationReceiptId
      )) ?? mapPack;
    } else if (referencedMap && !referencedAircraft) {
      aircraft = assetLibrary.aircraft.find((candidate) => (
        isAutonomyAircraftAssetQualified(candidate)
        && candidate.qualificationReceiptId === referencedMap.qualificationReceiptId
      )) ?? aircraft;
    }
  }
  if (aircraft.id === workspace.aircraft.id && mapPack.id === workspace.mapPack.id) return workspace;
  const updatedAt = new Date().toISOString();
  return updatedWorkspace(workspace, {
    aircraft,
    mapPack,
    mission: {
      ...workspace.mission,
      aircraftProfileId: aircraft.id,
      mapPackId: mapPack.id,
      compiledPlan: null,
      updatedAt,
    },
  });
}

function AutonomyMissionPlanCard({
  chinese,
  workspace,
}: {
  chinese: boolean;
  workspace: AutonomyWorkspaceState;
}) {
  const plan = workspace.mission.compiledPlan;
  if (!plan) return null;
  const blockingIssues = plan.issues.filter((issue) => issue.severity === "error");
  return (
    <section className="autonomy-inline-plan" aria-live="polite">
      <header>
        <span><Waypoints aria-hidden="true" /></span>
        <div>
          <small>{chinese ? "自动生成的任务计划" : "Generated mission plan"}</small>
          <h3>{workspace.mission.intent}</h3>
        </div>
        <em className={plan.canExecute ? "is-ready" : "is-blocked"}>
          {plan.canExecute ? (chinese ? "可进入仿真" : "Simulation ready") : (chinese ? "需要处理" : "Action required")}
        </em>
      </header>
      <div className="autonomy-inline-plan-bindings">
        <span><Navigation2 aria-hidden="true" /><small>{chinese ? "无人机" : "Aircraft"}</small><strong>{workspace.aircraft.name} · v{workspace.aircraft.version}</strong></span>
        <span><Layers3 aria-hidden="true" /><small>{chinese ? "地图" : "Map"}</small><strong>{workspace.mapPack.name}</strong></span>
          <span><Radar aria-hidden="true" /><small>{chinese ? "感知" : "Perception"}</small><strong>{chinese ? ({ map: "地图", vision: "视觉", fusion: "融合" } as const)[plan.perceptionMode] : plan.perceptionMode}</strong></span>
        <span><Route aria-hidden="true" /><small>{chinese ? "路线" : "Route"}</small><strong>{plan.metrics.routeLengthM.toFixed(1)} m · {Math.ceil(plan.metrics.estimatedDurationS)} s</strong></span>
      </div>
      {blockingIssues.length ? <ul className="autonomy-inline-plan-issues">{blockingIssues.map((issue) => <li key={issue.code}><ShieldCheck aria-hidden="true" /><span>{localizedPlanIssue(issue, chinese)}</span></li>)}</ul> : null}
      <details className="autonomy-task-graph" open>
        <summary>
          <span>{chinese ? "执行任务树" : "Execution task graph"}</span>
          <small>{plan.taskGraph.nodes.length} {chinese ? "个可审计节点" : "auditable nodes"}</small>
        </summary>
        <ol>
          {plan.taskGraph.nodes.map((node, index) => <li key={node.task_id} data-risk={node.risk}>
            <i>{String(index + 1).padStart(2, "0")}</i>
            <div>
              <strong>{localizedTaskNodeLabel(node, index, chinese)}</strong>
            <span>{localizedStructuredTerm(node.executor, chinese)} · {chinese ? ({ low: "低风险", medium: "中风险", high: "高风险", critical: "严重风险" } as const)[node.risk] : node.risk} · {node.timeout_s}s · {chinese ? "失败后" : "Fallback"} {localizedStructuredTerm(node.fallback, chinese)}</span>
              <small>{chinese ? "证据" : "Evidence"}: {node.completion_evidence.join(" · ")}</small>
            </div>
          </li>)}
        </ol>
      </details>
      <footer>
        <span>{plan.source === "backend"
          ? (chinese ? "后端合同" : "Backend contract")
          : plan.source === "agent-core"
            ? (chinese ? "AGENT Core 哈希绑定合同" : "AGENT Core hash-bound contract")
            : (chinese ? "本地安全预览" : "Local safety preview")} · {plan.contractId}</span>
        <div>
          <Link className="btn" to="/autonomy/aircraft">{chinese ? "无人机" : "Aircraft"}</Link>
          <Link className="btn" to="/autonomy/maps">{chinese ? "地图" : "Maps"}</Link>
          {plan.canExecute ? <Link className="btn btn-primary" to="/autonomy/live"><Airplay aria-hidden="true" />{chinese ? "进入仿真" : "Open simulation"}</Link> : null}
        </div>
      </footer>
    </section>
  );
}

export function AutonomyPlatform() {
  const auth = useOptionalAuth();
  const theme = useEditionTheme();
  const location = useLocation();
  const { interfaceLocale } = useI18n();
  const chinese = interfaceLocale === "zh-CN";
  const copy = chinese ? SECTION_COPY.zh : SECTION_COPY.en;
  const ownerId = auth?.account?.id ?? "local";
  const edition = theme.id;
  const [workspace, setWorkspace] = useState(() => loadAutonomyWorkspace(ownerId, edition));
  const [assetLibrary, setAssetLibrary] = useState(() => {
    const current = loadAutonomyWorkspace(ownerId, edition);
    return loadAutonomyAssetLibrary(ownerId, edition, current);
  });
  const [missionComposerDraft, setMissionComposerDraft] = useState("");
  const [agentCorePlugins, setAgentCorePlugins] = useState<AgentCorePluginEntry[]>([]);
  const [agentCoreHealth, setAgentCoreHealth] = useState<"browser" | "checking" | "ready" | "unavailable">(
    publicDemoConsole ? "browser" : "checking",
  );
  const [agentCoreRestarting, setAgentCoreRestarting] = useState(false);
  useEffect(() => {
    const next = loadAutonomyWorkspace(ownerId, edition);
    setWorkspace(next);
    setAssetLibrary(loadAutonomyAssetLibrary(ownerId, edition, next));
    setMissionComposerDraft("");
  }, [edition, ownerId]);

  useEffect(() => {
    if (publicDemoConsole) {
      setAgentCoreHealth("browser");
      return undefined;
    }
    let active = true;
    setAgentCoreHealth("checking");
    void getAgentCoreStatus().then((status) => {
      if (active) setAgentCoreHealth(status.available ? "ready" : "unavailable");
    }).catch(() => {
      if (active) setAgentCoreHealth("unavailable");
    });
    return () => {
      active = false;
    };
  }, []);

  useEffect(() => {
    let active = true;
    void getAgentCoreBootstrap().then((bootstrap) => {
      if (active) setAgentCorePlugins(bootstrap.plugins);
    }).catch(() => {
      if (active) setAgentCorePlugins([]);
    });
    return () => {
      active = false;
    };
  }, [edition, location.pathname]);

  const retryAgentCore = useCallback(async () => {
    setAgentCoreRestarting(true);
    try {
      const status = await restartAgentCore();
      setAgentCoreHealth(status.available ? "ready" : "unavailable");
      if (status.available) {
        const bootstrap = await getAgentCoreBootstrap();
        setAgentCorePlugins(bootstrap.plugins);
      }
    } catch {
      setAgentCoreHealth("unavailable");
    } finally {
      setAgentCoreRestarting(false);
    }
  }, []);

  const persist = useCallback((next: AutonomyWorkspaceState) => {
    const saved = saveAutonomyWorkspace(ownerId, edition, next);
    setWorkspace(saved);
    setAssetLibrary((current) => saveAutonomyAssetLibrary(
      ownerId,
      edition,
      withCurrentAutonomyAssets(current, saved),
    ));
  }, [edition, ownerId]);

  const registerExternalAsset = useCallback((
    version: AgentCoreAssetVersion,
    qualificationId: string | null = null,
  ) => {
    const reference = externalAssetReferenceFromVersion(version, qualificationId);
    setAssetLibrary((current) => saveAutonomyAssetLibrary(
      ownerId,
      edition,
      withExternalAutonomyAsset(current, reference),
    ));
    return reference;
  }, [edition, ownerId]);

  const bindQualifiedAssetPair = useCallback((
    job: AgentCoreAssetQualificationJob,
    mapVersion: AgentCoreAssetVersion,
    vehicleVersion: AgentCoreAssetVersion,
    runtimeContracts: AgentCoreAssetPairRuntimeContracts,
  ) => {
    const qualificationId = job.qualification_id;
    const valid = job.state === "qualified"
      && Boolean(qualificationId)
      && (mapVersion.kind === "map" || mapVersion.kind === "world")
      && vehicleVersion.kind === "vehicle"
      && mapVersion.maturity === "qualified"
      && vehicleVersion.maturity === "qualified"
      && job.map_asset_id === mapVersion.asset_id
      && job.vehicle_asset_id === vehicleVersion.asset_id
      && job.result_map_content_sha256 === mapVersion.content_sha256
      && job.result_vehicle_content_sha256 === vehicleVersion.content_sha256
      && runtimeContracts.schema_version === "dronedream.asset-pair-runtime-contracts.v1"
      && runtimeContracts.map.asset_id === mapVersion.asset_id
      && runtimeContracts.map.content_sha256 === mapVersion.content_sha256
      && runtimeContracts.map.coordinate_frame === "ENU"
      && runtimeContracts.vehicle.asset_id === vehicleVersion.asset_id
      && runtimeContracts.vehicle.content_sha256 === vehicleVersion.content_sha256
      && runtimeContracts.vehicle.coordinate_frame === "base_link_frd";
    if (!valid || !qualificationId) return false;

    const mapAsset = externalAssetReferenceFromVersion(mapVersion, qualificationId);
    const vehicleAsset = externalAssetReferenceFromVersion(vehicleVersion, qualificationId);
    const runtimeVehicle = runtimeContracts.vehicle;
    const runtimeMap = runtimeContracts.map;
    const knownSensor = (sensor: string): AutonomyWorkspaceState["aircraft"]["sensors"][number] | null => {
      const normalized = sensor.trim().toLowerCase().replaceAll("-", "_");
      if (["rgb", "camera", "rgb_camera", "color_camera"].includes(normalized)) return "rgb";
      if (["depth", "depth_camera", "rgbd"].includes(normalized)) return "depth";
      if (normalized.includes("stereo")) return "stereo";
      if (normalized.includes("thermal")) return "thermal";
      if (normalized.includes("lidar")) return "lidar";
      if (["gps", "gnss"].includes(normalized)) return "gps";
      if (["vio", "visual_inertial_odometry"].includes(normalized)) return "vio";
      return null;
    };
    const runtimeSensors = [...new Set(runtimeVehicle.sensors.map(knownSensor).filter((sensor): sensor is NonNullable<typeof sensor> => Boolean(sensor)))];
    const vehicleRuntimeContract: NonNullable<AutonomyWorkspaceState["aircraft"]["agentCoreRuntimeContract"]> = {
      schemaVersion: 1,
      assetId: runtimeVehicle.asset_id,
      contentSha256: runtimeVehicle.content_sha256,
      coordinateFrame: runtimeVehicle.coordinate_frame,
      dryMassKg: runtimeVehicle.dry_mass_kg,
      maximumTakeoffMassKg: runtimeVehicle.max_takeoff_mass_kg,
      bodyRadiusM: runtimeVehicle.body_radius_m,
      bodyHeightM: runtimeVehicle.body_height_m,
      maximumSpeedMps: runtimeVehicle.max_speed_mps,
      maximumAccelerationMps2: runtimeVehicle.max_acceleration_mps2,
      qualifiedRangeM: runtimeVehicle.qualified_range_m,
      reserveBatteryPercent: runtimeVehicle.reserve_battery_percent,
      maximumPickupPayloadKg: runtimeVehicle.max_pickup_payload_kg,
      sensors: runtimeVehicle.sensors,
      vehicleClass: runtimeVehicle.vehicle_class,
      simulationTargets: runtimeVehicle.simulation_targets.map((target) => ({
        targetId: target.target_id,
        simulator: target.simulator,
        simulatorVersion: target.simulator_version,
        rosDistribution: target.ros_distribution,
        autopilot: target.autopilot,
        entrypoint: target.entrypoint,
      })),
    };
    const mapRuntimeContract: NonNullable<AutonomyWorkspaceState["mapPack"]["agentCoreRuntimeContract"]> = {
      schemaVersion: 1,
      assetId: runtimeMap.asset_id,
      contentSha256: runtimeMap.content_sha256,
      coordinateFrame: runtimeMap.coordinate_frame,
      nodeCount: runtimeMap.node_count,
      edgeCount: runtimeMap.edge_count,
      namedEntityCount: runtimeMap.named_entity_count,
      navigationBoundsM: {
        minimum: runtimeMap.navigation_bounds_m.minimum,
        maximum: runtimeMap.navigation_bounds_m.maximum,
        span: runtimeMap.navigation_bounds_m.span,
      },
      semanticLayers: runtimeMap.semantic_layers,
      simulationTargets: runtimeMap.simulation_targets.map((target) => ({
        targetId: target.target_id,
        simulator: target.simulator,
        simulatorVersion: target.simulator_version,
        rosDistribution: target.ros_distribution,
        autopilot: target.autopilot,
        entrypoint: target.entrypoint,
      })),
    };
    const updatedAt = new Date().toISOString();
    const existingAircraft = assetLibrary.aircraft.find((candidate) => (
      candidate.agentCoreAssetId === vehicleAsset.id
      && candidate.agentCoreContentSha256 === vehicleAsset.contentSha256
    ));
    const aircraft = existingAircraft ? {
      ...existingAircraft,
      status: "validated-unsigned" as const,
      qualificationReceiptId: qualificationId,
      qualificationContentHash: vehicleAsset.contentSha256,
      agentCoreAssetId: vehicleAsset.id,
      agentCoreContentSha256: vehicleAsset.contentSha256,
      agentCoreRuntimeContract: vehicleRuntimeContract,
      dryMassKg: runtimeVehicle.dry_mass_kg,
      maximumTakeoffMassKg: runtimeVehicle.max_takeoff_mass_kg,
      bodyHeightM: runtimeVehicle.body_height_m,
      reserveBatteryPercent: runtimeVehicle.reserve_battery_percent,
      maximumPickupPayloadKg: runtimeVehicle.max_pickup_payload_kg,
      maximumSpeedMps: runtimeVehicle.max_speed_mps,
      maximumAccelerationMps2: runtimeVehicle.max_acceleration_mps2,
      sensors: runtimeSensors,
      sensorMounts: [],
      updatedAt,
    } : {
      ...defaultAutonomyWorkspace().aircraft,
      id: `imported-${vehicleAsset.id}-${vehicleAsset.contentSha256.slice(0, 10)}`,
      version: 1,
      name: vehicleAsset.name,
      manufacturer: vehicleAsset.sourceApplication,
      status: "validated-unsigned" as const,
      qualificationReceiptId: qualificationId,
      qualificationContentHash: vehicleAsset.contentSha256,
      agentCoreAssetId: vehicleAsset.id,
      agentCoreContentSha256: vehicleAsset.contentSha256,
      agentCoreRuntimeContract: vehicleRuntimeContract,
      airframe: runtimeVehicle.vehicle_class.replaceAll("_", " "),
      dryMassKg: runtimeVehicle.dry_mass_kg,
      maximumTakeoffMassKg: runtimeVehicle.max_takeoff_mass_kg,
      bodyHeightM: runtimeVehicle.body_height_m,
      reserveBatteryPercent: runtimeVehicle.reserve_battery_percent,
      maximumPickupPayloadKg: runtimeVehicle.max_pickup_payload_kg,
      maximumSpeedMps: runtimeVehicle.max_speed_mps,
      maximumAccelerationMps2: runtimeVehicle.max_acceleration_mps2,
      sensors: runtimeSensors,
      sensorMounts: [],
      updatedAt,
    };
    const sourceFile: AutonomyMapPack["sourceFiles"][number] = {
      name: mapAsset.name,
      bytes: 0,
      format: mapAsset.sourceFormat,
      importedAt: mapAsset.importedAt,
      sha256: mapAsset.contentSha256,
      receiptId: qualificationId,
      admission: "admitted",
      parser: mapAsset.sourceApplication,
      layers: ["mesh", "semantic"],
    };
    const existingMap = assetLibrary.maps.find((candidate) => (
      candidate.agentCoreAssetId === mapAsset.id
      && candidate.agentCoreContentSha256 === mapAsset.contentSha256
    ));
    const mapPack = existingMap ? {
      ...existingMap,
      status: "qualified" as const,
      contentHash: mapAsset.contentSha256,
      qualificationReceiptId: qualificationId,
      calibrated: true,
      compilerSceneId: null,
      agentCoreAssetId: mapAsset.id,
      agentCoreContentSha256: mapAsset.contentSha256,
      agentCoreRuntimeContract: mapRuntimeContract,
      coordinateFrame: runtimeMap.coordinate_frame,
      sourceFiles: [
        sourceFile,
        ...existingMap.sourceFiles.filter((file) => file.sha256 !== mapAsset.contentSha256),
      ],
      updatedAt,
    } : {
      ...defaultAutonomyWorkspace().mapPack,
      id: `imported-${mapAsset.id}-${mapAsset.contentSha256.slice(0, 10)}`,
      version: 1,
      name: mapAsset.name,
      status: "qualified" as const,
      contentHash: mapAsset.contentSha256,
      qualificationReceiptId: qualificationId,
      agentCoreAssetId: mapAsset.id,
      agentCoreContentSha256: mapAsset.contentSha256,
      agentCoreRuntimeContract: mapRuntimeContract,
      coordinateFrame: runtimeMap.coordinate_frame,
      calibrated: true,
      compilerSceneId: null,
      sourceFiles: [sourceFile],
      updatedAt,
    };
    const nextWorkspace = normalizeAutonomyWorkspace(updatedWorkspace(workspace, {
      aircraft,
      mapPack,
      mission: {
        ...workspace.mission,
        aircraftProfileId: aircraft.id,
        mapPackId: mapPack.id,
        compiledPlan: null,
        updatedAt,
      },
    }));
    if (!autonomyAssetPairQualified(nextWorkspace)) return false;
    const savedWorkspace = saveAutonomyWorkspace(ownerId, edition, nextWorkspace);
    setWorkspace(savedWorkspace);
    setAssetLibrary((current) => {
      const withPairReferences = withExternalAutonomyAsset(
        withExternalAutonomyAsset(current, mapAsset),
        vehicleAsset,
      );
      return saveAutonomyAssetLibrary(
        ownerId,
        edition,
        withCurrentAutonomyAssets(withPairReferences, savedWorkspace),
      );
    });
    return true;
  }, [assetLibrary.aircraft, assetLibrary.maps, edition, ownerId, workspace]);

  const selectAircraft = useCallback((aircraftId: string) => {
    const aircraft = assetLibrary.aircraft.find((candidate) => candidate.id === aircraftId);
    if (
      !aircraft
      || !isAutonomyAircraftAssetQualified(aircraft)
      || aircraft.qualificationReceiptId !== workspace.mapPack.qualificationReceiptId
      || aircraft.id === workspace.aircraft.id
    ) return;
    const updatedAt = new Date().toISOString();
    persist(updatedWorkspace(workspace, {
      aircraft,
      mission: {
        ...workspace.mission,
        aircraftProfileId: aircraft.id,
        compiledPlan: null,
        updatedAt,
      },
    }));
  }, [assetLibrary.aircraft, persist, workspace]);

  const selectMap = useCallback((mapId: string) => {
    const mapPack = assetLibrary.maps.find((candidate) => candidate.id === mapId);
    if (
      !mapPack
      || !autonomyMapPackQualified(mapPack)
      || mapPack.qualificationReceiptId !== workspace.aircraft.qualificationReceiptId
      || mapPack.id === workspace.mapPack.id
    ) return;
    const updatedAt = new Date().toISOString();
    persist(updatedWorkspace(workspace, {
      mapPack,
      mission: {
        ...workspace.mission,
        mapPackId: mapPack.id,
        compiledPlan: null,
        updatedAt,
      },
    }));
  }, [assetLibrary.maps, persist, workspace]);

  const removeAsset = useCallback((
    kind: "aircraft" | "map" | "external",
    id: string,
    contentSha256: string | null = null,
  ) => {
    if (kind === "external") {
      setAssetLibrary((current) => saveAutonomyAssetLibrary(ownerId, edition, {
        ...current,
        externalAssets: current.externalAssets.filter((asset) => (
          asset.id !== id || (contentSha256 && asset.contentSha256 !== contentSha256)
        )),
      }));
      return;
    }
    const defaults = defaultAutonomyWorkspace();
    const removingCurrent = kind === "aircraft"
      ? workspace.aircraft.id === id
      : workspace.mapPack.id === id;
    const nextWorkspace = removingCurrent
      ? normalizeAutonomyWorkspace(updatedWorkspace(workspace, kind === "aircraft"
        ? {
            aircraft: defaults.aircraft,
            mission: {
              ...workspace.mission,
              aircraftProfileId: defaults.aircraft.id,
              compiledPlan: null,
              updatedAt: new Date().toISOString(),
            },
          }
        : {
            mapPack: defaults.mapPack,
            mission: {
              ...workspace.mission,
              mapPackId: defaults.mapPack.id,
              compiledPlan: null,
              updatedAt: new Date().toISOString(),
            },
          }))
      : workspace;
    const savedWorkspace = removingCurrent
      ? saveAutonomyWorkspace(ownerId, edition, nextWorkspace)
      : workspace;
    if (removingCurrent) setWorkspace(savedWorkspace);
    setAssetLibrary((current) => saveAutonomyAssetLibrary(
      ownerId,
      edition,
      withCurrentAutonomyAssets({
        ...current,
        aircraft: kind === "aircraft"
          ? current.aircraft.filter((asset) => asset.id !== id)
          : current.aircraft,
        maps: kind === "map"
          ? current.maps.filter((asset) => asset.id !== id)
          : current.maps,
      }, savedWorkspace),
    ));
  }, [edition, ownerId, workspace]);

  const sections: Array<{ id: AutonomySectionId; to: string }> = [
    { id: "overview", to: "/autonomy" },
    { id: "aircraft", to: "/autonomy/aircraft" },
    { id: "maps", to: "/autonomy/maps" },
    { id: "plugins", to: "/autonomy/plugins" },
    { id: "live", to: "/autonomy/live" },
  ];
  const currentSectionPath = normalizedAutonomyPath(location.pathname);
  const currentSection = sections.find((section) => section.to === currentSectionPath)?.id ?? "overview";
  const usesSidebarNavigation = edition === "autonomy";
  const healthAlert = agentCoreHealth === "unavailable" ? (
    <div className="agent-core-health-alert" role="alert">
      <ShieldCheck aria-hidden="true" />
      <span>
        {chinese
          ? "AGENT Core 未能启动；规划、插件、资产认证与执行均已安全闭锁。"
          : "AGENT Core could not start; planning, plugins, asset qualification, and execution are safely blocked."}
      </span>
      <button type="button" className="btn" disabled={agentCoreRestarting} onClick={() => void retryAgentCore()}>
        {agentCoreRestarting
          ? (chinese ? "正在重启" : "Restarting")
          : (chinese ? "重启 Core" : "Restart Core")}
      </button>
    </div>
  ) : null;

  return (
    <div className={`autonomy-platform-page${usesSidebarNavigation ? " is-sidebar-routed" : ""}`}>
      {!usesSidebarNavigation ? (
        <header className="autonomy-platform-header">
          <h1>{copy[currentSection]}</h1>
          <nav className="autonomy-section-switch" aria-label={copy.title}>
            {sections.map(({ id, to }) => {
              const Icon = SECTION_ICONS[id];
              const selected = currentSectionPath === to;
              return (
                <NavLink
                  key={id}
                  to={to}
                  end={id === "overview"}
                  className={({ isActive }) => isActive || selected ? "active" : undefined}
                  aria-current={selected ? "page" : undefined}
                >
                  <Icon aria-hidden="true" />
                  <span>{copy[id]}</span>
                </NavLink>
              );
            })}
          </nav>
          {healthAlert}
        </header>
      ) : null}

      <main className="autonomy-platform-content">
        {usesSidebarNavigation ? healthAlert : null}
        <Outlet context={{
          edition,
          chinese,
          workspace,
          assetLibrary,
          persist,
          selectAircraft,
          selectMap,
          registerExternalAsset,
          bindQualifiedAssetPair,
          agentCorePlugins,
          missionComposerDraft,
          setMissionComposerDraft,
          removeAsset,
        } satisfies WorkspaceContext} />
      </main>
    </div>
  );
}

export function AutonomyOverview() {
  const {
    edition,
    chinese,
    workspace,
    assetLibrary,
    selectAircraft,
    selectMap,
    persist,
    agentCorePlugins,
    missionComposerDraft: composer,
    setMissionComposerDraft: setComposer,
  } = useAutonomyWorkspace();
  const auth = useOptionalAuth();
  const {
    settings: modelAccess,
    profiles: modelProfiles,
    activeProfileId,
    selectAccessMode,
    selectManagedModel,
    selectProfile,
  } = useModelAccess();
  const [contextMenuOpen, setContextMenuOpen] = useState(false);
  const [voiceConsentPending, setVoiceConsentPending] = useState(false);
  const [voiceConsentGranted, setVoiceConsentGranted] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [managedModels, setManagedModels] = useState(DEFAULT_MANAGED_MODEL_CATALOG);
  const [managedModelsReady, setManagedModelsReady] = useState(true);
  const [generating, setGenerating] = useState(false);
  const [pendingAttachments, setPendingAttachments] = useState<File[]>([]);
  const [inputProvenance, setInputProvenance] = useState<"text" | "web-speech" | "audio-attachment">("text");
  const contextMenuRef = useRef<HTMLDivElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const audioInputRef = useRef<HTMLInputElement>(null);
  const configuredProfiles = modelProfiles.filter((profile) => (
    profile.apiKey.trim()
    || (profile.agentCoreProfileId && profile.agentCoreSelectionId)
  ));
  const selectedManagedModel = managedModels.find(
    (model) => model.provider === modelAccess.managedProvider
      && model.model === modelAccess.managedModel
      && managedModelAvailableForAssistant(model),
  ) ?? null;
  const selectedCustomProfileId = modelAccess.accessMode === "byok"
    && configuredProfiles.some((profile) => profile.id === activeProfileId)
    ? activeProfileId
    : null;
  const selectedPlanningModel = modelAccess.accessMode === "platform"
    ? selectedManagedModel
      ? { accessMode: "platform" as const, provider: selectedManagedModel.provider, model: selectedManagedModel.model }
      : null
    : selectedCustomProfileId && modelAccess.model.trim()
      ? {
          accessMode: "byok" as const,
          provider: modelAccess.provider,
          model: modelAccess.model.trim(),
          agentCoreProfileId: modelAccess.agentCoreProfileId,
          agentCoreSelectionId: modelAccess.agentCoreSelectionId,
        }
      : null;
  const copy = chinese ? {
    question: "你希望无人机完成什么任务？",
    placeholder: "描述目标、途经点、环境和需要完成的工作…",
    workflow: "自主飞行任务",
    context: "任务上下文",
    aircraft: "当前无人机",
    map: "当前地图",
    selected: "已选择",
    edit: "管理",
    send: "生成任务合同",
    model: "模型",
    addFiles: "添加任务文件",
    removeFile: "移除文件",
    fileLimit: "每个文件不超过 25 MB，一次最多 8 个。",
    invalidFile: "文件必须有效、每个不超过 25 MB，并且一次最多添加 8 个。",
    microphone: "使用语音输入",
    audioAttachment: "添加语音文件",
    voiceDisabled: "语音输入插件已关闭。",
    stopVoice: "停止语音输入",
    requestingVoice: "正在请求麦克风权限…",
    listening: "正在聆听…",
    voiceConsent: "浏览器可能使用语音服务转写麦克风音频；音频不会写入任务合同。",
    startVoice: "允许并开始",
    cancelVoice: "取消",
    voiceUnavailable: "当前环境无法使用语音输入，你仍可继续输入文字。",
    tooLong: "任务描述不能超过 2,000 个字符。",
    modelUnavailable: "请先选择可用于任务规划的模型。",
    modelFallback: "模型推理暂时不可用；系统已使用确定性安全编译器生成可审阅计划。",
    followUpPlaceholder: "继续补充地点、载荷、路线或安全要求…",
    deterministicPlanReply: "我已根据当前绑定的无人机、地图和安全约束生成可审阅的任务计划。你可以继续提出修改，我会在同一对话中更新任务合同与执行任务树。",
    examples: [
      { title: "办公室取物", body: "从办公室起飞，避开走廊和楼梯中的人员，前往取物点，确认载荷后安全返航。" },
      { title: "视觉巡检", body: "沿指定区域自主巡检，使用实时视觉识别目标与动态障碍，并报告每个检查点的进度。" },
      { title: "未知环境探索", body: "只给定起点和终点，边飞行边建立局部地图，规划安全航迹并在环境变化时实时重规划。" },
    ],
  } : {
    question: "What should your drone do?",
    placeholder: "Describe the goal, waypoints, environment, and work to complete…",
    workflow: "Autonomous mission",
    context: "Mission context",
    aircraft: "Current aircraft",
    map: "Current map",
    selected: "Selected",
    edit: "Manage",
    send: "Build mission contract",
    model: "Model",
    addFiles: "Attach mission files",
    removeFile: "Remove file",
    fileLimit: "Up to 8 files, 25 MB each.",
    invalidFile: "Files must be valid, at most 25 MB each, with no more than 8 attached.",
    microphone: "Use voice input",
    audioAttachment: "Attach an audio recording",
    voiceDisabled: "The voice-input plugin is disabled.",
    stopVoice: "Stop voice input",
    requestingVoice: "Requesting microphone access…",
    listening: "Listening…",
    voiceConsent: "Your browser may use a speech service to transcribe microphone audio. Audio is not written to the mission contract.",
    startVoice: "Allow and start",
    cancelVoice: "Cancel",
    voiceUnavailable: "Voice input is unavailable here. You can keep typing.",
    tooLong: "The mission description must stay within 2,000 characters.",
    modelUnavailable: "Choose an available planning model before continuing.",
    modelFallback: "Model reasoning was unavailable; the deterministic safety compiler generated a reviewable plan.",
    followUpPlaceholder: "Add a location, payload, route, or safety requirement…",
    deterministicPlanReply: "I generated a reviewable mission plan from the bound aircraft, map, and safety constraints. Continue with any changes and I will update the mission contract and execution graph in this conversation.",
    examples: [
      { title: "Office pickup", body: "Take off from the office, avoid people in the corridor and stairwell, collect the payload, and return safely." },
      { title: "Visual inspection", body: "Inspect the assigned area with live vision, track dynamic obstacles, and report progress at every checkpoint." },
      { title: "Unknown environment", body: "Use only the start and goal, build a local map in flight, plan a safe route, and replan as the world changes." },
    ],
  };
  const publicWorkspace = defaultAutonomyWorkspace();
  const publicAircraft = publicDemoConsole
    ? assetLibrary.aircraft.find((aircraft) => aircraft.id === publicWorkspace.aircraft.id) ?? publicWorkspace.aircraft
    : workspace.aircraft;
  const publicMap = publicDemoConsole
    ? assetLibrary.maps.find((mapPack) => mapPack.id === publicWorkspace.mapPack.id) ?? publicWorkspace.mapPack
    : workspace.mapPack;
  const appendTranscript = useCallback((transcript: string) => {
    setInputProvenance("web-speech");
    setComposer((current) => {
      const next = current.trim() ? `${current.trim()} ${transcript}` : transcript;
      return next.slice(0, 2_000);
    });
  }, [setComposer]);
  const voice = useVoiceInput({ locale: chinese ? "zh-CN" : "en", onTranscript: appendTranscript });
  const voicePlugins = agentCorePlugins.filter((plugin) => (
    plugin.placement.slot_id === "interaction.voice-input"
  ));
  const activeVoicePlugin = voicePlugins.find((plugin) => plugin.enabled && plugin.health === "healthy") ?? null;
  const voiceMode: "web-speech" | "audio-attachment" | "disabled" = activeVoicePlugin?.plugin_id === "voice.audio-attachment"
    ? "audio-attachment"
    : activeVoicePlugin?.plugin_id === "voice.web-speech" || voicePlugins.length === 0
      ? "web-speech"
      : "disabled";
  const enqueueAttachments = useCallback((files: File[], provenance: "text" | "audio-attachment" = "text") => {
    const valid = files.filter((file) => file.name.trim() && file.size > 0 && file.size <= 25 * 1024 * 1024);
    if (valid.length !== files.length) {
      setError(copy.invalidFile);
      return;
    }
    setPendingAttachments((current) => {
      const merged = [...current];
      for (const file of valid) {
        if (!merged.some((item) => item.name === file.name && item.size === file.size && item.lastModified === file.lastModified)) {
          merged.push(file);
        }
      }
      if (merged.length > 8) {
        setError(copy.invalidFile);
        return current;
      }
      return merged;
    });
    if (provenance === "audio-attachment") setInputProvenance("audio-attachment");
  }, [copy.invalidFile]);
  const conversationActive = workspace.mission.messages.length > 0 || Boolean(workspace.mission.compiledPlan);
  const conversationMessages: AutonomyConversationMessage[] = workspace.mission.messages.length
    ? workspace.mission.messages
    : workspace.mission.compiledPlan
      ? [
          {
            id: "migrated-user-message",
            role: "user",
            content: workspace.mission.intent,
            createdAt: workspace.mission.updatedAt,
            planContractId: null,
          },
          {
            id: "migrated-assistant-message",
            role: "assistant",
            content: workspace.mission.planningBrief || copy.deterministicPlanReply,
            createdAt: workspace.mission.updatedAt,
            planContractId: workspace.mission.compiledPlan.contractId,
          },
        ]
      : [];

  useEffect(() => {
    if (!auth?.account) {
      setManagedModels(DEFAULT_MANAGED_MODEL_CATALOG);
      setManagedModelsReady(true);
      return;
    }
    let active = true;
    setManagedModelsReady(false);
    void getManagedModelCatalog()
      .then((catalog) => {
        if (!active) return;
        setManagedModels(completeManagedModelCatalog(catalog.models));
        setManagedModelsReady(true);
      })
      .catch(() => {
        if (!active) return;
        setManagedModels(DEFAULT_MANAGED_MODEL_CATALOG);
        setManagedModelsReady(true);
      });
    return () => {
      active = false;
    };
  }, [auth?.account]);

  useEffect(() => {
    if (
      modelAccess.accessMode !== "platform"
      || selectedManagedModel
      || !managedModelsReady
    ) return;
    const fallback = managedModels.find(managedModelAvailableForAssistant);
    if (fallback) selectManagedModel(fallback.provider, fallback.model);
  }, [
    managedModels,
    managedModelsReady,
    modelAccess.accessMode,
    selectManagedModel,
    selectedManagedModel,
  ]);

  useEffect(() => {
    if (!contextMenuOpen) return undefined;
    const closeOnOutside = (event: PointerEvent) => {
      if (!contextMenuRef.current?.contains(event.target as Node)) setContextMenuOpen(false);
    };
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") setContextMenuOpen(false);
    };
    document.addEventListener("pointerdown", closeOnOutside);
    document.addEventListener("keydown", closeOnEscape);
    return () => {
      document.removeEventListener("pointerdown", closeOnOutside);
      document.removeEventListener("keydown", closeOnEscape);
    };
  }, [contextMenuOpen]);

  const submitMission = async (event: FormEvent) => {
    event.preventDefault();
    const intent = composer.trim();
    if (!intent) return;
    if (intent.length > 2_000) {
      setError(copy.tooLong);
      return;
    }
    if (!selectedPlanningModel || generating) {
      setError(copy.modelUnavailable);
      return;
    }
    voice.cancel();
    consumeAutonomyHandoff();
    setGenerating(true);
    setError(null);
    try {
      const submittedAttachments = pendingAttachments.slice(0, 8);
      const missionWorkspace = resolveMissionAssets(workspace, assetLibrary, intent);
      const assistantWorkspaceId = missionWorkspace.mission.conversationId ?? createExperimentWorkspaceId();
      const turnId = crypto.randomUUID();
      const followUpPrefix = chinese ? "\n补充指令：" : "\nFollow-up instruction: ";
      const revisedIntent = missionWorkspace.mission.messages.length || missionWorkspace.mission.compiledPlan
        ? `${missionWorkspace.mission.intent.slice(0, Math.max(0, 2_000 - followUpPrefix.length - intent.length))}${followUpPrefix}${intent}`
        : intent;
      const submittedAt = new Date().toISOString();
      const userMessage: AutonomyConversationMessage = {
        id: `user-${turnId}`,
        role: "user",
        content: intent,
        createdAt: submittedAt,
        planContractId: null,
        attachments: submittedAttachments.map((file) => ({
          name: file.name,
          contentType: file.type || "application/octet-stream",
          byteSize: file.size,
        })),
      };
      const priorMessages = missionWorkspace.mission.messages;
      persist(updatedWorkspace(missionWorkspace, {
        mission: {
          ...missionWorkspace.mission,
          intent: revisedIntent,
          conversationId: assistantWorkspaceId,
          messages: [...priorMessages, userMessage].slice(-100),
          aircraftProfileId: missionWorkspace.aircraft.id,
          mapPackId: missionWorkspace.mapPack.id,
          updatedAt: submittedAt,
        },
      }));
      setComposer("");
      const planning = await planAutonomyMission({
        edition,
        workspace: missionWorkspace,
        intent: revisedIntent,
        instruction: intent,
        conversationId: assistantWorkspaceId,
        turnId,
        chinese,
        selectedModel: selectedPlanningModel,
        accountId: auth?.account?.id ?? null,
        publicDemo: publicDemoConsole,
        requestPurpose: "initial_plan",
        attachments: submittedAttachments,
        inputChannel: inputProvenance === "text" ? "text" : "voice",
        transcriptSource: inputProvenance === "text" ? null : inputProvenance,
      });
      setPendingAttachments([]);
      setInputProvenance("text");
      if (!planning.compiledPlan) {
        const updatedAt = new Date().toISOString();
        const assistantMessage: AutonomyConversationMessage = {
          id: `assistant-${turnId}`,
          role: "assistant",
          content: planning.planningBrief,
          createdAt: updatedAt,
          planContractId: null,
        };
        persist(updatedWorkspace(missionWorkspace, {
          mission: {
            ...missionWorkspace.mission,
            intent: revisedIntent,
            planningModel: selectedPlanningModel,
            planningBrief: planning.planningBrief,
            planningRunId: planning.planningRunId,
            conversationId: assistantWorkspaceId,
            messages: [...priorMessages, userMessage, assistantMessage].slice(-100),
            aircraftProfileId: missionWorkspace.aircraft.id,
            mapPackId: missionWorkspace.mapPack.id,
            compiledPlan: null,
            currentStep: 0,
            updatedAt,
          },
        }));
        return;
      }
      const updatedAt = new Date().toISOString();
      const assistantMessage: AutonomyConversationMessage = {
        id: `assistant-${turnId}`,
        role: "assistant",
        content: planning.planningBrief || copy.deterministicPlanReply,
        createdAt: updatedAt,
        planContractId: planning.compiledPlan.contractId,
      };
      persist(updatedWorkspace(missionWorkspace, {
        mission: {
          ...missionWorkspace.mission,
          intent: revisedIntent,
          planningModel: selectedPlanningModel,
          planningBrief: planning.planningBrief,
          planningRunId: planning.planningRunId,
          conversationId: assistantWorkspaceId,
          messages: [...priorMessages, userMessage, assistantMessage].slice(-100),
          aircraftProfileId: missionWorkspace.aircraft.id,
          mapPackId: missionWorkspace.mapPack.id,
          compiledPlan: planning.compiledPlan,
          currentStep: 0,
          updatedAt,
        },
      }));
    } catch (reason) {
      setError(localizedAutonomyError(reason, chinese, {
        zh: "请检查规划模型、任务资产与运行环境后重试。",
        en: "Check the planning model, mission assets, and runtime before trying again.",
      }));
    } finally {
      setGenerating(false);
    }
  };

  const voiceStatus = voice.state === "requesting"
    ? copy.requestingVoice
    : voice.state === "listening"
      ? copy.listening
      : voice.error
        ? copy.voiceUnavailable
        : null;

  return (
    <section className={`autonomy-command-page ${conversationActive ? "is-conversation" : ""}`} data-grants-hardware-authority="false">
      <div className={`autonomy-command-stage ${conversationActive ? "is-conversation" : ""}`}>
        {conversationActive ? (
          <div className="autonomy-conversation-scroll">
            <div className="autonomy-conversation-thread" aria-live="polite">
              {conversationMessages.map((message) => (
                <article className={`autonomy-conversation-message is-${message.role}`} key={message.id}>
                  {message.role === "assistant" ? (
                    <span className="autonomy-conversation-avatar" aria-hidden="true"><Sparkles /></span>
                  ) : null}
                  <div className="autonomy-conversation-body">
                    <p>{message.role === "assistant"
                      ? localizedAutonomyError(message.content, chinese, {
                          zh: "任务计划已更新，请查看下方的结构化计划。",
                          en: "The mission plan has been updated. Review the structured plan below.",
                        })
                      : message.content}</p>
                    {message.attachments?.length ? (
                      <div className="autonomy-message-attachments">
                        {message.attachments.map((attachment) => (
                          <span key={`${message.id}:${attachment.name}:${attachment.byteSize}`}>
                            <Paperclip aria-hidden="true" />
                            {attachment.name}
                          </span>
                        ))}
                      </div>
                    ) : null}
                    {message.role === "assistant"
                      && workspace.mission.compiledPlan
                      && message.planContractId === workspace.mission.compiledPlan.contractId
                      ? <AutonomyMissionPlanCard chinese={chinese} workspace={workspace} />
                      : null}
                  </div>
                  {message.role === "user" ? (
                    <span className="autonomy-conversation-avatar is-user-account" aria-label={auth?.account?.displayName ?? (chinese ? "本地用户" : "Local user")}>
                      {auth?.account?.avatarUrl ? (
                        <img src={auth.account.avatarUrl} alt="" />
                      ) : auth?.account?.displayName ? (
                        auth.account.displayName.slice(0, 1).toLocaleUpperCase()
                      ) : (
                        <CircleUserRound aria-hidden="true" />
                      )}
                    </span>
                  ) : null}
                </article>
              ))}
              {generating ? (
                <article className="autonomy-conversation-message is-assistant is-generating" aria-label={chinese ? "正在生成任务计划" : "Generating mission plan"}>
                  <span className="autonomy-conversation-avatar" aria-hidden="true"><Sparkles /></span>
                  <div className="autonomy-conversation-thinking"><i /><i /><i /></div>
                </article>
              ) : null}
            </div>
          </div>
        ) : (
          <>
            <div className="assistant-hero-icon autonomy-command-hero-icon" aria-hidden="true">
              <AutonomyCloudTerminalIcon />
            </div>
            <h2>{copy.question}</h2>
            <div className="assistant-examples autonomy-command-examples">
              {copy.examples.map((example, index) => (
                <button
                  type="button"
                  key={example.title}
                  aria-label={example.title}
                  onClick={() => setComposer(example.body)}
                >
                  <span className="assistant-example-heading">
                    <AutonomyTemplateIcon index={index} />
                    <span>
                      <strong>{example.title}</strong>
                      <small>{example.body}</small>
                    </span>
                  </span>
                </button>
              ))}
            </div>
          </>
        )}
        <form className="assistant-composer autonomy-command-composer" onSubmit={submitMission}>
          <textarea
            value={composer}
            maxLength={2_000}
            rows={conversationActive ? 2 : 3}
            placeholder={conversationActive ? copy.followUpPlaceholder : copy.placeholder}
            aria-label={conversationActive ? copy.followUpPlaceholder : copy.placeholder}
            onChange={(event) => {
              setComposer(event.target.value);
              setError(null);
            }}
            onKeyDown={(event) => {
              if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
                event.preventDefault();
                event.currentTarget.form?.requestSubmit();
              }
            }}
          />
          <input
            ref={fileInputRef}
            type="file"
            multiple
            hidden
            onChange={(event) => {
              enqueueAttachments(Array.from(event.currentTarget.files ?? []));
              event.currentTarget.value = "";
            }}
          />
          <input
            ref={audioInputRef}
            type="file"
            accept="audio/*,.wav,.mp3,.m4a,.flac,.ogg,.opus,.aac"
            hidden
            onChange={(event) => {
              enqueueAttachments(Array.from(event.currentTarget.files ?? []), "audio-attachment");
              event.currentTarget.value = "";
            }}
          />
          {pendingAttachments.length ? (
            <div className="autonomy-pending-attachments" aria-label={copy.addFiles}>
              {pendingAttachments.map((file) => (
                <span key={`${file.name}:${file.size}:${file.lastModified}`}>
                  <Paperclip aria-hidden="true" />
                  <b>{file.name}</b>
                  <small>{Math.max(1, Math.ceil(file.size / 1024))} KB</small>
                  <button
                    type="button"
                    aria-label={`${copy.removeFile}: ${file.name}`}
                    title={`${copy.removeFile}: ${file.name}`}
                    onClick={() => {
                      const next = pendingAttachments.filter((item) => item !== file);
                      setPendingAttachments(next);
                      if (
                        inputProvenance === "audio-attachment"
                        && !next.some((item) => item.type.startsWith("audio/"))
                      ) setInputProvenance("text");
                    }}
                  >×</button>
                </span>
              ))}
            </div>
          ) : null}
          <div className="assistant-composer-bar">
            <div className="assistant-add-menu" ref={contextMenuRef}>
              <button
                type="button"
                className="assistant-add-button"
                aria-label={copy.context}
                title={copy.context}
                aria-haspopup="dialog"
                aria-expanded={contextMenuOpen}
                onClick={() => setContextMenuOpen((current) => !current)}
              >
                <Plus aria-hidden="true" strokeWidth={1.8} />
              </button>
              {contextMenuOpen ? (
                <div className="assistant-add-popover autonomy-context-popover" role="dialog" aria-label={copy.context}>
                  <strong className="assistant-task-popover-title">{copy.context}</strong>
                  {edition === "autonomy" ? (
                    <button
                      type="button"
                      className="autonomy-context-file-action"
                      onClick={() => {
                        setContextMenuOpen(false);
                        fileInputRef.current?.click();
                      }}
                    >
                      <Paperclip aria-hidden="true" />
                      <span><b>{copy.addFiles}</b><small>{copy.fileLimit}</small></span>
                    </button>
                  ) : null}
                  <section className="autonomy-context-group" aria-label={copy.aircraft}>
                    <header><span><Navigation2 aria-hidden="true" />{copy.aircraft}</span><Link to="/autonomy/aircraft" onClick={() => setContextMenuOpen(false)}>{copy.edit}</Link></header>
                    {[publicAircraft].map((aircraft) => <label className="autonomy-context-asset" key={aircraft.id}>
                      <input type="radio" name="autonomy-aircraft" value={aircraft.id} disabled={!isAutonomyAircraftAssetQualified(aircraft)} checked={aircraft.id === workspace.aircraft.id} onChange={() => selectAircraft(aircraft.id)} />
                      <span><b>{aircraft.name}</b><small>{aircraft.airframe} · GPS · {aircraft.controlInterface.toUpperCase()}</small></span>
                      {aircraft.id === workspace.aircraft.id ? <em>{copy.selected}</em> : null}
                    </label>)}
                  </section>
                  <section className="autonomy-context-group" aria-label={copy.map}>
                    <header><span><Layers3 aria-hidden="true" />{copy.map}</span><Link to="/autonomy/maps" onClick={() => setContextMenuOpen(false)}>{copy.edit}</Link></header>
                    {[publicMap].map((mapPack) => <label className="autonomy-context-asset" key={mapPack.id}>
                      <input type="radio" name="autonomy-map" value={mapPack.id} disabled={!autonomyMapPackQualified(mapPack)} checked={mapPack.id === workspace.mapPack.id} onChange={() => selectMap(mapPack.id)} />
                      <span><b>{mapPack.name}</b><small>{mapRepresentationLabel(mapPack.representation, chinese)} · {mapPack.coordinateFrame}</small></span>
                      {mapPack.id === workspace.mapPack.id ? <em>{copy.selected}</em> : null}
                    </label>)}
                  </section>
                </div>
              ) : null}
            </div>
            <span className="assistant-task-chip is-explicit"><Route aria-hidden="true" />{copy.workflow}</span>
            <span className="assistant-composer-spacer" />
            <AssistantModelPicker
              ariaLabel={copy.model}
              chooseModelLabel={chinese ? "选择模型" : "Choose model"}
              defaultGroupLabel={chinese ? "默认" : "Default"}
              customGroupLabel={chinese ? "自定义" : "Custom"}
              addCustomModelLabel={chinese ? "添加自定义模型" : "Add custom model"}
              temporarilyUnavailableLabel={chinese ? "暂时不可用" : "Temporarily unavailable"}
              defaultModels={managedModels}
              customProfiles={configuredProfiles}
              selectedDefault={modelAccess.accessMode === "platform" ? selectedManagedModel : null}
              selectedCustomId={selectedCustomProfileId}
              disabled={!managedModelsReady}
              onSelectDefault={(model) => {
                selectAccessMode("platform");
                selectManagedModel(model.provider, model.model);
              }}
              onSelectCustom={(profileId) => {
                selectProfile(profileId);
                selectAccessMode("byok");
              }}
              onOpenSettings={() => openAppSettings("model")}
            />
            <button
              type="button"
              className={`assistant-voice-button ${voice.state === "listening" ? "listening" : ""}`}
              aria-label={voice.state === "listening" ? copy.stopVoice : voiceMode === "audio-attachment" ? copy.audioAttachment : copy.microphone}
              title={voice.state === "listening" ? copy.stopVoice : voiceMode === "audio-attachment" ? copy.audioAttachment : copy.microphone}
              onClick={() => {
                if (voiceMode === "disabled") {
                  setError(copy.voiceDisabled);
                  return;
                }
                if (voiceMode === "audio-attachment") {
                  audioInputRef.current?.click();
                  return;
                }
                if (voice.state === "listening") {
                  voice.stop();
                  return;
                }
                if (!voice.supported) {
                  void voice.start();
                  return;
                }
                if (!voiceConsentGranted) {
                  setVoiceConsentPending(true);
                  return;
                }
                void voice.start();
              }}
            >
              <Mic aria-hidden="true" strokeWidth={1.9} />
            </button>
            <button
              type="submit"
              className="assistant-send-button"
              disabled={!composer.trim() || !managedModelsReady || !selectedPlanningModel || generating}
              aria-label={copy.send}
              title={copy.send}
            >
              <ArrowUp aria-hidden="true" strokeWidth={2} />
            </button>
          </div>
          {voiceConsentPending ? (
            <div className="assistant-voice-consent" role="note">
              <p>{copy.voiceConsent}</p>
              <button type="button" className="btn btn-primary" onClick={() => {
                setVoiceConsentPending(false);
                setVoiceConsentGranted(true);
                void voice.start();
              }}>{copy.startVoice}</button>
              <button type="button" className="btn" onClick={() => setVoiceConsentPending(false)}>{copy.cancelVoice}</button>
            </div>
          ) : null}
          {voiceStatus ? <p className="assistant-composer-status">{voiceStatus}</p> : null}
          {error ? <p className="assistant-composer-error" role="alert">{error}</p> : null}
        </form>
      </div>
    </section>
  );
}

const MAP_REPRESENTATION_LABELS: Record<AutonomyMapPack["representation"], { zh: string; en: string }> = {
  "hybrid-3d": { zh: "混合三维", en: "Hybrid 3D" },
  mesh: { zh: "网格", en: "Mesh" },
  "point-cloud": { zh: "点云", en: "Point cloud" },
  occupancy: { zh: "占据栅格 / ESDF", en: "Occupancy / ESDF" },
  terrain: { zh: "地形 / DEM", en: "Terrain / DEM" },
};

function mapRepresentationLabel(value: AutonomyMapPack["representation"], chinese: boolean): string {
  return chinese ? MAP_REPRESENTATION_LABELS[value].zh : MAP_REPRESENTATION_LABELS[value].en;
}

export function AutonomyAircraft() {
  const { chinese, workspace, assetLibrary, selectAircraft, removeAsset } = useAutonomyWorkspace();
  const [details, setDetails] = useState<{ title: string; rows: Array<[string, string]> } | null>(null);
  const defaultAircraftId = defaultAutonomyWorkspace().aircraft.id;
  const externalAircraft = assetLibrary.externalAssets.filter((asset) => asset.kind === "vehicle");
  const openAircraftDetails = (aircraft: AutonomyWorkspaceState["aircraft"]) => setDetails({
    title: aircraft.name,
    rows: [
      [chinese ? "制造商" : "Manufacturer", aircraft.manufacturer || "—"],
      [chinese ? "机架" : "Airframe", aircraft.airframe || "—"],
      [chinese ? "飞控" : "Flight controller", aircraft.flightController || "—"],
      [chinese ? "版本" : "Version", `v${aircraft.version}`],
      [chinese ? "传感器" : "Sensors", aircraft.sensors.join(" · ") || "—"],
    ],
  });

  return (
    <section className="autonomy-repository-page">
      <div className="autonomy-repository-toolbar">
        <p>{chinese ? "双击卡片查看详情" : "Double-click a card for details"}</p>
        <AutonomyAssetConnectorPanel kind="vehicle" chinese={chinese} compact />
      </div>
      <div className="autonomy-repository-grid" aria-label={chinese ? "无人机仓库" : "Aircraft repository"}>
        {assetLibrary.aircraft.map((aircraft) => (
          <article key={aircraft.id} data-selected={workspace.aircraft.id === aircraft.id}>
            <button
              type="button"
              className="autonomy-repository-card-surface"
              onClick={() => selectAircraft(aircraft.id)}
              onDoubleClick={() => openAircraftDetails(aircraft)}
            >
              <span className="autonomy-repository-preview is-aircraft"><Navigation2 aria-hidden="true" /></span>
              <span className="autonomy-repository-copy">
                <strong>{aircraft.name}</strong>
                <small>{[aircraft.manufacturer, aircraft.airframe].filter(Boolean).join(" · ")}</small>
              </span>
            </button>
            {aircraft.id !== defaultAircraftId ? (
              <button
                type="button"
                className="autonomy-repository-delete"
                aria-label={chinese ? `删除 ${aircraft.name}` : `Delete ${aircraft.name}`}
                onClick={() => removeAsset("aircraft", aircraft.id)}
              ><Trash2 aria-hidden="true" /></button>
            ) : null}
          </article>
        ))}
        {externalAircraft.map((asset) => (
          <article key={`${asset.id}:${asset.contentSha256}`}>
            <button
              type="button"
              className="autonomy-repository-card-surface"
              onDoubleClick={() => setDetails({
                title: asset.name,
                rows: [
                  [chinese ? "来源" : "Source", asset.sourceApplication || "—"],
                  [chinese ? "格式" : "Format", asset.sourceFormat.toUpperCase()],
                  [chinese ? "版本" : "Version", asset.version || "—"],
                  [chinese ? "状态" : "Status", asset.maturity.replaceAll("_", " ")],
                ],
              })}
            >
              <span className="autonomy-repository-preview is-aircraft is-imported"><Navigation2 aria-hidden="true" /></span>
              <span className="autonomy-repository-copy"><strong>{asset.name}</strong><small>{asset.sourceApplication || asset.sourceFormat}</small></span>
            </button>
            <button type="button" className="autonomy-repository-delete" aria-label={chinese ? `删除 ${asset.name}` : `Delete ${asset.name}`} onClick={() => removeAsset("external", asset.id, asset.contentSha256)}><Trash2 aria-hidden="true" /></button>
          </article>
        ))}
      </div>
      {details ? <RepositoryDetailsDialog chinese={chinese} details={details} onClose={() => setDetails(null)} /> : null}
    </section>
  );
}

export function AutonomyMaps() {
  const { chinese, workspace, assetLibrary, selectMap, removeAsset } = useAutonomyWorkspace();
  const [details, setDetails] = useState<{ title: string; rows: Array<[string, string]> } | null>(null);
  const defaultMapId = defaultAutonomyWorkspace().mapPack.id;
  const externalMaps = assetLibrary.externalAssets.filter((asset) => asset.kind === "map" || asset.kind === "world");
  const openMapDetails = (mapPack: AutonomyMapPack) => setDetails({
    title: mapPack.name,
    rows: [
      [chinese ? "类型" : "Type", mapRepresentationLabel(mapPack.representation, chinese)],
      [chinese ? "坐标系" : "Coordinate frame", mapPack.coordinateFrame],
      [chinese ? "分辨率" : "Resolution", `${mapPack.resolutionM} m`],
      [chinese ? "楼层" : "Floors", String(mapPack.floorCount)],
      [chinese ? "版本" : "Version", `v${mapPack.version}`],
    ],
  });

  return (
    <section className="autonomy-repository-page">
      <div className="autonomy-repository-toolbar">
        <p>{chinese ? "双击卡片查看详情" : "Double-click a card for details"}</p>
        <AutonomyAssetConnectorPanel kind="map" chinese={chinese} compact />
      </div>
      <div className="autonomy-repository-grid" aria-label={chinese ? "地图仓库" : "Map repository"}>
        {assetLibrary.maps.map((mapPack) => (
          <article key={mapPack.id} data-selected={workspace.mapPack.id === mapPack.id}>
            <button type="button" className="autonomy-repository-card-surface" onClick={() => selectMap(mapPack.id)} onDoubleClick={() => openMapDetails(mapPack)}>
              <span className="autonomy-repository-preview is-map"><Layers3 aria-hidden="true" /></span>
              <span className="autonomy-repository-copy"><strong>{mapPack.name}</strong><small>{mapRepresentationLabel(mapPack.representation, chinese)} · v{mapPack.version}</small></span>
            </button>
            {mapPack.id !== defaultMapId ? <button type="button" className="autonomy-repository-delete" aria-label={chinese ? `删除 ${mapPack.name}` : `Delete ${mapPack.name}`} onClick={() => removeAsset("map", mapPack.id)}><Trash2 aria-hidden="true" /></button> : null}
          </article>
        ))}
        {externalMaps.map((asset) => (
          <article key={`${asset.id}:${asset.contentSha256}`}>
            <button type="button" className="autonomy-repository-card-surface" onDoubleClick={() => setDetails({ title: asset.name, rows: [[chinese ? "来源" : "Source", asset.sourceApplication || "—"], [chinese ? "格式" : "Format", asset.sourceFormat.toUpperCase()], [chinese ? "版本" : "Version", asset.version || "—"], [chinese ? "状态" : "Status", asset.maturity.replaceAll("_", " ")]] })}>
              <span className="autonomy-repository-preview is-map is-imported"><Layers3 aria-hidden="true" /></span>
              <span className="autonomy-repository-copy"><strong>{asset.name}</strong><small>{asset.sourceApplication || asset.sourceFormat}</small></span>
            </button>
            <button type="button" className="autonomy-repository-delete" aria-label={chinese ? `删除 ${asset.name}` : `Delete ${asset.name}`} onClick={() => removeAsset("external", asset.id, asset.contentSha256)}><Trash2 aria-hidden="true" /></button>
          </article>
        ))}
      </div>
      {details ? <RepositoryDetailsDialog chinese={chinese} details={details} onClose={() => setDetails(null)} /> : null}
    </section>
  );
}

function RepositoryDetailsDialog({
  chinese,
  details,
  onClose,
}: {
  chinese: boolean;
  details: { title: string; rows: Array<[string, string]> };
  onClose: () => void;
}) {
  return (
    <div className="autonomy-repository-dialog-backdrop" role="presentation" onMouseDown={(event) => {
      if (event.target === event.currentTarget) onClose();
    }}>
      <section className="autonomy-repository-dialog" role="dialog" aria-modal="true" aria-label={details.title}>
        <header><h2>{details.title}</h2><button type="button" onClick={onClose} aria-label={chinese ? "关闭" : "Close"}><X aria-hidden="true" /></button></header>
        <dl>{details.rows.map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{value}</dd></div>)}</dl>
      </section>
    </div>
  );
}

const MISSION_STEPS = [
  { id: "contract", icon: Waypoints, en: "Task contract", zh: "任务合同" },
  { id: "aircraft", icon: Navigation2, en: "Aircraft", zh: "无人机" },
  { id: "world", icon: Layers3, en: "World", zh: "环境" },
  { id: "trajectory", icon: Route, en: "Trajectory", zh: "航迹规划" },
  { id: "safety", icon: ShieldCheck, en: "Safety", zh: "安全策略" },
  { id: "review", icon: CircleCheck, en: "Review", zh: "检查验证" },
] as const;

export function AutonomyMissionRedirect() {
  return <Navigate replace to="/autonomy" />;
}

export function AutonomyMission() {
  const { chinese, workspace, persist } = useAutonomyWorkspace();
  const step = workspace.mission.currentStep;
  const handoffConsumed = useRef(false);
  useEffect(() => {
    if (handoffConsumed.current) return;
    handoffConsumed.current = true;
    const handoff = consumeAutonomyHandoff();
    if (!handoff) return;
    const updatedAt = new Date().toISOString();
    persist(updatedWorkspace(workspace, { mission: { ...workspace.mission, intent: handoff, currentStep: 0, updatedAt } }));
  }, [persist, workspace]);
  const selectStep = (currentStep: number) => {
    const updatedAt = new Date().toISOString();
    persist(updatedWorkspace(workspace, { mission: { ...workspace.mission, currentStep, updatedAt } }));
  };
  const mapReady = autonomyMapPackQualified(workspace.mapPack);
  const aircraftReady = isAutonomyAircraftAssetQualified(workspace.aircraft);
  const assetPairReady = autonomyAssetPairQualified(workspace);
  const blockers = [
    ...(!aircraftReady ? [chinese ? "机型质量包络无效" : "Aircraft mass envelope is invalid"] : []),
    ...(!mapReady ? [chinese ? "地图资料尚未完成运行场景绑定与认证" : "The map profile requires a qualified runtime binding"] : []),
    ...(aircraftReady && mapReady && !assetPairReady
      ? [chinese ? "地图与无人机必须来自同一次成对真实仿真认证" : "Map and aircraft must share one paired real-simulation qualification"]
      : []),
  ];
  return (
    <section className="autonomy-mission-page">
      <ol className="autonomy-mission-stepper">
        {MISSION_STEPS.map((item, index) => {
          const Icon = item.icon;
          return <li key={item.id} className={index === step ? "is-active" : index < step ? "is-complete" : ""}><button type="button" onClick={() => selectStep(index)}><span>{index < step ? <Check aria-hidden="true" /> : index + 1}</span><Icon aria-hidden="true" /><strong>{chinese ? item.zh : item.en}</strong></button></li>;
        })}
      </ol>

      <div className="autonomy-mission-stage">
        {step === 0 ? <section><header><Waypoints aria-hidden="true" /><h2>{chinese ? "任务合同" : "Task contract"}</h2><Link className="btn" to="/autonomy"><Sparkles aria-hidden="true" />{chinese ? "任务对话" : "Mission chat"}</Link></header><blockquote>{workspace.mission.intent}</blockquote><div className="autonomy-mission-model"><Cpu aria-hidden="true" /><span>{chinese ? "规划模型" : "Planning model"}</span><strong>{workspace.mission.planningModel.provider} · {workspace.mission.planningModel.model}</strong></div>{workspace.mission.planningBrief ? <p className="autonomy-planning-brief">{localizedAutonomyError(workspace.mission.planningBrief, chinese, { zh: "任务规划已完成，请继续检查结构化合同。", en: "Mission planning is complete. Continue reviewing the structured contract." })}</p> : null}<div className="autonomy-contract-points"><span><i>S</i>{chinese ? "起点" : "Start"}</span><ChevronRight /><span><i>1</i>{chinese ? "工作点" : "Work point"}</span><ChevronRight /><span><i>H</i>{chinese ? "返航" : "Return"}</span></div></section> : null}
        {step === 1 ? <section><header><Navigation2 aria-hidden="true" /><h2>{workspace.aircraft.name}</h2><Link className="btn" to="/autonomy/aircraft">{chinese ? "无人机仓库" : "Aircraft repository"}</Link></header><div className="autonomy-stage-metrics"><Metric icon={<Database />} label={chinese ? "资产标识" : "Asset ID"} value={workspace.aircraft.agentCoreAssetId ?? "—"} /><Metric icon={<ShieldCheck />} label={chinese ? "资格" : "Qualification"} value={readinessLabel(aircraftReady, chinese)} /><Metric icon={<FileClock />} label={chinese ? "内容哈希" : "Content hash"} value={workspace.aircraft.agentCoreContentSha256?.slice(0, 16) ?? "—"} /><Metric icon={<CircleCheck />} label={chinese ? "认证凭据" : "Receipt"} value={workspace.aircraft.qualificationReceiptId ?? "—"} /></div></section> : null}
        {step === 2 ? <section><header><Layers3 aria-hidden="true" /><h2>{workspace.mapPack.name}</h2><Link className="btn" to="/autonomy/maps">{chinese ? "地图仓库" : "Map repository"}</Link></header><div className="autonomy-stage-metrics"><Metric icon={<Database />} label={chinese ? "表示" : "Representation"} value={mapRepresentationLabel(workspace.mapPack.representation, chinese)} /><Metric icon={<ScanLine />} label={chinese ? "分辨率" : "Resolution"} value={`${workspace.mapPack.resolutionM.toFixed(3)} m`} /><Metric icon={<HardDrive />} label={chinese ? "资产" : "Assets"} value={String(workspace.mapPack.sourceFiles.length)} /><Metric icon={<ShieldCheck />} label={chinese ? "资格" : "Qualification"} value={readinessLabel(mapReady, chinese)} /></div></section> : null}
        {step === 3 ? <section><header><Route aria-hidden="true" /><h2>{chinese ? "航迹目标" : "Trajectory objectives"}</h2></header><div className="autonomy-planner-choices"><button className="is-selected"><ShieldCheck />{chinese ? "安全优先" : "Safety first"}</button><button><Activity />{chinese ? "平滑飞行" : "Smooth flight"}</button><button><Gauge />{chinese ? "时间效率" : "Time efficient"}</button><button><Cpu />{chinese ? "能量效率" : "Energy efficient"}</button></div></section> : null}
        {step === 4 ? <section><header><ShieldCheck aria-hidden="true" /><h2>{chinese ? "安全策略" : "Safety policy"}</h2></header><div className="autonomy-safety-policy-list"><span><Radio />{chinese ? "失联" : "Link loss"}<strong>{chinese ? "悬停 → 降落" : "HOLD → LAND"}</strong></span><span><MapPin />{chinese ? "越界" : "Geofence"}<strong>{chinese ? "降落" : "LAND"}</strong></span><span><Camera />{chinese ? "感知过期" : "Stale perception"}<strong>{chinese ? "悬停" : "HOLD"}</strong></span><span><Weight />{chinese ? "载荷超限" : "Payload overrun"}<strong>{chinese ? "降落" : "LAND"}</strong></span></div></section> : null}
        {step === 5 ? <section><header><CircleCheck aria-hidden="true" /><h2>{chinese ? "检查并验证" : "Review & qualify"}</h2></header><div className="autonomy-review-block"><div className={aircraftReady ? "is-ready" : "is-blocked"}><Navigation2 /><span>{chinese ? "无人机" : "Aircraft"}</span><strong>{readinessLabel(aircraftReady, chinese)}</strong></div><div className={mapReady ? "is-ready" : "is-blocked"}><Layers3 /><span>{chinese ? "地图资料" : "Map profile"}</span><strong>{readinessLabel(mapReady, chinese)}</strong></div><div className="is-ready"><ShieldCheck /><span>{chinese ? "安全策略" : "Safety policy"}</span><strong>{chinese ? "已绑定" : "Bound"}</strong></div></div>{blockers.length ? <ul className="autonomy-review-blockers">{blockers.map((blocker) => <li key={blocker}>{blocker}</li>)}</ul> : <Link className="btn btn-primary" to="/autonomy/live"><Airplay />{chinese ? "进入仿真验证" : "Open simulation validation"}</Link>}</section> : null}
      </div>

      <footer className="autonomy-mission-footer">
        <button className="btn" type="button" disabled={step === 0} onClick={() => selectStep(step - 1)}>{chinese ? "上一步" : "Back"}</button>
        <span>{step + 1} / {MISSION_STEPS.length}</span>
        <button className="btn btn-primary" type="button" disabled={step === MISSION_STEPS.length - 1} onClick={() => selectStep(step + 1)}>{chinese ? "下一步" : "Next"}<ChevronRight aria-hidden="true" /></button>
      </footer>
    </section>
  );
}

export function AgentCoreLiveMission({
  chinese,
  workspace,
  planningModel,
  accountId,
}: {
  chinese: boolean;
  workspace: AutonomyWorkspaceState;
  planningModel: AutonomyPlanningModel;
  accountId: string | null;
}) {
  const [thread, setThread] = useState<Awaited<ReturnType<typeof getBoundAgentCoreThread>>>(null);
  const [runtimeReady, setRuntimeReady] = useState<boolean | null>(null);
  const [runtimeIssue, setRuntimeIssue] = useState<string | null>(null);
  const [executionEvidence, setExecutionEvidence] = useState<AgentCoreExecutionEvidence | null>(null);
  const [working, setWorking] = useState(false);
  const [runtimeMessage, setRuntimeMessage] = useState("");
  const [error, setError] = useState<string | null>(null);
  const conversationId = workspace.mission.conversationId;
  const binding = useMemo(() => ({
    edition: "autonomy" as const,
    accountId,
    conversationId: conversationId || "",
  }), [accountId, conversationId]);

  useEffect(() => {
    if (!conversationId) return undefined;
    let cancelled = false;
    const refresh = async () => {
      try {
        const [nextThread, runtime] = await Promise.all([
          getBoundAgentCoreThread(binding),
          getAgentCoreRuntimeStatus(),
        ]);
        if (cancelled) return;
        setThread(nextThread);
        setRuntimeReady(runtime.runtime_available && runtime.resources_ready && runtime.provisioned);
        setRuntimeIssue(runtime.issue);
        if (nextThread && ["executing", "completed", "failed"].includes(nextThread.state)) {
          try {
            setExecutionEvidence(await getAgentCoreExecutionEvidence(nextThread.thread_id));
          } catch (reason) {
            if (!(reason instanceof AgentCoreRequestError) || reason.status !== 404) throw reason;
            setExecutionEvidence(null);
          }
        } else {
          setExecutionEvidence(null);
        }
      } catch (reason) {
        if (!cancelled) setError(localizedAutonomyError(reason, chinese, {
          zh: "AGENT Core 暂时不可用。",
          en: "AGENT Core is unavailable.",
        }));
      }
    };
    void refresh();
    const timer = window.setInterval(() => void refresh(), 1_500);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [binding, chinese, conversationId]);

  const executionInput = {
    ...binding,
    accessMode: planningModel.accessMode,
    provider: planningModel.provider,
    model: planningModel.model,
    agentCoreProfileId: planningModel.accessMode === "byok"
      ? planningModel.agentCoreProfileId ?? null
      : null,
    agentCoreSelectionId: planningModel.accessMode === "byok"
      ? planningModel.agentCoreSelectionId ?? null
      : null,
  };
  const start = async () => {
    setWorking(true);
    setError(null);
    try {
      await executeBoundAgentCoreMission(executionInput);
      setThread(await getBoundAgentCoreThread(binding));
    } catch (reason) {
      setError(localizedAutonomyError(reason, chinese, {
        zh: "AGENT Core 执行失败。",
        en: "AGENT Core execution failed.",
      }));
    } finally {
      setWorking(false);
    }
  };
  const sendRuntimeMessage = async (event: FormEvent) => {
    event.preventDefault();
    const text = runtimeMessage.trim();
    if (!text || !conversationId || thread?.state !== "executing") return;
    setWorking(true);
    setError(null);
    try {
      await submitRuntimeMessageToBoundAgentCore({ ...binding, text });
      setRuntimeMessage("");
      setThread(await getBoundAgentCoreThread(binding));
    } catch (reason) {
      setError(localizedAutonomyError(reason, chinese, {
        zh: "AGENT Core 未能处理运行中消息。",
        en: "AGENT Core could not process the runtime message.",
      }));
    } finally {
      setWorking(false);
    }
  };
  const stateLabel = !thread
    ? (chinese ? "没有绑定任务" : "No bound mission")
    : thread.state === "awaiting_confirmation"
      ? (chinese ? "等待确认" : "Awaiting confirmation")
      : thread.state === "executing"
        ? (chinese ? "真实仿真执行中" : "Real simulation running")
        : thread.state === "holding"
          ? (chinese ? "安全悬停中" : "Holding safely")
          : thread.state === "landing"
            ? (chinese ? "安全降落中" : "Landing safely")
            : thread.state === "completed"
              ? (chinese ? "已通过验收" : "Acceptance passed")
              : thread.state === "failed"
                ? (chinese ? "未通过验收" : "Acceptance failed")
                : chinese ? "正在准备任务" : "Preparing mission";
  const statusMessages = (thread?.messages ?? [])
    .filter((message) => message.kind === "status" || message.kind === "error")
    .slice(-8);
  const evidenceResult = executionEvidence?.result;
  const evidenceGates = evidenceResult ? Object.values(evidenceResult.gates) : [];
  const passedEvidenceGates = evidenceGates.filter(Boolean).length;
  return (
    <section className="agent-core-live-mission" aria-live="polite">
      <header>
        <span><Orbit aria-hidden="true" /></span>
        <div><small>ROS 2 · Gazebo · PX4 SITL</small><h2>{chinese ? "AGENT Core 真实仿真" : "AGENT Core real simulation"}</h2></div>
        <em data-state={thread?.state ?? "unbound"}>{stateLabel}</em>
      </header>
      <div className="agent-core-live-bindings">
        <span><Layers3 aria-hidden="true" /><small>{chinese ? "地图哈希" : "Map hash"}</small><strong>{workspace.mapPack.agentCoreContentSha256?.slice(0, 16) ?? "—"}</strong></span>
        <span><Navigation2 aria-hidden="true" /><small>{chinese ? "无人机哈希" : "Aircraft hash"}</small><strong>{workspace.aircraft.agentCoreContentSha256?.slice(0, 16) ?? "—"}</strong></span>
        <span><Cpu aria-hidden="true" /><small>{chinese ? "模型" : "Model"}</small><strong>{planningModel.provider} · {planningModel.model}</strong></span>
      </div>
      {runtimeReady === false ? <p className="agent-core-live-warning"><ShieldCheck aria-hidden="true" />{localizedAutonomyError(runtimeIssue, chinese, { zh: "运行环境尚未就绪，请从首屏完成环境安装。", en: "The runtime is not ready. Complete setup from the launch screen." })}</p> : null}
      {error ? <p className="agent-core-live-error">{error}</p> : null}
      {thread?.state === "awaiting_confirmation" ? (
        <div className="agent-core-live-confirmation">
          <p>{chinese ? "确认后才会启动真实的 Gazebo 与 PX4 SITL；规划合同、地图和无人机哈希在启动前会再次校验。" : "Gazebo and PX4 SITL start only after confirmation. The mission contract and exact asset hashes are revalidated before launch."}</p>
          <button className="btn btn-primary" type="button" disabled={working || runtimeReady !== true} onClick={() => void start()}><Airplay aria-hidden="true" />{working ? (chinese ? "正在启动" : "Starting") : (chinese ? "确认并开始仿真" : "Confirm and start simulation")}</button>
        </div>
      ) : null}
      {thread?.state === "executing" ? (
        <form className="agent-core-runtime-message" onSubmit={(event) => void sendRuntimeMessage(event)}>
          <label htmlFor="agent-core-runtime-message">{chinese ? "执行中指令" : "Runtime instruction"}</label>
          <div><input id="agent-core-runtime-message" value={runtimeMessage} maxLength={1_000} onChange={(event) => setRuntimeMessage(event.target.value)} placeholder={chinese ? "输入后无人机会先进入安全悬停，再解释并执行更改" : "The aircraft enters safe hold before interpreting and applying the change"} /><button className="btn btn-primary" type="submit" disabled={working || !runtimeMessage.trim()}>{chinese ? "发送" : "Send"}</button></div>
        </form>
      ) : null}
      {evidenceResult ? (
        <section className="agent-core-execution-evidence">
          <header>
            <div><small>{chinese ? "闭环验收证据" : "Closed-loop acceptance evidence"}</small><h3>{evidenceResult.status === "verified" ? (chinese ? "已验证" : "Verified") : (chinese ? "未通过" : "Failed")}</h3></div>
            <strong>{passedEvidenceGates} / {evidenceGates.length} {chinese ? "项门禁通过" : "gates passed"}</strong>
          </header>
          <dl>
            <div><dt>{chinese ? "位姿样本" : "Pose samples"}</dt><dd>{evidenceResult.measurements.pose_sample_count.toLocaleString()}</dd></div>
            <div><dt>{chinese ? "ROS 观测" : "ROS observations"}</dt><dd>{evidenceResult.measurements.ros_observation_rows.toLocaleString()}</dd></div>
            <div><dt>{chinese ? "最小目标距离" : "Minimum goal distance"}</dt><dd>{evidenceResult.measurements.minimum_goal_distance_m === null ? "—" : `${evidenceResult.measurements.minimum_goal_distance_m.toFixed(3)} m`}</dd></div>
            <div><dt>{chinese ? "着陆状态" : "Landing state"}</dt><dd>{evidenceResult.measurements.landing_state ? localizedStructuredTerm(evidenceResult.measurements.landing_state, chinese) : "—"}</dd></div>
            <div><dt>{chinese ? "运行时改道" : "Runtime replans"}</dt><dd>{evidenceResult.runtime_interruption_count}</dd></div>
            <div><dt>{chinese ? "插件回执" : "Plugin receipts"}</dt><dd>{evidenceResult.plugin_hook_receipt_count}</dd></div>
          </dl>
          <footer>
            <span>{chinese ? "任务合同" : "Contract"}<code>{evidenceResult.contract_id}</code></span>
            <span>{chinese ? "证据链头" : "Evidence chain head"}<code>{evidenceResult.workflow_evidence_chain_head}</code></span>
            <span>{chinese ? "结果哈希" : "Result hash"}<code>{evidenceResult.workflow_result_sha256}</code></span>
          </footer>
        </section>
      ) : null}
      {statusMessages.length ? <ol className="agent-core-runtime-events">{statusMessages.map((message) => <li key={message.message_id} data-kind={message.kind}><time>{new Date(message.created_at).toLocaleTimeString()}</time><span>{localizedAutonomyError(message.content, chinese, message.kind === "error" ? { zh: "运行时发生错误，请查看错误码与证据记录。", en: "A runtime error occurred. Review the error code and evidence record." } : { zh: "运行状态已更新。", en: "Runtime status updated." })}</span></li>)}</ol> : null}
    </section>
  );
}

type LiveSource = AgentCoreLiveSource | {
  id: string;
  kind: "camera";
  label: string;
  transport: "media-device";
  mode: "hardware";
  ready: true;
};

function recordingMimeType() {
  return [
    "video/mp4;codecs=avc1",
    "video/mp4",
    "video/webm;codecs=vp9",
    "video/webm;codecs=vp8",
    "video/webm",
  ].find((value) => MediaRecorder.isTypeSupported(value)) ?? "";
}

async function blobBase64(blob: Blob) {
  return new Promise<string>((resolve, reject) => {
    const reader = new FileReader();
    reader.onerror = () => reject(reader.error ?? new Error("RECORDING_READ_FAILED"));
    reader.onload = () => resolve(String(reader.result).split(",", 2)[1] ?? "");
    reader.readAsDataURL(blob);
  });
}

async function persistLiveRecording(blob: Blob, fileName: string) {
  const core = (window as Window & {
    __TAURI__?: { core?: { invoke(command: string, args?: Record<string, unknown>): Promise<unknown> } };
  }).__TAURI__?.core;
  if (core) {
    const value = await core.invoke("save_live_recording", {
      request: { fileName, bodyBase64: await blobBase64(blob) },
    });
    return String((value as { path?: unknown })?.path ?? fileName);
  }
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = fileName;
  anchor.click();
  window.setTimeout(() => URL.revokeObjectURL(url), 2_000);
  return fileName;
}

export function AutonomyLive() {
  const { chinese, workspace } = useAutonomyWorkspace();
  const auth = useOptionalAuth();
  const edition = useEditionTheme().id;
  const conversationId = workspace.mission.conversationId;
  const binding = useMemo(() => ({
    edition,
    accountId: auth?.account?.id ?? null,
    conversationId: conversationId || "",
  }), [auth?.account?.id, conversationId, edition]);
  const [threadId, setThreadId] = useState("");
  const [coreSources, setCoreSources] = useState<AgentCoreLiveSource[]>([]);
  const [deviceSources, setDeviceSources] = useState<LiveSource[]>([]);
  const [sourceId, setSourceId] = useState("");
  const [playing, setPlaying] = useState(false);
  const [stream, setStream] = useState<MediaStream | null>(null);
  const [telemetry, setTelemetry] = useState<AgentCoreLiveTelemetry | null>(null);
  const [recording, setRecording] = useState(false);
  const [recordingStatus, setRecordingStatus] = useState("");
  const videoRef = useRef<HTMLVideoElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const recorderRef = useRef<MediaRecorder | null>(null);
  const recorderStreamRef = useRef<MediaStream | null>(null);
  const sources = useMemo<LiveSource[]>(() => [...coreSources, ...deviceSources], [coreSources, deviceSources]);

  useEffect(() => {
    if (!conversationId) {
      setThreadId("");
      setCoreSources([]);
      return undefined;
    }
    let cancelled = false;
    const refresh = async () => {
      try {
        const thread = await getBoundAgentCoreThread(binding);
        if (!cancelled) {
          const boundId = thread?.thread_id ?? "";
          setThreadId(boundId);
          if (!boundId) setCoreSources([]);
        }
      } catch {
        if (!cancelled) {
          setThreadId("");
          setCoreSources([]);
        }
      }
    };
    void refresh();
    const timer = window.setInterval(() => void refresh(), 1_500);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [binding, conversationId]);

  useEffect(() => {
    let cancelled = false;
    const discover = async () => {
      const discovered: LiveSource[] = [];
      try {
        const devices = await navigator.mediaDevices?.enumerateDevices();
        (devices ?? []).filter((device) => device.kind === "videoinput").forEach((device, index) => {
          discovered.push({
            id: `device-${device.deviceId}`,
            label: device.label || `${chinese ? "摄像头" : "Camera"} ${index + 1}`,
            kind: "camera",
            transport: "media-device",
            mode: "hardware",
            ready: true,
          });
        });
      } catch {
        // Simulation and adapter-registered sources remain available without camera permission.
      }
      if (cancelled) return;
      setDeviceSources(discovered);
    };
    void discover();
    navigator.mediaDevices?.addEventListener?.("devicechange", discover);
    return () => {
      cancelled = true;
      navigator.mediaDevices?.removeEventListener?.("devicechange", discover);
    };
  }, [chinese]);

  useEffect(() => {
    if (!threadId) return undefined;
    let cancelled = false;
    const refresh = async () => {
      try {
        const catalog = await getAgentCoreLiveSources(threadId);
        if (!cancelled) setCoreSources(catalog.sources);
      } catch {
        if (!cancelled) setCoreSources([]);
      }
    };
    void refresh();
    const timer = window.setInterval(() => void refresh(), 900);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [threadId]);

  useEffect(() => {
    setSourceId((current) => sources.some((source) => source.id === current)
      ? current
      : sources[0]?.id ?? "");
    if (!sources.length) setPlaying(false);
  }, [sources]);

  const stop = useCallback(() => {
    if (recorderRef.current?.state === "recording") recorderRef.current.stop();
    stream?.getTracks().forEach((track) => track.stop());
    setStream(null);
    setTelemetry(null);
    setPlaying(false);
  }, [stream]);

  useEffect(() => () => stream?.getTracks().forEach((track) => track.stop()), [stream]);
  useEffect(() => {
    if (videoRef.current) videoRef.current.srcObject = stream;
  }, [stream]);

  const selectedSource = sources.find((source) => source.id === sourceId) ?? null;
  const play = async () => {
    if (!selectedSource) return;
    if (selectedSource.transport === "media-device") {
      try {
        const deviceId = selectedSource.id.slice("device-".length);
        const nextStream = await navigator.mediaDevices.getUserMedia({ video: { deviceId: { exact: deviceId } }, audio: false });
        setStream(nextStream);
      } catch {
        setPlaying(false);
        return;
      }
    }
    setPlaying(true);
  };

  useEffect(() => {
    if (!playing || selectedSource?.transport !== "agent-core-frame" || !threadId) return undefined;
    let cancelled = false;
    let busy = false;
    const draw = async () => {
      if (busy) return;
      busy = true;
      try {
        const frame = await getAgentCoreLiveFrame(threadId);
        const bitmap = await createImageBitmap(frame);
        const canvas = canvasRef.current;
        if (canvas && !cancelled) {
          if (canvas.width !== bitmap.width || canvas.height !== bitmap.height) {
            canvas.width = bitmap.width;
            canvas.height = bitmap.height;
          }
          canvas.getContext("2d")?.drawImage(bitmap, 0, 0);
        }
        bitmap.close();
      } catch {
        // The camera sensor may need a short warm-up after Gazebo starts.
      } finally {
        busy = false;
      }
    };
    void draw();
    const timer = window.setInterval(() => void draw(), 120);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [playing, selectedSource?.transport, threadId]);

  useEffect(() => {
    if (!playing || selectedSource?.kind !== "gps") {
      setTelemetry(null);
      return undefined;
    }
    let cancelled = false;
    const refresh = async () => {
      try {
        const value = selectedSource.transport === "agent-core-telemetry" && threadId
          ? await getAgentCoreLiveTelemetry(threadId)
          : selectedSource.url
            ? await fetch(selectedSource.url, { cache: "no-store" }).then((response) => {
              if (!response.ok) throw new Error("GPS_SOURCE_UNAVAILABLE");
              return response.json() as Promise<AgentCoreLiveTelemetry>;
            })
            : null;
        if (!cancelled) setTelemetry(value);
      } catch {
        if (!cancelled) setTelemetry(null);
      }
    };
    void refresh();
    const timer = window.setInterval(() => void refresh(), 400);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [playing, selectedSource, threadId]);

  const geographicPosition = useMemo(() => {
    if (!telemetry) return null;
    if (telemetry.coordinate_frame === "wgs84" && typeof telemetry.latitude === "number" && typeof telemetry.longitude === "number") {
      return { latitude: telemetry.latitude, longitude: telemetry.longitude, altitudeM: telemetry.altitude_m ?? null };
    }
    const origin = workspace.mapPack.origin;
    if (typeof origin.latitude !== "number" || typeof origin.longitude !== "number") return null;
    const north = telemetry.north_m ?? 0;
    const east = telemetry.east_m ?? 0;
    const latitude = origin.latitude + north / 111_320;
    const longitude = origin.longitude + east / (111_320 * Math.max(0.01, Math.cos(origin.latitude * Math.PI / 180)));
    return { latitude, longitude, altitudeM: (origin.altitudeM ?? 0) + (telemetry.up_m ?? 0) };
  }, [telemetry, workspace.mapPack.origin]);

  const toggleRecording = async () => {
    if (recording) {
      recorderRef.current?.stop();
      return;
    }
    if (!playing || !selectedSource) return;
    let capture: MediaStream | null = null;
    let ownsCapture = false;
    if (selectedSource.transport === "media-device") capture = stream;
    if (selectedSource.transport === "agent-core-frame") capture = canvasRef.current?.captureStream(15) ?? null;
    if (!capture && videoRef.current) {
      capture = (videoRef.current as HTMLVideoElement & { captureStream?: () => MediaStream }).captureStream?.() ?? null;
    }
    if (!capture && navigator.mediaDevices?.getDisplayMedia) {
      capture = await navigator.mediaDevices.getDisplayMedia({ video: true, audio: false });
      ownsCapture = true;
    }
    if (!capture) {
      setRecordingStatus(chinese ? "当前画面无法录制" : "This source cannot be recorded");
      return;
    }
    const mimeType = recordingMimeType();
    const chunks: Blob[] = [];
    const recorder = new MediaRecorder(capture, mimeType ? { mimeType } : undefined);
    recorderRef.current = recorder;
    recorderStreamRef.current = ownsCapture ? capture : null;
    recorder.ondataavailable = (event) => { if (event.data.size) chunks.push(event.data); };
    recorder.onerror = () => setRecordingStatus(chinese ? "录制失败" : "Recording failed");
    recorder.onstop = async () => {
      setRecording(false);
      recorderStreamRef.current?.getTracks().forEach((track) => track.stop());
      recorderStreamRef.current = null;
      const type = recorder.mimeType || mimeType || "video/webm";
      const blob = new Blob(chunks, { type });
      if (!blob.size) return;
      const extension = type.includes("mp4") ? "mp4" : "webm";
      const fileName = `DroneDream-${new Date().toISOString().replace(/[:.]/gu, "-")}.${extension}`;
      try {
        const saved = await persistLiveRecording(blob, fileName);
        setRecordingStatus(`${chinese ? "已保存" : "Saved"}: ${saved}`);
      } catch {
        setRecordingStatus(chinese ? "保存录像失败" : "Unable to save recording");
      }
    };
    recorder.start(1_000);
    setRecordingStatus("");
    setRecording(true);
  };

  useEffect(() => () => recorderStreamRef.current?.getTracks().forEach((track) => track.stop()), []);

  return (
    <section className="autonomy-live-viewer">
      <div className="autonomy-live-player">
        <div className="autonomy-live-screen" data-playing={playing}>
          {playing && selectedSource?.transport === "agent-core-frame" ? <canvas ref={canvasRef} aria-label={selectedSource.label} /> : null}
          {playing && selectedSource?.kind === "gps" ? (
            <div className="autonomy-live-map" data-ready={Boolean(telemetry)}>
              <div className="autonomy-live-map-grid" />
              {telemetry ? <MapPin className="autonomy-live-map-marker" aria-hidden="true" /> : null}
              <div className="autonomy-live-coordinates">
                {geographicPosition
                  ? <><strong>{geographicPosition.latitude.toFixed(6)}, {geographicPosition.longitude.toFixed(6)}</strong><span>{geographicPosition.altitudeM?.toFixed(1) ?? "—"} m</span></>
                  : telemetry
                    ? <><strong>E {(telemetry.east_m ?? 0).toFixed(1)} · N {(telemetry.north_m ?? 0).toFixed(1)}</strong><span>{(telemetry.up_m ?? 0).toFixed(1)} m</span></>
                    : <span>{chinese ? "等待定位" : "Waiting for position"}</span>}
              </div>
            </div>
          ) : null}
          {playing && selectedSource?.transport === "video" && selectedSource.url ? <video ref={videoRef} src={selectedSource.url} autoPlay playsInline muted controls={false} /> : null}
          {playing && selectedSource?.transport === "image" && selectedSource.url ? <img src={selectedSource.url} alt={selectedSource.label} /> : null}
          {playing && selectedSource?.transport === "media-device" ? <video ref={videoRef} autoPlay playsInline muted /> : null}
          {!playing ? <div className="autonomy-live-off"><VideoOff aria-hidden="true" /><span>{chinese ? "无画面" : "No signal"}</span></div> : null}
        </div>
        <div className="autonomy-live-controls">
          <button className="autonomy-live-play" type="button" onClick={() => playing ? stop() : void play()} disabled={!selectedSource} aria-label={playing ? (chinese ? "停止" : "Stop") : (chinese ? "播放" : "Play")}>
            {playing ? <Square aria-hidden="true" /> : <Play aria-hidden="true" />}
          </button>
          <button className="autonomy-live-record" type="button" onClick={() => void toggleRecording()} disabled={!playing} data-recording={recording} aria-label={recording ? (chinese ? "停止录制" : "Stop recording") : (chinese ? "开始录制" : "Record")}>
            {recording ? <Square aria-hidden="true" /> : <span className="autonomy-live-record-dot" aria-hidden="true" />}
          </button>
          <select
            value={sourceId}
            disabled={sources.length <= 1}
            aria-label={chinese ? "画面来源" : "Video source"}
            onChange={(event) => {
              stop();
              setSourceId(event.target.value);
            }}
          >
            {!sources.length ? <option value="">{chinese ? "无可用画面" : "No source"}</option> : null}
            {sources.map((source) => <option key={source.id} value={source.id}>{source.label}</option>)}
          </select>
        </div>
      </div>
      {recordingStatus ? <p className="autonomy-live-recording-status" aria-live="polite">{recordingStatus}</p> : null}
    </section>
  );
}
