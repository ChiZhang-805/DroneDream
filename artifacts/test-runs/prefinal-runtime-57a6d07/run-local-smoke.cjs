"use strict";

const crypto = require("crypto");
const fs = require("fs");
const path = require("path");
const { chromium } = require("../../../frontend/node_modules/playwright");

const EXECUTION_SUBJECT = "06fc17fc0e42e9521f6cc85aa4435e39944d001d";
const ENGINE_PACK_ID =
  "sha256:3306e99bd31907a4efaed05988d766b55629ab7c9e35eb1df0906a522d70d25f";
const ENGINE_PACK_ARCHIVE_SHA256 =
  "ca7e371019deb875b5c7700ca268971700c69a5123e01c3f7d4cb9d00f107535";
const PAYLOADS_PATH =
  "C:/Users/zju20/AppData/Local/Temp/dronedream-eab2485-campaign/payloads.json";
const PAYLOAD_INDEX = Number(process.env.OFFLINE_PAYLOAD_INDEX || "0");
const SCENARIO_VARIANT = process.env.OFFLINE_SCENARIO_VARIANT || "original";
if (!Number.isInteger(PAYLOAD_INDEX) || PAYLOAD_INDEX < 0 || PAYLOAD_INDEX > 7) {
  throw new Error("OFFLINE_PAYLOAD_INDEX must be an integer from 0 through 7");
}
if (
  ![
    "original",
    "flyable-non-gps",
    "flyable-contract-aligned",
    "safe-high-preset",
  ].includes(SCENARIO_VARIANT)
) {
  throw new Error(
    "OFFLINE_SCENARIO_VARIANT is not one of the supported evidence variants",
  );
}
const IS_FLYABLE_VARIANT = SCENARIO_VARIANT.startsWith("flyable-");
if (IS_FLYABLE_VARIANT && ![1, 4, 6, 7].includes(PAYLOAD_INDEX)) {
  throw new Error(
    "flyable variants are only defined for payload indices 1, 4, 6, and 7",
  );
}
if (SCENARIO_VARIANT === "flyable-contract-aligned" && PAYLOAD_INDEX !== 7) {
  throw new Error("the flyable-contract-aligned variant is only defined for payload index 7");
}
if (SCENARIO_VARIANT === "safe-high-preset" && PAYLOAD_INDEX !== 4) {
  throw new Error("the safe-high-preset variant is only defined for payload index 4");
}
const RECEIPT_VARIANT_SUFFIX =
  SCENARIO_VARIANT === "original" ? "" : `-${SCENARIO_VARIANT}`;
const RECEIPT_PATH = path.join(
  __dirname,
  `matrix-${String(PAYLOAD_INDEX + 1).padStart(2, "0")}-${EXECUTION_SUBJECT.slice(0, 7)}${RECEIPT_VARIANT_SUFFIX}-receipt.json`,
);

function atomicWriteJson(target, value) {
  const temporary = `${target}.${process.pid}.tmp`;
  fs.writeFileSync(temporary, `${JSON.stringify(value, null, 2)}\n`, "utf8");
  fs.renameSync(temporary, target);
}

const payloads = JSON.parse(fs.readFileSync(PAYLOADS_PATH, "utf8"));
const payload = structuredClone(payloads[PAYLOAD_INDEX]);
if (!payload || typeof payload !== "object") {
  throw new Error(`the frozen payload at index ${PAYLOAD_INDEX} is unavailable`);
}
let campaignAdjustment = null;
if (IS_FLYABLE_VARIANT) {
  const requestedGpsNoiseM =
    payload.advanced_scenario_config?.sensor_degradation?.gps_noise_m;
  payload.sensor_noise_level = "medium";
  if (payload.advanced_scenario_config?.sensor_degradation) {
    payload.advanced_scenario_config.sensor_degradation.gps_noise_m = 0;
  }
  for (const scenarioCase of payload.scenario_suite?.cases || []) {
    if (!scenarioCase.config || typeof scenarioCase.config !== "object") continue;
    scenarioCase.config.sensor_noise_level = "medium";
    if (scenarioCase.scenario_type === "noise_perturbed") {
      scenarioCase.scenario_type = "nominal";
    }
    if (scenarioCase.config.advanced_scenario_config?.sensor_degradation) {
      scenarioCase.config.advanced_scenario_config.sensor_degradation.gps_noise_m = 0;
    }
  }
  campaignAdjustment = {
    id: "flyable_non_gps_v1",
    requestedGpsNoiseM,
    appliedGpsNoiseM: 0,
    sensorNoisePreset: "medium",
    reason:
      "Continuous pre-arm GPS noise triggered the normal PX4 horizontal-position-drift gate; this variant retains explicit barometer, IMU, dropout, wind, battery, and payload effects while keeping GNSS nominal.",
  };
}
if (SCENARIO_VARIANT === "flyable-contract-aligned") {
  const wind = payload.wind || {};
  const northMps = Number(wind.north || 0) - Number(wind.south || 0);
  const eastMps = Number(wind.east || 0) - Number(wind.west || 0);
  const alignedDirectionDeg =
    ((Math.atan2(eastMps, northMps) * 180) / Math.PI + 360) % 360;
  const originalGustDirectionDeg =
    payload.advanced_scenario_config?.wind_gusts?.direction_deg;
  if (payload.advanced_scenario_config?.wind_gusts) {
    payload.advanced_scenario_config.wind_gusts.direction_deg = alignedDirectionDeg;
  }
  for (const scenarioCase of payload.scenario_suite?.cases || []) {
    if (scenarioCase.config?.advanced_scenario_config?.wind_gusts) {
      scenarioCase.config.advanced_scenario_config.wind_gusts.direction_deg =
        alignedDirectionDeg;
    }
  }
  campaignAdjustment.originalGustDirectionDeg = originalGustDirectionDeg;
  campaignAdjustment.appliedGustDirectionDeg = alignedDirectionDeg;
  campaignAdjustment.windContractReason =
    "Gazebo WindEffects can represent simultaneous steady wind and sinusoidal gusts exactly only when their horizontal directions are aligned.";
}
if (SCENARIO_VARIANT === "safe-high-preset") {
  const requestedGpsNoiseM =
    payload.advanced_scenario_config?.sensor_degradation?.gps_noise_m;
  if (payload.advanced_scenario_config?.sensor_degradation) {
    payload.advanced_scenario_config.sensor_degradation.gps_noise_m = 0;
  }
  for (const scenarioCase of payload.scenario_suite?.cases || []) {
    if (scenarioCase.config?.advanced_scenario_config?.sensor_degradation) {
      scenarioCase.config.advanced_scenario_config.sensor_degradation.gps_noise_m = 0;
    }
  }
  campaignAdjustment = {
    id: "safe_high_sensor_preset_v1",
    requestedGpsNoiseM,
    appliedGpsNoiseM: 0,
    sensorNoisePreset: payload.sensor_noise_level,
    reason:
      "Validates that the built-in high sensor preset keeps GNSS nominal while retaining its high barometer and IMU profile plus explicit dropout.",
  };
}
payload.display_name = `Pre-final matrix - ${payload.display_name}`;
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
  payloadIndex: PAYLOAD_INDEX,
  scenarioVariant: SCENARIO_VARIANT,
  campaignAdjustment,
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
        const boundedBody = JSON.stringify(response.json ?? null).slice(0, 1600);
        throw new Error(
          `local API ${method} ${apiPath} returned ${response.status}: ${boundedBody}`,
        );
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
    receipt.trials = [];
    for (const trial of trials || []) {
      const detail = await api(
        "GET",
        `/api/v1/trials/${encodeURIComponent(trial.id)}`,
      );
      receipt.trials.push({
        id: trial.id,
        candidateId: trial.candidate_id || detail?.candidate_id || null,
        candidateLabel: detail?.candidate_label || null,
        candidateSourceType: detail?.candidate_source_type || null,
        candidateIsBaseline: detail?.candidate_is_baseline ?? null,
        candidateIsBest: detail?.candidate_is_best ?? null,
        candidateGenerationIndex: detail?.candidate_generation_index ?? null,
        status: trial.status,
        failureCode: trial.failure_code || detail?.failure_code || null,
        failureReason: trial.failure_reason || detail?.failure_reason || null,
        simulatorBackend: detail?.simulator_backend || null,
        attempts: detail?.attempt_count ?? null,
        metrics: detail?.metrics || null,
      });
    }
    const artifacts = await api(
      "GET",
      `/api/v1/jobs/${encodeURIComponent(created.id)}/artifacts`,
    );
    receipt.artifacts = (artifacts || []).map((artifact) => ({
      id: artifact.id,
      ownerType: artifact.owner_type,
      ownerId: artifact.owner_id,
      artifactType: artifact.artifact_type,
      displayName: artifact.display_name || null,
      fileSizeBytes: artifact.file_size_bytes ?? null,
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
