import {
  sensitiveAllowedOrigins,
  SensitiveCorsError,
  sensitiveCorsHeaders,
} from "./sensitive_cors.ts";

function assert(value: unknown, message: string): asserts value {
  if (!value) throw new Error(message);
}

function expectCorsError(
  request: Request,
  allowed: ReadonlySet<string>,
  code: SensitiveCorsError["code"],
): void {
  try {
    sensitiveCorsHeaders(request, allowed);
  } catch (error) {
    assert(
      error instanceof SensitiveCorsError,
      "expected a sensitive CORS error",
    );
    assert(error.code === code, `expected ${code}, received ${error.code}`);
    return;
  }
  throw new Error(`expected ${code}`);
}

Deno.test("rejects the public HTTP mirror for preflight and actual requests", () => {
  const allowed = sensitiveAllowedOrigins(undefined, [
    "https://getdronedream.com",
    "http://localhost:5173",
  ]);
  for (const method of ["OPTIONS", "POST"]) {
    expectCorsError(
      new Request("https://functions.example.test/sensitive", {
        method,
        headers: { Origin: "http://47.93.180.216" },
      }),
      allowed,
      "ORIGIN_NOT_ALLOWED",
    );
  }
});

Deno.test("rejects unknown and opaque null origins", () => {
  const allowed = sensitiveAllowedOrigins(undefined, [
    "https://getdronedream.com",
  ]);
  for (const origin of ["https://unknown.example", "null"]) {
    expectCorsError(
      new Request("https://functions.example.test/sensitive", {
        headers: { Origin: origin },
      }),
      allowed,
      "ORIGIN_NOT_ALLOWED",
    );
  }
});

Deno.test("allows an exact HTTPS origin and preserves credentials semantics", () => {
  const allowed = sensitiveAllowedOrigins(undefined, [
    "https://getdronedream.com",
  ]);
  const headers = new Headers(sensitiveCorsHeaders(
    new Request("https://functions.example.test/sensitive", {
      headers: { Origin: "https://getdronedream.com" },
    }),
    allowed,
  ));
  assert(
    headers.get("Access-Control-Allow-Origin") === "https://getdronedream.com",
    "the exact HTTPS origin should be returned",
  );
  assert(
    headers.get("Access-Control-Allow-Credentials") === "true",
    "credentialed requests should remain explicit",
  );
});

Deno.test("rejects wildcard and public HTTP configured aliases", () => {
  for (
    const configured of ["*", "http://47.93.180.216", "http://example.com"]
  ) {
    try {
      sensitiveAllowedOrigins(configured, ["https://getdronedream.com"]);
    } catch (error) {
      assert(
        error instanceof SensitiveCorsError,
        "expected a configuration error",
      );
      assert(
        error.code === "ORIGIN_CONFIGURATION_INVALID",
        "unsafe configured origins must fail closed",
      );
      continue;
    }
    throw new Error(`unsafe origin was accepted: ${configured}`);
  }
});

Deno.test("keeps explicit loopback and Tauri development origins available", () => {
  const allowed = sensitiveAllowedOrigins(undefined, [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://tauri.localhost",
    "tauri://localhost",
  ]);
  assert(
    allowed.size === 4,
    "all explicit local origins should remain available",
  );
});
