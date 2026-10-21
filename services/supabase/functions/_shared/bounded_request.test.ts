import {
  BoundedRequestError,
  readBoundedJsonObject,
  readBoundedRequestText,
} from "./bounded_request.ts";

function assert(value: unknown, message: string): asserts value {
  if (!value) throw new Error(message);
}

async function expectCode(
  work: () => Promise<unknown>,
  code: BoundedRequestError["code"],
): Promise<void> {
  try {
    await work();
  } catch (error) {
    assert(
      error instanceof BoundedRequestError && error.code === code,
      `expected ${code}`,
    );
    return;
  }
  throw new Error(`expected ${code}`);
}

Deno.test("bounded request rejects announced and streamed overruns and cancels", async () => {
  let announcedCancelled = false;
  const announced = new ReadableStream<Uint8Array>({
    start(controller) {
      controller.enqueue(new TextEncoder().encode("safe"));
    },
    cancel() {
      announcedCancelled = true;
    },
  });
  await expectCode(
    () =>
      readBoundedRequestText(
        new Request("https://example.test", {
          method: "POST",
          headers: { "Content-Length": "99" },
          body: announced,
        }),
        8,
      ),
    "REQUEST_TOO_LARGE",
  );
  assert(announcedCancelled, "announced overrun must cancel the body");

  let streamedCancelled = false;
  const streamed = new ReadableStream<Uint8Array>({
    start(controller) {
      controller.enqueue(new Uint8Array(5));
      controller.enqueue(new Uint8Array(5));
    },
    cancel() {
      streamedCancelled = true;
    },
  });
  await expectCode(
    () =>
      readBoundedRequestText(
        new Request("https://example.test", {
          method: "POST",
          headers: { "Content-Length": "1" },
          body: streamed,
        }),
        8,
      ),
    "REQUEST_TOO_LARGE",
  );
  assert(streamedCancelled, "actual overrun must cancel the body");
});

Deno.test("bounded request accepts the exact byte boundary and JSON object", async () => {
  const raw = '{"ok":true}';
  const parsed = await readBoundedJsonObject(
    new Request("https://example.test", { method: "POST", body: raw }),
    new TextEncoder().encode(raw).byteLength,
  );
  assert(parsed.ok === true, "normal JSON should be preserved");
});

Deno.test("bounded request rejects invalid UTF-8 and stream failures", async () => {
  await expectCode(
    () =>
      readBoundedRequestText(
        new Request("https://example.test", {
          method: "POST",
          body: new Uint8Array([0xc3, 0x28]),
        }),
        8,
      ),
    "REQUEST_INVALID_ENCODING",
  );

  const failed = new ReadableStream<Uint8Array>({
    pull() {
      throw new Error("private upstream detail");
    },
  });
  await expectCode(
    () =>
      readBoundedRequestText(
        new Request("https://example.test", { method: "POST", body: failed }),
        8,
      ),
    "REQUEST_READ_FAILED",
  );
});
