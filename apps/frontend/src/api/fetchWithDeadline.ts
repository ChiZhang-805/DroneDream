export class FetchDeadlineError extends Error {
  readonly timeoutMs: number;

  constructor(timeoutMs: number) {
    super(`Request timed out after ${Math.ceil(timeoutMs / 1_000)} seconds.`);
    this.name = "FetchDeadlineError";
    this.timeoutMs = timeoutMs;
  }
}

export class FetchResponseSizeError extends Error {
  readonly maxResponseBytes: number;
  readonly httpStatus: number;

  constructor(maxResponseBytes: number, httpStatus = 0) {
    const mebibyte = 1024 * 1024;
    const readableLimit =
      maxResponseBytes >= mebibyte && maxResponseBytes % mebibyte === 0
        ? `${maxResponseBytes / mebibyte} MiB`
        : `${maxResponseBytes} bytes`;
    super(
      `Response exceeded the ${readableLimit} safety limit.`,
    );
    this.name = "FetchResponseSizeError";
    this.maxResponseBytes = maxResponseBytes;
    this.httpStatus = httpStatus;
  }
}

/**
 * Apply a hard deadline and optional byte limit through both response headers
 * and response body while preserving a caller-provided abort signal.
 *
 * The explicit race is intentional: native fetch rejects when aborted, but a
 * test double, embedded transport, or future fetch shim may ignore the signal.
 * Such an implementation must not leave the product waiting forever.
 */
export async function fetchWithDeadline(
  input: RequestInfo | URL,
  init: RequestInit | undefined,
  timeoutMs: number,
  maxResponseBytes?: number,
): Promise<Response> {
  if (!Number.isFinite(timeoutMs) || timeoutMs <= 0) {
    throw new TypeError("Fetch deadline must be a positive finite duration.");
  }
  if (
    maxResponseBytes !== undefined &&
    (!Number.isSafeInteger(maxResponseBytes) || maxResponseBytes <= 0)
  ) {
    throw new TypeError("Fetch response limit must be a positive safe integer.");
  }

  const controller = new AbortController();
  const upstreamSignal = init?.signal;
  let responseController: ReadableStreamDefaultController<Uint8Array> | null =
    null;
  let responseReader: ReadableStreamDefaultReader<Uint8Array> | null = null;
  let timer: ReturnType<typeof setTimeout> | undefined;
  let rejectDeadline: ((reason: unknown) => void) | null = null;
  let settled = false;
  let receivedBytes = 0;

  const cleanup = () => {
    if (timer !== undefined) clearTimeout(timer);
    timer = undefined;
    upstreamSignal?.removeEventListener("abort", relayAbort);
  };
  const fail = (reason: unknown) => {
    if (settled) return;
    settled = true;
    cleanup();
    controller.abort(reason);
    rejectDeadline?.(reason);
    responseController?.error(reason);
    void responseReader?.cancel(reason).catch(() => undefined);
  };
  const relayAbort = () => {
    fail(
      upstreamSignal?.reason ??
        new DOMException("The request was aborted.", "AbortError"),
    );
  };

  const deadline = new Promise<never>((_resolve, reject) => {
    rejectDeadline = reject;
    timer = setTimeout(() => {
      fail(new FetchDeadlineError(timeoutMs));
    }, timeoutMs);
  });
  if (upstreamSignal?.aborted) {
    relayAbort();
  } else {
    upstreamSignal?.addEventListener("abort", relayAbort, { once: true });
  }

  let response: Response;
  try {
    response = await Promise.race([
      fetch(input, { ...init, signal: controller.signal }),
      deadline,
    ]);
  } catch (error) {
    if (!settled) {
      settled = true;
      cleanup();
    }
    throw error;
  }
  const declaredLength = response.headers.get("Content-Length");
  if (
    maxResponseBytes !== undefined &&
    declaredLength !== null &&
    /^\d+$/.test(declaredLength.trim()) &&
    Number(declaredLength) > maxResponseBytes
  ) {
    const error = new FetchResponseSizeError(maxResponseBytes, response.status);
    fail(error);
    void response.body?.cancel(error).catch(() => undefined);
    throw error;
  }
  if (response.body === null) {
    settled = true;
    cleanup();
    return response;
  }

  responseReader = response.body.getReader();
  const boundedBody = new ReadableStream<Uint8Array>({
    start(streamController) {
      responseController = streamController;
    },
    async pull(streamController) {
      try {
        const chunk = await responseReader?.read();
        if (!chunk || chunk.done) {
          if (!settled) {
            settled = true;
            cleanup();
            streamController.close();
          }
          return;
        }
        if (
          maxResponseBytes !== undefined &&
          receivedBytes + chunk.value.byteLength > maxResponseBytes
        ) {
          fail(new FetchResponseSizeError(maxResponseBytes, response.status));
          return;
        }
        receivedBytes += chunk.value.byteLength;
        streamController.enqueue(chunk.value);
      } catch (error) {
        if (!settled) {
          settled = true;
          cleanup();
          streamController.error(error);
        }
      }
    },
    async cancel(reason) {
      if (!settled) {
        settled = true;
        cleanup();
      }
      await responseReader?.cancel(reason);
    },
  });
  return new Response(boundedBody, {
    status: response.status,
    statusText: response.statusText,
    headers: response.headers,
  });
}
