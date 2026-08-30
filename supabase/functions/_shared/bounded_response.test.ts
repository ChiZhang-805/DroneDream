import {
  BoundedResponseError,
  readBoundedResponseText,
} from "./bounded_response.ts";

function assert(value: unknown, message: string): asserts value {
  if (!value) throw new Error(message);
}

async function expectBoundedError(
  promise: Promise<unknown>,
  code: BoundedResponseError["code"],
): Promise<BoundedResponseError> {
  try {
    await promise;
  } catch (error) {
    assert(
      error instanceof BoundedResponseError,
      "expected a bounded response error",
    );
    assert(error.code === code, `expected ${code}, received ${error.code}`);
    return error;
  }
  throw new Error(`expected ${code}`);
}

Deno.test("rejects an oversized valid Content-Length before reading and cancels", async () => {
  let cancelled = false;
  const body = new ReadableStream<Uint8Array>({
    pull(controller) {
      controller.enqueue(new Uint8Array([1]));
    },
    cancel() {
      cancelled = true;
    },
  });
  const response = new Response(body, { headers: { "Content-Length": "65" } });

  await expectBoundedError(
    readBoundedResponseText(response, 64),
    "UPSTREAM_RESPONSE_TOO_LARGE",
  );
  assert(cancelled, "the rejected body must be cancelled");
  assert(!body.locked, "the response body lock must be released");
});

Deno.test("rejects a chunked response that exceeds the measured limit", async () => {
  let cancelled = false;
  const body = new ReadableStream<Uint8Array>({
    start(controller) {
      controller.enqueue(new Uint8Array(40));
      controller.enqueue(new Uint8Array(25));
    },
    cancel() {
      cancelled = true;
    },
  });

  await expectBoundedError(
    readBoundedResponseText(new Response(body), 64),
    "UPSTREAM_RESPONSE_TOO_LARGE",
  );
  assert(cancelled, "the over-limit reader must be cancelled");
  assert(!body.locked, "the response body lock must be released");
});

Deno.test("rejects a falsely small Content-Length when actual bytes exceed it", async () => {
  let cancelled = false;
  const body = new ReadableStream<Uint8Array>({
    start(controller) {
      controller.enqueue(new Uint8Array(33));
      controller.enqueue(new Uint8Array(32));
    },
    cancel() {
      cancelled = true;
    },
  });
  const response = new Response(body, { headers: { "Content-Length": "1" } });

  await expectBoundedError(
    readBoundedResponseText(response, 64),
    "UPSTREAM_RESPONSE_TOO_LARGE",
  );
  assert(cancelled, "the falsely announced body must be cancelled");
});

Deno.test("accepts a response exactly at the byte boundary", async () => {
  const text = "a".repeat(64);
  const body = new ReadableStream<Uint8Array>({
    start(controller) {
      controller.enqueue(new TextEncoder().encode(text.slice(0, 31)));
      controller.enqueue(new TextEncoder().encode(text.slice(31)));
      controller.close();
    },
  });

  assert(
    await readBoundedResponseText(new Response(body), 64) === text,
    "the exact boundary should be accepted",
  );
  assert(!body.locked, "the response body lock must be released");
});

Deno.test("accepts normal JSON and an empty body", async () => {
  const json = '{"ok":true}';
  const parsed = JSON.parse(
    await readBoundedResponseText(new Response(json), 64),
  ) as { ok?: boolean };
  assert(parsed.ok === true, "normal JSON should be returned unchanged");
  assert(
    await readBoundedResponseText(new Response(null), 64) === "",
    "an empty response body should return an empty string",
  );
});

Deno.test("maps a stream failure without exposing partial bytes", async () => {
  const body = new ReadableStream<Uint8Array>({
    start(controller) {
      controller.enqueue(new TextEncoder().encode("private provider text"));
      controller.error(new Error("upstream contained a secret"));
    },
  });
  const error = await expectBoundedError(
    readBoundedResponseText(new Response(body), 128),
    "UPSTREAM_RESPONSE_READ_FAILED",
  );
  assert(
    !error.message.includes("secret"),
    "the stream error must be sanitized",
  );
  assert(!body.locked, "the response body lock must be released");
});

Deno.test("maps an aborted stream to a structured error", async () => {
  const body = new ReadableStream<Uint8Array>({
    pull() {
      throw new DOMException(
        "provider aborted with private data",
        "AbortError",
      );
    },
  });
  const error = await expectBoundedError(
    readBoundedResponseText(new Response(body), 64),
    "UPSTREAM_RESPONSE_ABORTED",
  );
  assert(
    !error.message.includes("private"),
    "the abort error must be sanitized",
  );
  assert(!body.locked, "the response body lock must be released");
});

Deno.test("rejects non-UTF-8 bytes and cancels the stream", async () => {
  let cancelled = false;
  const body = new ReadableStream<Uint8Array>({
    start(controller) {
      controller.enqueue(new Uint8Array([0xff]));
    },
    cancel() {
      cancelled = true;
    },
  });
  await expectBoundedError(
    readBoundedResponseText(new Response(body), 64),
    "UPSTREAM_RESPONSE_INVALID_ENCODING",
  );
  assert(cancelled, "invalid UTF-8 must cancel the reader");
  assert(!body.locked, "the response body lock must be released");
});
