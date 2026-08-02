"use strict";

const crypto = require("crypto");
const fs = require("fs");
const path = require("path");
const { chromium } = require("../../../frontend/node_modules/playwright");

const EXECUTION_SUBJECT = "2d5c0e5864021ef129359b0f303bdba092bd4928";
const ENGINE_PACK_ID =
  "sha256:5ced4e533701d2416f71c7735688bf0cfb1cd4ef3f8404df74065b96a2079d09";
const ENGINE_PACK_ARCHIVE_SHA256 =
  "a7624ac1cc7b29e704782b08a6686cec4077dbc7607517c394701862d8ee4804";
const PAYLOADS_PATH =
  "C:/Users/zju20/AppData/Local/Temp/dronedream-eab2485-campaign/payloads.json";
const RECEIPT_PATH = path.join(__dirname, "local-runtime-smoke-recheck-receipt.json");

function atomicWriteJson(target, value) {
  const temporary = `${target}.${process.pid}.tmp`;
  fs.writeFileSync(temporary, `${JSON.stringify(value, null, 2)}\n`, "utf8");
  fs.renameSync(temporary, target);
}

const payloads = JSON.parse(fs.readFileSync(PAYLOADS_PATH, "utf8"));
const payload = structuredClone(payloads[0]);
if (!payload || typeof payload !== "object") {
  throw new Error("the frozen calm-hover payload is unavailable");
}
payload.display_name = "Pre-final runtime smoke - calm vertical takeoff and hover";
payload.optimizer_strategy = "heuristic";
payload.llm = null;
payload.openai = null;
payload.max_iterations = 1;
payload.max_total_trials = 2;
payload.scenario_suite.cases = payload.scenario_suite.cases.slice(0, 1);

const receipt = {
  schemaVersion: "dronedream.prefinal-runtime-smoke.v1",
  executionSubject: EXECUTION_SUBJECT,
  enginePackId: ENGINE_PACK_ID,
  enginePackArchiveSha256: ENGINE_PACK_ARCHIVE_SHA256,
  startedAt: new Date().toISOString(),
  completedAt: null,
  modelProviderCalls: 0,
  displayName: payload.display_name,
  jobId: null,
  status: "preflight",
  progress: null,
  latestError: null,
  harnessEvents: 0,
  trials: [],
};

async function main() {
  const browser = await chromium.connectOverCDP("http://127.0.0.1:9223");
  try {
    const page = browser
      .contexts()
      .flatMap((context) => context.pages())
      .find((candidate) => candidate.url().startsWith("http://tauri.localhost"));
    if (!page) throw new Error("desktop WebView is unavailable");

    async function api(method, apiPath, body = null, idempotencyKey = null) {
      const response = await page.evaluate(
        async ({ methodValue, pathValue, bodyValue, idempotencyValue }) => {
          const storageKey = Object.keys(sessionStorage).find(
            (name) => name.startsWith("sb-") && name.endsWith("-auth-token"),
          );
          const session = storageKey
            ? JSON.parse(sessionStorage.getItem(storageKey) || "null")
            : null;
          const result = await window.__TAURI_INTERNALS__.invoke("desktop_api_request", {
            request: {
              method: methodValue,
              path: pathValue,
              body: bodyValue === null ? null : JSON.stringify(bodyValue),
              accessToken: session?.access_token || null,
              accept: "application/json",
              idempotencyKey: idempotencyValue,
            },
          });
          const binary = result.bodyBase64 ? atob(result.bodyBase64) : "";
          const bytes = Uint8Array.from(binary, (character) => character.charCodeAt(0));
          return {
            status: result.status,
            json: binary ? JSON.parse(new TextDecoder().decode(bytes)) : null,
          };
        },
        {
          methodValue: method,
          pathValue: apiPath,
          bodyValue: body,
          idempotencyValue: idempotencyKey,
        },
      );
      if (response.status < 200 || response.status >= 300) {
        throw new Error(`local API ${method} ${apiPath} returned ${response.status}`);
      }
      return response.json?.data;
    }

    const created = await api("POST", "/api/v1/jobs", payload, crypto.randomUUID());
    if (!created?.id) throw new Error("job creation response omitted the job ID");
    receipt.jobId = created.id;
    receipt.status = created.status;
    atomicWriteJson(RECEIPT_PATH, receipt);
    console.log(`[prefinal-smoke] created ${created.id}`);

    const terminal = new Set(["COMPLETED", "FAILED", "CANCELLED"]);
    const deadline = Date.now() + 40 * 60 * 1000;
    let lastProgress = "";
    let finalJob = null;
    while (Date.now() < deadline) {
      const job = await api("GET", `/api/v1/jobs/${encodeURIComponent(created.id)}`);
      finalJob = job;
      receipt.status = job.status;
      receipt.progress = job.progress;
      receipt.latestError = job.latest_error
        ? { code: job.latest_error.code, message: job.latest_error.message }
        : null;
      receipt.harnessEvents = (job.recent_events || []).filter((event) =>
        String(event.event_type || "").startsWith("harness_"),
      ).length;
      atomicWriteJson(RECEIPT_PATH, receipt);
      const progress = `${job.status}|${job.progress?.current_phase || ""}|${
        job.progress?.completed_trials || 0
      }/${job.progress?.total_trials || 0}`;
      if (progress !== lastProgress) {
        lastProgress = progress;
        console.log(`[prefinal-smoke] ${progress}`);
      }
      if (terminal.has(String(job.status).toUpperCase())) break;
      await new Promise((resolve) => setTimeout(resolve, 5000));
    }
    if (!terminal.has(String(receipt.status).toUpperCase())) {
      throw new Error("job did not reach a terminal state before the smoke timeout");
    }

    const trials = await api(
      "GET",
      `/api/v1/jobs/${encodeURIComponent(created.id)}/trials?page=1&page_size=100`,
    );
    receipt.trials = (trials || []).map((trial) => ({
      id: trial.id,
      status: trial.status,
      failureCode: trial.failure_code || null,
      metrics: trial.metrics || null,
    }));
    receipt.bestCandidateId = finalJob?.best_candidate_id || null;
    receipt.optimizationOutcome = finalJob?.optimization_outcome || null;
    if (receipt.status === "COMPLETED") {
      const report = await api(
        "GET",
        `/api/v1/jobs/${encodeURIComponent(created.id)}/report`,
      );
      receipt.report = {
        status: report.report_status || null,
        bestCandidateId: report.best_candidate_id || null,
        winnerEvidenceId: report.winner_evidence_id || null,
        winnerFreezeReceiptId: report.winner_freeze_receipt_id || null,
      };
    }
    receipt.completedAt = new Date().toISOString();
    atomicWriteJson(RECEIPT_PATH, receipt);
    console.log(
      `[prefinal-smoke] terminal=${receipt.status} trials=${receipt.trials.length} model_calls=0`,
    );
    if (receipt.status !== "COMPLETED" || receipt.report?.status !== "READY") {
      process.exitCode = 1;
    }
  } finally {
    await browser.close();
  }
}

main().catch((error) => {
  receipt.status = "failed-closed";
  receipt.latestError = { code: "SMOKE_RUNNER_ERROR", message: error.message };
  receipt.completedAt = new Date().toISOString();
  atomicWriteJson(RECEIPT_PATH, receipt);
  console.error(`[prefinal-smoke] failed closed: ${error.message}`);
  process.exitCode = 1;
});
