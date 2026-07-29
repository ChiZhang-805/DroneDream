const HTTPS_SENSITIVE_HOSTS = new Set([
  "getdronedream.com",
  "www.getdronedream.com",
  "chizhang-805.github.io",
]);

function isLoopbackHost(hostname: string): boolean {
  const normalized = hostname.toLowerCase();
  return normalized === "localhost"
    || normalized === "127.0.0.1"
    || normalized === "[::1]"
    || normalized.endsWith(".localhost");
}

export function isSensitiveCloudOriginAllowed(url: string): boolean {
  if (url.startsWith("tauri://localhost/") || url === "tauri://localhost") {
    return true;
  }
  let parsed: URL;
  try {
    parsed = new URL(url);
  } catch {
    return false;
  }
  if (parsed.username || parsed.password) return false;
  if (parsed.protocol === "https:") {
    return HTTPS_SENSITIVE_HOSTS.has(parsed.hostname.toLowerCase())
      && (parsed.port === "" || parsed.port === "443");
  }
  return parsed.protocol === "http:" && isLoopbackHost(parsed.hostname);
}

export function sensitiveCloudActionsAllowed(): boolean {
  if (typeof window === "undefined") return false;
  return isSensitiveCloudOriginAllowed(window.location.href);
}
