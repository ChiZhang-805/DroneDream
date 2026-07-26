import { verifyStripeSignature } from "./index.ts";

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
  const signed = new Uint8Array(await crypto.subtle.sign(
    "HMAC",
    key,
    encoder.encode(`${timestamp}.${rawBody}`),
  ));
  return [...signed].map((byte) => byte.toString(16).padStart(2, "0")).join("");
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
