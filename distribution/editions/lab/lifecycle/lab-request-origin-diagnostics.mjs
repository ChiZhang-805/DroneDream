import { createHash } from "node:crypto";

const AUTH_MARKER = /(?:\/auth\/v1\/|oauth|authorize|token|session)/iu;
const NETWORK_SCHEMES = new Set(["http", "https", "ws", "wss"]);
const INTERNAL_SCHEMES = new Map([
  ["asset", "tauri-asset-scheme"],
  ["blob", "embedded-app-resource"],
  ["data", "embedded-app-resource"],
  ["ipc", "tauri-ipc-scheme"],
  ["tauri", "tauri-internal-scheme"],
]);
const INTERNAL_HOSTS = new Map([
  ["asset.localhost", "tauri-asset-origin"],
  ["ipc.localhost", "tauri-ipc-origin"],
  ["tauri.localhost", "tauri-app-origin"],
]);
const SAFE_RESOURCE_TYPES = new Set([
  "document",
  "stylesheet",
  "image",
  "media",
  "font",
  "script",
  "texttrack",
  "xhr",
  "fetch",
  "eventsource",
  "websocket",
  "manifest",
  "other",
]);

function sha256(value) {
  return createHash("sha256").update(value, "utf8").digest("hex");
}

function normalizedPort(url) {
  if (url.port) return Number(url.port);
  if (url.protocol === "http:" || url.protocol === "ws:") return 80;
  if (url.protocol === "https:" || url.protocol === "wss:") return 443;
  return null;
}

function safeResourceType(value) {
  const normalized = String(value ?? "other").toLowerCase();
  return SAFE_RESOURCE_TYPES.has(normalized) ? normalized : "other";
}

function initiatorClass(resourceType, observationSource, isNavigationRequest) {
  if (isNavigationRequest) return "document-navigation";
  if (observationSource === "performance-resource") {
    return `performance-${safeResourceType(resourceType)}`;
  }
  return `webview-${safeResourceType(resourceType)}`;
}

function endpointIdentity(cdpEndpoint) {
  try {
    const parsed = new URL(cdpEndpoint);
    if (parsed.protocol !== "http:" || parsed.hostname !== "127.0.0.1" || !parsed.port) {
      return null;
    }
    return { hostname: parsed.hostname, port: Number(parsed.port) };
  } catch {
    return null;
  }
}

export function classifyRequest(rawUrl, options = {}) {
  const resourceType = safeResourceType(options.resourceType);
  const observationSource = options.observationSource === "performance-resource"
    ? "performance-resource"
    : "playwright-request";
  const authSensitive = AUTH_MARKER.test(String(rawUrl));
  let parsed;
  try {
    parsed = new URL(String(rawUrl));
  } catch {
    return {
      scheme: "unparseable",
      hostClass: "unparseable-url",
      port: null,
      pathSha256: sha256(""),
      queryPresent: false,
      fragmentPresent: false,
      resourceType,
      initiatorClass: initiatorClass(
        resourceType,
        observationSource,
        options.isNavigationRequest === true,
      ),
      observationSource,
      authSensitive,
      decision: "deny",
      reason: authSensitive ? "auth-sensitive-unparseable-url" : "unparseable-url",
    };
  }

  const scheme = parsed.protocol.slice(0, -1).toLowerCase();
  const base = {
    scheme,
    port: normalizedPort(parsed),
    pathSha256: sha256(parsed.pathname || ""),
    queryPresent: parsed.search.length > 0,
    fragmentPresent: parsed.hash.length > 0,
    resourceType,
    initiatorClass: initiatorClass(
      resourceType,
      observationSource,
      options.isNavigationRequest === true,
    ),
    observationSource,
    authSensitive,
  };
  const finalize = (record) => authSensitive
    ? {
        ...record,
        decision: "deny",
        reason: "auth-sensitive-route-or-query",
      }
    : record;

  const internalSchemeClass = INTERNAL_SCHEMES.get(scheme);
  if (internalSchemeClass) {
    return finalize({
      ...base,
      hostClass: internalSchemeClass,
      decision: "allow",
      reason: "tauri-or-embedded-internal-resource",
    });
  }

  if (!NETWORK_SCHEMES.has(scheme)) {
    return finalize({
      ...base,
      hostClass: "unknown-scheme-origin",
      decision: "deny",
      reason: "unknown-scheme",
    });
  }

  const hostname = parsed.hostname.toLowerCase();
  const internalHostClass = INTERNAL_HOSTS.get(hostname);
  if (internalHostClass) {
    return finalize({
      ...base,
      hostClass: internalHostClass,
      decision: "allow",
      reason: "tauri-webview-internal-origin",
    });
  }

  const cdp = endpointIdentity(options.cdpEndpoint);
  if (cdp && hostname === cdp.hostname && normalizedPort(parsed) === cdp.port) {
    return finalize({
      ...base,
      hostClass: "execution-owned-cdp",
      decision: "allow",
      reason: "exact-execution-owned-cdp-origin",
    });
  }

  if (hostname === "127.0.0.1" || hostname === "localhost") {
    return finalize({
      ...base,
      hostClass: "local-loopback",
      decision: "allow",
      reason: "local-loopback-origin",
    });
  }

  return finalize({
    ...base,
    hostClass: "external-network-origin",
    decision: "deny",
    reason: "external-origin-not-allowlisted",
  });
}

export function requestDiagnosticsEvidence(records, { phase, status, failureClass = null }) {
  const allowedCount = records.filter((record) => record.decision === "allow").length;
  const deniedCount = records.length - allowedCount;
  const authSensitiveCount = records.filter((record) => record.authSensitive).length;
  return {
    schemaVersion: 1,
    kind: "dronedream-lab-redacted-request-origin-diagnostics",
    phase,
    status,
    failureClass,
    redactionContract: {
      rawUrlPersisted: false,
      rawHostPersisted: false,
      rawPathPersisted: false,
      queryPersistedOrHashed: false,
      headersCookiesTokensApiKeysEmailsPersisted: false,
      retainedFields: [
        "scheme",
        "hostClass",
        "port",
        "pathSha256",
        "queryPresent",
        "fragmentPresent",
        "resourceType",
        "initiatorClass",
        "observationSource",
        "authSensitive",
        "decision",
        "reason",
      ],
    },
    observedCount: records.length,
    allowedCount,
    deniedCount,
    authSensitiveCount,
    records,
  };
}
