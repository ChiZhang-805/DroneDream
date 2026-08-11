export class SensitiveCorsError extends Error {
  readonly code: "ORIGIN_NOT_ALLOWED" | "ORIGIN_CONFIGURATION_INVALID";
  readonly status: 403 | 503;

  constructor(
    code: "ORIGIN_NOT_ALLOWED" | "ORIGIN_CONFIGURATION_INVALID",
    message: string,
    status: 403 | 503,
  ) {
    super(message);
    this.name = "SensitiveCorsError";
    this.code = code;
    this.status = status;
  }
}

function localDevelopmentHost(hostname: string): boolean {
  const normalized = hostname.toLowerCase();
  return normalized === "localhost" ||
    normalized === "127.0.0.1" ||
    normalized === "[::1]" ||
    normalized.endsWith(".localhost");
}

export function isSafeSensitiveOrigin(origin: string): boolean {
  if (origin === "tauri://localhost") return true;
  let parsed: URL;
  try {
    parsed = new URL(origin);
  } catch {
    return false;
  }
  if (
    parsed.username ||
    parsed.password ||
    parsed.search ||
    parsed.hash ||
    parsed.pathname !== "/"
  ) {
    return false;
  }
  if (parsed.protocol === "https:") return parsed.origin === origin;
  return parsed.protocol === "http:" &&
    localDevelopmentHost(parsed.hostname) &&
    parsed.origin === origin;
}

export function sensitiveAllowedOrigins(
  configured: string | undefined,
  defaults: readonly string[],
): Set<string> {
  const candidates = (configured?.trim() ? configured.split(",") : defaults)
    .map((origin) => origin.trim())
    .filter(Boolean);
  if (
    !candidates.length ||
    candidates.some((origin) => !isSafeSensitiveOrigin(origin))
  ) {
    throw new SensitiveCorsError(
      "ORIGIN_CONFIGURATION_INVALID",
      "The sensitive CORS allowlist contains an unsafe origin.",
      503,
    );
  }
  return new Set(candidates);
}

export function sensitiveCorsHeaders(
  request: Request,
  allowedOrigins: ReadonlySet<string>,
): HeadersInit {
  const origin = request.headers.get("Origin");
  if (!origin) return {};
  if (!allowedOrigins.has(origin)) {
    throw new SensitiveCorsError(
      "ORIGIN_NOT_ALLOWED",
      "The request origin is not allowed.",
      403,
    );
  }
  return {
    "Access-Control-Allow-Origin": origin,
    "Access-Control-Allow-Credentials": "true",
    Vary: "Origin",
  };
}
