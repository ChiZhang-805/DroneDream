export type BoundedResponseErrorCode =
  | "UPSTREAM_RESPONSE_TOO_LARGE"
  | "UPSTREAM_RESPONSE_READ_FAILED"
  | "UPSTREAM_RESPONSE_ABORTED"
  | "UPSTREAM_RESPONSE_INVALID_ENCODING";

export class BoundedResponseError extends Error {
  readonly code: BoundedResponseErrorCode;
  readonly limitBytes: number;

  constructor(
    code: BoundedResponseErrorCode,
    message: string,
    limitBytes: number,
  ) {
    super(message);
    this.name = "BoundedResponseError";
    this.code = code;
    this.limitBytes = limitBytes;
  }
}

function validContentLength(value: string | null): number | null {
  const normalized = value?.trim() ?? "";
  if (!/^(0|[1-9][0-9]*)$/u.test(normalized)) return null;
  const parsed = Number(normalized);
  return Number.isSafeInteger(parsed) ? parsed : null;
}

function isAbortError(error: unknown): boolean {
  return error instanceof DOMException && error.name === "AbortError";
}

async function cancelBody(
  body: ReadableStream<Uint8Array> | null,
): Promise<void> {
  if (!body) return;
  let reader: ReadableStreamDefaultReader<Uint8Array> | null = null;
  try {
    reader = body.getReader();
    await reader.cancel("bounded response rejected");
  } catch {
    // Cancellation is best-effort. The bounded error remains authoritative and
    // must not be replaced by an upstream cancellation failure.
  } finally {
    try {
      reader?.releaseLock();
    } catch {
      // A failed release cannot expose or enlarge the rejected response body.
    }
  }
}

export async function readBoundedResponseText(
  response: Response,
  limitBytes: number,
): Promise<string> {
  if (!Number.isSafeInteger(limitBytes) || limitBytes <= 0) {
    throw new TypeError("limitBytes must be a positive safe integer.");
  }

  const announcedLength = validContentLength(
    response.headers.get("Content-Length"),
  );
  if (announcedLength !== null && announcedLength > limitBytes) {
    await cancelBody(response.body);
    throw new BoundedResponseError(
      "UPSTREAM_RESPONSE_TOO_LARGE",
      "The upstream response exceeded the configured byte limit.",
      limitBytes,
    );
  }

  const body = response.body;
  if (!body) return "";

  let reader: ReadableStreamDefaultReader<Uint8Array>;
  try {
    reader = body.getReader();
  } catch {
    throw new BoundedResponseError(
      "UPSTREAM_RESPONSE_READ_FAILED",
      "The upstream response stream could not be read.",
      limitBytes,
    );
  }

  const decoder = new TextDecoder("utf-8", { fatal: true });
  const textParts: string[] = [];
  let receivedBytes = 0;

  try {
    while (true) {
      let result: ReadableStreamReadResult<Uint8Array>;
      try {
        result = await reader.read();
      } catch (error) {
        throw new BoundedResponseError(
          isAbortError(error) ? "UPSTREAM_RESPONSE_ABORTED" : "UPSTREAM_RESPONSE_READ_FAILED",
          isAbortError(error) ? "The upstream response was aborted." : "The upstream response stream failed.",
          limitBytes,
        );
      }

      if (result.done) break;
      const chunk = result.value;
      receivedBytes += chunk.byteLength;
      if (receivedBytes > limitBytes) {
        try {
          await reader.cancel("bounded response byte limit exceeded");
        } catch {
          // Preserve the deterministic too-large error even if cancellation
          // itself fails.
        }
        throw new BoundedResponseError(
          "UPSTREAM_RESPONSE_TOO_LARGE",
          "The upstream response exceeded the configured byte limit.",
          limitBytes,
        );
      }

      try {
        textParts.push(decoder.decode(chunk, { stream: true }));
      } catch {
        try {
          await reader.cancel("bounded response contained invalid UTF-8");
        } catch {
          // Preserve the invalid-encoding error.
        }
        throw new BoundedResponseError(
          "UPSTREAM_RESPONSE_INVALID_ENCODING",
          "The upstream response was not valid UTF-8.",
          limitBytes,
        );
      }
    }

    try {
      textParts.push(decoder.decode());
    } catch {
      throw new BoundedResponseError(
        "UPSTREAM_RESPONSE_INVALID_ENCODING",
        "The upstream response was not valid UTF-8.",
        limitBytes,
      );
    }
    return textParts.join("");
  } finally {
    try {
      reader.releaseLock();
    } catch {
      // The response body has already been bounded or rejected.
    }
  }
}
