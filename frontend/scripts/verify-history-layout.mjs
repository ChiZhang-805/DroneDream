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

function parseArguments(argv) {
  const valueOptions = new Set(["--label", "--output", "--port"]);
  const parsed = new Map();
  for (let index = 0; index < argv.length; index += 1) {
    const argument = argv[index];
    const separator = argument.indexOf("=");
    const key = separator >= 0 ? argument.slice(0, separator) : argument;
    if (!valueOptions.has(key)) throw new Error(`Unknown history layout option: ${argument}`);
    if (parsed.has(key)) throw new Error(`Duplicate history layout option: ${key}`);
    const inlineValue = separator >= 0 ? argument.slice(separator + 1) : null;
    const value = inlineValue ?? argv[index + 1];
    if (!value || value.startsWith("--")) {
      throw new Error(`History layout option requires a value: ${key}`);
    }
    parsed.set(key, value);
    if (inlineValue === null) index += 1;
  }
  return parsed;
}

const args = parseArguments(process.argv.slice(2));
const label = String(args.get("--label") || "after");
const outputRoot = path.resolve(
  repoRoot,
  String(
    args.get("--output")
      || path.join("artifacts", "test-runs", "history-jobs-layout", label),
  ),
);
const host = "127.0.0.1";
const port = Number(args.get("--port") || 5189);
const origin = `http://${host}:${port}`;

process.env.VITE_API_BASE_URL = origin;
process.env.VITE_PUBLIC_DEMO_CONSOLE = "false";

const cases = [
  { id: "compact-en-populated", locale: "en", viewport: { width: 1440, height: 900 }, populated: true },
  { id: "compact-zh-empty", locale: "zh-CN", viewport: { width: 1440, height: 900 }, populated: false },
  { id: "wide-zh-populated", locale: "zh-CN", viewport: { width: 2048, height: 1080 }, populated: true },
  { id: "wide-en-empty", locale: "en", viewport: { width: 2048, height: 1080 }, populated: false },
];

const jobTemplates = [
  {
    id: "job_history_alpha_20260728",
    control_version: 4,
    display_name: "Aurora constrained MOBO validation",
    track_type: "circle",
    objective_profile: "robust",
    simulator_backend_requested: "real_cli",
    optimizer_strategy: "constrained_mobo",
    status: "COMPLETED",
    created_at: "2026-07-28T07:00:00Z",
    updated_at: "2026-07-28T07:12:00Z",
  },
  {
    id: "job_history_beta_20260728",
    control_version: 2,
    display_name: "Long-horizon recovery evaluation",
    track_type: "lemniscate",
    objective_profile: "smooth",
    simulator_backend_requested: "mock",
    optimizer_strategy: "optimizer_portfolio",
    status: "FAILED",
    created_at: "2026-07-28T07:20:00Z",
    updated_at: "2026-07-28T07:41:00Z",
  },
  {
    id: "job_history_gamma_20260728",
    control_version: 1,
    display_name: "Cross-scenario robustness sweep",
    track_type: "u_turn",
    objective_profile: "stable",
    simulator_backend_requested: "real_cli",
    optimizer_strategy: "turbo",
    status: "CANCELLED",
    created_at: "2026-07-28T08:00:00Z",
    updated_at: "2026-07-28T08:18:00Z",
  },
];

const jobs = Array.from({ length: 24 }, (_, index) => {
  const template = jobTemplates[index % jobTemplates.length];
  return {
    ...template,
    id: `${template.id}_${String(index + 1).padStart(2, "0")}`,
    display_name: `${template.display_name} ${String(index + 1).padStart(2, "0")}`,
    created_at: `2026-07-28T${String(7 + Math.floor(index / 4)).padStart(2, "0")}:${String((index % 4) * 12).padStart(2, "0")}:00Z`,
  };
});

function git(...gitArgs) {
  return execFileSync("git", gitArgs, { cwd: repoRoot, encoding: "utf8" }).trim();
}

async function sha256File(filePath) {
  return createHash("sha256").update(await readFile(filePath)).digest("hex");
}

async function measure(page) {
  return page.evaluate(() => {
    const box = (selector) => {
      const element = document.querySelector(selector);
      if (!(element instanceof HTMLElement)) return null;
      const bounds = element.getBoundingClientRect();
      const style = getComputedStyle(element);
      return {
        clientWidth: element.clientWidth,
        scrollWidth: element.scrollWidth,
        clientHeight: element.clientHeight,
        scrollHeight: element.scrollHeight,
        top: Number(bounds.top.toFixed(2)),
        bottom: Number(bounds.bottom.toFixed(2)),
        left: Number(bounds.left.toFixed(2)),
        right: Number(bounds.right.toFixed(2)),
        width: Number(bounds.width.toFixed(2)),
        height: Number(bounds.height.toFixed(2)),
        overflowX: style.overflowX,
        overflowY: style.overflowY,
      };
    };
    const headers = Array.from(
      document.querySelectorAll(".history-results thead th"),
      (header) => ({
        text: header.textContent?.trim() ?? "",
        clientWidth: header.clientWidth,
        scrollWidth: header.scrollWidth,
        whiteSpace: getComputedStyle(header).whiteSpace,
      }),
    );
    const rows = Array.from(document.querySelectorAll(".history-results tbody tr"));
    const resultCard = box(".history-body > .section-card:last-child");
    const historyBody = box(".history-body");
    const historyResults = box(".history-results");
    const columnWidths = Array.from(
      document.querySelectorAll(".history-results thead th"),
      (header) => Number(header.getBoundingClientRect().width.toFixed(2)),
    );
    return {
      language: document.documentElement.lang,
      document: {
        clientWidth: document.documentElement.clientWidth,
        scrollWidth: document.documentElement.scrollWidth,
      },
      appMain: box(".app-main"),
      historyPage: box(".history-page"),
      historyBody,
      resultCard,
      resultCardBody: box(".history-body > .section-card:last-child > .section-card-body"),
      historyResults,
      historyTable: box(".history-results > table"),
      headers,
      columnWidths,
      rowCount: rows.length,
      hasEmptyState: Boolean(document.querySelector(".history-empty-row")),
      resultBottomGap:
        resultCard && historyBody
          ? Number((historyBody.bottom - resultCard.bottom).toFixed(2))
          : null,
      tableHeaderPosition: getComputedStyle(
        document.querySelector(".history-results thead"),
      ).position,
    };
  });
}

function containmentViolations(metrics) {
  const violations = [];
  if (metrics.document.scrollWidth > metrics.document.clientWidth + 1) {
    violations.push(`document ${metrics.document.clientWidth}/${metrics.document.scrollWidth}`);
  }
  for (const [name, entry] of [
    ["appMain", metrics.appMain],
    ["historyPage", metrics.historyPage],
    ["historyBody", metrics.historyBody],
    ["resultCard", metrics.resultCard],
    ["resultCardBody", metrics.resultCardBody],
    ["historyResults", metrics.historyResults],
  ]) {
    if (entry && entry.scrollWidth > entry.clientWidth + 1) {
      violations.push(`${name} ${entry.clientWidth}/${entry.scrollWidth}`);
    }
  }
  return violations;
}

async function verifyVerticalScroll(page) {
  return page.evaluate(() => {
    const results = document.querySelector(".history-results");
    const header = document.querySelector(".history-results thead");
    const rows = Array.from(document.querySelectorAll(".history-results tbody tr"));
    if (!(results instanceof HTMLElement) || !(header instanceof HTMLElement) || rows.length < 2) {
      return null;
    }
    const firstBefore = rows[0].getBoundingClientRect();
    const headerBefore = header.getBoundingClientRect();
    results.scrollTop = results.scrollHeight;
    const firstAfter = rows[0].getBoundingClientRect();
    const lastAfter = rows.at(-1).getBoundingClientRect();
    const headerAfter = header.getBoundingClientRect();
    const resultsAfter = results.getBoundingClientRect();
    return {
      maxScrollTop: results.scrollHeight - results.clientHeight,
      scrollTop: results.scrollTop,
      reachedEnd: Math.abs(results.scrollTop - (results.scrollHeight - results.clientHeight)) <= 1,
      firstRowMoved: firstAfter.top < firstBefore.top - 20,
      lastRowVisible: lastAfter.bottom <= resultsAfter.bottom + 1 && lastAfter.top >= resultsAfter.top - 1,
      stickyHeaderStable: Math.abs(headerAfter.top - headerBefore.top) <= 1,
    };
  });
}

await mkdir(path.dirname(outputRoot), { recursive: true });
try {
  await mkdir(outputRoot);
} catch (error) {
  if (error && typeof error === "object" && error.code === "EEXIST") {
    throw new Error(`History layout evidence output already exists: ${outputRoot}`, { cause: error });
  }
  throw error;
}

const server = await createServer({
  configFile: path.join(frontendRoot, "vite.config.ts"),
  root: frontendRoot,
  logLevel: "warn",
  server: { host, port, strictPort: true },
});
let browser;
const startedAt = new Date().toISOString();
const results = [];

try {
  await server.listen();
  browser = await chromium.launch({ channel: "msedge", headless: true });
  for (const testCase of cases) {
    const apiRequests = [];
    const consoleErrors = [];
    const pageErrors = [];
    const context = await browser.newContext({ viewport: testCase.viewport, colorScheme: "light" });
    await context.addInitScript((locale) => {
      window.localStorage.setItem("drone-dream:locale", locale);
    }, testCase.locale);
    const page = await context.newPage();
    page.on("console", (message) => {
      if (message.type() === "error") consoleErrors.push(message.text());
    });
    page.on("pageerror", (error) => pageErrors.push(error.message));
    await page.route("**/api/v1/jobs**", async (route) => {
      const request = route.request();
      apiRequests.push({ method: request.method(), url: request.url() });
      if (request.method() !== "GET") {
        await route.fulfill({ status: 405, contentType: "application/json", body: "{}" });
        return;
      }
      const items = testCase.populated ? jobs : [];
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          success: true,
          data: { items, page: 1, page_size: 200, total: items.length },
        }),
      });
    });

    await page.goto(`${origin}/console/history?docsPreview=1`, { waitUntil: "networkidle" });
    await page.locator(testCase.populated ? ".history-results tbody tr" : ".history-empty-row").first().waitFor();
    const initial = await measure(page);
    const violations = containmentViolations(initial);
    await page.screenshot({ path: path.join(outputRoot, `${testCase.id}-initial.png`) });
    const verticalScroll = testCase.populated ? await verifyVerticalScroll(page) : null;
    if (testCase.populated) {
      await page.screenshot({ path: path.join(outputRoot, `${testCase.id}-scrolled.png`) });
    }

    const headerTexts = initial.headers.map(({ text }) => text);
    const headersSingleLine = initial.headers.every(({ whiteSpace }) => whiteSpace === "nowrap");
    const headersNotClipped = initial.headers.every(
      ({ clientWidth, scrollWidth }) => scrollWidth <= clientWidth + 1,
    );
    const widthsArePurposeful = new Set(initial.columnWidths.map((width) => Math.round(width))).size >= 5
      && initial.columnWidths[1] > initial.columnWidths[6]
      && initial.columnWidths[1] > initial.columnWidths[7];
    const internalVerticalScroll = testCase.populated
      ? initial.historyResults.scrollHeight > initial.historyResults.clientHeight + 1
        && ["auto", "scroll"].includes(initial.historyResults.overflowY)
        && verticalScroll?.reachedEnd
        && verticalScroll.firstRowMoved
        && verticalScroll.lastRowVisible
        && verticalScroll.stickyHeaderStable
      : initial.hasEmptyState
        && initial.historyResults.scrollHeight <= initial.historyResults.clientHeight + 1;
    const expectedLanguage = initial.language === testCase.locale;
    const passed = expectedLanguage
      && violations.length === 0
      && headerTexts.length === 8
      && !headerTexts.includes("Job ID")
      && !headerTexts.includes("Updated at")
      && !headerTexts.includes("任务 ID")
      && !headerTexts.includes("更新时间")
      && headersSingleLine
      && headersNotClipped
      && widthsArePurposeful
      && initial.resultBottomGap !== null
      && Math.abs(initial.resultBottomGap) <= 1
      && initial.tableHeaderPosition === "sticky"
      && internalVerticalScroll
      && apiRequests.every(({ method }) => method === "GET")
      && consoleErrors.length === 0
      && pageErrors.length === 0;

    results.push({
      ...testCase,
      passed,
      initial,
      containmentViolations: violations,
      verticalScroll,
      headersSingleLine,
      headersNotClipped,
      widthsArePurposeful,
      internalVerticalScroll,
      apiRequests,
      consoleErrors,
      pageErrors,
    });
    await context.close();
  }
} finally {
  await browser?.close();
  await server.close();
}

const finishedAt = new Date().toISOString();
const evidence = {
  schemaVersion: 2,
  label,
  expected: "full-height Jobs card, non-equal eight-column table, and contained vertical scrolling",
  sourceCommit: git("rev-parse", "HEAD"),
  sourceDirty: git("status", "--short") !== "",
  sourceChanges: git("status", "--short").split(/\r?\n/).filter(Boolean),
  stylesheetSha256: await sha256File(path.join(frontendRoot, "src", "styles.css")),
  verifierSha256: await sha256File(path.join(frontendRoot, "scripts", "verify-history-layout.mjs")),
  command: `npm run test:history-layout -- --label=${label}`,
  browser: { name: "Microsoft Edge", version: browser?.version() ?? null },
  startedAt,
  finishedAt,
  durationMs: Date.parse(finishedAt) - Date.parse(startedAt),
  passed: results.every((result) => result.passed),
  cases: results,
};
await writeFile(
  path.join(outputRoot, "measurements.json"),
  `${JSON.stringify(evidence, null, 2)}\n`,
  "utf8",
);

for (const result of results) {
  process.stdout.write(
    `${result.id}: ${result.passed ? "PASS" : "FAIL"} `
      + `results=${result.initial.historyResults.clientWidth}/${result.initial.historyResults.scrollWidth} `
      + `height=${result.initial.historyResults.clientHeight}/${result.initial.historyResults.scrollHeight} `
      + `columns=${result.initial.columnWidths.join(",")} `
      + `violations=${result.containmentViolations.join(",") || "none"}\n`,
  );
}
process.stdout.write(`Evidence: ${path.join(outputRoot, "measurements.json")}\n`);
if (!evidence.passed) process.exitCode = 1;
