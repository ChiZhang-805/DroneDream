export type BoundedRequestErrorCode =
  | "REQUEST_TOO_LARGE"
  | "REQUEST_READ_FAILED"
  | "REQUEST_ABORTED"
  | "REQUEST_INVALID_ENCODING"
  | "INVALID_JSON"
  | "INVALID_JSON_OBJECT";

export class BoundedRequestError extends Error {
  readonly code: BoundedRequestErrorCode;
  readonly status: 400 | 413;
  readonly limitBytes: number;

  constructor(
    code: BoundedRequestErrorCode,
    message: string,
    status: 400 | 413,
    limitBytes: number,
  ) {
    super(message);
    this.name = "BoundedRequestError";
    this.code = code;
    this.status = status;
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

async function rejectUnreadBody(
  body: ReadableStream<Uint8Array> | null,
): Promise<void> {
  if (!body) return;
  let reader: ReadableStreamDefaultReader<Uint8Array> | null = null;
  try {
    reader = body.getReader();
    await reader.cancel("bounded request rejected");
  } catch {
    // Cancellation is best-effort. The bounded rejection remains authoritative.
  } finally {
    try {
      reader?.releaseLock();
    } catch {
      // The request is already rejected and no bytes are exposed.
    }
  }
}

export async function readBoundedRequestText(
  request: Request,
  limitBytes: number,
): Promise<string> {
  if (!Number.isSafeInteger(limitBytes) || limitBytes <= 0) {
    throw new TypeError("limitBytes must be a positive safe integer.");
  }

  const announcedLength = validContentLength(
    request.headers.get("Content-Length"),
  );
  if (announcedLength !== null && announcedLength > limitBytes) {
    await rejectUnreadBody(request.body);
    throw new BoundedRequestError(
      "REQUEST_TOO_LARGE",
      "The request body exceeds the configured byte limit.",
      413,
      limitBytes,
    );
  }

  const body = request.body;
  if (!body) return "";
  let reader: ReadableStreamDefaultReader<Uint8Array>;
  try {
    reader = body.getReader();
  } catch {
    throw new BoundedRequestError(
      "REQUEST_READ_FAILED",
      "The request body stream could not be read.",
      400,
      limitBytes,
    );
  }

  const decoder = new TextDecoder("utf-8", { fatal: true });
  const parts: string[] = [];
  let receivedBytes = 0;
  try {
    while (true) {
      let result: ReadableStreamReadResult<Uint8Array>;
      try {
        result = await reader.read();
      } catch (error) {
        const aborted = isAbortError(error);
        throw new BoundedRequestError(
          aborted ? "REQUEST_ABORTED" : "REQUEST_READ_FAILED",
          aborted
            ? "The request body stream was aborted."
            : "The request body stream failed.",
          400,
          limitBytes,
        );
      }
      if (result.done) break;
      receivedBytes += result.value.byteLength;
      if (receivedBytes > limitBytes) {
        try {
          await reader.cancel("bounded request byte limit exceeded");
        } catch {
          // Preserve the deterministic too-large error.
        }
        throw new BoundedRequestError(
          "REQUEST_TOO_LARGE",
          "The request body exceeds the configured byte limit.",
          413,
          limitBytes,
        );
      }
      try {
        parts.push(decoder.decode(result.value, { stream: true }));
      } catch {
        try {
          await reader.cancel("bounded request contained invalid UTF-8");
        } catch {
          // Preserve the invalid-encoding error.
        }
        throw new BoundedRequestError(
          "REQUEST_INVALID_ENCODING",
          "The request body must be valid UTF-8.",
          400,
          limitBytes,
        );
      }
    }
    try {
      parts.push(decoder.decode());
    } catch {
      throw new BoundedRequestError(
        "REQUEST_INVALID_ENCODING",
        "The request body must be valid UTF-8.",
        400,
        limitBytes,
      );
    }
    return parts.join("");
  } finally {
    try {
      reader.releaseLock();
    } catch {
      // The body has already been consumed or rejected.
    }
  }
}

export async function readBoundedJsonObject(
  request: Request,
  limitBytes: number,
): Promise<Record<string, unknown>> {
  const raw = await readBoundedRequestText(request, limitBytes);
  let parsed: unknown;
  try {
    parsed = JSON.parse(raw);
  } catch {
    throw new BoundedRequestError(
      "INVALID_JSON",
      "The request body must be valid JSON.",
      400,
      limitBytes,
    );
  }
  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
    throw new BoundedRequestError(
      "INVALID_JSON_OBJECT",
      "The request body must be a JSON object.",
      400,
      limitBytes,
    );
  }
  return parsed as Record<string, unknown>;
}
