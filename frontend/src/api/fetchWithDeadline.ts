export class FetchDeadlineError extends Error {
  readonly timeoutMs: number;

  constructor(timeoutMs: number) {
    super(`Request timed out after ${Math.ceil(timeoutMs / 1_000)} seconds.`);
    this.name = "FetchDeadlineError";
    this.timeoutMs = timeoutMs;
  }
}

/**
 * Apply a hard deadline while preserving a caller-provided abort signal.
 *
 * The explicit race is intentional: native fetch rejects when aborted, but a
 * test double, embedded transport, or future fetch shim may ignore the signal.
 * Such an implementation must not leave the product waiting forever.
 */
export async function fetchWithDeadline(
  input: RequestInfo | URL,
  init: RequestInit | undefined,
  timeoutMs: number,
): Promise<Response> {
  if (!Number.isFinite(timeoutMs) || timeoutMs <= 0) {
    throw new TypeError("Fetch deadline must be a positive finite duration.");
  }

  const controller = new AbortController();
  const upstreamSignal = init?.signal;
  const relayAbort = () => controller.abort(upstreamSignal?.reason);
  if (upstreamSignal?.aborted) {
    relayAbort();
  } else {
    upstreamSignal?.addEventListener("abort", relayAbort, { once: true });
  }

  let timer: ReturnType<typeof setTimeout> | undefined;
  const deadline = new Promise<never>((_resolve, reject) => {
    timer = setTimeout(() => {
      const error = new FetchDeadlineError(timeoutMs);
      controller.abort(error);
      reject(error);
    }, timeoutMs);
  });

  try {
    return await Promise.race([
      fetch(input, { ...init, signal: controller.signal }),
      deadline,
    ]);
  } finally {
    if (timer !== undefined) clearTimeout(timer);
    upstreamSignal?.removeEventListener("abort", relayAbort);
  }
}
