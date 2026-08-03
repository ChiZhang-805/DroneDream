import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { createHash } from "node:crypto";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import path from "node:path";
import process from "node:process";
import { fileURLToPath } from "node:url";

import { chromium } from "playwright";
import { createServer } from "vite";

const frontendRoot = path.resolve(fileURLToPath(new URL("..", import.meta.url)));
const repoRoot = path.resolve(frontendRoot, "..");
const args = new Map(process.argv.slice(2).map((argument) => {
  const [key, ...value] = argument.split("=");
  return [key, value.join("=") || true];
}));
const label = String(args.get("--label") || "working-tree");
const outputRoot = path.resolve(repoRoot, String(
  args.get("--output")
    || path.join(
      "frontend",
      "node_modules",
      ".cache",
      "result-honesty-layout",
      label,
    ),
));
const host = "127.0.0.1";
const port = Number(args.get("--port") || 5203);
const origin = `http://${host}:${port}`;
const cases = [
  { id: "desktop-en", locale: "en", viewport: { width: 1440, height: 1000 } },
  { id: "desktop-zh", locale: "zh-CN", viewport: { width: 1440, height: 1000 } },
  { id: "mobile-en", locale: "en", viewport: { width: 390, height: 844 } },
  { id: "mobile-zh", locale: "zh-CN", viewport: { width: 390, height: 844 } },
];

process.env.VITE_API_BASE_URL = origin;
process.env.VITE_PUBLIC_DEMO_CONSOLE = "false";

const job = {
  id: "job_no_validated_winner",
  control_version: 1,
  display_name: "No-winner evidence gate fixture",
  track_type: "circle",
  reference_track: null,
  start_point: { x: 0, y: 0 },
  altitude_m: 3,
  wind: { north: 0, east: 0, south: 0, west: 0 },
  sensor_noise_level: "medium",
  objective_profile: "robust",
  status: "COMPLETED",
  progress: {
    completed_trials: 13,
    total_trials: 13,
    current_phase: "completed",
  },
  baseline_candidate_id: "cand_baseline",
  best_candidate_id: null,
  source_job_id: null,
  latest_error: null,
  created_at: "2026-04-22T09:00:00Z",
  updated_at: "2026-04-22T09:05:00Z",
  queued_at: "2026-04-22T09:00:10Z",
  started_at: "2026-04-22T09:00:20Z",
  completed_at: "2026-04-22T09:05:00Z",
  cancelled_at: null,
  failed_at: null,
  recent_events: [],
  simulator_backend_requested: "real_cli",
  optimizer_strategy: "gpt",
  max_iterations: 20,
  trials_per_candidate: 3,
  acceptance_criteria: {
    target_rmse: 0.5,
    target_max_error: null,
    min_pass_rate: 0.8,
  },
  current_generation: 0,
  optimization_outcome: "no_usable_candidate",
  openai_model: "gpt-4.1",
};

const report = {
  job_id: job.id,
  best_candidate_id: "cand_baseline",
  summary_text: "baseline recommended",
  baseline_metrics: {
    rmse: 1.2,
    max_error: 2,
    overshoot_count: 3,
    completion_time: 9,
    score: 4.2,
  },
  optimized_metrics: {
    rmse: 0.9,
    max_error: 1.5,
    overshoot_count: 2,
    completion_time: 8,
    score: 3,
  },
  comparison: [{
    metric: "rmse",
    label: "RMSE",
    baseline: 1.2,
    optimized: 0.9,
    lower_is_better: true,
    unit: "m",
  }],
  best_parameters: { MPC_XY_P: 0.95 },
  winner_evidence_id: null,
  winner_freeze_receipt_id: null,
  report_status: "READY",
  created_at: "2026-04-22T09:05:00Z",
  updated_at: "2026-04-22T09:05:00Z",
};

const comparison = {
  items: [
    {
      job_id: "job_validated_winner",
      status: "COMPLETED",
      track_type: "circle",
      simulator_backend: "mock",
      optimizer_strategy: "heuristic",
      optimization_outcome: "success",
      baseline_metrics: { rmse: 1.2, max_error: 2.1 },
      optimized_metrics: {
        rmse: 0.9,
        max_error: 1.8,
        pass_rate: 0.9,
        mystery_signal: 1,
      },
      best_candidate_id: "cand_1",
      best_parameters: {},
      trial_count: 10,
      completed_trial_count: 10,
      failed_trial_count: 0,
      created_at: "2026-01-01",
      completed_at: "2026-01-01",
    },
    {
      job_id: "job_diagnostic_only",
      status: "COMPLETED",
      track_type: "circle",
      simulator_backend: "real_cli",
      optimizer_strategy: "gpt",
      optimization_outcome: null,
      baseline_metrics: {
        rmse: 1.5,
        max_error: 2.4,
        pass_rate: 0.5,
        mystery_signal: 0,
      },
      optimized_metrics: null,
      best_candidate_id: null,
      best_parameters: {},
      trial_count: 2,
      completed_trial_count: 1,
      failed_trial_count: 0,
      created_at: "2026-01-01",
      completed_at: null,
    },
  ],
};

function git(...gitArgs) {
  return execFileSync("git", gitArgs, { cwd: repoRoot, encoding: "utf8" }).trim();
}

async function sha256File(filePath) {
  return createHash("sha256").update(await readFile(filePath)).digest("hex");
}

async function screenshot(page, testCase, surface) {
  const target = path.join(outputRoot, `${testCase.id}-${surface}.png`);
  await page.screenshot({ path: target, fullPage: false });
  return {
    path: path.relative(repoRoot, target).replaceAll("\\", "/"),
    sha256: await sha256File(target),
  };
}

function envelope(data) {
  return JSON.stringify({ success: true, data });
}

async function geometry(page, tableSelector = null) {
  return page.evaluate((selector) => {
    const table = selector ? document.querySelector(selector) : null;
    if (selector && !(table instanceof HTMLElement)) {
      throw new Error(`Missing table container: ${selector}`);
    }
    const tableStyle = table instanceof HTMLElement ? getComputedStyle(table) : null;
    return {
      documentWidth: document.documentElement.clientWidth,
      documentScrollWidth: document.documentElement.scrollWidth,
      table: table instanceof HTMLElement ? {
        clientWidth: table.clientWidth,
        scrollWidth: table.scrollWidth,
        overflowX: tableStyle?.overflowX ?? null,
      } : null,
    };
  }, tableSelector);
}

async function installFixtureRoutes(context, apiRequests) {
  await context.route("**/api/v1/**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    apiRequests.push({ method: request.method(), path: url.pathname });
    let data;
    if (request.method() === "POST" && url.pathname.endsWith("/jobs/compare")) {
      data = comparison;
    } else if (request.method() === "GET" && url.pathname.endsWith(`/${job.id}/trials`)) {
      data = [];
    } else if (request.method() === "GET" && url.pathname.endsWith(`/${job.id}/candidates`)) {
      data = {
        items: [],
        pareto_candidate_ids: [],
        recommendations: {},
        objective_directions: {},
      };
    } else if (request.method() === "GET" && url.pathname.endsWith(`/${job.id}/report`)) {
      data = report;
    } else if (request.method() === "GET" && url.pathname.endsWith(`/${job.id}/artifacts`)) {
      data = [];
    } else if (request.method() === "GET" && url.pathname.endsWith(`/jobs/${job.id}`)) {
      data = job;
    } else {
      await route.fulfill({
        status: 405,
        contentType: "application/json",
        body: JSON.stringify({
          success: false,
          error: { code: "UNEXPECTED_FIXTURE_REQUEST", message: "Unexpected request." },
        }),
      });
      return;
    }
    await route.fulfill({ status: 200, contentType: "application/json", body: envelope(data) });
  });
}

await mkdir(outputRoot, { recursive: true });
const server = await createServer({
  configFile: path.join(frontendRoot, "vite.config.ts"),
  root: frontendRoot,
  logLevel: "error",
  server: { host, port, strictPort: true },
});
await server.listen();
const browser = await chromium.launch({ channel: "msedge", headless: true });
const results = [];
let failure = null;

try {
  for (const testCase of cases) {
    const apiRequests = [];
    const consoleErrors = [];
    const pageErrors = [];
    const context = await browser.newContext({ viewport: testCase.viewport });
    await context.addInitScript((locale) => {
      window.localStorage.setItem("drone-dream:locale", locale);
    }, testCase.locale);
    await installFixtureRoutes(context, apiRequests);
    const page = await context.newPage();
    page.on("console", (message) => {
      if (message.type() === "error") consoleErrors.push(message.text());
    });
    page.on("pageerror", (error) => pageErrors.push(error.message));
    const entry = { case: testCase };
    try {
      await page.goto(`${origin}/console/jobs/${job.id}?docsPreview=1`, {
        waitUntil: "networkidle",
      });
      const diagnostic = testCase.locale === "en" ? "Diagnostic parameters" : "诊断参数";
      const noWinner = testCase.locale === "en" ? "No validated winner" : "无已验证赢家";
      await page.getByText(diagnostic, { exact: true }).waitFor();
      await page.getByText(noWinner, { exact: true }).waitFor();
      assert.equal(await page.getByText("baseline recommended", { exact: true }).count(), 0);
      assert.equal(await page.getByText(
        testCase.locale === "en" ? "Baseline winner" : "基线胜出",
        { exact: true },
      ).count(), 0);
      await page.getByText(diagnostic, { exact: true }).scrollIntoViewIfNeeded();
      const detailGeometry = await geometry(page);
      assert.equal(detailGeometry.documentScrollWidth, detailGeometry.documentWidth);
      entry.detail = {
        ...detailGeometry,
        diagnostic,
        noWinner,
        image: await screenshot(page, testCase, "job-detail-no-winner"),
      };

      await page.goto(
        `${origin}/console/compare?job_ids=job_validated_winner,job_diagnostic_only&docsPreview=1`,
        { waitUntil: "networkidle" },
      );
      const accepted = testCase.locale === "en" ? "Accepted winner" : "已验收赢家";
      const pending = testCase.locale === "en" ? "Not finalized" : "尚未定稿";
      await page.getByText(accepted, { exact: true }).waitFor();
      await page.getByText(pending, { exact: true }).waitFor();
      const compareGeometry = await geometry(page, ".data-table-wrapper");
      assert.equal(compareGeometry.documentScrollWidth, compareGeometry.documentWidth);
      if (testCase.viewport.width <= 520) {
        assert(compareGeometry.table.scrollWidth > compareGeometry.table.clientWidth);
        assert(["auto", "scroll"].includes(compareGeometry.table.overflowX));
      }
      const diagnosticRow = page.locator("tr", { hasText: "job_diagnostic_only" });
      assert.equal(await diagnosticRow.locator("td").filter({ hasText: "0.9" }).count(), 0);
      entry.compare = {
        ...compareGeometry,
        accepted,
        pending,
        image: await screenshot(page, testCase, "job-compare"),
      };

      const unsafeRequests = apiRequests.filter(({ method, path: requestPath }) =>
        method !== "GET" && !(method === "POST" && requestPath.endsWith("/jobs/compare"))
      );
      assert.deepEqual(unsafeRequests, []);
      assert.deepEqual(consoleErrors, []);
      assert.deepEqual(pageErrors, []);
      entry.apiRequests = apiRequests;
      entry.consoleErrors = consoleErrors;
      entry.pageErrors = pageErrors;
      entry.passed = true;
    } catch (error) {
      entry.passed = false;
      entry.error = error instanceof Error ? error.stack ?? error.message : String(error);
      failure ??= error;
    }
    results.push(entry);
    await context.close();
  }
} finally {
  await browser.close();
  await server.close();
}

const receipt = {
  schemaVersion: 1,
  label,
  sourceCommit: git("rev-parse", "HEAD"),
  sourceDirty: git("status", "--short") !== "",
  verifierSha256: await sha256File(
    path.join(frontendRoot, "scripts", "verify-result-honesty-layout.mjs"),
  ),
  browser: { name: "Microsoft Edge" },
  passed: results.every((entry) => entry.passed),
  cases: results,
};
const receiptPath = path.join(outputRoot, "result-honesty-layout-receipt.json");
await writeFile(receiptPath, `${JSON.stringify(receipt, null, 2)}\n`, "utf8");
for (const entry of results) {
  process.stdout.write(`${entry.case.id}: ${entry.passed ? "PASS" : "FAIL"}\n`);
}
process.stdout.write(`Receipt: ${receiptPath}\n`);
if (failure) throw failure;
