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
  sensitiveAllowedOrigins,
  SensitiveCorsError,
  sensitiveCorsHeaders,
} from "../_shared/sensitive_cors.ts";

type JsonRecord = Record<string, unknown>;
type ClientEventName =
  | "assistant_turn_succeeded"
  | "assistant_turn_failed"
  | "fixed_scenario_selected"
  | "job_created";

const DEFAULT_ALLOWED_ORIGINS = [
  "https://getdronedream.com",
  "https://www.getdronedream.com",
  "http://localhost:5173",
  "http://127.0.0.1:5173",
  "http://tauri.localhost",
  "tauri://localhost",
];
const MAX_BODY_BYTES = 8 * 1024;
const MAX_PROPERTIES = 12;
const MAX_STRING_LENGTH = 96;
const MAX_PAST_MS = 24 * 60 * 60 * 1_000;
const MAX_FUTURE_MS = 5 * 60 * 1_000;
const EVENT_PROPERTIES: Record<ClientEventName, ReadonlySet<string>> = {
  assistant_turn_succeeded: new Set([
    "provider",
    "model",
    "duration_ms",
    "source",
  ]),
  assistant_turn_failed: new Set([
    "provider",
    "model",
    "duration_ms",
    "error_code",
    "source",
  ]),
  fixed_scenario_selected: new Set([
    "scenario_key",
    "template_version",
    "source",
  ]),
  job_created: new Set(["source", "strategy", "parameter_count"]),
};
const SENSITIVE_KEY =
  /(prompt|completion|message|content|config|parameter_value|trajectory|track|file|password|secret|token|authorization|api_?key|byok|email|stack|error_message)/iu;
const TOKEN_LIKE_VALUE =
  /(^|[^A-Za-z0-9])(bearer\s+|sk-[A-Za-z0-9_-]{8,}|eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,})/iu;

export interface ProductEventDependencies {
  authenticate(token: string): Promise<User>;
  record(
    userId: string,
    envelope: ValidatedProductEvent,
  ): Promise<{ inserted: boolean; received_at: string }>;
}

export interface ValidatedProductEvent {
  schema_version: 1;
  event_id: string;
  name: ClientEventName;
  occurred_at: string;
  properties: JsonRecord;
}

class ProductEventError extends Error {
  readonly code: string;
  readonly status: number;

  constructor(code: string, message: string, status: number) {
    super(message);
    this.name = "ProductEventError";
    this.code = code;
    this.status = status;
  }
}

function requiredEnv(name: string): string {
  const value = Deno.env.get(name)?.trim();
  if (!value) {
    throw new ProductEventError(
      "SERVICE_NOT_CONFIGURED",
      "Product analytics is not configured.",
      503,
    );
  }
  return value;
}

function allowedOrigins(): Set<string> {
  return sensitiveAllowedOrigins(
    Deno.env.get("PRODUCT_EVENTS_ALLOWED_ORIGINS"),
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
      "Access-Control-Allow-Methods": "POST, OPTIONS",
    };
  } catch (error) {
    if (error instanceof SensitiveCorsError) {
      throw new ProductEventError(error.code, error.message, error.status);
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
  if (error instanceof ProductEventError) {
    if (
      error.code === "ORIGIN_NOT_ALLOWED" ||
      error.code === "ORIGIN_CONFIGURATION_INVALID"
    ) {
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
  console.error("product-events unexpected failure", "INTERNAL_ERROR");
  return jsonResponse(request, 500, {
    error: {
      code: "INTERNAL_ERROR",
      message: "The product event could not be accepted.",
    },
  });
}

function bearerToken(request: Request): string {
  const match = /^Bearer\s+(.+)$/iu.exec(
    request.headers.get("Authorization")?.trim() ?? "",
  );
  if (!match?.[1]) {
    throw new ProductEventError(
      "AUTHENTICATION_REQUIRED",
      "A valid account session is required.",
      401,
    );
  }
  return match[1].trim();
}

function exactKeys(value: JsonRecord, expected: readonly string[]): boolean {
  const actual = Object.keys(value).sort();
  const sortedExpected = [...expected].sort();
  return actual.length === sortedExpected.length &&
    actual.every((key, index) => key === sortedExpected[index]);
}

function isUuid(value: unknown): value is string {
  return typeof value === "string" &&
    /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/iu
      .test(value);
}

function isClientEventName(value: unknown): value is ClientEventName {
  return typeof value === "string" && value in EVENT_PROPERTIES;
}

function validateOccurredAt(value: unknown, nowMs: number): string {
  if (typeof value !== "string") {
    throw new ProductEventError(
      "INVALID_EVENT",
      "occurred_at must be an ISO timestamp.",
      400,
    );
  }
  const parsed = Date.parse(value);
  if (
    !Number.isFinite(parsed) || parsed < nowMs - MAX_PAST_MS ||
    parsed > nowMs + MAX_FUTURE_MS
  ) {
    throw new ProductEventError(
      "INVALID_EVENT_TIME",
      "occurred_at is outside the accepted time window.",
      400,
    );
  }
  return new Date(parsed).toISOString();
}

function validateProperties(name: ClientEventName, value: unknown): JsonRecord {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new ProductEventError(
      "INVALID_PROPERTIES",
      "properties must be a bounded JSON object.",
      400,
    );
  }
  const properties = value as JsonRecord;
  const entries = Object.entries(properties);
  if (entries.length > MAX_PROPERTIES) {
    throw new ProductEventError(
      "INVALID_PROPERTIES",
      "properties contains too many entries.",
      400,
    );
  }
  const allowed = EVENT_PROPERTIES[name];
  for (const [key, item] of entries) {
    if (
      !/^[a-z][a-z0-9_]{0,47}$/u.test(key) || !allowed.has(key) ||
      SENSITIVE_KEY.test(key)
    ) {
      throw new ProductEventError(
        "INVALID_PROPERTY",
        "An event property is not allowed.",
        400,
      );
    }
    if (
      item !== null && !["string", "number", "boolean"].includes(typeof item)
    ) {
      throw new ProductEventError(
        "INVALID_PROPERTY",
        "Event properties must be JSON primitives.",
        400,
      );
    }
    if (typeof item === "string") {
      if (
        item.length > MAX_STRING_LENGTH ||
        !/^[A-Za-z0-9_.:@/\-]*$/u.test(item) ||
        TOKEN_LIKE_VALUE.test(item)
      ) {
        throw new ProductEventError(
          "SENSITIVE_PROPERTY_REJECTED",
          "An event property value is not allowed.",
          400,
        );
      }
    }
    if (typeof item === "number" && !Number.isFinite(item)) {
      throw new ProductEventError(
        "INVALID_PROPERTY",
        "Numeric event properties must be finite.",
        400,
      );
    }
  }
  return properties;
}

export function validateProductEvent(
  body: JsonRecord,
  nowMs = Date.now(),
): ValidatedProductEvent {
  if (
    !exactKeys(body, [
      "schema_version",
      "event_id",
      "name",
      "occurred_at",
      "properties",
    ])
  ) {
    throw new ProductEventError(
      "INVALID_EVENT",
      "The product event envelope is invalid.",
      400,
    );
  }
  if (
    body.schema_version !== 1 || !isUuid(body.event_id) ||
    !isClientEventName(body.name)
  ) {
    throw new ProductEventError(
      "INVALID_EVENT",
      "The product event envelope is invalid.",
      400,
    );
  }
  return {
    schema_version: 1,
    event_id: body.event_id,
    name: body.name,
    occurred_at: validateOccurredAt(body.occurred_at, nowMs),
    properties: validateProperties(body.name, body.properties),
  };
}

let cachedClient: SupabaseClient | null = null;

function adminClient(): SupabaseClient {
  if (cachedClient) return cachedClient;
  cachedClient = createClient(
    requiredEnv("SUPABASE_URL"),
    requiredEnv("SUPABASE_SERVICE_ROLE_KEY"),
    { auth: { autoRefreshToken: false, persistSession: false } },
  );
  return cachedClient;
}

function actualDependencies(): ProductEventDependencies {
  const client = adminClient();
  return {
    async authenticate(token) {
      const { data, error } = await client.auth.getUser(token);
      if (error || !data.user) {
        throw new ProductEventError(
          "AUTHENTICATION_REQUIRED",
          "The account session is invalid.",
          401,
        );
      }
      return data.user;
    },
    async record(userId, envelope) {
      const { data, error } = await client.rpc("record_product_event", {
        p_user_id: userId,
        p_event_id: envelope.event_id,
        p_schema_version: envelope.schema_version,
        p_name: envelope.name,
        p_occurred_at: envelope.occurred_at,
        p_properties: envelope.properties,
      });
      const row = Array.isArray(data) ? data[0] : data;
      if (error || !row || typeof row !== "object") {
        throw new ProductEventError(
          "EVENT_STORAGE_FAILED",
          "The product event could not be stored.",
          503,
        );
      }
      const record = row as JsonRecord;
      return {
        inserted: record.inserted === true,
        received_at: String(record.received_at ?? ""),
      };
    },
  };
}

export async function handleProductEventsRequest(
  request: Request,
  dependencies?: ProductEventDependencies,
): Promise<Response> {
  try {
    const cors = corsHeaders(request);
    if (request.method === "OPTIONS") {
      return new Response(null, { status: 204, headers: cors });
    }
    const pathname = new URL(request.url).pathname.replace(/\/+$/u, "");
    if (request.method !== "POST" || !pathname.endsWith("/product-events")) {
      return jsonResponse(request, 404, {
        error: {
          code: "NOT_FOUND",
          message: "The product-events route was not found.",
        },
      });
    }
    const deps = dependencies ?? actualDependencies();
    const user = await deps.authenticate(bearerToken(request));
    const envelope = validateProductEvent(
      await readBoundedJsonObject(request, MAX_BODY_BYTES),
    );
    const result = await deps.record(user.id, envelope);
    return jsonResponse(request, result.inserted ? 201 : 200, {
      accepted: true,
      duplicate: !result.inserted,
      event_id: envelope.event_id,
      received_at: result.received_at,
    });
  } catch (error) {
    return errorResponse(request, error);
  }
}

if (import.meta.main) {
  Deno.serve((request) => handleProductEventsRequest(request));
}
