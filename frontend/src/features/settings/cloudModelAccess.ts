import { getAuthAccessToken } from "../auth/authTokenStore";
import {
  FetchDeadlineError,
  FetchResponseSizeError,
  fetchWithDeadline,
} from "../../api/fetchWithDeadline";
import type { ManagedModelProvider } from "./ModelAccessContext";

export type ManagedModelPlanId = "free" | "plus" | "pro";
export type ManagedModelGrantScope = "assistant" | "job";
export type PaymentMethod = "alipay" | "wechat" | "card";

export interface ManagedModelPlan {
  id: ManagedModelPlanId;
  name: string;
  monthly_price_cny_fen: number;
  included_ai_credits: number;
  capability_set: "core-v1";
}

export interface ManagedModelUsageTotals {
  reserved_ai_credits: number;
  consumed_ai_credits: number;
  remaining_ai_credits: number;
  request_count: number;
  input_tokens: number;
  output_tokens: number;
  total_tokens: number;
  estimated_request_count: number;
  credit_policy_version: number;
}

export interface ManagedModelUsageRequest {
  request_id: string;
  purpose: ManagedModelGrantScope;
  provider: string;
  model: string;
  status: "reserved" | "completed" | "failed" | "expired";
  reserved_ai_credits: number;
  consumed_ai_credits: number | null;
  input_tokens: number | null;
  output_tokens: number | null;
  total_tokens: number | null;
  usage_estimated: boolean;
  created_at: string;
  settled_at: string | null;
}

export interface ManagedModelUsageSnapshot {
  plan: ManagedModelPlan;
  period: {
    starts_at: string;
    ends_at: string;
  };
  usage: ManagedModelUsageTotals;
  recent_requests: ManagedModelUsageRequest[];
}

export interface ManagedModelGrant {
  access_mode: "platform";
  grant: string;
  scope: ManagedModelGrantScope;
  expires_at: string;
  max_calls: number;
  gateway_base_url: string;
  managed_model: string;
  usage: ManagedModelUsageSnapshot;
}

export interface ManagedModelChatMessage {
  role: "system" | "user" | "assistant";
  content: string;
}

export interface ManagedModelChatCompletion {
  id?: string;
  model: string;
  choices: Array<{
    message: {
      role: "assistant";
      content: string;
    };
  }>;
  usage?: {
    prompt_tokens?: number;
    completion_tokens?: number;
    total_tokens?: number;
  };
}

export interface ManagedModelCatalogEntry {
  provider: ManagedModelProvider;
  display_name: string;
  model: string;
  enabled: boolean;
  assistant_enabled: boolean;
  job_enabled: boolean;
  policy_version: number;
}

export interface ManagedModelCatalog {
  generated_at: string;
  models: ManagedModelCatalogEntry[];
}

export interface BillingAvailability {
  enabled: boolean;
  billing_mode: "manual_monthly_renewal";
  methods: Record<PaymentMethod, boolean>;
  entitlement_activation: "verified_server_callback_only";
  plans: ManagedModelPlan[];
}

export type CheckoutTarget =
  | { kind: "redirect"; url: string }
  | { kind: "qr_code"; code_url: string };

export interface BillingCheckout {
  order_id: string;
  plan_id: Exclude<ManagedModelPlanId, "free">;
  payment_method: PaymentMethod;
  amount_cny_fen: number;
  currency: "CNY";
  expires_at: string;
  checkout: CheckoutTarget;
}

export class CloudModelAccessError extends Error {
  readonly code: string;
  readonly status: number;

  constructor(code: string, message: string, status: number) {
    super(message);
    this.name = "CloudModelAccessError";
    this.code = code;
    this.status = status;
  }
}

const CLOUD_REQUEST_TIMEOUT_MS = 30_000;
const CLOUD_RESPONSE_MAX_BYTES = 1024 * 1024;

function deriveFunctionUrl(functionName: string, explicitUrl: string | undefined): string {
  const explicit = explicitUrl?.trim().replace(/\/+$/u, "");
  if (explicit) return explicit;
  const supabaseUrl = (
    import.meta.env.VITE_SUPABASE_URL as string | undefined
  )?.trim().replace(/\/+$/u, "");
  return supabaseUrl ? `${supabaseUrl}/functions/v1/${functionName}` : "";
}

export const modelGatewayUrl = deriveFunctionUrl(
  "model-gateway",
  import.meta.env.VITE_MODEL_GATEWAY_URL as string | undefined,
);
export const billingCheckoutUrl = deriveFunctionUrl(
  "billing-checkout",
  import.meta.env.VITE_BILLING_CHECKOUT_URL as string | undefined,
);

function authenticatedHeaders(): Record<string, string> {
  const token = getAuthAccessToken();
  if (!token) {
    throw new CloudModelAccessError(
      "AUTHENTICATION_REQUIRED",
      "Sign in to use the included managed-model allowance.",
      401,
    );
  }
  return {
    Authorization: `Bearer ${token}`,
    "Content-Type": "application/json",
    Accept: "application/json",
  };
}

async function cloudRequest<T>(
  baseUrl: string,
  path: string,
  init?: RequestInit,
  authenticated = true,
): Promise<T> {
  if (!baseUrl) {
    throw new CloudModelAccessError(
      "SERVICE_NOT_CONFIGURED",
      "The DroneDream cloud service URL is not configured in this build.",
      503,
    );
  }
  const requestHeaders = authenticated
    ? authenticatedHeaders()
    : {
        "Content-Type": "application/json",
        Accept: "application/json",
      };
  let response: Response;
  try {
    response = await fetchWithDeadline(
      `${baseUrl}${path}`,
      {
        ...init,
        headers: {
          ...requestHeaders,
          ...(init?.headers ?? {}),
        },
      },
      CLOUD_REQUEST_TIMEOUT_MS,
      CLOUD_RESPONSE_MAX_BYTES,
    );
  } catch (error) {
    if (error instanceof FetchResponseSizeError) {
      throw new CloudModelAccessError(
        "RESPONSE_TOO_LARGE",
        error.message,
        error.httpStatus,
      );
    }
    throw new CloudModelAccessError(
      "NETWORK_ERROR",
      error instanceof Error ? error.message : "The cloud service could not be reached.",
      0,
    );
  }
  let parsed: unknown;
  try {
    parsed = await response.json();
  } catch (error) {
    if (error instanceof FetchDeadlineError) {
      throw new CloudModelAccessError("NETWORK_ERROR", error.message, 0);
    }
    if (error instanceof FetchResponseSizeError) {
      throw new CloudModelAccessError(
        "RESPONSE_TOO_LARGE",
        error.message,
        response.status,
      );
    }
    throw new CloudModelAccessError(
      "INVALID_RESPONSE",
      `The cloud service returned HTTP ${response.status} without JSON.`,
      response.status,
    );
  }
  const envelope = parsed as {
    data?: T;
    error?: { code?: string; message?: string };
  };
  if (response.ok && envelope.data !== undefined) return envelope.data;
  throw new CloudModelAccessError(
    envelope.error?.code ?? "CLOUD_REQUEST_FAILED",
    envelope.error?.message ?? `The cloud request failed with HTTP ${response.status}.`,
    response.status,
  );
}

export function getManagedModelUsage(): Promise<ManagedModelUsageSnapshot> {
  return cloudRequest<ManagedModelUsageSnapshot>(modelGatewayUrl, "/usage");
}

export function getManagedModelCatalog(): Promise<ManagedModelCatalog> {
  return cloudRequest<ManagedModelCatalog>(modelGatewayUrl, "/models");
}

export function issueManagedModelGrant(
  scope: ManagedModelGrantScope,
  scopeReference?: string | null,
  provider?: ManagedModelProvider,
): Promise<ManagedModelGrant> {
  return cloudRequest<ManagedModelGrant>(modelGatewayUrl, "/grants", {
    method: "POST",
    body: JSON.stringify({
      scope,
      scope_reference: scopeReference || null,
      ...(provider ? { provider } : {}),
    }),
  });
}

export async function completeManagedModelChat(
  grant: ManagedModelGrant,
  messages: ManagedModelChatMessage[],
  responseFormat?: Record<string, unknown>,
): Promise<ManagedModelChatCompletion> {
  if (!grant.grant.startsWith("ddg_") || grant.grant.length > 128) {
    throw new CloudModelAccessError(
      "MODEL_GRANT_INVALID",
      "The managed-model grant is invalid.",
      401,
    );
  }
  const gateway = new URL(grant.gateway_base_url);
  if (
    gateway.protocol !== "https:"
    || gateway.username
    || gateway.password
    || !gateway.pathname.endsWith("/model-gateway")
  ) {
    throw new CloudModelAccessError(
      "MODEL_GATEWAY_INVALID",
      "The managed-model gateway address is invalid.",
      503,
    );
  }
  if (messages.length < 1 || messages.length > 24) {
    throw new CloudModelAccessError(
      "INVALID_REQUEST",
      "The conversation is outside the supported size.",
      400,
    );
  }

  let response: Response;
  try {
    response = await fetchWithDeadline(
      `${gateway.toString().replace(/\/+$/u, "")}/chat/completions`,
      {
        method: "POST",
        headers: {
          Authorization: `Bearer ${grant.grant}`,
          "Content-Type": "application/json",
          Accept: "application/json",
          "Idempotency-Key": crypto.randomUUID(),
        },
        body: JSON.stringify({
          messages,
          ...(responseFormat ? { response_format: responseFormat } : {}),
        }),
      },
      120_000,
      CLOUD_RESPONSE_MAX_BYTES,
    );
  } catch (error) {
    throw new CloudModelAccessError(
      "NETWORK_ERROR",
      error instanceof Error ? error.message : "The managed model could not be reached.",
      0,
    );
  }
  const parsed = await response.json() as Partial<ManagedModelChatCompletion> & {
    error?: { code?: string; message?: string };
  };
  if (!response.ok) {
    throw new CloudModelAccessError(
      parsed.error?.code ?? "MODEL_REQUEST_FAILED",
      parsed.error?.message ?? `The managed model returned HTTP ${response.status}.`,
      response.status,
    );
  }
  if (
    typeof parsed.model !== "string"
    || !Array.isArray(parsed.choices)
    || typeof parsed.choices[0]?.message?.content !== "string"
  ) {
    throw new CloudModelAccessError(
      "INVALID_RESPONSE",
      "The managed model returned an invalid response.",
      502,
    );
  }
  return parsed as ManagedModelChatCompletion;
}

export function getBillingAvailability(): Promise<BillingAvailability> {
  return cloudRequest<BillingAvailability>(
    billingCheckoutUrl,
    "/availability",
    { method: "GET" },
    false,
  );
}

export function createBillingCheckout(
  planId: Exclude<ManagedModelPlanId, "free">,
  paymentMethod: PaymentMethod,
): Promise<BillingCheckout> {
  return cloudRequest<BillingCheckout>(billingCheckoutUrl, "/create", {
    method: "POST",
    body: JSON.stringify({
      plan_id: planId,
      payment_method: paymentMethod,
      idempotency_key: crypto.randomUUID(),
    }),
  });
}
