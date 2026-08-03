import {
  createClient,
  type SupabaseClient,
  type User,
} from "npm:@supabase/supabase-js@2.110.8";
import {
  BoundedRequestError,
  readBoundedJsonObject,
} from "../_shared/bounded_request.ts";
import {
  BoundedResponseError,
  readBoundedResponseText,
} from "../_shared/bounded_response.ts";
import {
  sensitiveAllowedOrigins,
  SensitiveCorsError,
  sensitiveCorsHeaders,
} from "../_shared/sensitive_cors.ts";

type JsonRecord = Record<string, unknown>;
type ModelPurpose = "assistant" | "job";
export type ModelProvider = "openai" | "deepseek" | "qwen";

const DEFAULT_ALLOWED_ORIGINS = [
  "https://getdronedream.com",
  "https://www.getdronedream.com",
  "http://localhost:5173",
  "http://127.0.0.1:5173",
  "http://tauri.localhost",
  "tauri://localhost",
];
const MAX_REQUEST_BYTES = 300_000;
const MAX_MESSAGES = 128;
const MAX_MESSAGE_CONTENT_BYTES = 262_144;
const MODEL_PROVIDER_RESPONSE_BASE_BYTES = 32 * 1_024;
const MODEL_PROVIDER_RESPONSE_BYTES_PER_OUTPUT_TOKEN = 64;
const MODEL_PROVIDER_RESPONSE_HARD_CAP_BYTES = 1_024 * 1_024;
const MODEL_PROVIDER_MAX_OUTPUT_TOKENS = 16_384;

class GatewayError extends Error {
  readonly code: string;
  readonly status: number;

  constructor(code: string, message: string, status: number) {
    super(message);
    this.name = "GatewayError";
    this.code = code;
    this.status = status;
  }
}

function requiredEnv(name: string): string {
  const value = Deno.env.get(name)?.trim();
  if (!value) {
    throw new GatewayError(
      "SERVICE_NOT_CONFIGURED",
      `The model gateway is missing required server configuration (${name}).`,
      503,
    );
  }
  return value;
}

function positiveIntegerEnv(
  name: string,
  fallback: number,
  minimum: number,
  maximum: number,
): number {
  const raw = Deno.env.get(name)?.trim();
  if (!raw) return fallback;
  const parsed = Number(raw);
  if (!Number.isSafeInteger(parsed) || parsed < minimum || parsed > maximum) {
    throw new GatewayError(
      "SERVICE_NOT_CONFIGURED",
      `${name} must be an integer from ${minimum} to ${maximum}.`,
      503,
    );
  }
  return parsed;
}

function allowedOrigins(): Set<string> {
  return sensitiveAllowedOrigins(
    Deno.env.get("MODEL_GATEWAY_ALLOWED_ORIGINS"),
    DEFAULT_ALLOWED_ORIGINS,
  );
}

function corsHeaders(request: Request): HeadersInit {
  if (!request.headers.get("Origin")) return {};
  let originHeaders: HeadersInit;
  try {
    originHeaders = sensitiveCorsHeaders(request, allowedOrigins());
  } catch (error) {
    if (error instanceof SensitiveCorsError) {
      throw new GatewayError(error.code, error.message, error.status);
    }
    throw error;
  }
  return {
    ...originHeaders,
    "Access-Control-Allow-Headers":
      "authorization, apikey, content-type, idempotency-key, x-client-info",
    "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
    "Access-Control-Expose-Headers":
      "x-dronedream-usage-estimated, x-dronedream-consumed-credits",
  };
}

function uncorsedJsonResponse(status: number, body: JsonRecord): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: {
      "Content-Type": "application/json; charset=utf-8",
      "Cache-Control": "no-store",
    },
  });
}

function jsonResponse(
  request: Request,
  status: number,
  body: JsonRecord,
  extraHeaders: HeadersInit = {},
): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: {
      "Content-Type": "application/json; charset=utf-8",
      "Cache-Control": "no-store",
      ...corsHeaders(request),
      ...extraHeaders,
    },
  });
}

function errorResponse(request: Request, error: unknown): Response {
  if (error instanceof BoundedRequestError) {
    return jsonResponse(request, error.status, {
      error: { code: error.code, message: error.message },
    });
  }
  if (error instanceof GatewayError) {
    if (
      error.code === "ORIGIN_NOT_ALLOWED" ||
      error.code === "ORIGIN_CONFIGURATION_INVALID"
    ) {
      return uncorsedJsonResponse(error.status, {
        error: { code: error.code, message: error.message },
      });
    }
    return jsonResponse(request, error.status, {
      error: { code: error.code, message: error.message },
    });
  }
  const rawMessage = error instanceof Error ? error.message : "";
  const knownCode = [
    "MODEL_QUOTA_EXHAUSTED",
    "MODEL_GRANT_INVALID",
    "MODEL_PLAN_UNAVAILABLE",
    "MODEL_PROVIDER_DISABLED",
    "CREDIT_POLICY_MISMATCH",
    "IDEMPOTENCY_CONFLICT",
  ].find((code) => rawMessage.includes(code));
  if (knownCode) {
    const status = knownCode === "MODEL_QUOTA_EXHAUSTED" ? 402 : 409;
    return jsonResponse(request, status, {
      error: {
        code: knownCode,
        message: knownCode === "MODEL_QUOTA_EXHAUSTED"
          ? "The included managed-model allowance is exhausted. Switch to BYOK or upgrade."
          : "The managed-model request could not be authorized.",
      },
    });
  }
  console.error("model-gateway unexpected error", error);
  return jsonResponse(request, 500, {
    error: {
      code: "INTERNAL_ERROR",
      message: "The managed-model gateway could not complete the request.",
    },
  });
}

let cachedAdmin: SupabaseClient | null = null;

function adminClient(): SupabaseClient {
  if (cachedAdmin) return cachedAdmin;
  cachedAdmin = createClient(
    requiredEnv("SUPABASE_URL"),
    requiredEnv("SUPABASE_SERVICE_ROLE_KEY"),
    {
      auth: {
        autoRefreshToken: false,
        persistSession: false,
      },
    },
  );
  return cachedAdmin;
}

function bearerToken(request: Request): string {
  const authorization = request.headers.get("Authorization")?.trim() ?? "";
  const match = /^Bearer\s+(.+)$/i.exec(authorization);
  if (!match?.[1]) {
    throw new GatewayError(
      "AUTHENTICATION_REQUIRED",
      "A bearer token is required.",
      401,
    );
  }
  return match[1].trim();
}

async function authenticatedUser(request: Request): Promise<User> {
  const token = bearerToken(request);
  if (token.startsWith("ddg_")) {
    throw new GatewayError(
      "AUTHENTICATION_REQUIRED",
      "A signed-in account is required.",
      401,
    );
  }
  const { data, error } = await adminClient().auth.getUser(token);
  if (error || !data.user) {
    throw new GatewayError(
      "AUTHENTICATION_REQUIRED",
      "The account session is invalid.",
      401,
    );
  }
  return data.user;
}

function endpointPath(request: Request): string {
  const pathname = new URL(request.url).pathname.replace(/\/+$/, "");
  const marker = "/model-gateway";
  const markerIndex = pathname.lastIndexOf(marker);
  return markerIndex >= 0
    ? pathname.slice(markerIndex + marker.length) || "/"
    : pathname;
}

function isRecord(value: unknown): value is JsonRecord {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function readJsonBody(request: Request): Promise<JsonRecord> {
  return readBoundedJsonObject(request, MAX_REQUEST_BYTES);
}

export function modelProvider(value: unknown): ModelProvider {
  if (value === "openai" || value === "deepseek" || value === "qwen") {
    return value;
  }
  throw new GatewayError(
    "INVALID_MODEL_PROVIDER",
    "provider must be openai, deepseek, or qwen.",
    400,
  );
}

function grantKeysAreValid(body: JsonRecord): boolean {
  const keys = Object.keys(body);
  return keys.every((key) =>
    ["scope", "provider", "scope_reference"].includes(key)
  ) &&
    keys.includes("scope") && keys.includes("provider");
}

function base64Url(bytes: Uint8Array): string {
  let binary = "";
  for (const byte of bytes) binary += String.fromCharCode(byte);
  return btoa(binary)
    .replaceAll("+", "-")
    .replaceAll("/", "_")
    .replace(/=+$/u, "");
}

async function sha256Hex(value: string): Promise<string> {
  const bytes = new TextEncoder().encode(value);
  const digest = new Uint8Array(await crypto.subtle.digest("SHA-256", bytes));
  return [...digest].map((byte) => byte.toString(16).padStart(2, "0")).join("");
}

function newGrantToken(): string {
  const entropy = crypto.getRandomValues(new Uint8Array(32));
  return `ddg_${base64Url(entropy)}`;
}

function validScopeReference(value: unknown): string | null {
  if (value == null || value === "") return null;
  if (
    typeof value !== "string" ||
    value.length > 128 ||
    !/^[A-Za-z0-9_.:-]+$/u.test(value)
  ) {
    throw new GatewayError(
      "INVALID_REQUEST",
      "scope_reference is invalid.",
      400,
    );
  }
  return value;
}

async function usageSnapshot(userId: string): Promise<JsonRecord> {
  const { data, error } = await adminClient().rpc("model_access_snapshot", {
    p_user_id: userId,
  });
  if (error || !isRecord(data)) {
    throw error ?? new Error("MODEL_USAGE_SNAPSHOT_INVALID");
  }
  return data;
}

async function handleUsage(request: Request): Promise<Response> {
  const user = await authenticatedUser(request);
  return jsonResponse(request, 200, { data: await usageSnapshot(user.id) });
}

async function handleModels(request: Request): Promise<Response> {
  await authenticatedUser(request);
  const { data, error } = await adminClient().from("model_provider_policies")
    .select("provider,enabled,assistant_enabled,job_enabled,version,updated_at")
    .order("provider");
  if (error) {
    throw new GatewayError(
      "MODEL_CATALOG_UNAVAILABLE",
      "The managed model catalog is unavailable.",
      503,
    );
  }
  return jsonResponse(request, 200, {
    data: (data ?? []).map((row) => ({
      provider: row.provider,
      enabled: row.enabled,
      assistant_enabled: row.assistant_enabled,
      job_enabled: row.job_enabled,
      version: row.version,
      updated_at: row.updated_at,
      managed_model: providerAlias(modelProvider(row.provider)),
    })),
  });
}

async function handleGrant(request: Request): Promise<Response> {
  const user = await authenticatedUser(request);
  const body = await readJsonBody(request);
  if (!grantKeysAreValid(body)) {
    throw new GatewayError(
      "INVALID_REQUEST",
      "The grant request body is invalid.",
      400,
    );
  }
  const scope = body.scope;
  if (scope !== "assistant" && scope !== "job") {
    throw new GatewayError(
      "INVALID_REQUEST",
      "scope must be assistant or job.",
      400,
    );
  }
  const provider = modelProvider(body.provider);
  const token = newGrantToken();
  const tokenHash = await sha256Hex(token);
  const { data, error } = await adminClient().rpc("model_gateway_issue_grant", {
    p_user_id: user.id,
    p_token_sha256: tokenHash,
    p_scope: scope,
    p_provider: provider,
    p_scope_reference: validScopeReference(body.scope_reference),
  });
  if (error || !isRecord(data)) {
    throw error ?? new Error("MODEL_GRANT_ISSUE_FAILED");
  }
  const requestUrl = new URL(request.url);
  requestUrl.pathname = requestUrl.pathname
    .replace(/\/grants\/?$/u, "/chat/completions");
  return jsonResponse(request, 201, {
    data: {
      access_mode: "platform",
      grant: token,
      scope,
      provider,
      expires_at: data.expires_at,
      max_calls: data.max_calls,
      gateway_base_url: requestUrl.toString().replace(
        /\/chat\/completions$/u,
        "",
      ),
      managed_model: providerAlias(provider),
      usage: await usageSnapshot(user.id),
    },
  });
}

function validateMessages(value: unknown): JsonRecord[] {
  if (
    !Array.isArray(value) || value.length < 1 || value.length > MAX_MESSAGES
  ) {
    throw new GatewayError(
      "INVALID_REQUEST",
      "messages must be a non-empty bounded array.",
      400,
    );
  }
  let contentBytes = 0;
  const messages = value.map((item) => {
    if (!isRecord(item)) {
      throw new GatewayError(
        "INVALID_REQUEST",
        "Each message must be an object.",
        400,
      );
    }
    if (!["system", "user", "assistant"].includes(String(item.role))) {
      throw new GatewayError(
        "INVALID_REQUEST",
        "A message role is not allowed.",
        400,
      );
    }
    if (typeof item.content !== "string") {
      throw new GatewayError(
        "INVALID_REQUEST",
        "Message content must be text.",
        400,
      );
    }
    contentBytes += new TextEncoder().encode(item.content).byteLength;
    return { role: item.role, content: item.content };
  });
  if (contentBytes > MAX_MESSAGE_CONTENT_BYTES) {
    throw new GatewayError(
      "MODEL_PROMPT_TOO_LARGE",
      "The model prompt is too large.",
      413,
    );
  }
  return messages;
}

function idempotencyKey(request: Request): string {
  const raw = request.headers.get("Idempotency-Key")?.trim() ||
    crypto.randomUUID();
  if (raw.length < 8 || raw.length > 128 || !/^[A-Za-z0-9_.:-]+$/u.test(raw)) {
    throw new GatewayError(
      "INVALID_IDEMPOTENCY_KEY",
      "Idempotency-Key is invalid.",
      400,
    );
  }
  return raw;
}

function providerAlias(provider: ModelProvider): string {
  return Deno.env.get(`PLATFORM_${provider.toUpperCase()}_MODEL_ALIAS`)
    ?.trim() ||
    Deno.env.get("PLATFORM_LLM_MODEL_ALIAS")?.trim() || "DroneDream Managed";
}

function providerConfiguration(provider: ModelProvider) {
  const prefix = `PLATFORM_${provider.toUpperCase()}`;
  const legacyBaseUrl = provider === "openai"
    ? Deno.env.get("PLATFORM_LLM_BASE_URL")?.trim()
    : undefined;
  const baseUrl =
    (Deno.env.get(`${prefix}_BASE_URL`)?.trim() || legacyBaseUrl ||
      (provider === "openai" ? "https://api.openai.com/v1" : "")).replace(
        /\/+$/u,
        "",
      );
  if (!baseUrl) {
    throw new GatewayError(
      "SERVICE_NOT_CONFIGURED",
      `${prefix}_BASE_URL is required.`,
      503,
    );
  }
  const parsed = new URL(baseUrl);
  if (parsed.protocol !== "https:" || parsed.username || parsed.password) {
    throw new GatewayError(
      "SERVICE_NOT_CONFIGURED",
      `${prefix}_BASE_URL must be a credential-free HTTPS URL.`,
      503,
    );
  }
  return {
    apiKey: requiredEnv(
      Deno.env.get(`${prefix}_API_KEY`)?.trim()
        ? `${prefix}_API_KEY`
        : provider === "openai"
        ? "PLATFORM_LLM_API_KEY"
        : `${prefix}_API_KEY`,
    ),
    baseUrl,
    model: requiredEnv(
      Deno.env.get(`${prefix}_MODEL`)?.trim()
        ? `${prefix}_MODEL`
        : provider === "openai"
        ? "PLATFORM_LLM_MODEL"
        : `${prefix}_MODEL`,
    ),
    provider,
    alias: providerAlias(provider),
    maxOutputTokens: positiveIntegerEnv(
      "PLATFORM_LLM_MAX_OUTPUT_TOKENS",
      2_048,
      64,
      16_384,
    ),
    outputCreditWeight: positiveIntegerEnv(
      "PLATFORM_LLM_OUTPUT_CREDIT_WEIGHT",
      4,
      1,
      100,
    ),
    creditPolicyVersion: positiveIntegerEnv(
      "PLATFORM_LLM_CREDIT_POLICY_VERSION",
      1,
      1,
      1_000_000,
    ),
  };
}

export function modelProviderResponseLimitBytes(
  maxOutputTokens: number,
): number {
  const boundedTokens = Number.isSafeInteger(maxOutputTokens) &&
      maxOutputTokens > 0
    ? Math.min(maxOutputTokens, MODEL_PROVIDER_MAX_OUTPUT_TOKENS)
    : 64;
  return Math.min(
    MODEL_PROVIDER_RESPONSE_HARD_CAP_BYTES,
    MODEL_PROVIDER_RESPONSE_BASE_BYTES +
      boundedTokens * MODEL_PROVIDER_RESPONSE_BYTES_PER_OUTPUT_TOKEN,
  );
}

export function readModelProviderResponseBody(
  response: Response,
  maxOutputTokens: number,
): Promise<string> {
  return readBoundedResponseText(
    response,
    modelProviderResponseLimitBytes(maxOutputTokens),
  );
}

function integerUsage(value: unknown): number | null {
  return Number.isSafeInteger(value) && Number(value) >= 0
    ? Number(value)
    : null;
}

async function failReservation(requestId: string, code: string): Promise<void> {
  const { error } = await adminClient().rpc("model_usage_fail", {
    p_request_id: requestId,
    p_error_code: code,
  });
  if (error) {
    console.error("failed to release model reservation", requestId, error);
  }
}

async function handleChatCompletions(request: Request): Promise<Response> {
  const grant = bearerToken(request);
  if (!grant.startsWith("ddg_") || grant.length < 40 || grant.length > 128) {
    throw new GatewayError(
      "MODEL_GRANT_INVALID",
      "The managed-model grant is invalid.",
      401,
    );
  }
  const body = await readJsonBody(request);
  const messages = validateMessages(body.messages);
  const responseFormat = body.response_format;
  if (responseFormat != null && !isRecord(responseFormat)) {
    throw new GatewayError(
      "INVALID_REQUEST",
      "response_format must be an object.",
      400,
    );
  }
  const requestKey = idempotencyKey(request);
  const requestId = crypto.randomUUID();
  const tokenHash = await sha256Hex(grant);
  const { data: grantRecord, error: grantLookupError } = await adminClient()
    .from("model_gateway_grants")
    .select("scope,provider")
    .eq("token_sha256", tokenHash)
    .maybeSingle();
  if (
    grantLookupError ||
    !isRecord(grantRecord) ||
    (grantRecord.scope !== "assistant" && grantRecord.scope !== "job") ||
    !["openai", "deepseek", "qwen"].includes(String(grantRecord.provider))
  ) {
    throw new GatewayError(
      "MODEL_GRANT_INVALID",
      "The managed-model grant is invalid.",
      401,
    );
  }
  const purpose = grantRecord.scope as ModelPurpose;
  const provider = modelProvider(grantRecord.provider);
  const config = providerConfiguration(provider);
  const serializedPromptBytes = new TextEncoder().encode(JSON.stringify({
    messages,
    response_format: responseFormat ?? null,
  })).byteLength;
  // UTF-8 bytes are a conservative upper bound for byte-level model tokens.
  // Output is reserved at its configured maximum and weighted by policy.
  const reservedCredits = serializedPromptBytes +
    config.maxOutputTokens * config.outputCreditWeight;
  const { data: reservation, error: reserveError } = await adminClient().rpc(
    "model_usage_reserve",
    {
      p_request_id: requestId,
      p_request_key: requestKey,
      p_token_sha256: tokenHash,
      p_purpose: purpose,
      p_provider: config.provider,
      p_model: config.model,
      p_reserved_ai_credits: reservedCredits,
      p_output_credit_weight: config.outputCreditWeight,
      p_credit_policy_version: config.creditPolicyVersion,
    },
  );
  if (reserveError) throw reserveError;
  if (!isRecord(reservation) || reservation.request_id !== requestId) {
    throw new GatewayError(
      "IDEMPOTENCY_CONFLICT",
      "This model request was already processed or is still in progress.",
      409,
    );
  }

  const providerBody: JsonRecord = {
    model: config.model,
    messages,
    stream: false,
    max_completion_tokens: config.maxOutputTokens,
  };
  if (responseFormat) providerBody.response_format = responseFormat;

  let providerResponse: Response;
  try {
    providerResponse = await fetch(`${config.baseUrl}/chat/completions`, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${config.apiKey}`,
        "Content-Type": "application/json",
        Accept: "application/json",
        "Idempotency-Key": requestKey,
      },
      body: JSON.stringify(providerBody),
      signal: AbortSignal.timeout(
        positiveIntegerEnv("PLATFORM_LLM_TIMEOUT_MS", 90_000, 5_000, 300_000),
      ),
    });
  } catch (error) {
    await failReservation(requestId, "PROVIDER_NETWORK_ERROR");
    console.error("managed model provider network error", error);
    throw new GatewayError(
      "MODEL_PROVIDER_UNAVAILABLE",
      "The managed model provider is temporarily unavailable.",
      503,
    );
  }

  let providerText: string;
  try {
    providerText = await readModelProviderResponseBody(
      providerResponse,
      config.maxOutputTokens,
    );
  } catch (error) {
    const rejectionCode = error instanceof BoundedResponseError
      ? error.code
      : "UPSTREAM_RESPONSE_READ_FAILED";
    await failReservation(requestId, rejectionCode);
    console.error("managed model provider response rejected", rejectionCode);
    throw new GatewayError(
      "MODEL_PROVIDER_INVALID_RESPONSE",
      "The managed model provider returned an invalid response.",
      502,
    );
  }
  if (!providerResponse.ok) {
    await failReservation(
      requestId,
      `PROVIDER_HTTP_${providerResponse.status}`,
    );
    console.error("managed model provider HTTP error", providerResponse.status);
    throw new GatewayError(
      "MODEL_PROVIDER_FAILED",
      "The managed model provider could not complete the request.",
      providerResponse.status === 429 ? 429 : 502,
    );
  }

  let providerJson: JsonRecord;
  try {
    const parsed: unknown = JSON.parse(providerText);
    if (!isRecord(parsed)) {
      throw new Error("provider response is not an object");
    }
    providerJson = parsed;
  } catch {
    await failReservation(requestId, "PROVIDER_RESPONSE_INVALID");
    throw new GatewayError(
      "MODEL_PROVIDER_INVALID_RESPONSE",
      "The managed model provider returned an invalid response.",
      502,
    );
  }

  const usage = isRecord(providerJson.usage) ? providerJson.usage : null;
  const inputTokens = integerUsage(usage?.prompt_tokens);
  const outputTokens = integerUsage(usage?.completion_tokens);
  const totalTokens = integerUsage(usage?.total_tokens);
  const hasActualUsage = inputTokens !== null &&
    outputTokens !== null &&
    totalTokens === inputTokens + outputTokens;
  const consumedCredits = hasActualUsage
    ? inputTokens + outputTokens * config.outputCreditWeight
    : reservedCredits;
  const { error: settleError } = await adminClient().rpc("model_usage_settle", {
    p_request_id: requestId,
    p_consumed_ai_credits: consumedCredits,
    p_input_tokens: hasActualUsage ? inputTokens : null,
    p_output_tokens: hasActualUsage ? outputTokens : null,
    p_total_tokens: hasActualUsage ? totalTokens : null,
    p_usage_estimated: !hasActualUsage,
    p_provider_request_id: typeof providerJson.id === "string"
      ? providerJson.id
      : null,
  });
  if (settleError) {
    console.error(
      "managed model usage settlement failed",
      requestId,
      settleError,
    );
    throw new GatewayError(
      "MODEL_USAGE_SETTLEMENT_FAILED",
      "The model response was produced but its allowance receipt could not be sealed.",
      503,
    );
  }

  // The managed service deliberately exposes a stable DroneDream alias rather
  // than leaking or coupling clients to the upstream provider/model choice.
  providerJson.model = config.alias;
  delete providerJson.system_fingerprint;
  return new Response(JSON.stringify(providerJson), {
    status: 200,
    headers: {
      "Content-Type": "application/json; charset=utf-8",
      "Cache-Control": "no-store",
      "X-DroneDream-Usage-Estimated": String(!hasActualUsage),
      "X-DroneDream-Consumed-Credits": String(consumedCredits),
      ...corsHeaders(request),
    },
  });
}

export async function handleModelGatewayRequest(
  request: Request,
): Promise<Response> {
  try {
    const cors = corsHeaders(request);
    if (request.method === "OPTIONS") {
      return new Response(null, { status: 204, headers: cors });
    }
    const path = endpointPath(request);
    if (request.method === "GET" && path === "/usage") {
      return await handleUsage(request);
    }
    if (request.method === "GET" && path === "/models") {
      return await handleModels(request);
    }
    if (request.method === "POST" && path === "/grants") {
      return await handleGrant(request);
    }
    if (request.method === "POST" && path === "/chat/completions") {
      return await handleChatCompletions(request);
    }
    return jsonResponse(request, 404, {
      error: {
        code: "NOT_FOUND",
        message: "The model-gateway route was not found.",
      },
    });
  } catch (error) {
    return errorResponse(request, error);
  }
}

if (import.meta.main) {
  Deno.serve(handleModelGatewayRequest);
}
