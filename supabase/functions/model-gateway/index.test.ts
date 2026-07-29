import { handleModelGatewayRequest, modelProviderResponseLimitBytes, readModelProviderResponseBody } from "./index.ts";

function assert(value: unknown, message: string): asserts value {
  if (!value) throw new Error(message);
}

async function responseErrorCode(response: Response): Promise<string> {
  const body = await response.json() as { error?: { code?: string } };
  return body.error?.code ?? "";
}

Deno.test("model response byte budget scales conservatively and has a hard cap", () => {
  assert(
    modelProviderResponseLimitBytes(64) === 32 * 1_024 + 64 * 64,
    "the minimum provider token budget should receive base plus per-token bytes",
  );
  assert(
    modelProviderResponseLimitBytes(2_048) === 32 * 1_024 + 2_048 * 64,
    "the default output budget should map deterministically",
  );
  assert(
    modelProviderResponseLimitBytes(16_384) === 1_024 * 1_024,
    "the configured maximum should stop at one MiB",
  );
  assert(
    modelProviderResponseLimitBytes(Number.MAX_SAFE_INTEGER) === 1_024 * 1_024,
    "an invalid caller value must not enlarge the hard cap",
  );
});

Deno.test("model call-point reader accepts JSON and rejects actual overrun", async () => {
  const text = '{"choices":[{"message":{"content":"ok"}}]}';
  assert(
    await readModelProviderResponseBody(new Response(text), 64) === text,
    "the model call point should preserve normal JSON",
  );

  let cancelled = false;
  const body = new ReadableStream<Uint8Array>({
    start(controller) {
      controller.enqueue(
        new Uint8Array(
          modelProviderResponseLimitBytes(64) + 1,
        ),
      );
    },
    cancel() {
      cancelled = true;
    },
  });
  try {
    await readModelProviderResponseBody(new Response(body), 64);
  } catch (error) {
    assert(
      error instanceof Error &&
        error.name === "BoundedResponseError" &&
        "code" in error &&
        error.code === "UPSTREAM_RESPONSE_TOO_LARGE",
      "the model call point should preserve a structured bounded error",
    );
    assert(cancelled, "the model call point must cancel an oversized body");
    return;
  }
  throw new Error("the oversized model response should fail closed");
});

Deno.test("model gateway rejects the HTTP mirror for preflight and actual calls", async () => {
  for (const method of ["OPTIONS", "POST"]) {
    const response = await handleModelGatewayRequest(
      new Request("https://functions.example.test/model-gateway/grants", {
        method,
        headers: { Origin: "http://47.93.180.216" },
      }),
    );
    assert(response.status === 403, `${method} should be rejected`);
    assert(
      await responseErrorCode(response) === "ORIGIN_NOT_ALLOWED",
      `${method} should return the structured origin error`,
    );
    assert(
      !response.headers.has("Access-Control-Allow-Origin"),
      "the rejected origin must not receive CORS access",
    );
  }
});

Deno.test("model gateway allows exact HTTPS preflight without requiring auth", async () => {
  const response = await handleModelGatewayRequest(
    new Request("https://functions.example.test/model-gateway/grants", {
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
