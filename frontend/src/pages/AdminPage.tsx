import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type FormEvent,
} from "react";

import { useAdminAccess } from "../features/admin/AdminAccessContext";
import {
  AdminConsoleError,
  exportAdminUsers,
  getAdminDashboard,
  listAdminAudit,
  listAdminModels,
  listAdminTopics,
  listAdminUsers,
  removeAdminTopic,
  updateAdminModel,
  type AdminAuditRow,
  type AdminDashboardSnapshot,
  type AdminManagedModel,
  type AdminRange,
  type AdminTopicRow,
  type AdminUserRow,
} from "../features/admin/adminConsole";
import { useI18n } from "../i18n/I18nProvider";

type AdminTab = "overview" | "models" | "users" | "community";

const COPY = {
  en: {
    eyebrow: "OWNER CONTROL CENTER",
    title: "Administration",
    subtitle: "Product growth, managed models, account usage, and community safety — with server-enforced access and an immutable audit trail.",
    overview: "Growth overview",
    models: "Model availability",
    users: "Users & usage",
    community: "Community & audit",
    loading: "Loading administration data…",
    deniedTitle: "Administration access denied",
    deniedBody: "This page is available only to a server-authorized DroneDream owner account.",
    unavailableTitle: "Administration service unavailable",
    retry: "Retry access check",
    refresh: "Refresh data",
    range: "Date range",
    ranges: { "7d": "7 days", "30d": "30 days", "90d": "90 days" },
    generated: "Generated",
    utcNote: "Daily boundaries and cohorts use UTC.",
    totalUsers: "Total users",
    newUsers: "New users",
    activeUsers: "Active users",
    trendAria: "Daily active, new, and activated users trend",
    activation: "7-day activation",
    dauWauMau: "DAU / WAU / MAU",
    stickiness: "DAU / MAU",
    retention: "D1 / D7 / D30 retention",
    paidConversion: "Paid conversion",
    dailyTrend: "Daily product value",
    new: "New",
    active: "Active",
    activated: "Activated",
    funnel: "Activation funnel",
    cohortRetention: "Weekly retention cohorts",
    cohort: "Cohort",
    size: "Size",
    featureAdoption: "Feature adoption",
    acquisition: "Acquisition quality",
    signupSource: "Verified signup source",
    timeToValue: "Time to first value",
    median: "Median",
    p90: "P90",
    usersLabel: "users",
    frequency: "uses per user",
    reliability: "Reliability & quota health",
    jobSuccess: "Job success",
    modelSuccess: "Model success",
    rateLimited: "Rate-limited",
    p95Latency: "P95 model latency",
    quotaExhausted: "Quota exhausted",
    monetization: "Plans & managed usage",
    credits: "AI credits consumed",
    tokens: "model tokens",
    estimated: "usage rows estimated",
    definitions: "Metric definitions",
    modelPolicyBody: "These switches affect both the browser console and desktop conversation after the central policy is published. Keys remain server-side; user BYOK keys stay in each user's settings.",
    provider: "Provider",
    model: "Model",
    globallyEnabled: "Available",
    assistantEnabled: "Conversation",
    jobEnabled: "Optimization jobs",
    lastChange: "Last change",
    saving: "Saving…",
    modelSaveFailed: "The model policy could not be saved.",
    userPrivacy: "Passwords and password hashes are never returned by this interface.",
    exportUsers: "Export user data",
    exportingUsers: "Preparing export…",
    exportStarted: "CSV download started:",
    exportFailed: "The user data export could not be prepared.",
    exportScope: "Exports every user matching the applied email search. Passwords, API keys, auth tokens, and raw conversations are excluded.",
    searchEmail: "Search email",
    search: "Search",
    email: "Email",
    plan: "Subscription",
    lastSignIn: "Last sign-in",
    usage: "Current-period usage",
    requests: "requests",
    remaining: "remaining",
    noUsers: "No users match this search.",
    previous: "Previous",
    next: "Next",
    page: "Page",
    of: "of",
    topics: "Community topics",
    topic: "Topic",
    author: "Author",
    reports: "Reports",
    comments: "Comments",
    status: "Status",
    remove: "Remove",
    removed: "Removed",
    removeTitle: "Remove community topic",
    removeWarning: "The topic will be hidden from public listings. The record and audit evidence are retained for review.",
    reason: "Moderation reason",
    reasonPlaceholder: "State the policy or safety reason (minimum 8 characters).",
    cancel: "Cancel",
    confirmRemove: "Confirm removal",
    moderationFailed: "The topic could not be removed.",
    audit: "Recent administrative audit",
    action: "Action",
    target: "Target",
    actor: "Actor",
    time: "Time",
    noAudit: "No administrative changes in this range.",
    funnelSteps: {
      registered: "Registered",
      runtime_ready: "Runtime ready",
      first_draft: "First draft",
      first_job: "First job",
      first_success: "First successful run",
    },
    featureNames: {
      assistant: "Tuning chat",
      fixed_scenarios: "Fixed scenarios",
      custom_tracks: "Custom tracks",
      community: "Community",
    },
    acquisitionSources: {
      direct: "Direct",
      documentation: "Documentation",
      community: "Community",
      referral: "Referral",
      unknown: "Unknown",
    },
    metricDefinitions: {
      active_user: { label: "Active user", definition: "A signed-in user who reaches a value event: assistant turn, draft save, job action, report export, or community contribution." },
      activated_user: { label: "Activated user", definition: "A newly registered user who completes a first successful simulation job within seven days." },
      retention: { label: "Retention", definition: "A registered cohort member who returns for another value event on the measured day." },
      time_to_value: { label: "Time to first value", definition: "Elapsed time from verified registration to the first successful simulation job." },
    },
  },
  "zh-CN": {
    eyebrow: "所有者控制中心",
    title: "管理端",
    subtitle: "统一查看产品增长、托管模型、账户用量与社区安全；权限由服务端强制验证，所有管理操作均保留审计记录。",
    overview: "增长总览",
    models: "模型开放状态",
    users: "用户与用量",
    community: "社区与审计",
    loading: "正在加载管理数据…",
    deniedTitle: "无权访问管理端",
    deniedBody: "只有经过服务端授权的 DroneDream 所有者账户才能打开此页面。",
    unavailableTitle: "管理服务暂时不可用",
    retry: "重新检查权限",
    refresh: "刷新数据",
    range: "统计时间范围",
    ranges: { "7d": "近 7 天", "30d": "近 30 天", "90d": "近 90 天" },
    generated: "生成时间",
    utcNote: "每日统计边界与留存分组统一使用 UTC。",
    totalUsers: "累计用户",
    newUsers: "新增用户",
    activeUsers: "活跃用户",
    trendAria: "每日活跃、新增与完成激活用户趋势",
    activation: "7 日激活率",
    dauWauMau: "日活 / 周活 / 月活",
    stickiness: "日活 / 月活",
    retention: "次日 / 7 日 / 30 日留存",
    paidConversion: "付费转化率",
    dailyTrend: "每日产品价值行为",
    new: "新增",
    active: "活跃",
    activated: "完成激活",
    funnel: "激活漏斗",
    cohortRetention: "每周留存分组",
    cohort: "注册周",
    size: "人数",
    featureAdoption: "功能采用情况",
    acquisition: "获客质量",
    signupSource: "可信注册来源",
    timeToValue: "首次价值用时",
    median: "中位数",
    p90: "P90",
    usersLabel: "位用户",
    frequency: "人均使用次数",
    reliability: "可靠性与额度健康",
    jobSuccess: "任务成功率",
    modelSuccess: "模型请求成功率",
    rateLimited: "限流比例",
    p95Latency: "模型 P95 延迟",
    quotaExhausted: "额度耗尽用户",
    monetization: "订阅与托管模型用量",
    credits: "已消耗 AI 额度",
    tokens: "模型 Token",
    estimated: "条用量为估算值",
    definitions: "指标口径",
    modelPolicyBody: "中央策略发布后，这些开关会同时约束网页控制台和桌面对话。平台密钥始终在服务端；用户 BYOK 密钥仍只在其个人设置中输入。",
    provider: "服务商",
    model: "模型",
    globallyEnabled: "全局开放",
    assistantEnabled: "对话可用",
    jobEnabled: "调优任务可用",
    lastChange: "最后修改",
    saving: "正在保存…",
    modelSaveFailed: "无法保存模型开放策略。",
    userPrivacy: "此管理端永远不会返回用户密码或密码哈希。",
    exportUsers: "导出用户数据",
    exportingUsers: "正在准备导出…",
    exportStarted: "CSV 已开始下载：",
    exportFailed: "无法生成用户数据导出文件。",
    exportScope: "导出符合当前邮箱搜索条件的全部用户；不包含密码、API Key、登录令牌或原始对话。",
    searchEmail: "搜索邮箱",
    search: "搜索",
    email: "邮箱",
    plan: "订阅",
    lastSignIn: "最近登录",
    usage: "本周期用量",
    requests: "次请求",
    remaining: "剩余额度",
    noUsers: "没有符合条件的用户。",
    previous: "上一页",
    next: "下一页",
    page: "第",
    of: "页 / 共",
    topics: "社区帖子",
    topic: "帖子",
    author: "作者",
    reports: "举报",
    comments: "评论",
    status: "状态",
    remove: "删帖",
    removed: "已移除",
    removeTitle: "移除社区帖子",
    removeWarning: "帖子会立即从公开列表隐藏，但原始记录与管理审计会保留，便于复核。",
    reason: "管理原因",
    reasonPlaceholder: "说明违反的规则或安全原因（至少 8 个字符）。",
    cancel: "取消",
    confirmRemove: "确认移除",
    moderationFailed: "无法移除该帖子。",
    audit: "最近管理审计",
    action: "操作",
    target: "对象",
    actor: "管理员",
    time: "时间",
    noAudit: "当前范围内没有管理操作。",
    funnelSteps: {
      registered: "完成注册",
      runtime_ready: "运行环境就绪",
      first_draft: "创建首份草稿",
      first_job: "创建首个任务",
      first_success: "首次仿真成功",
    },
    featureNames: {
      assistant: "调优对话",
      fixed_scenarios: "固定场景",
      custom_tracks: "自定义赛道",
      community: "社区",
    },
    acquisitionSources: {
      direct: "直接访问",
      documentation: "产品文档",
      community: "社区",
      referral: "用户推荐",
      unknown: "来源未知",
    },
    metricDefinitions: {
      active_user: { label: "活跃用户", definition: "已登录且完成至少一个价值行为的用户：进行调优对话、保存草稿、操作任务、导出报告或参与社区。" },
      activated_user: { label: "激活用户", definition: "新注册用户在七天内完成第一次成功的仿真任务。" },
      retention: { label: "留存", definition: "同一注册分组中的用户在被统计日再次完成价值行为。" },
      time_to_value: { label: "首次价值用时", definition: "从验证注册完成到第一次成功仿真任务之间的时间。" },
    },
  },
} as const;

function formatPercent(value: number | null): string {
  return value === null ? "—" : `${value.toFixed(1)}%`;
}

function safeError(error: unknown, fallback: string): string {
  if (error instanceof AdminConsoleError && [401, 403].includes(error.status)) {
    return fallback;
  }
  return error instanceof Error ? error.message : fallback;
}

function translatedLabel(
  dictionary: Readonly<Record<string, string>>,
  key: string,
  fallback: string,
): string {
  return dictionary[key] ?? fallback;
}

function TrendChart({
  snapshot,
  label,
}: {
  snapshot: AdminDashboardSnapshot;
  label: string;
}) {
  const maximum = Math.max(1, ...snapshot.daily.flatMap((day) => [
    day.active_users,
    day.new_users,
    day.activated_users,
  ]));
  const points = (key: "active_users" | "new_users" | "activated_users") =>
    snapshot.daily.map((day, index) => {
      const x = snapshot.daily.length <= 1 ? 0 : (index / (snapshot.daily.length - 1)) * 100;
      const y = 96 - (day[key] / maximum) * 88;
      return `${x},${y}`;
    }).join(" ");
  return (
    <div className="admin-trend-chart" role="img" aria-label={label}>
      <svg viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden="true">
        <polyline className="is-active" points={points("active_users")} />
        <polyline className="is-new" points={points("new_users")} />
        <polyline className="is-activated" points={points("activated_users")} />
      </svg>
      <div className="admin-trend-dates">
        <span>{snapshot.daily.at(0)?.date}</span>
        <span>{snapshot.daily.at(-1)?.date}</span>
      </div>
    </div>
  );
}

export function AdminPage() {
  const { locale } = useI18n();
  const copy = COPY[locale];
  const access = useAdminAccess();
  const [tab, setTab] = useState<AdminTab>("overview");
  const [range, setRange] = useState<AdminRange>("30d");
  const [dashboard, setDashboard] = useState<AdminDashboardSnapshot | null>(null);
  const [models, setModels] = useState<AdminManagedModel[]>([]);
  const [users, setUsers] = useState<AdminUserRow[]>([]);
  const [userPage, setUserPage] = useState(1);
  const [usersTotal, setUsersTotal] = useState(0);
  const [topics, setTopics] = useState<AdminTopicRow[]>([]);
  const [topicPage, setTopicPage] = useState(1);
  const [topicsTotal, setTopicsTotal] = useState(0);
  const [audit, setAudit] = useState<AdminAuditRow[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [savingProvider, setSavingProvider] = useState<string | null>(null);
  const [userSearch, setUserSearch] = useState("");
  const [submittedUserSearch, setSubmittedUserSearch] = useState("");
  const [exportingUsers, setExportingUsers] = useState(false);
  const [userExportMessage, setUserExportMessage] = useState<string | null>(null);
  const [moderatingTopic, setModeratingTopic] = useState<AdminTopicRow | null>(null);
  const [moderationReason, setModerationReason] = useState("");
  const [moderating, setModerating] = useState(false);
  const loadSequenceRef = useRef(0);
  const moderationDialogRef = useRef<HTMLElement | null>(null);
  const moderationReasonRef = useRef<HTMLTextAreaElement | null>(null);
  const moderationTriggerRef = useRef<HTMLButtonElement | null>(null);

  const loadAll = useCallback(async () => {
    if (access.status !== "allowed") return;
    const sequence = ++loadSequenceRef.current;
    setLoading(true);
    setError(null);
    try {
      const [nextDashboard, nextModels, nextUsers, nextTopics, nextAudit] = await Promise.all([
        getAdminDashboard(range),
        listAdminModels(),
        listAdminUsers(userPage, submittedUserSearch),
        listAdminTopics(topicPage),
        listAdminAudit(1),
      ]);
      if (sequence !== loadSequenceRef.current) return;
      setDashboard(nextDashboard);
      setModels(nextModels);
      setUsers(nextUsers.items);
      setUsersTotal(nextUsers.total);
      setTopics(nextTopics.items);
      setTopicsTotal(nextTopics.total);
      setAudit(nextAudit.items);
    } catch (caught) {
      if (sequence !== loadSequenceRef.current) return;
      setError(safeError(caught, copy.unavailableTitle));
    } finally {
      if (sequence === loadSequenceRef.current) setLoading(false);
    }
  }, [access.status, copy.unavailableTitle, range, submittedUserSearch, topicPage, userPage]);

  useEffect(() => {
    void loadAll();
    return () => {
      loadSequenceRef.current += 1;
    };
  }, [loadAll]);

  const closeModeration = useCallback((restoreFocus = true) => {
    setModeratingTopic(null);
    setModerationReason("");
    if (restoreFocus) {
      window.requestAnimationFrame(() => moderationTriggerRef.current?.focus());
    }
  }, []);

  useEffect(() => {
    if (!moderatingTopic) return;
    window.requestAnimationFrame(() => moderationReasonRef.current?.focus());
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !moderating) {
        event.preventDefault();
        closeModeration();
        return;
      }
      if (event.key !== "Tab") return;
      const dialog = moderationDialogRef.current;
      if (!dialog) return;
      const focusable = Array.from(dialog.querySelectorAll<HTMLElement>(
        'button:not([disabled]), textarea:not([disabled]), [href], [tabindex]:not([tabindex="-1"])',
      )).filter((element) => !element.hidden);
      if (focusable.length === 0) return;
      const first = focusable[0];
      const last = focusable.at(-1) ?? first;
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [closeModeration, moderating, moderatingTopic]);

  const number = useMemo(
    () => new Intl.NumberFormat(locale === "zh-CN" ? "zh-CN" : "en-US"),
    [locale],
  );
  const date = useMemo(
    () => new Intl.DateTimeFormat(locale === "zh-CN" ? "zh-CN" : "en-US", {
      dateStyle: "medium",
      timeStyle: "short",
      timeZone: "UTC",
    }),
    [locale],
  );

  if (["disabled", "denied"].includes(access.status)) {
    return (
      <main className="admin-state-page">
        <section className="admin-state-card" role="alert">
          <h1>{copy.deniedTitle}</h1>
          <p>{copy.deniedBody}</p>
        </section>
      </main>
    );
  }
  if (access.status === "loading") {
    return <main className="admin-state-page" aria-busy="true"><p>{copy.loading}</p></main>;
  }
  if (access.status === "unavailable") {
    return (
      <main className="admin-state-page">
        <section className="admin-state-card" role="alert">
          <h1>{copy.unavailableTitle}</h1>
          <p>{access.error}</p>
          <button type="button" className="btn btn-primary" onClick={() => void access.refresh()}>
            {copy.retry}
          </button>
        </section>
      </main>
    );
  }

  const toggleModel = async (
    item: AdminManagedModel,
    key: "enabled" | "assistant_enabled" | "job_enabled",
  ) => {
    setSavingProvider(item.provider);
    setError(null);
    try {
      const updated = await updateAdminModel(item.provider, {
        enabled: key === "enabled" ? !item.enabled : item.enabled,
        assistant_enabled: key === "assistant_enabled" ? !item.assistant_enabled : item.assistant_enabled,
        job_enabled: key === "job_enabled" ? !item.job_enabled : item.job_enabled,
        version: item.version,
      });
      setModels((current) => current.map((model) =>
        model.provider === updated.provider ? updated : model
      ));
    } catch (caught) {
      setError(safeError(caught, copy.modelSaveFailed));
    } finally {
      setSavingProvider(null);
    }
  };

  const submitSearch = (event: FormEvent) => {
    event.preventDefault();
    setUserPage(1);
    setSubmittedUserSearch(userSearch.trim());
  };

  const startUserExport = async () => {
    setExportingUsers(true);
    setUserExportMessage(null);
    setError(null);
    try {
      const exported = await exportAdminUsers(submittedUserSearch);
      const objectUrl = URL.createObjectURL(exported.blob);
      const anchor = document.createElement("a");
      anchor.href = objectUrl;
      anchor.download = exported.file_name;
      anchor.hidden = true;
      try {
        document.body.append(anchor);
        anchor.click();
      } finally {
        anchor.remove();
        window.setTimeout(() => URL.revokeObjectURL(objectUrl), 0);
      }
      const count = exported.row_count === null ? "" : ` (${number.format(exported.row_count)})`;
      setUserExportMessage(`${copy.exportStarted} ${exported.file_name}${count}`);
    } catch (caught) {
      setError(safeError(caught, copy.exportFailed));
    } finally {
      setExportingUsers(false);
    }
  };

  const confirmModeration = async () => {
    if (!moderatingTopic || moderationReason.trim().length < 8) return;
    setModerating(true);
    setError(null);
    try {
      await removeAdminTopic(moderatingTopic.id, moderationReason);
      setTopics((current) => current.map((topic) =>
        topic.id === moderatingTopic.id ? { ...topic, status: "removed" } : topic
      ));
      closeModeration(false);
      const refreshedAudit = await listAdminAudit(1);
      setAudit(refreshedAudit.items);
    } catch (caught) {
      setError(safeError(caught, copy.moderationFailed));
    } finally {
      setModerating(false);
    }
  };

  return (
    <main className="admin-page" id="main-content" tabIndex={-1}>
      <header className="admin-hero">
        <div>
          <span>{copy.eyebrow}</span>
          <h1>{copy.title}</h1>
          <p>{copy.subtitle}</p>
        </div>
        <div className="admin-hero-actions">
          <label>
            <span className="sr-only">{copy.range}</span>
            <select value={range} onChange={(event) => setRange(event.target.value as AdminRange)}>
              <option value="7d">{copy.ranges["7d"]}</option>
              <option value="30d">{copy.ranges["30d"]}</option>
              <option value="90d">{copy.ranges["90d"]}</option>
            </select>
          </label>
          <button type="button" className="btn" disabled={loading} onClick={() => void loadAll()}>
            {copy.refresh}
          </button>
        </div>
      </header>
      <nav className="admin-tabs" aria-label={copy.title}>
        {([
          ["overview", copy.overview],
          ["models", copy.models],
          ["users", copy.users],
          ["community", copy.community],
        ] as const).map(([key, label]) => (
          <button key={key} type="button" className={tab === key ? "active" : undefined} aria-pressed={tab === key} onClick={() => setTab(key)}>
            {label}
          </button>
        ))}
      </nav>
      {error ? <p className="admin-error" role="alert">{error}</p> : null}
      {loading && !dashboard ? <p className="admin-loading" aria-busy="true">{copy.loading}</p> : null}

      {tab === "overview" && dashboard ? (
        <div className="admin-overview">
          <div className="admin-generated">
            <span>{copy.generated}: {date.format(new Date(dashboard.generated_at))}</span>
            <span>{copy.utcNote}</span>
          </div>
          <section className="admin-kpi-grid" aria-label={copy.overview}>
            <article><span>{copy.totalUsers}</span><strong>{number.format(dashboard.summary.total_users)}</strong></article>
            <article><span>{copy.newUsers}</span><strong>{number.format(dashboard.summary.new_users)}</strong></article>
            <article><span>{copy.activeUsers}</span><strong>{number.format(dashboard.summary.active_users)}</strong></article>
            <article><span>{copy.activation}</span><strong>{formatPercent(dashboard.summary.activation_rate_pct)}</strong></article>
            <article><span>{copy.dauWauMau}</span><strong>{dashboard.summary.dau} / {dashboard.summary.wau} / {dashboard.summary.mau}</strong></article>
            <article><span>{copy.stickiness}</span><strong>{formatPercent(dashboard.summary.dau_mau_pct)}</strong></article>
            <article><span>{copy.retention}</span><strong>{formatPercent(dashboard.summary.d1_retention_pct)} / {formatPercent(dashboard.summary.d7_retention_pct)} / {formatPercent(dashboard.summary.d30_retention_pct)}</strong></article>
            <article><span>{copy.paidConversion}</span><strong>{formatPercent(dashboard.summary.paid_conversion_pct)}</strong></article>
          </section>
          <div className="admin-overview-grid">
            <section className="admin-panel admin-trend-panel">
              <header><h2>{copy.dailyTrend}</h2><div className="admin-legend"><span className="is-active">{copy.active}</span><span className="is-new">{copy.new}</span><span className="is-activated">{copy.activated}</span></div></header>
              <TrendChart snapshot={dashboard} label={copy.trendAria} />
            </section>
            <section className="admin-panel">
              <h2>{copy.funnel}</h2>
              <div className="admin-funnel">
                {dashboard.funnel.map((step) => (
                  <div key={step.key}>
                    <div><span>{translatedLabel(copy.funnelSteps, step.key, step.label)}</span><strong>{number.format(step.users)} · {formatPercent(step.overall_conversion_pct)}</strong></div>
                    <span style={{ width: `${step.overall_conversion_pct}%` }} />
                  </div>
                ))}
              </div>
            </section>
            <section className="admin-panel">
              <h2>{copy.cohortRetention}</h2>
              <div className="admin-table-scroll">
                <table><thead><tr><th>{copy.cohort}</th><th>{copy.size}</th><th>D1</th><th>D7</th><th>D30</th></tr></thead><tbody>
                  {dashboard.retention.map((cohort) => <tr key={cohort.cohort_start}><td>{cohort.cohort_start}</td><td>{cohort.cohort_size}</td><td>{formatPercent(cohort.d1_pct)}</td><td>{formatPercent(cohort.d7_pct)}</td><td>{formatPercent(cohort.d30_pct)}</td></tr>)}
                </tbody></table>
              </div>
            </section>
            <section className="admin-panel">
              <h2>{copy.featureAdoption}</h2>
              <div className="admin-feature-list">
                {dashboard.features.map((feature) => <div key={feature.key}><div><strong>{translatedLabel(copy.featureNames, feature.key, feature.label)}</strong><span>{feature.users} {copy.usersLabel} · {feature.frequency_per_user.toFixed(1)} {copy.frequency}</span></div><b>{formatPercent(feature.adoption_pct)}</b></div>)}
              </div>
            </section>
            <section className="admin-panel">
              <h2>{copy.acquisition}</h2>
              <div className="admin-table-scroll">
                <table><thead><tr><th>{copy.signupSource}</th><th>{copy.newUsers}</th><th>{copy.activated}</th><th>{copy.activation}</th></tr></thead><tbody>
                  {dashboard.acquisition.map((source) => <tr key={source.key}><td>{translatedLabel(copy.acquisitionSources, source.key, source.label)}</td><td>{number.format(source.new_users)}</td><td>{number.format(source.activated_users)}</td><td>{formatPercent(source.activation_rate_pct)}</td></tr>)}
                </tbody></table>
              </div>
              <dl className="admin-time-to-value"><div><dt>{copy.timeToValue} · {copy.median}</dt><dd>{dashboard.time_to_value.median_minutes === null ? "—" : `${number.format(dashboard.time_to_value.median_minutes)} min`}</dd></div><div><dt>{copy.timeToValue} · {copy.p90}</dt><dd>{dashboard.time_to_value.p90_minutes === null ? "—" : `${number.format(dashboard.time_to_value.p90_minutes)} min`}</dd></div></dl>
            </section>
            <section className="admin-panel">
              <h2>{copy.reliability}</h2>
              <dl className="admin-definition-grid"><div><dt>{copy.jobSuccess}</dt><dd>{formatPercent(dashboard.reliability.job_success_pct)}</dd></div><div><dt>{copy.modelSuccess}</dt><dd>{formatPercent(dashboard.reliability.model_success_pct)}</dd></div><div><dt>{copy.rateLimited}</dt><dd>{formatPercent(dashboard.reliability.model_rate_limited_pct)}</dd></div><div><dt>{copy.p95Latency}</dt><dd>{dashboard.reliability.p95_model_latency_ms ? `${number.format(dashboard.reliability.p95_model_latency_ms)} ms` : "—"}</dd></div><div><dt>{copy.quotaExhausted}</dt><dd>{number.format(dashboard.reliability.quota_exhausted_users)}</dd></div></dl>
            </section>
            <section className="admin-panel">
              <h2>{copy.monetization}</h2>
              <dl className="admin-definition-grid"><div><dt>Free / Plus / Pro</dt><dd>{dashboard.monetization.free_users} / {dashboard.monetization.plus_users} / {dashboard.monetization.pro_users}</dd></div><div><dt>{copy.credits}</dt><dd>{number.format(dashboard.monetization.consumed_ai_credits)}</dd></div><div><dt>{copy.tokens}</dt><dd>{number.format(dashboard.monetization.model_input_tokens + dashboard.monetization.model_output_tokens)}</dd></div><div><dt>{copy.estimated}</dt><dd>{number.format(dashboard.monetization.estimated_usage_requests)}</dd></div></dl>
            </section>
          </div>
          <section className="admin-panel admin-metric-definitions">
            <h2>{copy.definitions}</h2>
            <dl>{dashboard.definitions.map((definition) => {
              const translated = copy.metricDefinitions[
                definition.key as keyof typeof copy.metricDefinitions
              ];
              return <div key={definition.key}><dt>{translated?.label ?? definition.label}</dt><dd>{translated?.definition ?? definition.definition}</dd></div>;
            })}</dl>
          </section>
        </div>
      ) : null}

      {tab === "models" ? (
        <section className="admin-panel admin-model-panel">
          <header><div><h2>{copy.models}</h2><p>{copy.modelPolicyBody}</p></div></header>
          <div className="admin-model-list">
            {models.map((item) => (
              <article key={item.provider}>
                <div className="admin-model-title"><span>{item.display_name}</span><strong>{item.model}</strong></div>
                <label><span>{copy.globallyEnabled}</span><input type="checkbox" checked={item.enabled} disabled={savingProvider === item.provider} onChange={() => void toggleModel(item, "enabled")} /></label>
                <label><span>{copy.assistantEnabled}</span><input type="checkbox" checked={item.assistant_enabled} disabled={!item.enabled || savingProvider === item.provider} onChange={() => void toggleModel(item, "assistant_enabled")} /></label>
                <label><span>{copy.jobEnabled}</span><input type="checkbox" checked={item.job_enabled} disabled={!item.enabled || savingProvider === item.provider} onChange={() => void toggleModel(item, "job_enabled")} /></label>
                <small>{savingProvider === item.provider ? copy.saving : `${copy.lastChange}: ${date.format(new Date(item.updated_at))}`}</small>
              </article>
            ))}
          </div>
        </section>
      ) : null}

      {tab === "users" ? (
        <section className="admin-panel admin-users-panel">
          <header><div><h2>{copy.users}</h2><p>{copy.userPrivacy}</p></div><div className="admin-users-toolbar"><form onSubmit={submitSearch}><label><span className="sr-only">{copy.searchEmail}</span><input type="search" value={userSearch} onChange={(event) => setUserSearch(event.target.value)} placeholder={copy.searchEmail} /></label><button type="submit" className="btn">{copy.search}</button></form><button type="button" className="btn admin-user-export" disabled={exportingUsers} onClick={() => void startUserExport()}>{exportingUsers ? copy.exportingUsers : copy.exportUsers}</button></div></header>
          <p className="admin-user-export-scope">{copy.exportScope}</p>
          {userExportMessage ? <p className="admin-user-export-status" role="status">{userExportMessage}</p> : null}
          <div className="admin-table-scroll"><table><thead><tr><th>{copy.email}</th><th>{copy.plan}</th><th>{copy.lastSignIn}</th><th>{copy.usage}</th></tr></thead><tbody>
            {users.map((user) => <tr key={user.id}><td><strong>{user.email}</strong><small>{date.format(new Date(user.created_at))}</small></td><td><strong>{user.plan.toUpperCase()}</strong><small>{user.subscription_status}</small></td><td>{user.last_sign_in_at ? date.format(new Date(user.last_sign_in_at)) : "—"}</td><td><strong>{number.format(user.period_consumed_ai_credits)}</strong><small>{number.format(user.period_request_count)} {copy.requests} · {number.format(user.period_total_tokens)} {copy.tokens} · {number.format(user.period_remaining_ai_credits)} {copy.remaining}</small></td></tr>)}
            {users.length === 0 ? <tr><td colSpan={4}>{copy.noUsers}</td></tr> : null}
          </tbody></table></div>
          <div className="admin-pager"><button type="button" className="btn" disabled={loading || userPage <= 1} onClick={() => setUserPage((current) => Math.max(1, current - 1))}>{copy.previous}</button><span>{copy.page} {userPage} {copy.of} {Math.max(1, Math.ceil(usersTotal / 25))}{locale === "zh-CN" ? " 页" : ""}</span><button type="button" className="btn" disabled={loading || userPage >= Math.max(1, Math.ceil(usersTotal / 25))} onClick={() => setUserPage((current) => current + 1)}>{copy.next}</button></div>
        </section>
      ) : null}

      {tab === "community" ? (
        <div className="admin-community-grid">
          <section className="admin-panel">
            <h2>{copy.topics}</h2>
            <div className="admin-table-scroll"><table><thead><tr><th>{copy.topic}</th><th>{copy.author}</th><th>{copy.comments}</th><th>{copy.reports}</th><th>{copy.status}</th><th /></tr></thead><tbody>
              {topics.map((topic) => <tr key={topic.id}><td><strong>{topic.title}</strong><small>{date.format(new Date(topic.created_at))}</small></td><td>{topic.author_email}</td><td>{topic.comment_count}</td><td>{topic.report_count}</td><td>{topic.status === "removed" ? copy.removed : copy.active}</td><td><button type="button" className="btn btn-danger" disabled={topic.status === "removed"} onClick={(event) => { moderationTriggerRef.current = event.currentTarget; setModeratingTopic(topic); }}>{copy.remove}</button></td></tr>)}
            </tbody></table></div>
            <div className="admin-pager"><button type="button" className="btn" disabled={loading || topicPage <= 1} onClick={() => setTopicPage((current) => Math.max(1, current - 1))}>{copy.previous}</button><span>{copy.page} {topicPage} {copy.of} {Math.max(1, Math.ceil(topicsTotal / 25))}{locale === "zh-CN" ? " 页" : ""}</span><button type="button" className="btn" disabled={loading || topicPage >= Math.max(1, Math.ceil(topicsTotal / 25))} onClick={() => setTopicPage((current) => current + 1)}>{copy.next}</button></div>
          </section>
          <section className="admin-panel">
            <h2>{copy.audit}</h2>
            <div className="admin-table-scroll"><table><thead><tr><th>{copy.time}</th><th>{copy.actor}</th><th>{copy.action}</th><th>{copy.target}</th></tr></thead><tbody>
              {audit.map((row) => <tr key={row.id}><td>{date.format(new Date(row.created_at))}</td><td>{row.actor_email}</td><td><strong>{row.action}</strong><small>{row.reason}</small></td><td>{row.target_type}{row.target_id ? ` · ${row.target_id}` : ""}</td></tr>)}
              {audit.length === 0 ? <tr><td colSpan={4}>{copy.noAudit}</td></tr> : null}
            </tbody></table></div>
          </section>
        </div>
      ) : null}

      {moderatingTopic ? (
        <div className="admin-dialog-backdrop" role="presentation">
          <section ref={moderationDialogRef} role="dialog" aria-modal="true" aria-labelledby="admin-remove-title" className="admin-dialog">
            <h2 id="admin-remove-title">{copy.removeTitle}</h2>
            <strong>{moderatingTopic.title}</strong>
            <p>{copy.removeWarning}</p>
            <label><span>{copy.reason}</span><textarea ref={moderationReasonRef} value={moderationReason} minLength={8} maxLength={500} onChange={(event) => setModerationReason(event.target.value)} placeholder={copy.reasonPlaceholder} /></label>
            <div><button type="button" className="btn" disabled={moderating} onClick={() => closeModeration()}>{copy.cancel}</button><button type="button" className="btn btn-danger" disabled={moderating || moderationReason.trim().length < 8} onClick={() => void confirmModeration()}>{copy.confirmRemove}</button></div>
          </section>
        </div>
      ) : null}
    </main>
  );
}
