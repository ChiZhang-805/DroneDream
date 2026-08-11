import {
  handleProductEventsRequest,
  type ProductEventDependencies,
  validateProductEvent,
} from "./index.ts";
import type { User } from "npm:@supabase/supabase-js@2.110.8";

function assert(value: unknown, message: string): asserts value {
  if (!value) throw new Error(message);
}

const NOW = Date.now();
const EVENT_ID = "11111111-1111-4111-8111-111111111111";

function envelope(
  overrides: Record<string, unknown> = {},
): Record<string, unknown> {
  return {
    schema_version: 1,
    event_id: EVENT_ID,
    name: "job_created",
    occurred_at: new Date(NOW).toISOString(),
    properties: { source: "wizard", strategy: "bayesian", parameter_count: 7 },
    ...overrides,
  };
}

function dependencies(
  overrides: Partial<ProductEventDependencies> = {},
): ProductEventDependencies {
  return {
    authenticate: () =>
      Promise.resolve({ id: "22222222-2222-4222-8222-222222222222" } as User),
    record: () =>
      Promise.resolve({
        inserted: true,
        received_at: "2026-08-03T00:00:01.000Z",
      }),
    ...overrides,
  };
}

function request(value: unknown, token = "test-token"): Request {
  return new Request("https://example.test/functions/v1/product-events", {
    method: "POST",
    headers: {
      Authorization: `Bearer ${token}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify(value),
  });
}

Deno.test("product events require authentication before parsing the body", async () => {
  const req = request(envelope());
  req.headers.delete("Authorization");
  const response = await handleProductEventsRequest(req, dependencies());
  assert(response.status === 401, "missing bearer token must be rejected");
});

Deno.test("product events derive user identity and are safely idempotent", async () => {
  let recordedUser = "";
  const deps = dependencies({
    record: (userId) => {
      recordedUser = userId;
      return Promise.resolve({
        inserted: false,
        received_at: "2026-08-03T00:00:01.000Z",
      });
    },
  });
  const response = await handleProductEventsRequest(request(envelope()), deps);
  assert(
    response.status === 200,
    "duplicate events should return idempotent success",
  );
  assert(
    recordedUser === "22222222-2222-4222-8222-222222222222",
    "user id must come from verified JWT identity",
  );
  const responseBody = await response.json() as Record<string, unknown>;
  assert(
    responseBody.duplicate === true,
    "duplicate delivery must be explicit",
  );
});

Deno.test("product event validation rejects identity forgery and unknown envelope fields", () => {
  for (
    const extra of [{ user_id: "forged" }, { email: "owner@example.test" }, {
      received_at: new Date(NOW).toISOString(),
    }]
  ) {
    let rejected = false;
    try {
      validateProductEvent(envelope(extra), NOW);
    } catch {
      rejected = true;
    }
    assert(rejected, `${Object.keys(extra)[0]} must be rejected`);
  }
});

Deno.test("product event validation rejects unknown, nested, oversized, and sensitive properties", () => {
  const invalid = [
    envelope({ properties: { unknown: "value" } }),
    envelope({ properties: { source: { nested: true } } }),
    envelope({ properties: { source: "a".repeat(97) } }),
    envelope({ properties: { source: "sk-example-secret-value" } }),
    envelope({ properties: { prompt: "hello" } }),
  ];
  for (const event of invalid) {
    let rejected = false;
    try {
      validateProductEvent(event, NOW);
    } catch {
      rejected = true;
    }
    assert(rejected, "unsafe property payload must be rejected");
  }
});

Deno.test("product event validation rejects invalid UUID, schema, event, and time", () => {
  const invalid = [
    envelope({ event_id: "not-a-uuid" }),
    envelope({ schema_version: 2 }),
    envelope({ name: "job_succeeded" }),
    envelope({
      occurred_at: new Date(NOW - 25 * 60 * 60 * 1000).toISOString(),
    }),
  ];
  for (const event of invalid) {
    let rejected = false;
    try {
      validateProductEvent(event, NOW);
    } catch {
      rejected = true;
    }
    assert(rejected, "invalid event envelope must fail closed");
  }
});

Deno.test("product event request body is bounded before JSON parsing", async () => {
  const response = await handleProductEventsRequest(
    request({ ...envelope(), padding: "x".repeat(9 * 1024) }),
    dependencies(),
  );
  assert(response.status === 413, "oversized bodies must be rejected");
});

Deno.test("analytics storage failure is sanitized and does not echo properties", async () => {
  const response = await handleProductEventsRequest(
    request(
      envelope({
        properties: {
          source: "wizard",
          strategy: "bayesian",
          parameter_count: 7,
        },
      }),
    ),
    dependencies({
      record: () => Promise.reject(new Error("database raw secret")),
    }),
  );
  assert(
    response.status === 500,
    "unexpected storage errors should fail closed",
  );
  const text = await response.text();
  assert(
    !text.includes("database raw secret") && !text.includes("bayesian"),
    "errors must not echo raw values",
  );
});
