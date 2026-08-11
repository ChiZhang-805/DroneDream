import { createClient, type SupabaseClient, type User } from "npm:@supabase/supabase-js@2.110.8";

type JsonRecord = Record<string, unknown>;
type PaymentMethod = "alipay" | "wechat" | "card";

const DEFAULT_ALLOWED_ORIGINS = [
  "https://getdronedream.com",
  "https://www.getdronedream.com",
  "http://47.93.180.216",
  "http://localhost:5173",
  "http://127.0.0.1:5173",
  "http://tauri.localhost",
  "tauri://localhost",
];
const MAX_BODY_BYTES = 128_000;

class BillingError extends Error {
  readonly code: string;
  readonly status: number;

  constructor(code: string, message: string, status: number) {
    super(message);
    this.name = "BillingError";
    this.code = code;
    this.status = status;
  }
}

function env(name: string): string {
  return Deno.env.get(name)?.trim() ?? "";
}

function requiredEnv(name: string): string {
  const value = env(name);
  if (!value) {
    throw new BillingError(
      "PAYMENT_NOT_CONFIGURED",
      "This payment channel has not been activated.",
      503,
    );
  }
  return value;
}

function allowedOrigins(): Set<string> {
  const configured = env("BILLING_ALLOWED_ORIGINS")
    .split(",")
    .map((origin) => origin.trim())
    .filter(Boolean);
  return new Set(configured.length ? configured : DEFAULT_ALLOWED_ORIGINS);
}

function corsHeaders(request: Request): HeadersInit {
  const origin = request.headers.get("Origin");
  if (!origin) return {};
  if (!allowedOrigins().has(origin)) {
    throw new BillingError("ORIGIN_NOT_ALLOWED", "The request origin is not allowed.", 403);
  }
  return {
    "Access-Control-Allow-Origin": origin,
    "Access-Control-Allow-Credentials": "true",
    "Access-Control-Allow-Headers": "authorization, apikey, content-type, x-client-info",
    "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
    Vary: "Origin",
  };
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

function isRecord(value: unknown): value is JsonRecord {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function isPaymentMethod(value: unknown): value is PaymentMethod {
  return value === "alipay" || value === "wechat" || value === "card";
}

function endpointPath(request: Request): string {
  const pathname = new URL(request.url).pathname.replace(/\/+$/u, "");
  const marker = "/billing-checkout";
  const markerIndex = pathname.lastIndexOf(marker);
  return markerIndex >= 0 ? pathname.slice(markerIndex + marker.length) || "/" : pathname;
}

let cachedAdmin: SupabaseClient | null = null;

function adminClient(): SupabaseClient {
  if (cachedAdmin) return cachedAdmin;
  cachedAdmin = createClient(
    requiredEnv("SUPABASE_URL"),
    requiredEnv("SUPABASE_SERVICE_ROLE_KEY"),
    {
      auth: { autoRefreshToken: false, persistSession: false },
    },
  );
  return cachedAdmin;
}

function bearerToken(request: Request): string {
  const match = /^Bearer\s+(.+)$/iu.exec(
    request.headers.get("Authorization")?.trim() ?? "",
  );
  if (!match?.[1]) {
    throw new BillingError("AUTHENTICATION_REQUIRED", "Sign in before checkout.", 401);
  }
  return match[1].trim();
}

async function authenticatedUser(request: Request): Promise<User> {
  const { data, error } = await adminClient().auth.getUser(bearerToken(request));
  if (error || !data.user) {
    throw new BillingError("AUTHENTICATION_REQUIRED", "The account session is invalid.", 401);
  }
  return data.user;
}

async function readBodyText(request: Request): Promise<string> {
  const announced = Number(request.headers.get("Content-Length") ?? "0");
  if (Number.isFinite(announced) && announced > MAX_BODY_BYTES) {
    throw new BillingError("REQUEST_TOO_LARGE", "The request body is too large.", 413);
  }
  const raw = await request.text();
  if (new TextEncoder().encode(raw).byteLength > MAX_BODY_BYTES) {
    throw new BillingError("REQUEST_TOO_LARGE", "The request body is too large.", 413);
  }
  return raw;
}

async function readJsonBody(request: Request): Promise<JsonRecord> {
  const raw = await readBodyText(request);
  try {
    const parsed: unknown = JSON.parse(raw);
    if (!isRecord(parsed)) throw new Error("body is not an object");
    return parsed;
  } catch {
    throw new BillingError("INVALID_REQUEST", "The request body must be valid JSON.", 400);
  }
}

function paymentEnabled(): boolean {
  return env("PAYMENTS_ENABLED").toLowerCase() === "true";
}

function alipayConfigured(): boolean {
  return paymentEnabled() && [
    "ALIPAY_APP_ID",
    "ALIPAY_MERCHANT_PRIVATE_KEY_PKCS8",
    "ALIPAY_PUBLIC_KEY_SPKI",
    "ALIPAY_SELLER_ID",
    "ALIPAY_NOTIFY_URL",
    "ALIPAY_RETURN_URL",
  ].every((name) => Boolean(env(name)));
}

function wechatConfigured(): boolean {
  return paymentEnabled() && [
    "WECHAT_APP_ID",
    "WECHAT_MCH_ID",
    "WECHAT_MERCHANT_CERT_SERIAL",
    "WECHAT_MERCHANT_PRIVATE_KEY_PKCS8",
    "WECHAT_PLATFORM_CERTIFICATE_SERIAL",
    "WECHAT_PLATFORM_PUBLIC_KEY_SPKI",
    "WECHAT_API_V3_KEY",
    "WECHAT_NOTIFY_URL",
  ].every((name) => Boolean(env(name)));
}

function cardConfigured(): boolean {
  return paymentEnabled() && [
    "STRIPE_SECRET_KEY",
    "STRIPE_WEBHOOK_SECRET",
    "STRIPE_SUCCESS_URL",
    "STRIPE_CANCEL_URL",
  ].every((name) => Boolean(env(name)));
}

function channelConfigured(method: PaymentMethod): boolean {
  if (method === "alipay") return alipayConfigured();
  if (method === "wechat") return wechatConfigured();
  return cardConfigured();
}

async function availability(): Promise<JsonRecord> {
  const { data: plans, error } = await adminClient()
    .from("model_subscription_plans")
    .select(
      "plan_id,display_name,monthly_price_cny_fen,included_ai_credits,capability_set",
    )
    .eq("active", true)
    .order("display_rank", { ascending: true });
  if (error) throw error;
  return {
    enabled: paymentEnabled(),
    billing_mode: "manual_monthly_renewal",
    methods: {
      alipay: alipayConfigured(),
      wechat: wechatConfigured(),
      card: cardConfigured(),
    },
    entitlement_activation: "verified_server_callback_only",
    plans: (plans ?? []).map((plan) => ({
      id: plan.plan_id,
      name: plan.display_name,
      monthly_price_cny_fen: plan.monthly_price_cny_fen,
      included_ai_credits: plan.included_ai_credits,
      capability_set: plan.capability_set,
    })),
  };
}

function pemBytes(value: string, label: "PRIVATE KEY" | "PUBLIC KEY"): Uint8Array {
  const normalized = value.replaceAll("\\n", "\n");
  const body = normalized
    .replace(`-----BEGIN ${label}-----`, "")
    .replace(`-----END ${label}-----`, "")
    .replace(/\s+/gu, "");
  if (!body) {
    throw new BillingError("PAYMENT_NOT_CONFIGURED", "A payment signing key is invalid.", 503);
  }
  let binary: string;
  try {
    binary = atob(body);
  } catch {
    throw new BillingError("PAYMENT_NOT_CONFIGURED", "A payment signing key is invalid.", 503);
  }
  return Uint8Array.from(binary, (character) => character.charCodeAt(0));
}

function bytesToBase64(bytes: Uint8Array): string {
  let binary = "";
  for (const byte of bytes) binary += String.fromCharCode(byte);
  return btoa(binary);
}

function arrayBuffer(bytes: Uint8Array): ArrayBuffer {
  const copy = new Uint8Array(bytes.byteLength);
  copy.set(bytes);
  return copy.buffer;
}

export async function rsaSign(message: string, privateKeyPem: string): Promise<string> {
  const key = await crypto.subtle.importKey(
    "pkcs8",
    arrayBuffer(pemBytes(privateKeyPem, "PRIVATE KEY")),
    { name: "RSASSA-PKCS1-v1_5", hash: "SHA-256" },
    false,
    ["sign"],
  );
  const signature = await crypto.subtle.sign(
    "RSASSA-PKCS1-v1_5",
    key,
    new TextEncoder().encode(message),
  );
  return bytesToBase64(new Uint8Array(signature));
}

export async function rsaVerify(
  message: string,
  signatureBase64: string,
  publicKeyPem: string,
): Promise<boolean> {
  let signature: Uint8Array;
  try {
    signature = Uint8Array.from(atob(signatureBase64), (character) =>
      character.charCodeAt(0)
    );
  } catch {
    return false;
  }
  const key = await crypto.subtle.importKey(
    "spki",
    arrayBuffer(pemBytes(publicKeyPem, "PUBLIC KEY")),
    { name: "RSASSA-PKCS1-v1_5", hash: "SHA-256" },
    false,
    ["verify"],
  );
  return crypto.subtle.verify(
    "RSASSA-PKCS1-v1_5",
    key,
    arrayBuffer(signature),
    new TextEncoder().encode(message),
  );
}

async function sha256Hex(value: string): Promise<string> {
  const digest = new Uint8Array(
    await crypto.subtle.digest("SHA-256", new TextEncoder().encode(value)),
  );
  return [...digest].map((byte) => byte.toString(16).padStart(2, "0")).join("");
}

function bytesToHex(bytes: Uint8Array): string {
  return [...bytes].map((byte) => byte.toString(16).padStart(2, "0")).join("");
}

async function hmacSha256Hex(secret: string, value: string): Promise<string> {
  const key = await crypto.subtle.importKey(
    "raw",
    new TextEncoder().encode(secret),
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["sign"],
  );
  return bytesToHex(new Uint8Array(
    await crypto.subtle.sign("HMAC", key, new TextEncoder().encode(value)),
  ));
}

function constantTimeHexEqual(left: string, right: string): boolean {
  if (
    left.length !== right.length
    || left.length === 0
    || !/^[0-9a-f]+$/iu.test(left)
    || !/^[0-9a-f]+$/iu.test(right)
  ) {
    return false;
  }
  let difference = 0;
  for (let index = 0; index < left.length; index += 1) {
    difference |= left.charCodeAt(index) ^ right.charCodeAt(index);
  }
  return difference === 0;
}

export async function verifyStripeSignature(
  rawBody: string,
  signatureHeader: string,
  webhookSecret: string,
  nowMilliseconds = Date.now(),
): Promise<boolean> {
  const components = signatureHeader.split(",").map((component) => component.trim());
  const timestampText = components
    .find((component) => component.startsWith("t="))
    ?.slice(2) ?? "";
  const timestamp = Number(timestampText);
  const signatures = components
    .filter((component) => component.startsWith("v1="))
    .map((component) => component.slice(3));
  if (
    !webhookSecret
    || !Number.isSafeInteger(timestamp)
    || timestamp <= 0
    || Math.abs(nowMilliseconds / 1_000 - timestamp) > 300
    || signatures.length === 0
  ) {
    return false;
  }
  const expected = await hmacSha256Hex(
    webhookSecret,
    `${timestampText}.${rawBody}`,
  );
  return signatures.some((signature) => constantTimeHexEqual(signature, expected));
}

export function canonicalParameters(
  parameters: URLSearchParams,
  excluded: Set<string> = new Set(),
): string {
  return [...parameters.entries()]
    .filter(([key]) => !excluded.has(key))
    .sort(([left], [right]) => left.localeCompare(right))
    .map(([key, value]) => `${key}=${value}`)
    .join("&");
}

export function alipayNotificationProtocolMatches(
  parameters: URLSearchParams,
  expectedAppId: string,
  expectedSellerId: string,
): boolean {
  return parameters.get("sign_type") === "RSA2"
    && parameters.get("app_id") === expectedAppId
    && parameters.get("seller_id") === expectedSellerId
    && ["TRADE_SUCCESS", "TRADE_FINISHED"].includes(
      parameters.get("trade_status") ?? "",
    );
}

function alipayTimestamp(): string {
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone: "Asia/Shanghai",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hourCycle: "h23",
  }).formatToParts(new Date());
  const value = (type: string) => parts.find((part) => part.type === type)?.value ?? "";
  return `${value("year")}-${value("month")}-${value("day")} `
    + `${value("hour")}:${value("minute")}:${value("second")}`;
}

function fenToYuan(amount: number): string {
  return (amount / 100).toFixed(2);
}

interface PaymentOrder {
  order_id: string;
  plan_id: "plus" | "pro";
  payment_method: PaymentMethod;
  amount_cny_fen: number;
  status: string;
  checkout_expires_at: string;
}

function asOrder(value: unknown): PaymentOrder {
  if (
    !isRecord(value)
    || typeof value.order_id !== "string"
    || (value.plan_id !== "plus" && value.plan_id !== "pro")
    || !isPaymentMethod(value.payment_method)
    || !Number.isSafeInteger(value.amount_cny_fen)
    || typeof value.status !== "string"
    || typeof value.checkout_expires_at !== "string"
  ) {
    throw new BillingError("PAYMENT_ORDER_INVALID", "The payment order is invalid.", 500);
  }
  return value as unknown as PaymentOrder;
}

async function createAlipayCheckout(order: PaymentOrder): Promise<JsonRecord> {
  const parameters = new URLSearchParams({
    app_id: requiredEnv("ALIPAY_APP_ID"),
    method: "alipay.trade.page.pay",
    format: "JSON",
    charset: "utf-8",
    sign_type: "RSA2",
    timestamp: alipayTimestamp(),
    version: "1.0",
    notify_url: requiredEnv("ALIPAY_NOTIFY_URL"),
    return_url: requiredEnv("ALIPAY_RETURN_URL"),
    biz_content: JSON.stringify({
      out_trade_no: order.order_id,
      product_code: "FAST_INSTANT_TRADE_PAY",
      total_amount: fenToYuan(order.amount_cny_fen),
      subject: `DroneDream ${order.plan_id === "plus" ? "Plus" : "Pro"} · 1 month`,
      timeout_express: "30m",
    }),
  });
  parameters.set(
    "sign",
    await rsaSign(
      canonicalParameters(parameters),
      requiredEnv("ALIPAY_MERCHANT_PRIVATE_KEY_PKCS8"),
    ),
  );
  return {
    kind: "redirect",
    url: `https://openapi.alipay.com/gateway.do?${parameters.toString()}`,
  };
}

function randomNonce(): string {
  return crypto.randomUUID().replaceAll("-", "");
}

async function wechatAuthorization(
  method: string,
  path: string,
  body: string,
): Promise<string> {
  const timestamp = Math.floor(Date.now() / 1_000).toString();
  const nonce = randomNonce();
  const signature = await rsaSign(
    `${method}\n${path}\n${timestamp}\n${nonce}\n${body}\n`,
    requiredEnv("WECHAT_MERCHANT_PRIVATE_KEY_PKCS8"),
  );
  const quote = (value: string) => value.replaceAll("\\", "\\\\").replaceAll("\"", "\\\"");
  return "WECHATPAY2-SHA256-RSA2048 "
    + `mchid="${quote(requiredEnv("WECHAT_MCH_ID"))}",`
    + `nonce_str="${quote(nonce)}",`
    + `timestamp="${timestamp}",`
    + `serial_no="${quote(requiredEnv("WECHAT_MERCHANT_CERT_SERIAL"))}",`
    + `signature="${quote(signature)}"`;
}

async function createWechatCheckout(order: PaymentOrder): Promise<JsonRecord> {
  const path = "/v3/pay/transactions/native";
  const body = JSON.stringify({
    appid: requiredEnv("WECHAT_APP_ID"),
    mchid: requiredEnv("WECHAT_MCH_ID"),
    description: `DroneDream ${order.plan_id === "plus" ? "Plus" : "Pro"} · 1 month`,
    out_trade_no: order.order_id,
    notify_url: requiredEnv("WECHAT_NOTIFY_URL"),
    amount: { total: order.amount_cny_fen, currency: "CNY" },
  });
  const response = await fetch(`https://api.mch.weixin.qq.com${path}`, {
    method: "POST",
    headers: {
      Authorization: await wechatAuthorization("POST", path, body),
      "Content-Type": "application/json",
      Accept: "application/json",
      "User-Agent": "DroneDream-Billing/1.0.0",
    },
    body,
    signal: AbortSignal.timeout(30_000),
  });
  const responseText = await response.text();
  const responseTimestamp = response.headers.get("Wechatpay-Timestamp") ?? "";
  const responseNonce = response.headers.get("Wechatpay-Nonce") ?? "";
  const responseSignature = response.headers.get("Wechatpay-Signature") ?? "";
  const responseSerial = response.headers.get("Wechatpay-Serial") ?? "";
  const responseTimestampNumber = Number(responseTimestamp);
  const responseSignatureValid = responseSerial
    === requiredEnv("WECHAT_PLATFORM_CERTIFICATE_SERIAL")
    && Number.isSafeInteger(responseTimestampNumber)
    && Math.abs(Date.now() / 1_000 - responseTimestampNumber) <= 300
    && await rsaVerify(
      `${responseTimestamp}\n${responseNonce}\n${responseText}\n`,
      responseSignature,
      requiredEnv("WECHAT_PLATFORM_PUBLIC_KEY_SPKI"),
    );
  let responseJson: unknown;
  try {
    responseJson = JSON.parse(responseText);
  } catch {
    responseJson = null;
  }
  if (
    !response.ok
    || !responseSignatureValid
    || !isRecord(responseJson)
    || typeof responseJson.code_url !== "string"
  ) {
    console.error("WeChat checkout creation failed", response.status);
    throw new BillingError(
      "PAYMENT_PROVIDER_FAILED",
      "WeChat Pay could not create the checkout.",
      502,
    );
  }
  return { kind: "qr_code", code_url: responseJson.code_url };
}

async function createCardCheckout(order: PaymentOrder): Promise<JsonRecord> {
  const parameters = new URLSearchParams({
    mode: "payment",
    client_reference_id: order.order_id,
    success_url: requiredEnv("STRIPE_SUCCESS_URL"),
    cancel_url: requiredEnv("STRIPE_CANCEL_URL"),
    "payment_method_types[0]": "card",
    "line_items[0][quantity]": "1",
    "line_items[0][price_data][currency]": "cny",
    "line_items[0][price_data][unit_amount]": String(order.amount_cny_fen),
    "line_items[0][price_data][product_data][name]":
      `DroneDream ${order.plan_id === "plus" ? "Plus" : "Pro"} · 1 month`,
    "metadata[order_id]": order.order_id,
    "metadata[plan_id]": order.plan_id,
    "payment_intent_data[metadata][order_id]": order.order_id,
    // Stripe permits 30 minutes to 24 hours. The database checkout deadline is
    // 35 minutes so the provider session always expires first.
    expires_at: String(Math.floor(Date.now() / 1_000) + 30 * 60 + 30),
  });
  const response = await fetch("https://api.stripe.com/v1/checkout/sessions", {
    method: "POST",
    headers: {
      Authorization: `Bearer ${requiredEnv("STRIPE_SECRET_KEY")}`,
      "Content-Type": "application/x-www-form-urlencoded",
      Accept: "application/json",
      "Idempotency-Key": `dronedream-${order.order_id}`,
      "User-Agent": "DroneDream-Billing/1.0.0",
    },
    body: parameters.toString(),
    signal: AbortSignal.timeout(30_000),
  });
  const responseText = await response.text();
  let responseJson: unknown;
  try {
    responseJson = JSON.parse(responseText);
  } catch {
    responseJson = null;
  }
  const checkoutUrl = isRecord(responseJson) && typeof responseJson.url === "string"
    ? responseJson.url
    : "";
  let trustedCheckoutUrl = false;
  try {
    const parsed = new URL(checkoutUrl);
    trustedCheckoutUrl = parsed.protocol === "https:"
      && (
        parsed.hostname === "checkout.stripe.com"
        || parsed.hostname.endsWith(".checkout.stripe.com")
      );
  } catch {
    trustedCheckoutUrl = false;
  }
  if (
    !response.ok
    || !isRecord(responseJson)
    || responseJson.object !== "checkout.session"
    || typeof responseJson.id !== "string"
    || !responseJson.id.startsWith("cs_")
    || !trustedCheckoutUrl
  ) {
    console.error("Card checkout creation failed", response.status);
    throw new BillingError(
      "PAYMENT_PROVIDER_FAILED",
      "Card payment could not create the checkout.",
      502,
    );
  }
  return { kind: "redirect", url: checkoutUrl };
}

async function handleCreate(request: Request): Promise<Response> {
  const user = await authenticatedUser(request);
  const body = await readJsonBody(request);
  const planId = body.plan_id;
  const paymentMethod = body.payment_method;
  if (
    (planId !== "plus" && planId !== "pro")
    || !isPaymentMethod(paymentMethod)
  ) {
    throw new BillingError("INVALID_REQUEST", "Choose Plus or Pro and a payment method.", 400);
  }
  if (!channelConfigured(paymentMethod)) {
    throw new BillingError(
      "PAYMENT_NOT_CONFIGURED",
      "This payment channel has not been activated yet.",
      503,
    );
  }
  const idempotencyKey = typeof body.idempotency_key === "string"
    ? body.idempotency_key
    : crypto.randomUUID();
  if (
    idempotencyKey.length < 8
    || idempotencyKey.length > 128
    || !/^[A-Za-z0-9_.:-]+$/u.test(idempotencyKey)
  ) {
    throw new BillingError("INVALID_REQUEST", "The checkout idempotency key is invalid.", 400);
  }
  const { data, error } = await adminClient().rpc("billing_create_order", {
    p_user_id: user.id,
    p_plan_id: planId,
    p_payment_method: paymentMethod,
    p_idempotency_key: idempotencyKey,
    p_billing_period_months: 1,
  });
  if (error) throw error;
  const order = asOrder(data);
  if (order.status !== "pending") {
    throw new BillingError("PAYMENT_ORDER_NOT_PAYABLE", "This order is no longer payable.", 409);
  }
  const checkout = paymentMethod === "alipay"
    ? await createAlipayCheckout(order)
    : paymentMethod === "wechat"
      ? await createWechatCheckout(order)
      : await createCardCheckout(order);
  return jsonResponse(request, 201, {
    data: {
      order_id: order.order_id,
      plan_id: order.plan_id,
      payment_method: order.payment_method,
      amount_cny_fen: order.amount_cny_fen,
      currency: "CNY",
      expires_at: order.checkout_expires_at,
      checkout,
    },
  });
}

async function paymentOrder(orderId: string, method: PaymentMethod): Promise<PaymentOrder> {
  const { data, error } = await adminClient()
    .from("payment_orders")
    .select("order_id,plan_id,payment_method,amount_cny_fen,status,checkout_expires_at")
    .eq("order_id", orderId)
    .eq("payment_method", method)
    .maybeSingle();
  if (error || !data) {
    throw new BillingError("PAYMENT_ORDER_NOT_FOUND", "The payment order was not found.", 404);
  }
  return asOrder(data);
}

async function markPaid(
  order: PaymentOrder,
  providerOrderReference: string,
  providerTransactionReference: string,
  providerEventReference: string,
  payloadHash: string,
): Promise<void> {
  const { error } = await adminClient().rpc("billing_mark_order_paid", {
    p_order_id: order.order_id,
    p_provider_order_reference: providerOrderReference,
    p_provider_transaction_reference: providerTransactionReference,
    p_provider_event_reference: providerEventReference,
    p_payload_sha256: payloadHash,
  });
  if (error) throw error;
}

async function handleAlipayNotify(request: Request): Promise<Response> {
  if (!alipayConfigured()) {
    return new Response("failure", { status: 503 });
  }
  const raw = await readBodyText(request);
  const parameters = new URLSearchParams(raw);
  const signature = parameters.get("sign") ?? "";
  const verified = await rsaVerify(
    canonicalParameters(parameters, new Set(["sign", "sign_type"])),
    signature,
    requiredEnv("ALIPAY_PUBLIC_KEY_SPKI"),
  );
  const orderId = parameters.get("out_trade_no") ?? "";
  const transactionId = parameters.get("trade_no") ?? "";
  const eventReference = parameters.get("notify_id") ?? transactionId;
  if (
    !verified
    || !alipayNotificationProtocolMatches(
      parameters,
      requiredEnv("ALIPAY_APP_ID"),
      requiredEnv("ALIPAY_SELLER_ID"),
    )
    || !/^[0-9a-f-]{36}$/iu.test(orderId)
    || !transactionId
    || !eventReference
  ) {
    return new Response("failure", { status: 400 });
  }
  try {
    const order = await paymentOrder(orderId, "alipay");
    if (parameters.get("total_amount") !== fenToYuan(order.amount_cny_fen)) {
      return new Response("failure", { status: 400 });
    }
    await markPaid(
      order,
      orderId,
      transactionId,
      eventReference,
      await sha256Hex(raw),
    );
    return new Response("success", {
      status: 200,
      headers: { "Content-Type": "text/plain; charset=utf-8" },
    });
  } catch (error) {
    console.error("Alipay notification processing failed", error);
    return new Response("failure", { status: 500 });
  }
}

function base64Bytes(value: string): Uint8Array {
  return Uint8Array.from(atob(value), (character) => character.charCodeAt(0));
}

async function decryptWechatResource(resource: JsonRecord): Promise<JsonRecord> {
  const ciphertext = typeof resource.ciphertext === "string" ? resource.ciphertext : "";
  const nonce = typeof resource.nonce === "string" ? resource.nonce : "";
  const associatedData = typeof resource.associated_data === "string"
    ? resource.associated_data
    : "";
  const keyBytes = new TextEncoder().encode(requiredEnv("WECHAT_API_V3_KEY"));
  if (keyBytes.byteLength !== 32 || !ciphertext || !nonce) {
    throw new BillingError("PAYMENT_NOTIFICATION_INVALID", "Invalid WeChat resource.", 400);
  }
  const key = await crypto.subtle.importKey(
    "raw",
    keyBytes,
    { name: "AES-GCM" },
    false,
    ["decrypt"],
  );
  const plaintext = await crypto.subtle.decrypt(
    {
      name: "AES-GCM",
      iv: new TextEncoder().encode(nonce),
      additionalData: new TextEncoder().encode(associatedData),
      tagLength: 128,
    },
    key,
    arrayBuffer(base64Bytes(ciphertext)),
  );
  const parsed: unknown = JSON.parse(new TextDecoder().decode(plaintext));
  if (!isRecord(parsed)) {
    throw new BillingError("PAYMENT_NOTIFICATION_INVALID", "Invalid WeChat resource.", 400);
  }
  return parsed;
}

export function isWechatTransactionSuccessEnvelope(
  value: unknown,
): value is JsonRecord & { resource: JsonRecord } {
  if (!isRecord(value) || value.event_type !== "TRANSACTION.SUCCESS") {
    return false;
  }
  const resource = value.resource;
  return isRecord(resource)
    && resource.algorithm === "AEAD_AES_256_GCM"
    && resource.original_type === "transaction"
    && typeof resource.ciphertext === "string"
    && typeof resource.nonce === "string";
}

async function handleWechatNotify(request: Request): Promise<Response> {
  if (!wechatConfigured()) {
    return jsonResponse(request, 503, { code: "FAIL", message: "not configured" });
  }
  const raw = await readBodyText(request);
  const timestamp = request.headers.get("Wechatpay-Timestamp") ?? "";
  const nonce = request.headers.get("Wechatpay-Nonce") ?? "";
  const signature = request.headers.get("Wechatpay-Signature") ?? "";
  const serial = request.headers.get("Wechatpay-Serial") ?? "";
  const timestampNumber = Number(timestamp);
  if (
    serial !== requiredEnv("WECHAT_PLATFORM_CERTIFICATE_SERIAL")
    || !Number.isSafeInteger(timestampNumber)
    || Math.abs(Date.now() / 1_000 - timestampNumber) > 300
    || !await rsaVerify(
      `${timestamp}\n${nonce}\n${raw}\n`,
      signature,
      requiredEnv("WECHAT_PLATFORM_PUBLIC_KEY_SPKI"),
    )
  ) {
    return jsonResponse(request, 401, { code: "FAIL", message: "invalid signature" });
  }
  try {
    const notification: unknown = JSON.parse(raw);
    if (!isWechatTransactionSuccessEnvelope(notification)) {
      throw new Error("invalid notification");
    }
    const resource = await decryptWechatResource(notification.resource);
    const orderId = typeof resource.out_trade_no === "string" ? resource.out_trade_no : "";
    const transactionId = typeof resource.transaction_id === "string"
      ? resource.transaction_id
      : "";
    const eventReference = typeof notification.id === "string" ? notification.id : "";
    const amount = isRecord(resource.amount) ? resource.amount : null;
    const order = await paymentOrder(orderId, "wechat");
    if (
      resource.trade_state !== "SUCCESS"
      || resource.appid !== requiredEnv("WECHAT_APP_ID")
      || resource.mchid !== requiredEnv("WECHAT_MCH_ID")
      || integerValue(amount?.total) !== order.amount_cny_fen
      || amount?.currency !== "CNY"
      || !transactionId
      || !eventReference
    ) {
      throw new Error("notification fields do not match the order");
    }
    await markPaid(
      order,
      orderId,
      transactionId,
      eventReference,
      await sha256Hex(raw),
    );
    return jsonResponse(request, 200, { code: "SUCCESS", message: "成功" });
  } catch (error) {
    console.error("WeChat notification processing failed", error);
    return jsonResponse(request, 500, { code: "FAIL", message: "processing failed" });
  }
}

async function handleCardNotify(request: Request): Promise<Response> {
  if (!cardConfigured()) {
    return new Response("not configured", { status: 503 });
  }
  const raw = await readBodyText(request);
  const signature = request.headers.get("Stripe-Signature") ?? "";
  if (
    !await verifyStripeSignature(
      raw,
      signature,
      requiredEnv("STRIPE_WEBHOOK_SECRET"),
    )
  ) {
    return new Response("invalid signature", { status: 401 });
  }
  let event: unknown;
  try {
    event = JSON.parse(raw);
  } catch {
    return new Response("invalid payload", { status: 400 });
  }
  if (
    !isRecord(event)
    || typeof event.id !== "string"
    || !event.id.startsWith("evt_")
    || typeof event.type !== "string"
    || !isRecord(event.data)
    || !isRecord(event.data.object)
  ) {
    return new Response("invalid payload", { status: 400 });
  }
  if (event.type !== "checkout.session.completed") {
    return new Response("ignored", { status: 200 });
  }
  const session = event.data.object;
  const metadata = isRecord(session.metadata) ? session.metadata : null;
  const orderId = typeof session.client_reference_id === "string"
    ? session.client_reference_id
    : "";
  const sessionId = typeof session.id === "string" ? session.id : "";
  const paymentIntent = typeof session.payment_intent === "string"
    ? session.payment_intent
    : "";
  if (
    session.object !== "checkout.session"
    || session.mode !== "payment"
    || session.payment_status !== "paid"
    || session.status !== "complete"
    || session.currency !== "cny"
    || metadata?.order_id !== orderId
    || !/^[0-9a-f-]{36}$/iu.test(orderId)
    || !sessionId.startsWith("cs_")
    || !paymentIntent.startsWith("pi_")
  ) {
    return new Response("payment fields do not match", { status: 400 });
  }
  try {
    const order = await paymentOrder(orderId, "card");
    if (
      metadata?.plan_id !== order.plan_id
      || integerValue(session.amount_total) !== order.amount_cny_fen
    ) {
      return new Response("payment amount does not match", { status: 400 });
    }
    await markPaid(
      order,
      sessionId,
      paymentIntent,
      event.id,
      await sha256Hex(raw),
    );
    return new Response("received", { status: 200 });
  } catch (error) {
    console.error("Card notification processing failed", error);
    return new Response("processing failed", { status: 500 });
  }
}

function integerValue(value: unknown): number | null {
  return Number.isSafeInteger(value) && Number(value) >= 0 ? Number(value) : null;
}

function errorResponse(request: Request, error: unknown): Response {
  if (error instanceof BillingError) {
    return jsonResponse(request, error.status, {
      error: { code: error.code, message: error.message },
    });
  }
  const rawMessage = error instanceof Error ? error.message : "";
  const knownCode = [
    "IDEMPOTENCY_CONFLICT",
    "PAYMENT_PLAN_UNAVAILABLE",
    "PAYMENT_ORDER_NOT_PAYABLE",
  ].find((code) => rawMessage.includes(code));
  if (knownCode) {
    return jsonResponse(request, 409, {
      error: { code: knownCode, message: "The checkout order could not be created." },
    });
  }
  console.error("billing-checkout unexpected error", error);
  return jsonResponse(request, 500, {
    error: { code: "INTERNAL_ERROR", message: "The checkout service failed." },
  });
}

export async function handleBillingRequest(request: Request): Promise<Response> {
  const path = endpointPath(request);
  // Provider callbacks do not use browser CORS and must receive their exact
  // protocol acknowledgements instead of the generic JSON envelope.
  if (request.method === "POST" && path === "/webhooks/alipay") {
    return handleAlipayNotify(request);
  }
  if (request.method === "POST" && path === "/webhooks/wechat") {
    return handleWechatNotify(request);
  }
  if (request.method === "POST" && path === "/webhooks/card") {
    return handleCardNotify(request);
  }
  try {
    const cors = corsHeaders(request);
    if (request.method === "OPTIONS") {
      return new Response(null, { status: 204, headers: cors });
    }
    if (request.method === "GET" && path === "/availability") {
      return jsonResponse(request, 200, { data: await availability() });
    }
    if (request.method === "POST" && path === "/create") {
      return await handleCreate(request);
    }
    return jsonResponse(request, 404, {
      error: { code: "NOT_FOUND", message: "The billing route was not found." },
    });
  } catch (error) {
    return errorResponse(request, error);
  }
}

if (import.meta.main) {
  Deno.serve(handleBillingRequest);
}
