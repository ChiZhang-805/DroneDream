"use strict";

const crypto = require("crypto");
const fs = require("fs");
const path = require("path");

const REPOSITORY_ROOT = path.resolve(__dirname, "../..");
const REGISTRY_PATH = path.join(
  REPOSITORY_ROOT,
  "backend/evaluation_artifacts/prefinal-realistic-scenario-registry-v1.json",
);
const REGISTRY_MANIFEST_PATH = path.join(
  REPOSITORY_ROOT,
  "backend/evaluation_artifacts/prefinal-realistic-scenario-registry-v1.manifest.json",
);
const EVIDENCE_ROOT = path.join(REPOSITORY_ROOT, "artifacts/test-runs");
const TERMINAL_STATUSES = new Set(["COMPLETED", "FAILED", "CANCELLED"]);

function fail(message) {
  throw new Error(message);
}

function isLowerHex(value, length) {
  return typeof value === "string" && new RegExp(`^[0-9a-f]{${length}}$`).test(value);
}

function isPackId(value) {
  return typeof value === "string" && /^sha256:[0-9a-f]{64}$/.test(value);
}

function sha256(value) {
  return crypto.createHash("sha256").update(value).digest("hex");
}

function canonicalJson(value) {
  if (Array.isArray(value)) return `[${value.map(canonicalJson).join(",")}]`;
  if (value && typeof value === "object") {
    return `{${Object.keys(value)
      .sort()
      .map((key) => `${JSON.stringify(key)}:${canonicalJson(value[key])}`)
      .join(",")}}`;
  }
  return JSON.stringify(value);
}

function fileSha256(filePath) {
  return sha256(fs.readFileSync(filePath));
}

function atomicWriteJson(target, value, initializedPaths) {
  const temporary = `${target}.${process.pid}.${crypto.randomUUID()}.tmp`;
  if (!initializedPaths.has(target) && fs.existsSync(target)) {
    fail(`refusing to overwrite existing evidence: ${target}`);
  }
  fs.writeFileSync(temporary, `${JSON.stringify(value, null, 2)}\n`, {
    encoding: "utf8",
    flag: "wx",
  });
  fs.renameSync(temporary, target);
  initializedPaths.add(target);
}

function parseArguments(argv) {
  const options = {
    problems: [],
    cdpUrl: "http://127.0.0.1:9223",
    timeoutSeconds: 45 * 60,
  };
  for (let index = 0; index < argv.length; index += 1) {
    const name = argv[index];
    const value = argv[index + 1];
    if (!name.startsWith("--") || value === undefined || value.startsWith("--")) {
      fail(`invalid or missing value for argument ${name}`);
    }
    index += 1;
    if (name === "--problem") options.problems.push(value);
    else if (name === "--output-directory") options.outputDirectory = value;
    else if (name === "--expected-source") options.expectedSource = value;
    else if (name === "--expected-pack-id") options.expectedPackId = value;
    else if (name === "--repository-evidence-head") options.repositoryEvidenceHead = value;
    else if (name === "--desktop-source") options.desktopSource = value;
    else if (name === "--desktop-sha256") options.desktopSha256 = value;
    else if (name === "--cdp-url") options.cdpUrl = value;
    else if (name === "--timeout-seconds") options.timeoutSeconds = Number(value);
    else fail(`unknown argument ${name}`);
  }
  if (options.problems.length === 0) fail("at least one --problem is required");
  if (new Set(options.problems).size !== options.problems.length) {
    fail("problem IDs must not be duplicated");
  }
  if (!options.outputDirectory) fail("--output-directory is required");
  if (!isLowerHex(options.expectedSource, 40)) fail("--expected-source must be a full Git SHA");
  if (!isPackId(options.expectedPackId)) fail("--expected-pack-id must be a SHA-256 pack ID");
  if (!isLowerHex(options.repositoryEvidenceHead, 40)) {
    fail("--repository-evidence-head must be a full Git SHA");
  }
  if (!isLowerHex(options.desktopSource, 40)) fail("--desktop-source must be a full Git SHA");
  if (!isLowerHex(options.desktopSha256, 64)) {
    fail("--desktop-sha256 must be a SHA-256 digest");
  }
  if (!/^http:\/\/127\.0\.0\.1:\d+$/.test(options.cdpUrl)) {
    fail("--cdp-url must be an HTTP loopback URL");
  }
  if (!Number.isInteger(options.timeoutSeconds) || options.timeoutSeconds < 60) {
    fail("--timeout-seconds must be an integer of at least 60");
  }
  return options;
}

function resolveEvidenceDirectory(value) {
  const target = path.resolve(REPOSITORY_ROOT, value);
  const relative = path.relative(EVIDENCE_ROOT, target);
  if (!relative || relative.startsWith("..") || path.isAbsolute(relative)) {
    fail("output directory must be a new child of artifacts/test-runs");
  }
  return target;
}

function selectProblems(registry, requestedIds) {
  const frozenRegistry = JSON.parse(fs.readFileSync(REGISTRY_PATH, "utf8"));
  const manifest = JSON.parse(fs.readFileSync(REGISTRY_MANIFEST_PATH, "utf8"));
  if (
    registry.schema_version !== "dronedream.prefinal-scenario-registry/v1"
    || registry.status !== "design_only_not_execution_approved"
    || registry.report_eligible !== false
    || registry.calibration_protocol?.uses_provider !== false
    || registry.calibration_protocol?.uses_optimizer !== false
  ) {
    fail("scenario registry is not a baseline-only pre-final calibration contract");
  }
  const registryFile = manifest.files?.find(
    (record) => record.path === path.basename(REGISTRY_PATH),
  );
  const unsignedManifest = { ...manifest };
  delete unsignedManifest.manifest_sha256;
  if (
    manifest.schema_version !== "dronedream.prefinal-scenario-registry-manifest/v1"
    || manifest.status !== registry.status
    || manifest.report_eligible !== false
    || manifest.registry_sha256 !== registry.registry_sha256
    || manifest.manifest_sha256 !== sha256(canonicalJson(unsignedManifest))
    || registryFile?.bytes !== fs.statSync(REGISTRY_PATH).size
    || registryFile?.sha256 !== fileSha256(REGISTRY_PATH)
    || canonicalJson(registry) !== canonicalJson(frozenRegistry)
  ) {
    fail("scenario registry hash verification failed");
  }
  const byId = new Map(registry.problems.map((problem) => [problem.problem_id, problem]));
  return requestedIds.map((problemId) => {
    const problem = byId.get(problemId);
    if (!problem) fail(`unknown pre-final problem ID: ${problemId}`);
    return problem;
  });
}

function prepareBaselinePayload(problem, sourceShortSha) {
  const payload = structuredClone(problem.job_template);
  const trialCount = (payload.scenario_suite?.cases || [])
    .filter((scenarioCase) => scenarioCase.enabled !== false)
    .reduce((total, scenarioCase) => total + (scenarioCase.seeds || []).length, 0);
  if (trialCount !== 4) fail(`${problem.problem_id} must contain exactly four baseline runs`);
  payload.display_name = `Physical calibration ${sourceShortSha} ${problem.problem_id}`;
  payload.optimizer_strategy = "none";
  payload.max_iterations = 1;
  payload.max_total_trials = trialCount;
  payload.provider_turn_cap = 0;
  payload.continue_exploration_after_qualified = false;
  payload.exploration_budget = null;
  payload.llm = null;
  payload.openai = null;
  return payload;
}

function boundedError(error) {
  const message = error instanceof Error ? error.message : String(error);
  return message.replace(/[\u0000-\u001f\u007f]/g, " ").slice(0, 1600);
}

async function connectToDesktop(cdpUrl) {
  const { chromium } = require("../../frontend/node_modules/playwright");
  const browser = await chromium.connectOverCDP(cdpUrl);
  const page = browser
    .contexts()
    .flatMap((context) => context.pages())
    .find((candidate) => candidate.url().startsWith("http://tauri.localhost"));
  if (!page) {
    await browser.close();
    fail("desktop WebView is unavailable");
  }
  return { browser, page };
}

async function invokeDesktop(page, command) {
  return page.evaluate(
    (commandName) => window.__TAURI_INTERNALS__.invoke(commandName),
    command,
  );
}

async function localApi(page, method, apiPath, body = null, idempotencyKey = null) {
  const response = await page.evaluate(
    async ({ methodValue, pathValue, bodyValue, idempotencyValue }) => {
      const storageKey = Object.keys(sessionStorage).find(
        (name) => name.startsWith("sb-") && name.endsWith("-auth-token"),
      );
      const session = storageKey
        ? JSON.parse(sessionStorage.getItem(storageKey) || "null")
        : null;
      if (!session?.access_token) return { status: 0, json: null, missingSession: true };
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
      const binary = result.bodyBase64 ? atob(result.bodyBase64) : "";
      const bytes = Uint8Array.from(binary, (character) => character.charCodeAt(0));
      return {
        status: result.status,
        json: binary ? JSON.parse(new TextDecoder().decode(bytes)) : null,
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
  if (response.missingSession) fail("desktop WebView has no authenticated account session");
  if (response.status < 200 || response.status >= 300) {
    fail(`local API ${method} ${apiPath} returned ${response.status}`);
  }
  return response.json?.data;
}

async function collectTerminalEvidence(page, job) {
  const trials = await localApi(
    page,
    "GET",
    `/api/v1/jobs/${encodeURIComponent(job.id)}/trials?page=1&page_size=100`,
  );
  const trialEvidence = [];
  for (const trial of trials || []) {
    const detail = await localApi(page, "GET", `/api/v1/trials/${encodeURIComponent(trial.id)}`);
    trialEvidence.push({
      id: trial.id,
      candidateId: trial.candidate_id || detail?.candidate_id || null,
      candidateIsBaseline: detail?.candidate_is_baseline ?? null,
      status: trial.status,
      failureCode: trial.failure_code || detail?.failure_code || null,
      failureReason: trial.failure_reason || detail?.failure_reason || null,
      simulatorBackend: detail?.simulator_backend || null,
      attempts: detail?.attempt_count ?? null,
      metrics: detail?.metrics || null,
    });
  }
  const artifacts = await localApi(
    page,
    "GET",
    `/api/v1/jobs/${encodeURIComponent(job.id)}/artifacts`,
  );
  let report = null;
  if (job.status === "COMPLETED") {
    const value = await localApi(page, "GET", `/api/v1/jobs/${encodeURIComponent(job.id)}/report`);
    report = {
      status: value.report_status || null,
      bestCandidateId: value.best_candidate_id || null,
      firstQualifiedCandidateId: job.first_qualified_candidate_id || null,
      firstQualifiedFreezeReceiptId: job.first_qualified_freeze_receipt_id || null,
      firstQualifiedAt: job.first_qualified_at || null,
      winnerEvidenceId: value.winner_evidence_id || null,
      winnerFreezeReceiptId: value.winner_freeze_receipt_id || null,
    };
  }
  const events = job.recent_events || [];
  const providerEvents = events.filter((event) =>
    /provider|cognitive_turn/i.test(String(event.event_type || "")),
  );
  return {
    trials: trialEvidence,
    artifacts: (artifacts || []).map((artifact) => ({
      id: artifact.id,
      ownerType: artifact.owner_type,
      ownerId: artifact.owner_id,
      artifactType: artifact.artifact_type,
      displayName: artifact.display_name || null,
      fileSizeBytes: artifact.file_size_bytes ?? null,
    })),
    report,
    providerEventsObserved: providerEvents.length,
  };
}

async function runProblem(page, problem, options, outputDirectory, initializedPaths) {
  const payload = prepareBaselinePayload(problem, options.expectedSource.slice(0, 7));
  const receiptPath = path.join(outputDirectory, `${problem.problem_id}-receipt.json`);
  const receipt = {
    schemaVersion: "dronedream.prefinal-physical-calibration-receipt/v1",
    executionSource: options.expectedSource,
    repositoryEvidenceHead: options.repositoryEvidenceHead,
    problemId: problem.problem_id,
    registryOrdinal: problem.registry_ordinal,
    difficulty: problem.difficulty,
    startedAt: new Date().toISOString(),
    completedAt: null,
    providerCallsAttempted: 0,
    providerCallsSucceeded: 0,
    providerRetries: 0,
    jobId: null,
    status: "preflight",
    optimizationOutcome: null,
    progress: null,
    latestError: null,
    trials: [],
    artifacts: [],
    report: null,
  };
  atomicWriteJson(receiptPath, receipt, initializedPaths);
  const created = await localApi(page, "POST", "/api/v1/jobs", payload, crypto.randomUUID());
  if (!created?.id) fail("job creation response omitted the job ID");
  receipt.jobId = created.id;
  receipt.status = created.status;
  atomicWriteJson(receiptPath, receipt, initializedPaths);
  console.log(`[physical-calibration] ${problem.problem_id} created ${created.id}`);

  const deadline = Date.now() + options.timeoutSeconds * 1000;
  let job = created;
  let lastProgress = "";
  while (Date.now() < deadline) {
    job = await localApi(page, "GET", `/api/v1/jobs/${encodeURIComponent(created.id)}`);
    receipt.status = job.status;
    receipt.progress = job.progress;
    receipt.optimizationOutcome = job.optimization_outcome || null;
    receipt.latestError = job.latest_error
      ? { code: job.latest_error.code, message: job.latest_error.message }
      : null;
    atomicWriteJson(receiptPath, receipt, initializedPaths);
    const progress = `${job.status}|${job.progress?.current_phase || ""}|${
      job.progress?.completed_trials || 0
    }/${job.progress?.total_trials || 0}`;
    if (progress !== lastProgress) {
      lastProgress = progress;
      console.log(`[physical-calibration] ${problem.problem_id} ${progress}`);
    }
    if (TERMINAL_STATUSES.has(String(job.status).toUpperCase())) break;
    await new Promise((resolve) => setTimeout(resolve, 5000));
  }
  if (!TERMINAL_STATUSES.has(String(receipt.status).toUpperCase())) {
    fail(`${problem.problem_id} did not reach a terminal state before timeout`);
  }
  Object.assign(receipt, await collectTerminalEvidence(page, job));
  if (receipt.providerEventsObserved !== 0) {
    fail(`${problem.problem_id} unexpectedly recorded provider/cognitive events`);
  }
  receipt.completedAt = new Date().toISOString();
  atomicWriteJson(receiptPath, receipt, initializedPaths);
  return { receiptPath, receipt };
}

function buildCampaignManifest(options, registry, enginePack, accountHash, results) {
  const receipts = results.map(({ receiptPath, receipt }) => ({
    file: path.basename(receiptPath),
    bytes: fs.statSync(receiptPath).size,
    sha256: fileSha256(receiptPath),
    problemId: receipt.problemId,
    difficulty: receipt.difficulty,
    jobId: receipt.jobId,
    status: receipt.status,
    optimizationOutcome: receipt.optimizationOutcome,
    trials: receipt.trials.length,
    completedTrials: receipt.trials.filter((trial) => trial.status === "COMPLETED").length,
    failedTrials: receipt.trials.filter((trial) => trial.status === "FAILED").length,
    passingTrials: receipt.trials.filter((trial) => trial.metrics?.pass_flag === true).length,
  }));
  return {
    schemaVersion: "dronedream.prefinal-physical-calibration-manifest/v1",
    executionSource: options.expectedSource,
    repositoryEvidenceHead: options.repositoryEvidenceHead,
    desktop: {
      sourceCommit: options.desktopSource,
      binarySha256: options.desktopSha256,
    },
    enginePack: {
      expectedPackId: options.expectedPackId,
      observed: enginePack,
    },
    runtime: { expectedProviderCalls: 0, providerRetries: 0 },
    accountSubjectSha256: accountHash,
    registry: {
      file: path.relative(REPOSITORY_ROOT, REGISTRY_PATH).replaceAll("\\", "/"),
      fileSha256: fileSha256(REGISTRY_PATH),
      registrySha256: registry.registry_sha256,
      version: registry.registry_version,
      claimBoundary: registry.claim_boundary,
    },
    receipts,
    summary: {
      jobs: receipts.length,
      completedJobs: receipts.filter((item) => item.status === "COMPLETED").length,
      failedJobs: receipts.filter((item) => item.status === "FAILED").length,
      trials: receipts.reduce((sum, item) => sum + item.trials, 0),
      completedTrials: receipts.reduce((sum, item) => sum + item.completedTrials, 0),
      failedTrials: receipts.reduce((sum, item) => sum + item.failedTrials, 0),
      passingTrials: receipts.reduce((sum, item) => sum + item.passingTrials, 0),
      providerCallsAttempted: 0,
      providerCallsSucceeded: 0,
    },
    claimBoundary:
      "Baseline-only PX4/Gazebo physical calibration. No model, optimizer comparison, algorithm superiority, real-aircraft safety, or report-eligible claim.",
  };
}

async function main(argv = process.argv.slice(2)) {
  const options = parseArguments(argv);
  const outputDirectory = resolveEvidenceDirectory(options.outputDirectory);
  if (fs.existsSync(outputDirectory)) fail(`output directory already exists: ${outputDirectory}`);
  fs.mkdirSync(outputDirectory);
  const initializedPaths = new Set();
  const registry = JSON.parse(fs.readFileSync(REGISTRY_PATH, "utf8"));
  const problems = selectProblems(registry, options.problems);
  const campaignPath = path.join(outputDirectory, "campaign-manifest.json");
  const { browser, page } = await connectToDesktop(options.cdpUrl);
  const results = [];
  try {
    const enginePack = await invokeDesktop(page, "get_engine_pack_status");
    if (
      enginePack.installedPackId !== options.expectedPackId
      || enginePack.installedSourceCommit !== options.expectedSource
    ) {
      fail("desktop bridge observed an unexpected active Engine Pack identity");
    }
    const session = await localApi(page, "GET", "/api/v1/session");
    if (session?.status !== "ready" || typeof session.user_id !== "string") {
      fail("local API did not verify the authenticated desktop session");
    }
    const accountHash = sha256(session.user_id);
    for (const problem of problems) {
      try {
        results.push(
          await runProblem(page, problem, options, outputDirectory, initializedPaths),
        );
      } catch (error) {
        const failurePath = path.join(outputDirectory, "runner-failure.json");
        atomicWriteJson(
          failurePath,
          {
            schemaVersion: "dronedream.prefinal-physical-calibration-runner-failure/v1",
            executionSource: options.expectedSource,
            failedProblemId: problem.problem_id,
            failedAt: new Date().toISOString(),
            error: boundedError(error),
            providerCallsAttempted: 0,
          },
          initializedPaths,
        );
        throw error;
      }
    }
    const campaign = buildCampaignManifest(options, registry, enginePack, accountHash, results);
    atomicWriteJson(campaignPath, campaign, initializedPaths);
    console.log(`[physical-calibration] completed ${results.length} baseline-only jobs`);
    if (campaign.summary.completedJobs !== campaign.summary.jobs) process.exitCode = 1;
  } finally {
    await browser.close();
  }
}

if (require.main === module) {
  main().catch((error) => {
    console.error(`[physical-calibration] failed closed: ${boundedError(error)}`);
    process.exitCode = 1;
  });
}

module.exports = {
  buildCampaignManifest,
  parseArguments,
  prepareBaselinePayload,
  resolveEvidenceDirectory,
  selectProblems,
};
