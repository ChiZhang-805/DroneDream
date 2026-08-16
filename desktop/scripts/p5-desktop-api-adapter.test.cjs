"use strict";

const assert = require("node:assert/strict");
const crypto = require("node:crypto");
const test = require("node:test");

const {
  connectToDesktop,
  createP5DesktopApiAdapter,
  decodeJsonResponse,
  localApi,
  rejectSensitiveFields,
  validateEnginePackStatus,
  validateRoute,
} = require("./p5-desktop-api-adapter.cjs");

const packId = `sha256:${"a".repeat(64)}`;
const sourceCommit = "b".repeat(40);
const requestPayload = {
  altitude_m: 3,
  display_name: "P5 单元",
  llm: null,
  openai: null,
  provider_request_cap: 0,
  provider_turn_cap: 0,
};
const requestCanonicalJson =
  '{"altitude_m":3.0,"display_name":"P5 单元","llm":null,"openai":null,"provider_request_cap":0,"provider_turn_cap":0}';
const requestSha256 = crypto
  .createHash("sha256")
  .update(requestCanonicalJson, "utf8")
  .digest("hex");
const mutationRequestSha256 = crypto
  .createHash("sha256")
  .update(`{"operation":"jobs.create","payload":${requestCanonicalJson}}`, "utf8")
  .digest("hex");
const idempotencyKey = "12345678-1234-5abc-8def-1234567890ab";
const idempotencyKeySha256 = crypto
  .createHash("sha256")
  .update(idempotencyKey, "ascii")
  .digest("hex");

function jsonResponse(data, overrides = {}) {
  return {
    status: 200,
    contentType: "application/json; charset=utf-8",
    bodyBase64: Buffer.from(JSON.stringify({ data }), "utf8").toString("base64"),
    missingSession: false,
    ...overrides,
  };
}

function fakePage(response) {
  const calls = [];
  return {
    calls,
    async evaluate(_callback, argument) {
      calls.push(argument);
      return typeof response === "function" ? response(argument) : response;
    },
  };
}

test("P5 route allowlist rejects arbitrary paths, bodies, and idempotency drift", () => {
  assert.doesNotThrow(() => validateRoute("GET", "/api/v1/session", null, null));
  assert.doesNotThrow(() =>
    validateRoute("POST", "/api/v1/jobs", requestPayload, idempotencyKey),
  );
  assert.throws(() => validateRoute("GET", "https://example.com", null, null), /allowlisted/);
  assert.throws(() => validateRoute("DELETE", "/api/v1/jobs/job-1", null, null), /allowlisted/);
  assert.throws(
    () => validateRoute("POST", "/api/v1/jobs", requestPayload, "random-key"),
    /frozen idempotency/,
  );
  assert.throws(
    () => validateRoute("GET", "/api/v1/jobs/job-1", { mutate: true }, null),
    /cannot carry/,
  );
});

test("local API passes only the bounded request contract and returns decoded data", async () => {
  const page = fakePage(jsonResponse({ id: "job-p5-unit" }));
  const result = await localApi(
    page,
    "POST",
    "/api/v1/jobs",
    requestPayload,
    idempotencyKey,
  );

  assert.deepEqual(result, { id: "job-p5-unit" });
  assert.deepEqual(page.calls, [
    {
      methodValue: "POST",
      pathValue: "/api/v1/jobs",
      bodyValue: requestPayload,
      idempotencyValue: idempotencyKey,
    },
  ]);
  assert.equal(JSON.stringify(page.calls).includes("access_token"), false);
});

test("adapter creates one source-bound observation and exposes read-only evidence routes", async () => {
  const page = fakePage((argument) => {
    if (argument === undefined) {
      return {
        supported: true,
        updateRequired: false,
        installedPackId: packId,
        installedSourceCommit: sourceCommit,
      };
    }
    if (argument?.methodValue === "POST") return jsonResponse({ id: "job-p5-unit" });
    if (argument?.pathValue?.includes("/physical-stability-dispatches/")) {
      return jsonResponse({
        schema_id: "dronedream.physical-stability-dispatch-inspection/v1",
        state: "completed",
        idempotency_key_sha256: idempotencyKeySha256,
        mutation_request_sha256: mutationRequestSha256,
        observed_job_id: "job-p5-unit",
      });
    }
    return jsonResponse([]);
  });
  const adapter = createP5DesktopApiAdapter(page, { packId, sourceCommit });
  const observation = await adapter.createJob({
    requestPayload,
    requestCanonicalJson,
    idempotencyKey,
    requestSha256,
    scenarioId: "hover-mild-crosswind",
  });
  assert.deepEqual(observation, {
    schema_id: "dronedream.physical-stability-job-create-observation/v1",
    scenario_id: "hover-mild-crosswind",
    observed_job_id: "job-p5-unit",
    idempotency_key: idempotencyKey,
    request_sha256: requestSha256,
  });
  const inspected = await adapter.inspectJobCreation({
    requestPayload,
    requestCanonicalJson,
    idempotencyKey,
    requestSha256,
    scenarioId: "hover-mild-crosswind",
  });
  assert.deepEqual(inspected, {
    state: "completed",
    observation,
  });
  await adapter.getJob("job-p5-unit");
  await adapter.getTrials("job-p5-unit");
  await adapter.getTrial("trial-p5-unit");
  await adapter.getArtifacts("job-p5-unit");
  await adapter.getReport("job-p5-unit");
  await adapter.getPhysicalStabilityEvidence("job-p5-unit");
  assert.deepEqual(
    page.calls.filter((call) => call?.pathValue).slice(2).map((call) => call.pathValue),
    [
      "/api/v1/jobs/job-p5-unit",
      "/api/v1/jobs/job-p5-unit/trials?page=1&page_size=100",
      "/api/v1/trials/trial-p5-unit",
      "/api/v1/jobs/job-p5-unit/artifacts",
      "/api/v1/jobs/job-p5-unit/report",
      "/api/v1/jobs/job-p5-unit/physical-stability-evidence",
    ],
  );
  await assert.rejects(
    adapter.createJob({
      requestPayload,
      requestCanonicalJson,
      idempotencyKey,
      requestSha256: "0".repeat(64),
      scenarioId: "hover-mild-crosswind",
    }),
    /SHA does not recompute/,
  );
});

test("dispatch inspection retains unresolved states and rejects a mismatched key hash", async () => {
  const unresolvedPage = fakePage(
    jsonResponse({
      schema_id: "dronedream.physical-stability-dispatch-inspection/v1",
      state: "in_progress",
      idempotency_key_sha256: idempotencyKeySha256,
      mutation_request_sha256: mutationRequestSha256,
      observed_job_id: null,
    }),
  );
  const unresolved = await createP5DesktopApiAdapter(unresolvedPage, {
    packId,
    sourceCommit,
  }).inspectJobCreation({
    requestPayload,
    requestCanonicalJson,
    idempotencyKey,
    requestSha256,
    scenarioId: "hover-mild-crosswind",
  });
  assert.deepEqual(unresolved, { state: "in_progress" });

  const driftedPage = fakePage(
    jsonResponse({
      schema_id: "dronedream.physical-stability-dispatch-inspection/v1",
      state: "completed",
      idempotency_key_sha256: "0".repeat(64),
      mutation_request_sha256: mutationRequestSha256,
      observed_job_id: "job-p5-unit",
    }),
  );
  await assert.rejects(
    createP5DesktopApiAdapter(driftedPage, { packId, sourceCommit }).inspectJobCreation({
      requestPayload,
      requestCanonicalJson,
      idempotencyKey,
      requestSha256,
      scenarioId: "hover-mild-crosswind",
    }),
    /inspection response is invalid/,
  );
});

test("response decoding fails closed on session, status, content, base64, and secrets", async () => {
  await assert.rejects(
    localApi(fakePage({ missingSession: true }), "GET", "/api/v1/session"),
    /no authenticated account session/,
  );
  assert.throws(
    () => decodeJsonResponse(jsonResponse({}, { status: 500 }), "GET", "/api/v1/session"),
    /returned 500/,
  );
  assert.throws(
    () =>
      decodeJsonResponse(
        jsonResponse({}, { contentType: "text/html" }),
        "GET",
        "/api/v1/session",
      ),
    /not JSON/,
  );
  assert.throws(
    () =>
      decodeJsonResponse(
        jsonResponse({}, { bodyBase64: "not-base64" }),
        "GET",
        "/api/v1/session",
      ),
    /base64/,
  );
  assert.throws(
    () => decodeJsonResponse(jsonResponse({ api_key: "forbidden" }), "GET", "/api/v1/session"),
    /sensitive field/,
  );
  assert.throws(
    () =>
      decodeJsonResponse(
        jsonResponse({}, { bodyBase64: Buffer.from([0xff]).toString("base64") }),
        "GET",
        "/api/v1/session",
      ),
    /valid UTF-8 JSON/,
  );
  assert.throws(() => rejectSensitiveFields({ nested: { password: "forbidden" } }), /sensitive/);
});

test("Engine Pack identity is exact and the desktop command surface is not caller-controlled", async () => {
  const status = {
    supported: true,
    updateRequired: false,
    installedPackId: packId,
    installedSourceCommit: sourceCommit,
  };
  assert.deepEqual(validateEnginePackStatus(status, { packId, sourceCommit }), {
    installedPackId: packId,
    installedSourceCommit: sourceCommit,
  });
  assert.throws(
    () => validateEnginePackStatus({ ...status, updateRequired: true }, { packId, sourceCommit }),
    /does not match/,
  );
  assert.throws(
    () =>
      validateEnginePackStatus(status, {
        packId: `sha256:${"f".repeat(64)}`,
        sourceCommit,
      }),
    /does not match/,
  );
  const page = fakePage(status);
  const adapter = createP5DesktopApiAdapter(page, { packId, sourceCommit });
  assert.deepEqual(await adapter.verifyEnginePack(), {
    installedPackId: packId,
    installedSourceCommit: sourceCommit,
  });
  assert.deepEqual(page.calls, [undefined]);
});

test("desktop connector rejects non-loopback endpoints before loading Playwright", async () => {
  await assert.rejects(connectToDesktop("https://desktop.example.com:9223"), /loopback/);
});
