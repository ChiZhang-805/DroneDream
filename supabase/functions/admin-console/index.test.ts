import {
  type AdminConsoleDependencies,
  AdminConsoleError,
  type AdminIdentity,
  buildDashboardSnapshot,
  buildUsersCsv,
  handleAdminConsoleRequest,
  protectCsvFormula,
  type SafeAdminUser,
} from "./index.ts";

function assert(value: unknown, message: string): asserts value {
  if (!value) throw new Error(message);
}

function user(overrides: Partial<SafeAdminUser> = {}): SafeAdminUser {
  return {
    id: "11111111-1111-4111-8111-111111111111",
    email: "admin@example.test",
    created_at: "2026-08-03T00:00:00.000Z",
    last_sign_in_at: null,
    plan: "free",
    subscription_status: "active",
    period_consumed_ai_credits: 0,
    period_remaining_ai_credits: 300000,
    period_request_count: 0,
    period_total_tokens: 0,
    ...overrides,
  };
}

function dependencies(
  identity: AdminIdentity | null = {
    userId: "22222222-2222-4222-8222-222222222222",
    role: "owner",
    permissions: [],
  },
  overrides: Partial<AdminConsoleDependencies> = {},
): AdminConsoleDependencies {
  return {
    nowMs: () => Date.now(),
    resolveIdentity: () => Promise.resolve(identity),
    dashboard: (range) =>
      Promise.resolve({
        range,
        generated_at: "2026-08-03T00:00:00.000Z",
      }),
    listModels: () => Promise.resolve([]),
    updateModel: (_actor, provider, body) =>
      Promise.resolve({
        provider,
        ...body,
        version: body.version + 1,
      }),
    listUsers: () => Promise.resolve([user()]),
    listTopics: () => Promise.resolve({ rows: [], total: 0 }),
    removeTopic: (_actor, topicId, reason) =>
      Promise.resolve({
        id: topicId,
        hidden_reason: reason,
      }),
    listAudit: () => Promise.resolve({ rows: [], total: 0 }),
    recordExportAudit: () => Promise.resolve(),
    ...overrides,
  };
}

function request(path: string, init: RequestInit = {}): Request {
  const headers = new Headers(init.headers);
  if (!headers.has("Authorization")) {
    headers.set("Authorization", "Bearer test-token");
  }
  if (init.body && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  return new Request(`https://example.test/functions/v1/admin-console${path}`, {
    ...init,
    headers,
  });
}

async function body(response: Response): Promise<Record<string, unknown>> {
  return await response.json() as Record<string, unknown>;
}

Deno.test("admin access is default deny and never trusts request email", async () => {
  const denied = await handleAdminConsoleRequest(
    request("/access"),
    dependencies(null),
  );
  assert(
    denied.status === 200,
    "access discovery should be safe for authenticated non-admins",
  );
  const deniedBody = await body(denied);
  assert(
    (deniedBody.data as Record<string, unknown>).authorized === false,
    "non-admin access must be false",
  );

  const forged = await handleAdminConsoleRequest(
    request("/dashboard?range=7d&email=owner@example.test"),
    dependencies(null),
  );
  assert(forged.status === 403, "a forged email query must not grant access");
});

Deno.test("admin routes re-check permissions and reject unknown ranges", async () => {
  const limited: AdminIdentity = {
    userId: "22222222-2222-4222-8222-222222222222",
    role: "admin",
    permissions: ["dashboard.read"],
  };
  const forbidden = await handleAdminConsoleRequest(
    request("/users"),
    dependencies(limited),
  );
  assert(
    forbidden.status === 403,
    "users.read must be enforced on every request",
  );

  const invalid = await handleAdminConsoleRequest(
    request("/dashboard?range=forever"),
    dependencies(limited),
  );
  assert(invalid.status === 400, "unknown dashboard ranges must fail closed");
});

Deno.test("paginated routes use the frontend page-result envelope", async () => {
  for (const path of ["/users", "/community/topics", "/audit"]) {
    const response = await handleAdminConsoleRequest(
      request(path),
      dependencies(),
    );
    assert(response.status === 200, `${path} should succeed`);
    const payload = await body(response);
    const page = payload.data as Record<string, unknown>;
    assert(Array.isArray(page.items), `${path} must expose data.items`);
    assert(page.page === 1, `${path} must expose its current page`);
    assert(page.page_size === 25, `${path} must expose its page size`);
    assert(typeof page.total === "number", `${path} must expose its total`);
  }
});

Deno.test("model updates enforce exact bodies and preserve version conflicts", async () => {
  const extra = await handleAdminConsoleRequest(
    request("/models/openai", {
      method: "PATCH",
      body: JSON.stringify({
        enabled: true,
        assistant_enabled: true,
        job_enabled: true,
        version: 1,
        key: "secret",
      }),
    }),
    dependencies(),
  );
  assert(extra.status === 400, "extra model policy fields must be rejected");

  const conflict = await handleAdminConsoleRequest(
    request("/models/qwen", {
      method: "PATCH",
      body: JSON.stringify({
        enabled: true,
        assistant_enabled: true,
        job_enabled: false,
        version: 3,
      }),
    }),
    dependencies(undefined, {
      updateModel: () =>
        Promise.reject(
          new AdminConsoleError(
            "MODEL_POLICY_VERSION_CONFLICT",
            "The model policy changed; refresh and retry.",
            409,
          ),
        ),
    }),
  );
  assert(conflict.status === 409, "version conflicts must remain explicit");
});

Deno.test("community removal requires a UUID, bounded reason, and permission", async () => {
  const short = await handleAdminConsoleRequest(
    request("/community/topics/11111111-1111-4111-8111-111111111111/remove", {
      method: "POST",
      body: JSON.stringify({ reason: "short" }),
    }),
    dependencies(),
  );
  assert(short.status === 400, "short removal reasons must be rejected");

  const ok = await handleAdminConsoleRequest(
    request("/community/topics/11111111-1111-4111-8111-111111111111/remove", {
      method: "POST",
      body: JSON.stringify({ reason: "Verified policy violation" }),
    }),
    dependencies(),
  );
  assert(
    ok.status === 200,
    "valid soft-removal requests should reach the atomic dependency",
  );
});

Deno.test("user export is fixed-schema, private, quoted, and formula-safe", async () => {
  const audits: Array<Record<string, unknown>> = [];
  const response = await handleAdminConsoleRequest(
    request("/users/export", {
      method: "POST",
      body: JSON.stringify({ format: "csv", search: "person@example.test" }),
    }),
    dependencies(undefined, {
      listUsers: () =>
        Promise.resolve([user({
          email: '\t=HYPERLINK("https://example.test")',
          plan: "plus,preview",
        })]),
      recordExportAudit: (
        _actor,
        outcome,
        filterHash,
        rowCount,
        failureClass,
      ) => {
        audits.push({ outcome, filterHash, rowCount, failureClass });
        return Promise.resolve();
      },
    }),
  );
  assert(response.status === 200, "valid CSV exports should succeed");
  assert(
    response.headers.get("Cache-Control") === "private, no-store",
    "exports must not be cached",
  );
  assert(
    response.headers.get("X-Content-Type-Options") === "nosniff",
    "exports must disable sniffing",
  );
  assert(
    response.headers.get("X-Export-Row-Count") === "1",
    "row count must be explicit",
  );
  const raw = new Uint8Array(await response.clone().arrayBuffer());
  assert(
    raw[0] === 0xef && raw[1] === 0xbb && raw[2] === 0xbf,
    "CSV must carry a UTF-8 BOM",
  );
  const csv = await response.text();
  assert(
    csv.startsWith(
      "id,email,created_at,last_sign_in_at,plan,subscription_status,period_consumed_ai_credits,period_remaining_ai_credits,period_request_count,period_total_tokens\r\n",
    ),
    "CSV header order and BOM must be stable",
  );
  assert(
    csv.includes("'\t=HYPERLINK"),
    "leading whitespace formula injection must be neutralized",
  );
  assert(csv.includes('"plus,preview"'), "commas must be RFC-quoted");
  assert(
    !csv.includes("password") &&
      !csv.includes("access_token") &&
      !csv.includes("refresh_token") &&
      !csv.includes("auth_token") &&
      !csv.includes("api_key"),
    "credential and password columns must not exist",
  );
  assert(
    audits.length === 1 && audits[0].outcome === "succeeded",
    "successful exports must be audited once",
  );
  assert(
    !JSON.stringify(audits).includes("person@example.test"),
    "audit must not contain raw search text",
  );
});

Deno.test("CSV helpers neutralize every spreadsheet formula prefix", () => {
  for (const value of ["=1+1", "+1", "-1", "@SUM(A1)", "  =1", "\t+1"]) {
    assert(
      protectCsvFormula(value).startsWith("'"),
      `${JSON.stringify(value)} must be escaped`,
    );
  }
  const encoded = new TextDecoder().decode(buildUsersCsv([user()]));
  assert(
    encoded.includes("admin@example.test"),
    "safe user columns should be encoded",
  );
});

Deno.test("user export rejects URL filters, unknown fields, byte overruns, and timeouts", async () => {
  const queryFilter = await handleAdminConsoleRequest(
    request("/users/export?search=private@example.test", {
      method: "POST",
      body: JSON.stringify({ format: "csv", search: null }),
    }),
    dependencies(),
  );
  assert(queryFilter.status === 400, "export search must never enter a URL");

  const extra = await handleAdminConsoleRequest(
    request("/users/export", {
      method: "POST",
      body: JSON.stringify({ format: "csv", search: null, page: 1 }),
    }),
    dependencies(),
  );
  assert(extra.status === 400, "unknown export fields must fail closed");

  const oversized = await handleAdminConsoleRequest(
    request("/users/export", {
      method: "POST",
      body: JSON.stringify({ format: "csv", search: null }),
    }),
    dependencies(undefined, {
      listUsers: () =>
        Promise.resolve([user({ email: "a".repeat(20 * 1024 * 1024) })]),
    }),
  );
  assert(oversized.status === 413, "exports over 20 MiB must not succeed");

  const clock = [0, 60_000];
  const timedOut = await handleAdminConsoleRequest(
    request("/users/export", {
      method: "POST",
      body: JSON.stringify({ format: "csv", search: null }),
    }),
    dependencies(undefined, {
      nowMs: () => clock.shift() ?? 60_000,
    }),
  );
  assert(
    timedOut.status === 503,
    "exports at the 60-second deadline must fail",
  );
  assert(
    timedOut.headers.get("Content-Disposition") === null,
    "failed exports must never be returned as partial attachments",
  );
});

Deno.test("dashboard exposes the stable frontend metric contract without fabricated values", () => {
  const first = user({
    id: "11111111-1111-4111-8111-111111111111",
    email: "first@example.test",
    created_at: "2026-07-28T00:00:00.000Z",
    plan: "plus",
    period_consumed_ai_credits: 120,
  });
  const second = user({
    id: "22222222-2222-4222-8222-222222222222",
    email: "second@example.test",
    created_at: "2026-07-29T00:00:00.000Z",
    plan: "pro",
    period_consumed_ai_credits: 80,
  });
  const older = user({
    id: "33333333-3333-4333-8333-333333333333",
    email: "older@example.test",
    created_at: "2026-06-01T00:00:00.000Z",
  });
  const event = (
    userId: string,
    name: string,
    receivedAt: string,
    properties: Record<string, unknown> = {},
  ) => ({
    user_id: userId,
    name,
    occurred_at: receivedAt,
    received_at: receivedAt,
    properties,
  });
  const snapshot = buildDashboardSnapshot(
    "7d",
    [first, second, older],
    [
      event(first.id, "registration_verified", "2026-07-28T00:01:00.000Z", {
        source: "docs",
      }),
      event(first.id, "runtime_ready", "2026-07-28T00:02:00.000Z"),
      event(first.id, "draft_saved", "2026-07-28T00:03:00.000Z"),
      event(first.id, "job_created", "2026-07-28T00:04:00.000Z"),
      event(first.id, "job_succeeded", "2026-07-29T01:00:00.000Z"),
      event(second.id, "registration_verified", "2026-07-29T00:01:00.000Z", {
        source: "referral",
      }),
      event(second.id, "job_failed", "2026-07-30T00:00:00.000Z"),
      event(older.id, "assistant_turn_succeeded", "2026-08-03T08:00:00.000Z"),
    ],
    [
      {
        user_id: first.id,
        status: "completed",
        error_code: null,
        created_at: "2026-08-02T00:00:00.000Z",
        input_tokens: 40,
        output_tokens: 20,
        usage_estimated: false,
      },
      {
        user_id: second.id,
        status: "failed",
        error_code: "RATE_LIMITED",
        created_at: "2026-08-03T00:00:00.000Z",
        input_tokens: null,
        output_tokens: null,
        usage_estimated: true,
      },
    ],
    new Date("2026-08-03T12:00:00.000Z"),
  );
  const summary = snapshot.summary as Record<string, unknown>;
  const reliability = snapshot.reliability as Record<string, unknown>;
  const monetization = snapshot.monetization as Record<string, unknown>;
  assert(snapshot.timezone === "UTC", "dashboard timestamps must be UTC");
  assert(
    summary.total_users === 3,
    "total users must come from the safe directory",
  );
  assert(summary.new_users === 2, "new users must be range bounded");
  assert(
    summary.activation_rate_pct === 50,
    "seven-day activation must be cohort based",
  );
  assert(summary.d1_retention_pct === 100, "D1 must use mature user cohorts");
  assert(
    Array.isArray(snapshot.daily) && snapshot.daily.length === 7,
    "daily keys must be stable",
  );
  assert(
    Array.isArray(snapshot.funnel) && snapshot.funnel.length === 5,
    "funnel must be a stable array",
  );
  assert(
    Array.isArray(snapshot.definitions),
    "metric definitions must be an array",
  );
  assert(
    reliability.model_success_pct === 50,
    "model reliability must use trusted rows",
  );
  assert(
    reliability.model_rate_limited_pct === 50,
    "rate limits must be explicit",
  );
  assert(
    reliability.p95_model_latency_ms === null,
    "unavailable latency must remain null",
  );
  assert(
    monetization.plus_users === 1 && monetization.pro_users === 1,
    "plans must remain distinct",
  );
  assert(
    monetization.estimated_usage_requests === 1,
    "estimated usage must be disclosed",
  );
});
