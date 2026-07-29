import {
  alipayNotificationProtocolMatches,
  canonicalParameters,
  handleBillingRequest,
  isWechatTransactionSuccessEnvelope,
  readPaymentProviderResponseBody,
  rsaSign,
  rsaVerify,
  verifyStripeSignature,
} from "./index.ts";

const encoder = new TextEncoder();

function assert(value: unknown, message: string): asserts value {
  if (!value) throw new Error(message);
}

async function signature(
  secret: string,
  timestamp: number,
  rawBody: string,
): Promise<string> {
  const key = await crypto.subtle.importKey(
    "raw",
    encoder.encode(secret),
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["sign"],
  );
  const signed = new Uint8Array(
    await crypto.subtle.sign(
      "HMAC",
      key,
      encoder.encode(`${timestamp}.${rawBody}`),
    ),
  );
  return [...signed].map((byte) => byte.toString(16).padStart(2, "0")).join("");
}

function pem(label: "PRIVATE KEY" | "PUBLIC KEY", bytes: ArrayBuffer): string {
  const body = btoa(String.fromCharCode(...new Uint8Array(bytes)));
  const lines = body.match(/.{1,64}/gu) ?? [];
  return `-----BEGIN ${label}-----\n${lines.join("\n")}\n-----END ${label}-----`;
}

Deno.test("Stripe webhook verification accepts an exact recent raw body", async () => {
  const now = Date.parse("2026-07-26T12:00:00Z");
  const timestamp = Math.floor(now / 1_000);
  const raw = '{"id":"evt_test","type":"checkout.session.completed"}';
  const expected = await signature("whsec_test", timestamp, raw);

  assert(
    await verifyStripeSignature(
      raw,
      `t=${timestamp},v1=deadbeef,v1=${expected}`,
      "whsec_test",
      now,
    ),
    "a valid v1 signature should be accepted",
  );
});

Deno.test("Stripe webhook verification rejects body mutation and stale replay", async () => {
  const now = Date.parse("2026-07-26T12:00:00Z");
  const timestamp = Math.floor(now / 1_000);
  const raw = '{"id":"evt_test","paid":true}';
  const expected = await signature("whsec_test", timestamp, raw);
  const header = `t=${timestamp},v1=${expected}`;

  assert(
    !await verifyStripeSignature(
      '{"id":"evt_test","paid":false}',
      header,
      "whsec_test",
      now,
    ),
    "a changed raw body must invalidate the signature",
  );
  assert(
    !await verifyStripeSignature(
      raw,
      header,
      "whsec_test",
      now + 301_000,
    ),
    "a signature older than five minutes must be rejected",
  );
});

Deno.test("Alipay canonical RSA2 verification rejects field mutation", async () => {
  const keyPair = await crypto.subtle.generateKey(
    {
      name: "RSASSA-PKCS1-v1_5",
      modulusLength: 2048,
      publicExponent: new Uint8Array([1, 0, 1]),
      hash: "SHA-256",
    },
    true,
    ["sign", "verify"],
  );
  const privateKey = pem(
    "PRIVATE KEY",
    await crypto.subtle.exportKey("pkcs8", keyPair.privateKey),
  );
  const publicKey = pem(
    "PUBLIC KEY",
    await crypto.subtle.exportKey("spki", keyPair.publicKey),
  );
  const parameters = new URLSearchParams({
    seller_id: "seller-1",
    trade_status: "TRADE_SUCCESS",
    app_id: "app-1",
    total_amount: "39.00",
    sign_type: "RSA2",
  });
  const canonical = canonicalParameters(
    parameters,
    new Set(["sign", "sign_type"]),
  );
  assert(
    canonical ===
      "app_id=app-1&seller_id=seller-1&total_amount=39.00&trade_status=TRADE_SUCCESS",
    "Alipay fields must be sorted into the provider canonical form",
  );
  const signed = await rsaSign(canonical, privateKey);
  assert(
    await rsaVerify(canonical, signed, publicKey),
    "the RSA2 signature should verify",
  );
  assert(
    !await rsaVerify(canonical.replace("39.00", "129.00"), signed, publicKey),
    "changing a signed amount must invalidate the signature",
  );
  assert(
    alipayNotificationProtocolMatches(parameters, "app-1", "seller-1"),
    "the expected RSA2 success protocol fields should match",
  );
  parameters.set("sign_type", "RSA");
  assert(
    !alipayNotificationProtocolMatches(parameters, "app-1", "seller-1"),
    "legacy or unexpected signature modes must fail closed",
  );
});

Deno.test("WeChat callback envelope accepts only encrypted transaction success", () => {
  const valid = {
    event_type: "TRANSACTION.SUCCESS",
    resource: {
      algorithm: "AEAD_AES_256_GCM",
      original_type: "transaction",
      ciphertext: "ciphertext",
      nonce: "nonce",
    },
  };
  assert(
    isWechatTransactionSuccessEnvelope(valid),
    "valid payment envelope should pass",
  );
  assert(
    !isWechatTransactionSuccessEnvelope({
      ...valid,
      event_type: "REFUND.SUCCESS",
    }),
    "a refund event must not activate a subscription",
  );
  assert(
    !isWechatTransactionSuccessEnvelope({
      ...valid,
      resource: { ...valid.resource, algorithm: "RSA" },
    }),
    "an unexpected resource algorithm must fail closed",
  );
});

Deno.test("payment call-point reader covers WeChat and Stripe with a 64 KiB cap", async () => {
  for (const provider of ["wechat", "stripe"] as const) {
    const text = '{"ok":true}';
    assert(
      await readPaymentProviderResponseBody(new Response(text), provider) ===
        text,
      `${provider} should preserve a normal JSON response`,
    );

    let cancelled = false;
    const body = new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(new Uint8Array(64 * 1_024 + 1));
      },
      cancel() {
        cancelled = true;
      },
    });
    try {
      await readPaymentProviderResponseBody(new Response(body), provider);
    } catch (error) {
      assert(
        error instanceof Error &&
          "code" in error &&
          error.code === "PAYMENT_PROVIDER_FAILED",
        `${provider} should return a structured payment-provider error`,
      );
      assert(
        !error.message.includes("private"),
        `${provider} should not expose an upstream body`,
      );
      assert(cancelled, `${provider} should cancel an oversized body`);
      continue;
    }
    throw new Error(`${provider} should reject an oversized body`);
  }
});

Deno.test("billing gateway rejects the HTTP mirror before auth or provider work", async () => {
  for (const method of ["OPTIONS", "POST"]) {
    const response = await handleBillingRequest(
      new Request("https://functions.example.test/billing-checkout/create", {
        method,
        headers: { Origin: "http://47.93.180.216" },
      }),
    );
    const body = await response.json() as { error?: { code?: string } };
    assert(response.status === 403, `${method} should be rejected`);
    assert(
      body.error?.code === "ORIGIN_NOT_ALLOWED",
      `${method} should return the structured origin error`,
    );
    assert(
      !response.headers.has("Access-Control-Allow-Origin"),
      "the rejected origin must not receive CORS access",
    );
  }
});

Deno.test("billing gateway allows exact HTTPS preflight", async () => {
  const response = await handleBillingRequest(
    new Request("https://functions.example.test/billing-checkout/create", {
      method: "OPTIONS",
      headers: { Origin: "https://getdronedream.com" },
    }),
  );
  assert(response.status === 204, "the canonical HTTPS preflight should pass");
  assert(
    response.headers.get("Access-Control-Allow-Origin") ===
      "https://getdronedream.com",
    "the exact allowed HTTPS origin should be returned",
  );
});
