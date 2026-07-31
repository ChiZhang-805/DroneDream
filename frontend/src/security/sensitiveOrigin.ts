const HTTPS_SENSITIVE_HOSTS = new Set([
  "getdronedream.com",
  "www.getdronedream.com",
  "chizhang-805.github.io",
]);

const HTTP_INTERNAL_PREVIEW_HOSTS = new Set([
  "47.93.180.216",
  "getdronedream.com",
  "www.getdronedream.com",
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

export function isAccountCommunityOriginAllowed(url: string): boolean {
  if (isSensitiveCloudOriginAllowed(url)) return true;
  let parsed: URL;
  try {
    parsed = new URL(url);
  } catch {
    return false;
  }
  if (parsed.username || parsed.password) return false;
  return parsed.protocol === "http:"
    && (parsed.port === "" || parsed.port === "80")
    && HTTP_INTERNAL_PREVIEW_HOSTS.has(parsed.hostname.toLowerCase());
}

export function accountCommunityActionsAllowed(): boolean {
  if (typeof window === "undefined") return false;
  return isAccountCommunityOriginAllowed(window.location.href);
}
