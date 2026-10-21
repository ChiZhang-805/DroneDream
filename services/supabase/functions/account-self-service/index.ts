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

const DEFAULT_ALLOWED_ORIGINS = [
  "https://getdronedream.com",
  "https://www.getdronedream.com",
  "http://localhost:5173",
  "http://127.0.0.1:5173",
  "http://tauri.localhost",
  "tauri://localhost",
];
const MAX_BODY_BYTES = 1024;

export interface AccountSelfServiceDependencies {
  authenticate(token: string): Promise<{ id: string }>;
  deleteAccount(userId: string): Promise<void>;
}

export class AccountSelfServiceError extends Error {
  readonly code: string;
  readonly status: number;

  constructor(code: string, message: string, status: number) {
    super(message);
    this.name = "AccountSelfServiceError";
    this.code = code;
    this.status = status;
  }
}

function requiredEnv(name: string): string {
  const value = Deno.env.get(name)?.trim();
  if (!value) {
    throw new AccountSelfServiceError(
      "SERVICE_NOT_CONFIGURED",
      "Account deletion is not configured.",
      503,
    );
  }
  return value;
}

function allowedOrigins(): Set<string> {
  return sensitiveAllowedOrigins(
    Deno.env.get("ACCOUNT_SELF_SERVICE_ALLOWED_ORIGINS"),
    DEFAULT_ALLOWED_ORIGINS,
  );
}

function corsHeaders(request: Request): HeadersInit {
  if (!request.headers.get("Origin")) return {};
  try {
    return {
      ...sensitiveCorsHeaders(request, allowedOrigins()),
      "Access-Control-Allow-Headers": "authorization, apikey, content-type, x-client-info",
      "Access-Control-Allow-Methods": "POST, OPTIONS",
    };
  } catch (error) {
    if (error instanceof SensitiveCorsError) {
      throw new AccountSelfServiceError(error.code, error.message, error.status);
    }
    throw error;
  }
}

function jsonResponse(request: Request, status: number, body: JsonRecord): Response {
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
  if (error instanceof BoundedRequestError || error instanceof AccountSelfServiceError) {
    if (
      error instanceof AccountSelfServiceError &&
      ["ORIGIN_NOT_ALLOWED", "ORIGIN_CONFIGURATION_INVALID"].includes(error.code)
    ) {
      return new Response(JSON.stringify({ error: { code: error.code, message: error.message } }), {
        status: error.status,
        headers: {
          "Content-Type": "application/json; charset=utf-8",
          "Cache-Control": "private, no-store",
        },
      });
    }
    return jsonResponse(request, error.status, {
      error: { code: error.code, message: error.message },
    });
  }
  console.error("account-self-service unexpected failure", "INTERNAL_ERROR");
  return jsonResponse(request, 500, {
    error: { code: "INTERNAL_ERROR", message: "The account request could not be completed." },
  });
}

function bearerToken(request: Request): string {
  const match = /^Bearer\s+(.+)$/iu.exec(request.headers.get("Authorization")?.trim() ?? "");
  if (!match?.[1]) {
    throw new AccountSelfServiceError(
      "AUTHENTICATION_REQUIRED",
      "A valid account session is required.",
      401,
    );
  }
  return match[1].trim();
}

function validateDeleteBody(body: JsonRecord): void {
  const keys = Object.keys(body);
  if (keys.length !== 1 || keys[0] !== "confirmation" || body.confirmation !== "DELETE") {
    throw new AccountSelfServiceError(
      "ACCOUNT_DELETE_CONFIRMATION_REQUIRED",
      "Confirm permanent account deletion.",
      400,
    );
  }
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

function mapRpcError(error: { message?: string } | null): never {
  const message = error?.message ?? "";
  if (message.includes("ACCOUNT_DELETE_TRANSFER_FOUNDER")) {
    throw new AccountSelfServiceError(
      "ACCOUNT_DELETE_TRANSFER_FOUNDER",
      "Transfer the organization Founder role before deleting this account.",
      409,
    );
  }
  if (message.includes("ACCOUNT_DELETE_RETENTION_REQUIRED")) {
    throw new AccountSelfServiceError(
      "ACCOUNT_DELETE_RETENTION_REQUIRED",
      "This account has records that must be retained. Contact support for account closure.",
      409,
    );
  }
  if (message.includes("ACCOUNT_DELETE_NOT_FOUND")) {
    throw new AccountSelfServiceError("ACCOUNT_DELETE_NOT_FOUND", "This account no longer exists.", 404);
  }
  throw new AccountSelfServiceError(
    "ACCOUNT_DELETE_FAILED",
    "The account could not be deleted.",
    503,
  );
}

function actualDependencies(): AccountSelfServiceDependencies {
  const client = adminClient();
  return {
    async authenticate(token) {
      const { data, error } = await client.auth.getUser(token);
      if (error || !data.user) {
        throw new AccountSelfServiceError(
          "AUTHENTICATION_REQUIRED",
          "The account session is invalid.",
          401,
        );
      }
      return { id: data.user.id };
    },
    async deleteAccount(userId) {
      const { error } = await client.rpc("account_delete_self", { p_user_id: userId });
      if (error) mapRpcError(error);
    },
  };
}

export async function handleAccountSelfServiceRequest(
  request: Request,
  dependencies?: AccountSelfServiceDependencies,
): Promise<Response> {
  try {
    const cors = corsHeaders(request);
    if (request.method === "OPTIONS") return new Response(null, { status: 204, headers: cors });

    const pathname = new URL(request.url).pathname.replace(/\/+$/u, "");
    if (request.method !== "POST" || !pathname.endsWith("/account-self-service/delete")) {
      return jsonResponse(request, 404, {
        error: { code: "NOT_FOUND", message: "The account self-service route was not found." },
      });
    }

    const body = await readBoundedJsonObject(request, MAX_BODY_BYTES);
    validateDeleteBody(body);
    const deps = dependencies ?? actualDependencies();
    const user = await deps.authenticate(bearerToken(request));
    await deps.deleteAccount(user.id);
    return jsonResponse(request, 200, { deleted: true });
  } catch (error) {
    return errorResponse(request, error);
  }
}

if (import.meta.main) {
  Deno.serve((request) => handleAccountSelfServiceRequest(request));
}
