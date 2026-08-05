"use strict";

// Narrow, fail-closed adapter for the preregistered P5 physical-stability run.
// Merely importing this module performs no desktop, network, Runtime, PX4, or
// Gazebo I/O.  A future RED-window runner must inject an already connected
// Tauri WebView page and the exact expected Engine Pack identity.

const crypto = require("node:crypto");

const MAX_JSON_RESPONSE_BYTES = 16 * 1024 * 1024;
const P5_IDEMPOTENCY_KEY = /^p5-[0-9a-f]{16}-[0-9]{2}-[0-9a-f]{16}$/;
const PACK_ID = /^sha256:[0-9a-f]{64}$/;
const GIT_COMMIT = /^[0-9a-f]{40}$/;
const IDENTIFIER = "[a-z0-9][a-z0-9._-]{0,127}";
const ROUTES = [
  { method: "GET", pattern: /^\/api\/v1\/session$/ },
  { method: "POST", pattern: /^\/api\/v1\/jobs$/ },
  { method: "GET", pattern: new RegExp(`^/api/v1/jobs/${IDENTIFIER}$`) },
  {
    method: "GET",
    pattern: new RegExp(
      `^/api/v1/jobs/${IDENTIFIER}/trials\\?page=1&page_size=100$`,
    ),
  },
  { method: "GET", pattern: new RegExp(`^/api/v1/jobs/${IDENTIFIER}/artifacts$`) },
  { method: "GET", pattern: new RegExp(`^/api/v1/jobs/${IDENTIFIER}/report$`) },
  { method: "GET", pattern: new RegExp(`^/api/v1/trials/${IDENTIFIER}$`) },
];
const SENSITIVE_KEYS = new Set([
  "access_token",
  "api_key",
  "authorization",
  "cookie",
  "password",
  "provider_request_id",
  "raw_chat",
  "raw_chat_history",
  "raw_prompt",
  "secret",
]);

function fail(message) {
  throw new Error(message);
}

function rejectSensitiveFields(value, path = "$") {
  if (Array.isArray(value)) {
    value.forEach((item, index) => rejectSensitiveFields(item, `${path}[${index}]`));
    return;
  }
  if (value && typeof value === "object") {
    for (const [key, item] of Object.entries(value)) {
      if (SENSITIVE_KEYS.has(key.trim().toLowerCase())) {
        fail(`sensitive field is forbidden at ${path}.${key}`);
      }
      rejectSensitiveFields(item, `${path}.${key}`);
    }
  }
}

function canonicalJson(value) {
  if (value === null || typeof value === "boolean" || typeof value === "string") {
    return JSON.stringify(value);
  }
  if (typeof value === "number") {
    if (!Number.isFinite(value)) fail("non-finite number is forbidden in a P5 payload");
    return JSON.stringify(value);
  }
  if (Array.isArray(value)) return `[${value.map(canonicalJson).join(",")}]`;
  if (value && typeof value === "object") {
    return `{${Object.keys(value)
      .sort()
      .map((key) => `${JSON.stringify(key)}:${canonicalJson(value[key])}`)
      .join(",")}}`;
  }
  fail("undefined or unsupported value is forbidden in a P5 payload");
}

function canonicalSha256(value) {
  rejectSensitiveFields(value);
  return crypto.createHash("sha256").update(canonicalJson(value), "utf8").digest("hex");
}

function validateRoute(method, apiPath, body, idempotencyKey) {
  if (!ROUTES.some((route) => route.method === method && route.pattern.test(apiPath))) {
    fail(`P5 desktop API route is not allowlisted: ${method} ${apiPath}`);
  }
  if (method === "POST") {
    if (body === null || typeof body !== "object" || Array.isArray(body)) {
      fail("P5 Job creation requires one JSON object body");
    }
    if (!P5_IDEMPOTENCY_KEY.test(idempotencyKey || "")) {
      fail("P5 Job creation requires its frozen idempotency key");
    }
    rejectSensitiveFields(body);
  } else if (body !== null || idempotencyKey !== null) {
    fail("P5 read-only API requests cannot carry a body or idempotency key");
  }
}

function decodeJsonResponse(response, method, apiPath) {
  if (!response || typeof response !== "object") fail("desktop API returned no response");
  if (response.missingSession === true) {
    fail("desktop WebView has no authenticated account session");
  }
  if (!Number.isInteger(response.status) || response.status < 200 || response.status >= 300) {
    const status = Number.isInteger(response.status) ? response.status : "invalid";
    fail(`P5 desktop API ${method} ${apiPath} returned ${status}`);
  }
  if (
    typeof response.contentType !== "string"
    || !/^application\/json(?:\s*;|$)/i.test(response.contentType)
  ) {
    fail("P5 desktop API response is not JSON");
  }
  if (typeof response.bodyBase64 !== "string") fail("P5 desktop API body is missing");
  if (response.bodyBase64.length > Math.ceil(MAX_JSON_RESPONSE_BYTES / 3) * 4 + 4) {
    fail("P5 desktop API JSON body exceeds its local cap");
  }
  if (
    response.bodyBase64.length % 4 !== 0
    || !/^(?:[A-Za-z0-9+/]{4})*(?:[A-Za-z0-9+/]{2}==|[A-Za-z0-9+/]{3}=)?$/.test(
      response.bodyBase64,
    )
  ) {
    fail("P5 desktop API body is not canonical base64");
  }
  const bytes = Buffer.from(response.bodyBase64, "base64");
  if (bytes.length > MAX_JSON_RESPONSE_BYTES) fail("P5 desktop API JSON body exceeds its cap");
  let envelope;
  try {
    envelope = JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(bytes));
  } catch {
    fail("P5 desktop API body is not valid UTF-8 JSON");
  }
  if (!envelope || typeof envelope !== "object" || Array.isArray(envelope)) {
    fail("P5 desktop API response envelope is invalid");
  }
  if (!Object.prototype.hasOwnProperty.call(envelope, "data")) {
    fail("P5 desktop API response omitted its data envelope");
  }
  rejectSensitiveFields(envelope.data);
  return envelope.data;
}

async function localApi(page, method, apiPath, body = null, idempotencyKey = null) {
  validateRoute(method, apiPath, body, idempotencyKey);
  if (!page || typeof page.evaluate !== "function") fail("desktop WebView page is unavailable");
  const response = await page.evaluate(
    async ({ methodValue, pathValue, bodyValue, idempotencyValue }) => {
      let session = null;
      try {
        const storageKey = Object.keys(sessionStorage).find(
          (name) => name.startsWith("sb-") && name.endsWith("-auth-token"),
        );
        session = storageKey ? JSON.parse(sessionStorage.getItem(storageKey) || "null") : null;
      } catch {
        return { status: 0, contentType: null, bodyBase64: "", missingSession: true };
      }
      if (!session?.access_token) {
        return { status: 0, contentType: null, bodyBase64: "", missingSession: true };
      }
      const result = await window.__TAURI_INTERNALS__.invoke("desktop_api_request", {
        request: {
          method: methodValue,
          path: pathValue,
          body: bodyValue === null ? null : JSON.stringify(bodyValue),
          accessToken: session.access_token,
          accept: "application/json",
          idempotencyKey: idempotencyValue,
        },
      });
      return {
        status: result.status,
        contentType: result.contentType || null,
        bodyBase64: result.bodyBase64 || "",
        missingSession: false,
      };
    },
    {
      methodValue: method,
      pathValue: apiPath,
      bodyValue: body,
      idempotencyValue: idempotencyKey,
    },
  );
  return decodeJsonResponse(response, method, apiPath);
}

function validateEnginePackStatus(status, expected) {
  if (!PACK_ID.test(expected.packId || "") || !GIT_COMMIT.test(expected.sourceCommit || "")) {
    fail("expected Engine Pack identity is invalid");
  }
  if (!status || typeof status !== "object") fail("Engine Pack status is unavailable");
  if (
    status.supported !== true
    || status.updateRequired !== false
    || status.installedPackId !== expected.packId
    || status.installedSourceCommit !== expected.sourceCommit
  ) {
    fail("active Engine Pack does not match the P5 composite inventory");
  }
  return {
    installedPackId: status.installedPackId,
    installedSourceCommit: status.installedSourceCommit,
  };
}

async function verifyEnginePack(page, expected) {
  if (!page || typeof page.evaluate !== "function") fail("desktop WebView page is unavailable");
  const status = await page.evaluate(
    () => window.__TAURI_INTERNALS__.invoke("get_engine_pack_status"),
  );
  return validateEnginePackStatus(status, expected);
}

async function connectToDesktop(cdpUrl) {
  if (!/^http:\/\/127\.0\.0\.1:[0-9]{2,5}$/.test(cdpUrl)) {
    fail("desktop CDP endpoint must be an explicit loopback URL");
  }
  const { chromium } = require("../../frontend/node_modules/playwright");
  const browser = await chromium.connectOverCDP(cdpUrl);
  const pages = browser.contexts().flatMap((context) => context.pages());
  const matching = pages.filter((page) => page.url().startsWith("http://tauri.localhost"));
  if (matching.length !== 1) {
    await browser.close();
    fail("exactly one DroneDream desktop WebView must be available");
  }
  return { browser, page: matching[0] };
}

function encodeIdentifier(value, label) {
  if (!new RegExp(`^${IDENTIFIER}$`).test(value || "")) fail(`${label} is invalid`);
  return encodeURIComponent(value);
}

function createP5DesktopApiAdapter(page, expectedEnginePack) {
  if (
    !PACK_ID.test(expectedEnginePack?.packId || "")
    || !GIT_COMMIT.test(expectedEnginePack?.sourceCommit || "")
  ) {
    fail("expected Engine Pack identity is invalid");
  }
  const expected = Object.freeze({
    packId: expectedEnginePack.packId,
    sourceCommit: expectedEnginePack.sourceCommit,
  });
  return Object.freeze({
    verifyEnginePack: () => verifyEnginePack(page, expected),
    getSession: () => localApi(page, "GET", "/api/v1/session"),
    async createJob({ requestPayload, idempotencyKey, requestSha256, scenarioId }) {
      encodeIdentifier(scenarioId, "scenario ID");
      if (canonicalSha256(requestPayload) !== requestSha256) {
        fail("P5 Job request payload SHA does not recompute");
      }
      await verifyEnginePack(page, expected);
      const result = await localApi(
        page,
        "POST",
        "/api/v1/jobs",
        requestPayload,
        idempotencyKey,
      );
      if (!result || !new RegExp(`^${IDENTIFIER}$`).test(result.id || "")) {
        fail("P5 Job creation response omitted a valid Job ID");
      }
      return {
        schema_id: "dronedream.physical-stability-job-create-observation/v1",
        scenario_id: scenarioId,
        observed_job_id: result.id,
        idempotency_key: idempotencyKey,
        request_sha256: requestSha256,
      };
    },
    getJob(jobId) {
      return localApi(page, "GET", `/api/v1/jobs/${encodeIdentifier(jobId, "Job ID")}`);
    },
    getTrials(jobId) {
      return localApi(
        page,
        "GET",
        `/api/v1/jobs/${encodeIdentifier(jobId, "Job ID")}/trials?page=1&page_size=100`,
      );
    },
    getTrial(trialId) {
      return localApi(page, "GET", `/api/v1/trials/${encodeIdentifier(trialId, "Trial ID")}`);
    },
    getArtifacts(jobId) {
      return localApi(
        page,
        "GET",
        `/api/v1/jobs/${encodeIdentifier(jobId, "Job ID")}/artifacts`,
      );
    },
    getReport(jobId) {
      return localApi(
        page,
        "GET",
        `/api/v1/jobs/${encodeIdentifier(jobId, "Job ID")}/report`,
      );
    },
  });
}

module.exports = {
  MAX_JSON_RESPONSE_BYTES,
  canonicalSha256,
  connectToDesktop,
  createP5DesktopApiAdapter,
  decodeJsonResponse,
  localApi,
  rejectSensitiveFields,
  validateEnginePackStatus,
  validateRoute,
};
