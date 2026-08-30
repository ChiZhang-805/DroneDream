import {
  createClient,
  type SupabaseClient,
} from "npm:@supabase/supabase-js@2.110.8";
import {
  BoundedRequestError,
  readBoundedJsonObject,
} from "../_shared/bounded_request.ts";
import {
  sensitiveAllowedOrigins,
  SensitiveCorsError,
  sensitiveCorsHeaders,
} from "../_shared/sensitive_cors.ts";

type JsonRecord = Record<string, unknown>;
type AdminRole = "owner" | "admin";
type Provider = "openai" | "deepseek" | "qwen";
type SoftwareEdition = "universal" | "sim" | "lab" | "field" | "autonomy";

const ALL_PERMISSIONS = [
  "dashboard.read",
  "models.read",
  "models.write",
  "users.read",
  "users.export",
  "users.delete",
  "community.read",
  "community.remove",
  "audit.read",
] as const;
type Permission = typeof ALL_PERMISSIONS[number];

const DEFAULT_ALLOWED_ORIGINS = [
  "https://getdronedream.com",
  "https://www.getdronedream.com",
  "http://localhost:5173",
  "http://127.0.0.1:5173",
  "http://tauri.localhost",
  "tauri://localhost",
];
const MAX_JSON_BYTES = 16 * 1024;
const MAX_SEARCH_LENGTH = 96;
const MAX_PAGE_SIZE = 100;
const MAX_EXPORT_ROWS = 50_000;
const MAX_EXPORT_BYTES = 20 * 1024 * 1024;
const EXPORT_DEADLINE_MS = 60_000;

export interface AdminIdentity {
  userId: string;
  role: AdminRole;
  permissions: Permission[];
}

export interface SafeAdminUser {
  id: string;
  display_name: string;
  email: string;
  created_at: string;
  last_sign_in_at: string | null;
  plan: string;
  billing_scope: "individual" | "business";
  organization_name: string | null;
  subscription_status: string;
  licensed_editions: SoftwareEdition[];
  period_consumed_ai_credits: number;
  period_remaining_ai_credits: number;
  period_request_count: number;
  period_total_tokens: number;
}

export interface AdminConsoleDependencies {
  nowMs(): number;
  resolveIdentity(token: string): Promise<AdminIdentity | null>;
  dashboard(range: "7d" | "30d" | "90d"): Promise<JsonRecord>;
  listModels(): Promise<JsonRecord[]>;
  updateModel(
    actorUserId: string,
    provider: Provider,
    body: ModelPatch,
  ): Promise<JsonRecord>;
  listUsers(search: string | null): Promise<SafeAdminUser[]>;
  deleteUser(
    actorUserId: string,
    targetUserId: string,
    reason: string,
  ): Promise<JsonRecord>;
  listTopics(
    page: number,
    pageSize: number,
  ): Promise<{ rows: JsonRecord[]; total: number }>;
  removeTopic(
    actorUserId: string,
    topicId: string,
    reason: string,
  ): Promise<JsonRecord>;
  listAudit(
    page: number,
    pageSize: number,
  ): Promise<{ rows: JsonRecord[]; total: number }>;
  recordExportAudit(
    actorUserId: string,
    outcome: "succeeded" | "failed",
    filterHash: string,
    rowCount: number,
    failureClass?: string,
  ): Promise<void>;
}

export interface ModelPatch {
  enabled: boolean;
  assistant_enabled: boolean;
  job_enabled: boolean;
  version: number;
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

function requiredEnv(name: string): string {
  const value = Deno.env.get(name)?.trim();
  if (!value) {
    throw new AdminConsoleError(
      "SERVICE_NOT_CONFIGURED",
      "The administration service is not configured.",
      503,
    );
  }
  return value;
}

function allowedOrigins(): Set<string> {
  return sensitiveAllowedOrigins(
    Deno.env.get("ADMIN_CONSOLE_ALLOWED_ORIGINS"),
    DEFAULT_ALLOWED_ORIGINS,
  );
}

function corsHeaders(request: Request): HeadersInit {
  if (!request.headers.get("Origin")) return {};
  try {
    return {
      ...sensitiveCorsHeaders(request, allowedOrigins()),
      "Access-Control-Allow-Headers":
        "authorization, apikey, content-type, x-client-info",
      "Access-Control-Allow-Methods": "GET, PATCH, POST, OPTIONS",
      "Access-Control-Expose-Headers":
        "content-disposition, x-export-row-count",
    };
  } catch (error) {
    if (error instanceof SensitiveCorsError) {
      throw new AdminConsoleError(error.code, error.message, error.status);
    }
    throw error;
  }
}

function jsonResponse(
  request: Request,
  status: number,
  body: JsonRecord,
): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: {
      "Content-Type": "application/json; charset=utf-8",
      "Cache-Control": "private, no-store",
      "X-Content-Type-Options": "nosniff",
      ...corsHeaders(request),
    },
  });
}

function errorResponse(request: Request, error: unknown): Response {
  if (error instanceof BoundedRequestError) {
    return jsonResponse(request, error.status, {
      error: { code: error.code, message: error.message },
    });
  }
  if (error instanceof AdminConsoleError) {
    const headersAllowed = error.code !== "ORIGIN_NOT_ALLOWED" &&
      error.code !== "ORIGIN_CONFIGURATION_INVALID";
    if (!headersAllowed) {
      return new Response(
        JSON.stringify({
          error: { code: error.code, message: error.message },
        }),
        {
          status: error.status,
          headers: {
            "Content-Type": "application/json; charset=utf-8",
            "Cache-Control": "private, no-store",
          },
        },
      );
    }
    return jsonResponse(request, error.status, {
      error: { code: error.code, message: error.message },
    });
  }
  console.error("admin-console unexpected failure", "INTERNAL_ERROR");
  return jsonResponse(request, 500, {
    error: {
      code: "INTERNAL_ERROR",
      message: "The administration request could not be completed.",
    },
  });
}

function bearerToken(request: Request): string {
  const match = /^Bearer\s+(.+)$/iu.exec(
    request.headers.get("Authorization")?.trim() ?? "",
  );
  if (!match?.[1]) {
    throw new AdminConsoleError(
      "AUTHENTICATION_REQUIRED",
      "A valid account session is required.",
      401,
    );
  }
  return match[1].trim();
}

function endpointPath(request: Request): string {
  const pathname = new URL(request.url).pathname.replace(/\/+$/u, "");
  const marker = "/admin-console";
  const markerIndex = pathname.lastIndexOf(marker);
  return markerIndex >= 0
    ? pathname.slice(markerIndex + marker.length) || "/"
    : pathname;
}

function positiveInteger(value: string | null, fallback: number): number {
  if (value == null || value === "") return fallback;
  if (!/^[1-9][0-9]*$/u.test(value)) {
    throw new AdminConsoleError(
      "INVALID_QUERY",
      "A pagination value is invalid.",
      400,
    );
  }
  const parsed = Number(value);
  if (!Number.isSafeInteger(parsed)) {
    throw new AdminConsoleError(
      "INVALID_QUERY",
      "A pagination value is invalid.",
      400,
    );
  }
  return parsed;
}

function pagination(url: URL): { page: number; pageSize: number } {
  const page = positiveInteger(url.searchParams.get("page"), 1);
  const pageSize = positiveInteger(url.searchParams.get("page_size"), 25);
  if (pageSize > MAX_PAGE_SIZE || page > 100_000) {
    throw new AdminConsoleError(
      "INVALID_QUERY",
      "Pagination is outside the allowed range.",
      400,
    );
  }
  return { page, pageSize };
}

function normalizedSearch(value: unknown): string | null {
  if (value == null || value === "") return null;
  if (typeof value !== "string" || value.length > MAX_SEARCH_LENGTH) {
    throw new AdminConsoleError(
      "INVALID_SEARCH",
      "The search value is invalid.",
      400,
    );
  }
  const normalized = value.trim();
  return normalized || null;
}

function requirePermission(
  identity: AdminIdentity,
  permission: Permission,
): void {
  if (identity.role !== "owner" && !identity.permissions.includes(permission)) {
    throw new AdminConsoleError(
      "ADMIN_PERMISSION_REQUIRED",
      "This administrator does not have the required permission.",
      403,
    );
  }
}

function exactKeys(value: JsonRecord, keys: readonly string[]): boolean {
  const actual = Object.keys(value).sort();
  const expected = [...keys].sort();
  return actual.length === expected.length &&
    actual.every((key, index) => key === expected[index]);
}

function validateModelPatch(value: JsonRecord): ModelPatch {
  if (
    !exactKeys(value, [
      "enabled",
      "assistant_enabled",
      "job_enabled",
      "version",
    ])
  ) {
    throw new AdminConsoleError(
      "INVALID_REQUEST",
      "The model policy body is invalid.",
      400,
    );
  }
  if (
    typeof value.enabled !== "boolean" ||
    typeof value.assistant_enabled !== "boolean" ||
    typeof value.job_enabled !== "boolean" ||
    !Number.isSafeInteger(value.version) || Number(value.version) <= 0 ||
    (!value.enabled && (value.assistant_enabled || value.job_enabled))
  ) {
    throw new AdminConsoleError(
      "INVALID_REQUEST",
      "The model policy body is invalid.",
      400,
    );
  }
  return {
    enabled: value.enabled,
    assistant_enabled: value.assistant_enabled,
    job_enabled: value.job_enabled,
    version: Number(value.version),
  };
}

function validUuid(value: string): boolean {
  return /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/iu
    .test(value);
}

async function sha256Hex(value: string): Promise<string> {
  const digest = await crypto.subtle.digest(
    "SHA-256",
    new TextEncoder().encode(value),
  );
  return [...new Uint8Array(digest)]
    .map((byte) => byte.toString(16).padStart(2, "0"))
    .join("");
}

export function protectCsvFormula(value: string): string {
  let index = 0;
  while (index < value.length && value.charCodeAt(index) <= 0x20) index += 1;
  if (["=", "+", "-", "@"].includes(value[index] ?? "")) return `'${value}`;
  return value;
}

export function csvCell(value: unknown): string {
  const normalized = Array.isArray(value) ? value.join("|") : value;
  const raw = protectCsvFormula(normalized == null ? "" : String(normalized));
  return /[",\r\n]/u.test(raw) ? `"${raw.replaceAll('"', '""')}"` : raw;
}

const EXPORT_COLUMNS: readonly (keyof SafeAdminUser)[] = [
  "id",
  "display_name",
  "email",
  "created_at",
  "last_sign_in_at",
  "plan",
  "billing_scope",
  "organization_name",
  "subscription_status",
  "licensed_editions",
  "period_consumed_ai_credits",
  "period_remaining_ai_credits",
  "period_request_count",
  "period_total_tokens",
];

export function buildUsersCsv(users: SafeAdminUser[]): ArrayBuffer {
  const lines = [
    EXPORT_COLUMNS.join(","),
    ...users.map((user) =>
      EXPORT_COLUMNS.map((column) => csvCell(user[column])).join(",")
    ),
  ];
  return new TextEncoder().encode(`\uFEFF${lines.join("\r\n")}\r\n`).buffer;
}

let cachedAdminClient: SupabaseClient | null = null;

function adminClient(): SupabaseClient {
  if (cachedAdminClient) return cachedAdminClient;
  cachedAdminClient = createClient(
    requiredEnv("SUPABASE_URL"),
    requiredEnv("SUPABASE_SERVICE_ROLE_KEY"),
    { auth: { autoRefreshToken: false, persistSession: false } },
  );
  return cachedAdminClient;
}

function numberValue(value: unknown): number {
  const number = Number(value ?? 0);
  return Number.isFinite(number) && number >= 0 ? number : 0;
}

function safeDisplayName(metadata: JsonRecord, email: string): string {
  for (const key of ["display_name", "full_name", "name"] as const) {
    const value = metadata[key];
    if (typeof value === "string") {
      const normalized = value.trim().replace(/\s+/gu, " ");
      if (normalized && normalized.length <= 80) return normalized;
    }
  }
  return email.split("@", 1)[0]?.slice(0, 80) || "DroneDream user";
}

function organizationName(value: unknown): string | null {
  const record = Array.isArray(value) ? value[0] : value;
  if (!record || typeof record !== "object") return null;
  const name = (record as JsonRecord).name;
  return typeof name === "string" && name.trim()
    ? name.trim().slice(0, 120)
    : null;
}

function modelPresentation(provider: Provider): {
  display_name: string;
  model: string;
} {
  const displayName = provider === "openai"
    ? "OpenAI"
    : provider === "deepseek"
    ? "DeepSeek"
    : "Qwen";
  const prefix = `PLATFORM_${provider.toUpperCase()}`;
  const configured = Deno.env.get(`${prefix}_MODEL`)?.trim() ||
    (provider === "openai" ? Deno.env.get("PLATFORM_LLM_MODEL")?.trim() : "");
  return {
    display_name: displayName,
    model: configured || `${displayName} managed model`,
  };
}

async function fetchAllSafeUsers(
  client: SupabaseClient,
  search: string | null,
  startedAt = Date.now(),
): Promise<SafeAdminUser[]> {
  const rawUsers: Array<{
    id: string;
    email?: string;
    created_at: string;
    last_sign_in_at?: string;
    user_metadata: JsonRecord;
  }> = [];
  for (let page = 1; page <= 1_000; page += 1) {
    if (Date.now() - startedAt >= EXPORT_DEADLINE_MS - 5_000) {
      throw new AdminConsoleError(
        "EXPORT_TIMEOUT",
        "The export exceeded its time limit.",
        503,
      );
    }
    const { data, error } = await client.auth.admin.listUsers({
      page,
      perPage: 100,
    });
    if (error) {
      throw new AdminConsoleError(
        "USER_DIRECTORY_FAILED",
        "The user directory is unavailable.",
        503,
      );
    }
    rawUsers.push(...data.users.map((user) => ({
      id: user.id,
      email: user.email,
      created_at: user.created_at,
      last_sign_in_at: user.last_sign_in_at,
      user_metadata: user.user_metadata as JsonRecord,
    })));
    if (data.users.length < 100) break;
    if (rawUsers.length > MAX_EXPORT_ROWS) {
      throw new AdminConsoleError(
        "EXPORT_ROW_LIMIT",
        "The export row limit was exceeded.",
        413,
      );
    }
  }
  const needle = search?.toLocaleLowerCase("en-US") ?? null;
  const filtered = needle
    ? rawUsers.filter((user) =>
      (user.email ?? "").toLocaleLowerCase("en-US").includes(needle)
    )
    : rawUsers;
  if (filtered.length > MAX_EXPORT_ROWS) {
    throw new AdminConsoleError(
      "EXPORT_ROW_LIMIT",
      "The export row limit was exceeded.",
      413,
    );
  }
  const ids = filtered.map((user) => user.id);
  const entitlementByUser = new Map<string, JsonRecord>();
  const periodByUser = new Map<string, JsonRecord>();
  const licensesByUser = new Map<string, Set<SoftwareEdition>>();
  for (let offset = 0; offset < ids.length; offset += 200) {
    const batch = ids.slice(offset, offset + 200);
    if (!batch.length) continue;
    const [entitlements, periods, licenses] = await Promise.all([
      client.from("account_entitlements")
        .select(
          "user_id,plan_id,status,billing_scope,organization_id,organizations(name)",
        )
        .in("user_id", batch),
      client.from("model_usage_periods")
        .select(
          "user_id,included_ai_credits,consumed_ai_credits,request_count,total_tokens,period_end",
        )
        .in("user_id", batch)
        .gt("period_end", new Date().toISOString())
        .order("period_end", { ascending: false }),
      client.from("user_software_licenses")
        .select("user_id,edition")
        .in("user_id", batch)
        .eq("status", "active"),
    ]);
    if (entitlements.error || periods.error || licenses.error) {
      throw new AdminConsoleError(
        "USER_METRICS_FAILED",
        "User usage metrics are unavailable.",
        503,
      );
    }
    for (const row of entitlements.data ?? []) {
      entitlementByUser.set(String(row.user_id), row);
    }
    for (const row of periods.data ?? []) {
      const userId = String(row.user_id);
      if (!periodByUser.has(userId)) periodByUser.set(userId, row);
    }
    for (const row of licenses.data ?? []) {
      const userId = String(row.user_id);
      const edition = String(row.edition) as SoftwareEdition;
      if (!["universal", "sim", "lab", "field", "autonomy"].includes(edition)) {
        continue;
      }
      const editions = licensesByUser.get(userId) ?? new Set<SoftwareEdition>();
      editions.add(edition);
      licensesByUser.set(userId, editions);
    }
  }
  return filtered.map((user) => {
    const entitlement = entitlementByUser.get(user.id);
    const period = periodByUser.get(user.id);
    const included = numberValue(period?.included_ai_credits);
    const consumed = numberValue(period?.consumed_ai_credits);
    return {
      id: user.id,
      display_name: safeDisplayName(user.user_metadata, user.email ?? ""),
      email: user.email ?? "",
      created_at: user.created_at,
      last_sign_in_at: user.last_sign_in_at ?? null,
      plan: String(entitlement?.plan_id ?? "free"),
      billing_scope: entitlement?.billing_scope === "business"
        ? "business"
        : "individual",
      organization_name: organizationName(entitlement?.organizations),
      subscription_status: String(entitlement?.status ?? "active"),
      licensed_editions: [...(licensesByUser.get(user.id) ?? [])].sort(),
      period_consumed_ai_credits: consumed,
      period_remaining_ai_credits: Math.max(included - consumed, 0),
      period_request_count: numberValue(period?.request_count),
      period_total_tokens: numberValue(period?.total_tokens),
    };
  });
}

interface DashboardEventRow {
  user_id: string;
  name: string;
  occurred_at: string;
  received_at: string;
  properties: JsonRecord;
}

interface DashboardModelUsageRow {
  user_id: string;
  status: string;
  error_code: string | null;
  created_at: string;
  input_tokens: number | null;
  output_tokens: number | null;
  usage_estimated: boolean;
}

function percentage(numerator: number, denominator: number): number {
  if (denominator <= 0) return 0;
  return Math.round((numerator / denominator) * 1_000) / 10;
}

function utcDay(value: string | number | Date): string {
  return new Date(value).toISOString().slice(0, 10);
}

function addUtcDays(value: string | Date, days: number): Date {
  const date = new Date(value);
  return new Date(date.getTime() + days * 86_400_000);
}

function mondayUtc(value: string | Date): string {
  const date = new Date(value);
  const day = date.getUTCDay();
  date.setUTCDate(date.getUTCDate() - (day === 0 ? 6 : day - 1));
  date.setUTCHours(0, 0, 0, 0);
  return utcDay(date);
}

function percentile(values: number[], quantile: number): number | null {
  if (!values.length) return null;
  const sorted = [...values].sort((left, right) => left - right);
  const index = Math.min(
    sorted.length - 1,
    Math.max(0, Math.ceil(quantile * sorted.length) - 1),
  );
  return Math.round(sorted[index] * 10) / 10;
}

function dashboardDefinitions(): JsonRecord[] {
  return [
    {
      key: "active_users",
      label: "Active users",
      definition:
        "Distinct verified users with a privacy-bounded product event received by the server in the selected UTC period.",
    },
    {
      key: "activation_rate",
      label: "Seven-day activation",
      definition:
        "Share of accounts created in the period that reached a trusted job_succeeded event within seven days of account creation.",
    },
    {
      key: "retention",
      label: "Cohort retention",
      definition:
        "Share of sufficiently mature account cohorts with a server-received product event on UTC day 1, 7, or 30 after registration.",
    },
    {
      key: "time_to_value",
      label: "Time to first value",
      definition:
        "Minutes from account creation to the first trusted job_succeeded event. Cohorts without a success are excluded.",
    },
    {
      key: "model_reliability",
      label: "Model reliability",
      definition:
        "Completion, rate-limit, token, and estimate counts from trusted model_usage_requests rows. P95 latency is unavailable until a bounded latency field exists.",
    },
    {
      key: "monetization",
      label: "Plans and usage",
      definition:
        "Current plan and current-period credit totals from server-side entitlement and usage tables; payment revenue is not inferred.",
    },
  ];
}

export function buildDashboardSnapshot(
  range: "7d" | "30d" | "90d",
  users: SafeAdminUser[],
  allEvents: DashboardEventRow[],
  modelRows: DashboardModelUsageRow[],
  now = new Date(),
): JsonRecord {
  const days = Number(range.slice(0, -1));
  const endExclusive = new Date(Date.UTC(
    now.getUTCFullYear(),
    now.getUTCMonth(),
    now.getUTCDate() + 1,
  ));
  const rangeStart = addUtcDays(endExclusive, -days);
  const rangeStartMs = rangeStart.getTime();
  const endExclusiveMs = endExclusive.getTime();
  const within = (value: string, startMs = rangeStartMs): boolean => {
    const timestamp = Date.parse(value);
    return timestamp >= startMs && timestamp < endExclusiveMs;
  };
  const events = allEvents.filter((event) => within(event.received_at));
  const selectedModels = modelRows.filter((row) => within(row.created_at));
  const newUsers = users.filter((user) => within(user.created_at));
  const eventsByUser = new Map<string, DashboardEventRow[]>();
  for (const event of allEvents) {
    const rows = eventsByUser.get(event.user_id) ?? [];
    rows.push(event);
    eventsByUser.set(event.user_id, rows);
  }
  for (const rows of eventsByUser.values()) {
    rows.sort((left, right) =>
      Date.parse(left.received_at) - Date.parse(right.received_at)
    );
  }

  const distinctUsers = (rows: DashboardEventRow[]): number =>
    new Set(rows.map((row) => row.user_id)).size;
  const activeUsers = distinctUsers(events);
  const todayStart = addUtcDays(endExclusive, -1).getTime();
  const weekStart = addUtcDays(endExclusive, -7).getTime();
  const monthStart = addUtcDays(endExclusive, -30).getTime();
  const dau = distinctUsers(
    allEvents.filter((event) => within(event.received_at, todayStart)),
  );
  const wau = distinctUsers(
    allEvents.filter((event) => within(event.received_at, weekStart)),
  );
  const mau = distinctUsers(
    allEvents.filter((event) => within(event.received_at, monthStart)),
  );

  const firstEvent = (userId: string, name: string): DashboardEventRow | null =>
    eventsByUser.get(userId)?.find((event) => event.name === name) ?? null;
  const activatedNewUsers = newUsers.filter((user) => {
    const success = firstEvent(user.id, "job_succeeded");
    return success !== null && Date.parse(success.received_at) >=
        Date.parse(user.created_at) &&
      Date.parse(success.received_at) <=
        Date.parse(user.created_at) + 7 * 86_400_000;
  });

  const funnelKeys = [
    ["registration_verified", "Registration verified"],
    ["runtime_ready", "Runtime ready"],
    ["draft_saved", "Draft saved"],
    ["job_created", "Job created"],
    ["job_succeeded", "Job succeeded"],
  ] as const;
  let previousFunnelUsers = newUsers.length;
  const funnel = funnelKeys.map(([key, label], index) => {
    const usersAtStep = index === 0
      ? newUsers.length
      : newUsers.filter((user) => {
        const createdAt = Date.parse(user.created_at);
        return (eventsByUser.get(user.id) ?? []).some((event) =>
          event.name === key && Date.parse(event.received_at) >= createdAt &&
          Date.parse(event.received_at) <= createdAt + 7 * 86_400_000
        );
      }).length;
    const row = {
      key,
      label,
      users: usersAtStep,
      overall_conversion_pct: percentage(usersAtStep, newUsers.length),
      previous_step_conversion_pct: index === 0
        ? (newUsers.length ? 100 : 0)
        : percentage(usersAtStep, previousFunnelUsers),
    };
    previousFunnelUsers = usersAtStep;
    return row;
  });

  const cohortMap = new Map<string, SafeAdminUser[]>();
  for (const user of newUsers) {
    const cohort = mondayUtc(user.created_at);
    cohortMap.set(cohort, [...(cohortMap.get(cohort) ?? []), user]);
  }
  const retainedAt = (user: SafeAdminUser, day: number): boolean => {
    const start = Date.parse(user.created_at) + day * 86_400_000;
    const end = start + 86_400_000;
    return (eventsByUser.get(user.id) ?? []).some((event) => {
      const received = Date.parse(event.received_at);
      return received >= start && received < end;
    });
  };
  const retention = [...cohortMap.entries()].sort(([left], [right]) =>
    left.localeCompare(right)
  ).map(([cohortStart, cohortUsers]) => {
    const cohortAgeDays = Math.floor(
      (endExclusiveMs - Date.parse(cohortStart)) / 86_400_000,
    );
    const value = (day: number): number | null =>
      cohortAgeDays <= day ? null : percentage(
        cohortUsers.filter((user) => retainedAt(user, day)).length,
        cohortUsers.length,
      );
    return {
      cohort_start: cohortStart,
      cohort_size: cohortUsers.length,
      d1_pct: value(1),
      d7_pct: value(7),
      d30_pct: value(30),
    };
  });
  const aggregateRetention = (day: number): number => {
    const mature = newUsers.filter((user) =>
      endExclusiveMs - Date.parse(user.created_at) > day * 86_400_000
    );
    return percentage(
      mature.filter((user) => retainedAt(user, day)).length,
      mature.length,
    );
  };

  const acquisitionByKey = new Map<
    string,
    { users: SafeAdminUser[]; activated: Set<string> }
  >();
  const activatedIds = new Set(activatedNewUsers.map((user) => user.id));
  for (const user of newUsers) {
    const registration = firstEvent(user.id, "registration_verified");
    const rawSource = registration?.properties.source;
    const source = typeof rawSource === "string" &&
        /^[a-z][a-z0-9_-]{0,47}$/u.test(rawSource)
      ? rawSource
      : "unknown";
    const bucket = acquisitionByKey.get(source) ?? {
      users: [],
      activated: new Set<string>(),
    };
    bucket.users.push(user);
    if (activatedIds.has(user.id)) bucket.activated.add(user.id);
    acquisitionByKey.set(source, bucket);
  }
  const acquisition = [...acquisitionByKey.entries()].map(([key, bucket]) => ({
    key,
    label: key === "unknown" ? "Unknown or not recorded" : key,
    new_users: bucket.users.length,
    activated_users: bucket.activated.size,
    activation_rate_pct: percentage(bucket.activated.size, bucket.users.length),
  }));

  const ttfvMinutes = newUsers.flatMap((user) => {
    const success = firstEvent(user.id, "job_succeeded");
    if (!success) return [];
    const minutes =
      (Date.parse(success.received_at) - Date.parse(user.created_at)) /
      60_000;
    return minutes >= 0 ? [minutes] : [];
  });

  const featureGroups = [
    ["assistant", "Assistant", [
      "assistant_turn_succeeded",
      "assistant_turn_failed",
    ]],
    ["fixed_scenarios", "Fixed scenarios", ["fixed_scenario_selected"]],
    ["jobs", "Jobs", ["job_created"]],
    ["reports", "Reports", ["report_exported"]],
    ["community", "Community", ["community_contributed"]],
  ] as const;
  const features = featureGroups.map(([key, label, names]) => {
    const matches = events.filter((event) =>
      names.includes(event.name as never)
    );
    const usersForFeature = distinctUsers(matches);
    return {
      key,
      label,
      users: usersForFeature,
      adoption_pct: percentage(usersForFeature, activeUsers),
      frequency_per_user: usersForFeature
        ? Math.round((matches.length / usersForFeature) * 10) / 10
        : 0,
    };
  });

  const jobSucceeded = events.filter((event) => event.name === "job_succeeded");
  const jobFailed = events.filter((event) => event.name === "job_failed");
  const completedModels = selectedModels.filter((row) =>
    row.status === "completed"
  );
  const failedModels = selectedModels.filter((row) => row.status === "failed");
  const rateLimited = failedModels.filter((row) =>
    /rate.?limit|too.?many.?requests|429/iu.test(row.error_code ?? "")
  );
  const quotaRows = failedModels.filter((row) =>
    /quota|credit|allowance|exhaust/iu.test(row.error_code ?? "")
  );
  const plans = { free: 0, plus: 0, pro: 0 };
  for (const user of users) {
    if (user.plan === "plus" || user.plan === "pro") plans[user.plan] += 1;
    else plans.free += 1;
  }
  const payingUsers = plans.plus + plans.pro;

  const dates: string[] = [];
  for (let offset = 0; offset < days; offset += 1) {
    dates.push(utcDay(addUtcDays(rangeStart, offset)));
  }
  const daily = dates.map((date) => {
    const dailyEvents = events.filter((event) =>
      utcDay(event.received_at) === date
    );
    return {
      date,
      new_users: newUsers.filter((user) =>
        utcDay(user.created_at) === date
      ).length,
      active_users: distinctUsers(dailyEvents),
      activated_users: distinctUsers(
        dailyEvents.filter((event) => event.name === "job_succeeded"),
      ),
      successful_jobs:
        dailyEvents.filter((event) => event.name === "job_succeeded").length,
      model_requests:
        selectedModels.filter((row) => utcDay(row.created_at) === date).length,
    };
  });

  return {
    generated_at: now.toISOString(),
    timezone: "UTC",
    range,
    summary: {
      total_users: users.length,
      new_users: newUsers.length,
      active_users: activeUsers,
      dau,
      wau,
      mau,
      dau_mau_pct: percentage(dau, mau),
      activation_rate_pct: percentage(
        activatedNewUsers.length,
        newUsers.length,
      ),
      d1_retention_pct: aggregateRetention(1),
      d7_retention_pct: aggregateRetention(7),
      d30_retention_pct: aggregateRetention(30),
      paying_users: payingUsers,
      paid_conversion_pct: percentage(payingUsers, users.length),
    },
    daily,
    funnel,
    retention,
    acquisition,
    time_to_value: {
      median_minutes: percentile(ttfvMinutes, 0.5),
      p90_minutes: percentile(ttfvMinutes, 0.9),
    },
    features,
    reliability: {
      job_success_pct: percentage(
        jobSucceeded.length,
        jobSucceeded.length + jobFailed.length,
      ),
      model_success_pct: percentage(
        completedModels.length,
        completedModels.length + failedModels.length,
      ),
      model_rate_limited_pct: percentage(
        rateLimited.length,
        selectedModels.length,
      ),
      p95_model_latency_ms: null,
      quota_exhausted_users: new Set(quotaRows.map((row) => row.user_id)).size,
    },
    monetization: {
      free_users: plans.free,
      plus_users: plans.plus,
      pro_users: plans.pro,
      consumed_ai_credits: users.reduce(
        (sum, user) => sum + user.period_consumed_ai_credits,
        0,
      ),
      model_input_tokens: selectedModels.reduce(
        (sum, row) => sum + numberValue(row.input_tokens),
        0,
      ),
      model_output_tokens: selectedModels.reduce(
        (sum, row) => sum + numberValue(row.output_tokens),
        0,
      ),
      estimated_usage_requests:
        selectedModels.filter((row) => row.usage_estimated).length,
    },
    definitions: dashboardDefinitions(),
    quality: {
      sources: [
        "auth.users",
        "account_entitlements",
        "model_usage_periods",
        "product_events",
        "model_usage_requests",
      ],
      estimated: selectedModels.some((row) => row.usage_estimated),
      unavailable: ["p95_model_latency_ms"],
    },
  };
}

function actualDependencies(): AdminConsoleDependencies {
  const client = adminClient();
  return {
    nowMs: () => Date.now(),
    async resolveIdentity(token) {
      const { data, error } = await client.auth.getUser(token);
      if (error || !data.user) {
        throw new AdminConsoleError(
          "AUTHENTICATION_REQUIRED",
          "The account session is invalid.",
          401,
        );
      }
      const ownerEmail = requiredEnv("ADMIN_OWNER_EMAIL").toLocaleLowerCase(
        "en-US",
      );
      if ((data.user.email ?? "").toLocaleLowerCase("en-US") === ownerEmail) {
        const { error: bootstrapError } = await client.rpc(
          "admin_bootstrap_owner",
          {
            p_user_id: data.user.id,
          },
        );
        if (bootstrapError) {
          throw new AdminConsoleError(
            "ADMIN_BOOTSTRAP_FAILED",
            "Administrator bootstrap failed closed.",
            503,
          );
        }
      }
      const { data: row, error: accessError } = await client.from("app_admins")
        .select("user_id,role,permissions,active")
        .eq("user_id", data.user.id)
        .maybeSingle();
      if (accessError) {
        throw new AdminConsoleError(
          "ADMIN_ACCESS_FAILED",
          "Administrator access could not be verified.",
          503,
        );
      }
      if (
        !row || row.active !== true ||
        !["owner", "admin"].includes(String(row.role))
      ) return null;
      const permissions = Array.isArray(row.permissions)
        ? row.permissions.filter((value): value is Permission =>
          ALL_PERMISSIONS.includes(value as Permission)
        )
        : [];
      return { userId: data.user.id, role: row.role as AdminRole, permissions };
    },
    async dashboard(range) {
      const days = Number(range.slice(0, -1));
      const lookbackDays = Math.max(days, 30) + 31;
      const since = new Date(Date.now() - lookbackDays * 86_400_000)
        .toISOString();
      const [users, eventResult, modelResult] = await Promise.all([
        fetchAllSafeUsers(client, null),
        client.from("product_events")
          .select("user_id,name,occurred_at,received_at,properties")
          .gte("received_at", since)
          .order("received_at", { ascending: true })
          .limit(50_001),
        client.from("model_usage_requests")
          .select(
            "user_id,status,error_code,created_at,input_tokens,output_tokens,usage_estimated",
          )
          .gte("created_at", since)
          .order("created_at", { ascending: true })
          .limit(50_001),
      ]);
      if (eventResult.error || modelResult.error) {
        throw new AdminConsoleError(
          "DASHBOARD_QUERY_FAILED",
          "Dashboard metrics are unavailable.",
          503,
        );
      }
      if (
        (eventResult.data?.length ?? 0) > 50_000 ||
        (modelResult.data?.length ?? 0) > 50_000
      ) {
        throw new AdminConsoleError(
          "DASHBOARD_ROW_LIMIT",
          "Dashboard metrics exceed the bounded query limit.",
          413,
        );
      }
      return buildDashboardSnapshot(
        range,
        users,
        (eventResult.data ?? []) as DashboardEventRow[],
        (modelResult.data ?? []) as DashboardModelUsageRow[],
      );
    },
    async listModels() {
      const { data, error } = await client.from("model_provider_policies")
        .select(
          "provider,enabled,assistant_enabled,job_enabled,version,updated_at",
        )
        .order("provider");
      if (error) {
        throw new AdminConsoleError(
          "MODEL_CATALOG_FAILED",
          "The model catalog is unavailable.",
          503,
        );
      }
      return (data ?? []).map((row) => {
        const provider = String(row.provider) as Provider;
        return {
          ...row,
          ...modelPresentation(provider),
          // The bootstrap email is a server-only secret and is never returned.
          updated_by_email: null,
        };
      });
    },
    async updateModel(actorUserId, provider, body) {
      const { data, error } = await client.rpc("admin_update_model_policy", {
        p_actor_user_id: actorUserId,
        p_provider: provider,
        p_enabled: body.enabled,
        p_assistant_enabled: body.assistant_enabled,
        p_job_enabled: body.job_enabled,
        p_expected_version: body.version,
      });
      if (error?.message.includes("MODEL_POLICY_VERSION_CONFLICT")) {
        throw new AdminConsoleError(
          "MODEL_POLICY_VERSION_CONFLICT",
          "The model policy changed; refresh and retry.",
          409,
        );
      }
      if (error || !data) {
        throw new AdminConsoleError(
          "MODEL_POLICY_UPDATE_FAILED",
          "The model policy could not be updated.",
          503,
        );
      }
      const row = data as JsonRecord;
      return {
        ...row,
        ...modelPresentation(provider),
        updated_by_email: null,
      };
    },
    listUsers(search) {
      return fetchAllSafeUsers(client, search);
    },
    async deleteUser(actorUserId, targetUserId, reason) {
      const { data, error } = await client.rpc("admin_delete_user", {
        p_actor_user_id: actorUserId,
        p_target_user_id: targetUserId,
        p_reason: reason,
      });
      if (error?.message.includes("ADMIN_USER_DELETE_SELF")) {
        throw new AdminConsoleError(
          "ADMIN_USER_DELETE_SELF",
          "The owner account cannot delete itself.",
          409,
        );
      }
      if (error?.message.includes("ADMIN_USER_DELETE_NOT_FOUND")) {
        throw new AdminConsoleError(
          "ADMIN_USER_DELETE_NOT_FOUND",
          "The user account no longer exists.",
          404,
        );
      }
      if (error?.message.includes("ADMIN_USER_DELETE_RETENTION_REQUIRED")) {
        throw new AdminConsoleError(
          "ADMIN_USER_DELETE_RETENTION_REQUIRED",
          "This account has protected administrative, organization, or payment history and cannot be permanently deleted.",
          409,
        );
      }
      if (error || !data) {
        throw new AdminConsoleError(
          "ADMIN_USER_DELETE_FAILED",
          "The user account could not be deleted.",
          503,
        );
      }
      return data as JsonRecord;
    },
    async listTopics(page, pageSize) {
      const from = (page - 1) * pageSize;
      const { data, error, count } = await client.from("community_topics")
        .select(
          "id,author_id,author_name,title,created_at,hidden_at,hidden_reason",
          { count: "exact" },
        )
        .order("created_at", { ascending: false })
        .range(from, from + pageSize - 1);
      if (error) {
        throw new AdminConsoleError(
          "COMMUNITY_QUERY_FAILED",
          "Community moderation data is unavailable.",
          503,
        );
      }
      const topics = (data ?? []) as Array<{
        id: string;
        author_id: string;
        title: string;
        created_at: string;
        hidden_at: string | null;
      }>;
      const topicIds = topics.map((topic) => topic.id);
      const authorIds = [...new Set(topics.map((topic) => topic.author_id))];
      const [authorResults, commentResult] = await Promise.all([
        Promise.all(authorIds.map(async (userId) => {
          const { data: userData, error: userError } = await client.auth.admin
            .getUserById(userId);
          if (userError || !userData.user) {
            throw new AdminConsoleError(
              "COMMUNITY_AUTHOR_LOOKUP_FAILED",
              "Community author data is unavailable.",
              503,
            );
          }
          return [userId, userData.user.email ?? ""] as const;
        })),
        topicIds.length
          ? client.from("community_comments").select("topic_id")
            .in("topic_id", topicIds).limit(10_001)
          : Promise.resolve({ data: [], error: null }),
      ]);
      if (commentResult.error) {
        throw new AdminConsoleError(
          "COMMUNITY_COMMENT_COUNT_FAILED",
          "Community comment counts are unavailable.",
          503,
        );
      }
      if ((commentResult.data?.length ?? 0) > 10_000) {
        throw new AdminConsoleError(
          "COMMUNITY_COMMENT_LIMIT",
          "Community comment counts exceed the bounded query limit.",
          413,
        );
      }
      const authorEmail = new Map(authorResults);
      const commentsByTopic = new Map<string, number>();
      for (const comment of commentResult.data ?? []) {
        const topicId = String(comment.topic_id);
        commentsByTopic.set(topicId, (commentsByTopic.get(topicId) ?? 0) + 1);
      }
      return {
        rows: topics.map((topic) => ({
          id: topic.id,
          title: topic.title,
          author_email: authorEmail.get(topic.author_id) ?? "",
          created_at: topic.created_at,
          comment_count: commentsByTopic.get(topic.id) ?? 0,
          // No report table exists in the current schema; zero is an explicit
          // absence, not an inferred moderation outcome.
          report_count: 0,
          status: topic.hidden_at ? "removed" : "published",
        })),
        total: count ?? 0,
      };
    },
    async removeTopic(actorUserId, topicId, reason) {
      const { data, error } = await client.rpc("admin_remove_community_topic", {
        p_actor_user_id: actorUserId,
        p_topic_id: topicId,
        p_reason: reason,
      });
      if (error || !data) {
        throw new AdminConsoleError(
          "COMMUNITY_REMOVE_FAILED",
          "The topic could not be removed.",
          503,
        );
      }
      return data as JsonRecord;
    },
    async listAudit(page, pageSize) {
      const from = (page - 1) * pageSize;
      const { data, error, count } = await client.from("admin_audit_log")
        .select(
          "id,actor_user_id,action,target_type,target_id,reason,outcome,created_at",
          { count: "exact" },
        )
        .order("created_at", { ascending: false })
        .range(from, from + pageSize - 1);
      if (error) {
        throw new AdminConsoleError(
          "AUDIT_QUERY_FAILED",
          "The audit log is unavailable.",
          503,
        );
      }
      return {
        rows: (data ?? []).map((row) => ({
          id: row.id,
          created_at: row.created_at,
          actor_id: row.actor_user_id,
          action: row.action,
          target_type: row.target_type,
          target_id: row.target_id,
          reason: row.reason,
          outcome: row.outcome,
        })),
        total: count ?? 0,
      };
    },
    async recordExportAudit(
      actorUserId,
      outcome,
      filterHash,
      rowCount,
      failureClass,
    ) {
      const metadata: JsonRecord = {
        filter_sha256: filterHash,
        row_count: rowCount,
      };
      if (failureClass) metadata.failure_class = failureClass;
      const { error } = await client.from("admin_audit_log").insert({
        actor_user_id: actorUserId,
        action: "users.export",
        target_type: "user_directory",
        target_id: null,
        reason: null,
        metadata,
        outcome,
      });
      if (error && outcome === "succeeded") {
        throw new AdminConsoleError(
          "EXPORT_AUDIT_FAILED",
          "The export audit receipt could not be sealed.",
          503,
        );
      }
    },
  };
}

export async function handleAdminConsoleRequest(
  request: Request,
  dependencies?: AdminConsoleDependencies,
): Promise<Response> {
  try {
    const cors = corsHeaders(request);
    if (request.method === "OPTIONS") {
      return new Response(null, { status: 204, headers: cors });
    }
    const deps = dependencies ?? actualDependencies();
    const identity = await deps.resolveIdentity(bearerToken(request));
    const path = endpointPath(request);
    if (path === "/access" && request.method === "GET") {
      return jsonResponse(request, 200, {
        data: {
          authorized: identity !== null,
          role: identity?.role ?? null,
          permissions: identity?.role === "owner"
            ? [...ALL_PERMISSIONS]
            : identity?.permissions ?? [],
        },
      });
    }
    if (!identity) {
      throw new AdminConsoleError(
        "ADMIN_ACCESS_DENIED",
        "Administrator access is required.",
        403,
      );
    }
    const url = new URL(request.url);

    if (path === "/dashboard" && request.method === "GET") {
      requirePermission(identity, "dashboard.read");
      const range = url.searchParams.get("range") ?? "30d";
      if (
        !(["7d", "30d", "90d"] as const).includes(range as "7d" | "30d" | "90d")
      ) {
        throw new AdminConsoleError(
          "INVALID_RANGE",
          "The dashboard range is invalid.",
          400,
        );
      }
      return jsonResponse(request, 200, {
        data: await deps.dashboard(range as "7d" | "30d" | "90d"),
      });
    }
    if (path === "/models" && request.method === "GET") {
      requirePermission(identity, "models.read");
      return jsonResponse(request, 200, { data: await deps.listModels() });
    }
    const modelMatch = /^\/models\/(openai|deepseek|qwen)$/u.exec(path);
    if (modelMatch && request.method === "PATCH") {
      requirePermission(identity, "models.write");
      const body = validateModelPatch(
        await readBoundedJsonObject(request, MAX_JSON_BYTES),
      );
      return jsonResponse(request, 200, {
        data: await deps.updateModel(
          identity.userId,
          modelMatch[1] as Provider,
          body,
        ),
      });
    }
    if (path === "/users" && request.method === "GET") {
      requirePermission(identity, "users.read");
      const { page, pageSize } = pagination(url);
      const search = normalizedSearch(url.searchParams.get("search"));
      const all = await deps.listUsers(search);
      const start = (page - 1) * pageSize;
      return jsonResponse(request, 200, {
        data: {
          items: all.slice(start, start + pageSize),
          page,
          page_size: pageSize,
          total: all.length,
        },
      });
    }
    if (path === "/users/export" && request.method === "POST") {
      requirePermission(identity, "users.export");
      if ([...url.searchParams.keys()].length > 0) {
        throw new AdminConsoleError(
          "INVALID_REQUEST",
          "Export filters must be supplied in the JSON body.",
          400,
        );
      }
      const startedAt = deps.nowMs();
      const body = await readBoundedJsonObject(request, MAX_JSON_BYTES);
      if (!exactKeys(body, ["format", "search"]) || body.format !== "csv") {
        throw new AdminConsoleError(
          "INVALID_REQUEST",
          "The export request is invalid.",
          400,
        );
      }
      const search = normalizedSearch(body.search);
      const filterHash = await sha256Hex(
        search?.toLocaleLowerCase("en-US") ?? "",
      );
      try {
        const users = await deps.listUsers(search);
        if (users.length > MAX_EXPORT_ROWS) {
          throw new AdminConsoleError(
            "EXPORT_ROW_LIMIT",
            "The export row limit was exceeded.",
            413,
          );
        }
        const bytes = buildUsersCsv(users);
        if (bytes.byteLength > MAX_EXPORT_BYTES) {
          throw new AdminConsoleError(
            "EXPORT_BYTE_LIMIT",
            "The export byte limit was exceeded.",
            413,
          );
        }
        if (deps.nowMs() - startedAt >= EXPORT_DEADLINE_MS) {
          throw new AdminConsoleError(
            "EXPORT_TIMEOUT",
            "The export exceeded its time limit.",
            503,
          );
        }
        await deps.recordExportAudit(
          identity.userId,
          "succeeded",
          filterHash,
          users.length,
        );
        return new Response(bytes, {
          status: 200,
          headers: {
            "Content-Type": "text/csv;charset=utf-8",
            "Content-Disposition":
              'attachment; filename="dronedream-users.csv"',
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
            "X-Export-Row-Count": String(users.length),
            ...corsHeaders(request),
          },
        });
      } catch (error) {
        const failureClass = error instanceof AdminConsoleError
          ? error.code
          : "INTERNAL_ERROR";
        await deps.recordExportAudit(
          identity.userId,
          "failed",
          filterHash,
          0,
          failureClass,
        ).catch(() => undefined);
        throw error;
      }
    }
    const deleteUserMatch = /^\/users\/([0-9a-f-]+)\/delete$/iu.exec(path);
    if (deleteUserMatch && request.method === "POST") {
      requirePermission(identity, "users.delete");
      if (!validUuid(deleteUserMatch[1])) {
        throw new AdminConsoleError(
          "INVALID_USER_ID",
          "The user id is invalid.",
          400,
        );
      }
      if (
        deleteUserMatch[1].toLocaleLowerCase("en-US") ===
          identity.userId.toLocaleLowerCase("en-US")
      ) {
        throw new AdminConsoleError(
          "ADMIN_USER_DELETE_SELF",
          "The owner account cannot delete itself.",
          409,
        );
      }
      const body = await readBoundedJsonObject(request, MAX_JSON_BYTES);
      if (
        !exactKeys(body, ["reason"]) || typeof body.reason !== "string" ||
        body.reason.trim().length < 8 || body.reason.trim().length > 500
      ) {
        throw new AdminConsoleError(
          "INVALID_DELETE_REASON",
          "A deletion reason from 8 to 500 characters is required.",
          400,
        );
      }
      return jsonResponse(request, 200, {
        data: await deps.deleteUser(
          identity.userId,
          deleteUserMatch[1],
          body.reason.trim(),
        ),
      });
    }
    if (path === "/community/topics" && request.method === "GET") {
      requirePermission(identity, "community.read");
      const { page, pageSize } = pagination(url);
      const result = await deps.listTopics(page, pageSize);
      return jsonResponse(request, 200, {
        data: {
          items: result.rows,
          total: result.total,
          page,
          page_size: pageSize,
        },
      });
    }
    const removeMatch = /^\/community\/topics\/([0-9a-f-]+)\/remove$/iu.exec(
      path,
    );
    if (removeMatch && request.method === "POST") {
      requirePermission(identity, "community.remove");
      if (!validUuid(removeMatch[1])) {
        throw new AdminConsoleError(
          "INVALID_TOPIC_ID",
          "The topic id is invalid.",
          400,
        );
      }
      const body = await readBoundedJsonObject(request, MAX_JSON_BYTES);
      if (
        !exactKeys(body, ["reason"]) || typeof body.reason !== "string" ||
        body.reason.trim().length < 8 || body.reason.trim().length > 500
      ) {
        throw new AdminConsoleError(
          "INVALID_REMOVE_REASON",
          "A removal reason from 8 to 500 characters is required.",
          400,
        );
      }
      await deps.removeTopic(
        identity.userId,
        removeMatch[1],
        body.reason.trim(),
      );
      return jsonResponse(request, 200, { data: { removed: true } });
    }
    if (path === "/audit" && request.method === "GET") {
      requirePermission(identity, "audit.read");
      const { page, pageSize } = pagination(url);
      const result = await deps.listAudit(page, pageSize);
      return jsonResponse(request, 200, {
        data: {
          items: result.rows,
          total: result.total,
          page,
          page_size: pageSize,
        },
      });
    }
    return jsonResponse(request, 404, {
      error: {
        code: "NOT_FOUND",
        message: "The admin-console route was not found.",
      },
    });
  } catch (error) {
    return errorResponse(request, error);
  }
}

if (import.meta.main) {
  Deno.serve((request) => handleAdminConsoleRequest(request));
}
