import { afterEach, describe, expect, it, vi } from "vitest";

import {
  FetchResponseSizeError,
  fetchWithDeadline,
} from "../api/fetchWithDeadline";

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("fetchWithDeadline response bounds", () => {
  it("rejects an oversized declared response before buffering its body", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response("tiny", {
          headers: { "Content-Length": "5" },
        }),
      ),
    );

    await expect(
      fetchWithDeadline("https://example.test/data", undefined, 1_000, 4),
    ).rejects.toMatchObject({
      name: "FetchResponseSizeError",
      maxResponseBytes: 4,
    });
  });

  it("rejects a chunked response once retained bytes exceed the limit", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(
          new ReadableStream<Uint8Array>({
            start(controller) {
              controller.enqueue(new Uint8Array([1, 2, 3]));
              controller.enqueue(new Uint8Array([4, 5]));
              controller.close();
            },
          }),
        ),
      ),
    );

    const response = await fetchWithDeadline(
      "https://example.test/chunked",
      undefined,
      1_000,
      4,
    );
    await expect(response.arrayBuffer()).rejects.toBeInstanceOf(
      FetchResponseSizeError,
    );
  });

  it("rejects invalid response limits before starting a request", async () => {
    const fetchSpy = vi.fn();
    vi.stubGlobal("fetch", fetchSpy);

    await expect(
      fetchWithDeadline("https://example.test/data", undefined, 1_000, 0),
    ).rejects.toThrow("positive safe integer");
    expect(fetchSpy).not.toHaveBeenCalled();
  });
});
