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
    if (!valueOptions.has(key)) throw new Error(`Unknown dashboard layout option: ${argument}`);
    if (parsed.has(key)) throw new Error(`Duplicate dashboard layout option: ${key}`);
    const inlineValue = separator >= 0 ? argument.slice(separator + 1) : null;
    const value = inlineValue ?? argv[index + 1];
    if (!value || value.startsWith("--")) {
      throw new Error(`Dashboard layout option requires a value: ${key}`);
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
      || path.join("frontend", "node_modules", ".cache", "dashboard-layout", label),
  ),
);
const host = "127.0.0.1";
const port = Number(args.get("--port") || 5191);
const origin = `http://${host}:${port}`;

process.env.VITE_API_BASE_URL = origin;
process.env.VITE_PUBLIC_DEMO_CONSOLE = "false";

const cases = [
  { id: "universal-en-empty", edition: "universal", locale: "en", populated: false, viewport: { width: 1440, height: 900 } },
  { id: "sim-zh-populated", edition: "sim", locale: "zh-CN", populated: true, viewport: { width: 1440, height: 900 } },
  { id: "lab-en-empty", edition: "lab", locale: "en", populated: false, viewport: { width: 1920, height: 1080 } },
  { id: "field-zh-populated", edition: "field", locale: "zh-CN", populated: true, viewport: { width: 1920, height: 1080 } },
];

const statuses = ["PENDING", "RUNNING", "COMPLETED", "FAILED", "CANCELLED"];
const jobTemplates = [
  { track_type: "circle", objective_profile: "robust", status: "COMPLETED" },
  { track_type: "lemniscate", objective_profile: "smooth", status: "RUNNING" },
  { track_type: "u_turn", objective_profile: "stable", status: "FAILED" },
];
const jobs = Array.from({ length: 36 }, (_, index) => ({
  id: `dashboard_job_${String(index + 1).padStart(3, "0")}`,
  control_version: 4,
  display_name: `Viewport contract verification ${String(index + 1).padStart(2, "0")}`,
  simulator_backend_requested: "real_cli",
  optimizer_strategy: "constrained_mobo",
  created_at: `2026-08-14T${String(7 + Math.floor(index / 6)).padStart(2, "0")}:${String((index % 6) * 9).padStart(2, "0")}:00Z`,
  updated_at: "2026-08-14T12:00:00Z",
  ...jobTemplates[index % jobTemplates.length],
}));

async function sha256File(filePath) {
  return createHash("sha256").update(await readFile(filePath)).digest("hex");
}

function pagedResponse(items, total = items.length) {
  return JSON.stringify({ success: true, data: { items, page: 1, page_size: 50, total } });
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
        width: Number(bounds.width.toFixed(2)),
        height: Number(bounds.height.toFixed(2)),
        overflowX: style.overflowX,
        overflowY: style.overflowY,
      };
    };
    const dashboardBody = box(".dashboard-body");
    const recentCard = box(".dashboard-recent-jobs");
    const tableHeaders = Array.from(
      document.querySelectorAll(".dashboard-recent-jobs-content thead th"),
      (header) => getComputedStyle(header).position,
    );
    return {
      language: document.documentElement.lang,
      edition: document.documentElement.dataset.brandEdition,
      viewport: { width: window.innerWidth, height: window.innerHeight },
      document: {
        clientWidth: document.documentElement.clientWidth,
        scrollWidth: document.documentElement.scrollWidth,
        clientHeight: document.documentElement.clientHeight,
        scrollHeight: document.documentElement.scrollHeight,
      },
      appMain: box(".app-main"),
      dashboardPage: box(".dashboard-page"),
      dashboardBody,
      recentCard,
      recentCardBody: box(".dashboard-recent-jobs-content"),
      recentContent: box(".dashboard-recent-jobs-content"),
      recentTableWrapper: box(".dashboard-recent-jobs-content .data-table-wrapper"),
      emptyState: box(".dashboard-empty-jobs"),
      rowCount: document.querySelectorAll(".dashboard-recent-jobs-content tbody tr").length,
      bodyBottomGap: dashboardBody && recentCard
        ? Number((dashboardBody.bottom - recentCard.bottom).toFixed(2))
        : null,
      viewportBottomGap: recentCard
        ? Number((window.innerHeight - recentCard.bottom).toFixed(2))
        : null,
      tableHeaders,
    };
  });
}

function containmentViolations(metrics) {
  const violations = [];
  if (metrics.document.scrollWidth > metrics.document.clientWidth + 1) {
    violations.push(`document-x ${metrics.document.clientWidth}/${metrics.document.scrollWidth}`);
  }
  if (metrics.document.scrollHeight > metrics.document.clientHeight + 1) {
    violations.push(`document-y ${metrics.document.clientHeight}/${metrics.document.scrollHeight}`);
  }
  for (const [name, entry] of [
    ["appMain", metrics.appMain],
    ["dashboardPage", metrics.dashboardPage],
    ["dashboardBody", metrics.dashboardBody],
    ["recentCard", metrics.recentCard],
    ["recentCardBody", metrics.recentCardBody],
    ["recentContent", metrics.recentContent],
  ]) {
    if (entry && entry.scrollWidth > entry.clientWidth + 1) {
      violations.push(`${name}-x ${entry.clientWidth}/${entry.scrollWidth}`);
    }
  }
  return violations;
}

async function verifyInternalScroll(page) {
  return page.evaluate(() => {
    const wrapper = document.querySelector(".dashboard-recent-jobs-content .data-table-wrapper");
    const header = document.querySelector(".dashboard-recent-jobs-content thead");
    const rows = Array.from(document.querySelectorAll(".dashboard-recent-jobs-content tbody tr"));
    if (!(wrapper instanceof HTMLElement) || !(header instanceof HTMLElement) || rows.length < 2) return null;
    const firstBefore = rows[0].getBoundingClientRect();
    const headerBefore = header.getBoundingClientRect();
    wrapper.scrollTop = wrapper.scrollHeight;
    const firstAfter = rows[0].getBoundingClientRect();
    const lastAfter = rows.at(-1).getBoundingClientRect();
    const headerAfter = header.getBoundingClientRect();
    const wrapperAfter = wrapper.getBoundingClientRect();
    return {
      reachedEnd: Math.abs(wrapper.scrollTop - (wrapper.scrollHeight - wrapper.clientHeight)) <= 1,
      firstRowMoved: firstAfter.top < firstBefore.top - 20,
      lastRowVisible: lastAfter.bottom <= wrapperAfter.bottom + 1,
      stickyHeaderStable: Math.abs(headerAfter.top - headerBefore.top) <= 1,
    };
  });
}

await mkdir(path.dirname(outputRoot), { recursive: true });
try {
  await mkdir(outputRoot);
} catch (error) {
  if (error && typeof error === "object" && error.code === "EEXIST") {
    throw new Error(`Dashboard layout evidence output already exists: ${outputRoot}`, { cause: error });
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
const results = [];

try {
  await server.listen();
  browser = await chromium.launch({ channel: "msedge", headless: true });
  for (const testCase of cases) {
    const consoleErrors = [];
    const pageErrors = [];
    const context = await browser.newContext({ viewport: testCase.viewport, colorScheme: "light" });
    await context.addInitScript(({ edition, locale }) => {
      window.localStorage.setItem("dronedream:universal-workspace:v2", edition);
      window.localStorage.setItem("drone-dream:locale", locale);
    }, { edition: testCase.edition, locale: testCase.locale });
    const page = await context.newPage();
    page.on("console", (message) => {
      if (message.type() === "error") consoleErrors.push(message.text());
    });
    page.on("pageerror", (error) => pageErrors.push(error.message));
    await page.route("**/api/v1/jobs**", async (route) => {
      const requestUrl = new URL(route.request().url());
      if (route.request().method() !== "GET") {
        await route.fulfill({ status: 405, contentType: "application/json", body: "{}" });
        return;
      }
      const status = requestUrl.searchParams.get("status");
      if (status && statuses.includes(status)) {
        const statusItems = testCase.populated ? jobs.filter((job) => job.status === status).slice(0, 1) : [];
        const total = testCase.populated ? jobs.filter((job) => job.status === status).length : 0;
        await route.fulfill({ status: 200, contentType: "application/json", body: pagedResponse(statusItems, total) });
        return;
      }
      const items = testCase.populated ? jobs : [];
      await route.fulfill({ status: 200, contentType: "application/json", body: pagedResponse(items) });
    });

    await page.goto(`${origin}/console/dashboard?docsPreview=1`, { waitUntil: "networkidle" });
    await page.locator(".dashboard-recent-jobs").waitFor();
    await page.locator(testCase.populated ? ".dashboard-recent-jobs-content tbody tr" : ".dashboard-empty-jobs").first().waitFor();
    const initial = await measure(page);
    const violations = containmentViolations(initial);
    const internalScroll = testCase.populated ? await verifyInternalScroll(page) : null;
    await page.screenshot({ path: path.join(outputRoot, `${testCase.id}.png`) });

    const scrollContract = testCase.populated
      ? initial.recentTableWrapper
        && initial.recentTableWrapper.scrollHeight > initial.recentTableWrapper.clientHeight + 1
        && ["auto", "scroll"].includes(initial.recentTableWrapper.overflowY)
        && internalScroll?.reachedEnd
        && internalScroll.firstRowMoved
        && internalScroll.lastRowVisible
        && internalScroll.stickyHeaderStable
      : initial.emptyState
        && initial.recentCard
        && initial.recentCard.height <= 72
        && initial.emptyState.height <= initial.recentCard.height;
    const viewportContract = testCase.populated
      ? initial.bodyBottomGap !== null
        && Math.abs(initial.bodyBottomGap) <= 1
        && initial.viewportBottomGap !== null
        && initial.viewportBottomGap <= 64
      : true;
    const passed = initial.language === testCase.locale
      && initial.edition === testCase.edition
      && violations.length === 0
      && viewportContract
      && scrollContract
      && consoleErrors.length === 0
      && pageErrors.length === 0;

    results.push({ ...testCase, passed, initial, violations, internalScroll, scrollContract, consoleErrors, pageErrors });
    await context.close();
  }
} finally {
  await browser?.close();
  await server.close();
}

const evidence = {
  schemaVersion: 1,
  label,
  expected: "Populated recent jobs scrolls within the remaining viewport; an empty dashboard uses one compact status row",
  stylesheetSha256: await sha256File(path.join(frontendRoot, "src", "styles.css")),
  verifierSha256: await sha256File(path.join(frontendRoot, "scripts", "verify-dashboard-layout.mjs")),
  passed: results.every((result) => result.passed),
  cases: results,
};
await writeFile(path.join(outputRoot, "measurements.json"), `${JSON.stringify(evidence, null, 2)}\n`, "utf8");

for (const result of results) {
  process.stdout.write(
    `${result.id}: ${result.passed ? "PASS" : "FAIL"} `
      + `cardHeight=${result.initial.recentCard?.height ?? "missing"} `
      + `bottom=${result.initial.viewportBottomGap ?? "missing"} `
      + `rows=${result.initial.rowCount} violations=${result.violations.join(",") || "none"}\n`,
  );
}
process.stdout.write(`Evidence: ${path.join(outputRoot, "measurements.json")}\n`);
if (!evidence.passed) process.exitCode = 1;
