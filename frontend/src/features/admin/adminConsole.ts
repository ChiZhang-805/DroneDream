import { getAuthAccessToken } from "../auth/authTokenStore";
import {
  FetchDeadlineError,
  FetchResponseSizeError,
  fetchWithDeadline,
} from "../../api/fetchWithDeadline";
import type { SoftwareEditionId } from "../licensing/softwareLicense";

export type AdminRange = "7d" | "30d" | "90d";
export type ManagedProviderId = "openai" | "deepseek" | "qwen";

export interface AdminAccessSnapshot {
  authorized: boolean;
  role: "owner" | "admin" | null;
  permissions: string[];
}

export interface AdminMetricDefinition {
  key: string;
  label: string;
  definition: string;
}

export interface AdminSummaryMetrics {
  total_users: number;
  new_users: number;
  active_users: number;
  dau: number;
  wau: number;
  mau: number;
  dau_mau_pct: number;
  activation_rate_pct: number;
  d1_retention_pct: number;
  d7_retention_pct: number;
  d30_retention_pct: number;
  paying_users: number;
  paid_conversion_pct: number;
}

export interface AdminDailyMetric {
  date: string;
  new_users: number;
  active_users: number;
  activated_users: number;
  successful_jobs: number;
  model_requests: number;
}

export interface AdminFunnelStep {
  key: string;
  label: string;
  users: number;
  overall_conversion_pct: number;
  previous_step_conversion_pct: number;
}

export interface AdminRetentionCohort {
  cohort_start: string;
  cohort_size: number;
  d1_pct: number | null;
  d7_pct: number | null;
  d30_pct: number | null;
}

export interface AdminFeatureMetric {
  key: string;
  label: string;
  users: number;
  adoption_pct: number;
  frequency_per_user: number;
}

export interface AdminAcquisitionMetric {
  key: string;
  label: string;
  new_users: number;
  activated_users: number;
  activation_rate_pct: number;
}

export interface AdminTimeToValueMetrics {
  median_minutes: number | null;
  p90_minutes: number | null;
}

export interface AdminReliabilityMetrics {
  job_success_pct: number;
  model_success_pct: number;
  model_rate_limited_pct: number;
  p95_model_latency_ms: number | null;
  quota_exhausted_users: number;
}

export interface AdminMonetizationMetrics {
  free_users: number;
  plus_users: number;
  pro_users: number;
  consumed_ai_credits: number;
  model_input_tokens: number;
  model_output_tokens: number;
  estimated_usage_requests: number;
}

export interface AdminDashboardSnapshot {
  generated_at: string;
  timezone: "UTC";
  range: AdminRange;
  summary: AdminSummaryMetrics;
  daily: AdminDailyMetric[];
  funnel: AdminFunnelStep[];
  retention: AdminRetentionCohort[];
  acquisition: AdminAcquisitionMetric[];
  time_to_value: AdminTimeToValueMetrics;
  features: AdminFeatureMetric[];
  reliability: AdminReliabilityMetrics;
  monetization: AdminMonetizationMetrics;
  definitions: AdminMetricDefinition[];
}

export interface AdminManagedModel {
  provider: ManagedProviderId;
  display_name: string;
  model: string;
  enabled: boolean;
  assistant_enabled: boolean;
  job_enabled: boolean;
  version: number;
  updated_at: string;
  updated_by_email: string | null;
}

export interface AdminUserRow {
  id: string;
  display_name: string;
  email: string;
  created_at: string;
  last_sign_in_at: string | null;
  plan: "free" | "plus" | "pro";
  billing_scope: "individual" | "business";
  organization_name: string | null;
  subscription_status: string;
  licensed_editions: SoftwareEditionId[];
  period_consumed_ai_credits: number;
  period_remaining_ai_credits: number;
  period_request_count: number;
  period_total_tokens: number;
}

export interface AdminTopicRow {
  id: string;
  title: string;
  author_email: string;
  created_at: string;
  comment_count: number;
  report_count: number;
  status: "published" | "removed";
}

export interface AdminAuditRow {
  id: string;
  created_at: string;
  actor_email: string;
  action: string;
  target_type: string;
  target_id: string | null;
  reason: string | null;
}

export interface AdminPageResult<T> {
  items: T[];
  page: number;
  page_size: number;
  total: number;
}

export interface AdminUserExport {
  blob: Blob;
  file_name: string;
  row_count: number | null;
}

export class AdminConsoleError extends Error {
  readonly code: string;
  readonly status: number;

  constructor(code: string, message: string, status: number) {
    super(message);
    this.name = "AdminConsoleError";
    this.code = code;
    this.status = status;
  }
}

function adminExportTransportError(error: unknown): AdminConsoleError {
  if (error instanceof AdminConsoleError) return error;
  if (error instanceof FetchResponseSizeError) {
    return new AdminConsoleError("EXPORT_TOO_LARGE", error.message, error.httpStatus);
  }
  if (error instanceof FetchDeadlineError) {
    return new AdminConsoleError("EXPORT_TIMEOUT", error.message, 0);
  }
  return new AdminConsoleError(
    "EXPORT_NETWORK_ERROR",
    error instanceof Error ? error.message : "The user export could not be downloaded.",
    0,
  );
}

const ADMIN_TIMEOUT_MS = 20_000;
const ADMIN_RESPONSE_MAX_BYTES = 2 * 1024 * 1024;
const ADMIN_EXPORT_TIMEOUT_MS = 60_000;
const ADMIN_EXPORT_MAX_BYTES = 20 * 1024 * 1024;

function deriveAdminConsoleUrl(): string {
  const explicit = (
    import.meta.env.VITE_ADMIN_CONSOLE_URL as string | undefined
  )?.trim().replace(/\/+$/u, "");
  if (explicit) return explicit;
  const supabaseUrl = (
    import.meta.env.VITE_SUPABASE_URL as string | undefined
  )?.trim().replace(/\/+$/u, "");
  return supabaseUrl ? `${supabaseUrl}/functions/v1/admin-console` : "";
}

export const adminConsoleUrl = deriveAdminConsoleUrl();

function adminPreviewEnabled(): boolean {
  return import.meta.env.DEV
    && new URLSearchParams(window.location.search).get("adminPreview") === "1";
}

function authenticatedHeaders(accept = "application/json"): Record<string, string> {
  const token = getAuthAccessToken();
  if (!token) {
    throw new AdminConsoleError(
      "AUTHENTICATION_REQUIRED",
      "Sign in before opening the administration console.",
      401,
    );
  }
  return {
    Authorization: `Bearer ${token}`,
    "Content-Type": "application/json",
    Accept: accept,
  };
}

function safeCsvCell(value: unknown): string {
  let normalized = Array.isArray(value)
    ? value.join("|")
    : value === null || value === undefined ? "" : String(value);
  if (/^[=+\-@]/u.test(normalized)) normalized = `'${normalized}`;
  return `"${normalized.replaceAll('"', '""')}"`;
}

function previewUserExport(search: string): AdminUserExport {
  const query = search.trim().toLowerCase();
  const rows = query
    ? PREVIEW_USERS.filter((user) => user.email.toLowerCase().includes(query))
    : PREVIEW_USERS;
  const fields: Array<keyof AdminUserRow> = [
    "id",
    "email",
    "created_at",
    "last_sign_in_at",
    "plan",
    "subscription_status",
    "period_consumed_ai_credits",
    "period_remaining_ai_credits",
    "period_request_count",
    "period_total_tokens",
  ];
  const csv = [
    fields.map((field) => safeCsvCell(field)).join(","),
    ...rows.map((user) => fields.map((field) => safeCsvCell(user[field])).join(",")),
  ].join("\r\n");
  return {
    blob: new Blob(["\ufeff", csv, "\r\n"], { type: "text/csv;charset=utf-8" }),
    file_name: "DroneDream-users-preview.csv",
    row_count: rows.length,
  };
}

function exportFileName(response: Response): string {
  const disposition = response.headers.get("Content-Disposition") ?? "";
  const match = /filename="?([A-Za-z0-9._-]+)"?/iu.exec(disposition);
  return match?.[1]?.toLowerCase().endsWith(".csv")
    ? match[1]
    : `DroneDream-users-${new Date().toISOString().slice(0, 10)}.csv`;
}

async function adminRequest<T>(path: string, init?: RequestInit): Promise<T> {
  if (!adminConsoleUrl) {
    throw new AdminConsoleError(
      "SERVICE_NOT_CONFIGURED",
      "The administration service is not configured in this build.",
      503,
    );
  }
  let response: Response;
  try {
    response = await fetchWithDeadline(
      `${adminConsoleUrl}${path}`,
      {
        ...init,
        headers: {
          ...authenticatedHeaders(),
          ...(init?.headers ?? {}),
        },
      },
      ADMIN_TIMEOUT_MS,
      ADMIN_RESPONSE_MAX_BYTES,
    );
  } catch (error) {
    if (error instanceof AdminConsoleError) throw error;
    if (error instanceof FetchResponseSizeError) {
      throw new AdminConsoleError("RESPONSE_TOO_LARGE", error.message, error.httpStatus);
    }
    throw new AdminConsoleError(
      "NETWORK_ERROR",
      error instanceof Error ? error.message : "The administration service could not be reached.",
      0,
    );
  }
  let payload: unknown;
  try {
    payload = await response.json();
  } catch {
    throw new AdminConsoleError(
      "INVALID_RESPONSE",
      `The administration service returned HTTP ${response.status} without JSON.`,
      response.status,
    );
  }
  const envelope = payload as {
    data?: T;
    error?: { code?: string; message?: string };
  };
  if (response.ok && envelope.data !== undefined) return envelope.data;
  throw new AdminConsoleError(
    envelope.error?.code ?? "ADMIN_REQUEST_FAILED",
    envelope.error?.message ?? `The administration request failed with HTTP ${response.status}.`,
    response.status,
  );
}

const PREVIEW_MODELS: AdminManagedModel[] = [
  {
    provider: "openai",
    display_name: "GPT",
    model: "gpt-4.1",
    enabled: true,
    assistant_enabled: true,
    job_enabled: true,
    version: 4,
    updated_at: "2026-08-02T01:20:00Z",
    updated_by_email: "owner@example.test",
  },
  {
    provider: "deepseek",
    display_name: "DeepSeek",
    model: "deepseek-chat",
    enabled: true,
    assistant_enabled: true,
    job_enabled: true,
    version: 2,
    updated_at: "2026-08-02T01:16:00Z",
    updated_by_email: "owner@example.test",
  },
  {
    provider: "qwen",
    display_name: "Qwen",
    model: "qwen-plus",
    enabled: true,
    assistant_enabled: true,
    job_enabled: true,
    version: 3,
    updated_at: "2026-08-02T01:12:00Z",
    updated_by_email: "owner@example.test",
  },
];

function previewDashboard(range: AdminRange): AdminDashboardSnapshot {
  const daily = Array.from({ length: range === "7d" ? 7 : 14 }, (_, index) => ({
    date: new Date(Date.UTC(2026, 6, 20 + index)).toISOString().slice(0, 10),
    new_users: 8 + ((index * 5) % 13),
    active_users: 34 + index * 3 + (index % 3) * 4,
    activated_users: 5 + ((index * 3) % 9),
    successful_jobs: 18 + index * 2,
    model_requests: 55 + index * 7,
  }));
  return {
    generated_at: "2026-08-02T02:00:00Z",
    timezone: "UTC",
    range,
    summary: {
      total_users: 1284,
      new_users: 146,
      active_users: 438,
      dau: 91,
      wau: 304,
      mau: 438,
      dau_mau_pct: 20.8,
      activation_rate_pct: 61.4,
      d1_retention_pct: 42.1,
      d7_retention_pct: 24.8,
      d30_retention_pct: 14.3,
      paying_users: 87,
      paid_conversion_pct: 6.8,
    },
    daily,
    funnel: [
      { key: "registered", label: "Registered", users: 146, overall_conversion_pct: 100, previous_step_conversion_pct: 100 },
      { key: "runtime_ready", label: "Runtime ready", users: 118, overall_conversion_pct: 80.8, previous_step_conversion_pct: 80.8 },
      { key: "first_draft", label: "First draft", users: 103, overall_conversion_pct: 70.5, previous_step_conversion_pct: 87.3 },
      { key: "first_job", label: "First job", users: 91, overall_conversion_pct: 62.3, previous_step_conversion_pct: 88.3 },
      { key: "first_success", label: "First successful run", users: 78, overall_conversion_pct: 53.4, previous_step_conversion_pct: 85.7 },
    ],
    retention: [
      { cohort_start: "2026-07-01", cohort_size: 102, d1_pct: 43.1, d7_pct: 25.5, d30_pct: 14.7 },
      { cohort_start: "2026-07-08", cohort_size: 119, d1_pct: 44.5, d7_pct: 26.1, d30_pct: null },
      { cohort_start: "2026-07-15", cohort_size: 131, d1_pct: 40.5, d7_pct: 23.7, d30_pct: null },
      { cohort_start: "2026-07-22", cohort_size: 146, d1_pct: 42.1, d7_pct: null, d30_pct: null },
    ],
    acquisition: [
      { key: "direct", label: "Direct", new_users: 56, activated_users: 36, activation_rate_pct: 64.3 },
      { key: "documentation", label: "Documentation", new_users: 34, activated_users: 24, activation_rate_pct: 70.6 },
      { key: "community", label: "Community", new_users: 22, activated_users: 14, activation_rate_pct: 63.6 },
      { key: "referral", label: "Referral", new_users: 18, activated_users: 11, activation_rate_pct: 61.1 },
      { key: "unknown", label: "Unknown", new_users: 16, activated_users: 5, activation_rate_pct: 31.3 },
    ],
    time_to_value: { median_minutes: 42, p90_minutes: 310 },
    features: [
      { key: "assistant", label: "Tuning chat", users: 318, adoption_pct: 72.6, frequency_per_user: 4.8 },
      { key: "fixed_scenarios", label: "Fixed scenarios", users: 204, adoption_pct: 46.6, frequency_per_user: 2.1 },
      { key: "custom_tracks", label: "Custom tracks", users: 171, adoption_pct: 39.0, frequency_per_user: 1.7 },
      { key: "community", label: "Community", users: 96, adoption_pct: 21.9, frequency_per_user: 3.4 },
    ],
    reliability: {
      job_success_pct: 92.7,
      model_success_pct: 98.2,
      model_rate_limited_pct: 0.7,
      p95_model_latency_ms: 2840,
      quota_exhausted_users: 11,
    },
    monetization: {
      free_users: 1197,
      plus_users: 65,
      pro_users: 22,
      consumed_ai_credits: 183421,
      model_input_tokens: 9482300,
      model_output_tokens: 2431000,
      estimated_usage_requests: 4,
    },
    definitions: [
      { key: "active_user", label: "Active user", definition: "A signed-in user who reaches a value event: assistant turn, draft save, job action, report export, or community contribution." },
      { key: "activated_user", label: "Activated user", definition: "A newly registered user who completes a first successful simulation job within seven days." },
      { key: "retention", label: "Retention", definition: "A registered cohort member who returns for another value event on the measured day." },
      { key: "time_to_value", label: "Time to first value", definition: "Elapsed time from verified registration to the first successful simulation job." },
    ],
  };
}

const PREVIEW_USERS: AdminUserRow[] = [
  { id: "usr-001", display_name: "Avery Lin", email: "pilot.one@example.test", created_at: "2026-07-02T08:00:00Z", last_sign_in_at: "2026-08-01T22:14:00Z", plan: "pro", billing_scope: "individual", organization_name: null, subscription_status: "active", licensed_editions: ["universal", "sim", "lab", "field"], period_consumed_ai_credits: 1840, period_remaining_ai_credits: 8160, period_request_count: 43, period_total_tokens: 231440 },
  { id: "usr-002", display_name: "Morgan Wu", email: "pilot.two@example.test", created_at: "2026-07-14T11:30:00Z", last_sign_in_at: "2026-08-01T19:05:00Z", plan: "plus", billing_scope: "business", organization_name: "Northwind Robotics", subscription_status: "active", licensed_editions: ["sim", "lab"], period_consumed_ai_credits: 640, period_remaining_ai_credits: 2360, period_request_count: 19, period_total_tokens: 97220 },
  { id: "usr-003", display_name: "Riley Chen", email: "pilot.three@example.test", created_at: "2026-07-28T04:40:00Z", last_sign_in_at: null, plan: "free", billing_scope: "individual", organization_name: null, subscription_status: "active", licensed_editions: [], period_consumed_ai_credits: 0, period_remaining_ai_credits: 100, period_request_count: 0, period_total_tokens: 0 },
];

const PREVIEW_TOPICS: AdminTopicRow[] = [
  { id: "topic-001", title: "Stable hover before entering a circle track", author_email: "pilot.one@example.test", created_at: "2026-08-01T12:10:00Z", comment_count: 12, report_count: 0, status: "published" },
  { id: "topic-002", title: "Comparing wind-search parameter ranges", author_email: "pilot.two@example.test", created_at: "2026-08-01T08:45:00Z", comment_count: 7, report_count: 2, status: "published" },
];

const PREVIEW_AUDIT: AdminAuditRow[] = [
  { id: "audit-001", created_at: "2026-08-02T01:20:00Z", actor_email: "owner@example.test", action: "model_policy.updated", target_type: "model_provider", target_id: "openai", reason: "Scheduled availability review" },
];

export async function getAdminAccess(): Promise<AdminAccessSnapshot> {
  if (adminPreviewEnabled()) {
    return { authorized: true, role: "owner", permissions: ["dashboard.read", "models.read", "models.write", "users.read", "users.export", "users.delete", "community.read", "community.remove", "audit.read"] };
  }
  return adminRequest<AdminAccessSnapshot>("/access");
}

export async function getAdminDashboard(range: AdminRange): Promise<AdminDashboardSnapshot> {
  if (adminPreviewEnabled()) return previewDashboard(range);
  return adminRequest<AdminDashboardSnapshot>(`/dashboard?range=${range}`);
}

export async function listAdminModels(): Promise<AdminManagedModel[]> {
  if (adminPreviewEnabled()) return structuredClone(PREVIEW_MODELS);
  return adminRequest<AdminManagedModel[]>("/models");
}

export async function updateAdminModel(
  provider: ManagedProviderId,
  patch: Pick<AdminManagedModel, "enabled" | "assistant_enabled" | "job_enabled" | "version">,
): Promise<AdminManagedModel> {
  if (adminPreviewEnabled()) {
    const current = PREVIEW_MODELS.find((model) => model.provider === provider);
    if (!current) throw new AdminConsoleError("NOT_FOUND", "Model provider not found.", 404);
    return { ...current, ...patch, version: current.version + 1 };
  }
  return adminRequest<AdminManagedModel>(`/models/${provider}`, {
    method: "PATCH",
    body: JSON.stringify(patch),
  });
}

export async function listAdminUsers(
  page: number,
  search: string,
): Promise<AdminPageResult<AdminUserRow>> {
  if (adminPreviewEnabled()) {
    const query = search.trim().toLowerCase();
    const items = query
      ? PREVIEW_USERS.filter((user) => user.email.toLowerCase().includes(query))
      : PREVIEW_USERS;
    return { items, page, page_size: 25, total: items.length };
  }
  const params = new URLSearchParams({ page: String(page), page_size: "25" });
  if (search.trim()) params.set("search", search.trim());
  return adminRequest<AdminPageResult<AdminUserRow>>(`/users?${params}`);
}

export async function deleteAdminUser(userId: string, reason: string): Promise<void> {
  if (adminPreviewEnabled()) return;
  await adminRequest<{ deleted_user_id: string; deleted: true }>(
    `/users/${encodeURIComponent(userId)}/delete`,
    {
      method: "POST",
      body: JSON.stringify({ reason: reason.trim() }),
    },
  );
}

export async function exportAdminUsers(search: string): Promise<AdminUserExport> {
  if (adminPreviewEnabled()) return previewUserExport(search);
  if (!adminConsoleUrl) {
    throw new AdminConsoleError(
      "SERVICE_NOT_CONFIGURED",
      "The administration service is not configured in this build.",
      503,
    );
  }
  let response: Response;
  try {
    response = await fetchWithDeadline(
      `${adminConsoleUrl}/users/export`,
      {
        method: "POST",
        headers: authenticatedHeaders("text/csv"),
        body: JSON.stringify({
          format: "csv",
          search: search.trim() || null,
        }),
      },
      ADMIN_EXPORT_TIMEOUT_MS,
      ADMIN_EXPORT_MAX_BYTES,
    );
  } catch (error) {
    throw adminExportTransportError(error);
  }
  if (!response.ok) {
    let message = `The user export failed with HTTP ${response.status}.`;
    let code = "USER_EXPORT_FAILED";
    try {
      const envelope = await response.json() as {
        error?: { code?: string; message?: string };
      };
      code = envelope.error?.code ?? code;
      message = envelope.error?.message ?? message;
    } catch {
      // Keep the bounded generic message; never reflect an arbitrary response body.
    }
    throw new AdminConsoleError(code, message, response.status);
  }
  const contentType = response.headers.get("Content-Type")?.toLowerCase() ?? "";
  if (!contentType.startsWith("text/csv")) {
    throw new AdminConsoleError(
      "INVALID_EXPORT_TYPE",
      "The administration service returned a non-CSV user export.",
      response.status,
    );
  }
  const disposition = response.headers.get("Content-Disposition")?.toLowerCase() ?? "";
  const cacheControl = response.headers.get("Cache-Control")?.toLowerCase() ?? "";
  if (!disposition.startsWith("attachment") || !cacheControl.includes("no-store")) {
    throw new AdminConsoleError(
      "INSECURE_EXPORT_RESPONSE",
      "The user export response did not include the required attachment and no-store controls.",
      response.status,
    );
  }
  let blob: Blob;
  try {
    // Content-Length is optional. The bounded response stream can still reject
    // here when a chunked export crosses the limit or stalls after headers.
    blob = await response.blob();
  } catch (error) {
    throw adminExportTransportError(error);
  }
  if (blob.size === 0) {
    throw new AdminConsoleError(
      "EMPTY_EXPORT",
      "The administration service returned an empty user export.",
      response.status,
    );
  }
  const rowCountHeader = response.headers.get("X-Export-Row-Count");
  const parsedRowCount = rowCountHeader && /^\d+$/u.test(rowCountHeader)
    ? Number(rowCountHeader)
    : null;
  const rowCount = parsedRowCount !== null && Number.isSafeInteger(parsedRowCount)
    ? parsedRowCount
    : null;
  return { blob, file_name: exportFileName(response), row_count: rowCount };
}

export async function listAdminTopics(page: number): Promise<AdminPageResult<AdminTopicRow>> {
  if (adminPreviewEnabled()) {
    return { items: PREVIEW_TOPICS, page, page_size: 25, total: PREVIEW_TOPICS.length };
  }
  return adminRequest<AdminPageResult<AdminTopicRow>>(`/community/topics?page=${page}&page_size=25`);
}

export async function removeAdminTopic(topicId: string, reason: string): Promise<void> {
  if (adminPreviewEnabled()) return;
  await adminRequest<{ removed: true }>(`/community/topics/${encodeURIComponent(topicId)}/remove`, {
    method: "POST",
    body: JSON.stringify({ reason: reason.trim() }),
  });
}

export async function listAdminAudit(page: number): Promise<AdminPageResult<AdminAuditRow>> {
  if (adminPreviewEnabled()) {
    return { items: PREVIEW_AUDIT, page, page_size: 25, total: PREVIEW_AUDIT.length };
  }
  return adminRequest<AdminPageResult<AdminAuditRow>>(`/audit?page=${page}&page_size=25`);
}
